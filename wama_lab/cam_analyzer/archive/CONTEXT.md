> ⚠️ **ARCHIVÉ / SUPERSEDED (2026-07-21).** Handoff de reprise devenu obsolète. Faits durables projet → `projects/ENA_CASA.md` ; état/priorités → `CAM_ANALYZER_CHANGELOG.md` (§ État courant). Conservé pour provenance uniquement — NE PLUS METTRE À JOUR.

---

# Cam Analyzer — Contexte complet & reprise (handoff)

> But : reprendre Cam Analyzer dans une **session neuve** sans recharger l'énorme transcript
> (~265 Mo). Ce fichier consigne TOUT le contexte utile. Sources de vérité techniques = le **code**
> (`wama_lab/cam_analyzer/`) + **ROADMAP.md §9**. Tenir à jour à chaque palier.

---

## 1. Qu'est-ce que c'est
App **WAMA Lab** (métier spécialisé, estampillée « Lab » comme `face_analyzer` ; ≠ apps génériques
WAMA) pour l'**analyse vidéo multi-caméras synchronisées** (post-processing uniquement) de caméras
embarquées sur une **navette autonome** (labo transport Lescot). Objectif : sécurité / cohabitation
avec les usagers de la route.

**Entrées** : rosbags (script d'extraction fourni séparément) **ou** vidéos déjà extraites.
3–4 caméras : **avant, arrière, gauche, droite**. Screenshots d'exemple : `media/cam_analyzer/`.
**Architecture session-based**, modulaire et flexible (import multi-rosbags → sessions parallèles).

**Deux types de rapport** (`AnalysisProfile.REPORT_TYPE_CHOICES`) :
- `proximity_overtaking` — proximité & dépassements (rapport historique, Phases 1–3) ;
- `intersection_insertion` — **insertions de véhicules aux intersections** au passage de la navette
  (chantier principal récent).

---

## ÉTAT ACTUEL (mise à jour 2026-07-20)

> Depuis la refonte « Distances / vue de dessus » (Phase 3+), une grande partie de ce que les
> sections d'état ci-dessous décrivaient comme « à faire » ou « pas en place » **est désormais
> implémentée**. Cette section fait foi ; les §4, §6, §7/§7bis, §8, §10 conservent le raisonnement
> mais sont requalifiés en historique là où ils décrivaient un état pré-refonte. Détail complet
> (bascules, plan de calibration sol 2a/2b/2c) : **`CAM_ANALYZER_CHAINE_TRAITEMENT.md`**.

Ce qui est désormais IMPLÉMENTÉ :
- **Vue de dessus 360°** : fusion de toutes les caméras dans le repère véhicule ; positions monde
  tracées sur mini-carte **Leaflet** (fond sombre OU orthophoto **IGN 🛰**, nord OU cap-navette 🧭).
- **Tracker global multi-caméras** (`utils/multicam_tracker.py`) : hand-off d'identité inter-caméras
  (gids), classes stables par vote, stationnés + ancres monde, remplissage de fantômes, filtre
  d'artefacts, cap serveur des garés (consensus ratio bbox + prior cluster).
- **Lissage Kalman CV + RTS** (`utils/trajectory_smoother.py`) — écrit `world_en` sur chaque détection.
- **Analyse incrémentale COMPLÈTE** : registre de couverture (`utils/coverage.py` +
  `wama/common/utils/intervals.py`), bouton « **Compléter l'analyse** », mode **Live**
  (`live_analysis_task`), enchaînement auto du tracking 360° (`_run_global_tracking`) en fin de
  complétion / Live.
- **Calibration** : yaw / FOV / levier antenne GPS réglables par session ; **calibration sol AUTO**
  (`utils/homography_estimator.py`) — résout le pitch caméra par minimisation de l'étalement monde des
  stationnés (mesuré : désaccord sol⟷pinhole **14,55 m → 3,05 m** à pitch **21,5°** ; k1/distorsion
  testé et **écarté**). Calib stockée sur la **SESSION** (`config['ground_calib']`,
  `CameraView.ground_homography`, mig 0014), plus seulement sur le profil.
- **11 bascules de comparaison A/B** (`utils/features.py` + `wama/common/utils/feature_flags.py`).
- **Branches d'intersection apprises du trafic** (`utils/intersection_branches.py`) ; **marquages SAM3
  agrégés en monde** (`utils/marking_world.py`) ; **interpolation SAM3** + cadence `profile.sam3_fps`.
- **Nouveaux endpoints** : `camera-yaw/`, `features/`, `complete-analysis/`, `live-cursor/`.

---

## 2. Librairies spécifiques
- **Extraction rosbags** : https://github.com/rpng/rosbags
- **Segmentation route / voies** : **YOLOPv2** https://github.com/CAIC-AD/YOLOPv2
  (drivable area + lane lines, TorchScript) — branché, **à tester**.
- **YOLO** (ultralytics) : détection + tracking BoTSORT. Modèles dans
  `AI-models/models/vision/yolo/detect/` : `yolo11{n,s,m,l,x}.pt` + variantes `-seg.pt`.
  Classes COCO routières : person(0), bicycle(1), car(2), motorcycle(3), bus(5), truck(7).
  **Évolution prévue** : passer de `yolov11n-detect` → `yolov11s-seg` (meilleure précision + segmentation).
- **SAM3** : marquages au sol épars (crosswalks, stop_lines, trottoirs en fallback) — uniquement
  dans les fenêtres d'intersection (coûteux).

---

## 3. Modèle de données (`models.py`, migrations 0001→0020)
> Principales migrations post-0010 : **0011** `ConflictEvent`, **0013** `camera_calibration`,
> **0014** `CameraView.ground_homography`, **0016/0017** `gps_time_offset` / `gps_time_scale`,
> **0018** `lane_width_m`, **0020** `sam3_fps`.
- **AnalysisProfile** : config réutilisable — `model_path` YOLO, `task_type` (detect/segment),
  `target_classes` (IDs COCO), `confidence`, `iou_threshold`, `tracker` (botsort), `report_type`,
  `intersections` = [{name, lat, lon, radius_m}], `sam3_markings_enabled` (mig 0006), seuils.
- **AnalysisSession** : UUID, statut (draft/pending/processing/completed/failed), `config`,
  `results_summary`, `progress`, timestamps.
- **CameraView** : position (front/rear/left/right), `video_file`, durée/fps/résolution,
  `time_offset` (sync inter-caméras).
- **DetectionFrame** : détections frame par frame `[{class_id,class_name,confidence,bbox,track_id,proximity}]`.
- **TemporalSegment** : segments (close_following/overtaking/crossing/custom), start/end, metadata.
- **LaneEvent** (mig 0009) : `lane_id`, `in_shuttle_lane`, `distance_m`, `relative_speed_kmh`, …
  → consolidation par voie.
- **ConflictEvent** : conflit consolidé par (track_id, fenêtre d'intersection) — 1 véhicule = 1 événement.
- **AnalysisPass** (mig 0010) : **traçabilité des analyses déjà faites** (cf. §8 incrémental).

Upload : `cam_analyzer/{user_id}/input/` et `/output/`.

### 3bis. Code réel (`utils/` + `tasks.py`) — source de vérité
> Inventaire au 2026-06 (tailles = profondeur indicative). **À re-vérifier dans le code** avant reprise.

**`utils/`** :
- `rosbag_extractor.py`, `rosbag_metadata_extractor.py`, `rtmaps_parser.py` — extraction entrées
  (rosbag **et** RTMaps `.rec`/CSV).
- `quadrature_video.py` — vidéo quadrature multi-caméras.
- `yolopv2_segmenter.py` — YOLOPv2 (drivable area + lane lines).
- `road_segmenter.py`, `road_model_downloader.py` — segmentation route (+ download modèle).
- `sam3_road_analyzer.py` — marquages au sol via SAM3.
- `lane_partition.py` — partition voies.
- `intersection_analyzer.py` (**38 Ko — le gros moteur**) — analyse intersections/insertions.
- `distance_speed.py` (**3.8 Ko — basique**) — *désormais couche fallback* ; le calcul principal passe
  par la projection sol homographique + `trajectory_smoother.py` (Kalman/RTS). Voir ÉTAT ACTUEL.
- `pass_tracking.py` — **suivi des passes incrémentales** (cf. §8, implémenté, pas juste schéma).
- `window_recompute.py` — recalcul sur fenêtre/param changé (gestion STALE).

**`tasks.py`** (Celery, queue `gpu`) — tout est câblé :
- `process_session_task` (pipeline complet), 4 détecteurs de segments (`_detect_close_following`,
  `_overtaking`, `_crossing`, `_intersection_insertion`), `_compute_lane_events`,
  `_compute_conflict_events` (+ `_gps_speed_at`, `_window_idx_for`), `detect_temporal_segments`.
- Tâches de **recalcul incrémental** séparées : `compute_lane_events_task`,
  `compute_temporal_segments_task`, `compute_conflict_events_task`, `analyze_sam3_only_task`,
  `extract_rtmaps_task` (+ `_extract_h264_frames_to_avi`).

---

## 4. État RÉEL (vérifié dans le code, 2026-06)
> **⚠️ STATUT À RE-VÉRIFIER dans le code avant chaque reprise.** Dixit Fabien : la **quasi-totalité
> est implémentée** ; ce qui manque = **tests** + qualité de la Phase 3. Les marques ci-dessous = code
> PRÉSENT (≠ validé fonctionnellement).

- **Scaffolding + UI** — implémenté : modèles, vues CRUD, templates (grille 4 caméras + silhouette
  navette, drag&drop, lecture synchronisée + `time_offset`), enregistrement écosystème, migrations.
- **Entrées** — implémenté : extraction rosbag + RTMaps + quadrature vidéo.
- **Détection YOLO + tracking BoTSORT** — implémenté : `process_session_task`, `DetectionFrame`,
  vidéo annotée, overlay canvas, timeline proximité.
- **YOLOPv2 (drivable + lanes)** — implémenté, **à tester**.
- **Segmentation route + SAM3 marquages** — implémenté (`road_segmenter`, `sam3_road_analyzer`).
- **Partition voies + LaneEvent** — implémenté (`lane_partition`, `_compute_lane_events`).
- **ConflictEvent (TTC, Δt, min_distance, sévérité, navette_passed_first)** — implémenté
  (`_compute_conflict_events`).
- **Fenêtres d'intersection + GPS** — implémenté (`intersection_windows`, `gps_track`, `_gps_speed_at`).
- **Segments temporels (4 types dont intersection_stop / insertion_front)** — implémenté.
- **Passes incrémentales (`AnalysisPass`, STALE, recompute)** — implémenté (≠ juste schéma).
- **Distance / vitesse** — *Historiquement* basique (`distance_speed.py` ~3.8 Ko) → vitesses non
  réalistes. **Désormais résolu** : projection sol homographique + lissage Kalman/RTS
  (`trajectory_smoother.py`) ; `distance_speed.py` reste le fallback. Voir **ÉTAT ACTUEL**.
- **Infos caméras / calibration (intrinsèques) pour « mesures absolues »** — *Historiquement* le
  chaînon manquant. **Désormais en place** : calibration sol AUTO (`homography_estimator.py`) + manuelle
  + stockée sur la session (mig 0013/0014). Voir **ÉTAT ACTUEL**.
- **Tests** — **non faits / partiels** sur l'ensemble.

---

## 5. Rapport « intersections / insertions » — analyse critique (faisabilité)
Détecter les véhicules **arrêtés/à l'arrêt aux intersections** (D/G) sur lesquelles la navette
arrive, puis s'ils **s'insèrent devant la navette** (même voie / voie opposée) ou **attendent** que
la navette passe. Route à 1 voie par sens. Caméras **avant + arrière** principalement.

**Facile ✅** : détection véhicules (YOLO), tracking multi-objets (BoTSORT/ByteTrack), classification
type véhicule, déclenchement par timecode/zone ±100 m (si GPS), extraction timecodes t0/t1/t2 (découle
du tracking fiable).

**Faisable mais complexe ⚠️** :
1. **Véhicule « arrêté » vs « en mouvement » depuis caméra embarquée** = LE verrou technique. La
   caméra bouge → un véhicule à l'arrêt a un flot optique important. Il faut **compenser l'ego-motion**.
   - Bonne option : vitesse navette + calibration caméra → modéliser le flot du fond, le résidu =
     mouvement propre des objets.
   - Alternative : homographie entre frames sur les marquages au sol (fond statique) → flot résiduel.
   - À éviter : optical flow pur (trop bruité).
   - **Levier #1 : vérifier que les données de vitesse navette sont synchronisées aux vidéos.**
2. **Segmentation réseau routier / position relative** : chaussée, ligne centrale, zone d'intersection.
   Hybride recommandé : segmentation road/non-road + détection marquages. Les intersections = justement
   là où les marquages disparaissent (peut servir de signal).
3. **« Inséré voie navette » vs « franchit voie opposée »** : nécessite de connaître le côté de la
   ligne centrale à chaque instant — fragile aux intersections (peu de marquages).

**Difficile / à risque ❌** :
1. **Distance absolue (mètres)** : caméra monoculaire embarquée → imprécis sans calibration. Marquages
   (lignes 3 m / intervalles) = meilleure approche mais seulement en approche frontale, dégrade > 15 m,
   suppose caméra bien fixée. → **Phase 1 : travailler en distance relative / taille apparente.**
2. **Bird's eye view + TTC/PET** : calibration complète + homographie sol (IPM) + hypothèse sol plan.
   Réservé à une phase avancée, à valider sur quelques cas.
3. **Garés vs arrêtés** : track persistant + distance au centre d'intersection + heuristique « présent
   uniquement dans la zone ±100 m ».

**Questions critiques (à confirmer par Fabien)** : (1) vitesse navette synchronisée ? format/fréquence/
décalage ; (2) GPS des intersections connu ? ; (3) résolution+framerate caméras ? ; (4) calibration
caméra dispo ? ; (5) volume (heures, nb intersections) ; (6) offline only ? ; (7) avant/arrière
synchronisées entre elles ?

---

## 6. Capacités — état RÉEL (code présent ; « à tester » = pas validé)
| Capacité | Outil | État |
|---|---|---|
| Détection véhicules/piétons/2-roues | YOLO yolov11n-detect (ultralytics) | ✅ implémenté |
| Tracking inter-frames | YOLO BoTSORT | ✅ implémenté |
| Drivable area + lane lines | YOLOPv2 (TorchScript) | ✅ implémenté, à tester |
| Marquages (crosswalks, stop_lines, trottoirs) | SAM3 prompted (+ fallback) | ✅ implémenté |
| Identification voie navette / objet | `lane_partition` + `_compute_lane_events` | ✅ implémenté, à tester |
| Conflit avant/après / TTC | `_compute_conflict_events` (ConflictEvent) | ✅ implémenté, à tester |
| Estimation distance / vitesse | projection sol homographique + `trajectory_smoother.py` | ✅ projection sol homographique + lissage Kalman (historique `distance_speed.py` = fallback) |
| Calibration caméra (mesures absolues) | `homography_estimator.py` + calib session/manuelle | ✅ **fait** (auto + manuel + session, mig 0013/0014) |

**Division** : YOLOPv2 = drivable+lanes denses (chaque frame) ; YOLO+BoTSORT = détection+tracking
(chaque frame) ; SAM3 = marquages épars (fenêtres d'intersection) ; GPS+math = conflit/vitesse/distance.

---

## 7. Algorithmes — approche de référence (implémentés, voir §6 ; à valider/affiner)
**Identification voie navette + conflits** (codé dans `lane_partition` + `_compute_lane_events` +
`_compute_conflict_events`) :
1. YOLOPv2 → polygones lane lines + drivable area.
2. Partition du drivable area aux lane lines → N polygones (voies).
3. Voie navette = celle contenant le point image bottom-center (0.95×height).
4. Pour chaque objet tracké : foot point dans quelle voie ? Persistance track_id ⇒ t_enter/t_exit voie.
5. Conflit : objet en voie navette ET trajectoire convergente. TTC = distance / vitesse_relative.
6. Avant/après : compare t_navette vs t_objet au point X. |Δt| < seuil → conflit ; sinon passé avant /
   passera après.

**Estimation distances / vitesses** (*Historique* — le problème « vitesses irréalistes » décrit ici
est **désormais résolu** par la projection sol homographique + lissage Kalman ; cf. **ÉTAT ACTUEL**.
Raisonnement conservé car il fonde le design retenu) :
- *Idée 1 — références normalisées (la plus robuste)* : largeur voie urbaine FR 3.0 m (échelle
  horizontale via lane lines), passage piéton bandes 0.5 m, pointillés 3 m trait / 9 m vide (échelle
  longitudinale), hauteur piéton 1.7 m / véhicule par classe → distance par triangulation pinhole.
- *Idée 2 — homographie sol* : calibrée sur un crosswalk (rectangle de dims connues) → projection
  image→sol, distance exacte du bottom-center. Auto-calibration à chaque crosswalk traversé.
- *Idée 3 — GPS navette* : vitesse/position/heading propres + distance pixel→sol → vitesse **absolue**
  des objets (relative + vitesse navette).
- *Historiquement le chaînon manquant* : ajouter les infos des caméras (calibration/intrinsèques)
  pour fiabiliser les « mesures absolues ». **Désormais en place** : calibration sol AUTO
  (`homography_estimator.py`) résolvant le pitch + calib manuelle/session (cf. **ÉTAT ACTUEL**).

### 7bis. POURQUOI les vitesses étaient irréalistes (analyse historique `distance_speed.py`, 2026-06 — désormais résolu, voir ÉTAT ACTUEL)
Méthode actuelle = **triangulation pinhole monoculaire** : `distance ≈ (hauteur_réelle_classe × focal_y)
/ hauteur_bbox_px`, avec `focal_y` déduit d'un **FoV vertical SUPPOSÉ par position** (avant/arrière 60°,
gauche/droite 90°) et d'une **hauteur réelle SUPPOSÉE par classe** (voiture 1.5 m, piéton 1.7 m, …).
Puis **vitesse = Δdistance/Δt** entre frames (seuil dt > 0.05 s). Causes d'irréalisme, par ordre d'impact :
1. **Dérivation d'un signal bruité** : la distance est bruitée frame-à-frame (jitter de bbox,
   occlusion/troncature qui réduit la hauteur du bbox → distance surestimée) ; la **différencier**
   amplifie ce bruit → vitesses qui oscillent énormément. **AUCUN lissage** (ni Kalman, ni moyenne
   glissante) avant la dérivation.
2. **FoV supposé, non calibré** → `focal_y` faux → **erreur d'échelle systématique** sur toutes les distances.
3. **Hauteur de classe supposée** : forte variance intra-classe (berline vs SUV vs utilitaire = « car »)
   → biais de distance.
4. **Hauteur de bbox = mauvaise primitive** : sensible à la troncature au bord de l'image et à l'angle.
5. **Pas d'ego-motion robuste sur la vitesse** : la soustraction de la vitesse GPS de la navette est
   prévue, mais la vitesse relative elle-même est trop bruitée pour être exploitable.

**Voie de correction (cf. §7 idées 1–3 + §10)** : (a) **calibration / intrinsèques caméra** (le manque
identifié) ; (b) **échelle par références sol normalisées** (largeur voie 3 m via lane lines, pointillés
3 m/9 m, passages piétons 0.5 m) ou **homographie sol (IPM)** calibrée sur un crosswalk, plutôt que la
hauteur de bbox ; (c) **lisser/filtrer** la distance (Kalman/EMA) AVANT de dériver ; (d) vitesse absolue
= relative filtrée + vitesse GPS navette.

### 7ter. Modules vérifiés RÉELS (≠ stubs, 2026-06)
- `intersection_analyzer.py` : moteur complet — `IntersectionAnalyzer` (interpolation GPS `haversine`/
  `gps_at`, `find_intersection_windows`, `analyze_window`, `_find_stopped_phase` arrêt/mouvement relatif,
  `_classify_post_stop_v2` insertion, `_find_t2`, densité trafic, trajectoire bbox).
- `lane_partition.py` : heuristique `lane_id` = nb de franchissements de lignes vers la gauche ;
  voie navette = bottom-centre (0.5W, 0.95H) ; `-1` si dashes cassés (limite documentée).
- `pass_tracking.py` : passes incrémentales réelles — params surveillés/pass → **STALE** au changement,
  `recompute_stale` avec **cascade de dépendances** (amont STALE → aval STALE), `get_passes_status`.

---

## 8. Analyse incrémentale (`AnalysisPass`) — IMPLÉMENTÉE (à tester)
Besoin : stocker les traitements en BDD sous forme d'**indicateurs** pour qu'une **relance** (ex :
ajouter piétons aux voitures) **complète** l'analyse sans tout refaire ni écraser les overlays.
**État réel** : `AnalysisPass` (mig 0010, PassType extraction/intersection_windows/yolo_detect/
yolopv2_lanes/sam3_markings/lane_events/temporal_segments/distance/conflicts, statut **STALE** si un
paramètre du profil change, granularité par caméra, snapshot des `parameters`) + `pass_tracking.py`
+ `window_recompute.py` + tâches de recalcul ciblé (`compute_*_task`). Le mécanisme « ne refaire que
ce qui manque / est périmé » est donc **codé**. → reste à **valider** (et à confirmer le comportement
exact relance YOLO avec classes ajoutées : complétion vs réécriture des overlays).

---

## 9. Bug connu — sur-fragmentation des segments temporels
~500 `TemporalSegment` sur 130 min, beaucoup chevauchants à ±1 s = symptôme de détection per-frame
**sans consolidation par track_id**. `_merge_segments` (seuil 1.0 s) fusionne par type mais **ignore
track_id** → 2 véhicules au même instant = 2 segments parallèles non fusionnés.
**Ne pas corriger maintenant** : Phase 5 (`ConflictEvent`) consolide par (track_id, fenêtre
d'intersection) — 1 véhicule = 1 événement ; Phase 3 (`LaneEvent`) idem pour la voie → le bruit
disparaît mécaniquement. **Palliatif UI** possible : filtrer les segments < 1 s (quasi tous doublons).

---

## 10. Reprendre ici — priorités (mise à jour 2026-07-20)
> Les priorités « fiabiliser les vitesses » et « calibration pas en place » de juin 2026 sont
> **traitées** (cf. **ÉTAT ACTUEL**). Point de reprise réel = achever le **plan de calibration sol**.
- [ ] **Étape 2b du plan de calibration sol** (point de reprise) : **échelle absolue** via passages
  piétons segmentés sur l'**orthophoto IGN** + matching avec les crossings caméra
  (`marking_world.py`). La calib AUTO actuelle (2a) résout le pitch mais pas l'échelle métrique globale.
- [ ] **Étape 2c** : **calibration jointe** (pitch + échelle) une fois 2b disponible.
  → détail dans **`CAM_ANALYZER_CHAINE_TRAITEMENT.md`**, section « Calibration sol — plan complet ».
- [ ] **Valider** empiriquement l'ensemble (analyse incrémentale, tracking 360°, Live).
- [ ] (optionnel) palliatif UI segments < 1 s (§9).

---

## 11. Hygiène de session
La session d'origine « cam-analyzer-intersection-insertion » (~265 Mo) reste sur disque mais **ne pas
la recharger** (lent + coûteux). Bloat = user/assistant/file-history-snapshot (3465 Edit)/progress —
**pas d'images**. Repartir d'une **session neuve** sur ce fichier + ROADMAP §9 + le code. Voir mémoire
[[project-cam-analyzer]].
