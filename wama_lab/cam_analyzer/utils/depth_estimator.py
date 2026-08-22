"""
Estimation de profondeur monoculaire pour cam_analyzer — modèle Apple Depth Pro.

Piste documentée dans `CAM_ANALYZER_CHAINE_TRAITEMENT.md` §[E]. Chaîne en 3 ÉTAGES DÉCOUPLÉS
(décision Fabien 2026-08-05 : « l'analyse d'abord, les calculs ensuite, l'affichage en ON/OFF ») :

  ── Étage 1 · ANALYSE (GPU, coûteux) ─ `run_depth_analysis(session)` ─ passe `depth` du volet.
     Inférence Depth Pro sur des frames échantillonnées des 4 caméras, puis STOCKAGE de la donnée
     BRUTE ré-utilisable : carte de profondeur métrique par frame (disque, float16 sous-échantillonné
     → `DepthFrame`), focale estimée, et profondeur de contact par détection (`depth_distance_m`).
     SEUL point d'inférence de toute la chaîne. Brique partagée : `estimate_depth(frame) -> (depth_m, focal_px)`.

  ── Étage 2 · CALCULS (CPU, re-jouable sans GPU) ─ relisent la db de l'étage 1, N'inférent JAMAIS :
       · plan de sol (`estimate_ground_plane_ph`) : déprojette la zone roulable des cartes stockées,
         ajuste le plan (briques pures) → (pitch, hauteur) pour le re-calage §[E]/usage 4 ;
       · cross-check distance & reflets (`depth_distance_report`) : agrège les `depth_distance_m`
         déjà stockés → métriques A/B console (usages 3 + 1). Aucune écriture.
     Ces calculs sont consommés par les passes existantes `global_tracking` (projection) et `distance`.

  ── Étage 3 · AFFICHAGE (ON/OFF) ─ le flag ⚑ `depth_estimation` bascule la consommation du plan
     profondeur (vs homographie) dans la projection ; l'overlay de profondeur (rendu de la carte
     stockée) est un incrément ultérieur — la carte est stockée dès maintenant pour l'alimenter.
     Le SCORING (`placement_spread`, dans `homography_estimator`) donne l'A/B profondeur↔homographie
     sur la même échelle chiffrée.

⚠ GPU interdit sous WSL2 sur ce poste (crashs hôte) : SEUL l'étage 1 infère, côté runtime/R760xa.
   Les étages 2 (lecture db, numpy) sont sûrs en CPU/WSL2. Le 1er run réel valide (a) l'API
   `transformers` de Depth Pro et (b) le gain `placement_spread` ; la convention de signe du pitch
   `atan2(nz, -ny)` est déjà VALIDÉE (test CPU pur, plan synthétique).

Modèle : `apple/DepthPro-hf` déposé par `pull_model` dans `models/vision/depth-pro/`. Retenu vs DA3
car intégration `AutoModelForDepthEstimation` sans package custom, et focale estimée qui sert
directement le re-calage du plan de sol (cf. §[E]).
"""
from __future__ import annotations

import logging
import math

import numpy as np
from django.conf import settings

# Cœur de calcul PUR (déprojection, RANSAC de plan, pitch/hauteur, contact-sol) — tronc commun
# WAMA Data. Ce module N'IMPLÉMENTE PLUS la géométrie : il charge le modèle, décode les frames,
# écrit en base, et DÉLÈGUE tout le calcul à ces briques (cf. skill cam-analyzer §3).
from wama_data.functions.geometry.depth_geometry import (
    deproject_depth, fit_plane_ransac, plane_pitch_height, contact_depth)

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


# ── Plomberie app (rasterisation masque, I/O disque) — la géométrie est dans les briques pures ──

