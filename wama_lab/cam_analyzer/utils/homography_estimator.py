"""
Estimation AUTO de la calibration sol (étape 2 du chantier homographie — emplacement
prévu dès la conception, cf. header de ground_projection.py).

Principe (idée Fabien « fusionner proches et lointains sur assez de pas de temps ») :
un objet STATIQUE (véhicule stationné, marquage) est vu à 12 m puis à 4 m avec un
déplacement ego CONNU entre les deux. Si la projection sol est juste, toutes ses
observations projetées en MONDE coïncident ; si le tangage/la hauteur sont faux, elles
s'étalent le long de l'axe d'approche. On résout donc (pitch, height) par caméra en
MINIMISANT l'étalement monde des objets statiques — des centaines d'observations par
session, toutes distances confondues.

Garde-fou d'échelle : l'étalement seul est quasi insensible à une compression globale
(hauteur trop faible → tout se rapproche → étalement réduit). On ancre l'échelle sur la
distance pinhole par hauteur de classe (non biaisée en moyenne) : terme
|Y_sol − dist_pinhole| médian.

v1 : solveur + RAPPORT (mesure avant/après). L'intégration au positionnement des
objets (fusion bas-de-bbox ⟷ pinhole) ne se fera qu'après validation des chiffres —
bascule ⚑ auto_ground_calib, OFF par défaut.
"""
import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)

Y_MIN, Y_MAX = 2.0, 15.0


def _collect_static_obs(session, position, max_gids=40, max_per_gid=120):
    """Observations bas-de-bbox des STATIONNÉS sur une caméra : (u, v, t, dist_pinhole)."""
    from ..models import DetectionFrame
    stat = set((session.results_summary or {}).get('stationary_global_tracks') or [])
    if not stat:
        return {}, (384, 248)
    cam = session.cameras.filter(position=position).first()
    if not cam:
        return {}, (384, 248)
    size = (cam.width or 384, cam.height or 248)
    obs = defaultdict(list)
    qs = (DetectionFrame.objects.filter(camera=cam)
          .order_by('frame_number').only('detections', 'timestamp'))
    for df in qs.iterator(chunk_size=1000):
        for d in (df.detections or []):
            gid = d.get('global_track_id')
            if gid not in stat or d.get('predicted'):
                continue
            bb = d.get('bbox')
            dist = d.get('distance_m') or d.get('dist_euclid_m')
            if not bb or len(bb) < 4 or not dist:
                continue
            if bb[0] <= 6 or bb[2] >= size[0] - 6:
                continue   # bbox coupée : bas-de-bbox non fiable
            if len(obs[gid]) < max_per_gid:
                obs[gid].append(((bb[0] + bb[2]) / 2.0, bb[3], df.timestamp, float(dist)))
    obs = dict(sorted(obs.items(), key=lambda kv: -len(kv[1]))[:max_gids])
    return {g: v for g, v in obs.items() if len(v) >= 8}, size


