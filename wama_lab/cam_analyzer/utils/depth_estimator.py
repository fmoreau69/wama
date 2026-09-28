"""
Estimation de profondeur monoculaire pour cam_analyzer — ZoeDepth KITTI par défaut (2026-09-28),
Apple Depth Pro au choix (`config['depth_model']`). Modèles déclarés par `backends/depth_engine`.

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
   `transformers` de Depth Pro et (b) le gain `placement_spread`. ⚠ La convention de signe du
   pitch annoncée « VALIDÉE » ici le 2026-08-05 était INVERSÉE (validation circulaire) : corrigée
   et gardée le 2026-09-28 (`depth_geometry.plane_pitch_height`, `tests_depth_geometry`).

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

# ── Le MOTEUR vit désormais dans `backends/depth_engine.py` (coupe pur/ORM, 2026-09-07) ──────
# Ce module garde ce qui touche la BASE ; il consomme le moteur, jamais l'inverse. Les deux
# symboles importés sont exactement ceux que l'orchestration appelle — pas une ré-exportation
# de confort : `tasks.py` appelle `depth_estimator.is_available()`, et le garder ici lui évite
# de connaître l'organisation interne du paquet.
from wama.common.backends.depth_engine import (  # noqa: F401  (is_available est relayée à tasks.py)
    DEPTH_MODEL_DIR, DEPTH_MODEL_ID, clear_model_cache, estimate_depth, is_available, load,
    unload,
)


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
        logger.warning('[profondeur] carte de profondeur illisible : %s', abs_path, exc_info=True)
        return None


DEFAULT_DEPTH_WINDOW_FPS = 2.0


def depth_window_fps(session) -> float:
    """Cadence de la profondeur DANS les fenêtres d'intersection (`config['depth_window_fps']`,
    défaut 2 images/s ; 0 = seulement l'échantillon global du plan de sol)."""
    try:
        return max(0.0, float((getattr(session, 'config', None) or {}).get(
            'depth_window_fps', DEFAULT_DEPTH_WINDOW_FPS)))
    except (TypeError, ValueError):
        return DEFAULT_DEPTH_WINDOW_FPS


def frames_in_windows(rows, windows, fps):
    """Numéros de frames à ~`fps` images/s À L'INTÉRIEUR des fenêtres d'intersection.

    `rows` : [(frame_number, timestamp)] triés ; `windows` : `session.intersection_windows`
    ([{t_enter, t_exit}] en temps VIDÉO, convention `41bef1a`). Pur, sans ORM."""
    if not fps or fps <= 0 or not windows:
        return []
    spans = sorted((float(w['t_enter']), float(w['t_exit'])) for w in windows
                   if w.get('t_enter') is not None and w.get('t_exit') is not None)
    period, out, last, j = 1.0 / float(fps), [], None, 0
    for fn, ts in rows:
        if ts is None:
            continue
        while j < len(spans) and ts > spans[j][1]:
            j += 1
        if j >= len(spans):
            break
        if ts < spans[j][0]:
            continue
        if last is None or ts - last >= period - 1e-6:
            out.append(fn)
            last = ts
    return out