def _rasterize_drivable(detections, h, w, sx: float = 1.0, sy: float = 1.0):
    """Masque booléen HxW des zones roulables depuis les polygones `road_mask` d'une frame.

    (sx, sy) mettent à l'échelle les coordonnées polygone (exprimées en pixels d'ORIGINE) vers la
    résolution cible HxW — nécessaire quand on rasterise sur une carte de profondeur STOCKÉE
    sous-échantillonnée (étage 2). Repli (aucun polygone) : tiers inférieur de l'image (proxy sol)."""
    import cv2
    mask = np.zeros((h, w), dtype=np.uint8)
    got = False
    for d in (detections or []):
        if d.get('type') != 'road_mask':
            continue
        poly = d.get('polygon')
        if not poly or len(poly) < 3:
            continue
        pts = np.asarray(poly, dtype=np.float32) * np.asarray([sx, sy], dtype=np.float32)
        pts = pts.round().astype(np.int32).reshape(-1, 1, 2)
        cv2.fillPoly(mask, [pts], 1)
        got = True
    if not got:
        mask[int(h * 0.6):, :] = 1   # proxy : bas de l'image
    return mask.astype(bool)


def _has_bbox_obj(d) -> bool:
    """Détection « objet du monde » avec bbox exploitable (masques/marquages/fantômes exclus).
    Plus permissif que `_usable_det` : n'exige PAS de distance pinhole → l'étage 1 STOCKE le maximum
    de profondeurs de contact ; le cross-check (étage 2) filtrera ce qui a un pinhole à comparer."""
    bb = d.get('bbox')
    if not (isinstance(bb, (list, tuple)) and len(bb) >= 4):
        return False
    if d.get('type') in ('road_mask', 'sam3_marking') or d.get('predicted'):
        return False
    if d.get('class_name') in ('road_mask', 'sam3_marking'):
        return False
    return True


def _save_depth_map(camera, frame_number, depth_small, focal_scaled) -> str:
    """Persiste une carte de profondeur (déjà sous-échantillonnée) en .npz float16. Chemin RELATIF."""
    import os
    from ..models import depth_output_dir
    rel_dir = depth_output_dir(camera)
    rel_path = os.path.join(rel_dir, f"{int(frame_number):08d}.npz")
    abs_path = os.path.join(settings.MEDIA_ROOT, rel_path)
    np.savez_compressed(abs_path, depth=depth_small.astype(np.float16),
                        focal=np.float32(focal_scaled or 0.0))
    return rel_path


def _load_depth_map(depth_frame):
    """Relit une carte stockée (float16 → float32 HxW mètres), ou None si illisible."""
    import os
    abs_path = os.path.join(settings.MEDIA_ROOT, depth_frame.depth_path)
    try:
        with np.load(abs_path) as z:
            return z['depth'].astype(np.float32)
    except Exception:
        logger.warning('[DepthPro] carte de profondeur illisible : %s', abs_path, exc_info=True)
        return None


