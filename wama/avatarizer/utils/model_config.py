"""
Configuration des modèles de l'Avatarizer — MuseTalk (lip-sync) + CodeFormer (restauration).

Règle AGENTS.md « Ajout d'un nouveau modèle AI » : les chemins viennent de
settings.MODEL_PATHS['lipsync'] (fallback AI-models/models/lipsync/) ; le cache HF des
sous-processus MuseTalk (Whisper/DWPose) est isolé sous le dossier du modèle.

CodeFormer = option « qualité supérieure » déclenchable par l'utilisateur (use_enhancer).
MuseTalk = v1.5 seule (la v1.0 est retirée le 2026-09-30 : son moteur exécutait toujours la
v1.5 — REMOVAL_LEDGER). TalkingHead = avatar 3D riggé, sans poids. Découverte catalogue :
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

#: Les POIDS de CodeFormer — DÉCLARÉS (2026-10-10) : les quatre fichiers que le code vendorisé lit
#: (`inference_codeformer.py`, `facelib/detection`, `facelib/parsing`), tous publiés par UNE
#: version GitHub, rangés sous `CODEFORMER_MODELS_DIR/<sous-dossier>/` — la disposition que le
#: backend relie par symlinks depuis `codeformer/weights/`. Taille et empreinte MESURÉES le 10/10
#: sur les fichiers installés (qui ont servi aux traitements réussis) ; les tailles égalent celles
#: de la version, qui ne publie pas d'empreinte. Lue par la découverte (installation par le
#: catalogue : bouton « Installer », `pull_model avatarizer:codeformer`, `install_requires
#: avatarizer`). Les sous-dossiers que le backend relie en dérivent (garde :
#: `avatarizer/tests_codeformer_weights`).
CODEFORMER_RELEASE = {
    'ref': 'sczhou/CodeFormer:v0.1.0',
    'files': [
        {'path': 'CodeFormer/codeformer.pth', 'size': 376637898,
         'sha256': '1009e537e0c2a07d4cabce6355f53cb66767cd4b4297ec7a4a64ca4b8a5684b7'},
        {'path': 'facelib/detection_Resnet50_Final.pth', 'size': 109497761,
         'sha256': '6d1de9c2944f2ccddca5f5e010ea5ae64a39845a86311af6fdf30841b0a5a16d'},
        {'path': 'facelib/parsing_parsenet.pth', 'size': 85331193,
         'sha256': '3d558d8d0e42c20224f13cf5a29c79eba2d59913419f945545d8cf7b72920de2'},
        {'path': 'realesrgan/RealESRGAN_x2plus.pth', 'size': 67061725,
         'sha256': '49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb'},
    ],
}

# Empreintes VRAM des SOUS-PROCESSUS GPU, déclarées au gouverneur le temps de leur exécution.
# ⚠️ ESTIMATIONS NON MESURÉES (cf. ancien workers.py) — à confronter au réel ; le catalogue
# AIModel déclare 4.0 pour MuseTalk seul (UNet), ici on réserve le pipeline complet.
MUSETALK_VRAM_GB = 8.0
CODEFORMER_VRAM_GB = 3.0

#: Le TIRAGE du modèle d'animation (2026-09-30) se fait parmi les modèles de l'avatarizer qui
#: acceptent les entrées FOURNIES (`resolve_model_choice`, `available_inputs`/`consumes`) : une
#: photo ne laisse que MuseTalk, un GLB que TalkingHead ; entre deux modèles d'une même entrée,
#: le tirage commun tranche (VRAM, curseur). Repli par NATURE d'avatar si le catalogue ne propose
#: rien (première installation).
#: En CLÉS de catalogue depuis la route F4b ⑤ (2026-10-07) : c'est l'espace du select et du tirage.
ANIMATION_FALLBACK = {'work_object3d': 'avatarizer:talkinghead',
                      'work_image': 'avatarizer:musetalk-v1.5'}

#: DOMAINE du modèle d'animation — UNE déclaration, que le select (`params.py`, `options_query`)
#: et le tirage du worker lisent. Par TÂCHE (route F4b, étape ⑤ — 2026-10-07), jamais par source :
#: un modèle `lip-sync` installé depuis le model manager doit y entrer. Mesuré avant de basculer :
#: le domaine rend les deux mêmes modèles que l'ancien (`source='avatarizer'`), en clés entières.
ANIMATION_SPEC = {'task': 'lip-sync'}

AVATARIZER_MODELS = {
    'musetalk-v1.5': {
        'model_id': 'musetalk-v1.5',
        'engine': 'musetalk',
        'hf_id': 'TMElyralab/MuseTalk',
        'type': 'lipsync',
        'vram_gb': MUSETALK_VRAM_GB,
        'version': 'v15',
        'description': "MuseTalk V1.5 — lip-sync temps quasi réel, meilleure fidélité labiale.",
    },
    # Avatar 3D riggé rendu en vidéo (2026-09-30) — PAS de poids : le moteur est TalkingHead
    # (vendorisé sous `static/vendors/`), l'« objet » animé est le GLB fourni par l'utilisateur.
    # Ce qu'il EXIGE de ce GLB se déclare en attributs de la nature `object3d`, mesurés dans le
    # fichier (`media_probe`) : squelette + visage ARKit requis, visèmes Oculus souhaités.
    'talkinghead': {
        'model_id': 'talkinghead',
        'engine': 'talkinghead',
        'repo': 'met4citizen/TalkingHead',
        'license': 'MIT',
        'type': 'lipsync',
        'vram_gb': 0.2,          # mesuré le 2026-09-30 (talkinghead_backend.recommended_vram_gb)
        # Langues ayant un module de visèmes (wama-avatar.js) ; les autres parlent en visèmes anglais.
        'languages': ['fr', 'en', 'de', 'fi', 'lt'],
        'description': "TalkingHead — avatar 3D riggé (GLB) animé par l'audio, rendu image par image ; "
                       "rapide, sans modèle génératif, non photoréaliste.",
    },
    'codeformer': {
        'model_id': 'codeformer',
        'hf_id': 'sczhou/CodeFormer',
        'type': 'face-restoration',
        'vram_gb': CODEFORMER_VRAM_GB,
        'description': "CodeFormer — restauration de visage (option qualité supérieure, use_enhancer).",
        'release': CODEFORMER_RELEASE,
    },
}
