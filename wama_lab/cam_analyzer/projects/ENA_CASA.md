# Projet ENA_CASA — spécificités (données + calibration + rig)

> **Portée.** Ce document consigne tout ce qui est **spécifique au projet** ENA_CASA (jeu de
> données, réglages de calibration, géométrie du rig, contexte métier du run). Il est
> **volontairement hors des piliers de l'application** (`README` / `CHAINE_TRAITEMENT` /
> `CHANGELOG`) : `cam_analyzer` est une **application générique multi-projets** ; un projet en est
> une **configuration**, pas une propriété de l'app.
>
> **Statut manifeste.** Ce doc est **façonné comme le futur manifeste** pour un *lift-and-shift*
> (remplir le JSON, pas réécrire). Le §1 (données) miroir du kind **`dataset`** (`wama/common/
> manifests/builtin/dataset.py`, déjà *validate+store*) → **ingestable tel quel** quand on voudra.
> Le §2 (calibration/rig) **n'a pas encore de kind** → graine d'une extension `project` ou d'un
> nouveau kind `calibration`. Aucun kind ne **projette** encore dans les registres (`AnalysisProfile`
> / `session.config`) : tant que le write-back n'existe pas, **ce doc reste la source de vérité
> projet**, et la config vit sur `AnalysisSession.config` / `AnalysisProfile` / `CameraView`.
>
> **Ne PAS mettre ici** ce qui est générique (formules, chaîne, méthode) → cela va dans
> `CHAINE_TRAITEMENT.md`. Ici : uniquement des **valeurs et faits propres à ENA_CASA**.

Dernière mise à jour : 2026-07-21.

---

## Enveloppe (commune à tout manifeste)

| Champ | Valeur |
|---|---|
| `manifest_kind` | `dataset` (pour le §1) — le §2 attend un kind `calibration`/extension `project` |
| `key` | `ENA_CASA` |
| `schema_version` | `1.0` |
| `name` | ENA — navette autonome Navya, site Nice (CASA) |
| `world` | `lab` |
| `visibility` | `unit` (labo Lescot) |
| `source` | `{type: 'toolbox tierce', ref: 'claude/WAMA-Lab/Cam_Analyzer/toolbox tierce/ENA_NAVYA/7_00/Model/manifest.xml'}` (+ variante `ENA_MILLA`) |
| `projects` | `['ENA_CASA']` |

> ⚠️ **Pré-projet ≠ réalité.** Les specs d'instrumentation annoncées (4× AXIS F4005-E Dome 110°,
> enregistreur F44, centrale SBG Ellipse-N) sont des **a priori surchargeables**, pas la vérité. Les
> valeurs ci-dessous sont **mesurées sur les données réelles** quand elles divergent du pré-projet.

---

## Contexte métier (durable, propre au run)

- **Commanditaire / usage** : labo **Lescot** (Université Gustave Eiffel — SHS / ergonomie / sciences
  cognitives des transports). Étude de la **cohabitation navette autonome ↔ usagers** en intersection.
- **Véhicule ego** : **navette autonome Navya Autonom** (une seule navette-ego dans le jeu ENA_CASA).
- **Site** : **Nice (CASA)**, `43,62 N / 7,07 E` → **normes routières FR** par défaut.
- **Run de référence** : **2022-04-04**. 2 sessions / ~56 655 frames (base WSL2 réelle).
- **Scène** : une **navette-leader** roule devant l'ego (objet suivi légitime navette↔navette).

---

## §1 — Données (miroir du kind `dataset`)

> Structure = `body` d'un manifeste `dataset` : `source` + `signals[]` typés + `reference_tables{}`
> + `records[]`. À terme : `ingest_manifest()` (`wama/common/manifests/ingest.py`).

### `source`
- **Vidéo** : composant **quad RTMaps** — **4 vues dans UN SEUL flux** h264 `800×500 @ 12 fps`
  (~2 h 20), découpé en 4 panneaux par `quadrature_video.py`.
- **Véhicule** : fichier **`.rec`** RTMaps (horodatage `MM:SS.µs`) + **CSV par canal**
  (`RecFile_Data/…_*.csv`, format `sample_ts_µs;valeur`, `;`-séparé) — **parsing propre = les CSV**,
  pas le `.rec` monolithique.

