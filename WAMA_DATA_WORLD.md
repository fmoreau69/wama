# WAMA Data — cadre du monde DATA et intégration de BIND

> **Statut : document VIVANT, ouvert le 2026-08-19.** C'est le « document dédié » annoncé par
> `WAMA_DATA_FUNCTION_CARDS.md §7ter` (*« le cadre complet du monde data fera l'objet d'un document
> dédié »*). Il est LA référence du domaine « monde data » : couche temporelle, sessions, plugins
> graphiques, format `.trip`, et intégration de BIND/pynd.
>
> **Ce qu'il ne redit pas** — pour ne pas dupliquer :
> - le **bornage** fonction / librairie / plugin → `WAMA_DATA_FUNCTION_CARDS.md §7ter` (arbitrage figé) ;
> - le descripteur `FunctionSpec` et la taxonomie de types → `WAMA_DATA_FUNCTION_CARDS.md §2, §3` ;
> - la distinction **mécanisme vs plugin de visualisation** → `wama/common/mecanismes.py` (en-tête,
>   arbitrage du 19/08) ;
> - les manifestes et leurs kinds → `WAMA_MANIFEST_SPEC.md`, `WAMA_MANIFEST_ARCHITECTURE.md`.
>
> ⚠ **Règle de rédaction de ce document** : ne consigner comme FAIT BIND que ce qui a été lu dans
> les sources. Tout le reste est marqué `⛏ À CARTOGRAPHIER`. Un plan d'intégration bâti sur des
> suppositions est exactement ce qu'on cherche à éviter.

---

## 1. Pourquoi ce document existe

Objectif posé par Fabien : **ne pas implémenter des bouts de BIND dans WAMA pour découvrir ensuite
qu'il faut tout refaire**, faute d'avoir vu l'ensemble ou d'avoir mal fait converger les deux
philosophies. On pose donc d'abord la description exhaustive, on la confronte au schéma-driven
WAMA, et on n'implémente qu'ensuite.

Deux sources :

| | chemin | nature |
|---|---|---|
| **BIND** | `\\vrlescot\SAVES\DEV\BIND` | framework MATLAB complet (fenêtres OS multiples, plugins à chaud) |
| **pynd** | `\\vrlescot\SAVES\DEV\pynd` | le **cœur** de BIND porté en Python (112 `.py`) — pas la GUI |

---

## 2. La pile temporelle — quatre couches

> Découpage arrêté le 19/08 après recadrage de Fabien : **la gestion du temps est indépendante du
> transport.** Une horloge de lecture (un curseur qui avance) n'est PAS une couche temporelle.

| couche | ce qu'elle sait | ce qu'elle ignore | domicile visé |
|---|---|---|---|
| **1. Référentiel temporel** | bases de temps, origines, dérives, discontinuités, politique de rééchantillonnage **par type de donnée** ; répond `at(t)`, `range(t₀,t₁)`, `next_event(t)`, vue décimée | qu'on lit, qu'il y a une vitesse, qu'il y a un écran | **WAMA Data** (`wama/common/data/`) |
| **2. Curseur de session** | une position, une vitesse, une direction — *dans* le référentiel | la nature des données | session |
| **3. Télécommande** (shuttle / magneto) | émettre des **commandes** de navigation | tout le reste | **brique UI** (`mecanismes.py`, clé `shuttle`) |
| **4. Vues** (plugins graphiques) | dessiner ce que le référentiel rend à `t` | comment le temps est aligné | **plugins** (kind `plugin`) |

