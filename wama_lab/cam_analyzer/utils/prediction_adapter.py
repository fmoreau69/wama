"""
Adaptateur cam_analyzer ↔ Prédiction.

Reconstruit les trajectoires MONDE (repère métrique local) de la navette et des objets
suivis, puis calcule TTC/PET navette↔objet via le cœur Prédiction (common.prediction).

Pourquoi le repère monde : Prédiction extrapole les trajectoires ; comme la navette bouge,
un objet à position ego constante avance en réalité → il faut le monde pour un TTC juste.

Position ego de l'objet = reconstruction PINHOLE (distance_m + cap du bbox), plus fiable
que l'homographie (comprimée/biaisée). Puis ego → monde via GPS (position + cap navette).
"""
import math

import numpy as np

from wama.common.prediction import (point_traj_to_shape, extrapolate_speed_accel,
                                   extrapolate_kalman, collision_detection)

# Dimensions (longueur, largeur) en m par classe pour les empreintes.
CLASS_DIMS = {
    'car': (4.5, 1.8), 'truck': (8.0, 2.5), 'bus': (10.0, 2.8),
    'person': (0.6, 0.6), 'bicycle': (1.8, 0.6), 'motorcycle': (2.0, 0.8),
}
SHUTTLE_DIMS = (5.5, 2.1)   # navette

# Orientation de montage de chaque caméra (deg, sens horaire depuis l'avant véhicule).
CAMERA_YAW = {'front': 0.0, 'right': 90.0, 'rear': 180.0, 'left': -90.0}


def cam_to_vehicle(lateral, longitudinal, yaw_deg):
    """Position repère caméra → repère VÉHICULE commun (via l'orientation de la caméra)."""
    t = math.radians(yaw_deg)
    s, c = math.sin(t), math.cos(t)
    return (longitudinal * s + lateral * c, longitudinal * c - lateral * s)


def make_local_frame(gps_track):
    """Origine = 1er point GPS. Retourne to_local(lat, lon) -> (east, north) en mètres."""
    lat0, lon0 = gps_track[0]['lat'], gps_track[0]['lon']
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))

    def to_local(lat, lon):
        return ((lon - lon0) * m_lon, (lat - lat0) * m_lat)
    return to_local


def shuttle_trajectory(gps_track, to_local):
    """GPS → [t, east, north, heading_deg] (points avec cap valide, triés)."""
    rows = []
    for p in gps_track:
        h = p.get('heading')
        if h is None:
            continue
        e, n = to_local(p['lat'], p['lon'])
        rows.append((p['ts'], e, n, h))
    rows.sort(key=lambda r: r[0])
    return np.array(rows) if rows else np.zeros((0, 4))


def pinhole_ego(det, iw, ih, fov_v_deg=60.0):
    """Détection → position ego (latéral droite, longitudinal avant) en m, ou None.
    Reconstruction pinhole (comme l'affichage) : robuste au biais de l'homographie."""
    dm = det.get('distance_m')
    bb = det.get('bbox')
    if dm is None or not (isinstance(bb, (list, tuple)) and len(bb) >= 4):
        return None
    if bb[0] <= 8 or bb[2] >= iw - 8:      # coupé au bord → cap non fiable
        return None
    focal = ih / (2.0 * math.tan(math.radians(fov_v_deg) / 2.0))
    bcx = (bb[0] + bb[2]) / 2.0
    lateral = dm * (bcx - iw / 2.0) / focal
    return lateral, dm       # [latéral, longitudinal]


def ego_to_world(shuttle_e, shuttle_n, heading_deg, lateral, longitudinal):
    """Position ego (latéral, longitudinal) + pose navette → position monde (east, north)."""
    h = math.radians(heading_deg)
    east = shuttle_e + longitudinal * math.sin(h) + lateral * math.cos(h)
    north = shuttle_n + longitudinal * math.cos(h) - lateral * math.sin(h)
    return east, north


