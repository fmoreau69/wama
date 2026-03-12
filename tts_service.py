"""
WAMA TTS Microservice - FastAPI
Standalone TTS service that keeps models preloaded in GPU memory.
Django and Celery workers call this service via HTTP.

Usage:
    python -m uvicorn tts_service:app --host 0.0.0.0 --port 8001 --workers 1
"""

import os
import sys
import logging
import tempfile
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(level=logging.INFO, format="%(asctime)s [TTS] %(levelname)s %(message)s")
logger = logging.getLogger("tts_service")

# ---------------------------------------------------------------------------
# Project paths (reuse Django/model_config paths without importing Django)
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).parent
AI_MODELS_DIR = PROJECT_DIR / "AI-models"

COQUI_DIR = AI_MODELS_DIR / "models" / "speech" / "coqui"
BARK_DIR = AI_MODELS_DIR / "models" / "speech" / "bark"
HIGGS_DIR = AI_MODELS_DIR / "models" / "speech" / "higgs"
KOKORO_DIR = AI_MODELS_DIR / "models" / "speech" / "kokoro"

for d in (COQUI_DIR, BARK_DIR, HIGGS_DIR, KOKORO_DIR):
    d.mkdir(parents=True, exist_ok=True)

# Environment variables
os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ.setdefault("TTS_HOME", str(COQUI_DIR))
os.environ.setdefault("SUNO_USE_SMALL_MODELS", "False")
os.environ.setdefault("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0")

# Default voices directory
DEFAULT_VOICES_DIR = PROJECT_DIR / "media" / "synthesizer" / "default_voices"
DEFAULT_VOICES_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Imports légers – seul torch est chargé ici au niveau module
# Les patches torchaudio et transformers sont appliqués en lazy dans _load_coqui/_load_higgs
# ---------------------------------------------------------------------------
import torch
import numpy as np

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Patch torch.load for PyTorch 2.6+ (weights_only=True default breaks Bark)
_original_torch_load = torch.load
def _patched_torch_load(*args, **kwargs):
    if "weights_only" not in kwargs:
        kwargs["weights_only"] = False
    return _original_torch_load(*args, **kwargs)
torch.load = _patched_torch_load

# Note: torchaudio and transformers patches are applied lazily inside
# _load_coqui() and _load_higgs() to avoid slowing down service startup.


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="WAMA TTS Service", version="1.0")

# ---------------------------------------------------------------------------
# Global model state
# ---------------------------------------------------------------------------
import threading

_current_engine = None       # "coqui", "bark", "higgs", or "kokoro"
_current_model_name = None   # e.g. "xtts_v2", "bark", "higgs_audio", "kokoro"
_tts_instance = None         # Coqui TTS instance
_bark_funcs = None           # {"generate_audio": ..., "SAMPLE_RATE": ...}
_higgs_engine = None         # HiggsAudioServeEngine instance
_kokoro_pipelines = {}       # lang_code → KPipeline
_kokoro_lock = threading.Lock()

# Serialise concurrent Higgs generation requests.
# _higgs_engine.generate() mutates self.current_past_key_values_bucket on the shared
# model instance. Two simultaneous calls (e.g. one still running after HTTP timeout
# + the next request arriving) corrupt this shared state → "target cache size 1024
# is smaller than source cache size 4096". The lock ensures sequential execution.
_higgs_generation_lock = threading.Lock()

# Service readiness flag: False while models are loading at startup
_service_ready = False
_service_ready_lock = threading.Lock()

# Constantes TTS partagées (modèles, langues, presets, mappings)
import sys as _sys
_sys.path.insert(0, str(PROJECT_DIR))
from wama.common.tts.constants import (
    COQUI_MODEL_MAPPING,
    BARK_LANG_DEFAULTS,
    HIGGS_LANGUAGE_NAMES as _HIGGS_LANGUAGE_NAMES,
    PRESET_DOWNLOAD_MAPPING,
    KOKORO_LANG_MAP as _KOKORO_LANG_MAP,
    KOKORO_VOICE_MAP as _KOKORO_VOICE_MAP,
)