def run_depth_analysis(session, *, max_frames_per_cam: int = 24,
                       downsample_long: int = 384, device: str = 'cuda'):
    """ÉTAGE 1 (ANALYSE) — inférence de profondeur sur des frames échantillonnées des 4 caméras.

    Modèle : `depth_model_for(session)` (ZoeDepth KITTI par défaut depuis le 2026-09-28).
    STOCKE la donnée BRUTE ré-utilisable, sans AUCUN calcul dérivé (plan, A/B = étage 2) :
      · une carte de profondeur par frame (disque, float16 sous-échantillonné) → DepthFrame —
        BRUTE, c'est-à-dire à l'échelle du modèle : l'étage 2 l'ancre si le modèle ne rend pas de
        mètres exploitables tels quels ;
      · la focale estimée (repli ~0,8·W si le modèle n'en rend pas), à l'échelle de la carte ;
      · la profondeur de contact par détection (PLEINE résolution) → `depth_distance_m` (JSON
        additif, même échelle brute).
    Deux échantillons (2026-09-28) : `max_frames_per_cam` images réparties sur tout le parcours ;
    plus, dans les fenêtres d'intersection, `depth_window_fps` images/s portant au moins un objet.
    Toutes voient leur carte stockée (~84 Ko l'une : ~0,6 Go pour les 7 143 images de la session
    de référence à 2 images/s) — la donnée brute une fois, les calculs la relisent sans GPU.
    Retourne {'maps', 'contacts', 'cameras', 'model', 'window_frames', 'window_fps'}, ou None.

    ⚠ SEUL point d'inférence GPU de la chaîne profondeur (interdit sous WSL2 ici → runtime/R760xa).
    """
    model_key = depth_model_for(session)
    if not is_available(model_key):
        logger.info('[profondeur] analyse ignorée : poids absents (%s)', model_key)
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

    fps_win = depth_window_fps(session)
    windows = getattr(session, 'intersection_windows', None) or []
    n_maps = n_contacts = cams_done = n_window = 0
    for cam in cams:
        try:
            video_path = cam.video_file.path
        except Exception:
            continue
        rows = list(cam.detections.order_by('frame_number').values_list('frame_number', 'timestamp'))
        if not rows:
            continue
        step = max(1, len(rows) // max(1, max_frames_per_cam))
        chosen = [fn for fn, _ in rows[::step][:max_frames_per_cam]]
        map_frames = set(chosen)
        window_fns = frames_in_windows(rows, windows, fps_win)
        objs = {o.frame_number: o for o in
                cam.detections.filter(frame_number__in=set(chosen) | set(window_fns))
                   .only('frame_number', 'detections', 'timestamp')}
        # Une image de fenêtre sans objet n'apporte rien (pas de carte stockée) : pas d'inférence.
        window_fns = [fn for fn in window_fns if fn not in map_frames and objs.get(fn) is not None
                      and any(_has_bbox_obj(d) for d in (objs[fn].detections or []))]
        plan = sorted(map_frames | set(window_fns))

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            continue
        pos = [None]   # dernière frame lue : avancer SÉQUENTIELLEMENT dans une fenêtre

        def _read(fn):
            if pos[0] is None or fn <= pos[0] or fn - pos[0] > 48:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(fn))
                pos[0] = fn - 1
            while pos[0] < fn - 1:
                if not cap.grab():
                    return None
                pos[0] += 1
            ok, fr = cap.read()
            pos[0] = fn
            return fr if ok else None

        try:
            for fn in plan:
                frame = _read(fn)
                if frame is None:
                    continue
                h, w = frame.shape[:2]
                try:
                    depth_m, focal_px = estimate_depth(frame, device, model_key=model_key)
                except Exception:
                    logger.warning('[profondeur] estimate_depth a échoué (frame %s)', fn, exc_info=True)
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
                            logger.warning('[profondeur] save detections %s échoué', fn, exc_info=True)

                if fn not in map_frames:
                    n_window += 1
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
        logger.info('[profondeur] analyse %s (%s) : cumul %d cartes, %d images de fenêtre, '
                    '%d contacts', cam.position, model_key, n_maps, n_window, n_contacts)

    return {'maps': n_maps, 'contacts': n_contacts, 'cameras': cams_done, 'model': model_key,
            'window_frames': n_window, 'window_fps': fps_win}


def depth_model_for(session) -> str:
    """Le modèle de profondeur de la session : `config['depth_model']` s'il est déclaré au moteur,
    sinon le défaut du moteur (ZoeDepth KITTI depuis le 2026-09-28)."""
    from wama.common.backends.depth_engine import DEFAULT_DEPTH_MODEL, DEPTH_MODELS
    key = ((getattr(session, 'config', None) or {}).get('depth_model') or '').strip()
    return key if key in DEPTH_MODELS else DEFAULT_DEPTH_MODEL


def stored_depth_model(session) -> str:
    """Le modèle qui a produit les cartes STOCKÉES (écrit par l'étage 1 depuis le 2026-09-28).
    Absent = cartes antérieures, toutes produites par Depth Pro."""
    return ((getattr(session, 'results_summary', None) or {}).get('depth_model') or 'depthpro')


PLANE_MAX_FRAMES = 60


def _has_road_mask(detections) -> bool:
    return any(d.get('type') == 'road_mask' and len(d.get('polygon') or []) >= 3
               for d in (detections or []))


