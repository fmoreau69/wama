"""
Transcriber Model Configuration

Centralized configuration for all models used by the Transcriber application.
Uses the centralized AI-models directory structure from settings.py.
"""

import os
import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# =============================================================================
# MODEL PATHS CONFIGURATION
# =============================================================================

# Get centralized paths from settings
MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

# Whisper models directory
WHISPER_DIR = MODEL_PATHS.get('speech', {}).get('whisper',
    settings.AI_MODELS_DIR / "models" / "speech" / "whisper")

# VibeVoice models directory
VIBEVOICE_DIR = MODEL_PATHS.get('speech', {}).get('vibevoice',
    settings.AI_MODELS_DIR / "models" / "speech" / "vibevoice")

# Qwen3-ASR models directory
QWEN_ASR_DIR = MODEL_PATHS.get('speech', {}).get('qwen_asr',
    settings.AI_MODELS_DIR / "models" / "speech" / "qwen_asr")

# Ensure directories exist
WHISPER_DIR.mkdir(parents=True, exist_ok=True)
VIBEVOICE_DIR.mkdir(parents=True, exist_ok=True)
QWEN_ASR_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

TRANSCRIBER_MODELS = {
    # UN SEUL moteur Whisper exposé par l'app (backend faster-whisper, modèle large-v3).
    # Les 5 variantes de taille (tiny/base/small/medium/large) étaient des stubs anglais jamais
    # affichés ni sélectionnables (aucun sélecteur de taille dans l'UI/params) — purgées, cf.
    # REMOVAL_LEDGER R10. Clé 'whisper' = nom du moteur backend = clé des stats ETA existantes
    # (`ModelRuntimeStat` : transcriber:whisper).
    # Description ABSENTE ici : la découverte la tire de la CLASSE backend
    # (`WhisperBackend.description`/`description_long`) — source unique = ce qui s'affiche.
    'whisper': {
        'model_id': 'large-v3',
        'hf_model_id': 'openai/whisper-large-v3',
        'type': 'speech-to-text',
        'size_gb': 2.87,
    },
}

# VibeVoice ASR models (Microsoft)
VIBEVOICE_MODELS = {
    'vibevoice-asr': {
        'model_id': 'vibevoice-asr',
        'hf_model_id': 'microsoft/VibeVoice-ASR',
        'type': 'speech-to-text',
        'size_gb': 18,
        'vram_gb': 16,
        # Description ABSENTE : tirée de la CLASSE backend (VibeVoiceBackend) par la découverte
        # — source unique = ce qui s'affiche. (L'ancien stub dupliquait, avec VRAM-in-text.)
        'supports_diarization': True,
        'supports_timestamps': True,
        'supports_hotwords': True,
        'max_audio_minutes': 60,
        'languages': '50+',
    },
}

# Qwen3-ASR models (Alibaba) — context biasing, 52 languages, low VRAM
QWEN_ASR_MODELS = {
    'qwen3-asr-0.6b': {
        'model_id': 'Qwen/Qwen3-ASR-0.6B',
        'hf_model_id': 'Qwen/Qwen3-ASR-0.6B',
        'type': 'speech-to-text',
        'size_gb': 1.5,
        'vram_gb': 2,
        # Description PAR-MODÈLE (2 tailles pour un même moteur) — la VRAM vient du catalogue
        # (vram_gb), jamais du texte.
        'description': 'Qwen3-ASR 0.6B — rapide, context biasing, 52 langues',
        'supports_hotwords': True,
        'supports_timestamps': True,
        'languages': '52',
    },
    'qwen3-asr-1.7b': {
        'model_id': 'Qwen/Qwen3-ASR-1.7B',
        'hf_model_id': 'Qwen/Qwen3-ASR-1.7B',
        'type': 'speech-to-text',
        'size_gb': 3.5,
        'vram_gb': 4,
        'description': 'Qwen3-ASR 1.7B — précis, context biasing, 52 langues',
        'supports_hotwords': True,
        'supports_timestamps': True,
        'languages': '52',
    },
}

# Combined models dictionary
TRANSCRIBER_MODELS = {
    **TRANSCRIBER_MODELS,
    **VIBEVOICE_MODELS,
    **QWEN_ASR_MODELS,
}

# Default model
DEFAULT_MODEL = 'whisper-base'


def setup_model_environment():
    """
    Setup environment variables for Whisper model caching.
    Call this before loading any models.
    """
    os.environ['WHISPER_CACHE'] = str(WHISPER_DIR)
    logger.info(f"Whisper cache directory: {WHISPER_DIR}")


def get_whisper_download_root() -> Path:
    """
    Get the download root directory for Whisper models.

    Returns:
        Path to the whisper models directory
    """
    return WHISPER_DIR


def get_model_info(model_key: str = None) -> dict:
    """
    Get model information.

    Args:
        model_key: Key from TRANSCRIBER_MODELS (e.g., 'whisper-base')
                   If None, returns default model info

    Returns:
        Dictionary with model configuration
    """
    if model_key is None:
        model_key = DEFAULT_MODEL

    if model_key not in TRANSCRIBER_MODELS:
        # Try to match by short name (e.g., 'base' -> 'whisper-base')
        full_key = f'whisper-{model_key}'
        if full_key in TRANSCRIBER_MODELS:
            model_key = full_key
        else:
            raise ValueError(f"Unknown model: {model_key}. Available: {list(TRANSCRIBER_MODELS.keys())}")

    return TRANSCRIBER_MODELS[model_key].copy()


def load_whisper_model(model_size: str = 'base', device: str = None):
    """
    Load a Whisper model with proper caching.

    Args:
        model_size: Size of the model ('tiny', 'base', 'small', 'medium', 'large')
        device: Device to load on ('cuda', 'cpu', or None for auto)

    Returns:
        Loaded whisper model
    """
    setup_model_environment()

    try:
        import whisper
        import torch

        if device is None:
            device = "cuda" if torch.cuda.is_available() else "cpu"

        download_root = str(WHISPER_DIR)
        logger.info(f"Loading Whisper {model_size} model from {download_root} on {device}")

        model = whisper.load_model(model_size, device=device, download_root=download_root)

        logger.info(f"Whisper {model_size} model loaded successfully")
        return model

    except ImportError:
        raise ImportError(
            "whisper library not installed. "
            "Install with: pip install openai-whisper"
        )


def list_available_models() -> dict:
    """
    List all available transcriber models with their status.

    Returns:
        Dictionary with model info and download status
    """
    result = {}

    for key, config in TRANSCRIBER_MODELS.items():
        # Check if model appears to be downloaded
        model_id = config['model_id']
        model_file = WHISPER_DIR / f"{model_id}.pt"
        is_downloaded = model_file.exists()

        result[key] = {
            **config,
            'downloaded': is_downloaded,
            'local_path': str(model_file) if is_downloaded else None,
        }

    return result
