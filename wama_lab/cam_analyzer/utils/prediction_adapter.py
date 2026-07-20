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
# Latérales : fixées aux épaules AVANT, orientées ~±75° de l'axe (70-80° d'après
# l'installation ENA — recouvrement avant↔latérales, aucun avec l'arrière). Ajustable
# par session via le bouton Yaw (session.config['camera_yaw']).
CAMERA_YAW = {'front': 0.0, 'right': 75.0, 'rear': 180.0, 'left': -75.0}


def camera_yaw_map(session):
    """Yaw de montage par caméra : défauts CAMERA_YAW surchargés par la calibration de
    session (`session.config['camera_yaw'] = {position: deg}`) — sur le terrain les
    caméras ne sont pas toutes montées exactement à 0/±90/180°, et une erreur de yaw
    décale latéralement tous les objets de la vue (sin(Δyaw)·distance) → hand-off
    inter-caméras impossible. Éditable depuis la vue de dessus (bouton Yaw)."""
    yaw = dict(CAMERA_YAW)
    try:
        for k, v in ((getattr(session, 'config', None) or {}).get('camera_yaw') or {}).items():
            if k in yaw:
                yaw[k] = float(v)
    except (TypeError, ValueError):
        pass
    return yaw


# ── Géométrie RÉELLE du rig ENA (schéma claude/ENA_Installation + specs AXIS) ────────
# Avant/arrière : AXIS F4005-E dome, FOV 110°H / ~61°V, aux extrémités de la navette.
# Latérales : AXIS F1015 vari-focale réglées ~55°H → ~31°V (table constructeur
# 97°-52°H ↔ 53°-30°V), fixées aux épaules avant, orientées ~±75° de l'axe.
CAMERA_FOV_H = {'front': 110.0, 'right': 55.0, 'rear': 110.0, 'left': 55.0}
CAMERA_FOV_V = {'front': 61.0, 'right': 31.0, 'rear': 61.0, 'left': 31.0}
# FOV V utilisés HISTORIQUEMENT à l'annotation (anciens DEFAULT_FOV_V_DEG) : sessions
# analysées avant le correctif n'ont pas config['fov_v_used'] → on suppose ces valeurs
# pour le facteur de correction des distances stockées (latérales : 90° supposé vs 31°
# réel = distances 3,6× trop courtes).
LEGACY_FOV_V = {'front': 60.0, 'right': 90.0, 'rear': 60.0, 'left': 90.0}
# Montage (droite_m, avant_m) dans le repère véhicule, origine = CENTRE ARRIÈRE.
# Le point GPS (= l'antenne, coin arrière droit du rig ENA) est ramené à cette origine
# par le levier GPS_ANTENNA dans shuttle_trajectory(). Navya ≈ 4,75 m × 2,11 m.
CAMERA_MOUNT = {'front': (0.0, 4.5), 'right': (1.0, 3.4),
                'rear': (0.0, 0.0), 'left': (-1.0, 3.4)}


