"""
Configuration des modèles de l'Avatarizer — MuseTalk (lip-sync) + CodeFormer (restauration).

Règle CLAUDE.md « Ajout d'un nouveau modèle AI » : les chemins viennent de
settings.MODEL_PATHS['lipsync'] (fallback AI-models/models/lipsync/) ; le cache HF des
sous-processus MuseTalk (Whisper/DWPose) est isolé sous le dossier du modèle.

CodeFormer = option « qualité supérieure » déclenchable par l'utilisateur (use_enhancer) ;
quality_mode v15/v10 sélectionne la version MuseTalk. Découverte catalogue :
model_registry._discover_avatarizer_models().
"""
from pathlib import Path

from django.conf import settings

_LIPSYNC = getattr(settings, 'MODEL_PATHS', {}).get('lipsync', {})

# Checkpoints dans AI-models/ (organisés par type, pas par application)
MUSETALK_MODELS_DIR = Path(_LIPSYNC.get(
    'musetalk', settings.AI_MODELS_DIR / 'models' / 'lipsync' / 'musetalk'))
CODEFORMER_MODELS_DIR = Path(_LIPSYNC.get(
    'codeformer', settings.AI_MODELS_DIR / 'models' / 'lipsync' / 'codeformer'))
for _d in (MUSETALK_MODELS_DIR, CODEFORMER_MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# Cache HF isolé pour les téléchargements du sous-processus MuseTalk (whisper, dwpose…)
MUSETALK_HF_CACHE = MUSETALK_MODELS_DIR / 'hf_cache'

# Dépôts vendorés IN-TREE (code, pas poids) — les backends lancent leurs scripts en sous-processus
APP_DIR = Path(__file__).resolve().parent.parent
MUSETALK_DIR = APP_DIR / 'musetalk'
CODEFORMER_DIR = APP_DIR / 'codeformer'

# Sous-dossiers weights/ de CodeFormer redirigés vers AI-models/ via symlinks
CODEFORMER_WEIGHTS_SUBDIRS = ['CodeFormer', 'facelib', 'realesrgan']

# Empreintes VRAM des SOUS-PROCESSUS GPU, déclarées au gouverneur le temps de leur exécution.
# ⚠️ ESTIMATIONS NON MESURÉES (cf. ancien workers.py) — à confronter au réel ; le catalogue
# AIModel déclare 4.0 pour MuseTalk seul (UNet), ici on réserve le pipeline complet.
MUSETALK_VRAM_GB = 8.0
CODEFORMER_VRAM_GB = 3.0

AVATARIZER_MODELS = {
    'musetalk-v1.5': {
        'model_id': 'musetalk-v1.5',
        'hf_id': 'TMElyralab/MuseTalk',
        'type': 'lipsync',
        'vram_gb': MUSETALK_VRAM_GB,
        'version': 'v15',
        'description': "MuseTalk V1.5 — lip-sync temps quasi réel, meilleure fidélité labiale.",
    },
    'musetalk-v1.0': {
        'model_id': 'musetalk-v1.0',
        'hf_id': 'TMElyralab/MuseTalk',
        'type': 'lipsync',
        'vram_gb': MUSETALK_VRAM_GB,
        'version': 'v10',
        'description': "MuseTalk V1.0 — version historique, fallback si les poids v1.5 manquent.",
    },
    'codeformer': {
        'model_id': 'codeformer',
        'hf_id': 'sczhou/CodeFormer',
        'type': 'face-restoration',
        'vram_gb': CODEFORMER_VRAM_GB,
        'description': "CodeFormer — restauration de visage (option qualité supérieure, use_enhancer).",
    },
}