def _unload_current():
    """Unload whatever model is currently loaded and free GPU memory."""
    global _current_engine, _current_model_name, _tts_instance, _bark_funcs, _higgs_engine

    if _current_engine == "coqui" and _tts_instance is not None:
        logger.info(f"Unloading Coqui model: {_current_model_name}")
        del _tts_instance
        _tts_instance = None
    elif _current_engine == "bark":
        logger.info("Unloading Bark")
        _bark_funcs = None
    elif _current_engine == "higgs" and _higgs_engine is not None:
        logger.info("Unloading Higgs Audio engine")
        del _higgs_engine
        _higgs_engine = None
    elif _current_engine == "kokoro":
        logger.info("Unloading Kokoro")
        _kokoro_pipelines.clear()

    _current_engine = None
    _current_model_name = None

    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        logger.info("GPU cache cleared")


def _load_coqui(model_name: str):
    """Load a Coqui TTS model."""
    global _current_engine, _current_model_name, _tts_instance

    # Patch torchaudio.load → soundfile (torchcodec may not be available)
    try:
        import torchaudio
        import soundfile as sf

        def _soundfile_load(uri, frame_offset=0, num_frames=-1, normalize=True,
                            channels_first=True, format=None, buffer_size=4096,
                            backend=None):
            data, sample_rate = sf.read(
                str(uri), dtype="float32",
                start=frame_offset,
                stop=frame_offset + num_frames if num_frames > 0 else None,
                always_2d=True,
            )
            audio_tensor = torch.from_numpy(data)
            if channels_first:
                audio_tensor = audio_tensor.t()
            return audio_tensor, sample_rate

        torchaudio.load = _soundfile_load
        logger.info("Patched torchaudio.load → soundfile backend")
    except Exception as e:
        logger.warning(f"Could not patch torchaudio: {e}")

    from TTS.api import TTS

    full_id = COQUI_MODEL_MAPPING.get(model_name, model_name)
    logger.info(f"Loading Coqui model: {full_id} on {DEVICE}")
    _tts_instance = TTS(full_id).to(DEVICE)
    _current_engine = "coqui"
    _current_model_name = model_name
    logger.info(f"Coqui model {model_name} loaded")


def _load_bark():
    """Load Bark models."""
    global _current_engine, _current_model_name, _bark_funcs

    original_xdg = os.environ.get("XDG_CACHE_HOME")
    os.environ["XDG_CACHE_HOME"] = str(BARK_DIR)
    logger.info(f"Setting XDG_CACHE_HOME={BARK_DIR} for Bark")

    from bark import SAMPLE_RATE, generate_audio, preload_models

    logger.info("Preloading Bark models...")
    preload_models()

    _bark_funcs = {
        "generate_audio": generate_audio,
        "SAMPLE_RATE": SAMPLE_RATE,
    }
    _current_engine = "bark"
    _current_model_name = "bark"
    logger.info("Bark loaded and preloaded")


