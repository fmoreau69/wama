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

## 0. ÉTAT D'AVANCEMENT — mesuré, jamais écrit

> **C'est le point d'entrée du chantier.** Le reste du document porte la vision, la cartographie et
> le plan ; cette section dit **où on en est réellement**, et elle est régénérée depuis le code.
>
> Pourquoi mesurée : `PROJECT_STATUS §39` annonçait « 10 DataType » et « 19 fonctions » quand le
> réel était 11 et 31, en ignorant deux briques entières — et personne ne l'avait corrigé. Un état
> écrit à la main dérive **toujours**. Ajouter un `.md` de statut aurait reproduit le défaut ;
> mesurer l'empêche par construction.

<!-- WAMA:FAITS(wama_data) — généré par « python manage.py doc_facts », ne pas éditer -->
> Mesuré depuis le code — **ne pas éditer à la main** (`python manage.py doc_facts`).
> Registre des modules : `wama/common/data/modules.py`.

**Bilan** : 7 ⏳ (non commencé) · 3 🔶 (livré mais INERTE)

> 🔶 **AUCUN consommateur hors `common/data/` — le sous-système entier est INERTE.** Aucune app, tâche ou route ne s'en sert encore : les briques s'appellent entre elles, et c'est tout. Le premier module à donner un usage réel fera basculer ces lignes en ✅.

| Module | Rôle | Flux | État | Briques | Testées | Conso. int/ext | Doc |
|---|---|---|---|---|---|---|---|
| **Importer** | Lit une source et rend un référentiel temporel interrogeable | fichiers + manifeste `dataset` → référentiel | 🔶 | 3/3 | 1 | 1/0 | §6.6, §9bis.1 |
| **Référentiel temporel** | Aligne des flux à cadences incommensurables | référentiel → échantillons, `segments`, vue décimée | 🔶 | 1/1 | 1 | 3/0 | §2, §3 |
| **Connector** | Branche une base existante comme source | base SQLite → référentiel | 🔶 | 1/1 | 0 | 1/0 | §6.2 |
| **Explorer** | Explore un dataset en table et en graphe | référentiel → vues | ⏳ | — | — | — | §7 |
| **Segmenter** | Produit des segments : autour d'un événement, par prédicat, ou par plages constantes d'un catégoriel | `events` ou signal + prédicat → `segments` | ⏳ | — | — | — | §9ter (spécification), §6.7 |
| **Calculator** | Calcule des indicateurs PAR SEGMENT et les y adjoint | `segments` + signaux → colonnes d'indicateurs | ⏳ | — | — | — | §6.7 |
| **Visualizer** | Vues synchronisées sur l'axe partagé (plugins) | référentiel → plugins co-chargés | ⏳ | — | — | — | §4, §8.2 |
| **Exporter** | Rend les segments et indicateurs exploitables hors WAMA | `segments` + indicateurs → fichiers (pivot long → large) | ⏳ | — | — | — | §6.7 |
| **Recorder** | Enregistre depuis une source temps réel | flux LSL/RTMaps/ROS → `dataset` | ⏳ | — | — | — | §7 |
| **Analyzer** | Orchestre les modules selon un manifeste `pipeline` | manifeste `pipeline` → exécution | ⏳ | — | — | — | §9bis.2 |

<details><summary>⚠ <b>7 module(s) avec un blocage déclaré</b> — ce qui empêche d'avancer, en une ligne</summary>

- **Importer** — alignement par TRIGGERS non conçu (D12) ; `DATASET_SOURCES` non réconcilié avec le registre des lecteurs (G1) ; lecteur `.rec` encore une FONCTION (`functions/io/rtmaps_rec.py`) au lieu d'un lecteur de source
- **Référentiel temporel** — AUCUN consommateur — la brique est inerte tant qu'un module ne s'en sert pas
- **Segmenter** — SPÉCIFIÉ (§9ter) mais non écrit — 8 modes tirés des 3 sources. ⚠ le modèle actuel ne sait pas représenter un segment OUVERT (fin inconnue), D15
- **Calculator** — même angle mort que le Segmenter ; dépend de lui
- **Visualizer** — vue déclarative = verrou §7ter point 3 ; écrire 2-3 plugins AVANT d'extraire
- **Recorder** — périmètre v1 non tranché (D5)
- **Analyzer** — nœud FONCTION absent du kind `pipeline` (D13)

</details>
<!-- /WAMA:FAITS(wama_data) -->

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
| 1 | fréquences déduites du signal | le schéma PRÉVOIT une fréquence déclarée (`MetaDatas.frequency INT DEFAULT -1`) — ⚠ **mais elle vaut 0 pour les 10 flux d'un trip réel**, voir §6.7 : la cadence est EMERGENTE, pas déclarée | `SQLiteTrip.m:125` + mesure |
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

### 4.6 Le PIPELINE DE MONTAGE (passe 3) — et la réponse à « que déclare un plugin ? »

> Le découpage annoncé par Fabien (`configurators` / `loading` / `plugins` / `widgets`) est
> **intégralement confirmé**. Il n'était pas dans `BIND_core/+plugins` : ce sont quatre **packages
> parallèles**, ce qui explique que la passe 2 ne l'ait pas vu.

| package | domicile | rôle |
|---|---|---|
| `+loading` | `BIND_core` — **`Loader.m` (933 l.)** | découvre les plugins, calcule ce qui est utilisable, instancie, sauvegarde l'environnement |
| `+configurators` | `BIND_core` (contrat, 4 classes) + `BIND_plugins` (**18 impls**) | GUI de paramétrage par plugin |
| `+widgets` | `BIND_plugins` | briques de sélection réutilisées : `VariablesSelector`, `EventSituationSelector`, `EventSituationList`, `PositionChooser` |
| `+plugins` | `BIND_core` (templates) + `BIND_plugins` (impls) | les plugins eux-mêmes |

**Le contrat de configuration** (`BIND_core/+configurators/`) :

- **`Argument`** = un argument d'appel du constructeur du plugin : `name`, `isOptionnal`, `value`,
  `order` (position 1 réservée au plugin). Optionnel ⇒ le nom sert de clé (syntaxe clé/valeur MATLAB).
