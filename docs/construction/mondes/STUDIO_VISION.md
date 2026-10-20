# STUDIO_VISION.md — Le studio comme pipeline de production AV assisté par IA

> **Statut : VISION (vague, en cours de maturation).** Capture l'intention de Fabien (2026-06-25)
> pour faire du **studio** (éditeur de pipelines — ex-« méta-app », vocabulaire précisé le 2026-09-15 →
> `WAMA_APP_GENERATION_ROUTE.md §10.6`) un environnement de **production audiovisuelle assistée par IA** :
> constitution de rushs, **montage vidéo automatisé**, **mixage/mastering audio** assisté.
> Les **specs d'outils détaillées** (montage, mixage/mastering) seront fournies plus tard par Fabien.
> Le mixage/mastering est explicitement un **PoC** (aucun outil équivalent n'existe à ce jour).
>
> S'appuie sur le squelette existant : voir `memory/project_meta_app_studio.md`, `MODES_QUEUE_UX.md`
> (§ méta-app), `CARD_DESIGN.md`. Route actuelle : `/studio/` (app Django dédiée `wama/studio`,
> migrée de `common` — corrigé 2026-07-09, l'app studio existe et est montée à la racine des URLs).

## Idée maîtresse
Le **studio** (canvas de nœuds — entrée, sortie, app, fonction, pipeline — + connecteurs typés ;
~~canvas méta-app : nœuds-app~~, vocabulaire précisé le 2026-09-15) n'est pas qu'un orchestrateur de
tâches : c'est l'endroit où l'on **assemble une production**. On y **constitue ses ressources**
(rushs vidéo, pistes audio) puis on les **monte / mixe / masterise** via des apps dédiées,
réutilisées comme nœuds. Le **typage par connexion** (sortie ∩ entrée) garde le tout cohérent.

> ⚠ **Précisé le 2026-09-15 → `WAMA_APP_GENERATION_ROUTE.md §10.6`** : le studio est l'**éditeur en
> graphe du MÊME objet que les cards** — une card porte une instance de pipeline (0..N process) dans
> TOUS les mondes ; le studio est donc leur point commun et en impose l'uniformité. Son catalogue de
> gauche est à renommer « Catalogue » (sections repliables, pipelines sauvegardés visibles,
> glisser-déposer au lieu du clic) — §10.6 point 5.4.

## Le studio est AUSSI une bibliothèque (acté 2026-08-12 — marche D de la route)
Deux extensions actées, **domicile de la doctrine = `WAMA_APP_GENERATION_ROUTE.md §10.4`**
(3 espèces de chaînage : agrément / métier / production — ne pas la redocumenter ici) :
- **Capacités héritées** : une app peut hériter une capacité d'une autre (ex. transcriber ←
  `denoise_audio` de l'enhancer) via l'arête `uses` du manifeste (SPEC §7.5) ; l'utilisateur
  voit une case à cocher, le runtime exécute un micro-pipeline par le MÊME pivot
  (`launch_graph`/`execute_tool`) — le studio comme bibliothèque, pas comme UI.
  *Précisé le 2026-09-15 → ROUTE §10.6 point 7* : l'option = un process `optional` inséré dans le
  pipeline de la card, exécuté par le moteur commun (plus « un micro-pipeline studio de 2 nœuds »).
- **Pipeline sauvegardé = capacité composite** : une `StudioPipeline` enregistrée peut être
  référencée par une app (interop wama-lab ↔ studio ; maillon = write-back du kind
  `pipeline`). ~~Le précédent avatarizer (mode TTS retiré, le studio chaîne TTS → avatar) reste
  la règle pour le chaînage de PRODUCTION.~~ **Corrigé le 2026-09-15** : ce précédent est périmé
  depuis le 2026-08-28 — TTS → avatar est redevenu un **workflow dérivé DANS l'avatarizer** (le texte
  déclenche le TTS, l'audio fourni prime, `MODES_QUEUE_UX.md §2bis`, lignes 93-100) ; la composition
  studio Synthesizer → Avatarizer reste possible mais facultative. Le chaînage de PRODUCTION reste
  l'assemblage entre apps (ROUTE §10.4), sans ce précédent pour exemple.

## Décision d'architecture (Fabien, 2026-06-25) — apps dédiées, pas sous-modules du studio
Le **montage automatisé** et le **mixage/mastering** sont des **apps WAMA dédiées**, **pas** des
sous-modules du studio. Raison : dans WAMA, **une app traite** (entrées → `process()` → sortie, avec
modes/capacités/**page d'édition dédiée**) ; **le studio orchestre** (canvas qui câble des apps). Le
montage prend N rushs + audio → produit un montage = travail d'app.
*Précisé le 2026-09-15 → ROUTE §10.6* : la décision « apps dédiées » tient ; le studio COMPOSE des
pipelines (apps, fonctions, sous-pipelines) et le **moteur commun** les exécute, depuis le studio
comme depuis n'importe quelle file.

Conséquences :
- L'app **« Monteur »** est **automatiquement un nœud du studio** (via `APP_CATALOG`/`studio-nodes`)
  **et** utilisable **standalone** (sa page). File/batch/inspecteur/card = offerts par la coque commune.
- **Un seul Monteur, avec des MODES** (pas deux apps d'emblée) :
  - mode **clip musical** (piloté rythme : BPM + dynamique, moteur de `MusicVideoGenerator`) ;
  - mode **narratif** (court-métrage / documentaire scientifique : scénario, storyboard, voix off, B-roll).
  Le noyau est partagé (ingestion rushs, timeline/séquencement, transitions, rendu FFmpeg). La
  différence = la **logique de pilotage** = un **mode** (entrées/réglages déclarés via `app_modes`).
- L'« **environnement à part** » du documentaire = une **page d'édition dédiée par mode**
  (timeline beat-sync vs éditeur scénario/storyboard), déclarée via la capacité
  **`edit_page={route,label,icon}`** (par mode). **On ne scinde en deux apps que si/quand le noyau
  cesse d'être partagé** (anti-fragmentation prématurée).
- **Mixage/Mastering** = **app dédiée** également (édition audio, page type station de mixage),
  **dans un second temps**. Même logique : nœud studio + standalone.

## Quatre chaînes (mêmes briques studio)

### 1. Chaîne VIDÉO — du rush au montage
- **Constituer la base de médias (rushs)** :
  - glisser des **médias vidéo existants** (les siens) ;
  - ajouter une **card batch de prompts** envoyée à l'**Imager vidéo** → **génère des vidéos** ;
  - mélanger généré + importé → ensemble des rushs.
- **Monter** : une **app de montage automatisé** (à concevoir), réutilisable comme **nœud studio**,
  qui prend N rushs (+ éventuellement audio) et produit un montage. Assistance IA (sélection,
  rythme, raccords…). → specs à venir.

- **Prior art (Fabien) : `MusicVideoGenerator`** (https://github.com/fmoreau69/MusicVideoGenerator,
  CLI, jamais terminé). Apporte le **cœur réutilisable = analyse audio pour montage en rythme** :
  synchronisation **BPM + dynamique** (passages forts → coupes plus rapides / visuels plus intenses ;
  mode tempo seul), overlays + chroma-shift entre clips. Le **sourcing média** y était **aléatoire
  depuis des dossiers locaux** (l'idée mots-clés/paroles → creative commons n'a jamais été implémentée).
  - **Le saut WAMA** (au-delà du repo) :
    - **générer** les médias (Imager vidéo) au lieu de seulement les sourcer ;
    - **Describer** pour extraire **mots-clés/thèmes des paroles** — directement depuis l'**audio**
      (transcription) **ou** un texte fourni ;
    - **LLM spécialisés cinéma** pour générer **scénario + storyboard** ;
    - **media_library / providers** (Wikimedia, Pixabay, Freesound…) pour le sourcing creative commons.
  - → Le **nœud « montage »** réutilise l'**analyse rythme/dynamique** de MusicVideoGenerator comme
    moteur de timing des coupes ; le reste de la chaîne (rushs générés/sourcés, keywords, storyboard)
    vient des apps WAMA branchées en amont dans le studio.

### 2. Chaîne AUDIO — de la ressource au master
- **Constituer les ressources audio** :
  - **générer musiques & ambiances sonores** (Composer) ;
  - ajouter ses **propres musiques** ;
  - **découper en stems** des morceaux complets si besoin (outil de séparation de sources) pour
    préparer toutes les ressources.
- **Mixer / masteriser** : une app de **mixage/mastering** assistée IA (workflow différent du
  montage). **PoC** — réflexion déjà entamée par Fabien, specs à venir. Outils envisagés : stems,
  préparation des ressources, traitement assisté.

### Composer — génération musicale personnalisable (style Suno)
Améliorer la **génération de musique dans le Composer** pour la **personnaliser** (dans l'esprit de
Suno ou équivalents), afin qu'elle alimente la chaîne audio avec des ressources de qualité et
contrôlables.

### 2bis. Chaîne FILM — le **Movie Director** (idée Fabien, 2026-09-04)

> Discussion consignée telle qu'exposée, **confrontée au pipeline réel**. Rien n'est décidé ici :
> ce qui suit dit ce que le fonctionnement actuel PERMET, ce qu'il REFUSE, et les manques nommés.

**Le générateur de films, en deux étapes.**

*Étape 1 — les documents.* Une app **Movie Director** tient synopsis → scénario → **découpage** →
**storyboard**, et séquence les plans (court-métrage). Pour chaque plan elle a besoin d'images
d'**entrée et de sortie de plan** : elle envoie donc un **batch de prompts** à l'**Imager**, dont la
sortie **revient** au Movie Director pour être insérée dans les documents. Une fois la boucle
terminée, le Movie Director livre **l'ensemble des documents**.

*Étape 2 — les plans.* Ces documents entrent dans un **second Movie Director**, sur une autre
modalité d'entrée. Celui-ci émet **prompts + fichiers de référence** vers un **Imager vidéo**, qui
produit les plans. Par-dessus, une **couche de contrôle** doit tenir la constance du **style, des
décors et des personnages** d'un plan à l'autre.

#### Ce que le pipeline actuel permet DÉJÀ (mesuré le 2026-09-04)

- **Les entrées multiples existent, et elles sont métadonnée-driven.** `studio_node_ports()` dérive
  trois familles de ports d'entrée : `work` (média, multi), `prompt`, et **`reference`**
  (`reference_image`, `reference_voice`, déclarés sur un mode ou sur le domaine). C'est exactement
  la forme « prompts + fichiers de référence » de l'étape 2 — **rien à inventer**.
- **La composition app↔app est le fonctionnement normal du studio** : un nœud = une app, les liens
  portent `to_port`. Le Movie Director n'est donc pas un cas spécial, c'est une app de plus.
  *(Corrigé le 2026-09-15 : « un nœud = une app » était vrai à la mesure du 09-04 ; depuis le 09-09
  un nœud peut aussi être une fonction ou la source `dataset_input`, et le type `pipeline` est prévu
  — ROUTE §10.6 point 3.1.)*

#### Ce que le pipeline REFUSE aujourd'hui — et pourquoi ce n'est pas bloquant

- **Le graphe est ACYCLIQUE, par construction** : `studio/tasks.py` calcule un ordre topologique et
  **lève** `ValueError('Le graphe contient un cycle')`. La « boucle de rétroaction » Imager →
  Movie Director ne peut donc pas être une arête de retour.
- **Mais ce n'en est pas une.** Fabien a lui-même **déroulé** la boucle pour l'étape 2 (« un
  SECOND Movie Director »). Le même geste vaut à l'intérieur de l'étape 1 : *Director-découpage →
  Imager → Director-assemblage*. Trois nœuds, aucun cycle, et chaque nœud garde une responsabilité
  lisible. **La rétroaction est un déroulement, pas une exception au moteur** — c'est d'ailleurs la
  seule forme qui reste ré-exécutable et traçable plan par plan.

#### Les manques RÉELS (nommés, non résolus)

1. **Une sortie unique par nœud.** `studio_node_ports()` rend `{'inputs': [...], 'output': {…}}` —
   **singulier**. Le Movie Director en veut deux (les documents enrichis d'images, puis le jeu
   complet). C'est le seul manque **structurel** de la chaîne, et il est générique : d'autres apps
   voudront séparer « produit intermédiaire » et « livrable ». À traiter comme les ports d'entrée
   l'ont été — **dérivés des métadonnées**, jamais déclarés à la main par app.
2. **La couche de constance (style / décors / personnages).** Ce n'est **pas** une fonction de
   l'Imager ni du pipeline : c'est un **artefact partagé** — une « bible » (chartes de style, fiches
   personnages, images de référence, seeds) que **chaque** nœud générateur consomme par son port
   `reference`. Le port existe ; ce qui manque est l'artefact et sa propagation. Piste naturelle :
   un manifeste (`project` ou `dataset`) plutôt qu'une table d'app — il doit survivre au film et
   se réutiliser. Les modèles récents à édition guidée (qwen-image-edit et sa famille) sont les
   consommateurs attendus de cette bible, pas son substitut.
3. **L'Avatarizer n'est pas au bon endroit dans la chaîne — et pas au bon niveau de maturité.**
   Il n'est ni une étape globale ni un concurrent de l'Imager vidéo : il opère **par plan**, en
   AVAL, sur les plans marqués « personnage parlant », en consommant (a) la fiche personnage de la
   bible et (b) l'audio du **Synthesizer**. Aujourd'hui il fait du **lipsync** (MuseTalk) sur une
   vidéo existante : c'est de la synchronisation labiale, pas de l'animation de personnage
   contrôlée. Le manque est donc **dans l'app**, pas dans le câblage — et il est le plus lourd des
   trois. ⚠ Voir aussi les **licences Hunyuan qui excluent l'UE** pour toute une famille de modèles
   d'avatars parlants.
4. **Les apps qui n'existent pas** : Movie Director (×1, instancié deux fois dans le graphe — pas
   deux apps), et le nœud de **montage** déjà tracé au §1 (chaîne vidéo) qui reste le débouché
   naturel des plans produits.

#### Ce que cette chaîne confirme du modèle WAMA

Le studio n'a besoin d'**aucune notion de « film »** : le Movie Director est une app comme les
autres, ses documents sont des médias, sa bible est un artefact déclaré, et le séquencement est un
graphe. **La seule évolution du moteur propre à cette chaîne est la sortie multiple** (précisé le
2026-09-15 : le chantier du moteur commun — ligne par process, états, `STALE`, nœud `pipeline` — est
distinct, ROUTE §10.6) — le reste est du
développement d'apps. C'est le meilleur signe que le découpage app/studio tient : une ambition
aussi grosse qu'un générateur de films n'ajoute qu'un port.

### 3. Chaîne OBJETS 3D — de la photo au prop de simulation (idée Fabien 2026-08-18)
**Cas d'usage** : image contenant un/des véhicules → **segmentation** (future app **detector**,
YOLO/SAM3 — périmètre = ROADMAP §17bis) → **reconstruction 2D→3D** (modèle mono-image → mesh
texturé) → objet 3D collecté dans la **médiathèque WAMA**, puis **passerelle vers virtualib**
(librairie d'objets 3D existante, hors WAMA, non connectée) → usage en **simulation Unreal Engine**.
- **Retour 3D→2D** : réutiliser l'objet 3D dans l'**Imager** — générer un décor en image, rendre
  l'objet sous un point de vue choisi (« l'aplatir »), l'**insérer correctement placé** dans le
  décor (harmonisation img2img/inpainting + profondeur). Recouvre le périmètre Detector §17bis
  (« remplacer/insérer, traçable comme synthétique »).
  ⚠ **Avec ou sans modèle IA dédié ? Arbitrage tranché en deux étapes** (question Fabien 19/08,
  détail = ROADMAP §17ter) : le **rendu** reste DÉTERMINISTE (Blender headless / three.js — un
  modèle IA y ferait perdre la maîtrise de pose/focale/échelle, justement ce qu'on veut contrôler
  pour une expérimentation) ; seule l'**harmonisation** (lumière, ombre, grain) justifie un
  modèle — et on ne l'ajoute qu'après avoir mesuré que le collage simple ne suffit pas.
- **Chantier technique consigné dans `ROADMAP.md §17ter`** (candidats modèles, licences, taxonomie
  `'3d'`, port `object_3d`, séquencement) — ne pas redocumenter ici.
- **PoC possible SANS l'app detector** : SAM3 (déjà pilotable par prompt dans l'anonymizer) →
  crop → modèle 2D→3D → GLB en médiathèque. GPU : avec Fabien.

### 4. Chaîne CONSIGNE ANIMÉE — avatar parlant dans un décor généré (idée Fabien 2026-08-18)
**Cas d'usage** : chaîner **Synthesizer (TTS) → Avatarizer → Imager (décor)** pour produire des
**consignes animées** présentées à des participants d'expérimentation (SHS) — un avatar parlant,
incrusté dans un décor généré.
- C'est le prolongement DIRECT du précédent de référence (~~mode TTS retiré de l'avatarizer, le
  studio chaîne TTS → avatar~~ — **corrigé le 2026-09-15** : depuis le 2026-08-28 le TTS est un
  workflow dérivé DANS l'avatarizer, `MODES_QUEUE_UX.md:93-100` ; la composition studio reste
  possible, ROUTE §10.4 espèce « production ») : **cas de validation de bout en
  bout** du studio, et candidat naturel au premier **`StudioPipeline` sauvegardé = capacité
  composite** (write-back du kind `pipeline`, maillon restant).
- Trou propre : **l'avatar dans le décor** — voie par défaut = compositing (matte du buste →
  incrustation sur fond Imager) plutôt qu'un modèle avatar à fond de référence, car mutualisable.
- **Modèles d'avatars : DÉJÀ PROSPECTÉS, ne pas re-prospecter** — `docs/construction/archive/PROSPECTION_AVATARS_2026-08-17.md`
  (12+ candidats, licences vérifiées AU FICHIER ; ⚠ Hunyuan EXCLUT l'UE). Deux usages distincts,
  tous deux actés (mémoire `project-avatar-talking`) : **(a) consignes offline** avec avatar
  « scientist » (EchoMimicV3-Flash / StableAvatar) = CETTE chaîne ; **(b) mode avatar parlant
  TEMPS RÉEL de l'AI-Assistant** (1ʳᵉ voie TalkingHead, MIT, rendu navigateur three.js, zéro VRAM
  serveur, visèmes FR) = un autre chantier, mais **le même moteur de rendu** que la preview 3D de
  la chaîne 3 et que le rendu 3D→2D : vendoriser three.js une fois sert les trois (cf. ROADMAP
  §17ter, « AVATARS »). « Avatar avancé intégré dans un décor » = (a) + la couture ci-dessous.

### ⚑ Convergence des chaînes 3 et 4 — couture identifiée, NE PAS construire par anticipation
Les deux chaînes butent sur la **même brique manquante : « insérer un élément dans une scène
générée »** (objet 3D rendu → décor ; avatar détouré → décor : détourage/matte, placement,
perspective, harmonisation lumière). Règle du **second consommateur** (cf. ROADMAP §17bis) : la
première chaîne qui l'implémente le fait dans son app ; la seconde déclenche l'extraction vers
`common/`. La couture est notée ici pour que ce jour-là ce soit une heure, pas une redécouverte.

## Pourquoi ça colle au modèle studio
- Chaque étape = un **nœud** (app, fonction ou pipeline — précisé le 2026-09-15, ROUTE §10.6) à **ports typés** (vidéo in/out, audio in/out, **stems**, **prompt**,
  référence). Le montage = nœud à **entrées multiples** (N rushs + audio). Le mixage = nœud agrégeant
  **pistes/stems**. Le master = nœud final.
- Renforce le besoin déjà identifié de **ports plus riches** dans le studio : **multi-entrées**,
  distinction **travail / référence / prompt / url** (cf. `INPUT_TYPES` d'`app_modes`). À faire avant
  d'exécuter de vrais pipelines.
- Le **composant card** circule entre nœuds (un rush, une piste, un montage = une card).

## Ce qui reste à préciser (Fabien fournira)
- Specs des **outils de montage** (sélection/assemblage/raccords assistés IA).
- Specs **mixage/mastering** (PoC) : séparation en stems, préparation des ressources, chaîne de
  traitement, métriques de mastering.
- Modèles IA candidats (génération vidéo déjà en place côté Imager ; musique côté Composer ;
  séparation de sources, etc.).

## Prochaines marches techniques (côté studio, indépendantes des specs)
1. Ports **multi-entrées** + types **travail/référence/prompt/url** sur les nœuds.
   *(2026-10-20 : les ports typés existent — `studio_node_ports`, union des modèles, un port lu
   = un argument du même nom de l'outil ; l'URL est une MODALITÉ de chaque port, pas un type.
   Ce qui manque est la façon de les ALIMENTER : §Entrées du Studio ci-dessous.)*
2. ~~**Card batch de prompts** comme nœud-source branché sur l'Imager vidéo.~~ Retirée (le
   moteur ne savait pas faire circuler un lot) ; remplacée par la card « Fichier de lot » et le
   lot de la card d'entrée universelle (§Entrées du Studio, 2026-10-20).
3. Réutiliser le **composant card** pour les éléments qui circulent.
4. ~~**Persistance** du graphe puis **exécution** (la file = méta-app à 1 app).~~ ✅ livré le
   2026-07-11 (corrigé le 2026-09-15) ; la formule « file = méta-app à 1 app » est remplacée par
   **card = instance de pipeline** (`WAMA_APP_GENERATION_ROUTE.md §10.6`).

## Entrées du Studio — la card d'entrée v4 rendue dans le Studio (décision de Fabien, 2026-10-20)

**Le constat.** Le Studio a quatre sources : « Texte », « Médias importés », « Jeu de données »
et « Base connectée » (`studio/services/builtin_nodes.py`, `wama_data/functions/io/nodes.py`).
Elles suffisent au monde Data. Elles ne suffisent pas au monde Médias : « Médias importés » ne
prend qu'UN fichier de la médiathèque et ne vérifie que son existence (`builtin_nodes.py:22-33`).
Il n'y a ni import depuis le poste, ni URL, ni plusieurs fichiers, ni fichier de lot, ni moyen
d'alimenter un port de référence par ses modalités.

La card d'entrée v4 des apps fait déjà tout cela (`CARD_DESIGN §11.10-11.11`) : un onglet par
port, chacun avec ses modalités (Importer · Médiathèque · URL), plusieurs fichiers ou un dossier
sur le port de travail, l'onglet du fichier de lot, et la forme d'entrée déduite des ports.
**On ne réinvente rien : on la rend dans le Studio.**

**Ce qui est décidé :**

1. **Médias et données ne se mélangent pas.** « Jeu de données » et « Base connectée » restent
   les entrées du monde Data.
2. **Une card d'entrée UNIVERSELLE (médias) qui s'adapte à ce qu'elle alimente.** Branchée sur un
   nœud d'app, elle prend les onglets de la card v4 de cette app : `input_slots(app, domaine)`,
   donc l'union des modèles, l'obligation (`required`, `one_of`), la forme d'entrée
   (`entry_form`) et les ports portés ailleurs. L'appariement entrée ↔ modèle (`WamaInputMatch`)
   suit le modèle réglé sur le nœud. Non branchée, elle accepte tout fichier, comme l'assistant.
3. **Ses ajouts vivent dans une MODALE qui reprend la card v4 de l'app, avec le volet droit à
   côté.** Le volet porte les réglages du nœud, déjà générés du schéma de l'app
   (`wama-studio.js`, `renderNodeSettings`). C'est le premier consommateur de la section Entrée
   que `CARD_DESIGN §11.10` point 4 (exigence 8) promettait à la modale ⚙ et à l'inspecteur. La
   même pièce servira ensuite la section Entrée des modales ⚙ des apps.
4. **Des cards SIMPLIFIÉES, déclinées de la même pièce, pour aller droit au but** quand on sait ce
   qu'on ajoute : « Texte », « Fichier(s) de travail », « Fichier(s) de référence » et « Fichier de
   lot ». **« Texte » reste tel quel** : prompts, textes libres, aperçus textuels qui ne sont pas
   des fichiers (décision maintenue — la question est revenue plusieurs fois).
5. **Composer ne met rien en file : les modalités DÉSIGNENT.**
   - Médiathèque : le fichier est pointé, jamais recopié.
   - Poste : le fichier est rangé dans l'espace du compte, puis désigné.
   - URL : téléchargée au lancement, comme au port de référence de la v4 (« un fichier joint
     prime »).

   Au lancement, chaque port arrive dans l'argument du même nom de l'outil
   (`generic_runner.port_arguments`), puis passe par la désignation commune et sa règle de
   lecture. Cela corrige au passage le contrôle de « Médias importés ».
6. **Le LOT dans le Studio, comme dans les apps.** Une card d'entrée peut porter plusieurs
   fichiers. Plusieurs fichiers de travail OU un fichier de lot donnent la même chose : un lot
   (`CARD_DESIGN §11.11 G`, précision du 2026-10-20). **Le pipeline tourne une fois par élément
   du lot** (une card = une instance de pipeline, `WAMA_APP_GENERATION_ROUTE §10.6`). Le moteur
   ne distingue pas les deux voies, pas plus que les apps.
7. **Le live : rien pour l'instant.** Il reste hors du Studio (`app_registry.app_has_live_input`,
   décision du 2026-09-28), mais ce n'est pas exclu : à revoir à l'usage.

**✅ Tranché le 2026-10-20 — comment la card se branche sur l'app : les deux formes, sans
recouvrement** (proposition acceptée par Fabien). Un nœud d'app reçoit ses entrées PAR PORT
(`studio/tasks.py`, une valeur par lien, indexée par `to_port`). Les cards simplifiées par port se
branchent sur les ports existants. La card universelle et le fichier de lot se branchent sur le
port « Entrée de card ». Ce port ne se déclare pas par app : il se DÉRIVE pour tout nœud qui crée
une card (`entries.card_port`, posé par la palette, jamais dans `studio_node_ports` — la card v4
et les manifestes n'en ont pas l'usage). Il porte exactement ce que porte une ligne de lot, une card
entière (`CARD_DESIGN §11.11`, onglet du fichier de lot, 2026-09-29). Côté moteur, sa valeur se
déplie en ports avant `create` (`entries.unfold`). Un port alimenté deux fois — par lui ET par un
lien direct, d'une autre valeur — se refuse au lancement du nœud, en le nommant (la seconde valeur
écrasait la première en silence).

### ✅ Livré le 2026-10-20 — ce qui est fait, et avec quoi

**Les cards** (registre commun des nœuds intégrés, `studio/services/builtin_nodes.py`) :

| card | clé (donnée des graphes) | se branche sur | multiplie |
|---|---|---|---|
| Texte | `text_input` | le port de consigne | — (inchangée) |
| Entrée (universelle) | `card_input` | « Entrée de card » | plusieurs fichiers de travail, ou son fichier de lot |
| Fichier(s) de travail | `media_import` (ex-« Médias importés ») | un port de travail | plusieurs fichiers |
| Fichier(s) de référence | `reference_input` | un port de référence | plusieurs fichiers |
| Fichier de lot | `batch_input` | « Entrée de card » | une card par ligne |

Ce qu'une card désigne vit dans son réglage caché `entry` ; `media_import` lit encore son ancien
`asset_path`, qui garde son sélecteur pour une fonction ou la Sortie (pas de card d'app à rendre).
La palette range les entrées PAR MONDE (`BuiltinNode.world`) : « Entrées médias », « Entrées
données ».

**La modale** (`studio/js/wama-studio-entry.js`, `WamaStudioEntry`) : la card v4 de l'app branchée,
rendue par le serveur (`/studio/api/entry-card/`, le gabarit des dix apps en `compose_only` : tout
se JOINT, la barre de lot — qui crée des cards — n'est pas rendue), restreinte à ce que la card du
Studio porte (tous les onglets ; l'onglet de son port ; l'onglet du fichier de lot) ; à côté, le
volet : les réglages du nœud de l'app, par le rendu commun du Studio. Vérifiée dans un navigateur
sur la page servie (dépôt, retenue, onglet seul, fichier de lot compté) — sans erreur console.

**Le lot** : déplié au lancement (`entries.lot_graphs`, appelé par `launch.launch_graph` avant le
dispatch) en un graphe par élément, joué chacun comme un run ENFANT du run lancé
(`StudioRun.parent`, migration `studio/0005`) ; un élément en échec n'arrête pas les autres ; à la
fin, les cards de chaque nœud d'app forment UN lot de sa file (`consolidate_arrival`). Le canvas
résume chaque nœud par la règle d'un lot d'app (`batch_views.lot_overview`, extraite de
`batch_status` pour n'en avoir qu'une) ; le ZIP du run prend les résultats de tous les éléments.

**Cartographie de l'existant réutilisé** (relevée le 2026-10-20 avant d'écrire — rien de réécrit) :

| besoin | la brique | ce qui a été ajouté |
|---|---|---|
| onglets, modalités, face fichiers | `_new_item_card_v4.html`, `WamaInputSlots` | `compose_only` ; `WamaInputSlots.wire` exposée (une card rendue après le chargement) |
| dépôt joint au port qui l'admet | `WamaImport({attach: 'card'})` | — |
| médiathèque (désignation) | `WamaApp.pickFromLibrary`, `MediaPicker` | — |
| dépôt du poste dans l'espace du compte | `WamaFM.upload` → `enregistrer_fichier_utilisateur` | — |
| garde de lecture d'une désignation | `media_paths.designate` | `check_designation` (les mêmes gardes, sans pointer ni copier) |
| URL téléchargée au lancement | `source_ingest._download` (primitives de l'ingest) | `download_to_user`, `ingest_mode_for` (le mode suit la nature du port) |
| lignes d'un fichier de lot | `batch_parsers` (balises, CSV à en-têtes, listes) | `parse_batch_lines` (toutes familles), `line_to_ports` |
| regroupement en lot | `queue_manipulation.consolidate_arrival` | — |
| état d'un lot | `batch_status` de `make_batch_views` | `lot_overview` (la règle, extraite) |
| port = argument de l'outil | `generic_runner.port_arguments` | — |
| ce qu'un nœud reçoit (inspecteur) | `graph_flow.node_context` | les ports d'une card entière |

**Ce qui reste, nommé :**
- **L'appariement entrée ↔ modèle dans la modale** (`WamaInputMatch`) : la card montre sa ligne
  d'état, mais rien ne la relie encore au sélecteur de modèle du volet de la modale — chaque app
  câble le sien sur sa page, avec les métadonnées de ses modèles.
- **La card universelle NON branchée** n'accepte rien encore : elle prend la forme de la card de
  l'app qu'elle alimente (« Reliez la card à une app »). « Accepter tout fichier, comme
  l'assistant » avant le branchement reste à faire.
- **Le nom de sortie d'une ligne de lot** (`-o`) n'est pas appliqué au Studio ; une ligne qui le
  porte n'échoue pas, il est ignoré (comme chez les apps de type A, `BATCH_FORMAT.md`).
- **Une ligne de lot programmée** (`--when`/`--at`) : le réglage est refusé comme inconnu de l'app
  — la programmation d'un run du Studio n'existe pas.
- **Les colonnes d'une ligne nommées par PORT** valent au Studio (`line_to_ports`) ; les vues de lot
  des apps gardent chacune leur correspondance (`CARD_DESIGN §11.11`, question ouverte des lots).

---

## PRINCIPE DIRECTEUR (recadrage Fabien 2026-07-12) : le studio consomme le CONTRAT, jamais l'état courant

> Le studio doit fonctionner sur le **schéma d'une app complètement uniforme**, quelle que soit
> l'app. Si un mécanisme manque à une app pour être orchestrable, on **finit le port de l'app**
> (le manque devient un item de portage) — on n'écrit **jamais** de colle côté studio qui
> s'adapte à son état actuel. La colle par app fige l'hétérogénéité et crée une seconde source
> de vérité qui dérive. (Mémoire : feedback_studio_uniform_contract.)

### Le contrat d'app exécutable (spec cible)
Une app est orchestrable quand ces 4 éléments viennent du CONTRAT COMMUN :
| # | Élément | Source unique | État |
|---|---|---|---|
| 1 | **Entrées typées** (ports du nœud) | `APP_CATALOG` / `studio_node_ports()` | ✅ en place |
| 2 | **Création** depuis les entrées | triade `wama/tool_api.py` **normalisée** : `add_to_<app>(user, <entrées typées>, **params)` → clé UNIFORME `item_id` (params filtrés par introspection de signature) | ✅ **10/10** (re-mesuré 2026-08-27 : `item_id` natif ou via wrappers `@wraps` sur toutes les triades) — ⚠ **rectifié le 2026-10-06** : la mesure comptait les dix APPS, pas la branche audio (`add_to_audio_enhancer` ne rendait que `audio_enhancement_id`), et les quatre créateurs historiques encore offerts au modèle (`create_image`…) n'avaient la clé que par leur alias. Désormais rendue À LA SOURCE par chaque créateur, et TENUE : `tests_tool_item_contract`, dérivé du registre d'outils |
| 3 | **Suivi + résultat** | clés CANONIQUES de `unified_detail(app, pk)` : `status`/`progress`/`result_file`/`result_text` | ✅ **10/10** (la sortie multi-images de l'imager est entrée au mécanisme préview n°30) |
| 4 | **Params de nœud** | `params.py` (PARAMS_JSON, filtrable par contexte `pipeline`) — JAMAIS de spec locale | ✅ runner générique (2026-07-13) : pointeur `params_module`/`params_attr`, mapping de FORME |

### État courant — ✅ RÉSORBÉ (mis à jour 2026-08-27 ; le suivi fin vit dans PROJECT_STATUS)
Le shim V1 (`runners.py`, 10 adapters manuels) a été **vidé app par app, 10/10 le 2026-07-13** :
il ne reste que la façade `runner_for()` déléguant au runner **GÉNÉRIQUE**
(`generic_runner.py::GENERIC_APPS`, 10 entrées). Ajouter une app au studio = remplir son contrat
+ quelques lignes de `GENERIC_APPS` — jamais un adapter. ⚠ Ce document est une VISION : les états
d'avancement n'y ont plus leur place, ils pourrissaient (les 4 lignes ci-dessus sont restées
fausses 6 semaines) — l'avancement se lit dans `PROJECT_STATUS.md` et la grille.

### Preview entrée/sortie — ✅ LIVRÉ
Le toggle **[Entrée | Comparer | Sortie]** est dans l'inspecteur commun
(`wama-inspector.js`, clés canoniques `source_file`/`result_file`), toutes apps — la décision du
2026-07-12 est exécutée.
