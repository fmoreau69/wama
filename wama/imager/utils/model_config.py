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

COGVIDEOX_DIR = MODEL_PATHS.get('diffusion', {}).get('cogvideox',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "cogvideox")

LTX_DIR = MODEL_PATHS.get('diffusion', {}).get('ltx',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "ltx")

MOCHI_DIR = MODEL_PATHS.get('diffusion', {}).get('mochi',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "mochi")

FLUX_DIR = MODEL_PATHS.get('diffusion', {}).get('flux',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "flux")

LOGO_DIR = MODEL_PATHS.get('diffusion', {}).get('logo',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "logo")

# Ensure directories exist
for dir_path in [WAN_DIR, HUNYUAN_DIR, STABLE_DIFFUSION_DIR, COGVIDEOX_DIR, LTX_DIR, MOCHI_DIR, FLUX_DIR, LOGO_DIR]:
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
    'hunyuan-image-2.1': {
        'model_id': 'hunyuan-image-2.1',
        'hf_id': 'hunyuanvideo-community/HunyuanImage-2.1-Diffusers',
        'type': 'image',
        'mode': 't2i',
        'vram_gb': 16,
        'description': 'HunyuanImage 2.1 - High quality image generation',
    },
}

# CogVideoX Models
COGVIDEOX_MODELS = {
    'cogvideox-2b': {
        'model_id': 'cogvideox-2b',
        'hf_id': 'THUDM/CogVideoX-2b',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 4,
        'disk_gb': 6,
        'fps': 8,
        'resolution': '720x480',
        'description': 'CogVideoX 2B - Fast and efficient (4GB VRAM)',
    },
    'cogvideox-5b': {
        'model_id': 'cogvideox-5b',
        'hf_id': 'THUDM/CogVideoX-5b',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 5,
        'disk_gb': 12,
        'fps': 8,
        'resolution': '720x480',
        'description': 'CogVideoX 5B - Higher quality (5GB VRAM)',
    },
    'cogvideox-5b-i2v': {
        'model_id': 'cogvideox-5b-i2v',
        'hf_id': 'THUDM/CogVideoX-5b-I2V',
        'type': 'video',
        'mode': 'i2v',
        'vram_gb': 5,
        'disk_gb': 12,
        'fps': 8,
        'resolution': '720x480',
        'description': 'CogVideoX 5B I2V - Animate images (5GB VRAM)',
    },
}

# LTX-Video Models
LTX_MODELS = {
    'ltx-video-2b': {
        'model_id': 'ltx-video-2b',
        'hf_id': 'Lightricks/LTX-Video',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 8,
        'disk_gb': 5,
        'fps': 24,
        'resolution': '704x480',
        'description': 'LTX-Video 2B - Fast text-to-video (8GB VRAM)',
    },
    'ltx-video-0.9.8': {
        'model_id': 'ltx-video-0.9.8',
        'hf_id': 'Lightricks/LTX-Video-0.9.8-dev',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 10,
        'disk_gb': 6,
        'fps': 24,
        'resolution': '704x480',
        'description': 'LTX-Video 0.9.8 - Latest version (10GB VRAM)',
    },
    'ltx-video-0.9.8-distilled': {
        'model_id': 'ltx-video-0.9.8-distilled',
        'hf_id': 'Lightricks/LTX-Video-0.9.8-distilled',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 6,
        'disk_gb': 4,
        'fps': 24,
        'resolution': '704x480',
        'description': 'LTX-Video 0.9.8 Distilled - Light VRAM (6GB)',
    },
}

