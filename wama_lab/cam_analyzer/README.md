# Cam Analyzer

Application **WAMA Lab** d'analyse vidéo **multi-caméras synchronisées** (post-processing) pour
caméras embarquées sur une **navette autonome** (laboratoire transport, Université Gustave Eiffel /
Lescot). Objectif : étudier la **sécurité et la cohabitation** de la navette avec les autres usagers
de la route (détection d'objets, segmentation de voie, proximité, conflits aux intersections).

> **Statut** : pipeline complet **implémenté** (détection → tracking 360° → vue de dessus →
> intersections/conflits), **validation navigateur en cours** sur session réelle. Le gros chantier
> récent = **reconstruction de la scène en vue de dessus** (fusion multi-caméras, hand-off d'identité,
> lissage Kalman) + **calibration sol semi-automatique**.
> Voir la section **« État courant & RESTE À FAIRE »** en tête de
> [`CAM_ANALYZER_CHANGELOG.md`](CAM_ANALYZER_CHANGELOG.md) pour l'état détaillé et les priorités de reprise.
>
> **Documentation = 3 piliers** (rôles nets, zéro doublon) :
> [`CAM_ANALYZER_CHAINE_TRAITEMENT.md`](CAM_ANALYZER_CHAINE_TRAITEMENT.md) — comment ça marche + pourquoi
> (chaîne de bout en bout, formules, calibration, conception ; **DOIT matcher le code**) ;
> [`CAM_ANALYZER_CHANGELOG.md`](CAM_ANALYZER_CHANGELOG.md) — historique + backlog + non-régression
> (**traçabilité** quoi/pourquoi/annulation — à jour à CHAQUE changement de comportement) ;
> ce **README** — carte d'entrée (modules/API/limites).
> Les **spécificités projet** (ex. ENA_CASA : données, calibration, rig) vivent dans
> [`projects/`](projects/) — `cam_analyzer` est **générique multi-projets**.

---

## Fonctionnalités

- **Sessions** (à la `face_analyzer`) : une analyse = une session UUID ; import multi-rosbags →
  plusieurs sessions en parallèle.
- **Multi-caméras** : 3–4 vues embarquées (avant / arrière / gauche / droite), disposées autour d'une
  silhouette de navette, **drag & drop** des vidéos, **lecture synchronisée** (play/pause/seek + offset
  de synchro par caméra).
- **Détection & tracking** : YOLO (ultralytics, boxes ou segmentation) + BoTSORT — véhicules, piétons, etc.
- **Vue de dessus 360°** : toutes les caméras fusionnées dans le repère véhicule, positions monde tracées
  sur une mini-carte Leaflet (fond sombre ou **orthophoto IGN 🛰**, orientation nord ou **cap-navette 🧭**).
  Tracker global inter-caméras : **hand-off d'identité** (un véhicule garde son id d'une caméra à l'autre),
  classes stables par vote, stationnés ancrés, trajectoires **lissées Kalman**, remplissage de fantômes.
- **Segmentation de la route** : YOLOPv2 (zone roulable + lignes de voie) + modèle BDD100K-seg ;
  marquages au sol (passages piétons, lignes d'arrêt) via SAM3, **interpolés** entre keyframes à l'affichage.
- **Attribution de voie** : chaque objet est rattaché à une voie ; identification de la voie navette.
- **Calibration** : yaw/FOV/levier antenne GPS réglables par session ; **calibration sol semi-automatique**
  (pitch caméra estimé par ego-motion) ; voies croisantes et marquages d'intersection reconstruits.
- **Bascules de comparaison ⚑** : 11 leviers A/B (correction FOV, cap, filtre d'artefacts, cap des garés,
  branches apprises, marquages monde, calibration sol…) pour mesurer chaque amélioration avec/sans.
- **Timeline de proximité** colorée (vert → rouge) synchronisée à la lecture.
- **Segmentation temporelle** automatique (suivi rapproché, dépassement, croisement, arrêt/insertion
  aux intersections).
- **Conflits & TTC** : événements consolidés par objet (avant/après navette, Δt, distance min, TTC,
  sévérité) aux fenêtres d'intersection (déclenchées par GPS).
- **Analytics** : graphiques (distance / vitesse / accélération / dimensions de l'objet le plus proche),
  **exports** CSV/JSON (détections, segments, conflits).
- **Analyse incrémentale** : les traitements sont tracés par « passes » ; relancer en ajoutant une
  classe **complète** l'analyse sans tout refaire (invalidation `STALE` + cascade de dépendances).
- **Entrées** : rosbags ou vidéos extraites, ou enregistrements **RTMaps** (`.rec` + CSV) avec
  extraction de vidéo quadrature.

## Types de rapport (`AnalysisProfile.report_type`)

| Type | Objet |
|------|-------|
| `proximity_overtaking` | Proximité & dépassements (rapport historique). |
| `intersection_insertion` | Véhicules s'arrêtant/arrêtés aux intersections puis s'insérant devant la navette (même voie / voie opposée) ou attendant son passage. |

---

## Architecture

### Modèles (`models.py`)
- **AnalysisProfile** — config réutilisable : modèle YOLO, classes cibles, seuils, tracker,
  `report_type`, `intersections` `[{name,lat,lon,radius_m}]`, options SAM3, `sam3_fps` (cadence),
  `geometry_enabled`, modèle de route.
- **AnalysisSession** — UUID, statut (draft/pending/processing/paused/completed/failed), `source_type`
  (video/rtmaps), `gps_track`, `intersection_windows`, `camera_calibration`, `results_summary`, progression.
  `config` porte les réglages par session : `camera_yaw`/`camera_fov`/`gps_antenna` (calibration),
  `features` (bascules ⚑), `ground_calib` (pitch estimé), `analyzed_ranges` (couverture).
- **CameraView** — position, fichier vidéo, fps/résolution/durée, `time_offset` (synchro).
- **DetectionFrame** — détections frame par frame (`bbox`, classe, confiance, `track_id`, proximité).
- **TemporalSegment** — segments typés (suivi rapproché, dépassement, croisement, arrêt/insertion).
- **LaneEvent** — passage d'un objet dans une voie (`lane_id`, `in_shuttle_lane`, t_enter/t_exit).
- **ConflictEvent** — conflit consolidé par objet (type, navette passée avant/après, Δt, distance min,
  TTC, sévérité).
- **AnalysisPass** — traçabilité incrémentale (type de passe, statut + `STALE`, snapshot des paramètres).

### Pipeline (`utils/`)
| Module | Rôle |
|--------|------|
| `rosbag_extractor.py`, `rosbag_metadata_extractor.py` | Extraction vidéos / métadonnées rosbags. |
| `rtmaps_parser.py`, `quadrature_video.py` | Parsing RTMaps + vidéo quadrature multi-caméras. |
| `yolopv2_segmenter.py` | YOLOPv2 : zone roulable + lignes de voie. |
| `road_segmenter.py`, `road_model_downloader.py` | Segmentation route (BDD100K-seg) + téléchargement modèle. |
| `sam3_road_analyzer.py` | Marquages au sol (SAM3 prompté ; cadence `profile.sam3_fps`, l'affichage **interpole** entre keyframes). |
| `lane_partition.py` | Attribution de voie par franchissements de lignes ; voie navette. |
| `intersection_analyzer.py` | Moteur intersections : fenêtres GPS, phase d'arrêt, classification d'insertion, t0/t1/t2 (t2 raffiné par ratio d'aspect), densité. |
| `distance_speed.py` | Distance pinhole (fallback) + **vitesse/TTC filtrés** (EMA + régression fenêtrée + clamp). |
| `ground_projection.py` | **Projection sol par homographie** : point-sol bbox → `(X,Y)` repère navette → distances longitudinale/latérale/euclidienne. |
| `calibration.py` | **Calibration homographie** : `homography_from_quad` (DLT 4 coins), solveur pitch 1-point, intrinsèques depuis FoV. |
| `homography_estimator.py` | **Calibration sol AUTO** : résout le pitch/hauteur caméra en minimisant l'étalement monde des stationnés (auto-calibration par ego-motion, sans vérité terrain). Étape 2a du plan de calibration. |
| `prediction_adapter.py` | Repère véhicule : `camera_geometry` (yaw/FOV/montage par caméra + surcharges session), `shuttle_trajectory` (levier antenne GPS), `pinhole_ego`/`ground_ego`, `ego_to_world`. |
| `multicam_tracker.py` | **Tracker global 360°** : hand-off d'identité inter-caméras (gids), classes stables par vote, stationnés + ancres monde, remplissage de fantômes, filtre d'artefacts, cap serveur des garés, écrit `world_en`. |
| `trajectory_smoother.py` | **Lissage Kalman CV + RTS** des trajectoires monde (`smooth_track`). |
| `artifact_filter.py` | Détecte les reflets/artefacts collés à l'image (bbox immobile pendant que la navette avance). |
| `intersection_branches.py` | **Voies croisantes apprises du trafic** (trajectoires monde des véhicules). |
| `marking_world.py` | **Marquages SAM3 agrégés en monde** (stop_line/crossing projetés multi-passages → bornes d'intersection). |
| `coverage.py` | Registre de couverture d'analyse (`analyzed_ranges` par caméra) pour la complétion incrémentale et le mode Live. |
| `features.py` | Registre des **bascules de comparaison** (11 flags A/B, cf. `CAM_ANALYZER_CHAINE_TRAITEMENT.md`). |
| `ego_pose.py` | **Ego-pose GPS + accéléromètre** (parse CSV RecFile_Data ; cap = course GPS tenue à l'arrêt ; priorité API navette si dispo). |
| `pass_tracking.py`, `window_recompute.py` | Passes incrémentales (STALE + cascade) et recalcul ciblé. |

### Tâches Celery (`tasks.py`, queue `gpu`)
`process_session_task` (pipeline complet ; paramètre `completion_scope` pour la **complétion
incrémentale**), `compute_lane_events_task`, `compute_distance_task`, `compute_temporal_segments_task`,
`compute_conflict_events_task`, `compute_global_tracking_task` (**tracking 360°** seul), `analyze_sam3_only_task`,
`live_analysis_task` (**mode Live**, analyse au fil de la lecture), `extract_rtmaps_task`.
`_run_global_tracking()` = cœur partagé (gids + trajectoires lissées + ancres + branches + marquages),
enchaîné automatiquement en fin de complétion et de mode Live.

### Modèles & librairies
- **YOLO** : `AI-models/models/vision/yolo/detect/` (`yolo11{n,s,m,l,x}.pt` + `-seg`). Classes COCO
  routières : person(0), bicycle(1), car(2), motorcycle(3), bus(5), truck(7).
- **YOLOPv2** : https://github.com/CAIC-AD/YOLOPv2 (TorchScript).
- **Segmentation route** : `keremberke/yolov8m-bdd100k-seg` (auto-download).
- **SAM3** : marquages au sol prompts.
- **rosbags** : https://github.com/rpng/rosbags.

---

## API (préfixe `/lab/cam-analyzer/`)

- **Sessions** : `api/sessions/` (list), `create/`, `<id>/`, `<id>/update/`, `<id>/delete/`.
- **Caméras** : `<id>/cameras/upload/`, `cameras/<cid>/delete/`, `.../update-position/`, `.../stream/`.
- **Analyse** : `<id>/start/`, `<id>/status/`, `<id>/cancel/`, `<id>/recompute-windows/`,
  `<id>/start-sam3/`, `<id>/passes/` + `passes/run/`, `<id>/cameras/<cid>/detections/`.
- **Analyse incrémentale** : `<id>/complete-analysis/` (compléter les zones non analysées),
  `<id>/live-cursor/` (mode Live : suit le curseur de lecture, préempté par les tâches batch).
- **Calibration** : `<id>/calibrate/` (POST : 4 coins d'un passage piéton + dimensions → homographie sol
  par DLT), `<id>/camera-yaw/` (yaw/FOV latéral/levier antenne par session), `<id>/features/` (bascules ⚑).
- **Export & analytics** : `<id>/export/{detections,json,segments,conflicts}/`, `<id>/segments/`,
  `<id>/analytics/`.
- **Profils** : `api/profiles/`, `profiles/save/`, `profiles/<pid>/delete/`.
- **Route** : `api/road-model/download/`.
- **RTMaps** : `<id>/rtmaps/upload/`, `.../upload-avi/`, `.../status/`.
- **Console** : `console/`.

## Entrées / sorties
`media/cam_analyzer/{user_id}/input/` et `.../output/` (vidéos annotées, exports). Géré aussi via le
FileManager (WAMA Lab → Cam Analyzer).

---

## Limites connues

- **Vitesses irréalistes** : ✅ **corrigé** — `distance_speed.py` filtre désormais vitesse/TTC (lissage
  EMA de la distance + régression sur fenêtre courte + clamp/rejet des valeurs implausibles) au lieu
  d'une dérivée frame-à-frame brute. Voir [`CAM_ANALYZER_DISTANCE_DESIGN.md`](CAM_ANALYZER_DISTANCE_DESIGN.md) §3a.
- **Vue de dessus des objets** : ✅ **implémentée** — fusion 360° de toutes les caméras dans le repère
  véhicule, positions monde lissées (Kalman) tracées sur la mini-carte Leaflet, ancres pour les stationnés,
  fond orthophoto IGN (🛰) et orientation cap-navette (🧭).
- **Distances absolues** : deux canaux comparables par bascule ⚑. **Pinhole** (défaut, hauteur de bbox).
  **Homographie sol** (`ground_projection.py`) activée par caméra quand une calibration existe : soit
  manuelle via `calibrate/` (4 coins → DLT), soit **AUTO** via `homography_estimator.py` (pitch estimé par
  ego-motion, bascule `auto_ground_calib`). Le désaccord des deux canaux sur session réelle (14,55 m au
  pitch nul → 3,05 m au pitch estimé) a montré que **l'angle** était la grosse erreur. **Reste** :
  l'échelle absolue (étape 2b — passages piétons segmentés sur l'ortho + matching) et la calib jointe (2c).
- **Attribution de voie** : heuristique par franchissements de lignes ; renvoie `-1` quand les pointillés
  sont trop fragmentés (intersections).
- **Reflets de vitrage** : les « fantômes géants » fragmentés (bbox ~90 % image, conf basse) échappent au
  filtre cinématique `artifact_filter` (raffinement = analyse de transparence sur candidats, à venir).
- **Validation** : le pipeline est complet ; validation navigateur sur session réelle en cours.

## Intégration WAMA
Menu *Applications → WAMA Lab → Cam Analyzer*, carte sur la page d'accueil, dossiers dans le FileManager,
tâches sur la queue Celery `gpu`. App enregistrée dans `wama/settings.py` (INSTALLED_APPS + routes) et
`wama_lab/urls.py` (`cam-analyzer/`).

## Rapport & UI (améliorations récentes)
- **Pertinence** : chaque véhicule d'intersection est tagué `of_interest` (`event_type ∈ {insertion,
  wait}` + classe usager de la route) ; les `turn` et faux positifs COCO sont masqués par défaut
  (bascule « Afficher tout »). 1 ligne/véhicule avec **chips t0/t1/t2 cliquables** (seek + resync).
- **Filtre de classes** : répartition, résumé et **overlay vidéo** limités aux usagers de la route ;
  la légende du camembert sert de filtre overlay interactif.
- **Divers** : renommage de session (🖉), durées en `hh:mm:ss`, panneau pipeline affiché au chargement,
  marqueur GPS **interpolé** (fluide), **vue de dessus des objets** tracée sur la carte (fusion 360°).

## Documentation — 3 piliers + projets
| Fichier | Rôle | Change quand |
|---|---|---|
| [`README.md`](README.md) | Carte d'entrée — vue d'ensemble, modules, API, limites. | Un module/endpoint/limite change. |
| [`CAM_ANALYZER_CHAINE_TRAITEMENT.md`](CAM_ANALYZER_CHAINE_TRAITEMENT.md) | **Comment ça marche + pourquoi** : chaîne [1..10], formules, bascules ⚑, calibration, plan sol 2a/2b/2c, **conception**. DOIT matcher le code. | La logique du pipeline change (même commit que le changelog). |
| [`CAM_ANALYZER_CHANGELOG.md`](CAM_ANALYZER_CHANGELOG.md) | **Historique + backlog + non-régression** : « État courant & RESTE » en tête, journal 1 ligne/commit, procédure. | À CHAQUE changement de comportement. |
| [`projects/ENA_CASA.md`](projects/ENA_CASA.md) | **Spécificités projet** (hors app générique) : données (façon manifeste `dataset`), calibration, rig, contexte du run. | Le run/le rig/la calibration du projet change. |

> Docs **archivés** (`archive/`, contenu vivant absorbé — provenance seulement) : `CAM_ANALYZER_DISTANCE_DESIGN.md`
> (→ CHAINE § Conception), `CAM_ANALYZER_TOPDOWN_STATUS.md` (→ CHANGELOG § État courant), `CONTEXT.md`
> (→ projects/ENA_CASA.md + CHANGELOG). Audit fondateur : `docs/AUDIT_CAM_ANALYZER_VUE_DE_DESSUS_2026-07-15.md`.

## Voir aussi
- **ROADMAP.md §9** — phases détaillées et règles d'événements.
- [`projects/ENA_CASA.md`](projects/ENA_CASA.md) — jeu de données, calibration et rig du run ENA_CASA.
