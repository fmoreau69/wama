"""TripoSR — reconstruction image → objet 3D (GLB). AUCUN ORM. ROADMAP §17ter, trou 4.

Le CODE du modèle est vendorisé (`wama/common/backends/vendor/triposr/`, route `library` voie
vendor : `manage.py install_library triposr`, manifeste `manifests/libraries/triposr.json` —
clone à commit épinglé + le correctif `patches/triposr_pymcubes_lazy_rembg.diff` : marching
cubes sur PyMCubes au lieu de torchmcubes, qui exige une extension CUDA à compiler ; `rembg`
importé paresseusement), comme MuseTalk et CodeFormer. Les POIDS (`config.yaml` + `model.ckpt`,
`stabilityai/TripoSR`, MIT) sont DÉCLARÉS (`TRIPOSR_FILES`) et installés par le pilote `files` du
model manager (2026-10-16, règle « librairies et modèles par la route ») — ils étaient tirés par
`hf_hub_download` au premier chargement, à côté de la route. Ce backend ne télécharge plus rien :
la tâche qui l'emploie fait installer le modèle et attend (`model_readiness.ensure_installed`).

⚠ ÉCRIT LE 2026-09-13, NON EXÉCUTÉ : le premier run GPU se fait AVEC Fabien (règle crashs
hôte). Ce qui est attesté sans GPU : le contrat (flags, moteur, résolution par la clé de
catalogue), la spec de fonction, le câblage studio. Ce qui ne l'est pas : l'inférence — et en
particulier l'ORIENTATION des faces après le rabattement sur PyMCubes (la convention d'axes de
torchmcubes est reproduite par la permutation `[2, 1, 0]` du code amont ; à vérifier sur le
premier maillage, cf. `patches/triposr_pymcubes_lazy_rembg.diff`).

⚠ Reconstruction PLAUSIBLE, pas métrique (§17ter) : les faces occultées sont HALLUCINÉES.
Déclaré au catalogue (`capabilities.reconstruction = 'plausible'`), pas en mémoire humaine.
"""
import logging
import os
from pathlib import Path
from typing import Optional

from django.conf import settings

from .base import BaseModelBackend

logger = logging.getLogger(__name__)

HF_REPO = 'stabilityai/TripoSR'
MODEL_KEY = 'huggingface:triposr'
MODEL_DIR = Path(settings.MODEL_PATHS.get('vision', {}).get('triposr')
                 or settings.AI_MODELS_DIR / 'models' / 'vision' / 'triposr')
#: Le commit du dépôt du Hub dont les fichiers sont tirés (révision FIGÉE, pilote `files`).
HF_REVISION = '5b521936b01fbe1890f6f9baed0254ab6351c04a'
#: Les fichiers DÉCLARÉS (forme du pilote `files`). `model.ckpt` : taille et empreinte PUBLIÉES par
#: le Hub (LFS) ; `config.yaml` (hors LFS, sans empreinte publiée) : MESURÉE le 2026-10-16 sur le
#: fichier de ce commit, tiré dans un dossier jetable.
TRIPOSR_FILES = [
    {'path': 'config.yaml', 'size': 987,
     'sha256': '74ca708ce086bf68e97709ea6b3d91f14717921c04691e84043f0eb8fcc68e62',
     'origin': {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION,
                'file': 'config.yaml'}},
    {'path': 'model.ckpt', 'size': 1677246742,
     'sha256': '429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee',
     'origin': {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION,
                'file': 'model.ckpt'}},
]
#: Racine DÉCLARÉE du code tiers (settings.BACKEND_VENDOR_DIR quand il existe, sinon le dossier
#: `vendor/` de ce paquet).
VENDOR_DIR = Path(getattr(settings, 'BACKEND_VENDOR_DIR', None)
                  or Path(__file__).resolve().parent / 'vendor') / 'triposr'


def _vendored_tsr():
    """Le paquet `tsr` vendorisé, importé depuis SON dossier — jamais installé dans le venv
    (geste commun `BaseModelBackend.import_vendored`)."""
    return TripoSRBackend.import_vendored('tsr.system')


