# WAMA Data — Fonctions comme cards génériques par capacités

> **Statut : IMPLÉMENTÉ (MAJ 2026-07-25).** Taxonomie (`common/data/data_types.py`) + catalogue
> (`function_catalog.py`) + **19 fonctions** enregistrées au démarrage + page catalogue
> `/model-manager/functions/` (cards, tri/filtre, projet, confidentialité). **Reste** : l'UI de
> chaînage (canvas) + exposition `tool_api`. Ce document fixe le cap capability-first pour toute
> nouvelle fonction. **Centralisation : `wama/common/` (comme le reste).**

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

**Placement par DOMAINE (refactoring 2026-07-22, 9945ca8/a06f3be)** : les implémentations vivent
sous `wama/common/data/functions/<domaine>/` — 4 sous-paquets : `io/` (parsing, ex. RTMaps .rec),
`geometry/` (primitives + métriques), `kinematics/` (extrapolation, collision), `driving/`
(fonctions métier conduite, dont les 4 toolbox tierce). Le domaine est un **3ᵉ axe orthogonal** à
`data_type` et `category` (cf. docstring `functions/__init__.py`). Les anciens paquets
`common/rtmaps/` et `common/prediction/` sont SUPPRIMÉS (consolidés ici).

---

## 7bis. RÈGLE SYSTÉMATIQUE — tout traitement se déclare (2026-07-20)

> **Tout traitement CHAÎNABLE, existant ou futur, EST déclaré par un `FunctionSpec` dans le
> catalogue.** C'est le pendant de « toute app est dans APP_CATALOG ». **Exception assumée
> (2026-07-22)** : les **libs helper** (parsing, primitives) utilisées PAR des fonctions ne sont
> pas des FunctionSpec — actuellement `io/rtmaps_rec.py` (`parse_rec`), `geometry/shapes.py`
> (`rect_intersect_sat`, `point_traj_to_shape`), `kinematics/extrapolation.py`
> (`extrapolate_speed_accel`, `extrapolate_kalman`), `kinematics/collision.py`
> (`collision_detection`).

Deux `binding` cohabitent dans le MÊME `FUNCTION_CATALOG` :
- **`pure`** — signature `(données_typées, params) → données_typées`, chaînable direct. Défaut pour
  toute nouvelle fonction. Ex. les 4 fonctions toolbox tierce (`wama/common/data/functions/driving/`).
