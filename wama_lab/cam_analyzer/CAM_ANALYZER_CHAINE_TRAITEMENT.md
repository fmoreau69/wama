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

Dernière mise à jour : 2026-07-21.

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
  : 23,5 m pinhole vs 6,8 m homographie) → **débranchée** ; ne subsiste que sous `profile.geometry_enabled`.
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

Lancé par « Calculer les indicateurs par prédiction » (`annotate_prediction_task`).

- Association frame par frame en repère monde : gate prédictif `pe = e + ve·dt` (gate 3,5 m,
  gap max 1 s). **Vitesse de track lissée EMA α=0.3 + rejet des mesures >15 m/s** (le delta
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

**Câblage effectif (2026-08-05, 1ère passe)** :
- **Couche de calcul = briques PURES du tronc commun** (`wama/common/data/functions/geometry/depth_geometry.py`,
  numpy seul) : `deproject_depth`, `fit_plane_ransac` (RANSAC + raffinement SVD), `plane_pitch_height`,
  `ground_plane_from_depth`, `contact_depth`. Auto-déclarées au **catalogue** (`geometry.depth_ground_plane`,
  `geometry.depth_contact_distance`) + type `DataType.DEPTH_MAP`. **Aucune géométrie dans `utils/`** : la règle
  §3 (logique pure ↦ `common/`, jamais dans une app) est respectée ; pas d'inversion de dépendance.
- `utils/depth_estimator.py` = **orchestration couplée-session** seule : `load`/`estimate_depth`
  (keep_loaded, `HF_HUB_CACHE` avant import HF, fp16, `post_process_depth_estimation`),
  `estimate_ground_plane_ph` (décode les frames roulables → **DÉLÈGUE** déprojection/RANSAC/pitch aux briques
  pures, applique les gardes physiques rig), `depth_distance_report`. Déclaré au catalogue en `Binding.APP`
  (`cam_analyzer.depth_ground_plane`, `cam_analyzer.depth_distance_report`).
- `homography_estimator.estimate_camera(session, pos, seed=)` : `seed` fourni → score ce couple et
  court-circuite la grille ; `store_ground_calib` lit ⚑ `depth_estimation` (ON → graine profondeur,
  repli grille si échec) et **estampe `source`** (`'depth'`/`'homographie'`) dans `ground_calib[pos]`.
  `tasks.py` déclenche/**recalcule** la calib dès que la **source stockée diffère de la voulue** (plus
  seulement « calib absente ») ; le tracker (`multicam_tracker.py`) consomme la calib sous ⚑ `auto_ground_calib`
  **OU** `depth_estimation`. Console `plan de sol : profondeur | homographie | pinhole`.
- ✅ **Convention de signe du pitch VALIDÉE** (`atan2(nz, -ny)`) par test pur CPU (plan synthétique
  pitch +8,00°/hauteur 1,501 m récupérés, fit direct + round-trip carte de profondeur). Reste à confirmer
  au run la **qualité réelle** de la profondeur Depth Pro (API `transformers` + gain `placement_spread`).
- **Usages 3 + 1 (mesure-et-rapport)** : `depth_estimator.depth_distance_report(session)` — UNE seule
  passe Depth Pro échantillonnée (≤12 frames, partagée par les deux usages), appelée en fin de
  `_run_global_tracking` sous le même flag. Écrit le champ **additif** `depth_distance_m` (profondeur
  au contact-sol de la bbox) et **ne bascule aucune source** : le placement continue de venir du
  pinhole/homographie. Deux lignes A/B console indépendantes — usage 3 : désaccord médian
  profondeur↔pinhole et ↔homographie (m) ; usage 1 : désaccord des détections `artifact` vs propres
  (un reflet projette une profondeur incohérente). Persisté `results_summary['depth_report']`.
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
