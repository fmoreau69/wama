# STUDIO_VISION.md — Le studio comme pipeline de production AV assisté par IA

> **Statut : VISION (vague, en cours de maturation).** Capture l'intention de Fabien (2026-06-25)
> pour faire du **studio méta-app** un environnement de **production audiovisuelle assistée par IA** :
> constitution de rushs, **montage vidéo automatisé**, **mixage/mastering audio** assisté.
> Les **specs d'outils détaillées** (montage, mixage/mastering) seront fournies plus tard par Fabien.
> Le mixage/mastering est explicitement un **PoC** (aucun outil équivalent n'existe à ce jour).
>
> S'appuie sur le squelette existant : voir `memory/project_meta_app_studio.md`, `MODES_QUEUE_UX.md`
> (§ méta-app), `CARD_DESIGN.md`. Route actuelle : `/studio/` (app Django dédiée `wama/studio`,
> migrée de `common` — corrigé 2026-07-09, l'app studio existe et est montée à la racine des URLs).

## Idée maîtresse
Le **studio** (canvas méta-app : nœuds-app + connecteurs typés) n'est pas qu'un orchestrateur de
tâches : c'est l'endroit où l'on **assemble une production**. On y **constitue ses ressources**
(rushs vidéo, pistes audio) puis on les **monte / mixe / masterise** via des apps dédiées,
réutilisées comme nœuds. Le **typage par connexion** (sortie ∩ entrée) garde le tout cohérent.

## Le studio est AUSSI une bibliothèque (acté 2026-08-12 — marche D de la route)
Deux extensions actées, **domicile de la doctrine = `WAMA_APP_GENERATION_ROUTE.md §10.4`**
(3 espèces de chaînage : agrément / métier / production — ne pas la redocumenter ici) :
- **Capacités héritées** : une app peut hériter une capacité d'une autre (ex. transcriber ←
  `denoise_audio` de l'enhancer) via l'arête `uses` du manifeste (SPEC §7.5) ; l'utilisateur
  voit une case à cocher, le runtime exécute un micro-pipeline par le MÊME pivot
  (`launch_graph`/`execute_tool`) — le studio comme bibliothèque, pas comme UI.
- **Pipeline sauvegardé = capacité composite** : une `StudioPipeline` enregistrée peut être
  référencée par une app (interop wama-lab ↔ studio ; maillon = write-back du kind
  `pipeline`). Le précédent avatarizer (mode TTS retiré, le studio chaîne TTS → avatar) reste
  la règle pour le chaînage de PRODUCTION.

## Décision d'architecture (Fabien, 2026-06-25) — apps dédiées, pas sous-modules du studio
Le **montage automatisé** et le **mixage/mastering** sont des **apps WAMA dédiées**, **pas** des
sous-modules du studio. Raison : dans WAMA, **une app traite** (entrées → `process()` → sortie, avec
modes/capacités/**page d'édition dédiée**) ; **le studio orchestre** (canvas qui câble des apps). Le
montage prend N rushs + audio → produit un montage = travail d'app.

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

### 3. Chaîne OBJETS 3D — de la photo au prop de simulation (idée Fabien 2026-08-18)
**Cas d'usage** : image contenant un/des véhicules → **segmentation** (future app **detector**,
YOLO/SAM3 — périmètre = ROADMAP §17bis) → **reconstruction 2D→3D** (modèle mono-image → mesh
texturé) → objet 3D collecté dans la **médiathèque WAMA**, puis **passerelle vers virtualib**
(librairie d'objets 3D existante, hors WAMA, non connectée) → usage en **simulation Unreal Engine**.
- **Retour 3D→2D** : réutiliser l'objet 3D dans l'**Imager** — générer un décor en image, rendre
  l'objet sous un point de vue choisi (« l'aplatir »), l'**insérer correctement placé** dans le
  décor (harmonisation img2img/inpainting + profondeur). Recouvre le périmètre Detector §17bis
  (« remplacer/insérer, traçable comme synthétique »).
- **Chantier technique consigné dans `ROADMAP.md §17ter`** (candidats modèles, licences, taxonomie
  `'3d'`, port `object_3d`, séquencement) — ne pas redocumenter ici.
- **PoC possible SANS l'app detector** : SAM3 (déjà pilotable par prompt dans l'anonymizer) →
  crop → modèle 2D→3D → GLB en médiathèque. GPU : avec Fabien.

### 4. Chaîne CONSIGNE ANIMÉE — avatar parlant dans un décor généré (idée Fabien 2026-08-18)
**Cas d'usage** : chaîner **Synthesizer (TTS) → Avatarizer → Imager (décor)** pour produire des
**consignes animées** présentées à des participants d'expérimentation (SHS) — un avatar parlant,
incrusté dans un décor généré.
- C'est le prolongement DIRECT du précédent de référence (mode TTS retiré de l'avatarizer, le
  studio chaîne TTS → avatar, ROUTE §10.4 espèce « production ») : **cas de validation de bout en
  bout** du studio, et candidat naturel au premier **`StudioPipeline` sauvegardé = capacité
  composite** (write-back du kind `pipeline`, maillon restant).
- Trou propre : **l'avatar dans le décor** — voie par défaut = compositing (matte du buste →
  incrustation sur fond Imager) plutôt qu'un modèle avatar à fond de référence, car mutualisable.

### ⚑ Convergence des chaînes 3 et 4 — couture identifiée, NE PAS construire par anticipation
Les deux chaînes butent sur la **même brique manquante : « insérer un élément dans une scène
générée »** (objet 3D rendu → décor ; avatar détouré → décor : détourage/matte, placement,
perspective, harmonisation lumière). Règle du **second consommateur** (cf. ROADMAP §17bis) : la
première chaîne qui l'implémente le fait dans son app ; la seconde déclenche l'extraction vers
`common/`. La couture est notée ici pour que ce jour-là ce soit une heure, pas une redécouverte.

## Pourquoi ça colle au modèle studio
- Chaque étape = un **nœud-app** à **ports typés** (vidéo in/out, audio in/out, **stems**, **prompt**,
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
2. **Card batch de prompts** comme nœud-source branché sur l'Imager vidéo.
3. Réutiliser le **composant card** pour les éléments qui circulent.
4. **Persistance** du graphe puis **exécution** (la file = méta-app à 1 app).

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
| 2 | **Création** depuis les entrées | triade `wama/tool_api.py` **normalisée** : `add_to_<app>(user, <entrées typées>, **params)` → clé UNIFORME `item_id` (params filtrés par introspection de signature) | 🔄 1/10 normalisée (enhancer, 2026-07-13) — suivantes : transcriber, describer, reader (déjà proches) |
| 3 | **Suivi + résultat** | clés CANONIQUES de `unified_detail(app, pk)` : `status`/`progress`/`result_file` (+ `result_text` à ajouter au schéma pour transcriber/describer/reader) | ✅ 8/10 (manquent imager résultat multi-images, avatarizer detail ✅ fait) |
| 4 | **Params de nœud** | `params.py` (PARAMS_JSON, filtrable par contexte `pipeline`) — JAMAIS de spec locale | ✅ runner générique (2026-07-13) : pointeur `params_module`/`params_attr`, mapping de FORME |

### État courant (à résorber)
`wama/studio/services/runners.py` = **SHIM V1 GELÉ** : 10 adapters manuels écrits avant ce
recadrage (signatures encodées, params dupliqués, champs de sortie par modèle). Interdiction de
l'étendre — chaque manque = item de portage de l'app concernée (exemple du bon geste :
`start_composer` manquait à la triade → ajouté au registre central, pas contourné). Le fichier
disparaît app par app au profit du runner GÉNÉRIQUE piloté par le contrat.

### Preview entrée/sortie (décision 2026-07-12)
L'inspecteur (toutes apps, pas seulement studio) doit permettre de basculer la preview
**[Entrée | Sortie]** — clés canoniques `source_file`/`result_file` déjà normalisées — avec un
mode **slider comparatif** offert automatiquement quand entrée et sortie sont de nature
comparable (image/image, vidéo/vidéo : anonymizer, enhancer, converter…). Capacité DÉRIVÉE des
types I/O du manifeste, zéro flag par app.
