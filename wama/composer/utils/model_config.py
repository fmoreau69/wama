"""
Composer Model Configuration

AudioCraft models (MusicGen + AudioGen) for music and SFX generation.
"""

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Model paths (AGENTS.md rule: paths first, then imports)
# ---------------------------------------------------------------------------

MODEL_PATHS = getattr(settings, 'MODEL_PATHS', {})

MUSICGEN_DIR = MODEL_PATHS.get('music', {}).get(
    'musicgen', settings.AI_MODELS_DIR / 'models' / 'music' / 'musicgen'
)
AUDIOGEN_DIR = MODEL_PATHS.get('music', {}).get(
    'audiogen', settings.AI_MODELS_DIR / 'models' / 'music' / 'audiogen'
)
MINIMAX_MUSIC3_DIR = MODEL_PATHS.get('music', {}).get(
    'minimax_music3', settings.AI_MODELS_DIR / 'models' / 'music' / 'MiniMax-Music3'
)

Path(MUSICGEN_DIR).mkdir(parents=True, exist_ok=True)
Path(AUDIOGEN_DIR).mkdir(parents=True, exist_ok=True)
Path(MINIMAX_MUSIC3_DIR).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Anatomie déclarée (`composition`) — la forme AUDIOCRAFT, pas la forme transformers
# ---------------------------------------------------------------------------
# POURQUOI (2026-09-19, chantier VRAM décision A) : les dépôts `facebook/musicgen-*` et
# `audiogen-medium` portent DEUX formes des mêmes poids — la forme transformers
# (`pytorch_model.bin` ou `model*.safetensors`) et la forme audiocraft (`state_dict.bin` +
# `compression_state_dict.bin`). Sans déclaration, le poids par composant les additionne :
# mesuré, `musicgen-medium` sortait à 11,1 Go de fichiers pour 7,5 Go de modèle réel, et
# `musicgen-small` à 5,4 pour 2,2.
#
# Et c'est la forme AUDIOCRAFT que WAMA charge, la seule : `audiocraft_backend.py:199`
# (`MusicGen.get_pretrained`) et `:244` (`AudioGen.get_pretrained`) — la lib tire
# `compression_state_dict.bin` puis `state_dict.bin` (`audiocraft/models/loaders.py:71` et
# `:87`). Aucun `MusicgenForConditionalGeneration` n'existe dans WAMA : la forme transformers
# n'est JAMAIS touchée. *Deux formes dans un dépôt, une seule chargée — et le dépôt ne dit pas
# laquelle.*
#
# ⚠ Ce que la composition ne dit pas : l'encodeur de texte T5 (`t5-base` pour small, `t5-large`
# pour medium/melody/audiogen) est tiré par transformers dans le cache HF PARTAGÉ, pas dans le
# dépôt du modèle. C'est sa place (doctrine `AGENTS.md §sous-dépendances partagées`), mais il
# pèse dans la VRAM sans figurer ici.


def _audiocraft_composition() -> dict:
    """`composition` d'un modèle AudioCraft — mêmes deux fichiers pour toute la famille.

    Rôles nommés comme ceux de `minimax-music3` (`language_model`, `vocoder`…) : un même
    vocabulaire de rôles à travers le composer, pas un par moteur.
    """
    return {
        'components': [{'role': 'language_model', 'pattern': 'state_dict.bin'},
                       {'role': 'compression_model', 'pattern': 'compression_state_dict.bin'}],
        'runtime': {'engine': 'audiocraft'},
    }


# ---------------------------------------------------------------------------
# Model catalogue
# ---------------------------------------------------------------------------

COMPOSER_MODELS = {
    'musicgen-small': {
        'engine': 'audiocraft',
        # Releve 2026-09-19 sur la carte HF : state_dict 0,78 Go + compression 0,22 = 1,0 Go (le depot en porte 5,4).
        'composition': _audiocraft_composition(),
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
        'engine': 'audiocraft',
        # Releve 2026-09-19 sur la carte HF : state_dict 3,43 Go + compression 0,22 = 3,6 Go (le depot en porte 11,1).
        'composition': _audiocraft_composition(),
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
        'engine': 'audiocraft',
        # Releve 2026-09-19 sur la carte HF : state_dict 2,58 Go + compression 0,22 = 2,8 Go (le depot en porte 8,6).
        'composition': _audiocraft_composition(),
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
    'minimax-music3': {
        'hf_id': 'audio-cpp/MiniMax-Music3-GGUF',
        # Discriminateur de MOTEUR (2026-08-27) : 'audiocpp' = binaire audio.cpp en
        # sous-processus (composants GGUF déclarés par le manifeste, AIModel.composition).
        # Les entrées sans 'backend' restent sur AudioCraft — défaut historique.
        'backend': 'audiocpp',
        'type': 'music',
        'vram_gb': 13,
        'description': 'MiniMax-Music3 — chansons complètes avec paroles chantées (Q8)',
        'description_long': "MiniMax-Music3 (MiniMax, package GGUF Q8 via audio.cpp) : "
                            "génération de CHANSONS complètes — voix chantées, paroles avec "
                            "tags [verse]/[chorus], structure longue (jusqu'à 5 min). "
                            "Complémentaire de MusicGen (instrumental court). Le prompt "
                            "attendu est riche : description globale + voix + arrangement, "
                            "et les paroles dans des sections taguées ; sans tag de paroles, "
                            "la génération part en instrumental.",
        'max_duration': 300,
        'sample_rate': 32000,
        'cache_dir': MINIMAX_MUSIC3_DIR,
        # Estimations PROVISOIRES (aucune mesure locale encore — l'ETA auto-apprenant
        # affinera dès les premières générations, cf. eta_estimator).
        'gen_factor': 6.0,
        'overhead_s': 120,
    },
    'audiogen-medium': {
        'engine': 'audiocraft',
        # Releve 2026-09-19 : state_dict 3,43 Go + compression 0,22 = 3,65 Go, et ce depot ne
        # porte QUE la forme audiocraft — il n'y a rien a ecarter ici. La composition n'y sert
        # donc pas a corriger un poids, mais a dire les deux composants et leur moteur.
        'composition': _audiocraft_composition(),
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


def clamp_duration(value, model_id=None):
    """Durée bornée par la SOURCE UNIQUE = le schéma `params.py` (via `coerce_params`), plafonnée
    par le `max_duration` du modèle si `model_id` est connu. Remplace les clamps hardcodés
    `max(10, min(600, …))` (cf. PROJECT_STATUS §21bis). Le cap modèle ne s'applique qu'au moment où
    le vrai modèle est résolu (pas pour les pseudo-modèles `auto-*` ni au dépôt batch)."""
    from wama.common.utils.param_schema import coerce_params
    from wama.composer.params import PARAMS
    caps = {}
    if model_id and model_id in COMPOSER_MODELS:
        md = COMPOSER_MODELS[model_id].get('max_duration')
        if md:
            caps['duration'] = md
    return coerce_params(PARAMS, {'duration': value}, caps=caps).get('duration', value)


def estimate_seconds(model_id: str, duration: float) -> int:
    """
    Estimate generation time in seconds (warm GPU, RTX 4090).
    Formula: duration * gen_factor + overhead_s
    Note: first-ever run adds ~30-60s for model download.
    """
    cfg = COMPOSER_MODELS.get(model_id, {})
    return max(5, int(duration * cfg.get('gen_factor', 1.5) + cfg.get('overhead_s', 15)))
