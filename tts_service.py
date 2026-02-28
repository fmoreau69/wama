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

for d in (COQUI_DIR, BARK_DIR, HIGGS_DIR):
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

_current_engine = None       # "coqui", "bark", or "higgs"
_current_model_name = None   # e.g. "xtts_v2", "bark", "higgs_audio"
_tts_instance = None         # Coqui TTS instance
_bark_funcs = None           # {"generate_audio": ..., "SAMPLE_RATE": ...}
_higgs_engine = None         # HiggsAudioServeEngine instance

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

    audio_array = np.array(audio_array)
    if audio_array.dtype != np.int16:
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

    # Estimate max tokens needed: ~300 tokens/sec is typical for Higgs codec
    # Add generous headroom; worker timeout is 300s so cap at ~250s of audio
    estimated_tokens = max(8192, len(text) * 20)  # rough upper bound
    max_tokens = min(estimated_tokens, 75000)

    # Diagnostic: log cache state before reset
    try:
        for bucket_len, kv_cache in _higgs_engine.kv_caches.items():
            seq_len = kv_cache.get_seq_length()
            logger.info(f"[Higgs diag] KV cache[{bucket_len}] seq_length BEFORE reset = {seq_len}")
    except Exception as _e:
        logger.warning(f"[Higgs diag] Could not read cache lengths: {_e}")

    logger.info(f"[Higgs diag] max_tokens={max_tokens}, text_chars={len(text)}")
    cuda_graph_keys = list(_higgs_engine.model.decode_graph_runners.keys()) if hasattr(_higgs_engine.model, "decode_graph_runners") else []
    logger.info(f"[Higgs diag] CUDA graph runner keys: {cuda_graph_keys}")

    output = _higgs_engine.generate(
        chat_ml_sample=chat_ml,
        max_new_tokens=max_tokens,
        temperature=0.3,
        top_p=0.95,
        force_audio_gen=True,
    )

    if output.audio is None or len(output.audio) == 0:
        raise ValueError("Higgs Audio returned empty audio")

    # Use actual sampling rate from engine (never hardcode 24000)
    actual_sr = int(output.sampling_rate) if hasattr(output, 'sampling_rate') and output.sampling_rate else 24000
    logger.info(f"Higgs audio: {len(output.audio)} samples @ {actual_sr} Hz = {len(output.audio)/actual_sr:.1f}s")

    # Diagnostic: log usage stats and expected vs actual KV fill
    completion_tokens = 0
    if output.usage:
        logger.info(f"[Higgs diag] Usage: {output.usage}")
        completion_tokens = output.usage.get("completion_tokens", 0) if isinstance(output.usage, dict) else getattr(output.usage, "completion_tokens", 0)

    # Diagnostic: log cache state after generation
    try:
        for bucket_len, kv_cache in _higgs_engine.kv_caches.items():
            seq_len = kv_cache.get_seq_length()
            logger.info(f"[Higgs diag] KV cache[{bucket_len}] seq_length AFTER = {seq_len}")
    except Exception as _e:
        logger.warning(f"[Higgs diag] Could not read cache lengths after generation: {_e}")

    # Deep diagnostic: inspect actual key tensor values.
    # Expected seq_len after generation ≈ prefill_len + completion_tokens.
    # If seq_len stays at prefill_len, decode writes are broken (CUDA graph bug).
    try:
        kv_1024 = _higgs_engine.kv_caches.get(1024)
        kv_4096 = _higgs_engine.kv_caches.get(4096)
        # Use whichever bucket was actually used (larger of the two non-zero ones)
        active_kv = None
        for kv in (kv_4096, kv_1024):
            if kv is not None and kv.layers[0].is_initialized:
                active_kv = kv
                break
        if active_kv is not None:
            keys = active_kv.layers[0].keys  # (batch, heads, max_len, head_dim)
            seq_l0 = active_kv.get_seq_length(0)
            seq_l1 = active_kv.get_seq_length(1)
            expected = seq_l0 + completion_tokens  # rough: assumes seq_l0 = prefill_len
            logger.info(
                f"[Higgs diag] layer0 seq_len={seq_l0}, layer1 seq_len={seq_l1}, "
                f"completion_tokens={completion_tokens}, expected_final≈{expected}"
            )
            # Sample positions: prefill boundary, +1, +10, +100, end of bucket
            max_pos = keys.shape[2]
            sample_positions = [
                max(0, seq_l0 - 2), seq_l0, seq_l0 + 1,
                min(seq_l0 + 10, max_pos - 1),
                min(seq_l0 + 100, max_pos - 1),
                max_pos - 1,
            ]
            # Deduplicate preserving order
            seen = set()
            sample_positions = [p for p in sample_positions if not (p in seen or seen.add(p))]
            for pos in sample_positions:
                v = keys[0, 0, pos, :4].cpu().float().tolist()
                nz = any(x != 0.0 for x in v)
                logger.info(f"[Higgs diag] keys[0,0,{pos},:4] = {[round(x,4) for x in v]}  {'NON-ZERO' if nz else 'ZERO'}")
    except Exception as _e:
        logger.warning(f"[Higgs diag] Deep key-value inspection failed: {_e}")

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
