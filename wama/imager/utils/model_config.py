"""
Imager Model Configuration

Centralized configuration for all models used by the Imager application.
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

# Diffusion models directories
WAN_DIR = MODEL_PATHS.get('diffusion', {}).get('wan',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "wan")

HUNYUAN_DIR = MODEL_PATHS.get('diffusion', {}).get('hunyuan',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "hunyuan")

STABLE_DIFFUSION_DIR = MODEL_PATHS.get('diffusion', {}).get('stable_diffusion',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "stable-diffusion")

# Ensure directories exist
for dir_path in [WAN_DIR, HUNYUAN_DIR, STABLE_DIFFUSION_DIR]:
    Path(dir_path).mkdir(parents=True, exist_ok=True)

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

# Wan Video Models
WAN_MODELS = {
    'wan-ti2v-5b': {
        'model_id': 'wan-ti2v-5b',
        'hf_id': 'Wan-AI/Wan2.2-TI2V-5B-Diffusers',
        'type': 'video',
        'mode': 'txt2vid',
        'vram_gb': 8,
        'description': 'Wan 2.2 TI2V 5B (~8GB)',
    },
    'wan-t2v-14b': {
        'model_id': 'wan-t2v-14b',
        'hf_id': 'Wan-AI/Wan2.2-T2V-A14B-Diffusers',
        'type': 'video',
        'mode': 'txt2vid',
        'vram_gb': 24,
        'description': 'Wan 2.2 T2V 14B (~24GB)',
    },
    'wan-i2v-14b': {
        'model_id': 'wan-i2v-14b',
        'hf_id': 'Wan-AI/Wan2.2-I2V-A14B-Diffusers',
        'type': 'video',
        'mode': 'img2vid',
        'vram_gb': 24,
        'description': 'Wan 2.2 I2V 14B (~24GB)',
    },
}

# Hunyuan Video Models
HUNYUAN_MODELS = {
    'hunyuan-t2v-480p': {
        'model_id': 'hunyuan-t2v-480p',
        'hf_id': 'hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_t2v',
        'type': 'video',
        'mode': 't2v',
        'resolution': '480p',
        'vram_gb': 14,
        'description': 'HunyuanVideo 1.5 T2V 480p',
    },
    'hunyuan-t2v-720p': {
        'model_id': 'hunyuan-t2v-720p',
        'hf_id': 'hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-720p_t2v',
        'type': 'video',
        'mode': 't2v',
        'resolution': '720p',
        'vram_gb': 24,
        'description': 'HunyuanVideo 1.5 T2V 720p',
    },
    'hunyuan-i2v-480p': {
        'model_id': 'hunyuan-i2v-480p',
        'hf_id': 'hunyuanvideo-community/HunyuanVideo-1.5-Diffusers-480p_i2v',
        'type': 'video',
        'mode': 'i2v',
        'resolution': '480p',
        'vram_gb': 14,
        'description': 'HunyuanVideo 1.5 I2V 480p',
    },
}

# Stable Diffusion Models (image generation)
STABLE_DIFFUSION_MODELS = {
    'stable-diffusion-v1-5': {
        'model_id': 'stable-diffusion-v1-5',
        'hf_id': 'stable-diffusion-v1-5/stable-diffusion-v1-5',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Stable Diffusion 1.5 - Classic model',
    },
    'stable-diffusion-xl': {
        'model_id': 'stable-diffusion-xl',
        'hf_id': 'stabilityai/stable-diffusion-xl-base-1.0',
        'type': 'image',
        'pipeline': 'sdxl',
        'vram_gb': 10,
        'description': 'Stable Diffusion XL - High resolution',
    },
    'openjourney-v4': {
        'model_id': 'openjourney-v4',
        'hf_id': 'prompthero/openjourney-v4',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'OpenJourney v4 - Midjourney style',
    },
    'dreamlike-art-2': {
        'model_id': 'dreamlike-art-2',
        'hf_id': 'dreamlike-art/dreamlike-diffusion-1.0',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Dreamlike Art - Artistic style',
    },
    'realistic-vision-v5': {
        'model_id': 'realistic-vision-v5',
        'hf_id': 'SG161222/Realistic_Vision_V5.1_noVAE',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Realistic Vision V5 - Photorealistic',
    },
    'deliberate-v2': {
        'model_id': 'deliberate-v2',
        'hf_id': 'stablediffusionapi/deliberate-v2',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Deliberate v2 - Realistic/Artistic',
    },
}

# Combined models dictionary
IMAGER_MODELS = {
    **WAN_MODELS,
    **HUNYUAN_MODELS,
    **STABLE_DIFFUSION_MODELS,
}


def setup_model_environment():
    """
    Setup environment variables for model caching.
    Call this before loading any models.
    """
    logger.info(f"Wan models directory: {WAN_DIR}")
    logger.info(f"Hunyuan models directory: {HUNYUAN_DIR}")
    logger.info(f"Stable Diffusion models directory: {STABLE_DIFFUSION_DIR}")


def get_wan_directory() -> Path:
    """Get the Wan models directory path."""
    return Path(WAN_DIR)


def get_hunyuan_directory() -> Path:
    """Get the Hunyuan models directory path."""
    return Path(HUNYUAN_DIR)


def get_stable_diffusion_directory() -> Path:
    """Get the Stable Diffusion models directory path."""
    return Path(STABLE_DIFFUSION_DIR)


def setup_hf_cache_for_wan():
    """Setup HuggingFace cache for Wan models."""
    wan_dir = str(WAN_DIR)
    os.environ['HF_HUB_CACHE'] = wan_dir
    os.environ['HF_HOME'] = wan_dir
    os.environ['HUGGINGFACE_HUB_CACHE'] = wan_dir
    return wan_dir


def setup_hf_cache_for_hunyuan():
    """Setup HuggingFace cache for Hunyuan models."""
    hunyuan_dir = str(HUNYUAN_DIR)
    os.environ['HF_HUB_CACHE'] = hunyuan_dir
    os.environ['HF_HOME'] = hunyuan_dir
    os.environ['HUGGINGFACE_HUB_CACHE'] = hunyuan_dir
    return hunyuan_dir


def get_model_info(model_name: str) -> dict:
    """
    Get model information.

    Args:
        model_name: Model name from IMAGER_MODELS

    Returns:
        Dictionary with model configuration
    """
    if model_name not in IMAGER_MODELS:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(IMAGER_MODELS.keys())}")

    info = IMAGER_MODELS[model_name].copy()

    # Add cache directory based on model type
    if model_name in WAN_MODELS:
        info['cache_dir'] = str(WAN_DIR)
    elif model_name in HUNYUAN_MODELS:
        info['cache_dir'] = str(HUNYUAN_DIR)
    else:
        info['cache_dir'] = str(STABLE_DIFFUSION_DIR)

    return info


def list_available_models() -> dict:
    """
    List all available imager models with their info.

    Returns:
        Dictionary with model info grouped by type
    """
    return {
        'wan': WAN_MODELS,
        'hunyuan': HUNYUAN_MODELS,
        'stable_diffusion': STABLE_DIFFUSION_MODELS,
    }


def get_video_models() -> dict:
    """Get all video generation models (Wan + Hunyuan)."""
    return {**WAN_MODELS, **HUNYUAN_MODELS}


def get_image_models() -> dict:
    """Get all image generation models (Stable Diffusion)."""
    return STABLE_DIFFUSION_MODELS
