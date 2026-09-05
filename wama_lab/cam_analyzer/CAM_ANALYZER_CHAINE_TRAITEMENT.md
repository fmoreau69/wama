# Cam Analyzer — Chaîne de traitement de bout en bout

> **But** : document de référence expliquant TOUTE la chaîne, de la vidéo brute aux
> indicateurs d'intersection — étape par étape, avec les formules, les fichiers, les
> paramètres de calibration et les limites connues.
> **Voir aussi** : [`CAM_ANALYZER_CHANGELOG.md`](CAM_ANALYZER_CHANGELOG.md) (traçabilité +
> **État courant & RESTE À FAIRE** en tête), [`projects/ENA_CASA.md`](projects/ENA_CASA.md)
> (spécificités **projet** : données, calibration, rig — hors app générique),
> `docs/AUDIT_CAM_ANALYZER_VUE_DE_DESSUS_2026-07-15.md` (audit fondateur).
> Le raisonnement de conception (ex-`DISTANCE_DESIGN`) est désormais **absorbé** ci-dessous
> (§ Conception & justification) ; l'ancien doc est dans `archive/`.

> **Piliers de doc (3, rôles nets)** : `README` = carte d'entrée (modules/API/limites) ·
> **ce document** = comment ça marche + pourquoi (DOIT matcher le code) · `CHANGELOG` =
> historique + backlog + non-régression. Un changement de comportement ne touche que
> **CHAINE (si la logique change) + CHANGELOG (toujours)**.

Dernière mise à jour : **2026-09-05** (inventaire exhaustif mesuré dans le code — §INVENTAIRE ;
corrections §[2] IMU, §[4] voie ancienne, §[7] paramètres). Photo précédente : 2026-07-21.

---

## Vue d'ensemble

```
vidéos 4 caméras (RTMaps)          données véhicule (RTMaps)
        │                                   │
   [1] Analyse par caméra              [2] Piste GPS + capteurs
   YOLO+ByteTrack, YOLOPv2, SAM3       (ego_pose.py : cap = bearing entre fixes)
        │                                   │
   [3] Distances & vitesses (pinhole)       │
   [4] Projection sol (⚑ auto_ground_calib  │
       OFF ; recalage ortho 2b = rapport)   │
        │                                   │
        └────────────┬──────────────────────┘
                     ▼
   [5] Repère ego → véhicule (pinhole_ego + cam_to_vehicle : FOV H, yaw, bras de levier)
                     ▼
   [6] Repère véhicule → monde (pose GPS interpolée, cap circulaire)
                     ▼
   [7] Tracking global 360° (hand-off inter-caméras, stationnés, classe stable, fantômes)
                     ▼
   [8] Prédiction TTC/PET par trajectoire
                     ▼
   [9] Vue de dessus (rendu live)      [10] Indicateurs d'intersection (conflits)
```

---

## [1] Analyse par caméra — `tasks.py` (`analyze_session_task`)

Chaque caméra (`front`, `rear`, `left`, `right`) est analysée indépendamment :

- **YOLO + ByteTrack** : détections avec `track_id` **par-caméra** (⚠ le même véhicule a un
  `track_id` différent sur chaque vue — l'ID unifié est `global_track_id`, étape [7]).
- **YOLOPv2** (caméra avant, option 4 vues) : zone roulable + lignes de voie (`road_mask`).
- **SAM3** : marquages au sol (`sam3_marking`), fenêtré sur les intersections.
- Attribution de voie (`lane_partition.py`, avant uniquement).

Persistance : `DetectionFrame.detections` = liste de dicts JSON, **dans l'espace pixel natif
de chaque caméra** (front 384×248, left 408×244, rear 408×248, right 384×244 — vérifié en base).

## [2] Pose ego (GPS) — `ego_pose.py`

- Piste GPS ~1 fixe / 2,7 s. **Cap = bearing entre fixes consécutifs** (maintenu si
  déplacement < 0,30 m) → **bruité à faible vitesse** (±10-25°), c'est LA source d'erreur
  angulaire dominante (bras de levier : 8 m × 15° ≈ 2 m d'arc sur les objets).
- Synchro vidéo↔GPS : `ts = t_vidéo × gps_time_scale + gps_time_offset` (par session).
- Interpolation backend : `_shuttle_pose_at` (prediction_adapter) — position lerp, **cap
  en interpolation CIRCULAIRE** (plus court arc ; l'ancien lerp linéaire passait par 180°
  au wrap 359°→1° — navette plein nord = wrap permanent).
- Rendu JS : cap lissé par **moyenne circulaire sur ±2 fixes** (`updateTopDown`).
- ⚠ **Accéléromètre : parsé, stocké, JAMAIS CONSOMMÉ** (mesuré 2026-09-05, `git log -S` : un seul
  commit, celui qui a créé `imu_track` le 2026-07-09). `EgoPose.accel` n'est lu par aucune méthode ;
  `profile.use_imu` n'a aucun consommateur. **Aucun filtre (Kalman ou autre) ne s'applique à la
  navette** : position = GPS brut interpolé linéairement, cap = bearing entre fixes. Le Kalman+RTS
  de `trajectory_smoother` ne sert que les OBJETS mobiles (§[7]). Détail : §INVENTAIRE D.1.
  → **Comblé le même jour derrière ⚑ `shuttle_filter` (OFF)** : `ego_pose.effective_gps_track`
  est désormais le point d'accès UNIQUE de la pose pour tout ce qui POSITIONNE (tracker,
  prédiction, calib 2a, marquages, branches, artefacts) ; fenêtres et couverture restent sur le
  brut (elles délimitent l'analyse). Le lisseur a rejoint `wama_data.kinematics.rts_smoother`,
  `trajectory_smoother` délègue (non-régression sur empreinte).

## [3] Distances & vitesses — `distance_speed.py`

- **Distance pinhole par la HAUTEUR de bbox** : `distance_m = H_classe · f_y / h_bbox_px`
  avec `f_y = ih / (2·tan(FOV_V/2))`. C'est **la** distance de référence (affichée sur les
  vues caméra et utilisée partout).
- `DEFAULT_FOV_V_DEG` = **valeurs réelles du rig** : avant/arrière 61° (AXIS F4005-E 110°H),
  latérales 31° (AXIS F1015 réglées ~55°H). ⚠ Les sessions annotées AVANT le 2026-07-16
  utilisaient 60/90° → distances latérales ×3,6 trop courtes, **corrigées rétroactivement**
  via `dist_scale` (voir [5]). L'analyse trace `session.config['fov_v_used']` par caméra.
- **Vitesse relative** = dérivée de distance (régression fenêtrée ~0,6 s) — une voiture
  garée « affiche » la vitesse de la navette qui s'en approche (suffixe « rel. » dans l'UI).
