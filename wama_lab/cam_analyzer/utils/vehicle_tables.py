"""Tableaux PAR VÉHICULE de la session — insertions aux intersections et dépassements (2026-10-29).

La colle de la passe `vehicle_tables` : lit ce que le tracking 360° a persisté (positions et vitesses monde
lissées `world_en` / `world_vel` par `global_track_id`, garés retenus) et ce que la passe Indicateurs a
annoté (`prediction_ttc` / `prediction_pet`), les remet au calcul pur
(`wama_data.functions.driving.vehicle_interactions`) et écrit les deux tableaux dans la sortie de la
session. Les exports CSV et le rapport les relisent : aucun ne recalcule.

Base de temps : le calcul se fait en temps GPS (celui des vitesses physiques et de la trajectoire de la
navette, `t = image / fps × échelle + décalage`, comme le tracker) ; les INSTANTS rapportés sont rendus en
temps VIDÉO, celui du lecteur — les durées, TTC et PET restent en secondes physiques.
"""
from __future__ import annotations

import json
import logging
import os
from collections import defaultdict

logger = logging.getLogger(__name__)

PASS_KEY = 'vehicle_tables'
#: Classes suivies comme véhicules (le piéton n'est ni inséré ni dépassant).
VEHICLE_CLASSES = ('car', 'truck', 'bus', 'motorcycle', 'bicycle')
#: Champs des lignes qui sont des INSTANTS (rendus en temps vidéo).
INSTANT_FIELDS = ('first_seen_s', 'last_seen_s', 't0_s', 'dmin_t_s', 'ttc_min_t_s', 't1_s', 't2_s',
                  't1_shuttle_lane_s', 't2_shuttle_lane_s', 't1_opposite_lane_s', 't2_opposite_lane_s',
                  'shuttle_at_entry_point_s', 't_start_s', 't_alongside_s', 't_end_s', 'cut_in_t_s')
#: Champs des lignes qui sont des DURÉES (secondes physiques, jamais converties). Tout champ en `_s` est
#: l'un ou l'autre (`tests_vehicle_tables`) : un instant oublié ici sortirait décalé, sans erreur.
DURATION_FIELDS = ('waited_s', 'duration_s', 'ttc_min_s', 'ttc_pred_min_s', 'pet_s', 'shuttle_time_margin_s',
                   'rear_ttc_min_s', 'cut_in_ttc_min_s')
#: Marge (s) autour d'une fenêtre pour le chemin de la navette.
PATH_MARGIN_S = 30.0


def output_path(session) -> str:
    from django.conf import settings
    from wama.common.utils.media_paths import app_media_dir
    return os.path.join(settings.MEDIA_ROOT, app_media_dir('cam_analyzer', session.user_id, 'output'),
                        'tables', str(session.id), 'vehicle_tables.json')


def read_tables(session) -> dict | None:
    """Les tableaux écrits par la passe, ou None si elle n'a pas été jouée."""
    path = output_path(session)
    if not os.path.isfile(path):
        return None
    with open(path, encoding='utf-8') as fh:
        return json.load(fh)


def _vehicle_observations(session, scale, off):
    """{gid: [(t_gps, e, n, ve, vn, classe, ttc, pet)…] triés} — une observation par image (moyenne des
    caméras qui la voient à la même image)."""
    from ..models import DetectionFrame
    cams = [c for c in session.cameras.all()]
    fps = (cams[0].fps if cams else None) or 12.0
    acc = defaultdict(lambda: defaultdict(list))
    classes = defaultdict(lambda: defaultdict(int))
    for cam in cams:
        rows = (DetectionFrame.objects.filter(camera=cam).values_list('frame_number', 'detections')
                .iterator(chunk_size=2000))
        for fn, found in rows:
            for d in found or []:
                gid, w = d.get('global_track_id'), d.get('world_en')
                if gid is None or not w or d.get('class_name') not in VEHICLE_CLASSES:
                    continue
                acc[gid][fn].append(d)
                classes[gid][d['class_name']] += 1
    out = {}
    for gid, frames in acc.items():
        cls = max(classes[gid], key=classes[gid].get)
        series = []
        for fn in sorted(frames):
            ds = frames[fn]
            e = sum(d['world_en'][0] for d in ds) / len(ds)
            n = sum(d['world_en'][1] for d in ds) / len(ds)
            vels = [d['world_vel'] for d in ds if d.get('world_vel')]
            ve = sum(v[0] for v in vels) / len(vels) if vels else 0.0
            vn = sum(v[1] for v in vels) / len(vels) if vels else 0.0
            ttcs = [d['prediction_ttc'] for d in ds if d.get('prediction_ttc') is not None]
            pets = [d['prediction_pet'] for d in ds if d.get('prediction_pet') is not None]
            series.append((fn / fps * scale + off, e, n, ve, vn, cls,
                           min(ttcs) if ttcs else None, min(pets) if pets else None))
        out[gid] = series
    return out