def run_depth_analysis(session, *, max_frames_per_cam: int = 24,
                       downsample_long: int = 384, device: str = 'cuda'):
    """ÉTAGE 1 (ANALYSE) — inférence Depth Pro sur des frames échantillonnées des 4 caméras.

    STOCKE la donnée BRUTE ré-utilisable, sans AUCUN calcul dérivé (plan, A/B = étage 2) :
      · une carte de profondeur métrique par frame (disque, float16 sous-échantillonné) → DepthFrame ;
      · la focale estimée, mise à l'échelle de la carte stockée → DepthFrame.focal_px ;
      · la profondeur de contact par détection (PLEINE résolution) → `depth_distance_m` (JSON additif).
    Retourne {'maps', 'contacts', 'cameras'}, ou None si indisponible.

    ⚠ SEUL point d'inférence GPU de la chaîne profondeur (interdit sous WSL2 ici → runtime/R760xa).
    """
    if not is_available():
        logger.info('[DepthPro] analyse ignorée : poids Depth Pro absents')
        return None
    try:
        import cv2
    except Exception:
        return None
    from ..models import DepthFrame

    cams = [c for c in session.cameras.all()
            if getattr(c, 'video_file', None) and c.detections.exists()]
    if not cams:
        return None

    n_maps = n_contacts = cams_done = 0
    for cam in cams:
        try:
            video_path = cam.video_file.path
        except Exception:
            continue
        rows = list(cam.detections.order_by('frame_number').values_list('frame_number', flat=True))
        if not rows:
            continue
        step = max(1, len(rows) // max(1, max_frames_per_cam))
        chosen = rows[::step][:max_frames_per_cam]
        objs = {o.frame_number: o for o in
                cam.detections.filter(frame_number__in=chosen)
                   .only('frame_number', 'detections', 'timestamp')}

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            continue
        try:
            for fn in chosen:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(fn))
                ok, frame = cap.read()
                if not ok or frame is None:
                    continue
                h, w = frame.shape[:2]
                try:
                    depth_m, focal_px = estimate_depth(frame, device)
                except Exception:
                    logger.warning('[DepthPro] estimate_depth a échoué (frame %s)', fn, exc_info=True)
                    continue
                if depth_m is None:
                    continue
                if depth_m.shape != (h, w):
                    depth_m = cv2.resize(depth_m, (w, h), interpolation=cv2.INTER_NEAREST)

                # (a) Profondeur de contact par détection — PLEINE résolution (bbox en px d'origine).
                obj = objs.get(fn)
                if obj is not None:
                    changed = False
                    for d in (obj.detections or []):
                        if not _has_bbox_obj(d):
                            continue
                        dd = contact_depth(depth_m, d['bbox'])   # brique pure (contact-sol)
                        if dd is None:
                            continue
                        d['depth_distance_m'] = round(dd, 2)     # champ ADDITIF (n'écrase rien)
                        changed = True
                        n_contacts += 1
                    if changed:
                        try:
                            obj.save(update_fields=['detections'])
                        except Exception:
                            logger.warning('[DepthPro] save detections %s échoué', fn, exc_info=True)

                # (b) Carte sous-échantillonnée (long-côté ≤ downsample_long) → disque + DepthFrame.
                s = min(1.0, float(downsample_long) / max(h, w)) if max(h, w) > 0 else 1.0
                if s < 1.0:
                    small = cv2.resize(depth_m, (max(1, round(w * s)), max(1, round(h * s))),
                                       interpolation=cv2.INTER_NEAREST)
                else:
                    small = depth_m
                sh, sw = small.shape[:2]
                # Focale mise à l'échelle de la carte stockée : déprojection cohérente sans w d'origine.
                focal_scaled = (focal_px or 0.8 * w) * (sw / float(w))
                rel_path = _save_depth_map(cam, fn, small, focal_scaled)
                _dmin = float(np.nanmin(small)) if small.size else None
                _dmax = float(np.nanmax(small)) if small.size else None
                DepthFrame.objects.update_or_create(
                    camera=cam, frame_number=int(fn),
                    defaults={
                        'timestamp': float(getattr(obj, 'timestamp', 0.0) or 0.0),
                        'focal_px': round(float(focal_scaled), 3),
                        'depth_path': rel_path,
                        'width': sw, 'height': sh,
                        'd_min': None if _dmin is None else round(_dmin, 3),
                        'd_max': None if _dmax is None else round(_dmax, 3),
                    })
                n_maps += 1
        finally:
            cap.release()
        cams_done += 1
        logger.info('[DepthPro] analyse %s : cumul %d cartes, %d contacts', cam.position,
                    n_maps, n_contacts)

    return {'maps': n_maps, 'contacts': n_contacts, 'cameras': cams_done}