def camera_geometry(session):
    """Géométrie effective par caméra : {position: {yaw, fov_h, dist_scale, mount}}.
    Défauts du rig ENA surchargés par la calibration de session (`session.config` :
    `camera_yaw`, `camera_mount`, `fov_v_used` — ce dernier écrit par l'analyse pour
    que `dist_scale` devienne 1.0 quand les distances sont annotées avec le bon FOV)."""
    cfg = (getattr(session, 'config', None) or {})
    yaw = camera_yaw_map(session)
    fov_used = cfg.get('fov_v_used') or {}
    mounts = cfg.get('camera_mount') or {}
    # FOV RÉELS surchargables par session (`config['camera_fov'] = {pos: {'h':deg,'v':deg}}`)
    # — les F1015 latérales sont VARI-FOCALES (97-52°H) : le réglage terrain est incertain
    # (55° supposé, probablement resté au large 97°). Changer le FOV réel ajuste dist_scale
    # (tan(used/2)/tan(réel/2)) → les distances affichées/traquées se recalent SANS
    # ré-annotation. Éditable depuis le bouton Yaw de la vue de dessus.
    fov_over = cfg.get('camera_fov') or {}
    # Bascules de comparaison (⚑ Modes) : appliquées ICI et nulle part ailleurs —
    # camera_geometry est la source unique de la géométrie, donc couper une bascule
    # neutralise le levier partout (tracking, prédiction… le JS a son miroir camGeo).
    from .features import effective as _features_effective
    feat = _features_effective(session)
    geo = {}
    for pos in CAMERA_YAW:
        try:
            used = float(fov_used.get(pos, LEGACY_FOV_V[pos]))
        except (TypeError, ValueError):
            used = LEGACY_FOV_V[pos]
        ov = fov_over.get(pos) or {}
        try:
            real_h = float(ov.get('h', CAMERA_FOV_H[pos]))
            real_v = float(ov.get('v', CAMERA_FOV_V[pos]))
        except (TypeError, ValueError):
            real_h, real_v = CAMERA_FOV_H[pos], CAMERA_FOV_V[pos]
        m = mounts.get(pos) or CAMERA_MOUNT[pos]
        geo[pos] = {
            'yaw': yaw[pos],
            'fov_h': real_h,
            'dist_scale': (math.tan(math.radians(used) / 2) / math.tan(math.radians(real_v) / 2)
                           if feat.get('fov_dist_correction', True) else 1.0),
            'mount': (float(m[0]), float(m[1])) if feat.get('mount_lever_arm', True) else (0.0, 0.0),
        }
    return geo


def cam_to_vehicle(lateral, longitudinal, yaw_deg, mount=(0.0, 0.0)):
    """Position repère caméra → repère VÉHICULE commun (via l'orientation de la caméra).
    `mount` = position de MONTAGE de la caméra dans le repère véhicule (droite, avant)
    en m, origine = CENTRE ARRIÈRE (le point GPS y est ramené via GPS_ANTENNA). La
    caméra avant est à l'extrémité AVANT (~4,5 m devant l'arrière) : sans ce bras de
    levier, tous les objets avant étaient dessinés ~4,5 m trop près. Audit 2026-07-16."""
    t = math.radians(yaw_deg)
    s, c = math.sin(t), math.cos(t)
    return (longitudinal * s + lateral * c + mount[0],
            longitudinal * c - lateral * s + mount[1])


def make_local_frame(gps_track):
    """Origine = 1er point GPS. Retourne to_local(lat, lon) -> (east, north) en mètres."""
    lat0, lon0 = gps_track[0]['lat'], gps_track[0]['lon']
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))

    def to_local(lat, lon):
        return ((lon - lon0) * m_lon, (lat - lat0) * m_lat)
    return to_local


# Position de l'ANTENNE GPS dans le repère véhicule (latéral droite, longitudinal avant),
# origine = centre arrière. Rig ENA : antenne dans le COIN ARRIÈRE DROIT (schéma
# d'installation, confirmé utilisateur 2026-07-20) → tout le repère véhicule était calé
# ~1 m à droite de la réalité (le point GPS était traité comme le centre arrière) —
# composante du « décalage latéral systématique vers la droite » signalé à l'origine.
GPS_ANTENNA = (1.0, 0.0)


def antenna_offset(session=None):
    """Levier d'antenne effectif (latéral, longitudinal) — déclaré par session
    (config['gps_antenna']), défaut rig ENA, désactivable (⚑ antenna_lever)."""
    ant = list(GPS_ANTENNA)
    if session is not None:
        try:
            cfg = session.config or {}
            ov = cfg.get('gps_antenna')
            if isinstance(ov, (list, tuple)) and len(ov) >= 2:
                ant = [float(ov[0]), float(ov[1])]
            from .features import effective
            if not effective(session).get('antenna_lever', True):
                return (0.0, 0.0)
        except Exception:
            pass
    return (ant[0], ant[1])


