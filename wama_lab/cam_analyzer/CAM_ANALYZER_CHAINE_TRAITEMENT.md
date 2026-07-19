# Cam Analyzer — Chaîne de traitement de bout en bout

> **But** : document de référence expliquant TOUTE la chaîne, de la vidéo brute aux
> indicateurs d'intersection — étape par étape, avec les formules, les fichiers, les
> paramètres de calibration et les limites connues.
> **Voir aussi** : [`CAM_ANALYZER_CHANGELOG.md`](CAM_ANALYZER_CHANGELOG.md) (traçabilité de
> toutes les modifications, avec procédure d'annulation), `CAM_ANALYZER_DISTANCE_DESIGN.md`
> (design distances), `CONTEXT.md` (contexte métier), `docs/AUDIT_CAM_ANALYZER_VUE_DE_DESSUS_2026-07-15.md`.

Dernière mise à jour : 2026-07-16.

---

## Vue d'ensemble

```
vidéos 4 caméras (RTMaps)          données véhicule (RTMaps)
        │                                   │
   [1] Analyse par caméra              [2] Piste GPS + capteurs
   YOLO+ByteTrack, YOLOPv2, SAM3       (ego_pose.py : cap = bearing entre fixes)
        │                                   │
   [3] Distances & vitesses (pinhole)       │
   [4] (Homographie sol — DÉBRANCHÉE)       │
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

## [4] Homographie sol — `ground_projection.py` — ⚠ DÉBRANCHÉE de la vue de dessus

Calibrée depuis les passages piétons SAM3 (dimensions normées). Écrit `dist_longitudinal_m`,
`dist_lateral_m`, `ground_xy` sur les détections. **État 2026-07-16 : calibration prouvée
cassée sur les données réelles** — latéral avec inversions de signe (#546 : centre bbox à
gauche de l'axe, X homographie +1,74 m) et profondeur non monotone (#537 : 23,5 m pinhole
vs 6,8 m homographie). La vue de dessus n'utilise PLUS ces champs. ⚠ Piège : l'extraction
debug affiche `dist_long` (homographie), l'UI affiche `distance_m` (pinhole).
**Chantier ouvert** : recalibration multi-frames (passages piétons + lignes centrales).

## [5] Repère caméra → véhicule — `prediction_adapter.py`

`camera_geometry(session)` = **source unique** de la géométrie par caméra
(défauts rig ENA surchargés par `session.config`) :

| Paramètre | Défauts rig | Surcharge session | Rôle |
|---|---|---|---|
| `yaw` | front 0°, right **75°**, rear 180°, left **−75°** | `config['camera_yaw']` (bouton 🧭 Yaw) | orientation de montage |
| `fov_h` | 110/55/110/55° | — | focale latérale `f_x = iw/(2·tan(FOV_H/2))` |
| `dist_scale` | `tan(fov_v_used/2)/tan(fov_v_réel/2)` | `config['fov_v_used']` (écrit par l'analyse) | correction des distances annotées avec un ancien FOV |
| `mount` | front (0, +4.5), sides (±1.0, +3.4), rear (0,0) | `config['camera_mount']` | bras de levier (origine = **antenne GPS, à l'ARRIÈRE du toit**) |

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

### Chantier : analyse incrémentale par complétion (design 2026-07-18, non implémenté)

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
| `camera_yaw` | bouton 🧭 Yaw (vue de dessus) | [5] backend + [9] JS |
| `camera_mount` | (manuel, pas d'UI) | [5] backend + [9] JS |
| `fov_v_used` | l'analyse ([1]) | `dist_scale` [5]/[9] |
| `gps_time_offset/scale` | UI synchro | [2] |

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
| `mount_lever_arm` | ON | live | bras de levier des caméras (antenne GPS arrière) |
| `heading_ratio` | ON | live | cap par ratio de bbox fondu avec la trajectoire |
| `track_speed_unified` | OFF | compute | (chantier) vitesse/distance monde uniques par track |

## Limites connues / chantiers ouverts

1. **Unification distance/vitesse par track** (bascule `track_speed_unified`, à
   implémenter) : servir sur chaque détection la position/vitesse MONDE du
   `global_track_id` (tracker [7], `ve/vn` lissés) au lieu des valeurs par-caméra —
   une seule vérité par véhicule sur toutes les vues, améliore distance/vitesse/TTC
   génériquement.
2. **Cap par cluster de stationnés** (générique, pas de cas codé en dur) : l'axe de
   stationnement est APPRIS des véhicules eux-mêmes — moyenne AXIALE des caps ratio des
   stationnés voisins utilisée comme *prior* pondéré (pas contrainte dure). Épi,
   bataille, créneau émergent naturellement du cluster. Même levier que l'EMA
   temporelle, appliqué spatialement.
3. **YOLO-OBB** (boîtes orientées natives) : l'orientation devient une mesure — poids
   publics entraînés sur imagerie aérienne, fine-tuning nécessaire → long terme.
   **Raccourci disponible : exploiter les MASQUES du mode segment.** La chaîne entière
   est indexée sur bbox/classe/conf/track (`_extract_detections` ne lit que
   `prediction.boxes`) → tout fonctionne à l'identique en mode segmentation, MAIS les
   masques sont actuellement JETÉS à l'extraction. Or ils offrent : (a) l'orientation
   par `minAreaRect` du masque = boîte orientée GRATUITE (le levier OBB sans
   fine-tuning), (b) le point de contact sol affiné (ligne des roues vs bas de bbox) →
   meilleure distance, (c) le centre latéral robuste (centroïde vs centre bbox,
   insensible aux rétroviseurs/ombres). À déclarer comme bascule `mask_geometry` le
   moment venu.
4. **Homographie à recalibrer** (multi-frames passages piétons + lignes centrales) — le
   latéral pinhole reste moins précis à >20 m.
5. **Bbox coupées au bord** : pas affichées en vue de dessus (délibéré) ; le hand-off
   les ponte temporellement (gate croissant, gap 2,5 s).
6. **Cap ratio** : ambiguïté résiduelle aux angles > pic diagonal (~68°).
7. « Fixer » la zone routière rose (road_mask) : non opérationnel, sémantique à préciser.
