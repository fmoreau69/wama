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
from wama.common.catalog.data_types import DataType as DT
from wama.common.catalog.function_catalog import (
    FunctionSpec, PortSpec, ParamSpec, FunctionCategory as FC, Binding, register)

_APP = 'cam_analyzer'


def _spec(key, name, desc, category, impl, tags, inputs, outputs, params=None, cost=None, projects=('ENA',)):
    return register(FunctionSpec(
        key=f'cam_analyzer.{key}', name=name, description=desc, category=category,
        binding=Binding.APP, app=_APP, impl=impl, tags=tags,
        inputs=inputs, outputs=outputs, params=params or [], cost=cost or {},
        projects=list(projects)))


# ── Extraction & fenêtrage (les deux premières passes du registre `PASSES`) ────
# Déclarées le 2026-09-09 pour que CHAQUE passe du pipeline soit un nœud `function` (D13) :
# avant, `extraction` et `intersection_windows` n'existaient que dans le registre des passes.
_spec('extraction', 'Extraction RTMaps', "Décode le `.rec`/quadrature RTMaps : vidéos par caméra, "
      "trace GPS annotée (cap/vitesse), synchro GPS↔vidéo (scale/offset), accéléromètre stocké.",
      FC.TRANSFORM, 'cam_analyzer.tasks:extract_rtmaps_task', ['io', 'rtmaps', 'gnss'],
      inputs=[PortSpec('rec', DT.TABLE, description="Enregistrement RTMaps (.rec + CSV par canal).")],
      outputs=[PortSpec('video', DT.TABLE, produced_fields=['position', 'fps', 'path'],
                        description='Une vidéo par caméra.'),
               PortSpec('track', DT.GEO_TRACK,
                        produced_fields=['ts', 'lat', 'lon', 'heading', 'speed_kmh'],
                        # levier 10 : cap = bearing entre fixes bruts, TENU si < 0,30 m —
                        # ±10-25° à basse vitesse (§[2]), la source d'erreur angulaire dominante.
                        # Non chiffrée par ligne : `declared` ; la valeur mesurée vit sur
                        # `shuttle_filter` (levier 15), qui en dérive.
                        estimates='heading', estimate_field='heading',
                        uncertainty={'model': 'declared',
                                     'note': '±10-25° à basse vitesse (§[2]) ; tenu si < 0,30 m'},
                        derived_from=['gps'])],
      cost={'cpu_bound': True})

_spec('intersection_windows', "Fenêtres d'intersection", "Découpe la trace en fenêtres temporelles "
      "autour des intersections déclarées (rayon d'ANALYSE) — ce que les passes aval regardent.",
      FC.DETECTOR, 'cam_analyzer.utils.window_recompute:recompute_intersection_windows', ['geo', 'per-section'],
      inputs=[PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'])],
      outputs=[PortSpec('windows', DT.SEGMENTS, produced_fields=['start', 'end', 'intersection'])],
      cost={'cpu_bound': True})

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
              PortSpec('track', DT.GEO_TRACK, optional=True, group='reference')],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['distance_m', 'speed', 'ttc', 'ground_xy'],
                        # levier 1 : pinhole H_classe·f/h_bbox, ±20 % (jitter 1 px) — la
                        # référence de tout le reste, dérivée de la bbox SEULE.
                        estimates='distance', estimate_field='distance_m',
                        uncertainty={'model': 'relative', 'ratio': 0.2},
                        derived_from=['bbox'])])

