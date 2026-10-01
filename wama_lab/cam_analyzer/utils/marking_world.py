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
    # rangée de triangles (ralentisseur) : un marquage TRANSVERSE à part, jamais calé sur l'axe
    # des passages piétons (il leur était superposé tant que SAM3 le rendait sous `crossing`)
    'shark_teeth': 'shark_teeth',
    'line': 'line',
    'center_line': 'line',
    'lane_line': 'line',
}

MAX_RANGE_M = 12.0    # au-delà, l'erreur de projection plan-sol explose
MIN_RANGE_M = 2.0
CROSSING_MAX_HALF_M = 4.0   # demi-longueur max d'un passage piéton dessiné (une chaussée)
CROSSING_ON_ROAD_M = 3.5    # un passage PARALLÈLE à la rue ne peut pas être sur la trajectoire


def contact_points(det, gp, yaw_rad, mount, max_lateral_m=15.0):
    """Points de CONTACT AU SOL d'un marquage SAM3, en repère VÉHICULE (latéral droite, avant),
    origine = centre arrière : la caméra est replacée par son orientation et son montage.

    BORD BAS du polygone seulement (ligne de contact au sol) : près de l'horizon, dY/dv explose —
    projeter toute la hauteur du polygone étale le marquage sur des mètres LE LONG de la visée et
    la PCA se verrouille sur l'axe du corridor (biais mesuré 2 itérations de suite). On garde, par
    colonne (8 paquets en u), le point le plus BAS : une profondeur par colonne → l'étendue restante
    est la vraie latérale. Partagé par l'agrégation monde et la mesure par passage du recalage ortho
    (2026-10-01)."""
    pts = det.get('polygon') or []
    if not pts and det.get('bbox'):
        b = det['bbox']
        pts = [[b[0], b[3]], [b[2], b[3]], [(b[0] + b[2]) / 2, b[3]]]
    cols = {}
    for pt in pts[:60]:
        cbin = int(pt[0] // 24)
        if cbin not in cols or pt[1] > cols[cbin][1]:
            cols[cbin] = pt
    out = []
    for pt in cols.values():
        xy = gp.project(pt[0], pt[1])
        if not xy:
            continue
        X, Y = xy
        if not (MIN_RANGE_M <= Y <= MAX_RANGE_M) or abs(X) > max_lateral_m:
            continue
        # caméra → véhicule (rotation yaw + montage)
        out.append((Y * math.sin(yaw_rad) + X * math.cos(yaw_rad) + mount[0],
                    Y * math.cos(yaw_rad) - X * math.sin(yaw_rad) + mount[1]))
    return out


def snap_crossing(bearing, corridor_bearing, extent_m, distance_to_path_m):
    """Axe d'un passage piéton agrégé (⚑ marking_axis_snap) : calé sur la plus proche des deux
    directions du corridor — en travers de la rue de la navette, ou parallèle (il traverse alors
    une rue LATÉRALE) — et demi-longueur bornée à `CROSSING_MAX_HALF_M`. Un passage PARALLÈLE posé
    à moins de `CROSSING_ON_ROAD_M` de la trajectoire est impossible (il serait sur la chaussée de
    la navette, dans son sens) : None. Rend (gisement mod 180, demi-longueur) ou None."""
    along = corridor_bearing % 180.0
    across = (corridor_bearing + 90.0) % 180.0

    def gap(a, b):
        d = abs(a - b) % 180.0
        return min(d, 180.0 - d)
    axis = along if gap(bearing, along) < gap(bearing, across) else across
    if axis == along and distance_to_path_m < CROSSING_ON_ROAD_M:
        return None
    return axis, min(max(extent_m, 2.0) / 2.0, CROSSING_MAX_HALF_M)


def _projector_for(camera, geo):
    """GroundProjector de la caméra, par ordre de confiance — ou None (caméra ignorée) :
    ① la calibration sol 2a (`config['ground_calib']`, pitch/hauteur ESTIMÉS — celle que le
    tracking utilise, `prediction_adapter.ground_projector_for`) ; ② l'homographie DLT de SAM3
    sous ⚑ sam3_homography. ⚠ Jusqu'au 2026-09-29, à défaut d'homographie, une calibration
    PARAMÉTRIQUE à pitch 0° (« biais assumé », écrite avant que 2a n'existe) : la caméra avant
    est inclinée de 16°, l'arrière de 25° — les marquages des caméras sans calibration partaient
    loin dans l'axe de visée et étiraient des « passages piétons » le long de la rue (constat de
    Fabien). Une caméra sans calibration ne projette plus rien."""
    from .prediction_adapter import ground_projector_for
    gp2a = ground_projector_for(camera.session, camera.position, geo)
    if gp2a is not None:
        return gp2a, True
    from .ground_projection import GroundProjector
    w, h = camera.width or 384, camera.height or 288
    cal = getattr(camera, 'ground_homography', None)
    # ⚑ sam3_homography (défaut ON = historique) : OFF ⇒ paramétrique même si une homographie
    # DLT existe. Elle était consommée ici SANS condition (§INVENTAIRE D.2) alors qu'elle est
    # prouvée biaisée (#546/#537) — un levier doit pouvoir se comparer.
    try:
        from .features import enabled as _feat_on
        if cal and not _feat_on(camera.session, 'sam3_homography'):
            cal = None
    except Exception:
        pass
    if not cal:
        return None, False
    try:
        gp = GroundProjector(cal, (w, h))
        return (gp if gp.available else None), True
    except Exception:
        return None, False


def aggregate_markings(session, min_obs=3, max_pts=6000):
    """Projette et agrège les marquages SAM3 en monde, par intersection."""
    from ..models import DetectionFrame
    from .prediction_adapter import (make_local_frame, shuttle_trajectory,
                                     antenna_offset, camera_geometry,
                                     ego_to_world, _shuttle_pose_at, video_to_gps_time)

    from .ego_pose import effective_gps_track   # ⚑ shuttle_filter : filtrée si ON, sinon brute
    # ortho=False : le recalage ortho MESURE sur ces marquages — les placer avec sa propre
    # correction lui ferait mesurer un résidu, et la correction suivante oscillerait
    gt = effective_gps_track(session, ortho=False)
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
            # Pose au temps GPS (base de `sh_traj`), pas au temps vidéo — `video_to_gps_time`.
            se, sn, sh = _shuttle_pose_at(sh_traj, video_to_gps_time(session, df.timestamp))
            for d in dets:
                kind = _LABEL_KIND[(d.get('label') or d.get('class_name') or '').lower()]
                # contact au sol (bord bas par colonne, cf. `contact_points`) → monde
                world_pts = [ego_to_world(se, sn, sh, lat_v, lon_v)
                             for lat_v, lon_v in contact_points(d, gp, yaw, mnt)]
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
    _TOP_K = {'stop_line': 4, 'crossing': 3, 'line': 2, 'shark_teeth': 2}
    try:
        from .features import enabled as _feat_on
        _snap = _feat_on(session, 'marking_axis_snap')
    except Exception:
        _snap = True
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
            if kind == 'crossing' and _snap:
                # ⚑ marking_axis_snap : un passage piéton TRAVERSE la rue de la navette ou une rue
                # latérale — son axe est calé sur la plus proche des deux directions du corridor
                # (l'axe du nuage agrégé sur des dizaines de passages dérive : diagonales, axes
                # parallèles à la rue), et sa longueur bornée à une chaussée.
                path_m = min(math.hypot(r[1] - me, r[2] - mn) for r in sh_traj[::3])
                snapped = snap_crossing(brg, corridor[key], hi - lo, path_m)
                if snapped is None:
                    continue
                brg, half = snapped
                ux, uy = math.sin(math.radians(brg)), math.cos(math.radians(brg))
                lo, hi = -half, half
            a = (me + ux * lo, mn + uy * lo)
            b = (me + ux * hi, mn + uy * hi)
            # Reclassement GÉOMÉTRIQUE : le prompt SAM3 « stop_line » attrape aussi
            # les lignes de rive/axe LONGITUDINALES (mesuré : amas dominants ∥ corridor).
            # Une vraie ligne d'arrêt est transverse — ∥ corridor (± 25°) ⇒ 'line'.
            _ad = abs(brg - corridor[key]) % 180.0
            _kind_eff = 'line' if (kind == 'stop_line'
                                   and min(_ad, 180.0 - _ad) < 25.0) else kind
            # Une rangée de triangles LONGITUDINALE n'existe pas : c'est une ligne mal lue.
            if kind == 'shark_teeth' and min(_ad, 180.0 - _ad) < 25.0:
                continue
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
