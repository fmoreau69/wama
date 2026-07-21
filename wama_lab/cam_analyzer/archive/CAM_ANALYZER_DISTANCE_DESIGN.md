> ⚠️ **ARCHIVÉ / SUPERSEDED (2026-07-21).** Contenu vivant absorbé dans `CAM_ANALYZER_CHAINE_TRAITEMENT.md` (§ Conception & justification, terminologie, plan calibration sol). Les valeurs propres au run ENA_CASA sont dans `projects/ENA_CASA.md`. Conservé pour provenance uniquement — NE PLUS METTRE À JOUR.

---

# Cam Analyzer — Distances, vitesses, TTC & vue de dessus (design)

> Document de conception du chantier **Phase 3** : passer d'une distance pinhole non
> calibrée (vitesses/TTC aberrants) à une **géométrie sol par homographie**, avec
> fallback robuste, fusion inertielle, filtrage des véhicules d'intérêt, et une
> **vue de dessus cartographiée** des éléments autour de la navette.
>
> Périmètre initial de travail : le jeu `ENA_CASA` (site de Nice, une seule navette ego).
> ⚠️ **Mise à jour** : la **vue de dessus 360° multi-caméras est désormais implémentée** (elle
> n'est plus hors scope) — voir l'ADDENDUM ci-dessous, qui SUPERSÈDE les statuts du corps.

---

## ADDENDUM POST-IMPLÉMENTATION (2026-07-20)

> Ce document reste valable pour son **raisonnement de conception** (il fonde le design), mais le
> chantier a été **exécuté puis dépassé**. Cet addendum décrit ce qui a réellement été construit et
> **SUPERSÈDE les marqueurs de statut du corps** (« à créer », « hors scope », « 0 entrée », le
> phasage, le « BUG STRUCTUREL »…). En cas de contradiction, l'addendum fait foi.

Ce qui a réellement été construit :
- **Calibration sol AUTO retenue** (`utils/homography_estimator.py`) = **minimisation de l'étalement
  monde des stationnés**, qui **résout le pitch** caméra (mesuré : désaccord sol⟷pinhole
  **14,55 m → 3,05 m** à pitch **21,5°**). **k1 / distorsion testé et ÉCARTÉ** (pas de gain sur cette
  optique quasi-rectiligne). L'étape **2a « placement par projection sol » est faite** mais derrière la
  bascule `auto_ground_calib` (**OFF** par défaut) ; **2b** (échelle absolue via marquages ortho) et
  **2c** (calibration jointe pitch + échelle) restent à venir.
- **Lissage Kalman CV + RTS** (`utils/trajectory_smoother.py`, écrit `world_en`) — va **au-delà** du
  simple lissage EMA de la correction 3a.
- **Vue de dessus 360° multi-caméras IMPLÉMENTÉE** (`utils/multicam_tracker.py` : hand-off d'identité
  inter-caméras, repère ego commun) — exactement ce que le §6 « Points ouverts » déclarait hors scope.
- **Calibration stockée sur la SESSION** (`config['ground_calib']`) + `CameraView.ground_homography`
  (mig **0014**) → le « **BUG STRUCTUREL : la calibration fuit via le profil** » (Roadmap calibration)
  est **RÉSOLU**.
- **SAM3 fonctionnel** (crossing / stop_line), **interpolation** entre keyframes, cadence
  `profile.sam3_fps`, **agrégation monde** (`utils/marking_world.py`) — le corps qui indiquait
  « 0 entrée / inactif » est **périmé**.
- **11 feature flags A/B** (`utils/features.py`) ; **cap serveur des stationnés**
  (`anchor_heading` / `heading_cluster` / `heading_ratio`) ; **levier antenne GPS** ; **fond
  orthophoto IGN** ; bouton **cap navette** (Leaflet-rotate).

---

## 1. Constat & vérifications empiriques (2026-07-07)

Base réelle (WSL2 Postgres), 2 sessions / **56 655 frames** :

| Vérification | Résultat empirique |
|---|---|
| Détections SAM3 (`sam3_marking`) | *Constat 2026-07-07 : 0 entrée.* **Périmé** : SAM3 est désormais fonctionnel (crossing/stop_line, interpolation, agrégation monde `marking_world.py`) — voir ADDENDUM. |
| Types stockés | `road_mask` 78 463 (dont classes `lane (yolopv2)` ≈ 55,6k, `drivable area (yolopv2)` ≈ 22,9k), + objets COCO. |
| « Passages piétons roses » | **Ce ne sont pas des détections de passage.** Les polygones `road_mask` sont rendus en **magenta** (`index.js:1659`) ; la tête *lane* de YOLOPv2 s'allume sur les **zébrures** → un polygone `lane` épouse le passage. C'est le masque de lignes, pas un passage étiqueté. |
| Classes objets | **COCO non filtré** : `airplane`, `bird` 2950, `train` 3432, `boat`, `sheep`… → beaucoup de faux positifs. Filtre `target_classes` appliqué **au read-time seulement**, conditionné à un `target_classes` non vide. |
| Lentilles (frames réelles) | Avant `ENA_CASA` = **quasi-rectiligne / grand-angle modéré**. Avant `tele` du jeu rural (hors scope) = **fisheye + vignettage fort**. Latérales (mirror) = quasi-rectilignes. → **undistorsion par caméra**, paramétrée. |
| Scène `ENA_CASA` | Une **navette-leader** roule devant l'ego-navette (objet détecté légitime, suivi navette↔navette). Le panneau « front » de la quadrature est correct (pas de mismap). |
| IMU/GPS (`.rec`) | **Accéléromètre 3 axes en `g`, ~10 Hz** (Z≈0,95 g = gravité). **Aucun gyroscope.** Cap uniquement via **course GPS (VTG/RMC)**, valide **en mouvement** (vide à l'arrêt). GPS ~1 Hz, bon fix (9 sats, HDOP 0,87). Position 43,62 N / 7,07 E = **Nice** → **normes FR**. |

### 1bis. Instrumentation : **pré-projet ≠ réalité** (à vérifier empiriquement)

Le plan d'instrumentation annonce **4× AXIS F4005-E Dome (110°)** via enregistreur **AXIS F44**
et centrale inertielle **SBG Ellipse-N**. ⚠️ **Ce sont des specs de pré-projet ; la réalité peut
différer** → on les traite comme **a priori surchargeables**, jamais comme vérité. Vérifs sur les
données réelles (`ENA_CASA`) :

| Élément | Pré-projet | **Réalité mesurée** |
|---|---|---|
| Enregistrement caméras | 4 flux | **Composant *quad* RTMaps : 4 vues dans 1 seul flux** h264 `800×500 @ 12 fps` (~2h20), split en 4 panneaux **~384×248** par `quadrature_video.py`. |
| Résolution utile / caméra | (1080p implicite) | **~384×248** → très basse def + très grand-angle → `fx ≈ 134 px`, **plafond de précision** à assumer. |
| IMU | SBG Ellipse-N (gyro+cap) | `.rec` ne logge que **`Accel_Sensor.X/Y/Z`** (g, ~10 Hz) + GPS NMEA. **Aucun canal orientation/cap/gyro** → **cap = course GPS seule**. Si un log SBG séparé existe, à récupérer. |
| Format `.rec` | (supposé) | Horodatage `MM:SS.µs` ; accel en **3 flux par axe** partageant un `sample_ts`. **`rtmaps_parser.py` attend un flux `x,y,z` combiné → accel jamais parsé** (bug à corriger). |
| Distorsion | — | 110° dome ⇒ barillet attendu ; **estimable en ligne** via la contrainte « lignes droites après undistorsion » (pas besoin des coeffs constructeur). |

**Robustesse au doute sur les specs** : comme `H` est **estimée depuis les lignes**, elle **mesure la
géométrie réelle** (fx effectif, distorsion, pitch) directement dans l'image. Les specs constructeur ne
servent que d'a priori/bornes/fallback → **le risque « la réalité diffère » est absorbé par le design**.

### 1quater. Ego-pose : sources hiérarchisées (cap = point dur)

- **API navette** (schéma vu : `orientation`, `speed`, `driving_direction`, lat/lon, mode…) =
  **source prioritaire SI disponible** → donnerait le **cap directement** (y compris à l'arrêt) +
  vitesse + sens de marche. ⚠️ **Absente du jeu `ENA_CASA`** (l'échantillon fourni est un *stub*
  `VEHICLE-STUB-1`, coords Lyon, `orientation` vide). À réclamer à l'exploitant pour le run 2022-04-04.
- **Fallback `ENA_CASA`** = GPS + accel. **Parsing propre = les CSV par canal** (`RecFile_Data/…_*.csv`,
  format `sample_ts_µs;valeur`, `;`-séparé, ts en microsecondes) plutôt que le `.rec` monolithique :
  accel = fusion des 3 CSV X/Y/Z par ts ; position = `…_oPosition.csv`. **Cap = cap GPS (course)**
  quand en mouvement, tenu au dernier connu à l'arrêt.
- Ordre de priorité ego-pose : **API navette > (GPS + accel)**. Module `ego_pose.py`.

### 1ter. Implantation des caméras (schéma pré-projet, `claude/…Livrable 2.4.1…png`)

4 caméras aux **mi-arêtes**, chacune 110° : **avant** (bout avant, axe +Y) · **arrière** (bout arrière,
axe −Y) · **gauche** (mi-flanc, axe −X) · **droite** (mi-flanc, axe +X). → les vues **latérales G/D
regardent perpendiculairement** = idéales pour le **cross-check d'insertion**. Donne les extrinsèques de
montage (position + yaw par caméra) pour la fusion en vue de dessus (recouvrement d'angles aux coins).

**Correctif déjà livré (Phase 3a)** — `utils/distance_speed.py` : la vitesse était une
différence à 2 points d'une distance bruitée → dérivée explosive (−73…+89 km/h sur signal
cohérent). Remplacé par **lissage EMA interne + régression moindres-carrés sur ~0,6 s +
clamp des sauts impossibles + rejet des vitesses hors plage plausible**. Les **distances
`distance_m` ne sont PAS modifiées** (jugées cohérentes) ; seuls vitesse/TTC sont filtrés.

---

## 2. Décisions actées

1. **Option B (homographie sol)** comme méthode cible de distance, avec **fallback** vers
   le pinhole actuel + lissage quand la géométrie n'est pas calculable ou désactivée.
2. **Une primitive unifie tout** : projeter le **point-sol** de l'objet (centre-bas de la
   bbox, supposé au sol) par l'homographie `H` (image→plan-sol) → **position `(X, Y)`** dans
   le repère navette. Distance, vitesse, TTC, **vue de dessus** et filtrage stationnés en
   découlent.
3. **`H` est constante par caméra** (montage rigide + sol plan) → les marquages servent à
   **accumuler des correspondances dans le temps** pour estimer **une seule `H` stable**
   (auto-calibration en ligne), pas à recalculer par frame.
4. **Sources hiérarchisées + confrontation** (couche de fusion, chaque source émet
   `(valeur, confiance)`) :
   1. Calibration utilisateur (vérité terrain injectée) ;
   2. **Lignes de voie** (YOLOPv2) — échelle latérale via largeur de voie, longitudinale via
      période des pointillés ;
   3. Passages piétons (SAM3) — **désormais actif** (SAM3 fonctionnel, cf. ADDENDUM) ; 2ᵉ estimateur ;
   4. **Pinhole + lissage** — dernier recours, jamais faux « d'un coup ».

   Règles : lignes ⟷ pinhole se confrontent ; désaccord fort → segmentation douteuse →
   fallback pinhole. Passages redeviennent 2ᵉ estimateur si SAM3 relancé.
5. **La calibration précise n'est PAS requise** : l'homographie estimée depuis les lignes
   **absorbe intrinsèques + extrinsèques**. La focale connue = a priori + borne + fallback.
   L'**échelle métrique** vient de largeur de voie + période pointillés (fournies par
   l'utilisateur, défaut normes FR). **Seule contrainte** : une caméra fisheye doit être
   **redressée d'abord**.
6. **Toutes les références métriques et dimensions sont surchargeables au profil**
   (idéalement mesurées, sinon défauts normes FR / constructeur Navya).
7. **Fusion IMU (accéléromètre)** avec le GPS pour l'**ego-pose** : améliore vitesse propre
   et trajectoire, donne le tilt (pitch/roll via gravité). **N'apporte pas le cap** (pas de
   gyro) → cap = course GPS quand en mouvement, tenu au dernier connu à l'arrêt.
8. **Vue de dessus** = tracé des `(X, Y)` autour d'une silhouette navette dimensionnée
   (**Navya Autonom par défaut** : 4,75 × 2,11 × 2,65 m, surchargeable), offset
   bas-de-vue→pare-choc réglable.
9. **Filtrage des véhicules d'intérêt** : (a) filtre classes usagers-route ; (b) scoping
   intersection (comportement d'insertion vs passage navette : avant / a attendu / opposée)
   dans les fenêtres utilisateur + zone routière ; (c) cross-check par **vues latérales**.

   **§2.9 — Règle `of_interest` (implémentée).** Chaque `TemporalSegment` d'intersection est
   tagué (non destructif) dans `_detect_intersection_insertion` :
   `of_interest = (event_type ∈ {insertion, wait}) ET (vehicle_class ∈ ROAD_USER_CLASSES)`.
   Les `event_type='turn'` (traversée/virage sans interaction) et faux positifs COCO
   (airplane/bird…) → `of_interest=False`, **masqués par défaut** dans le rapport (bascule
   « Afficher tout » côté UI). Résultat mesuré sur P97 : **130 segments → 5 d'intérêt**
   (123 `turn` + 2 non-usagers écartés). Le frontend rend 1 ligne/véhicule d'intérêt avec
   **chips t0/t1/t2 cliquables** (seek + resync). `t2` (« pleinement inséré ») s'appuiera sur
   le **ratio d'aspect** (`bbox_trajectory` déjà stocké) — raffinement à venir.

### Terminologie distances (actée)
- `dist_longitudinal_m` = **Y** (projection instantanée sur l'axe navette). *Longitudinale*,
  pas « curviligne » (la vraie curviligne = longueur d'arc le long de la trajectoire GPS ;
  grandeur distincte, éventuellement ajoutée plus tard).
- `dist_lateral_m` = **X** (écart latéral).
- `dist_euclid_m` = **‖(X, Y)‖** (distance directe / euclidienne — préféré à « rectiligne »).

---

## 3. Architecture cible

```
                 ┌─────────────────────────────────────────────┐
   marquages ───▶│ homography_estimator.py                     │
   (lignes)      │  accumule corresp. → H par caméra + conf.    │──┐
                 └─────────────────────────────────────────────┘  │
   calib profil ─────────────────────────────────────────────────┼─▶ ground_projection.py
   pinhole (FoV/hauteurs) ────────────────────────────────────────┘   (undistort → H|pinhole
                                                                        → (X,Y) → distances)
                                                                              │
   GPS + IMU ──▶ ego_pose.py (fusion, cap GPS) ───────────────────────────────┤
                                                                              ▼
                                                          per-detection: dist_*_m, ground_xy,
                                                          relative_speed_kmh, ttc_s, *_source
                                                                              │
                                        ┌─────────────────────────────────────┼──────────────┐
                                        ▼                                     ▼              ▼
                                 vue de dessus (JS)             filtrage stationnés     rapport scopé
                                                                (+ corridor)         (intersection_analyzer)
```

Modules (`utils/`) — **les trois EXISTENT désormais** (n'étaient plus « à créer ») :
`ground_projection.py` (socle), `homography_estimator.py` (calib sol AUTO / lignes → H),
`ego_pose.py` (GPS+IMU). `distance_speed.py` reste la couche fallback + dérivation temporelle
(déjà durcie en 3a) ; le lissage principal est désormais `trajectory_smoother.py` (Kalman+RTS).

---

## 4. Schéma de données

### `AnalysisProfile` (config utilisateur, surchargeable)
- `geometry_enabled` (bool, def. False) — activer la projection homographique.
- `camera_calibration` (JSON) — par position : `{lens_type, fx_px, fy_px, cx_px, cy_px,
  distortion[], fov_h_deg, fov_v_deg, height_m, pitch_deg, yaw_deg, roll_deg, mount_x_m,
  mount_y_m, homography[3][3]}`. Tous optionnels (manquants → estimés/pinhole).
  ⚠️ **Mise à jour** : la calibration n'est plus **seulement** sur `AnalysisProfile`. Elle est
  désormais portée aussi par la **session** (`AnalysisSession.config['ground_calib']`) et par
  `CameraView.ground_homography` (mig **0014**) — voir ADDENDUM (résout la fuite inter-sessions).
- Références sol : `lane_width_m` (3.5), `dash_mark_length_m` (3.0), `dash_gap_length_m`
  (9.0), `crossing_band_width_m` (0.5), `crossing_gap_width_m` (0.5).
- Navette ego : `ego_length_m` (4.75), `ego_width_m` (2.11), `ego_height_m` (2.65),
  `ego_cam_to_bumper_m` (null).
- `use_imu` (bool, def. True).

### `AnalysisSession`
- `imu_track` (JSON) — `[{ts, ax, ay, az}, ...]` (g), extrait du `.rec`.
- (`gps_track` existant porte déjà `heading`.)

### Par détection (`DetectionFrame.detections[]`, JSON — pas de migration)
- Existants : `distance_m` (pinhole brut, conservé), `relative_speed_kmh`, `ttc_s`.
- Ajouts : `dist_longitudinal_m`, `dist_lateral_m`, `dist_euclid_m`, `ground_xy` [X,Y],
  `distance_source` ∈ {homography, pinhole}.

---

## 5. Phasage

- **3a — Lissage vitesse/TTC** ✅ *livré & validé* (fallback de B).
- **3b — Socle homographie + calibration profil** : schéma profil/session, `ground_projection.py`
  (undistort → H|pinhole → distances), filtre classes par défaut, sanity-check quadrature.
- **3c — Estimateur lignes + consensus** : `homography_estimator.py`, fusion/fallback.
- **3d — Vue de dessus** ✅ *implémentée* (v1) : **zoom sémantique sur UNE carte Leaflet ancrée monde** (Nord en haut), pas
  deux modes commutés. Les objets `(X,Y)` égo sont convertis en **lat/lon** via la pose navette (GPS +
  cap course) et **posés sur la même carte** que le marqueur ; ils **apparaissent en fondu sous un seuil
  de zoom** (dézoom → trajet GPS seul ; zoom → vue tactique locale). **Auto-suivi** (auto-pan + zoom par
  défaut) pour garder navette+objets cadrés en lecture ; couche objets mise à jour par frame (marqueur
  déjà interpolé). Option gardée sous le coude : panneau égo dédié (navette en haut, qui tourne).
  Précision = calibration + cap ; l'interpolation lisse le rendu. La vue = simple tracé des `(X,Y)` déjà
  calculés pour les distances → quasi « gratuite » une fois la calibration active.
  **Couches objets (décidé)** : (1) **couleur TTC/proximité** en paliers vert/orange/rouge (robuste basse
  précision, cohérent avec la timeline) ; (2) **vecteur vitesse absolu** (`(dX,dY)/dt` tourné en repère
  monde), toggle, introduit APRÈS calibration+lissage, direction-seule si bruité ; (3) **trace du chemin
  récent** (dernières N s) avec **opacité décroissante** vers l'ancien (souvent + parlante qu'un vecteur
  pour lire une manœuvre, ex. arc d'insertion). **Navette** : marqueur **orienté** (chevron = cap) au zoom
  monde → **rectangle à l'échelle** (dims ego du profil ~4,75×2,11 m, orienté cap) au zoom tactique.
- **3e — Ego-pose (GPS+IMU) + filtrage stationnés + corridor + scoping intersection**.

3d et 3e sont parallélisables au-dessus de 3b/3c.

---

## 6. Points ouverts / risques

- **Undistorsion fisheye** : nécessaire pour les caméras à forte distorsion (hors scope
  actuel `ENA_CASA` qui est quasi-rectiligne, mais prévu au schéma `lens_type`/`distortion`).
- **Sol plan** : hypothèse locale acceptée ; dévers/pente urbaine négligés sur la portée utile.
- **Point-sol tronqué** (objet coupé en bas d'image) → position fausse → garde-fou confiance
  + fallback pinhole.
- **Cap à l'arrêt** : non observable (pas de gyro) → tenir le dernier cap GPS.
- **Vue de dessus multi-caméras 360°** : ~~hors scope~~ → **IMPLÉMENTÉE** (`multicam_tracker.py`,
  hand-off d'identité, repère ego commun). N'est plus un point ouvert — voir ADDENDUM.
- **Auto-calibration sol** : ~~ouverte~~ → **faite** (`homography_estimator.py`, résout le pitch).
  Restent ouverts : l'échelle métrique absolue (étape 2b, marquages ortho) et la calib jointe (2c).
```

---

## Roadmap calibration (2026-07-08, proposition validée à discuter)

**Contexte** : SAM3 confirmé fonctionnel (fix bug tensor `bool(Tensor)`) — crossing détecté à
score 0.799. Chaîne 1-frame → homographie → distances sol → vue de dessus branchée (bouton
« 📐 Calib. SAM3 » + helper partagé `_calibrate_from_crossing_polygons`, réutilisé par l'auto-scan
base `_auto_calibrate_from_crossings`).

### Points tranchés
- **Une image suffit MATHÉMATIQUEMENT** (homographie = 8 DDL, 1 quad planaire = 8 contraintes) mais
  la précision **s'effondre au loin** (coins groupés en bas d'image → horizon mal contraint). →
  **multi-frames** (même passage proche→loin via ego-motion GPS+IMU) = fit sur-déterminé qui recale
  l'horizon + moyenne le bruit. « Garder les 6 images » = garder toutes les observations.
- **Ne PAS se cantonner aux zones d'analyse** pour la calibration (meilleurs passages ailleurs). La
  **sélection manuelle d'une frame reste la baseline**. Semi-auto = GPS pour localiser un passage puis
  extraire frames proche→loin.
- ✅ **BUG STRUCTUREL RÉSOLU** : `camera_calibration` était sur `AnalysisProfile` (réutilisé entre
  sessions, views.py:318) → la calibration fuyait d'une session à l'autre. **Corrigé** : calib portée
  par la **session** (`config['ground_calib']`) + `CameraView.ground_homography` (mig **0014**).
- **Caméras qui décrochent** (entre sessions ET en cours de session) : calibration DOIT être **par
  session**. En cours de session → surveiller le **RMS de reprojection** des passages successifs ; saut
  = caméra bougée → **époques de calibration** (avant/après).
- **360°** : montage fixe par session → 1 homographie/caméra/session. Côtés/arrière voient rarement un
  passage entier → les calibrer par **marquages de voie (yolopv2)**, pas SAM3. Repère ego commun →
  hand-off de tracks par continuité de position sol → trajectoires continues.

### Phasage
> **Statut 2026-07-20** (SUPERSÈDE la colonne d'origine) : Phase **0 = FAITE** (calib par session,
> `CameraView.ground_homography`, mig 0014), Phase **C (360° / hand-off) = FAITE**
> (`multicam_tracker.py`), Phase **B (auto-calib) = en grande partie faite**
> (`homography_estimator.py`, pitch résolu ; reste l'échelle absolue 2b + calib jointe 2c).

| Phase | Contenu | Statut |
|-------|---------|--------|
| ✅ Actuel | 📐 Calib. SAM3 manuel (baseline) | fait |
| **0** | Calibration **par session** (`CameraView.ground_homography`, mig 0014), plus sur profil partagé ; dims passage/ego restent sur profil | ✅ **fait** |
| **A** | Raffinement **multi-frames** GPS-ancré (précision au loin) | partiel |
| **B** | Auto-calibration **par session** (`homography_estimator.py`) + détection dérive RMS | ✅ **en grande partie faite** (reste 2b échelle + 2c jointe) |
| **C** | **360°** : sides via voies, repère ego commun, hand-off de tracks | ✅ **fait** (`multicam_tracker.py`) |

**Point de reprise** : étape **2b** (échelle métrique absolue via passages piétons ortho IGN +
matching crossings caméra `marking_world.py`), puis **2c** (calibration jointe pitch + échelle).
