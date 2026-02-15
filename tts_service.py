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
# Patches – applied BEFORE any model import
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

# Patch torchaudio.load to use soundfile (torchcodec may not be available)
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

# Patch LLAMA_ATTENTION_CLASSES for boson_multimodal compatibility
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
_current_engine = None       # "coqui", "bark", or "higgs"
_current_model_name = None   # e.g. "xtts_v2", "bark", "higgs_audio"
_tts_instance = None         # Coqui TTS instance
_bark_funcs = None           # {"generate_audio": ..., "SAMPLE_RATE": ...}
_higgs_engine = None         # HiggsAudioServeEngine instance

# Coqui model name → HuggingFace model ID
COQUI_MODEL_MAPPING = {
    "xtts_v2": "tts_models/multilingual/multi-dataset/xtts_v2",
    "vits": "tts_models/en/vctk/vits",
    "tacotron2": "tts_models/en/ljspeech/tacotron2-DDC",
    "speedy_speech": "tts_models/en/ljspeech/speedy-speech",
}


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

    from boson_multimodal.serve.serve_engine import HiggsAudioServeEngine

    model_path = "bosonai/higgs-audio-v2-generation-3B-base"
    tokenizer_path = "bosonai/higgs-audio-v2-tokenizer"

    logger.info(f"Loading Higgs Audio engine: {model_path}")
    _higgs_engine = HiggsAudioServeEngine(
        model=model_path,
        tokenizer=tokenizer_path,
        device="cuda",
    )
    _current_engine = "higgs"
    _current_model_name = "higgs_audio"
    logger.info("Higgs Audio engine loaded")


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

    # Preset → file mapping
    _LJ_BASE = "https://github.com/idiap/coqui-ai-TTS/raw/main/tests/data/ljspeech/wavs"
    preset_mapping = {
        "default": ("default.wav", f"{_LJ_BASE}/LJ001-0001.wav"),
        "male_1": ("male_1.wav", f"{_LJ_BASE}/LJ001-0015.wav"),
        "male_2": ("male_2.wav", f"{_LJ_BASE}/LJ001-0020.wav"),
        "female_1": ("female_1.wav", f"{_LJ_BASE}/LJ001-0010.wav"),
        "female_2": ("female_2.wav", f"{_LJ_BASE}/LJ001-0025.wav"),
    }

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

    lang_defaults = {
        "en": "v2/en_speaker_0", "fr": "v2/fr_speaker_0",
        "es": "v2/es_speaker_0", "de": "v2/de_speaker_0",
        "it": "v2/it_speaker_0", "pt": "v2/pt_speaker_0",
        "pl": "v2/pl_speaker_0", "tr": "v2/tr_speaker_0",
        "ru": "v2/ru_speaker_0", "nl": "v2/nl_speaker_0",
        "cs": "v2/cs_speaker_0", "zh-cn": "v2/zh_speaker_0",
        "ja": "v2/ja_speaker_0", "ko": "v2/ko_speaker_0",
    }
    return lang_defaults.get(language, "v2/en_speaker_0")


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


def _generate_higgs(text: str, speaker_wav: str = None,
                    multi_speaker: bool = False,
                    scene_description: str = "",
                    options: dict = None) -> str:
    """Generate audio with Higgs Audio v2. Returns path to temp WAV file."""
    from boson_multimodal.data_types import ChatMLSample, Message, TextContent, AudioContent
    from scipy.io.wavfile import write as write_wav

    content_parts = []

    # Voice cloning: load reference audio
    if speaker_wav and os.path.exists(speaker_wav):
        import soundfile as sf_lib
        audio_data, sr = sf_lib.read(speaker_wav, dtype="float32")
        if sr != 24000:
            from scipy.signal import resample
            num_samples = int(len(audio_data) * 24000 / sr)
            audio_data = resample(audio_data, num_samples).astype(np.float32)
            sr = 24000
        content_parts.append(AudioContent(audio=audio_data, sampling_rate=sr))

    # Multi-speaker scene description
    final_text = text
    if multi_speaker and scene_description:
        final_text = f"<|scene_desc_start|>{scene_description.strip()}<|scene_desc_end|>{text}"

    content_parts.append(TextContent(text=final_text))

    chat_ml = ChatMLSample(messages=[
        Message(role="user", content=content_parts)
    ])

    output = _higgs_engine.generate(
        chat_ml_sample=chat_ml,
        max_new_tokens=2048,
        temperature=0.3,
        top_p=0.95,
    )

    if output.audio is None or len(output.audio) == 0:
        raise ValueError("Higgs Audio returned empty audio")

    combined = np.array(output.audio, dtype=np.float32)
    max_val = np.max(np.abs(combined))
    if max_val > 0:
        combined = combined / max_val
    combined_int16 = (combined * 32767).astype(np.int16)

    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(PROJECT_DIR / "logs"))
    write_wav(tmp.name, 24000, combined_int16)
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

    return {
        "status": "ok",
        "device": DEVICE,
        "loaded_model": _current_model_name,
        "engine": _current_engine,
        "gpu_memory_gb": round(gpu_mem, 2),
    }


@app.post("/tts")
def tts_endpoint(req: TTSRequest):
    """Generate audio from text. Returns raw WAV bytes."""
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
                req.text, req.speaker_wav,
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
    logger.info("=== TTS Service starting ===")
    logger.info(f"Device: {DEVICE}")
    logger.info(f"Coqui DIR: {COQUI_DIR}")
    logger.info(f"Bark DIR: {BARK_DIR}")
    logger.info(f"Higgs DIR: {HIGGS_DIR}")

    try:
        _switch_model("xtts_v2")
        logger.info("XTTS v2 preloaded successfully")
    except Exception as e:
        logger.error(f"Failed to preload XTTS v2: {e}", exc_info=True)
        logger.warning("TTS Service started without preloaded model - will load on first request")