def compute_vehicle_tables(session) -> dict:
    """Calcule les deux tableaux de la session et les écrit ; rend le bilan."""
    import numpy as np
    from wama_data.functions.driving.vehicle_interactions import (PathFrame, ShuttleTrack, insertion_rows,
                                                                  overtaking_rows, LANE_WIDTH_M)
    from .ego_pose import effective_gps_track
    from .prediction_adapter import (CLASS_DIMS, SHUTTLE_DIMS, antenna_offset, gps_time_mapping,
                                     make_local_frame, shuttle_trajectory)
    gt = effective_gps_track(session)
    if len(gt) < 5:
        raise ValueError('trace GPS absente ou trop courte')
    to_local = make_local_frame(gt)
    sh = shuttle_trajectory(gt, to_local, antenna=antenna_offset(session))
    if len(sh) < 5:
        raise ValueError('trajectoire de la navette trop courte')
    scale, off = gps_time_mapping(session)

    def to_video(t):
        return None if t is None else round((t - off) / scale, 2)

    lane_w = float(getattr(session, 'lane_width_m', 0.0) or 0.0) or LANE_WIDTH_M
    lengths = {k: v[0] for k, v in CLASS_DIMS.items()}
    widths = {k: v[1] for k, v in CLASS_DIMS.items()}
    rs = session.results_summary or {}
    parked = {str(g) for g in (rs.get('stationary_global_tracks') or [])}
    vehicles = {str(g): obs for g, obs in _vehicle_observations(session, scale, off).items()}

    insertions = []
    for idx, w in enumerate(session.intersection_windows or []):
        if w.get('lat') is None or w.get('t_enter') is None:
            continue
        ta, tb = w['t_enter'] * scale + off, w['t_exit'] * scale + off
        part = sh[(sh[:, 0] >= ta - PATH_MARGIN_S) & (sh[:, 0] <= tb + PATH_MARGIN_S)]
        if len(part) < 3:
            continue
        try:
            path = PathFrame(part[:, 1:3])
        except ValueError:
            continue
        track = ShuttleTrack(part, path, length_m=SHUTTLE_DIMS[0], width_m=SHUTTLE_DIMS[1])
        local = {g: [o for o in obs if ta - PATH_MARGIN_S <= o[0] <= tb + PATH_MARGIN_S]
                 for g, obs in vehicles.items()}
        local = {g: obs for g, obs in local.items() if obs}
        window = {'name': w.get('name', ''), 'idx': idx, 't_enter': ta, 't_exit': tb,
                  'center': to_local(w['lat'], w['lon']), 'radius_m': w.get('radius_m')}
        insertions.extend(insertion_rows(window, track, local, parked=parked, lane_w=lane_w, lengths=lengths,
                                         widths=widths))
    overtakes = overtaking_rows(ShuttleTrack(sh, length_m=SHUTTLE_DIMS[0], width_m=SHUTTLE_DIMS[1]), vehicles,
                                parked=parked,
                                lane_w=lane_w, lengths=lengths, widths=widths)
    for row in insertions + overtakes:
        for key in INSTANT_FIELDS:
            if key in row:
                row[key] = to_video(row[key])
    for row in overtakes:
        row['intersection'] = _nearest_window(session.intersection_windows or [], row.get('t_alongside_s'))
    tables = {'insertions': insertions, 'overtakes': overtakes, 'lane_width_m': lane_w,
              'parked_excluded': len(parked), 'vehicles': len(vehicles)}
    path = output_path(session)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(tables, fh, ensure_ascii=False, default=lambda v: v.item() if isinstance(v, np.generic) else str(v))
    return {'insertions': len(insertions), 'inserted': sum(1 for r in insertions if r['inserted']),
            'overtakes': len(overtakes),
            'cut_ins': sum(1 for r in overtakes if r.get('cut_in')),
            'vehicles': len(vehicles), 'lane_width_m': lane_w}


def _nearest_window(windows, t):
    """Nom de la fenêtre d'intersection qui contient l'instant vidéo `t` ('' hors fenêtre)."""
    if t is None:
        return ''
    for w in windows:
        if w.get('t_enter') is not None and w['t_enter'] <= t <= w['t_exit']:
            return w.get('name', '')
    return ''


