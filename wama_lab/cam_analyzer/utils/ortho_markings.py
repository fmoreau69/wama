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
    """Proxy pour joindre geopf.fr depuis WSL — délègue à la brique commune
    (`common/utils/http_proxy.py`, extraite 2026-07-29 ; le réglage historique
    `CAM_ANALYZER_ORTHO_PROXY` reste honoré)."""
    from wama.common.utils.http_proxy import outbound_proxies
    return outbound_proxies('CAM_ANALYZER_ORTHO_PROXY')


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


#: Un passage piéton de la caméra et celui de l'orthophoto ne sont appariés qu'à moins de cet écart
#: le long de la marche (au-delà : autre marquage).
PASS_MATCH_M = 8.0
#: Le passage ortho doit couper la route de la navette : son étendue latérale (repère navette)
#: englobe la trajectoire à cette marge près ; côté caméra, seuls les points de contact à moins de
#: `PASS_LATERAL_M` de l'axe comptent (un passage d'une rue latérale ne dit rien du « le long »).
PASS_PATH_MARGIN_M = 1.0
PASS_LATERAL_M = 6.0
PASS_MIN_OBS = 5


def measure_passes(session):
    """Écart LE LONG DE LA MARCHE, passage par passage, entre un passage piéton vu par la caméra
    avant et le même passage sur l'orthophoto (2026-10-01).

    Pourquoi par passage : `match_recalage` compare des marquages agrégés PAR LIEU (tous passages
    confondus). Sur ENA_CASA les 14 fenêtres appariées sont 14 traversées du MÊME carrefour : une
    seule mesure, recopiée 14 fois, que la décomposition classait entièrement en biais caméra —
    correction nulle partout, alors que la navette était dessinée 5 à 7 m trop en arrière à 2983 s.

    Pourquoi le BORD PROCHE : la caméra voit le bord bas du marquage (le plus proche) ; le bord proche
    du polygone ortho change donc avec le sens de marche. Comparer des centres fabriquerait un écart
    qui s'inverse avec le sens — la signature même qui sépare biais caméra et biais GPS.

    Rend (passes, rapport) : passes = [{'key', 'ts' (temps GPS), 'heading_deg', 'along_m', 'n'}],
    `along_m` > 0 : la carte place le passage PLUS LOIN que la caméra ne le voit — la navette est
    dessinée en arrière de sa position vraie."""
    import statistics
    from ..models import DetectionFrame
    from .marking_world import _LABEL_KIND, _projector_for, contact_points
    from .ego_pose import effective_gps_track
    from .prediction_adapter import (make_local_frame, shuttle_trajectory, antenna_offset,
                                     camera_geometry, _shuttle_pose_at, video_to_gps_time)
    rs = session.results_summary or {}
    ortho = rs.get('ortho_markings') or {}
    report = {'windows': 0, 'measured': 0, 'skipped': {}}
    cam = session.cameras.filter(position='front').first()
    if cam is None or not ortho:
        report['reason'] = 'pas de caméra avant' if cam is None else 'aucun passage ortho segmenté'
        return [], report
    geo = camera_geometry(session).get('front')
    gp, _cal = _projector_for(cam, geo) if geo else (None, False)
    if gp is None:
        report['reason'] = 'caméra avant sans calibration sol (lancer « Tracking 360° »)'
        return [], report
    # la mesure ne lit JAMAIS sa propre correction (même règle que `marking_world`)
    gt = effective_gps_track(session, ortho=False)
    to_local = make_local_frame(gt)
    sh_traj = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    yaw, mnt = math.radians(geo['yaw']), geo.get('mount') or (0.0, 0.0)
    passes = []
    for wi, w in enumerate(session.intersection_windows or []):
        polys = [[to_local(p[0], p[1]) for p in oc.get('poly_latlon') or []]
                 for oc in ortho.get(str(wi)) or ortho.get(wi) or []]
        polys = [p for p in polys if len(p) >= 3]
        if not polys or w.get('t_enter') is None or w.get('t_exit') is None:
            continue
        report['windows'] += 1
        deltas, stamps, heads = [], [], []
        qs = (DetectionFrame.objects.filter(camera=cam, timestamp__gte=w['t_enter'],
                                            timestamp__lte=w['t_exit'])
              .order_by('frame_number').only('detections', 'timestamp'))
        for df in qs.iterator(chunk_size=500):
            dets = [d for d in (df.detections or []) if d.get('type') == 'sam3_marking'
                    and _LABEL_KIND.get((d.get('label') or d.get('class_name') or '').lower()) == 'crossing']
            if not dets:
                continue
            tg = video_to_gps_time(session, df.timestamp)
            se, sn, hd = _shuttle_pose_at(sh_traj, tg)
            ue, un = math.sin(math.radians(hd)), math.cos(math.radians(hd))
            # bord proche (repère navette) des passages ortho qui COUPENT la route, devant
            ahead = []
            for P in polys:
                along = [(e - se) * ue + (n - sn) * un for e, n in P]
                lat = [(e - se) * un - (n - sn) * ue for e, n in P]
                if min(lat) <= PASS_PATH_MARGIN_M and max(lat) >= -PASS_PATH_MARGIN_M and min(along) > 0:
                    ahead.append(min(along))
            if not ahead:
                continue
            map_near = min(ahead)
            for d in dets:
                pts = [lo for la, lo in contact_points(d, gp, yaw, mnt) if abs(la) <= PASS_LATERAL_M]
                if not pts:
                    continue
                # flottants PYTHON : la projection rend du numpy, que `results_summary` (JSON)
                # refuserait à l'écriture
                delta = float(map_near - min(pts))
                if abs(delta) <= PASS_MATCH_M:
                    deltas.append(delta)
                    stamps.append(float(tg))
                    heads.append(float(hd))
        if len(deltas) < PASS_MIN_OBS:
            report['skipped'][str(wi)] = len(deltas)
            continue
        # cap médian en circulaire (un passage plein nord oscille entre 359° et 1°)
        hx = statistics.median(math.sin(math.radians(h)) for h in heads)
        hy = statistics.median(math.cos(math.radians(h)) for h in heads)
        passes.append({'key': str(wi), 'ts': round(statistics.median(stamps), 2),
                       'heading_deg': round(math.degrees(math.atan2(hx, hy)) % 360.0, 1),
                       'along_m': round(statistics.median(deltas), 2), 'n': len(deltas)})
    report['measured'] = len(passes)
    return passes, report


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
