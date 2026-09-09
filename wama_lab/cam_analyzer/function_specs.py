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
               # ⚠ `ts` et non `time` : c'est le nom RÉELLEMENT écrit par le décodage RTMaps.
               # Le champ canonique d'un `geo_track` est `time` (`CANONICAL_FIELDS`) — relevé
               # le 2026-09-09 en soldant le même écart sur `trajectory_offset`. Sans effet
               # aujourd'hui (fonction app-bound : ses liens ORDONNENT, aucune frame ne
               # circule), mais à trancher le jour d'un portage `pure` : renommer ici suppose
               # de vérifier ce qu'écrit `extract_rtmaps_task`, pas seulement la déclaration.
               PortSpec('track', DT.GEO_TRACK,
                        produced_fields=['ts', 'lat', 'lon', 'heading', 'speed_kmh'],
                        description="Trace GPS de la navette annotée cap/vitesse, synchronisée "
                                    "sur les vidéos. C'est le RÉFÉRENTIEL de toute la chaîne : "
                                    "toutes les passes aval s'y rapportent.",
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
      inputs=[PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'],
                       description="Trace de la navette : c'est sa POSITION qui décide de "
                                   "l'entrée et de la sortie du rayon d'analyse.")],
      outputs=[PortSpec('windows', DT.SEGMENTS, produced_fields=['start', 'end', 'intersection'],
                        description="Une fenêtre par passage d'intersection ; `intersection` "
                                    "nomme laquelle. C'est le PÉRIMÈTRE que les passes aval "
                                    "regardent — hors fenêtre, elles ne calculent rien.")],
      cost={'cpu_bound': True})

# ── Détection & segmentation image ────────────────────────────────────────────
_spec('yolo_detect', 'Détection YOLO', "Détection/segmentation d'objets par frame (ultralytics).",
      FC.DETECTOR, 'cam_analyzer.tasks:process_session_task', ['vision', 'gpu'],
      inputs=[PortSpec('video', DT.TABLE, description='Frames caméra (RTMaps).')],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['frame', 'bbox', 'class_name', 'confidence', 'track_id'],
                        description="Détections par frame. `track_id` est LOCAL à une caméra — "
                                    "l'identité inter-caméras est le rôle du tracking 360° "
                                    "(`global_track_id`). Les confondre associerait deux "
                                    "objets distincts vus par deux caméras.")],
      cost={'vram_gb': 4})

_spec('yolopv2_lanes', 'Zone roulable + voies (YOLOPv2)', "Segmentation zone roulable + lignes de voie.",
      FC.DETECTOR, 'cam_analyzer.tasks:process_session_task', ['vision', 'gpu'],
      inputs=[PortSpec('video', DT.TABLE, description='Frames caméra (RTMaps).')],
      outputs=[PortSpec('lanes', DT.DETECTIONS, produced_fields=['drivable', 'lane'],
                        description="Deux masques par frame : `drivable` = zone roulable, "
                                    "`lane` = lignes de voie. Masques image, PAS des objets "
                                    "suivis — ils n'ont ni `track_id` ni distance.")],
      cost={'vram_gb': 3})

_spec('sam3_markings', 'Marquages SAM3', "Marquages au sol (passages piétons, lignes d'arrêt) segmentés par SAM3.",
      FC.DETECTOR, 'cam_analyzer.tasks:analyze_sam3_only_task', ['vision', 'gpu'],
      inputs=[PortSpec('video', DT.TABLE, description='Frames caméra (RTMaps).')],
      outputs=[PortSpec('markings', DT.DETECTIONS, produced_fields=['label', 'polygon', 'bbox'],
                        description="Marquages au sol segmentés, en coordonnées IMAGE "
                                    "(`polygon`). Leur passage au monde est le rôle du "
                                    "tracking 360°, pas de cette passe.")],
      params=[ParamSpec('sam3_fps', 'float', 2.0, 0.5, 12.0, 'img/s', 'Cadence de segmentation.')],
      cost={'vram_gb': 8})

