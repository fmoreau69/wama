"""
Estimation de profondeur monoculaire pour cam_analyzer — modèle Apple Depth Pro.

Piste documentée dans `CAM_ANALYZER_CHAINE_TRAITEMENT.md` §[E]. Ce module :
  1. charge Depth Pro (métrique + focale estimée, natif `transformers`) en keep_loaded ;
  2. expose `estimate_depth(frame_bgr) -> (depth_m HxW mètres, focal_px)` — brique réutilisable ;
  3. dérive un plan de sol (pitch, hauteur) depuis le nuage de profondeur restreint à la zone
     roulable (`estimate_ground_plane_ph`), pour le re-calage §[E]/usage 4.

⚑ Portillon : le flag `depth_estimation` (défaut OFF) est le SEUL interrupteur de toute
l'amélioration profondeur (décision 2026-08-05 : un flag global, pas de sous-flags par usage qui
polluent la liste ⚑ Modes). Quand ON, `homography_estimator.store_ground_calib` prend la source
profondeur au lieu de la recherche homographique ; le SCORING (`placement_spread`) reste dans
`homography_estimator` → l'A/B profondeur↔homographie se lit sur la même échelle chiffrée.

⚠ GPU interdit sous WSL2 sur ce poste (crashs hôte) : l'inférence tourne côté runtime/R760xa.
   Ce module N'A PAS été fumé au GPU ici ; le premier run réel valide (a) l'API `transformers`
   de Depth Pro et (b) la CONVENTION de signe du pitch ci-dessous (la métrique `placement_spread`
   en console le révèle immédiatement : un signe faux fait exploser l'étalement).

Modèle : `apple/DepthPro` déposé par `pull_model` dans `models/vision/depth-pro/`. Retenu vs DA3
car intégration `AutoModelForDepthEstimation` sans package custom, et focale estimée qui sert
directement le re-calage du plan de sol (cf. §[E]).
"""
from __future__ import annotations

import logging
import math

import numpy as np
from django.conf import settings

logger = logging.getLogger(__name__)

# « Path d'abord, env vars ensuite, import après » (CLAUDE.md §Ajout d'un nouveau modèle AI).
DEPTH_MODEL_ID = 'apple/DepthPro-hf'  # natif transformers, métrique + focale estimée, Apache-2.0
DEPTH_MODEL_DIR = (settings.MODEL_PATHS.get('vision', {}).get('depth')
                   or settings.AI_MODELS_DIR / "models" / "vision" / "depth-pro")

# keep_loaded : Depth Pro est coûteux à charger et identique pour toutes les caméras/analyses →
# cache module (chargé 1×, réutilisé), même patron que `yolopv2_segmenter._MODEL_CACHE`.
_MODEL_CACHE = {}   # (model_id, device) -> (processor, model)


def is_available() -> bool:
    """Vrai si les poids Depth Pro sont présents sur disque (téléchargés via `pull_model`)."""
    try:
        from pathlib import Path
        root = Path(DEPTH_MODEL_DIR)
        return root.exists() and any(root.rglob('*.safetensors'))
    except Exception:
        return False


def clear_model_cache():
    """Libère Depth Pro gardé en cache (keep_loaded) et rend la VRAM. À appeler avant une étape
    VRAM-critique (comme `yolopv2_segmenter.clear_model_cache`)."""
    global _MODEL_CACHE
    _MODEL_CACHE.clear()
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def load(device: str = 'cuda'):
    """Charge Depth Pro (keep_loaded) et retourne (processor, model, device_effectif).

    Pattern obligatoire (CLAUDE.md §Ajout d'un nouveau modèle AI) : HF_HUB_CACHE posé AVANT tout
    import HF, cache_dir passé à `from_pretrained`.
    """
    import os
    cache = str(DEPTH_MODEL_DIR)
    os.environ['HF_HUB_CACHE'] = cache
    os.environ['HUGGINGFACE_HUB_CACHE'] = cache        # AVANT tout import HF

    import torch
    if device == 'cuda' and not torch.cuda.is_available():
        logger.warning("[DepthPro] CUDA indisponible — repli CPU")
        device = 'cpu'

    _key = (DEPTH_MODEL_ID, device)
    cached = _MODEL_CACHE.get(_key)
    if cached is not None:
        return cached[0], cached[1], device

    from transformers import AutoModelForDepthEstimation, AutoImageProcessor
    dtype = torch.float16 if device == 'cuda' else torch.float32
    processor = AutoImageProcessor.from_pretrained(DEPTH_MODEL_ID, cache_dir=cache)
    model = AutoModelForDepthEstimation.from_pretrained(
        DEPTH_MODEL_ID, cache_dir=cache, torch_dtype=dtype,
    ).to(device).eval()
    _MODEL_CACHE[_key] = (processor, model)
    logger.info(f"[DepthPro] Chargé (cache) : {DEPTH_MODEL_ID} sur {device}")
    return processor, model, device