def _ensure_endpoint(hist, t0):
    """Ajoute un point interpolé à t0 en fin d'historique (grilles futures alignées)."""
    hist = np.asarray(hist, dtype=float)
    if abs(hist[-1, 0] - t0) < 1e-6:
        return hist
    a, b = hist[-2], hist[-1]
    f = (t0 - a[0]) / max(b[0] - a[0], 1e-9)
    pt = np.array([t0, a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2])])
    return np.vstack([hist, pt])


def _shuttle_pose_at(shuttle_traj, ts):
    """Interpolation linéaire de la pose navette (east, north, heading) à ts."""
    t = shuttle_traj[:, 0]
    if ts <= t[0]:
        return shuttle_traj[0, 1], shuttle_traj[0, 2], shuttle_traj[0, 3]
    if ts >= t[-1]:
        return shuttle_traj[-1, 1], shuttle_traj[-1, 2], shuttle_traj[-1, 3]
    i = int(np.searchsorted(t, ts))
    a, b = shuttle_traj[i - 1], shuttle_traj[i]
    f = (ts - a[0]) / max(b[0] - a[0], 1e-9)
    return a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]), a[3] + f * (b[3] - a[3])


def build_object_world_trajectory(det_rows, shuttle_traj, iw, ih, fov_v_deg=60.0):
    """
    det_rows : liste de (ts, det) pour UN track_id, triés par ts.
    Retourne (T, 3) [t, east, north] de l'objet dans le repère monde, ou None si trop court.
    """
    pts = []
    for ts, det in det_rows:
        ego = pinhole_ego(det, iw, ih, fov_v_deg)
        if ego is None:
            continue
        se, sn, sh = _shuttle_pose_at(shuttle_traj, ts)
        e, n = ego_to_world(se, sn, sh, ego[0], ego[1])
        pts.append((ts, e, n))
    if len(pts) < 3:
        return None
    return smooth_trajectory(np.array(pts), window=5)   # lissage anti-tremblement


def annotate_prediction_indicators(session, method='speed_accel', max_range_m=45.0,
                                 fov_v_deg=60.0, frame_range=None):
    """
    Calcule TTC/PET par PRÉDICTION de trajectoire (navette↔objet) pour chaque détection
    suivie proche et les stocke (`prediction_ttc`/`prediction_pet`). Utilise les TRACKS GLOBAUX
    multi-caméra (`global_track_id`, à calculer avant via annotate_global_tracks) → une
    trajectoire CONTINUE par objet même en passant d'une caméra à l'autre = TTC/PET meilleurs.
    Repli sur `<caméra>:<track_id>` si les tracks globaux ne sont pas encore calculés.
    """
    from collections import defaultdict
    from django.apps import apps
    DF = apps.get_model('cam_analyzer', 'DetectionFrame')
    gt = session.gps_track or []
    if len(gt) < 5:
        return 0
    to_local = make_local_frame(gt)
    sh_traj = shuttle_trajectory(gt, to_local)
    if len(sh_traj) < 5:
        return 0
    cams = [c for c in session.cameras.all()
            if c.position in CAMERA_YAW and DF.objects.filter(camera=c).exists()]
    if not cams:
        return 0
    fps = cams[0].fps or 12.0
    scale = session.gps_time_scale or 1.0
    off = session.gps_time_offset or 0.0

    # Collecte par global_track_id, avec position MONDE de chaque détection (toutes caméras).
    by_gid = defaultdict(list)   # gid -> [(ts, det, frame_obj, e, n, ego_long, class)]
    for c in cams:
        iw = getattr(c, 'width', None) or 384
        ih = getattr(c, 'height', None) or 248
        q = DF.objects.filter(camera=c)
        if frame_range:
            q = q.filter(frame_number__gte=frame_range[0], frame_number__lte=frame_range[1])
        for f in q.only('frame_number', 'detections').order_by('frame_number'):
            ts = f.frame_number / fps * scale + off
            se, sn, sh = _shuttle_pose_at(sh_traj, ts)
            for d in (f.detections or []):
                if d.get('class_name') not in CLASS_DIMS:
                    continue
                gid = d.get('global_track_id')
                if gid is None:
                    if d.get('track_id') is None:
                        continue
                    gid = c.position + ':' + str(d['track_id'])
                ego = pinhole_ego(d, iw, ih, fov_v_deg)
                if ego is None:
                    continue
                xv, yv = cam_to_vehicle(ego[0], ego[1], CAMERA_YAW[c.position])
                e, n = ego_to_world(se, sn, sh, xv, yv)
                by_gid[gid].append((ts, d, f, e, n, ego[1], d.get('class_name', 'car')))

    count, dirty = 0, set()
    for gid, rows in by_gid.items():
        rows.sort(key=lambda r: r[0])
        # Trajectoire monde continue ; dédupliquer les ts identiques (2 caméras) par moyenne.
        agg = {}
        for ts, _, _, e, n, _, _ in rows:
            pe, pn, k = agg.get(ts, (0.0, 0.0, 0))
            agg[ts] = (pe + e, pn + n, k + 1)
        ts_sorted = sorted(agg)
        if len(ts_sorted) < 3:
            continue
        obj_traj = smooth_trajectory(
            np.array([[t, agg[t][0] / agg[t][2], agg[t][1] / agg[t][2]] for t in ts_sorted]), window=5)
        cls = rows[0][6]
        for ts, d, f, e, n, ego_long, _ in rows:
            if ego_long > max_range_m:
                continue
            r = ttc_pet_shuttle_object(sh_traj, obj_traj, ts, method=method, class_name=cls)
            changed = False
            if r['ttc'] is not None:
                d['prediction_ttc'] = round(r['ttc'], 2); changed = True
            if r['pet'] is not None:
                d['prediction_pet'] = round(r['pet'], 2); changed = True
            if changed:
                dirty.add(f)
                count += 1
    for f in dirty:
        f.save(update_fields=['detections'])
    return count


