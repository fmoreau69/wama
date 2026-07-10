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

## Deux chaînes (mêmes briques studio)

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
