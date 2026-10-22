# WAMA_SCENES_3D.md — Vues 3D : lire le tri et la proximité des éléments

> **Domaine** : les SCÈNES 3D qui montrent les données de WAMA — leurs éléments, ce qui les
> rapproche, ce qui les groupe. ⚠ Ne couvre PAS les médias 3D (objets `.glb`, avatar parlant,
> rendu 3D→2D : `STUDIO_VISION`, `ROADMAP`), qui partagent seulement le moteur vendorisé.
>
> **Statut (2026-10-21)** : CARTOGRAPHIE et démarche, demandées par Fabien. ✅ La **brique commune**
> est livrée le soir même (GO de Fabien, §4) avec ses deux premières scènes de registre, licences et
> modèles ; le reste de la cartographie est une INTENTION (⏳). Chaque fait ci-dessous a été relevé
> dans le code le jour même — un chiffre qui a vieilli se remesure, il ne se recopie pas.

## 0. Pourquoi

Fabien, le 2026-10-21, après avoir présenté WAMA avec la présentation sans la constellation :
*« on m'a dit que c'était un peu compliqué. Je trouve que les visualisations 3D aident à
comprendre et se représenter les choses, voir l'ampleur et l'envergure de ce qu'il y a derrière.
Notamment pour tout le monde transversal. »* — et : *« utiliser la 3D pour représenter le tri des
cards par proximité comme pour les utilisateurs »*, en gardant l'esthétique de la constellation et
des quatre mondes.

Trois principes en découlent, qui valent pour toute scène de ce document :
1. **Une scène est une LECTURE, pas un éditeur.** Elle dit ce qui est proche, groupé, lié, gros ;
   on agit ailleurs (la file, le studio, le catalogue), et un clic y mène.
2. **Les faits viennent de leur brique** — registre, service, modèle — jamais recopiés dans la
   scène (doctrine `AGENTS.md`, point 3 : métadonnée-driven). La distance, elle, se calcule à
   l'écran, parce que ses poids sont des curseurs.
3. **UN moteur** (décision de Fabien, 2026-10-21 : *« une brique commune réutilisable pour
   différents registres »*), pas une page écrite par sujet.

## 1. Ce qui existe (mesuré le 2026-10-21)

| scène | où | données | moteur |
|---|---|---|---|
| Les quatre mondes | présentation, frame `mondes` | déclarées dans la scène | `wama/static/presentation/wama-presentation-3d.js` (`buildWorlds`) |
| Les droits — tous les cas | présentation, frame `acces` | `accounts.permissions.access_cases()` via `presentation_access_cases` | même module (`buildAccess` : une grille `InstancedMesh` profil × rôles × outil) |
| Constellation des utilisateurs | page admin `accounts:user-constellation`, et la frame `constellation` de la présentation (iframe, `?embed=1`) | `wama/accounts/constellation.py` | la brique commune (§4) ; son adaptateur `wama/accounts/static/accounts/js/user-constellation.js` met les faits au contrat et rend le volet d'une personne |
| Licences (C1) ✅ 2026-10-21 | `common:scene` `licenses`, bouton « Constellation » du catalogue des licences | `wama/common/services/license_scene.py` (`license_audit`) | la brique commune, sans adaptateur |
| Modèles (C2) ✅ 2026-10-21 | `common:scene` `models`, bouton de la gestion des modèles | `wama/model_manager/services/model_scene.py` (catalogue visible du demandeur) | la brique commune, sans adaptateur |

Et, hors de ce domaine, la visionneuse d'objets 3D (`wama/common/static/common/js/wama-3d-viewer.js`)
et l'avatar (TalkingHead). Tous lisent three.js 0.180 vendorisé par l'importmap commune
(`wama/common/templates/common/_three_importmap.html`, montée par `base.html`) ; addons présents :
`OrbitControls`, chargeurs GLTF/FBX/DRACO, `BufferGeometryUtils`. **Absents** : rendu de texte 3D
(CSS2D), lignes épaisses, post-traitement — les étiquettes sont du HTML projeté, comme dans les
deux modules ci-dessus.