def ground_plane_from_stored_depth(session, position):
    """ÉTAGE 2 (CALCUL) — plan de sol d'UNE caméra depuis les cartes stockées, échelle ANCRÉE.

    Rend {pitch_deg, height_m, height_fit_m, scale, anchored, frames, n_inliers} ou
    {'skipped': raison}. AUCUNE inférence (sûr en CPU/WSL2) : relit `DepthFrame`, déprojette la
    zone roulable avec fx ET fy du rig, ajuste le plan (briques pures), puis :
      • modèle à échelle métrique déclarée (Depth Pro) : hauteur = hauteur ajustée, `scale` = 1 ;
      • modèle à échelle à ancrer (ZoeDepth) : le PITCH ne dépend pas de l'échelle, la hauteur
        ajustée si — `scale` = hauteur de référence du rig / hauteur ajustée, et la hauteur rendue
        EST la référence. La profondeur reste ainsi indépendante du pinhole (`§E.2`).

    Seules les images portant un VRAI masque de route (YOLOPv2) comptent : le repli « bas d'image »
    prenait carrosserie et habitacle (mesuré le 2026-09-28) — pas de masque, pas de plan.
    Convention : pitch > 0 = caméra penchée vers le bas (corrigée le 2026-09-28).
    """
    from wama.common.backends.depth_engine import depth_model_spec
    from wama_data.functions.geometry.depth_geometry import anchor_depth_scale
    from .prediction_adapter import camera_geometry

    cam = session.cameras.filter(position=position).first()
    if cam is None:
        return {'skipped': 'caméra absente'}
    dframes = list(cam.depth_frames.order_by('frame_number'))
    if not dframes:
        return {'skipped': 'aucune carte stockée'}   # étage 1 pas encore lancé

    det_by_fn = dict(cam.detections
                     .filter(frame_number__in=[d.frame_number for d in dframes])
                     .values_list('frame_number', 'detections'))
    ow, oh = (cam.width or 0), (cam.height or 0)
    # Focales RÉELLES du rig (source unique `camera_geometry`), horizontale ET verticale : elles
    # diffèrent (110° H / 61° V avant-arrière → fx ≈ 134, fy ≈ 210 px). Jusqu'au 2026-09-28 la
    # déprojection prenait la focale unique ESTIMÉE par le modèle (`df.focal_px`) pour les deux
    # axes — mesuré ce jour-là : Depth Pro l'estime ~2× trop grande sur ce rig grand-angle.
    # Repli sur la focale stockée si la géométrie de la caméra est inconnue.
    geo = camera_geometry(session).get(position) or {}
    # Au plus `PLANE_MAX_FRAMES` cartes, réparties dans le temps : depuis l'échantillon des
    # fenêtres (2026-09-28) une caméra en porte ~2 000, et le plan n'en demande pas tant.
    usable = [df for df in dframes if ow and oh and _has_road_mask(det_by_fn.get(df.frame_number))]
    if len(usable) > PLANE_MAX_FRAMES:
        step = len(usable) / float(PLANE_MAX_FRAMES)
        usable = [usable[int(i * step)] for i in range(PLANE_MAX_FRAMES)]
    all_pts = []
    frames_used = 0
    for df in usable:
        dets = det_by_fn.get(df.frame_number)
        depth = _load_depth_map(df)
        if depth is None:
            continue
        h, w = depth.shape[:2]
        if geo.get('fov_h') and geo.get('fov_v'):
            focal_px = w / (2.0 * math.tan(math.radians(geo['fov_h']) / 2.0))
            focal_y_px = h / (2.0 * math.tan(math.radians(geo['fov_v']) / 2.0))
        else:
            focal_px = df.focal_px or (0.8 * w)   # focale DÉJÀ à l'échelle de la carte stockée
            focal_y_px = None
        # Masque roulable à l'échelle de la carte : polygones en px d'origine → (sx, sy).
        drivable = _rasterize_drivable(dets, h, w, sx=w / float(ow), sy=h / float(oh))
        pts = deproject_depth(depth, focal_px, mask=drivable, focal_y_px=focal_y_px,
                              z_min=0.5, z_max=60.0, max_points=4000)
        if len(pts) < 50:
            continue
        all_pts.append(pts)
        frames_used += 1

    if frames_used < 2 or not all_pts:
        return {'skipped': 'moins de 2 cartes avec un masque de route', 'frames': frames_used}
    fit = fit_plane_ransac(np.concatenate(all_pts, axis=0), min_inliers=300)
    if fit is None:
        return {'skipped': 'aucun plan (RANSAC)', 'frames': frames_used}
    normal, offset, n_inl, _rms = fit
    pitch_deg, height_fit = plane_pitch_height(normal, offset)   # brique pure

    spec = depth_model_spec(stored_depth_model(session))
    if spec['metric_scale']:
        scale, height_m, anchored = 1.0, height_fit, False
        plausible = 1.0 <= height_m <= 4.0
    else:
        height_m = float(geo.get('height_m') or 0.0)
        scale = anchor_depth_scale(height_fit, height_m)
        anchored, plausible = True, scale is not None
    out = {'pitch_deg': round(pitch_deg, 2), 'height_m': round(height_m, 3),
           'height_fit_m': round(height_fit, 3), 'scale': round(scale, 4) if scale else None,
           'anchored': anchored, 'frames': frames_used, 'n_inliers': int(n_inl)}
    # Garde-fous physiques (rig ENA) : hors plage → repli homographie plutôt qu'une calib absurde.
    if not plausible or not (-10.0 <= pitch_deg <= 35.0):
        logger.info('[profondeur] plan de sol %s hors plage (%s) — repli homographie', position, out)
        return {'skipped': 'hors plage physique', **out}
    logger.info('[profondeur] plan de sol %s : %s', position, out)
    return out