- **`Configuration`** = collection ordonnée d'`Argument`s, avec unicité de l'`order` vérifiée.
- **`ConfiguratorUser`** = interface de rappel à un seul verbe : `receiveConfiguration(pluginId, configuration)`.
- **`PluginConfigurator`** = fenêtre modale construite avec `(pluginId, metaTrip, caller, [configuration])`,
  où **`metaTrip` est le catalogue de ce qui est disponible** — *« the MetaInformations object that
  contains all the data and variables the plugin should be able to **propose** »*.

> ### ⭐ Le point le plus important de la passe 3
>
> **Un plugin BIND ne déclare PAS ce qu'il consomme.** Le liage donnée↔plugin est résolu par
> l'**UTILISATEUR au moment du montage** :
>
> 1. le `Loader` calcule un `MetaInformations` = catalogue des `Data`/`Event`/`Situation` et de leurs
>    variables réellement présentes dans le trip ;
> 2. il le passe au **configurateur** du plugin (que le plugin nomme via `getConfiguratorClass`) ;
> 3. le configurateur **propose** ce catalogue à l'utilisateur, via des widgets réutilisables
>    (`VariablesSelector(figureHandler, metaTrip, 'DATA', …)`, `DataPlotterConfigurator.m:138`) ;
> 4. l'utilisateur choisit ; le configurateur émet une `Configuration` ;
> 5. le rappel `receiveConfiguration` rend le tout au `Loader`, qui instancie le plugin avec ces
>    arguments (`addPluginWithConfiguration`).
>
> Exemple réel — `DataPlotterConfigurator` produit : `dataIdentifiers`(2, les variables choisies),
> `position`(3), `timeWindow`(4), `scaleMode`(5), `scale`(6), `colors`(7), `lineTypes`(8), `markers`(9).

**Ce que ça coûte, et ce que ça dit pour WAMA.** Le prix de ce choix est **18 GUI écrites à la main**
— `DataPlotterConfigurator.m` fait **802 lignes**. Et `Argument.value` n'est *« une chaîne ou un
tableau de chaînes »* : **aucun système de types**, pas d'unité, pas de bornes, pas de choix
énumérés. Le typage vit dans la GUI, en dur, une fois par plugin.

> **C'est exactement l'inverse de WAMA**, dont le `Param` porte type, choix, unité, bornes,
> `show_if`, et dont l'UI est **générée**. Autrement dit : *WAMA peut GÉNÉRER ce que BIND écrit à la
> main* — à condition qu'un plugin déclare ce qu'il consomme en **types de données** plutôt que de
> livrer une GUI sur mesure. C'est précisément le verrou « vue déclarative » de §7ter point 3, et on
> sait désormais ce qu'il remplace : 18 configurateurs, ~4000 lignes.

**Deux mécanismes du `Loader` à reprendre** :

- **`validateConfiguration(metaInformations, configuration)`** — méthode **statique du configurateur**,
  appelée par `isPluginConfigurationValid(pluginId, metaInformations)`. Elle vérifie qu'une
  configuration **enregistrée** reste valide face au catalogue d'un **autre** trip. C'est la mesure de
  **compatibilité** que l'arbitrage du 19/08 prescrit pour un plugin — BIND l'a, écrite à la main par
  configurateur. Chez WAMA elle serait **dérivable** de `is_compatible()` sur les types.
- **`getTripsCommonMetaInformations()`** — sur un `TripSet`, on ne propose que ce qui est **commun à
  tous les trips**. La compatibilité au niveau du corpus, gratuitement.

**Sauvegarde d'environnement — le mécanisme existe déjà** : `Loader` sauvegarde/recharge un
environnement par fichier (`saveEnvironment`/`loadEnvironment`), contenant `pluginSet` +
`pluginConfigurationSet` + le `TripSet`. C'est exactement le « Presets de configurations
trips/plugins » de §7, et sa composition (plugins + leurs configurations + trips) **confirme la
position retenue : c'est un manifeste**, pas un dump de session.

### 4.7 Les 18 plugins réels — héritage et déclarations

| template | plugins |
|---|---|
| **`GraphicalPlugin & TripStreamingPlugin`** (8) | `DataPlotter` · `Annotation` · `AtlasCoding` · `AtlasRRverification` · `RCE2Coding` · `RCE2RRverification` · `ValueDisplay` · `ContinentalTechnologiesViewer` (+ `XMPPStreamer`, ordre inversé) |
| `GraphicalPlugin & TripPlugin` (4) | `Magneto` · `MessageDisplay` · `EventSituationBrowser` · `GpsViewer` (ordre inversé) |
| `VisualisationPlugin` (3) | `EventSituationDisplay` · `SituationDisplay` · `VideoSynchroniser` |
| `TripPlugin` seul (2) | `VideoPlayer` · `MockUpTripPlugin` |

**Le template dominant est `TripStreamingPlugin`** — *« display some scrolling datas contained in a
certain timeframe **to avoid loading the whole data** »*. La lecture par FENÊTRE temporelle est donc
la norme chez BIND, pas l'exception. Ça confirme §3.5 : sans contrat de fenêtrage/décimation, aucun
plugin de visualisation n'est viable.

**Déclarations statiques** : 17 plugins sur 18 déclarent `isInstanciable = true` et un configurateur
dédié — la correspondance **1 plugin ↔ 1 configurateur est systématique**.

**Deux résidus établis** (le corpus a des années d'histoire — les signaler est utile, ne pas les
lire comme des intentions) :

1. **`VisualisationPlugin` = `GraphicalPlugin & TripPlugin`** existe comme template nommé, et
   **4 plugins réécrivent cette combinaison à la main** au lieu de l'utiliser (`Magneto`,
   `MessageDisplay`, `EventSituationBrowser`, `GpsViewer`). Deux d'entre eux inversent même l'ordre
   des parents. Le template nommé n'a jamais été adopté partout.
2. **`isMultiTrip` est incohérent, et ça a une conséquence.** Aucun plugin ne le surcharge : tous
   héritent. Or `TripPlugin.isMultiTrip` rend **`true`** alors que sa propre docstring dit *« focused
   on an only Trip »* (bug relevé en passe 2), tandis que `VisualisationPlugin` le surcharge à
   `false`. Résultat : `Magneto` et `EventSituationDisplay` — tous deux mono-trip et graphiques —
   annoncent des valeurs **opposées**. Comme le `Loader` filtre les plugins offerts selon le mode,
   ce booléen ment pour 15 plugins sur 18.