**Deux limites de la présentation**, relevées pour la demande « côte à côte » de Fabien :
- un SEUL rendu WebGL et une seule scène active à la fois (`attach`/`detach`, le choix de la scène
  est écrit en dur : `worlds` sinon `access`) ;
- la vue d'ensemble existe (touche O, `overview()` de `wama/static/presentation/wama-presentation.js`)
  et montre plusieurs frames ensemble — mais leurs scènes 3D s'y détachent.
Deux scènes vivantes côte à côte demandent donc soit un rendu par emplacement, soit un rendu
partagé découpé en fenêtres (`setScissor`) — c'est l'affaire de la brique commune (§4).

## 2. La grammaire d'une scène de proximité

Ce que la constellation des utilisateurs a fait apparaître, et que toute scène du §3 réemploie :

| élément | ce qu'il porte | exemple (utilisateurs) |
|---|---|---|
| **nœud** (étoile) | un élément ; taille = un volume, couleur = une catégorie | une personne ; activité ; profil |
| **groupe** (sphère translucide) | une appartenance déclarée ; les groupes aux MÊMES membres se fondent | unité de l'annuaire, projet |
| **lien** (arc, particules orientées) | une relation orientée et comptée | un partage, de celui qui partage vers qui reçoit |
| **facteur de distance** (curseur) | ce qui RAPPROCHE deux nœuds, pondérable à l'écran | partages, projets, unités, métiers |
| **satellites, anneau** | ce qu'un nœud porte | apports au catalogue, métiers |
| **volet de détail** | tout ce qu'on sait d'un nœud, ses voisins et POURQUOI | « les plus proches » avec leurs raisons |
| **couches** | ce qu'on montre ou cache | sphères, liens, comptes de test, noms |
| **cœur** | le système, ce qui n'est à personne | « WAMA » |

