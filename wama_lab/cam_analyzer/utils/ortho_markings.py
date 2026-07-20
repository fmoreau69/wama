"""
Recalage ABSOLU par marquages ortho — étape 2b du plan de calibration sol
(CAM_ANALYZER_CHAINE_TRAITEMENT.md, idée Fabien validée 2026-07-20).

L'orthophoto IGN est géoréférencée par construction. On y segmente les passages piétons
avec SAM3 (vus du ciel → positions ABSOLUES lat/lon), puis on les MATCHE avec les
crossings agrégés depuis les caméras (`marking_world.py`). Le décalage médian mesuré =
offset de recalage par intersection (biais GPS + biais de projection caméra). C'est
l'ÉCHELLE/POSITION absolue que le solveur d'étalement 2a (angle seul) ne peut pas donner.

Complémentarité (jamais confondre) : 2a = ANGLE via ego-motion (sans vérité terrain) ;
2b = POSITION absolue via géométrie géoréférencée connue. Les crossings ortho n'ont pas
de correspondance inter-frame → ils entrent par la géométrie connue, pas par l'étalement.

v1 = fetch + segmentation + matching + RAPPORT (offset par intersection stocké dans
`results_summary['ortho_recalage']` + crossings ortho pour affichage). L'APPLICATION de
l'offset au positionnement se fera derrière une bascule après validation visuelle.
"""
import logging
import math

logger = logging.getLogger(__name__)

TILE = 256
_WMTS = ("https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0"
         "&LAYER=ORTHOIMAGERY.ORTHOPHOTOS&STYLE=normal&TILEMATRIXSET=PM"
         "&FORMAT=image/jpeg&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}")
ORTHO_ZOOM = 19          # 20 non servi partout (404) ; 19 ≈ 0.22 m/px, suffisant pour zébras


def _proxies():
    """Proxy pour joindre geopf.fr depuis WSL : settings.CAM_ANALYZER_ORTHO_PROXY,
    sinon HTTP(S)_PROXY de l'environnement (le worker Celery en hérite en général)."""
    import os
    try:
        from django.conf import settings
        p = getattr(settings, 'CAM_ANALYZER_ORTHO_PROXY', None)
    except Exception:
        p = None
    p = p or os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')
    return {'http': p, 'https': p} if p else None


def _lonlat_to_tilexy(lon, lat, z):
    n = 2 ** z
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    return x, y


def _tilexy_to_lonlat(x, y, z):
    n = 2 ** z
    lon = x / n * 360.0 - 180.0
    lat = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n))))
    return lon, lat


def fetch_ortho_mosaic(lat, lon, radius_m=45.0, zoom=ORTHO_ZOOM, session_headers=None):
    """Mosaïque BGR des tuiles ortho couvrant un carré ~2·radius_m autour de (lat, lon).
    Retourne (image_bgr, to_lonlat) où to_lonlat(px, py) -> (lon, lat) (exact, Web Mercator).
    None si le réseau échoue."""
    import numpy as np
    import cv2
    import requests

    mpp = 156543.03 * math.cos(math.radians(lat)) / (2 ** zoom)
    half_px = radius_m / mpp
    cx, cy = _lonlat_to_tilexy(lon, lat, zoom)
    tx0 = int(math.floor(cx - half_px / TILE))
    ty0 = int(math.floor(cy - half_px / TILE))
    tx1 = int(math.floor(cx + half_px / TILE))
    ty1 = int(math.floor(cy + half_px / TILE))
    cols, rows = tx1 - tx0 + 1, ty1 - ty0 + 1
    if cols > 6 or rows > 6:
        return None   # garde-fou : rayon déraisonnable
    proxies = _proxies()
    mosaic = np.zeros((rows * TILE, cols * TILE, 3), dtype=np.uint8)
    ok = 0
    for j in range(rows):
        for i in range(cols):
            url = _WMTS.format(z=zoom, x=tx0 + i, y=ty0 + j)
            try:
                r = requests.get(url, timeout=25, headers=session_headers or {},
                                 proxies=proxies)
                if r.status_code != 200:
                    continue
                tile = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
                if tile is None or tile.shape[:2] != (TILE, TILE):
                    continue
                mosaic[j * TILE:(j + 1) * TILE, i * TILE:(i + 1) * TILE] = tile
                ok += 1
            except Exception:
                logger.debug('ortho tile fetch failed z%s x%s y%s', zoom, tx0 + i, ty0 + j)
    if ok == 0:
        return None

    def to_lonlat(px, py):
        gx = tx0 + px / TILE
        gy = ty0 + py / TILE
        return _tilexy_to_lonlat(gx, gy, zoom)

    return mosaic, to_lonlat


