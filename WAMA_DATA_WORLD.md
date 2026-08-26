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
> Registre des modules : `wama_data/modules.py`.

**Bilan** : 3 ⏳ (non commencé) · 2 🔄 (partiel) · 5 🔶 (livré mais INERTE)

> 🔶 **AUCUN consommateur hors `wama_data/` — le sous-système entier est INERTE.** Aucune app, tâche ou route ne s'en sert encore : les briques s'appellent entre elles, et c'est tout. Le premier module à donner un usage réel fera basculer ces lignes en ✅.

| Module | Rôle | Flux | État | Briques | Testées | Conso. int/ext | Doc |
|---|---|---|---|---|---|---|---|
| **Importer** | Lit une source et rend un référentiel temporel interrogeable | fichiers + manifeste `dataset` → référentiel, écrit en `.wdat` | 🔶 | 9/9 | 3 | 7/0 | §6.6, §6.6bis, §9bis.1, §9quater.2, §9duodecies, §9terdecies |
| **Référentiel temporel** | Aligne des flux à cadences incommensurables | référentiel → échantillons, `segments`, vue décimée, cadres typés | 🔶 | 2/2 | 2 | 2/0 | §2, §3, §9quater.7 |
| **Connector** | Branche une base existante comme source | base SQLite (`.trip` externe, `.wdat` natif) → référentiel | 🔶 | 3/3 | 0 | 3/0 | §6.2, §9quater.2, §9terdecies |
| **Explorer** | Explore un dataset en table et en graphe — c'est aussi l'INTERFACE du Calculator : la vue tableur est le lieu où l'on ajoute une colonne calculée et où l'on voit le résultat | référentiel → vues table/graphe + colonnes calculées | 🔄 | 1/2 | 1 | 1/0 | §7, §9quater.6, §9quater.7 |
| **Segmenter** | Produit des segments : autour d'un événement, par jonction de deux flux, par CHAÎNE de conditions (ET/OU/XOR/NON) avec hystérésis, par plages constantes d'un catégoriel, ou par CODAGE (humain ou IA) — la chaîne sort en segments OU en événements, au choix du PORT | `events` ou signal + conditions → `segments` \| `events` | 🔶 | 6/6 | 5 | 16/0 | §9ter (spécification), §9ter.6 A-B (portage), §6.7 |
| **Calculator** | Calcule des COLONNES DÉRIVÉES (moyenne glissante, dérivée, cumul) et des INDICATEURS PAR SEGMENT qu'il adjoint aux segments | signal → signal enrichi · `segments` + signal → colonnes d'indicateurs | 🔄 | 2/3 | 2 | 2/0 | §6.7 |
| **Visualizer** | Vues synchronisées sur l'axe partagé (plugins) | référentiel → plugins co-chargés | ⏳ | — | — | — | §4, §8.2 |
| **Exporter** | Exporte TOUT le contenu d'un trip de façon configurable — données, méta-infos, événements, situations et leurs indicateurs : sélection ordonnée de colonnes, identité, contexte, regroupement | données/méta/`events`/`segments` + sélection → fichiers (concaténation, jamais pivot) | 🔶 | 2/2 | 2 | 4/0 | §9ter.5, §9ter.6 C |
| **Recorder** | Enregistre depuis une source temps réel | flux LSL/RTMaps/ROS → `dataset` | ⏳ | — | — | — | §7 |
| **Analyzer** | Orchestre les modules selon un manifeste `pipeline` | manifeste `pipeline` → exécution | ⏳ | — | — | — | §9bis.2 |

<details><summary>⚠ <b>10 module(s) avec un blocage déclaré</b> — ce qui empêche d'avancer, en une ligne</summary>

- **Importer** — alignement par TRIGGERS non conçu (D12) ; ⚠ le lecteur `.rec` EXISTE depuis le 2026-08-24 (`sources/rtmaps.py`, inventaire par le `.idy`, vérifié sur les DEUX grammaires RTMaps et contre l'export CSV de RTMaps lui-même) — reste la couche SÉMANTIQUE par famille de flux (le `data_parser/` de pynd : `clé=valeur` à virgule française, JSON, colonnes tabulées), la charge étant aujourd'hui rendue telle quelle ; `functions/io/rtmaps_rec.py` demeure un utilitaire du Lab, non migré à dessein. ⚠ « l'ÉCRITURE du conteneur natif `.wdat` reste à écrire — aucune ligne n'écrit encore de SQLite » a été RETIRÉ le 2026-08-24 : l'écrivain (`containers/`, un moteur et deux schémas) ET le lecteur (`sources/wdat.py`) sont livrés, l'aller-retour est éprouvé et la compatibilité BIND attestée par contre-épreuve (§9duodecies, §9terdecies). ⚠ « `DATASET_SOURCES` non réconcilié avec le registre des lecteurs (G1) » a été RETIRÉ de cette liste le 2026-08-24 : c'était une glose fausse à deux titres (§9decies). G1 dit « le moteur ne cite aucun format » — vrai défaut, corrigé, testé. Et `source.type` (PROVENANCE) n'a pas à coïncider avec un format de lecteur (CAPACITÉ) : le kind réclame un reader source-AGNOSTIQUE
- **Référentiel temporel** — ⚠ Son blocage « AUCUN consommateur » est LEVÉ le 2026-08-23 : il n'en avait aucun parce que rien ne pouvait convertir sa sortie en `TypedFrame` — c'est désormais `frames.py`. Un flux chargé traverse une fonction du catalogue et revient au référentiel (34 tests). Reste : la fenêtre/résolution comme DÉCLARATION sérialisable (le view-model de l'Explorer)
- **Connector** — Les DEUX bases se lisent depuis le 2026-08-24 (`.trip` externe et `.wdat` natif, socle SQLite partagé). ⚠ Ce qui le sépare encore de l'Importer n'est PAS une capacité de lecture mais un GESTE : brancher une base sans la copier suppose de décider ce qu'on fait d'une source qui bouge sous les pieds — question jamais posée, et c'est elle le vrai reste
- **Explorer** — CŒUR LIVRÉ le 2026-08-23 — le PONT (`frames.py`, 34 tests) et le VIEW-MODEL (`vue.py`, 31 tests) : une `View` déclare flux/fenêtre/résolution/colonnes dérivées, est sérialisable en JSON, et rend la règle de §9quater.4 EXÉCUTABLE en la dérivant de la `FunctionCategory`. Reste l'UI, et elle seule : `wama_data` n'a encore AUCUNE surface Django (ni views, ni urls, ni templates) et aucune bibliothèque de graphe n'est vendorée — deux décisions cadrées par §9quater.7 (« une lib qui DESSINE oui, une lib qui décide de la MISE EN PAGE non »)
- **Segmenter** — MOTEUR complet — le portage schéma-driven de §9ter.6 A-B est LIVRÉ le 2026-08-23 (chaîne de conditions en ARBRE, 14 opérateurs filtrés par la SORTE de colonne LUE dans la donnée, offsets et « répéter » de la jonction, second port `masque → events`). Restent DEUX manques de §9ter.6 A, tous deux d'INTERFACE et non de moteur : le filtrage manuel occurrence par occurrence (= la file de cards + l'inspecteur, mécanisme existant, zéro code) et l'interface de codage, qui doit se GÉNÉRER du protocole — elle dépend du transport (Magneto + vue média) et de la vue déclarative, donc du Visualizer
- **Calculator** — MOTEUR écrit et éprouvé (49 tests — 32 sur le cœur pur, 17 sur la frontière pandas) : reste son emploi sur un corpus RÉEL, qui dépend de l'Importer — sans flux aligné, il n'y a rien à calculer
- **Visualizer** — vue déclarative = verrou §7ter point 3 ; écrire 2-3 plugins AVANT d'extraire
- **Exporter** — MOTEUR écrit et éprouvé le 2026-08-23 (49 tests — 37 sur le cœur pur, 12 sur la frontière pandas) sur le modèle RÉEL cette fois : une DÉCLARATION sérialisable, DEUX axes de regroupement au lieu des quatre branches recopiées, l'aperçu qui EST l'export borné. ⚠ Il n'est PAS au catalogue de fonctions et ce n'est pas un oubli : un puits n'a pas de `FunctionCategory` honnête. ⚠ MAIS SON BLOCAGE A CHANGÉ DE NATURE le 2026-08-24 : **D13 est TRANCHÉE** (§9undecies.2 — un seul kind `pipeline`, étendu d'un nœud `function`). Ce n'est donc plus une décision qu'on attend, c'est une IMPLÉMENTATION qui manque, et l'abstention de `functions/io/export.py` — écrite « tant que D13 n'est pas tranchée » — doit être relue à cette lumière. Restent : le nœud `function` dans le kind, les formats `xlsx`/`mat` (refusés explicitement, pas écrits), et l'app qui le pilote
- **Recorder** — périmètre v1 non tranché (D5)
- **Analyzer** — ⚠ D13 n'est plus en attente — TRANCHÉE le 2026-08-24 (§9undecies.2) : un seul kind `pipeline`, étendu d'un nœud `function`, parce qu'un protocole réel TRAVERSE les mondes et que deux kinds le rendraient inexprimable. Le nœud reste à IMPLÉMENTER, et avec lui le dispatch app (job de file, asynchrone) vs fonction (transformation typée, synchrone). C'est désormais le premier chantier non bloqué de la chaîne

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
| **1. Référentiel temporel** | bases de temps, origines, dérives, discontinuités, politique de rééchantillonnage **par type de donnée** ; répond `at(t)`, `range(t₀,t₁)`, `next_event(t)`, vue décimée | qu'on lit, qu'il y a une vitesse, qu'il y a un écran | **WAMA Data** (`wama_data/`) |
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

Dérivé des modules visés (§7) et de la taxonomie **existante** `wama/common/catalog/data_types.py`
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

#### 6.6bis Ce que la lecture du CODE et d'un `.rec` RÉEL ajoute (2026-08-24)

> §6.6 ci-dessus est **juste** — la mieux cartographiée du document. Ce qui suit ne la corrige pas,
> il ajoute ce qu'elle n'avait pas vu, et deux de ces points auraient rendu une implémentation
> hâtive fausse. Sources : `pynd/rec2trip/` et le corpus réel (`.rec` de **1,54 Go**, son `.idy`,
> son `.idx`, **et le `.trip` que BIND en a produit**).

**① Les parseurs sont un REGISTRE.** `self._parsers: Dict[(component, output), DataParser]`, peuplé
par `add_data_parser()`. C'est la capacité agrégative de §9quinquies, déjà présente chez pynd.

**② ⭐ LE FICHIER `.idy` DÉCLARE TOUT L'INVENTAIRE — 2,7 Ko contre 1,54 Go.** Une ligne par flux :

```
<toi> @ Record <component>.<output>(<nom_de_table>,<producteur>[…]) as <encodage>
```

Il donne le **nom de la table `.trip`** (`BIOPAC_MP150_resp`) **et l'encodage déclaré** — `txt`,
`tabbed_text`, `video_file`, `audio_file`, `raw`. **C'est la source du `probe()`** : inventorier
sans toucher au gigaoctet. Rapport ~**500 000×**. Rien de tout cela n'était consigné.

**③ ⚠ MAIS L'ENCODAGE N'EST QUE LE TRANSPORT, pas la structure.** Mesuré sur le fichier réel :
`DR2.message` et `PUPIL_GLASSES.gaze` sont tous deux `as txt`, et pourtant —

```
DR2.message   → Pas=1776;Temps=00:00:32,13872;V_vp:Vitesse=0,000;V_vp:Pk=1420000;…
PUPIL_GLASSES → {"topic": "gaze.3d.01.", "gaze_normals_3d": {…}}
```

