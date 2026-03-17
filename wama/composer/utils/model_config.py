"""
Composer Model Configuration

AudioCraft models (MusicGen + AudioGen) for music and SFX generation.
"""

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model paths (CLAUDE.md rule: paths first, then imports)
# ---------------------------------------------------------------------------

MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

MUSICGEN_DIR = MODEL_PATHS.get('music', {}).get(
    'musicgen', settings.AI_MODELS_DIR / 'models' / 'music' / 'musicgen'
)
AUDIOGEN_DIR = MODEL_PATHS.get('music', {}).get(
    'audiogen', settings.AI_MODELS_DIR / 'models' / 'music' / 'audiogen'
)

Path(MUSICGEN_DIR).mkdir(parents=True, exist_ok=True)
Path(AUDIOGEN_DIR).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

COMPOSER_MODELS = {
    'musicgen-small': {
        'hf_id': 'facebook/musicgen-small',
        'audiocraft_name': 'small',
        'type': 'music',
        'vram_gb': 4,
        'description': 'MusicGen Small — génération rapide, 300M params',
        'max_duration': 30,
        'sample_rate': 32000,
        'cache_dir': MUSICGEN_DIR,
    },
    'musicgen-medium': {
        'hf_id': 'facebook/musicgen-medium',
        'audiocraft_name': 'medium',
        'type': 'music',
        'vram_gb': 8,
        'description': 'MusicGen Medium — meilleure qualité, 1.5B params',
        'max_duration': 30,
        'sample_rate': 32000,
        'cache_dir': MUSICGEN_DIR,
    },
    'musicgen-melody': {
        'hf_id': 'facebook/musicgen-melody',
        'audiocraft_name': 'melody',
        'type': 'music',
        'vram_gb': 8,
        'description': 'MusicGen Melody — conditionné par mélodie de référence',
        'max_duration': 30,
        'sample_rate': 32000,
        'cache_dir': MUSICGEN_DIR,
    },
    'audiogen-medium': {
        'hf_id': 'facebook/audiogen-medium',
        'audiocraft_name': 'medium',
        'type': 'sfx',
        'vram_gb': 16,
        'description': 'AudioGen Medium — bruitages et sons d\'ambiance, 1.5B params',
        'max_duration': 30,
        'sample_rate': 16000,
        'cache_dir': AUDIOGEN_DIR,
    },
}

MUSIC_MODELS = {k: v for k, v in COMPOSER_MODELS.items() if v['type'] == 'music'}
SFX_MODELS = {k: v for k, v in COMPOSER_MODELS.items() if v['type'] == 'sfx'}
