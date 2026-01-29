"""
Synthesizer Model Configuration

Centralized configuration for all models used by the Synthesizer application.
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

# Coqui TTS models directory
COQUI_DIR = MODEL_PATHS.get('speech', {}).get('coqui',
    settings.AI_MODELS_DIR / "models" / "speech" / "coqui")

# Bark models directory
BARK_DIR = MODEL_PATHS.get('speech', {}).get('bark',
    settings.AI_MODELS_DIR / "models" / "speech" / "bark")

# Ensure directories exist
Path(COQUI_DIR).mkdir(parents=True, exist_ok=True)
Path(BARK_DIR).mkdir(parents=True, exist_ok=True)

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

SYNTHESIZER_MODELS = {
    'xtts_v2': {
        'model_id': 'tts_models/multilingual/multi-dataset/xtts_v2',
        'type': 'tts',
        'engine': 'coqui',
        'multilingual': True,
        'voice_cloning': True,
        'description': 'XTTS v2 - Voice cloning multilingual',
        'languages': ['en', 'es', 'fr', 'de', 'it', 'pt', 'pl', 'tr', 'ru', 'nl', 'cs', 'ar', 'zh-cn', 'ja', 'hu', 'ko'],
    },
    'vits': {
        'model_id': 'tts_models/en/vctk/vits',
        'type': 'tts',
        'engine': 'coqui',
        'multilingual': False,
        'voice_cloning': False,
        'description': 'VITS - Fast English TTS',
        'languages': ['en'],
    },
    'tacotron2': {
        'model_id': 'tts_models/en/ljspeech/tacotron2-DDC',
        'type': 'tts',
        'engine': 'coqui',
        'multilingual': False,
        'voice_cloning': False,
        'description': 'Tacotron2 - High quality English TTS',
        'languages': ['en'],
    },
    'speedy_speech': {
        'model_id': 'tts_models/en/ljspeech/speedy-speech',
        'type': 'tts',
        'engine': 'coqui',
        'multilingual': False,
        'voice_cloning': False,
        'description': 'Speedy Speech - Very fast English TTS',
        'languages': ['en'],
    },
    'bark': {
        'model_id': 'suno/bark',
        'type': 'tts',
        'engine': 'bark',
        'multilingual': True,
        'voice_cloning': False,
        'description': 'Bark - Natural, emotional TTS with sound effects',
        'languages': ['en', 'fr', 'es', 'de', 'it', 'pt', 'pl', 'tr', 'ru', 'nl', 'cs', 'zh-cn', 'ja', 'ko'],
    },
}

# Default model
DEFAULT_MODEL = 'xtts_v2'


def setup_model_environment():
    """
    Setup environment variables for TTS model caching.
    Call this before loading any models.
    """
    # Coqui TTS home directory
    os.environ['TTS_HOME'] = str(COQUI_DIR)
    logger.info(f"TTS_HOME set to: {COQUI_DIR}")

    # Bark uses XDG_CACHE_HOME - but we set it per-session in workers.py
    # to avoid affecting other HuggingFace downloads
    logger.info(f"Bark cache directory: {BARK_DIR}")


def get_coqui_directory() -> Path:
    """
    Get the Coqui TTS models directory path.

    Returns:
        Path to the Coqui TTS models directory
    """
    return Path(COQUI_DIR)


def get_bark_directory() -> Path:
    """
    Get the Bark models directory path.

    Returns:
        Path to the Bark models directory
    """
    return Path(BARK_DIR)


def get_model_info(model_name: str = None) -> dict:
    """
    Get model information.

    Args:
        model_name: Model name from SYNTHESIZER_MODELS
                   If None, returns default model info

    Returns:
        Dictionary with model configuration
    """
    if model_name is None:
        model_name = DEFAULT_MODEL

    if model_name not in SYNTHESIZER_MODELS:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(SYNTHESIZER_MODELS.keys())}")

    info = SYNTHESIZER_MODELS[model_name].copy()

    # Add path info based on engine
    if info['engine'] == 'coqui':
        info['cache_dir'] = str(COQUI_DIR)
    elif info['engine'] == 'bark':
        info['cache_dir'] = str(BARK_DIR)

    return info


def list_available_models() -> dict:
    """
    List all available synthesizer models with their info.

    Returns:
        Dictionary with model info
    """
    result = {}

    for key, config in SYNTHESIZER_MODELS.items():
        result[key] = {
            **config,
            'cache_dir': str(COQUI_DIR) if config['engine'] == 'coqui' else str(BARK_DIR),
        }

    return result


def get_models_by_engine(engine: str) -> dict:
    """
    Get models filtered by engine.

    Args:
        engine: 'coqui' or 'bark'

    Returns:
        Dictionary of models matching the engine
    """
    return {
        key: config
        for key, config in SYNTHESIZER_MODELS.items()
        if config.get('engine') == engine
    }


def get_coqui_models() -> dict:
    """Get all Coqui TTS models."""
    return get_models_by_engine('coqui')


def get_bark_models() -> dict:
    """Get all Bark models."""
    return get_models_by_engine('bark')