def estimate_ground_plane_ph(session, position):
    """ÉTAGE 2 (CALCUL) — (pitch_deg, height_m) du plan de sol, ou None (repli homographie).

    Relit les cartes de profondeur DÉJÀ stockées par l'étage 1 (`run_depth_analysis` → DepthFrame) :
    AUCUNE inférence GPU ici (sûr en CPU/WSL2). Déprojette la zone roulable de chaque carte (brique
    pure), cumule le nuage, ajuste le plan (RANSAC + SVD, brique pure), en tire pitch/hauteur.

    Convention : repère caméra X-droite, Y-bas, Z-avant. Normale-sol orientée haut (ny<0). Pitch
    (piqué caméra, >0 = vers le bas) = atan2(nz, -ny) ; hauteur = |offset|. Signe VALIDÉ (test CPU pur).
    """
    cam = session.cameras.filter(position=position).first()
    if cam is None:
        return None
    dframes = list(cam.depth_frames.order_by('frame_number'))
    if not dframes:
        return None   # étage 1 pas encore lancé → repli homographie

    det_by_fn = dict(cam.detections
                     .filter(frame_number__in=[d.frame_number for d in dframes])
                     .values_list('frame_number', 'detections'))
    ow, oh = (cam.width or 0), (cam.height or 0)
    all_pts = []
    frames_used = 0
    for df in dframes:
        depth = _load_depth_map(df)
        if depth is None:
            continue
        h, w = depth.shape[:2]
        focal_px = df.focal_px or (0.8 * w)   # focale DÉJÀ à l'échelle de la carte stockée
        # Masque roulable à l'échelle de la carte : polygones en px d'origine → (sx, sy).
        if ow and oh:
            drivable = _rasterize_drivable(det_by_fn.get(df.frame_number), h, w,
                                           sx=w / float(ow), sy=h / float(oh))
        else:
            drivable = _rasterize_drivable([], h, w)   # dims caméra inconnues → proxy bas d'image
        pts = deproject_depth(depth, focal_px, mask=drivable,
                              z_min=1.5, z_max=60.0, max_points=4000)
        if len(pts) < 50:
            continue
        all_pts.append(pts)
        frames_used += 1

    if frames_used < 2 or not all_pts:
        return None
    pts = np.concatenate(all_pts, axis=0)
    fit = fit_plane_ransac(pts, min_inliers=300)   # brique pure (RANSAC + raffinement SVD)
    if fit is None:
        return None
    normal, offset, n_inl, _rms = fit
    pitch_deg, height_m = plane_pitch_height(normal, offset)   # brique pure

    # Garde-fous physiques (rig ENA) : hors plage → repli homographie plutôt qu'une calib absurde.
    if not (1.0 <= height_m <= 4.0) or not (-10.0 <= pitch_deg <= 35.0):
        logger.info('[DepthPro] plan de sol hors plage (pitch=%.1f°, h=%.2f m) — repli homographie',
                    pitch_deg, height_m)
        return None
    logger.info('[DepthPro] plan de sol %s : pitch=%.2f° h=%.2f m (%d inliers, %d cartes stockées)',
                position, pitch_deg, height_m, n_inl, frames_used)
    return (round(pitch_deg, 2), round(height_m, 3))


def _usable_det(d):
    """Détection exploitable pour le cross-check distance : objet du monde avec bbox + distance
    pinhole. Exclut masques/marquages et fantômes."""
    bb = d.get('bbox')
    if not (isinstance(bb, (list, tuple)) and len(bb) >= 4):
        return False
    if d.get('type') in ('road_mask', 'sam3_marking') or d.get('predicted'):
        return False
    if d.get('class_name') in ('road_mask', 'sam3_marking'):
        return False
    return bool(d.get('distance_m'))