def _load_higgs():
    """Load Higgs Audio v2 engine."""
    global _current_engine, _current_model_name, _higgs_engine

    # Redirect HF hub cache to our managed directory (must be before any HF import)
    HIGGS_DIR.mkdir(parents=True, exist_ok=True)
    os.environ['HF_HUB_CACHE'] = str(HIGGS_DIR)
    os.environ['HUGGINGFACE_HUB_CACHE'] = str(HIGGS_DIR)

    # Patches required by boson_multimodal against transformers 4.57+
    # Applied here (lazily) to avoid ~60-90s import overhead at service startup.
    try:
        from transformers.models.llama import modeling_llama as _llama_module
        if not hasattr(_llama_module, "LLAMA_ATTENTION_CLASSES"):
            _llama_module.LLAMA_ATTENTION_CLASSES = {
                "eager": _llama_module.LlamaAttention,
                "sdpa": _llama_module.LlamaAttention,
                "flash_attention_2": _llama_module.LlamaAttention,
            }
            logger.info("Patched LLAMA_ATTENTION_CLASSES for boson_multimodal")
    except Exception as e:
        logger.warning(f"Could not patch LLAMA_ATTENTION_CLASSES: {e}")

    try:
        from transformers.modeling_utils import ALL_ATTENTION_FUNCTIONS
        _patched_keys = []
        for _key in (None, "eager"):
            if _key not in ALL_ATTENTION_FUNCTIONS:
                ALL_ATTENTION_FUNCTIONS[_key] = ALL_ATTENTION_FUNCTIONS["sdpa"]
                _patched_keys.append(repr(_key))
        if _patched_keys:
            logger.info(f"Patched ALL_ATTENTION_FUNCTIONS: added {', '.join(_patched_keys)} → sdpa")
    except Exception as e:
        logger.warning(f"Could not patch ALL_ATTENTION_FUNCTIONS: {e}")

    try:
        from transformers import GenerationConfig as _GC
        if not hasattr(_GC, "generation_kwargs"):
            _orig_gc_init = _GC.__init__
            def _patched_gc_init(self, *args, **kwargs):
                _orig_gc_init(self, *args, **kwargs)
                if not isinstance(getattr(self, "generation_kwargs", None), dict):
                    self.generation_kwargs = {}
            _GC.__init__ = _patched_gc_init
            _GC.generation_kwargs = {}
            logger.info("Patched GenerationConfig.generation_kwargs for boson_multimodal")
    except Exception as e:
        logger.warning(f"Could not patch GenerationConfig.generation_kwargs: {e}")

    from boson_multimodal.serve.serve_engine import HiggsAudioServeEngine

    model_path = "bosonai/higgs-audio-v2-generation-3B-base"
    tokenizer_path = "bosonai/higgs-audio-v2-tokenizer"

    logger.info(f"Loading Higgs Audio engine: {model_path}")
    _higgs_engine = HiggsAudioServeEngine(
        model_name_or_path=model_path,
        audio_tokenizer_name_or_path=tokenizer_path,
        device="cuda",
    )
    _current_engine = "higgs"
    _current_model_name = "higgs_audio"
    logger.info("Higgs Audio engine loaded")

    # Optional: disable CUDA graphs entirely for debugging.
    # Set env var HIGGS_DISABLE_CUDA_GRAPHS=1 before starting the service.
    if os.environ.get("HIGGS_DISABLE_CUDA_GRAPHS"):
        _higgs_engine.model.decode_graph_runners.clear()
        logger.warning("[Higgs debug] CUDA graphs DISABLED via HIGGS_DISABLE_CUDA_GRAPHS")


def _get_kokoro_pipeline(lang_code: str):
    """Lazy-load a Kokoro pipeline for the given lang_code (thread-safe)."""
    if lang_code not in _kokoro_pipelines:
        with _kokoro_lock:
            if lang_code not in _kokoro_pipelines:
                # Must be set BEFORE importing kokoro/huggingface_hub
                os.environ['HF_HUB_CACHE'] = str(KOKORO_DIR)
                os.environ['HUGGINGFACE_HUB_CACHE'] = str(KOKORO_DIR)
                from kokoro import KPipeline
                _kokoro_pipelines[lang_code] = KPipeline(
                    lang_code=lang_code, repo_id='hexgrad/Kokoro-82M')
    return _kokoro_pipelines[lang_code]


def _load_kokoro():
    """Load Kokoro (preload French pipeline)."""
    global _current_engine, _current_model_name
    _get_kokoro_pipeline('f')
    _current_engine = "kokoro"
    _current_model_name = "kokoro"
    logger.info("Kokoro loaded (French pipeline ready)")