#: Colonnes des exports CSV, dans l'ordre de lecture (champ de ligne, en-tête) — déclarées plus bas dans
#: la forme de l'Exporter du monde Data (`EXPORTS`).
_INSERTION_FIELDS = (
    ('intersection', 'intersection'), ('window_idx', 'passage'), ('id', 'vehicule_G'),
    ('class_name', 'classe'), ('first_seen_s', 'vu_de_s'), ('last_seen_s', 'vu_jusqua_s'),
    ('inserted', 'insertion'), ('before_shuttle', 'insertion_avant_passage_navette'),
    ('after_shuttle', 'insertion_apres_passage_navette'), ('shuttle_lane', 'insertion_voie_navette'),
    ('opposite_lane', 'insertion_voie_opposee'),
    ('t0_s', 't0_premier_mouvement_s'), ('started_from_stop', 'depart_apres_arret'), ('waited_s', 'attente_s'),
    ('lane_t1_t2', 'voie_de_t1_t2'), ('t1_s', 't1_entree_voie_s'), ('t2_s', 't2_sortie_voie_s'),
    ('t2_kind', 't2_nature'),
    ('d0_m', 'd0_m'), ('d1_m', 'd1_m'), ('d2_m', 'd2_m'), ('dmin_m', 'dmin_m'), ('dmin_t_s', 'dmin_instant_s'),
    ('vmax_kmh', 'vmax_kmh'), ('ttc_min_s', 'ttc_min_observe_s'), ('ttc_min_distance_m', 'distance_au_ttc_min_m'),
    ('ttc_min_t_s', 'ttc_min_instant_s'), ('pet_s', 'pet_observe_s'), ('pet_first', 'pet_premier_passe'),
    ('ttc_pred_min_s', 'ttc_predit_min_s'),
    ('gap_to_shuttle_at_t1_m', 'ecart_au_centre_navette_a_t1_m'),
    ('shuttle_at_entry_point_s', 'navette_au_point_dentree_s'),
    ('shuttle_time_margin_s', 'marge_temporelle_navette_s'),
    ('rear_present', 'vehicule_arriere_navette'), ('rear_min_gap_m', 'arriere_distance_min_m'),
    ('rear_ttc_min_s', 'arriere_ttc_min_s'), ('rear_ttc_min_gap_m', 'arriere_distance_au_ttc_min_m'),
    ('rear_mean_gap_m', 'arriere_distance_moyenne_m'), ('rear_span', 'arriere_mesure_sur'),
    ('t1_shuttle_lane_s', 't1_voie_navette_s'), ('t2_shuttle_lane_s', 't2_voie_navette_s'),
    ('t1_opposite_lane_s', 't1_voie_opposee_s'), ('t2_opposite_lane_s', 't2_voie_opposee_s'),
)
_OVERTAKE_FIELDS = (
    ('id', 'vehicule_G'), ('class_name', 'classe'), ('direction', 'sens'), ('side', 'cote'),
    ('intersection', 'intersection'), ('t_start_s', 'debut_s'), ('t_alongside_s', 'a_hauteur_s'),
    ('t_end_s', 'fin_s'), ('duration_s', 'duree_s'), ('lateral_gap_min_m', 'ecart_lateral_min_m'),
    ('relative_speed_kmh', 'vitesse_relative_kmh'), ('vehicle_speed_kmh', 'vitesse_vehicule_kmh'),
    ('shuttle_speed_kmh', 'vitesse_navette_kmh'), ('vmax_kmh', 'vmax_kmh'), ('ttc_min_s', 'ttc_min_observe_s'),
    ('cut_in', 'rabattement'), ('cut_in_t_s', 'rabattement_instant_s'), ('cut_in_gap_m', 'rabattement_ecart_m'),
    ('cut_in_ttc_min_s', 'rabattement_ttc_min_s'),
)


def _table_export(name, fields):
    from wama_data.core.export import Column, Declaration, Identity
    return Declaration(name, tuple(Column(name, key, label) for key, label in fields), identite=Identity(()))


#: Les deux exports, déclarés comme tout export du monde Data (`wama_data/core/export.py`) : une
#: `Declaration` par tableau, rendue par le même `export` / `render` — pas un second écrivain CSV.
EXPORTS = {'insertions': _table_export('insertions', _INSERTION_FIELDS),
           'overtakes': _table_export('overtakes', _OVERTAKE_FIELDS)}


def _cell(key, value):
    """Une valeur lisible : le `G…` de la vue de dessus, oui/non pour un booléen ; une absence reste
    absente (`render` en fait une cellule vide)."""
    if key == 'id' and value is not None:
        return f'G{value}'
    if isinstance(value, bool):
        return 'oui' if value else 'non'
    return value


def csv_text(tables, kind) -> str:
    """Le CSV d'un des deux tableaux (`kind` : 'insertions' ou 'overtakes')."""
    from wama_data.core.export import export, render
    rows = [{k: _cell(k, v) for k, v in row.items()} for row in tables.get(kind) or []]
    (exported,) = export([EXPORTS[kind]], {'session': {kind: rows}})
    return render(exported)