def shuttle_trajectory(gps_track, to_local, antenna=None):
    """GPS → [t, east, north, heading_deg] (points avec cap valide, triés).
    `antenna` (latéral, longitudinal) : position de l'antenne dans le repère véhicule —
    le point GPS est ramené au CENTRE ARRIÈRE (origine des montages caméra) en
    retranchant le levier tourné par le cap."""
    ax, ay = antenna if antenna else (0.0, 0.0)
    rows = []
    for p in gps_track:
        h = p.get('heading')
        if h is None:
            continue
        e, n = to_local(p['lat'], p['lon'])
        if ax or ay:
            hr = math.radians(h)
            e -= ay * math.sin(hr) + ax * math.cos(hr)
            n -= ay * math.cos(hr) - ax * math.sin(hr)
        rows.append((p['ts'], e, n, h))
    rows.sort(key=lambda r: r[0])
    return np.array(rows) if rows else np.zeros((0, 4))


def pinhole_ego(det, iw, ih, fov_v_deg=60.0, fov_h_deg=None, dist_scale=1.0):
    """Détection → position ego (latéral droite, longitudinal avant) en m, ou None.
    Reconstruction pinhole (comme l'affichage) : robuste au biais de l'homographie.
    `fov_h_deg` : FOV HORIZONTAL réel de la caméra → focale latérale correcte (l'ancien
    calcul appliquait la focale verticale 60° à toutes les caméras : latéral compressé
    ~1,6× sur la caméra avant 110°). `dist_scale` : correction des distances stockées
    annotées avec un mauvais FOV V (latérales : 90° supposé vs 31° réel = ×3,6).
    Audit 2026-07-16 (specs rig ENA)."""
    dm = det.get('distance_m')
    bb = det.get('bbox')
    if dm is None or not (isinstance(bb, (list, tuple)) and len(bb) >= 4):
        return None
    if bb[0] <= 8 or bb[2] >= iw - 8:      # coupé au bord → cap non fiable
        return None
    dm = dm * dist_scale
    if fov_h_deg:
        focal = iw / (2.0 * math.tan(math.radians(fov_h_deg) / 2.0))
    else:
        focal = ih / (2.0 * math.tan(math.radians(fov_v_deg) / 2.0))
    bcx = (bb[0] + bb[2]) / 2.0
    lateral = dm * (bcx - iw / 2.0) / focal
    return lateral, dm       # [latéral, longitudinal]


def ground_projector_for(session, position, geo):
    """GroundProjector à partir du pitch/hauteur ESTIMÉS et persistés
    (`config['ground_calib'][pos]`, cf. homography_estimator.store_ground_calib).
    Retourne None si pas de calib pour cette caméra → l'appelant retombe sur le pinhole.
    Étape 2a du plan de calibration sol : l'ANGLE, derrière ⚑ auto_ground_calib."""
    cal = ((session.config or {}).get('ground_calib') or {}).get(position)
    if not cal:
        return None
    cam = session.cameras.filter(position=position).first()
    if not cam or not cam.width or not cam.height:
        return None
    try:
        from .ground_projection import GroundProjector
        from .calibration import intrinsics_from_fov
        intr = intrinsics_from_fov(cam.width, cam.height, geo['fov_h'],
                                   CAMERA_FOV_V.get(position, 61.0))
        gp = GroundProjector(dict(intr, height_m=cal['height_m'],
                                  pitch_deg=cal['pitch_deg'], hfov_deg=geo['fov_h'],
                                  lens_type='rectilinear'), (cam.width, cam.height))
        return gp if gp.available else None
    except Exception:
        return None


