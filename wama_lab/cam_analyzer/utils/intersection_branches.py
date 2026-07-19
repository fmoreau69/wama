"""
Branches d'intersection APPRISES DU TRAFIC — chantier validé 2026-07-20 (idée Fabien).

Plutôt que dessiner une bande perpendiculaire symétrique « sans savoir de quel côté est
la voie », on APPREND les branches réelles depuis les trajectoires monde des véhicules
suivis (world_en lissées Kalman par le tracking 360°) : autour de chaque intersection
d'intérêt, les segments de trajectoires dont la direction s'écarte du corridor navette
de plus de `min_angle_deg` révèlent la voie croisante — position, azimut, étendue
OBSERVÉE (on ne dessine que là où des véhicules ont roulé) et largeur (dispersion
latérale + gabarit). Zéro dépendance réseau, auto-cohérent avec notre géométrie (les
biais de mesure s'annulent en moyenne sur N véhicules).

Limite assumée : une branche sans trafic observé pendant les fenêtres analysées reste
invisible (fallback affichage = bande symétrique actuelle).

Sortie (persistée dans results_summary['intersection_branches']) :
    { "<index fenêtre>": [ {"a": [lat, lon], "b": [lat, lon], "bearing_deg": float,
                            "width_m": float, "n_tracks": int}, ... ] }
"""
import logging
import math
from collections import defaultdict

logger = logging.getLogger(__name__)


def _axial_diff(a, b):
    """Écart axial (mod 180°) entre deux directions en degrés."""
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


