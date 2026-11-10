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
| S1 | **Un pipeline du Studio** | nœuds (app, fonction, source, puits) · ports typés · liens | **profondeur** topologique en axe (`pipeline.topo_order`, `node_depths`), type de port | **prêtes** : `StudioPipeline.graph`, `wama/common/manifests/builtin/pipeline.py`, `studio/services/graph_flow.py` | les longues chaînes en couches ; un run (`StudioRun.node_states`) anime le flux ; un LOT = les runs enfants (`StudioRun.parent`) en strates |
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
  (`mediapipe_models:gesture-recognizer` — `custom:…` jusqu'au 2026-10-27, rangée depuis sous la
  source de son fichier déclaré —, tâche `hand-gesture`), déclarée par `common/hand_gestures.py`,
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

### 3.7 L'interface ENTIÈRE, progressivement 3D et spatiale — veille et pistes (Fabien, 2026-11-10) ⏳

> Rien n'est décidé ni implémenté. Né de la question du choix du domaine
> (`MODES_QUEUE_UX.md §2ter`) : *« on pourrait imaginer que les pages soient des objets 3D à
> facettes, chaque face un domaine, avec un effet de bascule […] et à terme de la manipulation avec
> le mode main »*, puis élargi par Fabien à l'interface complète de WAMA : *« une interface web
> holographique 3D manipulable avec les mains, les gestes, le regard […] comme dans Minority Report
> ou plus récent »*, **à condition de garder une expérience optimale sur tout support (PC, Mac,
> tablette, smartphone, VR), en Responsive Web Design**. Recherche du 2026-11-10 ; les sources sont
> LUES sauf mention. ⚠ Ce fichier couvrait jusqu'ici les vues 3D des DONNÉES ; cette section l'étend
> à l'interface — si le chantier s'ouvre, sa place (ce fichier ou un domaine propre) est à décider,
> avec sa ligne dans la table des domaines d'`AGENTS.md`.

**Ce qui existe déjà dans WAMA** : three.js vendorisé et monté partout (importmap de `base.html`,
pour l'avatar de l'assistant) ; le registre des scènes (§4) ; les MAINS à la webcam, universelles
(pointeur, pincement = clic) et déclarées par page (§3.6) ; les gestes au doigt (`wama-gestures.js`,
`ROADMAP §27`). Rien pour le REGARD, WebXR ou un casque.

**Ce que disent les plateformes spatiales** — elles convergent : *l'œil vise, la main reste basse
et confirme* :
- visionOS (HIG Spatial layout, https://developer.apple.com/design/human-interface-guidelines/spatial-layout) :
  pas de contenu ancré à la tête, pas de profondeur sur le TEXTE, peu de changements de profondeur,
  gestes INDIRECTS (regarder + pincer, main au repos), cibles à 60 pt d'entraxe (un point y est un
  angle) ; les « ornaments » accrochent les barres d'outils au bord d'une fenêtre ;
