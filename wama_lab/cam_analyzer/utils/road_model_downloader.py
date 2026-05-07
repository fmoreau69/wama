"""
Auto-download road / drivable-area models for cam_analyzer.

YOLOPv2 (CAIC-AD) is a TorchScript multi-task model (object det + drivable
area + lane lines). It is NOT an Ultralytics YOLO checkpoint — loading it
through ultralytics.YOLO() will fail. A dedicated YOLOPv2RoadSegmenter
backend is required to actually use it (todo). For now this module just
makes the .pt file available on disk so the dropdown can list it.
"""
from __future__ import annotations

import logging
from pathlib import Path

from django.conf import settings

logger = logging.getLogger(__name__)

ROAD_MODELS_DIR = Path(settings.BASE_DIR) / 'AI-models' / 'models' / 'vision' / 'yolo' / 'segment'

# Official GitHub release asset
YOLOPV2_URL = 'https://github.com/CAIC-AD/YOLOPv2/releases/download/V0.0.1/yolopv2.pt'
YOLOPV2_LOCAL_NAME = 'yolopv2.pt'

# Kept for backwards-compat with the existing endpoint name
BDD100K_SEG_LOCAL_NAME = YOLOPV2_LOCAL_NAME


def ensure_bdd100k_seg(force: bool = False) -> tuple[bool, str, str]:
    """
    Make sure yolopv2.pt is present in the segment dir.

    Returns (success, absolute_path, message). Streams the GitHub release
    asset to disk; idempotent when the file already exists.
    """
    ROAD_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    target = ROAD_MODELS_DIR / YOLOPV2_LOCAL_NAME

    if target.exists() and not force:
        return True, str(target), f"Déjà présent : {target.name}"

    try:
        import requests
    except ImportError as exc:
        return False, '', f"requests non installé : {exc}"

    logger.info(f"[road-model] Downloading {YOLOPV2_URL} ...")
    tmp = target.with_suffix(target.suffix + '.part')
    try:
        with requests.get(YOLOPV2_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            total = int(r.headers.get('content-length', 0))
            done = 0
            with open(tmp, 'wb') as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
            if total and done < total:
                raise IOError(f"Download truncated: {done}/{total} bytes")
        tmp.replace(target)
    except Exception as exc:
        logger.error(f"[road-model] Download failed: {exc}", exc_info=True)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False, '', f"Échec téléchargement : {exc}"

    logger.info(f"[road-model] {YOLOPV2_LOCAL_NAME} ready at {target}")
    return True, str(target), (
        f"Téléchargé : {YOLOPV2_LOCAL_NAME}. "
        f"Note : backend YOLOPv2 (TorchScript multi-tête) pas encore branché — "
        f"sélectionner ce modèle dans le profil échouera à l'inférence."
    )
