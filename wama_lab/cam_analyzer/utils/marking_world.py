"""
Marquages SAM3 agrégés en coordonnées MONDE — étape 1 du chantier « marquages comme
indicateurs d'intersection » (validé 2026-07-20, idée Fabien).

Les stop_line / crossing / lignes segmentés par SAM3 sont des faits STATIQUES du monde,
observés à chaque passage et à chaque keyframe : on les projette au sol et on les agrège
multi-frames/multi-passages, exactement comme les ancres de stationnés et les branches
apprises. Usages : bornes réelles d'intersection (stop_line = où elle commence), axe de
la branche perpendiculaire (crossing en travers de la croisante — fonctionne SANS trafic,
le complément exact des branches apprises), et à terme recalibration d'homographie
(chantier « multi-frame crosswalks »).

RÉUTILISE (ne pas réinventer — cartographie 2026-07-20) :
- `ground_projection.GroundProjector` : image → sol caméra (X latéral, Y avant), depuis
  `camera.ground_homography` (flux « Calibrer »/« Calib. SAM3 ») quand il existe, sinon
  calibration paramétrique par défaut (FOV réels + hauteur 2.4 m + pitch 0 — plan-sol,
  biais assumé, confiance moindre) ;
- `prediction_adapter` : camera_geometry (yaw/mount), shuttle_trajectory (levier antenne
  inclus), ego_to_world ;
- clustering axial : même approche que `intersection_branches`.

Sortie (results_summary['intersection_markings']) :
    { "<index fenêtre>": [ {"a": [lat, lon], "b": [lat, lon], "label": str,
                            "bearing_deg": float, "n_obs": int, "calibrated": bool} ] }
"""
import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)

# Étiquettes SAM3 retenues et leur regroupement d'affichage
_LABEL_KIND = {
    'stop_line': 'stop_line',
    'crossing': 'crossing',
    'crosswalk': 'crossing',
    'line': 'line',
    'center_line': 'line',
    'lane_line': 'line',
}

MAX_RANGE_M = 12.0    # au-delà, l'erreur de projection plan-sol explose
MIN_RANGE_M = 2.0


def _projector_for(camera, geo):
    """GroundProjector : homographie calibrée si présente, sinon paramétrique défaut."""
    from .ground_projection import GroundProjector
    w, h = camera.width or 384, camera.height or 288
    cal = getattr(camera, 'ground_homography', None)
    calibrated = bool(cal)
    if not cal:
        from .calibration import intrinsics_from_fov
        from .prediction_adapter import CAMERA_FOV_V
        intr = intrinsics_from_fov(w, h, geo['fov_h'],
                                   CAMERA_FOV_V.get(camera.position, 61.0))
        cal = dict(intr, height_m=2.4, pitch_deg=0.0,
                   hfov_deg=geo['fov_h'], lens_type='rectilinear')
    try:
        gp = GroundProjector(cal, (w, h))
        return (gp if gp.available else None), calibrated
    except Exception:
        return None, False