def _generate_kokoro(text: str, language: str = "fr",
                     voice_preset: str = "default") -> str:
    """Generate audio with Kokoro. Returns path to temp WAV file."""
    import wave

    lang_code = _KOKORO_LANG_MAP.get(language, 'a')
    is_male = voice_preset in ('male_1', 'male_2')
    voice = (_KOKORO_VOICE_MAP.get((lang_code, is_male))
             or _KOKORO_VOICE_MAP.get((lang_code, False), 'af_heart'))

    pipeline = _get_kokoro_pipeline(lang_code)

    samples = []
    for _, _, audio in pipeline(text, voice=voice, speed=1.0):
        if audio is not None:
            arr = audio.numpy() if hasattr(audio, 'numpy') else np.array(audio)
            samples.append(arr)

    if not samples:
        raise RuntimeError("Kokoro: aucun audio généré")

    audio_np = np.concatenate(samples).astype(np.float32)
    peak = np.abs(audio_np).max()
    if peak > 1e-6:
        audio_np /= peak
    audio_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(PROJECT_DIR / "logs"))
    tmp.close()
    with wave.open(tmp.name, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(24000)
        wf.writeframes(audio_int16.tobytes())

    return tmp.name


def _switch_model(model_name: str):
    """Switch to the requested model, unloading the current one first."""
    global _current_model_name

    if _current_model_name == model_name:
        logger.info(f"Model {model_name} already loaded, skipping")
        return

    _unload_current()

    if model_name in COQUI_MODEL_MAPPING:
        _load_coqui(model_name)
    elif model_name == "bark":
        _load_bark()
    elif model_name == "higgs_audio":
        _load_higgs()
    elif model_name == "kokoro":
        _load_kokoro()
    else:
        # Try as a Coqui model anyway
        _load_coqui(model_name)


# ---------------------------------------------------------------------------
# Voice preset helper
# ---------------------------------------------------------------------------
def _get_speaker_wav(voice_preset: str) -> Optional[str]:
    """Resolve a voice preset name to a WAV file path."""
    import urllib.request

    # Check TTS package samples first
    try:
        import pkg_resources
        tts_path = pkg_resources.resource_filename("TTS", "")
        samples_dir = os.path.join(tts_path, "utils", "samples")
        if os.path.exists(samples_dir):
            for f in os.listdir(samples_dir):
                if f.endswith(".wav"):
                    return os.path.join(samples_dir, f)
    except Exception:
        pass

    # Preset → file mapping (depuis wama.common.tts.constants)
    preset_mapping = PRESET_DOWNLOAD_MAPPING

    # Download missing presets
    for name, (fname, url) in preset_mapping.items():
        fpath = DEFAULT_VOICES_DIR / fname
        if not fpath.exists():
            try:
                logger.info(f"Downloading voice preset {name} from {url}")
                urllib.request.urlretrieve(url, str(fpath))
            except Exception as e:
                logger.warning(f"Could not download preset {name}: {e}")

    # Return matching preset
    if voice_preset in preset_mapping:
        fpath = DEFAULT_VOICES_DIR / preset_mapping[voice_preset][0]
        if fpath.exists():
            return str(fpath)

    # Fallback to default
    default_path = DEFAULT_VOICES_DIR / "default.wav"
    if default_path.exists():
        return str(default_path)

    return None


def _get_bark_speaker(voice_preset: str, language: str) -> str:
    """Map a voice preset to a Bark speaker prompt."""
    if voice_preset.startswith("bark_v2_"):
        parts = voice_preset.replace("bark_v2_", "").split("_")
        if len(parts) == 2:
            return f"v2/{parts[0]}_speaker_{parts[1]}"

    # lang_defaults depuis wama.common.tts.constants
    return BARK_LANG_DEFAULTS.get(language, "v2/en_speaker_0")


# ---------------------------------------------------------------------------
# Generation functions
# ---------------------------------------------------------------------------
def _generate_coqui(text: str, model_name: str, language: str = "fr",
                    speaker_wav: str = None, voice_preset: str = "default") -> str:
    """Generate audio with Coqui TTS. Returns path to temp WAV file."""
    kwargs = {"text": text}

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(PROJECT_DIR / "logs"))
    kwargs["file_path"] = tmp.name
    tmp.close()

    if model_name == "xtts_v2":
        kwargs["language"] = language
        wav_path = speaker_wav or _get_speaker_wav(voice_preset)
        if wav_path and os.path.exists(wav_path):
            kwargs["speaker_wav"] = wav_path
        else:
            raise ValueError("XTTS v2 requires a speaker_wav reference audio file")

    _tts_instance.tts_to_file(**kwargs)
    return tmp.name


