"""
Describer Model Configuration

Centralized configuration for all models used by the Describer application.
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

# Vision-Language models
BLIP_DIR = MODEL_PATHS.get('vision_language', {}).get('blip',
    settings.AI_MODELS_DIR / "models" / "vision-language" / "blip")

BART_DIR = MODEL_PATHS.get('vision_language', {}).get('bart',
    settings.AI_MODELS_DIR / "models" / "vision-language" / "bart")

# Speech models (Whisper)
WHISPER_DIR = MODEL_PATHS.get('speech', {}).get('whisper',
    settings.AI_MODELS_DIR / "models" / "speech" / "whisper")

# HuggingFace cache (shared)
HF_CACHE_DIR = MODEL_PATHS.get('cache', {}).get('huggingface',
    settings.AI_MODELS_DIR / "cache" / "huggingface")

# Ensure directories exist
BLIP_DIR.mkdir(parents=True, exist_ok=True)
BART_DIR.mkdir(parents=True, exist_ok=True)
WHISPER_DIR.mkdir(parents=True, exist_ok=True)
HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

DESCRIBER_MODELS = {
    # Image description
    'blip': {
        'model_id': 'Salesforce/blip-image-captioning-large',
        'type': 'vision-language',
        'task': 'image-to-text',
        'local_dir': BLIP_DIR,
        'description': 'BLIP image captioning model for detailed image descriptions',
        'size_gb': 1.8,
        'source': 'huggingface',
    },

    # Text summarization
    'bart': {
        'model_id': 'facebook/bart-large-cnn',
        'type': 'summarization',
        'task': 'summarization',
        'local_dir': BART_DIR,
        'description': 'BART model for text summarization',
        'size_gb': 1.6,
        'source': 'huggingface',
    },

    # Audio transcription
    'whisper': {
        'model_id': 'openai/whisper-base',
        'type': 'speech-to-text',
        'task': 'automatic-speech-recognition',
        'local_dir': WHISPER_DIR,
        'description': 'OpenAI Whisper for audio transcription',
        'size_gb': 0.3,
        'source': 'openai',  # Uses whisper library, not HF
        'variants': ['tiny', 'base', 'small', 'medium', 'large'],
    },
}


def setup_model_environment():
    """
    Setup environment variables for model caching.
    Call this before loading any models.
    """
    # Whisper uses its own cache
    os.environ['WHISPER_CACHE'] = str(WHISPER_DIR)

    logger.info(f"Model cache directories configured:")
    logger.info(f"  BLIP: {BLIP_DIR}")
    logger.info(f"  BART: {BART_DIR}")
    logger.info(f"  Whisper: {WHISPER_DIR}")


def get_model_path(model_key: str) -> Path:
    """
    Get the local path for a model.

    Args:
        model_key: Key from DESCRIBER_MODELS (e.g., 'blip', 'whisper')

    Returns:
        Path to the model directory
    """
    if model_key not in DESCRIBER_MODELS:
        raise ValueError(f"Unknown model: {model_key}. Available: {list(DESCRIBER_MODELS.keys())}")

    return DESCRIBER_MODELS[model_key]['local_dir']


def get_model_info(model_key: str) -> dict:
    """
    Get full model information.

    Args:
        model_key: Key from DESCRIBER_MODELS

    Returns:
        Dictionary with model configuration
    """
    if model_key not in DESCRIBER_MODELS:
        raise ValueError(f"Unknown model: {model_key}")

    return DESCRIBER_MODELS[model_key].copy()


def list_available_models() -> dict:
    """
    List all available describer models with their status.

    Returns:
        Dictionary with model info and download status
    """
    result = {}

    for key, config in DESCRIBER_MODELS.items():
        local_dir = config['local_dir']

        # Check if model appears to be downloaded
        is_downloaded = False
        if local_dir.exists():
            # Check for any model files
            model_files = list(local_dir.glob('**/*.bin')) + \
                         list(local_dir.glob('**/*.safetensors')) + \
                         list(local_dir.glob('**/*.pt'))
            is_downloaded = len(model_files) > 0

        result[key] = {
            **config,
            'downloaded': is_downloaded,
            'local_path': str(local_dir),
        }

    return result


# Setup environment on module import
setup_model_environment()
