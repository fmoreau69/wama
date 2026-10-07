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

from wama_data.functions.geometry.frame_edges import touches_side_edge

logger = logging.getLogger(__name__)

Y_MIN, Y_MAX = 2.0, 15.0


def calibration_reference(results_summary) -> set:
    """Gids des immobiles sur lesquels la calibration se JUGE : la référence compacte du tracking
    (`calibration_reference_gids`, même vide — une liste vide est une mesure), sinon, pour un
    tracking antérieur à elle, les garés."""
    rs = results_summary or {}
    ref = rs.get('calibration_reference_gids')
    return set(ref if ref is not None else (rs.get('stationary_global_tracks') or []))


def calibration_geometry(geo):
    """La géométrie de caméra avec laquelle une calibration sol est faite — champ, orientation, montage,
    distorsion : tout ce que `_eval_params` en lit. Retenue avec la calibration (`store_ground_calib`)."""
    mount = geo.get('mount') or (0.0, 0.0)
    return {'k1': round(float(geo.get('k1') or 0.0), 4), 'fov_h': round(float(geo.get('fov_h') or 0.0), 3),
            'fov_v': round(float(geo.get('fov_v') or 0.0), 3), 'yaw': round(float(geo.get('yaw') or 0.0), 3),
            'mount': [round(float(mount[0]), 3), round(float(mount[1]), 3)]}


def stale_calibrations(session):
    """Caméras dont la calibration sol a été faite avec une AUTRE géométrie que celle en service — ou ne dit
    pas avec laquelle (calibration antérieure au 2026-10-07). Vécu : basculer ⚑ measured_lens_distortion
    changeait la distorsion sans recalibrer — le tracking gardait des tangages estimés pour l'ancienne, sans
    rien dire. Le tracking recalibre quand cette liste n'est pas vide."""
    from .prediction_adapter import camera_geometry
    geo = camera_geometry(session)
    out = []
    for pos, cal in (((session.config or {}).get('ground_calib')) or {}).items():
        if isinstance(cal, dict) and pos in geo and cal.get('geometry') != calibration_geometry(geo[pos]):
            out.append(pos)
    return sorted(out)


def _collect_static_obs(session, position, max_gids=40, max_per_gid=120):
    """Observations bas-de-bbox des immobiles de RÉFÉRENCE sur une caméra : (u, v, t_gps,
    dist_pinhole). La référence est `calibration_reference_gids` (immobiles compacts) et non les
    garés : sous ⚑ parked_off_road ces derniers tolèrent le bruit de placement que la calibration
    doit mesurer, et toutes les caméras étaient rejetées (2026-10-01). Repli sur les garés pour une
    session dont le tracking est antérieur à la référence."""
    from ..models import DetectionFrame
    from .prediction_adapter import video_to_gps_time
    stat = calibration_reference(session.results_summary)
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
            # bbox coupée au bord latéral : bas-de-bbox non fiable.
            # Même notion que `prediction_adapter.pinhole_ego`, désormais partagée
            # (`geometry.frame_edges`) — mais la MARGE reste celle d'ici (6 px) : l'unifier
            # à 8 px changerait le jeu d'observations de l'estimateur, donc son pitch.
            # C'est une décision à mesurer, pas un effet de bord (`CHAINE §H ③`).
            if touches_side_edge(bb, size[0], size[1], margin_px=6.0):
                continue
            if len(obs[gid]) < max_per_gid:
                # Temps GPS (base de la trajectoire navette), pas le temps vidéo : cf.
                # `video_to_gps_time` — l'écart atteint ~5 min en fin de session ENA.
                obs[gid].append(((bb[0] + bb[2]) / 2.0, bb[3],
                                 video_to_gps_time(session, df.timestamp), float(dist)))
    obs = dict(sorted(obs.items(), key=lambda kv: -len(kv[1]))[:max_gids])
    return {g: v for g, v in obs.items() if len(v) >= 8}, size


