# WAMA Data — Fonctions comme cards génériques par capacités

> **Statut : DESIGN / annonce de couleur (2026-07-20).** Rien d'implémenté encore. Ce document
> fixe le cap pour que toute fonction de traitement écrite à partir de maintenant (toolbox tierce
> map-matching, freinage, sections…) soit **conçue capability-first** et devienne une card sans
> retouche le jour où l'UI de chaînage arrive. **Centralisation : `wama/common/` (comme le reste).**

---

## 1. Principe

> **Une fonction de traitement est entièrement décrite par ses CAPACITÉS d'entrées/sorties.
> La card, les ports, la modale de paramètres s'AUTO-GÉNÈRENT à partir de ce descripteur** —
> exactement comme une app devient une card depuis `APP_CATALOG`, et comme le volet droit
> s'auto-remplit depuis `to_dict()`/métadonnées.

C'est le prolongement direct de deux principes WAMA déjà posés :
- **Métadonnée-driven** : l'UI se génère depuis les descriptions, pas écrite à la main.
- **Studio / méta-app** : canvas de nœuds reliés par **ports typés** ; une connexion n'est valide
  que si les types sont compatibles. Ici les nœuds sont : **card d'entrée (données) → card fonction →
  card de sortie**, et le chaînage de fonctions = le chaînage d'apps, même moteur (vanilla JS + SVG,
  réutiliser le canvas studio existant — NE PAS créer un 2ᵉ canvas).

Chaîne cible :

```
[Card ENTRÉE]                 [Card FONCTION]                [Card SORTIE]
 source de données     →       capability-matched     →      vue / export / stockage
 + tri / filtre / sélection    (params en modale)            (typée par l'entrée acceptée)
 → port de sortie typé         ports typés E/S               port d'entrée typé
```

---

## 2. Le descripteur de fonction (`FunctionSpec`)

À déclarer dans un registre central `wama/common/data/function_catalog.py` (analogue de `APP_CATALOG`).

```python
FunctionSpec:
    key:         str            # id unique, ex. "gps_map_match"
    name:        str            # libellé card
    description: str            # remplit l'UI (métadonnée-driven)
    category:    str            # taxonomie de fonction (voir §4)
    tags:        list[str]      # ex. ["geo", "timeseries", "requires-road-map", "column-wise"]
    inputs:      list[PortSpec] # créneaux d'entrée typés
    outputs:     list[PortSpec] # créneaux de sortie typés
    params:      list[ParamSpec]# paramètres → modale de réglages auto-générée
    cost:        dict           # optionnel : vram_gb, cpu_bound, ~durée (hint scheduling)
    fn:          callable       # implémentation (dans common/)

PortSpec:
    key:             str        # nom du créneau, ex. "track"
    data_type:       str        # type de la taxonomie DONNÉE (voir §3)
    required_fields: list[str]  # champs PRÉCIS exigés si spécifique, ex. ["lat","lon","heading"]
    produced_fields: list[str]  # (sortie) champs ajoutés/produits, ex. ["section_id","direction"]
    cardinality:     "one"|"many"
    optional:        bool

ParamSpec:
    key, type (float|int|bool|enum|str), default, min/max/choices, unit, description
```

**Règle d'or** : une fonction ne connaît QUE ses `data_type` + `required_fields`. Elle ne sait pas
d'où viennent les données ni où elles vont — c'est le canvas qui relie.

---

## 3. Taxonomie des TYPES DE DONNÉE (le cœur — analogue de `MEDIA_CATEGORIES`)

Le pendant, côté données, de la taxonomie média (`app_registry.MEDIA_CATEGORIES`/`normalize_types()`).
**À déclarer UNE fois, centralement** (`wama/common/data/data_types.py`) pour que sources et fonctions
parlent la même langue. Proposition de départ (extensible) :

| `data_type` | Description | Champs canoniques |
|---|---|---|
| `geo_track` | trajectoire géolocalisée temporelle | `time, lat, lon[, heading, speed, alt]` |
| `timeseries` | temps + N colonnes numériques | `time` + colonnes |
| `signal` | canal unique échantillonné | `time, value` (+ `fs`) |
| `events` | occurrences datées discrètes | `time[, duration, type, value]` |
| `table` | lignes × colonnes (tabulaire) | colonnes libres |
| `column` | une colonne isolée (applicable colonne-à-colonne) | `value` |
| `scalar` | valeur unique / indicateur agrégé | `value` |
| `sections` | intervalles routiers/temporels typés | `start, end[, type, id]` |
| `road_map` | polylignes routières (référentiel) | `geometry(WKT), id[, type]` |
| `detections` | objets détectés par frame (spécifique cam) | `frame, bbox, class, track_id…` |