_spec('global_tracking', 'Tracking 360°', "Hand-off d'identité inter-caméras (gids), classes stables, "
      "stationnés+ancres, fantômes, lissage Kalman → world_en. Enchaîne branches et marquages monde.",
      FC.ENRICHER, 'cam_analyzer.tasks:_run_global_tracking', ['vision', 'geo', 'per-vehicle'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id', 'distance_m'],
                       cardinality='many', description='Détections des 4 caméras.'),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference')],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['global_track_id', 'world_en', 'stable_class', 'artifact'],
                        # position monde = distance bbox ∘ pose GPS : DEUX données natives,
                        # donc jamais fusionnable avec une source bbox OU gps seule. σ non
                        # chiffrée par détection — `placement_spread` en donne une par run.
                        estimates='position', estimate_field='world_en',
                        uncertainty={'model': 'declared',
                                     'note': "σ par run = placement_spread (RMS des stationnés)"},
                        derived_from=['bbox', 'gps'])])

_spec('artifact_filter', 'Filtre reflets/artefacts', "Reflets de vitrage : bbox fixe pendant que la navette "
      "avance (cinématique) OU bbox géante + confiance basse (fantôme géant).",
      FC.TRANSFORM, 'cam_analyzer.utils.artifact_filter:detect_static_artifacts', ['vision'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id']),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference')],
      outputs=[PortSpec('detections', DT.DETECTIONS, produced_fields=['artifact'])])

_spec('ground_calib', 'Calibration sol auto (pitch)', "Estime le pitch/hauteur caméra en minimisant "
      "l'étalement monde des stationnés (auto-calibration par ego-motion).",
      FC.INDICATOR, 'cam_analyzer.utils.homography_estimator:store_ground_calib', ['vision', 'geo', 'needs-calibration'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'global_track_id', 'distance_m']),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference')],
      outputs=[PortSpec('ground_calib', DT.SCALAR, produced_fields=['pitch_deg', 'height_m'],
                        # levier 18 : l'angle par l'ego-motion (stationnés + GPS) — désaccord
                        # 14,55 → 3,05 m mesuré, mais aucune σ sur l'angle lui-même.
                        estimates='ground_plane', estimate_field='pitch_deg',
                        uncertainty={'model': 'declared',
                                     'note': 'jugée par placement_spread, pas par σ'},
                        derived_from=['bbox', 'gps'])])