def estimate_depth(frame_bgr, device: str = 'cuda'):
    """Profondeur métrique d'une frame BGR.

    Retourne (depth_m, focal_px) :
      - depth_m : ndarray HxW float32, profondeur métrique le long de l'axe optique (mètres) ;
      - focal_px : focale estimée par Depth Pro (pixels, résolution d'origine) ou None.
    Brique réutilisable (les autres usages profondeur §[E] la partagent).
    """
    import torch
    from PIL import Image
    import cv2

    processor, model, device = load(device)
    h0, w0 = frame_bgr.shape[:2]
    image = Image.fromarray(cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB))
    inputs = processor(images=image, return_tensors='pt')
    inputs = {k: (v.to(device) if hasattr(v, 'to') else v) for k, v in inputs.items()}
    with torch.no_grad():
        outputs = model(**inputs)
    post = processor.post_process_depth_estimation(outputs, target_sizes=[(h0, w0)])[0]

    depth = post['predicted_depth']
    depth_m = depth.detach().float().cpu().numpy().astype(np.float32)
    def _scalar(x):
        if x is None:
            return None
        if hasattr(x, 'item'):
            try:
                return float(x.item())
            except Exception:
                return float(np.asarray(x).reshape(-1)[0])
        return float(x)

    focal_px = _scalar(post.get('focal_length', None))
    if not focal_px:
        # Selon la version transformers, seul l'angle de champ horizontal peut être fourni.
        fov_h = _scalar(post.get('field_of_view', None))
        if fov_h:
            focal_px = (w0 / 2.0) / math.tan(math.radians(fov_h) / 2.0)
    return depth_m, focal_px


def unload():
    """keep_loaded : ne libère PAS le cache (réutilisé sur les vues/analyses suivantes)."""
    return None


# ── Géométrie pure (candidate à extraction vers common/data/functions/geometry) ───────────────