def estimate_ground_plane_ph(session, position):
    """ÉTAGE 2 (CALCUL) — (pitch_deg, height_m) du plan de sol, ou None (repli homographie) : la
    graine que `store_ground_calib` fait scorer par `estimate_camera`. Détail et ancrage de
    l'échelle : `ground_plane_from_stored_depth`."""
    res = ground_plane_from_stored_depth(session, position)
    if 'skipped' in res:
        return None
    return (res['pitch_deg'], res['height_m'])


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


def depth_distance_report(session, max_frames=12, scales=None):
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

    `scales` : {position: facteur} ancré par l'étage 2 (`ground_plane_from_stored_depth`). Les
    profondeurs STOCKÉES sont brutes : si le modèle qui les a produites ne rend pas de mètres
    exploitables tels quels, une caméra SANS facteur est écartée (et comptée) — comparer au pinhole
    une profondeur à un facteur 3 près mesurerait le facteur, pas le désaccord.

    Retourne un dict de métriques (aussi persisté par l'appelant dans
    results_summary['depth_report']), ou None si indisponible/insuffisant.
    """
    from wama.common.backends.depth_engine import depth_model_spec
    model_key = stored_depth_model(session)
    metric = depth_model_spec(model_key)['metric_scale']
    scales = dict(scales or {})
    diffs_pin, diffs_hom = [], []          # usage 3 : |profondeur − pinhole| / − homographie
    art_pin, clean_pin = [], []            # usage 1 : |profondeur − pinhole| reflets vs propres
    frames_used = 0
    n_obj = 0
    cams_unscaled = []

    # Lecture PURE : n'agrège que ce que l'étage 1 (`run_depth_analysis`) a déjà écrit
    # (`depth_distance_m` sur les détections). Aucune inférence GPU, aucune écriture — sûr en
    # CPU/WSL2, re-jouable à volonté. Sans analyse préalable → aucune donnée → None (repli).
    for cam in session.cameras.all():
        k = scales.get(cam.position) or (1.0 if metric else None)
        if k is None:
            cams_unscaled.append(cam.position)
            continue
        for fn, det in (cam.detections.order_by('frame_number')
                        .values_list('frame_number', 'detections')):
            hit = False
            for d in (det or []):
                dd = d.get('depth_distance_m')
                if dd is None or not _usable_det(d):
                    continue
                hit = True
                n_obj += 1
                dd = float(dd) * k
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
        logger.info('[profondeur] cross-check distance : pas assez d\'observations '
                    '(caméras sans échelle ancrée : %s)', cams_unscaled or 'aucune')
        return None

    def _med(xs):
        return round(float(np.median(xs)), 2) if xs else None

    report = {
        'model': model_key,
        'scales': {p: round(v, 4) for p, v in scales.items()},
        'cameras_unscaled': cams_unscaled,
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
    logger.info('[profondeur] Distance (usage 3) : désaccord médian profondeur↔pinhole = %s m '
                '(%d obj, %d frames) ; ↔homographie = %s m (%d obj)',
                report['disagree_pinhole_m'], n_obj, frames_used,
                report['disagree_homography_m'], report['n_homography'])
    if art_pin:
        verdict = ('reflets PLUS incohérents' if (report['reflet_pinhole_m'] or 0)
                   > (report['clean_pinhole_m'] or 0) else 'signal non concluant')
        logger.info('[profondeur] Reflets (usage 1) : désaccord profondeur↔pinhole reflets=%s m (%d) '
                    'vs propres=%s m (%d) — %s', report['reflet_pinhole_m'], report['reflet_n'],
                    report['clean_pinhole_m'], report['clean_n'], verdict)
    return report