3. `MockUpTripPlugin` déclare `getConfiguratorClass = 'banana.split'` et n'override pas
   `isInstanciable` (donc `false`) : c'est un **doublure de test**, pas un plugin réel. À exclure de
   tout inventaire fonctionnel.

⛏ **Reste** : `Loader.getAvailablePlugins` (mécanique exacte de la découverte par package) ; le
détail interne des 4 widgets ; les arguments consommés plugin par plugin (seul `DataPlotter` est
détaillé ci-dessus).

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

### 6.5 `pynd` — ce que le portage Python a retenu, et ce qu'il a abandonné (passe 4)

**Il a retenu la couche DONNÉES, intégralement. Il a abandonné tout le reste.**

| | MATLAB | pynd |
|---|---|---|
| API données | `Trip` : ~76 méthodes abstraites | **`sqlite_trip.py` : 106 méthodes**, API portée fidèlement (`get_data_occurences_in_time_interval`, `..._near_time`, `..._at_time`, min/max, `add_*`…) |
| contrat abstrait | `Trip.m` (1240 l.) | **`trip.py` : 9 lignes** — `__init__` = `pass`, tout le reste `NotImplementedError` |
| couche temporelle | `TimerTrip.m` | **absente** — `# TODO Uncomment when timer is implement` (`sqlite_trip.py:114`) |
| observers / messages | `Observable`/`Observer`, `TripMessage`, `TimerMessage` | **absents** |
| plugins / configurateurs / widgets | 4 packages | **absents** |

`Record` (45 l.) enveloppe un curseur `sqlite3` en colonnes (`zip(*cursor.fetchall())`) avec
`get_variable_values(nom)`.

> **Lecture pour WAMA — le portage a fait le tri à notre place.** Ce qui a survécu au changement de
> langage est exactement ce qui était *portable* : l'accès aux données. Ce qui est tombé était
> couplé à MATLAB — le timer est un `timer` MATLAB, les observateurs des `handle` classes, les
> plugins des `figure`. **Cela valide le découpage en 4 couches** : le référentiel est portable tel
> quel, le curseur / la télécommande / les vues sont propres à l'hôte et se rebâtissent pour le web.

### 6.6 `rec2trip` — la spécification de l'Importer

`DataParser` (ABC) identifie un flux par `(component, output)` — le vocabulaire **RTMaps**. Il
vérifie la continuité des index (`check_idx`, erreur si un index saute) et délègue l'horodatage :

```python
def parse_line_common(self, time_of_issue, idx, data, timestamp=None):
    self.check_idx(idx)
    ts = self._timestamper.timestamp(time_of_issue, idx, data, timestamp)
    self.parse_data(data, ts)
```

**⭐ Le `Timestamper` est LA réponse à la question d'alignement de §3.** Trois stratégies, choisies
**par flux** à l'import :

| stratégie | règle |
|---|---|
| `TimestampTS` | utiliser l'horodatage porté par la donnée elle-même (repli sur `time_of_issue` + avertissement s'il manque) |
| `TimeOfIssueTS` | utiliser l'heure d'émission du système d'acquisition |
| **`ResamplingTS(frequency)`** | **reconstruire la ligne de temps** : `start_time + idx / frequency` — le 1ᵉʳ échantillon fixe l'origine, l'index fait le reste |

C'est ainsi que `MetaDatas.frequency` prend son sens, et **pourquoi le `.trip` peut supposer tout le
monde sur une base de temps commune** : le recalage est fait UNE fois, à l'ingestion, flux par flux.
Seules les vidéos gardent un `offset` (fichiers externes, non rééchantillonnés).

#### ⚠ TROIS opérations à ne jamais confondre (précision Fabien, 2026-08-20)

| # | opération | effet sur les échantillons | statut |
|---|---|---|---|
| 1 | **Ré-horodatage** — `ResamplingTS` : recalculer les timestamps depuis `start + idx / fréquence_théorique` | **aucun** : tous les échantillons sont conservés, seule leur étiquette de temps change. **Pas d'interpolation.** | ✅ à l'import, **par flux**, quand le pas de temps dérive alors que l'équipement a une cadence théorique connue |
| 2 | **Rééchantillonnage sur grille commune** — interpoler tous les flux vers une cadence unique | **crée de nouvelles valeurs** ; détruit le signal d'origine ; faux sur un catégoriel | ❌ **jamais systématique** (D10) |
| 3 | **Rééchantillonnage à la demande** — vers une **table annexe**, pour un usage précis | crée de nouvelles valeurs, mais **à côté** : l'original reste intact | ✅ **option explicite**, après import ou plus tard ; c'est ce que fait déjà `cam_analyzer` |

> Le nom de `ResamplingTS` est trompeur : **il ne rééchantillonne rien**, il ré-horodate. C'est
> exactement le geste que Fabien décrit — « si le pas variable n'est pas voulu, on corrige à l'import
> en fixant la fréquence théorique de l'équipement ». BIND l'a donc déjà, comme une des trois
> stratégies choisies **flux par flux**.

**Et le pas de temps variable est une CAPACITÉ, pas un défaut** : certains équipements produisent
légitimement des échantillons irréguliers (événements, détections, fixations oculaires). Le
référentiel doit les porter tels quels — d'où `frequency` optionnelle et non contraignante.