def learn_branches(session, radius_m=25.0, min_angle_deg=30.0, min_span_m=8.0,
                   min_tracks=3, max_branches=2, max_pts_per_track=400):
    """Apprend les branches croisantes de chaque intersection depuis les world_en."""
    from ..models import DetectionFrame
    from .prediction_adapter import make_local_frame, shuttle_trajectory, antenna_offset

    gt = session.gps_track or []
    if len(gt) < 2:
        return {}
    to_local = make_local_frame(gt)
    sh_traj = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    if len(sh_traj) < 5:
        return {}
    lat0, lon0 = float(gt[0]['lat']), float(gt[0]['lon'])
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat0))

    wins = session.intersection_windows or []   # champ modèle (PAS results_summary)
    if not wins:
        return {}
    stat_set = set((session.results_summary or {}).get('stationary_global_tracks') or [])

    # Trajectoires monde par gid (échantillonnées), stationnés exclus
    tracks = defaultdict(list)   # gid -> [(t, e, n)]
    for cam in session.cameras.all():
        qs = (DetectionFrame.objects.filter(camera=cam)
              .order_by('frame_number').only('detections', 'timestamp'))
        for df in qs.iterator(chunk_size=1000):
            for d in (df.detections or []):
                gid = d.get('global_track_id')
                w = d.get('world_en')
                if gid is None or gid in stat_set or not w:
                    continue
                lst = tracks[gid]
                if len(lst) < max_pts_per_track:
                    lst.append((df.timestamp, float(w[0]), float(w[1])))

    out = {}
    for wi, w in enumerate(wins):
        wlat, wlon = w.get('lat'), w.get('lon')
        if wlat is None or wlon is None:
            continue
        we, wn = to_local(wlat, wlon)
        # Axe du corridor navette au plus proche de l'intersection
        dists = [(abs(math.hypot(r[1] - we, r[2] - wn)), r[3]) for r in sh_traj[::5]]
        corridor = min(dists, key=lambda x: x[0])[1] % 180.0

        segs = []   # (bearing_axial, pts) par track croisant
        for gid, pts in tracks.items():
            near = [(t, e, n) for (t, e, n) in pts
                    if math.hypot(e - we, n - wn) <= radius_m]
            if len(near) < 4:
                continue
            near.sort()
            de = near[-1][1] - near[0][1]
            dn = near[-1][2] - near[0][2]
            span = math.hypot(de, dn)
            if span < min_span_m:
                continue
            brg = math.degrees(math.atan2(de, dn)) % 180.0
            if _axial_diff(brg, corridor) < min_angle_deg:
                continue   # même axe que la navette : pas une branche croisante
            # RECTITUDE : un véhicule qui TOURNE dans l'intersection produit un azimut
            # intermédiaire qui mélange deux branches (mesuré : clusters saturés à 12 m
            # de large). On n'apprend la voie que des trajets qui la traversent droit :
            # cap de la 1re moitié ≈ cap de la 2de (écart axial ≤ 20°).
            mid = len(near) // 2
            d1e, d1n = near[mid][1] - near[0][1], near[mid][2] - near[0][2]
            d2e, d2n = near[-1][1] - near[mid][1], near[-1][2] - near[mid][2]
            if min(math.hypot(d1e, d1n), math.hypot(d2e, d2n)) >= 2.0:
                b1 = math.degrees(math.atan2(d1e, d1n)) % 180.0
                b2 = math.degrees(math.atan2(d2e, d2n)) % 180.0
                if _axial_diff(b1, b2) > 20.0:
                    continue   # trajectoire coudée (véhicule tournant) : exclue
            segs.append((brg, [(e, n) for (_t, e, n) in near]))

        # Regroupement par axe (±20°) → 1 cluster = 1 branche
        clusters = []
        for brg, pts in segs:
            for cl in clusters:
                if _axial_diff(brg, cl['brg']) <= 20.0:
                    cl['pts'].extend(pts)
                    cl['brgs'].append(brg)
                    cl['n'] += 1
                    break
            else:
                clusters.append({'brg': brg, 'brgs': [brg], 'pts': list(pts), 'n': 1})

        branches = []
        # Seules les branches DOMINANTES (le bruit latéral à 10-20 m fragmente les
        # clusters secondaires) : tri par nombre de véhicules, max `max_branches`.
        clusters.sort(key=lambda c: -c['n'])
        for cl in clusters[:max_branches]:
            if cl['n'] < min_tracks:
                continue
            # Axe = moyenne axiale ; centreligne = point moyen + projections extrêmes
            sx = sum(math.cos(math.radians(b * 2)) for b in cl['brgs'])
            sy = sum(math.sin(math.radians(b * 2)) for b in cl['brgs'])
            brg = (math.degrees(math.atan2(sy, sx)) / 2.0) % 180.0
            ux, uy = math.sin(math.radians(brg)), math.cos(math.radians(brg))
            ce = sum(p[0] for p in cl['pts']) / len(cl['pts'])
            cn = sum(p[1] for p in cl['pts']) / len(cl['pts'])
            projs = sorted((p[0] - ce) * ux + (p[1] - cn) * uy for p in cl['pts'])
            perps = sorted(abs(-(p[0] - ce) * uy + (p[1] - cn) * ux) for p in cl['pts'])
            lo, hi = projs[int(len(projs) * 0.02)], projs[int(len(projs) * 0.98) - 1]
            half_w = perps[int(len(perps) * 0.85) - 1] + 1.0   # p85 dispersion + demi-gabarit
            a = (ce + ux * lo, cn + uy * lo)
            b = (ce + ux * hi, cn + uy * hi)
            branches.append({
                'a': [round(lat0 + a[1] / m_lat, 7), round(lon0 + a[0] / m_lon, 7)],
                'b': [round(lat0 + b[1] / m_lat, 7), round(lon0 + b[0] / m_lon, 7)],
                'bearing_deg': round(brg, 1),
                'width_m': round(max(3.0, min(12.0, 2 * half_w)), 1),
                'n_tracks': cl['n'],
            })
        if branches:
            out[str(wi)] = branches
    if out:
        logger.info("branches apprises : %s",
                    {k: len(v) for k, v in out.items()})
    return out
