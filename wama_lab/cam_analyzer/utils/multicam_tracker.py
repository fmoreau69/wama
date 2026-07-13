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
from collections import defaultdict

from django.apps import apps

from .prediction_adapter import (make_local_frame, shuttle_trajectory, pinhole_ego,
                               ego_to_world, _shuttle_pose_at, CLASS_DIMS)


def world_to_vehicle(world_e, world_n, shuttle_e, shuttle_n, heading_deg):
    """Position monde → repère véhicule (inverse d'ego_to_world) : (latéral, longitudinal)."""
    de, dn = world_e - shuttle_e, world_n - shuttle_n
    h = math.radians(heading_deg)
    s, c = math.sin(h), math.cos(h)
    lateral = de * c - dn * s
    longitudinal = de * s + dn * c
    return lateral, longitudinal

# Orientation de montage de chaque caméra (deg, sens horaire depuis l'avant véhicule).
CAMERA_YAW = {'front': 0.0, 'right': 90.0, 'rear': 180.0, 'left': -90.0}


def _cam_to_vehicle(lateral, longitudinal, yaw_deg):
    """Position dans le repère caméra → repère VÉHICULE commun (via l'orientation caméra)."""
    t = math.radians(yaw_deg)
    s, c = math.sin(t), math.cos(t)
    return (longitudinal * s + lateral * c, longitudinal * c - lateral * s)


def annotate_global_tracks(session, fov_v_deg=60.0, gate_m=3.5, max_gap_s=1.0,
                           frame_range=None, spread_max_m=6.0):
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
    track_hist = defaultdict(list)   # gid -> [(fn, t, world_e, world_n, class)]
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
                if d.get('class_name') not in CLASS_DIMS:
                    continue
                # Accepte les détections suivies (track_id) ET les objets SEGMENTÉS sans
                # track_id (le tracker global les suit par position monde). Exclut les
                # fantômes (predicted) qui n'ont ni track_id ni source segmentation.
                if d.get('track_id') is None and d.get('source') != 'segmentation':
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
            track_hist[best['id']].append((fn, t, e, n, d.get('class_name', 'car')))
            dirty.add(f)

    # ── Comblement des trous de détection au hand-off (empreintes prédites) ──────
    # Pour chaque track, on interpole en repère MONDE entre avant/après le trou, puis on
    # convertit en repère véhicule et on insère une détection "fantôme" (predicted) dans
    # la frame front manquante. Bornes : trou ≤ max_gap_frames.
    front_frames = per_cam.get('front', (None, None, {}))[2]
    max_gap_frames = int(1.2 * fps)   # ~1,2 s max
    ghosts = 0
    if front_frames:
        # Retirer les anciens fantômes (idempotence si on recalcule).
        for fr in front_frames.values():
            if fr.detections and any(d.get('predicted') for d in fr.detections):
                fr.detections = [d for d in fr.detections if not d.get('predicted')]
                dirty.add(fr)
        for gid, hist in track_hist.items():
            hist.sort()
            # positions monde uniques par frame (moyenne si doublons)
            byfn = {}
            for fn, t, e, n, cls in hist:
                pe, pn, k = byfn.get(fn, (0.0, 0.0, 0))
                byfn[fn] = (pe + e, pn + n, k + 1)
            fns_h = sorted(byfn)
            cls = hist[0][4]
            for i in range(1, len(fns_h)):
                f0, f1 = fns_h[i - 1], fns_h[i]
                gap = f1 - f0
                if gap <= 1 or gap - 1 > max_gap_frames:
                    continue
                e0, n0 = byfn[f0][0] / byfn[f0][2], byfn[f0][1] / byfn[f0][2]
                e1, n1 = byfn[f1][0] / byfn[f1][2], byfn[f1][1] / byfn[f1][2]
                for fn in range(f0 + 1, f1):
                    fr = front_frames.get(fn)
                    if not fr:
                        continue
                    a = (fn - f0) / gap
                    we, wn = e0 + a * (e1 - e0), n0 + a * (n1 - n0)   # interpolation monde
                    t = fn / fps * scale + off
                    se, sn, sh = _shuttle_pose_at(sh_traj, t)
                    lat, lon = world_to_vehicle(we, wn, se, sn, sh)
                    if lon <= 0:
                        continue
                    if fr.detections is None:
                        fr.detections = []
                    fr.detections.append({
                        'type': 'ghost', 'predicted': True, 'global_track_id': gid,
                        'class_name': cls, 'vehicle_xy': [round(lat, 3), round(lon, 3)],
                    })
                    dirty.add(fr)
                    ghosts += 1

    # ── Détection des véhicules STATIONNÉS (garés) ──────────────────────────────
    # Track à vitesse max ~nulle sur toute sa vie = garé, SAUF s'il passe près d'une
    # intersection (voiture arrêtée au carrefour = pertinente, on la garde).
    windows = session.intersection_windows or []
    win_local = []
    for w in windows:
        if w.get('lat') is not None and w.get('lon') is not None:
            we, wn = to_local(w['lat'], w['lon'])
            win_local.append((we, wn, w.get('radius_m', 30.0)))

    def _near_intersection(hs):
        for (_, _, e, n, _) in hs:
            for we, wn, wr in win_local:
                if math.hypot(e - we, n - wn) <= wr:
                    return True
        return False

    # Métrique robuste au bruit : ÉTALEMENT spatial de la position monde sur la vie du
    # track (un véhicule garé reste groupé ; un mobile s'étale le long de son trajet).
    stationary_gids = []
    for gid, hist in track_hist.items():
        hs = sorted(hist)
        if len(hs) < 5 or (hs[-1][1] - hs[0][1]) < 1.0:
            continue
        e0, n0 = hs[0][2], hs[0][3]
        spread = max(math.hypot(e - e0, n - n0) for (_, _, e, n, _) in hs)
        if spread < spread_max_m and not _near_intersection(hs):
            stationary_gids.append(gid)

    for f in dirty:
        f.save(update_fields=['detections'])
    return {'tracks': next_id - 1, 'stationary_gids': stationary_gids}