def _eval_params(pitch_deg, height_m, obs, size, geo, sh_traj, fov_v_deg, k1=0.0):
    """Coût = étalement monde des statiques + ancrage d'échelle sur le pinhole.
    `k1` : distorsion radiale (Brown-Conrady) — les dômes AXIS 110° ne sont pas
    rectilinéaires, le résiduel d'étalement à k1=0 en est la signature."""
    from .ground_projection import GroundProjector
    from .calibration import intrinsics_from_fov
    from .prediction_adapter import ego_to_world, _shuttle_pose_at
    intr = intrinsics_from_fov(size[0], size[1], geo['fov_h'], fov_v_deg)
    cal = dict(intr, height_m=height_m, pitch_deg=pitch_deg,
               hfov_deg=geo['fov_h'], lens_type='rectilinear')
    if k1:
        cal['distortion'] = [k1, 0.0, 0.0, 0.0, 0.0]
    try:
        gp = GroundProjector(cal, size)
        if not gp.available:
            return None
    except Exception:
        return None
    yaw = math.radians(geo['yaw'])
    mnt = geo.get('mount') or (0.0, 0.0)
    spreads, scale_errs = [], []
    for gid, rows in obs.items():
        pts, dys = [], []
        for u, v, t, dist in rows:
            xy = gp.project(u, v)
            if not xy:
                continue
            X, Y = xy
            if not (Y_MIN <= Y <= Y_MAX):
                continue
            se, sn, sh = _shuttle_pose_at(sh_traj, t)
            lat_v = Y * math.sin(yaw) + X * math.cos(yaw) + mnt[0]
            lon_v = Y * math.cos(yaw) - X * math.sin(yaw) + mnt[1]
            e, n = ego_to_world(se, sn, sh, lat_v, lon_v)
            pts.append((e, n))
            dys.append(abs(math.hypot(lat_v, lon_v) - dist))
        if len(pts) < 6:
            continue
        me = sorted(p[0] for p in pts)[len(pts) // 2]
        mn = sorted(p[1] for p in pts)[len(pts) // 2]
        d2 = sorted(math.hypot(p[0] - me, p[1] - mn) for p in pts)
        spreads.append(d2[int(len(d2) * 0.7)])       # p70 robuste aux outliers
        scale_errs.append(sorted(dys)[len(dys) // 2])
    if len(spreads) < 3:
        return None
    spread = sum(spreads) / len(spreads)
    scale = sum(scale_errs) / len(scale_errs)
    return spread + 0.5 * scale, spread, scale, len(spreads)


def estimate_camera(session, position='front', with_k1=False):
    """Grille (pitch, height[, k1]) → meilleurs paramètres + rapport avant/après.
    `with_k1=False` (défaut) : recherche pitch seul à hauteur physique (~8 s/caméra) —
    k1 a été ÉCARTÉ comme levier (sature la borne sans gain, cf. CHANGELOG 8a19577).
    with_k1=True reste dispo pour le diagnostic."""
    from .prediction_adapter import (camera_geometry, make_local_frame,
                                     shuttle_trajectory, antenna_offset, CAMERA_FOV_V)
    gt = session.gps_track or []
    if len(gt) < 2:
        return None
    to_local = make_local_frame(gt)
    sh_traj = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    geo = camera_geometry(session).get(position)
    if geo is None or len(sh_traj) < 5:
        return None
    obs, size = _collect_static_obs(session, position)
    if not obs:
        return None
    fov_v = CAMERA_FOV_V.get(position, 61.0)

    base = _eval_params(0.0, 2.4, obs, size, geo, sh_traj, fov_v)
    # Hauteur FIXÉE au physique (rig ENA ~2.4 m) : la surface de coût est dégénérée
    # pitch⟷hauteur (l'optimum libre fuit vers des hauteurs absurdes). On résout donc
    # pitch × k1 à hauteur connue — les deux vrais inconnus optiques.
    best, best_p, best_k, best_h = None, 0.0, 0.0, 2.4
    _k_range = range(-45, 46, 3) if with_k1 else range(0, 1)   # k1 écarté par défaut
    for h10 in (23, 24, 25):               # hauteur 2.3 … 2.5 m (plage physique)
        for p10 in range(-50, 305, 5):     # pitch −5.0° … +30.0° par 0.5°
            for k100 in _k_range:           # k1 −0.45 … +0.45 par 0.03 (si with_k1)
                r = _eval_params(p10 / 10.0, h10 / 10.0, obs, size, geo, sh_traj,
                                 fov_v, k1=k100 / 100.0)
                if r and (best is None or r[0] < best[0]):
                    best, best_p, best_k, best_h = r, p10 / 10.0, k100 / 100.0, h10 / 10.0
    if best is None:
        return None
    return {
        'position': position,
        'pitch_deg': best_p,
        'k1': best_k,
        'height_m': best_h,
        'n_objects': best[3],
        'spread_m': round(best[1], 2),
        'scale_err_m': round(best[2], 2),
        'baseline_spread_m': round(base[1], 2) if base else None,
        'baseline_scale_err_m': round(base[2], 2) if base else None,
    }


def store_ground_calib(session, positions=('front', 'rear', 'left', 'right'),
                       min_objects=6, max_spread_m=2.5):
    """Estime et PERSISTE la calibration sol par caméra dans
    `session.config['ground_calib']` = {pos: {pitch_deg, height_m, spread_m,
    scale_err_m, n_objects}}. N'écrit QUE les caméras FIABLES : ≥ min_objects
    stationnés ET étalement résiduel ≤ max_spread_m (une calib à 5-6 m d'étalement
    ne converge pas → l'appliquer DÉGRADERAIT le placement, on la rejette).
    Retourne le résumé (avec la raison du skip).

    Étape 2a du plan de calibration sol (CAM_ANALYZER_CHAINE_TRAITEMENT.md) :
    l'ANGLE seul (le gain sûr, ×5 mesuré). L'échelle absolue viendra de 2b (ortho).
    """
    cfg = session.config or {}
    calib = dict(cfg.get('ground_calib') or {})
    report = {}
    for pos in positions:
        try:
            r = estimate_camera(session, pos, with_k1=False)
        except Exception:
            logger.warning('estimate_camera %s failed', pos, exc_info=True)
            r = None
        if not r or r['n_objects'] < min_objects:
            report[pos] = {'skipped': 'trop peu de stationnés',
                           'n_objects': (r or {}).get('n_objects', 0)}
            calib.pop(pos, None)
            continue
        if r['spread_m'] > max_spread_m:
            report[pos] = {'skipped': 'étalement trop grand (calib non convergée)',
                           'spread_m': r['spread_m'], 'n_objects': r['n_objects']}
            calib.pop(pos, None)   # ne pas garder une vieille calib douteuse non plus
            continue
        calib[pos] = {
            'pitch_deg': r['pitch_deg'], 'height_m': r['height_m'],
            'spread_m': r['spread_m'], 'scale_err_m': r['scale_err_m'],
            'n_objects': r['n_objects'],
        }
        report[pos] = calib[pos]
    cfg['ground_calib'] = calib
    session.config = cfg
    session.save(update_fields=['config'])
    return report