# ── Positionnement / géométrie ────────────────────────────────────────────────
_spec('distance', 'Distance / vitesse / TTC', "Distance pinhole/homographie + vitesse et TTC filtrés par track.",
      FC.ENRICHER, 'cam_analyzer.tasks:compute_distance_task', ['vision', 'geo'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id'],
                       description="Détections d'UNE caméra : la hauteur de `bbox` donne la "
                                   "distance pinhole, `track_id` permet le filtrage temporel."),
              PortSpec('track', DT.GEO_TRACK, optional=True, group='reference',
                       description="Trace de la navette, OPTIONNELLE : sans elle, la vitesse "
                                   "reste relative à la caméra au lieu d'être absolue.")],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['distance_m', 'speed', 'ttc', 'ground_xy'],
                        description="Les mêmes détections, enrichies. `ground_xy` est le point "
                                    "de contact au sol dans le repère caméra — pas encore "
                                    "monde (c'est le tracking 360° qui y projette).",
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
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference',
                       description="Pose de la navette : c'est elle qui ancre les détections "
                                   "dans le monde. Sans elle, `world_en` n'a pas de sens.")],
      outputs=[PortSpec('detections', DT.DETECTIONS,
                        produced_fields=['global_track_id', 'world_en', 'stable_class', 'artifact'],
                        description="Détections des 4 caméras RÉUNIES sous une identité unique "
                                    "(`global_track_id`) et posées en coordonnées monde "
                                    "est/nord (`world_en`).",
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
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id'],
                       description="Détections à filtrer : `track_id` est indispensable — le "
                                   "critère porte sur l'IMMOBILITÉ d'une piste dans le temps, "
                                   "pas sur une frame isolée."),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference',
                       description="Trace de la navette : c'est son DÉPLACEMENT qui rend "
                                   "suspecte une bbox immobile (un reflet de vitrage suit la "
                                   "caméra, un objet réel non).")],
      outputs=[PortSpec('detections', DT.DETECTIONS, produced_fields=['artifact'],
                        description="Les mêmes détections, MARQUÉES `artifact` — aucune n'est "
                                    "supprimée : l'aval décide s'il les écarte.")])

_spec('ground_calib', 'Calibration sol auto (pitch)', "Estime le pitch/hauteur caméra en minimisant "
      "l'étalement monde des stationnés (auto-calibration par ego-motion).",
      FC.INDICATOR, 'cam_analyzer.utils.homography_estimator:store_ground_calib', ['vision', 'geo', 'needs-calibration'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'global_track_id', 'distance_m'],
                       description="Détections DÉJÀ suivies en monde : la calibration se règle "
                                   "sur les véhicules STATIONNÉS, qu'on ne peut isoler qu'avec "
                                   "une identité globale."),
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference',
                       description="Trace de la navette : l'ego-motion fournit la parallaxe qui "
                                   "rend le pitch observable sans mire.")],
      outputs=[PortSpec('ground_calib', DT.SCALAR, produced_fields=['pitch_deg', 'height_m'],
                        description="Pose de la caméra par rapport au sol — un seul couple pour "
                                    "la session, pas une valeur par frame.",
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
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id'],
                       description="Détections posées en monde et suivies : la métrique mesure "
                                   "la DISPERSION des positions d'une même piste stationnée — "
                                   "sans identité globale, il n'y a rien à disperser.")],
      outputs=[PortSpec('placement_spread', DT.SCALAR,
                        produced_fields=['rms_median_m', 'rms_mean_m', 'rms_p90_m', 'n_tracks'],
                        description="Étalement RMS en mètres, un jeu par run. PLUS BAS = "
                                    "MEILLEUR ; `n_tracks` dit sur combien de pistes il porte "
                                    "(un RMS sur 2 pistes ne se compare pas à un RMS sur 50).")])

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
                        description="Les détections reçoivent une distance issue de la CARTE "
                                    "de profondeur, indépendante de la bbox — c'est cette "
                                    "indépendance qui autorise à la fusionner avec le pinhole "
                                    "plutôt qu'à seulement la confronter.",
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
              PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'], group='reference',
                       description="Trace de la navette : situe les cartes de profondeur dans "
                                   "la session (elle n'entre pas dans l'ajustement du plan).")],
      outputs=[PortSpec('ground_calib', DT.SCALAR,
                        produced_fields=['pitch_deg', 'height_m', 'source'],
                        description="Même grandeur que `ground_calib`, obtenue par une donnée "
                                    "native DIFFÉRENTE : `source` dit laquelle a servi — c'est "
                                    "ce champ qui rend l'A/B lisible.",
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
              PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'depth_distance_m'],
                       description="Détections portant DÉJÀ leur profondeur de contact : cette "
                                   "passe RELIT, elle ne ré-infère jamais (aucun GPU).")],
      outputs=[PortSpec('ground_calib', DT.SCALAR, produced_fields=['pitch_deg', 'height_m', 'source'],
                        description="Sortie de `depth_ground_plane`, réémise ici parce que la "
                                    "passe enchaîne les deux calculs."),
               PortSpec('depth_report', DT.SCALAR,
                        produced_fields=['disagree_pinhole_m', 'disagree_homography_m'],
                        description="Sortie de `depth_distance_report`, même raison.")],
      cost={'cpu_bound': True})

