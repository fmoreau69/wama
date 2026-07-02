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

# Higgs Audio models directory
HIGGS_DIR = MODEL_PATHS.get('speech', {}).get('higgs',
    settings.AI_MODELS_DIR / "models" / "speech" / "higgs")

# Kokoro models directory (hexgrad/Kokoro-82M)
KOKORO_DIR = MODEL_PATHS.get('speech', {}).get('kokoro',
    settings.AI_MODELS_DIR / "models" / "speech" / "kokoro")

# Ensure directories exist
Path(COQUI_DIR).mkdir(parents=True, exist_ok=True)
Path(BARK_DIR).mkdir(parents=True, exist_ok=True)
Path(HIGGS_DIR).mkdir(parents=True, exist_ok=True)
Path(KOKORO_DIR).mkdir(parents=True, exist_ok=True)

# =============================================================================
# DESCRIPTIONS (source unique par-app — le registre les LIT, ne les hardcode plus ; cf. R9)
# DEUX champs SÉPARÉS et INDÉPENDANTS (format de référence = transcriber/backends) :
#   'short' → affiché directement sous le select (concis, 1-2 clauses). PAS de VRAM (le JS
#             l'append depuis le catalogue vram_gb).
#   'long'  → paragraphe AUTONOME affiché en overlay ⓘ (peut mentionner la VRAM en prose).
# Clés = suffixe de model_key exposé par la découverte.
# =============================================================================

REGISTRY_MODEL_DESCRIPTIONS = {
    'coqui-xtts': {
        'short': "Coqui XTTS v2 — TTS multilingue avec clonage de voix.",
        'long': "Coqui XTTS v2 : synthèse vocale multilingue (17 langues) avec clonage de voix "
                "à partir d'un simple échantillon de référence de quelques secondes. Bon compromis "
                "qualité/rapidité, référence polyvalente pour la plupart des usages.",
    },
    'bark': {
        'short': "Bark — TTS expressif avec effets sonores.",
        'long': "Bark (Suno) : synthèse vocale expressive capable de générer rires, soupirs, "
                "hésitations et bruitages. Presets de locuteurs sur 13 langues ; ne fait pas de "
                "clonage de voix libre. Idéal pour un rendu vivant et naturel.",
    },
    'higgs-audio': {
        'short': "Higgs Audio v2 — multi-locuteurs avec clonage de voix.",
        'long': "Higgs Audio v2 (Boson AI, 3B) : synthèse multi-locuteurs avec clonage de voix et "
                "conditionnement de scène pour des dialogues à plusieurs voix. 9 langues. Le plus "
                "détaillé mais le plus gourmand en ressources.",
    },
    'kokoro': {
        'short': "Kokoro 82M — TTS multilingue ultra-léger.",
        'long': "Kokoro 82M : modèle de synthèse vocale très léger (82M paramètres) couvrant "
                "FR/EN/ES/IT/PT/JA/ZH avec des voix fixes par langue. Extrêmement rapide et peu "
                "gourmand, adapté au temps réel et aux petites configurations.",
    },
}

# Pont valeur d'option UI (select #tts_model, cf. TTS_MODEL_CHOICES) → clé catalogue
# (`AIModel.model_key` sans le préfixe `synthesizer:`). Les moteurs Coqui légers
# (vits/tacotron2/speedy_speech) n'ont pas d'entrée catalogue dédiée → pas d'aide affichée.
ENGINE_CATALOG_KEYS = {
    'xtts_v2': 'coqui-xtts',
    'bark': 'bark',
    'higgs_audio': 'higgs-audio',
    'kokoro': 'kokoro',
}

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
    'higgs_audio': {
        'model_id': 'bosonai/higgs-audio-v2-generation-3B-base',
        'tokenizer_id': 'bosonai/higgs-audio-v2-tokenizer',
        'type': 'tts',
        'engine': 'higgs',
        'multilingual': True,
        'voice_cloning': True,
        'multi_speaker': True,
        'description': 'Higgs Audio v2 - Multi-speaker, Voice Cloning (24GB VRAM)',
        'languages': ['en', 'fr', 'es', 'de', 'it', 'pt', 'zh-cn', 'ja', 'ko'],
    },
    'kokoro': {
        'model_id': 'hexgrad/Kokoro-82M',
        'type': 'tts',
        'engine': 'kokoro',
        'multilingual': True,
        'voice_cloning': False,
        'description': 'Kokoro 82M - Léger, FR/EN/ES/IT/PT/JA/ZH, sans clonage vocal',
        'languages': ['fr', 'en', 'es', 'it', 'pt', 'ja', 'zh-cn'],
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
    elif info['engine'] == 'higgs':
        info['cache_dir'] = str(HIGGS_DIR)
    elif info['engine'] == 'kokoro':
        info['cache_dir'] = str(KOKORO_DIR)

    return info


def list_available_models() -> dict:
    """
    List all available synthesizer models with their info.

    Returns:
        Dictionary with model info
    """
    result = {}

    for key, config in SYNTHESIZER_MODELS.items():
        cache_dirs = {'coqui': str(COQUI_DIR), 'bark': str(BARK_DIR), 'higgs': str(HIGGS_DIR), 'kokoro': str(KOKORO_DIR)}
        result[key] = {
            **config,
            'cache_dir': cache_dirs.get(config['engine'], str(COQUI_DIR)),
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


def get_higgs_directory() -> Path:
    """
    Get the Higgs Audio models directory path.

    Returns:
        Path to the Higgs Audio models directory
    """
    return Path(HIGGS_DIR)


def get_higgs_models() -> dict:
    """Get all Higgs Audio models."""
    return get_models_by_engine('higgs')