def _rasterize_drivable(detections, h, w):
    """Masque booléen HxW des zones roulables depuis les polygones `road_mask` d'une frame.
    Repli (aucun polygone) : tiers inférieur de l'image (proxy sol grossier)."""
    import cv2
    mask = np.zeros((h, w), dtype=np.uint8)
    got = False
    for d in (detections or []):
        if d.get('type') != 'road_mask':
            continue
        poly = d.get('polygon')
        if not poly or len(poly) < 3:
            continue
        pts = np.asarray(poly, dtype=np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(mask, [pts], 1)
        got = True
    if not got:
        mask[int(h * 0.6):, :] = 1   # proxy : bas de l'image
    return mask.astype(bool)


def _fit_ground_plane_ransac(pts, iters=250, thresh=0.10, min_inliers=300):
    """RANSAC de plan sur un nuage (N,3) en repère caméra (X droite, Y bas, Z avant).
    Retourne (normal_unitaire_vers_le_haut, d, n_inliers) avec plan n·P + d = 0, ou None."""
    n_pts = len(pts)
    if n_pts < min_inliers:
        return None
    rng = np.random.default_rng(20260805)   # déterministe (pas de Math.random) — reproductible
    best_c, best_n, best_d = -1, None, None
    for _ in range(iters):
        idx = rng.choice(n_pts, 3, replace=False)
        p0, p1, p2 = pts[idx]
        n = np.cross(p1 - p0, p2 - p0)
        nn = np.linalg.norm(n)
        if nn < 1e-6:
            continue
        n = n / nn
        d = -float(n.dot(p0))
        dist = np.abs(pts.dot(n) + d)
        c = int((dist < thresh).sum())
        if c > best_c:
            best_c, best_n, best_d = c, n, d
    if best_n is None or best_c < min_inliers:
        return None
    # Raffinement moindres carrés sur les inliers (SVD sur nuage centré).
    dist = np.abs(pts.dot(best_n) + best_d)
    inl = pts[dist < thresh]
    if len(inl) >= 3:
        c0 = inl.mean(axis=0)
        _, _, vt = np.linalg.svd(inl - c0)
        best_n = vt[-1] / np.linalg.norm(vt[-1])
        best_d = -float(best_n.dot(c0))
    # Orienter la normale vers le HAUT (en repère caméra, le haut est -Y).
    if best_n[1] > 0:
        best_n, best_d = -best_n, -best_d
    return best_n, best_d, best_c


def estimate_ground_plane_ph(session, position):
    """(pitch_deg, height_m) du plan de sol par profondeur monoculaire, ou None (repli homographie).

    Convention : repère caméra X-droite, Y-bas, Z-avant. Normale-sol unitaire orientée vers le haut
    n=(nx,ny,nz), ny<0. Pitch (piqué caméra, >0 = vers le bas) = atan2(nz, -ny) ; hauteur = distance
    origine→plan = |d|. ⚠ signe du pitch NON validé au GPU — à confirmer au 1er run (cf. en-tête).
    """
    if not is_available():
        return None
    try:
        import cv2
    except Exception:
        return None

    cam = session.cameras.filter(position=position).first()
    if cam is None or not getattr(cam, 'video_file', None):
        return None
    try:
        video_path = cam.video_file.path
    except Exception:
        return None

    # Frames de calibration : celles qui portent un masque roulable (road_mask), échantillonnées
    # (budget = frames de calibration seulement, pas toute la vidéo). Repli : frames avec détections.
    rows = list(cam.detections.order_by('frame_number')
                .values_list('frame_number', 'detections'))
    if not rows:
        return None
    with_road = [(fn, det) for fn, det in rows
                 if any(d.get('type') == 'road_mask' for d in (det or []))]
    pool = with_road or rows
    n_cal = min(8, len(pool))
    step = max(1, len(pool) // n_cal)
    chosen = pool[::step][:n_cal]

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return None
    all_pts = []
    frames_used = 0
    try:
        for frame_number, det in chosen:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(frame_number))
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            h, w = frame.shape[:2]
            try:
                depth_m, focal_px = estimate_depth(frame)
            except Exception:
                logger.warning('[DepthPro] estimate_depth a échoué (frame %s)', frame_number,
                               exc_info=True)
                continue
            if depth_m is None:
                continue
            # Rééchelle si la profondeur ne fait pas exactement HxW (sécurité).
            if depth_m.shape != (h, w):
                depth_m = cv2.resize(depth_m, (w, h), interpolation=cv2.INTER_NEAREST)
            f = focal_px or (0.8 * w)   # repli : focale ~0.8·largeur si non estimée
            cx, cy = w / 2.0, h / 2.0

            drivable = _rasterize_drivable(det, h, w)
            vs, us = np.nonzero(drivable)
            if len(us) == 0:
                continue
            # Sous-échantillonnage (≤ 4000 px/frame) pour tenir le budget mémoire/CPU.
            if len(us) > 4000:
                sel = np.linspace(0, len(us) - 1, 4000).astype(int)
                us, vs = us[sel], vs[sel]
            z = depth_m[vs, us].astype(np.float32)
            valid = (z > 1.5) & (z < 60.0) & np.isfinite(z)   # plage utile route
            if valid.sum() < 50:
                continue
            us, vs, z = us[valid], vs[valid], z[valid]
            x = (us - cx) * z / f
            y = (vs - cy) * z / f
            all_pts.append(np.stack([x, y, z], axis=1))
            frames_used += 1
    finally:
        cap.release()

    if frames_used < 2 or not all_pts:
        return None
    pts = np.concatenate(all_pts, axis=0)
    fit = _fit_ground_plane_ransac(pts)
    if fit is None:
        return None
    n, d, n_inl = fit
    height_m = abs(d)
    pitch_deg = math.degrees(math.atan2(float(n[2]), -float(n[1])))

    # Garde-fous physiques (rig ENA) : hors plage → repli homographie plutôt qu'une calib absurde.
    if not (1.0 <= height_m <= 4.0) or not (-10.0 <= pitch_deg <= 35.0):
        logger.info('[DepthPro] plan de sol hors plage (pitch=%.1f°, h=%.2f m) — repli homographie',
                    pitch_deg, height_m)
        return None
    logger.info('[DepthPro] plan de sol %s : pitch=%.2f° h=%.2f m (%d inliers, %d frames)',
                position, pitch_deg, height_m, n_inl, frames_used)
    return (round(pitch_deg, 2), round(height_m, 3))
