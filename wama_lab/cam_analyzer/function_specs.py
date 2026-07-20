"""
Déclaration CAPABILITY des traitements cam_analyzer dans le catalogue WAMA Data.

But : n'oublier AUCUN traitement déjà intégré et l'exprimer dans le même langage de
capacités que les fonctions pures WAMA Data (voir `WAMA_DATA_FUNCTION_CARDS.md`).

Ces fonctions sont pour l'instant `binding='app'` : couplées à `AnalysisSession` (elles
lisent/écrivent la BDD via des passes Celery), donc cataloguées mais pas encore chaînables
comme les fonctions pures. Le portage vers `binding='pure'` (adaptateur de ports
detections/geo_track ↔ TypedFrame) se fera au cas par cas quand on voudra les chaîner.

Importé au chargement de l'app (`apps.py::ready`) → tout le catalogue voit ces traitements.
"""
from wama.common.data.data_types import DataType as DT
from wama.common.data.function_catalog import (
    FunctionSpec, PortSpec, ParamSpec, FunctionCategory as FC, Binding, register)

_APP = 'cam_analyzer'


def _spec(key, name, desc, category, impl, tags, inputs, outputs, params=None, cost=None):
    return register(FunctionSpec(
        key=f'cam_analyzer.{key}', name=name, description=desc, category=category,
        binding=Binding.APP, app=_APP, impl=impl, tags=tags,
        inputs=inputs, outputs=outputs, params=params or [], cost=cost or {}))


# ── Détection & segmentation image ────────────────────────────────────────────
_spec('yolo_detect', 'Détection YOLO', "Détection/segmentation d'objets par frame (ultralytics).",
      FC.DETECTOR, 'cam_analyzer.tasks:process_session_task', ['vision', 'gpu'],
      inputs=[PortSpec('video', DT.TABLE, description='Frames caméra (RTMaps).')],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['frame', 'bbox', 'class_name', 'confidence', 'track_id'])],
      cost={'vram_gb': 4})

_spec('yolopv2_lanes', 'Zone roulable + voies (YOLOPv2)', "Segmentation zone roulable + lignes de voie.",
      FC.DETECTOR, 'cam_analyzer.tasks:process_session_task', ['vision', 'gpu'],
      inputs=[PortSpec('video', DT.TABLE)],
      outputs=[PortSpec('lanes', DT.DETECTIONS, produced_fields=['drivable', 'lane'])],
      cost={'vram_gb': 3})

_spec('sam3_markings', 'Marquages SAM3', "Marquages au sol (passages piétons, lignes d'arrêt) segmentés par SAM3.",
      FC.DETECTOR, 'cam_analyzer.tasks:analyze_sam3_only_task', ['vision', 'gpu'],
      inputs=[PortSpec('video', DT.TABLE)],
      outputs=[PortSpec('markings', DT.DETECTIONS, produced_fields=['label', 'polygon', 'bbox'])],
      params=[ParamSpec('sam3_fps', 'float', 2.0, 0.5, 12.0, 'img/s', 'Cadence de segmentation.')],
      cost={'vram_gb': 8})

# ── Positionnement / géométrie ────────────────────────────────────────────────
_spec('distance', 'Distance / vitesse / TTC', "Distance pinhole/homographie + vitesse et TTC filtrés par track.",
      FC.ENRICHER, 'cam_analyzer.tasks:compute_distance_task', ['vision', 'geo'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id']),
              PortSpec('track', DT.GEO_TRACK, optional=True)],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['distance_m', 'speed', 'ttc', 'ground_xy'])])

_spec('global_tracking', 'Tracking 360°', "Hand-off d'identité inter-caméras (gids), classes stables, "
      "stationnés+ancres, fantômes, lissage Kalman → world_en. Enchaîne branches et marquages monde.",
      FC.ENRICHER, 'cam_analyzer.tasks:_run_global_tracking', ['vision', 'geo', 'per-vehicle'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id', 'distance_m'],
                       cardinality='many', description='Détections des 4 caméras.'),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'])],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['global_track_id', 'world_en', 'stable_class', 'artifact'])])

_spec('artifact_filter', 'Filtre reflets/artefacts', "Reflets de vitrage : bbox fixe pendant que la navette "
      "avance (cinématique) OU bbox géante + confiance basse (fantôme géant).",
      FC.TRANSFORM, 'cam_analyzer.utils.artifact_filter:detect_static_artifacts', ['vision'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id']),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'])],
      outputs=[PortSpec('detections', DT.DETECTIONS, produced_fields=['artifact'])])