- Meta Horizon (https://developers.meta.com/horizon/design/hands-ui-best-practices/) : cibles ≥ 22 mm,
  commandes fréquentes dans la moitié BASSE, aucun bouton qui bouge au survol, un retour sonore et
  visuel à chaque sélection (pas d'haptique) ; plus de 60 % des usages Quest 3 passent par le
  navigateur et des panneaux 2D ;
- Android XR (https://developer.android.com/design/ui/xr/guides/spatial-ui) : « Material Design for XR »
  reprend les MÊMES composants Material 3, spatialisés sur casque — la même interface, une projection
  de plus ;
- la fatigue du bras levé (« gorilla arm ») se mesure (Consumed Endurance, CHI 2014 ; NICER, 2024).

**Ce qui marche AUJOURD'HUI dans un navigateur** :
- WebXR : Quest Browser (mains par défaut), Chrome sur Android XR (Hand Input, ancres), Safari
  visionOS en `immersive-vr` (le pincement arrive en « transient-pointer ») ; pas Safari iOS/macOS,
  pas Firefox ;
- l'élément HTML `<model>` (visionOS 26 : relief sur casque, rendu 2D ailleurs) ; le « Spatial CSS »
  de WebKit reste une proposition ; **WebSpatial** (https://webspatial.dev/docs, présenté au W3C le
  2025-11-10) : de petites extensions HTML/CSS — la MÊME app rendue en page ordinaire, spatialisée
  sur casque — l'approche la plus proche du principe métadonnée-driven de WAMA ;
- HTML-in-canvas (essai Chromium, avril 2026) : du DOM dessiné dans une scène 3D en restant dans
  l'arbre d'accessibilité ;
- la View Transitions API est disponible dans tous les navigateurs majeurs (fin 2025) : une bascule
  animée sur le DOM RÉEL, sans WebGL ;
- **le fait principal** : une app web bien construite est DÉJÀ pilotable à la souris, au doigt et au
  regard + pincement — Safari visionOS, Quest Browser et Chrome Android XR traduisent le pincement en
  clic. ⚠ Une page web ne reçoit JAMAIS le regard sur visionOS (vie privée : le survol est dessiné
  par Safari).

**Sans casque** : MediaPipe (déjà vendorisé, §3.6) pour la main ; le regard par webcam (WebGazer) a
2 à 3,7° d'erreur (~100 px) et dérive — utilisable pour une ZONE, jamais un bouton, et le projet n'est
plus maintenu ; Google Project Gameface (tête + expressions) en fait un outil d'ACCESSIBILITÉ.

**Minority Report, et ce qu'on en a retenu** : John Underkoffler (conseiller du film) a construit
g-speak puis Mezzanine (Oblong) ; il disait lui-même que le geste compte moins que la COLLABORATION.
Oblong s'est reconvertie en 2025 hors de l'interface. La critique HCI est constante (bras levés =
fatigue en minutes) ; les films récents (Blade Runner 2049) ont quitté l'hologramme tape-à-l'œil.
**Aucune application de productivité web à navigation globale en 3D n'a été trouvée** : les sites 3D
primés (Awwwards 2024 : Igloo Inc) sont des vitrines, invisibles aux lecteurs d'écran sans DOM
parallèle ; les bureaux 3D (Looking Glass de Sun, le cube de Compiz) ont été montrés puis oubliés.
⇒ l'idée de Fabien d'une interface globale 3D et multi-supports n'existe pas en production : c'est un
terrain libre, à condition d'éviter les échecs connus.

**Les principes qui en découlent (proposés)** — quatre couches, chacune facultative au-dessus de la
précédente, la 2D restant la vérité :
- **C0** le DOM porte tout (accessibilité, URL, clavier) ; **C1** profondeur et bascules en CSS 3D +
  View Transitions sur ce DOM ; **C2** des îlots WebGL (les scènes du §4) avec leur double DOM ;
  **C3** casque (WebXR, WebSpatial, `<model>`), activé par DÉTECTION de fonction ;
- une seule saisie, les Pointer Events : cibles larges, rien caché derrière un survol (visionOS
  l'ignore), `prefers-reduced-motion` (la bascule devient un fondu), pas de profondeur sur le texte ;
- **une même structure rendue en 2D ou en spatial**, comme Material for XR, SwiftUI sur visionOS et
  WebSpatial : pour WAMA, la source est le schéma qui existe déjà (`APP_CATALOG`, `app_modes`, la spec
  de détail, `to_dict()`) — le rendu spatial en est une PROJECTION de plus, jamais une seconde
  interface écrite à la main (principe 3 d'`AGENTS.md`).

**Pistes de concepts pour WAMA (proposées, aucune retenue)** :
1. **Prisme de domaine** — chaque app est un prisme, une face par domaine ; changer de domaine fait
   tourner le prisme. CSS 3D + View Transitions sur le DOM réel (rotation < 400 ms, fondu en
   `reduced-motion`) ; le focus et l'URL suivent. C'est la forme 3D de l'idée de Fabien, posée en
   TRANSITION sur un sélecteur accessible (`MODES_QUEUE_UX.md §2ter`), pas en seul accès.
2. **Pipeline en profondeur** — les nœuds d'un pipeline (`ROUTE §10.6`) étagés sur l'axe Z, les cards
   avancent à mesure qu'elles progressent : une vue d'ensemble d'un lot, jamais l'édition.
3. **Établi spatial d'une card** — sur casque, le résultat grandeur nature (avant/après côte à côte,
   forme d'onde en arc), les réglages en panneau bas ; seulement s'il est GÉNÉRÉ des métadonnées de
   la card.
4. **Revue de masse au geste** — pouce haut / bas / suivant pour trier des centaines d'éléments, à la
   webcam (les mains du §3.6) ; désactivée par défaut, équivalent clavier et annulation.
5. **« Ce lot-ci »** — la voix de l'assistant désigne, un regard grossier situe la ZONE visée ; le
   regard ne déclenche jamais rien (et rien sur visionOS).
6. **Médiathèque en constellation sémantique** — les médias placés par proximité de leurs vecteurs
   (pgvector existe) ; la brique du §4 la porte ; une projection 2D et des filtres à côté.
7. **Aperçu en relief des sorties 3D** — avatars, `.glb`, vidéos stéréo ouverts en `<model>` ou Quick
   Look ; le meilleur rapport gain/coût (⚠ médias 3D : hors du périmètre initial de ce fichier).
8. **Salle de revue collaborative** — la leçon d'Underkoffler : un grand écran ou un casque partagé en
   réunion de labo, chaque participant pointe et classe depuis son téléphone ; commencer par
   « présentateur + spectateurs ».
Ordre suggéré par la recherche : 7 et 1 (faible coût, aucune perte d'accessibilité), puis 6 et 2,
puis 3 quand WebSpatial ou le Spatial CSS se stabilisent ; 4 et 5 expérimentales, sur option.
**Non confirmé** : `<model>` sur iOS/macOS 27, l'AR WebXR sur visionOS 26, une mesure publiée de la
latence de MediaPipe dans le navigateur (à mesurer chez nous).

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
  *Depuis le 2026-11-09, ce domicile est une DÉRIVATION, plus un jeton écrit : une famille de
  données reçoit ses couleurs de `theme_generator.identity_colours` (ci-dessous) — c'est là que
  viendrait la famille de licences.*
- ✅ **Les types de modèles, lus par leur valeur (2026-11-08)** : la scène des modèles recopiait
  dix alias `--wc-type-*` (le onzième type, `nlp`, sans couleur) ; elle lit désormais le jeton du
  THÈME par la valeur du type (`--wama-mm-type-<valeur>`, `model_scene.py`), comme le badge de la
  gestion des modèles, et une pastille de couche peut nommer un jeton du thème entier
  (`scenes.layer_token`). Garde : `tests_theme.ModelTypeColoursTest` (chaque type de l'enum a sa
  couleur et un texte lisible dans chaque thème ; aucune source ne recopie la liste des types).
- ✅ **Leurs couleurs se DÉRIVENT de l'enum (2026-11-09, accord de Fabien)** — `CARD_DESIGN §9.1`
  (« déclaratif et dérivé, pas 10 hex à la main — une 11ᵉ hérite sa nuance »), appliqué aux apps
  depuis le 2026-07-05 mais pas aux types, dont les onze couleurs se choisissaient à la main, deux
  fois (sombre, clair). `theme_generator.identity_colours` répartit une teinte par type sur le
  cercle, dans l'ordre de `ModelType`, à la saturation des apps (65 %) ; le texte posé dessus est
  le plus lisible des deux textes de palette, et le fond s'en écarte juste assez pour 4,5:1.
  `base.html` pose le bloc sur `:root` (`#wama-identity-colours`, `theme_generator.model_type_css`
  par le processeur de contexte `theme`) : les jetons ont QUITTÉ `wama-theme.css`, une seule source.
  Changement visible : les onze types changent de couleur. Gardes : `ModelTypeColoursTest` (lisible
  sous chaque thème, une couleur distincte par type, aucun bloc de thème ne les déclare, une famille
  quelconque hérite les siennes). `hsl_hex` vit désormais dans `theme_mirror` (deux lecteurs).
- La mise en espace des scènes licences et modèles (`layout`, `label_limit`) est un premier réglage.
- ✅ ~~**Capture caméra / micro sans brique commune**~~ (relevé le 2026-10-22 en écrivant les
  mains) — **soldé le 2026-10-26** : `common/js/wama-capture.js` (`WamaCapture`), adoptée par les
  quatre sites (médiathèque, écoute de l'assistant, Face Analyzer, mains) ; domicile et contrat :
  `WAMA_APP_CONVENTIONS §12.5`.
- Aucun monde sur `AIModel` : il passe par `source` → `APP_CATALOG`.
- Proximité sémantique des cards : images seules, deux espaces séparés, pas de voisinage card ↔
  card, pas de réduction de dimension (§3.3).
- La présentation : un seul rendu, une seule scène active.
- Les renvois de la documentation ne sont pas exposés par une fonction (calculés dans
  `check_docs`).
- Hors domaine, relevé au passage : le face_analyzer charge Chart.js depuis un CDN
  (`wama_lab/face_analyzer/templates/face_analyzer/realtime.html`, `video.html`), contre la règle
  « assets locaux, aucun CDN ». *(Complété le 2026-10-31, mesuré : aussi le cam_analyzer, Chart.js —
  `wama_lab/cam_analyzer/templates/cam_analyzer/base.html:682` — et la page de démonstration des
  modes, Bootstrap et Font Awesome — `wama/common/templates/common/modes_demo.html:8-9`.)*

## 7. À trancher (Fabien)

1. ✅ GO pour la brique commune (§4), et l'ordre du §5 — Fabien, 2026-10-21 : *« commence par les
   licences, puis les modèles »*, sans aucune régression des visuels existants.
2. ✅ Un registre de scènes à part, qui NOMME le registre projeté (tranché en livrant, §4 — à
   revoir si Fabien préfère l'autre forme).
3. La proximité sémantique des cards : vectoriser aussi leur TEXTE (transcriptions, descriptions)
   dans l'espace `text`, et calculer les voisins côté serveur ?
4. Le côte à côte dans la présentation : deux emplacements dans une frame, ou une vue « deux
   frames » ?
5. (2026-11-10, §3.7) L'interface progressivement 3D et spatiale : ouvrir le chantier ? avec quelles
   pistes d'abord (la recherche suggère l'aperçu en relief et le prisme de domaine) ? dans ce fichier
   ou dans un domaine propre ? — session de conception + concile.