l'un est du `clé=valeur;` **à virgule décimale française**, l'autre du JSON. **Deux couches
distinctes** : le transport se lit du `.idy` (générique) ; la sémantique reste par famille de flux
(c'est le rôle de `data_parser/`). ⚠ La virgule décimale est un piège concret : un `float()` naïf
échoue, et la colonne resterait silencieusement du texte.

**④ TROIS DÉTECTIONS DE PERTE QUI N'AGISSENT SUR RIEN** — chez pynd, la donnée est mesurée puis jetée :

| détection | ce qui en est fait |
|---|---|
| `_check_enough_parser()` | **résultat calculé puis jeté** : `if not self._check_enough_parser(): pass` |
| ligne sans parseur | **ignorée en silence** — l'avertissement est en commentaire |
| `check_idx` (index qui saute = échantillon perdu) | `log.error` seulement, avec un `TODO` qui le reconnaît |

WAMA a déjà le domicile de ces trois faits : l'**`Ecart`** (§9octies). *Le manifeste déclare,
l'importer MESURE.* L'adaptation schéma-driven n'invente donc presque rien — elle donne une
structure à ce que pynd calcule déjà et laisse tomber.

**⑤ La logique `isBase` de `rec2trip` s'annule elle-même** : les parseurs `overwrite` posent
`is_base=False`, puis les lignes suivantes remettent **tout** à `True`.

**⑥ `.rec` est le premier format STREAMÉ à flux ENTRELACÉS.** `.trip` est du SQLite indexé, `.csv`
un flux unique ; un `.rec` est un texte séquentiel où les 20 flux sont mêlés. `read()` exige donc
une première passe, et l'accès paresseux suppose de garder des **offsets d'octets** (module
`array`, pas des listes Python — 7,7 M lignes estimées).

⏳ **Piste non vérifiée** : le `.idx` (16 Ko) est un index BINAIRE — en-tête `[STDB v2.0]`,
section `[Index]`, puis des entiers 8 octets croissants (~2 075 entrées, soit un point tous les
~740 Ko). Ce sont vraisemblablement des points de reprise dans le `.rec`, ce qui permettrait de
chercher sans balayer. **Non confirmé** : pynd ne le lit pas, et je n'ai pas la spec RTMaps. À ne
pas utiliser tant que sa sémantique n'est pas établie.

**⑦ Le corpus contient l'ENTRÉE et la SORTIE** — le `.rec` **et** le `.trip` que BIND en a produit.
C'est le banc d'essai idéal du portage : un `RecReader` WAMA se confronte à un résultat de
référence, au lieu d'être jugé sur lui-même.

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

1. ~~**L'Exporter fait un pivot long → large.**~~ ⚠ **FAUX — corrigé le 2026-08-23 (Fabien).**
   Il n'y a **aucun pivot**, nulle part. Une table `situation_*` est DÉJÀ `occurrences ×
   indicateurs` (mesuré : `situation_0_15` = 7 lignes, `MetaSituationVariables` = 312 variables
   pour 12 situations, soit ~26 colonnes chacune) — c'est-à-dire déjà l'orientation du fichier de
   sortie. L'export écrit les tables telles quelles ; la seule différence avec le livrable est la
   **mise en onglets Excel par type de situation**. Ce que BIND appelle « combinaison » est une
   **concaténation** (verticale entre trips ou entre déclarations, horizontale en mode
   `concat_all`), jamais un remaniement d'orientation.

   > **Pourquoi cette ligne a coûté cher.** Elle contredisait §9ter.5, qui décrit l'export
   > CORRECTEMENT parce qu'il a été lu dans le code. Le 2026-08-23 une session a suivi celle-ci,
   > et a livré un Exporter « pivot long → large » — reverté (`ef756b63`). Deux récits du même
   > mécanisme dans un même document : **le suivant lira celui qui l'arrange**. D'où la règle
   > ci-dessous, §9ter.6.
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
| **Segmenter** | signal/events → `segments`/`events` (5 modes) | 🔶 moteur, cf. §9ter.6 pour les manques | app |
| **Calculator** | colonnes dérivées · indicateurs par segment | 🔶 écrit (49 tests) | app |
| **Visualizer** | référentiel → plugins synchronisés | ⏳ | app |
| **Exporter** | TOUT le contenu d'un trip (données, méta, events, situations) → fichiers | ⏳ cf. §9ter.6 | module |
| **Analyzer** | orchestre les précédents | ⏳ | app |

**Le découpage brique/app est le même que côté média** : le traitement vit dans `wama_data/`, l'app
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
| 1 | la signature du Segmenter est **`(ancre, o₁, o₂)`**, pas `(ancre, durée)` | ✅ `autour()` + `segment_autour_event` |
| 2 | ajouter le mode **jonction de deux flux** | ✅ `jonction()` — appariement par le TEMPS, pas par index |
| 3 | l'hystérésis (`durée_min`, `trou_toléré`) est un **paramètre du mode conditionnel** | ✅ `conditionnelle()` |
| 4 | « présent dans » est une **opération ensembliste sur segments** (inclusion stricte), réutilisée **aussi à l'export** — donc une fonction du catalogue, pas un bout de Segmenter | ✅ `present_dans()` / `chevauche()`, déclarées |
| 5 | `Signal` doit accepter une **fin `None`** = segment ouvert (D15) | ✅ `OUVERT = None` — **pas** de sentinelle numérique |
| 6 | le **codage** (manuel ou IA) produit des segments comme les autres modes — même sortie, origine tracée | ✅ `coding.py` — le `codeur` est le SEUL champ qui les distingue |
| 7 | une segmentation **se sauvegarde et se rejoue** → c'est un manifeste `pipeline`, pas un réglage d'écran | 🔄 protocole sérialisable des deux sens ; kind `protocol` pas encore enregistré |

> **Ne pas réinventer** : les concepts sont posés depuis des années et éprouvés sur de vraies
> campagnes. Le travail est de les **traduire** dans le vocabulaire typé de WAMA — pas de les
> redécouvrir.

### 9ter.4 Le CODAGE — le modèle direct du codage vidéo par IA

Trois pièces séparées, et c'est ce découpage qui compte :

| pièce | rôle |
|---|---|
| **le protocole** — un fichier `.pro` | déclare CE QUI EST CODABLE. Édité par une application à part (`ProtocolCreator`), pas par l'outil d'analyse |
| **l'interface de codage** — `GenericCodingInterface(trip, protoPath)` | **GÉNÉRIQUE** : elle est pilotée par le protocole, jamais écrite par projet |
| **la session** | refuse de démarrer sans vidéo (`getVideoFiles()`) et ouvre automatiquement **Magneto + VideoPlayer** — le codage EXIGE le transport et la vue, synchronisés |

> C'est le principe schéma-driven appliqué au codage, et il date de 2019. Transposé à WAMA :
> **le protocole est un manifeste** (l'éthogramme de BORIS en est l'équivalent nommé), l'interface
> se génère, et **une IA de vision n'est qu'un producteur de plus des mêmes événements** — même
> sortie, origine tracée. C'est la conséquence 6 de §9ter.3, confirmée par un mécanisme réel.

#### Ce qui est ÉCRIT (2026-08-22) — `wama_data/core/coding.py`

Le découpage ci-dessus est repris **tel quel**, moteur d'abord :

| pièce du modèle | dans WAMA | note |
|---|---|---|
| le protocole `.pro` | `Protocole` / `Comportement` / `Modificateur` — gelés, sérialisables JSON dans les deux sens | prêt pour un kind de manifeste ; l'éditeur reste une app à part, comme dans le modèle |
| l'interface générique | ⏳ **pas écrite, et c'est volontaire** | elle doit se GÉNÉRER du protocole ; l'écrire avant la vue déclarative rejouerait la rigidité qu'on combat |
| la session | `SessionCodage` — refuse de démarrer **sans média**, un seul geste (`marquer`) qui ouvre/ferme | la règle « pas de codage sans support » vient du modèle, pas d'un excès de prudence |

Ce que le codage comportemental apporte et que le modèle MATLAB n'avait pas : l'**état ouvert**
(`end = None`), les **modificateurs typés**, les **sujets** (deux personnes tiennent le même état
sans se fermer l'une l'autre), et l'**exclusion mutuelle** — ouvrir un mode ferme le concurrent, et
cette fermeture SUBIE est tracée (`closed_by='exclusive'`) séparément d'une fermeture voulue.

> **Le point qui justifie tout le module** : `rejouer(protocole, média, gestes, codeur=…)` est le
> point d'entrée du codage AUTOMATIQUE. Un modèle de vision produit une liste de gestes, on la
> rejoue, et l'on obtient **exactement** la sortie d'un codage humain — validée par le même
> protocole, refusée aux mêmes endroits (un code hors éthogramme est rejeté que la faute vienne
> d'un doigt ou d'une hallucination). Il n'y a donc PAS de « module de codage IA » à écrire :
> il y a un champ `codeur` qui change. `codage_accord` mesure ensuite l'écart entre les deux.

⚠ **Trois fois** le même piège dans la couche d'adaptation vers pandas : une valeur absente devient
`NaN`, qui n'est ni `None` ni faux et traverse tous les tests d'absence naïfs — réintroduisant la
sentinelle numérique que le modèle refuse. La détection est désormais **une seule fonction**
(`manquant()`), et une régression versionnée la garde.

### 9ter.5 L'EXPORT — ce que le livrable chercheur doit produire

`exporterPresentDans` explique la forme du fichier remis aux chercheurs, mesurée en §6.7 :

- colonnes nommées **`table.variable`** — d'où les en-têtes `0_15.startTimecode` ;
- **nom du trip en 1ʳᵉ colonne** — d'où « Trip Name » ;
- filtre **« présent dans »** appliqué à l'export lui-même ;
- **concaténation entre trips** (`exportConcatenation`, `concatTrips`) — c'est ainsi qu'on passe
  d'une passation à 377 lignes pour 69 ;
- **aperçu** avant écriture ;
- formats : `.csv`, `.txt`, `.xlsx`, `.mat`.

> ⚠ **La présentation sur-promet.** Elle annonce une option « Échantillonnage » dans les options
> d'export : **0 occurrence dans le code**. C'est la troisième fois de cette cartographie qu'un
> document annonce ce que le code ne fait pas (avec `frequency` déclarée et le Calculator « à
> venir ») — et la raison pour laquelle chaque affirmation ici est confrontée aux sources.

⛏ Seul reste non lu : le **Calculator**, annoncé « à venir » en 2019 — et l'absence de toute
fonction de calcul d'indicateurs dans les 151 fonctions de BIND_GUI confirme qu'il n'a jamais
existé. C'est le module que WAMA écrira **sans modèle**, et le seul de la chaîne dans ce cas.

---

### 9ter.6 PORTAGE SCHÉMA-DRIVEN du Segmenter et de l'Exporter (2026-08-23)

> **Consigne de Fabien, qui commande toute cette section** : « reprendre le concept et le
> fonctionnement pour l'adapter et le porter à WAMA en schéma-driven. Pas juste transposer le
> code. » Les sources lues : `BIND_GUI.mlapp` (le code VIVANT — 2 537 lignes d'export, extraites
> de l'archive ; les 3 `.m` de `BIND_GUI/src/+export` n'ont **aucun appelant**) et
> `claude/WAMA-Data/Présentation_BIND_GUI.pptx` (diapos 12 et 17 = les schémas fonctionnels,
> diapos 14-16 et 18 = les captures d'interface).

#### A. Ce qui manque au Segmenter — mesuré, pas supposé

> ✅ **PORTÉ le 2026-08-23.** La colonne de droite était l'état au 22/08 ; la troisième dit ce qui
> a été livré. Les deux seuls manques restants sont d'**INTERFACE**, pas de moteur.

| BIND (diapo 12 + captures) | WAMA au 22/08 | au 23/08 |
|---|---|---|
| Temporelle **simple** : ancre ± inf/sup | ✅ `autour(ancres, offset_debut, offset_fin)` | ✅ inchangé |
| Temporelle **double** : Table 1 **+ offset**, Table 2 **+ offset** | ❌ `jonction()` n'a **aucun offset** | ✅ `offset_debut` / `offset_fin`, appliqués APRÈS l'appariement |
| ☐ **Répéter sur les prochains segments** | ❌ absent | ✅ `repeter` — défaut **inversé** (voir ci-dessous) |
| Conditionnelle : **liste de conditions** `(C1) (C2)…` | ❌ **un seul** prédicat | ✅ `Condition` déclarée, N par chaîne |
| **Connecteur logique** `ET / OU / XOR / NON` + imbrication | ❌ absent | ✅ **arbre** validé à la déclaration |
| Opérateurs **texte** (`contient`) | ❌ 6 opérateurs numériques | ✅ **14 opérateurs**, filtrés par la SORTE de colonne |
| Cible **Event \| Situation** au choix | ❌ produit toujours des `segments` | ✅ deux **ports** du même masque |
| « Présent dans » **dans le geste** | 🔶 `present_dans` existe, mais à part | 🔶 inchangé — c'est un CONTEXTE d'export (point 5), traité côté Exporter |
| **Filtrage manuel** occurrence par occurrence | ❌ absent | ⏳ **c'est la CARD** (point 6) — mécanisme existant, aucune interface à écrire |
| Nom **auto-dérivé** des paramètres (`deb_fin_0_0`) | 🔶 `nom` libre | ✅ `nom_jonction()` / `nom_chaine()`, `nom` libre restant possible |

> **Le défaut de `repeter` est INVERSÉ par rapport à BIND, délibérément.** Chez lui, ne pas cocher
> la case produit UN segment ; ici, `repeter=True` est le défaut et produit toute la série. Deux
> raisons : c'est le comportement historique de `jonction()` (l'inverser serait une régression
> silencieuse pour les chaînes existantes), et produire la série est le cas courant d'une analyse
> — le cas particulier mérite d'être demandé plutôt que subi.

> ⚠ **Ce que la lecture du code a corrigé dans le tableau ci-dessus.** « Répéter sur les prochains
> segments » n'est pas seulement une case : son implémentation (`appliquer_prochainSeg`) apparie
> les deux tables **par INDEX** et, quand elles n'ont pas le même nombre d'occurrences, ne sait que
> refuser — « Impossible de répéter sur les prochains segments puisque la taille des tableaux sont
> differents. Veuillez filtrer les tables. » L'appariement **par le temps** que `jonction()` faisait
> déjà n'a pas ce cas d'échec : le choix WAMA était bon, et on sait maintenant contre quoi.

#### B. La chaîne conditionnelle — le morceau qui demande une vraie traduction

BIND présente une liste `(C1) (C2)…` et un champ **texte** éditable, `ET (C1 ,C2)`, dont l'exemple
affiché est `NON(C1 ET C2 OU(C4 XOR (C5 ET C6)))`. Transposer cela donnerait un champ texte et un
parseur. Ce n'est pas ce qu'on fait — voici la traduction, point par point.

> ⚠ **CE QUE LA LECTURE DU CODE A ÉTABLI (2026-08-23), et qui rend ce §B plus fort qu'écrit.**
> L'assemblage n'est pas « du texte » au sens vague : c'est du texte **passé à `eval()`** —
>
> ```matlab
> ET = @and;  OU = @or;  NON = @not;  XOR = @xor;
> master_mask = eval(strrep(operations, 'C', 'masks.C'));
> ```
>
> Trois conséquences, toutes vérifiables :
> - **Le rattrapage est un `uialert` unique** — « Probleme avec les connecteurs, Impossible de
>   segmenter » — qui ne dit NI quelle condition, NI où. C'est ce que le point 2 remplace.
> - **`ET`/`OU`/`XOR` sont BINAIRES** (`@and`, `@or`, `@xor`) et `NON` unaire. Le constructeur
>   (`fusion_connecteur`) fabrique donc l'imbrication à gauche par concaténation de chaînes :
>   `ET ( ET (C1 , C2) , C3 )` pour dire « les trois ».
> - **L'exemple affiché par l'interface n'est pas dans la syntaxe qu'elle accepte.** Il montre de
>   l'INFIXE (`C1 ET C2`) là où `eval()` n'exécute que du PRÉFIXE (`ET(C1, C2)`) — `ET` est une
>   poignée de fonction, pas un opérateur. L'exemple est un **contre-exemple**. C'est le symptôme
>   exact d'un texte qui sert à la fois de modèle et d'affichage : les deux divergent sans que
>   rien ne le signale. ⚠ Une version antérieure de cette ligne recopiait l'exemple **sans son
>   `ET`** (`NON(C1 C2 OU(…))`) — corrigé ici sur le source.

1. **Une condition est une DÉCLARATION typée, pas une ligne d'interface.**
   `Condition(cle='C1', source='commentaires_simu', champ='texte', operateur='contient',
   valeur='FIN')` — donc sérialisable, donc **entrant dans un manifeste**, donc rejouable et
   exportable en script. Chez BIND elle vit dans une struct d'application (`app.export.ficN`,
   `save_env_*`), c'est-à-dire dans une session.

2. **L'assemblage est un ARBRE ; le texte n'en est que le RENDU.**
   `{"op":"ET","args":["C1",{"op":"OU","args":["C2",{"op":"NON","args":["C3"]}]}]}`
   La chaîne `NON(C1 C2 OU(…))` reste une **saisie** acceptée (on la parse vers l'arbre) et un
   **affichage**, jamais le modèle. Ce que ça gagne, concrètement : une référence à un `C4`
   inexistant, une arité fausse ou une parenthèse manquante se refusent **à la déclaration** au
   lieu d'échouer à l'exécution — et l'arbre se compare, se diffe et se stocke.

3. **Les opérateurs se DÉCLARENT dans un registre, et se filtrent par SORTE de colonne.**
   Même geste que `STATISTIQUES` du Calculator : un registre `{nom → (test, sortes admises)}`. Le
   gain n'est pas la centralisation, c'est que **l'UI se dérive de la donnée** — une colonne texte
   ne propose pas `>=`, une colonne numérique ne propose pas `contient`.

   > ⚠ **DEUX AFFIRMATIONS DE CETTE LIGNE ÉTAIENT FAUSSES**, corrigées le 2026-08-23 après lecture
   > du code et de `data_types.py`. Les consigner importe : la seconde a failli faire écrire un
   > branchement qui n'existait pas.
   >
   > - **« BIND offre une liste plate » — NON.** Il filtre, mais **sur le mauvais axe** : la liste
   >   dépend de ce qu'on CRÉE (une situation n'a droit qu'aux 6 comparaisons numériques, un
   >   événement aux 16), jamais du type de la colonne testée. On peut donc y appliquer `<` à une
   >   colonne de texte — MATLAB compare alors les codes des caractères et rend un masque
   >   plausible. Le défaut est plus intéressant que « pas de filtre » : filtrer sur la SORTIE est
   >   arbitraire, c'est l'ENTRÉE qui décide du sens d'un opérateur.
   > - **« WAMA a déjà `data_types.py` pour savoir de quel type est une colonne : la vérification
   >   est gratuite » — NON.** `data_types.py` type le **CADRE** (`TypedFrame.data_type`), et
   >   `TypedFrame` n'expose que `.fields`, une liste de NOMS. Rien n'y type une colonne. La
   >   vérification a donc coûté une notion neuve — la **SORTE** (numérique / texte / booléen),
   >   trois valeurs et pas une de plus — et sa dérivation depuis un `dtype`
   >   (`functions/temporal/conditions.py::sorte_de_colonne`). Elle vit dans l'ADAPTATEUR : le
   >   cœur reste sans pandas.
   >
   > **Et la sorte n'est jamais DÉCLARÉE, elle est LUE dans la donnée** — une `sorte` présente
   > dans le JSON d'entrée est ignorée. Si on pouvait la saisir, se tromper en la saisissant
   > rétablirait exactement le défaut qu'on corrige.

4. **« Que créer ? Event | Situation » devient un PORT DE SORTIE, pas un bouton radio.**
   La chaîne produit un **masque booléen**. Deux fonctions déclarées le consomment :
   `masque → events` (instants de bascule) et `masque → segments` (plages, avec l'hystérésis
   `duree_min`/`trou_tolere` déjà écrite). C'est composable, typé, et **le cœur ne bouge pas** :
   `conditionnelle()` prend DÉJÀ un masque en entrée — c'est la couche déclarative au-dessus qui
   manquait, pas le moteur.

5. **« Présent dans » est un CONTEXTE déclaré, appliqué par la brique commune.**
   BIND le recopie dans quatre fonctions (`ExportConcatPresentDans`, `ExportConEveSitPresentDans`,
   `exporterPresentDans`, `exporterTousNormalPresentDans`). WAMA a `present_dans()` : il devient un
   **champ** du geste (`contexte=[…]`), pas une quatrième variante de chaque fonction.

6. **Le filtrage manuel n'est pas une UI à écrire — c'est la CARD.**
   BIND affiche une table d'occurrences avec une case « Ignore » par ligne. WAMA possède déjà ce
   geste : une file de cards avec sélection, et un inspecteur. Le « filtrage manuel events /
   situations » de la diapo 12 est donc **la file appliquée à une collection de segments** —
   mécanisme existant, zéro interface spécifique. C'est l'exemple le plus net de ce que veut dire
   « porter le concept plutôt que le code ».

7. **Le nom se DÉRIVE des paramètres.** `deb_fin_0_0` chez BIND est construit des deux tables et
   des deux offsets. Même règle que `nom_produit()` du Calculator (`vitesse` + `moyenne` →
   `vitesse_moyenne`) : une règle déclarée, pas une saisie à retenir.

#### C. L'Exporter — la déclaration remplace la struct de session

`§9ter.5` décrit correctement ce que BIND produit. Ce qui suit dit comment WAMA le porte.

> ⚠ **PÉRIMÈTRE — recadrage de Fabien (2026-08-23), après une formulation fausse de ma part.**
> L'Exporter **n'est en aval d'aucun module en particulier**. Il exporte **tout le contenu d'un
> trip, de façon entièrement configurable** : les **tables de données**, les **méta-informations**,
> les **événements** et les **situations** — ces dernières portant les colonnes d'indicateurs que
> le Calculator y a adjointes. Vérifié dans le code : le sélecteur à trois niveaux est alimenté
> par la MÉTA (`meta.getDataVariablesNamesList` / `getEventVariablesNamesList`), et les colonnes
> d'identité `Trip Name` / `Participant` / `Scénario` sont elles-mêmes des méta-infos
> (`getAttribute('participant_id')`, `scenario()`).
>
> Ce que j'avais écrit — « la chaîne conditionnelle décide de ce qu'il y aura à exporter » — est
> faux deux fois : elle n'est **qu'un mode de segmentation parmi plusieurs** (temporelle simple,
> temporelle double, conditionnelle, états, codage vidéo), et l'export **ne dépend d'aucun** d'eux.
> Ce qui alimente l'export, c'est **l'ensemble de ce que le trip contient** à l'instant où on
> l'exporte : segments produits par n'importe quel mode, événements, données brutes, méta, et
> calculs adjoints.

1. **Une DÉCLARATION D'EXPORT remplace `app.export.ficN`** : un nom, une liste **ordonnée** de
   colonnes `source.champ`, l'identité en tête (`trip_id`, `participant`, `scénario`), le contexte
   « présent dans », la décimation, le format. Sérialisable — donc **c'est un manifeste**, et §7 de
   ce document l'a déjà tranché pour la sauvegarde d'environnement (« c'est un manifeste, pas un
   dump de session »). Les `save_env_export` / `load_export` de BIND arrivent alors **gratuitement**.

   > ⚠ **La décimation existe mais n'est OFFERTE nulle part** (relevé 2026-08-23). `subSampling`
   > vaut **1000 écrit en dur** dans le script de lot, et l'option « Échantillonnage » annoncée par
   > la présentation a 0 occurrence dans le code — c'est le cas déjà signalé en §9ter.5. Sa
   > sémantique est un **PAS** (`for i = 1:sub_sampling:length`), donc « garder une ligne sur N »,
   > **pas** « couper après N » : les deux lectures donnent des fichiers différents et seule la
   > première est la sienne. Elle devient ici un champ déclaré (`Declaration.decimation`, ≥ 1),
   > et **l'aperçu s'applique APRÈS elle** — montrer les 20 premières lignes brutes d'un export
   > décimé au 1000ᵉ ne montrerait pas l'export.

2. **Les 4 modes de concaténation sont DEUX AXES, pas quatre branches.** BIND croise deux cases
   (`ConcatTrip`, `ConcatSituationEvents`) en quatre `elseif` qui recopient chacun la même boucle
   d'écriture. WAMA déclare `regroupement = {lots: bool, declarations: bool}` et **une seule**
   implémentation de groupement : les quatre modes deviennent une conséquence, pas un chemin de code.

   > ✅ **CONFIRMÉ SUR LE CODE (2026-08-23).** Les quatre branches de `exportation` (`normal`,
   > `concat_event_situation`, `concat_trip`, `concat_all`) parcourent toutes la **même matrice**
   > `data_for_all{i_fic, i_trip}` — déclarations × trips. Concaténer ou non sur chaque axe donne
   > exactement ces quatre modes : ce sont bien deux booléens.
   >
   > ⚠ **Et les branches coûtent CINQ défauts, pas un.** La ligne précédente n'en citait qu'un ;
   > le relevé ligne à ligne en donne cinq, tous dans le code recopié — c'est l'argument, pas le
   > style :
   > 1. `concat_all` accumule dans la **mauvaise variable** (`dataconcat_fic = [dataconcat; …]` au
   >    lieu de `[dataconcat_fic; …]`) : seule la **dernière déclaration de chaque trip survit** ;
   > 2. `concat_all` et `concat_trip` lisent `i_trip` / `i_fic` **après la fin de leur boucle** —
   >    nom de fichier et chemin sont ceux du dernier tour (c'est le défaut déjà cité) ;
   > 3. `concat_all` concatène **horizontalement** (`,`) là où les trois autres empilent (`;`) ;
   > 4. le `header` retenu est celui de la **dernière** déclaration alors que les données en
   >    concatènent plusieurs, **aux colonnes différentes** ;
   > 5. deux `try … catch` **à corps vide** avalent en silence les incompatibilités de taille.
   >
   > Une implémentation unique n'en a aucun — non par talent, mais parce qu'il n'y a plus quatre
   > endroits où diverger. Les cinq ont un test dans `wama_data/core/tests_export.py`.

2bis. **Il y a DÉJÀ deux conventions d'en-tête dans le même système** (relevé 2026-08-23, non
   anticipé). L'interface produit `table.variable` (`strcat(tables, '.', vars)`) — d'où les
   en-têtes `0_15.startTimecode` du livrable décrit en §9ter.5. Le chemin script
   (`ExportTrip2Files.buildHeader`) produit le nom de variable **NU**, précédé d'un `trip_id` ; et
   sa branche multi-occurrences est du **code mort** qui référence une variable jamais définie
   (`i_occurrence`) — elle lèverait si on l'atteignait. Deux chemins, deux conventions, dont une
   qui ne peut pas s'exécuter. C'est pourquoi l'en-tête est ici un **CHAMP de la colonne déclarée**
   (`Colonne.entete`, défaut `source.champ`) et non une reconstruction par chemin.

3. **L'interface ne s'écrit pas, elle se génère de la déclaration.** Le sélecteur à trois niveaux
   (type → table → variables), l'ordre `▲▼✕`, l'aperçu : ce sont des **rendus** du schéma. WAMA a
   déjà `param_schema.py` + `WamaParams` qui font exactement cela côté apps.

4. **L'aperçu est l'export borné à N lignes**, pas un second chemin. Chez BIND `ebApercu` est une
   fonction distincte : deux chemins qui peuvent diverger, donc un aperçu qui finit par mentir.

#### D. Ordre de travail

⚠ **Les deux chantiers sont INDÉPENDANTS** — il n'y a pas de dépendance à respecter, seulement une
priorité à choisir. (Ma formulation précédente, « Segmenter d'abord parce que la chaîne
conditionnelle décide de ce qu'il y aura à exporter », est fausse : voir l'encadré de PÉRIMÈTRE
en C.)

- **Le Segmenter** a **plusieurs modes** de production — temporelle simple, temporelle double,
  conditionnelle, états, codage vidéo — dont chacun crée des situations **ou** des événements.
  La chaîne conditionnelle est **un mode parmi eux** ; c'est celui dont le manque est le plus
  large, pas celui dont les autres dépendent. Les manques listés en A touchent aussi la
  segmentation double (offsets, « répéter ») et le filtrage manuel.
- **L'Exporter** exporte **tout ce que le trip contient** : données, méta-infos, événements,
  situations et les indicateurs qui y ont été adjoints. Il est prêt à être écrit **dès
  maintenant** — il n'attend rien du Segmenter.

#### E. Ce qui a été LIVRÉ le 2026-08-23, et ce qui reste

Les deux chantiers étant indépendants, les deux ont été faits dans la même session.

| livré | briques | preuve |
|---|---|---|
| **Chaîne conditionnelle** (B, points 1-4 et 7) | `core/conditions.py`, `functions/temporal/conditions.py` | 41 tests cœur + 26 frontière |
| **Manques temporels** (A : offsets de jonction, `repeter`, second port) | `core/segmentation.py` (`jonction`, `bascules`) | 15 tests |
| **Exporter** (C, points 1-4) | `core/export.py`, `functions/io/export.py` | 37 tests cœur + 12 frontière |

`wama_data` passe de **198 à 327 tests**, tous verts. Les gardes centrales ont été vérifiées
« mordantes » (neutralisées une à une → échec au symptôme exact), conformément à la leçon des deux
harnais qui avaient annoncé « 0 FAIL » sur du vide.

**Reste, et chaque manque est NOMMÉ :**

1. **Le filtrage manuel** (A, point 6) — c'est la **file de cards + l'inspecteur**, mécanisme
   existant. Rien à écrire dans le monde Data : le geste est de brancher une collection de
   segments sur la file. À faire quand une app pilotera le Segmenter.
2. **« Présent dans » dans le geste** (B, point 5) — `present_dans()` existe et reste à part. Sa
   place est un **champ `contexte` de la déclaration d'export**, pas une variante de fonction ;
   il n'est pas encore câblé dans `Declaration`.
3. **L'Exporter n'est PAS au catalogue de fonctions**, et c'est une décision. Un puits ne rend
   aucune donnée typée : aucune des sept `FunctionCategory` ne lui convient, et en ajouter une
   modifierait le **substrat partagé avec le Lab** pour une valeur que rien ne consomme (aucune
   interface ne rend les catégories). Où vit ce nœud est exactement la **décision D13**. Un test
   (`PasDeDeclarationAuCatalogueTest`) verrouille l'abstention pour qu'elle ne se défasse pas par
   inadvertance.
4. **Formats `xlsx` / `mat`** — déclarés, refusés **explicitement** par le cœur (ils demandent une
   bibliothèque, donc l'adaptateur). Rendre un CSV sous une extension `.xlsx` serait pire.
5. **L'interface de codage** (5ᵉ mode) — inchangée : elle dépend du Visualizer.

⚠ **Ce que ces deux portages ont appris sur la méthode**, au-delà du code : sur les **cinq**
affirmations de ce §9ter.6 que la lecture du code a pu confronter, **deux étaient fausses** (« BIND
offre une liste plate », « `data_types.py` sait typer une colonne ») et **une sous-estimait** le
problème d'un facteur cinq (« les défauts qui vont avec » → cinq défauts distincts). Toutes trois
allaient dans le même sens : **elles rendaient le travail plus facile qu'il n'était**. C'est la
même famille d'erreur que le pivot inexistant qui a fait reverter le premier Exporter — écrire la
spécification depuis un schéma et une intuition plutôt que depuis le code vivant.

Le Calculator, lui, reste valide : ses deux modes sont confirmés par la diapo 7 (« Calcul
d'indicateurs globaux et par situations ») et par la ligne du §7 (« transformation de colonnes …
indicateurs par situation »).

⚠ **Corpus à lire AVANT tout travail Data** : `claude/WAMA-Data/` — `Présentation_BIND_GUI.pptx`
(schémas fonctionnels + captures), `BIND_contexte.doc`, `Fonctions.xlsx`, `Usages_BIND.xlsx`,
`Plugins_BIND.xlsx`, `DOCUMENTATION_SauvegardeETchargementDeConfigPlugins.docx`. Aucun des six
n'avait été ouvert avant le 2026-08-23, alors qu'ils étaient dans le dépôt : c'est la cause
première des deux erreurs de cette session.

---

## 9quater. MANIPULATION DES DONNÉES — persistance, colonnes calculées, conteneur natif

> **Origine : échange avec Fabien du 2026-08-23**, tranché dans la foulée. Cette section clôt
> **D3** et **D9**, et complète le reste ouvert de **D10** (« où vit la table annexe et comment
> elle se déclare »). Elle répond à une question qui n'avait jamais été posée en ces termes :
> **quand une colonne calculée reste-t-elle dans sa table, et quand en sort-elle ?**

### 9quater.1 L'état MESURÉ au moment de trancher (2026-08-23)

Un point de la discussion partait d'une prémisse fausse — utile à consigner, parce que c'est elle
qui rend les décisions ci-dessous peu coûteuses.

| | mesuré |
|---|---|
| Écriture SQLite dans `wama_data` | **AUCUNE** — zéro `INSERT` / `CREATE TABLE` / `to_sql`. `sources/trip.py:53` ouvre en `mode=ro`, commentaire à l'appui : « on n'écrit **jamais** dans une source importée » |
| Objet d'exécution | `TypedFrame` = `pandas.DataFrame` + `data_type` + `meta`. **C'est déjà pandas, partout** — il n'y a rien à décider là-dessus |
| Lecture | **PARESSEUSE** — les instants sont chargés, les valeurs par tranche. Motif écrit dans le module : la base réelle fait 1,28 Go / 5,26 M lignes / 6 cadences |
| Explorer | ⏳ — et c'est, **avec le Connector, le seul module sans blocage déclaré** (`modules.py`) |

**Conséquence** : « on stocke en SQLite puis on réinjecte » est un PLAN, pas l'existant. Rien n'est
encore écrit, donc **rien n'est encore à migrer** — c'est le moment le moins cher pour nommer le
conteneur et fixer la règle.

### 9quater.2 D3 TRANCHÉE — le conteneur natif s'appelle `.wdat`

**Il faut séparer deux choses que le mot « `.trip` » confond :**

| | quoi | renommé ? |
|---|---|---|
| **Le lecteur** `TripReader` | lit le format **externe** de BIND | **NON, jamais.** WAMA lira des `.trip` pour toujours ; l'appeler autrement rendrait le code faux |
| **Le conteneur natif** | ce dans quoi WAMA écrira | **il n'existait pas et n'avait pas de nom** — c'était ça, la vraie question |

**Pourquoi `trip` ne convient pas comme nom natif** — et l'argument n'est pas une préférence, il a
un **précédent daté dans ce dépôt** : le 2026-08-20, le type `SECTIONS` a été renommé `SEGMENTS`,
motif écrit dans `wama/common/catalog/data_types.py` — « *« section » est connoté routier, or WAMA
Data doit rester universel* ». `trip` est la même faute un cran au-dessus : il présuppose un
**déplacement** là où le besoin réel est **une acquisition multi-flux datée**. Un labo qui analyse
des données temporelles sans aucun trajet — y compris le LESCOT — n'a pas à manipuler des « trips ».

**Nom retenu : `.wdat`** (« enregistrement WAMA »). Trois raisons :

1. il dit ce que la chose **est** (une acquisition datée), pas ce qu'on en fait ;
2. il est neutre sur le domaine — routier, oculométrie, audio, comportement ;
3. ⚠ **il évite une collision réelle** : `dataset` était le candidat naturel et il est **déjà pris**
   — c'est un *kind* de manifeste, et il désigne un **corpus**, pas un enregistrement. Un `.trip`
   BIND est **une passation**. Nommer le fichier `.dataset` aurait mis deux granularités sous un
   mot.

> ⚠ **`.rec` était écarté d'avance** : c'est l'extension de RTMaps, que l'Importer doit lire
> (`functions/io/rtmaps_rec.py`). Le `w` n'est pas décoratif.

### 9quater.3 D9 TRANCHÉE — `time`, et `timecode` reste un ALIAS D'ENTRÉE

Ce n'était pas un arbitrage de goût : la mesure tranche seule.

1. **`time` est déjà le champ canonique** de la taxonomie partagée — `CANONICAL_FIELDS` le déclare
   pour `TIMESERIES`, `SIGNAL`, `EVENTS` et `GEO_TRACK`. Cette taxonomie est la **glu inter-mondes**
   (le Lab en dépend) : la renommer coûterait bien au-delà du monde Data.
2. ⚠ **`timecode` est DÉJÀ PRIS DANS WAMA, avec un AUTRE SENS ET UN AUTRE TYPE.** Ses 4 occurrences
   du monde Médias sont le **timecode AV positionnel** du Transcriber — `mm:ss` / `hh:mm:ss`, donc
   une **chaîne** (`transcriber/.../edit.js`, `edit.html`, `app_registry.py`). Celui de BIND est un
   **flottant en secondes**. Adopter le mot donnerait **deux types incompatibles au même mot dans
   la même plateforme** — exactement la juxtaposition de vocabulaires que WAMA s'interdit.
3. **La normalisation existe déjà et fonctionne** : `sources/tabular.py:23` accepte
   `('time', 'timestamp', 'timecode', 't', 'temps', 'time_s', 'seconds')` en entrée et rend `time` ;
   `sources/trip.py` lit les colonnes `timecode` / `startTimecode` de BIND et produit
   `time` / `start` / `end`. **Il n'y a rien à écrire, seulement à ne pas défaire.**

### 9quater.4 LA RÈGLE — une nouvelle table SSI la clé temporelle change

> **Une colonne calculée reste dans SA table tant que la CLÉ TEMPORELLE ne change pas.
> Elle en sort dès qu'elle change.**

⚠ **Cette règle n'est pas nouvelle : elle était DÉJÀ APPLIQUÉE par le code sans être écrite nulle
part.** C'est exactement ce qui sépare les deux modes du Calculator, et les deux
`FunctionCategory` qu'ils portent (`functions/temporal/calculation.py`) :

| mode | catégorie | granularité | résultat |
|---|---|---|---|
| colonnes dérivées (glissant, dérivée, cumul) | `ENRICHER` — « ajoute des champs à l'entrée » | **inchangée** | colonne **adjointe** (`_avec_colonne` : `df[nom] = valeurs` sur une copie) |
| indicateurs par segment | `AGGREGATE` — « agrège par groupe » | **change** | **nouveau** cadre, de type `segments` |

La consigner ici lui donne le statut de règle, au lieu de la laisser être une propriété émergente
que le prochain module pourrait contredire sans s'en apercevoir.

#### Les trois cas, et ce qu'ils donnent

**(a) Deux colonnes de la MÊME table** (« multiplier une colonne par une autre, comme dans Excel »)
→ même clé temporelle → **même table**, une colonne de plus. Le nom se **dérive** par règle
(`nom_produit()` existe : `vitesse` + `moyenne` → `vitesse_moyenne`), jamais saisi — mêmes motifs
qu'en §9ter.6 B7.

**(b) Deux colonnes de tables à PAS DIFFÉRENTS** → trois options, et **l'interpolation est la pire** :

| option | verdict |
|---|---|
| **Interpoler** pour aligner, puis multiplier | ❌ — c'est ce que **D6** refuse (« jamais d'interpolation », admise en **affichage** seulement). Multiplier deux colonnes interpolées fabrique des valeurs que personne n'a mesurées, et rien dans la sortie ne le dit |
| **Agréger** le flux rapide sur les intervalles du flux lent | ✅ **défaut recommandé** — `calcul_par_segment` **existe déjà**, n'invente aucune valeur, et répond au besoin réel dans la majorité des cas |
| **Rééchantillonner** vers une **table annexe** | ✅ **en option, explicite et tracée** — sanctionné par D10. La grille change, donc c'est *nécessairement* une nouvelle table |

> **Ne jamais offrir l'interpolation silencieuse.** Si l'utilisateur veut croiser deux cadences,
> on lui propose l'agrégation ; s'il veut vraiment une grille commune, il la **déclare**.

**(c) Calcul sur une PORTION, via `present_dans`** → **pas de nouvelle table.** Restreindre à un
contexte ne change pas la clé temporelle : ce sont les mêmes instants, en moins. La colonne revient
donc dans la table d'origine **avec des trous** (`None` hors contexte) — ce qui est *plus*
informatif qu'une table à part, puisqu'on lit le contexte dans la donnée elle-même.

> ⚠ **Nuance qui compte, et qui justifie de calculer SUR la restriction plutôt que de masquer
> après.** Une moyenne glissante calculée sur la restriction n'est pas celle calculée sur tout puis
> masquée : aux **bords du contexte**, la seconde laisse fuir des échantillons extérieurs dans la
> fenêtre. Les deux sont des réponses différentes à des questions différentes — restreindre
> d'abord est celle que l'utilisateur demande quand il dit « seulement pendant les dépassements ».
>
> **Corollaire** : le contexte doit être **tracé sur la colonne**. Deux colonnes de même nom
> calculées sur deux contextes différents doivent être distinguables. C'est **D11** (« paramètres
> en colonnes/métadonnées plutôt que dans le NOM de la table ») appliqué un cran plus bas.

#### D10 complété — où vit la table annexe, et comment elle se déclare

La table annexe n'est **pas un concept à inventer** : c'est un `TypedFrame` de plus, qui se
distingue par sa **PROVENANCE DÉCLARÉE**. Le patron existe déjà un cran plus bas — `_tracer()` du
Segmenter pose `origin` sur **chaque segment produit**, pour qu'on puisse distinguer plus tard un
segment codé par un humain d'un segment proposé par un modèle. Même geste, au niveau de la table :

- **elle vit dans le même conteneur** (`.wdat`) que ses sources, jamais dans un fichier à part —
  une table dérivée séparée de son enregistrement devient orpheline à la première copie ;
- **elle porte sa provenance en méta** : tables sources, grille cible, méthode d'alignement,
  contexte éventuel. Pas dans son NOM (D11) ;
- **elle est nommée par règle dérivée**, comme tout le reste (§9ter.6 B7) ;
- **elle n'est jamais créée implicitement** : la produire est un geste, exactement comme l'entrée
  au RAG est un geste et non un balayage.

### 9quater.5 Ce qu'on PERSISTE — la déclaration, pas les valeurs

Le geste d'interface décrit par Fabien est le bon : l'utilisateur voit la colonne calculée
apparaître **dans la même table** que l'originale, et décide ensuite. Mais **ce qu'on écrit n'est
pas ce qu'il voit** :

> **On persiste la DÉCLARATION. Les valeurs ne sont qu'un CACHE, keyé par elle.**

Trois raisons, toutes déjà des principes du dépôt :

1. **une colonne matérialisée devient périmée vis-à-vis de sa source sans que rien ne le signale** —
   c'est la même famille de défaut que les statuts de `.md` qui surestiment l'avancement ;
2. **le volume** — l'enregistrement réel fait déjà 1,28 Go ; matérialiser chaque colonne dérivée le
   multiplie, et la lecture paresseuse existante n'aurait plus de sens ;
3. **c'est la doctrine WAMA partout ailleurs** — manifestes, `write_back` réversible, « jamais
   d'apply auto ». La déclaration est l'objet durable ; le reste se recalcule.

Les valeurs ne s'écrivent **en dur** qu'à l'**export**, où elles sont précisément le produit demandé.

#### 9quater.5bis TROIS NIVEAUX D'ÉCRITURE — « on écrit là où c'est RÉGÉNÉRABLE » (2026-08-24)

> **Précision de Fabien**, qui corrige une formulation trop courte de ma part. J'avais écrit que
> « on n'écrit jamais dans une source importée » interdit de *muter* une source. C'est vrai mais
> incomplet : ce qui est protégé, ce sont les **RAW DATA**. Le fichier **importé**, lui, est un
> **fichier de TRAVAIL**, et on a le droit d'écrire dedans.

| niveau | écriture | régénérable depuis |
|---|---|---|
| **raw data** — `.rec`, CSV, vidéos, hors dépôt | ❌ **jamais** | — c'est l'origine |
| **fichier de travail** — le `.wdat` | ✅ **oui** | raw + protocole + gestes |
| **déclarations** — `Vue`, `Declaration`, conditions, protocole | ✅ | elles SONT la source |

> **Le critère tient en une ligne : on écrit là où c'est RÉGÉNÉRABLE.** Le fichier de travail est
> writable *précisément parce que* le perdre ne perd rien d'irremplaçable.

⚠ **LE POINT QUI AURAIT PU CASSER LE MODÈLE — et qui ne le casse pas.** Une chose du fichier de
travail n'est pas dérivable des raw data : le **codage humain**. Un chercheur qui code trois heures
de vidéo crée de l'information qui n'existe nulle part ailleurs.

Sauf que `core/coding.py` l'a déjà résolu : le codage n'est pas stocké comme un RÉSULTAT, il est
capturé comme une suite de **GESTES REJOUABLES** — `rejouer(protocole, media, gestes, codeur=…)`,
même point d'entrée pour un humain et pour un modèle de vision. **La formule exacte est donc
`raw + protocole + gestes`** : les gestes sont l'apport humain irréductible, ils sont petits,
déclaratifs, et se rangent avec le protocole, pas avec le conteneur.

#### ⚠ Conséquence : D13 n'est PAS une question de côté

Le protocole de traitement est un manifeste **`pipeline`** (§9bis : « le kind existe déjà, aucun
nouveau kind à créer »). Mais **il lui manque le nœud fonction — c'est D13**.

Or sans ce nœud, le protocole n'est pas exprimable. Sans protocole exprimable, le fichier de
travail **n'est pas régénérable**. Et alors y écrire n'est plus une commodité, c'est un **risque** :
ce qu'on y écrit devient irremplaçable sans qu'on l'ait décidé.

> **D13 est la précondition du droit d'écrire dans le fichier de travail**, pas un détail de canvas.

Les briques de contrôle existent déjà : `SignalMeta.is_base` sépare acquis et dérivé, `_tracer`
pose l'`origin` sur chaque segment produit, `rejouer()` ferme la boucle.

⚠ **Et « régénérable » est une propriété à EXERCER, pas à déclarer.** Le même jour, une docstring
promettait une isolation qui n'existait pas faute d'un `try` (§9decies). Tant qu'aucun test ne
**reconstruit** un fichier de travail depuis `raw + protocole + gestes` et ne compare, la propriété
reste une affirmation — et c'est justement celle sur laquelle repose le droit d'écrire. **C'est le
vrai contenu du garde-fou G7.**

### 9quater.6 L'Explorer EST l'interface du Calculator

L'« Excel intégré » (vue tableur + graphe, tracé de courbes) n'est **pas un module de plus à côté
du Calculator** : c'est **son interface**. Deux constats le montrent —

- le **Calculator est écrit et éprouvé** (49 tests) et **n'a aucune UI** ;
- l'**Explorer** est déclaré « explore un dataset en table et en graphe », est ⏳, et est —
  **avec le Connector — le seul module sans blocage déclaré**, donc écrivable immédiatement.

La vue tableur est exactement le lieu où l'on ajoute une colonne calculée, où l'on voit le résultat
avant de le garder, et où la règle de §9quater.4 devient visible pour l'utilisateur : une colonne
qui s'ajoute à la table qu'il regarde, ou un onglet qui s'ouvre parce que la clé temporelle a
changé. **La règle n'a donc pas à être expliquée : elle se montre.**

### 9quater.7 Le CŒUR de l'Explorer — mesuré le 2026-08-23, et il est déjà écrit à 80 %

> **Recadrage de Fabien avant d'écrire une ligne** : « on parle bien du **cœur**, pas de l'UI ».
> La mesure lui donne raison deux fois — non seulement l'UI serait prématurée, mais le cœur qu'on
> croyait à écrire existe déjà et **n'attend qu'une pièce**.

#### Ce qui existe déjà, et qu'il ne faut donc PAS écrire

`core/temporal.py` (440 lignes, `TemporalReferential` + `Signal`) expose déjà l'essentiel de ce
qu'un explorateur demande :

| besoin de l'Explorer | brique existante |
|---|---|
| arbre des tables / colonnes / cadences | `sources.probe()` → `SourceInfo` |
| charger un enregistrement | `sources.load()` → `TemporalReferential` |
| **courbe zoomable sur des millions de points** | **`decimate_values(nom, t0, t1, buckets, colonne)`** — et la décimation rend les **min/max RÉELS** (premier+dernier de tranche perdrait une pointe) |
| ligne du curseur (toutes les colonnes à l'instant *t*) | `snapshot(t)` |
| navigation d'événement en événement | `next_event` / `previous_event` / `containing` / `overlapping` |
| étendue commune à des flux de cadences différentes | `common_span()` |

⚠ `buckets` est **littéralement** le paramètre d'un graphe zoomable : `buckets = largeur en pixels`.
La brique a été écrite pour ça (« la décimation est une condition d'existence : 2 M points sur
2000 px »), bien avant qu'on parle d'Explorer.

#### ⚠⚠ LE TROU : le référentiel et le catalogue NE PARLENT PAS LE MÊME OBJET

Il y a **deux mondes parallèles dans `wama_data`, et rien ne les relie** :

```
sources/ + core/temporal.py  →  Signal / TemporalReferential   (paresseux, indexé, décimant, SANS pandas)
functions/                   →  TypedFrame                     (pandas — ce que mangent Segmenter, Calculator, Exporter)
```

Vérifié le 2026-08-23 : **aucune fonction de conversion dans un sens ni dans l'autre.** Conséquence
concrète — on sait charger un `.trip` en référentiel, on sait calculer sur un `TypedFrame`, mais
**on ne sait pas prendre un flux de l'enregistrement chargé et lui appliquer une fonction du
catalogue.**

> **Et le dépôt le disait déjà**, sans que le lien ait été fait : le blocage déclaré du Référentiel
> dans `modules.py` est « **AUCUN consommateur** — la brique est inerte tant qu'un module ne s'en
> sert pas ». Il n'a aucun consommateur **parce que rien ne convertit sa sortie en ce que les
> fonctions mangent**. Le blocage n'était pas « personne ne s'en est encore servi », c'était
> « personne ne PEUT s'en servir ». Troisième fois de la journée qu'un fait vivait dans le dépôt
> sans être relié à sa conséquence.

**Le cœur de l'Explorer est donc : le PONT + le VIEW-MODEL** (« quels flux, quelle fenêtre, quelle
résolution, quelles colonnes dérivées ») — ce dernier sérialisable, donc une déclaration, comme
l'export (§9quater.5). Zéro UI, **zéro bibliothèque**.

#### ✅ LE PONT est livré — `wama_data/frames.py` (2026-08-23, 34 tests)

`frame_depuis_referentiel()` / `frame_depuis_signal()` à l'aller, `signal_depuis_frame()` /
`adjoindre()` au retour. **Le blocage déclaré du Référentiel est levé** : un flux chargé traverse
une fonction du catalogue et revient interrogeable (test `PontCompletTest`, sur le Calculator ET
sur la chaîne conditionnelle).

**Il vit à la RACINE du monde**, pas dans `core/` (qui est pur, sans pandas), pas dans `sources/`
(pur aussi, et qui n'a pas à connaître le catalogue), pas dans `functions/<domaine>/` (qui héberge
des fonctions *déclarées au catalogue* — le pont n'en est pas une, il est ce qui permet de les
alimenter). C'est une frontière à part entière, au même niveau que `modules.py`.

**Les quatre pièges qu'il traite, tous MESURÉS dans le code et chacun avec son test :**

| # | piège | pourquoi il est vicieux |
|---|---|---|
| ① | **le temps de session ≠ le temps du flux** | le référentiel travaille en temps de SESSION, chaque `Signal` en temps LOCAL (`± offset`). Un pont bâti sur le `Signal` seul **désalignerait silencieusement** deux flux d'offsets différents dans le même cadre |
| ② | **la colonne temporelle brute peut être PÉRIMÉE** | les accesseurs font un `SELECT *`, donc les lignes portent encore `timecode`. Or les instants ont pu être **ré-horodatés** à l'import : la colonne brute rendrait l'ANCIENNE valeur. Le temps vient donc **toujours** des `times`, et l'axe brut est **retiré** du cadre — le laisser mettrait deux colonnes de temps contradictoires dans le même tableau |
| ③ | **le contrat des lignes est réel mais N'ÉTAIT PAS DÉCLARÉ** | `StreamSpec.rows` est typé `Callable[[int,int], Any]` alors que les deux lecteurs rendent en fait une `List[Dict]`. Le pont le **vérifie** au lieu de l'espérer : un 3ᵉ lecteur rendant des tuples échoue ici avec un message clair, pas trois couches plus loin |
| ④ | **un cadre qui revient d'un calcul n'est pas une donnée acquise** | `SignalMeta.is_base` existait DÉJÀ pour ça (« la PROVENANCE : sans elle, impossible de savoir ce qu'un recalcul peut écraser sans perte ») et n'était pas employé en ce sens. `signal_depuis_frame()` force `is_base=False`, **sans paramètre pour le contourner** |

> ⚠ **Ce que le pont ne sait PAS faire, et qui n'est pas un oubli** : distinguer un flux de DONNÉES
> d'un flux d'ÉVÉNEMENTS. Un `Signal` ne porte pas sa famille — structurellement, « des instants +
> des colonnes » décrit les deux. On déduit donc `SEGMENTS` s'il y a des fins, `TIMESERIES` sinon,
> et l'appelant peut imposer le type. **Déduire la famille du texte de `comments`
> (« data · 3 colonne(s) ») serait prendre une TRACE pour une RÈGLE** — l'erreur déjà consignée.
> C'est un manque réel du modèle `Signal`, à traiter avec D8 (type « intervalle »).

> ⚠ **`adjoindre()` REFUSE d'écraser un flux existant** — `TemporalReferential.add()` le refusait
> déjà, et on ne contourne pas : écraser en place rendrait irrécupérable ce qui l'a produit. Un
> recalcul se range sous un nom dérivé, comme une colonne calculée.

#### ✅ LE VIEW-MODEL est livré — `wama_data/vue.py` (2026-08-23, 31 tests)

Seconde moitié du cœur. Une `Vue` déclare **quels flux (`Piste`), quelle fenêtre et quelle
résolution (`Fenetre`), quelles colonnes dérivées (`ColonneDerivee`)** — et elle est
**sérialisable en JSON pur, aller-retour vérifié**. C'est donc une déclaration au sens de
§9quater.5 : *on persiste ça, pas les valeurs.* `appliquer()` calcule à la demande et **n'écrit
rien** (test à l'appui : le référentiel ne gagne aucun flux au passage).

**⚠ CE QU'IL APPORTE VRAIMENT : la règle de §9quater.4 devient EXÉCUTABLE — et DÉRIVÉE DU
CATALOGUE.** Elle n'est plus une doctrine écrite ni une propriété émergente du Calculator : c'est
la `FunctionCategory` **déclarée par chaque fonction** qui décide.

| | catégories | conséquence |
|---|---|---|
| la clé temporelle **ne change pas** | `TRANSFORM` · `ENRICHER` | la colonne **s'adjoint** à la table regardée (`Resultat.tables`) |
| la clé temporelle **change** | `DETECTOR` · `INDICATOR` · `RESAMPLER` · `AGGREGATE` · `JOIN` | **table à part** (`Resultat.annexes`) |

Ce découpage n'est pas une invention : il se lit dans les définitions mêmes des catégories
(`function_catalog.py`) — « ajoute des champs/colonnes à l'entrée » et « même type en sortie »
d'un côté ; « produit des events », « produit un scalaire », « **change l'échantillonnage** »,
« agrège par groupe », « combine plusieurs entrées » de l'autre. `RESAMPLER` est littéralement le
cas (b) de §9quater.4.

> **Conséquence pratique : ajouter une fonction au catalogue la range automatiquement du bon côté,
> sans toucher `vue.py`.** Un test le vérifie sur **tout** le catalogue, et un autre refuse qu'une
> catégorie non classée tombe d'un côté par défaut — elle lève, en demandant qu'on tranche.

> ⚠ **`Resultat` sépare `tables` et `annexes` À DESSEIN** : c'est la règle rendue **visible**.
> L'interface n'a rien à décider — une colonne qui s'ajoute à la table qu'on regarde, ou un onglet
> qui s'ouvre. C'est ce que §9quater.6 annonçait : *« la règle n'a pas à être expliquée, elle se
> montre »*.

> ⚠ **`serie()` ne passe PAS par `appliquer()`** — un tracé qui matérialiserait un cadre pandas
> annulerait la décimation, qui existe précisément pour ne pas charger 5 M points. Il appelle
> `decimate_values` du référentiel, qui agrège **dans la source** quand elle sait le faire. Et il
> exige une fenêtre bornée avec `buckets > 0` : `buckets = 0` signifie « table, échantillons
> réels », pas « choisis pour moi ».

#### Position sur les BIBLIOTHÈQUES (question de Fabien, 2026-08-23)

La réponse n'est pas la même par couche :

| couche | verdict | motif |
|---|---|---|
| **données (le cœur)** | ❌ **non** | pandas est là ; lecture paresseuse et décimation min/max sont écrites, testées, **accordées au domaine** (pas de temps variable, 6 cadences). Les remplacer = réécrire une brique qui marche |
| **rendu — courbes** | ✅ **oui, ÉTROITE** — candidat : **uPlot** (MIT, ~45 Ko) | fait pour les millions de points, se branche **directement** sur `decimate_values(buckets=largeur_px)` |
| **rendu — grille** | ✅ **oui, ÉTROITE** — **Tabulator** ou **Grid.js** (MIT) | virtualisation, tri, édition. Un *renderer*, rien de plus |
| **framework tout-en-un** (Perspective, Bokeh/Panel, Dash, Streamlit) | ❌ **NON** | chacun apporte **son paradigme d'interface, sa mise en page et souvent son modèle serveur** — donc un **second système de widgets** à côté de `WamaParams` / `wama-inspector` / cards, alors que toute la doctrine est « l'UI se génère des métadonnées », et que **G2** interdit déjà un second canvas |

> **La ligne : une bibliothèque qui DESSINE, oui ; une bibliothèque qui décide de la MISE EN PAGE,
> non.** Deux précédents du dépôt disent la même chose — le **runtime Hermes écarté**, et le
> **DeepSeek Harness dont on n'a rien intégré** (« seule leçon = registre keyé »).

⚠ **À mentionner pour l'écrivain `.wdat`, pas pour maintenant** : **DuckDB** (MIT) lit du SQLite
directement et ferait une colonne dérivée sur 5 M lignes quasi gratuitement. C'est le moteur naturel
d'un `.wdat` — mais il concurrencerait `core/temporal.py`, donc c'est une décision à part.

⚠ Quel que soit le choix : **vendoring obligatoire** (pas de CDN, cf. les 9 paquets de
`wama/static/vendors/` — aucune bibliothèque de graphe à ce jour), et **ratification par
`LICENSING.md`** (dépôt en AGPL-3.0 : MIT / Apache-2.0 / BSD conviennent, mais c'est la politique
qui tranche).

#### Autres manques mesurés, à ne pas découvrir plus tard

- **`wama_data` n'a AUCUNE surface Django** — ni `views.py`, ni `urls.py`, ni `templates/`. C'est
  une app d'`INSTALLED_APPS` qui n'existe que pour son `ready()`. L'Explorer en sera la première :
  c'est un geste d'architecture, pas un détail d'écran.
- **Aucun point d'entrée « quel dataset j'explore »** — pas de modèle `Dataset`, et
  `DATASET_SOURCES` n'est qu'une liste de validation du kind de manifeste, non réconciliée avec le
  registre des lecteurs (c'est déjà le garde-fou **G1**, cité dans le blocage de l'Importer).

---

## 9quinquies. MÉTHODES UNIVERSELLES, CAPACITÉS AGRÉGATIVES — et ce qui entre dans un REGISTRE

> **Doctrine posée par Fabien le 2026-08-23**, confrontée au code le jour même :
> « **les méthodes d'import/connexion/export sont universelles et génériques ; les CAPACITÉS de
> types, elles, sont de l'agrégation — un peu comme on ajoute de nouveaux modèles.** »
>
> Réponse courte : **oui, on est aligné, et c'était déjà à moitié implémenté** — mais le relevé a
> trouvé **six vocabulaires de formats de natures différentes**, dont un désalignement introduit
> le matin même. Cette section fixe le critère pour que la question ne se repose pas par fichier.

### 9quinquies.1 Le relevé — six vocabularies, et ils ne sont PAS de même nature

| # | où | quoi | nature | registre ? |
|---|---|---|---|---|
| 1 | `wama_data/sources/__init__.py` | lecteurs d'entrée (`register_reader`, `reader_for`, `supported_extensions`) | **CAPACITÉ** — un lecteur est du CODE qui sait lire | ✅ vrai registre… mais **il n'était pas au registre des registres** |
| 2 | `wama_data/core/export.py::FORMATS` | formats de sortie | **CAPACITÉ** | ❌ **dict en dur** — écrit le matin du 23/08, **corrigé l'après-midi** |
| 3 | `manifests/builtin/dataset.py::DATASET_SOURCES` | 8 chaînes de validation | **vocabulaire figé** | ❌ tuple en dur — c'est le garde-fou **G1**, toujours ouvert (voir §9quinquies.4) |
| 4 | `app_registry.py::MEDIA_CATEGORIES` + `*_EXTENSIONS` | taxonomie média | **TAXONOMIE fermée** | ❌ **et c'est juste** — domicile unique déclaré, gardé par `check_redundancy.py` |
| 5 | `common/utils/export_formats.py::VOCABULAIRE` | libellé / icône / groupe (téléchargement) | **PRÉSENTATION** | ❌ et c'est juste |
| 6 | `common/utils/output_formats.py` | formats early-binding (réglage avant génération) | **PRÉSENTATION** | ❌ et c'est juste |

**Le désalignement était donc réel mais étroit** : deux entrées sur six, et l'une des deux (2) était
de moi. Les quatre autres sont correctes — ce qui compte autant que les défauts, parce que
« tout mettre en registre » serait la sur-correction évidente.

### 9quinquies.2 LE CRITÈRE — trois questions, dans cet ordre

> **Registre** quand l'ajout apporte du **COMPORTEMENT** et que la liste doit pouvoir s'allonger
> **sans toucher le moteur**.
> **Table de vocabulaire** quand l'ajout n'apporte que des **MOTS** (libellé, icône, catégorie) et
> que la liste est **fermée par la nature du domaine**.

| question | oui → | non → |
|---|---|---|
| ① **L'ajout apporte-t-il du comportement ?** Un lecteur *sait lire*, un écrivain *sait écrire*. Un libellé + une icône ne savent rien faire | registre | vocabulaire |
| ② **Un TIERS doit-il pouvoir l'ajouter sans modifier le moteur ?** (une app, un autre monde, un plugin) | registre | vocabulaire |
| ③ **La liste est-elle fermée par la NATURE du domaine ?** `image/video/audio/document/archive/text/3d` n'est pas extensible « par ajout de capacité » — c'est une taxonomie | vocabulaire, **domicile unique** | registre |

Et une quatrième, qui décide non pas *registre ou pas* mais *registre des registres ou pas* :

| ④ **L'utilisateur doit-il en voir l'état et pouvoir le RAFRAÎCHIR ?** | alors il entre au **registre des registres** — et hérite du bouton, de l'endpoint, de la permission, du chronométrage et du compte-rendu, sans une ligne d'UI |

⚠ **`MEDIA_CATEGORIES` répond NON à ③ et reste donc une taxonomie** — et son domicile unique est
déjà déclaré et **gardé mécaniquement** (`check_redundancy.py` : « `app_registry.py` : LE domicile
des vocabulaires média »). Le monde Médias n'a rien à changer. C'est le contre-exemple utile :
la réponse n'est pas « tout en registre ».

### 9quinquies.3 Faut-il un KIND DE MANIFESTE par famille de capacité ? **NON**

Trois raisons, toutes déjà mesurées ailleurs dans le dépôt :

1. **La question a déjà été tranchée pour la clé des registres**, et le relevé vaut ici :
   `registries.py` en tête — sur 7 surfaces catalogues, **4 seulement** correspondent à un kind,
   **3 kinds n'ont aucune page**, **3 pages ne sont pas des kinds**. `manifest_kind` est donc un
   **LIEN facultatif**, jamais la clé. Un kind par famille de capacité multiplierait les kinds
   morts.
2. **Une capacité qui est du CODE se déclare par du code**, comme `FunctionSpec`. Le kind
   `function` couvre déjà cette famille ; §9bis avait conclu la même chose pour le traitement
   (« le kind `pipeline` EXISTE DÉJÀ — aucun nouveau kind à créer »).
3. **Ce dont la couche manifeste a besoin n'est pas un kind de plus**, c'est que `DATASET_SOURCES`
   cesse d'être un tuple figé — point suivant.

### 9quinquies.4 ⚠ Pourquoi G1 ne peut PAS être fermé naïvement (trouvé le 2026-08-23)

Le garde-fou **G1** demande que `DATASET_SOURCES` soit réconcilié avec le registre des lecteurs.
La correction évidente — faire lire le registre par `manifests/builtin/dataset.py` — est
**interdite** : ce fichier est dans le **SUBSTRAT**, et le registre est dans un **MONDE**. Le
substrat importerait `wama_data`, c'est-à-dire exactement le défaut corrigé au déport du 22/08
(« `load_all()` citait `wama.common.data` ET `wama_lab.cam_analyzer` **en dur** »).

**La forme juste est l'inverse** : un registre de types de source vit dans le substrat (comme
`FUNCTION_CATALOG` vit dans `wama/common/catalog/`) et **chaque monde y pousse ses types depuis
son `apps.py:ready()`**. `DATASET_SOURCES` devient alors la vue de ce registre, et non une liste.
⏳ **Non fait** — c'est une modification du substrat, à coordonner.

### 9quinquies.5 Ce qui a été FAIT le 2026-08-23

- **`core/export.py::FORMATS` est devenu un REGISTRE** (`enregistrer_format()`,
  `formats_disponibles()`, `formats_ecrivables()`). ⚠ La distinction qui porte le modèle :
  **un format DÉCLARÉ n'est pas un format ÉCRIVABLE.** `xlsx` et `mat` appartiennent au livrable
  (§9ter.5) donc une déclaration a le droit de les nommer, mais leur écrivain demande une
  bibliothèque et vit dans l'adaptateur. **L'écart entre déclaré et écrivable EST la dette, et il
  est mesurable** au lieu d'être supposé.
- **Les deux capacités du monde entrent au registre des registres** — `lecteurs_data` (partagé par
  l'Importer ET le Connector) et `formats_export_data`. ⚠ **Déclarés depuis `wama_data/apps.py`,
  jamais depuis `common/registries_builtin.py`** : le monde POUSSE, le substrat ne tire jamais.
  Un test vérifie par AST que le substrat n'importe aucun monde.

> ⚠ **Le rafraîchisseur des lecteurs a un piège qui a failli passer.** Un `importlib.reload()` du
> paquet `sources` **VIDE le registre** au lieu de le recharger : le paquet repeuple via
> `_register_builtins()`, qui fait `from . import trip, tabular` — des modules déjà en cache, donc
> un import no-op. Mesuré en remettant la version naïve : **0 lecteur**, et le compte-rendu
> annonçait « ok ». On reprend donc la séquence éprouvée du rafraîchisseur de fonctions —
> `invalidate_caches` → instantané → purge → rechargement (modules découverts par `pkgutil`, jamais
> cités en dur) → **restauration intégrale si quoi que ce soit casse**.

### 9quinquies.6bis Le même anti-patron ailleurs — les TESTS NOCTURNES (corrigé le 2026-08-23)

> **Question de Fabien** : « peut-on aussi alimenter les tests nocturnes au fur et à mesure ? »
> **Réponse : non — et c'est mieux ainsi.** « Au fur et à mesure » était précisément le symptôme.

`nightly_scenarios.py::_run_wama_data` nommait **2 modules en dur** alors que le monde en comptait
**15** : **13 suites ne tournaient jamais la nuit**, dont les 411 tests écrits ce jour-là. Et sa
garde ne pouvait pas le voir —

```python
if not total:
    return False, "aucun test chargé — les modules de test ont-ils été déplacés ?"
```

⚠ **Elle protège contre une DISPARITION, jamais contre une OMISSION. Une liste en dur ne peut
détecter que sa propre péremption vers le bas.** C'est exactement le critère de §9quinquies.2
appliqué un cran plus loin : la liste des suites est une **capacité agrégative** (écrire un fichier
de test = ajouter une capacité de vérification), donc elle se **découvre**, elle ne s'énumère pas.

**Corrigé** : `_modules_de_test(paquet)` parcourt le paquet (`pkgutil`) et accepte les deux
conventions (`tests_*` du monde Data, `test_*` par défaut Django). Résultat mesuré : **15 modules,
411 tests, 0 échec** au lieu de 2 modules. **Écrire un `tests_*.py` suffit désormais à le faire
tourner la nuit** — il n'y a plus rien à alimenter.

> ⚠ **Le correctif crée son propre mode de panne, et il est gardé** : `walk_packages` ne descend
> pas dans un répertoire sans `__init__.py`. Une suite entière pourrait donc cesser d'être
> découverte sans qu'aucun test n'échoue — seul un total baisserait, et personne ne connaît un
> total par cœur. D'où `wama/common/tests_nightly.py`, dont le contrôle central compare la
> découverte au **système de fichiers** (chemin délibérément différent de celui qu'il vérifie) et
> **nomme les fichiers manquants** dans son message d'échec. Et le compte-rendu nocturne rapporte
> désormais le **nombre de modules**, pas seulement le nombre de tests.

### 9quinquies.6 Ce qui reste à décider

| # | question |
|---|---|
| **G1** | le registre de types de source dans le substrat, alimenté par les mondes (§9quinquies.4) |
| — | **écrivains `xlsx` / `mat`** : déclarés, sans écrivain. Le geste est prévu (`enregistrer_format('xlsx', ecrivain=…)` depuis l'adaptateur) |
| — | le **Connector** partage le registre des lecteurs — à confirmer quand il aura une surface : une base branchée « en connexion » est-elle un lecteur comme un autre, ou une capacité distincte (connexion vivante vs import figé) ? |

---

## 9sexies. AUDIT A — les trois déclarations confrontées entre elles (2026-08-23)

> **Demande de Fabien** : avant toute UI et avant l'API assistant, vérifier que ce qui a été écrit
> dans la journée **tient ensemble**. `Vue`, `Declaration` d'export et l'arbre de conditions ont été
> écrits **le même jour, sans jamais être confrontés**.

### 9sexies.1 Ce qui tenait déjà, et n'était pas garanti

- **✅ La composition Vue → Export marche sans une ligne de glu.** `Resultat.tables` est un
  `Mapping[str, TypedFrame]`, exactement ce que `lot_depuis_frames()` attend. **Vérifié en
  exécutant**, pas déduit : `livrable_A, 12 lignes`, en-têtes
  `['trip_id', 'vitesse.time', 'vitesse.value', 'vitesse.value_moyenne']`. Les **annexes** aussi.
- **✅ Deux patrons de validation cohérents** : `__post_init__` pour l'intrinsèque, fonction libre
  pour ce qui dépend d'un contexte (le référentiel, la liste des clés).
- **✅ `check_redundancy` : zéro trouvaille** dans ces fichiers.

### 9sexies.2 🔴 Le défaut principal — une propriété AFFIRMÉE qui n'existait pas

| | `to_dict` / aller-retour, AVANT l'audit |
|---|---|
| `Vue` | ✅ testé |
| `Declaration` (export) | ❌ **rien** |
| `Condition` | ❌ **rien** |

Or **les deux docstrings l'affirmaient** : §9ter.6 B1 — « une condition est une DÉCLARATION typée…
donc **sérialisable**, donc **entrant dans un manifeste** » ; §9quater C1 — « Sérialisable — donc
**c'est un manifeste** ».

> ⚠ **C'est le défaut reproché le matin même à §9ter.6 (« une spec écrite depuis une intuition ment
> dans le sens optimiste »), reproduit l'après-midi dans mes propres docstrings.** `Vue` avait la
> propriété uniquement parce qu'elle a été écrite en dernier, en y pensant.

**Corrigé** : `Condition.to_dict()` / `condition_depuis_dict()`, `Declaration.to_dict()` /
`declaration_depuis_dict()`, aller-retour **JSON pur** testé pour les deux, et **relecture validée
comme à la construction** — un manifeste ne doit pas être la porte d'entrée des états impossibles.
L'arbre logique, lui, **était déjà du JSON pur par construction** : rien à sérialiser.

> ⚠ **`sorte` n'est PAS sérialisée, délibérément.** Elle est **lue dans la donnée** par
> l'adaptateur ; la sérialiser inviterait à la relire, donc à laisser une déclaration contredire la
> colonne qu'elle décrit — le défaut même que le filtrage par sorte corrige.

### 9sexies.3 🟠 Le vocabulaire — `source` était DÉJÀ PRIS

| concept | avant | après |
|---|---|---|
| la table nommée | `source` (export, conditions) · `flux` (vue) | **`flux`** partout |
| la colonne | `champ` (export, conditions) · `colonnes` (vue) | **`champ`** partout |

**Le choix de `flux` n'est pas une préférence** : dans ce monde, **`source` désigne déjà un
fichier/format à lire** — `SourceReader`, `SourceInfo`, `sources/`, `SourceInfo.streams`. L'employer
pour un nom de table était une **ambiguïté réelle**. Et `champ` s'aligne sur le substrat
(`TypedFrame.fields`, `CANONICAL_FIELDS`, `required_fields`/`produced_fields`).

> ⚠ **Le paramètre `colonne` des fonctions du catalogue N'EST PAS renommé, et ce n'est pas une
> exception oubliée** : c'est le paramètre d'une fonction, pas un champ de déclaration. Une
> fonction nomme ses arguments comme elle veut ; le renommer casserait les `ParamSpec` déclarés et
> toute déclaration sérialisée. La frontière est nette : **`champ` dans les déclarations,
> l'argument de la fonction dans les `params`.**

⚠ Le renommage était **gratuit à cet instant précis** — rien n'est encore persisté. Le même
argument que `.wdat` (§9quater.2) : c'est le moment le moins cher, et il ne se représentera pas.

### 9sexies.4 🟠 Le nommage dérivé — quatre règles, trois lieux, dont une f-string

La doctrine §9ter.6 B7 (« le nom se DÉRIVE, il ne se saisit pas ») était **appliquée par quatre
règles éparpillées**, et l'une n'était pas une règle :

```
nom_produit()                functions/temporal/calculation.py   ← dans l'ADAPTATEUR
nom_jonction(), nom_chaine() core/conditions.py                  ← dans le CŒUR
Colonne.titre                core/export.py
f"{d.flux}_{d.fonction}"     vue.py:259, EN DUR                  ← pas une règle du tout
```

**Corrigé** : brique unique `wama_data/core/noms.py` — `normaliser()` (point de passage unique),
`nom_produit`, `nom_jonction`, `nom_annexe`. Les anciens emplacements **réexportent** au lieu de
redéfinir, et un test vérifie **l'identité des fonctions** (`assertIs`) : une redéfinition locale,
même à l'identique, échoue. La brique **n'a aucune dépendance** — condition pour que
`conditions.py` l'importe sans cycle, ce qu'un test garde par AST.

> ⚠ **`Colonne.titre` reste dans `export.py`, à dessein** : ce n'est pas un nom dérivé de
> paramètres mais un **en-tête de fichier**, dont la convention (`flux.champ`) appartient au
> livrable chercheur et se surcharge colonne par colonne. Le rapprocher mêlerait deux règles qui
> n'ont ni la même source ni la même raison de changer.

> ⚠ **Le chemin par défaut du nom d'annexe n'était couvert par AUCUN test** : tous passaient un
> `nom=` explicite, donc la f-string n'était jamais exercée. C'est ainsi qu'une non-règle survit.

### 9sexies.5 🟡 Ce qui reste ouvert après l'audit

| # | point |
|---|---|
| 1 | **Deux fonctions `valider`** exportées (`core.conditions`, `vue`) → collision à l'import. Non traité : les renommer touche des appelants, et la collision n'a encore mordu personne |
| 2 | **Aucun rattachement manifeste** pour les trois déclarations, alors que §7 tranche « c'est un manifeste, pas un dump de session ». Le kind `pipeline` est le candidat (§9bis : « aucun nouveau kind à créer »), mais il lui manque le nœud fonction — **D13** |
| 3 | **Rien ne câble Vue → export** : la composition marche, elle n'est ni exposée ni testée hors de l'audit. Une composition qui marche par accident se casse au premier changement |

`wama_data` : **411 → 437 tests**.

---

## 9septies. DOMAINES, MODES, SPATIAL — trois questions, une seule réponse (2026-08-23)

> **Questions de Fabien** : le monde Médias fonctionne en **domaines** (un onglet par domaine) et
> en **modes**. Faut-il des domaines dans le monde Data — « domaine temporel » vs « domaine
> spatial » ? Les modes du Segmenter (temporel simple, double, conditionnel, états, codage)
> aideraient-ils à générer l'UI schéma-driven ? Et faut-il un **mode de segmentation spatiale** ?
>
> **Réponse courte : non, non, et non — mais il manquait bien deux choses**, et ce ne sont pas
> celles qu'on croyait.

### 9septies.1 Domaines — le critère écrit le matin même y répond

`app_modes.py` (refonte du 2026-08-23) pose : **« un domaine est un WORKFLOW distinct, PAS un type
de fichier »**, et le critère qui tranche est *« le domaine se justifie quand la surface de
RÉGLAGES et le workflow divergent »*.

« Temporel » et « spatial » ne divergent ni en réglages ni en workflow : on cherche des bornes dans
les deux cas. **Ce n'est pas un domaine.**

### 9septies.2 Modes — la même doctrine l'écrit noir sur blanc

> ⚠ **« Ne PAS confondre mode d'UI et workflow de backend.** L'imager choisit txt2img / img2img /
> style2img **selon les entrées fournies** : c'est une décision de MOTEUR. »

Les modes du Segmenter se choisissent **exactement ainsi** : selon ce qu'on a en entrée (des
ancres ? deux flux ? un signal ? une vidéo ?). Décision de moteur, pas switch d'UI.

**Et ils sont déjà déclarés, plus finement que des modes** : chacun est un `FunctionSpec` avec ses
**ports typés** et ses `ParamSpec`.

> **`app_modes.py` est ce qu'il faut quand l'UI doit se dériver d'une app qui n'est PAS décomposée.
> Le catalogue de fonctions est ce qu'on obtient quand elle l'EST.** Une app média est une file
> monolithique avec UN schéma de params — il faut un moyen déclaratif de la découper en onglets.
> Le monde Data part déjà découpé.

Pour la génération d'UI, le catalogue donne même **plus** : `can_connect()` sur les ports typés
répond à « quelles fonctions proposer sur ce que j'ai sous la main », ce qu'`accepts` approxime
côté média. **L'alignement est conceptuel, pas structurel — il n'y a rien à transposer.**

### 9septies.3 Le spatial — mesuré dans `cam_analyzer`, et il n'a jamais eu besoin d'un mode

`wama_lab/cam_analyzer/utils/intersection_analyzer.py::find_intersection_windows` fait déjà de la
segmentation spatiale. Relevé ligne à ligne :

```python
dist = haversine(gps['lat'], gps['lon'], i_lat, i_lon)
if dist <= radius:  … ouvre / poursuit la fenêtre
else:               … ferme
# puis : fusionne si écart ≤ merge_gap_s OU si jamais sorti au-delà de exit_distance_factor × radius
#        et jette les fenêtres < min_duration_s
```

C'est **`conditionnelle()` avec hystérésis**, à un masque près — `merge_gap_s` = `trou_tolere`,
`min_duration_s` = `duree_min`.

> **La segmentation spatiale n'est donc pas un mode : c'est une COLONNE DÉRIVÉE suivie de la
> chaîne conditionnelle existante.** La distance a la même clé temporelle que la trace dont elle
> vient → `ENRICHER` → elle reste dans la table (§9quater.4) → la chaîne la voit comme n'importe
> quelle colonne numérique.

⚠ **Et c'est ce qui rend `distance_carrefour <= 40 ET vitesse > 30` exprimable sans une ligne
neuve.** Un « mode spatial » séparé n'aurait *jamais* pu se mêler à un prédicat temporel : il
aurait fallu un troisième mode pour ça, puis un quatrième. **C'est l'argument décisif, et il n'est
pas esthétique.**

> ⚠ **Correction assumée** : la réponse donnée une heure plus tôt — « il faut un opérateur de
> masque spatial, donc un point d'extension de la chaîne » — était **plus compliquée que
> nécessaire**. C'est la mesure de `cam_analyzer` qui l'a corrigée. Aucun point d'extension : une
> colonne dérivée suffit.

### 9septies.4 Les DEUX manques réels, tous deux trouvés par la mesure

**① L'hystérésis de VALEUR n'existait pas.** `conditionnelle()` porte une hystérésis **de TEMPS**
(`duree_min`, `trou_tolere`). `cam_analyzer` a en plus `exit_distance_factor` — « ne referme pas si
le sujet n'est jamais *vraiment* sorti ». **Sans ce mécanisme, porter cam_analyzer serait une
RÉGRESSION** : un GPS qui tremble sur la frontière découperait un passage unique en confettis.

→ `core/segmentation.py::masque_hysteresis()` — le **déclencheur de Schmitt**, deux seuils, dans
les deux sens (`<=` pour une distance, `>=` pour une vitesse). ⚠ **Pas bit-à-bit l'équivalent** de
la fusion a posteriori de cam_analyzer, et le module le dit : lui ouvre deux fenêtres puis les
recolle, le Schmitt n'en ouvre jamais qu'une. Les deux coïncident dans le cas courant et diffèrent
aux bords. La forme en flux est la bonne généralisation — elle ne demande pas de connaître l'avenir.

**② La distance géodésique était implémentée QUATRE fois**, toutes hors du monde Data :
`intersection_analyzer::haversine`, `ego_pose::_haversine_m`, `cam_analyzer::make_local_frame`,
`gps_map_match::_local_frame` (dont le commentaire dit déjà « cohérent avec … cam_analyzer »).

→ `core/geo.py` est le **domicile unique**. Les copies du Lab sont des **candidates à l'adoption**,
nommées dans le module pour que le portage soit un geste et non une redécouverte. ⚠ Une position
absente rend une distance **absente**, jamais une distance : la calculer sur `0.0` placerait le
sujet au large de l'Afrique — énorme, plausible, et faux.

### 9septies.5 Livré, et ce qui n'a délibérément PAS été écrit

| | |
|---|---|
| `core/geo.py` | haversine + distances à un point — domicile unique (11 tests) |
| `core/segmentation.py::masque_hysteresis` | hystérésis de valeur, deux seuils, deux sens (8 tests) |
| `functions/geo/spatial.py::distance_a_point` | **ENRICHER** déclaré au catalogue — le nom de colonne se dérive du nom du POINT (11 tests) |

⚠ **PAS de `segment_dans_rayon()`.** Elle ne demanderait aucune brique neuve (distance +
`segment_chaine_conditionnelle`) et dupliquerait le seuil et l'hystérésis. Même arbitrage, mot pour
mot, que le « temps passé au-dessus d'un seuil » déjà écarté de `core/calculation.py`.

**Le portage de cam_analyzer est attesté, pas promis** : `tests_spatial.py::CasCamAnalyzerTest`
refait sa zone à rayon avec les briques génériques, montre que le tremblement de frontière découpe
en confettis **sans** l'hystérésis de valeur et pas **avec**, et croise spatial et temporel dans une
seule chaîne. Le portage lui-même reste à faire — périmètre `wama_lab`.

`wama_data` : **437 → 472 tests**. ⚠ Et la découverte nocturne (§9quinquies.6bis) est passée de 15
à **18 modules toute seule** : le correctif de la veille a payé le jour même.

### 9septies.6 Une vraie ZONE (polygone, couloir) — MESURÉ comme faisable, DIFFÉRÉ à dessein

> **Question de Fabien** : le cas cam_analyzer est un rayon autour d'un point. Mais définir une
> **zone spatiale** est un cas possible. Faut-il l'ajouter maintenant, ou sera-ce facile plus tard ?

**« Facile plus tard » a été VÉRIFIÉ, pas affirmé.** Trois mesures :

| cas | verdict |
|---|---|
| **zone RECTANGULAIRE** | ✅ **gratuite aujourd'hui** — `ET(C1, C2, C3, C4)` sur `lat`/`lon`, sans rien ajouter |
| **colonne BOOLÉENNE** (ce que rendrait un point-dans-polygone) | ✅ la chaîne la consomme : `sorte_de_colonne` rend `booleen`, `== True` s'applique |
| **booléen ✕ prédicat temporel** | ✅ `ET(dans_zone, vitesse >= 30)` fonctionne |

**Tout l'aval d'un masque spatial est donc déjà en place.** Il ne manque que l'`ENRICHER` qui
produit la colonne — une fonction, ~40 lignes, aucun risque d'architecture.

**Différé quand même, et pour une raison qui n'est pas la paresse** : la question ouverte n'est pas
l'algorithme, c'est **la FORME de la zone dans la déclaration**.

- **paramètre** ? Une liste de coordonnées dans un `ParamSpec` — peu maniable, et un `ParamSpec`
  ne porte que des scalaires (le type `'json'` existe mais n'est rendu nulle part, cf. §9ter.6 B).
- **port typé** ? Alors il faut un `DataType` de zone. **Il n'existe pas** — `ROAD_MAP` est des
  polylignes (`geometry, id`), pas des surfaces.

Et derrière : géodésique ou plan (à quelle échelle bascule-t-on ?), règle d'enroulement, trous,
points exactement sur l'arête. **Trancher tout cela sans cas d'usage, c'est écrire une spec depuis
une intuition — l'erreur commise deux fois dans cette même journée, toujours dans le sens
optimiste.** Le couloir le long d'une polyligne pose la même question, en réutilisant `ROAD_MAP`.

⏳ **Pending nommé** : « zone spatiale — paramètre ou port typé ? et faut-il un `DataType` de
surface ? ». À trancher **au premier cas réel**, pas avant. Le coût de l'attente est nul : le motif
est prouvé et l'aval ne bougera pas.

---

## 9octies. LE POINT D'ENTRÉE — le manifeste `dataset` devient EXÉCUTABLE (2026-08-24)

> Chantier **C** du plan : « quel jeu de données j'ouvre ». La mesure a changé le périmètre — il
> n'y avait **pas de modèle Django à créer**.

### 9octies.1 La déclaration existait déjà, et n'était branchée nulle part

Le kind `dataset` se valide depuis longtemps et déclare tout ce qu'il faut — `source {type, ref}`,
`signals` typés, `reference_tables`, `records` — avec la mention explicite **« `extract=None` —
AUTORÉ, le manifeste est l'origine »**. Mais **rien ne le consommait** : zéro référence hors de son
module, et **zéro manifeste `dataset` au corpus** (`manifests/` ne contient qu'`apps`, `libraries`,
`models`).

⚠ **Même forme de trou que le Référentiel sans consommateur (§9quater.7)** : une pièce déclarée,
complète, et débranchée. C'est la troisième de la journée — le motif mérite d'être nommé :
*dans ce dépôt, ce qui manque est rarement la déclaration ; c'est ce qui la lit.*

### 9octies.2 Ce qui est livré — `wama_data/dataset.py`

| | |
|---|---|
| `verifier(body, racine)` → `Ecart` | confronte le manifeste à la source **sans la charger** (`probe` seul) — sur 1,28 Go, la différence compte |
| `charger(body, racine)` → **`(référentiel, Ecart)`** | ouvre le jeu, ne charge que les signaux **déclarés** |

**La doctrine du §9bis commande tout le module** — *« le LLM propose, la machine dispose ; un
manifeste qui VALIDE ensuite l'import est CIRCULAIRE ; le manifeste déclare des attentes
vérifiables mécaniquement et l'importer MESURE L'ÉCART »*. D'où deux choix qui n'en sont pas :

- **On ne rend jamais le référentiel seul.** Le couple force la réception de l'écart : l'ignorer
  devient un geste délibéré, pas une distraction.
- **Un écart n'est pas une erreur par défaut.** Un corpus réel est hétérogène ; refuser de charger
  parce qu'un signal manque rendrait le manifeste inutilisable sur une passation partielle.
  `strict=True` reste disponible. ⚠ Asymétrie voulue : un flux **non déclaré** ne rend pas l'écart
  non conforme (une source peut contenir plus qu'on n'en décrit) ; un signal **déclaré et absent**,
  si — c'est une promesse non tenue.

⚠ **Ce que le module NE peut PAS vérifier, et ne prétend pas vérifier** : le `data_type` de chaque
signal. `SourceInfo` rend des **noms** de flux, pas leurs types. Annoncer une vérification de type
serait promettre ce que la mesure ne donne pas.

### 9octies.3 ⚠ ~~G1 n'est pas « non réconcilié » — les deux vocabulaires sont EXCLUSIFS~~

> 🔴 **CETTE SECTION EST FAUSSE — corrigée le 2026-08-24 en §9decies.** Le constat de disjonction
> est exact, mais l'INTERPRÉTATION ne l'est pas : ce n'est pas G1, et ce n'est pas un défaut. Lire
> §9decies. La section est conservée telle quelle pour que la correction reste lisible.

Constat non anticipé, sorti d'un test :

```
DATASET_SOURCES   = (rtmaps, lsl, rosbag, csv, parquet, db, docs, other)
formats de lecteur = (trip, tabular)
                     intersection : ∅
```

- un manifeste qui nomme le lecteur réel (`tabular`) est **REFUSÉ par la validation du kind** ;
- un manifeste **valide** (`csv`) désigne un format auquel **aucun lecteur ne répond**.

> **Conséquence mesurable : aucun manifeste `dataset` valide ne peut rendre « rien à signaler »
> aujourd'hui.** `Ecart.type_source` le rapporte à chaque passage, et un test l'atteste — il
> tombera le jour où G1 sera fermé, ce qui est exactement ce qu'on attend d'un test de garde-fou.

Le correctif reste celui de §9quinquies.4 (un registre substrat que les mondes alimentent) — **non
fait**, car il touche le substrat.

### 9octies.4 ⚠ Un défaut RÉEL trouvé par le test de bout en bout

`sources/tabular.py` ne typait **aucune** colonne : `csv.reader` rend des chaînes, et le lecteur ne
convertissait que l'axe du temps servant à l'indexation. Un jeu importé depuis un CSV traversait
donc le référentiel, le pont et la `Vue` sans broncher — **puis levait dans le Calculator**
(`fmean` : « must be real number, not str »). Le test existant `test_acces_aux_valeurs` assertait
même `"1.0"` en **chaîne**, sans justification : **il enregistrait le défaut au lieu d'une décision.**

**Corrigé** — `tabular._numerise()` convertit les colonnes **entièrement** numériques.
⚠ **La décision est prise PAR COLONNE, jamais par cellule** : convertir « quand ça marche » ferait
qu'une même colonne se comparerait tantôt comme du texte tantôt comme un nombre selon les lignes —
exactement ce que `_num()` refuse dans `core/conditions.py`, et ce que la notion de SORTE suppose
absent. Une cellule vide ne disqualifie pas la colonne et devient `None` : un trou est un trou.

### 9octies.5 Le premier chemin ENTIÈREMENT DÉCLARATIF, de bout en bout

```
manifeste `dataset` → référentiel → Vue → fonction du catalogue → Declaration d'export → fichier
```

`tests_dataset.py::ChaineDeclarativeTest` le parcourt en entier, vérifie que le manifeste employé
**passe la validation officielle de son kind** (sinon il prouverait un chemin que le corpus
refuserait), et que **les trois déclarations font l'aller-retour JSON** — sans quoi la chaîne ne
serait pas rejouable.

`wama_data` : **472 → 496 tests**. ⏳ Reste au chantier du point d'entrée : l'**écrivain `.wdat`**
(aucune ligne n'écrit encore de SQLite) et un corpus de manifestes `dataset` (le dossier n'existe
pas).

---

## 9nonies. LA FAMILLE D'UN FLUX — portée comme DONNÉE (2026-08-24)

> Chantier **B** du plan : « `Signal` ne porte pas sa famille ». Le fil a livré **la correction
> attendue, plus deux défauts réels qu'il a fallu trouver pour la vérifier.**

### 9nonies.1 Le fait était connu, et jeté dans un commentaire

Le pont (§9quater.7) ne savait pas distinguer un flux de **DONNÉES** d'un flux d'**ÉVÉNEMENTS** :
structurellement, « des instants + des colonnes » décrit les deux. On déduisait donc le type de la
seule structure.

⚠ **Mais le lecteur `.trip` CONNAISSAIT la famille** : il la calcule depuis le préfixe de table
(`data_` / `event_` / `situation_`) — et la jetait dans **une chaîne de commentaire**
(`comments=f"{famille} · …"`). Le pont refusait, à raison, de la relire de là : *un libellé est une
TRACE, pas une règle*. **Le fait existait ; il n'était pas porté comme DONNÉE.**

**Quatrième occurrence du même motif en deux jours** — après le Référentiel « sans consommateur »,
la règle `ENRICHER`/`AGGREGATE` non écrite, et `SignalMeta.is_base` inemployé.

**Corrigé** : `SignalMeta.data_type`, rempli par les lecteurs avec les constantes de la taxonomie
**partagée** (jamais recopiées). `type_par_defaut()` préfère la famille **déclarée** et ne retombe
sur la structure que si la source se tait. ⚠ Le champ est typé `str` et non `DataType` à dessein —
`core/` reste sans dépendance ; ce sont les lecteurs, un étage plus haut, qui connaissent la
taxonomie.

### 9nonies.2 ⚠ Le lecteur `.trip` n'avait AUCUNE couverture — et personne ne pouvait le voir

En voulant tester la correction, constat : **les seuls tests du `TripReader` étaient
`BaseReelleTest`**, conditionnés à un fichier de **1,28 Go vivant hors dépôt** (`claude/`, gitignoré).

Le jour où ce fichier a été **déplacé**, les tests se sont mis à **sauter en silence** — un
`skipUnless` sur un chemin périmé n'annonce pas « le chemin a changé », il annonce « absente », ce
qui est **faux et rassurant**. Le lecteur le plus complexe du monde s'est retrouvé sans filet, et
le seul signal était « 10 sautés » dans un compte-rendu que personne ne lit ligne à ligne.

**Deux réponses, et la seconde compte davantage :**

1. **`wama_data/corpus.py`** — le chemin était **recopié dans trois fichiers de test**. Domicile
   unique, et un message de skip qui **dit OÙ l'on a cherché**.
2. **Un `.trip` SYNTHÉTIQUE généré** (`tests_sources::_trip_synthetique`) — les trois familles de
   table, au schéma relevé. C'est le garde-fou **G7** (« échantillon réduit versionné ») satisfait
   **sans committer de binaire**. La base réelle garde son rôle — éprouver le volume, les six
   cadences, les valeurs sales — mais **elle n'est plus la CONDITION de toute vérification**.

### 9nonies.3 ⚠ Le fixture a payé immédiatement : une FUITE DE CONNEXION

`trip.py` écrivait partout `with self._open(path) as con:` **en croyant fermer**. Or le
gestionnaire de contexte d'une `sqlite3.Connection` gère la **TRANSACTION**, pas la fermeture : il
committe ou annule, puis laisse la connexion **ouverte**. Chaque `probe`, `read`, `_columns`,
`_times`… en fuyait une — et ce module en ouvre une **par appel**, à dessein (sécurité entre fils
d'exécution). **La fuite était donc proportionnelle à l'usage.**

> ⚠ **Invisible sous Linux**, où l'on supprime un fichier ouvert sans broncher. Sous Windows, le
> fichier devient indélogeable — et c'est un dossier temporaire de test qui l'a révélé. **La base
> réelle, jamais supprimée, ne l'aurait jamais montré.** Un corpus qu'on ne fait que lire ne teste
> pas ce qu'on lui fait subir.

Corrigé par un `@contextmanager` : tous les appelants gardent leur `with`, et la fermeture devient
impossible à oublier au lieu d'être à répéter.

`wama_data` : **496 → 500 tests**, et le lecteur `.trip` passe de **0** à **9** tests qui ne
dépendent d'aucun fichier externe.

---

## 9decies. G1 — FERMÉ, et il n'était pas où on le disait (2026-08-24)

> Chantier **D** du plan. Il a commencé par relire l'énoncé du garde-fou, et **c'est cette
> relecture qui a tout changé** : ce qu'on appelait « G1 » depuis des semaines n'était pas G1.

### 9decies.1 L'énoncé réel, et la glose qui l'avait remplacé

Le tableau des garde-fous (§8) dit :

> **G1** | *aucun format privilégié* dans l'Importer/Exporter | test : **le moteur ne cite aucun
> format ; ajouter un lecteur ne le modifie pas**

Il ne dit **rien** de `DATASET_SOURCES`. Or la formule répandue — reprise dans `modules.py`, dans
§9quinquies et dans §9octies.3 — était « `DATASET_SOURCES` non réconcilié avec le registre des
lecteurs (G1) ». **Une glose avait remplacé l'énoncé, et personne n'était retourné à la source.**

Conséquence : on cherchait à fermer G1 en construisant un registre de types de source dans le
substrat… alors que **le vrai défaut tenait en une ligne, ailleurs**.

### 9decies.2 Le VRAI défaut de G1 — une ligne dans le moteur

```python
def _register_builtins():
    from . import trip, tabular      # ← livrer un 3ᵉ lecteur oblige à ÉDITER le moteur
```

G1 exige littéralement l'inverse. **Troisième occurrence en deux jours du même anti-patron** —
une énumération là où une découverte s'impose (après la liste des suites nocturnes et celle des
lecteurs dans le rafraîchisseur).

**Corrigé** : `sources.modules_lecteurs()` découvre par `pkgutil`, et c'est le **domicile unique**
— le rafraîchisseur du registre (`apps.py`) en tenait une seconde copie, désormais supprimée.

⚠ **Et un second défaut est tombé avec** : la docstring promettait « isolé pour qu'un format
manquant n'empêche pas les autres (un `.trip` reste lisible même si `openpyxl` manque) » — **sans
aucun `try`**. Une dépendance absente faisait donc échouer l'import du **paquet entier**, donc tout
`wama_data`, pour un format optionnel. **La propriété était écrite, pas implémentée.** Elle l'est.

**5 tests de garde-fou** vérifient G1 mécaniquement, dont le plus littéral : *déposer* un lecteur
dans le paquet suffit à l'enregistrer, sans toucher au moteur. Morsure vérifiée — remettre
`from . import trip, tabular` fait tomber deux tests.

### 9decies.3 ⚠ Et `DATASET_SOURCES` n'est PAS un défaut — j'avais encodé une erreur de catégorie

`source.type` dit **d'où la donnée vient** — provenance : `rtmaps`, `lsl`, `rosbag`, `csv`,
`parquet`, `db`, `docs`. Le format d'un lecteur dit **qui sait l'ouvrir** — capacité : `trip`,
`tabular`. **Deux axes, deux questions.**

Et l'intention est écrite noir sur blanc dans le kind lui-même :

> « Le chantier ultérieur n'est donc pas une projection mais un **reader source-agnostique** »

`reader_for()` résout par le chemin et **ne consulte jamais `source.type`**. Les deux vocabularies
sont donc **volontairement indépendants** — leur disjonction est une conséquence du design, pas un
symptôme.

> 🔴 **Ce que j'avais écrit la veille était donc une erreur de catégorie** : `Ecart.type_source`
> comparait une provenance à une capacité et rapportait la différence comme une divergence
> « garde-fou G1 ». Et je l'avais même mesurée en la prenant pour une trouvaille : « aucun
> manifeste valide ne peut rendre *rien à signaler* ». **C'était vrai, et c'était le symptôme de
> mon propre contrôle, pas du système.**
>
> ⚠ **Un contrôle qui sonne sur TOUT cas valide n'est pas un contrôle : il apprend à ignorer le
> compte-rendu.** Le champ devient `Ecart.lecteur` — informatif (« qui a lu »), jamais un verdict.

### 9decies.4 La leçon, et elle vaut au-delà de ce fil

**Deux fois en deux jours, une glose a survécu à l'énoncé qu'elle résumait** — « G1 =
`DATASET_SOURCES` », et « le Référentiel n'a aucun consommateur » (qui voulait dire « personne ne
PEUT s'en servir »). Dans les deux cas la formule était plus mémorable que le fait, et c'est la
formule qui a circulé.

> **Avant de fermer un garde-fou, relire son énoncé — pas ce qu'on en dit ailleurs.** Le coût de
> ne pas le faire, ici, aurait été de construire un registre substrat inutile tout en laissant la
> vraie ligne fautive en place.

`wama_data` : **500 → 504 tests**.

---

## 9undecies. LE PROTOCOLE — du langage naturel au script rejouable (2026-08-24)

> Issu d'un échange avec Fabien. **Ce n'est pas un module de plus** : c'est la description complète
> du trajet qu'un traitement parcourt, du texte que le chercheur écrit jusqu'au script qu'un
> relecteur peut rejouer. Trois choses s'y décident — D13, la borne du script généré, et le statut
> de la copie projetée. Une seule d'entre elles était correctement énoncée avant cet échange.

### 9undecies.1 La chaîne

```
   protocole en langage naturel        (le chercheur écrit ce qu'il veut faire)
        ↓  l'AI-Assistant traduit
   manifeste `pipeline`                (déclaration exécutable — le LLM propose, la machine dispose)
        ↓  WAMA déroule
   écriture dans le fichier de TRAVAIL (.wdat natif, ou .trip si compatibilité BIND)
        ↓  génération
   script rejouable                    (Python d'abord, autres langages selon couverture MESURÉE)
```

⚠ Rien dans cette chaîne n'écrit sur les **données brutes**. Le fichier de travail est régénérable
depuis `raw_data + protocole` — c'est précisément ce qui autorise à y écrire (règle posée le
2026-08-23, cf. §9quater.2).

### 9undecies.2 D13 — CLOSE : un seul kind `pipeline`, étendu

Le kind existe déjà avec la bonne forme : `{nodes:[{id, app, params}], links, layout}`, et
`kind = source|sink|app`. Il lui manque le nœud **`function`**. Trois raisons de l'étendre plutôt
que de créer un kind `data_process` :

1. **La forme du graphe est identique** — nœuds, liens, paramètres, présentation séparée.
2. §9bis l'avait déjà conclu (« aucun nouveau kind à créer ; il lui manque le nœud fonction »).
3. ⭐ **Et l'argument décisif, apparu dans l'échange** : **un protocole réel TRAVERSE les mondes.**
   « Transcris la vidéo, puis segmente les données autour des mots-clés » mêle une app du monde
   Médias et une fonction du monde Data. **Deux kinds rendraient ce protocole inexprimable** — il
   faudrait un troisième objet pour recoller les deux, c'est-à-dire réintroduire la duplication que
   la règle « une source, N rendus » interdit.

⚠ La nuance à porter dans l'exécuteur, pas dans le schéma : un nœud `app` est un **job de file**
(asynchrone, produit des fichiers) ; un nœud `function` est une **transformation typée**
(synchrone, produit un `TypedFrame`). Ce n'est pas une raison de séparer le kind — c'est une raison
de **dispatcher sur `kind`**, ce que l'exécuteur fait déjà.

### 9undecies.3 Le script généré : clé en main, et la borne n'est PAS où je l'avais mise

**§9bis portait la borne « export MATLAB borné par la bibliothèque de fonctions → squelette +
contrat de données ». Je l'ai reprise et ÉTENDUE À TOUS LES LANGAGES. C'était faux**, et Fabien l'a
relevé : on a le dataset, les segments, les colonnes, et un manifeste qui dit quelle fonction
s'applique sur quoi — il ne manque rien.

**Mesuré** : `FunctionSpec.fn` **est le callable réel** (`function_catalog.py:67`). Donc
`fn.__module__` + `fn.__qualname__` donnent le chemin d'import exact. Un script Python généré
n'imite pas le traitement, il **appelle le même code** :

```python
ref, ecart = charger(manifeste_dataset)
cadre = frame_depuis_referentiel(ref, 'vitesse')
cadre = calcul_glissant(cadre, fenetre_s=2.0)   # LA fonction que WAMA appelle, pas une copie
```

**Le vrai critère n'est pas le langage, c'est : la cible peut-elle ATTEINDRE l'implémentation ?**

| route | résultat | prix |
|---|---|---|
| **Python** | appelle les fonctions WAMA | aucun — exact par construction |
| **pont** (MATLAB appelle Python) | exact | exige WAMA installé |
| **transpilation** (vrai MATLAB) | autonome | **une SECONDE implémentation** → divergence silencieuse |

⚠ Le piège : la raison même de vouloir du MATLAB est en général « tourner **sans** WAMA » — elle
pousse donc vers la transpilation, c'est-à-dire vers le risque de divergence.

⭐ **Et il se règle par la mesure, pas par la prudence.** WAMA peut dérouler sa propre chaîne ET le
script généré sur le même dataset, puis **comparer les sorties**. La transpilation devient alors
**vérifiée** au lieu d'être crue — même principe que G7 (exercer, pas déclarer).

> **Conséquence sur la borne de §9bis : la couverture n'est pas PAR LANGAGE, elle est PAR FONCTION,
> et elle est MESURABLE.** Une fonction dont l'équivalent cible passe la contre-épreuve est clé en
> main ; le squelette n'est le **repli** que là où la couverture manque. Un « squelette toujours »
> serait une borne posée par défaut d'avoir mesuré.

### 9undecies.4 La copie projetée — et le semis inter-instances

Deux emplacements, **et c'est bien les deux** :

| | rôle | droits |
|---|---|---|
| **magasin** (`Manifest`) | LA source — éditable, versionnée, unique | lecture/écriture |
| **copie projetée** (dans le `.wdat`) | rend le conteneur autoportant | **lecture seule, estampillée** |

L'estampille (quel manifeste, quelle version) est ce qui empêche la copie de devenir une **seconde
source**. Sans elle, on aurait exactement la duplication que « une source, N rendus » interdit.

**L'usage collaboratif** que vise Fabien — plusieurs personnes sur le même dossier de dataset,
voir ce que l'autre a traité, ajouter un traitement avec son suivi — a une conséquence directe :
la copie projetée doit porter **qui et quand**, pas seulement le manifeste. C'est un **journal de
traitements**, et c'est ce qui rend le suivi lisible **sans base partagée**.

**Recopier le manifeste dans le catalogue d'une autre instance (dev → prod) : la porte existe
déjà.** Mesuré : `ingest()` est **idempotent sur `kind+key`, transactionnel, et sandbox par défaut**
(`visibility='private'`, `ingest.py:78-112`). Un manifeste venu d'ailleurs atterrit donc **privé**,
et quelqu'un doit le `promote()`. Ce n'est pas une gêne — c'est la garde.

⚠ **Un seul point à construire** : `ingest()` écrase `obj.body` **sans rien dire** si la clé existe
déjà (`ingest.py:95-111`). Entre dev et prod, `pipeline:mon-protocole` peut exister **des deux côtés
avec des contenus différents** — c'est le cas probable, pas le cas rare. L'import depuis une copie
projetée doit **comparer avant** et **montrer le conflit**.

D'où la règle, en trois temps :

- **dans une instance** — la copie est en lecture seule, **le magasin gagne** ;
- **entre instances, magasin vide** — **la copie sème** ;
- **entre instances, les deux existent et diffèrent** — **conflit montré, jamais d'écrasement
  silencieux.**

---

## 9duodecies. L'ÉCRIVAIN DE CONTENEUR — un moteur, deux schémas (2026-08-24)

> Vérifié le 2026-08-23 : **zéro écriture SQLite dans tout `wama_data`** (0 `INSERT`, 0 `to_sql`).
> Le monde savait lire trois formats et n'en savait écrire aucun — un importeur sans fichier de
> travail, c'est-à-dire une chaîne qui recommence à zéro à chaque ouverture. `wama_data/containers/`
> le comble : le pendant exact de `sources/`, registre compris.

### 9duodecies.1 Pourquoi un seul moteur

`.wdat` (natif, **D3**) et `.trip` (compatibilité BIND) partagent **toute** la mécanique : une table
par flux, un index temporel, une écriture transactionnelle par tranches, la conversion des valeurs.
Ils ne diffèrent que par des **noms** et par la **richesse du catalogue**. Deux écrivains auraient
donc dupliqué la seule partie difficile pour ne varier que la partie triviale.

Le partage des rôles est ce qui rend les deux formats comparables :

| le MOTEUR décide | le SCHÉMA décide |
|---|---|
| transaction, tranches, index, conversion des valeurs, écriture atomique | noms de table, colonnes de temps, tables de catalogue, **ce qui est perdu** |

⚠ **Le contrat est SANS ÉTAT, et la signature le garantit.** `nom_table()` reçoit le **signal**, pas
sa seule méta — sinon le schéma `.trip`, qui encode la famille dans le préfixe, devrait mémoriser ce
qu'il a vu ailleurs. Or **un schéma est un singleton de registre** : tout état retenu fuirait d'une
écriture à la suivante et entre fils d'exécution. Défaut écrit puis corrigé dans la même passe.

⚠ **G1 s'applique à l'écriture à l'identique** : les schémas sont **découverts** (`pkgutil`), jamais
cités. Et le nouveau module de test a été ramassé tout seul par le scénario nocturne (20 → 21
modules) — troisième fois que la découverte paie le jour même.

### 9duodecies.2 Écriture atomique — on écrit à côté, on renomme ensuite

Une écriture interrompue ne doit pas laisser un conteneur à moitié rempli : **il s'ouvrirait
normalement** et mentirait sur son contenu. Un `.partiel` est écrit puis renommé ; une version
existante n'est remplacée qu'une fois la nouvelle complète, et un échec la laisse intacte. Un
conteneur existant n'est jamais écrasé sans `ecraser=True` — c'est un fichier de **travail**, il
porte des traitements.

### 9duodecies.3 Ce que `.wdat` corrige — quatre faits que `.trip` connaît sans les porter

1. ⭐ **La famille n'est plus dans le NOM.** `.trip` l'encode en préfixe (`data_`/`event_`/
   `situation_`) ; ici **toutes** les tables portent le même préfixe `flux_` — le nom ne dit rien,
   le catalogue dit tout (`WamaStreams.data_type`). C'est §9nonies appliqué à l'écriture.
2. **Les unités sont écrites** (`WamaVariables.unit`) — le champ que `.trip` déclare, laisse vide
   **partout** et ne relit jamais.
3. **Les pertes d'acquisition sont une colonne**, pas un message de journal.
4. **La copie projetée du protocole est dans le conteneur** (`WamaManifests`), **estampillée** et
   marquée `read_only`. Une copie **sans estampille est refusée** : sans elle on ne peut ni la
   rapprocher du magasin ni la dater, donc elle cesse d'être une projection pour devenir une
   seconde source (§9undecies.4).

Et `.wdat` **garde** de `.trip` la structure « une table par flux » — parce qu'elle est la
conséquence de **D10** (aucune grille commune), pas une bizarrerie héritée.

### 9duodecies.4 Le schéma `.trip` est RELEVÉ, pas deviné

Neuf tables de catalogue, mesurées sur la base réelle avant d'écrire une ligne :

```
MetaDatas      (name, type, frequency INT, comments, isBase)   ← flux `data_`
MetaEvents     (name, comments, isBase)          ⚠ PAS de frequency
MetaSituations (name, comments, isBase)          ⚠ PAS de frequency
Meta{Data,Event,Situation}Variables (<x>_name, name, type, unit, comments)
MetaTripDatas / MetaParticipantDatas (key, value)   MetaTripVideos (filename, offset, description)
```

⚠ Les trois tables `*Variables` comptent **la colonne de temps elle-même** parmi les variables.
Reproduit tel quel — un outil qui itère les variables attendrait sinon une colonne de moins.

⚠ **Et le relevé a confirmé D11 sur la donnée** : les 12 situations réelles se nomment `0_15`,
`15_45`, `30_60`… — **les paramètres de fenêtre SONT le nom**, avec 312 lignes de variables pour
12 situations. C'est ce que `.wdat` refuse de reconduire.

**La compatibilité est attestée par CONTRE-ÉPREUVE**, pas par affirmation : ce que WAMA écrit,
`TripReader` — écrit contre le format de BIND, sans rien savoir de cet écrivain — le relit, et
retrouve flux, familles, instants, bornes et valeurs. Un aller-retour jugé par le seul écrivain ne
prouverait que sa cohérence interne. Même geste que la contre-épreuve CSV du lecteur `.rec`.

### 9duodecies.5 Ce que la langue de l'autre ne sait pas dire — **compté**

`Rapport.pertes` énumère, fait par fait, ce qu'un `.trip` ne porte pas : pertes d'acquisition ·
`default_lookup` · décalage **par flux** (seul un décalage par média existe) · cadence **arrondie**
(`frequency` est un entier) · cadence **perdue** sur un événement ou une situation (pas de colonne)
· **segments ouverts** (D15 — aucune représentation de « fin non observée ») · **copies projetées**
(pas de table de manifestes, donc le conteneur n'est pas autoportant) · famille **devinée** quand
aucune n'est déclarée.

> **Le pire cas n'est pas la perte, c'est la perte SILENCIEUSE** : elle laisse croire à un
> aller-retour fidèle, et c'est en la découvrant six mois plus tard qu'on doute de tout le reste.
> `Rapport.fidele` répond par oui ou non, et « non » n'est pas une erreur — c'est un fait à lire.

### 9duodecies.6 Deux défauts trouvés par la mesure, dont un dans mon propre récit

⚠ **Le lecteur `.trip` échouait sur du texte cp1252, et survivait PAR CHANCE.** Quatre tables de la
base réelle (`MetaEvents`, `MetaSituations` et leurs `*Variables`) contiennent « Ajouté à partir de
BIND_GUI » écrit par MATLAB sous Windows. Le `sqlite3` de Python décode en UTF-8 strict et lève
`OperationalError: Could not decode to UTF-8` — **pas une exception de décodage**, donc un message
qui n'oriente même pas vers l'encodage. Le lecteur y survivait parce qu'il ne lit **ni** `MetaEvents`
**ni** `MetaSituations` ; la première ligne qui aurait voulu ces déclarations aurait échoué sur un
corpus valide. Corrigé par un décodeur UTF-8 → cp1252 qui **rend le texte** au lieu de le remplacer.
⚠ L'ORDRE des codecs est l'argument : cp1252 associe un caractère à 251 octets sur 256, donc essayé
en premier il rendrait « AjoutÃ© » **sans jamais lever**. On teste le codec qui sait dire non.

⚠⚠ **Et une morsure sur six n'a pas mordu — la mienne.** J'avais écrit que `manquant()` protégeait
du piège pandas à l'écriture. Neutraliser l'appel n'a fait échouer **aucun** test, et la mesure dit
pourquoi : **SQLite coerce lui-même `NaN` en `NULL`**. Le garde-fou n'était pas porteur, et mon test
prouvait le résultat sans rien prouver du mécanisme — *un test de stockage n'est pas un test
d'usage*, la leçon de la veille appliquée à moi le lendemain.

⭐ **Le vrai trou était à côté, et la même mesure l'a montré** : `json.dumps([nan])` produit le
littéral `[NaN]`, **que la spécification JSON n'accepte pas**. Une valeur composite contenant une
absence était donc écrite sous une forme qu'aucun analyseur standard ne relit — couvert ni par
`manquant()` ni par SQLite. D'où `_sans_nan`, récursif, et un test qui mord.

`wama_data` : **541 → 590 tests** (44 pour l'écrivain, 4 pour son registre, +1 pour le trou JSON).

---

## 9terdecies. LE LECTEUR `.wdat` — et le socle SQLite que le second lecteur a révélé (2026-08-24)

> Sans lecteur, `.wdat` était **write-only** : on pouvait produire un conteneur et jamais le
> rouvrir. Or c'est exactement ce que le format est censé être — **le fichier de travail**, l'endroit
> où les traitements s'accumulent. `sources/wdat.py` le referme.

### 9terdecies.1 Le socle, révélé par le second lecteur

`TripReader` portait **~120 lignes d'accès SQLite** qui ne doivent rien au format de BIND :
ouverture en lecture seule, décodage du texte, colonnes, valeurs triées, les trois niveaux
d'agrégation. Le lecteur natif en avait besoin **à l'identique, à deux noms de colonne près**.

→ `sources/_sqlite.py::SqliteSourceReader`. Un lecteur de base concret n'écrit plus que
**`can_read`, `probe`, `read`** — c'est-à-dire sa seule connaissance du schéma. `trip.py` passe de
~300 à **171 lignes** sans perdre une garantie (73 tests `sources` inchangés).

⚠ **Symétrie exacte avec `containers/` écrit le même jour** : la mécanique est commune, la
connaissance du schéma est le seul propre de chacun. Ce n'est pas une coïncidence — lire et écrire
un conteneur posent le même problème, et il se résout du même côté.

⚠ Le module s'appelle `_sqlite.py` **par contrat, pas par politesse** : `modules_lecteurs()`
découvre les modules du paquet pour les enregistrer comme lecteurs (G1), et le préfixe `_` est ce
qui l'en exclut.

⚠ Et une règle a été **récupérée** au passage : `_times` et `_ends` ne différaient que par la
colonne lue, mais **seule la seconde** portait la remarque qui vaut pour les deux — *les fins
doivent sortir dans le même ordre que les débuts*. Une règle écrite dans une seule de deux copies
est une règle qu'on perd en touchant l'autre. `_values(table, colonne, tri)` la porte une fois.

### 9terdecies.2 Ce que le lecteur natif relit et que `.trip` ne sait pas dire

| fait | `.trip` | `.wdat` |
|---|---|---|
| famille du flux | déduite d'un **préfixe de table** | `WamaStreams.data_type`, **relue** |
| unité par colonne | champ présent, **vide partout, jamais relu** | `WamaVariables.unit`, écrite **et relue** |
| pertes d'acquisition | aucun champ | `WamaStreams.losses` |
| décalage **par flux** | seulement par média | `WamaStreams.offset` |
| protocole embarqué | aucune table | `WamaManifests`, estampillé |

⭐ **La famille se décide sur les COLONNES PRÉSENTES, jamais sur le nom de table.** C'est ce que
`.wdat` corrige : `flux_phases` ne dit rien, la présence de `start`/`end` et le catalogue disent
tout. Un lecteur qui analyserait le préfixe reconduirait le défaut qu'on vient de retirer.

### 9terdecies.3 L'aller-retour est la preuve, et il vérifie les DEUX choses

13 tests écrivent un référentiel puis le relisent. ⚠ Et l'un d'eux applique explicitement la leçon
de D15 : **prouver qu'une valeur SURVIT ne prouve pas qu'on puisse l'INTERROGER**. Le segment ouvert
est donc vérifié aux deux niveaux — `end_at(1) is None` **et** `containing(99.0) == [1]` (l'état
non refermé court encore).

Le point d'entrée universel est éprouvé lui aussi : `sources.load(chemin.wdat)` rend un référentiel
interrogeable **sans que l'appelant sache quel lecteur a travaillé** — et un `.wdat` n'est pas pris
pour un `.trip`, les deux étant du SQLite (c'est le reniflage du contenu qui les sépare, pas
l'extension seule).

### 9terdecies.4 Ce qu'il ne fait PAS, et pourquoi c'est délibéré

⏳ **Il ne réinjecte pas les protocoles embarqués dans le magasin.** Rouvrir un conteneur ne doit
pas écrire dans le catalogue **par effet de bord** : c'est un **ingest**, donc une décision
d'utilisateur, et il porte le conflit de **D16** (`ingest()` écrase `body` en silence sur
`kind+key` existant). `probe()` les **compte** et `protocoles()` les **expose** ; personne ne les
ingère à l'insu de quiconque.

`wama_data` : **590 → 603 tests** · lecteurs : **3 → 4**.

---

## 11. MODULES — cartographie détaillée, écran par écran (2026-08-24)

> **Pourquoi cette section, et pourquoi elle n'existait pas.** §7 nomme les modules, §9bis trace le
> plan, §0 mesure l'avancement. Aucun des trois ne dit **ce que l'utilisateur fait à l'écran**, ni
> ne confronte l'écran de l'outil d'origine au code déjà écrit. Fabien a commencé à déposer, module
> par module, schémas de principe et captures dans `claude/WAMA-Data/Modules/<Module>/` — cette
> section est leur confrontation au réel.
>
> ⚠ **On ne reprend pas l'existant, on le critique.** Consigne du 23/08 : « reprendre le concept et
> le fonctionnement pour l'ADAPTER et le PORTER en schéma-driven. **Pas juste transposer le code.** »
> Chaque sous-section dit donc trois choses : ce qui s'aligne déjà, ce qui manque, et ce qu'on
> propose de faire ÉVOLUER.

---

### 11.1 EXPORTER — ce qui s'aligne déjà, exactement

Sources : `Modules/Exporter/Schéma de principe.png` + `Screenshot_Exporter.png`, et les précisions
de Fabien du 2026-08-24.

| écran d'origine | notre code | |
|---|---|---|
| « Concaténation : ☐ Trips ☐ Situation/Events » | `Regroupement(lots, declarations)` | ⭐ **1:1** — `mode_origine` rend littéralement `concat_trip` / `concat_event_situation` / `concat_all` |
| « Vos fichiers » (la file d'export) | `exporter(declarations, …)` — N déclarations | ✅ |
| « Aperçu » | `apercu()` — l'aperçu EST l'export borné | ✅ |
| « Format : tsv ▾ » | registre `FORMATS` (5 déclarés, 3 écrivables) | ✅ |
| « Votre fichier » + ▲▼✕ | `Declaration.colonnes` — tuple ORDONNÉ, l'ordre est une donnée | ✅ |
| « Sous-échantillonnage : 1 » | `Declaration.decimation` | ✅ |
| en-têtes `table.colonne` | `Colonne.titre` → `flux.champ` | ✅ |
| identité de ligne | `Identite`, dont la docstring cite déjà « nom du trip, participant, scénario » | ✅ |

**Le geste, tel que Fabien le décrit** : choisir une FAMILLE (1ʳᵉ colonne) → une ou des TABLES
(2ᵉ colonne) → si **une seule** table, accès aux COLONNES ; si **plusieurs**, elles partent entières
→ « Ajouter ces données » → le contenu s'accumule dans « Votre fichier », réordonnable et
supprimable → on itère → « présent dans » optionnel → le fichier rejoint la file → format,
destination, concaténation → **« Exporter Trip réf »** ou **« Exporter Sélection »**.

### 11.2 EXPORTER — les quatre trous, mesurés

**① L'outil d'adéquation n'existe pas.** `Declaration.__post_init__` vérifie le nom, les colonnes
non vides, la décimation, le format et les en-têtes en double — **rien sur la cohérence**. On peut
donc construire aujourd'hui une déclaration mêlant `event_X.timecode` et `situation_Y.startTimecode` :
exactement le fichier incohérent que l'outil d'origine interdit.

> ⭐ **Mais la règle n'est pas « on ne mélange pas les familles ».** Fabien précise qu'on peut
> mélanger plusieurs tables `data`. Le vrai critère est **la CLÉ TEMPORELLE** — un événement en a
> une, une situation en a deux. Or c'est **exactement la règle écrite le 23/08 pour le Calculator**
> (§9quater.4) : *une nouvelle table SSI la clé temporelle change*. **La même règle gouverne
> l'export.** Ce n'est pas une règle d'export, c'est la règle du monde.
>
> ⚠ Et la famille n'en est qu'un **PROXY** — le même piège que « le nom de table dit la famille »,
> corrigé le même jour dans le `.wdat` (§9duodecies.3).

**② Le filtrage / « présent dans » n'est pas câblé.** Zéro occurrence de filtre ou de condition
dans tout `core/export.py`. Mais `present_dans()` existe (`core/segmentation.py`, exposé au
catalogue sous `segment_present_dans`) et la chaîne conditionnelle complète aussi (14 opérateurs,
arbre ET/OU/XOR/NON, 46 tests). **C'est un câblage, pas un moteur à écrire.**

⚠ **Et il ne sera pas dessiné d'intuition.** C'est ce qui a coûté le revert du premier Exporter :
sur 5 affirmations de §9ter.6 écrites depuis un schéma et une intuition, **2 étaient fausses et 1
sous-estimait d'un facteur 5**, toutes dans le sens optimiste. Avant d'ajouter un champ `filtre` à
`Declaration`, **lire le panneau d'export de `BIND_GUI.mlapp`** : filtre-t-il les LIGNES d'une table,
les OCCURRENCES retenues, ou les deux ? par déclaration ou globalement ?

> ✅ **RÉSOLU le 2026-08-26 — par le témoignage de l'AUTEUR, corroboré par l'écran.** Fabien
> précise : le « filtre » du panneau d'export porte sur les **COLONNES** (choisir ce qui entre dans
> « Votre fichier » — couvert 1:1 par `Declaration.colonnes`, §11.1) ; le filtrage des **LIGNES**
> n'a jamais été une option d'export — il passe par **`present_dans`** (« Sélectionnez vos
> situations » sur l'écran), et une sélection de lignes particulière se **PRÉPARE dans le
> Segmenter** puis s'applique par `present_dans`. Le screenshot le confirme : aucun widget de
> lignes sur le panneau. **Le champ `filtre` envisagé ci-dessus n'a donc pas lieu d'être** — le
> câblage requis est `present_dans` seul.
>
> ⭐ **TRANCHÉ (recommandation du 26/08, VALIDÉE par Fabien le jour même — « d'où l'intérêt du
> Segmenter qui, lui, s'adapte à chaque `.wdat` ») : PAS d'option « sélection de lignes » à
> l'Exporter.** ① Dans le modèle §11.8, un pipeline promu à la card mère doit se
> **REJOUER sur chaque fille** : `present_dans(segment déclaré)` se rejoue ; une liste de lignes
> cochées est une coordonnée **par fichier**, qui ne veut rien dire chez les sœurs — l'option
> créerait des exports non promouvables. ② *On persiste la DÉCLARATION, pas les valeurs* : le
> segment dit **POURQUOI** ces lignes (condition, plage), la liste ne dit que **LESQUELLES** — et
> c'est le pourquoi qu'un relecteur d'article doit lire dans le protocole. ③ Sélectionner des
> lignes **EST** une segmentation : une option d'Exporter serait un second moteur de segmentation,
> le « troisième vocabulaire » que §11.4 interdit. La friction UX se règle **en surface** : un
> raccourci « définir une sélection… » dans l'Exporter ouvre le Segmenter, crée un segment **nommé
> réel**, qui revient présélectionné dans « présent dans » — le geste vit dans l'Exporter, l'objet
> reste un segment (même motif qu'Explorer/Calculator, §11.8 ①).

**③ Les cadences différentes — le point dur, et Fabien le pose à part avec raison.** Deux tables
`data` à 1000 Hz et 10 Hz n'ont pas les mêmes instants ; les mettre en colonnes côte à côte exige de
décider quelle ligne va avec quelle ligne. ⚠ Et **D6/D10 interdisent l'interpolation**. Trois issues
honnêtes :

- **refuser** — un fichier par cadence ;
- **agréger** vers la plus lente — `calcul_par_segment` existe et n'invente aucune valeur ;
- **joindre au plus proche** sans interpoler (`at(how=NEAREST)`) — c'est une *jointure*, elle répète
  ou omet des lignes mais ne fabrique rien.

⚠ Dans les deux derniers cas, **il faut le DIRE dans le livrable** : une colonne à 10 Hz alignée sur
une base à 1000 Hz répète 100 fois la même valeur, et le chercheur croira avoir mesuré à 1000 Hz.
`Rapport.pertes` (§9duodecies.5) est déjà le mécanisme fait pour ça.

**④ « Trip réf » vs « Sélection » n'existe nulle part** dans `wama_data` — voir 11.4.

### 11.3 EXPORTER — trois évolutions proposées, plutôt qu'une reprise

**⭐ Les méta-données ne sont pas une 4ᵉ famille — elles sont l'IDENTITÉ.** Question ouverte de
Fabien (« à voir pour rajouter les meta-data et comment le faire »). Réponse : une méta **ne varie
pas dans le temps**, donc elle n'a **pas de clé temporelle**, donc elle ne peut pas être une table
qu'on concatène. Sa place est **en tête de ligne** — ce que `Identite` fait déjà.
⚠ Exception : Audio/Video portent un *offset*, ce sont des **médias liés**, pas des métas de ligne.

**Le nom du fichier doit rester DÉRIVABLE.** L'écran d'origine offre « Renommer ». Or la doctrine du
monde (§9ter.6 B7, `core/noms.py`) est que **le nom se dérive des paramètres** : un nom saisi
librement rompt le lien entre le fichier lu et le réglage qui l'a produit. Proposition — nom **dérivé
par défaut**, renommage possible mais **tracé comme une surcharge**, jamais un champ libre silencieux.

**L'aperçu doit montrer la PERTE, pas seulement les lignes.** `apercu()` rend l'export borné ; avec
③, il doit aussi dire « cette colonne est répétée 100× » ou « ces deux tables ont été agrégées ».

### 11.4 « Trip réf » vs « Sélection » — un MODE transverse, pas une option d'Exporter

Fabien le dit lui-même : l'utilisateur applique les modules « soit uniquement sur son trip de
référence (exploratoire/test), soit sur la sélection (production sur la pile sélectionnée) ». C'est
donc un **mode du monde Data entier**, pas un bouton de l'Exporter.

⭐ **Et WAMA a déjà ce geste** : c'est **item vs lot** du monde Médias (traiter cette card / traiter
le lot), avec sa doctrine écrite dans `wama/common/app_modes.py`. Le recoder par module créerait un
**troisième vocabulaire** pour une notion qui en a déjà un.

### 11.5 CATALOGER — et pourquoi son nom pose problème

Sources : `Modules/Cataloger/Schéma de principe.png` + `catalogue.png`.

L'arbre de l'écran : **Trips** (Sélection / Liste, avec un `(réf)` qui marque le fichier de
référence) · **Events & Situations** · **Datas** · **Metas** (Attributs, Audio/Video, Participant) ·
**Catalogue**. Trois boutons contextuels en pied : ✏ renommer · ✕ supprimer/désélectionner ·
👁 explorer (= l'Explorer).

Le geste : le **Connector** connecte des fichiers de travail (récursivement — un dossier de
passation, d'expérimentation, voire plusieurs si les datasets sont homogènes) ; le catalogue les
liste, permet de désigner **un fichier de référence** et/ou **une sélection**, et sert aussi à
**chercher / trier / filtrer à travers les données et méta-données**.

⚠ **En amont** : sur un dataset non indexé, un LLM cartographie le dossier et propose le manifeste
`dataset` — sinon l'utilisateur le fournit. C'est exactement « le LLM propose, la machine dispose »
(§9bis) : le manifeste déclare des attentes **vérifiables**, et `dataset.charger()` **mesure l'écart**
(`Ecart`, §9octies).

⚠ Le crayon (renommer) demande une garde explicite, et Fabien la pose lui-même : **on ne renomme pas
une table si elle diffère alors du manifeste `dataset`**. Si tout est passé par les mécanismes, il
n'y a d'ailleurs aucune raison de renommer — sauf pour un essai jetable.

⚠⚠ **Le nom « Cataloger » est déjà pris deux fois** — `wama/common/catalog/` (la glu inter-mondes :
taxonomie de types + registre de fonctions), et le « catalogue de fonctions » que **son propre écran
affiche en bas**. Trois choses porteraient le même mot. → **D19**.

⭐ **Et une hypothèse de structure** : si le schéma se lit bien, **le Cataloger est l'INTERFACE du
Connector** — le Connector connecte, le Cataloger liste, sélectionne et explore. C'est le même motif
que « l'Explorer est l'interface du Calculator » (§9quater, 23/08). Auquel cas ce n'est pas un module
de plus, et le compte de §7 ne bouge pas.

### 11.6 LA HIÉRARCHIE — explicitée par Fabien, et elle range le monde

> **projet → expérimentation → participant → scénario/essai → event/situation**

| niveau | ce que c'est dans WAMA | état |
|---|---|---|
| **projet** | `Manifest.scope_project` / `projects` | ✅ **existe déjà** dans le substrat |
| **expérimentation** | le manifeste **`dataset`** (un corpus de N fichiers) | ✅ kind livré |
| **participant** | méta du fichier de travail (`MetaParticipantDatas` existe dans `.trip`) | 🔶 lu, pas modélisé |
| **scénario / essai** | **UN fichier `.wdat`** | ✅ |
| **event / situation** | tables *dans* le fichier | ✅ |

⭐ **C'est ce qui a tranché D17** : `dataset` et le fichier de travail sont à **deux étages
différents**, donc `.wds` (« WAMA DataSet ») les aurait écrasés. Dans BIND un `.trip` est un trajet
ou un scénario de simulation ; **généralisé, c'est un ESSAI** — et c'est exactement ce que `.wdat`
doit pouvoir désigner sans présupposer de déplacement.

### 11.7 Ce que cette cartographie ne couvre pas encore

⏳ Modules déposés mais non confrontés : **Importer**, **Explorer**. ✅ Le **Segmenter** est
confronté depuis le 2026-08-26 (§11.9 — ses 4 captures, écran par écran, contre le code).

⚠ Et la méthode vaut d'être répétée telle quelle : **rattacher chaque écran au code de `BIND_GUI`
avant de conclure**. La cartographie de §9ter s'est faite depuis des schémas, et c'est là que les
trois affirmations fausses sont nées.

### 11.8 L'UI DU MONDE DATA — le Data Analyzer HÉRITE de la file du monde Médias (2026-08-25)

> Décisions de la discussion du 2026-08-25. Le point de départ de Fabien était « une UI différente,
> sur la base de BIND_GUI » ; la conclusion est l'inverse : **le monde Data adopte la file du monde
> Médias** — un `.wdat` est une **card**, les modules s'appliquent à la card ou au batch, et tout le
> travail déjà payé (densités, pile, volets, inspecteur, tri/filtrage à venir) est **hérité** au
> lieu d'être refait. ⚠ Ces décisions fixent la STRUCTURE ; le détail des écrans reste soumis à la
> méthode de §11.7 (rattacher chaque écran au code de `BIND_GUI` avant de conclure).

**① Le Data Analyzer = l'app-file du monde Data**, à l'image de Describer/Anonymizer/Transcriber.
Les modules de §7 ne sont **ni des apps, ni un onglet chacun** : ce sont des **surfaces ouvertes
depuis les boutons d'action de card** (l'équivalent des actions de card du monde Médias), et la
surface est **DÉCLARÉE par module**, pas codée en dur :

| surface | pour | exemples |
|---|---|---|
| **modale** | modules légers (paramétrer, lancer) | paramètres d'import, export |
| **page dédiée** | modules lourds et interactifs — précédent : la page de correction du Transcriber, déjà doctrine (`capabilities.edit_page`, `MODES_QUEUE_UX §7`) | Explorer, Segmenter en codage vidéo, Visualizer |

⭐ **Réconciliation moteur/UI** — « l'Explorer est l'interface du Calculator » (§9quater) et « les
modules sont des modales/pages depuis la card » (Fabien, 25/08) **ne se contredisent pas** : la
première parle des **MOTEURS** (pas de moteur Explorer séparé), la seconde de l'**UI**. La surface
Explorer ouverte depuis une card reste **motorisée par** le Calculator. Ce que §9quater interdit,
c'est un moteur Explorer distinct, pas un bouton Explorer.

**② La correspondance BIND ↔ WAMA — corrigée par Fabien.** La première version (Liste→file) était
**fausse** : la file WAMA est **CURATÉE**, on n'y verse pas un dossier entier hors batch.

| BIND_GUI (`catalogue.png`) | WAMA |
|---|---|
| **Liste** (dossier chargé) | **l'explorateur** (volet gauche global) — on y CONNECTE un dossier de données |
| **Sélection** | **la file** — chaque envoi crée un **batch** |
| trip **`(réf)`** | pas de card marquée — remplacé par la **promotion fille↔mère** (③) |

Le flux : connecter un dossier → **trier/filtrer** → « envoyer vers » / drag&drop → un batch
(ex. « les `.wdat` du scénario S3 »). ⭐ **Le tri/filtrage de l'explorateur, pour le monde Data,
est un filtrage par AXES (§13)** : les `.wdat` portent leurs coordonnées en méta (`WamaMeta`, D21),
donc « créer le batch du scénario S3 » n'est pas un multi-select manuel, c'est un **group-by sur un
axe du plan d'expérience**. Le rangement déclaré au §13 devient directement le moteur du
tri/filtrage/groupement — rien à inventer, un câblage.

⭐ **Le garde-fou batch est calculable depuis l'existant** : un traitement ne se propose au batch
que si `entrées typées de la FunctionSpec ⊆ ∩ des catalogues de flux des filles` — les deux côtés
existent (le `FUNCTION_CATALOG` type les E/S ; le lecteur `.wdat` expose le catalogue, §9terdecies).
⚠ Ne jamais griser en silence : le refus **dit quelle fille manque de quoi**.

**③ La promotion fille↔mère REMPLACE la « card de référence ».** Proposition de Fabien, meilleure
qu'un marqueur `(réf)` : elle **réutilise** l'héritage existant (les paramètres de la mère
s'appliquent aux filles sauf override individuel) et y ajoute **deux gestes symétriques** —
**↑ promouvoir** les réglages d'une fille vers la mère (qui les applique au batch) et
**↓ réaligner** les filles sur la mère. Conséquences : **n'importe quelle card peut être la
référence**, et on peut régler **plusieurs filles en parallèle** (comparaison A/B) avant de
promouvoir la gagnante. Le mécanisme **bénéficie aux deux mondes** → consigné au domaine file :
**`MODES_QUEUE_UX.md §5ter`**. ⚠ **La charge utile diffère et se DÉCLARE** : monde Médias = le dict
de paramètres ; monde Data = le **protocole** (§9undecies) accumulé sur la card, qui subsume les
paramètres. Le garde-fou de ② s'applique **au moment de la promotion**. Complète §11.4 (item vs
lot) sans le recouvrir : §11.4 dit **sur quoi** on applique ; la promotion dit **comment** le
réglage de la référence devient celui du lot.

**④ Le studio = second éditeur du MÊME protocole.** Deux chemins de construction du pipeline
coexistent (promotion depuis une card ; canvas du studio) — règle : **UNE représentation** (le
manifeste `pipeline` étendu, D13), **DEUX éditeurs**. Sinon deux formats de pipeline divergent.
Cf. `MODES_QUEUE_UX §6` (« la file = une méta-app à une app »).

**⑤ Afficher le contenu d'un `.wdat` — trois niveaux, et l'inspecteur NE CHANGE PAS de rôle.**
L'inspecteur reste infos/pipeline/actions de la card, comme au monde Médias — pas d'arbre de
contenu dedans.

| niveau | surface | contenu |
|---|---|---|
| coup d'œil | **preview dans la card** (équivalent de la miniature média) | mini-tableur + sparklines des flux principaux |
| consultation | **preview développée** (le « clic pour développer » existe déjà) | tables data/events/situations feuilletables |
| travail | **page Explorer dédiée par card** (la surface « page dédiée » de ①) | arbre local (Datas/Events & Situations/Metas, comme BIND) + tableur + graphes + fenêtres du Visualizer |

⚠ **L'arborescence INTRA-fichier ne va PAS dans le volet gauche GLOBAL** (qui reste un explorateur
de FICHIERS). La référence BIND est respectée un cran plus bas : l'arbre de `BIND_GUI` vivait *dans
la fenêtre de l'app* — son équivalent est le volet gauche **de la page Explorer de la card**.

**⑥ Le Visualizer — fenêtres flottantes synchronisées dans la page.** Les plugins graphiques se
lancent **à chaud** et se déplacent/redimensionnent dans le navigateur, comme des fenêtres à
l'intérieur de la page (layout persisté par utilisateur). Le **magnéto (§5) est le BUS de
synchronisation** : chaque fenêtre s'abonne au temps courant. ⚠ Le point de conception à fixer EN
PREMIER n'est pas le fenêtrage, c'est le **contrat de synchronisation** (quel événement, quelle
granularité temporelle, qui est maître) — c'est lui qui décide si un plugin s'écrit en 50 lignes ou
en 500. Le bornage des plugins reste celui de §4 (déjà figé).

**⑦ Évolutions du volet gauche global** (substrat, pas monde Data) : regrouper les apps Médias sous
une catégorie `media` à côté de `lab` / `data` quand leurs UI existeront, et **changer d'app en
cliquant son dossier** dans l'explorateur. → consignées au domaine : **`WAMA_VOLETS.md §8`**.

**⑧ Le bundle corpus `.wds`** s'exporte **depuis la card mère du batch** et se réimporte **en
batch** — voir **D26** (§10).

### 11.9 SEGMENTER — les 4 écrans confrontés au code (2026-08-26)

Sources : `Modules/Segmenter/` (Schéma de principe, Codage_vidéo, Segmentation_temporelle,
Segmentation conditionnelle, Filtrage_segmentation) — confrontés fonction par fonction, à la
demande de Fabien (« être sûr qu'on est aligné »). Le schéma de principe : trois chaînes (codage
vidéo / temporelle Simple‑Double / conditionnelle), sous-segmentation « présent dans » optionnelle,
filtrage manuel events/situations optionnel en bout de toutes les chaînes.

| écran d'origine | notre code | |
|---|---|---|
| Temporelle **Simple** — Event + marges inf/sup (s) | `autour()` → `segment_autour_event` — 2 offsets **indépendants** | ✅ |
| Temporelle **Double** — 2 tables, occurrence de départ, offsets, « Répéter » | `jonction()` — `depuis_debut`/`depuis_fin` (= les curseurs `tddAvant`/`tddApres` d'origine), `offset_debut`/`offset_fin`, `repeter`, segments **ouverts** au lieu de jetés | ✅ ⭐ et l'appariement est **TEMPOREL**, pas par index : le cas d'échec de l'original (« Veuillez filtrer les tables ») **n'existe plus** |
| Sous-segmentation « Présent dans » | `present_dans()` (strict) → `segment_present_dans`, + `chevauche()` | ✅ |
| **Conditionnelle** — conditions, saisie `ET(C1, C2)`, `NON/OU/XOR`, texte « contient » | `segment_chaine_conditionnelle` — 14 opérateurs typés par SORTE (refus AVANT exécution), et la saisie préfixe de l'écran est littéralement `analyser()` | ✅ |
| « fusion des trous / rejet des courtes » + hystérésis | `duree_min`, `trou_tolere`, `masque_hysteresis` | ✅ |
| « **Que créer ?** Event / Situation » | `segment_` / `event_chaine_conditionnelle` — un choix de **SORTIE**, deux fonctions chaînables | ✅ |
| **Codage vidéo** — Créer/Charger/Éditer protocole, Lancer | `Protocole`, `SessionCodage`, `rejouer()`, `accord()` + `codage_segments`/`codage_evenements`/`codage_accord` | ✅ (l'interface se GÉNÈRE du protocole — délibérément non écrite, dépend du Visualizer) |
| **Spatiale** (question de Fabien 26/08 : « ajoutée mais câblée ? ») | ✅ **câblée PAR CONSTRUCTION, pas comme un mode** (§9septies) : `distance_a_point` → colonne dérivée → chaîne conditionnelle. **Prouvé par test** : `test_spatial_ET_temporel_dans_la_MEME_chaine` mêle `distance ≤ 40 ET vitesse > 30`. + `ign_buildings`/`ign_roads`/`road_branches`/`sky_mask` au catalogue | ✅ |

**Les QUATRE trous mesurés :**

~~**① Marges sur une SITUATION**~~ — ✅ **SOLDÉ le 2026-08-26, ÉLARGI AU SPATIAL à la demande de
Fabien** (« il faut aussi gérer les ajustements de bornes temporelles/**spatiales** »). Deux
fonctions au catalogue : **`segment_marges`** (`start − avant`, `end + apres` ; négatif = rétrécir,
segment inversé **écarté** — même geste que `duree_min` —, fin ouverte inchangée, origine d'avant
la marge gardée dans `source`) et **`segment_marges_spatiales`** (marges en **MÈTRES PARCOURUS**,
converties en bornes par l'**abscisse curviligne** — `core/geo.py::abscisse_curviligne`, nouvelle
primitive : cumul monotone, trou GPS → `None` reporté, jamais inventé). ⭐ Même généralisation que
§9septies : la marge spatiale n'est pas un mode, c'est une marge sur une **COLONNE** monotone au
lieu de `time`. Les bornes rendues sont des **échantillons existants** (comme `at()`) : marge
rendue ≥ marge demandée, bornée là où la donnée s'arrête.

~~**② Le `FunctionSpec` de `segment_jonction` n'expose que `nom` + `fermer_dernier`**~~ — ✅
**SOLDÉ le 2026-08-26** : les 5 `ParamSpec` déclarés (`offset_debut`/`offset_fin`,
`depuis_debut`/`depuis_fin`, `repeter`), traversée testée, et un test qui garde la **DÉCLARATION**
elle-même (`functions/temporal/tests_segmentation.py` — *une capacité non déclarée est une
capacité invisible de l'UI générée*). `wama_data` : **645 tests** au vert.

**③ Conditionnelle sur table d'ÉVÉNEMENTS (la bascule [Data|Event] de l'écran).** `_ENTREE` est
`TIMESERIES` seulement ; « les occurrences de `commentaires_simu` dont `var_commentaires` contient
FIN » — filtrer des occurrences par prédicat — n'a pas de fonction. Une `event_filtre_conditionnel`
(EVENTS/SEGMENTS en entrée, **même** chaîne de conditions) comblerait le trou — ⭐ et couvrirait du
même coup l'essentiel du filtrage manuel **de façon déclarative**.

> ⭐ **Étendu aux SITUATIONS (question de Fabien, 26/08 : « durée > 1 min ? vitesse moyenne >
> 30 km/h ? ») — oui, et par COMPOSITION, pas par concept neuf.** La même fonction de filtre
> accepte EVENTS **et** SEGMENTS et teste leurs **colonnes**. « Durée > 1 min » : la durée se
> dérive (`end − start` ; un segment **ouvert** n'a pas de durée — à écarter explicitement, jamais
> en silence). « Vitesse moyenne > 30 » : l'indicateur par segment est **déjà le Calculator**
> (`calcul_par_segment` adjoint `moyenne_vitesse` à la table de segments), puis le même filtre
> s'applique. Deux fonctions chaînées — exactement le motif « un choix de sortie, pas un mode »
> déjà acté pour `segment_`/`event_chaine_conditionnelle`.

**④ Le filtrage MANUEL par occurrence (les cases « Ignore » de `Filtrage_segmentation.png`).**
Rien de dédié (`etats(ignorer=…)` ignore des **valeurs** d'un catégoriel, pas des occurrences ;
`depuis_*` ne saute que les N premières). ⭐ **Mais la moitié de sa raison d'être a DISPARU** :
l'outil d'origine appariait par index et **renvoyait l'utilisateur au filtrage manuel** dès que les
comptes différaient — l'appariement temporel de `jonction()` n'a pas ce cas d'échec. Le résiduel
légitime (écarter de fausses détections) est une **CURATION** : un geste **par fichier**, tracé
comme les gestes de codage, **non promouvable au batch** — cohérent avec « on persiste la
déclaration, pas les valeurs » et avec la décision export (§11.2 ② : le déclaratif se promeut, le
manuel reste local). À déclarer comme geste, pas comme fonction du catalogue.

(Mineur, à vérifier au câblage : la restriction « Situation : … » appliquée à la **sortie
événements** de la conditionnelle — `present_dans` opère sur des segments ; pour des events, soit
restreindre le signal d'entrée, soit un petit `events_present_dans`.)

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

## 12. APPRENTISSAGE, STATISTIQUES, SIMULATION — renvoi (2026-08-25)

Le monde Data n'intègre pour l'instant que des méthodes de **traitement**. Trois extensions sont
cadrées ailleurs, et **aucune n'est un chantier ouvert** :

- **modèles APPRIS** (motifs, situations, **profils conducteurs**) — le ML/DL n'est PAS demandé pour
  la détection des **traces**, qui reste déterministe (Calculator + `functions/driving/`) ;
- **couche statistique** — extension par `FunctionSpec`, sans blocage ; le coût est le garde-fou
  méthodologique (vision §28), pas le développement ;
- **boucle de simulation Unreal** — rejouer un profil à la place d'un conducteur pour évaluer le
  réalisme, puis générer des données.

> 📄 **Document de référence : [`WAMA_APPRENTISSAGE.md`](WAMA_APPRENTISSAGE.md)**

**Ce qui touche CE document et doit être traité avec lui** — son §3 : cinq déclarations gratuites
aujourd'hui et non rattrapables ensuite, dont trois portent sur des kinds que le monde Data
manipule déjà : `dataset` gagne l'**unité d'indépendance** (participant/session/véhicule) et la
provenance **réel/synthétique** ; le référentiel temporel gagne un **axe d'agrégation**
`fenêtre → participant → groupe`, car un profil n'est **pas** un objet temporel.

⚠ Deux garde-fous déjà écrits s'y appliquent : **pas de nouveau kind** (`§9quinquies.3` a tranché —
un entraînement est un `pipeline` produisant un `model`), et le **4ᵉ mode du Segmenter** (« appris »)
s'ajoute sans nouveau concept, puisqu'il produit les mêmes plages `(start, end)` étiquetées.

---

## 13. LE PLAN D'EXPÉRIENCE — axes déclarés, arborescence variable, taxonomie universelle (2026-08-25)

> Fait apporté par Fabien et **absent de tout ce document jusqu'ici** : la **comparaison par groupes
> de population** est une pratique **quasi systématique** au laboratoire, au même titre que la
> comparaison par scénarios pour un même participant. Ex. : comparer jeunes / âgés, avec des
> **catégories d'âge définies par les chercheurs** et **contrebalancement des scénarios** pour
> limiter les effets d'apprentissage. *« La laisser de côté aurait été une grave erreur de
> conception. »*

### 13.0 VOCABULAIRE — trois mots qu'il faut fixer avant d'aller plus loin

Écrit parce que la première rédaction les employait sans les définir, et que la question s'est posée
mot pour mot : *« qu'appelles-tu les axes ? qu'appelles-tu dataset — le manifeste ou le `.wdat` ? »*

| mot | ce que ça désigne ICI | ce que ça ne désigne PAS |
|---|---|---|
| **axe** | une **dimension du plan d'expérience** : participant, groupe, scénario, âge — ce qu'on appelle aussi regroupement ou catégorie | pas un axe temporel, pas un axe de graphe |
| **dataset** | le **manifeste** de kind `dataset` — la déclaration | ❌ **jamais** le fichier `.wdat` |
| **`.wdat`** | le **conteneur** de données, un essai / une passation | pas une déclaration |

**Et une réponse mesurée à la question « n'y a-t-il qu'un seul dataset pour une expérimentation
dans son ensemble ? » : oui.** Le kind le dit lui-même — `source.ref` = *« chemin/dossier/URI du jeu
brut »*, et *« un dataset est un **ACCÈS** (source.ref = arborescence serveur), pas un objet à
instancier »*. **Un manifeste `dataset` = une expérimentation = un arbre.** Les `.wdat` sont ses
feuilles.

> ⭐ **D'où le partage, en une phrase (formulation de Fabien, meilleure que ma première rédaction) :**
> **le manifeste `dataset` DÉCLARE les axes et leurs valeurs possibles ; le `.wdat` porte SON
> RANGEMENT en méta-info.** La déclaration est unique et vaut pour l'expérimentation ; les
> coordonnées sont par fichier.

### 13.1 ⚠⚠ L'ARBORESCENCE N'EST PAS LA TAXONOMIE — c'est un ENCODAGE de la taxonomie

L'arborescence varie d'une expérimentation à l'autre, et d'un laboratoire à l'autre :

```
Projets → Expérimentations → Groupes → Participants → Scénarios → Datasets   (le plus fréquent ici)
Projets → Expérimentations → Participants → Datasets                        (ni groupe ni scénario)
```
…plus des cas étrangers au domaine : **essais mécaniques** (série d'essais, éprouvette, machine),
**flux de trafic** (site, période, capteur). Et parfois, à côté des datasets, des dossiers `Data` /
`Raw data` qui contiennent malgré tout le fichier de travail `.trip`/`.wdat`.

> **Si WAMA modélise l'ARBRE, il hérite des habitudes de rangement de chaque laboratoire.**
> S'il modélise le **PLAN D'EXPÉRIENCE**, l'arbre n'est plus qu'un des moyens de le peupler.

C'est exactement le reproche que Fabien fait à la toolbox tierce : *« elle avait des préjugés et des
prérequis liés au monde de l'automobile, des expérimentations et des usages d'un laboratoire ; même
si c'était potentiellement dérivable, la taxonomie était trop spécialisée. »* **WAMA se veut
universel, testé ici — pas conçu ici.**

### 13.2 Trois choses distinctes, que le dossier confond

| | quoi | pourquoi ça compte |
|---|---|---|
| ① | **structure du plan** — ce qui est **niché** dans quoi, ce qui est **croisé** avec quoi | détermine ce qui est indépendant, ce qui est en mesures répétées |
| ② | **rôle** d'un niveau — manipulé, regroupant, mesuré | détermine **quel test** est licite |
| ③ | **arborescence de fichiers** | une **sérialisation** de ① et ②, mutable et accidentelle |

### 13.3 LE MODÈLE — `axes[]` : vocabulaire de RÔLES fermé, clés et libellés OUVERTS

**TROIS rôles**, et chacun énonce un **fait structurel sur le corpus** — jamais un choix d'analyse.

| rôle | ce que c'est (fait structurel) | exemples, tous domaines |
|---|---|---|
| `observation` | l'**unité d'observation** — le grain du corpus | participant · éprouvette · site de comptage |
| `factor` | ce qui **IDENTIFIE** une observation — sa suppression rend deux observations indiscernables | groupe d'âge · scénario · journée de passation · véhicule · expérimentateur · série d'essais |
| `attribute` | ce qui **QUALIFIE** une observation **sans l'identifier** | âge en années · kilométrage annuel · sexe simplement relevé · lot matière |

> ⚠ **Définition corrigée le 2026-08-25 (objection de Fabien).** La première rédaction disait
> *« une valeur **mesurée sur** une unité »* — mauvaise sur deux points, et il en a vu un :
> ① *« mesurée »* exclut à tort les attributs **discrets et non mesurés** (sexe, main dominante,
> catégorie de permis) ; ② *« unité »* rejouait la collision qu'on venait d'écarter.
> Le bon critère ne parle **ni de mesure, ni d'unité, ni de continu vs discret** — il parle
> d'**identification**, et il vient de SDMX (§13.3ter).

Attributs portés, en plus du rôle :

| attribut | sur | ce qu'il dit |
|---|---|---|
| `contains` / `crosses` | `factor` | **niché** ou **croisé** avec l'unité d'observation |
| `manipulated: true\|false` | `factor` | le protocole a-t-il **assigné** ce niveau, ou seulement **constaté** ? |
| `counterbalanced: true` | `factor` | l'ordre a été contrebalancé (effets d'apprentissage contrôlés) |
| `derived_from` | `factor` | ce facteur est un **découpage d'un attribut** — `groupe_age` ← `age` |

> ⭐ **`derived_from` décrit exactement la pratique du laboratoire** : « des catégories d'âge
> **définies par les chercheurs** ». L'attribut est le fait brut, le facteur est la partition que le
> chercheur en tire. Les deux coexistent, et le lien est déclaré au lieu d'être perdu.

#### ⚠⚠ Ce qui a été RETIRÉ, et pourquoi — `block` et `covariate`

La première rédaction (2026-08-25, matin) proposait quatre rôles dont `block` et `covariate`.
**Retirés le jour même après confrontation aux sources statistiques**, à la demande de Fabien
(*« je ne comprends pas le terme… vérifie ce que tu trouves »* — il avait raison sur les deux).

| terme | ce qu'il désigne réellement | pourquoi il ne peut pas être un rôle déclaré |
|---|---|---|
| **`block`** | un facteur de **NUISANCE** : « pas d'intérêt pour la question de recherche », dont on absorbe la variance pour dégager le signal | « sans intérêt » est un **jugement d'analyse**, pas un fait de corpus. Le groupe d'âge est un bloc dans une étude et **la question de recherche** dans la suivante |
| **`covariate`** | un prédicteur (généralement continu) **inclus pour contrôler** son effet | même défaut : c'est un **rôle dans un modèle donné**. Les sources le disent — la distinction facteur/covariable « reflète le rôle de la variable dans le modèle autant que son échelle de mesure », et une covariable **peut** être catégorielle |

> **La règle qui en découle, et qui vaut au-delà de ce fil :**
> **le manifeste déclare ce que le CORPUS est, jamais ce qu'une ANALYSE en fera.**
> Figer `block`/`covariate` dans la déclaration reviendrait à graver un choix d'analyse dans la
> description du corpus — et à le rendre faux dès la deuxième question de recherche.

Rien n'est perdu : `block` et `covariate` restent des **rôles d'analyse**, choisis au moment de
l'analyse, à partir des faits déclarés ici.

> ⚠⚠ **`unit` était le nom naturel — il est INTERDIT, et le mot est pris DEUX FOIS, pas une.**
> Vérifié le 2026-08-25 sur la question de Fabien.
>
> | sens déjà en service | où | portée |
> |---|---|---|
> | **OrgUnit** — unité d'organisation, niveau de partage | `manifests/envelope.py:21` : `VISIBILITIES = ('private','project','unit','public')` + `scope_org_unit` | la **même enveloppe** que le `body` où vivraient les axes |
> | ⭐ **unité de MESURE** (m/s, bpm, °) | `MetaDataVariables.unit` (`.trip`, §6.2) et **`WamaVariables.unit`** (`.wdat`, §9duodecies.3) | la **même couche de données** que les axes, à quelques tables d'écart |
>
> Le second est le plus dangereux des deux : il vit exactement là où les axes vont vivre, et §6.2
> le souligne déjà comme un acquis (*« `unit` est déclarée par variable »*). Un `role: unit` aurait
> mis trois sens du même mot dans un rayon de deux tables.
>
> Retenu : **`observation`**, **0 occurrence** dans le dépôt (mesuré). `factor` et `attribute` :
> **0 collision** également.
>
> #### Faut-il spécialiser les DEUX autres ? (proposition de Fabien : `org_unit` / `mes_unit`)
>
> **Non — et c'est mesuré, pas une préférence.** Le mot n'était ambigu que **dans le nom qu'on
> s'apprêtait à ajouter** ; les deux usages en place sont chacun désambiguïsés par leur contexte.
>
> | usage | renommer ? | pourquoi |
> |---|---|---|
> | `visibility: 'unit'` → `org_unit` | ❌ **non** | c'est une **valeur stockée en base** (`Manifest.visibility` + `ScopedVisibility.VIS_UNIT` sur les modèles d'app) : migration de données + ~15 sites d'appel, pour un mot **déjà désambiguïsé par son champ** (`visibility`) et son compagnon (`scope_org_unit`) |
> | `unit` (unité de mesure) → `mes_unit` | ❌ **non, et surtout pas** | c'est la **convention universelle** (netCDF/CF, UCUM, pint, HDF5) **et** le nom de colonne réel de `.trip` (`MetaDataVariables.unit`) : le renommer casserait la lecture du format qu'on importe, pour un mot qui, dans une table `variables`, ne peut rien signifier d'autre |
>
> ⇒ **Zéro renommage.** Une fois le nouveau rôle nommé `observation`, les trois sens cessent de se
> croiser : `visibility: unit` (enveloppe), `role: observation` (axes), `unit: m/s` (variables).

Et la relation, **qui est le morceau qui manque partout** :

- `contains:` → **nidification** (un groupe *contient* des participants) ;
- `crosses:` → **croisement** (un scénario est *croisé* avec le participant — chacun les fait tous).

```yaml
axes:
  - key: participant   role: observation
  - key: groupe_age    role: factor      contains: participant   manipulated: false
                       levels: ref:groupes_age   derived_from: age
  - key: scenario      role: factor      crosses:  participant   manipulated: true
                       counterbalanced: true
  - key: age           role: attribute   attached_to: participant   unit: year
```

**Les deux `factor` ne diffèrent que par deux attributs déclarés** — et ces deux attributs sont
exactement ce qui change les conclusions : `contains` vs `crosses` donne inter- ou intra-sujets ;
`manipulated` donne le droit (ou non) de parler d'effet plutôt que d'association.

> ⭐ **C'est `contains` vs `crosses` qui distingue les deux pratiques du laboratoire** — comparer des
> groupes, et comparer des scénarios chez un même participant. À profondeur de dossier identique,
> ce ne sont **pas le même test**. Porter la relation, c'est permettre à la couche statistique
> (`WAMA_APPRENTISSAGE.md §5`) de **proposer le test juste** au lieu de le demander : le principe
> métadonnée-driven appliqué à la statistique.

**L'universalité vient de là** : le vocabulaire de **rôles** est fermé (4 valeurs), les **clés et
libellés** sont ouverts. « Participant / groupe / scénario » sont des **libellés**, pas des rôles.

| domaine | `observation` | `factor` (niché) | `factor` (croisé) | `attribute` |
|---|---|---|---|---|
| conduite | participant | groupe d'âge, journée de passation | scénario, condition de trafic | âge, kilométrage annuel |
| essais mécaniques | éprouvette | **série** d'essais, machine | température, vitesse de charge | lot matière, épaisseur |
| flux de trafic | site de comptage | axe routier | période, météo | trafic moyen journalier |

Rien à redéfinir par domaine : on **déclare des axes**, on ne choisit pas dans une liste fermée de
niveaux métier.

### 13.3bis CONFRONTATION AUX TERMES STATISTIQUES — sourcée, et elle m'a donné tort (2026-08-25)

> Demandée par Fabien parce que la taxonomie doit tenir pour la future couche statistique :
> *« autant qu'on trouve la bonne taxonomie pour ne pas risquer des confusions plus tard »*.
> Quatre points vérifiés, dont **trois corrigent ce que j'avais écrit le matin même**.

**① Un scénario EST un facteur — et un groupe d'âge aussi.** J'avais opposé « `block` = groupe
d'âge » à « `factor` = scénario ». C'est faux. En plan d'expérience, **tout prédicteur catégoriel
est un facteur** : « les manipulations expérimentales *et* les prédicteurs catégoriels
observationnels (sexe, moment, statut) comptent tous deux comme des facteurs ». Le doute de Fabien
(*« un scénario n'est pas un facteur »*) venait du sens courant de « facteur explicatif », qui est
un **troisième** usage du mot — et une source note que `factor` est de toute façon ambigu, puisqu'il
désigne « quelque chose d'entièrement différent en analyse factorielle, où il est continu ».

**② Ce qui sépare les deux n'est PAS le mot, c'est un attribut — et il gouverne les conclusions.**
Toujours d'après la même source : *« qu'un facteur soit observationnel ou manipulé n'affecte pas
l'analyse, mais affecte les conclusions qu'on peut en tirer »*. ⭐ **C'est la justification exacte
de `manipulated: true|false`** : la propriété est trop décisive pour rester implicite dans un nom
de rôle, où personne ne la déclarerait.

**③ `contains` / `crosses` encode DÉJÀ inter- vs intra-sujets — confirmé mot pour mot.**
*« Dans un facteur inter-sujets, les sujets sont **nichés dans** les niveaux du facteur ; dans un
facteur intra-sujets (mesures répétées), les sujets sont **croisés avec** le facteur. »* Deux rôles
séparés `block`/`factor` pour porter cette information étaient donc **redondants** avec la relation.
Et le critère formel de croisement est vérifiable mécaniquement — « au moins une observation dans
chaque combinaison » — ce qui rejoint la réfutation arithmétique du §13.6.

**④ `block` est un facteur de NUISANCE, pas un regroupement d'intérêt.** *« Un facteur de nuisance
a probablement un effet sur la réponse, mais n'est pas un facteur qui vous intéresse. »* Le tableau
canonique oppose « intérêt : question de recherche principale » à « nuisance : sans intérêt ».
⇒ Appeler `block` le groupe d'âge — qui **est** la question de recherche au laboratoire — était un
contresens. Et « sans intérêt » n'étant pas un fait de corpus, `block` ne peut pas être un rôle
déclaré (voir §13.3).

**⑤ `covariate` est un rôle de modèle, pas une nature.** La convention dominante (facteur =
catégoriel, covariable = continu) est *« une convention, pas une règle stricte »* : une covariable
**peut** être catégorielle, et la distinction *« reflète le rôle de la variable dans le modèle
autant que son échelle de mesure »*. Fabien l'avait dit autrement — *« covariate est un facteur à
mon sens, l'âge peut expliquer les difficultés »* — et c'est le même constat.

> **Bilan de la confrontation.** La taxonomie retenue ne renomme pas le vocabulaire statistique :
> elle le **coupe au bon endroit**. Ce qui est stable (le grain, ce qui indexe, ce qui décrit, ce
> qui a été assigné, ce qui est niché ou croisé) est **déclaré dans le corpus** ; ce qui dépend de
> la question posée (intérêt vs nuisance, facteur vs covariable) reste **au moment de l'analyse**.

**Sources** (consultées le 2026-08-25) — Penn State STAT 502/503 (blocs et facteurs de nuisance) ·
NC3RS Experimental Design Assistant (variables indépendantes) · The Analysis Factor, K. Grace-Martin
(croisé vs niché ; « Confusing Statistical Terms : Covariate ») · Laerd Statistics et Wikipédia
(ANCOVA, covariable catégorielle) · « Teaching Design of Experiments using Hasse diagrams »
(arXiv:1912.08567, structure d'unités vs structure de traitements).

### 13.3ter CONFRONTATION AUX STANDARDS DE MÉTADONNÉES — cinq, et ils convergent (2026-08-25)

> Demandée par Fabien : *« j'avais regardé s'il n'existait pas déjà des taxonomies existantes pour
> ne pas réinventer »*, et *« vois si BORIS ne gère pas aussi cette taxonomie catégorielle »*.
> Résultat : **le modèle n'est pas inventé — il est réinventé, et mal nommé jusqu'ici**.

#### ⚠ D'ABORD, SÉPARER DEUX COUCHES QU'ON CONFOND (le filtre demandé)

Une discussion antérieure (EDAM, bio.tools, Galaxy, ToolShed/ToolDog, AgentCard A2A, registre MCP,
échec d'OWL-S/UDDI) portait sur une **autre question** que celle-ci. Les deux comptent pour WAMA,
mais elles ne se répondent pas :

| couche | la question | prior art pertinent | où dans WAMA |
|---|---|---|---|
| **CAPACITÉS** | « que sait faire cet outil, sur quoi, sous quel encodage » | **EDAM** (4 axes orthogonaux `operation`/`data`/`format`/`topic`), bio.tools, Galaxy tool XML, AgentCard, registre MCP · et l'**échec d'OWL-S** comme avertissement | `FunctionSpec`, `data_types.py`, kinds `function`/`app`/`model` |
| **PLAN D'EXPÉRIENCE** | « comment CE corpus est organisé » | **SDMX · DDI · BIDS · Psych-DS · BORIS** | kind `dataset` + `axes[]` (ce §13) |

⇒ **Le conseil « les 4 axes d'EDAM corrigent ton dict `capabilities` libre » vise la PREMIÈRE
couche**, pas celle-ci. Il reste juste — et à traiter dans `WAMA_APP_GENERATION_ROUTE.md` /
`WAMA_MANIFEST_SPEC.md`, pas ici. **Aucune** des sources de cette discussion ne traite le plan
d'expérience, sauf BIDS au passage. Appliquer EDAM aux axes serait une erreur de couche.

#### ⭐⭐ SDMX (ISO 17369) donne LE critère — et il ne parle ni de mesure ni d'unité

La *Data Structure Definition* de SDMX — le standard d'échange statistique des instituts nationaux —
n'a que **trois constructions**, et leur définition est exactement la nôtre :

| SDMX | définition officielle | notre rôle |
|---|---|---|
| **Dimension** | *composante **identifiante*** — « les dimensions forment ensemble la **clé primaire** » d'une observation | **`factor`** (dont `observation` = la plus fine) |
| **Measure** | le phénomène observé, la valeur | ⭐ **`signals[]`** — déjà présent dans le kind `dataset` |
| **Attribute** | *« n'aide pas à identifier les observations, mais y **ajoute une information utile** »*, rattaché à un **niveau déclaré** (dataset / groupe / série / observation) | **`attribute`** |

> **LE TEST, mécanique** : *retire la composante — deux observations deviennent-elles
> indiscernables ?* **Oui → `factor`. Non → `attribute`.**
> Rien sur « mesuré », rien sur l'unité, rien sur continu vs discret. Le `sexe` peut être l'un ou
> l'autre, et c'est le protocole qui tranche : recrutement par quotas et comparaison → il identifie
> ; simplement relevé → il qualifie.

⭐ **Conséquence forte : le kind `dataset` portait DÉJÀ deux des quatre constructions SDMX** —
`signals[]` (measures) et `reference_tables` (codelists). Il ne lui manquait que les dimensions et
les attributs. Le modèle n'est donc pas plaqué : il **complète** une structure déjà à moitié là.

⚠ **Limite honnête de l'alignement** : l'exemple canonique d'attribut en SDMX est… **l'unité de
mesure**. Leur `attribute` est donc plus large que le nôtre (il qualifie aussi une *variable*, pas
seulement une *observation*). Alignement fort, pas identité — ne pas le sur-vendre.

#### ⭐ BORIS confirme le lieu, et ajoute un SECOND critère (temporel)

BORIS — l'outil de codage vidéo comportemental de la communauté — a exactement ce mécanisme, sous le
nom d'**Independent variables** : *« ajouter de l'information sur l'observation […] des facteurs
susceptibles d'influencer les comportements (composition du groupe, température, conditions météo)
**qui ne changeront pas pendant une observation donnée** »*. Chaque variable porte un `Label`, une
`Description` et un **`Type` ∈ {text, numeric, value from set, timestamp}**, avec un « Set of
values » pour le dernier. Les valeurs sont **demandées à la création de l'observation**.

Deux enseignements :

1. ⭐ **« ne change pas pendant une observation » est le second critère, et il est temporel** — c'est
   la ligne exacte entre une **coordonnée d'axe** (méta du `.wdat`) et un **signal** (une table de
   flux). On avait le critère d'identification ; voilà celui de constance.
2. **`value from set` vs `text`/`numeric` EST notre distinction `factor`/`attribute`**, implémentée,
   dans l'outil que la communauté du codage vidéo utilise. Un ensemble de valeurs **fermé et
   déclaré** fait l'axe ; une valeur libre fait l'attribut.

⚠ **Ce que BORIS n'a pas** : ni nidification, ni croisement, ni `manipulated`. Sa liste est **plate**
— même forme de trou que `TripSet` (§13.5bis), qui agrégeait sans déclarer. C'est précisément le
delta que WAMA apporte, et il est maintenant attesté sur **deux** outils indépendants du domaine.

#### BIDS / Psych-DS — la forme de fichier, et le mot `Levels`

BIDS pose `participants.tsv` (**une ligne par sujet** ; colonnes `age`, `sex`, `handedness`,
`group`…) accompagné d'un **sidecar `participants.json`** qui décrit chaque colonne via `Description`
et ⭐ **`Levels`** — l'énumération des valeurs catégorielles. Les unités y sont déclarées à part
(`age` en années, ou en semaines si on le dit). **Psych-DS** généralise BIDS au tabulaire
comportemental (schéma LinkML, dictionnaires de données avec définitions catégorielles).

⇒ **`Levels` est le mot consacré pour ce que nous appelons les valeurs possibles d'un facteur** — et
chez nous il a déjà un domicile : `reference_tables`. Alignement lexical à faire, mécanisme déjà là.

#### DDI — le standard SHS qu'EDAM ne couvre pas

Constat de Fabien : EDAM n'a rien pour les SHS. Exact — et le standard qui manquait s'appelle **DDI**
(Data Documentation Initiative, alliance issue de l'ICPSR), *« largement utilisé pour décrire les
données des sciences sociales, comportementales et économiques »*. Il porte nommément :

- ⭐ l'**unité d'analyse** — *« les unités d'analyse peuvent être des personnes, des ménages, des
  familles, des établissements, des transactions, des pays »* : c'est notre `observation`, avec le
  même besoin d'universalité inter-domaines ;
- **`universe`** / `population` — ce que le corpus est censé couvrir. **Nous n'avons pas d'équivalent**
  (⇒ D25) ;
- ⭐ le principe de **réutilisation** : *« catégories de réponse, concepts et univers définis une fois
  puis utilisés plusieurs fois »*, les séries de vagues héritant des variables communes. C'est la
  réponse à la question « redéclare-t-on le plan à chaque expérimentation ? » : **non, on référence**.

#### Bilan — ce qu'on garde, ce qu'on aligne, ce qu'on n'importe pas

1. **On n'importe aucune ontologie.** Le dimensionnement l'interdit : ces standards portent des
   milliers de concepts pour des dizaines de milliers d'entrées ; nous avons une expérimentation à
   décrire. Le mode d'échec documenté d'OWL-S est **le vocabulaire trop large que personne
   n'annote** — pas la couverture insuffisante.
2. **On aligne, on ne forke pas** — c'est le patron d'EDAM-Bioimaging : espace de noms propre,
   correspondances déclarées (`exactMatch` / `broadMatch`) là où le terme existe. Alignements
   immédiats : `factor` ↔ SDMX *dimension* · `attribute` ↔ SDMX *attribute* · `signals` ↔ SDMX
   *measure* · `reference_tables` ↔ BIDS `Levels` / SDMX *codelist* · `observation` ↔ DDI *unité
   d'analyse*.
3. **On garde nos deux ajouts, qu'aucun des cinq ne porte** : les relations `contains`/`crosses` et
   la propriété `manipulated`. C'est là qu'est la valeur, et elle est mesurée : BORIS et TripSet
   déclarent des valeurs sans relations, SDMX déclare des clés sans plan d'expérience.

**Sources** (consultées le 2026-08-25) — SDMX Information Model 2.1 §2 et FMR Knowledge Base
(Data Structure Definition) · BORIS user guide v9.12 (Independent variables, Ethogram, Subjects) et
Friard & Gamba 2016, *Methods in Ecology and Evolution* · BIDS Specification (modality-agnostic
files, `participants.tsv`/`.json`, `Levels`) · Psych-DS (psychds-docs, schéma LinkML) ·
DDI Alliance (product overview) et IHSN (DDI metadata standard) · EDAM (edamontology.org) et
EDAM-Bioimaging pour le patron d'extension.

### 13.4 ⭐ ALIGNEMENT MESURÉ avec le kind `dataset` — verdict : **aligné, rien à revoir, deux ajouts**

Mesuré le 2026-08-25 dans `wama/common/manifests/builtin/dataset.py` — le kind déclare aujourd'hui :
`source {type, ref}`, `signals[]` typés sur `data_types`, `reference_tables{}`, `records[]`.

| constat | conséquence |
|---|---|
| **rien** ne décrit la position du jeu dans un plan d'expérience | c'est **le** trou — mais un trou d'**ajout**, pas de refonte |
| la docstring dit déjà « `source.ref` = **arborescence serveur** » et « un dataset est un **ACCÈS**, pas un objet à instancier » | ⭐ **un dataset est DÉJÀ un ARBRE, pas un fichier.** Il lui manque seulement de dire **comment** cet arbre est organisé |
| `reference_tables{values\|mapping}` existe déjà (enums) | ⭐ c'est **déjà le domicile des NIVEAUX** d'un axe (`groupes_age: {values: [jeunes, âgés]}`) — rien à créer |
| la couche au-dessus est déjà prévue : *« propriété/projet/visibilité → portée par l'ENVELOPPE commune (world/visibility/scope) »* + kind `project` | le niveau **Projet** a son kind ; les niveaux intermédiaires n'en veulent pas |

> **Donc : deux ajouts au kind `dataset` — `axes[]` (§13.3) et `source.layout` (§13.5).** Et
> **PAS de kind par niveau** : Expérimentation / Groupe / Participant / Scénario feraient quatre
> kinds pour un seul laboratoire, et autant d'inventés au suivant. `§9quinquies.3` a déjà tranché
> ce motif — pas un kind par famille. Même réponse à l'idée d'une « union de plusieurs kinds
> (catégorie, groupe, tag) » : **un seul kind, une liste d'axes, et des tags à côté** (§13.6).

### 13.5 DEUX LIEUX, pas trois modes — le manifeste déclare, le conteneur situe

> ⚠ **Rédaction corrigée le 2026-08-25.** La première version listait « trois modes de peuplement »
> en mettant sur le même plan **le patron**, **les méta du `.wdat`** et **le LLM**. C'était une
> erreur de catégorie : le patron et le LLM sont des **moyens de REMPLIR**, les méta du `.wdat` sont
> le **LIEU où le résultat se dépose**. Ils ne sont pas alternatifs.

| lieu | ce qu'il porte | cardinalité |
|---|---|---|
| **manifeste `dataset`** | les **axes** et leurs **valeurs possibles** (`reference_tables`) — le vocabulaire et la structure | **un**, pour l'expérimentation entière |
| **`.wdat`** (méta-info) | **le rangement** — les coordonnées de CE fichier sur ces axes (`groupe=âgés, participant=P12, scenario=S3`) | **un par essai / passation** |

⭐ **Pourquoi le rangement va dans le conteneur, et pas dans le chemin** : il **survit au
déplacement du fichier**. C'est déjà ce que faisaient les méta-infos `groupe`/`participant`/
`scénario` de l'outillage précédent — la reprendre n'est pas une régression, c'est la bonne idée
qu'on garde.

**Comment les méta se remplissent** — deux moyens, jamais bloquants :

| moyen | forme | note |
|---|---|---|
| **patron déclaré** — *le défaut et le repli* | `layout: "{groupe}/{participant}/{scenario}/*.wdat"` dans le manifeste | déterministe, auditable, **zéro GPU, zéro LLM** ; c'est un **aide-import**, pas une source de vérité |
| **proposé par le LLM** | exploration d'un arbre non rangé | ⚠ il propose **un PATRON**, jamais le manifeste ni les méta directement |

**Réponse au cas explicite** — *« comment fait-on si un chercheur ne veut pas de cette exploration
LLM et que les dossiers ne sont pas agencés logiquement ? »* : le patron se **déclare à la main**, ou
les `.wdat` **portent déjà** leurs coordonnées et le chemin n'est plus consulté du tout. Le LLM est
un **accélérateur, jamais un passage obligé**.

### 13.5bis ⭐ CE QUE `.trip` ET `.wdat` DISENT DÉJÀ — relevé, pas supposé (2026-08-25)

> Écrit après relecture de §6.2, §6.4, §9duodecies et §9terdecies à la demande de Fabien
> (*« ça manque d'approfondissement sur ce qu'on avait déjà acté »* — il avait raison, et la
> lecture ferme la moitié de D21).

**Le LIEU du rangement existe déjà dans les deux formats. Il n'y a rien à créer.**

| format | table | contenu |
|---|---|---|
| `.trip` | `MetaTripDatas (key, value)` | attributs libres **du trip** |
| `.trip` | `MetaParticipantDatas (key, value)` | attributs **du participant** |
| **`.wdat`** | **`WamaMeta (key TEXT PRIMARY KEY, value TEXT)`** | les **deux fusionnées en une** (`containers/wdat.py:102`) |

⇒ Le « rangement en méta-info » dont Fabien se souvenait est **exactement** `MetaTripDatas` /
`MetaParticipantDatas`. `.wdat` en a gardé le mécanisme et **retiré la distinction de table**.

#### ⭐ Et `TripSet` est le côté LECTURE — il montre précisément ce que WAMA ajoute

§6.4 le décrit sans le nommer ainsi : `TripSet` **agrège les métadonnées sur N trips** — *«
propriétés communes vs possibles, valeurs d'attributs pour tous les trips »*, c'est-à-dire *« quelles
données ai-je en commun sur l'ensemble de mes sujets ? »*. Le rattachement pressenti y était déjà
écrit : *« c'est le niveau `dataset` / `project` des kinds existants »*. **Confirmé — et voici la
différence exacte.**

> **BIND DÉRIVE le vocabulaire par agrégation. WAMA le DÉCLARE.**

Trois choses que la dérivation ne peut pas faire, et qui ne sont pas des raffinements :

1. **connaître un niveau à zéro occurrence** — un groupe dont aucune passation n'est encore
   importée n'existe pas pour l'agrégation ; il existe pour le protocole ;
2. **dire si un axe est niché ou croisé** — l'agrégation voit des **valeurs**, jamais des
   **relations**. C'est `contains`/`crosses`, donc le test licite, qui lui échappe entièrement ;
3. ⭐ **signaler un MANQUE** — si un `.wdat` ne porte pas son `participant`, l'agrégation ne
   proteste pas : elle rend simplement un ensemble plus petit. C'est précisément l'**`Ecart`** que
   la déclaration rend possible (§13.6), et la raison pour laquelle « déclarer puis mesurer »
   n'est pas une redite de ce qui existe.

#### ⚠ Ce que la fusion de `.wdat` rend NÉCESSAIRE (et qui reformule D21)

`.trip` séparait deux espaces (trip / participant) ; `WamaMeta` n'en a qu'un, et il porte **déjà**
des méta techniques — `schema_version` y est écrit (`containers/wdat.py:65`). Une clé `participant`
posée à plat y côtoierait donc une clé de format.

⇒ **La question ouverte n'est plus « quelle table » — elle est « comment nomme-t-on les clés ».**
Un préfixe d'espace de noms (`axe.participant = P12`) paraît forcé par la fusion, pas optionnel.
D21 est reformulée en ce sens.

### 13.6 ⭐ La confiance dans un LLM local : la contre-épreuve est le CORPUS, pas un second modèle

La question de Fabien — *« comment s'assurer de la bonne cartographie via un LLM local, sachant
qu'on ne donnera pas accès à un modèle cloud sur des données expérimentales ? Confrontation
LLM ? »* — **a déjà sa réponse écrite ET implémentée** dans `wama_data/dataset.py` :

> *« Le LLM propose, la machine dispose. Un manifeste généré par LLM qui VALIDE ensuite l'import est
> CIRCULAIRE. Le manifeste déclare des attentes **vérifiables mécaniquement** et l'importer
> **MESURE L'ÉCART**. »* — et `charger()` rend le couple `(référentiel, écart)`, jamais le
> référentiel seul, pour qu'ignorer l'écart soit un **geste délibéré**.

Appliqué aux axes, la réfutation est **arithmétique** :

| contrôle | ce qu'il donne |
|---|---|
| taux d'appariement du patron | 340/347 fichiers → **montrer les 7** |
| complétude du croisement | 12 participants × 4 scénarios = 48 attendus, 47 trouvés → **nommer le manquant** |
| contradiction dure | le même participant sous **deux** groupes → **erreur**, pas un écart |

> ⚠ **La confrontation LLM × LLM est plus faible et coûte du GPU** : deux modèles peuvent se tromper
> *d'accord*. Le système de fichiers, non. La contre-épreuve n'est pas un second avis, c'est **le
> corpus lui-même**.

**Le résidu que l'arithmétique n'attrape pas : l'étiquette sémantique.** Un patron parfaitement
apparié peut nommer `groupe` ce qui est en réalité `session`. Aucun compte ne le voit. → la
proposition est **montrée remplie, avec les effectifs** (`groupe : {jeunes: 12, âgés: 11}`) ; un
humain valide en cinq secondes. C'est la règle **« propose-cite-tu-valides »** déjà en vigueur pour
la prospection (`ROADMAP §16.1`) — **jamais d'auto-application**.

Même doctrine pour l'autre usage envisagé — *un protocole de traitement écrit en langage naturel,
traduit en manifeste `pipeline`* : c'est **§9undecies**, déjà cadré, et la borne y est la même.

### 13.7 Les tags — oui, mais à côté, et sans rôle

Un axe porte un **rôle** et une **relation** ; un tag n'a ni l'un ni l'autre. Les tags restent
utiles et infinis pour ce qui n'est pas une dimension de plan (`pilote`, `à refaire`, `séance du
matin`). **Ne pas leur faire porter la structure** — c'est précisément ce qui les rendrait
« simplistes » au sens de la question.

### 13.8 ⚠ NE PAS CONFONDRE — le nommage divergent entre sources (route réelle vs simulateur)

Autre fait apporté par Fabien : véhicule instrumenté sur route et conduite sur simulateur sont
**historiquement enregistrés tous deux en `.trip`** ; les **données sont en partie identiques**,
mais **le nommage des tables et des colonnes diverge** — et certaines grandeurs changent de nature :
**coordonnées GPS** d'un côté, **x, y, z dans le monde simulé** de l'autre.

Ce n'est **pas** le sujet des axes : les axes disent comment le **corpus** est organisé, ceci dit
comment un **flux** est identifié d'une source à l'autre. Deux mécanismes, deux endroits.

La réponse est **déjà à moitié dans le dépôt** :

1. **le sous-typage de `data_types.py` + `is_compatible`** — `position(wgs84)` et `position(world)`
   comme sous-types d'un `position` commun. Une fonction qui veut « une position » marche avec les
   deux ; une fonction qui **exige** du WGS84 (map-matching, fond de carte) refuse la simulée **par
   le type**, pas par convention ni par commentaire ;
2. **une table d'alias PAR SOURCE** — le mécanisme existe **en germe** et **codé en dur pour une
   seule clé** (`timecode` comme alias d'entrée, `sources/tabular.py`). À généraliser en **carte
   déclarée par source**, pas à réinventer.

> 🔚 **À MESURER avant de concevoir.** Fabien fournit deux jeux : un de l'**ancien** simulateur
> (rétrocompatibilité d'import uniquement — remplacé) et un du simulateur **actuel**. Premier geste :
> **relever les noms réels de tables et de colonnes**, pas les deviner. C'est la même méthode qui a
> payé sur `.rec` et sur la base `.trip` réelle.

### 13.9 INTÉGRATION DANS L'ÉCOSYSTÈME WAMA — où chaque pièce se branche

| pièce WAMA | ce que les axes y changent | état |
|---|---|---|
| kind `dataset` | **+ `axes[]`, + `source.layout`** | ⏳ deux champs à ajouter |
| `reference_tables` | domicile des **niveaux** d'un facteur (= `Levels` BIDS, *codelist* SDMX) | ✅ existe |
| `signals[]` | = les ***measures*** SDMX — inchangés, orthogonaux aux axes | ✅ existe |
| `Ecart` / `charger()` | la **réfutation arithmétique** du patron et du croisement | ✅ existe, à étendre |
| `WamaMeta` du `.wdat` | les **coordonnées**, préfixées `axe.` | ✅ existe (D21) |
| `.wds` — bundle corpus (D26) | transporte **manifeste + coordonnées ensemble** quand le corpus se déplace | ✅ tranché le 25/08 |
| explorateur & file Data (§11.8) | ⭐ **filtrage et group-by par axe → création de batch** | ✅ déjà relié |
| volet gauche — tri/filtrage (`WAMA_VOLETS §8`) | ⭐ **une SEULE brique de filtre pour les deux mondes** : facettes plates côté Médias (app, statut), facettes d'axes côté Data — pas deux tris | ✅ déjà relié |
| promotion mère↔fille (`MODES_QUEUE_UX §5ter`) | la card mère d'un batch = un niveau d'axe | ✅ |
| `FunctionSpec` / `data_types` | **rien** — les axes ne touchent pas la couche capacités (§13.3ter) | ✅ |
| couche statistique (`WAMA_APPRENTISSAGE §5`) | `contains`/`crosses`/`manipulated` ⇒ **le test licite** | ⏳ |
| `WAMA_APPRENTISSAGE §3` A1/A5 | **absorbés** par les axes | ✅ |
| kind `project` | rien — c'est l'unité de **droits** | ✅ D20 |

> ⭐ **Le point d'intégration le plus fort n'était pas prévu par ce §13 : c'est la FILE.**
> §11.8, écrit le même jour par une autre instance, le note déjà — *« le tri/filtrage de
> l'explorateur, pour le monde Data, est un filtrage par AXES : créer un batch = un group-by sur un
> axe »*. Les axes ne servent donc pas qu'à l'analyse : **ils sont ce qui rend la file du monde Data
> filtrable comme celle des Médias l'est par app et par statut.** Sans eux, l'explorateur Data n'a
> que des noms de fichiers à offrir. Deux fils indépendants ont convergé sur le même besoin — c'est
> le meilleur indice qu'il est réel.

#### ⚠ `manipulated` sur DEUX axes — oui, mais pas pour la raison proposée

Question de Fabien : *« on peut utiliser `groupe_age` comme `manipulated` si on veut comparer des
groupes d'âges »*. **Non — et la correction est la même règle pour la troisième fois.**

`manipulated` **n'est pas un choix d'analyse**. Il ne dit pas ce qu'on compare (on peut **toujours**
comparer), il dit **ce que le protocole a ASSIGNÉ**. On n'assigne personne à son âge ⇒
`groupe_age: manipulated: false`, **toujours**, quelle que soit la question posée ensuite.

**Mais oui, les deux peuvent être `true` — quand les deux sont assignés.** Exemple réel : `groupe` =
expérimental / contrôle **tiré au sort** × `scenario` contrebalancé. Plan factoriel mixte classique,
deux facteurs manipulés.

| | conclusion permise |
|---|---|
| `manipulated: false` | une différence est une **association** |
| `manipulated: true` | une différence peut être un **effet** |

⇒ Le mot ne borne pas l'**analyse**, il borne la **conclusion**. C'est exactement pourquoi il doit
être déclaré au corpus et pas choisi au moment du test.

#### Oui, les `key` sont ce sur quoi on trie, filtre et crée des batchs

Confirmé, et **déjà écrit ailleurs** : `§11.8 ⑧` fait du group-by sur axe le geste de création de
batch. Une `key` d'axe est donc simultanément : une **facette de filtre** dans l'explorateur, un
**critère de group-by** pour fabriquer un batch, une **colonne** dans un export, et une **clé de
jointure** entre `.wdat` d'un même corpus.

---

### 13.10 LES QUESTIONNAIRES — oui, et c'est le cas le plus NATUREL du modèle

Six méthodologies du laboratoire, confrontées au modèle :

| méthodologie | unité d'observation | axes typiques | axe temporel ? | verdict |
|---|---|---|---|---|
| questionnaire **en ligne** (panel à grande échelle) | répondant | vague, canal de recrutement | ❌ **aucun** | ⚠ **bloqué**, voir ci-dessous |
| questionnaire **participant** (psychotechnique, disque des émotions, avis) | participant | — il **produit** des attributs et des facteurs | ❌ | ✅ **le cas le plus naturel** |
| expérimentation **sur table** | participant | tâche, condition | ✅ | ✅ déjà compatible |
| **véhicule instrumenté** | participant | trajet, section | ✅ | ✅ + §13.8 (GPS) |
| **simulateur** | participant | scénario | ✅ | ✅ + §13.8 (x, y, z) |
| **naturalistic driving** | ⚠ conducteur **ou véhicule** | période, contexte | ✅ | ⚠ voir §13.11 |

**Trois rôles distincts pour un questionnaire**, qu'il ne faut pas confondre :

1. **producteur d'axes** — c'est l'usage principal. Un test psychotechnique, un disque des émotions,
   une échelle de Likert produisent des **`attribute`s** (valeur libre) et des **`factor`s** (niveaux
   fermés → `reference_tables`). ⭐ Un questionnaire participant **ne devient jamais un signal** : il
   ne varie pas pendant l'observation — c'est le critère BORIS (§13.3ter) qui le dit ;
2. **corpus à part entière** — un panel en ligne est un corpus dont l'unité est le répondant et qui
   **n'a aucun axe temporel** ;
3. **mesure répétée** — le même questionnaire avant/après ou par scénario devient un facteur
   **croisé** avec le participant (`crosses`), et il rentre dans le cas général.

> ✅ **BLOCAGE LEVÉ le 2026-08-26** (§13.14). `validate_dataset_body` exigeait *« signals doit être
> une liste non vide »* et refusait donc tout corpus purement questionnaire. La règle est désormais
> **« au moins l'un des deux »** : un dataset décrit des flux, un plan d'expérience, ou les deux.

⭐ **Et l'intérêt va plus loin que « ne pas bloquer » (précision de Fabien, 2026-08-26).** En
pratique les questionnaires sont traités **à part** des passations, et l'union se fait **au moment
des statistiques** — donc sur des sorties déjà agrégées. Les tenir dans le **même monde** permet de
croiser en gardant **la granularité fine des réponses**, et surtout de **rattacher le QUALITATIF à
l'exploitation QUANTITATIVE** : une citation, un verbatim, restent liés à l'item et au participant
au lieu d'être traités dans une chaîne séparée. C'est un gain de méthode, pas seulement de format.

**Prior art à reprendre pour nommer l'instrument** : BIDS a des fichiers `phenotype/` accompagnés
d'un `MeasurementToolMetadata` — `Description` (texte libre) + `TermURL` (vers une ontologie
d'instrument). C'est exactement la déclaration « ce questionnaire est l'échelle X v1.2 », et ça
manque à notre modèle, qui décrit les variables produites sans nommer l'outil qui les produit.

---

### 13.11 POINTS D'OMBRE — honnêtes, et deux ne sont pas des détails

| # | angle mort | gravité |
|---|---|---|
| ① | ~~corpus sans axe temporel~~ | ✅ **LEVÉ le 2026-08-26** (§13.14) |
| ② | ~~plusieurs unités d'observation dans un même corpus~~ | ✅ **LEVÉ le 2026-08-26** — plusieurs `observation` sont acceptées, et **dès qu'il y en a deux le rattachement devient obligatoire** (§13.14) |
| ②bis | ⚠ **ET J'AVAIS SURESTIMÉ CE TROU.** « mesures par participant **et** par trajet » — question de Fabien : *« en quoi on ne peut pas le faire avec l'existant ? »* — **était DÉJÀ exprimable** : le trajet est le grain, le participant le contient (`contains`), et chaque attribut nomme son niveau de rattachement (`attached_to`). Le cas réellement manquant était **deux grains NON emboîtés** (dyade conducteur+passager, plusieurs *subjects* BORIS). J'ai décrit comme structurel un besoin dont une moitié était déjà couverte | ✅ corrigé |
| ③ | **plan déséquilibré déclaré** — un participant qui n'a fait que 3 scénarios sur 4. L'`Ecart` le **signale**, mais on ne peut pas le **déclarer comme attendu** ; tout écart légitime sonnera donc comme un défaut | ⚠ un contrôle qui sonne toujours n'est plus lu (leçon `Ecart.lecteur`) |
| ④ | **vagues / longitudinal** — DDI a l'héritage de série entre vagues, nous non | ⚠ |
| ⑤ | **`universe`** — ce que le corpus vise, pas seulement ce qu'il contient (D25) | ⏳ |
| ⑥ | ⭐ ~~facteur DÉRIVÉ D'UN MODÈLE~~ | ✅ **LEVÉ le 2026-08-26** — `derived_from` accepte une référence de manifeste `{kind, key}`. Un profil de conducteur issu d'un clustering **est un facteur** dont la provenance est déclarée. ⭐ Fabien : *« si on peut ajouter un profil comme nouveau facteur, on peut alors relier un conducteur à un profil par comparaison »* — c'est exactement ce que la boucle avec `WAMA_APPRENTISSAGE` permet |
| ⑦ | **naturalistic driving** — ⚠ **ÉNONCÉ CORRIGÉ par Fabien (2026-08-26)** : j'avais écrit « la passation n'existe pas ». **Faux — chaque trajet EST une passation**, l'acquisition ne se déclenche qu'en roulage. Le vrai cas limite est l'enregistrement **continu** (une expérimentation de 2 mois de vidéo, déjà réalisée) : voir §13.14 « les deux découpages » | ⚠ requalifié, plus petit qu'annoncé |

**Niveau de confiance, RÉÉVALUÉ après les déblocages du 2026-08-26** : **élevé** sur l'universalité
du triplet (cinq standards convergents, trois domaines hors conduite vérifiés) ; **relevé de moyen
à bon** sur la modularité — les deux angles morts qualifiés de structurels (② et ⑥) sont levés et
couverts par des tests, et ②bis était en partie une erreur d'analyse de ma part ; **faible**, et
inchangé, sur ce qu'on n'a pas encore essayé : le seul juge reste le manifeste écrit à la main sur
un corpus réel.

---

### 13.12 QUICK WINS — dans cet ordre

| # | quoi | coût | pourquoi celui-là d'abord |
|---|---|---|---|
| ① | ✅ **FAIT 2026-08-26** — `axes[]` dans `validate_dataset_body` (+ 20 tests) ; `source.layout` reste à faire (D22) | un validateur | zéro UI, zéro migration, zéro dépendance |
| ② | ⭐ **écrire À LA MAIN le manifeste `dataset` du `.trip` réel** qu'on a déjà | une heure | **c'est le juge de tout le reste.** Le risque documenté n'est pas la couverture insuffisante, c'est **le vocabulaire trop large que personne n'annote** (mode d'échec d'OWL-S). Un manifeste réel, volontairement pauvre, dira où ça casse |
| ③ | ✅ **FAIT 2026-08-26** — `signals` facultatif si `axes` présent | 3 lignes | débloque les **questionnaires** (§13.10) |
| ④ | ✅ **FAIT 2026-08-26** — `attributs_de_coordonnees()` + aller-retour prouvé (§13.19) | petit | ferme **D21**, rend les `.wdat` **autoportants** |
| ⑤ | étendre `Ecart` aux axes (taux d'appariement, complétude du croisement, contradiction dure) | moyen | c'est **toute** la confiance accordée à une proposition LLM (§13.6) |
| ⑥ | exposer les axes en **facettes de filtre** de l'explorateur Data (§11.8) | dépend de l'UI en cours | premier bénéfice **visible**, et il sert le fil parallèle |

> ⚠ **J'avais écrit « l'ordre ① → ② n'est pas négociable ». Formulation à retirer — Fabien a
> proposé l'inverse et il a raison** : *« ne faut-il pas ajuster d'abord le code pour voir si ça
> reste compatible avec un trip réel avant de créer ce manifeste ? »* Un manifeste écrit contre un
> validateur qui refuse encore les questionnaires et les grains multiples aurait décrit un modèle
> qu'on venait de corriger. **①③ d'abord (ils LÈVENT des refus), ② ensuite** — et ② reste le juge
> de tout le reste, ce qui n'a pas changé.

---

### 13.14 ✅ LIVRÉ le 2026-08-26 — les déblocages, et trois corrections d'énoncé

> Décision de Fabien : *« il faut lever les blocages avant d'aller plus loin pour ne pas s'empêtrer
> plus tard »*. Fait dans `wama/common/manifests/builtin/dataset.py` +
> `wama/common/tests_manifest_axes.py` (**20 tests**, et **649 tests** `wama_data` + catalogues au
> vert — aucune régression).

⚠ **Le kind `dataset` n'avait AUCUN test** avant ce jour (mesuré : `validate_dataset_body` n'était
cité que par son propre module). Ses deux défauts étaient donc invisibles par construction — même
motif que le lecteur `.trip` sans couverture (§9nonies.2).

**Ce qui est livré :**

| # | déblocage | forme |
|---|---|---|
| ① | **corpus sans flux temporel** | `signals` et `axes` : « au moins l'un des deux ». Un panel en ligne se déclare sans aucun signal |
| ② | **plan d'expérience** `axes[]` | rôles `observation`/`factor`/`attribute` (vocabulaire **fermé**), `contains`/`crosses`, `attached_to`, `manipulated`, `counterbalanced`, `levels: ref:<table>`, `derived_from` |
| ③ | **plusieurs unités d'observation** | acceptées ; ⭐ **dès qu'il y en a deux, `contains`/`crosses`/`attached_to` devient OBLIGATOIRE** — un rattachement deviné est le genre d'erreur qu'on découvre à l'analyse |
| ④ | **facteur dérivé d'un modèle** | `derived_from: {kind: model, key: …}` — le profil de conducteur appris est un facteur à provenance déclarée |
| ⑤ | **nidification récursive** | `contains` s'enchaîne sans limite de profondeur ; seule la **boucle** est refusée |

#### ⭐ `present_dans` était DÉJÀ récursif — et son défaut est ailleurs

Précision de Fabien : *« `present_dans` peut être récursif — une situation de suivi de véhicule
avec des sous-situations à l'intérieur, ça a déjà été fait au laboratoire »*. **Vérifié dans le
code** : `present_dans(segments, reference)` est une **opération ensembliste fermée** (elle prend
des segments, elle rend des segments) — la réappliquer sur son propre résultat EST la récursion.
**Rien à ajouter.**

> ⚠ **Mais un défaut réel apparaît en le lisant** : le défaut est `strict=True`, qui exige des
> bornes **strictement intérieures**. Une sous-situation qui **partage une borne** avec sa
> situation mère est donc **silencieusement écartée** — or c'est le cas normal quand le
> sous-découpage vient du même geste. La docstring le dit déjà (*« `False` … quand la référence a
> été produite par le même découpage »*), mais **le défaut ne suit pas la docstring**. À trancher
> avant le premier découpage hiérarchique réel (⇒ **D32**, ex-D27 — voir la note de collision).

#### ⭐ Naturalistic driving — LES DEUX DÉCOUPAGES, et ils ne coïncident pas

Correction de Fabien : *« en naturalistic driving il y a bien des passations — chaque trajet est
une passation, l'acquisition ne se déclenche qu'en roulage »*. Mon « la passation n'existe pas »
était faux. Le cas limite est ailleurs, et il l'a nommé lui-même : une expérimentation **déjà
réalisée** de **2 mois de vidéo continue**, découpée « tous les x temps ».

D'où une distinction que le modèle doit tenir, et qu'il tient :

| découpage | qui le produit | pourquoi | dans WAMA |
|---|---|---|---|
| **d'ACQUISITION** | automatique, technique — toutes les X minutes / X Go | éviter la perte de données ; on ne stocke pas 2 mois continus | la **frontière d'un `.wdat`** |
| **d'ANALYSE** | le Segmenter, **par situations** | c'est l'unité sur laquelle on calcule et on compare | l'axe `observation` |

> ⭐ **Ils ne coïncident pas, et c'est très bien** — c'est même la question que Fabien pose : *« le
> découpage automatique correspond-il au découpage qu'on souhaite ? »* Réponse : **non, et il n'a
> pas à le faire.** Le conteneur est une commodité de stockage, le grain est une décision
> d'analyse. Le §13 les sépare déjà (§13.0 : « un manifeste `dataset` = une expérimentation ; les
> `.wdat` sont ses feuilles »).
>
> ⚠ **Conséquence à ne pas perdre** : une situation peut **traverser une frontière de conteneur**
> (un dépassement à cheval sur deux tranches de 10 minutes). Le Segmenter doit donc pouvoir lire
> **par-dessus** le découpage d'acquisition — ce qu'il ne sait pas faire aujourd'hui, chaque lecteur
> ouvrant **un** fichier (⇒ **D33**, ex-D28 — voir la note de collision).

---

### 13.15 ⭐ LE PREMIER MANIFESTE `dataset` ÉCRIT À LA MAIN — et ce qu'il a mordu (2026-08-26)

> `manifests/datasets/madison-simulateur.json`, transcrit **champ par champ depuis le catalogue
> d'un `.trip` réel** (`RecFile_REC_20190502_144710.trip` : 37 tables, 10 flux, 6 événements,
> 12 situations, 2 vidéos). Vocabulaire **volontairement pauvre**. Enveloppe **OK**, corps **OK**.
> C'était le quick win ② — « le juge de tout le reste ». Il a jugé.

#### ⭐ Ce que le fichier RÉEL contient déjà, et qu'on n'aurait pas deviné

**`MetaTripDatas` porte `('scenario', 'Test')` et `('participant_id', 'Passation_01')`.** Les
coordonnées d'axes **sont déjà là**, en **clés plates**, dans le fichier de 2019. §13.5 (« le
`.wdat` porte son rangement en méta-info ») n'était donc pas une proposition : c'est un **relevé**.

⚠ **Conséquence directe sur D21** : l'outil d'origine n'utilisait **aucun préfixe**. Notre `axe.`
n'est pas un ajout neutre, c'est un **changement de convention** — il faut donc lire les deux
formes (alias d'entrée, exactement comme `timecode` l'est déjà pour `time`), sinon on cesse de
reconnaître les coordonnées des corpus existants.

#### ⚠ Trois pièges que seule l'écriture du manifeste a exposés

| # | constat mesuré | conséquence |
|---|---|---|
| ① | **`participant_id` vaut `Passation_01`** — la clé dit « participant », la valeur nomme une **PASSATION** | le manifeste déclare donc `passation` comme unité d'observation, **pas** `participant`. Sur un corpus de N trips, les deux doivent être distingués : sinon deux passations d'une même personne comptent pour deux individus indépendants — exactement la fuite que l'axe `observation` doit empêcher |
| ② | **`MetaParticipantDatas` : 0 ligne** | la table des attributs participant **existe et n'a jamais été remplie**. Aucun `attribute` n'est déclarable depuis ce corpus : ni âge, ni groupe. **Le lieu existait, la pratique non** — et c'est précisément ce qu'une déclaration rend visible |
| ③ | `MetaEvents` déclare **`debScn-finVirage_0_0`** (tiret) alors que la table s'appelle **`event_debScn_finVirage_0_0`** (souligné) | **le nom du catalogue et le nom de la table divergent.** Un lecteur qui joint sur le nom rate cet événement en silence. Vaut pour tout import de `.trip` tiers |

Deux constats mineurs, notés pour ne pas être redécouverts : **`MetaDatas.frequency` vaut `0`** pour
les 8 flux acquis — ni une cadence réelle, ni le `-1` que §6.2 documente comme « non régulier » ;
et les 12 situations portent toutes `isBase=0`, donc **tout le contenu d'analyse est dérivé**,
cohérent avec §6.2.

#### ⚠⚠ Et un défaut de conception trouvé PAR l'écriture — `source` existe à DEUX étages

Le premier jet a échoué sur `source manquant ou non-dict`. Cause immédiate : j'avais écrit le
manifeste **à plat** au lieu de `{"body": {…}}`. Mais la correction a révélé le vrai problème :

| étage | vocabulaire de `source.type` | ce qu'il désigne |
|---|---|---|
| **enveloppe** (`envelope.py`) | `builtin` \| `library` \| `folder` \| `extract` | d'où vient **le MANIFESTE** |
| **corps** (`builtin/dataset.py`) | `rtmaps` \| `lsl` \| `rosbag` \| `csv` \| `parquet` \| `db` \| `docs` \| `other` | d'où viennent **les DONNÉES** |

**Le même nom, deux vocabulaires disjoints, dans un seul fichier.** C'est la même famille de défaut
que §9decies.3 (`source.type` provenance vs capacité de lecteur), qui avait déjà coûté une fausse
piste — et cette fois il est structurel, pas conjoncturel. ⇒ **D29**.

⚠ Et le **message d'erreur induit en erreur** : il annonce « source manquant » quand le vrai défaut
est que **tout le corps est au mauvais étage**. Le premier auteur d'un manifeste écrit à la main est
exactement celui qui n'a pas le contexte pour traduire ce message.

#### Ce que le manifeste ne déclare PAS, et pourquoi c'est le bon résultat

Pas d'`attribute` (rien à déclarer, ②), un seul niveau de `scenario` (`Test`), et `fenetre_analyse`
déclaré en facteur avec ses 12 niveaux — ce qui **applique D11** : les paramètres de fenêtre
cessent d'être enfouis dans un nom de table (`situation_0_15`) pour devenir **interrogeables**.

> **Bilan du quick win ②.** Le vocabulaire des axes n'a eu besoin d'**aucun ajout** pour décrire un
> corpus réel — c'est le point positif. Tout ce qui a cassé était **ailleurs** : la forme du
> corpus, l'ambiguïté de `source`, la qualité du message d'erreur, et les divergences du fichier
> source. C'est exactement ce qu'on attendait d'un manifeste écrit à la main plutôt que d'une
> spécification écrite à l'aveugle.

---

### 13.17 ✅ L'ÉCART PORTE LES AXES — et il a trouvé un défaut du lecteur `.trip` (2026-08-26)

> Quick win ⑤. `wama_data/dataset.py` + 12 tests (`tests_dataset.py`), **640 au vert**.
> Confronté au `.trip` réel, pas à une fixture.

**Ce qui est livré** — `Ecart` gagne `coordonnees` (axes situés) et `axes_sans_coordonnee`, et
`situer()` résout **trois graphies**, dans cet ordre : `axe.<clé>` (convention WAMA) · `<clé>`
(convention de l'outil d'origine, **relevée** au §13.15) · `source_key` (alias déclaré par l'axe).

> ⚠ **`axes_sans_coordonnee` est INFORMATIF, jamais un verdict.** Tous les axes ne sont pas des
> coordonnées de conteneur : `participant` et `scenario` valent pour tout le fichier, une fenêtre
> d'analyse indexe des **lignes**. Faire échouer la conformité dessus ferait sonner le contrôle sur
> tout manifeste correct — le défaut déjà corrigé une fois sur `Ecart.lecteur`.

**Résultat sur le fichier réel**, et il est exactement celui qu'on espérait :

```
axes situés          : scenario=Test
axes sans coordonnée : passation, fenetre_analyse
```

`scenario` est retrouvé **sans préfixe**, par la seconde graphie. `passation` ne l'est pas — parce
que sa clé source est `participant_id` et que le manifeste ne déclarait pas encore l'alias. **La
mesure a nommé le manque au lieu de le deviner** : c'est le geste que §13.6 promettait.

#### ⚠⚠ ET UN DÉFAUT RÉEL DU LECTEUR `.trip`, que seul ce parcours pouvait exposer

L'écart annonçait **15 signaux absents sur 15**, d'un fichier qui les contient tous. Mesuré :

| appel | identifiant employé |
|---|---|
| `probe().streams` | le nom de **TABLE** — `data_BIOPAC_MP150`, `event_CADISP` |
| `read()` → signal dans le référentiel | le nom du **CATALOGUE** — `BIOPAC_MP150`, `CADISP` |
| `load(streams=['CADISP'])` | ❌ `ValueError: 'CADISP' n'est pas un flux reconnu` |
| `load(streams=['event_CADISP'])` | ✅ … et rend un signal nommé **`CADISP`** |

> **L'identifiant pour DEMANDER un flux et celui pour le RETROUVER ne sont pas le même.** Un auteur
> de manifeste lit `MetaDatas` — il écrira donc systématiquement la forme que `probe()` rejette ;
> et s'il écrit la forme préfixée, le référentiel lui rendra des signaux qu'il ne saura plus
> adresser. **Les deux chemins sont cassés**, dans les deux sens.
>
> ⭐ Et c'est le **retour du défaut que `.wdat` avait été créé pour retirer** : §9duodecies.3 pose
> « la famille n'est plus dans le NOM », §9nonies « la famille portée comme DONNÉE ». Le lecteur
> `.trip`, lui, garde le préfixe de famille **dans l'identité du flux** côté `probe`, et le retire
> côté `read`. Le fait était établi ailleurs dans le dépôt et n'était pas relié à sa conséquence —
> **septième occurrence** du motif.

**Ce qui a été fait, et ce qui ne l'a pas été.** Le contrat de `probe()` n'est pas modifié : il
touche 73 tests `sources` et le travail en cours d'une autre instance. Ce qui est livré est un
**indice** : quand *tous* les signaux déclarés sont absents mais recouverts par un préfixe de
famille, l'écart **nomme la cause** (`⚠ les 15 signaux déclarés existent sous un nom PRÉFIXÉ (ex.
« BIOPAC_MP150 » → « data_BIOPAC_MP150 ») — voir D31`). Le pire cas n'est pas la perte, c'est la
perte **silencieuse**. ⇒ **D31** tranche le fond.

---

### 13.18 ✅ D31 CLOSE — `probe()` et `read()` nomment enfin la même chose (2026-08-26)

**La mesure d'abord, la décision ensuite.** Le fond de D31 opposait deux options ; c'est le risque
de **collision de noms entre familles** qui devait trancher, et il a été mesuré sur la base réelle :

```
flux : 28 · noms distincts : 28 · COLLISIONS : aucune
noms nus ressemblant à une table préfixée : aucun
```

**Option A retenue** — `probe()` expose le **nom de catalogue**, la famille restant portée comme
donnée (`SignalMeta.data_type`, déjà le cas depuis §9nonies). Trois précautions :

1. ⭐ **la forme préfixée reste acceptée en lecture** — `load(streams=['data_vitesse'])` marche
   toujours. *Un correctif qui casse ses propres appelants n'en est pas un* ;
2. l'index reste `{nom: [tables]}` et non `{nom: table}` : la collision n'est pas déclarée
   impossible, elle est rendue **détectable** — un nom porté par deux familles lève une erreur qui
   **nomme les candidates** ;
3. le contrat de `read()` est inchangé.

#### ⚠ Et une surestimation de ma part, corrigée par la mesure

J'avais écrit que l'option A « touche 73 tests `sources` ». **Faux** : 73 est le total du module.
Le changement a fait tomber **UN seul test** — celui qui attestait précisément l'ancien contrat
(`probe` rendant `data_vitesse`). Il est réécrit pour attester la **concordance** des deux bouts,
et deux tests l'accompagnent (graphie préfixée toujours acceptée, flux inconnu toujours refusé).
**642 tests au vert.** Annoncer un coût sans le mesurer, c'est ce qui fait renoncer à un correctif
juste — la borne héritée qu'on défend au lieu de la vérifier.

#### Le résultat sur le fichier réel, manifeste INCHANGÉ

```
conforme : True    ·    signaux manquants : ()
```

Le manifeste du §13.15, écrit depuis le catalogue, **décrit maintenant exactement le fichier**.
Restent 13 flux « présents non déclarés », et ils sont tous légitimes : les **12 tables de
situation** (décrites en `records`, pas en signaux — une source peut contenir plus que ce qu'on a
choisi d'en décrire) et `debScn_finVirage_0_0`.

> ⚠ **Ce dernier est le constat ③ du §13.15, et il SURVIT au correctif** — c'est important. Ce que
> `probe()` expose est le **nom de table moins son préfixe**, qui coïncide avec le nom de catalogue
> *sauf* là où l'outil d'origine a réécrit des caractères en créant la table (`debScn-finVirage_0_0`
> devenu `event_debScn_finVirage_0_0`, tiret → souligné). La divergence appartient au **fichier
> source**, pas au lecteur ; elle est désormais **visible** comme un flux non déclaré au lieu de
> passer inaperçue. On ne la corrige pas en silence : réécrire un nom de flux à l'import inventerait
> une donnée.

---

### 13.19 ✅ L'ALLER-RETOUR DES COORDONNÉES EST PROUVÉ — D21 close (2026-08-26)

Quick win ④. `attributs_de_coordonnees()` rend la forme **canonique d'écriture** `axe.<clé>`,
destinée à `Contexte.attributs` ; `situer()` la relit par sa première graphie. **649 tests au vert.**

⭐ **Aucun changement de schéma n'a été nécessaire** — et c'est le résultat intéressant :
`Contexte.attributs` alimentait déjà `WamaMeta`, et **les quatre lecteurs** (`trip`, `wdat`,
`rtmaps`, `tabular`) exposent déjà `SourceInfo.attributes`. La pièce manquante n'était pas un
mécanisme, c'était **une convention de nommage et sa preuve**.

Le test qui porte le tout écrit un `.wdat` avec deux coordonnées, le rouvre par `sources.probe()`
et les retrouve toutes les deux — écriture et lecture appariées de bout en bout.

#### D21 — pourquoi le préfixe est NÉCESSAIRE, et pas un confort

`WamaMeta` est un espace **partagé** : il porte déjà `format`, `schema_version`, `created_at`,
`created_by`, `streams`. Une clé `participant` posée à plat y côtoierait une clé de format — et un
axe qu'on appellerait `format` capterait la méta technique. Un test le fixe :
`situer([{key: 'format'}], {'format': 'wdat', 'axe.format': 'A4'})` rend **`A4`**.

C'est la fusion des deux tables de `.trip` en une seule (`§9duodecies.3`) qui rend le préfixe
obligatoire : là où l'outil d'origine séparait `MetaTripDatas` et `MetaParticipantDatas`, nous
n'avons qu'un espace, donc il faut le nommer.

> ⚠ **Et la compatibilité descendante n'est pas négociable** : les corpus existants n'ont **pas**
> le préfixe (§13.15 : `scenario`, `participant_id` depuis 2019). `situer()` lit donc les trois
> graphies — `axe.<clé>`, `<clé>`, `source_key`. Écrire la forme canonique n'oblige personne à
> réécrire ses fichiers.

---

### 13.16 RGPD et SI de laboratoire — non bloquant, mais UNE chose est gratuite maintenant

> Question de Fabien (2026-08-26) : un **registre RGPD** (cycle et traitement des données) est à
> remplir **pour chaque expérimentation** ; les documents (administratif, littérature, livrables)
> vivent sur le serveur distant dans le dossier du projet et sont suivis dans le SI du laboratoire.

**Verdict : rien de bloquant, et il ne faut PAS l'ouvrir maintenant.** Deux raisons de fond :

- le SI est un **système d'enregistrement** externe. Même doctrine que pour le suivi
  d'entraînement (`WAMA_APPRENTISSAGE §4`) : **on référence, on n'absorbe pas.** Dupliquer un
  registre RGPD dans WAMA créerait une seconde vérité qui divergerait ;
- l'ancrage naturel existe déjà et c'est le kind **`project`** — l'unité de droits cross-org, qui
  porte déjà `owner_org`, `lead`, `members`. Un identifiant de dossier SI y est un champ, pas une
  architecture.

#### ⭐ Ce qui est gratuit maintenant, et cher plus tard

Les axes rendent une partie de l'inventaire RGPD **dérivable au lieu d'être ressaisie** — et c'est
un effet de bord qu'on n'avait pas cherché :

| ce que le plan d'expérience dit déjà | ce que le registre RGPD demande |
|---|---|
| l'unité d'observation est une **personne** (`participant`) ou non (`véhicule`, `site`, `éprouvette`) | *le traitement porte-t-il sur des personnes physiques ?* |
| les `attribute` rattachés à cette unité | *quelles catégories de données ?* (âge, sexe, santé…) |
| un `factor` `derived_from` un `model` | *y a-t-il profilage ?* — question explicite du RGPD |

⇒ **Une seule déclaration mérite d'être posée tôt**, parce qu'elle est irrattrapable en aval :
`observation` doit pouvoir dire **si son unité est une personne**, et un axe **s'il est
identifiant direct, pseudonyme ou anonyme**. Sur le corpus mesuré au §13.15, `participant_id`
vaut `Passation_01` — un **pseudonyme**, la table de ré-identification vivant ailleurs : c'est
exactement le fait qu'un registre RGPD veut voir écrit. ⇒ **D30**.

Le reste — base légale, durée de conservation, DPIA, mesures de sécurité — est du **texte de
registre**, il n'a rien à faire dans un manifeste technique. La rétention, elle, a déjà son
mécanisme (`PROFILES_PERMISSIONS §3`).

---

### 13.13 Décisions ouvertes

Voir **D21 à D25** au §10 (D20 close).

---

## 14. LA MIGRATION DE NOMMAGE (D28) — cartographie MESURÉE et coût (2026-08-26)

> Demande de Fabien : *« Peux-tu faire la cartographie du renommage et évaluer le coût de
> remettre tout ça en ordre ? Je stoppe les autres instances quand on s'en occupe. »* Règle
> cible = celle du dépôt (CLAUDE.md, 22/08) : **identifiant importé = anglais ; tests = français ;
> prose/docstrings = français**.

### 14.1 La mesure — cinq faits qui dimensionnent le chantier

1. **~124 symboles publics français**, ~760 occurrences dans le code de `wama_data` (124 fichiers
   scannés) + ~970 dans ses tests. Par foyer : export 171+218 · segmentation 110+125 ·
   conditions 89+110 · frames/vue/dataset 89+203 · sources/containers 99+91 · valeurs/noms/geo
   93+67 · coding 55+65 · calculation 34+59 · enveloppes 19+33.
2. ⭐ **Les consommateurs EXTERNES sont déjà anglais.** 6 fichiers seulement importent
   `wama_data` hors du monde (5 × cam_analyzer, 1 × doc_facts) et tous consomment la famille
   anglaise (`trajectory_offset`, `sky_mask_at`, `parse_rec`, `depth_geometry`,
   `track_position_spread`, kinematics…) — **UNE exception** : `doc_facts` importe `mesurer`
   (1 site). La migration est donc quasi intégralement INTERNE.
3. ⭐⭐ **Zéro clé française sérialisée** : `manifests/` ne contient AUCUN `segment_*`/`calcul_*`/
   `codage_*`. Les 17 clés de catalogue françaises et les ~16 clés `ParamSpec` françaises ne
   vivent encore que dans le code — **la fenêtre se referme au premier protocole réel écrit**.
4. ⚠⚠ **Le vrai coût n'est PAS le volume, c'est l'HOMONYMIE code/prose.** Les docstrings français
   (qui RESTENT français) emploient les mêmes mots que les identifiants — « la *jonction* de deux
   flux », « les *marges* » : un sed aveugle corromprait la prose. → renommage **outillé AST**
   (rope/libcst) ou revue hunk par hunk ; jamais un remplacement textuel global.
5. Les valeurs de trace **écrites dans les données** (`origin='autour'|'jonction'|'marges'…`,
   colonnes `origin` des conteneurs) migrent avec les écrivains ; les fichiers déjà écrits
   gardent les anciennes valeurs → **tolérance de lecture**, pas de réécriture de données.

### 14.2 La table de correspondance proposée (à valider avant la passe)

**Clés de catalogue (17 — contrat sérialisable, priorité absolue)** :
`segment_autour_event→segment_around_events` · `segment_jonction→segment_join` ·
`segment_conditionnel→segment_conditional` · `segment_etats→segment_states` ·
`segment_present_dans→segment_within` · `segment_marges→segment_margins` ·
`segment_marges_spatiales→segment_spatial_margins` ·
`segment_chaine_conditionnelle→segment_condition_chain` ·
`event_chaine_conditionnelle→event_condition_chain` · `distance_a_point→distance_to_point` ·
`calcul_glissant→calc_rolling` · `calcul_derivee→calc_derivative` · `calcul_cumul→calc_cumulative` ·
`calcul_par_segment→calc_per_segment` · `codage_segments→coding_segments` ·
`codage_evenements→coding_events` · `codage_accord→coding_agreement`

**Clés `ParamSpec` (sérialisées dans les protocoles)** : `colonne→column` · `operateur→operator` ·
`seuil→threshold` · `duree_min→min_duration` · `trou_tolere→gap_tolerance` · `ignorer→ignore` ·
`connecteurs→connectors` · `avant/apres→before/after` (+`_m`) · `depuis_debut/depuis_fin→
skip_starts/skip_ends` · `repeter→repeat` · `fermer_dernier→drop_last_open` · `montantes/
descendantes→rising/falling` · `nom→name`

**Cœur, par module** (modules renommés : `valeurs.py→values.py`, `noms.py→naming.py`,
`vue.py→view.py`) :
- `segmentation` : `autour→around` · `jonction→join` · `conditionnelle→conditional` ·
  `masque_hysteresis→hysteresis_mask` · `bascules→edges` · `etats→states` ·
  `present_dans→within` · `chevauche→overlapping` · `ouverts→open_ones` · `fermer→close` ·
  `marges→margins` · `marges_spatiales→spatial_margins`
- `calculation` : `appliquer→apply` · `glissant→rolling` · `derivee→derivative` ·
  `cumul→cumulative` · `par_segment→per_segment` · `echantillons_du_segment→segment_samples`
- `conditions` : `Operateur→Operator` · `Connecteur→Connector` · `valider→validate` ·
  `evaluer→evaluate` · `rendre→render` · `analyser→parse` · `condition_depuis_dict→
  condition_from_dict` · `nom_chaine→chain_name` · `operateurs_pour→operators_for`
- `coding` : `Protocole→Protocol` · `SessionCodage→CodingSession` · `Modificateur→Modifier` ·
  `Comportement→Behavior` · `rejouer→replay` · `accord→agreement` · exceptions idem EN
- `export` : `Colonne→Column` · `Identite→Identity` · `Regroupement→Grouping` · `Fichier→
  ExportFile` · `exporter→export` · `apercu→preview` · `lignes→rows` · `rendre→render` ·
  `enregistrer_format→register_format` · `formats_disponibles/ecrivables→available/
  writable_formats` (`Declaration` : déjà anglais)
- `values`/`naming`/`geo` : `manquant→missing` · `presentes→present` · `normaliser→normalize` ·
  `abreger→abbreviate` · `nom_produit→derived_name` · `nom_jonction→join_name` ·
  `nom_annexe→annex_name` · `distances_a_point→distances_to_point` ·
  `abscisse_curviligne→arc_length`
- `frames`/`view`/`dataset` : `frame_depuis_signal→frame_from_signal` (et symétriques) ·
  `adjoindre→adjoin` · `type_par_defaut→default_type` · `Vue→View` · `Piste→Track` ·
  `Fenetre→Window` · `ColonneDerivee→DerivedColumn` · `Resultat→Result` · `serie→series` ·
  `Ecart→Discrepancy` · `charger→load` · `verifier→verify` · `situer→locate` ·
  `signaux/axes_declares→declared_signals/axes` · `chemin→path`
- `sources`/`containers`/`modules` : `ecrire→write` · `Rapport→Report` (champ `pertes→losses`) ·
  `Contexte→Context` · `Entree→Entry` · `Schema*→*Schema` · `enregistrer_schema→register_schema` ·
  `valeur_sql→sql_value` · `modules_lecteurs→reader_modules` · `temps_en_secondes→seconds_from` ·
  `mesurer→measure` (+ le site `doc_facts`)

**Ce qui ne bouge PAS** : les tests (méthodes françaises = la règle), la prose/docstrings
(français), les champs canoniques (`time`/`start`/`end` — déjà anglais, glu inter-mondes), la
famille driving/geometry/kinematics/io (déjà anglaise), les données déjà écrites.

### 14.3 Le plan — quatre passes commitées séparément, instances STOPPÉES

| passe | contenu | pourquoi cet ordre |
|---|---|---|
| **A** | les 17 clés de catalogue + ~16 clés ParamSpec + noms d'enveloppes | c'est le **contrat sérialisable** — le seul dont le coût CROÎT avec le temps |
| **B** | cœur (`core/*`) : ~50 fonctions + 3 renommages de module | le plus gros volume, purement interne |
| **C** | classes + `sources`/`containers`/`dataset`/`vue`/`frames` + `origin` (tolérance de lecture) | dépend de B |
| **D** | `doc_facts.mesurer`, références VIVES des `.md` (le Journal reste tel quel — c'est de l'histoire), garde `NomAbandonneTest` étendue aux anciens noms + clés | referme la porte |

**Garde-fous** (tous éprouvés) : renommage AST, jamais textuel (14.1.4) · *« un renommage ne
casse rien, il rend FAUX »* → grep des **COMPARAISONS** de chaînes (clés, `origin`) · garde de
renommage datée type D17 · **645 tests comme filet** + `manage.py check` + vérification **sur
HEAD en worktree isolé** après chaque passe.

**Coût estimé : une journée dédiée** (A ≈ 1-2 h · B ≈ une demi-journée · C ≈ 2-3 h · D ≈ 1-2 h),
instances stoppées (accord de Fabien acquis). Le report, lui, coûte : chaque protocole réel écrit
avant la passe A devra être migré ou aliasé.

### 14.5 ✅ EXÉCUTÉE le 2026-08-26 — GO de Fabien le jour même, trois commits

**~2 870 renommages** par moteur **tokenisé** (seuls les NAME bougent — la prose française des
docstrings n'a pas bougé d'un mot, ses références backtickées aux identifiants ont suivi) + 5
modules `git mv` (`values.py`, `naming.py`, `view.py`, `tests_naming.py`, `tests_view.py`).
Passe A = contrat sérialisé (`refactor(data)` e7b2e8ce) · passes B-C = symboles/classes/modules
(2cdf366c) · passe D = garde + docs.

**Surfaces de contrat DÉCOUVERTES en exécutant** (absentes de la table §14.2, migrées avec elle) :
les **jetons d'opérateurs** (`contains`, `startswith`… — les `libelle` restent français, UI), les
**jetons de statistiques** (`mean`, `stddev`… + suffixes de colonnes dérivées), les **clés du dict
`Condition`** (`key`/`field`/`operator`/`value`/`stream`), les **clés de gestes** et les **clés de
ports** (`gestures`/`starts`/`ends`). ⭐ La sérialisation du `Protocol` (éthogramme) était **déjà
anglaise** — rien à migrer côté fichiers de protocole.

**Trois collisions réelles, résolues à la main** — le genre que seuls les tests voient :
① `dataset.load` (ex-`charger`) **s'appelait lui-même** au lieu de `sources.load` → alias
`load_source` commenté (deux étages : un DATASET vs UN fichier) ; ② la **frontière substrat**
d'`apps.py` (`Registre(cle=…)`, `Resultat` — l'API française de `registries.py`, dette connue)
restaurée avec alias : elle se renommera AVEC le substrat, jamais depuis le monde ; ③ le `libelle`
UI `'contient'`, homonyme exact de l'ancien jeton — exempté de la garde avec son pourquoi.

**La garde** : `core/tests_naming.py::NomsAbandonnesD28Test` — ~120 identifiants + ~35
chaînes-contrat interdits, **tokenisée** (le texte brut aurait accusé la prose française, cf.
garde D17 qui, elle, peut se le permettre : `wrec` n'est pas un mot). Dérogations nominatives :
la garde elle-même, `apps.py` (frontière substrat).

**Vérifié** : `wama_data` **651** tests (dont la garde) · `wama.common` + `wama_lab` **249** —
cam_analyzer et face_analyzer intacts, comme §14.4 le prédisait · `check_docs` : **0 référence
nouvelle cassée** (les 5 CASSÉ sont la baseline `_result_tabs.html` antérieure) · `doc_facts`
aligné (`measure`, clés `name`/`stream`) et §0 régénéré · HEAD vérifié en worktree isolé.

### 14.4 REVÉRIFICATION wama_lab — demandée par Fabien avant le GO (2026-08-26)

> *« Il ne faut surtout pas casser wama_lab avec face_analyzer et cam_analyzer. »* Passe de
> revérification sur **TOUS les canaux de couplage**, pas seulement les imports.

| canal vérifié | résultat |
|---|---|
| `face_analyzer` → `wama_data` (tous types de fichiers) | **ZÉRO occurrence** — l'app ne touche pas le monde Data |
| `cam_analyzer` imports Python | 6 sites, **14 symboles, TOUS de la famille anglaise** (`parse_rec`, `sky_mask_at`, `deproject_depth`, `fit_plane_ransac`, `collision_detection`, `extrapolate_*`, `track_position_spread`, `point_traj_to_shape`, `trajectory_offset`…) — **aucun n'est dans la table §14.2** |
| ⚠ **kwargs des sites d'appel** (le canal subtil : un paramètre français renommé casserait un appel par mot-clé) | tous anglais — `mask`, `max_points`, `z_min/z_max`, `min_inliers`, `radius_m`, `max_pet_steps`, `min_obs` |
| clés de catalogue françaises dans `wama_lab` (py, js, html) | **zéro** |
| JS / templates / `.md` du Lab | 1 commentaire JS + prose de doc — non cassants |
| `function_specs.py` (déclaration au catalogue commun) | ne référence pas `wama_data` |
| sens inverse `wama_data` → `wama_lab` | prose seulement (docstrings, un test générique des mondes) |
| outillage hors mondes (`tools/`, `patches/`, `scripts/`, hooks) | zéro référence |

**Verdict : la passe ne touche formellement PAS `wama_lab`.** Le monde Lab consomme exclusivement
la famille anglaise — qui ne bouge pas — et jusque dans ses kwargs.

⚠ **Trois points de contact SUBSTRAT trouvés par cette même passe** (à intégrer, sinon ils
casseraient en silence… sauf le premier, que l'instrument attraperait) :

1. `mecanismes.py` — les **domiciles** `data_vue → wama_data/vue.py` et `data_noms →
   wama_data/core/noms.py` : à mettre à jour AVEC les renommages de modules (passes B/C) +
   régénérer `WAMA_MECANISMES.md`. Filet : `doc_facts --check` signale un domicile disparu.
2. `tests_nightly.py:60-61` — trois chemins de modules de test **en dur** (dont
   `wama_data.tests_vue`) : à mettre à jour avec `tests_vue.py → tests_view.py`.
3. `doc_facts.py:314` — `from wama_data.modules import mesurer` (déjà au plan, passe D).
   Le runner nocturne, lui, **découvre** les suites dynamiquement — sûr par construction.

---

## 10. Décisions en attente

| # | question | qui tranche |
|---|---|---|
| D1 | domicile du référentiel temporel : `wama_data/` ou module dédié ? | après passe 1 |
| D2 | le magneto : une brique à deux chromes, ou brique + plugin distincts ? | après passe 2 |
| ~~D3~~ | ✅ **TRANCHÉE 2026-08-23 (§9quater.2)** — `.trip` reste un format **importé, en lecture seule** ; WAMA a un conteneur **natif distinct**. ⚠ D3 a tranché le PRINCIPE et proposé le nom `.wrec` ; **le nom est repris par D17** (2026-08-24) — lire les deux ensemble, D3 seule est périmée sur ce point. `TripReader` garde son nom : il lit le format de BIND, pas le nôtre | Fabien |
| D4 | quels 2-3 plugins écrire en premier (pour extraire la vue déclarative ensuite) ? | après passe 3 |
| D5 | Recorder temps réel (LSL/RTMaps/ROS) : dans le périmètre v1 ou différé ? | Fabien |
| D6 | reprendre le « **jamais d'interpolation** » de BIND ? (position pressentie : oui pour la VALEUR, interpolation autorisée en option d'AFFICHAGE seulement) | Fabien, §3bis |
| D7 | le curseur appartient-il au **jeu de données** (choix BIND : un trip = une horloge) ou à la **session** (plusieurs sources hétérogènes) ? | après passe 2 |
| D8 | type « **intervalle** » dans `data_types.py` : nouveau `DataType.INTERVALS`, ou sous-type d'`EVENTS` avec durée ? (sans lui, pas de Segmenter ni de Calculator) | après passe 3 |
| ~~D9~~ | ✅ **TRANCHÉE 2026-08-23 (§9quater.3)** — `time` / `start` / `end`, et `timecode` reste un **alias d'entrée** (`tabular.py:23`). Ce n'était pas un arbitrage : `timecode` est **déjà pris dans WAMA** au sens AV positionnel (`mm:ss`, une CHAÎNE — Transcriber), là où BIND en fait un flottant en secondes | mesure |
| D10 | **rééchantillonnage : jamais systématique** (Fabien, 20/08) — mais **TROIS opérations distinctes**, cf. §6.6 : le **ré-horodatage** par fréquence théorique est ✅ à l'import et par flux (il n'interpole pas) ; le **rééchantillonnage sur grille commune** est ❌ ; le **rééchantillonnage à la demande vers une table annexe** est ✅ en option. Le **pas de temps variable est une capacité à porter**, pas un défaut à corriger. ✅ **RESTE CLOS le 2026-08-23 (§9quater.4)** : la table annexe vit **dans le même `.wdat`** que ses sources, porte sa **provenance en méta** (jamais dans son nom — D11), se nomme par règle dérivée, et n'est **jamais créée implicitement**. Et le défaut recommandé pour croiser deux cadences n'est PAS le rééchantillonnage mais l'**agrégation** (`calcul_par_segment`), qui n'invente aucune valeur | ✅ close |
| D11 | les paramètres de fenêtre d'une situation : **colonnes/métadonnées** (interrogeables) plutôt que dans le NOM de la table comme BIND (`situation_0_15`) ? | ⚠ **MÛRE** — « après A », et A est faite (§9ter.6). Le principe est déjà **appliqué un cran plus bas** par §9quater.4 (le contexte se trace sur la COLONNE) et par la table annexe (provenance en méta, jamais dans le nom). Reste à le ratifier au niveau de la situation elle-même |
| D12 | **alignement par TRIGGERS** (§9bis.6) : où vit l'appariement d'événements entre flux — dans l'Importer, ou comme fonction du catalogue applicable après import ? | avant l'Importer v2 |
| ~~D13~~ | ✅ **TRANCHÉE 2026-08-24 (§9undecies.2)** — **un seul kind `pipeline`, étendu** d'un nœud `function`. Décisif : **un protocole réel traverse les mondes** (« transcris la vidéo, puis segmente autour des mots-clés ») — deux kinds le rendraient inexprimable. La différence app/fonction (job asynchrone vs transformation typée) se traite dans l'**exécuteur**, qui dispatche déjà sur `kind` | Fabien |
| ~~D15~~ | ✅ **TRANCHÉE 2026-08-24 par la MESURE** — `Signal.ends` accepte `None`, mais un seul état non refermé rendait le flux **entier ininterrogeable** (`TypeError` dans `containing`/`overlapping`), et `frames.signal_depuis_frame` en produisait. Corrigé : `Signal._fin()` vaut `+∞` **pour les comparaisons**, `end_at()`/`duration_at()` rendent toujours `None`. ⚠ La convention existait déjà dans `segmentation.py` sans avoir été portée | mesure |
| D14 | granularité du **script généré** : un fichier plat rejouable, ou un module par fonction + un orchestrateur ? (impacte la lisibilité pour un relecteur académique) — ⚠ **le CADRE est posé (§9undecies.3)** : Python est **exact** (le script appelle `FunctionSpec.fn`), et la couverture des autres langages est **par fonction et mesurable** par contre-épreuve, pas « squelette par principe ». Reste la seule question de forme | avant l'Exporter de pipeline |
| D16 | **conflit d'ingest inter-instances** (§9undecies.4) : `ingest()` écrase `body` en silence sur `kind+key` existant. Comparer et montrer — mais **où** ? garde dans `ingest()` (protège tous les appelants, change un contrat existant) ou dans l'import depuis copie projetée seul ? | avant le 1ᵉʳ échange dev↔prod |
| ~~D17~~ | ✅ **TRANCHÉE 2026-08-24 (§9quater.2)** — le conteneur natif s'appelle **`.wdat`**, et non `.wrec` comme D3 l'avait proposé. ⚠⚠ **Le critère qui a tué `.trip` tue aussi `.wrec`** : « rec » présuppose une session d'ENREGISTREMENT là où le monde doit tenir des données temporelles sans aucune acquisition. Retenir le critère pour l'un et l'écarter pour l'autre aurait été défendre un choix parce qu'il était le nôtre. Second motif : `.wrec` était à **une lettre de `.rec`**, qu'on lit. Écartés aussi — `.wds` (écrase deux étages : le kind `dataset` est l'EXPÉRIMENTATION, le fichier est un ESSAI) et `.wdb` (nomme la base Postgres de WAMA — un nom faux par COLLISION est pire qu'un nom faux par connotation). ⭐ Coût réel : **le schéma n'a pas bougé d'un octet**, les tables du catalogue s'appelaient déjà `Wama*`. ⭐ **Suite 2026-08-25** : `.wds` a depuis reçu un domicile légitime **un étage AU-DESSUS** — le bundle corpus (**D26**) | Fabien |
| D18 | **routes du Converter** (§11) : par le PIVOT par défaut (2N adaptateurs au lieu de N(N−1)), ou route DIRECTE déclarée par paire ? ⚠ Le pivot est **prouvé lossy** pour `.rec` — il porte DEUX temps (émission + horodatage) et un index d'échantillon, `Signal.times` n'en garde qu'un. Et `trip2rec` de BIND l'atteste : il écrit le **même timecode aux deux places** parce que `.trip` avait déjà perdu l'autre. Quelle que soit la route, la PERTE doit être annoncée (`Rapport.pertes` existe) | avant le 1ᵉʳ Converter |
| D19 | **nom du « Cataloger »** (§11) : le mot est **déjà pris deux fois** — `wama/common/catalog/` (glu inter-mondes) et le « catalogue de fonctions » que son propre écran affiche en bas. Et si le schéma se lit bien, **le Cataloger est l'INTERFACE du Connector** (même motif que « l'Explorer est l'interface du Calculator ») — auquel cas ce n'est pas un module de plus | avant l'UI |
| ~~D20~~ | ✅ **CLOSE le 2026-08-25 PAR LA LECTURE DU CODE — les `axes[]` vont dans le `dataset`, et la question n'aurait pas dû être posée.** ⚠ Je l'avais formulée en ayant lu `builtin/dataset.py` **mais pas `builtin/project.py`** ; ce dernier y répond en toutes lettres : *« Ce qui décrit les DONNÉES d'une expérimentation, c'est le kind `dataset` — objet distinct »*, le kind `project` ne portant que `owner_org`, `lead`, `members` + rôles, c'est-à-dire **l'unité de DROITS** (« les permissions étaient posées à plusieurs niveaux […] et AUCUN ne couvrait un projet de recherche transversalement »). Second motif, dirimant : `project` est **`extract`** (généré depuis le modèle `Project` en base) — y ajouter des axes exigerait d'étendre le modèle Django, là où `dataset` est **autoré**. Et la prémisse « redéclarer le plan à chaque passation » était fausse : **un manifeste `dataset` = une expérimentation entière** (§13.0), pas une passation | ✅ close |
| D21 | **les coordonnées dans le `.wdat`** — ⚠ **REFORMULÉE le 2026-08-25 après relecture (§13.5bis)** : « quelle table ? » n'est plus la question, **c'est `WamaMeta (key, value)`**, qui existe déjà et reprend `MetaTripDatas`+`MetaParticipantDatas` de `.trip` fusionnées. La question restante est le **NOMMAGE DES CLÉS** : `WamaMeta` porte déjà des méta techniques (`schema_version`), donc une clé `participant` à plat y côtoierait une clé de format. Préfixe d'espace de noms (`axe.participant`) — **rendu nécessaire par la fusion**, pas optionnel. Reste à ratifier la forme exacte du préfixe | avec l'Importer v2 |
| D22 | **forme du patron** (§13.5 mode 1) : glob nommé `{groupe}/{participant}/…` ou expression régulière ? Arbitrage **lisibilité pour un chercheur** contre **pouvoir d'expression** sur des arbres sales | avant l'UI d'import |
| D23 | **les dossiers `Data` / `Raw data`** à côté des datasets (§13.1) : exclusion déclarée dans `source.layout`, ou rattachement au kind `project` ? ⚠ Ils peuvent contenir **malgré tout** le fichier de travail `.trip`/`.wdat` — donc « exclure par nom de dossier » est faux | avant le 1ᵉʳ manifeste `dataset` réel |
| D24 | **DEUX rôles ou TROIS ?** (§13.3ter) — SDMX n'en a pas pour « l'unité d'observation » : chez lui **toutes** les dimensions sont des dimensions, et l'unité est simplement **la plus fine**. D'où une simplification possible : `factor` / `attribute` seulement, + un marqueur **`grain: true`** sur le facteur qui porte l'unité d'observation. ⚠ Contre-argument : l'unité d'observation porte l'**indépendance statistique**, ce qui n'est pas une propriété comme une autre — la marquer par un rôle la rend impossible à oublier, un booléen se néglige. ⭐ Le vrai départage est empirique : **regarder si une fonction d'analyse a besoin de la distinguer par son RÔLE ou par une PROPRIÉTÉ** | avant la 1ʳᵉ fonction qui lit les axes |
| D32 | *(ex-D27 — voir la note de collision sous la table)* **`present_dans` et l'ÉGALITÉ des bornes** — ⚠ **ÉNONCÉ RESSERRÉ le 2026-08-26 (objection de Fabien).** J'avais écrit « le défaut contredit sa docstring » : trop fort, et à côté. Fabien : *« c'est normal que `strict=True`, on sous-segmente un segment, on ne peut pas avoir une borne du sous-segment qui sort du segment qui le contient »* — **exact, et ce n'est pas ce que `strict` arbitre**. `strict=True` teste `s['start'] > d and fin < f`, c'est-à-dire des bornes **strictement intérieures** : il rejette donc l'**ÉGALITÉ**, pas le débordement. Une sous-situation qui commence *exactement* quand sa mère commence (« les 10 premières secondes du suivi ») est **INCLUSE** et pourtant écartée. Démonstration limite : `present_dans(X, X)` rend **∅**. La docstring prévoit déjà le cas (`False` = « quand la référence a été produite par le même découpage ») — reste à décider **qui** le passe : le défaut, ou l'appelant hiérarchique | avant le 1ᵉʳ découpage hiérarchique |
| ~~D33~~ | *(ex-D28 — voir la note de collision sous la table)* ✅ **TRANCHÉE 2026-08-26 par Fabien** — la couture est un **AGRÉGATEUR `.wdat` → `.wdat`**, pas un lecteur multi-fichiers ni `.wds`. Plusieurs conteneurs sont **fusionnés en un seul** (ex. des tranches de 30 min en fichiers de 6 h), et le résultat est un `.wdat` ordinaire que tout le reste sait déjà lire. ⭐ Décisif : **`.wds` est un ENGLOBEUR de `.wdat` (D26), pas un fusionneur** — les deux répondent à des besoins différents et les confondre aurait donné un format à deux natures, ce que D26 interdit explicitement. Le moteur d'écriture existe déjà (§9duodecies, un moteur/deux schémas) ; restent la granularité de fusion (paramètre) et l'**audit de la fusion** (`Rapport.pertes`, comme toute projection) | ✅ close |
| ~~D31~~ | ✅ **CLOSE le 2026-08-26 (§13.18), option A** — `probe()` expose le **nom de catalogue**, la famille restant portée comme donnée (`SignalMeta.data_type`, déjà le cas). Le défaut : `probe()` listait `data_BIOPAC_MP150` là où `read()` rend `BIOPAC_MP150`, et `load(streams=['CADISP'])` levait quand `['event_CADISP']` passait — **l'identifiant pour DEMANDER et celui pour RETROUVER n'étaient pas le même**. Tranché **par la mesure** : 28 flux, 28 noms distincts, **aucune collision**. Trois précautions — la forme préfixée **reste acceptée** (un correctif qui casse ses appelants n'en est pas un), l'index reste `{nom: [tables]}` pour rendre une collision **détectable** plutôt que supposée impossible, et `read()` est inchangé. ⚠ **Et j'avais surestimé le coût** (« 73 tests ») : **un seul** est tombé, celui qui attestait l'ancien contrat. Manifeste inchangé ⇒ `conforme: True` sur le fichier réel | ✅ close |
| D34 | **garde mécanique contre les numéros de décision dupliqués** (note de collision ci-dessous) : deux instances ont ouvert D27 et D28 le même jour sur des sujets différents, et **rien n'a sonné** — ni `check_docs` ni `doc_facts` ne regardent l'unicité d'une clé dans un tableau. Quelques lignes dans `check_docs` (relever `^\| ~*D\d+`, échouer sur un doublon) suffiraient. ⚠ À généraliser aux autres registres numérotés du dépôt avant qu'ils n'aient le même problème | avant la prochaine session parallèle |
| D30 | **nature personnelle d'une unité d'observation** (§13.16) : `observation` doit-il déclarer si son unité est une **personne physique**, et un axe s'il est **identifiant direct / pseudonyme / anonyme** ? ⚠ Mesuré au §13.15 : `participant_id = 'Passation_01'` est un **pseudonyme**, fait qu'un registre RGPD veut voir écrit et qu'aucune relecture ultérieure ne pourra reconstituer. Gratuit maintenant, irrattrapable en aval. Le reste du registre (base légale, DPIA, conservation) reste **hors manifeste** | avec le 1ᵉʳ corpus à données personnelles |
| D29 | ⚠⚠ **`source` existe à DEUX étages avec DEUX vocabulaires** (§13.15) : enveloppe = `builtin\|library\|folder\|extract` (d'où vient le MANIFESTE), corps `dataset` = `rtmaps\|lsl\|csv\|…` (d'où viennent les DONNÉES). Même nom, sens disjoints, un seul fichier — même famille que §9decies.3, mais structurelle cette fois. Renommer le champ du corps (`data_source` ?), ou documenter la superposition et s'y tenir ? ⚠ Trouvé **en écrivant le premier manifeste**, pas en relisant le code | avant le 2ᵉ manifeste `dataset` |
| D25 | **`universe` / population** (DDI, §13.3ter) — le corpus déclare ce qu'il **contient** ; il ne déclare pas ce qu'il est censé **couvrir** (« conducteurs de 65-75 ans titulaires du permis depuis plus de 10 ans »). DDI porte les deux. ⚠ Sans lui, l'écart mesurable est « déclaré vs trouvé » ; avec lui il devient aussi « **visé** vs trouvé » — c'est-à-dire la couverture réelle d'une étude, qui est une question de relecture d'article. À arbitrer : champ du kind `dataset`, ou hors périmètre WAMA | après le 1ᵉʳ manifeste réel |
| ~~D27~~ | ✅ **TRANCHÉE ET LIVRÉE le 2026-08-26** (validation de Fabien : « on peut déjà s'occuper de la conversion des unités avec pint ») — **la donnée reste dans SON unité** (`WamaVariables.unit`, `ParamSpec.unit`) ; la conversion vit à la **PRÉSENTATION seule**, pilotée par une préférence utilisateur (métrique/impérial) ; l'**export** reste par défaut dans l'unité de la donnée, conversion possible mais **TRACÉE**. **Brique livrée** : `wama/common/utils/units.py` (**pint 0.25.3**, installé les 2 venvs + `requirements.txt` le même jour — règle maison), au registre des mécanismes (`units_display`), 13 tests. ⭐ Résolution par **DIMENSION** (toute unité de vitesse → mph en impérial), unité inconnue **reste affichable**, unité inconnue en conversion **refusée** (une valeur sous une étiquette fausse est pire qu'une erreur), un trou traverse en trou. Le test-clé est l'**OFFSET** °C→°F — ce qu'une table de facteurs maison rendrait faux en silence. ⏳ Reste au moment des surfaces : le champ de **préférence au profil**, le câblage preview/graphes/inspecteur, l'en-tête d'export converti | ✅ close |
| ~~D28~~ | ✅ **TRANCHÉE ET EXÉCUTÉE le 2026-08-26** (GO de Fabien, instances stoppées) — **l'API du monde Data est passée à l'anglais** : ~2 870 renommages tokenisés en 3 commits, 5 modules `git mv`, garde `NomsAbandonnesD28Test`, 651 + 249 tests au vert, 0 référence doc nouvelle cassée, Lab intact. **Détail complet : §14.5** ; la cartographie et la méthode restent en §14.1-14.4. Historique de la décision — **Normalisation du nommage de l'API du monde Data** (relevé de Fabien 26/08 : « du français mélangé à de l'anglais — seuls les tests acceptent le français »). **Mesuré** : le cœur de `wama_data` est français de bout en bout (~50 fonctions publiques — `autour`, `jonction`, `etats`, `exporter`, `rejouer`…) et le **CATALOGUE est SPLITTÉ** — famille temporal/geo/coding **française** (`segment_*`, `calcul_*`, `codage_*`, `distance_a_point`) contre famille driving/geometry **anglaise** (`trajectory_offset`, `brake_detection`, `gps_map_match`, `depth_*`, `ign_*`). La règle du dépôt (CLAUDE.md, 22/08 : **identifiant importé = anglais**) n'a pas été appliquée au monde Data, construit les mêmes jours. **Recommandation : migrer vers l'anglais en PASSE DÉDIÉE, maintenant que c'est bon marché** — `externe: 0` (0 views, 0 tool_api), et ⚠ **les clés de catalogue se SÉRIALISENT dans les protocoles** : chaque protocole rejouable écrit d'ici là renchérit la migration. Garde-fous obligatoires : ⚠ **coordination multi-instances** (l'autre instance travaille dans `wama_data` — partitionner), garde de renommage type `NomAbandonneTest` (D17), et « *un renommage ne casse rien, il rend FAUX* » → grepper les COMPARAISONS. ⭐ **Cartographie + coût MESURÉS le 26/08 → §14** (~124 symboles, ~1 730 occ py, consommateurs externes DÉJÀ anglais sauf `mesurer`, 0 clé sérialisée — table de correspondance à valider, 4 passes, ~1 journée, Fabien stoppe les autres instances pendant la passe) | Fabien (GO + table §14.2) |
| ~~D26~~ | ✅ **TRANCHÉE 2026-08-25 — `.wds` est RÉSERVÉ au bundle CORPUS-niveau.** L'objet qui EST un « WAMA Data Set » vit **un étage AU-DESSUS** du `.wdat` : D17 avait écarté `.wds` pour la FEUILLE (un essai), pas pour l'ARBRE. Contenu = **un batch de `.wdat`** + métas du corpus + manifeste `dataset` + protocoles ; **encodage pressenti : HDF5** (hiérarchique — un groupe par essai ; interop MATLAB/h5py/R ; Fabien a prototypé `.trip`→HDF5, faisabilité attestée) ; **exportable depuis la card mère du batch, réimportable EN BATCH** (§11.8 ⑧). ⚠ Deux conditions avant d'écrire une ligne : ① la projection SQLite→HDF5 **s'audite** (`Rapport.pertes`, §9duodecies.5 — raw + protocole + gestes doivent survivre à l'aller-retour, sinon le réimport ment) ; ② **une seule NATURE** — « batch de `.wdat` » décrit le CONTENU, HDF5 l'ENCODAGE ; pas une archive zip d'un côté et un export HDF5 de l'autre. Enrichit **Exporter** (geste corpus, card mère) et **Converter** (route fichier-à-fichier `.trip`/`.wdat`→HDF5) — deux modules, deux granularités, pas de doublon | Fabien |

---

> ### ⚠⚠ COLLISION DE NUMÉROTATION — D27 et D28 ont désigné DEUX décisions chacun (2026-08-26)
>
> Deux instances ont ouvert des décisions **le même jour, dans le même tableau**, sans se voir :
>
> | numéro | décision A (ouverte en premier) | décision B (écrite ensuite) |
> |---|---|---|
> | **D27** | `present_dans` et l'égalité des bornes → **renumérotée D32** | unités & conversion (pint) — **gardée** |
> | **D28** | agrégateur `.wdat` → `.wdat` → **renumérotée D33** | nommage de l'API du monde Data — **gardée** |
>
> **Ce sont les décisions A qui bougent**, bien qu'écrites en premier : les B sont référencées par
> du travail encore dans l'arbre, et déplacer un numéro sous les pieds de quelqu'un coûte plus cher
> que d'en déplacer un déjà commité. Les messages de commit `a3bebd9a` et `8b9a8ea9` citent encore
> D27/D28 au sens A — **cette table est la carte de renvoi**, un historique ne se réécrit pas.
>
> ⚠ **La leçon vaut au-delà de ce cas** : un registre à numérotation manuelle et à écriture
> concurrente **perd silencieusement une entrée** — la seconde écrase la première sans qu'aucun
> contrôle ne sonne. Ni `check_docs` ni `doc_facts` ne voient un doublon de clé dans un tableau.
> C'est exactement le motif « une brique sans consommateur » appliqué à la documentation. Un garde
> mécanique (numéro dupliqué = échec) coûterait quelques lignes ; **⇒ D34**.

## Journal

- **2026-08-25** — **l'UI du monde Data (§11.8) : le Data Analyzer HÉRITE de la file Médias — et `.wds` trouve son étage (D26).**
  - Le point de départ de Fabien était « une UI différente, sur la base de BIND_GUI » ; la
    conclusion est l'inverse : un `.wdat` = une **card**, les modules = des **surfaces**
    (modale légère | page dédiée lourde — précédent Transcriber) ouvertes depuis les actions de
    card, et tout l'existant Médias (densités, pile, volets, inspecteur) est hérité. Détail §11.8.
  - ⚠ **Ma première correspondance BIND↔WAMA était FAUSSE** (Liste→file) : la file WAMA est
    **CURATÉE** — Liste = l'explorateur (dossier connecté), Sélection = la file/le batch. Corrigée
    par Fabien. ⭐ Et le tri/filtrage de l'explorateur, pour le monde Data, est un **filtrage par
    AXES** (§13) : créer un batch = un group-by sur un axe — le rangement du §13 paie ici.
  - ⭐ **La promotion fille↔mère (proposition de Fabien) REMPLACE la « card de référence »** :
    elle réutilise l'héritage mère→filles existant, rend n'importe quelle card promouvable (A/B
    en parallèle), et bénéficie aux DEUX mondes → `MODES_QUEUE_UX §5ter`. Charge utile déclarée :
    params (Médias) / **protocole** §9undecies (Data) — et le studio est le **2ᵉ éditeur du même
    objet** (une représentation, deux éditeurs).
  - **Deux affirmations vraies à des étages différents ne se contredisent pas** : « l'Explorer est
    l'interface du Calculator » parle des MOTEURS, « les modules sont des modales/pages depuis la
    card » parle de l'UI — la surface Explorer d'une card reste motorisée par le Calculator.
    (Même famille que « deux granularités sous un mot » : avant de voir une contradiction, vérifier
    que les deux phrases parlent du même étage.)
  - **D26 close** : `.wds` réservé au **bundle corpus** (batch de `.wdat`, card mère → export,
    réimport en batch), encodage pressenti **HDF5** (prototype `.trip`→HDF5 de Fabien). L'extension
    que D17 avait écartée pour la FEUILLE reçoit l'ARBRE. Conditions : projection **auditée**
    (`Rapport.pertes`), une seule nature (contenu ≠ encodage).

- **2026-08-24** — **le point d'entrée, le lecteur `.rec`, et le PROTOCOLE.**
  - §9octies (le manifeste `dataset` devient exécutable), §9nonies (la famille d'un flux portée
    comme donnée), §9decies (G1 fermé — et il n'était pas où on le disait), puis le **lecteur
    RTMaps `.rec`** (troisième capacité d'import, `504 → 534` tests) : premier format **streamé**,
    et il **s'est enregistré sans qu'on touche au moteur** — G1 a payé le jour même.
  - **D15 close par la mesure**, trouvée en répondant à une question de Fabien (« que signifie
    segment ouvert ? »). ⚠ **La question a suffi à exposer un bug réel** introduit par mon propre
    pont la veille : un état non refermé rendait le flux entier ininterrogeable. **Mon test
    vérifiait que la valeur SURVIT, jamais qu'on puisse l'INTERROGER** — un test de stockage n'est
    pas un test d'usage. Et la convention existait déjà **deux fichiers plus loin**
    (`segmentation.py`), sans avoir été portée : **sixième occurrence** en deux jours du motif « le
    fait est établi ailleurs dans le dépôt et n'est pas relié à sa conséquence ».
  - **§9undecies — le protocole**, issu du même échange. **D13 close** (un seul kind `pipeline`
    étendu ; décisif : un protocole réel traverse les mondes), la **copie projetée** actée
    (lecture seule + estampille, journal qui/quand, semis inter-instances par `ingest()`), et
    **D16 ouverte** (`ingest()` écrase `body` en silence).
  - ⚠ **Et une borne que j'avais reprise SANS LA MESURER.** J'ai étendu à tous les langages la
    restriction « squelette + contrat » que §9bis ne posait que pour MATLAB, puis je l'ai défendue.
    Fabien a demandé pourquoi — **il avait raison** : `FunctionSpec.fn` est le callable réel, donc
    un script Python généré **appelle le même code**, exactement. Le vrai critère n'est pas le
    langage mais « la cible peut-elle atteindre l'implémentation ? », et la couverture est **par
    fonction, mesurable par contre-épreuve**. Même famille d'erreur que les trois affirmations de
    §9ter.6 : **une formule reprise d'un document plutôt que confrontée au code** — sauf qu'ici
    elle allait dans l'autre sens, elle rendait le travail plus PETIT qu'il n'est.
  - **§9duodecies — l'ÉCRIVAIN DE CONTENEUR** (`541 → 590` tests). Le monde Data écrit enfin du
    SQLite : un moteur, deux schémas (`.wdat` natif, `.trip` pour BIND), le schéma de l'autre
    **relevé sur la base réelle** avant d'écrire une ligne, et la compatibilité **attestée par
    contre-épreuve** (le lecteur `.trip` relit ce que WAMA écrit). Ce qu'un schéma ne sait pas
    porter est **compté** (`Rapport.pertes`), jamais tu.
  - ⚠ **Deux défauts trouvés par la mesure, dont un dans mon propre récit.** Le lecteur `.trip`
    échouait sur le texte **cp1252** des bases réelles et n'y survivait que parce qu'il ne lit ni
    `MetaEvents` ni `MetaSituations`. Et **une morsure sur six n'a pas mordu — la mienne** :
    `manquant()` ne protégeait rien à l'écriture puisque **SQLite coerce déjà `NaN` en `NULL`**,
    tandis que le vrai trou (`json.dumps([nan])` → `[NaN]`, JSON invalide) n'était couvert par
    personne. *Un test de stockage n'est pas un test d'usage* — la leçon de la veille, appliquée
    à moi le lendemain.
  - **§9terdecies — le LECTEUR `.wdat`** (`590 → 603` tests, lecteurs 3 → 4). Le format natif
    n'est plus write-only, donc il peut enfin servir de **fichier de travail**. ⚠ Et le second
    lecteur de base a révélé un **socle** : ~120 lignes d'accès SQLite qui ne devaient rien au
    format de BIND vivaient dans `TripReader` (qui passe de ~300 à 171 lignes, 73 tests
    inchangés). **Même geste que `containers/` le même jour** — lire et écrire un conteneur posent
    le même problème et il se résout du même côté.

- **2026-08-23** — **portage du Segmenter et de l'Exporter, puis trois décisions de fond.**
  - **Matin** : §9ter.6 A-B-C porté (chaîne conditionnelle en arbre, manques temporels, Exporter
    sur le modèle réel). `wama_data` passe de **198 à 327 tests**. Détail en §9ter.6 E.
  - **La leçon du portage** : sur les **cinq** affirmations de §9ter.6 que la lecture du code
    vivant a pu confronter, **deux étaient fausses** (« BIND offre une liste plate », «
    `data_types.py` sait typer une colonne ») et **une sous-estimait d'un facteur cinq** (un défaut
    des quatre branches d'export, alors qu'il y en a cinq). **Toutes trois dans le même sens :
    elles rendaient le travail plus facile qu'il n'était.** Même famille d'erreur que le pivot
    inexistant qui avait fait reverter le premier Exporter — écrire une spécification depuis un
    schéma et une intuition plutôt que depuis le code. Le corpus était dans le dépôt depuis le début.
  - **Après-midi — §9quater**, issue d'un échange avec Fabien : **D3 close** (conteneur natif
    `.wdat`, `.trip` reste un format importé en lecture seule), **D9 close** par la mesure
    (`time` ; `timecode` est déjà pris au sens AV dans le monde Médias), **le reste de D10 clos**
    (la table annexe vit dans le `.wdat`, provenance en méta, jamais implicite), et surtout **la
    règle de manipulation écrite** : *une nouvelle table SSI la clé temporelle change*.
  - ⚠ **Cette règle n'était pas nouvelle — elle était déjà APPLIQUÉE sans être écrite** : c'est ce
    qui sépare `ENRICHER` de `AGGREGATE` dans les deux modes du Calculator. La consigner l'empêche
    d'être contredite par le prochain module sans que personne ne s'en aperçoive. C'est le second
    cas du jour où une règle vivait dans le code sans exister dans la doctrine.
  - **L'Explorer est l'interface du Calculator**, pas un module de plus : le Calculator est écrit
    et éprouvé (49 tests) sans aucune UI, et l'Explorer est — avec le Connector — le seul module
    **sans blocage déclaré**, donc écrivable immédiatement.

- **2026-08-22** — **le monde sort du substrat.** WAMA Data quitte `wama/common/data/` pour une
  racine `wama_data/`, sœur de `wama/` et `wama_lab/` — cible déjà écrite dans `ROADMAP §18` (« un
  monde = un package frère »), jamais exécutée. La doctrine des MONDES était actée depuis le
  2026-07-20 ; `docs/VISION_STATUS.md` notait même « socle posé (`common/data/`) » comme un état
  normal, ce qui laissait croire que la traduction en arborescence avait été faite.
  - **Où passe la frontière** — seule vraie décision : le registre de fonctions et la taxonomie de
    types RESTENT dans `wama/common/catalog/`. Mesuré, pas déduit : `cam_analyzer/function_specs.py`
    y déclare des fonctions du **Lab**, et les manifestes `function`/`dataset` du substrat en
    dépendent. Les emporter ferait dépendre le Lab et le substrat du monde Data.
  - **Défaut corrigé, et c'est lui qui rendait le déport risqué** : `load_all()` citait
    `wama.common.data` ET `wama_lab.cam_analyzer` **en dur** — le déport l'aurait cassé
    **silencieusement** (catalogue à moitié peuplé, zéro erreur). Chaque monde se déclare désormais
    dans son propre `apps.py:ready()` ; le registre parcourt les apps installées.
  - **Structure** : `core/` (moteur sans Django), `sources/`, `functions/`, `modules.py`.
  - **Vérifié après redémarrage réel de WAMA** : 39 fonctions au catalogue peuplées par le seul
    cycle `ready()` (20 Data + 19 `cam_`), `load_all()` idempotent, les 19 fonctions cam_analyzer
    saines une par une, les 7 imports **différés** de cam_analyzer (invisibles au chargement des
    modules, donc seuls capables de casser en cours de tâche) résolus à la main, 282 connexions de
    chaînage valides, workers Celery avec leurs 15 tâches enregistrées, aucun `.pyc` orphelin sous
    l'ancien chemin, `check_app_conformity` inchangé. 245 tests OK.
  - ⚠ **Sortir Data n'a PAS désengorgé `common/`** (5 107 lignes sur ~39 800, soit 13 % ; les vrais
    blocs sont `utils/` 9 859 et `static/` 8 384) — et ce n'était pas le but. La justification est
    doctrinale : un monde n'est pas un sous-dossier du substrat.

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