# Mochi Models
MOCHI_MODELS = {
    'mochi-1-preview': {
        'model_id': 'mochi-1-preview',
        'hf_id': 'genmo/mochi-1-preview',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 22,
        'disk_gb': 18,
        'fps': 30,
        'resolution': '848x480',
        'description': 'Mochi-1 Preview - High quality 30fps (22GB VRAM)',
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
    'deliberate-v6': {
        'model_id': 'deliberate-v6',
        'hf_id': 'XpucT/Deliberate',
        'single_file': 'Deliberate_v6.safetensors',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Deliberate v6 - Realistic/Artistic (by XpucT)',
    },
}

# =============================================================================
# LOGO GENERATION MODELS
# =============================================================================
# Specialized models for logo and brand design generation

LOGO_MODELS = {
    # FLUX.1-dev + LoRA for Logo Design
    'flux-lora-logo-design': {
        'model_id': 'flux-lora-logo-design',
        'hf_id': 'Shakker-Labs/FLUX.1-dev-LoRA-Logo-Design',
        'base_model': 'black-forest-labs/FLUX.1-dev',
        'type': 'image',
        'pipeline': 'flux',
        'model_type': 'lora',
        'category': 'logo',
        'trigger_words': ['wablogo', 'logo', 'Minimalist'],
        'lora_scale': 0.8,
        'vram_gb': 16,
        'disk_gb': 24,
        'resolution': 1024,
        'min_resolution': 512,
        'max_resolution': 1024,
        'license': 'flux-1-dev-non-commercial',
        'description': 'FLUX Logo Design LoRA - Excellent quality logos (16GB VRAM)',
        'prompt_tips': [
            'Dual concept: "cat and coffee"',
            'Font integration: "a book with the word M"',
            'Text placement: "Below the graphic is the word coffee"',
        ],
    },

    # LogoRedmond V2 - SDXL + LoRA
    'logo-redmond-v2': {
        'model_id': 'logo-redmond-v2',
        'hf_id': 'artificialguybr/LogoRedmond-LogoLoraForSDXL-V2',
        'base_model': 'stabilityai/stable-diffusion-xl-base-1.0',
        'type': 'image',
        'pipeline': 'sdxl',
        'model_type': 'lora',
        'category': 'logo',
        'trigger_words': ['LogoRedAF'],
        'lora_scale': 0.7,
        'vram_gb': 10,
        'disk_gb': 7,
        'resolution': 1024,
        'min_resolution': 512,
        'max_resolution': 1024,
        'license': 'creativeml-openrail-m',
        'description': 'LogoRedmond V2 (SDXL LoRA) - Commercial OK (10GB VRAM)',
        'prompt_tips': [
            'Use trigger word: LogoRedAF',
            'Add style: detailed, minimalist, colorful, black and white',
            'Simple prompts work best',
        ],
    },

    # Amazing Logos V2 - Full SD 1.5 fine-tune
    'amazing-logos-v2': {
        'model_id': 'amazing-logos-v2',
        'hf_id': 'iamkaikai/amazing-logos-v2',
        'type': 'image',
        'pipeline': 'sd',
        'model_type': 'full_finetune',
        'category': 'logo',
        'trigger_words': [],
        'vram_gb': 4,
        'disk_gb': 2,
        'resolution': 512,
        'min_resolution': 256,
        'max_resolution': 768,
        'license': 'creativeml-openrail-m',
        'description': 'Amazing Logos V2 (SD 1.5) - Commercial OK (4GB VRAM)',
        'prompt_format': '{template} + [company name] + [concept & country] + [industry] + {template}',
        'prompt_tips': [
            'Format: Simple elegant logo for [Name], [letter/shape] [country], [industry], successful vibe, minimalist',
            'Shapes: circle, square, triangle, diamond, hexagon, spiral, wave',
            'Add "black and white" for monochrome',
        ],
    },
}

# Combined models dictionary
IMAGER_MODELS = {
    **WAN_MODELS,
    **HUNYUAN_MODELS,
    **COGVIDEOX_MODELS,
    **LTX_MODELS,
    **MOCHI_MODELS,
    **STABLE_DIFFUSION_MODELS,
    **LOGO_MODELS,
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
    elif model_name in COGVIDEOX_MODELS:
        info['cache_dir'] = str(COGVIDEOX_DIR)
    elif model_name in LTX_MODELS:
        info['cache_dir'] = str(LTX_DIR)
    elif model_name in MOCHI_MODELS:
        info['cache_dir'] = str(MOCHI_DIR)
    elif model_name in LOGO_MODELS:
        # Logo models - use FLUX_DIR for FLUX-based, LOGO_DIR for others
        if info.get('pipeline') == 'flux':
            info['cache_dir'] = str(FLUX_DIR)
        else:
            info['cache_dir'] = str(LOGO_DIR)
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
        'cogvideox': COGVIDEOX_MODELS,
        'ltx': LTX_MODELS,
        'mochi': MOCHI_MODELS,
        'stable_diffusion': STABLE_DIFFUSION_MODELS,
        'logo': LOGO_MODELS,
    }


def get_video_models() -> dict:
    """Get all video generation models."""
    return {
        **WAN_MODELS,
        **HUNYUAN_MODELS,
        **COGVIDEOX_MODELS,
        **LTX_MODELS,
        **MOCHI_MODELS,
    }


def get_image_models() -> dict:
    """Get all image generation models (Stable Diffusion)."""
    return STABLE_DIFFUSION_MODELS


def get_cogvideox_directory() -> Path:
    """Get the CogVideoX models directory path."""
    return Path(COGVIDEOX_DIR)


def get_ltx_directory() -> Path:
    """Get the LTX-Video models directory path."""
    return Path(LTX_DIR)


def get_mochi_directory() -> Path:
    """Get the Mochi models directory path."""
    return Path(MOCHI_DIR)


def get_flux_directory() -> Path:
    """Get the FLUX models directory path."""
    return Path(FLUX_DIR)


def get_logo_directory() -> Path:
    """Get the Logo models directory path."""
    return Path(LOGO_DIR)


def get_logo_models() -> dict:
    """Get all logo generation models."""
    return LOGO_MODELS


def is_logo_model(model_name: str) -> bool:
    """Check if a model is a logo generation model."""
    return model_name in LOGO_MODELS


def is_lora_model(model_name: str) -> bool:
    """Check if a model uses LoRA."""
    if model_name not in IMAGER_MODELS:
        return False
    return IMAGER_MODELS[model_name].get('model_type') == 'lora'


def get_model_trigger_words(model_name: str) -> list:
    """Get trigger words for a model (used in prompt preprocessing)."""
    if model_name not in IMAGER_MODELS:
        return []
    return IMAGER_MODELS[model_name].get('trigger_words', [])


def get_model_prompt_tips(model_name: str) -> list:
    """Get prompt tips for a model."""
    if model_name not in IMAGER_MODELS:
        return []
    return IMAGER_MODELS[model_name].get('prompt_tips', [])
