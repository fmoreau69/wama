"""
Imager Model Configuration

Centralized configuration for all models used by the Imager application.
Uses the centralized AI-models directory structure from settings.py.

# ════════════════════════════════════════════════════════════════════════
# ⚠️  RÈGLE OBLIGATOIRE — AJOUT D'UN NOUVEAU MODÈLE
# ════════════════════════════════════════════════════════════════════════
#
# Avant d'ajouter un modèle qui télécharge via HuggingFace Hub :
#
#  1. Ajouter une entrée dans settings.MODEL_PATHS['diffusion'] (ou 'speech'
#     etc.) avec le chemin dédié au modèle.
#
#  2. Ajouter la constante *_DIR ici en la lisant depuis MODEL_PATHS
#     (avec fallback explicite), par exemple :
#         MONMODELE_DIR = MODEL_PATHS.get('diffusion', {}).get('mon_modele',
#             settings.AI_MODELS_DIR / "models" / "diffusion" / "mon-modele")
#
#  3. Dans le backend (backends/*.py), AVANT tout import de transformers /
#     diffusers / huggingface_hub, ajouter :
#         os.environ['HF_HUB_CACHE'] = str(MON_MODELE_DIR)
#         os.environ['HUGGINGFACE_HUB_CACHE'] = str(MON_MODELE_DIR)
#     ET passer cache_dir=str(MON_MODELE_DIR) à from_pretrained().
#
#  4. Ajouter l'entrée dans IMAGER_MODELS (ou le groupe approprié) avec
#     au minimum : model_id, hf_id, type, mode, vram_gb, description.
#
#  5. Mettre à jour _discover_imager_models() dans model_registry.py.
#
#  Ne jamais laisser un modèle se télécharger dans AI-models/cache/huggingface/
#  via la mise en cache globale par défaut — chaque modèle a son propre répertoire.
# ════════════════════════════════════════════════════════════════════════
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

QWEN_IMAGE_DIR = MODEL_PATHS.get('diffusion', {}).get('qwen_image',
    settings.AI_MODELS_DIR / "models" / "diffusion" / "qwen-image")

# Ensure directories exist
for dir_path in [HUNYUAN_DIR, STABLE_DIFFUSION_DIR, COGVIDEOX_DIR, LTX_DIR,
                 MOCHI_DIR, FLUX_DIR, LOGO_DIR, QWEN_IMAGE_DIR]:
    Path(dir_path).mkdir(parents=True, exist_ok=True)

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

# ─── Hunyuan Image (Tencent) ──────────────────────────────────────────────────
HUNYUAN_MODELS = {
    'hunyuan-image-2.1': {
        'model_id': 'hunyuan-image-2.1',
        'hf_id': 'hunyuanvideo-community/HunyuanImage-2.1-Diffusers',
        'type': 'image',
        'mode': 't2i',
        'vram_gb': 16,
        'description': 'HunyuanImage 2.1 — qualité max, text rendering, 1K-4K',
    },
}

# ─── CogVideoX (Tsinghua THUDM) ───────────────────────────────────────────────
COGVIDEOX_MODELS = {
    'cogvideox-5b': {
        'model_id': 'cogvideox-5b',
        'hf_id': 'THUDM/CogVideoX-5b',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 5,
        'disk_gb': 12,
        'fps': 24,
        'resolution': '720x480',
        'description': 'CogVideoX 5B T2V (5GB VRAM, 24fps)',
    },
    'cogvideox-5b-i2v': {
        'model_id': 'cogvideox-5b-i2v',
        'hf_id': 'THUDM/CogVideoX-5b-I2V',
        'type': 'video',
        'mode': 'i2v',
        'vram_gb': 5,
        'disk_gb': 12,
        'fps': 24,
        'resolution': '720x480',
        'description': 'CogVideoX 5B I2V — Image-to-Video (5GB VRAM)',
    },
}

# ─── LTX-Video (Lightricks) ───────────────────────────────────────────────────
LTX_MODELS = {
    'ltx-video-0.9.8-distilled': {
        'model_id': 'ltx-video-0.9.8-distilled',
        'hf_id': 'Lightricks/LTX-Video-0.9.8-distilled',
        'type': 'video',
        'mode': 't2v',
        'vram_gb': 6,
        'disk_gb': 4,
        'fps': 24,
        'resolution': '704x480',
        'description': 'LTX-Video Distilled — rapide, 24fps (6GB VRAM)',
    },
}

# ─── Mochi (Genmo) ────────────────────────────────────────────────────────────
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
        'description': 'Mochi-1 Preview — haute qualité 30fps (22GB VRAM)',
    },
}

# ─── Stable Diffusion (image generation) ─────────────────────────────────────
STABLE_DIFFUSION_MODELS = {
    'stable-diffusion-v1-5': {
        'model_id': 'stable-diffusion-v1-5',
        'hf_id': 'stable-diffusion-v1-5/stable-diffusion-v1-5',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Stable Diffusion 1.5 — classique (compatibilité LoRA)',
    },
    'stable-diffusion-xl': {
        'model_id': 'stable-diffusion-xl',
        'hf_id': 'stabilityai/stable-diffusion-xl-base-1.0',
        'type': 'image',
        'pipeline': 'sdxl',
        'vram_gb': 10,
        'description': 'Stable Diffusion XL — haute résolution (compatibilité LoRA)',
    },
    'dreamlike-art-2': {
        'model_id': 'dreamlike-art-2',
        'hf_id': 'dreamlike-art/dreamlike-diffusion-1.0',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Dreamlike Art — style artistique',
    },
    'deliberate-v6': {
        'model_id': 'deliberate-v6',
        'hf_id': 'XpucT/Deliberate',
        'single_file': 'Deliberate_v6.safetensors',
        'type': 'image',
        'pipeline': 'sd',
        'vram_gb': 4,
        'description': 'Deliberate v6 — réaliste/artistique',
    },
}

# ─── Qwen Image 2 (Alibaba) ───────────────────────────────────────────────────
# Apache 2.0 — #1 open source (AI Arena), text rendering, 2K natif, character consistency
# HF IDs : Qwen/Qwen-Image-2512 (20B, gen), Qwen/Qwen-Image-Edit-2511 (editing)
# Backend : qwen_image_backend.py (diffusers-compatible)
QWEN_IMAGE_MODELS = {
    'qwen-image-2': {
        'model_id': 'qwen-image-2',
        'hf_id': 'Qwen/Qwen-Image-2512',
        'type': 'image',
        'mode': 't2i',
        'pipeline': 'qwen_image',
        'vram_gb': 16,
        'disk_gb': 40,
        'resolution': 2048,
        'description': 'Qwen Image 2 (20B) — #1 open source, text rendering, 2K natif',
        'license': 'apache-2.0',
    },
    'qwen-image-edit': {
        'model_id': 'qwen-image-edit',
        'hf_id': 'Qwen/Qwen-Image-Edit-2511',
        'type': 'image',
        'mode': 'edit',
        'pipeline': 'qwen_image',
        'vram_gb': 12,
        'disk_gb': 25,
        'resolution': 2048,
        'description': 'Qwen Image Edit — édition multi-image, 14 images, 2K',
        'license': 'apache-2.0',
    },
}

# =============================================================================
# LOGO GENERATION MODELS
# =============================================================================

LOGO_MODELS = {
    # Shakker-Labs FLUX Logo Design LoRA — best open-source logo model (2025-2026)
    # HF benchmark #1 for local logo generation. Replaces logo-redmond-v2 and amazing-logos-v2.
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
        'resolution': 768,
        'min_resolution': 512,
        'max_resolution': 768,
        # FLUX uses rectified flow — guidance_scale 3.5–7.5 (NOT 7.5–20 like SD)
        'default_guidance_scale': 3.5,
        'default_steps': 24,
        'license': 'flux-1-dev-non-commercial',
        'description': 'FLUX Logo Design LoRA — #1 open-source, logos professionnels, max 768px (16GB VRAM)',
        'prompt_tips': [
            'Dual Combination: "wablogo, Minimalist, Dual Combination: mountain and coffee cup"',
            'Font Combination: "wablogo, logo, Minimalist, Font Combination: rocket with letter S"',
            'Text below: "wablogo, Minimalist, coffee bean icon, Text Below Graphic: word \'BREW\'"',
            'guidance_scale recommandé : 3.5 (FLUX — pas 7.5 ni 20)',
        ],
    },
}

# =============================================================================
# COMBINED DICTIONARY
# =============================================================================

IMAGER_MODELS = {
    **HUNYUAN_MODELS,
    **COGVIDEOX_MODELS,
    **LTX_MODELS,
    **MOCHI_MODELS,
    **STABLE_DIFFUSION_MODELS,
    **QWEN_IMAGE_MODELS,
    **LOGO_MODELS,
}


# =============================================================================
# ENVIRONMENT SETUP HELPERS
# =============================================================================

def setup_hf_cache_for_model(cache_dir: str) -> None:
    """
    Set HuggingFace cache environment variables for a specific model directory.

    Call this BEFORE any import of transformers / diffusers / huggingface_hub
    to ensure ALL downloads (weights, tokenizer, configs) go to the right place.

    Args:
        cache_dir: Absolute path string to the model's dedicated directory.
    """
    os.environ['HF_HUB_CACHE'] = cache_dir
    os.environ['HUGGINGFACE_HUB_CACHE'] = cache_dir


def setup_hf_cache_for_hunyuan() -> str:
    """Setup HuggingFace cache for Hunyuan models. Returns the cache dir."""
    cache_dir = str(HUNYUAN_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_cogvideox() -> str:
    """Setup HuggingFace cache for CogVideoX models. Returns the cache dir."""
    cache_dir = str(COGVIDEOX_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_ltx() -> str:
    """Setup HuggingFace cache for LTX models. Returns the cache dir."""
    cache_dir = str(LTX_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_mochi() -> str:
    """Setup HuggingFace cache for Mochi models. Returns the cache dir."""
    cache_dir = str(MOCHI_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


def setup_hf_cache_for_qwen_image() -> str:
    """Setup HuggingFace cache for Qwen Image models. Returns the cache dir."""
    cache_dir = str(QWEN_IMAGE_DIR)
    setup_hf_cache_for_model(cache_dir)
    return cache_dir


# =============================================================================
# QUERY HELPERS
# =============================================================================

def get_model_info(model_name: str) -> dict:
    """
    Get model information including its dedicated cache directory.

    Args:
        model_name: Model ID from IMAGER_MODELS

    Returns:
        Dictionary with model configuration + cache_dir key
    """
    if model_name not in IMAGER_MODELS:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(IMAGER_MODELS.keys())}")

    info = IMAGER_MODELS[model_name].copy()

    if model_name in HUNYUAN_MODELS:
        info['cache_dir'] = str(HUNYUAN_DIR)
    elif model_name in COGVIDEOX_MODELS:
        info['cache_dir'] = str(COGVIDEOX_DIR)
    elif model_name in LTX_MODELS:
        info['cache_dir'] = str(LTX_DIR)
    elif model_name in MOCHI_MODELS:
        info['cache_dir'] = str(MOCHI_DIR)
    elif model_name in QWEN_IMAGE_MODELS:
        info['cache_dir'] = str(QWEN_IMAGE_DIR)
    elif model_name in LOGO_MODELS:
        info['cache_dir'] = str(FLUX_DIR) if info.get('pipeline') == 'flux' else str(LOGO_DIR)
    else:
        info['cache_dir'] = str(STABLE_DIFFUSION_DIR)

    return info


def list_available_models() -> dict:
    """List all available imager models grouped by family."""
    return {
        'hunyuan': HUNYUAN_MODELS,
        'cogvideox': COGVIDEOX_MODELS,
        'ltx': LTX_MODELS,
        'mochi': MOCHI_MODELS,
        'stable_diffusion': STABLE_DIFFUSION_MODELS,
        'qwen_image': QWEN_IMAGE_MODELS,
        'logo': LOGO_MODELS,
    }


def get_video_models() -> dict:
    """Get all video generation models."""
    return {
        **COGVIDEOX_MODELS,
        **LTX_MODELS,
        **MOCHI_MODELS,
    }


def get_image_models() -> dict:
    """Get all image generation models (excluding logo and video)."""
    return {
        **HUNYUAN_MODELS,
        **STABLE_DIFFUSION_MODELS,
        **QWEN_IMAGE_MODELS,
    }


def get_hunyuan_directory() -> Path:
    return Path(HUNYUAN_DIR)


def get_stable_diffusion_directory() -> Path:
    return Path(STABLE_DIFFUSION_DIR)


def get_cogvideox_directory() -> Path:
    return Path(COGVIDEOX_DIR)


def get_ltx_directory() -> Path:
    return Path(LTX_DIR)


def get_mochi_directory() -> Path:
    return Path(MOCHI_DIR)


def get_flux_directory() -> Path:
    return Path(FLUX_DIR)


def get_logo_directory() -> Path:
    return Path(LOGO_DIR)


def get_qwen_image_directory() -> Path:
    return Path(QWEN_IMAGE_DIR)


def get_logo_models() -> dict:
    return LOGO_MODELS


def is_logo_model(model_name: str) -> bool:
    return model_name in LOGO_MODELS


def is_lora_model(model_name: str) -> bool:
    if model_name not in IMAGER_MODELS:
        return False
    return IMAGER_MODELS[model_name].get('model_type') == 'lora'


def get_model_trigger_words(model_name: str) -> list:
    if model_name not in IMAGER_MODELS:
        return []
    return IMAGER_MODELS[model_name].get('trigger_words', [])


def get_model_prompt_tips(model_name: str) -> list:
    if model_name not in IMAGER_MODELS:
        return []
    return IMAGER_MODELS[model_name].get('prompt_tips', [])