class TripoSRBackend(BaseModelBackend):
    """Image (RGB/RGBA, fond retiré de préférence) → maillage GLB coloré par sommet."""

    ENGINE = 'triposr'
    #: Code vendorisé (`manifests/libraries/triposr.json`) : son absence entre dans
    #: `missing_packages()` par le contrat commun.
    VENDORED = True
    SUPPORTED_MODELS = ('triposr',)
    # `mcubes` = PyMCubes (wheel), remplace `torchmcubes` (extension CUDA) dans le code vendorisé.
    REQUIRED_PACKAGES = ['torch', 'trimesh', 'mcubes', 'omegaconf', 'einops', 'huggingface_hub']
    PIP_PACKAGES = ['trimesh==5.1.0', 'PyMCubes==0.1.6']
    recommended_vram_gb = 6.0
    description = ('TripoSR (Stability AI + Tripo, MIT) — reconstruction mono-image → maillage 3D '
                   'en une passe (LRM) ; plausible, non métrique.')

    def __init__(self):
        self._model = None
        self._device = 'cpu'

    # ── Cycle de vie ───────────────────────────────────────────────────────────────────
    def _weights_dir(self) -> Path:
        """Dossier LOCAL des poids déclarés, rendu par chemin pour que `TSR.from_pretrained`
        prenne sa branche `isdir`. Un fichier absent se dit — l'installation est celle du model
        manager, jamais ce backend."""
        missing = [f['path'] for f in TRIPOSR_FILES if not (MODEL_DIR / f['path']).exists()]
        if missing:
            raise RuntimeError(f"TripoSR : {', '.join(missing)} absent(s) de {MODEL_DIR} — installer "
                               f"« TripoSR » depuis le model manager (`pull_model {MODEL_KEY}`)")
        return MODEL_DIR

    def load(self, model: Optional[str] = None) -> bool:
        if self._model is not None:
            return True
        import torch
        tsr = _vendored_tsr()
        self._device = 'cuda' if torch.cuda.is_available() else 'cpu'
        weights = self._weights_dir()
        m = tsr.TSR.from_pretrained(str(weights), config_name='config.yaml', weight_name='model.ckpt')
        m.renderer.set_chunk_size(8192)
        m.to(self._device)
        self._model = m
        logger.info('[TripoSR] chargé sur %s depuis %s', self._device, weights)
        return True

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def unload(self) -> None:
        self._model = None
        try:
            import gc
            import torch
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    # ── Métier ─────────────────────────────────────────────────────────────────────────
    def process(self, image_path: str, output_path: str, resolution: int = 256,
                foreground_ratio: float = 0.85, remove_background: bool = False, **_ignored) -> str:
        """Écrit un GLB dans `output_path` et rend son chemin.

        `remove_background=True` exige `rembg` (optionnel, non installé par défaut) ; sans lui,
        l'image est prise telle quelle — une image DÉJÀ détourée (sortie du detector / SAM3,
        chaîne §17ter) est le cas nominal, et un fond uni fait l'affaire.
        """
        from PIL import Image
        import numpy as np
        import torch

        self.load()
        tsr_utils = __import__('tsr.utils', fromlist=['resize_foreground'])
        image = Image.open(image_path)
        if remove_background:
            image = tsr_utils.remove_background(image)          # rembg, paresseux (patch vendor)
        if image.mode == 'RGBA':
            image = tsr_utils.resize_foreground(image, foreground_ratio)
            arr = np.array(image).astype(np.float32) / 255.0
            arr = arr[:, :, :3] * arr[:, :, 3:4] + (1 - arr[:, :, 3:4]) * 0.5   # fond gris, comme run.py
            image = Image.fromarray((arr * 255.0).astype(np.uint8))
        else:
            image = image.convert('RGB')

        with torch.no_grad():
            scene_codes = self._model([image], device=self._device)
        meshes = self._model.extract_mesh(scene_codes, True, resolution=int(resolution))
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        meshes[0].export(output_path)                             # trimesh → GLB par l'extension
        return output_path
