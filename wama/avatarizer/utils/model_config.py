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

# (Le CODE vendorisé ne vit plus sous l'app : `settings.BACKEND_VENDOR_DIR`, lu par les backends
# communs. Les `MUSETALK_DIR`/`CODEFORMER_DIR` qui pointaient encore ici sur `APP_DIR/…` n'avaient
# plus aucun lecteur ; retirés le 2026-10-11.)


def _hub(repo, revision, file):
    return {'source': 'huggingface', 'repo': repo, 'revision': revision, 'file': file}


_MUSETALK_REV = '2bcb936e2fddb4d86db4c62fd45b387d0c061571'      # TMElyralab/MuseTalk
_SD_VAE_REV = '31f26fdeee1355a5c34592e401dd41e45d25a493'        # stabilityai/sd-vae-ft-mse
_WHISPER_REV = '169d4a4341b33bc18d8881c4b69c2e104e1cc0af'       # openai/whisper-tiny
_DWPOSE_REV = '1a7144101628d69ee7a3768d1ee3a094070dc388'        # yzd-v/DWPose

#: Les POIDS que l'inférence de MuseTalk v1.5 LIT — DÉCLARÉS (2026-10-11), sous
#: `MUSETALK_MODELS_DIR`, chacun avec son ORIGINE (pilote `files` de la route d'installation).
#: Relevés dans le code vendorisé : `scripts/inference.py` (unet, sa config, whisper),
#: `musetalk/utils/utils.py` (VAE), `preprocessing.py` (DWPose ; S3FD par `face_detection`),
#: `face_parsing/__init__.py` (BiSeNet et sa dorsale). Le code les atteint par le lien
#: `vendor/musetalk/models` et par `TORCH_HOME` (S3FD), que le backend pose
#: (`musetalk_backend._ensure_models_link`, `MUSETALK_TORCH_HOME`).
#: Origines, décision de Fabien (11/10) — la version OFFICIELLE quand elle existe :
#:   • quatre dépôts du Hub, figés à leur commit ; tailles et empreintes du Hub = fichiers en service ;
#:   • `resnet18-5c106cde.pth` : download.pytorch.org (torchvision) ;
#:   • `s3fd-619a316812.pth` : le site de l'auteur de face-alignment, l'adresse que la lib emploie ;
#:     pour ces deux-là, les 8-10 premiers caractères de l'empreinte SONT dans le nom (convention
#:     torch.hub) et concordent avec les octets mesurés ;
#:   • `79999_iter.pth` (BiSeNet, zllrunning/face-parsing.PyTorch) : l'officiel n'est que sur
#:     Google Drive, qui n'est pas une adresse de fichier stable — un MIROIR du Hub, accepté à
#:     l'empreinte des octets en service depuis février (une vingtaine de dépôts servent les mêmes).
#: ⚠ HORS de la liste : `syncnet/latentsync_syncnet.pt` (1,4 Go, ByteDance/LatentSync) — lu par
#: l'ENTRAÎNEMENT seul (`train.py`, perte de synchronisation), jamais par l'inférence. Retiré
#: du disque le 2026-10-12 (décision de Fabien) ; le déclarer ici le jour d'un affinage.
MUSETALK_FILES = [
    {'path': 'musetalkV15/unet.pth', 'size': 3400074924,
     'sha256': '7ebf6c98c181e20838e4c0054e96e944ac60d5d692cc01db42839fe11b787007',
     'origin': _hub('TMElyralab/MuseTalk', _MUSETALK_REV, 'musetalkV15/unet.pth')},
    {'path': 'musetalkV15/musetalk.json', 'size': 748,
     'sha256': '5b6923aee04d71692e0e9846c471e0a4ea07a4f686d39545e472bd4ba17e1b47',
     'origin': _hub('TMElyralab/MuseTalk', _MUSETALK_REV, 'musetalkV15/musetalk.json')},
    {'path': 'sd-vae/config.json', 'size': 547,
     'sha256': '92d3dfb746fca211a2c9e019e285f8597412211728dce3c5bcf4eda0f2d62e7e',
     'origin': _hub('stabilityai/sd-vae-ft-mse', _SD_VAE_REV, 'config.json')},
    {'path': 'sd-vae/diffusion_pytorch_model.bin', 'size': 334707217,
     'sha256': '1b4889b6b1d4ce7ae320a02dedaeff1780ad77d415ea0d744b476155c6377ddc',
     'origin': _hub('stabilityai/sd-vae-ft-mse', _SD_VAE_REV, 'diffusion_pytorch_model.bin')},
    {'path': 'whisper/config.json', 'size': 1983,
     'sha256': 'ffdccec4f3211f4c63310f2b7098f309fe70f3952cedc5e4d11e43f5b2379b98',
     'origin': _hub('openai/whisper-tiny', _WHISPER_REV, 'config.json')},
    {'path': 'whisper/preprocessor_config.json', 'size': 184990,
     'sha256': '9b5cd03a36fbb8a627c64d98a5b5b126ead95a77720723944487311f0110b666',
     'origin': _hub('openai/whisper-tiny', _WHISPER_REV, 'preprocessor_config.json')},
    {'path': 'whisper/pytorch_model.bin', 'size': 151095027,
     'sha256': '9607f98a2b22d9e229ae43c52ecea79dcede9e0c5cfae67e8da6eda86d8aac1d',
     'origin': _hub('openai/whisper-tiny', _WHISPER_REV, 'pytorch_model.bin')},
    {'path': 'dwpose/dw-ll_ucoco_384.pth', 'size': 406878486,
     'sha256': '0d9408b13cd863c4e95a149dd31232f88f2a12aa6cf8964ed74d7d97748c7a07',
     'origin': _hub('yzd-v/DWPose', _DWPOSE_REV, 'dw-ll_ucoco_384.pth')},
    {'path': 'face-parse-bisent/79999_iter.pth', 'size': 53289463,
     'sha256': '468e13ca13a9b43cc0881a9f99083a430e9c0a38abd935431d1c28ee94b26567',
     'origin': _hub('camenduru/MuseTalk', '5cfe77e50e1dc10ac599e5340d610d69a5086af2',
                    'face-parse-bisent/79999_iter.pth')},
    {'path': 'face-parse-bisent/resnet18-5c106cde.pth', 'size': 46827520,
     'sha256': '5c106cde386e87d4033832f2996f5493238eda96ccf559d1d62760c4de0613f8',
     'origin': {'source': 'pytorch_download', 'file': 'models/resnet18-5c106cde.pth'}},
    {'path': 'torch/hub/checkpoints/s3fd-619a316812.pth', 'size': 89843225,
     'sha256': '619a31681264d3f7f7fc7a16a42cbbe8b23f31a256f75a366e5a1bcd59b33543',
     'origin': {'source': 'face_alignment', 'file': 's3fd-619a316812.pth'}},
]

