"""Recalage LATÉRAL et de CAP de la navette par la voie vue + l'axe routier IGN (⚑ lane_map_recalage).

Patron « calculer, stocker, basculer » (celui de ⚑ shuttle_filter) : `compute_lane_map_recalage`
est un CALCUL (CPU + réseau IGN, rejouable) qui écrit `results_summary['lane_map_recalage'] =
{'track': [{ts, de_m, dn_m, dh_deg, anchored}], 'report': {…}}` ; la bascule ne fait que CHOISIR,
à la lecture, d'appliquer ou non la correction — côté serveur dans `ego_pose.effective_gps_track`,
côté JS par `_applyLaneMapRecalage`, au même point d'ingestion unique.

Toute la géométrie est dans la brique pure `wama_data.functions.driving.lane_map_matching` ; ce
module ne fait que l'ORM, la projection au sol des lignes YOLOPv2 (calib de la caméra avant) et
la collecte des tronçons BD TOPO le long du parcours.

Mesure fondatrice (2026-09-28, Roumanille-Poincaré) : GPS ≈ 2 m trop à droite de ce que disent
l'axe IGN et la voie vue par la caméra, cap figé à −5,9° pendant un arrêt.
"""
import logging
import math

import pandas as pd

logger = logging.getLogger(__name__)

#: Cadence des observations de voie (s, temps vidéo) : les lignes YOLOPv2 bougent lentement.
OBS_EVERY_S = 0.5
#: Bande de lecture des lignes DEVANT la caméra avant (m) — la plus fiable à 384×248.
Y_BAND_CAMERA = (5.0, 10.0)
#: Espacement des requêtes BD TOPO le long du parcours, et leur rayon (m).
ROADS_SPACING_M, ROADS_RADIUS_M = 200.0, 250.0
#: Largeurs de voie acceptées AVANT correction d'échelle (m, projection brute) — le filtre
#: réel (2,2–4,8 m) s'applique dans la brique, une fois l'échelle mesurée contre la carte.
LANE_WIDTH_RAW_M = (1.5, 10.0)


def _front_projector(session, geo):
    """GroundProjector de la caméra avant : calib sol stockée, sinon le plan de profondeur."""
    from .prediction_adapter import ground_projector_for
    gp = ground_projector_for(session, 'front', geo)
    if gp is not None:
        return gp, 'ground_calib'
    plane = ((session.results_summary or {}).get('depth_planes') or {}).get('front') or {}
    if 'skipped' in plane or not plane.get('pitch_deg'):
        return None, None
    s2 = type('S', (), {})()
    s2.config = {**(session.config or {}), 'ground_calib': {
        'front': {'pitch_deg': plane['pitch_deg'], 'height_m': plane['height_m']}}}
    return ground_projector_for(s2, 'front', geo), 'depth_plane'


def lane_observations(session, stats=None):
    """Observations de voie de la caméra avant, en temps GPS : [{ts, offset_m, width_m,
    rel_heading_deg}] — écart du CENTRE ARRIÈRE du véhicule (origine des montages et de la pose)
    au centre de sa voie. Les lignes sont passées dans le repère VÉHICULE (lacet et bras de
    levier de la caméra) avant l'ajustement : un lacet de montage biaiserait sinon le cap relatif.
    `stats` (dict), s'il est fourni, reçoit le compte des images écartées par porte."""
    if stats is None:
        stats = {}
    stats.update(frames_with_lanes=0, fewer_than_two_lines=0, no_lane_pair=0)
    from wama_data.functions.driving.lane_map_matching import lane_observation
    from ..models import DetectionFrame
    from .prediction_adapter import camera_geometry, video_to_gps_time

    cam = session.cameras.filter(position='front').first()
    if cam is None:
        return [], 'pas de caméra avant'
    geo = camera_geometry(session)['front']
    gp, source = _front_projector(session, geo)
    if gp is None:
        return [], 'caméra avant non calibrée (ni calib sol ni plan de profondeur)'
    yaw, (mx, my) = math.radians(geo['yaw']), geo['mount']

    def to_vehicle(pt):
        if pt is None:
            return None
        X, Y = pt
        return (Y * math.sin(yaw) + X * math.cos(yaw) + mx, Y * math.cos(yaw) - X * math.sin(yaw) + my)

    band = (Y_BAND_CAMERA[0] + my, Y_BAND_CAMERA[1] + my)
    out, last = [], -1e9
    qs = (DetectionFrame.objects.filter(camera=cam).order_by('frame_number')
          .values_list('timestamp', 'detections'))
    for ts, dets in qs.iterator(chunk_size=2000):
        if ts is None or ts - last < OBS_EVERY_S:
            continue
        lines = [d.get('polygon') for d in (dets or [])
                 if d.get('type') == 'road_mask' and 'lane' in str(d.get('class_name') or '').lower()
                 and len(d.get('polygon') or []) >= 2]
        if len(lines) < 2:
            if lines:
                stats['fewer_than_two_lines'] += 1
            continue
        last = ts
        stats['frames_with_lanes'] += 1
        pts = [[to_vehicle(gp.project(u, v)) for u, v in ln] for ln in lines]
        # largeur LARGE ici : l'échelle latérale de la projection n'est connue qu'une fois
        # confrontée à la carte — la brique pure ramène puis filtre (`lateral_scale`)
        obs = lane_observation(pts, y_band=band, eval_y=0.0, width_range=LANE_WIDTH_RAW_M)
        if not obs:
            stats['no_lane_pair'] += 1
        else:
            out.append({'ts': video_to_gps_time(session, ts), 'offset_m': obs['offset_m'],
                        'width_m': obs['width_m'], 'rel_heading_deg': obs['rel_heading_deg']})
    return out, source