_spec('depth_distance_report', 'Cross-check distance & reflets par profondeur (usages 3+1)',
      "ÉTAGE 2 (CALCUL, CPU) : LECTURE PURE des depth_distance_m déjà stockés par depth_analysis. "
      "MESURE-ET-RAPPORT (ne bascule AUCUNE source) : 3ᵉ source de distance indépendante (désaccord "
      "↔pinhole / ↔homographie = usage 3 ; confirmation des reflets = usage 1). Chaque usage écrit sa "
      "ligne A/B console ; résumé dans results_summary['depth_report']. AUCUNE ré-inférence GPU.",
      FC.ENRICHER, 'cam_analyzer.utils.depth_estimator:depth_distance_report',
      ['vision', 'geo', 'depth', 'monocular', 'ab-metric'],
      inputs=[PortSpec('detections', DT.DETECTIONS,
                       required_fields=['bbox', 'distance_m', 'depth_distance_m'],
                       description="Détections portant les DEUX distances — celle du pinhole "
                                   "et celle de la profondeur : c'est leur ÉCART qui est la "
                                   "mesure, aucune des deux n'est corrigée.")],
      outputs=[PortSpec('depth_report', DT.SCALAR,
                        produced_fields=['disagree_pinhole_m', 'disagree_homography_m'],
                        description="Désaccords en mètres entre sources de distance. RAPPORT "
                                    "SEUL : cette passe ne bascule aucune source.")],
      cost={'cpu_bound': True})

# ── Structure routière (apprise / marquée) ────────────────────────────────────
_spec('learned_branches', 'Branches apprises du trafic', "Voies croisantes aux intersections apprises "
      "des trajectoires monde des véhicules.",
      FC.AGGREGATE, 'cam_analyzer.utils.intersection_branches:learn_branches', ['geo', 'per-section'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id'],
                       description="Trajectoires monde des AUTRES véhicules : c'est leur "
                                   "passage répété qui révèle les voies, sans carte."),
              PortSpec('track', DT.GEO_TRACK, group='reference',
                       description="Trace de la navette — situe l'intersection observée.")],
      outputs=[PortSpec('branches', DT.SEGMENTS, produced_fields=['bearing_deg', 'width_m', 'a', 'b'],
                        description="Une branche par voie apprise : `a`/`b` en bornent le "
                                    "segment monde, `bearing_deg` donne son azimut. APPRISES "
                                    "du trafic, donc absentes si personne n'est passé.")])