#: Les POIDS de CodeFormer — DÉCLARÉS (2026-10-10) : les quatre fichiers que le code vendorisé lit
#: (`inference_codeformer.py`, `facelib/detection`, `facelib/parsing`), tous publiés par UNE
#: version GitHub, rangés sous `CODEFORMER_MODELS_DIR/<sous-dossier>/` — la disposition que le
#: backend relie par symlinks depuis `codeformer/weights/`. Taille et empreinte MESURÉES le 10/10
#: sur les fichiers installés (qui ont servi aux traitements réussis) ; les tailles égalent celles
#: de la version, qui ne publie pas d'empreinte. Lue par la découverte (installation par le
#: catalogue : bouton « Installer », `pull_model avatarizer:codeformer`, `install_requires
#: avatarizer`). Les sous-dossiers que le backend relie en dérivent (garde :
#: `avatarizer/tests_codeformer_weights`). Chaque fichier nomme son ORIGINE depuis le 2026-10-11
#: (pilote `files` : la forme commune à toutes les sources).
CODEFORMER_RELEASE = 'sczhou/CodeFormer:v0.1.0'


def _codeformer_file(path, size, sha256):
    return {'path': path, 'size': size, 'sha256': sha256,
            'origin': {'source': 'github', 'release': CODEFORMER_RELEASE,
                       'file': path.rsplit('/', 1)[-1]}}


CODEFORMER_FILES = [
    _codeformer_file('CodeFormer/codeformer.pth', 376637898,
                     '1009e537e0c2a07d4cabce6355f53cb66767cd4b4297ec7a4a64ca4b8a5684b7'),
    _codeformer_file('facelib/detection_Resnet50_Final.pth', 109497761,
                     '6d1de9c2944f2ccddca5f5e010ea5ae64a39845a86311af6fdf30841b0a5a16d'),
    _codeformer_file('facelib/parsing_parsenet.pth', 85331193,
                     '3d558d8d0e42c20224f13cf5a29c79eba2d59913419f945545d8cf7b72920de2'),
    _codeformer_file('realesrgan/RealESRGAN_x2plus.pth', 67061725,
                     '49fafd45f8fd7aa8d31ab2a22d14d91b536c34494a5cfe31eb5d89c2fa266abb'),
]

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
        'files': MUSETALK_FILES,
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
        'files': CODEFORMER_FILES,
    },
}