**Sources réellement supportées** (= périmètre concret de l'Importer WAMA) : **RTMaps** `.rec`
(pivot) · **Pupil Labs** (gaze, fixations, blinks, surfaces, pupil) · **Empatica E4** (physiologie) ·
**SIMAX** dr2 (simulateur de conduite) · **ProSivic** (car observer, object observer) · **IDS/ueye**
(timings caméra) · **Adeunis** · **CADISP** · média (audio, vidéo) · primitives (float, int, string,
vector, unique_data).

⛏ **Reste** : la sémantique exacte du `mode` d'agrégation de `TripSet` ; le package `ttm` de rec2trip.

---

### 6.7 CONFRONTATION À UNE BASE `.trip` RÉELLE (2026-08-20)

> Jusqu'ici tout venait du CODE. Une base réelle a été fournie : **1,28 Go, un participant,
> 34 min d'enregistrement, 5,26 M de lignes, 37 tables**. Elle confirme le schéma — et corrige deux
> de mes affirmations.

#### Aucun rééchantillonnage — six cadences natives coexistent

| table | lignes | cadence **mesurée** |
|---|---|---|
| `data_BIOPAC_MP150` | 2 037 207 | **1000,0 Hz** |
| `data_ECG_processed` | 2 037 206 | 1000,0 Hz |
| `data_PUPIL_GLASSES_gaze` / `_pupil` / `_processed` | ~251 400 | **123,1 Hz** |
| `data_DR2_Vehicule_VHS_vp` / `_Simulateur` | 115 033 | **56,3 Hz** |
| `data_IDSCAM_MASTER` / `_SLAVE` | ~81 500 | **40,0 Hz** |
| `data_PUPIL_GLASSES_fixations` | 38 262 | **18,7 Hz** |

**Position d'architecture (Fabien, 20/08)** : rééchantillonner à l'import est une **erreur
structurelle** — on perd le signal d'origine par interpolation, la vidéo garde de toute façon sa
propre cadence, et un signal catégoriel interpolé est simplement faux. Un rééchantillonnage se fait
**après import, dans une table annexe, pour un usage précis** (ce que fait déjà `cam_analyzer`),
jamais systématiquement. La base réelle montre que BIND respecte ce principe.

> ⚠ **Correction à §3bis** : j'écrivais « la fréquence est DÉCLARÉE ». Faux en pratique —
> `MetaDatas.frequency = 0` pour **les dix flux**. Le champ existe et n'est pas rempli. La cadence
> est une propriété **émergente** de la donnée. (Un modèle tiers comparable déclare, lui, une
> `resampling_base_frequency` globale *et* une source de temps par canal ; ce que la première
> déclenche réellement n'est pas vérifiable, son code étant protégé.)

`isBase` en revanche fonctionne exactement comme décrit : **1** pour les 8 flux acquis, **0** pour
`ECG_processed` et `PUPIL_GLASSES_processed` — les deux dérivés.

#### ⭐ La Situation est l'UNITÉ D'ANALYSE — c'est là que tout converge

12 tables `situation_<début>_<fin>` : `0_15`, `0_30`, `0_60`, `0_120`, `15_45`, `30_60`, `30_90`,
`45_75`, `60_90`, `60_120`, `75_105`, `90_120`. Ce sont des **fenêtres d'analyse glissantes et
emboîtées, ancrées sur les events**.

Chacune porte **26 colonnes** : `startTimecode`, `endTimecode`, `name`, `duration`, `situation`
(TAG/DEP), `level`, `disconfort`, puis les indicateurs calculés — `RRint_min/max/moy`, `SDNN`,
`RMSSD` (variabilité cardiaque), `SDLP`, `SDWA`, `SRR` (conduite), `nb_fix`, `duree_fix_*`,
`nb_sac`, `duree_sac_*`, `ampli_sac_*` (oculométrie).

> **Le Calculator n'écrit pas ailleurs : il AJOUTE DES COLONNES à la table de situation.** Une ligne
> = un (participant × event × fenêtre) avec tous ses indicateurs. C'est le point de jonction entre
> signaux bruts et statistique — et la raison d'être des situations.

**Les trois voies vers une situation** (dualité explicite/implicite) :

| voie | entrée | ce que fait le Segmenter |
|---|---|---|
| autour d'un **event** | 1 timestamp + durée | `[t, t+d]`, borné à l'occurrence suivante |
| **conditionnelle** | signal + prédicat | plages où le prédicat tient, avec **durée mini et trou toléré** (sans hystérésis on produit du confetti) |
| **états** | signal catégoriel | les plages de valeur constante SONT des situations (run-length) |

Les deux représentations — lignes `(start, end)` explicites, ou signal catégoriel échantillonné —
sont **convertibles**. C'est ça qu'il faut modéliser, pas seulement ajouter un type (⇒ **D8**).

#### La chaîne complète, jusqu'au livrable chercheur

```
RTMaps .rec → rec2trip → .trip (1,28 Go / participant / 34 min)
   ├─ 8 flux acquis (isBase=1) à cadences natives
   ├─ 2 flux dérivés (isBase=0)
   ├─ 6 tables event_* (17 à 62 lignes)
   └─ 12 tables situation_* = fenêtres × indicateurs
        ↓ export BIND_GUI
   AllSituations.xlsx — 12 onglets (un par fenêtre), 377 lignes, colonnes préfixées « 0_15.* »
        ↓ remaniement par les chercheurs
   Indicateurs final N passations.xlsx — onglet Global à 393 COLONNES (fenêtres côte à côte,
   renommées par domaine ECG_/COMP_/EYE_/EDA_), + onglets par condition + Personnalité joint
```

Trois enseignements que la lecture de code ne donnait pas :

1. **L'Exporter fait un pivot long → large.** Le `.trip` stocke une table par fenêtre ; le livrable
   met les fenêtres côte à côte, une ligne par passation. C'est son vrai travail.
2. **Les paramètres de fenêtre vivent dans le NOM de la table** (`situation_0_15`) — fragile. Chez
   WAMA ce seraient des colonnes ou des métadonnées, donc **interrogeables** au lieu d'être devinées.
3. **`MetaTripDatas` est un journal de calcul** : `calcul_RRIntervalsV2: OK`,
   `calcul_...IndicatorsECG_0_30: OK`… — des marqueurs d'idempotence disant ce qui a déjà tourné.
   À rapprocher de `RunOutcome` et de l'idempotence des manifestes.

#### Volume — la décimation est une condition d'existence

1,28 Go pour **34 min et un seul participant**. À l'échelle d'une étude (69 passations), ~88 Go.
Afficher `BIOPAC` (2 M points) sur 2000 px, c'est **1000 points par pixel** : sans vue décimée
(min/max par pixel, §3.5), aucun plugin de visualisation n'est viable. Ce n'est pas une
optimisation.

Enfin, les vidéos sont bien rattachées avec un **offset négatif sub-seconde** (−0,650804 s et
−0,661709 s pour l'audio) — le recalage fin des médias externes, conforme à §6.2.

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

### 8.1 Confrontation terme à terme (passe 5)

| # | BIND | WAMA | verdict |
|---|---|---|---|
| 1 | 3 familles `Data` / `Event` / `Situation` | `SIGNAL`/`TIMESERIES`, `EVENTS`, **rien pour l'intervalle** | ⚠ **trou** — bloque Segmenter ET Calculator (**D8**) |
| 2 | 1 table SQLite **par signal**, indexée ; transactions | — | ✅ à reprendre tel quel, c'est la bonne réponse au haut débit |
| 3 | `unit` par variable, `frequency` par Data, `isBase` (acquis/dérivé) | `Param` a l'unité ; pas d'équivalent `frequency`/`isBase` | ⚠ à ajouter — `isBase` est le socle de la provenance |
| 4 | alignement **à l'ingestion** (`Timestamper` ×3 stratégies) | — | ✅ modèle à copier ; déplace l'effort vers l'Importer |
| 5 | **jamais d'interpolation** (`at`/`near` seulement) | — | **D6** — position pressentie : reprendre pour la VALEUR, interpolation en option d'AFFICHAGE |
| 6 | manifeste de plugin = **méthodes statiques** + balayage du path | registres déclaratifs (`MANIFEST_KINDS`, `FUNCTION_CATALOG`, `mecanismes.py`) | ✅ WAMA est **plus fort** — registre explicite > convention de nommage |
| 7 | `Argument` **non typé** (chaîne ou tableau de chaînes) + **18 GUI à la main** (~4000 l.) | `Param` typé (type, choix, unité, bornes, `show_if`) + **UI générée** | ✅✅ **WAMA génère ce que BIND écrit à la main** — c'est LE gain de l'intégration |
| 8 | `validateConfiguration(metaInfos, config)` écrite par configurateur | `is_compatible()` sur les types | ✅ WAMA la **dérive** au lieu de l'écrire |
| 9 | synchro = **un canal Observer**, messages typés | — | ✅ contrat à reprendre (c'est §7ter point 4) |
| 10 | environnement = plugins + configurations + trips, dans un fichier | kinds `project`/`dataset`, diffables | ✅ **c'est un manifeste**, position confirmée |
| 11 | fenêtres OS flottantes (conséquence de MATLAB) | navigateur | ❌ **ne pas reproduire** — layout dockable + détachement `window.open` + `BroadcastChannel` |

**Ce que le portage `pynd` a prouvé** (§6.5) : la couche données est portable, la couche
temporelle et la couche plugins ne le sont pas. Elles se rebâtissent, elles ne se transposent pas.

### 8.2 Ce qui manque à WAMA, par ordre de blocage

1. **type « intervalle »** dans `data_types.py` (**D8**) — le moins cher, et il débloque le plus ;
2. **le référentiel temporel** (§3) — rien n'existe ; sa difficulté réelle est à l'**ingestion**, pas
   à la consultation, ce qui la rend beaucoup plus abordable qu'estimé au 19/08 ;
3. **le noyau de plugins** : cycle de vie, pairs, souscription au canal (§4.3) ;
4. **la vue déclarative** — le verrou §7ter point 3. On sait maintenant ce qu'elle remplace : les
   18 configurateurs de BIND. ⚠ Garde-fou §7ter maintenu : **ne pas spécifier dans l'abstrait** —
   écrire 2-3 plugins d'abord, extraire ensuite ;
5. **le conteneur de vues** : layout dockable + détachement en vraie fenêtre.
   > Amorce existante : `audio_player` gère déjà l'exclusivité **inter-onglets** (`mecanismes.py:333`).

### 8.3 Plan d'intégration ordonné

> Chaque marche est **utile seule** et ne présuppose que les précédentes. Aucune n'est engagée.

| # | marche | pourquoi ici | dépend de |
|---|---|---|---|
| **A** | `DataType.INTERVALS` + champs `frequency` / `is_base` dans la taxonomie | quelques dizaines de lignes, déverrouille Segmenter + Calculator, et rend la compatibilité vérifiable | — |
| **B** | **Importer** : `Timestamper` (3 stratégies) + lecture `.trip` SQLite | c'est là qu'est la vraie difficulté temporelle ; pynd donne le code de référence à 90 % | A |
| **C** | **Référentiel** : `at(t)`, `range(t₀,t₁)`, `next_event(t)` + **vue décimée** (min/max par pixel) | sans la décimation aucun plugin de visualisation n'est viable (§3.5) ; BIND l'a résolu par `TripStreamingPlugin`, template dominant | B |
| **D** | **Curseur de session** + canal de messages typés (souscription) | couche 2 : trois valeurs et un canal ; c'est le contrat explicite de §7ter point 4 | C |
| **E** | **`WamaShuttle` émet une commande** au lieu d'appliquer une vitesse + spec magneto BIND | débloque la forme fenêtrée ET l'adoption Transcriber ; la brique existe déjà | D |
| **F** | **2-3 plugins écrits à la main** (courbe, carte, bandes d'événements) | la règle du 2ᵉ consommateur interdit d'extraire avant | C, D |
| **G** | **Extraire la vue déclarative** de ces 2-3 plugins | remplace les 18 configurateurs de BIND par de la génération | F |
| **H** | Segmenter, Calculator, Visualizer, Analyzer | deviennent minces une fois A→D en place | A, C |

**Non planifié, à trancher avant d'y toucher** : Recorder temps réel (LSL/RTMaps/ROS) — **D5** ;
conteneur de vues détachables — après F.

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
| 3 | ✅ **faite** (Claude, lecture directe) | §4.6 pipeline de montage · §4.7 les 18 plugins · §5bis magneto. Découpage `configurators`/`loading`/`plugins`/`widgets` **confirmé** (4 packages parallèles). ⭐ Un plugin **ne déclare pas** ce qu'il consomme : c'est l'utilisateur qui le lie au montage |
| 4 | ✅ **faite** | §6.5 ce que `pynd` a retenu (données : 106 méthodes) / abandonné (temporel, observers, plugins) · §6.6 `rec2trip` + le `Timestamper` ×3 stratégies + les sources réelles |
| 5 | ✅ **faite** | §8.1 confrontation terme à terme (11 points) · §8.2 manques ordonnés · §8.3 plan d'intégration A→H |

> **wama-dev-ai n'a produit aucune de ces passes.** Quatre tentatives ont échoué (prompt sans
> `{tools}`, outils aveugles au corpus, navigation en boucle), puis les chargements de modèle ont
> fait tomber la machine — Ollama est à l'arrêt sur décision de Fabien (20/08). L'outillage est
> corrigé et commité ; les passes ont été faites en lecture directe.

---

## 9bis. PLAN D'IMPLÉMENTATION — modules, chaînage, points d'IA, garde-fous

> Établi le 2026-08-22 avec Fabien. **Deux principes qui priment sur le découpage** :
>
> 1. **La modularité prime sur le cas d'usage.** Un cas concret complet existe et servira de
>    référence de validation — mais *« l'exemple n'est qu'un chemin »* : l'Importer doit lire du
>    RTMaps, du LSL, et des enregistrements isolés recalés par **triggers** via des fichiers
>    classiques. Aucun format n'est la voie royale.
> 2. **L'IA dans la chaîne est la RAISON D'ÊTRE de WAMA Data**, pas un ornement. Si un module ne
>    laisse aucune place à l'assistant, il faut se demander pourquoi il vit dans WAMA plutôt que
>    dans un script.

### 9bis.1 Les modules et leur nature

| module | consomme → produit | brique commune | app/UI |
|---|---|---|---|
| **Recorder** | flux temps réel → `dataset` | ⏳ (LSL/RTMaps/ROS) | app — **D5, différable** |
| **Importer** | fichiers + `dataset` → référentiel | ✅ `data/sources/` (registre) | app |
| **Connector** | base existante → référentiel | ✅ lecteur `.trip` (cas particulier) | module |
| **Explorer** | référentiel → vues table/graphe | ⏳ | app |
| **Segmenter** | signal/events + prédicat → `segments` | ⏳ | app |
| **Calculator** | `segments` + signaux → colonnes d'indicateurs | ⏳ | app |
| **Visualizer** | référentiel → plugins synchronisés | ⏳ | app |
| **Exporter** | `segments` + indicateurs → fichiers | ⏳ | module |
| **Analyzer** | orchestre les précédents | ⏳ | app |

**Le découpage brique/app est le même que côté média** : le traitement vit dans `common/data/`, l'app
n'est qu'une surface. Un module qui code sa logique dans son app est hors-route.

### 9bis.2 Le chaînage — rien de neuf à inventer

Les pièces existent et il faut **les relier, pas les refaire** :

- **`FunctionSpec` + `FUNCTION_CATALOG`** : toute étape de traitement est une fonction à ports typés.
  Règle §7bis déjà posée : *tout traitement se déclare*.
- **Kind `pipeline`** : il **existe déjà** et porte exactement ce qu'il faut — `{nodes, links}` avec
  la **présentation (`layout`) séparée du fonctionnel**. Il ne connaît que `source|sink|app` : il
  faut y ajouter le nœud **fonction**. C'est une extension, pas un nouveau kind.
- **Canvas studio** : le chaînage se dessine là. ⚠ **Ne JAMAIS créer un second canvas** — l'héritage
  de capacités est déjà acté (§7ter) : une fonction déclarée apparaît au canvas sans code studio.

### 9bis.3 Une source, N rendus — le piège à éviter

Fabien souhaite pouvoir sortir la chaîne en script Python/MATLAB, en diagramme, et la réimporter.
**Ne jamais faire traduire une représentation en une autre** : avec *n* représentations cela fait
*n(n−1)* traducteurs qui divergent.

```
                     ┌── canvas studio        (édition)
manifeste `pipeline` ├── diagramme Mermaid    (lecture ; UML d'activité si livrable académique)
  = SOURCE UNIQUE    ├── script Python        (reproductibilité — exécutable)
                     ├── squelette MATLAB     (portabilité BORNÉE, voir ci-dessous)
                     └── résumé en langage naturel
```

C'est le geste déjà éprouvé pour `WAMA_MECANISMES.md` : le registre est la source, le `.md` un rendu
régénéré, donc incapable de dériver.

**Le retour (script → pipeline) recouvre DEUX fonctionnalités qu'il ne faut pas confondre :**

| | faisabilité |
|---|---|
| réimporter un script **généré par WAMA** | ✅ exact — le script porte l'identifiant de son pipeline |
| importer un script **étranger** | ⚠ assistif seulement : sortie = *proposition à relire*, jamais un import direct. C'est de la compréhension de programme, sans garantie |

**Limite de l'export MATLAB** : générer du Python est tractable parce que les fonctions *sont* en
Python. Pour MATLAB, seuls les pas ayant un équivalent MATLAB s'exportent. L'export MATLAB sera donc
un **squelette + contrat de données**, pas une portabilité feinte.

### 9bis.4 Où l'IA entre — et où elle n'entre pas

| étape | rôle de l'IA | ⚠ garde |
|---|---|---|
| cartographie d'un dossier de données | **aucun** — un scan déterministe (types, tailles, nommage, en-têtes) fait mieux, gratuitement et sans hallucination | |
| **protocole en langage naturel → manifeste `dataset`** | ⭐ **le pont sémantique** : c'est là que l'IA est irremplaçable | le manifeste est une **proposition** |
| **protocole de traitement → manifeste `pipeline`** | ⭐ idem | idem |
| validation de l'import | **aucun** — mécanique | le manifeste déclare des attentes VÉRIFIABLES (monotonie, cadence, plages, énumérés) et l'importer MESURE l'écart |
| **codage vidéo** (annotation d'événements par vision) | ⭐ produit des `events`, donc des segments | relecture humaine ; traçabilité de l'origine |
| lancement de traitements par lots | orchestration via `tool_api` | jamais d'apply automatique |

> 🔴 **La règle qui évite le pire : le LLM propose, la machine dispose.** Un manifeste généré par LLM
> qui « valide » ensuite l'import est CIRCULAIRE — si le modèle prend une colonne pour un horodatage,
> l'import valide contre un manifeste faux et toute la chaîne est silencieusement erronée. Le contrat
> `verify` de `ManifestKind` existe déjà : c'est sa place.

### 9bis.5 Garde-fous MÉCANIQUES (pas des intentions)

Ce sont eux que Fabien demande — « des mécanismes pour s'assurer qu'on ne part pas dans un mauvais
sens ». Chacun doit être un contrôle exécutable, pas une règle écrite.

| # | garde-fou | forme |
|---|---|---|
| G1 | **aucun format privilégié** dans l'Importer/Exporter | test : le moteur ne cite aucun format ; ajouter un lecteur ne le modifie pas |
| G2 | **pas de second canvas** | contrôle : aucune implémentation de graphe/DAG hors `studio/` |
| G3 | **tout traitement déclaré** (§7bis) | contrôle : aucune fonction de traitement hors `FUNCTION_CATALOG` |
| G4 | **round-trip du `pipeline`** | `extract → verify` comme les autres kinds |
| G5 | **sortie d'IA = proposition** | tout manifeste généré passe par `verify` et rapporte ses écarts |
| G6 | **grille de conformité WAMA Data** | mesurée, comme la grille d'apps — sinon l'avancement se raconte |
| G7 | **cas complet de bout en bout** | ⏳ quand une chaîne WAMA produira un export : rejouer le cas connu. ⚠ nécessite un **échantillon réduit VERSIONNÉ** (le corpus réel est hors dépôt) |

### 9ter. LE SEGMENTER — spécification tirée des trois sources (passe 6, 2026-08-22)

> ⚠ **Rectification.** J'avais déclaré la cartographie « complète » alors que **BIND_GUI n'avait
> pas été lu** — or c'est là que vivent le Segmenter, le Calculator et l'Exporter. 478 Ko de source
> MATLAB (8791 lignes, 151 fonctions) étaient restés fermés. Voici la passe qui manquait.

### 9ter.1 Les modes réels

Sources : présentation BIND_GUI (2019, schéma) **confrontée au code** (`BIND_GUI.mlapp`), plus le
modèle tiers (fonction `calculatePlageSansTrou`) et BORIS (`constants.py`).

| mode | définition RÉELLE | BIND_GUI | modèle tiers | BORIS |
|---|---|---|---|---|
| **temporelle simple** | ancre + **DEUX offsets** : `start = tc + o₁`, `end = tc + o₂` | ✅ | — | — |
| **temporelle double** | **jonction de DEUX tables** : début pris dans l'une, fin dans l'autre, appariement occurrence à occurrence avec curseurs indépendants | ✅ | — | — |
| **conditionnelle** | conditions sur variables, combinées par **ET / OU** | ✅ | ✅ | — |
| **hystérésis** | durée minimale + **trou toléré** | ❌ | ✅ | — |
| **état (run-length)** | plages de valeur constante d'un catégoriel | implicite | ✅ | ✅ |
| **codage** (manuel ou IA) | protocole déclaré + exécution | ✅ | — | ✅ (éthogramme) |
| **sous-segmentation « présent dans »** | ne garder que les segments **strictement inclus** dans un segment de référence | ✅ | — | — |
| **filtrage manuel** | curation humaine des events/situations produits | ✅ | — | — |
| **segment OUVERT** (fin inconnue) | état commencé, non terminé | ❌ | ❌ | ✅ `UNPAIRED` |

**Ce que j'avais modélisé était faux sur deux points** :

1. Je décrivais « autour d'un événement **+ durée** ». Le réel est **deux offsets indépendants** —
   c'est ce qui permet `15_45` (fenêtre commençant 15 s *après* l'ancre), impossible à exprimer
   avec une simple durée. Confirmé par les 12 tables mesurées dans la base réelle.
2. Je ne connaissais pas la **jonction de deux tables**. C'est pourtant le mode qui produit
   « du début du bloc à la pause suivante », « du début de scénario à la fin de virage » — des
   segments dont les deux bornes viennent de flux *différents*.

### 9ter.2 Le meilleur des trois mondes

Chaque source apporte ce que les autres n'ont pas :

- **BIND_GUI** — la *combinatoire* : simple/double, ET/OU, « présent dans », filtrage manuel, et la
  **sauvegarde/rechargement d'une segmentation** (`load_segmentation`, menus `Segmentation` /
  `Export` / `Environnement complet`). C'est une segmentation **rejouable**, donc déjà un manifeste
  qui s'ignore.
- **Modèle tiers** — l'*hystérésis* (`durée minimale`, `trou toléré`). Sans elle, une segmentation
  par seuil produit du confetti : c'est un détail de spécification qui ne s'invente pas.
- **BORIS** — l'*état ouvert* (`UNPAIRED`) et le vocabulaire de **codage** (éthogramme, sujet,
  modificateurs typés, comportements mutuellement exclusifs). Indispensable dès qu'un humain **ou
  une IA** code en cours de flux : ni BIND ni WAMA ne savent aujourd'hui représenter un segment
  commencé et non terminé.

### 9ter.3 Conséquences pour WAMA

| # | conséquence | statut |
|---|---|---|
| 1 | la signature du Segmenter est **`(ancre, o₁, o₂)`**, pas `(ancre, durée)` | à écrire |
| 2 | ajouter le mode **jonction de deux flux** | à écrire |
| 3 | l'hystérésis (`durée_min`, `trou_toléré`) est un **paramètre du mode conditionnel** | à écrire |
| 4 | « présent dans » est une **opération ensembliste sur segments** (inclusion stricte), réutilisée **aussi à l'export** — donc une fonction du catalogue, pas un bout de Segmenter | à écrire |
| 5 | `Signal` doit accepter une **fin `None`** = segment ouvert (D15) | ⚠ modèle actuel incapable |
| 6 | le **codage** (manuel ou IA) produit des segments comme les autres modes — même sortie, origine tracée | à écrire |
| 7 | une segmentation **se sauvegarde et se rejoue** → c'est un manifeste `pipeline`, pas un réglage d'écran | à écrire |

> **Ne pas réinventer** : les concepts sont posés depuis des années et éprouvés sur de vraies
> campagnes. Le travail est de les **traduire** dans le vocabulaire typé de WAMA — pas de les
> redécouvrir.

⛏ Reste non lu de BIND_GUI : le Calculator (annoncé « à venir » en 2019, donc probablement absent),
l'Exporter (`ExportConcatPresentDans`, `exporterTousNormalPresentDans`…), et le cycle de vie du
protocole de codage (`vbCreerProtocole` / `vbEditerProtocole` / `vbLancerCodage`).

---

## 9bis.6 Ce que la cartographie n'a pas couvert — à traiter avant l'Importer v2

**L'alignement par TRIGGERS.** RTMaps et LSL fournissent une horloge d'acquisition commune ; des
enregistrements **isolés** recalés par triggers, non : la référence commune y est un **événement
partagé** (marqueur, impulsion) qu'il faut **apparier entre flux** pour en déduire l'offset. Ni le
`Timestamper` (qui décide le temps d'un échantillon DANS un flux) ni §6.6 ne savent le faire.

C'est une **quatrième stratégie d'ingestion**, de nature différente : elle ne porte pas sur un flux
mais sur une **relation entre flux**. À concevoir explicitement — l'ignorer produirait un Importer
qui ne sait lire que des acquisitions déjà synchronisées, c'est-à-dire le cas facile.

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
| D10 | **rééchantillonnage : jamais systématique** (Fabien, 20/08) — mais **TROIS opérations distinctes**, cf. §6.6 : le **ré-horodatage** par fréquence théorique est ✅ à l'import et par flux (il n'interpole pas) ; le **rééchantillonnage sur grille commune** est ❌ ; le **rééchantillonnage à la demande vers une table annexe** est ✅ en option. Le **pas de temps variable est une capacité à porter**, pas un défaut à corriger. Reste : où vit la table annexe et comment elle se déclare | tranchée sauf table annexe |
| D11 | les paramètres de fenêtre d'une situation : **colonnes/métadonnées** (interrogeables) plutôt que dans le NOM de la table comme BIND (`situation_0_15`) ? | après A |
| D12 | **alignement par TRIGGERS** (§9bis.6) : où vit l'appariement d'événements entre flux — dans l'Importer, ou comme fonction du catalogue applicable après import ? | avant l'Importer v2 |
| D13 | nœud **fonction** dans le kind `pipeline` : étendre `source\|sink\|app`, ou déclarer les fonctions comme un `app` d'un genre particulier ? | avant le 1ᵉʳ pipeline de données |
| D15 | **segment OUVERT** (fin inconnue) : `Signal.ends` accepte-t-il `None` ? Indispensable au codage en cours de flux — un humain ou une IA qui code ouvre un état avant de le fermer. BORIS le porte (`UNPAIRED`), ni BIND ni WAMA ne savent le représenter | avant le codage vidéo |
| D14 | granularité du **script généré** : un fichier plat rejouable, ou un module par fonction + un orchestrateur ? (impacte la lisibilité pour un relecteur académique) | avant l'Exporter de pipeline |

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
- **2026-08-20 — passes 3, 4 et 5 faites : LA CARTOGRAPHIE EST COMPLÈTE.** Résultat central : **un
  plugin BIND ne déclare pas ce qu'il consomme** — le `Loader` calcule un catalogue
  (`MetaInformations`), le configurateur le PROPOSE via des widgets, l'utilisateur choisit, et la
  `Configuration` (liste d'`Argument`s ordonnés, **non typés**) sert d'arguments au constructeur.
  Prix payé : **18 GUI écrites à la main, ~4000 lignes**, dont `DataPlotterConfigurator` à 802.
  ⇒ **C'est exactement ce que WAMA sait GÉNÉRER** — le gain principal de l'intégration est là, pas
  dans la reprise de code. Le portage `pynd` confirme le découpage en couches : la couche données a
  survécu au changement de langage (106 méthodes), la couche temporelle et la couche plugins non
  (timer en `TODO`, aucun observer, aucun plugin). L'alignement multi-sources est résolu à
  l'ingestion par un `Timestamper` à 3 stratégies, dont une qui **reconstruit la ligne de temps**
  depuis la fréquence déclarée et l'index. Plan d'intégration ordonné A→H en §8.3, la première
  marche étant le type « intervalle » (quelques dizaines de lignes, débloque le plus).
  **Toujours aucune ligne de WAMA Data implémentée.**
- **2026-08-20 — confrontation à une base `.trip` RÉELLE** (§6.7) : 1,28 Go, 1 participant, 34 min,
  5,26 M lignes. **Aucun rééchantillonnage** — six cadences natives coexistent (1000 / 123,1 / 56,3
  / 40 / 18,7 Hz) ; position d'architecture arrêtée (**D10**) : on ne rééchantillonne PAS à
  l'import. ⚠ **Correction** : `MetaDatas.frequency` vaut 0 pour les 10 flux — la cadence est
  émergente, pas déclarée, contrairement à ce que §3bis affirmait. `isBase` en revanche est bien
  utilisé (8 acquis / 2 dérivés). ⭐ **La Situation est l'unité d'analyse** : 12 fenêtres glissantes
  ancrées sur events, 26 colonnes chacune, et **le Calculator écrit ses indicateurs COMME COLONNES
  de la table de situation**. Trois voies vers une situation (autour d'un event · conditionnelle
  avec durée mini + trou toléré · run-length d'un signal catégoriel) — les représentations explicite
  et implicite sont convertibles. Chaîne complète établie jusqu'au livrable chercheur : l'Exporter
  fait un **pivot long → large** (12 onglets → 393 colonnes). Volume : ~88 Go pour une étude, donc
  la **décimation est une condition d'existence**, pas une optimisation. Deux décisions ajoutées
  (D10, D11).
- **2026-08-21 — marches A, B et C LIVRÉES** (`data_types` : `SECTIONS`→`SEGMENTS` ; `temporal.py` ;
  `data/sources/` avec 2 lecteurs). ⚠ Correction : j'avais annoncé un TROU (« pas de type
  intervalle ») — FAUX, `SECTIONS` existait et était consommé par 4 fonctions dont 3 du
  cam_analyzer. Trois défauts trouvés par la MESURE : agrégation par index → quadratique ; min/max
  attribués à la mauvaise tranche (arrondi flottant) ; `float('')` sur une fréquence vide rendant un
  flux entier illisible. Contrôles consignés (`tests_temporal`, `tests_sources` — 57 tests, deux
  niveaux : synthétique partout, base réelle sautée si absente) et inscrits au **nocturne**
  (`common.consistency.wama_data`) ; 3 briques déclarées au registre des mécanismes.
- **2026-08-22 — PLAN D'IMPLÉMENTATION** (§9bis) : modules, chaînage, points d'IA, 7 garde-fous
  mécaniques. Deux recadrages de Fabien : *« l'exemple n'est qu'un chemin »* — la modularité prime
  sur le cas d'usage, l'Importer doit couvrir RTMaps, LSL **et** des enregistrements isolés recalés
  par **triggers** ; et **l'IA dans la chaîne est la raison d'être de WAMA Data**, pas un ornement.
  Deux trouvailles : le kind **`pipeline` existe déjà** et sépare déjà le fonctionnel de la
  présentation (donc aucun nouveau kind à créer pour le traitement) ; et **l'alignement par
  triggers** est une 4ᵉ stratégie d'ingestion qu'aucune passe n'avait vue — elle porte sur une
  RELATION entre flux, pas sur un flux. D12→D14 ajoutées.