- **`app`** — couplée à une app (lit/écrit la session/BDD via une passe Celery). **Cataloguée** (capacités
  déclarées, `impl` = chemin d'implémentation) mais **pas encore chaînable** ; à porter vers `pure` au cas
  par cas via un adaptateur de ports quand on veut la mettre dans une chaîne.

**Inventaire déclaré à ce jour** (19 fonctions, vérifié au démarrage) :
- **Pures (5)** : `gps_map_match`, `brake_detection`, `generate_sections`, `operator_annotations`,
  `placement_spread` (geometry — indicateur A/B d'étalement RMS, b779395).
- **App-bound cam_analyzer (14)**, déclarées dans `wama_lab/cam_analyzer/function_specs.py`
  (clés **namespacées** `cam_analyzer.<key>`), enregistrées
  via `apps.py::ready` : `yolo_detect`, `yolopv2_lanes`, `sam3_markings`, `distance`, `global_tracking`,
  `artifact_filter`, `ground_calib`, `learned_branches`, `world_markings`, `ortho_recalage`,
  `lane_events`, `temporal_segments`, `conflicts`, `prediction`.

**Checklist à l'ajout d'un traitement (toute app)** :
1. Écrire un `FunctionSpec` (key, name, description, category, tags, inputs/outputs typés, params).
2. `binding='pure'` si possible (impl dans `common/data/`), sinon `'app'` + `impl` + `app`.
3. `register(spec)` (import chargé via l'`apps.py::ready` de l'app) → il apparaît au catalogue.
4. Types d'E/S pris dans la taxonomie `data_types` ; étendre la taxonomie AVANT d'inventer un type.

## 7ter. BORNAGE fonction / librairie / plugin (arbitrage Fabien, 2026-08-19)

> Point d'entrée de la réflexion « monde DATA » ouverte le 19/08 (modèle **BIND** : charger à chaud
> des plugins de visualisation/traitement TOUS SYNCHRONISÉS pendant une session d'analyse — « je
> veux aussi analyser le cardiaque »). Le cadre complet du monde data fera l'objet d'un document
> dédié que Fabien rédigera ; **cette section ne fixe QUE le bornage des objets**, pour qu'il ne
> soit pas re-débattu à chaque fois.

**La limite n'est PAS la taille.** C'est le piège qui a déclenché la discussion (« une fonction
mathématique simple est une fonction, mais mon traitement cardiaque agrège 6 traitements — est-ce
encore une fonction ? »). Le formalisme WAMA borne déjà par le **mode de consommation** :
`library` exige un nom + une version + des dépendances (« *une library sans version n'est pas
installable* », `manifests/builtin/library.py`), `FunctionSpec` exige des ports typés. Ni l'un ni
l'autre ne parle de volume.

> **Règle universelle : on ne classe pas ce qu'une chose EST, on déclare comment elle se CONSOMME.**

| Question (falsifiable) | Oui → | Nature |
|---|---|---|
| Appelable avec des entrées typées → sorties typées, **sans session ni UI** ? | `function` | unité de **calcul** |
| Identité de livraison propre — **nom + version + dépendances** — qu'on installe ? | `library` | unité d'**installation** |
| Se **branche** dans un hôte via un point d'extension déclaré, chargeable **à chaud** par l'utilisateur ? | `plugin` | unité de **montage** |

**Les trois ne s'excluent pas — ce sont des ANGLES, pas des cases.** Le traitement cardiaque est
les trois à la fois : 6 **fonctions** (détection de pics, correction, intervalles RR, rythme…),
chacune chaînable seule dans le studio ; **une librairie** si elle porte ses propres dépendances
et son cycle de version ; **un plugin** pour l'usage « clic bouton » synchronisé en session.
Vouloir un classement EXCLUSIF est précisément ce qui produit les mauvais bornages.

**Appartenance = RELATION, jamais contenance** (précision Fabien) : une fonction reste déclarée au
`FUNCTION_CATALOG` même quand une librairie la regroupe. La librairie ajoute l'écosystème
d'intégration (dépendances, vocabulaire partagé, défauts, adaptateurs) qui rend les fonctions
exploitables par un plugin sans réécrire la glu à chaque fois. Une fonction « dans » une librairie
au sens où elle y disparaîtrait casserait le chaînage studio.

**Ce qui justifie le kind `plugin`** — trois propriétés qu'aucun autre kind ne porte :
1. **un point d'extension** (où ça se branche : canvas studio, axe d'une session data, slot de card) ;
2. **la session partagée** : contrat de synchronisation avec les **pairs co-chargés** (ni fonction
   ni librairie n'ont de pairs) ;
3. **des contributions UI déclarées** (vues, actions, params exposés). Une fonction n'a pas d'UI
   propre : la sienne est DÉRIVÉE de ses ports.

⚠ **Garde-fou anti-fourre-tout** : sans AUCUNE des trois, ce n'est pas un plugin — c'est une
fonction ou une librairie mal nommée. Et **un plugin ne CONTIENT pas de traitement, il en
RÉFÉRENCE** (prolonge §7bis) : sinon il devient une boîte noire et l'héritage studio tombe.

**Inspiration des écosystèmes** (question Fabien « comment GitHub distingue-t-il ? ») : GitHub ne
distingue RIEN — un dépôt est un dépôt. La distinction se fait dans les **registres** (PyPI/npm :
manifeste = nom + version + dépendances + points d'entrée) et les **marketplaces** : un plugin
pytest est un paquet ordinaire qui déclare `entry_points={"pytest11": …}`, une extension VSCode
déclare `contributes` + `activationEvents`. D'où la formule retenue :
**plugin = librairie + point d'extension déclaré (+ contributions UI)**.

**Dimensionnement — aucun objet intermédiaire à inventer.** Des fonctions qui partagent un domaine
sans dépendance ni cycle propres restent des fonctions groupées par `category`/`tags` (champs qui
existent déjà). Elles deviennent une librairie le jour où elles tirent leurs propres dépendances.
Test factuel, pas jugement de taille.

**Studio & profils de pipeline** : un plugin qui DÉCLARE ses fonctions les fait entrer au
`FUNCTION_CATALOG` → elles apparaissent au canvas sans code studio spécifique (héritage de
capacités déjà acté). Une chaîne de plugins enregistrée comme profil réutilisable = le kind
**`pipeline`** existant (`requires` → plugins), `project` par-dessus pour la portée.

**Horizon : auto-instanciation de plugins** (objectif LONG TERME, explicitement pas un chantier).
Transposition de l'auto-génération d'apps du monde média. Le banc codegen du 13/08 a montré que les
écarts décisifs sont des **trous de MATIÈRE**, pas de modèle — un générateur invente ce qu'on ne
lui décrit pas. Prérequis à garder en tête AVANT d'y prétendre :
1. tout traitement déclaré (§7bis) — déjà la règle ;
2. le manifeste `library` doit porter l'**inventaire** des fonctions exposées avec leur
   VOCABULAIRE (unités, noms de champs attendus), pas seulement leurs signatures ;
3. **la vue doit devenir déclarative** — décrite par ce qu'elle CONSOMME (axe x, séries, unités,
   axe de synchronisation), pas par son code de dessin. C'est le vrai verrou : côté média l'UI est
   générée parce que `param_schema` + ports existent ; l'équivalent « vue de données » n'existe pas ;
4. l'axe de session doit être un **contrat explicite** (souscription), sinon aucune synchronisation
   générique n'est possible.
⚠ Ne pas spécifier la « vue déclarative » dans l'abstrait : la route média n'a gagné sa généralité
qu'APRÈS 10 apps réelles. Écrire 2-3 plugins d'abord, extraire ensuite (règle du 2ᵉ consommateur).

## 8. Reste à trancher (quand on implémentera)

- ✅ TRANCHÉ (2026-07-20, c3b009c) — représentation runtime : wrapper **`TypedFrame`**
  (DataFrame + `data_type` + `meta`), cf. `common/data/data_types.py:69`, consommé par les
  fonctions (`placement_metrics` retourne un `TypedFrame(DataType.SCALAR)`).
- Persistance des chaînes (comme les graphes studio) + exécution (réutiliser Celery + le scheduling
  par `cost`).
- Registre : exposé via la page catalogue `/model-manager/functions/` + le kind manifeste
  `function` (repli `UserFunction`). **Reste ouvert** : exposition `tool_api` pour que
  l'assistant IA propose/enchaîne des fonctions.
- Croisement avec le RAG (fonctions descriptibles → héritage université→labo→équipe→user).
