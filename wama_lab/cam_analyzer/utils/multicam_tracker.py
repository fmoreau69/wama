"""
Tracker global multi-caméra (repère monde) pour cam_analyzer.

Associe les détections de TOUTES les caméras analysées (avant/arrière/gauche/droite) en
tracks GLOBAUX persistants : un objet garde un seul `global_track_id` en passant d'une
caméra à l'autre (hand-off) → plus de disparition/réapparition au bord du champ, et les
doublons (même objet vu par 2 caméras) partagent l'ID.

Post-traitement (pas de re-détection). Vérifie les caméras réellement analysées.
Association = plus-proche-voisin en repère monde avec gating + prédiction de position.
"""
import math

from django.apps import apps

from .prospect_adapter import (make_local_frame, shuttle_trajectory, pinhole_ego,
                               ego_to_world, _shuttle_pose_at, CLASS_DIMS)

# Orientation de montage de chaque caméra (deg, sens horaire depuis l'avant véhicule).
CAMERA_YAW = {'front': 0.0, 'right': 90.0, 'rear': 180.0, 'left': -90.0}


def _cam_to_vehicle(lateral, longitudinal, yaw_deg):
    """Position dans le repère caméra → repère VÉHICULE commun (via l'orientation caméra)."""
    t = math.radians(yaw_deg)
    s, c = math.sin(t), math.cos(t)
    return (longitudinal * s + lateral * c, longitudinal * c - lateral * s)


def annotate_global_tracks(session, fov_v_deg=60.0, gate_m=3.5, max_gap_s=1.0, frame_range=None):
    """
    Assigne un `global_track_id` à chaque détection (objets suivis) de toutes les caméras
    ANALYSÉES, associées en repère monde. Retourne le nombre de tracks globaux créés.
    """
    DF = apps.get_model('cam_analyzer', 'DetectionFrame')
    gt = session.gps_track or []
    if len(gt) < 5:
        return 0
    to_local = make_local_frame(gt)
    sh_traj = shuttle_trajectory(gt, to_local)
    if len(sh_traj) < 5:
        return 0

    # ── Caméras réellement analysées (position connue + détections présentes) ──
    cams = []
    for c in session.cameras.all():
        if c.position in CAMERA_YAW and DF.objects.filter(camera=c).exists():
            cams.append(c)
    if not cams:
        return 0

    fps = cams[0].fps or 12.0
    scale = session.gps_time_scale or 1.0
    off = session.gps_time_offset or 0.0

    per_cam = {}
    for c in cams:
        iw = getattr(c, 'width', None) or 384
        ih = getattr(c, 'height', None) or 248
        _q = DF.objects.filter(camera=c)
        if frame_range:
            _q = _q.filter(frame_number__gte=frame_range[0], frame_number__lte=frame_range[1])
        frames = {f.frame_number: f for f in _q.only('frame_number', 'detections')}
        per_cam[c.position] = (iw, ih, frames)

    all_fns = sorted({fn for (_, _, frames) in per_cam.values() for fn in frames})
    tracks = []        # {id, e, n, ve, vn, last_t}
    next_id = 1
    dirty = set()

    for fn in all_fns:
        t = fn / fps * scale + off
        se, sn, sh = _shuttle_pose_at(sh_traj, t)
        # Détections de cette frame (toutes caméras) en position monde.
        dets_here = []
        for pos, (iw, ih, frames) in per_cam.items():
            f = frames.get(fn)
            if not f:
                continue
            for d in (f.detections or []):
                if d.get('class_name') not in CLASS_DIMS or d.get('track_id') is None:
                    continue
                ego = pinhole_ego(d, iw, ih, fov_v_deg)
                if ego is None:
                    continue
                xv, yv = _cam_to_vehicle(ego[0], ego[1], CAMERA_YAW[pos])
                e, n = ego_to_world(se, sn, sh, xv, yv)
                dets_here.append((f, d, e, n))

        # Association plus-proche-voisin (gating + prédiction). On autorise plusieurs
        # détections → même track (fusion des doublons vus par 2 caméras).
        for f, d, e, n in dets_here:
            best, best_dist = None, gate_m
            for tr in tracks:
                dt = t - tr['last_t']
                if dt < 0 or dt > max_gap_s:
                    continue
                pe = tr['e'] + tr['ve'] * dt
                pn = tr['n'] + tr['vn'] * dt
                dist = math.hypot(e - pe, n - pn)
                if dist < best_dist:
                    best, best_dist = tr, dist
            if best is None:
                best = {'id': next_id, 'e': e, 'n': n, 've': 0.0, 'vn': 0.0, 'last_t': t}
                tracks.append(best)
                next_id += 1
            else:
                dt = t - best['last_t']
                if dt > 1e-3:
                    best['ve'] = (e - best['e']) / dt
                    best['vn'] = (n - best['n']) / dt
                    best['e'], best['n'], best['last_t'] = e, n, t
            d['global_track_id'] = best['id']
            dirty.add(f)

    for f in dirty:
        f.save(update_fields=['detections'])
    return next_id - 1
