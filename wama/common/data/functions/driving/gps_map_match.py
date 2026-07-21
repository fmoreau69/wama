"""
Map-matching GPS — portage toolbox tierce `MapMatch.m` (partenaire/ENA), capability-first.

Recale une trace GPS bruitée sur l'axe routier réel (plus-proche-segment) et attribue à
chaque échantillon : la SECTION routière, le SENS de circulation (±1, aller/retour), et un
CAP DE RÉFÉRENCE propre (bien plus stable que le cap de course GPS à basse vitesse).

Méthode (identique à toolbox tierce) :
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

from ..data_types import DataType, TypedFrame
from ..function_catalog import (FunctionSpec, PortSpec, ParamSpec,
                                FunctionCategory, register)

_M_PER_DEG_LAT = 111320.0


def _local_frame(center_lat, center_lon):
    """Projection plane ENU simple centrée (x=Est, y=Nord), en mètres. Suffisant à
    l'échelle d'un parcours ; cohérent avec `make_local_frame` de cam_analyzer."""
    m_lon = _M_PER_DEG_LAT * math.cos(math.radians(center_lat))

    def to_xy(lat, lon):
        return ((lon - center_lon) * m_lon, (lat - center_lat) * _M_PER_DEG_LAT)
    return to_xy


def _bearing_deg(lat1, lon1, lat2, lon2):
    """Cap initial grand-cercle (deg, 0=Nord, sens horaire) — comme UTL_ComputeBearing."""
    dlon = math.radians(lon2 - lon1)
    y = math.cos(math.radians(lat2)) * math.sin(dlon)
    x = (math.cos(math.radians(lat1)) * math.sin(math.radians(lat2))
         - math.sin(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.cos(dlon))
    return math.degrees(math.atan2(y, x)) % 360.0


def _angle_diff(a, b):
    """Différence signée repliée dans [-180, 180] — comme UTL_AngleDiff."""
    return (a - b + 180.0) % 360.0 - 180.0


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
        rows.append({'id': r.get('nom'), 'type': (r.get('description') or None),
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


def map_match(track: TypedFrame, road_map: TypedFrame, *, max_dist_m=20.0,
              angle_same_deg=60.0, angle_opp_deg=120.0) -> TypedFrame:
    """Map-matching : enrichit `track` (geo_track) avec section_id / direction /
    matched_bearing / match_dist_m. Enricher — ne retire aucune colonne."""
    out = track.df.copy()
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
        PortSpec('road_map', DataType.ROAD_MAP, required_fields=['geometry'],
                 description='Polylignes routières de référence (WKT).'),
    ],
    outputs=[
        PortSpec('track', DataType.GEO_TRACK,
                 produced_fields=['section_id', 'direction', 'matched_bearing', 'match_dist_m']),
    ],
    params=[
        ParamSpec('max_dist_m', 'float', 20.0, 1.0, 100.0, unit='m',
                  description='Distance max de matching à un segment.'),
        ParamSpec('angle_same_deg', 'float', 60.0, 0.0, 180.0, unit='°',
                  description='Écart de cap sous lequel le sens = +1 (même sens).'),
        ParamSpec('angle_opp_deg', 'float', 120.0, 0.0, 180.0, unit='°',
                  description='Écart de cap au-dessus duquel le sens = −1 (sens inverse).'),
    ],
    cost={'cpu_bound': True},
    projects=['ENA'],
    fn=map_match,
))