def ground_ego(projector, bbox):
    """Position ego (latéral, longitudinal) par PROJECTION SOL du bas de bbox
    (point de contact) via le pitch estimé — alternative au pinhole (hauteur de bbox).
    Retourne None hors de portée utile → l'appelant garde le pinhole."""
    if projector is None or not bbox or len(bbox) < 4:
        return None
    bcx = (bbox[0] + bbox[2]) / 2.0
    xy = projector.project(bcx, bbox[3])
    if not xy:
        return None
    lateral, longitudinal = xy[0], xy[1]
    if not (1.0 < longitudinal < 40.0):    # garde-fou : au-delà, projection sol non fiable
        return None
    return lateral, longitudinal


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
    # Cap : interpolation CIRCULAIRE (plus court arc). L'interpolation linéaire naïve
    # en degrés faisait passer le cap par ~180° au wrap 359°→1° (navette plein nord =
    # zone de wrap permanente) → tous les objets alentour balayaient un demi-tour
    # fantôme pendant l'intervalle GPS (~2,7 s), amplifié par le bras de levier
    # cap × distance. Audit vue de dessus 2026-07-16.
    dh = (b[3] - a[3] + 180.0) % 360.0 - 180.0
    return a[1] + f * (b[1] - a[1]), a[2] + f * (b[2] - a[2]), (a[3] + f * dh) % 360.0


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
    sh_traj = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    if len(sh_traj) < 5:
        return 0
    cams = [c for c in session.cameras.all()
            if c.position in CAMERA_YAW and DF.objects.filter(camera=c).exists()]
    if not cams:
        return 0
    _geo = camera_geometry(session)  # yaw/FOV/montage réels par caméra (rig + session)
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
                _g = _geo[c.position]
                ego = pinhole_ego(d, iw, ih, fov_v_deg,
                                  fov_h_deg=_g['fov_h'], dist_scale=_g['dist_scale'])
                if ego is None:
                    continue
                xv, yv = cam_to_vehicle(ego[0], ego[1], _g['yaw'], mount=_g['mount'])
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
        # Échantillonnage : ne calculer que toutes les K détections et RÉUTILISER la valeur
        # sur l'intervalle (le TTC/PET varie lentement) → ~K× moins de calculs.
        K = 4
        last = {'ttc': None, 'pet': None}
        for idx, (ts, d, f, e, n, ego_long, _) in enumerate(rows):
            if ego_long > max_range_m:
                continue
            if idx % K == 0:
                last = ttc_pet_shuttle_object(sh_traj, obj_traj, ts, method=method, class_name=cls)
            changed = False
            if last['ttc'] is not None:
                d['prediction_ttc'] = round(last['ttc'], 2); changed = True
            if last['pet'] is not None:
                d['prediction_pet'] = round(last['pet'], 2); changed = True
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
    dt = 0.2                       # pas plus grossier (2× moins d'étapes, résolution 0,2s)
    horizon_s = min(horizon_s, 4.0)
    n_future = int(horizon_s / dt)
    extra = extrapolate_kalman if method == 'kalman' else extrapolate_speed_accel
    # Forcer les deux historiques à finir à t0 → grilles futures alignées (t0, t0+dt, …).
    sh_hist = _ensure_endpoint(sh_hist, t0)
    ob_hist = _ensure_endpoint(ob_hist, t0)
    sh_fut = extra(sh_hist, n_future, dt=dt)
    ob_fut = extra(ob_hist, n_future, dt=dt)
    # Ne garder que le FUTUR (t >= t0) : TTC/PET mesurés depuis t0, et pas de collision
    # passée parasite → moitié moins de tests SAT.
    sh_fut = sh_fut[sh_fut[:, 0] >= t0 - 1e-6]
    ob_fut = ob_fut[ob_fut[:, 0] >= t0 - 1e-6]
    if len(sh_fut) < 2 or len(ob_fut) < 2:
        return {'ttc': None, 'pet': None}
    sh_shape = point_traj_to_shape(sh_fut, *SHUTTLE_DIMS)
    ob_shape = point_traj_to_shape(ob_fut, *CLASS_DIMS.get(class_name, (2.0, 1.0)))
    res = collision_detection(sh_shape, ob_shape, max_pet_steps=12)   # PET borné (±2,4s)
    return {'ttc': res['ttc'], 'pet': res['pet']}
