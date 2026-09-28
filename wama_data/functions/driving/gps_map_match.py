"""
Map-matching GPS — portage d'une toolbox tierce (`MapMatch.m`), capability-first.

Recale une trace GPS bruitée sur l'axe routier réel (plus-proche-segment) et attribue à
chaque échantillon : la SECTION routière, le SENS de circulation (±1, aller/retour), et un
CAP DE RÉFÉRENCE propre (bien plus stable que le cap de course GPS à basse vitesse).

Méthode (identique à l'original) :
- projection plane locale des waypoints et du véhicule (repère ENU centré sur la moyenne) ;
- distance²-point-segment (projection paramétrique t clampée [0,1]) sur tous les segments ;
- match si distance ≤ `max_dist_m` (défaut 20 m) → section + cap du segment ;
- sens : |Δ(cap véhicule, cap segment)| < angle_same → +1 ; > angle_opp → −1 ; sinon 0.

Entrée route (`road_map`) : polylignes WKT LINESTRING (lon lat). `load_road_map_csv` lit le
format export Google MyMaps (col. WKT, nom, description), le même que `Section CASA- sections.csv`.
"""
from __future__ import annotations

import math
import re

from wama.common.catalog.data_types import DataType, TypedFrame
from wama.common.catalog.function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                FunctionCategory, register)

_M_PER_DEG_LAT = 111320.0


def local_frame(center_lat, center_lon):
    """Projection plane ENU simple centrée (x=Est, y=Nord), en mètres — et son inverse.
    Suffisant à l'échelle d'un parcours ; cohérent avec `make_local_frame` de cam_analyzer.
    Rend (to_xy(lat, lon) → (x, y), to_ll(x, y) → (lat, lon)). Publique depuis le 2026-09-28 :
    `lane_map_matching` en a besoin, et la recopier en ferait une seconde projection à tenir."""
    m_lon = _M_PER_DEG_LAT * math.cos(math.radians(center_lat))

    def to_xy(lat, lon):
        return ((lon - center_lon) * m_lon, (lat - center_lat) * _M_PER_DEG_LAT)

    def to_ll(x, y):
        return (center_lat + y / _M_PER_DEG_LAT, center_lon + x / m_lon)
    return to_xy, to_ll


def _local_frame(center_lat, center_lon):
    """Aller seul de `local_frame` (appelants historiques du module)."""
    return local_frame(center_lat, center_lon)[0]


def _bearing_deg(lat1, lon1, lat2, lon2):
    """Cap initial grand-cercle (deg, 0=Nord, sens horaire) — comme UTL_ComputeBearing."""
    dlon = math.radians(lon2 - lon1)
    y = math.cos(math.radians(lat2)) * math.sin(dlon)
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon))
    return math.degrees(math.atan2(y, x)) % 360.0


def angle_diff(a, b):
    """Différence signée repliée dans [-180, 180] — comme UTL_AngleDiff."""
    return (a - b + 180.0) % 360.0 - 180.0


_angle_diff = angle_diff   # nom historique du module


def _dist2_point_segment(px, py, ax, ay, bx, by):
    """Distance² d'un point à un segment [A,B] (projection paramétrique clampée)."""
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 <= 1e-12:
        return (px - ax) ** 2 + (py - ay) ** 2
    t = ((px - ax) * dx + (py - ay) * dy) / seg2
    t = max(0.0, min(1.0, t))
    cx, cy = ax + t * dx, ay + t * dy
    return (px - cx) ** 2 + (py - cy) ** 2


def _parse_linestring(wkt):
    """'LINESTRING (lon lat, lon lat, …)' → [(lat, lon), …]."""
    m = re.search(r'\(([^)]*)\)', wkt or '')
    if not m:
        return []
    pts = []
    for pair in m.group(1).split(','):
        toks = pair.strip().split()
        if len(toks) >= 2:
            try:
                lon, lat = float(toks[0]), float(toks[1])
                pts.append((lat, lon))
            except ValueError:
                continue
    return pts


def load_road_map_csv(path):
    """Lit un CSV WKT (export MyMaps : WKT, nom, description) → TypedFrame `road_map`.
    Une ligne par section : geometry (liste de (lat,lon)), id, type (depuis description)."""
    import pandas as pd
    raw = pd.read_csv(path)
    rows = []
    for _, r in raw.iterrows():
        geom = _parse_linestring(str(r.get('WKT', '')))
        if len(geom) < 2:
            continue
        rows.append({'id': r.get('name'), 'type': (r.get('description') or None),
                     'geometry': geom})
    df = pd.DataFrame(rows)
    return TypedFrame(df, DataType.ROAD_MAP, meta={'source': str(path)})