def aggregate_markings(session, min_obs=3, max_pts=6000):
    """Projette et agrège les marquages SAM3 en monde, par intersection."""
    from ..models import DetectionFrame
    from .prediction_adapter import (make_local_frame, shuttle_trajectory,
                                     antenna_offset, camera_geometry,
                                     ego_to_world, _shuttle_pose_at)

    gt = session.gps_track or []
    wins = session.intersection_windows or []
    if len(gt) < 2 or not wins:
        return {}
    to_local = make_local_frame(gt)
    sh_traj = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    if len(sh_traj) < 5:
        return {}
    geo = camera_geometry(session)
    lat0, lon0 = float(gt[0]['lat']), float(gt[0]['lon'])
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))

    # Observations monde par (lieu, label-kind) : points projetés de tous les polygones
    places = {}
    for wi, w in enumerate(wins):
        if w.get('lat') is None:
            continue
        key = (round(w['lat'], 5), round(w['lon'], 5))
        places.setdefault(key, {'wids': [], 'en': to_local(w['lat'], w['lon'])})
        places[key]['wids'].append(wi)

    # Axe du corridor navette à chaque lieu (pour reclasser par géométrie)
    corridor = {}
    for key, pl in places.items():
        we, wn = pl['en']
        dists = [(abs(math.hypot(r[1] - we, r[2] - wn)), r[3]) for r in sh_traj[::5]]
        corridor[key] = min(dists, key=lambda x: x[0])[1] % 180.0

    obs = defaultdict(list)     # (place_key, kind) -> [(e, n, frame_id)]
    any_calibrated = {}
    for cam in session.cameras.all():
        g = geo.get(cam.position)
        if not g:
            continue
        gp, calibrated = _projector_for(cam, g)
        if gp is None:
            continue
        yaw = math.radians(g['yaw'])
        mnt = g.get('mount') or (0.0, 0.0)
        qs = (DetectionFrame.objects.filter(camera=cam)
              .order_by('frame_number').only('detections', 'timestamp'))
        for df in qs.iterator(chunk_size=1000):
            dets = [d for d in (df.detections or [])
                    if d.get('type') == 'sam3_marking'
                    and _LABEL_KIND.get((d.get('label') or d.get('class_name') or '').lower())]
            if not dets:
                continue
            se, sn, sh = _shuttle_pose_at(sh_traj, df.timestamp)
            for d in dets:
                kind = _LABEL_KIND[(d.get('label') or d.get('class_name') or '').lower()]
                pts = d.get('polygon') or []
                if not pts and d.get('bbox'):
                    b = d['bbox']
                    pts = [[b[0], b[3]], [b[2], b[3]], [(b[0] + b[2]) / 2, b[3]]]
                # BORD BAS du polygone seulement (ligne de contact au sol) : près de
                # l'horizon, dY/dv explose — projeter toute la hauteur du polygone
                # étale le marquage sur des mètres LE LONG de la visée et la PCA se
                # verrouille sur l'axe du corridor (biais mesuré 2 itérations de suite).
                # On garde, par colonne (8 paquets en u), le point le plus BAS : une
                # profondeur par colonne → l'étendue restante est la vraie latérale.
                _cols = {}
                for pt in pts[:60]:
                    cbin = int(pt[0] // 24)
                    if cbin not in _cols or pt[1] > _cols[cbin][1]:
                        _cols[cbin] = pt
                world_pts = []
                for pt in _cols.values():
                    xy = gp.project(pt[0], pt[1])
                    if not xy:
                        continue
                    X, Y = xy
                    if not (MIN_RANGE_M <= Y <= MAX_RANGE_M) or abs(X) > 15:
                        continue
                    # caméra → véhicule (rotation yaw + montage) → monde
                    lat_v = Y * math.sin(yaw) + X * math.cos(yaw) + mnt[0]
                    lon_v = Y * math.cos(yaw) - X * math.sin(yaw) + mnt[1]
                    world_pts.append(ego_to_world(se, sn, sh, lat_v, lon_v))
                if not world_pts:
                    continue
                # rattachement au lieu le plus proche (≤ 35 m) — sur le centroïde,
                # mais on stocke les POINTS du polygone : l'axe PCA doit refléter
                # l'étendue PHYSIQUE du marquage (transverse pour une stop_line),
                # pas la traînée de dérive de projection le long du corridor
                # (biais mesuré : stop_lines sorties parallèles au corridor).
                ce = sum(p[0] for p in world_pts) / len(world_pts)
                cn = sum(p[1] for p in world_pts) / len(world_pts)
                best, bd = None, 35.0
                for key, pl in places.items():
                    dd = math.hypot(pl['en'][0] - ce, pl['en'][1] - cn)
                    if dd < bd:
                        bd, best = dd, key
                if best is None:
                    continue
                lst = obs[(best, kind)]
                if len(lst) < max_pts:
                    step = max(1, len(world_pts) // 8)
                    lst.extend((p[0], p[1], df.pk) for p in world_pts[::step][:8])
                    any_calibrated[(best, kind)] = (any_calibrated.get((best, kind), False)
                                                    or calibrated)

    # Clustering spatial par (lieu, kind) : un marquage = un amas de centroïdes.
    # Anti-fragmentation (mesuré 1498 segments à la 1re passe — 10× le réel) :
    # (1) amas gloutons 6 m, (2) FUSION des amas proches (< 5 m), (3) seuil en FRAMES
    # distinctes (pas en points), (4) TOP-K par type — le vrai signal domine largement
    # (amas à 500-1100 obs vs bruit SAM3 à 3-20).
    _TOP_K = {'stop_line': 4, 'crossing': 3, 'line': 2}
    out = defaultdict(list)
    for (key, kind), pts in obs.items():
        clusters = []
        for e, n, fid in pts:
            for cl in clusters:
                if math.hypot(cl['e'] / cl['n_'] - e, cl['n'] / cl['n_'] - n) <= 6.0:
                    cl['e'] += e; cl['n'] += n; cl['n_'] += 1
                    cl['pts'].append((e, n)); cl['frames'].add(fid)
                    break
            else:
                clusters.append({'e': e, 'n': n, 'n_': 1, 'pts': [(e, n)],
                                 'frames': {fid}})
        # fusion des amas proches (la dérive de projection inter-passages scinde
        # le même marquage physique)
        merged = []
        for cl in sorted(clusters, key=lambda c: -c['n_']):
            for mg in merged:
                if math.hypot(mg['e'] / mg['n_'] - cl['e'] / cl['n_'],
                              mg['n'] / mg['n_'] - cl['n'] / cl['n_']) <= 5.0:
                    mg['e'] += cl['e']; mg['n'] += cl['n']; mg['n_'] += cl['n_']
                    mg['pts'].extend(cl['pts']); mg['frames'] |= cl['frames']
                    break
            else:
                merged.append(cl)
        merged = [c for c in merged if len(c['frames']) >= max(min_obs, 8)]
        merged.sort(key=lambda c: -len(c['frames']))
        for cl in merged[:_TOP_K.get(kind, 2)]:
            # axe principal du nuage (PCA 2D allégée)
            me, mn = cl['e'] / cl['n_'], cl['n'] / cl['n_']
            sxx = sum((p[0] - me) ** 2 for p in cl['pts'])
            syy = sum((p[1] - mn) ** 2 for p in cl['pts'])
            sxy = sum((p[0] - me) * (p[1] - mn) for p in cl['pts'])
            ang = 0.5 * math.atan2(2 * sxy, sxx - syy)   # axe est/nord
            brg = (90.0 - math.degrees(ang)) % 180.0     # → gisement mod 180
            ux, uy = math.sin(math.radians(brg)), math.cos(math.radians(brg))
            projs = sorted((p[0] - me) * ux + (p[1] - mn) * uy for p in cl['pts'])
            lo = projs[max(0, int(len(projs) * 0.05))]
            hi = projs[min(len(projs) - 1, int(len(projs) * 0.95))]
            if hi - lo < 1.0:            # trop court pour définir un axe fiable
                lo, hi = -1.0, 1.0
            a = (me + ux * lo, mn + uy * lo)
            b = (me + ux * hi, mn + uy * hi)
            # Reclassement GÉOMÉTRIQUE : le prompt SAM3 « stop_line » attrape aussi
            # les lignes de rive/axe LONGITUDINALES (mesuré : amas dominants ∥ corridor).
            # Une vraie ligne d'arrêt est transverse — ∥ corridor (± 25°) ⇒ 'line'.
            _ad = abs(brg - corridor[key]) % 180.0
            _kind_eff = 'line' if (kind == 'stop_line'
                                   and min(_ad, 180.0 - _ad) < 25.0) else kind
            seg = {
                'a': [round(lat0 + a[1] / m_lat, 7), round(lon0 + a[0] / m_lon, 7)],
                'b': [round(lat0 + b[1] / m_lat, 7), round(lon0 + b[0] / m_lon, 7)],
                'label': _kind_eff,
                'bearing_deg': round(brg, 1),
                'n_obs': len(cl['frames']),
                'calibrated': any_calibrated.get((key, kind), False),
            }
            for wi in places[key]['wids']:
                out[str(wi)].append(seg)
    if out:
        logger.info("marquages monde : %s",
                    {k: len(v) for k, v in out.items()})
    return dict(out)
