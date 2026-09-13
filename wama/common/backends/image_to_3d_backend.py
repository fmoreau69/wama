"""TripoSR — reconstruction image → objet 3D (GLB). AUCUN ORM. ROADMAP §17ter, trou 4.

Le CODE du modèle est vendorisé (`wama/common/backends/vendor/triposr/`, `tools/setup_triposr.sh`
— clone à commit épinglé + deux patches : marching cubes sur PyMCubes au lieu de torchmcubes,
qui exige une extension CUDA à compiler ; `rembg` importé paresseusement), comme MuseTalk et
CodeFormer. Les POIDS (`config.yaml` + `model.ckpt`, `stabilityai/TripoSR`, MIT) sont tirés par
`hf_hub_download(cache_dir=MODEL_DIR)` au premier chargement — jamais de mutation
d'environnement (AGENTS.md §Ajout d'un nouveau modèle AI, ROADMAP §5b).

⚠ ÉCRIT LE 2026-09-13, NON EXÉCUTÉ : le premier run GPU se fait AVEC Fabien (règle crashs
hôte). Ce qui est attesté sans GPU : le contrat (flags, moteur, résolution par la clé de
catalogue), la spec de fonction, le câblage studio. Ce qui ne l'est pas : l'inférence — et en
particulier l'ORIENTATION des faces après le rabattement sur PyMCubes (la convention d'axes de
torchmcubes est reproduite par la permutation `[2, 1, 0]` du code amont ; à vérifier sur le
premier maillage, cf. `tools/setup_triposr.sh`).

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
MODEL_DIR = Path(settings.MODEL_PATHS.get('vision', {}).get('triposr')
                 or settings.AI_MODELS_DIR / 'models' / 'vision' / 'triposr')
#: Racine DÉCLARÉE du code tiers (même que setup_avatarizer.sh : settings.BACKEND_VENDOR_DIR
#: quand il existe, sinon le dossier `vendor/` de ce paquet).
VENDOR_DIR = Path(getattr(settings, 'BACKEND_VENDOR_DIR', None)
                  or Path(__file__).resolve().parent / 'vendor') / 'triposr'


def _vendored_tsr():
    """Le paquet `tsr` vendorisé, importé depuis SON dossier — jamais installé dans le venv."""
    import importlib
    import sys
    if str(VENDOR_DIR) not in sys.path:
        sys.path.insert(0, str(VENDOR_DIR))
    return importlib.import_module('tsr.system')


class TripoSRBackend(BaseModelBackend):
    """Image (RGB/RGBA, fond retiré de préférence) → maillage GLB coloré par sommet."""

    ENGINE = 'triposr'
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

    # ── Disponibilité : le code vendorisé fait partie de la réponse ─────────────────────
    @classmethod
    def missing_packages(cls):
        manques = super().missing_packages()
        if not (VENDOR_DIR / 'tsr' / 'system.py').is_file():
            manques.append('vendor:triposr (tools/setup_triposr.sh)')
        return manques

    # ── Cycle de vie ───────────────────────────────────────────────────────────────────
    def _weights_dir(self) -> Path:
        """Dossier LOCAL des poids : téléchargés une fois sous `MODEL_DIR` (cache_dir), puis
        rendus par chemin pour que `TSR.from_pretrained` prenne sa branche `isdir`."""
        from huggingface_hub import hf_hub_download
        MODEL_DIR.mkdir(parents=True, exist_ok=True)
        cfg = hf_hub_download(HF_REPO, 'config.yaml', cache_dir=str(MODEL_DIR))
        hf_hub_download(HF_REPO, 'model.ckpt', cache_dir=str(MODEL_DIR))
        return Path(cfg).parent

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