def _build_segments(road_map: TypedFrame):
    """Précalcule tous les segments [(lat,lon)→(lat,lon)] + centre carte."""
    all_pts = []
    sections = []
    for _, row in road_map.df.iterrows():
        geom = row['geometry']
        sections.append((row.get('id'), geom))
        all_pts.extend(geom)
    if not all_pts:
        return [], None
    clat = sum(p[0] for p in all_pts) / len(all_pts)
    clon = sum(p[1] for p in all_pts) / len(all_pts)
    to_xy = _local_frame(clat, clon)
    segments = []   # (ax, ay, bx, by, seg_bearing, section_id)
    for sid, geom in sections:
        for i in range(1, len(geom)):
            (la, lo), (lb, lob) = geom[i - 1], geom[i]
            ax, ay = to_xy(la, lo)
            bx, by = to_xy(lb, lob)
            segments.append((ax, ay, bx, by, _bearing_deg(la, lo, lb, lob), sid))
    return segments, to_xy


# ── Rattachement CONTINU (Viterbi) — ajouté le 2026-09-28 ────────────────────────────────
# Le plus-proche-segment ci-dessus saute sur une route PARALLÈLE ou PERPENDICULAIRE dès que le
# GPS dérive (mesuré sur la session ENA : +11 à +15 m sur une parallèle, Δcap −78° à une
# intersection). Le Viterbi choisit la SUITE de tronçons la plus vraisemblable : distance, cap
# (au sens de circulation le plus proche, ignoré à l'arrêt où le cap est TENU) et continuité.

def road_segments(roads, to_xy):
    """Tronçons [{'coords': [(lon, lat)…], …}] → segments [{ax, ay, bx, by, bearing, road}]
    (bearing = cap du segment a→b ; `road` = index du tronçon dans `roads`)."""
    segs = []
    for ri, r in enumerate(roads):
        pts = [to_xy(lat, lon) for lon, lat in (r.get('coords') or [])]
        for (ax, ay), (bx, by) in zip(pts, pts[1:]):
            if math.hypot(bx - ax, by - ay) < 0.05:
                continue
            segs.append({'ax': ax, 'ay': ay, 'bx': bx, 'by': by, 'road': ri,
                         'bearing': math.degrees(math.atan2(bx - ax, by - ay)) % 360.0})
    return segs


def _project(px, py, s):
    """(distance, latéral signé à DROITE du sens a→b, dépassement) du point sur le segment.
    Le dépassement (m) est la distance, le long du segment, au-delà de l'extrémité la plus
    proche quand la projection tombe HORS du segment : le « latéral » n'est alors que la distance
    au bout, pas un écart perpendiculaire (vécu : l'impasse d'un parking, 2026-09-28)."""
    dx, dy = s['bx'] - s['ax'], s['by'] - s['ay']
    L2 = dx * dx + dy * dy
    t_raw = ((px - s['ax']) * dx + (py - s['ay']) * dy) / L2
    t = max(0.0, min(1.0, t_raw))
    d = math.hypot(px - s['ax'] - t * dx, py - s['ay'] - t * dy)
    cross = dx * (py - s['ay']) - dy * (px - s['ax'])        # > 0 : à GAUCHE de a→b
    return d, (-d if cross > 0 else d), abs(t_raw - t) * math.sqrt(L2)


def _connected(s1, s2, tol=2.0):
    ends1 = ((s1['ax'], s1['ay']), (s1['bx'], s1['by']))
    ends2 = ((s2['ax'], s2['ay']), (s2['bx'], s2['by']))
    return any(math.hypot(a[0] - b[0], a[1] - b[1]) <= tol for a in ends1 for b in ends2)