def _generate_bark(text: str, language: str = "fr",
                   voice_preset: str = "default") -> str:
    """Generate audio with Bark. Returns path to temp WAV file."""
    from scipy.io.wavfile import write as write_wav

    speaker = _get_bark_speaker(voice_preset, language)
    audio_array = _bark_funcs["generate_audio"](text, history_prompt=speaker)
    sample_rate = _bark_funcs["SAMPLE_RATE"]

    audio_array = np.array(audio_array, dtype=np.float32)
    # Normalize to [-1, 1] before int16 conversion — Bark output can exceed ±1.0
    # which causes clipping/saturation without normalization.
    peak = np.abs(audio_array).max()
    if peak > 1e-6:
        audio_array = audio_array / peak
    audio_array = (audio_array * 32767).astype(np.int16)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(PROJECT_DIR / "logs"))
    write_wav(tmp.name, sample_rate, audio_array)
    tmp.close()
    return tmp.name


# _HIGGS_LANGUAGE_NAMES est importé depuis wama.common.tts.constants


def _generate_higgs(text: str, language: str = "fr",
                    voice_preset: str = "default",
                    speaker_wav: str = None,
                    multi_speaker: bool = False,
                    scene_description: str = "",
                    options: dict = None) -> str:
    """Generate audio with Higgs Audio v2. Returns path to temp WAV file."""
    from boson_multimodal.data_types import ChatMLSample, Message, TextContent, AudioContent
    from scipy.io.wavfile import write as write_wav

    content_parts = []
    _tmp_ref_path = None  # track trimmed temp file for cleanup

    # System message with explicit language instruction
    lang_name = _HIGGS_LANGUAGE_NAMES.get(language, language.capitalize())
    system_message = Message(
        role="system",
        content=TextContent(text=f"Generate high-quality {lang_name} speech audio of the provided text.")
    )

    # Voice cloning: resolve reference audio path (direct path or preset fallback)
    ref_wav = speaker_wav or _get_speaker_wav(voice_preset)
    if ref_wav and os.path.exists(ref_wav):
        logger.info(f"[Higgs] Voice reference: {ref_wav}")
    else:
        logger.warning(f"[Higgs] No voice reference found (speaker_wav={speaker_wav!r}, preset={voice_preset!r}) — using default voice")
        ref_wav = None

    if ref_wav:
        # Trim reference audio to 6 seconds max.
        # Higgs Audio v2 was trained on 3-8s references; shorter is safer.
        # Longer references expand the KV cache context and can degrade generation quality.
        MAX_REF_DURATION_S = 6.0
        try:
            import librosa, soundfile as _sf
            _raw, _sr = librosa.load(ref_wav, sr=None)
            _dur = len(_raw) / _sr
            logger.info(f"[Higgs] Voice reference: {_dur:.1f}s @ {_sr}Hz")
            max_samples = int(MAX_REF_DURATION_S * _sr)
            if len(_raw) > max_samples:
                _raw = _raw[:max_samples]
                _tmp_ref = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(PROJECT_DIR / "logs"))
                _sf.write(_tmp_ref.name, _raw, _sr)
                _tmp_ref.close()
                _tmp_ref_path = _tmp_ref.name
                logger.info(f"[Higgs] Voice reference trimmed to {MAX_REF_DURATION_S}s → {_tmp_ref_path}")
                ref_wav = _tmp_ref_path
        except Exception as _e:
            logger.warning(f"[Higgs] Could not trim reference audio: {_e} — using original")

        # Pass file path directly — serve_engine.py loads via librosa.load(audio_url)
        content_parts.append(AudioContent(audio_url=ref_wav))

    # Multi-speaker scene description
    final_text = text
    if multi_speaker and scene_description:
        final_text = f"<|scene_desc_start|>{scene_description.strip()}<|scene_desc_end|>{text}"

    content_parts.append(TextContent(text=final_text))

    chat_ml = ChatMLSample(messages=[
        system_message,
        Message(role="user", content=content_parts)
    ])

    # Estimate max tokens: Higgs codec produces ~300 audio tokens/sec.
    # Natural speech rate ~2.5 words/sec → duration ≈ words/2.5 s.
    # Add 1.5× safety margin + 1500 overhead (system prompt, audio ref tokens).
    # Previous formula used max(8192, ...) which generated up to 8192 tokens
    # for a 23-word text → 8192 / 27 tok/s (RAM-swapped) = 303s → timeout.
    _words = len(text.split())
    _estimated_audio_tokens = int(_words / 2.5 * 300)
    max_tokens = min(max(int(_estimated_audio_tokens * 1.5) + 1500, 2000), 75000)
    logger.info(f"[Higgs] max_tokens={max_tokens} for {_words} words (~{_estimated_audio_tokens} audio tokens)")

    # Serialise: only one Higgs generation at a time.
    # Two concurrent HTTP threads sharing the model instance corrupt
    # self.current_past_key_values_bucket → "target cache size 1024 < source 4096".
    with _higgs_generation_lock:
        # Diagnostic: log cache state before generation
        try:
            for bucket_len, kv_cache in _higgs_engine.kv_caches.items():
                seq_len = kv_cache.get_seq_length()
                logger.info(f"[Higgs diag] KV cache[{bucket_len}] seq_length BEFORE = {seq_len}")
        except Exception as _e:
            logger.warning(f"[Higgs diag] Could not read cache lengths: {_e}")

        logger.info(f"[Higgs diag] max_tokens={max_tokens}, text_chars={len(text)}")

        output = _higgs_engine.generate(
            chat_ml_sample=chat_ml,
            max_new_tokens=max_tokens,
            temperature=0.7,   # serve_engine default; 0.3 was too aggressive (caused early EOS)
            top_p=0.95,
            force_audio_gen=True,
        )

    if output.audio is None or len(output.audio) == 0:
        raise ValueError("Higgs Audio returned empty audio")

    # Use actual sampling rate from engine (never hardcode 24000)
    actual_sr = int(output.sampling_rate) if hasattr(output, 'sampling_rate') and output.sampling_rate else 24000
    logger.info(f"Higgs audio: {len(output.audio)} samples @ {actual_sr} Hz = {len(output.audio)/actual_sr:.1f}s")

    if output.usage:
        logger.info(f"[Higgs diag] Usage: {output.usage}")

    # Diagnostic: log KV cache seq_length AFTER generation (expected: prefill + audio steps)
    try:
        for bucket_len, kv_cache in _higgs_engine.kv_caches.items():
            seq_len = kv_cache.get_seq_length()
            logger.info(f"[Higgs diag] KV cache[{bucket_len}] seq_length AFTER = {seq_len}")
    except Exception as _e:
        logger.debug(f"[Higgs diag] Could not read post-gen cache lengths: {_e}")

    # Diagnostic: inspect generated audio tokens to understand generation quality
    try:
        _tok = output.generated_audio_tokens  # shape (num_codebooks, num_steps)
        if _tok is not None and hasattr(_tok, 'shape'):
            _n_steps = _tok.shape[1] if len(_tok.shape) > 1 else len(_tok)
            _unique = len(set(_tok.flatten().tolist())) if hasattr(_tok, 'flatten') else '?'
            _min_t = int(_tok.min()) if hasattr(_tok, 'min') else '?'
            _max_t = int(_tok.max()) if hasattr(_tok, 'max') else '?'
            logger.info(f"[Higgs diag] Audio tokens: {_n_steps} steps, range [{_min_t},{_max_t}], {_unique} unique values")
    except Exception as _de:
        logger.debug(f"[Higgs diag] Could not inspect audio tokens: {_de}")

    combined = np.array(output.audio, dtype=np.float32)
    max_val = np.max(np.abs(combined))
    if max_val > 0:
        combined = combined / max_val

    # Resample to 48kHz if needed (Higgs native output is 24kHz)
    target_sr = 48000
    if actual_sr != target_sr:
        from scipy.signal import resample as scipy_resample
        num_samples = int(len(combined) * target_sr / actual_sr)
        combined = scipy_resample(combined, num_samples).astype(np.float32)
        logger.info(f"Resampled {actual_sr}Hz → {target_sr}Hz ({len(combined)} samples)")
        actual_sr = target_sr

    combined_int16 = (combined * 32767).astype(np.int16)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(PROJECT_DIR / "logs"))
    write_wav(tmp.name, actual_sr, combined_int16)
    tmp.close()

    # Cleanup trimmed reference temp file
    if _tmp_ref_path:
        try:
            os.remove(_tmp_ref_path)
        except OSError:
            pass

    return tmp.name


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------
class TTSRequest(BaseModel):
    text: str
    model: str = "xtts_v2"
    language: str = "fr"
    voice_preset: str = "default"
    speaker_wav: Optional[str] = None
    multi_speaker: bool = False
    scene_description: str = ""
    options: dict = {}