def _poly_centroid_lonlat(poly, to_lonlat):
    if not poly:
        return None
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    return to_lonlat(cx, cy)


def segment_ortho_crossings(session, radius_m=45.0, min_conf=0.35):
    """Segmente les passages piétons sur l'ortho autour de chaque intersection.
    Retourne {intersection_index: [ {lat, lon, poly_latlon, conf} ]}.
    Charge SAM3 une fois (GPU). Nécessite le réseau (proxy WSL)."""
    wins = session.intersection_windows or []
    if not wins:
        return {}
    # lieux physiques (dédup lat/lon)
    places = {}
    for wi, w in enumerate(wins):
        if w.get('lat') is None:
            continue
        places.setdefault((round(w['lat'], 5), round(w['lon'], 5)), []).append(wi)
    if not places:
        return {}

    from .sam3_road_analyzer import SAM3RoadAnalyzer
    analyzer = SAM3RoadAnalyzer(
        marking_prompts=[{'label': 'crossing', 'prompt': 'pedestrian crossing zebra stripes'}],
        device='cuda')
    analyzer.load()
    out = {}
    try:
        for (lat, lon), wids in places.items():
            mos = fetch_ortho_mosaic(lat, lon, radius_m)
            if not mos:
                logger.warning('ortho mosaic indisponible pour %s,%s', lat, lon)
                continue
            image, to_lonlat = mos
            dets = analyzer.analyze_frame(image, min_confidence=min_conf)
            crossings = []
            for d in dets:
                if 'cross' not in (d.get('label') or '').lower():
                    continue
                poly = d.get('polygon') or []
                if not poly and d.get('bbox'):
                    b = d['bbox']
                    poly = [[b[0], b[1]], [b[2], b[1]], [b[2], b[3]], [b[0], b[3]]]
                cll = _poly_centroid_lonlat(poly, to_lonlat)
                if not cll:
                    continue
                poly_ll = [list(to_lonlat(p[0], p[1])[::-1]) for p in poly[:40]]  # [lat, lon]
                crossings.append({'lat': round(cll[1], 7), 'lon': round(cll[0], 7),
                                  'poly_latlon': [[round(a, 7), round(b, 7)] for a, b in poly_ll],
                                  'conf': round(float(d.get('confidence') or 0), 2)})
            for wi in wids:
                out[str(wi)] = crossings
            logger.info('ortho crossings @ %s,%s : %d', lat, lon, len(crossings))
    finally:
        analyzer.unload()
    return out


def _dist_m(lat1, lon1, lat2, lon2):
    m_lat = 111320.0
    m_lon = 111320.0 * math.cos(math.radians(lat1))
    return math.hypot((lat2 - lat1) * m_lat, (lon2 - lon1) * m_lon)


def match_recalage(session, ortho_crossings, max_match_m=12.0):
    """Apparie chaque crossing CAMÉRA (marking_world) au crossing ORTHO le plus proche
    et retourne l'offset médian (décalage caméra→ortho) par intersection + global.
    Retourne {'per_window': {wi: {de_m, dn_m, n}}, 'global': {de_m, dn_m, n}}."""
    cam_marks = (session.results_summary or {}).get('intersection_markings') or {}
    m_lat = 111320.0
    per_window = {}
    all_de, all_dn = [], []
    for wi, ocs in ortho_crossings.items():
        cam = [m for m in (cam_marks.get(wi) or []) if m.get('label') == 'crossing']
        if not cam or not ocs:
            continue
        m_lon = 111320.0 * math.cos(math.radians(ocs[0]['lat']))
        des, dns = [], []
        for cm in cam:
            # centre du segment caméra (a,b en [lat,lon])
            clat = (cm['a'][0] + cm['b'][0]) / 2.0
            clon = (cm['a'][1] + cm['b'][1]) / 2.0
            best, bd = None, max_match_m
            for oc in ocs:
                dd = _dist_m(clat, clon, oc['lat'], oc['lon'])
                if dd < bd:
                    bd, best = dd, oc
            if best:
                des.append((best['lon'] - clon) * m_lon)   # est (m)
                dns.append((best['lat'] - clat) * m_lat)    # nord (m)
        if des:
            des.sort(); dns.sort()
            per_window[wi] = {'de_m': round(des[len(des) // 2], 2),
                              'dn_m': round(dns[len(dns) // 2], 2), 'n': len(des)}
            all_de.extend(des); all_dn.extend(dns)
    result = {'per_window': per_window}
    if all_de:
        all_de.sort(); all_dn.sort()
        result['global'] = {'de_m': round(all_de[len(all_de) // 2], 2),
                            'dn_m': round(all_dn[len(all_dn) // 2], 2), 'n': len(all_de)}
    return result