def smooth_trajectory(traj, window=5):
    """Moyenne glissante sur les positions (réduit le tremblement GPS/pinhole)."""
    traj = np.asarray(traj, dtype=float)
    if len(traj) < window or window < 2:
        return traj
    out = traj.copy()
    k = window // 2
    for i in range(len(traj)):
        lo, hi = max(0, i - k), min(len(traj), i + k + 1)
        out[i, 1] = traj[lo:hi, 1].mean()
        out[i, 2] = traj[lo:hi, 2].mean()
    return out


def ttc_pet_shuttle_object(shuttle_traj, obj_traj, t0, horizon_s=5.0,
                           method='speed_accel', class_name='car'):
    """
    Calcule TTC/PET entre la navette et un objet à l'instant t0.
    Prend l'historique jusqu'à t0, extrapole les deux sur `horizon_s`, puis collision SAT.
    Retourne dict {'ttc', 'pet'} (secondes, ou None).
    """
    # Fenêtre navette [t0-2s, t0] en [t, e, n]
    st = shuttle_traj
    mask = (st[:, 0] <= t0 + 1e-6) & (st[:, 0] >= t0 - 2.0)
    sh_hist = st[mask][:, :3]
    ob_hist = obj_traj[(obj_traj[:, 0] <= t0 + 1e-6) & (obj_traj[:, 0] >= t0 - 2.0)]
    if len(sh_hist) < 3 or len(ob_hist) < 3:
        return {'ttc': None, 'pet': None}
    dt = 0.1
    n_future = int(horizon_s / dt)
    extra = extrapolate_kalman if method == 'kalman' else extrapolate_speed_accel
    # Forcer les deux historiques à finir à t0 → grilles futures alignées (t0, t0+dt, …).
    sh_hist = _ensure_endpoint(sh_hist, t0)
    ob_hist = _ensure_endpoint(ob_hist, t0)
    sh_fut = extra(sh_hist, n_future, dt=dt)
    ob_fut = extra(ob_hist, n_future, dt=dt)
    # Aligner les timecodes sur une grille commune pour la collision.
    sh_shape = point_traj_to_shape(sh_fut, *SHUTTLE_DIMS)
    ob_shape = point_traj_to_shape(ob_fut, *CLASS_DIMS.get(class_name, (2.0, 1.0)))
    res = collision_detection(sh_shape, ob_shape)
    return {'ttc': res['ttc'], 'pet': res['pet']}