def _eval_params(pitch_deg, height_m, obs, size, geo, sh_traj, fov_v_deg, k1=0.0, radial_k=0.0):
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
    if radial_k:
        cal['radial_inverse'] = radial_k          # distorsion de la caméra (⚑ lens_distortion)
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
    # Une calibration doit expliquer la MAJORITÉ de sa référence. Sans ce plancher, le coût (moyenne
    # sur les seuls immobiles restés dans la portée) RÉCOMPENSAIT les paramètres qui en écartent le plus :
    # mesuré le 2026-10-03 sur la latérale gauche, un tangage de −0,5° renvoyait l'essentiel des points
    # à 100 m et gardait 4 voitures sur 24 (étalement 0,09 m) — optimum dégénéré, calibration refusée.
    if len(spreads) < max(3, (len(obs) + 1) // 2):
        return None
    spread = sum(spreads) / len(spreads)
    scale = sum(scale_errs) / len(scale_errs)
    return spread + 0.5 * scale, spread, scale, len(spreads)


def estimate_camera(session, position='front', with_k1=False, seed=None):
    """Grille (pitch, height[, k1]) → meilleurs paramètres + rapport avant/après.
    `with_k1=False` (défaut) : recherche pitch seul à hauteur physique (~8 s/caméra) —
    k1 a été ÉCARTÉ comme levier (sature la borne sans gain, cf. CHANGELOG 8a19577).
    with_k1=True reste dispo pour le diagnostic."""
    from .prediction_adapter import (camera_geometry, make_local_frame,
                                     shuttle_trajectory, antenna_offset, CAMERA_FOV_V)
    from .ego_pose import effective_gps_track   # ⚑ shuttle_filter : l'ancre ego-motion de 2a
    gt = effective_gps_track(session)
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
    # Champ VERTICAL effectif de `camera_geometry` (source unique : surcharge de session, FOV mesuré)
    # — pas la table du rig. Jusqu'au 2026-10-02 la table (31° aux latérales) était combinée au champ
    # HORIZONTAL effectif (97° surchargé) : focales incohérentes, distances latérales ×1,8.
    fov_v = geo.get('fov_v') or CAMERA_FOV_V.get(position, 61.0)
    # Distorsion de la caméra (`camera_geometry`, ⚑ lens_distortion) : le MÊME modèle que la
    # projection du suivi — sinon la calibration ajusterait un faux tangage pour la compenser.
    _rk = float(geo.get('k1') or 0.0)

    base = _eval_params(0.0, 2.4, obs, size, geo, sh_traj, fov_v, radial_k=_rk)
    # ── Mode « graine externe » (⚑ depth_estimation) : au lieu de la recherche par grille, on SCORE
    # un couple (pitch, hauteur) fourni par une autre source (profondeur monoculaire Depth Pro →
    # plan de sol, cf. depth_estimator.estimate_ground_plane_ph). Le scoring reste ICI, source
    # UNIQUE de la métrique `placement_spread` → A/B loyal profondeur vs homographie.
    if seed is not None:
        sp_deg, sh_m = float(seed[0]), float(seed[1])
        r = _eval_params(sp_deg, sh_m, obs, size, geo, sh_traj, fov_v, radial_k=_rk)
        if r is None:
            return None
        return {
            'position': position,
            'pitch_deg': sp_deg,
            'k1': 0.0,
            'radial_k': _rk,
            'height_m': sh_m,
            'n_objects': r[3],
            'spread_m': round(r[1], 2),
            'scale_err_m': round(r[2], 2),
            'baseline_spread_m': round(base[1], 2) if base else None,
            'baseline_scale_err_m': round(base[2], 2) if base else None,
            'source': 'depth',
            'geometry': calibration_geometry(geo),
        }
    # Hauteur FIXÉE au physique (rig ENA ~2.4 m) : la surface de coût est dégénérée
    # pitch⟷hauteur (l'optimum libre fuit vers des hauteurs absurdes). On résout donc
    # pitch × k1 à hauteur connue — les deux vrais inconnus optiques.
    best, best_p, best_k, best_h = None, 0.0, 0.0, 2.4
    _ks = [k100 / 100.0 for k100 in range(-45, 46, 3)] if with_k1 else [0.0]
    for h10 in (23, 24, 25):               # hauteur 2.3 … 2.5 m (plage physique)
        for p10 in range(-50, 305, 5):     # pitch −5.0° … +30.0° par 0.5°
            for k1 in _ks:                  # k1 −0.45 … +0.45 par 0.03 (si with_k1, diagnostic Brown)
                r = _eval_params(p10 / 10.0, h10 / 10.0, obs, size, geo, sh_traj, fov_v, k1=k1,
                                 radial_k=_rk)
                if r and (best is None or r[0] < best[0]):
                    best, best_p, best_k, best_h = r, p10 / 10.0, k1, h10 / 10.0
    if best is None:
        return None
    return {
        'position': position,
        'pitch_deg': best_p,
        'k1': best_k,
        'radial_k': _rk,
        'height_m': best_h,
        'n_objects': best[3],
        'spread_m': round(best[1], 2),
        'scale_err_m': round(best[2], 2),
        'baseline_spread_m': round(base[1], 2) if base else None,
        'baseline_scale_err_m': round(base[2], 2) if base else None,
        'geometry': calibration_geometry(geo),
    }


def store_ground_calib(session, positions=('front', 'rear', 'left', 'right'),
                       min_objects=6, max_spread_m=2.5, depth_seeds=None):
    """Estime et PERSISTE la calibration sol par caméra dans
    `session.config['ground_calib']` = {pos: {pitch_deg, height_m, spread_m,
    scale_err_m, n_objects}}. N'écrit QUE les caméras FIABLES : ≥ min_objects
    stationnés ET étalement résiduel ≤ max_spread_m (une calib à 5-6 m d'étalement
    ne converge pas → l'appliquer DÉGRADERAIT le placement, on la rejette).
    Retourne le résumé (avec la raison du skip).

    Étape 2a du plan de calibration sol (CAM_ANALYZER_CHAINE_TRAITEMENT.md) :
    l'ANGLE seul (le gain sûr, ×5 mesuré). L'échelle absolue viendra de 2b (ortho).

    `depth_seeds` : {pos: (pitch_deg, height_m) | None} déjà calculées par l'appelant (passe
    `depth_calc`, qui ajuste chaque plan UNE fois) ; absent → calculées ici sous ⚑ depth_estimation.
    """
    cfg = session.config or {}
    calib = dict(cfg.get('ground_calib') or {})
    report = {}
    # ⚑ depth_estimation (défaut OFF) : quand ON, la source du plan de sol est la profondeur
    # monoculaire (Depth Pro) au lieu de la recherche homographique. UN seul flag global pour toute
    # l'amélioration profondeur (décision 2026-08-05 — pas de sous-flags qui polluent ⚑ Modes).
    _use_depth = False
    try:
        from .features import enabled as _feat_enabled
        _use_depth = bool(_feat_enabled(session, 'depth_estimation'))
    except Exception:
        _use_depth = False
    for pos in positions:
        try:
            seed = None
            if _use_depth:
                if depth_seeds is not None:
                    seed = depth_seeds.get(pos)
                else:
                    from .depth_estimator import estimate_ground_plane_ph
                    seed = estimate_ground_plane_ph(session, pos)  # (pitch_deg, height_m) | None
            # seed None (depth OFF ou échec) → repli sur la recherche homographique par grille.
            r = estimate_camera(session, pos, with_k1=False, seed=seed)
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
            # SOURCE du plan de sol : 'depth' (graine profondeur scorée) ou 'homographie'
            # (recherche par grille). Permet au pipeline de RECALCULER quand la bascule
            # ⚑ depth_estimation change sans avoir à effacer la calib à la main.
            'source': r.get('source', 'homographie'),
            # la géométrie de caméra de CE calcul : une autre en service la rend périmée (`stale_calibrations`)
            'geometry': r.get('geometry'),
        }
        report[pos] = calib[pos]
    cfg['ground_calib'] = calib
    session.config = cfg
    session.save(update_fields=['config'])
    return report
