"""
Describer Model Configuration

Centralized configuration for all models used by the Describer application.
Uses the centralized AI-models directory structure from settings.py.
"""

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# =============================================================================
# MODEL PATHS CONFIGURATION
# =============================================================================

# Get centralized paths from settings
MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

# Vision-Language models — catégorie 'vlm' (ex-'vision-language')
BLIP_DIR = MODEL_PATHS.get('vlm', {}).get('blip',
    settings.AI_MODELS_DIR / "models" / "vlm" / "blip")

# HuggingFace cache (shared)
HF_CACHE_DIR = MODEL_PATHS.get('cache', {}).get('huggingface',
    settings.AI_MODELS_DIR / "cache" / "huggingface")

# Ensure directories exist
BLIP_DIR.mkdir(parents=True, exist_ok=True)
HF_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

DESCRIBER_MODELS = {
    # Image description
    'blip': {
        'engine': 'transformers',
        'model_id': 'Salesforce/blip-image-captioning-large',
        'type': 'vision-language',
        'task': 'image-to-text',
        'local_dir': BLIP_DIR,
        'description': "BLIP — légendage d'images (captioning)",
        'description_long': "BLIP (Salesforce) : modèle de légendage d'images — produit une "
                            "description textuelle du contenu visuel. Léger et rapide, utilisé "
                            "comme repli local quand aucun modèle vision plus riche (Ollama) "
                            "n'est disponible.",
        'size_gb': 1.8,
        'source': 'huggingface',
    },

    # Transcription audio : PAS de modèle propre. Le describer passe par la brique commune
    # `common/utils/whisper_utils.transcribe_audio`, qui charge `large-v3` par le backend du
    # transcriber — donc le modèle `transcriber:whisper`. L'entrée `whisper` qui vivait ici
    # annonçait `openai/whisper-base` à 0,3 Go (divergence relevée le 2026-09-06) : un doublon
    # sous une fausse identité, présent au menu du transcriber. Retirée le 2026-10-01 (R28).
}


def setup_model_environment():
    """
    Setup environment variables for model caching.
    Call this before loading any models.
    """
    logger.info(f"Model cache directories configured:")
    logger.info(f"  BLIP: {BLIP_DIR}")


def get_model_path(model_key: str) -> Path:
    """
    Get the local path for a model.

    Args:
        model_key: Key from DESCRIBER_MODELS (e.g., 'blip')

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
