"""
CodeFormer Backend — restauration de visage (option qualite superieure)

Backend hors process : le modele tourne dans un SOUS-PROCESSUS (script du depot vendore),
pas dans l'interpreteur Celery — load()/unload() ne retiennent donc rien en memoire ;
la VRAM est declaree au gouverneur pour la duree de process() (vram_reservation).
Code deplace verbatim depuis workers.py (port F4, 2026-07-31) : le worker orchestre,
le backend execute.
"""

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

from wama.common.backends.base import BaseModelBackend
from wama.common.services.resource_governor import vram_reservation
from wama.avatarizer.utils.model_config import (
    CODEFORMER_DIR,
    CODEFORMER_MODELS_DIR,
    CODEFORMER_VRAM_GB,
    CODEFORMER_WEIGHTS_SUBDIRS,
)

logger = logging.getLogger(__name__)


def _ensure_codeformer_weights_in_ai_models() -> None:
    """
    Redirige codeformer/weights/<subdir>/ vers AI-models/models/lipsync/codeformer/<subdir>/
    via des symlinks, en déplaçant les fichiers déjà téléchargés si nécessaire.

    Appelé une seule fois au premier lancement de CodeFormer — idempotent.
    """
    weights_dir = CODEFORMER_DIR / 'weights'
    if not weights_dir.exists():
        return

    CODEFORMER_MODELS_DIR.mkdir(parents=True, exist_ok=True)

    for subdir in CODEFORMER_WEIGHTS_SUBDIRS:
        src = weights_dir / subdir          # ex: codeformer/weights/CodeFormer/
        dst = CODEFORMER_MODELS_DIR / subdir  # ex: AI-models/.../codeformer/CodeFormer/
        dst.mkdir(parents=True, exist_ok=True)

        if src.is_symlink():
            continue  # déjà redirigé

        if src.is_dir():
            # Déplacer les .pth existants vers AI-models/
            for f in src.iterdir():
                if f.name.startswith('.'):
                    continue  # .gitkeep etc.
                target = dst / f.name
                if not target.exists():
                    shutil.move(str(f), str(target))
                    logger.info(f"[avatarizer] CodeFormer weights déplacé : {f.name} → AI-models/")
            # Supprimer le répertoire vide et créer un symlink
            try:
                src.rmdir()
            except OSError:
                # Non vide (gitkeep) — supprimer les gitkeep puis réessayer
                for f in src.iterdir():
                    f.unlink()
                src.rmdir()
            src.symlink_to(dst.resolve())
            logger.info(f"[avatarizer] CodeFormer weights symlink créé : {src} → {dst}")
        else:
            src.symlink_to(dst.resolve())


def _run_codeformer(video_path: str, output_dir: str) -> str:
    """
    Améliore la qualité faciale de la vidéo avec CodeFormer.
    Si CodeFormer n'est pas installé ou échoue, renvoie le chemin d'origine.
    """
    if not CODEFORMER_DIR.exists():
        logger.warning(f"[avatarizer] CodeFormer absent ({CODEFORMER_DIR}) — amélioration ignorée.")
        return video_path

    _ensure_codeformer_weights_in_ai_models()

    cf_out = Path(output_dir) / 'codeformer_out'
    cf_out.mkdir(parents=True, exist_ok=True)

    try:
        # Même raison que MuseTalk : sous-processus GPU, empreinte déclarée le temps de l'appel.
        with vram_reservation(f"avatarizer.codeformer:{os.getpid()}", CODEFORMER_VRAM_GB):
            result = subprocess.run(
                [
                    sys.executable, 'inference_codeformer.py',
                    '-i', str(Path(video_path).resolve()),
                    '-o', str(cf_out.resolve()),
                    '--face_upsample',
                    '-w', '0.7',   # fidelity weight : 0 = amélioration max, 1 = fidélité max
                    '-s', '2',     # upscale ×2
                ],
                cwd=str(CODEFORMER_DIR),
                capture_output=True,
                text=True,
                timeout=1800,   # 30 min — chargement modèle + traitement vidéo longue
            )
    except subprocess.TimeoutExpired:
        logger.warning("[avatarizer] CodeFormer timeout (30 min) — on garde la vidéo MuseTalk.")
        return video_path

    if result.returncode != 0:
        logger.warning(f"[avatarizer] CodeFormer échoué — on garde la vidéo MuseTalk.\n{result.stderr[-300:]}")
        return video_path

    # CodeFormer écrit dans results/final_results/ ou directement dans -o
    video_name = Path(video_path).name
    for candidate in [
        cf_out / 'final_results' / video_name,
        cf_out / video_name,
    ]:
        if candidate.exists():
            return str(candidate)

    mp4_files = sorted(cf_out.rglob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True)
    return str(mp4_files[0]) if mp4_files else video_path


class CodeFormerBackend(BaseModelBackend):
    """Contrat commun autour du sous-processus CodeFormer (inference_codeformer.py vendore)."""

    REQUIRED_PACKAGES = ['basicsr', 'facexlib', 'realesrgan']
    recommended_vram_gb = CODEFORMER_VRAM_GB
    description = "CodeFormer — restauration/nettete du visage apres MuseTalk (use_enhancer)."
    _warm = False

    @classmethod
    def is_available(cls) -> bool:
        return (CODEFORMER_DIR / 'inference_codeformer.py').exists()

    def load(self, model=None) -> bool:
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        self._warm = False

    def process(self, *args, **kwargs):
        return _run_codeformer(*args, **kwargs)