def match_track(points, segments, *, radius_m=25.0, sigma_d_m=4.0, sigma_h_deg=20.0,
                switch_cost=6.0, connected_cost=0.5):
    """Rattachement CONTINU d'une trace aux segments — Viterbi.

    `points` : [(x, y, heading_deg | None, moving: bool)]. Émission (d/σd)² + (Δcap/σh)² ;
    transition 0 sur le même tronçon, `connected_cost` vers un tronçon qui le touche,
    `switch_cost` sinon. Un point sans candidat dans `radius_m` coupe la chaîne (None).
    Rend, par point, None ou {'segment', 'road', 'dist_m', 'forward' (circulation dans le sens
    a→b du segment), 'lateral_m' (à droite du sens de CIRCULATION), 'bearing_deg' (axe orienté
    dans le sens de circulation), 'overshoot_m' (au-delà du bout du segment : 0 si la projection
    tombe dessus)}."""
    n = len(points)
    cands = []
    for x, y, h, mv in points:
        cs = []
        for si, s in enumerate(segments):
            d, lat_ab, over = _project(x, y, s)
            if d > radius_m:
                continue
            fwd, dh = True, 0.0
            if h is not None:
                d_ab = abs(angle_diff(h, s['bearing']))
                fwd = d_ab <= 90.0
                dh = d_ab if fwd else 180.0 - d_ab
            cost = (d / sigma_d_m) ** 2 + ((dh / sigma_h_deg) ** 2 if (mv and h is not None) else 0.0)
            cs.append((si, cost, d, lat_ab, fwd, over))
        cands.append(cs)

    out = [None] * n
    i = 0
    while i < n:
        if not cands[i]:
            i += 1
            continue
        j = i
        while j < n and cands[j]:
            j += 1
        back = [[(c[1], None) for c in cands[i]]]
        for k in range(i + 1, j):
            cur = []
            for c in cands[k]:
                sc = segments[c[0]]
                best = None
                for pi, pc in enumerate(cands[k - 1]):
                    sp = segments[pc[0]]
                    tr = 0.0 if sp['road'] == sc['road'] else (
                        connected_cost if _connected(sp, sc) else switch_cost)
                    v = back[-1][pi][0] + tr
                    if best is None or v < best[0]:
                        best = (v, pi)
                cur.append((best[0] + c[1], best[1]))
            back.append(cur)
        idx = min(range(len(back[-1])), key=lambda q: back[-1][q][0])
        for k in range(j - 1, i - 1, -1):
            si, _, d, lat_ab, fwd, over = cands[k][idx]
            s = segments[si]
            out[k] = {'segment': si, 'road': s['road'], 'dist_m': round(d, 3), 'forward': fwd,
                      'overshoot_m': round(over, 3),
                      'lateral_m': lat_ab if fwd else -lat_ab,
                      'bearing_deg': s['bearing'] if fwd else (s['bearing'] + 180.0) % 360.0}
            if k > i:
                idx = back[k - i][idx][1]
        i = j
    return out


def _map_match_continuous(out, road_map, max_dist_m):
    """`map_match(method='continuous')` : mêmes colonnes que le plus-proche-segment."""
    rows = road_map.df.to_dict('records')
    all_pts = [p for r in rows for p in (r.get('geometry') or [])]
    clat = sum(p[0] for p in all_pts) / len(all_pts)
    clon = sum(p[1] for p in all_pts) / len(all_pts)
    to_xy, _ = local_frame(clat, clon)
    roads = [{'coords': [(p[1], p[0]) for p in (r.get('geometry') or [])]} for r in rows]
    segs = road_segments(roads, to_xy)
    has_heading = 'heading' in out.columns
    pts = []
    for r in out.itertuples(index=False):
        lat, lon = getattr(r, 'lat'), getattr(r, 'lon')
        h = getattr(r, 'heading') if has_heading else None
        if lat is None or lon is None or lat != lat or lon != lon:
            pts.append((1e12, 1e12, None, False))
            continue
        v = getattr(r, 'speed_kmh', None)
        pts.append((*to_xy(lat, lon), None if h is None or h != h else float(h),
                    bool(v is None or (v == v and v > 3.6))))
    m = match_track(pts, segs, radius_m=max_dist_m)
    out['section_id'] = [rows[x['road']].get('id') if x else None for x in m]
    out['direction'] = [(1 if x['forward'] else -1) if (x and has_heading) else 0 for x in m]
    out['matched_bearing'] = [round(segs[x['segment']]['bearing'], 1) if x else None for x in m]
    out['match_dist_m'] = [round(x['dist_m'], 2) if x else None for x in m]
    return out