Les **quatre familles de facteurs** de distance :
- **catégoriel** — même famille, même monde, même type (« même équipe ») ;
- **numérique** — l'écart de deux valeurs (rang de permissivité, VRAM, date) ;
- **relationnel** — un lien compté (partage, `requires`, dépendance, « Envoyer vers ») ;
- **sémantique** — la proximité de deux vecteurs (cosinus d'embeddings).

## 3. La cartographie — ce qui gagnerait à une scène 3D

Légende des données : **prêtes** (une fonction les rend aujourd'hui), **partielles** (une partie
manque, dite), **manquantes**. L'intérêt est la LECTURE qu'elle rend possible et que les pages
actuelles (tableaux, listes) ne donnent pas.

### 3.1 Le monde transversal — « l'ampleur et l'envergure »

| # | scène | nœuds · groupes · liens | facteurs de distance | données | ce qu'elle fait lire |
|---|---|---|---|---|---|
| T1 | **Les mécanismes** | 211 mécanismes (taille = nombre de consommateurs) · groupés par domaine · `depends_on` entre mécanismes, et vers les apps qui les adoptent | dépendance, apps communes, même domaine | **prêtes** : `wama/common/mecanismes.py` (`MECHANISMS`, `Mechanism.depends_on`), `wama/common/services/mecanismes_scan.py` (`adoption_matrix`) | le substrat comme un système : ce qui est central, ce qui est isolé, ce qu'une app emprunte |
| T2 | **La composition** (apps → modèles → librairies, fonctions, pipelines) | tous les manifestes · groupés par monde (`envelope.WORLDS`) · arêtes `requires` | `requires` partagés, même monde | **prêtes** : `wama/common/manifests/ingest.py` (`extract`, `resolve_requires`), clés énumérées par `manifest_export` | « qu'y a-t-il derrière une app », et les briques que plusieurs mondes partagent |
| T3 | **Briques UI ↔ mécanismes ↔ apps** | briques · leurs mécanismes · adoption par app | mécanismes communs, apps adoptantes | **prêtes** : `wama/common/surfaces.py` (`UIBrick.mechanisms`, `adoption`) | l'homogénéité de l'interface, ce qui reste à porter |
| T4 | **Conformité** | apps × critères × facettes F1–F8 · critère → mécanisme | — (grille, comme la scène des droits) | **prêtes** : `logs/conformity_report.json`, `conformity_checker.run_checks` | la forme existante de la scène des droits, réemployée telle quelle |
| T5 | **Tests nocturnes** | scénarios × apps × étages, couleur = verdict | — (grille) | **prêtes** : `nightly_tests.functional_grid` | où ça casse, d'un regard |
| T6 | **Documentation** | docs · renvois doc → code, doc → mécanisme/registre | renvois communs | **partielles** : les arêtes sont calculées DANS `check_docs` sans fonction publique ; `Mechanism.doc`, `Registry.doc` | quelle doc tient quel code |
| T7 | **Sources externes** | sources · groupées par nature (`kind`) | **hébergement** (privé → souverain → tiers) en axe radial, coût | **prêtes** : `wama/common/external_sources.py` (`SOURCES`) | la souveraineté rendue visible |

### 3.2 Les catalogues — une scène par registre

Les 19 registres (`registries.overview()`) n'exposent pas tous leurs éléments : **ont des
`entries`** apps, fonctions, nœuds intégrés, sources externes, formats médias, briques UI, thèmes,
docs ; **n'en ont pas** (il faut lire leur source) modèles, skills, librairies, licences, RAG,
souvenirs, prompts, backends et les trois registres de WAMA Data. C'est le premier trou de la
brique commune (§6).

| # | scène | nœuds · groupes · liens | facteurs de distance | données | lecture |
|---|---|---|---|---|---|
| C1 | **Licences** (l'exemple de Fabien) | licences (taille = éléments couverts) · familles `license_audit.FAMILLES` · satellites = modèles, librairies, médias ; liens app → licences héritées | **rang de permissivité** (permissive → interdite), attribution exigée, apps communes | **prêtes** : `wama/common/services/license_audit.py` (`inventaire`, `qualifier`, `par_app`, `synthese`) | ce qu'on peut faire de WAMA, et ce qu'une app hérite de pire |
| C2 | **Modèles** | `AIModel` (taille = VRAM ou usage) · groupés par type ou par app · liens modèle → moteur → librairie | tâche (`capabilities`), type, VRAM, moteur, famille de licence, local/distant, indice de qualité | **prêtes** (`AIModel.to_dict`, `backend_inventory`) ; ⚠ le MONDE d'un modèle passe par sa `source` → `APP_CATALOG` (aucun champ `world`) | le parc entier : doublons, trous, coût VRAM |
| C3 | **Moteurs et backends** | modèles → moteurs → librairies (arbre) · orphelins en évidence | lignée de classes, tâche | **prêtes** : `backend_inventory` (`inventory`, `orphelins`, `_class_lineage`) | « le modèle porte son moteur, le backend s'en dérive » rendu visible |
| C4 | **Fonctions et types de données** | fonctions (WAMA Data, Lab, apps) · catégorie, monde · arêtes de compatibilité de ports | `can_connect`, types communs, hiérarchie de types (`data_types._SUPERTYPES`) | **prêtes** : `wama/common/catalog/function_catalog.py`, `wama/common/catalog/data_types.py` | ce qu'on peut chaîner avec quoi |
| C5 | **Librairies** | librairies · dépendances (`Library.dependencies`) · apps qui les importent | dépendances, apps communes, licence | **prêtes** : `services/library_index.py` (`librairies_de`, `scan_imports`) | le poids de chaque librairie dans WAMA |
| C6 | **Skills et prompts** | skills · cibles de prompt qui les consomment | app, domaine, cible | **prêtes** : `services/skills_catalog.py`, `PROMPT_TARGETS` | ce que l'IA ajoute à chaque champ |

### 3.3 L'activité — « le tri des cards par proximité »

| # | scène | nœuds · groupes · liens | facteurs de distance | données | lecture |
|---|---|---|---|---|---|
| A1 | **La file en 3D** (toutes apps ou un lot) | cards (taille = durée, couleur = statut) · groupées par lot (`Batch*`) ou par app · liens « Envoyer vers » (`InputProvenance`, `kind='app'`) | **natures** d'entrée/sortie (`APP_CATALOG` `input_types`/`output_types`, `category_of_path`), **proximité sémantique**, **chronologie**, lot, statut | **partielles** — voir la note ci-dessous | trier des centaines de cards à l'œil : ce qui se ressemble, ce qui s'enchaîne |
| A2 | **La chronologie des tâches** | tâches sur un axe du temps (spirale ou couloir par app) · durée = longueur | temps, app, modèle | **prêtes** : `services/journal.py` (`sources`, `entrees`), `ProcessRun` (`started_at`, `finished_at`), `services/calendar.py` (observé, prévu, déclaré) | la charge réelle, les recouvrements GPU, les attentes |
| A3 | **Mémoire et RAG** | fragments et souvenirs · **sphères d'héritage** université → labo → équipe → utilisateur | proximité sémantique (espace texte), portée, sujet | **prêtes** : vecteurs `RagChunk`/`MemoryItem` (`Embedded`), `ScopedVisibility`, `memory/store.py` | ce que l'assistant « sait », et à quel niveau — le RAG par héritage dessiné tel qu'il est voulu |
| A4 | **Médiathèque** | assets · natures (`media_library/natures.py`, `ASSET_NATURES`) · étiquettes | nature, étiquettes, attributs | **partielles** : aucun vecteur sur les assets | retrouver par familiarité |
| A5 | **Utilisateurs** | ✅ livrée | partages, projets, unités, métiers | — | — |

⚠ **Ce qui manque à la proximité sémantique des cards (A1)**, relevé le 2026-10-21 :
- seules les IMAGES des cards ont un vecteur (`MediaVector`, espace `media`, 768 dimensions,
  `wama/common/vectors/media_index.py`) ; ni le texte d'une card (transcription, description), ni
  la vidéo, ni l'audio ; le texte n'est vectorisé que s'il est versé au RAG (espace `text`, 1024) ;
- **deux espaces qui ne se comparent jamais** (`wama/common/vectors/spaces.py`) : une scène mêlant
  images et textes doit garder deux constellations, ou ne rapprocher que par des facteurs non
  sémantiques entre elles ;
- aucune fonction « card voisine d'une card » : `media_index.search` part d'une REQUÊTE texte ;
- aucune réduction de dimension (ni UMAP, ni t-SNE, ni scikit-learn dans le dépôt). Une scène de
  quelques centaines de nœuds n'en a pas besoin : un graphe des k plus proches voisins (cosinus,
  numpy, déjà là) nourrit les forces. Au-delà, une ACP par numpy suffit à placer les graines ;
  UMAP ferait entrer une librairie — par la route `library`, sur décision.

### 3.4 Le Studio — les pipelines en 3D

| # | scène | nœuds · groupes · liens | facteurs | données | lecture |
|---|---|---|---|---|---|
| S1 | **Un pipeline du Studio** | nœuds (app, fonction, source, puits) · ports typés · liens | **profondeur** topologique en axe (`pipeline.topo_order`, `_depths`), type de port | **prêtes** : `StudioPipeline.graph`, `wama/common/manifests/builtin/pipeline.py`, `studio/services/graph_flow.py` | les longues chaînes en couches ; un run (`StudioRun.node_states`) anime le flux ; un LOT = les runs enfants (`StudioRun.parent`) en strates |
| S2 | **Le pipeline d'une app** (l'intérieur d'une card) | process de `APP_PIPELINES` · `depends_on` | profondeur, GPU, sorties | **prêtes** : `wama/common/services/process_pipeline.py` | ce qu'une app fait vraiment, étape par étape |
| S3 | **Tous les pipelines** | pipelines déclarés et enregistrés · nœuds partagés | apps et fonctions communes | **prêtes** | les chaînes qui se ressemblent |

⚠ L'ÉDITION reste 2D (le canvas SVG du Studio, `wama/studio/static/studio/js/wama-studio.js`) :
une vue 3D d'un pipeline est une lecture et un suivi d'exécution, pas un second éditeur.

### 3.5 La présentation

- **Côte à côte** (demande de Fabien) : deux scènes vivantes dans une même vue, pour éviter les
  allers-retours entre slides — par exemple « les droits, tous les cas » à côté des personnes
  réelles. Ce que le moteur actuel ne sait pas faire (§1).
- **Lier deux scènes** : choisir un cas dans la scène des droits allume les comptes qui sont dans
  ce cas. La scène des droits reste telle qu'elle est (décision de Fabien, 2026-10-21) ; seul le
  lien s'ajoute.
- Les scènes T1 (mécanismes) et T2 (composition) sont les meilleures candidates pour la frame
  « Monde Transversal », que Fabien juge la plus difficile à faire comprendre.

### 3.6 Deux pistes ouvertes par Fabien le 2026-10-22

**L'architecture de WAMA en constellation — ⏳ à concevoir avec Fabien avant d'écrire.** Le risque
est la pelote : 212 mécanismes, des dizaines d'apps, des centaines de modèles d'un coup. Principes
retenus (proposés, approuvés comme démarche) :
1. un ZOOM PAR NIVEAUX plutôt qu'une scène unique — les quatre mondes (l'esthétique de la frame
   `mondes` de la présentation) → l'intérieur d'un monde (ses apps et les mécanismes qu'elles
   empruntent) → l'intérieur d'une app (modèles, librairies, fonctions, pipelines, mécanismes) ;
   quelques dizaines d'éléments par niveau ;
