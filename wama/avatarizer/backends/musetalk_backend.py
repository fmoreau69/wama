"""
MuseTalk Backend — generation d'avatar parlant (lip-sync)

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
    MUSETALK_DIR,
    MUSETALK_HF_CACHE,
    MUSETALK_MODELS_DIR,
    MUSETALK_VRAM_GB,
)

logger = logging.getLogger(__name__)


def _build_musetalk_env() -> dict:
    """Construit les variables d'environnement pour le subprocess MuseTalk."""
    env = os.environ.copy()
    # Ajouter musetalk/ au PYTHONPATH pour ses imports internes
    existing = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = f"{MUSETALK_DIR}:{existing}" if existing else str(MUSETALK_DIR)
    # Pointer vers les checkpoints si disponibles
    if MUSETALK_MODELS_DIR.exists():
        env['MUSETALK_MODELS_DIR'] = str(MUSETALK_MODELS_DIR)
    # Isolation du cache HF du SOUS-PROCESSUS (whisper/dwpose de MuseTalk) — regle CLAUDE.md :
    # jamais de telechargement dans le cache global par defaut.
    env['HF_HUB_CACHE'] = str(MUSETALK_HF_CACHE)
    env['HUGGINGFACE_HUB_CACHE'] = str(MUSETALK_HF_CACHE)
    return env


def _run_musetalk(image_path: str, audio_path: str, output_dir: str, bbox_shift: int = 0) -> str:
    """
    Exécute MuseTalk via subprocess.

    MuseTalk écrit ses résultats dans <result_dir>/v15/*.mp4.
    On passe --result_dir pointant vers le dossier du job pour éviter tout
    déplacement de fichier et pour que les runs concurrents ne se mélangent pas.

    Retourne le chemin de la vidéo MP4 générée.
    """
    if not MUSETALK_DIR.exists():
        raise RuntimeError(
            f"MuseTalk introuvable dans {MUSETALK_DIR}.\n"
            "Lancez d'abord : bash wama/avatarizer/setup_avatarizer.sh"
        )

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Config YAML minimal (output_vid_dir ignoré par inference.py ; on utilise --result_dir)
    config = {
        'task_0': {
            'video_path': str(Path(image_path).resolve()),
            'audio_path': str(Path(audio_path).resolve()),
            'bbox_shift': int(bbox_shift),
        }
    }
    config_path = output_dir / 'musetalk_config.yaml'
    with open(config_path, 'w') as f:
        yaml.dump(config, f, default_flow_style=False, allow_unicode=True)

    logger.info(f"[avatarizer] MuseTalk config : {config_path}")

    # La VRAM de MuseTalk est consommée par un SOUS-PROCESSUS : invisible du gouverneur, qui
    # croirait la VRAM libre et laisserait une autre tâche GPU démarrer par-dessus. On la
    # déclare donc pour la durée de l'appel (cf. `vram_reservation`, PROJECT_STATUS §0).
    with vram_reservation(f"avatarizer.musetalk:{os.getpid()}", MUSETALK_VRAM_GB):
        result = subprocess.run(
            [
                sys.executable, '-W', 'ignore::UserWarning',
                '-m', 'scripts.inference',
                '--inference_config', str(config_path),
                '--version', 'v15',
                '--unet_model_path', './models/musetalkV15/unet.pth',
                '--unet_config', './models/musetalkV15/musetalk.json',
                '--result_dir', str(output_dir),   # MuseTalk écrit dans <output_dir>/v15/
            ],
            cwd=str(MUSETALK_DIR),
            env=_build_musetalk_env(),
            capture_output=True,
            text=True,
            timeout=600,
        )

    # Toujours capturer la sortie pour le diagnostic
    musetalk_output = ((result.stdout or '') + (result.stderr or '')).strip()

    if result.returncode != 0:
        raise RuntimeError(
            f"MuseTalk a échoué (code {result.returncode}) :\n{musetalk_output[-3000:]}"
        )

    # MuseTalk écrit dans <output_dir>/v15/<image_stem>_<audio_stem>.mp4
    # (inference.py utilise output_basename = f"{input_basename}_{audio_basename}")
    v15_dir = output_dir / 'v15'
    if v15_dir.exists():
        # Exclure les fichiers temp_ (vidéo sans audio, supprimés normalement)
        mp4_files = sorted(
            [p for p in v15_dir.glob('*.mp4') if not p.name.startswith('temp_')],
            key=lambda p: p.stat().st_mtime, reverse=True
        )
        if mp4_files:
            return str(mp4_files[0])

    # Fallback : MP4 directement dans output_dir
    mp4_files = sorted(
        output_dir.glob('*.mp4'), key=lambda p: p.stat().st_mtime, reverse=True
    )
    if mp4_files:
        return str(mp4_files[0])

    # Rien trouvé — analyser la sortie pour un message utilisateur clair
    if 'NO FACE DETECTED' in musetalk_output or 'division by zero' in musetalk_output:
        raise RuntimeError(
            "Aucun visage détecté dans l'image avatar.\n"
            "MuseTalk requiert une photo de face avec un visage bien visible et centré.\n"
            "Conseil : utilisez un portrait frontal, sans lunettes de soleil ni masque."
        )
    diagnostic = musetalk_output[-2000:] if musetalk_output else "(aucune sortie capturée)"
    raise RuntimeError(
        f"MuseTalk n'a produit aucun fichier MP4.\n"
        f"Sortie MuseTalk :\n{diagnostic}"
    )


class MuseTalkBackend(BaseModelBackend):
    """Contrat commun autour du sous-processus MuseTalk (scripts.inference du depot vendore)."""

    REQUIRED_PACKAGES = ['mmcv', 'mmpose', 'mmengine']
    recommended_vram_gb = MUSETALK_VRAM_GB
    description = "MuseTalk — lip-sync d'un avatar sur un audio (sous-processus GPU)."
    _warm = False

    @classmethod
    def is_available(cls) -> bool:
        return (MUSETALK_DIR / 'scripts' / 'inference.py').exists()

    def load(self, model=None) -> bool:
        self._warm = True
        return True

    @property
    def is_loaded(self) -> bool:
        return self._warm

    def unload(self) -> None:
        self._warm = False

    def process(self, *args, **kwargs):
        return _run_musetalk(*args, **kwargs)