def map_match(track: TypedFrame, road_map: TypedFrame, *, max_dist_m=20.0,
              angle_same_deg=60.0, angle_opp_deg=120.0, method='nearest') -> TypedFrame:
    """Map-matching : enrichit `track` (geo_track) avec section_id / direction /
    matched_bearing / match_dist_m. Enricher — ne retire aucune colonne.

    `method` : 'nearest' (défaut, le portage d'origine, point par point) ou 'continuous'
    (Viterbi : distance + cap + continuité — ne saute pas sur une parallèle ni à un carrefour)."""
    out = track.df.copy()
    if method == 'continuous' and not road_map.df.empty:
        return TypedFrame(_map_match_continuous(out, road_map, max_dist_m), DataType.GEO_TRACK,
                          meta=track.meta)
    segments, to_xy = _build_segments(road_map)
    if not segments:
        for c in ('section_id', 'direction', 'matched_bearing', 'match_dist_m'):
            out[c] = None
        return TypedFrame(out, DataType.GEO_TRACK, meta=track.meta)

    has_heading = 'heading' in out.columns
    max2 = max_dist_m * max_dist_m
    sec, dirn, mbear, mdist = [], [], [], []
    for row in out.itertuples(index=False):
        lat, lon = getattr(row, 'lat'), getattr(row, 'lon')
        if lat is None or lon is None or (lat != lat) or (lon != lon):
            sec.append(None); dirn.append(0); mbear.append(None); mdist.append(None)
            continue
        px, py = to_xy(lat, lon)
        best = None
        best_d2 = max2
        for s in segments:
            d2 = _dist2_point_segment(px, py, s[0], s[1], s[2], s[3])
            if d2 < best_d2:
                best_d2, best = d2, s
        if best is None:
            sec.append(None); dirn.append(0); mbear.append(None); mdist.append(None)
            continue
        sec.append(best[5])
        mbear.append(round(best[4], 1))
        mdist.append(round(math.sqrt(best_d2), 2))
        d = 0
        if has_heading:
            hd = getattr(row, 'heading')
            if hd is not None and hd == hd:
                ad = abs(_angle_diff(hd, best[4]))
                d = 1 if ad < angle_same_deg else (-1 if ad > angle_opp_deg else 0)
        dirn.append(d)
    out['section_id'] = sec
    out['direction'] = dirn
    out['matched_bearing'] = mbear
    out['match_dist_m'] = mdist
    return TypedFrame(out, DataType.GEO_TRACK, meta=track.meta)


SPEC = register(FunctionSpec(
    key='gps_map_match',
    name='Map-matching GPS',
    description="Recale la trace GPS sur l'axe routier (plus-proche-segment) et attribue "
                "section, sens de circulation (±1) et cap de référence propre.",
    category=FunctionCategory.ENRICHER,
    tags=['geo', 'timeseries', 'requires-road-map'],
    inputs=[
        PortSpec('track', DataType.GEO_TRACK, required_fields=['lat', 'lon'],
                 description='Trace GPS (heading optionnel pour le sens).'),
        # `group='reference'` (marche C) : le référentiel SERT à recaler la trace, il n'est
        # pas transformé — même rôle que l'image de référence d'un Imager.
        PortSpec('road_map', DataType.ROAD_MAP, required_fields=['geometry'],
                 description='Polylignes routières de référence (WKT).', group='reference'),
    ],
    outputs=[
        PortSpec('track', DataType.GEO_TRACK,
                 produced_fields=['section_id', 'direction', 'matched_bearing', 'match_dist_m'],
                 description="La MÊME trace, enrichie du rattachement routier : section, sens "
                             "de circulation (±1) et cap de l'axe (`matched_bearing`, plus "
                             "propre que le cap GPS à basse vitesse). `match_dist_m` mesure la "
                             "confiance du rattachement — un point loin de tout axe garde ses "
                             "colonnes mais son `section_id` ne vaut rien."),
    ],
    params=[
        ParamSpec('max_dist_m', 'float', 20.0, 1.0, 100.0, unit='m',
                  description='Distance max de matching à un segment.'),
        ParamSpec('angle_same_deg', 'float', 60.0, 0.0, 180.0, unit='°',
                  description='Écart de cap sous lequel le sens = +1 (même sens).'),
        ParamSpec('angle_opp_deg', 'float', 120.0, 0.0, 180.0, unit='°',
                  description='Écart de cap au-dessus duquel le sens = −1 (sens inverse).'),
        ParamSpec('method', 'enum', 'nearest', choices=['nearest', 'continuous'],
                  description="'nearest' : segment le plus proche, point par point (portage "
                              "d'origine) ; 'continuous' : Viterbi distance + cap + continuité, "
                              "qui ne saute pas sur une route parallèle ni à un carrefour."),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=map_match,
))