class LoadModelRequest(BaseModel):
    model: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@app.get("/health")
def health():
    gpu_mem = 0.0
    if torch.cuda.is_available():
        gpu_mem = torch.cuda.memory_allocated() / 1024**3

    with _service_ready_lock:
        ready = _service_ready

    return {
        "status": "ok" if ready else "loading",
        "device": DEVICE,
        "loaded_model": _current_model_name,
        "engine": _current_engine,
        "gpu_memory_gb": round(gpu_mem, 2),
    }


@app.post("/tts")
def tts_endpoint(req: TTSRequest):
    """Generate audio from text. Returns raw WAV bytes."""
    # Refuse requests while the service is still initialising so the caller
    # can detect the "not ready" state and retry rather than blocking a GPU
    # worker for the full model-loading time.
    with _service_ready_lock:
        ready = _service_ready
    if not ready:
        raise HTTPException(
            status_code=503,
            detail={"status": "loading", "message": "TTS service is still loading, retry shortly"},
        )

    try:
        # Switch model if needed
        _switch_model(req.model)

        # Generate audio
        if _current_engine == "coqui":
            wav_path = _generate_coqui(
                req.text, req.model, req.language,
                req.speaker_wav, req.voice_preset,
            )
        elif _current_engine == "bark":
            wav_path = _generate_bark(
                req.text, req.language, req.voice_preset,
            )
        elif _current_engine == "higgs":
            wav_path = _generate_higgs(
                req.text, req.language, req.voice_preset, req.speaker_wav,
                req.multi_speaker, req.scene_description,
                req.options,
            )
        elif _current_engine == "kokoro":
            wav_path = _generate_kokoro(req.text, req.language, req.voice_preset)
        else:
            raise ValueError(f"Unknown engine: {_current_engine}")

        # Read and return WAV bytes
        with open(wav_path, "rb") as f:
            wav_bytes = f.read()

        # Cleanup temp file
        try:
            os.remove(wav_path)
        except OSError:
            pass

        return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        logger.error(f"TTS generation error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/load-model")