def depth_distance_report(session, max_frames=12):
    """ÉTAGE 2 (CALCUL) — cross-check distance MULTI-USAGE, MESURE-ET-RAPPORT. Lecture PURE.

    N'infère RIEN : agrège les `depth_distance_m` DÉJÀ stockés par l'étage 1 (`run_depth_analysis`)
    sur les détections, et en tire des métriques A/B console. Ne bascule AUCUNE source existante
    (chemin OFF et distances pinhole/homographie intacts). Sûr en CPU/WSL2, re-jouable à volonté.
    `max_frames` est conservé pour compat d'appel mais IGNORÉ (on lit tout le stock, pas d'échantillonnage).

    Usages couverts (chacun sa ligne console → observables séparément sous le flag unique) :
      · usage 3 (réciproque du pinhole) : profondeur métrique au contact-sol de la bbox = 3ᵉ
        source indépendante ; A/B = désaccord médian profondeur↔pinhole et profondeur↔homographie.
      · usage 1 (reflets) : la profondeur confirme-t-elle `artifact_filter` ? désaccord médian
        des détections marquées `artifact` vs propres (un reflet de vitrage projette une
        profondeur incohérente avec un objet réel à cette position image).

    Retourne un dict de métriques (aussi persisté par l'appelant dans
    results_summary['depth_report']), ou None si indisponible/insuffisant.
    """
    diffs_pin, diffs_hom = [], []          # usage 3 : |profondeur − pinhole| / − homographie
    art_pin, clean_pin = [], []            # usage 1 : |profondeur − pinhole| reflets vs propres
    frames_used = 0
    n_obj = 0

    # Lecture PURE : n'agrège que ce que l'étage 1 (`run_depth_analysis`) a déjà écrit
    # (`depth_distance_m` sur les détections). Aucune inférence GPU, aucune écriture — sûr en
    # CPU/WSL2, re-jouable à volonté. Sans analyse préalable → aucune donnée → None (repli).
    for cam in session.cameras.all():
        for fn, det in (cam.detections.order_by('frame_number')
                        .values_list('frame_number', 'detections')):
            hit = False
            for d in (det or []):
                dd = d.get('depth_distance_m')
                if dd is None or not _usable_det(d):
                    continue
                hit = True
                n_obj += 1
                dd = float(dd)
                pin = d.get('distance_m')
                if pin:
                    e = abs(dd - float(pin))
                    diffs_pin.append(e)
                    (art_pin if d.get('artifact') else clean_pin).append(e)
                hom = d.get('dist_euclid_m') or d.get('dist_longitudinal_m')
                if hom:
                    diffs_hom.append(abs(dd - float(hom)))
            if hit:
                frames_used += 1

    if frames_used < 1 or not diffs_pin:
        logger.info('[DepthPro] cross-check distance : pas assez d\'observations')
        return None

    def _med(xs):
        return round(float(np.median(xs)), 2) if xs else None

    report = {
        'frames': frames_used,
        'n_obj': n_obj,
        'disagree_pinhole_m': _med(diffs_pin),
        'disagree_homography_m': _med(diffs_hom),
        'n_homography': len(diffs_hom),
        'reflet_pinhole_m': _med(art_pin),
        'reflet_n': len(art_pin),
        'clean_pinhole_m': _med(clean_pin),
        'clean_n': len(clean_pin),
    }
    # ── Lignes A/B console (une par usage) ────────────────────────────────────────────────
    logger.info('[DepthPro] Distance (usage 3) : désaccord médian profondeur↔pinhole = %s m '
                '(%d obj, %d frames) ; ↔homographie = %s m (%d obj)',
                report['disagree_pinhole_m'], n_obj, frames_used,
                report['disagree_homography_m'], report['n_homography'])
    if art_pin:
        verdict = ('reflets PLUS incohérents' if (report['reflet_pinhole_m'] or 0)
                   > (report['clean_pinhole_m'] or 0) else 'signal non concluant')
        logger.info('[DepthPro] Reflets (usage 1) : désaccord profondeur↔pinhole reflets=%s m (%d) '
                    'vs propres=%s m (%d) — %s', report['reflet_pinhole_m'], report['reflet_n'],
                    report['clean_pinhole_m'], report['clean_n'], verdict)
    return report