_spec('world_markings', 'Marquages SAM3 en monde', "stop_line/crossing projetés au sol et agrégés "
      "multi-passages (bornes d'intersection).",
      FC.AGGREGATE, 'cam_analyzer.utils.marking_world:aggregate_markings', ['vision', 'geo', 'per-section'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['polygon', 'label'],
                       description="Marquages segmentés en coordonnées IMAGE (sortie SAM3) — "
                                   "c'est cette passe qui les projette au sol."),
              PortSpec('track', DT.GEO_TRACK, group='reference',
                       description="Pose de la navette à chaque passage : elle fournit la "
                                   "projection image→monde et permet d'AGRÉGER les passages "
                                   "successifs sur un même marquage.")],
      outputs=[PortSpec('markings', DT.SEGMENTS, produced_fields=['a', 'b', 'label', 'bearing_deg'],
                        description="Marquages en MONDE, un segment `a`→`b` par marquage, "
                                    "consolidés sur plusieurs passages.")])

_spec('ortho_recalage', 'Recalage absolu ortho', "Segmente les passages piétons sur l'orthophoto IGN et "
      "mesure le décalage avec les crossings caméra (offset de recalage GPS/projection).",
      FC.INDICATOR, 'cam_analyzer.tasks:compute_ortho_recalage_task', ['vision', 'geo', 'gpu'],
      inputs=[PortSpec('markings', DT.SEGMENTS, required_fields=['a', 'b', 'label'],
                       description="Marquages vus par la CAMÉRA et projetés au monde — le côté "
                                   "mesuré de la comparaison ; l'orthophoto fournit l'autre."),
              PortSpec('road_map', DT.ROAD_MAP, optional=True, group='reference',
                       description="Référentiel routier, OPTIONNEL : sert au masquage satellite "
                                   "(bâti) qui pondère la confiance, pas au calcul de l'offset.")],
      outputs=[PortSpec('recalage', DT.SCALAR, produced_fields=['de_m', 'dn_m'],
                        description="Décalage est/nord en mètres entre marquages caméra et "
                                    "orthophoto — la SEULE position absolue de la chaîne. "
                                    "MESURE seule : l'appliquer est le rôle d'`ortho_correction`.",
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
      inputs=[PortSpec('recalage', DT.SCALAR, required_fields=['de_m', 'dn_m'],
                       description="Offsets MESURÉS par `ortho_recalage`, par intersection.")],
      outputs=[PortSpec('ortho_correction', DT.TABLE,
                        produced_fields=['anchors', 'camera_bias', 'sky_mask_deg', 'report'],
                        description="Ce qui est PERSISTÉ de la correction : les `anchors` "
                                    "(quelques repères, jamais une trace dupliquée — tout "
                                    "consommateur rejoue l'interpolation), le `camera_bias` "
                                    "écarté à dessein, et le masquage de ciel qui atténue la "
                                    "correction là où le GPS est déjà bon.")])

_spec('shuttle_filter', 'Filtre de trajectoire navette (Kalman+RTS)',
      "Lisse position et cap de la NAVETTE (brique pure driving.ego_track_filter), stocke la "
      "trace filtrée ; la bascule ⚑ shuttle_filter choisit à la lecture entre brut et filtré, "
      "au point d'ingestion unique (serveur + affichage). Rapport A/B : déplacement RMS, écart "
      "de cap médian, part de cap tenu.",
      FC.ENRICHER, 'cam_analyzer.utils.ego_pose:compute_shuttle_filter', ['geo', 'gnss', 'ego-motion', 'ab-metric'],
      inputs=[PortSpec('track', DT.GEO_TRACK, required_fields=['lat', 'lon'],
                       description="Trace BRUTE de la navette, telle que décodée du `.rec`.")],
      outputs=[PortSpec('track', DT.GEO_TRACK,
                        produced_fields=['lat_f', 'lon_f', 'heading_f', 'speed_f_kmh', 'heading_f_held'],
                        description="Trace filtrée en champs SÉPARÉS (`_f`) : le brut n'est "
                                    "jamais écrasé, c'est la bascule ⚑ qui choisit à la "
                                    "lecture. `heading_f_held` marque les caps TENUS (navette "
                                    "quasi immobile) — un cap tenu n'est pas une mesure.",
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
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id'],
                       description="Détections suivies : un franchissement est un CHANGEMENT "
                                   "de voie d'une même piste, il ne se lit pas sur une frame.")],
      outputs=[PortSpec('events', DT.EVENTS, produced_fields=['time', 'type', 'lane'],
                        description="Un événement daté par franchissement ou attribution de "
                                    "voie ; `lane` nomme la voie concernée.")])

_spec('temporal_segments', 'Segments temporels', "Détecte les segments temporels d'intérêt (approche, "
      "suivi, transverse) par objet.",
      FC.DETECTOR, 'cam_analyzer.tasks:compute_temporal_segments_task', ['vision', 'geo'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['bbox', 'track_id', 'distance_m'],
                       description="Détections suivies ET distancées : c'est l'ÉVOLUTION de la "
                                   "distance le long d'une piste qui distingue une approche "
                                   "d'un suivi ou d'un passage transverse.")],
      outputs=[PortSpec('segments', DT.EVENTS, produced_fields=['start', 'end', 'type'],
                        description="Plages temporelles d'intérêt par objet. ⚠ Typé `events` "
                                    "et non `segments` : ces plages sont rattachées à un objet "
                                    "suivi, pas à la session.")])

_spec('conflicts', 'Conflits', "Détecte les conflits (approche frontale, suivi rapproché, dépassement…) "
      "à partir des segments et des trajectoires.",
      FC.DETECTOR, 'cam_analyzer.tasks:compute_conflict_events_task', ['vision', 'geo'],
      inputs=[PortSpec('segments', DT.EVENTS, required_fields=['start', 'end', 'type'],
                       description="Plages d'intérêt par objet (sortie de `temporal_segments`) "
                                   "— elles bornent QUAND chercher un conflit."),
              PortSpec('detections', DT.DETECTIONS,
                       description="Trajectoires sur ces plages — elles disent QUI est en "
                                   "conflit avec qui. Aucun champ n'est exigé ici : la passe "
                                   "lit ce que la session a stocké.")],
      outputs=[PortSpec('conflicts', DT.EVENTS, produced_fields=['time', 'type', 'severity'],
                        description="Un événement daté par conflit détecté, gradué par "
                                    "`severity`. C'est la sortie MÉTIER de la chaîne.")])

# `indicators` = la clé de la PASSE (`PassType.INDICATORS`, `compute_indicators_task`) ; la
# fonction s'appelait `prediction` jusqu'au 2026-09-09 — un nom pour trois objets (passe, tâche,
# fonction), sinon le registre des passes ne peut pas dériver son nœud sans table de traduction.
_spec('indicators', 'Indicateurs prédiction (TTC/PET)', "TTC/PET par prédiction de trajectoire (ré-annotation "
      "des détections, sans re-détection).",
      FC.ENRICHER, 'cam_analyzer.tasks:compute_indicators_task', ['geo', 'per-vehicle'],
      inputs=[PortSpec('detections', DT.DETECTIONS, required_fields=['world_en', 'global_track_id'],
                       description="Trajectoires MONDE suivies : la prédiction extrapole une "
                                   "trajectoire, ce qui exige des positions comparables entre "
                                   "caméras — donc `world_en`, pas la bbox.")],
      outputs=[PortSpec('detections', DT.DETECTIONS, produced_fields=['prediction_ttc', 'prediction_pet'],
                        description="Les mêmes détections, RÉ-ANNOTÉES : temps avant collision "
                                    "et temps post-empiètement, tous deux PRÉDITS par "
                                    "extrapolation — jamais observés.",
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