**Confirmation par les sources (passe 1)** : `TimerTrip.m` — que je pensais être la couche
temporelle — **est exactement la couche 2**. Il porte `currentTimeInSeconds`, un `multiplier`
signé (négatif = arrière, c'est la vitesse du shuttle), `maxTimeInSeconds`, et notifie
`START` / `STOP` / `GOTO` / `STEP` / `MULTIPLIER_CHANGED` / `PERIOD_CHANGED` à ses observateurs.
Le découpage en 4 couches est donc celui de BIND, avec deux détails à reprendre :

- **le curseur avance en secondes d'horloge murale**, jamais en index d'échantillon :
  `newTime = t + (période × multiplier)` (`TimerTrip.m:354`). C'est *pourquoi* le référentiel doit
  être séparé — le curseur ignore toute cadence de données ;
- **sous charge, BIND dégrade le rafraîchissement, jamais la cohérence du temps** : si un tick
  dépasse 80 % de la période, la période augmente ; s'il tombe sous 20 %, elle redescend jusqu'au
  plancher initial (`TimerTrip.m:369-376`). Règle à reprendre telle quelle.

⚠ **Point de structure à arbitrer (D7)** : dans BIND le curseur est **possédé par le `Trip`**
(`Trip.m:42` — le `Trip` instancie son `TimerTrip` et réémet ses messages). Un trip = une horloge.
Pour WAMA, où une session peut mêler plusieurs sources hétérogènes, il faudra décider si le curseur
appartient au *jeu de données* ou à la *session*.

**Conséquences déjà actées :**

- La couche 1 est le préalable de `Segmenter`, `Calculator`, `Visualizer` et `Analyzer` (§7) : un
  segment est un *intervalle sur le référentiel*, une segmentation conditionnelle un *prédicat sur
  signaux alignés*, un indicateur par situation une *agrégation sur intervalle*. Les trois sont
  minces si la couche existe, impossibles à écrire proprement sinon.
- La couche 3 ne doit **rien** savoir du temps. Elle émet ; elle n'applique pas. C'est la seule
  retouche nécessaire à la brique existante `WamaShuttle` (contrat actuel `apply(speed)` — l'app
  applique à *son* lecteur, ce qui l'attache à un lecteur unique et interdit la forme fenêtrée).
- La couche 4 rejoint le point 4 de l'horizon §7ter : *« l'axe de session doit être un contrat
  explicite (souscription), sinon aucune synchronisation générique n'est possible »*.

---

## 3. Cahier des charges du référentiel temporel

Dérivé des modules visés (§7) et de la taxonomie **existante** `wama/common/data/data_types.py`
(`SIGNAL` avec `fs`, `TIMESERIES`, `EVENTS`, `GEO_TRACK`, tous ancrés sur `time` via
`CANONICAL_FIELDS`, avec sous-typage et `is_compatible`).

1. **Fréquences incommensurables** — GPS 1 Hz, vidéo 25 fps, oculométrie 60 Hz, ECG 1 kHz. Aucun pas
   commun : pas de grille unique, donc requêtes par `t` et non par index.
2. **Origines différentes et dérive** — plusieurs appareils démarrés à des instants distincts, avec
   des horloges qui divergent. C'est le problème que LSL traite à l'enregistrement et qu'un import
   `.xdf` / `.rec` / rosbag doit re-porter.
3. **Discontinuités** — coupures, trous d'acquisition, segments. Le temps n'est pas une droite continue.
4. **Politique de rééchantillonnage portée par le TYPE, jamais par le plugin** :
   - `SIGNAL` / `TIMESERIES` → interpolation déclarée (linéaire, précédent, aucune) ;
   - `EVENTS` → **jamais d'interpolation** (précédent / suivant uniquement) ;
   - `GEO_TRACK` → interpolable, mais pas comme un scalaire.
   > Interpoler linéairement une variable catégorielle est le bug classique de ce genre de couche.
   > La taxonomie existante porte déjà les catégories qui l'empêchent — il faut y adjoindre la politique.
5. **Décimation pour l'affichage** — un plugin traçant 1 kHz sur 2 h ne doit pas recevoir 7,2 M de
   points : le référentiel rend une vue décimée (min/max par pixel). Sans ce contrat, aucun plugin
   de visualisation n'est viable.

**Effet de bord vertueux** : la politique temporelle étant un attribut du *type*, la compatibilité
d'un plugin (mesure prescrite par l'arbitrage du 19/08) devient **vérifiable mécaniquement**.

### 3bis. Ce que BIND répond réellement (passe 1, lu dans les sources)

> ⚠ Deux des cinq exigences ci-dessus reposaient sur une supposition de ma part. Les sources
> disent autre chose, et la réponse de BIND est plus conservatrice — donc plus défendable pour un
> outil scientifique.

| # | ma supposition | ce que BIND fait | source |
|---|---|---|---|
| 4 | politique d'**interpolation** déclarée par type | **BIND n'interpole JAMAIS.** L'API n'expose que `…OccurenceAtTime(name, t)` (valeur exacte) et `…OccurenceNearTime(name, t)` (échantillon le plus proche). Rien entre les deux. | `Trip.m:235-299` |
| 1 | fréquences déduites du signal | la fréquence est **DÉCLARÉE** par donnée : `MetaDatas.frequency INT DEFAULT -1` (−1 = non régulier) | `SQLiteTrip.m:125` |
| 2 | recalage d'origine par source | **seules les VIDÉOS portent un offset** (`MetaTripVideos.offset DOUBLE DEFAULT 0`). Les données sont supposées déjà ramenées à la base de temps du trip **à l'import** (rôle de `rec2trip`) | `SQLiteTrip.m:122` |

**Conséquence de conception majeure** : chez BIND, l'alignement multi-sources est un problème
d'**ingestion**, pas de consultation. Le `.trip` est déjà aligné ; le référentiel n'a donc qu'à
répondre « quelle valeur au plus près de `t` ». C'est ce qui rend la couche simple — et ce qui
déplace la difficulté vers l'Importer.

⚠ **Décision ouverte (D6)** : WAMA reprend-il le « jamais d'interpolation » ? Argument pour :
interpoler silencieusement une mesure scientifique est un faux ami, et ça supprime d'un coup le
bug de la variable catégorielle interpolée. Argument contre : l'affichage d'un signal lent
(GPS 1 Hz) sous un curseur à 25 fps devient un escalier. Position pressentie : **reprendre la règle
BIND pour la VALEUR, autoriser l'interpolation comme option explicite d'AFFICHAGE seulement.**

⛏ **Reste à cartographier ici** : ce que `pynd` a retenu ou abandonné de ce contrat (passe 4).

---

## 4. Plugins graphiques — ce que BIND apporte au bornage déjà figé

Le kind `plugin` est justifié par trois propriétés (§7ter) : point d'extension, session partagée
avec les pairs co-chargés, contributions UI déclarées. BIND en est l'implémentation de référence.

### 4.1 Le manifeste d'un plugin BIND — des méthodes STATIQUES (passe 2)

`Plugin.m` est la racine, purement sémantique, et son contenu est un **manifeste déclaré en
statique** :

| méthode statique | rôle |
|---|---|
| `getName()` | nom lisible |
| `isMultiTrip()` | **capacité** : traite un seul trip (false) ou plusieurs (true) |
| `getConfiguratorClass()` | nom qualifié de la classe **configurateur**, ou chaîne vide s'il n'y en a pas |
| `isInstanciable()` | défaut **false** ; surchargé à `true` par les plugins « réels » — son but déclaré est de **permettre la RECHERCHE des plugins dans le path** |

> **C'est le mécanisme de découverte** : pas de registre central, pas de fichier d'enregistrement.
> BIND balaie le path MATLAB et interroge chaque classe. C'est l'équivalent idiomatique des
> `entry_points` de Python — et donc la confirmation de la formule §7ter :
> **plugin = librairie + point d'extension déclaré**.

### 4.2 La hiérarchie de templates

Un plugin concret ne dérive **jamais** de `Plugin` directement, mais d'un template abstrait :

| template | hérite de | rôle |
|---|---|---|
| `TripPlugin` | `Plugin` + `Observer` | analyse pilotée par le temps sur **un** `Trip` |
| `GraphicalPlugin` | `Plugin` + `Observer` | possède **une fenêtre** (figure MATLAB) + le `KeyPressManager` |
| `MultiGraphicalPlugin` | `Plugin` + `Observer` | fenêtre, mais non liée à un trip unique |
| **`VisualisationPlugin`** | `GraphicalPlugin` **+** `TripPlugin` | **le template standard** : fenêtre + synchronisation sur un trip (`isMultiTrip = false`) ; sait se **relier à un autre trip à chaud** (`changeCurrentTrip`) |
| `AnalysisPlugin` | `Plugin` | statistiques / filtrage, **asynchrone**, sur plusieurs trips (via un objet `Experimentation` ⛏ non encore lu) |
| `TripStreamingPlugin` | `TripPlugin` | **affiche seulement les données d'une fenêtre temporelle, « to avoid loading the whole data »** |
| `EncodingPlugin` | — | 7 lignes, quasi vide ⛏ |

### 4.3 Le contrat de synchronisation — un seul canal, des messages typés

Tout passe par **Observer/Observable**, et c'est le contrat explicite que §7ter (point 4) réclamait :

- le `Trip` **possède** son `TimerTrip` et **réémet** ses messages à ses propres observateurs
  (`Trip.m:66-68`) ;
- un plugin s'abonne au trip dans son constructeur (`addObserver`) et se désabonne dans son
  `delete()`, **en notifiant les pairs** (`OBSERVER_REMOVED`, `TripPlugin.m:68-73`) ;
- il reçoit donc sur **un seul `update(message)`** les deux familles : `TimerMessage`
  (`START` / `STOP` / `GOTO` / `STEP` / `MULTIPLIER_CHANGED` / `PERIOD_CHANGED`) et `TripMessage`
  (`DATA_*` / `EVENT_*` / `SITUATION_*` / `TRIP_META_CHANGED`), et dispatche sur la **classe** du message.

> **Montage / démontage explicites** : BIND écrit à la main, dans `delete()`, l'inverse de ce que
> le constructeur a fait. C'est exactement le problème que Cordis (DeepSeek Harness) formalise en
> « effets réversibles » — et que WAMA tient déjà au niveau manifeste avec
> `write_back` / `un_write_back`. Trois systèmes, trois granularités, même besoin.

### 4.4 Le clavier — un singleton qui diffuse à tous

`KeyPressManager` est un **singleton** auquel chaque `GraphicalPlugin` s'abonne. Toute frappe
captée par n'importe quelle fenêtre est rediffusée à **tous** les plugins graphiques sous forme de
`KeyMessage`. La docstring l'assume : *« if several plugins share some reactions to the same key
combinations, ALL the plugins will react, no matter which one has the focus »*.

> C'est ainsi que J/K/L du magneto pilotent la lecture depuis n'importe quelle fenêtre. C'est aussi
> une **verrue connue** : aucun plugin ne peut « capturer » un raccourci. Dans un navigateur le
> problème est plus simple (un seul document), mais la question de **qui possède un raccourci**
> devra être tranchée — ne pas reproduire le « tout le monde réagit ».

### 4.5 Amorce de vue déclarative — déjà présente

`TripStreamingPlugin` porte `dataName` et `variableName` (tableaux parallèles indexés) : le plugin
**déclare ce qu'il consomme**. C'est un précédent direct du verrou §7ter point 3 (*« la vue doit
devenir déclarative — décrite par ce qu'elle CONSOMME »*), et une preuve que la marche est
franchissable — BIND l'a franchie à moitié.

⛏ **Reste à cartographier** : la classe `Experimentation` ; la répartition `configurators` /
`loading` / `widgets` annoncée par Fabien (elle n'apparaît pas dans `BIND_core/+plugins` — donc
probablement côté `BIND_plugins` ou `BIND_GUI`, à confirmer en passe 3).

**Correspondance pressentie avec l'existant WAMA** (à confirmer/infirmer par la cartographie) :

| BIND | WAMA | état |
|---|---|---|
| `configurators` | schéma `Param` + `WamaParams` (registry de renderers depuis le 19/08) | ✅ existe |
| `loading` | `data_types.py` + `FUNCTION_CATALOG` (compatibilité de types) | 🔄 domicile décidé |
| `plugins` | registre de rendus (cascade mime → registre) | ⏳ palier annoncé (`mecanismes.py:329`) |
| `widgets` | briques UI = mécanismes | ✅ existe |
| noyau de plugins (cycle de vie, pairs, axe) | — | ❌ **le trou** |

---

## 5. Le magneto — spécification reprise de BIND

> Spécification établie par Fabien avec les stagiaires ; **plus complète que tout ce qui existe
> côté WAMA aujourd'hui**. Reprise telle quelle comme cible de la brique `shuttle`.
> Source : `BIND_plugins/src/+fr/+lescot/+bind/+plugins/Magneto.m`.

**Contrôle de lecture** : lecture/pause · avance/recul image par image · lecture avant/arrière ·
slider de vitesse **continu (float), centré sur 0, échelle logarithmique, symétrique**
(droite = avant, gauche = arrière), `max_speed` réglable à l'init (défaut ×32) · timeline de
position · « fermer tous les plugins » · « ramener tous les plugins au 1ᵉʳ plan ».

**Raccourcis** : `espace` lecture/pause · `←`/`→` image par image · `↑`/`↓` début/fin ·
`J`/`K`/`L` lecture arrière/stop/avant · `+`/`-` vitesse · `Ctrl+A` afficher les plugins ·
`Ctrl+Q` fermer les plugins.

**Télécommande ShuttlePro** : molette → slider de vitesse · bague centrale → slider de position ·
boutons → raccourcis clavier.

**Écart avec l'existant WAMA** : `WamaShuttle` (`wama/common/static/common/js/wama-shuttle.js`)
n'a que J/K/L par **paliers discrets** (`DEFAULT_LEVELS`), pas de pas image, pas de timeline, pas
de ShuttlePro. Le Transcriber en a une **copie locale** (`transcriber/static/transcriber/js/edit.js:283-320`)
avec lecture arrière par pas manuel — duplication à résorber APRÈS que le commun ait rattrapé la spec.

⚠ **Question ouverte (Fabien, 19/08)** : dans BIND le magneto est un *plugin* (fenêtre indépendante
invocable à chaud). Dans WAMA il peut être **la même brique UI** avec deux chromes — placement fixe
(cam_analyzer) ou fenêtré. Position retenue : *une brique, deux présentations*, à condition qu'elle
émette des commandes au lieu d'agir sur un lecteur.

### 5bis. Ce que `Magneto.m` dit vraiment (lu le 2026-08-20)

`classdef Magneto < GraphicalPlugin & TripPlugin` — **même double héritage que `VisualisationPlugin`** :
le magneto est un plugin graphique ordinaire, pas un objet à part. Sa docstring porte la phrase
architecturale la plus importante du corpus :

> *« This class instanciates a **panel** that allow to control the trip, **and by extension all the
> plugins that observe the trip** »* (`bind:BIND_plugins/src/+fr/+lescot/+bind/+plugins/Magneto.m:3-4`)

**Le magneto ne parle JAMAIS aux plugins.** Il pilote le `Trip` (donc le `TimerTrip` que celui-ci
possède), et la synchronisation de toutes les vues est une *conséquence* du graphe d'observateurs.
C'est exactement le contrat « émettre une commande, ne pas agir sur un lecteur » proposé pour
`WamaShuttle` — BIND le tient déjà, par construction.

> Conséquence pour WAMA : la question « brique UI ou plugin ? » perd son enjeu. Ce qui compte est
> **sur quoi elle agit** : le curseur, jamais les vues. Le chrome (panneau fixe ou fenêtre) devient
> un détail de présentation, ce qui valide la position « une brique, deux présentations ».

Organisation interne relevée : *simple commands panel* (stop, play, play backward, slider de
position) · *time panel* (temps courant, temps restant) · *advanced command panel* (rembobinage à
vitesse variable…). ⛏ Le détail des commandes avancées et le mapping ShuttlePro restent à lire.

---

## 6. Le format `.trip`

**Établi (passe 1, lu dans `SQLiteTrip.m`)** : `.trip` est une base **SQLite** (outillage `sqlite4m`),
avec un schéma en deux étages — un **catalogue de métadonnées fixe**, et des **tables de contenu
créées dynamiquement, une par élément**.

### 6.1 Le modèle en trois familles

`TripMessage.m` fixe le vocabulaire : tout contenu d'un trip est **`Data`**, **`Event`** ou
**`Situation`**, chacun avec les mêmes cinq verbes (`ADDED`, `REMOVED`, `VARIABLE_ADDED`,
`VARIABLE_REMOVED`, `CONTENT_CHANGED`), plus `TRIP_META_CHANGED`.

| famille | temps | équivalent WAMA (`data_types.py`) |
|---|---|---|
| **Data** | `timecode` — échantillonné, fréquence déclarée | `SIGNAL` / `TIMESERIES` ✅ |
| **Event** | `timecode` — occurrence ponctuelle | `EVENTS` ✅ |
| **Situation** | `startTimecode` + `endTimecode` — **intervalle** | ❌ **rien n'existe** |

> ⚠ **Trou identifié dans WAMA** : la taxonomie n'a pas de type « intervalle ». Or c'est
> exactement ce que produit le **Segmenter** et ce que consomme le **Calculator** (« indicateurs
> par situation »). À arbitrer : nouveau `DataType.INTERVALS`, ou sous-type d'`EVENTS` avec durée.

Noms réservés (`Trip.m:18`) : `timecode`, `startTimecode`, `endTimecode`.
> Divergence de vocabulaire : WAMA utilise `time` (`CANONICAL_FIELDS`). À réconcilier au moment de
> l'Importer, pas avant.

### 6.2 Catalogue de métadonnées (tables fixes)

```sql
MetaTripDatas        (key, value)                                  -- attributs libres du trip
MetaParticipantDatas (key, value)                                  -- attributs du participant
MetaTripVideos       (filename, offset DOUBLE DEFAULT 0, description)
MetaDatas            (name, type, frequency INT DEFAULT -1, comments, isBase BOOL DEFAULT 0)
MetaDataVariables    (data_name, name, type DEFAULT "REAL", unit, comments)
MetaEvents           (name, comments, isBase BOOL DEFAULT 1)
MetaEventVariables   (event_name, name, type, unit, comments)
MetaSituations       (name, comments, isBase BOOL DEFAULT 1)
MetaSituationVariables (situation_name, name, type, unit, comments)
```

Trois choses à retenir :

- **`unit` est déclarée par variable** — c'est précisément le « vocabulaire » que §7ter (point 2 de
  l'horizon) exige d'un manifeste `library` pour espérer générer quoi que ce soit ;
- **`frequency` est déclarée par `Data`** (−1 = non régulier) — l'hétérogénéité des cadences est
  documentée, pas devinée ;
- **`isBase`** distingue le contenu **acquis** du contenu **dérivé** (défaut 0 pour les `Data`,
  1 pour `Event`/`Situation`) : c'est la provenance, et donc le socle de tout recalcul par le
  Calculator. `TripSet` sait l'interroger (`checkIsBaseData/Event/Situation`).

### 6.3 Tables de contenu (créées dynamiquement)

Une table **par** data/event/situation : `CREATE TABLE "<prefix>_<name>" (…)` (`SQLiteTrip.m:1972`),
avec `timecode` (ou `startTimecode`/`endTimecode`) en clé primaire et **une colonne par variable**.
Un index est créé par colonne (`SQLiteTrip.m:2500`). Les timecodes sont écrits en `%.12f`.

> C'est la réponse de BIND au stockage haute fréquence : pas de blob, pas de table unique
> polymorphe — **une table native par signal, indexée**, et on laisse SQLite faire son travail.
> Écriture par lots (`setBatchOf…`) et **transactions** (`beginTransaction` / `commit` /
> `rollback`, `Trip.m:1197-1221`).

### 6.4 `TripSet` — le corpus, pas la synchronisation

Contrairement à ce que le nom suggère, `TripSet` **n'orchestre aucun temps**. C'est la couche
**corpus/étude** : agrégation de métadonnées sur N trips — propriétés communes vs possibles,
valeurs d'attributs pour tous les trips, variables d'événements/situations partagées, le tout avec
un `mode` d'agrégation. Autrement dit : *« quelles données ai-je en commun sur l'ensemble de mes
sujets ? »*

> Rattachement WAMA pressenti : c'est le niveau **`dataset`** / **`project`** des kinds existants,
> pas une brique temporelle.

⛏ **Reste à cartographier** : ce que `rec2trip` (pynd) convertit et depuis quoi (passe 4) ;
la sémantique exacte du `mode` d'agrégation de `TripSet`.

---

## 7. Modules et applications WAMA-Data (périmètre visé)

> Liste posée par Fabien le 19/08. **Application** = UI standalone accessible depuis le studio ;
> **Module** = UI minimaliste intégrée dans une application ou accessible depuis le studio.

| nom | rôle | origine BIND |
|---|---|---|
| **Recorder** | enregistrement depuis LSL, RTMaps, ROS | — |
| **Importer** | LSL `.xdf`, RTMaps `.rec`, rosbag `.ros`, dataframes `.dt`, fichiers `.xlsx/.csv/.txt` | `rec2trip` (pynd) |
| **Exporter** | export tables complètes / table personnalisée | BIND_GUI (implémenté) |
| **Connector** | connexion à une base SQLite | `.trip` |
| **Explorer** | exploration table / graphe | — |
| **Segmenter** | segmentation temporelle simple/double, conditionnelle (connecteurs de conditions), codage vidéo, filtrage | BIND_GUI (implémenté) |
| **Calculator** | transformation de colonnes (dérivée, fenêtrage, fixations oculaires, rythme cardiaque…), indicateurs par situation (moyenne, min, max, écart-type…) | BIND_GUI (**non implémenté**) |
| **Visualizer** | lancement des plugins graphiques | BIND_GUI |
| **Analyzer** | équivalent BIND_GUI — intègre tous les modules d'exploitation | BIND_GUI |

**Transversal — sauvegarde de l'environnement de travail** : presets de configurations trips/plugins,
paramètres de process.
> **Position retenue** : c'est un **manifeste**, pas un dump de session — composition déclarative
> (plugins chargés + leur configuration + position du curseur + trips) dans un vocabulaire fermé,
> donc rejouable et diffable. Rattachement pressenti aux kinds `project` / `dataset` existants.

---

## 8. Confrontation au schéma-driven WAMA

Ce que WAMA a déjà et qui sert directement :

- `data_types.py` — taxonomie typée avec sous-typage et `is_compatible` (**le socle**) ;
- `FUNCTION_CATALOG` / `FunctionSpec` — ports typés, chaînage studio ;
- `WamaParams` + `Param` — configurateurs générés, **extensibles par renderer keyé** depuis le 19/08 ;
- manifestes 7 kinds avec `write_back` / `un_write_back` — effets réversibles au build ;
- `mecanismes.py` — registre des briques transversales et de leur adoption.

Ce qui manque, par ordre de blocage :

1. **le référentiel temporel** (§3) — rien n'existe ;
2. **le noyau de plugins** : cycle de vie, pairs, souscription à l'axe (§4) ;
3. **la vue déclarative** — verrou identifié en §7ter point 3 : décrire une vue par ce qu'elle
   CONSOMME (axe x, séries, unités, axe de synchronisation) et non par son code de dessin.
   ⚠ Garde-fou §7ter : **ne pas spécifier dans l'abstrait** — écrire 2-3 plugins d'abord, extraire
   ensuite (règle du 2ᵉ consommateur) ;
4. le conteneur de vues : **layout dockable + détachement en vraie fenêtre** (`window.open` +
   `BroadcastChannel`), jamais un gestionnaire de fenêtres simulé en `div` absolus.
   > Amorce existante : `audio_player` gère déjà l'exclusivité **inter-onglets** (`mecanismes.py:333`).

---

## 9. Cartographie de BIND — périmètre et méthode

**Périmètre retenu (~460 fichiers sur 4305)** :

| inclus | fichiers | |
|---|---|---|
| `BIND_core` | 249 `.m` | noyau : kernel, plugins, processing, utils |
| `BIND_plugins` | 59 `.m` | implémentations, dont `Magneto.m` |
| `BIND_plugins_coding` | 35 `.m` | plugins de codage |
| `BIND_GUI` | 5 `.m` | mince — l'essentiel est dans les plugins |
| `pynd` | 112 `.py` | le cœur en Python |
| `BIND_doc` | 179 HTML | **NaturalDocs : API déjà structurée, entrée la moins chère** |

**Exclus** : `BIND_scripts` (979 `.m`, analyses résiduelles), `Matjab`, `sqlite4m`, `NaturalDocs4Matlab`,
`BIND_packagers`, `dependencies`, `gmapsBot`, `DShow*4BIND`, `XUPy`, `BIND_GS`.

**Outillage (mis en place le 2026-08-20 — réutilisable pour tout autre framework)** :

| brique | rôle |
|---|---|
| `wama-dev-ai/corpus.py` | accès **nommé et en lecture seule** aux dépôts externes — `bind:`, `pynd:` ; périmètre déclaré ; évasion de racine refusée ; écriture refusée ; **décodage `.mlapp`** (ZIP → source MATLAB) |
| `wama-dev-ai/prompts/cartography.txt` | la **méthode** : preuves obligatoires (`file`+`line`+`evidence`), règle anti-invention, `coverage` obligatoire, pas de `suggested_actions` |
| `.claude/skills/cartographie/` | le **séquençage** : préconditions, découpage en passes, relecture critique, consignation. Déclare `prompt: cartography` — la méthode n'est pas dupliquée |
| `run_audit.py --prompt` | sélection du prompt (était codé en dur sur `audit.txt`) |

> ⚠ **On n'a pas copié les sources** (arbitrage Fabien) : un doublon dans le dépôt dérive dès la
> première modification en amont. Le corpus reste la source.
>
> ⚠ **Piège rencontré, désormais gardé** : un prompt sans `{tools}`/`{task}` produit un échec
> SILENCIEUX (rapport de 0 octet, code de sortie 0). `run_audit` refuse maintenant de démarrer.
>
> ⚠ **Ne jamais `--force-model`** : la garde VRAM écarterait sinon silencieusement qwen3.8 au
> profit d'un modèle plus petit, sans aucun signal — cartographie médiocre sans le savoir.
> Le service TTS (kokoro) tient de la VRAM : arrêter WAMA avant une passe.

**Méthode en passes** (chacune produit un livrable écrit, aucune n'implémente) :

| # | passe | outil | livrable |
|---|---|---|---|
| 0 | inventaire structurel + extraction de l'API depuis `BIND_doc` | déterministe (script) | table classes / responsabilités |
| 1 | noyau temporel : `TimerTrip`, `Trip`, `TripSet`, `TripMessage`, `SQLiteTrip` | lecture dirigée | §3 et §6 remplis |
| 2 | noyau de plugins : `TripPlugin`, `TripStreamingPlugin`, cycle de vie, pairs | lecture dirigée | §4 rempli |
| 3 | plugins réels (Magneto, DataPlotter, GpsViewer, EventSituation*, Annotation) | wama-dev-ai (volumineux, read-only) | inventaire des contributions UI et de leurs besoins |
| 4 | `pynd` : ce que le portage Python a retenu et abandonné | wama-dev-ai | écart MATLAB→Python déjà payé |
| 5 | confrontation au schéma-driven + plan d'intégration ordonné | Claude | §8 arbitré, ROADMAP |

**État au 2026-08-20** :

| passe | état | livrable |
|---|---|---|
| 0 | ✅ faite | inventaire ci-dessus (~460 fichiers retenus sur 4305) |
| 1 | ✅ **faite** | §2 (confirmation couche 2), §3bis (corrections), §6 (schéma `.trip` complet) — lus : `TimerTrip.m`, `TripMessage.m`, `Trip.m`, `TripSet.m`, `SQLiteTrip.m` |
| 2 | ✅ **faite** | §4 (manifeste statique, hiérarchie de templates, contrat de synchronisation, clavier, amorce de vue déclarative) — lus : `Plugin.m`, `TripPlugin.m`, `GraphicalPlugin.m`, `VisualisationPlugin.m`, `MultiGraphicalPlugin.m`, `AnalysisPlugin.m`, `TripStreamingPlugin.m` |
| 3 | 🔄 **lancée** 20/08 | plugins réels (`Magneto`, `DataPlotter`, `GpsViewer`, `EventSituation*`, `Annotation`) — wama-dev-ai / qwen3.8. Questions : ce que chaque plugin DÉCLARE consommer · existence réelle du découpage configurators/loading/widgets · `Magneto` en détail · classe `Experimentation` · résidus |
| 4 | ⏳ wama-dev-ai | `pynd` : ce que le portage Python a retenu / abandonné, et `rec2trip` |
| 5 | ⏳ à faire | confrontation §8 arbitrée + plan d'intégration ordonné |

---

## 10. Décisions en attente

| # | question | qui tranche |
|---|---|---|
| D1 | domicile du référentiel temporel : `wama/common/data/` ou module dédié ? | après passe 1 |
| D2 | le magneto : une brique à deux chromes, ou brique + plugin distincts ? | après passe 2 |
| D3 | `.trip` : format importé/converti, ou format natif supporté par WAMA Data ? | après passe 1 |
| D4 | quels 2-3 plugins écrire en premier (pour extraire la vue déclarative ensuite) ? | après passe 3 |
| D5 | Recorder temps réel (LSL/RTMaps/ROS) : dans le périmètre v1 ou différé ? | Fabien |
| D6 | reprendre le « **jamais d'interpolation** » de BIND ? (position pressentie : oui pour la VALEUR, interpolation autorisée en option d'AFFICHAGE seulement) | Fabien, §3bis |
| D7 | le curseur appartient-il au **jeu de données** (choix BIND : un trip = une horloge) ou à la **session** (plusieurs sources hétérogènes) ? | après passe 2 |
| D8 | type « **intervalle** » dans `data_types.py` : nouveau `DataType.INTERVALS`, ou sous-type d'`EVENTS` avec durée ? (sans lui, pas de Segmenter ni de Calculator) | après passe 3 |
| D9 | vocabulaire temporel : garder `time` (WAMA) ou adopter `timecode`/`startTimecode`/`endTimecode` (BIND) ? — tranché au plus tard à l'écriture de l'Importer | différable |

---

## Journal

- **2026-08-19** — ouverture. Pile en 4 couches arrêtée (recadrage Fabien : gestion du temps ≠
  transport). Périmètre de cartographie établi (~460 fichiers). Spec magneto consignée depuis BIND.
  `.trip` = SQLite (établi). Aucune implémentation engagée.
- **2026-08-20** — **passe 1 faite** (noyau temporel + format). Trois corrections à mes hypothèses :
  `TimerTrip` est le *curseur*, pas la couche temporelle ; BIND **n'interpole jamais** ; l'alignement
  multi-sources est un problème d'**ingestion** (offset sur les vidéos seules), pas de consultation.
  Deux trous WAMA identifiés : **pas de type « intervalle »** (bloque Segmenter + Calculator), et
  divergence de vocabulaire `time` ↔ `timecode`. Décisions D6→D9 ajoutées.
  Toujours aucune implémentation engagée.
- **2026-08-20** — **passe 2 faite** (noyau de plugins). Le manifeste d'un plugin BIND est un jeu de
  **méthodes statiques** découvertes par balayage du path (`isInstanciable`) — confirmation directe
  de la formule §7ter « plugin = librairie + point d'extension déclaré ». Contrat de synchronisation
  identifié : **un seul canal Observer, deux familles de messages typés** — c'est le contrat
  explicite que §7ter point 4 réclamait. Amorce de **vue déclarative** trouvée dans
  `TripStreamingPlugin` (le plugin déclare les data/variables qu'il consomme). Verrue à ne pas
  reproduire : diffusion clavier à TOUS les plugins sans notion de capture.