_spec('placement_spread', 'Cohérence de placement (étalement stationnés)',
      "Métrique A/B OBJECTIVE : dispersion RMS monde des véhicules stationnés autour de leur "
      "barycentre (0 = idéal, plus bas = meilleur). Calculée en fin de tracking 360° via la brique "
      "commune WAMA Data `geometry.placement_spread` (pure), sans vérité terrain. Sert à trancher "
      "la bascule ⚑ auto_ground_calib ON/OFF sur un chiffre plutôt qu'« à l'œil ».",
      FC.INDICATOR, 'cam_analyzer.utils.multicam_tracker:annotate_global_tracks',
      ['geo', 'placement-quality', 'ab-metric', 'no-ground-truth'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id'])],
      outputs=[PortSpec('placement_spread', DT.SCALAR,
                        produced_fields=['rms_median_m', 'rms_mean_m', 'rms_p90_m', 'n_tracks'])])

# ── Profondeur monoculaire (⚑ depth_estimation, §[E]) ─────────────────────────
# Passes couplées session qui DÉLÈGUENT tout le calcul aux briques PURES WAMA Data
# `geometry.depth_ground_plane` / `geometry.depth_contact_distance` (patron placement_spread :
# la brique pure est cataloguée à part, ces entrées décrivent la passe qui l'emploie).
# Chaîne en 3 étages : ANALYSE (inférence+stockage) → CALCULS (lecture db, CPU) → AFFICHAGE (flag).
_spec('depth_analysis', 'Analyse de profondeur (Depth Pro)',
      "ÉTAGE 1 de la chaîne profondeur : passe `depth` du volet (session-wide, 4 caméras). Infère la "
      "profondeur métrique (Apple Depth Pro) sur des frames échantillonnées et STOCKE la donnée brute "
      "ré-utilisable — carte par frame (disque float16 → DepthFrame) + profondeur de contact par "
      "détection (champ additif depth_distance_m). SEUL point d'inférence GPU ; les CALCULS "
      "(depth_ground_plane, depth_distance_report) la relisent SANS ré-inférer.",
      FC.DETECTOR, 'cam_analyzer.tasks:compute_depth_task',
      ['vision', 'gpu', 'depth', 'monocular'],
      inputs=[PortSpec('video', DT.TABLE, description='Frames caméra (RTMaps).'),
              PortSpec('detections', DT.DETECTIONS, required_fields=['bbox'],
                       description='Détections (bbox → profondeur de contact).')],
      outputs=[PortSpec('depth', DT.DEPTH_MAP, produced_fields=['focal_px'],
                        description='Carte métrique par frame (DepthFrame, sur disque).'),
               PortSpec('detections', DT.DETECTIONS, produced_fields=['depth_distance_m'],
                        # levier 20 : distance de contact par la carte de profondeur —
                        # INDÉPENDANTE de la bbox (levier 1) : les deux SE FUSIONNENT ;
                        # σ croît fort au-delà de 15-20 m (§[E]), non chiffrée : declared.
                        estimates='distance', estimate_field='depth_distance_m',
                        uncertainty={'model': 'declared',
                                     'note': 'σ croît au-delà de 15-20 m (§[E]) ; jamais exécuté'},
                        derived_from=['depth_map'])],
      cost={'vram_gb': 8})

_spec('depth_ground_plane', 'Plan de sol par profondeur (usage 4)',
      "ÉTAGE 2 (CALCUL, CPU) : relit les cartes stockées (DepthFrame, par depth_analysis), déprojette "
      "la zone roulable → RANSAC (brique pure geometry.depth_ground_plane) → plan de sol. Sous ⚑ "
      "depth_estimation, PERSISTE ground_calib avec source='depth' au lieu de la recherche "
      "homographique ; l'A/B se lit sur placement_spread. AUCUNE ré-inférence GPU. Signe du pitch "
      "validé (test CPU) ; gain à confirmer au 1er run GPU.",
      FC.INDICATOR, 'cam_analyzer.utils.homography_estimator:store_ground_calib',
      ['vision', 'geo', 'depth', 'monocular', 'needs-calibration'],
      inputs=[PortSpec('depth', DT.DEPTH_MAP, description='Cartes de profondeur stockées (DepthFrame).'),
              PortSpec('detections', DT.DETECTIONS, required_fields=['polygon'],
                       description='Masque roulable (road_mask) par caméra.'),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference')],
      outputs=[PortSpec('ground_calib', DT.SCALAR,
                        produced_fields=['pitch_deg', 'height_m', 'source'],
                        # levier 19 : le même angle que ground_calib, par une donnée native
                        # DIFFÉRENTE (carte de profondeur) — c'est ce qui rend les deux
                        # confrontables ET fusionnables ; σ = résidu RANSAC, non exposé.
                        estimates='ground_plane', estimate_field='pitch_deg',
                        uncertainty={'model': 'declared', 'note': 'résidu RANSAC non exposé'},
                        derived_from=['depth_map', 'segmentation'])],
      cost={'cpu_bound': True})

_spec('depth_calc', 'Calculs profondeur (passe)',
      "La PASSE `depth_calc` du volet (session-wide, CPU) : relit les DepthFrame stockées et "
      "enchaîne les deux calculs catalogués à part — `depth_ground_plane` (plan de sol, "
      "store_ground_calib source='depth') puis `depth_distance_report` (cross-check). Déclarée "
      "comme passe pour que le pipeline soit exportable nœud par nœud (D13).",
      FC.ENRICHER, 'cam_analyzer.tasks:compute_depth_calc_task', ['vision', 'geo', 'depth', 'monocular'],
      inputs=[PortSpec('depth', DT.DEPTH_MAP, description='Cartes stockées (DepthFrame).'),
              PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'depth_distance_m'])],
      outputs=[PortSpec('ground_calib', DT.SCALAR, produced_fields=['pitch_deg', 'height_m', 'source']),
               PortSpec('depth_report', DT.SCALAR,
                        produced_fields=['disagree_pinhole_m', 'disagree_homography_m'])],
      cost={'cpu_bound': True})