### `signals[]` (typés sur la taxonomie `data_types`)
| `id` | `data_type` | Réalité mesurée |
|---|---|---|
| `video_quad` | `video` | 1 flux 800×500 @ 12 fps → 4 panneaux (voir §2 résolutions/caméra). |
| `gps` | `geo_track` | NMEA ~**1 Hz**, bon fix (**9 sats, HDOP 0,87**). Fournit lat/lon **et le cap (course VTG/RMC)** — **valide en mouvement uniquement** (vide à l'arrêt). |
| `accel_x` / `accel_y` / `accel_z` | `scalar` (g, ~10 Hz) | `Accel_Sensor.X/Y/Z`. **3 flux par axe** partageant un `sample_ts` (Z ≈ 0,95 g = gravité). |

> **Absents / pièges du jeu ENA_CASA** (à réclamer à l'exploitant pour le run 2022-04-04) :
> - **Aucun gyroscope / canal d'orientation** dans le `.rec` → **le cap ne vient QUE du GPS**
>   (course), non observable à l'arrêt (tenu au dernier connu). Si un log **SBG** séparé existe,
>   le récupérer.
> - **API navette** (schéma : `orientation`, `speed`, `driving_direction`, lat/lon, mode) = source
>   **prioritaire SI disponible** (donnerait le cap même à l'arrêt) mais **ABSENTE** : l'échantillon
>   fourni est un **stub `VEHICLE-STUB-1`** (coords Lyon, `orientation` vide).
> - Piège parseur : `rtmaps_parser.py` attendait un flux `x,y,z` combiné → **accel jamais parsé**
>   depuis le `.rec` (utiliser les CSV par canal).

### `reference_tables{}`
- Tables d'annotation toolbox tierce (`NV_AnnotationTag`, sections `Section CASA-sections.csv`, tags
  opérateur) — à recopier depuis le manifeste XML source lors de l'ingest.

### `records[]`
- `run_2022-04-04` → `{signals: [video_quad, gps, accel_x, accel_y, accel_z], sessions: 2, frames: ~56655}`.

---

## §2 — Calibration & rig (PAS encore de kind manifeste)

> Ces valeurs vivent aujourd'hui sur `AnalysisSession.config` / `AnalysisProfile` /
> `CameraView.ground_homography` (cf. table de calibration dans `CHAINE_TRAITEMENT.md`). Elles sont
> consignées ici **au titre du projet** : ce sont des mètres-étalons du run ENA_CASA, pas de la
> méthode générique. **Graine d'un futur kind `calibration`** (ou extension du body `project`).

### Implantation des 4 caméras (schéma pré-projet, mi-arêtes, chacune ~110°)
| Caméra | Axe | Montage (`camera_mount`, m) | `camera_yaw` (défaut) | Résolution panneau mesurée |
|---|---|---|---|---|
| avant (`front`) | +Y (bout avant) | (0, +4,5) | 0° | 384×248 |
| arrière (`rear`) | −Y (bout arrière) | (0, 0) ≈ antenne | 180° | 408×248 |
| gauche (`left`) | −X (mi-flanc) | (−1,0, +3,4) | −75° | 408×244 |
| droite (`right`) | +X (mi-flanc) | (+1,0, +3,4) | +75° | 384×244 |

- Les latérales G/D regardent **perpendiculairement** → idéales pour le **cross-check d'insertion**.
- **`gps_antenna`** : le point GPS est l'**antenne** (coin **arrière-droit** ≈ `(1.0, 0.0)`), **pas**
  le centre véhicule → tout le repère est ramené au **centre arrière** (⚑ `antenna_lever`).

### FOV & optiques (réels, ≠ pré-projet)
- **`DEFAULT_FOV_V_DEG`** (utilisé pour la distance pinhole) : avant/arrière **61°** (AXIS F4005-E
  110° H), latérales **31°** (AXIS **F1015** réglées ~**55° H**).
- ⚠️ Vari-focale F1015 **probablement restée au réglage LARGE ~97° H** (à confirmer à l'écran, audit
  #4) : un FOV réel plus large **surestime** les distances latérales → correction `dist_scale`.
- Optique **quasi-rectiligne** sur ENA_CASA (grand-angle modéré) → **k1/distorsion testé et ÉCARTÉ**
  (pas de gain). `fx ≈ 134 px` sur ~384 px → **plafond de précision** à assumer.

### Calibration sol (ground_calib, par caméra — ⚑ `auto_ground_calib`)
| Caméra | pitch estimé | hauteur | Étalement monde | Retenue ? |
|---|---|---|---|---|
| avant | 22° | 1,53 m | — | ✅ |
| droite | 26,5° | 1,6 m | — | ✅ |
| arrière | — | — | > 2,5 m | ❌ rejetée |
| gauche | — | — | > 2,5 m | ❌ rejetée |

- Hauteur caméra défaut si non calibrée : **`H cam ≈ 2,4 m`**.
- **Offset ortho 2b** mesuré (recalage absolu IGN) : **~5,1 m** (2,93 E / 4,2 N) — **RAPPORT seul,
  NON appliqué** (bascule à venir).

### Références métriques (normes FR, surchargeables au profil)
`lane_width_m` 3,5 · `dash_mark_length_m` 3,0 · `dash_gap_length_m` 9,0 ·
`crossing_band_width_m` 0,5 · `crossing_gap_width_m` 0,5.

### Dimensions ego (Navya Autonom, surchargeables)
`ego_length_m` **4,75** · `ego_width_m` **2,11** · `ego_height_m` **2,65** · `ego_cam_to_bumper_m` (null).

### Intersections (déclarées au profil, propres au site)
Zones nommées `{lat, lon, radius}` du site CASA — définies dans `AnalysisProfile.intersections`
(éditeur de profil), mutualisées par lieu physique (~1 m).

---

## Chantiers manifeste révélés par ce projet

1. **§1 ingestable maintenant** : le kind `dataset` est prêt → écrire le `body` JSON depuis le XML
   toolbox tierce source et `ingest_manifest()`. Reste : le **reader source-agnostique** (projection) pour
   que les apps consomment le dataset (chantier `dataset` projection).
2. **§2 sans foyer** : la **calibration/rig** n'a pas de kind → concevoir soit une **extension du
   body `project`**, soit un kind **`calibration`** (par session/caméra, avec époques de dérive), +
   **write-back** vers `AnalysisProfile`/`CameraView` pour que le manifeste **pilote** la config au
   lieu d'être recopié à la main.
3. **`project` kind** aujourd'hui = composition org seule (owner_org/lead/membres) → ENA_CASA devra
   aussi exister comme `Project` (couche cross-org) pour relier données + calibration + accès.
