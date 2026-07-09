# Cam Analyzer

Application **WAMA Lab** d'analyse vidéo **multi-caméras synchronisées** (post-processing) pour
caméras embarquées sur une **navette autonome** (laboratoire transport, Université Gustave Eiffel /
Lescot). Objectif : étudier la **sécurité et la cohabitation** de la navette avec les autres usagers
de la route (détection d'objets, segmentation de voie, proximité, conflits aux intersections).

> **Statut** : pipeline quasi-complet **implémenté**, **validation en cours** (pas tout testé).
> Voir [`CONTEXT.md`](CONTEXT.md) pour l'état détaillé, l'analyse de faisabilité et les priorités de reprise.

---

## Fonctionnalités

- **Sessions** (à la `face_analyzer`) : une analyse = une session UUID ; import multi-rosbags →
  plusieurs sessions en parallèle.
- **Multi-caméras** : 3–4 vues embarquées (avant / arrière / gauche / droite), disposées autour d'une
  silhouette de navette, **drag & drop** des vidéos, **lecture synchronisée** (play/pause/seek + offset
  de synchro par caméra).
- **Détection & tracking** : YOLO (ultralytics) + BoTSORT — véhicules, piétons, deux-roues, etc.
- **Segmentation de la route** : YOLOPv2 (zone roulable + lignes de voie) + modèle BDD100K-seg ;
  marquages au sol épars (passages piétons, lignes d'arrêt) via SAM3.
- **Attribution de voie** : chaque objet est rattaché à une voie ; identification de la voie navette.
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
  `report_type`, `intersections` `[{name,lat,lon,radius_m}]`, options SAM3, modèle de route.
- **AnalysisSession** — UUID, statut (draft/pending/processing/paused/completed/failed), `source_type`
  (video/rtmaps), `gps_track`, `intersection_windows`, `results_summary`, progression.
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
| `sam3_road_analyzer.py` | Marquages au sol (SAM3 prompté). |
| `lane_partition.py` | Attribution de voie par franchissements de lignes ; voie navette. |
| `intersection_analyzer.py` | Moteur intersections : fenêtres GPS, phase d'arrêt, classification d'insertion, t0/t1/t2 (t2 raffiné par ratio d'aspect), densité. |
| `distance_speed.py` | Distance pinhole (fallback) + **vitesse/TTC filtrés** (EMA + régression fenêtrée + clamp). |
| `ground_projection.py` | **Projection sol par homographie** : point-sol bbox → `(X,Y)` repère navette → distances longitudinale/latérale/euclidienne. |
| `calibration.py` | **Calibration homographie** : `solve_homography_dlt` (4 coins d'un objet-sol normé) + solveur pitch 1-point + intrinsèques depuis FoV. |
| `ego_pose.py` | **Ego-pose GPS + accéléromètre** (parse CSV RecFile_Data ; cap = course GPS tenue à l'arrêt ; priorité API navette si dispo). |
| `pass_tracking.py`, `window_recompute.py` | Passes incrémentales (STALE + cascade) et recalcul ciblé. |

### Tâches Celery (`tasks.py`, queue `gpu`)
`process_session_task` (pipeline complet), `compute_lane_events_task`,
`compute_temporal_segments_task`, `compute_conflict_events_task`, `analyze_sam3_only_task`,
`extract_rtmaps_task`.

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
- **Calibration** : `<id>/calibrate/` (POST : 4 coins d'un passage piéton + dimensions → homographie sol
  par DLT, enregistrée dans le profil + `geometry_enabled`).
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
- **Distances absolues** : 🔄 **homographie sol câblée** (`ground_projection.py`), activée par caméra
  quand le profil fournit une calibration (`geometry_enabled` + `camera_calibration[position]`). La
  calibration s'obtient sans mesure terrain via l'endpoint `calibrate/` (4 coins d'un passage piéton
  → DLT). Priorité méthode : DLT 4-points > solveur pitch 1-point > H analytique (priors FoV/hauteur)
  > fallback pinhole. **Reste** : la mini-UI de clic des coins (dernier maillon).
- **Attribution de voie** : heuristique par franchissements de lignes ; renvoie `-1` quand les pointillés
  sont trop fragmentés (intersections).
- **Sur-fragmentation des segments** : détection per-frame → doublons ; consolidée par `LaneEvent` /
  `ConflictEvent` (palliatif UI possible : filtrer les segments < 1 s).
- **Validation** : la majorité du pipeline est codée mais **pas entièrement testée**.

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
  marqueur GPS **interpolé** (fluide). Vue de dessus des objets = à venir (tracé des `(X,Y)` sur la carte).

## Voir aussi
- [`CAM_ANALYZER_DISTANCE_DESIGN.md`](CAM_ANALYZER_DISTANCE_DESIGN.md) — **conception distances/vitesses/TTC
  + homographie + calibration + ego-pose + vue de dessus** (décisions, preuves empiriques, phasage).
- [`CONTEXT.md`](CONTEXT.md) — handoff de reprise (état réel vérifié, faisabilité, algorithmes, priorités).
- **ROADMAP.md §9** — phases détaillées et règles d'événements.