_spec('depth_distance_report', 'Cross-check distance & reflets par profondeur (usages 3+1)',
      "ÉTAGE 2 (CALCUL, CPU) : LECTURE PURE des depth_distance_m déjà stockés par depth_analysis. "
      "MESURE-ET-RAPPORT (ne bascule AUCUNE source) : 3ᵉ source de distance indépendante (désaccord "
      "↔pinhole / ↔homographie = usage 3 ; confirmation des reflets = usage 1). Chaque usage écrit sa "
      "ligne A/B console ; résumé dans results_summary['depth_report']. AUCUNE ré-inférence GPU.",
      FC.ENRICHER, 'cam_analyzer.utils.depth_estimator:depth_distance_report',
      ['vision', 'geo', 'depth', 'monocular', 'ab-metric'],
      inputs=[PortSpec('detections', DT.DETECTIONS,
                       required_fields=['bbox', 'distance_m', 'depth_distance_m'])],
      outputs=[PortSpec('depth_report', DT.SCALAR,
                        produced_fields=['disagree_pinhole_m', 'disagree_homography_m'])],
      cost={'cpu_bound': True})

# ── Structure routière (apprise / marquée) ────────────────────────────────────
_spec('learned_branches', 'Branches apprises du trafic', "Voies croisantes aux intersections apprises "
      "des trajectoires monde des véhicules.",
      FC.AGGREGATE, 'cam_analyzer.utils.intersection_branches:learn_branches', ['geo', 'per-section'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id']),
              PortSpec('track', DT.GEO_TRACK, group='reference')],
      outputs=[PortSpec('branches', DT.SEGMENTS, produced_fields=['bearing_deg', 'width_m', 'a', 'b'])])

_spec('world_markings', 'Marquages SAM3 en monde', "stop_line/crossing projetés au sol et agrégés "
      "multi-passages (bornes d'intersection).",
      FC.AGGREGATE, 'cam_analyzer.utils.marking_world:aggregate_markings', ['vision', 'geo', 'per-section'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['polygon', 'label']),
              PortSpec('track', DT.GEO_TRACK, group='reference')],
      outputs=[PortSpec('markings', DT.SEGMENTS, produced_fields=['a', 'b', 'label', 'bearing_deg'])])

_spec('ortho_recalage', 'Recalage absolu ortho', "Segmente les passages piétons sur l'orthophoto IGN et "
      "mesure le décalage avec les crossings caméra (offset de recalage GPS/projection).",
      FC.INDICATOR, 'cam_analyzer.tasks:compute_ortho_recalage_task', ['vision', 'geo', 'gpu'],
      inputs=[PortSpec('markings', DT.SEGMENTS, required_fields=['a', 'b', 'label']),
              PortSpec('road_map', DT.ROAD_MAP, optional=True, group='reference')],
      outputs=[PortSpec('recalage', DT.SCALAR, produced_fields=['de_m', 'dn_m'],
                        # levier 21 : la seule POSITION ABSOLUE de la chaîne (2,93 E / 4,2 N m
                        # mesurés) — orthophoto ∘ marquages caméra ; σ = dispersion par
                        # intersection, non exposée en champ.
                        estimates='offset', estimate_field='de_m',
                        uncertainty={'model': 'declared',
                                     'note': 'dispersion par intersection dans le rapport'},
                        derived_from=['orthophoto', 'segmentation'])])