def load_model_endpoint(req: LoadModelRequest):
    """Pre-load a model (for warming up)."""
    try:
        _switch_model(req.model)
        return {
            "status": "loaded",
            "model": _current_model_name,
            "engine": _current_engine,
        }
    except Exception as e:
        logger.error(f"Model load error: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ---------------------------------------------------------------------------
# Startup – preload XTTS v2
# ---------------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    global _service_ready

    logger.info("=== TTS Service starting ===")
    logger.info(f"Device: {DEVICE}")
    logger.info(f"Coqui DIR: {COQUI_DIR}")
    logger.info(f"Bark DIR: {BARK_DIR}")
    logger.info(f"Higgs DIR: {HIGGS_DIR}")

    # TTS_SKIP_PRELOAD=1 → mark service ready immediately without loading any model.
    # Useful in development to avoid the long XTTS v2 warm-up time; the model
    # will be loaded on the first actual /tts request instead.
    if os.environ.get("TTS_SKIP_PRELOAD", "0") == "1":
        with _service_ready_lock:
            _service_ready = True
        logger.info("TTS_SKIP_PRELOAD=1 — service marked ready immediately (model loads on first request)")
        return

    # Run model preloading in a background thread so uvicorn can immediately
    # serve requests (including /health).  The /health endpoint returns
    # {"status": "loading"} until this thread marks _service_ready = True.
    def _background_preload():
        global _service_ready
        try:
            _switch_model("xtts_v2")
            logger.info("XTTS v2 preloaded successfully — service ready")
        except Exception as e:
            logger.error(f"Failed to preload XTTS v2: {e}", exc_info=True)
            logger.warning("TTS Service starting without preloaded model — will load on first request")
        finally:
            with _service_ready_lock:
                _service_ready = True

    t = threading.Thread(target=_background_preload, daemon=True, name="tts-preload")
    t.start()
    logger.info("Startup: model preloading started in background thread")
