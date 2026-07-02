"""
Enhancer Model Configuration

Centralized configuration for all models used by the Enhancer application.
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

# ONNX upscaling models directory
ONNX_MODELS_DIR = MODEL_PATHS.get('upscaling', {}).get('onnx',
    settings.AI_MODELS_DIR / "models" / "upscaling" / "onnx")

# Ensure directory exists
Path(ONNX_MODELS_DIR).mkdir(parents=True, exist_ok=True)

# =============================================================================
# DESCRIPTIONS (source unique par-app — le registre les LIT ; cf. REMOVAL_LEDGER R9).
# DEUX champs SÉPARÉS (format transcriber) : 'short' = one-liner sous le select (SANS VRAM,
# appendée par le JS depuis le catalogue) ; 'long' = paragraphe AUTONOME (overlay ⓘ).
# Clés = nom de fichier ONNX sans extension (= model_key sans le préfixe enhancer:).
# =============================================================================

REGISTRY_MODEL_DESCRIPTIONS = {
    'RealESRGANx4_fp16': {
        'short': "Real-ESRGAN ×4 — super-résolution photo de référence.",
        'long': "Real-ESRGAN ×4 (fp16, ONNX) : la référence de la super-résolution "
                "photographique — agrandit ×4 en reconstruisant détails et textures. "
                "Bon choix par défaut pour photos et captures réelles.",
    },
    'RealESR_Animex4_fp16': {
        'short': "Real-ESRGAN Anime ×4 — dessins et illustrations.",
        'long': "Real-ESRGAN Anime ×4 (fp16, ONNX) : variante spécialisée dessins, anime et "
                "illustrations — préserve les aplats et les contours nets sans inventer de "
                "texture photographique.",
    },
    'RealESR_Gx4_fp16': {
        'short': "Real-ESR general ×4 — généraliste ultra-léger.",
        'long': "Real-ESR general ×4 (fp16, ONNX) : version généraliste très compacte de "
                "Real-ESRGAN. Rapide et sobre, qualité légèrement en retrait — pour les "
                "traitements en volume ou les machines modestes.",
    },
    'BSRGANx4_fp16': {
        'short': "BSRGAN ×4 — robuste aux dégradations réelles.",
        'long': "BSRGAN ×4 (fp16, ONNX) : super-résolution entraînée sur des dégradations "
                "réalistes (flou, bruit, compression JPEG). Robuste sur images de qualité "
                "médiocre là où d'autres modèles amplifient les artefacts.",
    },
    'BSRGANx2_fp16': {
        'short': "BSRGAN ×2 — agrandissement modéré, robuste.",
        'long': "BSRGAN ×2 (fp16, ONNX) : même robustesse aux dégradations réelles que la "
                "version ×4, avec un agrandissement modéré ×2 — utile quand la source est "
                "déjà d'une taille correcte.",
    },
    'IRCNN_Lx1_fp16': {
        'short': "IRCNN L ×1 — débruitage sans agrandissement.",
        'long': "IRCNN variante L (fp16, ONNX) : débruitage pur (×1, aucune mise à l'échelle). "
                "Nettoie le bruit et les artefacts avant un éventuel upscale — à combiner avec "
                "un modèle ×2/×4.",
    },
    'IRCNN_Mx1_fp16': {
        'short': "IRCNN M ×1 — débruitage sans agrandissement (variante M).",
        'long': "IRCNN variante M (fp16, ONNX) : débruitage pur (×1), intensité de filtrage "
                "différente de la variante L — essayer les deux selon le niveau de bruit de "
                "la source.",
    },
}

# =============================================================================
# MODEL DEFINITIONS
# =============================================================================

ENHANCER_MODELS = {
    'RealESR_Gx4': {
        'model_id': 'RealESR_Gx4',
        'file': 'RealESR_Gx4_fp16.onnx',
        'type': 'upscaling',
        'scale': 4,
        'vram_usage': 2.5,
        'size_mb': 22,
        'description': 'Fast general-purpose 4x upscaler',
        'priority': 1,
    },
    'RealESR_Animex4': {
        'model_id': 'RealESR_Animex4',
        'file': 'RealESR_Animex4_fp16.onnx',
        'type': 'upscaling',
        'scale': 4,
        'vram_usage': 2.5,
        'size_mb': 22,
        'description': 'Fast anime-oriented 4x upscaler',
        'priority': 3,
    },
    'BSRGANx2': {
        'model_id': 'BSRGANx2',
        'file': 'BSRGANx2_fp16.onnx',
        'type': 'upscaling',
        'scale': 2,
        'vram_usage': 0.75,
        'size_mb': 4,
        'description': 'High-quality 2x upscaler',
        'priority': 2,
    },
    'BSRGANx4': {
        'model_id': 'BSRGANx4',
        'file': 'BSRGANx4_fp16.onnx',
        'type': 'upscaling',
        'scale': 4,
        'vram_usage': 0.75,
        'size_mb': 4,
        'description': 'High-quality 4x upscaler',
        'priority': 2,
    },
    'RealESRGANx4': {
        'model_id': 'RealESRGANx4',
        'file': 'RealESRGANx4_fp16.onnx',
        'type': 'upscaling',
        'scale': 4,
        'vram_usage': 2.5,
        'size_mb': 22,
        'description': 'Highest quality 4x upscaler (slow)',
        'priority': 3,
    },
    'IRCNN_Mx1': {
        'model_id': 'IRCNN_Mx1',
        'file': 'IRCNN_Mx1_fp16.onnx',
        'type': 'denoising',
        'scale': 1,
        'vram_usage': 4.0,
        'size_mb': 30,
        'description': 'Medium denoising (no upscaling)',
        'priority': 4,
    },
    'IRCNN_Lx1': {
        'model_id': 'IRCNN_Lx1',
        'file': 'IRCNN_Lx1_fp16.onnx',
        'type': 'denoising',
        'scale': 1,
        'vram_usage': 4.0,
        'size_mb': 30,
        'description': 'Strong denoising (no upscaling)',
        'priority': 4,
    },
}

# Default model
DEFAULT_MODEL = 'RealESR_Gx4'


def get_models_directory() -> Path:
    """
    Get the ONNX models directory path.

    Returns:
        Path to the ONNX models directory
    """
    return Path(ONNX_MODELS_DIR)


def get_model_path(model_name: str) -> Path:
    """
    Get the full path to a model file.

    Args:
        model_name: Model name from ENHANCER_MODELS

    Returns:
        Full path to the model file
    """
    if model_name not in ENHANCER_MODELS:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(ENHANCER_MODELS.keys())}")

    model_info = ENHANCER_MODELS[model_name]
    return get_models_directory() / model_info['file']


def get_model_info(model_name: str = None) -> dict:
    """
    Get model information.

    Args:
        model_name: Model name from ENHANCER_MODELS
                   If None, returns default model info

    Returns:
        Dictionary with model configuration
    """
    if model_name is None:
        model_name = DEFAULT_MODEL

    if model_name not in ENHANCER_MODELS:
        raise ValueError(f"Unknown model: {model_name}. Available: {list(ENHANCER_MODELS.keys())}")

    info = ENHANCER_MODELS[model_name].copy()
    info['local_path'] = str(get_model_path(model_name))
    info['downloaded'] = get_model_path(model_name).exists()

    return info


def list_available_models() -> dict:
    """
    List all available enhancer models with their status.

    Returns:
        Dictionary with model info and download status
    """
    result = {}

    for key, config in ENHANCER_MODELS.items():
        model_path = get_models_directory() / config['file']
        is_downloaded = model_path.exists()

        result[key] = {
            **config,
            'downloaded': is_downloaded,
            'local_path': str(model_path) if is_downloaded else None,
        }

    return result


def get_models_by_type(model_type: str) -> dict:
    """
    Get models filtered by type.

    Args:
        model_type: 'upscaling' or 'denoising'

    Returns:
        Dictionary of models matching the type
    """
    return {
        key: config
        for key, config in ENHANCER_MODELS.items()
        if config.get('type') == model_type
    }


def get_upscaling_models() -> dict:
    """Get all upscaling models."""
    return get_models_by_type('upscaling')


def get_denoising_models() -> dict:
    """Get all denoising models."""
    return get_models_by_type('denoising')