_spec('ortho_correction', 'Correction de trajectoire (ortho)',
      "APPLIQUE le recalage mesuré à la trajectoire, derrière la bascule ⚑ ortho_correction. "
      "La médiane globale est tenue pour un biais de PROJECTION caméra et n'est PAS appliquée ; "
      "seul l'écart LOCAL par intersection corrige le GPS, interpolé entre repères et atténué "
      "là où le ciel est dégagé (masquage satellite BD TOPO). Séparée de la mesure : "
      "recalibrer le seuil ne doit pas relancer la segmentation SAM3 des tuiles ortho.",
      FC.TRANSFORM, 'cam_analyzer.tasks:compute_ortho_correction_task', ['geo', 'gnss'],
      inputs=[PortSpec('recalage', DT.SCALAR, required_fields=['de_m', 'dn_m'])],
      outputs=[PortSpec('ortho_correction', DT.TABLE,
                        produced_fields=['anchors', 'camera_bias', 'sky_mask_deg', 'report'])])

_spec('shuttle_filter', 'Filtre de trajectoire navette (Kalman+RTS)',
      "Lisse position et cap de la NAVETTE (brique pure driving.ego_track_filter), stocke la "
      "trace filtrée ; la bascule ⚑ shuttle_filter choisit à la lecture entre brut et filtré, "
      "au point d'ingestion unique (serveur + affichage). Rapport A/B : déplacement RMS, écart "
      "de cap médian, part de cap tenu.",
      FC.ENRICHER, 'cam_analyzer.utils.ego_pose:compute_shuttle_filter', ['geo', 'gnss', 'ego-motion', 'ab-metric'],
      inputs=[PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'])],
      outputs=[PortSpec('track', DT.GEO_TRACK,
                        produced_fields=['lat_f', 'lon_f', 'heading_f', 'speed_f_kmh', 'heading_f_held'],
                        # levier 15 : MÊME facette que la brique pure `ego_track_filter` qu'elle
                        # délègue (σ 3° mesurée sur trace synthétique, provisoire ; cap tenu =
                        # pas une mesure). Une seule donnée native : gps.
                        estimates='heading', estimate_field='heading_f',
                        uncertainty={'model': 'held', 'field': 'heading_f_held', 'sigma': 3.0},
                        derived_from=['gps'])],
      cost={'cpu_bound': True})

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

# `indicators` = la clé de la PASSE (`PassType.INDICATORS`, `compute_indicators_task`) ; la
# fonction s'appelait `prediction` jusqu'au 2026-09-09 — un nom pour trois objets (passe, tâche,
# fonction), sinon le registre des passes ne peut pas dériver son nœud sans table de traduction.
_spec('indicators', 'Indicateurs prédiction (TTC/PET)', "TTC/PET par prédiction de trajectoire (ré-annotation "
      "des détections, sans re-détection).",
      FC.ENRICHER, 'cam_analyzer.tasks:compute_indicators_task', ['geo', 'per-vehicle'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id'])],
      outputs=[PortSpec('detections', DT.DETECTIONS, produced_fields=['prediction_ttc', 'prediction_pet'],
                        # levier 43 : extrapolation des trajectoires monde (bbox ∘ gps).
                        estimates='ttc', estimate_field='prediction_ttc',
                        uncertainty={'model': 'declared', 'note': 'aucune mesure A/B (§C)'},
                        derived_from=['bbox', 'gps'])])


# ── Le PIPELINE lui-même (D13 ③, 2026-09-09) ──────────────────────────────────
# Le registre des passes (`pass_tracking.PASSES`) s'inscrit comme source de manifeste
# `pipeline` sous la clé `cam_analyzer` : chaque passe est un nœud `function` (les specs
# ci-dessus), chaque dépendance un lien. Exporté par `manifest_export --kind pipeline`.
# Import paresseux : `pass_tracking` n'importe rien de Django au module, mais `function_specs`
# est chargé par `apps.ready()` et par `load_all()` hors cycle — la fabrique n'est appelée
# qu'à l'extraction.
from wama.common.manifests.builtin.pipeline import register_pipeline_source  # noqa: E402


def _cam_analyzer_pipeline():
    from wama_lab.cam_analyzer.utils.pass_tracking import pipeline_manifest
    return pipeline_manifest()


register_pipeline_source('cam_analyzer', _cam_analyzer_pipeline)