2. partir de QUESTIONS — des préréglages (couches, filtres, choix) : « qu'y a-t-il derrière le
   Transcriber ? », « qui utilise cette brique ? », « ce que plusieurs mondes partagent » ;
3. suivre une CHAÎNE entière (amont et aval d'un élément) — la brique n'allume aujourd'hui que les
   voisins directs : c'est le seul ajout de fond.
Données sans recopie : `mecanismes.py` (domaines, `depends_on`), les `requires` des manifestes,
`app_registry` (mondes). Les scènes T1/T2 du §3.1 en sont les briques.

**Les MAINS qui pilotent la 3D à la webcam — ✅ livrées le 2026-10-22** (« en serrant la main puis
en la déplaçant, ça fait tourner ; avec les deux mains, on zoome »). **Une interface GLOBALE**
(décision de Fabien le jour même : *« préparer la petite interface qui permettra de gérer tout ça de
façon globale et universelle dans WAMA, même si pour le moment ça ne s'applique qu'aux scènes 3D —
il vaut mieux déjà centraliser qu'ajouter des boutons dans toutes les scènes »*) :
- une ICÔNE de main dans la barre du haut (`includes/header.html`, `#wamaHandsToggle`), cachée tant
  qu'aucune page ne se déclare cible ; la vignette de la caméra en bas de la fenêtre, avec ses
  RÉGLAGES (⚙ : caméra, champ large 16:9 par défaut — la plupart des webcams recadrent en 4:3 —,
  zoom matériel au plus large quand la caméra l'expose, sensibilité ; gardés dans le navigateur, une
  caméra n'existant que sur sa machine) ; les MAINS VIRTUELLES (squelette) sur toute la page —
  `common/js/wama-hands-ui.js` + `common/css/wama-hands.css` ;
- UNIVERSEL : le pointeur au bout de l'index d'une main ouverte, et le PINCEMENT pouce-index qui
  clique l'élément dessous (bouton, lien, puce, ligne de légende…) ; l'image de la caméra couvre la
  fenêtre en miroir, avec une marge pour atteindre les bords sans sortir du champ ;
- PROPRE à une page, DÉCLARÉ (`registerHandTarget`) : une scène 3D y déclare la rotation (un poing),
  le zoom (deux poings), le clic (l'étoile sous le doigt) et le survol (son infobulle). Les deux
  premières versions (une puce parmi les couches, puis une icône par scène) sont retirées.
⏳ Suite (intention de Fabien) : d'autres pages se déclarent cibles — l'interface est prête.
- MediaPipe Gesture Recognizer (Apache-2.0), exécuté DANS LE NAVIGATEUR (`common/js/wama-hands.js`,
  librairie vendorisée `mediapipe-tasks-vision-1.1.1`, chargée seulement à l'allumage) : aucune
  image de la webcam ne quitte la page ;
- un poing fermé SAISIT la scène comme la souris (image en miroir) ; deux poings qui s'écartent
  rapprochent la caméra ; une main ouverte lâche ; un poing ne se déclare qu'après deux images et ne
  se relâche qu'après quatre (une image mal lue ne fait ni saisir ni lâcher), la paume est lissée ;
- le MODÈLE (`gesture_recognizer.task`, 8 Mo) est une ligne du catalogue
  (`custom:mediapipe-gesture-recognizer`, tâche `hand-gesture`), déclarée par `common/hand_gestures.py`,
  installée par la route (pilote `files`, origine `mediapipe_models`, comme le Face Landmarker) et
  servie au navigateur par `common:hand_model` ; absent, la vignette le dit et renvoie à la gestion
  des modèles ;
- YOLO pose écarté : 17 points du corps entier, pour la main le seul poignet (aucun doigt, donc pas
  de poing), et une exécution serveur qui imposerait d'envoyer chaque image ;
- ⚠ la caméra n'est permise qu'en contexte SÉCURISÉ (https, ou `localhost`) : servi en http par
  l'adresse réseau du serveur, le navigateur la refuse — la vignette le dit ;
- ⚠ **la librairie envoie d'elle-même une télémétrie d'usage à Google** (`POST
  https://odml.pa.googleapis.com/v1/log`, toutes les 60 s, aucune option publique pour la couper) —
  trouvé par le scénario nocturne, qui refuse tout POST. Coupée dans `wama-hands.js` : le temps des
  mains, tout `fetch` hors de l'origine de WAMA reçoit un refus LOCAL (le réseau n'est jamais
  atteint) et le journaliseur de MediaPipe s'arrête au premier refus. À revérifier à chaque montée
  de version de la librairie.
Gardes : `common/tests/tests_hands.py` (déclaration, ligne du catalogue, route du modèle, page, et
l'interprétation des gestes rejouée dans V8 : poing, zoom, pointeur, pincement, marge, champ,
sensibilité) ; étapes « mains » (icône, webcam factice) et « pincement » (clic universel rejoué
par `applyGesture`) du scénario `common.scene.<clé>.ui`.
⚠ Sa ligne du catalogue n'a pas de LICENCE, bien qu'elle soit établie (Apache-2.0, Google) — comme
le Face Landmarker du Face Analyzer : la découverte d'une ligne DÉCLARÉE hors HuggingFace ne pose
pas de licence. Trou du catalogue, préexistant, non ouvert ici ; il fait compter ces deux modèles en
« inconnue » dans l'audit des licences.

## 4. La brique commune — ✅ livrée le 2026-10-21

**Ce qui existe** (mesuré au commit) :
- **le registre des scènes** `wama/common/scenes.py` (`Scene`, `register_scene`) : chaque domaine y
  déclare sa scène dans le `ready()` de son app — couches et leur rôle (`groups`, `links`,
  `satellites`, `nodes`, `names`), facteurs (`relation`, `groups`, `hierarchy`, `jaccard`, `same`,
  `closeness`), sortes de groupes (hiérarchie, fusion des groupes aux mêmes membres, marge,
  attraction), mesures, textes, constantes de mise en espace (`layout`), plafond d'étiquettes
  (`label_limit`). Une déclaration incohérente est refusée à la déclaration ;
- **la brique JS** `wama/common/static/common/js/wama-constellation.js`, importée par son nom
  (`wama/constellation`, importmap commune), et sa feuille `wama-constellation.css` (préfixe `wc-`) ;
- **la page commune** `common/constellation.html` (HUD rendu de la déclaration) et ses routes
  `common:scene` / `common:scene_data` (`wama/common/scene_views.py`), lues sous le droit des
  Registres (`permissions.PATH_APP_MAP`, `common/scenes`) ;
- **le bouton** « Constellation » que reçoit la page d'un registre dont une scène se déclare
  (`wama_catalog.scene_button`, posé par l'en-tête commun `_catalog_header.html`) ;
- **les gardes** : `wama/common/tests/tests_scenes.py`, et un scénario nocturne par scène de la page
  commune (`common.scene.<clé>.ui`, `wama/common/services/ui_smoke_scenes.py`).

**Décision prise en livrant (question 2 du §7)** : un registre de scènes À PART, pas un champ de
`Registry` — les scènes ne projettent pas toutes un registre (utilisateurs, mécanismes, file, journal).
Une scène NOMME le registre qu'elle projette (`registry`), ce qui suffit au bouton de sa page.

**Où une scène lit ses données** (précisé avec Fabien le 2026-10-21, après une explication fausse de
ma part) : dans le REGISTRE lui-même, par la lecture unique que ses autres lecteurs empruntent déjà,
filtrée par les droits du demandeur — jamais par une copie :
- **modèles** : la table `AIModel` EST le registre des modèles ; la scène la lit par
  `AIModel.objects.catalogue_visible_to(user)`, la lecture de la page du catalogue, des sélecteurs
  des apps, de la sélection automatique et de l'assistant (système, publics, les siens, sa portée ;
  tout pour un administrateur). Seul tri propre à la scène : les modèles PROPOSÉS sont écartés
  (`is_proposed`), ils ont leur file à valider ;
- **licences** : registre DÉRIVÉ, sans table (`AIModel`, `Library`, médias, `requires` des apps) ; sa
  lecture unique est `license_audit.inventaire(user)` / `par_app`, celle de la page des licences, qui
  borne les médias d'utilisateur au périmètre visible du demandeur.
La fiche d'un registre dans `wama/common/registries.py` (nom, page, actualisation, compte) DÉCRIT le
catalogue sans en porter les éléments : aucune page ne lit ses données à travers elle, la scène non plus.

**La parité de la constellation des utilisateurs** (exigence de Fabien : *« aucune régression sur
les visuels 3D existants »*) a été MESURÉE, pas supposée : un banc rejoue 56 gestes (page, mode
intégré, téléphone, faits réels et faits synthétiques qui exercent projets, apports, partages à une
portée, comptes inactifs et de test, replis sans WebGL ou sans faits), temps figé
(`requestAnimationFrame` remplacé), faits servis d'un fichier, sur l'ancien code (arbre de travail
de HEAD) et sur le nouveau, captures comparées au pixel et DOM comparé une fois le seul renommage
`uc-` → `wc-` retiré. La scène des droits de la présentation n'est pas touchée.

### La forme proposée le matin (gardée pour la trace)

- **Un module de scène** dans les briques JS communes (`wama/common/static/common/js/`), extrait de
  la constellation des utilisateurs : rendu, fond étoilé, verre des sphères, forces à facteurs
  pondérés, groupes fondus quand leurs membres sont identiques, liens animés, étiquettes projetées,
  couches, curseurs, volet de détail, vol de caméra, mode intégré et noms masqués, couleurs lues
  des jetons de thème (`--wama-pres-*`). La page des utilisateurs en devient le **premier
  consommateur**, sans changement visible : c'est la preuve de l'extraction (parité mesurée par
  son scénario nocturne `accounts.constellation.ui`).
- **Un contrat de données unique** : `{nœuds, groupes, liens, facteurs, légende}` et le détail d'un
  nœud. Chaque source le DÉCLARE au lieu d'écrire une page :
  - un registre, par un champ de plus sur `Registry` (`wama/common/registries.py`), sur le modèle
    de `entries` — et sa page 3D se monte de sa déclaration, avec sa `permission` et son filtre
    de visibilité (`catalogue_visible_q`) ;
  - une source hors registre (mécanismes, file, journal, pipelines), par la même forme déclarée là
    où vit sa donnée.
- **Une page générique** qui monte n'importe quelle scène déclarée, et un **emplacement** (`slot`)
  que la présentation et d'autres pages réemploient — ce qui ouvre le côte à côte.
- **Gardes** : une scène déclarée = un scénario nocturne dérivé (comme `<app>.ui`) ; le budget de
  couleurs à zéro (`tests_theme`) ; le repli sans WebGL.

## 5. Ordre proposé

1. ✅ **Extraire la brique**, la constellation des utilisateurs portée dessus (parité mesurée, §4).
2. ✅ **Licences (C1) puis modèles (C2)** : données prêtes, l'exemple de Fabien, et la preuve du
   contrat « un registre déclare sa scène ».
2bis. ✅ **Filtrer depuis la légende** (demande de Fabien, 2026-10-21 : *« pouvoir filtrer aussi dans la
   constellation, par exemple depuis le panneau droit »* ; forme validée par lui le soir même),
   livré dans la BRIQUE, donc pour toute scène et toute coloration : une ligne d'étoiles de la
   légende se clique pour masquer ou afficher sa catégorie, son « ◎ » (au survol) ne garde qu'elle ;
   une ligne de sphère, quand une seule sphère porte sa couleur, ne garde que les membres de ce
   groupe. Les étoiles filtrées SORTENT et la mise en espace se refait sans elles (comme la couche
   « Comptes de test ») ; le HUD gauche rappelle les filtres (« Sans … » / « Seulement … », chacun
   retirable) et « Tout montrer ». Une scène qui rend sa propre légende emploie la même ligne
   (`api.filterRow`) — la constellation des utilisateurs la porte sur ses profils et ses mondes.
   Garde : l'étape « filtre de la légende » des scénarios `common.scene.<clé>.ui` et
   `accounts.constellation.ui`.
3. **Le transversal (T1, T2)** et sa frame dans la présentation, avec le côte à côte.
4. **La file en 3D (A1)** et la chronologie (A2) : après avoir comblé la proximité card ↔ card
   (§3.3 ⚠).
5. **Le Studio en 3D (S1)** en lecture et en suivi d'exécution.

## 6. Trous mesurés (2026-10-21)

- Registres sans `entries` (modèles, skills, librairies, licences, RAG, souvenirs, prompts,
  backends, et les trois de WAMA Data) : leur scène lit leurs éléments là où le registre les tient
  (sa table, ou la lecture qui le dérive) — ce que font les scènes des licences et des modèles (§4).
- **Deux déclarations en double, relevées à la revérification du 2026-10-21, non ramenées** : la
  couleur d'une FAMILLE de licences (pastilles `.li-r0…6` de `common/licenses.html`, tons
  `--wama-tone-*` qui s'inversent au thème clair, contre `--wc-rank-*` de la scène — teintes
  voisines, pas identiques) et le libellé de l'état d'installation d'un modèle (« Not downloaded »
  dans la gestion des modèles, « Non installé » dans la scène). Domicile à créer : un jeton par
  famille dans le thème, comme `--wama-mm-type-*` pour les types de modèles (ramené le jour même).
- La mise en espace des scènes licences et modèles (`layout`, `label_limit`) est un premier réglage.
- **Capture caméra / micro sans brique commune** (relevé le 2026-10-22 en écrivant les mains) :
  quatre sites appellent `getUserMedia` et refont chacun le contrôle du contexte sécurisé et le
  message de refus — l'enregistrement de la médiathèque (`library-add.js`), l'écoute de l'assistant
  (`wama-assistant-listen.js`), le temps réel du Face Analyzer (son gabarit) et les mains
  (`wama-hands.js`). Domicile à créer dans les briques JS communes ; non fait : il touche trois
  chantiers d'autres sessions.
- Aucun monde sur `AIModel` : il passe par `source` → `APP_CATALOG`.
- Proximité sémantique des cards : images seules, deux espaces séparés, pas de voisinage card ↔
  card, pas de réduction de dimension (§3.3).
- La présentation : un seul rendu, une seule scène active.
- Les renvois de la documentation ne sont pas exposés par une fonction (calculés dans
  `check_docs`).
- Hors domaine, relevé au passage : le face_analyzer charge Chart.js depuis un CDN
  (`wama_lab/face_analyzer/templates/face_analyzer/realtime.html`, `video.html`), contre la règle
  « assets locaux, aucun CDN ».

## 7. À trancher (Fabien)

1. ✅ GO pour la brique commune (§4), et l'ordre du §5 — Fabien, 2026-10-21 : *« commence par les
   licences, puis les modèles »*, sans aucune régression des visuels existants.
2. ✅ Un registre de scènes à part, qui NOMME le registre projeté (tranché en livrant, §4 — à
   revoir si Fabien préfère l'autre forme).
3. La proximité sémantique des cards : vectoriser aussi leur TEXTE (transcriptions, descriptions)
   dans l'espace `text`, et calculer les voisins côté serveur ?
4. Le côte à côte dans la présentation : deux emplacements dans une frame, ou une vue « deux
   frames » ?
