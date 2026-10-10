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

# Official GitHub release asset, as a `github` descriptor of the model installer (2026-10-07):
# the address derives from the declared `github` source, the file is checked against its PINNED
# digest — measured on 2026-10-10 two independent ways (a fresh download and the file already
# installed here agree: 156,380,200 bytes). The release publishes no digest of its own.
YOLOPV2_SPEC = {
    'kind': 'github', 'ref': 'CAIC-AD/YOLOPv2:V0.0.1', 'asset': 'yolopv2.pt',
    'sha256': 'f2a8c8374203ae3e67ff9c184e931f763957de92a993b23269e4e721627f1f8c',
}
YOLOPV2_LOCAL_NAME = YOLOPV2_SPEC['asset']

# Kept for backwards-compat with the existing endpoint name
BDD100K_SEG_LOCAL_NAME = YOLOPV2_LOCAL_NAME


def ensure_bdd100k_seg(force: bool = False) -> tuple[bool, str, str]:
    """
    Make sure yolopv2.pt is present in the segment dir.

    Returns (success, absolute_path, message). Streams the GitHub release
    asset to disk; idempotent when the file already exists.

    The download is the model installer's common one (`download_asset`, 2026-10-10) — partial
    file, pinned digest, atomic replace — instead of the copy that lived here (it checked the
    length only). Same folder and name as before: the profile dropdown lists that folder.
    """
    from wama.common.external_sources import proxies_for
    from wama.model_manager.services.model_installer import download_asset, github_asset_url

    ROAD_MODELS_DIR.mkdir(parents=True, exist_ok=True)
    target = ROAD_MODELS_DIR / YOLOPV2_LOCAL_NAME

    if target.exists() and not force:
        return True, str(target), f"Déjà présent : {target.name}"

    url = github_asset_url(YOLOPV2_SPEC)
    logger.info(f"[road-model] Downloading {url} ...")
    res = download_asset(url, str(target), timeout=60, sha256=YOLOPV2_SPEC['sha256'],
                         proxies=proxies_for('github'))
    if not res.get('ok'):
        logger.error(f"[road-model] Download failed: {res.get('error')}")
        return False, '', f"Échec téléchargement : {res.get('error')}"

    logger.info(f"[road-model] {YOLOPV2_LOCAL_NAME} ready at {target}")
    return True, str(target), (
        f"Téléchargé : {YOLOPV2_LOCAL_NAME}. "
        f"Note : backend YOLOPv2 (TorchScript multi-tête) pas encore branché — "
        f"sélectionner ce modèle dans le profil échouera à l'inférence."
    )
