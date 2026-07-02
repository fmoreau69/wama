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
        'description_long': "MusicGen Small (Meta AudioCraft, 300M) : génération musicale depuis "
                            "un prompt texte, version la plus légère et rapide de la famille. "
                            "Qualité en retrait — idéal pour esquisser des idées avant un rendu "
                            "sur Medium.",
        'max_duration': 30,
        'sample_rate': 32000,
        'cache_dir': MUSICGEN_DIR,
        # Estimation de durée (GPU chaud, RTX 4090) :
        # temps_total ≈ duration * gen_factor + overhead_s
        'gen_factor': 0.8,   # secondes de calcul par seconde d'audio
        'overhead_s': 12,    # chargement modèle + encodec
    },
    'musicgen-medium': {
        'hf_id': 'facebook/musicgen-medium',
        'audiocraft_name': 'medium',
        'type': 'music',
        'vram_gb': 8,
        'description': 'MusicGen Medium — meilleure qualité, 1.5B params',
        'description_long': "MusicGen Medium (Meta AudioCraft, 1.5B) : le meilleur équilibre "
                            "qualité/ressources de la famille MusicGen. Pistes instrumentales "
                            "cohérentes depuis un prompt texte (anglais — traduction automatique "
                            "en amont). Le choix par défaut.",
        'max_duration': 30,
        'sample_rate': 32000,
        'cache_dir': MUSICGEN_DIR,
        'gen_factor': 2.0,
        'overhead_s': 20,
    },
    'musicgen-melody': {
        'hf_id': 'facebook/musicgen-melody',
        'audiocraft_name': 'melody',
        'type': 'music',
        'vram_gb': 8,
        'description': 'MusicGen Melody — conditionné par mélodie de référence',
        'description_long': "MusicGen Melody (Meta AudioCraft) : génération guidée par une "
                            "MÉLODIE de référence (fichier audio) en plus du prompt — le modèle "
                            "suit la ligne mélodique fournie en changeant style et "
                            "instrumentation. Pour décliner un thème existant.",
        'max_duration': 30,
        'sample_rate': 32000,
        'cache_dir': MUSICGEN_DIR,
        'gen_factor': 2.2,
        'overhead_s': 22,
    },
    'audiogen-medium': {
        'hf_id': 'facebook/audiogen-medium',
        'audiocraft_name': 'facebook/audiogen-medium',
        'type': 'sfx',
        'vram_gb': 16,
        'description': 'AudioGen Medium — bruitages et sons d\'ambiance, 1.5B params',
        'description_long': "AudioGen Medium (Meta AudioCraft, 1.5B) : génération de BRUITAGES et "
                            "d'ambiances sonores (pas de musique) depuis un prompt texte — pas, "
                            "pluie, foule, machines… Complémentaire de MusicGen pour le sound "
                            "design.",
        'max_duration': 30,
        'sample_rate': 16000,
        'cache_dir': AUDIOGEN_DIR,
        'gen_factor': 2.0,
        'overhead_s': 20,
    },
}

MUSIC_MODELS = {k: v for k, v in COMPOSER_MODELS.items() if v['type'] == 'music'}
SFX_MODELS = {k: v for k, v in COMPOSER_MODELS.items() if v['type'] == 'sfx'}


def estimate_seconds(model_id: str, duration: float) -> int:
    """
    Estimate generation time in seconds (warm GPU, RTX 4090).
    Formula: duration * gen_factor + overhead_s
    Note: first-ever run adds ~30-60s for model download.
    """
    cfg = COMPOSER_MODELS.get(model_id, {})
    return max(5, int(duration * cfg.get('gen_factor', 1.5) + cfg.get('overhead_s', 15)))