- **TTC** = distance / vitesse de rapprochement (ratio → insensible à l'échelle de distance).

## [4] Projection sol — `ground_projection.py` + `homography_estimator.py` (⚑ `auto_ground_calib`, OFF)

État 2026-07-21 — **deux générations** de calibration sol :

- **Ancienne voie (passages piétons SAM3, `CameraView.ground_homography`)** — calibrée depuis les
  passages SAM3 (dimensions normées), écrivait `dist_longitudinal_m`/`dist_lateral_m`/`ground_xy`.
  **Prouvée biaisée** sur les données réelles (inversion de signe #546 ; profondeur non monotone #537
  : 23,5 m pinhole vs 6,8 m homographie). ⚠ **CONDITIONNÉE, pas débranchée** (corrigé 2026-09-05) :
  l'analyse l'applique dès que `profile.geometry_enabled ∧ camera.ground_homography`
  (`tasks.py:1274-1292`, `1383-1392`) — et la calibration SAM3 (`_calibrate_from_crossing_polygons`)
  **force `geometry_enabled=True`**. Consommateurs effectifs : `marking_world` (marquages sur la
  carte, **sans condition** si elle existe) et `lane_estimator` (largeur de voie) — **pas le
  tracker** (qui lit 2a et le pinhole), ni le JS pour les véhicules. Détail : §INVENTAIRE D.2.
- **Voie retenue (`homography_estimator.py`, étape 2a)** — l'angle (pitch/hauteur) est estimé par
  **étalement monde des stationnés** (auto-calibration, gain ×5 mesuré, cf. § Calibration sol) et
  stocké dans `session.config['ground_calib']`. Le tracker 360° l'applique via `ground_ego`
  **UNIQUEMENT si `auto_ground_calib` est ON** (défaut **OFF**) ; sinon → placement pinhole `[3]`.
- **Recalage ortho 2b** (`ortho_markings.py`, `compute_ortho_recalage_task`) : offset absolu par
  intersection via passages piétons SAM3 sur ortho IGN (~5,1 m mesuré). **RAPPORT SEUL —
  `results_summary['ortho_recalage']`, NON appliqué au positionnement** (bascule à venir).

> ⚠ **Placement mixte quand `auto_ground_calib` = ON** (gap G7, cf. CHANGELOG) : `ground_ego` retombe
> **silencieusement** sur le pinhole hors de portée utile → un A/B « ON vs OFF » compare *pinhole* à
> *sol+pinhole mélangé*. Toute mesure A/B doit s'appuyer sur `distance_source` ∈ {homography, pinhole}
> (présent par détection) pour être honnête.

Voir § **Calibration sol — plan complet** (angle par le mouvement / échelle par les marquages) et
`projects/ENA_CASA.md` §2 (valeurs de calibration du run ENA_CASA).

## [5] Repère caméra → véhicule — `prediction_adapter.py`

`camera_geometry(session)` = **source unique** de la géométrie par caméra
(défauts rig ENA surchargés par `session.config`) :

| Paramètre | Défauts rig | Surcharge session | Rôle |
|---|---|---|---|
| `yaw` | front 0°, right **75°**, rear 180°, left **−75°** | `config['camera_yaw']` (bouton 🧭 Yaw) | orientation de montage |
| `fov_h` | 110/55/110/55° | — | focale latérale `f_x = iw/(2·tan(FOV_H/2))` |
| `dist_scale` | `tan(fov_v_used/2)/tan(fov_v_réel/2)` | `config['fov_v_used']` (écrit par l'analyse) | correction des distances annotées avec un ancien FOV |
| `mount` | front (0, +4.5), sides (±1.0, +3.4), rear (0,0) | `config['camera_mount']` | bras de levier (origine = **CENTRE arrière** du véhicule ; le point GPS = antenne coin arrière droit y est ramené via `gps_antenna`) |

- `pinhole_ego(det, iw, ih, fov_v, fov_h_deg, dist_scale)` → (latéral, longitudinal) :
  longitudinal = `distance_m × dist_scale` ; **latéral = dm·(bcx − cx)/f_x** avec la focale
  **HORIZONTALE réelle** (l'ancienne focale verticale 60° supposée compressait ~1,6×).
  Rejette les bbox coupées au bord (x1≤8 ou x2≥iw−8 : cap/latéral non fiables).
- `cam_to_vehicle(lat, long, yaw, mount)` : rotation yaw + translation bras de levier.
  Sans le mount, tous les objets avant étaient dessinés ~4,5 m trop près de la navette.

## [6] Véhicule → monde — `prediction_adapter.py`

`ego_to_world(se, sn, sh, xv, yv)` : rotation par le cap navette + translation à la position
GPS (repère local est/nord). Toute erreur de cap ego balaye les objets en arc (bras de levier).

## [7] Tracking global 360° — `multicam_tracker.py` (`annotate_global_tracks`)

Lancé par `compute_indicators_task` (bouton « Calculer les indicateurs »), par la passe dédiée
`compute_global_tracking_task`, et en fin de mode Live — via `_run_global_tracking` (`tasks.py:2359`).
*(Corrigé 2026-09-05 : `annotate_prediction_task` cité ici n'existe pas.)* Ordre interne complet :
§INVENTAIRE A.11.

- Association frame par frame en repère monde : gate prédictif `pe = e + ve·dt` (gate **croissant**
  `3,5 m + 1,5 m/s·Δt`, trou max **2,5 s** — pas 1 s, corrigé 2026-09-05 ; verrou de chaîne 4 s ;
  recollement de tracklets ≤ 6 s). **Vitesse de track lissée EMA α=0.3 + rejet des mesures >15 m/s** (le delta
  instantané brut transformait 25 cm de jitter en 3 m/s fantôme → hand-off cassé).
- Écrit `global_track_id` (ID unifié 360°, affiché `G<n>` sur les vidéos — s'il est identique
  entre deux vues, le hand-off fonctionne).
- **Stationnés** : étalement des positions monde < seuil sur la durée → `stationary_gids`
  (→ badge 🅿, bouton « Masquer garés », cap figé en vue de dessus).
- **Classe stable** : vote majoritaire pondéré par la confiance sur toute la durée du track
  → `stable_class` sur chaque détection (anti-flapping car↔truck).
- **Fantômes** (`predicted:true`, `vehicle_xy`) : comblement des trous de détection au
  hand-off — affichés SEULEMENT si le bouton Prédiction est ON.

## [8] Prédiction TTC/PET — `annotate_prediction_indicators`

Trajectoires monde par `global_track_id` → TTC/PET par extrapolation (pas 0,2 s, horizon 4 s).
Écrit `prediction_ttc`/`prediction_pet` ; le bouton Prédiction bascule la couleur des
gabarits sur ces valeurs (sinon `ttc_s` de la frame).

## [9] Vue de dessus (rendu live) — `static/cam_analyzer/js/index.js`

Recalcule les positions **par frame** à partir des champs persistés (pas de positions
pré-calculées) — mêmes formules que [5]/[6] avec `camGeo` (miroir JS de `camera_geometry`) :

- **Position — hiérarchie GLOBALE (2026-07-19)** : ① **ancre** monde (stationné, médiane du
  track) > ② **`world_en`** (mobile tracké : trajectoire monde fusionnée **Kalman avant +
  RTS arrière** sur toutes les observations du gid, toutes caméras — écrite par le
  tracker, caméra-indépendante, sans retard de phase) > ③ reconstruction par frame
  (repli : Y = `distance_m × distScale` EMA, X = pinhole `f_x` FOV H EMA — les gardes
  zone-fiable/bord-d'image ne s'appliquent qu'ici). Les frames analysées APRÈS le dernier
  « Calculer les indicateurs » restent en repli jusqu'au prochain calcul.
- **Cap objet** — fusion (voir §Cap ci-dessous).
- **Gabarit** : rectangle aux dimensions de `stable_class` (sinon vote live), orienté au cap.
- Ego : silhouette navette étendue vers l'AVANT depuis le point GPS (antenne à l'arrière).
- Badge d'état (« 360° ON · Préd OFF · objets: F7 R2… ») + bascules persistées (localStorage).

### §Cap — fusion trajectoire ↔ ratio de bbox (2026-07-16, pondération vitesse 2026-07-17)

1. **Trajectoire** : direction de la trace monde, points HORODATÉS (cap identique en
   lecture avant/arrière — orienté par le signe de Δt), EMA, MAJ seulement si déplacement
   > 0,8 m/fenêtre ; purge sur seek > 2 s.
2. **Ratio de bbox** : l'étendue apparente `E = L·|sinθ| + W·|cosθ|` se déduit du seul
   ratio pixels (`E = H·(f_y/f_x)·(w_px/h_px)`, indépendant de la distance). Inversion →
   `|θ|` vs ligne de visée → 2 candidats de cap mod 180° (gabarit = rectangle, le sens
   n'importe pas), départagés par continuité temporelle, lissés par **EMA axiale**
   (vecteur d'angle doublé). Gating : conf ≥ 0.4, hauteur ≥ 12 px, bbox non coupée,
   classe avec dimensions connues.
3. **Pondération CONTINUE par la vitesse** (`w_ratio = clamp((2 − v)/2, 0, 1)`, v estimée
   sur la fenêtre de trace) : ratio seul à l'arrêt/stationné, trajectoire seule ≥ 2 m/s
   (~7 km/h — le mouvement réel observé est sans ambiguïté), **fondu axial** entre les
   deux dans l'intervalle.
   Limite connue : E écrête au pic diagonal (~68° pour une voiture) → un vrai 90° peut
   être lu ~68-80° ; les miroirs/ombres gonflent légèrement le ratio.

## [10] Indicateurs d'intersection — `tasks.py` (`_compute_conflict_events`) + `intersection_analyzer.py`

Fenêtres d'intersection (GPS + zones nommées) → événements de conflit sur les véhicules en
voie navette (TTC/PET/distance min/vitesses) → tables et timeline de l'UI.

---

## Doctrine : calculs GÉNÉRIQUES, seule la SORTIE du rapport diffère (2026-07-18)

Toute la chaîne [1..9] est **identique pour tous les types de rapport** (intersections,
dépassements, …). Les capacités sont gouvernées par ce que le profil DÉCLARE, jamais
par `report_type` :

| Étape | Gouvernée par |
|---|---|
| YOLOPv2 (voies/zone roulable) | `profile.road_model_path` présent |
| Fenêtres spatiales | `profile.intersections` non vide |
| Distance/vitesse/TTC, tracking 360°, ancres, fantômes, prédiction | toujours (aucune condition) |

Seule l'étape [10] (segments temporels typés, événements de conflit, rendu du rapport)
branche sur `report_type` — c'est la couche de SORTIE. Interdit d'ajouter un
`if report_type` en amont de [10].

**Chantier noté** : les détecteurs de segments « dépassement » datent d'avant le
tracking 360° — les refonder sur les trajectoires monde par `global_track_id`
(un dépassement = un track qui passe de derrière à devant le long du flanc,
exactement la signature validée sur G242) au lieu des heuristiques par caméra.

### Analyse incrémentale par complétion (design 2026-07-18, ✅ IMPLÉMENTÉ 2026-07-19)

> Statut : les 3 étapes sont livrées — registre `coverage.py`, bouton « Compléter l'analyse »
> (`complete_analysis` → `process_session_task(completion_scope=…)`), mode Live (⚡,
> `live_analysis_task`). La complétion et la fin de Live enchaînent automatiquement le
> tracking 360° (`_run_global_tracking`). Le design ci-dessous reste la référence.

Problème : le rapport intersections restreint l'analyse aux fenêtres (~zones de 60 m),
le rapport dépassements exige le parcours complet → une session analysée « restreinte »
ne peut pas produire un rapport dépassements sans tout ré-analyser.

Design retenu (validé sur le principe avec Fabien) :

1. **Le scope d'analyse = union des besoins des rapports demandés.** Chaque type de
   rapport DÉCLARE son scope requis (dépassements : parcours complet ; intersections :
   fenêtres ∪ rayon ; ronds-points futurs : leurs zones). Le rayon d'un rapport ne
   gouverne que sa FENÊTRE de sortie — pas ce qui a été analysé.
2. **Registre de couverture** : intervalles `[t0, t1]` réellement analysés par caméra
   (`session.config['analyzed_ranges']`), tenu par l'analyse. La présence de
   `DetectionFrame` en base est la vérité de secours.
3. **Complétion** : scope demandé − couverture = intervalles manquants → l'analyse ne
   traite QUE ces tranches (l'itérateur fenêtré `_use_window_iter` sait déjà itérer des
   plages de frames ; timecodes = frame/fps, inchangés).
4. **Coutures** : les `track_id` ByteTrack ne se recollent pas entre tranches — c'est le
   TRACKER 360° qui répare (verrou de chaîne + stitching en repère monde, déjà validé
   sur des trous > 2 s). Après complétion : relancer « Indicateurs » (obligatoire).
5. **Vidéo annotée** : PAS de patch incrémental (coût ≫ gain) — l'overlay live du player
   est dessiné depuis les DetectionFrames et couvre automatiquement les tranches
   complétées ; la vidéo annotée exportée reste un artefact à régénérer à la demande.
6. **Recommandation d'usage** : analyser le parcours COMPLET par défaut (une seule fois,
   tous les rapports deviennent des passes légères gratuites) ; la restriction reste une
   optimisation d'aperçu rapide, la complétion rattrape ensuite.

## Calibration par session (`AnalysisSession.config`)

| Clé | Écrite par | Consommée par |
|---|---|---|
| `camera_yaw` | panneau Calibration (Yaw 4×) | [5] backend + [9] JS |
| `camera_fov` | panneau Calibration (FOV lat.) | `camera_geometry` [5]/[9] |
| `camera_mount` | (manuel, pas d'UI) | [5] backend + [9] JS |
| `gps_antenna` | panneau Calibration (Antenne 2 champs) | `shuttle_trajectory` [7] (tracker/prediction/marking_world/branches/estimator) + `antennaCorrect` [9] (marqueur navette, parcours, **ET gabarit de voie `_sm`** — corrigé 552dd24 : le point GPS est l'antenne, coin arrière droit ≈ (1.0, 0.0), tout ramené au CENTRE arrière) |
| `fov_v_used` | l'analyse ([1]) | `dist_scale` [5]/[9] |
| `gps_time_offset/scale` | UI synchro | [2] |
| `features` | panneau ⚑ Modes | `effective(session)` (voir table bascules) |
| `analyzed_ranges` | [1] complétion/live | registre de couverture ([coverage.py]) |

`profile.sam3_fps` (cadence SAM3) et `profile.geometry_enabled` (active l'homographie sol)
sont sur le PROFIL (pas la session).

## Bascules de comparaison (⚑ Modes)

Chaque amélioration COMPARABLE est une bascule déclarée dans `utils/features.py`
(mécanisme générique : `wama/common/utils/feature_flags.py`, conçu pour WAMA Data) —
panneau ⚑ Modes de la vue de dessus, persistée dans `session.config['features']`.
Les bascules `live` agissent instantanément au rendu (JS `rebuildCamGeo`) ET côté
backend au prochain calcul (`camera_geometry` les consulte — un seul point d'application
par côté). Règle : **jamais de if ad hoc dispersé** pour une amélioration comparable.

| Bascule | Défaut | Scope | Effet |
|---|---|---|---|
| `fov_dist_correction` | ON | live | correction des distances annotées avec un ancien FOV V |
| `mount_lever_arm` | ON | live | bras de levier des caméras (montage vs centre arrière) |
| `heading_ratio` | ON | live | cap par ratio de bbox fondu avec la trajectoire |
| `antenna_lever` | ON | compute | point GPS = antenne (coin arrière droit ENA) ramené au centre arrière |
| `artifact_filter` | ON | live | masque les reflets/artefacts fixes (bbox immobile pendant que la navette avance) |
| `anchor_heading` | ON | live | cap des garés = consensus axial du ratio sur toute la vie du track |
| `heading_cluster` | ON | compute | prior de cap : garés voisins <15 m partagent leur axe |
| `sam3_interp` | ON | live | interpolation des marquages SAM3 entre keyframes (fondu aux bords) |
| `world_markings` | ON | compute | stop_line/crossing projetés+agrégés en monde (bornes d'intersection) |
| `learned_branches` | ON | compute | voies croisantes apprises des trajectoires du trafic |
| `ortho_correction` | OFF | compute | étape 2b APPLIQUÉE (fonction `cam_analyzer.ortho_correction`) : biais caméra (médiane globale) écarté, correction GPS locale par intersection, interpolée et atténuée selon le masquage satellite BD TOPO |
| `shuttle_filter` | OFF | compute | **pose NAVETTE filtrée** (Kalman vitesse-constante + RTS, brique pure `driving.ego_track_filter`) : position lissée, cap dérivé de la vitesse lissée et tenu sous 1 m/s. Calcul stocké (`results_summary.shuttle_filter`), bascule relue au point d'ingestion UNIQUE serveur (`ego_pose.effective_gps_track`) et JS (`_applyShuttleFilter`). Premier ⚑ qui touche la pose navette (2026-09-05). A/B console : déplacement RMS, écart de cap médian, part tenue |
| `track_speed_unified` | OFF | compute | (chantier) vitesse/distance monde uniques par track |

## Calibration sol — plan complet (angle par le mouvement + échelle par les marquages)

> **Insight fondateur (2026-07-20)** : la calibration homographique complète se décompose
> en DEUX inconnues aux sources DIFFÉRENTES et complémentaires. Ne jamais confondre les deux.
>
> - **L'ANGLE (tangage/roulis)** se récupère par le MOUVEMENT seul, sans vérité terrain :
>   un objet statique vu à plusieurs distances doit se projeter au même point monde
>   (ego-motion GPS = ancre). C'est l'auto-calibration → `homography_estimator.py`. La
>   cohérence contraint fortement l'angle (sensibilité différentielle à la distance) mais
>   est AVEUGLE à l'échelle (un facteur d'échelle global préserve le regroupement).
> - **L'ÉCHELLE ABSOLUE** exige des objets de GÉOMÉTRIE CONNUE au sol : passages piétons
>   (bandes ~50 cm), lignes axiales à intervalles normalisés. Ce sont des mètres-étalons.
>   Le mouvement ne peut PAS la déduire — c'est la limite mathématique, pas un manque d'effort.

**État `homography_estimator.py` (résout l'angle ; l'estimateur v1 reste un rapport) :**
- résout (pitch, hauteur) par étalement monde des stationnés + ancrage échelle pinhole ;
- MESURÉ caméra avant : baseline désaccord sol⟷pinhole 14,55 m → **3,05 m** à pitch 21,5°
  (hauteur physique 2,2 m). Gain ×5, entièrement dû à l'angle ;
- **k1 (distorsion) testé, ÉCARTÉ** : sature la borne sans gain (3,05→3,05) → pas le levier ;
- résiduel ~3 m = ancrage pinhole (±10 %) + bruit bas-de-bbox = **l'échelle manquante**.

**Étapes restantes (dans l'ordre) :**

- **2a — Pitch estimé : CÂBLÉ derrière `auto_ground_calib` (défaut OFF)** — `store_ground_calib`
  écrit `config['ground_calib']`, le tracker applique `ground_ego` (`multicam_tracker.py`).
  Caméra arrière = 3 stationnés seulement → non fiable (exclue). **Reste** : (i) une **métrique
  A/B objective** (désaccord sol⟷pinhole/ortho via `distance_source`, RMS reprojection) pour
  décider de basculer le défaut ; (ii) corriger le **placement mixte G7** (fallback pinhole
  silencieux) pour que l'A/B soit propre. La bascule seule ne « termine » pas 2a — la métrique si.
- **2b — Recalage ABSOLU via marquages ortho** (idée Fabien, l'échelle manquante) —
  ✅ **FAIT (rapport + affichage)**, commit `034912c`, `utils/ortho_markings.py`. SAM3 segmente
  les passages piétons **sur l'orthophoto IGN** (mosaïque WMTS z19 ≈ 0,22 m/px, géo-transform
  Web Mercator exacte), puis MATCHING avec nos crossings agrégés depuis les caméras
  (`marking_world.py`). Tâche `compute_ortho_recalage_task` + bouton « Recalage ortho »
  (panneau Calibration) ; crossings ortho tracés en orange sur la mini-carte. **MESURÉ** :
  2 passages piétons/intersection (conf ~0,7), offset global caméra→ortho **2,93 m E / 4,2 m N
  (~5,1 m)** = biais GPS + projection résiduel. **RAPPORT SEUL** : l'offset est stocké
  (`results_summary.ortho_recalage`) mais PAS appliqué au positionnement — validation visuelle
  d'abord. Amers = marquages PERMANENTS uniquement (les véhicules statiques de l'ortho datent
  d'un autre jour ; piste secondaire = repérer les ZONES DE STATIONNEMENT). NB : les crossings
  n'ont pas de correspondance inter-frame → ils entrent par la GÉOMÉTRIE CONNUE, pas par le
  solveur d'étalement 2a. **Reste 2b-app** : appliquer l'offset derrière une bascule.
- **2c — Calibration jointe** : une fois 2a+2b mesurés, résoudre angle+échelle+distorsion
  ensemble (contraintes mouvement ET marquages), écrire `camera.ground_homography` par caméra,
  brancher sur le placement des objets (fusion bas-de-bbox ⟷ pinhole).

## Autres limites connues / chantiers ouverts

1. **Unification distance/vitesse par track** (bascule `track_speed_unified`, OFF, à
   implémenter) : servir sur chaque détection la position/vitesse MONDE du `global_track_id`
   (tracker [7], `ve/vn` lissés) au lieu des valeurs par-caméra — une seule vérité par
   véhicule sur toutes les vues, améliore distance/vitesse/TTC génériquement.
2. ✅ **Cap par cluster de stationnés** — FAIT (bascule `heading_cluster`, 2026-07-20) :
   l'axe est appris des voisins <15 m (mélange axial pondéré). Voir table bascules.
3. **YOLO-OBB / masques du mode segment** : la chaîne entière est indexée sur
   bbox/classe/conf/track (`_extract_detections` ne lit que `prediction.boxes`) → tout
   fonctionne à l'identique en segmentation, MAIS les masques sont JETÉS à l'extraction. Ils
   offrent : (a) orientation par `minAreaRect` = boîte orientée GRATUITE (OBB sans
   fine-tuning), (b) point de contact sol affiné (ligne des roues vs bas de bbox) → meilleure
   distance ET meilleure entrée pour la calibration 2a, (c) centre latéral robuste (centroïde
   vs centre bbox). À déclarer bascule `mask_geometry` le moment venu.
4. **Branches apprises — couverture** : une branche sans trafic croisant observé reste
   invisible (fallback bande symétrique). Complétée par 2b (marquages = géométrie sans trafic).
5. **Bbox coupées au bord** : pas affichées en vue de dessus (délibéré) ; le hand-off les
   ponte temporellement (gate croissant, gap 2,5 s).
6. **Cap ratio** : ambiguïté résiduelle aux angles > pic diagonal (~68°).
7. **Reflets « fantômes géants »** (vitrage latéral) : bbox ~90 % image, conf 0,3, fragments
   1-4 s — non couverts par `artifact_filter` (critère « statique en image ») → raffinement =
   analyse de transparence sur candidats (conf basse + bbox géante + fragments courts).
8. « Fixer » la zone routière rose (road_mask) : non opérationnel, sémantique à préciser.

---

## [E] Piste EXPLORATOIRE — profondeur monoculaire (2026-08-05)

> ⚠ **1ère passe BRANCHÉE, non fumée au GPU (2026-08-05).** L'usage **4 (re-calage du plan de sol)**
> est câblé et sélectionnable via le flag global `depth_estimation` ; le reste de la section reste
> de la conception. **Aucun smoke GPU/navigateur** n'a été fait (GPU interdit sous WSL2 ici) →
> l'inférence Depth Pro et le gain `placement_spread` sont **à valider côté runtime/R760xa**.
> Détail dans `CAM_ANALYZER_CHANGELOG.md` (2026-08-05).

> 🧱 **DÉCOUPLAGE EN 3 ÉTAGES (2026-08-05, recadrage Fabien « analyse d'abord, calculs ensuite »).**
> La profondeur n'est plus un bloc monolithique greffé dans `global_tracking` (invisible) mais une
> chaîne de 3 étages indépendants, contrôlables séparément :
> - **ÉTAGE 1 — ANALYSE** = la **passe `depth`** du volet droit (`PassType.DEPTH`, **session-wide**,
>   les 4 caméras en UNE ligne). GPU. Infère et **STOCKE la donnée brute** : cartes de profondeur
>   downsamplées (float16 `.npz` sur disque, modèle `DepthFrame`) + profondeur de contact par
>   détection (`depth_distance_m`, champ additif du JSON `detections`). **Indépendante du flag** —
>   on lance l'analyse une fois, on la garde.
> - **ÉTAGE 2 — CALCULS** = la **passe `depth_calc`** du volet (`compute_depth_calc_task`, session-wide,
>   juste après `depth`, avant `global_tracking`). CPU, **re-jouable sans re-payer le GPU** : relit
>   `DepthFrame` → plan de sol (RANSAC, `store_ground_calib`) et cross-check distance
>   (`depth_distance_report`). Aucun `import torch/cv2` → **exécutable sous WSL2**.
> - **ÉTAGE 3 — AFFICHAGE** = le flag `depth_estimation` (consomme le plan profondeur vs homographie ;
>   overlay de profondeur différé, la carte est déjà stockée pour l'alimenter).

### Pourquoi cette piste ouvre maintenant

Le format s'y prête, contrairement à ce qu'on pourrait craindre d'un « 360° » : le rig est fait de
caméras **perspectives** (F4005-E 61° V, F1015 31°), pas d'un capteur équirectangulaire. Les
modèles de profondeur monoculaire sont entraînés sur des images perspectives — ils s'appliquent
caméra par caméra, sans reprojection ni couture.

Modèle retenu : **`apple/DepthPro-hf`** — natif `transformers` (`DepthProForDepthEstimation`),
**métrique** ET **focale/FOV estimés**, **Apache-2.0**. Ce dernier point est décisif : le
monoculaire manque d'échelle absolue, et la focale estimée par Depth Pro fournit exactement
l'intrinsèque que le re-calage du plan de sol consomme (§Conception). Écarté : DA3
(`depth_anything_3`, package custom), UniDepth v2 (ops CUDA custom), DA V2 Metric (exige les
intrinsèques connus). ⚠ Piège : `apple/DepthPro` (sans `-hf`) est le checkpoint d'origine
(`depth_pro.pt`, non chargeable par `transformers`) — c'est bien `apple/DepthPro-hf` qu'il faut.

### Ce que la profondeur apporterait, par usage

**1. Reflets — attaque la limite connue n°7.** Un objet réel crée une **discontinuité de
profondeur le long de sa silhouette** : le fond saute derrière lui. Un reflet est *dans le plan de
la surface réfléchissante* (vitrage latéral, carrosserie, chaussée mouillée), donc le champ de
profondeur reste **continu** à travers le contour de la détection. Le critère n'est pas « quelle
profondeur » mais « y a-t-il une marche au bord » — plus discriminant que le critère « statique en
image » d'`artifact_filter`, et que l'analyse de transparence envisagée jusqu'ici.
⚠ Réserve : les modèles monoculaires hallucinent parfois une silhouette plausible pour un reflet.
C'est le test de discontinuité au contour, pas la valeur brute, qu'il faut évaluer.

**2. Statique vs mobile — plus fort qu'une stabilisation.** La caméra bouge, donc la profondeur
d'un véhicule stationné change : c'est normal. Ce qui est invariant, c'est qu'elle doit évoluer
**exactement comme l'ego-motion le prédit**. Confronter l'évolution observée à l'évolution prédite
(GPS + map-matching déjà en place) donne un discriminant statique/mobile. Enjeu réel : un véhicule
garé n'est pas une interaction, un véhicule qui roule en est une.

**3. Confrontation au pinhole — réciproque, pas redondante.** La distance de référence
(`H_classe · f_y / h_bbox_px`, cf. §Conception) échoue dans deux cas précis : `H_classe` est une
taille moyenne (enfant, camionnette → erreur proportionnelle et silencieuse), et la hauteur de
bbox suppose l'objet **entier et non tronqué** — un piéton dont les jambes sont masquées est
déclaré *plus loin qu'il n'est*, précisément au moment d'un croisement. La profondeur lit les
pixels : elle ne dépend ni de la taille supposée, ni de l'intégrité de la boîte. Inversement, le
pinhole fournit l'**ancrage d'échelle** qui manque au monoculaire. Un désaccord franc entre les
deux est lui-même un signal : occlusion, ou objet de taille atypique.

**4. Re-calage du plan de sol.** Le nuage de points permettrait de ré-estimer le plan de sol, donc
d'attaquer le biais d'homographie mesuré (23,5 m pinhole contre 6,8 m homographie) qui avait fait
débrancher cette voie.

**5. Ordre d'occlusion.** La profondeur *ordinale* (qui est devant qui) est la partie robuste des
modèles monoculaires — aucune précision absolue requise — et servirait la continuité du tracking à
travers les croisements.

### Limites à garder en tête avant de chiffrer

- **Portée.** L'erreur relative croît avec la distance ; au-delà de ~30-40 m le signal ne vaut
  plus grand-chose. En deçà de ~15-20 m il est exploitable — soit la zone où les interactions se
  jouent. La piste est donc **de proximité**, assumée comme telle.
- **Le TTC est insensible au biais d'échelle** (rapport distance/vitesse) : même une profondeur
  biaisée d'un facteur constant donne un TTC exploitable. C'est ce qui rend la piste intéressante
  malgré l'imprécision métrique.
- **Coût GPU.** Un modèle de plus par image, en surcroît de la détection. Atténuation possible :
  n'exécuter que sur les ROI candidates, ou à cadence réduite.
- **Dépendance aux intrinsèques.** La profondeur métrique en dépend : la même erreur de FOV qui a
  coûté un facteur 3,6 (cf. [3]) mordrait ici. Même discipline de calibration.
- **Validation.** Comme toute bascule ici : A/B à **métrique chiffrée**, jamais visuel seul. Le
  banc générique (`manage.py bench --task <tâche>`) accueillerait un protocole `depth-estimation`,
  et l'A/B se ferait contre la distance pinhole sur des séquences à occlusion connue.

### Intégration — plan (décidé 2026-08-05)

Les 5 usages ne forment PAS un silo neuf : **ils alimentent l'instrument A/B** déjà en place
(brique commune pure `geometry.placement_spread`). Le chiffre qui tranchera la profondeur est le
même qui tranche `auto_ground_calib`.

**UN SEUL flag global `depth_estimation`** porte TOUTE l'amélioration profondeur (décision Fabien
2026-08-05 : les scopes des 5 usages ne se recouvrent pas, des sous-flags par usage pollueraient la
liste ⚑ Modes déjà longue). Pas de `depth_ground_plane`/`depth_reflection`/… : quand le flag est
ON, chaque usage porté s'active.

| Usage [E] | Point d'accroche pipeline | Métrique A/B | État |
|---|---|---|---|
| **4. Re-calage plan de sol** *(PoC #1)* | `store_ground_calib` → `estimate_camera(..., seed=)` (graine profondeur, scoring inchangé) | **#1 `placement_spread`** | ✅ **câblé, BASCULE** (non fumé GPU) |
| **3. Réciproque du pinhole** | `depth_distance_report` (post-tracking) → champ `depth_distance_m` | désaccord médian profondeur↔pinhole / ↔homographie | ✅ **mesure-et-rapport** (non fumé GPU) |
| **1. Reflets** (limite n°7) | `depth_distance_report` : désaccord des `artifact` vs propres | reflet_pinhole_m vs clean_pinhole_m | ✅ **mesure-et-rapport** (non fumé GPU) |
| **5. Ordre d'occlusion** | logique hand-off du tracker | #3 discontinuité au hand-off | ⏳ conception (profondeur ordonnée au hand-off — 2ᵉ passe) |
| **2. Statique vs mobile** | détection stationnés `multicam_tracker.py:405-425` | stabilité classif. statique/mobile | ⏳ conception (exige profondeur COMPENSÉE de l'ego — 2ᵉ passe) |

**Ordre de déroulé** : usage **4 d'abord** (fait, 1ère passe) — il se valide sur `placement_spread`
déjà en place et attaque le biais 23,5 vs 6,8 m qui avait fait débrancher l'homographie ([3]). A/B
**loyal** : `estimate_ground_plane_ph` ne rend QUE le couple candidat `(pitch, hauteur)` ; le
scoring reste dans `estimate_camera` → `placement_spread` calculée à l'identique pour profondeur vs
homographie vs pinhole.

**Câblage effectif (2026-08-05, 1ère passe — 3 ÉTAGES)** :
- **Couche de calcul = briques PURES du tronc commun** (`wama_data/functions/geometry/depth_geometry.py`,
  numpy seul) : `deproject_depth`, `fit_plane_ransac` (RANSAC + raffinement SVD), `plane_pitch_height`,
  `ground_plane_from_depth`, `contact_depth`. Auto-déclarées au **catalogue** (`geometry.depth_ground_plane`,
  `geometry.depth_contact_distance`) + type `DataType.DEPTH_MAP`. **Aucune géométrie dans `utils/`** : la règle
  §3 (logique pure ↦ `common/`, jamais dans une app) est respectée ; pas d'inversion de dépendance.
- **ÉTAGE 1 (ANALYSE, GPU)** — `utils/depth_estimator.run_depth_analysis(session)`, déclenché par la
  **passe `depth`** (`tasks.compute_depth_task` ← `views.dispatch_map['depth']`). UNE inférence Depth Pro
  échantillonnée (≤24 frames/cam, `load`/`estimate_depth` : keep_loaded, `HF_HUB_CACHE` avant import HF, fp16,
  `post_process_depth_estimation`). **STOCKE la donnée brute** : (a) carte downsamplée (long-side ≤384) en
  **float16 `.npz` disque** (`DepthFrame` + `depth_output_dir`, focale **déjà mise à l'échelle de la carte**
  pour une déprojection auto-cohérente) ; (b) profondeur de contact `depth_distance_m` en **champ additif** du
  JSON `DetectionFrame.detections` (calculée à pleine résolution, zéro migration). Catalogue : spec DETECTOR
  `cam_analyzer.depth_analysis` (sortie `DEPTH_MAP` + `detections.depth_distance_m`).
- **ÉTAGE 2 (CALCULS, CPU, re-jouable)** — passe `depth_calc` (`compute_depth_calc_task`) : orchestre les deux
  calculs dérivés. (a) `store_ground_calib(session)` → pour chaque caméra `estimate_ground_plane_ph(session, pos)`
  **relit** `DepthFrame` (`_load_depth_map`), rasterise la zone roulable à l'échelle carte, **DÉLÈGUE**
  déprojection/RANSAC/pitch aux briques pures, applique les gardes physiques rig (hauteur 1–4 m, pitch −10…35°),
  et estampe `source='depth'` dans `ground_calib` (repli homographie si ⚑ OFF/échec). (b) `depth_distance_report(session)`
  = **pure lecture** du champ `depth_distance_m` stocké (usages 3 + 1). **Aucun `import torch/cv2`** → sûrs sous
  WSL2, d'où une passe re-jouable à volonté. Briques déclarées au catalogue `Binding.APP` `cpu_bound`
  (`cam_analyzer.depth_ground_plane`, `cam_analyzer.depth_distance_report`), toutes deux lisant `DEPTH_MAP`.
  Le tracking (`global_tracking`) consomme ensuite la calib pré-stockée (recalcule seulement si la source diffère).
- `homography_estimator.estimate_camera(session, pos, seed=)` : `seed` fourni → score ce couple et
  court-circuite la grille ; `store_ground_calib` lit ⚑ `depth_estimation` (ON → graine profondeur,
  repli grille si échec) et **estampe `source`** (`'depth'`/`'homographie'`) dans `ground_calib[pos]`.
  `tasks.py` déclenche/**recalcule** la calib dès que la **source stockée diffère de la voulue** (plus
  seulement « calib absente ») ; le tracker (`multicam_tracker.py`) consomme la calib sous ⚑ `auto_ground_calib`
  **OU** `depth_estimation`. Console `plan de sol : profondeur | homographie | pinhole`.
- ✅ **Convention de signe du pitch VALIDÉE** (`atan2(nz, -ny)`) par test pur CPU (plan synthétique
  pitch +8,00°/hauteur 1,501 m récupérés, fit direct + round-trip carte de profondeur). Reste à confirmer
  au run la **qualité réelle** de la profondeur Depth Pro (API `transformers` + gain `placement_spread`).
- **Usages 3 + 1 (mesure-et-rapport)** : `depth_estimator.depth_distance_report(session)` est désormais
  **pure lecture** du champ `depth_distance_m` déjà écrit par l'ÉTAGE 1 (plus d'inférence propre : l'ancienne
  passe Depth Pro ad hoc de `_run_global_tracking` est supprimée au profit de la passe `depth` amont).
  **Ne bascule aucune source** : le placement continue de venir du pinhole/homographie. Deux lignes A/B console
  indépendantes — usage 3 : désaccord médian profondeur↔pinhole et ↔homographie (m) ; usage 1 : désaccord des
  détections `artifact` vs propres (un reflet projette une profondeur incohérente). Persisté
  `results_summary['depth_report']`.
- **Usages 2 et 5 différés en 2ᵉ passe** (raison, pas oubli) : la profondeur brute d'un track décroît
  quand la navette approche → statique/mobile (2) exige une profondeur **compensée de l'ego** ;
  l'ordre d'occlusion (5) exige une profondeur **ordonnée au hand-off**. Les deux méritent le run GPU
  de la 1ère passe (qualité Depth Pro confirmée) avant d'être câblés.

**Frontières / coordination (partition multi-instances)** :
- ✅ Tâche `depth-estimation` déclarée (`ModelTask`) — le garde-fou `check_model_taxonomy` passe.
- ✅ **Modèle onboardé via le mécanisme en place (2026-08-05)** : `pull_model apple/DepthPro-hf
  --category vision --family depth-pro` → `model.safetensors` + `config.json` dans
  `AI-models/models/vision/depth-pro/`. `settings.MODEL_PATHS['vision']['depth']` = `depth-pro` ;
  `model_registry._discover_depth_models()` (scan **filesystem**, source `huggingface`, **aucun import
  lab→core**) émet `huggingface:depthpro` (task=depth-estimation, vram 8 Go) ; sélectionnable
  VRAM-aware (8 Go ≤ budget 4090). Ancienne ligne DA3 (pk 226) purgée.
- ✅ **Base live = WSL2** : le `manage.py` Windows résout dynamiquement l'IP WSL2 (`_resolve_db_host`)
  et y écrit **directement** — pas de re-sync WSL2 séparé (croyance « deux bases » corrigée).
- ✅ Protocole banc `depth-estimation` (`bench.py::_bench_depth`) : latence/couverture/médiane/focale
  (grandeurs comparables, pas une note de qualité).
- ⚠ **GPU interdit sous WSL2** sur ce poste : inférence Depth Pro + déprojection + A/B `placement_spread`
  **à fumer côté runtime/R760xa**. Tout import torch/transformers/cv2 du loader est **paresseux** (dans
  les fonctions) pour que `manage.py check`/`py_compile` ne touchent jamais CUDA.

---

## INVENTAIRE EXHAUSTIF des traitements — MESURÉ dans le code au 2026-09-05

> **Pourquoi cette section, et pourquoi ce jour-là.** Le design d'origine (`archive/DISTANCE_DESIGN`,
> `§1quater.7` et son schéma de pipeline) déclarait la **fusion IMU+GPS faite** ; le code ne l'a
> **jamais faite** (`git log -S imu_track` : un seul commit, `89353afd` du 2026-07-09, celui qui a
> créé le champ — aucun ne l'a jamais lu). Une doc qui dit plus que le code fait re-câbler ce qui
> existe et croire fait ce qui ne l'est pas. **Tout ce qui suit a été lu dans la SOURCE** (docstring,
> signature, appelants par `grep`), jamais recopié d'un `.md`. Sert aussi de base aux présentations
> ENA : chaque traitement = entrées → traitement → sorties, dans l'ordre où il s'exécute.
>
> **Vocabulaire d'état** (à reprendre tel quel dans toute ligne de ce doc) :
> **CÂBLÉ** = s'exécute dans la chaîne nominale · **CONDITIONNÉ** = ne s'exécute que sous une condition
> de données/profil (préciser laquelle) · **⚑ OFF** = câblé derrière une bascule à défaut OFF ·
> **MESURE SEULE** = calcule et rapporte, ne modifie aucune donnée consommée · **JAMAIS EXÉCUTÉ** =
> câblé mais aucun run réel (GPU interdit sur le poste) · **DÉCLARÉ-MORT** = champ/drapeau existant
> sans aucun consommateur · **INEXISTANT** = cité par une doc, absent du code.

### A. Chronologie d'exécution — les 13 passes (`AnalysisPass.PassType`) en trois étages

L'ordre est celui de `pass_tracking._DEPENDS_ON` + `views.run_passes` (`dispatch_map`). Étage =
`pass_tracking._STAGE` : **ANALYSE** regarde les pixels (GPU), **CALCUL** dérive des données stockées
(CPU, rejouable sans GPU). Le 3ᵉ étage, **AFFICHAGE**, n'est pas une passe : c'est le JS (§C).

| # | passe | ét. | fonction | entrées | traitement | sorties écrites | état |
|---|---|---|---|---|---|---|---|
| 1 | `extraction` | A | `tasks.extract_rtmaps_task` (3045) → `quadrature_video`, `rtmaps_parser`, `ego_pose.parse_gps_position/parse_accel/annotate_gps_heading_speed` | `.rec` RTMaps + CSV par canal + vidéo quad 800×500 | découpe 4 vues (~384×248 après split) ; GPS NMEA → lat/lon/ts ; **cap = bearing entre fixes, tenu si déplacement < 0,30 m** ; vitesse = distance/temps ; accéléro X/Y/Z fusionnés par ts ; synchro auto `gps_time_scale/offset` | `CameraView`×4, `session.gps_track [{ts,lat,lon,heading,speed_kmh}]`, `session.imu_track [{ts,ax,ay,az}]`, `gps_time_*` | CÂBLÉ — **sauf `imu_track` : écrit, JAMAIS LU** (voir §D.1) |
| 2 | `intersection_windows` | A | `window_recompute.recompute_intersection_windows` | `gps_track` + `profile.intersections [{lat,lon,radius_m}]` | fenêtres temporelles où la navette est à < `radius_m` d'une intersection déclarée ; `bearing_deg` d'entrée | `session.intersection_windows [{t_enter,t_exit,lat,lon,bearing_deg,radius_m}]` | CÂBLÉ (sync, CPU) |
| 3 | `yolo_detect` | A | `tasks.process_session_task` (670) → ultralytics YOLO + BoTSORT ; inline : `lane_partition`, `distance_speed`, `ground_projection` (conditionné), `coverage` | vidéos, `profile.model_path/confidence/iou/tracker`, fenêtres (si `restrict_to_intersection_windows`) | détection+tracking **par caméra** (`track_id` local) ; attribution de voie (avant) ; **distance pinhole** `H_classe·f_y/h_bbox` + vitesse rel./TTC ; homographie sol **si** `profile.geometry_enabled ∧ camera.ground_homography` ; registre de couverture | `DetectionFrame.detections [{bbox,class_name,confidence,track_id,proximity,distance_m,relative_speed_kmh,ttc_s,lane_id,in_shuttle_lane[,ground_xy,dist_*_m,distance_source]}]`, `config.fov_v_used`, `config.analyzed_ranges` | CÂBLÉ ; volet homographie **CONDITIONNÉ** (§D.2) |
| 4 | `yolopv2_lanes` | A | `yolopv2_segmenter` (TorchScript CAIC-AD) | vue avant (4 vues si `yolopv2_all_views`) | zone roulable + lignes de voie → polygones | `detections` type `road_mask` (drivable) et `lane (yolopv2)` | CÂBLÉ |
| 5 | `sam3_markings` | A | `tasks.analyze_sam3_only_task` (2720) → `sam3_road_analyzer.SAM3RoadAnalyzer` ; option `calibrate` → `_auto_calibrate_from_crossings` → `calibration.homography_from_quad` (DLT) → `_reannotate_ground_distances` | frames DANS les fenêtres à `sam3_fps`, prompts texte (`stop_line`, `crossing`, …) | segmentation open-vocab → polygone+bbox par marquage ; **option** : le plus grand polygone `crossing` → 4 coins → homographie DLT (dimensions FR 0,5 m) → écrit `camera.ground_homography` **et force `profile.geometry_enabled=True`**, puis ré-annote `ground_xy` sur tout l'existant | `detections` type `sam3_marking {label,polygon,bbox,confidence}` ; **`camera.ground_homography`** (si calibrate) | CÂBLÉ ; la calibration DLT est **le PRODUCTEUR de la voie « ancienne »** (§D.2) |
| 6 | `depth` (ét. 1) | A | `depth_estimator.run_depth_analysis` (227) — Apple Depth Pro | ≤ 24 frames/caméra + détections | carte métrique + focale estimée ; profondeur au point de contact de chaque bbox | `DepthFrame` (`.npz` float16, `focal_px`), `detections.depth_distance_m` | CÂBLÉ, **JAMAIS EXÉCUTÉ** (crashs hôte) |
| 7 | `lane_events` | C | `tasks._compute_lane_events` (436) | `detections.lane_id` + fenêtres | entrées/sorties de voie par track | `LaneEvent {track_id,lane_id,in_shuttle_lane,t_enter,t_exit,window_idx}` | CÂBLÉ |
| 8 | `temporal_segments` | C | `tasks.detect_temporal_segments` (633) : `_detect_close_following/_overtaking/_crossing/_intersection_insertion` + `intersection_analyzer` | détections + fenêtres + `gps_track` (vitesse) | arrêté→INSERTION/WAIT/TURN (t0/t1/t2, `D0_relative = h_frame/h_bbox`), suivi rapproché, dépassement, traversée | `TemporalSegment {type,start,end,metadata}` | CÂBLÉ |
| 9 | `distance` | C | `tasks.compute_distance_task` (1766) → `distance_speed` | détections stockées (bbox, classe, ts) | **ré-annote** distance/vitesse/TTC avec les FOV V RÉELS, trace `fov_v_used` (→ `dist_scale` = 1) | `detections.distance_m/relative_speed_kmh/ttc_s`, `config.fov_v_used` | CÂBLÉ |
| 10 | `depth_calc` (ét. 2) | C | `tasks.compute_depth_calc_task` (1877) → `depth_estimator.estimate_ground_plane_ph` (RANSAC sur roulable, briques pures `geometry.depth_geometry`), `depth_distance_report` | `DepthFrame` + `road_mask` + `depth_distance_m` | plan de sol → (pitch, hauteur) source `depth` ; désaccord profondeur↔pinhole↔homographie ; confirmation reflets | `config.ground_calib[pos]{source:'depth'}`, `results_summary.depth_report` | CÂBLÉ, **JAMAIS EXÉCUTÉ** (pas de `DepthFrame`) |
| 11 | `global_tracking` | C | `tasks._run_global_tracking` (2359) → `multicam_tracker.annotate_global_tracks` (101) puis `intersection_branches.learn_branches`, `marking_world.aggregate_markings` | détections des caméras analysées, `gps_track`, bascules | **§A.11 ci-dessous** (le cœur) | `detections.global_track_id/world_en/stable_class/artifact` + fantômes `{type:'ghost',predicted,vehicle_xy,world_en}` ; `results_summary.stationary_global_tracks/stationary_anchors/placement_spread/intersection_branches/intersection_markings[/depth_report]` ; `config.ground_calib` (si ⚑) | CÂBLÉ |
| 12 | `indicators` | C | `tasks.compute_indicators_task` (2610) = `_run_global_tracking` **+** `prediction_adapter.annotate_prediction_indicators` (303) | détections + `gps_track` | trajectoire monde par gid (pinhole_ego → véhicule → monde), **moyenne glissante 5 pts**, extrapolation `speed_accel` (défaut) ou `kalman`, pas 0,2 s, horizon 4 s, collision SAT navette↔objet | `detections.prediction_ttc/prediction_pet` | CÂBLÉ — c'est le bouton « Calculer les indicateurs » |
| 13 | `conflicts` | C | `tasks._compute_conflict_events` (518) | fenêtres + détections + `_gps_speed_at` | conflits en voie navette (qui passe premier, Δt, distance min, TTC min, sévérité) | `ConflictEvent` | CÂBLÉ |

**Hors passes (boutons dédiés, panneau Calibration)** : `compute_ortho_recalage_task` (2498, MESURE
SEULE → `results_summary.ortho_recalage`) puis `compute_ortho_correction_task` (2539, ⚑ `ortho_correction`
OFF → `results_summary.ortho_correction` = ancres, appliquées **côté JS seulement**). `live_analysis_task`
(1931) = étape 3 incrémentale au fil de la lecture, puis enchaîne `_run_global_tracking`.

#### A.11 — `annotate_global_tracks` : l'ordre INTERNE (c'est là que se jouent position et cap)

1. **Artefacts** (⚑ `artifact_filter` ON) : `artifact_filter.detect_static_artifacts` — bbox dont le centre
   dérive < 4 px RMS pendant ≥ 10 s alors que la navette a parcouru ≥ 8 m → `artifact:true`, **exclu de
   l'association** ; + `is_giant_reflection` (bbox > 50 % image ∧ conf < 0,55).
2. **Position ego par détection** : si ⚑ `auto_ground_calib` ou ⚑ `depth_estimation` ON **et** calib
   présente → `ground_ego` (projection du bas de bbox, valide **1 < Y < 40 m**, sinon `None`) ; **sinon
   `pinhole_ego`** (rejette bbox coupée `x1 ≤ 8 ∨ x2 ≥ iw−8`). ⚠ Le repli `ground_ego→pinhole` est
   **silencieux** — aucun champ ne dit quelle source a servi (gap **G7**). Bbox coupée : mesure
   **dégradée** (`relaxed`) autorisée UNIQUEMENT pour prolonger une chaîne existante.
3. **Caméra → véhicule** : `cam_to_vehicle(yaw, mount)` — yaw de montage (défauts ±75°/0/180, surcharge
   `config.camera_yaw`), bras de levier (⚑ `mount_lever_arm`).
4. **Véhicule → monde** : `ego_to_world(pose navette)` — pose = `_shuttle_pose_at` : **interpolation
   linéaire** entre fixes (cap : interpolation **circulaire**), après levier d'antenne
   (⚑ `antenna_lever`). Fixes = `effective_gps_track` : **bruts par défaut**, filtrés Kalman+RTS
   si ⚑ `shuttle_filter` ON (calculé en tête de `_run_global_tracking`, §D.1).
5. **Association** plus-proche-voisin en monde : gate `3,5 m + 1,5 m/s·Δt`, trou max **2,5 s**,
   **verrou de chaîne** (un `track_id` caméra apparié garde son gid 4 s), vitesse de track EMA α=0,3,
   rejet > 15 m/s, dégradée : ratio < 0,7 et jamais de création.
6. **Recollement de tracklets** (stitching, trou ≤ 6 s, ≤ 2 s si < 1 m/s) : fin de A ajustée
   linéairement (2,5 s, en excluant 0,5 s de queue corrompue) → début de B à la position prédite.
7. **Stationnés** : ≥ 5 obs ∧ durée ≥ 4 s ∧ étalement < 6 m ∧ étalement/durée < 0,7 m/s ∧ **pas près
   d'une intersection** (`_near_intersection` — un arrêt au feu n'est pas un stationnement).
8. **Ancres** (stationnés) : position = **médiane** des observations ; cap = **consensus axial** du
   ratio l/h sur toute la vie du track (⚑ `anchor_heading`, `_ratio_heading_candidates` +
   `_axial_consensus` pic d'histogramme 5°) ; **prior de cluster** < 15 m (⚑ `heading_cluster`).
9. **Fantômes** (non-stationnés) : interpolation **monde** des trous ≤ 6 s, insérés dans les frames
   `front` (`predicted:true`, `vehicle_xy`, `world_en`, `dist_euclid_m`).
10. **Lissage Kalman + RTS** (`trajectory_smoother.smooth_track`, état `[x,y,vx,vy]`, vitesse constante,
    σa = 2,5, σm = 1,5) — **non-stationnés seulement, ≥ 5 obs, position seule (jamais le cap)** →
    `world_en` par détection.
11. **Classe stable** : vote pondéré par la confiance → `stable_class`.
12. **`placement_spread`** (brique pure `geometry.placement_metrics`) : RMS des positions des stationnés
    autour de leur barycentre — **la métrique A/B** (console + `results_summary`).

### B. Le chemin d'UNE bbox jusqu'à la carte — où chaque correction s'insère

```
bbox pixel (caméra native ~384×248)
 │  [distance]  H_classe·f_y/h_bbox  ·  ×dist_scale (⚑fov_dist_correction)  ·  EMA α=0,35 → vitesse/TTC
 ▼
ego caméra  (latéral = d·(bcx−cx)/f_x  |  OU projection sol ⚑auto_ground_calib / ⚑depth_estimation, 1<Y<40 m, repli pinhole SILENCIEUX)
 │  [véhicule]  rotation yaw montage  ·  + bras de levier (⚑mount_lever_arm)
 ▼
repère véhicule (origine centre arrière ; GPS ramené par levier d'antenne ⚑antenna_lever)
 │  [monde]  + pose navette : GPS BRUT interpolé linéairement, cap bearing-entre-fixes interpolé circulairement
 ▼
monde (est/nord local)
 │  [tracking]  association NN · stationné→ANCRE médiane · mobile→KALMAN+RTS (position)  · fantômes
 ▼
persisté : world_en | stationary_anchors | (rien pour les frames postérieures au dernier calcul)
 │  [affichage JS]  ① ancre  >  ② world_en  >  ③ RECONSTRUCTION par frame : EMA distance α=0,3 + EMA latéral α=0,3
 │                  cap objet : trace (EMA 0,25, MAJ si >0,8 m) ⊕ ratio bbox (⚑heading_ratio, poids (2−v)/2)
 │                  cap navette : moyenne circulaire ±2 fixes (JS seul)  ·  ortho ⚑ortho_correction (JS seul)
 ▼
mini-carte
```

Ce schéma dit **où** une erreur entre et **jusqu'où** elle se propage : tout ce qui est en amont
de « monde » est repris par le tracking ; tout ce qui touche la **pose navette** contamine
**toutes** les détections d'une même frame, et n'est corrigé nulle part.

### C. Inventaire EXHAUSTIF des LEVIERS de correction (43 relevés)

> C'est la liste que la « fusion de données » (§E) devra consommer. **Colonne ⚑** : `⚑ nom` = bascule
> déclarée dans `utils/features.py` ; `—` = codé en dur (un `if` ou une constante, **non comparable**
> A/B aujourd'hui) ; `param` = paramètre de fonction sans surface UI. **Colonne mesure** : la métrique
> objective qui permettrait de trancher — « aucune » veut dire que le levier n'a jamais été jugé que
> visuellement.

| # | levier | grandeur corrigée | source de données | où | ⚑ | état | mesure A/B |
|---|---|---|---|---|---|---|---|
| **Distance / vitesse (par caméra, étage ANALYSE et passe `distance`)** ||||||||
| 1 | pinhole hauteur de classe | distance | bbox + `CLASS_REAL_HEIGHT_M` | `distance_speed.pinhole_distance` | — | CÂBLÉ | référence de tout le reste ; ±20 % (jitter 1 px) |
| 2 | EMA α=0,35 + clamp de saut + régression 0,6 s + rejet > 130 km/h | vitesse rel., TTC | `distance_m` interne | `distance_speed.TrackKinematics` | — | CÂBLÉ | aucune |
| 3 | correction FOV V rétroactive `dist_scale = tan(used/2)/tan(réel/2)` | distance stockée | `config.fov_v_used` vs FOV réel | `prediction_adapter.camera_geometry` (+ miroir JS) | ⚑ `fov_dist_correction` ON | CÂBLÉ | ×3,6 latéral mesuré à l'audit 07-16 |
| 4 | focale **horizontale** réelle pour le latéral | latéral | `CAMERA_FOV_H` | `pinhole_ego` / JS 3206 | — | CÂBLÉ | compression ×1,6 corrigée (audit) |
| 5 | rejet bbox coupée (`x1 ≤ 8 ∨ x2 ≥ iw−8`) | latéral/cap | bbox | `pinhole_ego`, JS 3227 | — | CÂBLÉ | aucune |
| 6 | point de contact **masque** `seg_ground_px` | latéral | polygone de segmentation | `segmentation_bridge.mask_ground_point` → JS 3178 | — | CÂBLÉ si source segmentation | aucune |
| **Géométrie caméra → véhicule** ||||||||
| 7 | yaw de montage par caméra | latéral (sin Δyaw·d) | défauts rig + `config.camera_yaw` (bouton 🧭) | `camera_yaw_map` | manuel | CÂBLÉ | hand-off inter-caméras (qualitatif) |
| 8 | bras de levier de montage `CAMERA_MOUNT` | position (4,5 m avant) | rig | `camera_geometry` | ⚑ `mount_lever_arm` ON | CÂBLÉ | aucune |
| 9 | levier d'antenne GPS (coin arrière droit, 1 m) | tout le repère | `config.gps_antenna` | `antenna_offset`, `shuttle_trajectory`, JS `antennaCorrect` | ⚑ `antenna_lever` ON | CÂBLÉ | 1,00 m mesuré |
| **Pose navette (étage EXTRACTION + consommation)** ||||||||
| 10 | cap = bearing entre fixes, **tenu** si < 0,30 m | cap ego | GPS brut | `ego_pose.annotate_gps_heading_speed` | — | CÂBLÉ | ±10-25° à basse vitesse (`§[2]`) — **source d'erreur angulaire dominante** |
| 11 | moyenne circulaire du cap sur ±2 fixes | cap ego (affichage) | `cachedGpsTrack.heading` | **JS seul** `index.js:2940`, `2998` | — | CÂBLÉ (JS) | aucune |
| 12 | interpolation **circulaire** du cap entre fixes | cap ego (calcul) | `shuttle_traj` | `_shuttle_pose_at` | — | CÂBLÉ | wrap 359→1° corrigé |
| 13 | interpolation **linéaire** de la position entre fixes (~2,7 s) | position ego | GPS brut | `_shuttle_pose_at`, JS | — | CÂBLÉ | aucune |
| 14 | synchro GPS↔vidéo `scale/offset` | temps | `.rec` | `extract_rtmaps_task` + réglage manuel | manuel | CÂBLÉ | aucune |
| 15 | **filtre de Kalman + RTS sur la navette**, cap dérivé de la vitesse lissée (tenu < 1 m/s) | position/vitesse/cap ego | `gps_track` | `driving.ego_trajectory_filter` (pur) → `ego_pose.compute_shuttle_filter` → `effective_gps_track` (serveur, 6 consommateurs) + `_applyShuttleFilter` (JS) | ⚑ `shuttle_filter` **OFF** | **LIVRÉ 2026-09-05** (était INEXISTANT le matin même) ; pas d'accéléro en commande (axes non mesurés) | rapport : déplacement RMS, écart de cap médian, part tenue ; puis `placement_spread` OFF/ON |
| 16 | **fusion accéléromètre + GPS** | position/vitesse ego | `session.imu_track` (stocké) | **nulle part** — `EgoPose.accel` assigné jamais relu ; `profile.use_imu` (défaut True) **0 consommateur** | — | **DÉCLARÉ-MORT** depuis 2026-07-09 | — |
| **Position au sol (l'ANGLE)** ||||||||
| 17 | homographie sol par **DLT sur passage piéton SAM3** (« ancienne voie ») | distance/latéral (`ground_xy`, `dist_*_m`) | polygone `crossing` + dimensions FR | `calibration.homography_from_quad` ← `tasks._calibrate_from_crossing_polygons` → `camera.ground_homography` ; appliqué par `GroundProjector.distances_for_bbox` dans l'analyse | `profile.geometry_enabled` (défaut **False**, **forcé True par la calibration SAM3**) | **CONDITIONNÉ** — prouvée biaisée (#546, #537), mais **toujours productible et consommée** (§D.2) | RMS de reprojection du quad seulement |
| 18 | pitch/hauteur auto par **étalement des stationnés** (2a) | angle → position | stationnés d'un run précédent + `distance_m` + ego GPS (ancre) | `homography_estimator.estimate_camera/store_ground_calib` → `ground_projector_for` → `ground_ego` | ⚑ `auto_ground_calib` **OFF** | ⚑ OFF ; garde-fous : ≥ 6 objets, étalement ≤ 2,5 m ; **repli pinhole silencieux (G7)** | `placement_spread` ; désaccord 14,55 → 3,05 m (caméra avant) |
| 19 | plan de sol par **profondeur monoculaire** (Depth Pro, RANSAC) | angle → position | `DepthFrame` + `road_mask` | `depth_estimator.estimate_ground_plane_ph` → `store_ground_calib(seed)` | ⚑ `depth_estimation` **OFF** | **JAMAIS EXÉCUTÉ** | `placement_spread` (même scoring que 18) |
| 20 | **cross-check** distance profondeur ↔ pinhole ↔ homographie | (contrôle) | `depth_distance_m` | `depth_estimator.depth_distance_report` | ⚑ `depth_estimation` | MESURE SEULE, JAMAIS EXÉCUTÉ | désaccord médian (m) |
| 21 | recalage **absolu** ortho 2b (SAM3 sur orthophoto IGN vs crossings caméra) | position absolue | tuiles WMTS z19 + `intersection_markings` | `ortho_markings` → `compute_ortho_recalage_task` | bouton | MESURE SEULE | offset par intersection (2,93 E / 4,2 N m mesurés) |
| 22 | **correction** de trajectoire par ancres ortho, biais caméra écarté, atténuée par masque de ciel BD TOPO | position GPS | `results_summary.ortho_correction` + `geo.ign_vector.sky_mask` | `driving.trajectory_offset` (pur) → `compute_ortho_correction_task` ; **appliqué côté JS** (`_applyOrthoCorrection` au point d'ingestion de la trace) | ⚑ `ortho_correction` **OFF** | ⚑ OFF | rapport chiffré (décalage moyen/max, atténuation) |
| **Tracking 360° (étage CALCUL)** ||||||||
| 23 | filtre artefacts **cinématique** (bbox fixe ≥ 10 s, navette ≥ 8 m) + reflet géant | faux positifs | bbox + trajectoire navette | `artifact_filter` | ⚑ `artifact_filter` ON | CÂBLÉ | 91 artefacts marqués (run 07-19) |
| 24 | association NN gate croissant `3,5 + 1,5·Δt` m, trou 2,5 s | identité | positions monde | `annotate_global_tracks` | param | CÂBLÉ | aucune (hand-off qualitatif) |
| 25 | **verrou de chaîne** (4 s) | identité | `(caméra, track_id)` | idem | — | CÂBLÉ | 6 gids → 1 sur #166 (audit) |
| 26 | vitesse de track EMA α=0,3 + rejet > 15 m/s | prédiction de gate | positions | idem | — | CÂBLÉ | aucune |
| 27 | mesure **dégradée** (bbox coupée) pour prolonger seulement | continuité au dépassement | bbox | idem | — | CÂBLÉ | G432 (qualitatif) |
| 28 | recollement de tracklets (≤ 6 s ; ≤ 2 s si lent) | identité | extrémités ajustées | idem | — | CÂBLÉ | aucune |
| 29 | qualification **stationné** (≥ 5 obs, ≥ 4 s, < 6 m, < 0,7 m/s, hors intersection) | statique/mobile | `track_hist` | idem | param `spread_max_m` | CÂBLÉ | aucune ; **un garé PRÈS d'une intersection n'est jamais stationné** |
| 30 | **ancre** = médiane des positions | position des garés | `track_hist` | idem | — (structurel) | CÂBLÉ | `placement_spread` (mesure la dispersion qu'elle résume) |
| 31 | cap serveur par **consensus axial** du ratio l/h | cap des garés | bbox non coupées + **cap navette** | `_ratio_heading_candidates`, `_axial_consensus` | ⚑ `anchor_heading` ON | CÂBLÉ | 31/31 ancres avec cap (07-19) |
| 32 | **prior de cluster** (voisins < 15 m, soi ×2) | cap des garés | ancres voisines | idem | ⚑ `heading_cluster` ON | CÂBLÉ | aucune |
| 33 | **fantômes** interpolés en monde (trous ≤ 6 s) | continuité | `track_hist` | idem | — (affichage : bouton Prédiction) | CÂBLÉ | trou G242 comblé (18 fantômes) |
| 34 | **Kalman + RTS** (σa 2,5 / σm 1,5, vitesse constante) | position des **mobiles** | `track_hist` | `trajectory_smoother.smooth_track` → `world_en` | — | CÂBLÉ — **exclut les stationnés, position seule** | aucune |
| 35 | classe stable (vote pondéré) | gabarit | `class_name`×`confidence` | idem | — | CÂBLÉ | aucune |
| **Affichage (JS, repli ③ et cap)** ||||||||
| 36 | **EMA distance α=0,3** en repli ③ | distance affichée | `distance_m` | `index.js:3191` | — | CÂBLÉ (JS) | aucune — ⚠ **retard de phase**, hypothèse §D.3 |
| 37 | EMA latéral α=0,3 en repli ③ | latéral affiché | `bcx` | `index.js:3210` | — | CÂBLÉ (JS) | aucune |
| 38 | zone fiable `0 < Y ≤ 60 ∧ |X| ≤ 25` (repli ③ seul) | faux positifs lointains | position ego | `index.js:3218` | — | CÂBLÉ (JS) | aucune |
| 39 | cap objet = direction de trace, EMA 0,25, MAJ si déplacement > 0,8 m, **figé** si stationné | cap des mobiles | trail lat/lon | `index.js:3292-3310` | — | CÂBLÉ (JS) | aucune |
| 40 | cap **ratio de bbox** fondu avec la trace, poids `(2−v)/2` | cap des lents | bbox + cap navette | `index.js:3325-3390` | ⚑ `heading_ratio` ON | CÂBLÉ (JS) | aucune ; limite : écrête ~68° |
| 41 | interpolation des marquages SAM3 entre keyframes | rendu marquages | `sam3_marking` | `index.js:2045-2128` | ⚑ `sam3_interp` ON | CÂBLÉ (JS) | aucune |
| **Structure & indicateurs** ||||||||
| 42 | branches apprises du trafic (rectitude, ≥ 4 véh., span ≥ 14 m) / marquages SAM3 agrégés en monde (2-12 m) | géométrie d'intersection | `world_en` / `sam3_marking` + `GroundProjector` (`ground_homography` **si présent**, sinon pitch 0) | `intersection_branches`, `marking_world` | ⚑ `learned_branches`, ⚑ `world_markings` ON | CÂBLÉ ; **aucune vérité terrain** (→ `geo.osm_control_nodes`, 2026-09-04) | aucune |
| 43 | moyenne glissante 5 pts + extrapolation `speed_accel`\|`kalman` + SAT | TTC/PET | trajectoires monde | `prediction_adapter.smooth_trajectory`, `ttc_pet_shuttle_object`, `kinematics.extrapolation` | param `method` | CÂBLÉ | aucune |

**Déclaré, jamais implémenté** : ⚑ `track_speed_unified` (défaut OFF, 0 consommateur — le CHANGELOG le dit).
**Non câblé, mesurable** : `geometry.ego_rotation` (rotation caméra par flux de points, 2026-09-04) —
la seule 2ᵉ source de cap possible (levier 10 n'a aucun contradicteur) ; `geo.osm_control_nodes` —
la seule vérité terrain possible pour le levier 42.

**Ce que la liste révèle, en trois lignes.** (i) **13 des 43 leviers sont déclarés en ⚑**, les
30 autres sont des constantes : ils ne se comparent pas. (ii) **Un seul levier touche la pose
navette** (le 11, en JS, sur le cap seul) alors que le §B montre qu'elle contamine tout. (iii) **Un
seul chiffre A/B existe** (`placement_spread`) et il juge une configuration ENTIÈRE, jamais un
levier isolé — c'est ce que §E doit changer.

### D. Trois affirmations RÉFUTÉES par la lecture (la doc disait plus que le code)

**D.1 — « Fusion IMU + GPS pour l'ego-pose »** (`Décisions actées §7`, schéma du design, `ego_pose.py`
en-tête « GPS + accéléromètre (fallback) ») : **JAMAIS FAITE.** L'accéléromètre est parsé (3 CSV
→ `{ts,ax,ay,az}` en g), stocké (`session.imu_track`), annoncé en console — et **aucune ligne ne le
lit**. `EgoPose.__init__` l'assigne à `self.accel`, aucune méthode ne s'en sert. `profile.use_imu`
(défaut True, libellé « Fusionner l'accélérométrie… ») est une case UI **sans effet**. Le Kalman+RTS
n'a **jamais** été appliqué à la navette : un seul appelant, sur les objets mobiles, position seule.
La navette roule sur GPS brut interpolé linéairement. *Conséquence : avant tout re-câblage, savoir
que c'est un TROU et pas une régression — rien n'a été retiré.*
**Asymétrie à connaître** : le seul lissage du cap navette (moyenne circulaire ±2 fixes) vit dans le
JS, donc ne sert que le repli d'affichage ③ ; tout ce que le SERVEUR calcule (`world_en`, ancres,
TTC/PET, calibration 2a) hérite du cap brut à ±10-25°. Le chemin le mieux corrigé est le chemin de
secours. ⚠ Aucun ⚑ ne porte sur la pose navette (vérifié `features.py` : 14 bascules, zéro sur le
GPS) — c'est le premier trou à combler, derrière un ⚑ `shuttle_filter`.

**D.2 — « Ancienne voie (homographie SAM3) débranchée »** (`§[4]`) : **CONDITIONNÉE, pas débranchée.**
`process_session_task` l'applique dès que `profile.geometry_enabled ∧ camera.ground_homography`
(l. 1274-1292, 1383-1392) et écrit `distance_source='homography'`. Or la calibration SAM3
(`_calibrate_from_crossing_polygons`, l. 2272-2274) **force `geometry_enabled=True`** et
`analyze_sam3_only_task` l'appelle avec `calibrate`. `marking_world._projector_for` l'utilise
**sans condition** dès que `ground_homography` existe (`calibrated:true`), et `lane_estimator` en
dépend. Une session qui a lancé « Calib. SAM3 » remet donc en service une voie **prouvée biaisée**
(#546 inversion de signe, #537 profondeur non monotone).
*Périmètre RÉEL de l'impact (corrigé 2026-09-05 — la 1ʳᵉ rédaction disait « le tracker ne
l'ignore pas », c'était FAUX) : `multicam_tracker` lit `config.ground_calib` (2a) et `pinhole_ego`,
jamais `camera.ground_homography` ni `ground_xy` ; le JS ne lit `ground_xy` que si `distance_m`
est absent (l. 3215). Les consommateurs effectifs sont : l'analyse (écrit `ground_xy`/`dist_*_m`,
exploités par le seul export), **`marking_world`** (position des MARQUAGES sur la carte) et
**`lane_estimator`** (largeur de voie). Impact réel mais ÉTROIT : marquages et gabarit, pas les
véhicules.* Le switch que l'utilisateur connaît, ⚑ `auto_ground_calib`, porte sur 2a et est câblé
de bout en bout — pas sur cette voie, qui n'a AUCUN ⚑ (gouvernée par `profile.geometry_enabled`).

**D.3 — Les garés qui « suivent la navette puis se décrochent » (constat Fabien 2026-09-05) —
HYPOTHÈSE, à mesurer.** En repli ③ (frames postérieures au dernier calcul, OU véhicule non
qualifié stationné — cf. levier 29, notamment **près d'une intersection**), la distance affichée est
une **EMA α=0,3** (levier 36). Une EMA échange du jitter contre du **retard de phase** : pour un
garé que la navette approche, la distance lissée reste trop grande → l'objet est posé trop loin
devant → il **avance avec la navette**, plus lentement ; quand elle ralentit ou le dépasse, l'EMA
rattrape → il **se stabilise**. Phénoménologie identique au constat ; l'état **mixte** (certains
fixes, d'autres qui dérivent) = hiérarchie ① ancre / ② `world_en` / ③ repli. **Test objectif, sans
GPU** : relever les gids qui dérivent, vérifier s'ils ont une ancre ou un `world_en`. Tous en ③ ⇒
confirmé. *Le Kalman+RTS a été écrit « sans retard de phase » précisément pour remplacer ça — mais
il ne s'applique qu'après calcul, et jamais aux stationnés.*

### E. Vers la FUSION de données — ce que la liste §C rend possible (cadre, PAS un chantier ouvert)

La doctrine actuelle est **comparer** (⚑ ON/OFF, un chiffre). Fabien vise **fusionner** : accumuler
les leviers comme des sources calculées, les combiner, garder le ON/OFF par levier pour mesurer
gain ou dégradation. Le §C montre ce qui manque, et ce n'est ni la provenance ni le stockage :

1. **L'incertitude.** Aucun levier ne dit *à quel point* il est sûr. `placement_spread` note une
   configuration, pas une estimation. Sans σ, fusionner = poser des poids arbitraires = un réglage
   caché de plus. Chaque levier doit devenir un **modèle de mesure** : « j'estime G, je vaux ±σ, dans
   ce domaine de validité ». Ex. levier 1 : σ ∝ d², invalide si bbox tronquée ou `H_classe`
   inconnue ; levier 40 : σ explose vers 68° ; levier 19 : σ croît fort au-delà de 15-20 m (`§[E]`).
2. **Le critère fusion / contrôle** n'est pas la qualité, c'est l'**indépendance**. Fusion ⟸ mesures
   indépendantes et non biaisées ; **confrontation** ⟸ mesures corrélées ou porteuses d'un biais
   systématique. Leviers 1 et 40 viennent de **la même bbox** : ils se confrontent, jamais ne se
   fusionnent. GPS et vision sont indépendants : ils se fusionnent. Le recalage 2b **écarte** le
   biais caméra (médiane) au lieu de le fusionner — c'est déjà la bonne règle, appliquée une fois.
3. **La provenance d'une VALEUR** n'existe qu'à un endroit : `distance_source ∈ {homography,
   pinhole}` par détection — et G7 dit qu'elle est incomplète (le repli `ground_ego→pinhole` n'écrit
   rien). `binding pure|app` décrit la **fonction**, pas la donnée. La généralisation est une facette
   sur les sorties existantes (`PortSpec` : grandeur, σ, domaine), **pas un 9ᵉ registre**.
4. **Le risque de dégradation est réel et a deux noms** : le **biais** (un levier biaisé tire la
   fusion au lieu de s'annuler — `H_classe` d'une camionnette, l'erreur FOV ×3,6) et la
   **corrélation** (N leviers issus de la même source = illusion de N confirmations). D'où : gain
   probable **uniquement mesuré levier par levier** — la règle `§2a` (« la bascule ne conclut rien,
   la métrique conclut ») étendue à chaque levier.
5. **« Calculer, stocker, basculer sans recalculer »** est déjà le patron (profondeur : ANALYSE →
   CALCULS → AFFICHAGE, décision 2026-08-05) et c'est le **seul** qui rende la fusion praticable :
   chaque levier stocke son estimation une fois, la fusion est un calcul CPU rejouable, une bascule
   ne rejoue que la fusion — sinon comparer 10 leviers = 2¹⁰ ré-analyses.

Ordre de travail retenu (Fabien, 2026-09-05) : **inventaire (cette section) → filtrage navette
(§D.1, après le test §D.3) → facette estimateur (§E.1/3) → fusion.**

### F. Les modèles IA de la chaîne (chronologie, ce qu'ils apportent)

| ordre | modèle | passe | entrée | sortie | apport à la vue de dessus | état |
|---|---|---|---|---|---|---|
| 1 | **YOLO** (ultralytics, `profile.model_path`) + **BoTSORT** | `yolo_detect` | frame | bbox, classe, confiance, `track_id` par caméra | l'objet et sa hauteur (→ distance) ; l'identité locale (→ tracking) | CÂBLÉ |
| 2 | **YOLOPv2** (TorchScript, CAIC-AD) | `yolopv2_lanes` | frame avant (ou 4) | polygones zone roulable + lignes de voie | voie de la navette et des objets ; masque roulable pour le plan de sol profondeur | CÂBLÉ |
| 3 | **SAM3** (prompts texte) | `sam3_markings` | frames dans les fenêtres | polygones `stop_line`/`crossing` | bornes d'intersection en monde ; amers du recalage ortho ; **et** homographie DLT (§D.2) | CÂBLÉ |
| 4 | **SAM3 sur orthophoto IGN** | bouton recalage | tuiles WMTS z19 | crossings géoréférencés | l'échelle/position **absolue** que 2a ne donne pas | MESURE SEULE |
| 5 | **Apple Depth Pro** | `depth` / `depth_calc` | frames échantillonnées | carte métrique + focale | plan de sol (angle) sans stationnés ; 3ᵉ source de distance ; discriminant reflets | **JAMAIS EXÉCUTÉ** |
| 6 | **NVIDIA LocateAnything-3B** (détection open-vocab) | — | — | — | amers élargis pour 2b (lignes d'arrêt, flèches, îlots) ; auto-labeling | **poids présents, capacité absente** (`capabilities={}`, `backend_ref` vide, PoC seul) — licence non-commerciale |

---

## Conception & justification (design — absorbé de l'ex-`DISTANCE_DESIGN`)

> Raisonnement fondateur du chantier distances/vue-de-dessus. **Générique** (méthode, pas valeurs) ;
> les valeurs ENA_CASA sont dans `projects/ENA_CASA.md`. L'ancien doc est archivé.

### Décisions actées
1. **Option B (homographie sol)** comme méthode cible de distance, avec **fallback pinhole + lissage**
   quand la géométrie n'est pas calculable ou désactivée.
2. **Une primitive unifie tout** : projeter le **point-sol** de l'objet (centre-bas de bbox, supposé
   au sol) par l'homographie `H` (image→plan-sol) → position `(X, Y)` dans le repère navette. Distance,
   vitesse, TTC, vue de dessus et filtrage stationnés en découlent.
3. **`H` est constante par caméra** (montage rigide + sol plan) → les marquages **accumulent des
   correspondances dans le temps** pour estimer **une seule `H` stable** (auto-calibration en ligne),
   pas une `H` par frame.
4. **Sources hiérarchisées + confrontation** (chaque source émet `(valeur, confiance)`) : calibration
   utilisateur > lignes de voie (YOLOPv2) > passages piétons (SAM3) > **pinhole + lissage** (dernier
   recours, jamais faux « d'un coup »). Désaccord fort lignes⟷pinhole → segmentation douteuse → fallback.
5. **La calibration précise n'est PAS requise** : `H` estimée depuis les lignes **absorbe intrinsèques
   + extrinsèques**. L'échelle métrique vient des marquages (largeur voie + période pointillés, défauts
   normes FR). Seule contrainte : une caméra fisheye doit être **redressée d'abord**.
6. **Toutes les références métriques et dimensions sont surchargeables au profil** (idéalement mesurées).
7. **Fusion IMU (accéléromètre) + GPS** pour l'ego-pose : améliore vitesse propre et trajectoire, donne
   le tilt (pitch/roll via gravité). **N'apporte PAS le cap** (pas de gyro) → cap = course GPS en
   mouvement, tenu au dernier connu à l'arrêt.
   ⚠ **DÉCISION NON APPLIQUÉE** (mesuré 2026-09-05) : le design la déclarait faite (schéma
   `GPS + IMU ──▶ ego_pose.py (fusion)`), le code l'a **préparée** (parse + stockage + `use_imu`) et
   **jamais câblée**. C'est une intention, pas un état — voir §INVENTAIRE D.1 et levier 16.
8. **Vue de dessus** = tracé des `(X, Y)` autour d'une silhouette navette dimensionnée (profil).
9. **Filtrage véhicules d'intérêt** — règle `of_interest` (implémentée, non destructive) : chaque
   segment d'intersection est tagué `of_interest = (event_type ∈ {insertion, wait}) ET (classe ∈
   ROAD_USER_CLASSES)`. Les `turn` (traversée sans interaction) et faux positifs COCO → masqués par
   défaut (bascule « Afficher tout »). Mesuré P97 : 130 segments → 5 d'intérêt.

### L'insight fondateur (2 inconnues, 2 sources — ne jamais confondre)
- **L'ANGLE (tangage/roulis)** se récupère par le **MOUVEMENT seul**, sans vérité terrain (un objet
  statique vu à plusieurs distances doit se projeter au même point monde ; ego-motion GPS = ancre).
  Contraint fortement l'angle mais **aveugle à l'échelle**.
- **L'ÉCHELLE ABSOLUE** exige des objets de **géométrie connue au sol** (passages ~50 cm, lignes à
  intervalles normalisés) = mètres-étalons. Le mouvement ne peut PAS la déduire (limite mathématique).

### Terminologie distances (actée)
- `dist_longitudinal_m` = **Y** (projection instantanée sur l'axe navette).
- `dist_lateral_m` = **X** (écart latéral).
- `dist_euclid_m` = **‖(X, Y)‖** (distance directe / euclidienne — préféré à « rectiligne »).