def roads_along(track, *, spacing_m=ROADS_SPACING_M, radius_m=ROADS_RADIUS_M):
    """Tronçons BD TOPO le long d'une trace — une requête tous les `spacing_m`, dédoublonnés."""
    from wama_data.functions.geo.ign_vector import fetch_roads
    seen, roads, last = set(), [], None
    for p in track:
        if p.get('lat') is None or p.get('lon') is None:
            continue
        if last is not None:
            d = math.hypot((p['lat'] - last[0]) * 111320.0,
                           (p['lon'] - last[1]) * 111320.0 * math.cos(math.radians(p['lat'])))
            if d < spacing_m:
                continue
        last = (p['lat'], p['lon'])
        for r in fetch_roads(p['lat'], p['lon'], radius_m):
            key = r.get('id') or tuple(r['coords'][0]) + tuple(r['coords'][-1])
            if key not in seen:
                seen.add(key)
                roads.append(r)
    return roads


def centre_track(session, track):
    """La trace au CENTRE ARRIÈRE du véhicule (le GPS mesure l'ANTENNE, `antenna_offset`) —
    même levier que `shuttle_trajectory`. Sans cap, le point reste celui de l'antenne."""
    from .prediction_adapter import antenna_offset
    ax, ay = antenna_offset(session)
    out = []
    for p in track:
        if p.get('lat') is None or p.get('lon') is None:
            continue
        lat, lon, h = p['lat'], p['lon'], p.get('heading')
        if h is not None and (ax or ay):
            hr = math.radians(h)
            de = -(ay * math.sin(hr) + ax * math.cos(hr))
            dn = -(ay * math.cos(hr) - ax * math.sin(hr))
            lat += dn / 111320.0
            lon += de / (111320.0 * math.cos(math.radians(lat)))
        out.append({'ts': p['ts'], 'lat': lat, 'lon': lon, 'heading': h,
                    'speed_kmh': p.get('speed_kmh')})
    return out


def compute_lane_map_recalage(session, *, persist=True):
    """Calcule la correction et la PERSISTE (`persist=False` : mesure seule). Rend le rapport."""
    from wama.common.catalog.data_types import DataType, TypedFrame
    from wama_data.functions.driving.lane_map_matching import lane_map_recalage
    from .ego_pose import effective_gps_track

    gt = effective_gps_track(session, lane_map=False)   # ni elle-même ni l'ortho (appliquée après)
    frames = {}
    lanes, source = lane_observations(session, frames)
    report = {'lane_observations': len(lanes), 'projection': source, 'lane_frames': frames}
    if not lanes:
        report['skipped'] = source or 'aucune observation de voie'
        return report
    roads = roads_along(gt)
    report['roads'] = len(roads)
    if not roads:
        report['skipped'] = 'aucun tronçon BD TOPO (réseau IGN injoignable ?)'
        return report
    ctr = centre_track(session, gt)
    rm = pd.DataFrame([{'geometry': [(la, lo) for lo, la in r['coords']], 'nb_voies': r.get('nb_voies'),
                        'largeur_m': r.get('largeur'), 'sens': r.get('sens'), 'type': r.get('nature')}
                       for r in roads])
    out = lane_map_recalage(TypedFrame(pd.DataFrame(ctr), DataType.GEO_TRACK),
                            TypedFrame(rm, DataType.ROAD_MAP),
                            TypedFrame(pd.DataFrame(lanes), DataType.TABLE))
    report.update(out.meta.get('lane_map') or {})
    rows = [{'ts': float(r.ts), 'de_m': float(r.corr_de_m), 'dn_m': float(r.corr_dn_m),
             'dh_deg': float(r.corr_dh_deg), 'anchored': bool(r.lane_anchored)}
            for r in out.df.itertuples(index=False)]
    if persist:
        session.refresh_from_db(fields=['results_summary'])
        rs = session.results_summary or {}
        rs['lane_map_recalage'] = {'track': rows, 'report': report}
        session.results_summary = rs
        session.save(update_fields=['results_summary'])
    logger.info('[lane_map] %s', report)
    return report