_spec('ground_calib', 'Calibration sol auto (pitch)', "Estime le pitch/hauteur caméra en minimisant "
      "l'étalement monde des stationnés (auto-calibration par ego-motion).",
      FC.INDICATOR, 'cam_analyzer.utils.homography_estimator:store_ground_calib', ['vision', 'geo', 'needs-calibration'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'global_track_id', 'distance_m']),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'])],
      outputs=[PortSpec('ground_calib', DT.SCALAR, produced_fields=['pitch_deg', 'height_m'])])

# ── Structure routière (apprise / marquée) ────────────────────────────────────
_spec('learned_branches', 'Branches apprises du trafic', "Voies croisantes aux intersections apprises "
      "des trajectoires monde des véhicules.",
      FC.AGGREGATE, 'cam_analyzer.utils.intersection_branches:learn_branches', ['geo', 'per-section'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id']),
              PortSpec('track', DT.GEO_TRACK)],
      outputs=[PortSpec('branches', DT.SECTIONS, produced_fields=['bearing_deg', 'width_m', 'a', 'b'])])

_spec('world_markings', 'Marquages SAM3 en monde', "stop_line/crossing projetés au sol et agrégés "
      "multi-passages (bornes d'intersection).",
      FC.AGGREGATE, 'cam_analyzer.utils.marking_world:aggregate_markings', ['vision', 'geo', 'per-section'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['polygon', 'label']),
              PortSpec('track', DT.GEO_TRACK)],
      outputs=[PortSpec('markings', DT.SECTIONS, produced_fields=['a', 'b', 'label', 'bearing_deg'])])

_spec('ortho_recalage', 'Recalage absolu ortho', "Segmente les passages piétons sur l'orthophoto IGN et "
      "mesure le décalage avec les crossings caméra (offset de recalage GPS/projection).",
      FC.INDICATOR, 'cam_analyzer.tasks:compute_ortho_recalage_task', ['vision', 'geo', 'gpu'],
      inputs=[PortSpec('markings', DT.SECTIONS, required_fields=['a', 'b', 'label']),
              PortSpec('road_map', DT.ROAD_MAP, optional=True)],
      outputs=[PortSpec('recalage', DT.SCALAR, produced_fields=['de_m', 'dn_m'])])

# ── Évènements / indicateurs métier ───────────────────────────────────────────
_spec('lane_events', 'Évènements de voie', "Franchissements/attributions de voie par objet.",
      FC.DETECTOR, 'cam_analyzer.tasks:compute_lane_events_task', ['vision'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id'])],
      outputs=[PortSpec('events', DT.EVENTS, produced_fields=['time', 'type', 'lane'])])

_spec('temporal_segments', 'Segments temporels', "Détecte les segments temporels d'intérêt (approche, "
      "suivi, transverse) par objet.",
      FC.DETECTOR, 'cam_analyzer.tasks:compute_temporal_segments_task', ['vision', 'geo'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id', 'distance_m'])],
      outputs=[PortSpec('segments', DT.EVENTS, produced_fields=['start', 'end', 'type'])])

_spec('conflicts', 'Conflits', "Détecte les conflits (approche frontale, suivi rapproché, dépassement…) "
      "à partir des segments et des trajectoires.",
      FC.DETECTOR, 'cam_analyzer.tasks:compute_conflict_events_task', ['vision', 'geo'],
      inputs=[PortSpec('segments', DT.EVENTS, required_fields=['start', 'end', 'type']),
              PortSpec('detections', DT.DETECTIONS)],
      outputs=[PortSpec('conflicts', DT.EVENTS, produced_fields=['time', 'type', 'severity'])])

_spec('prediction', 'Indicateurs prédiction (TTC/PET)', "TTC/PET par prédiction de trajectoire (ré-annotation "
      "des détections, sans re-détection).",
      FC.ENRICHER, 'cam_analyzer.tasks:annotate_prediction_task', ['geo', 'per-vehicle'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id'])],
      outputs=[PortSpec('detections', DT.DETECTIONS, produced_fields=['prediction_ttc', 'prediction_pet'])])