**Sous-typage / compatibilité** : `geo_track ⊂ timeseries ⊂ table` (une géo-trace EST une timeseries
qui EST une table). La compatibilité de port suit cette relation + la satisfaction des `required_fields`.

---

## 4. Catégories & tags de fonction (drivent OÙ/COMMENT la card s'applique)

**Catégories** (ce que la fonction FAIT — pilote le regroupement UI et le port de sortie) :
- `transform` — transforme une donnée en même type (nettoyage, lissage, reprojection).
- `enricher` — ajoute des champs/colonnes à l'entrée (map-matching ajoute `section_id`/`direction`).
- `detector` — produit des `events` (freinage brusque, conflit).
- `indicator` — produit un `scalar`/agrégat (taux d'incidents, vitesse moyenne par section).
- `resampler` — change l'échantillonnage/cadence.
- `join` / `aggregate` — combine plusieurs entrées / agrège par groupe (par section, par véhicule).

**Tags** (facettes transverses pour tri/filtre/applicabilité) :
`column-wise` (applicable à une colonne), `geo`, `timeseries`, `requires-road-map`,
`requires-accel`, `needs-calibration`, `per-section`, `per-vehicle`… Les tags = ce que tu appelais
« celles qu'on applique à des colonnes », « celles qui calculent des indicateurs », etc.

---

## 5. Chaînage & validation de connexion (typé, comme le studio)

Une sortie `A.out` peut se relier à une entrée `B.in` **ssi** :
1. `B.in.data_type` est **compatible** avec `A.out.data_type` (égalité ou sous-typage §3) ;
2. les `B.in.required_fields` sont **satisfaisables** depuis les champs disponibles en sortie de A
   (champs de la source + `produced_fields` accumulés le long de la chaîne).

Le canvas propage le **schéma effectif** le long des liens (quels champs sont disponibles à chaque
étage) → il peut griser les fonctions inapplicables et pré-remplir le mapping de colonnes. C'est ce
qui rend le chaînage sûr et guidé, comme les ports typés des apps.

**Card d'entrée** = source + sélection (dataset, colonnes, **tri, filtre**, plage temporelle) → expose
un port de sortie typé par la sélection. **Card de sortie** = vue/export/stockage, accepte un type donné.

---

## 6. Inspiration toolbox tierce

Le modèle toolbox tierce (`manifest.xml`) EST déjà un pipeline de blocs à I/O déclarées : chaque flux
(`TS_NavyaAPI`, GNSS, accéléro, `TS_OperatorAnnotation`) est une timeseries typée que les scripts
consomment/produisent. La logique gérée/validité/near des annotations, les extracteurs par section,
le map-matching = autant de **fonctions à I/O nettes** qui se transposent 1-pour-1 en `FunctionSpec`.
Voir [[project_toolbox tierce_integration]] : ses fonctions seront **les premières function-cards**.

---

## 7. Conséquence IMMÉDIATE (avant même l'UI de chaînage)

> Toute fonction de traitement écrite à partir de maintenant (à commencer par toolbox tierce) est **conçue
> capability-first** : signature pure `(données_typées, params) → données_typées`, sans I/O de fichiers
> ni dépendance à une app, et **accompagnée de son `FunctionSpec`** (même si le registre/canvas n'existe
> pas encore). Ainsi le jour où l'UI arrive, on branche — zéro réécriture.

Placement : `wama/common/data/` (implémentations + `function_catalog.py` + `data_types.py`).
Ne PAS coder ces fonctions dans une app : brique commune d'abord (règle de centralisation).

---

## 8. Reste à trancher (quand on implémentera)

- Représentation runtime d'une « donnée typée » : DataFrame pandas + un `schema`/`meta` (data_type +
  champs) attaché ? Ou un petit wrapper `TypedFrame` ? (préférence : pandas + meta léger).
- Persistance des chaînes (comme les graphes studio) + exécution (réutiliser Celery + le scheduling
  par `cost`).
- Où vit le registre : `common/data/function_catalog.py` seul, ou exposé aussi via `tool_api.py`
  pour que l'assistant IA propose/enchaîne des fonctions.
- Croisement avec le RAG (fonctions descriptibles → héritage université→labo→équipe→user).
