# WAMA — Roadmap

> Dernière mise à jour : 2026-07-20 (Horizons + GNM ; **dédoublonnage exécuté** : sections actées → archive + renvois PROJECT_STATUS, bugs §0 → PROJECT_STATUS). Précédent : 2026-07-11 (audit conformité — PROJECT_STATUS §31 ; l'en-tête « 2026-05-16 » mentait, le contenu allait jusqu'à 2026-07-01)
> Légende : ✅ Fait · 🔄 En cours · ⏳ Planifié · 💡 Proposé · ❌ Abandonné · 🐛 Bug bloquant

---

## Frise — les grands jalons

> Vue d'ensemble pour un lecteur qui arrive (demande de Fabien, 2026-10-13) : un jalon par
> ligne, au mois près, **sans le détail des chantiers** — ce détail vit dans les sections
> ci-dessous et dans `PROJECT_STATUS`. Cette table est **LUE par la présentation**
> (`wama/common/roadmap_timeline.py` → diapositive « Roadmap ») : un jalon s'ajoute ou se
> corrige ICI, jamais dans le gabarit. Colonnes : Quand (texte court, affiché tel quel) ·
> État (✅ / 🔄 / ⏳ seulement) · Jalon (quelques mots) · Détail (une phrase, facultative).
> Dates relevées dans l'historique git le 2026-10-13 ; les jalons ⏳ ne portent pas de date
> tant qu'aucune décision n'en a fixé une.

| Quand | État | Jalon | Détail |
|---|---|---|---|
| 2023 | ✅ | Premiers pas | Un anonymiseur pour les vidéos du labo, développé à la main. |
| 2025-10 | ✅ | Socle de production | PostgreSQL, Celery et le Transcriber. |
| 2025-11 → 2026-04 | ✅ | Dix apps Médias | Voix, images, vidéo, musique, lecture, description, conversion. |
| 2026-01 → 02 | ✅ | Le monde Lab | Face Analyzer, puis Cam Analyzer pour la navette autonome. |
| 2026-06 | ✅ | Studio et tests de nuit | Les apps se chaînent ; chaque nuit, WAMA se remesure. |
| 2026-07 | ✅ | Quatre mondes, une conformité mesurée | Médias, Data, Lab, Transversal ; les règles se vérifient sur le code. |
| 2026-08 | ✅ | Bac à sable, monde Data, mémoire | Apps régénérées à part ; WAMA Data devient un monde ; RAG sur pgvector. |
| 2026-09 | ✅ | Un modèle de pipeline commun | Une card porte un pipeline ; le Studio l'édite en graphe. |
| 2026-10 | ✅ | Dix apps en pipeline, assistant vocal | Toutes les apps décrites dans le même modèle ; on parle à WAMA. |
| 2026-10 | 🔄 | Writer, née d'une fiche | Une fiche écrite à la main, le reste généré dans le bac à sable. |
| prochain | ⏳ | Writer sort du bac à sable | La première app générée passe en production. |
| prochain | ⏳ | Data Analyzer | L'app du monde Data. |
| ensuite | ⏳ | Droits sur modèles et fonctions | Le contrôle d'accès s'étend au-delà des apps. |
| ensuite | ⏳ | Serveur dédié | WAMA quitte le poste du labo pour un serveur Linux. |

---

## Horizons — boussole de priorités (2026-07-20)

> Hiérarchise TOUT le document par horizon pour ne pas s'éparpiller. Vision + statut vision ↔ code :
> `docs/construction/mondes/WAMA_VISION_COMPLET.md` (document unique depuis 2026-08-27 ; marquage ✅/🔄/⏳ par section,
> non-objectifs en Partie 13). En cas de conflit avec une priorité plus ancienne citée ailleurs dans ce
> fichier, CETTE section fait foi.
>
> **Rôles des documents de suivi (contrat 2026-07-20, amendé 2026-08-27)** — chaque info vit à UN
> seul niveau, les autres pointent : **Vision** (`docs/construction/mondes/WAMA_VISION_COMPLET.md`) = le cap, horizon
> années, avec un marquage d'état GROSSIER par section (l'ex-VISION_STATUS, fusionné) ; **ROADMAP**
> (ce fichier) = les chantiers macro et leur ordre, horizon trimestres ; **PROJECT_STATUS** = l'état
> d'avancement au jour le jour (fait/en cours/détails). Le dédoublonnage à venir = redescendre au
> bon niveau ce qui a dérivé (statuts et checklists détaillées présents ici → PROJECT_STATUS).

> 🔴 **CETTE BOUSSOLE A ÉTÉ RE-MESURÉE LE 2026-09-10 — deux de ses items disaient le CONTRAIRE
> du code.** Elle datait du 2026-07-20 et se déclare « fait foi » : un cap périmé qui se déclare
> prioritaire fait travailler à côté. Corrections portées ci-dessous, chacune avec sa mesure ;
> le détail et l'inventaire complet vivent au **§24**. *Règle appliquée : une doc qui contredit
> le code a tort par défaut — mesurer, corriger, dater.*

### H1 — Maintenant (finir avant d'ouvrir quoi que ce soit)
1. **Consolidation des mécanismes d'UI** 🔄 — intention GARDÉE : sa route est
   `WAMA_APP_GENERATION_ROUTE.md`, son reste mesuré au §24. *(Retirée de cette ligne le 2026-09-10
   avec le constat faux qui l'accompagnait, restaurée le 2026-09-14 — une intention ne se retire
   que par décision.)* Le constat, lui : ~~port schéma-driven des 5 apps restantes (enhancer,
   anonymizer, synthesizer, imager, avatarizer)~~ — ✅ **FAUX depuis des semaines, mesuré le 2026-09-10** : les cinq sont portées
   (`check_app_conformity` : enhancer 95 %, synthesizer 95 %, anonymizer 94 %, avatarizer 94 %,
   imager 92 % ; converter et describer à **100 %**). Ce n'est plus un goulot. **Ce qui RESTE
   de cette ligne** est nommé au §24 : trois critères rouges reviennent sur presque toutes les
   apps — `backend_routes`, `task_skeleton` (F5) et `detail_spec`/`triad_specs` (F3/F6).
2. Transcriber gold standard — ⚠ **95 %, pas 100 %** (mesuré 2026-09-10). Restent 3 rouges dont
   un de fond : `model_options_catalog` — la liste de modèles est **écrite en dur**
   (`transcriber/params.py:39`), donc un modèle installé n'apparaîtra jamais.
   **Extraction des dernières briques communes** 🔄 — intention GARDÉE, non re-mesurée ici.
   *(Même retrait du 2026-09-10, même restauration du 2026-09-14.)*
3. Studio — suites V1 : sorties → filemanager studio, specs montage/mixage (runners : 10/10 apps
   génériques sur le runner générique depuis 2026-07-13, cf. PROJECT_STATUS §37.10 ; restent les
   apps wama_lab).
4. Cam Analyzer Phase 3 (calibration vitesses) — livrable labo concret.

### H2 — Ensuite (dès H1 stabilisé)
1. ~~Fondation RAG **mono-niveau** (`wama/rag/`, ChromaDB + bge-m3)~~ — 🔴 **DOUBLEMENT FAUX,
   mesuré le 2026-09-10** : `wama/rag/` **n'existe pas** et n'existera pas ; **ChromaDB est MORT**
   (le code le dit lui-même : `wama/common/utils/prompt_pipeline.py:176` — « annonçait ChromaDB :
   PÉRIMÉ »). Le substrat RÉEL est **`wama/common/memory/`** sur **Postgres + pgvector**, livré
   (recherche HYBRIDE vecteur + plein-texte FR fusionnée par RRF, `memory/store.py:188`), scope
   hérité de `ScopedVisibility`. Jalons 1-11 et 13-14 livrés (`WAMA_MEMORY.md`).
   🔴 **MÉMOIRE et RAG sont DEUX mécanismes distincts, et les DEUX sont IMPLÉMENTÉS**
   (rectification Fabien, 2026-09-10) : `MemoryItem` = les **souvenirs** (faits, événements,
   procédures) ; `RagChunk` = les **fragments de documents**. Ils partagent le magasin, les
   mixins et `recall()` — ils ne se confondent pas pour autant.
   **Ce qui reste vraiment** : ~~la bascule d'embedder vers `qwen3-embedding:4b` et le réindex~~
   ✅ **faites le 2026-10-19** (bge-m3 → qwen3-embedding:4b, 10 779 vecteurs refaits, seuil
   re-mesuré — `WAMA_MEMORY §7`) ; jalon 12 (outillage assistant list/detail).
   **La hiérarchie université → labo → équipe**, qui devait « attendre la preuve d'usage »,
   n'est pas perdue : elle est HÉRITÉE d'`OrgUnit` + `ScopedVisibility` (`WAMA_MEMORY.md`, qui
   déplace la prudence sur l'USAGE — et y suit l'état de l'arbre `OrgUnit`). *(Phrase retirée
   le 2026-09-10 avec le constat voisin, restaurée le 2026-09-14.)*
2. Traduction de sortie (`translate_output` existe mais n'est appelé nulle part) + i18n statique.
3. Manifeste formel 🔄 — socle LIVRÉ et en avance sur ce fichier : enveloppe + 6 kinds + ingest
   idempotent + 1ʳᵉ projection write-back réelle (access → AppAccessPolicy, 2026-07-23) ; docs de
   référence `WAMA_MANIFEST_SPEC.md` + `WAMA_MANIFEST_ARCHITECTURE.md` + route
   `WAMA_APP_GENERATION_ROUTE.md` (F1–F8). Reste : `check_app_conformity` exécutable, scaffold
   d'app = dernier maillon, gaté.
4. Anonymisation multimodale (Presidio + GLiNER) = porte privacy avant tout routage cloud.
5. Évaluation continue : jeux de test par capacité + QC câblé ; la veille ne propose un modèle
   qu'avec delta mesuré. Prospection suites (multi-agents, routing capacité→app Phase A).
6. Face Analyzer : intégration au catalogue (flag lab) + premier flux exploitable.

### H2-parallèle — Couche Data (décision Fabien 2026-07-20 : fil indépendant, démarrage progressif)
> Reclassée depuis « lointain » : c'est le **prochain grand chantier** après H1/H2, à intégrer
> **progressivement, en parallèle du reste** — indépendant mais connecté au système.
1. **Socle data** : gestion des données tabulaires/signaux comme citoyens de première classe
   (types, aperçus, profils) — s'appuie sur la partie média existante (médiathèque, files).
2. **Centralisation des fonctions de calcul de wama_lab** (cam_analyzer, face_analyzer :
   trajectoires, TTC, fenêtres, métriques physio…) en briques communes réutilisables — même
   logique que `common/` côté apps : le labo capitalise ses calculs au lieu de les disperser.
3. La suite IA de la partie VII (Data Comprehender, boucle de découverte) reste en H3 — elle
   attend ce socle + le RAG + les garde-fous méthodologiques (vision v2 §28).

### H3 — Lointain (vision ; NE PAS ouvrir — cf. non-objectifs v2)
- Data Comprehender + boucle de découverte (partie VII aval) — après couche Data (H2-parallèle),
  RAG et garde-fous méthodologiques.
- **Modèles APPRIS (ML/DL sur les données elles-mêmes), couche statistique, boucle de simulation
  Unreal** → cadre écrit dans **`WAMA_APPRENTISSAGE.md`** (2026-08-25). ⚠ **Ne PAS ouvrir** — mais
  son **§3** (cinq déclarations : unité d'indépendance, réel/synthétique, `trained_from`, régime
  d'exécution, axe d'agrégation) est à traiter **avec le monde Data**, pas ici : gratuit maintenant,
  non rattrapable ensuite.
- Médiathèque universitaire, SI labo, assistant réunions (partie VIII) — conditionné au chapitre
  conformité (RGPD/consentement/SSO) et à l'adoption interne de la médiathèque.
- Story Director / storyboard / apps montage & mixage (partie V) — après Studio complet, avec cas
  d'usage labo nommé.
- ~~Connecteurs conversationnels (Mattermost/Matrix)~~ → **OUVERT le 2026-08-20, voir §19**
  (étape 0 livrée le jour même). Le modèle de menace reste une condition, traitée DANS le
  chantier (§19.4) au lieu de le précéder. Gouvernance des IA (partie XI) : toujours H3.
- Auto-instanciation d'apps ; migration infra Nginx/Linux étapes 2-3.

### Études / veille (aucun chantier ouvert)
- **GNM — modèle 3D paramétrique génératif de tête/visage** (évalué 2026-07-20, type FLAME/3DMM :
  253 params identité + 383 expression + pose, sampler sémantique, backends NumPy/JAX/PyTorch/TF,
  Apache 2.0 annoncé, **Python 3.13**, tête seule, projet très jeune). Verdict WAMA :
  - ✅ cas d'usage n°1 = **stimuli expérimentaux contrôlés** (identité×expression×pose à labels
    connus par construction — reproductibilité by design, aligné provenance v2) + données
    synthétiques d'entraînement/étalonnage pour face_analyzer ;
  - ⚠️ avatarizer : pas de branchement direct sur la chaîne actuelle (MuseTalk photo 2D + audio) —
    exigerait une chaîne rendu 3D complète (textures/rigging/éclairage) = chantier lourd, H3 ;
  - ⚠️ reconnaissance d'émotion par fitting 3DMM = analyse-par-synthèse = RECHERCHE, pas une
    intégration ; le face_analyzer garde une classif 2D dédiée ;
  - **Gate de test** (1 session WAMA Lab, avant toute intégration) : venv isolé py3.13 (stack WAMA
    = 3.12, jamais dans le venv principal), pin de commit, générer N maillages + rendu offscreen
    trimesh, mesurer VRAM/latence/qualité ; contre-vérifier licence et poids inclus. Si concluant :
    entrée « Proposés par IA » dans la prospection model_manager (confidence/complexity).
- **Avatars parlants interactifs type Praktika** (prospection agent 2026-08-17, licences vérifiées
  AU FICHIER LICENSE des repos — demande Fabien : consignes avec avatar « scientist » + mode avatar
  parlant de l'AI-Assistant ; PAS l'apprentissage de langues). **Rapport COMPLET (12+ candidats,
  URLs, VRAM, pièges) : [`docs/construction/archive/PROSPECTION_AVATARS_2026-08-17.md`](../archive/PROSPECTION_AVATARS_2026-08-17.md).**
  ⚠ **MISE À JOUR 2026-09-30 (demande Fabien, veille approfondie) : [`PROSPECTION_AVATARS_2026-09-30.md`](../archive/PROSPECTION_AVATARS_2026-09-30.md)
  REMPLACE le classement ci-dessous.** Qualité : **LongCat-Video-Avatar 1.5** (poids MIT, encodeur
  Whisper-large-v3) et **InfiniteTalk** (Apache-2.0, successeur de MultiTalk) — deux OMISSIONS du
  17/08, pas des nouveautés ; EchoMimicV3/StableAvatar reculent en repli. Léger : **TalkingHead
  rendu côté serveur** (Chromium headless, WebGL sur la 4090 via D3D12 : 60 i/s de rendu MESURÉS),
  MuseTalk v1.5 gardé, **SoulX-FlashHead 1.3B** (Apache-2.0) candidat photo→tête. Exclusions UE
  ajoutées : **MiniMax H3** (sorties comprises), **SkyReels V1** (base Hunyuan). Aucun modèle n'a de
  mesure publiée en FRANÇAIS : à mesurer chez nous avant tout choix définitif.
  ✅ **Moteur `talkinghead` LIVRÉ le 2026-09-30 (palier 1, backend + worker)** :
  `common/backends/talkinghead_backend.py` + `common/static/common/js/wama-avatar-render.js` (temps
  PILOTÉ image par image, son WAV multiplexé au décalage relevé sur `animClock`) ; le worker de
  l'avatarizer choisit le moteur d'après la NATURE de l'avatar (`.glb` → TalkingHead, photo →
  MuseTalk inchangé). Mesuré : 10,7 s de vidéo 1280×720 à 25 i/s en 15-21 s, pic VRAM ~0,2 Go.
  ✅ **Palier 2 LIVRÉ le 2026-09-30 (décisions de Fabien)** : jeton `work_object3d` (pas de port
  « avatar ») ; un avatar est un `object3d` dont le visage (`face_rig`/`visemes`) est MESURÉ dans
  le GLB ; le modèle `avatarizer:talkinghead` au catalogue exige ces attributs (`input_attributes`)
  ; la card dit « photo OU objet 3D » (exigences alternatives, `INPUT_MODEL_MATCHING §6.8`) ;
  source de la médiathèque **« Avatars 3D »** (`media_library/providers/avatars3d.py` : un dépôt =
  une ligne, licences relevées, fichier sans licence jamais proposé — TalkingHead : `mpfb` CC0,
  `brunette` CC BY-NC, 3 autres non commerciaux) ; l'audio SANS texte passe par la transcription
  (`whisper_utils`, mots datés → lèvres, langue entendue → visèmes), rendu réel 18 s pour 10,7 s.
  ✅ Soldés le même jour : verdict d'attributs DÈS L'AJOUT, tirage du modèle d'animation par
  `resolve_model_choice`, avatars 3D cités par NOM (lot, Studio — objets au visage ARKit seuls),
  retrait de `musetalk-v1.0` (R85). Route vendor (D-a) : cf. la décision D-a plus bas.
  Deux cas, deux podiums (état du 17/08) :
  - **(a) consignes OFFLINE** : ① **EchoMimicV3(-Flash)** (Ant, Apache-2.0, 01/2026, conçu 24 Go,
    12 Go quantifié, tête+corps, prompt-guidé — successeur naturel de MuseTalk) ; ② **StableAvatar**
    (MIT, Wan 1.3B, ~18 Go, vidéos LONGUES sans post-processing) ; ③ **MultiTalk** (Apache-2.0,
    multi-personnages/cartoon, 480p sur 4090, base 14B ≈ 30-60 Go disque). Repêchage : Sonic
    (CC BY-NC-SA — NC acceptable labo).
  - **(b) assistant TEMPS RÉEL** : ① **TalkingHead met4citizen** (MIT, three.js CÔTÉ NAVIGATEUR =
    zéro VRAM serveur, lip-sync à visèmes AVEC module FRANÇAIS, API streaming branchable sur le TTS
    WAMA — la voie « Praktika » sans conflit GPU/Celery ; GLB via **MPFB (CC0/CC-BY)** ou
    **RocketBox (MIT)** — ⛔ **PAS Ready Player Me, fermé le 31/01/2026**, cf. rapport) ; ② **LiveTalking** (Apache-2.0, réutilise MuseTalk,
    72 FPS annoncés/4090, WebRTC + interruption ; coût = GPU mobilisé par session → arbitrage
    resource_governor) ; ③ **OpenAvatarChat** (Alibaba, Apache-2.0, LLM OpenAI-compatible → Ollama
    local ; à piller en composants — LAM 3D rendu client — plutôt qu'adopter en bloc).
  - ⚠️ **Éliminatoire vérifié** : HunyuanVideo-Avatar — la licence Tencent Hunyuan **exclut
    explicitement l'UE** (« does not apply in the European Union ») → inutilisable au labo ;
    réflexe à garder sur TOUT modèle Hunyuan. ⚠️ Licences à DOUBLE ÉTAGE fréquentes (LivePortrait
    « MIT » + InsightFace NC ; Hallo2 « MIT » + S-Lab NC — même contrainte que CodeFormer déjà
    intégré) : toujours décoder LICENSE + README, consigner licence+auteur en base. ⚠️ Candidats
    anciens = venv CUDA séparés (Hallo2 figé CUDA 11.8 ; Ditto exige TensorRT).
  - **Lien N/A grille** : le gate `_has_engine_select` étant MESURÉ, l'ajout d'un sélecteur de
    modèles à l'avatarizer re-rendra automatiquement applicables model_help/input_match/model_caps.
  - **Arbitrage Fabien 17/08 (soir), précisé le 18/08** : pour le cas (b), **TalkingHead
    (met4citizen) = PREMIÈRE voie à attaquer** (le moins conséquent : rendu navigateur, zéro VRAM
    serveur, visèmes FR, streaming branchable sur le TTS WAMA) — **sans exclure les autres
    candidats** (LiveTalking photoréaliste, composants OpenAvatarChat/LAM) qui restent au banc.
    Pilote à ouvrir : vendoriser three.js + TalkingHead (règle assets LOCAUX, pas de CDN), avatar
    avatar de TEST du repo pour juger (le GLB « scientist » est un chantier SÉPARÉ — MPFB ou
    RocketBox ; ⛔ Ready Player Me FERMÉ le 31/01/2026, vérifié 20/08), pont TTS→audio+texte
    (speakAudio, alignement approché acceptable au pilote), toggle de mode dans l'UI assistant —
    ≈ une session dédiée. Cas (a) : gate de test EchoMimicV3 (rituel GNM : venv isolé, pin,
    mesures VRAM/latence/qualité) avant intégration avatarizer.
- **Bibliothèques UI externes pour la passe visuelle — 21st.dev et assimilés** (question Fabien
  2026-09-07, **décision : on ne fait rien pour le moment**, consigné pour ne pas reperdre la
  discussion). Socle MESURÉ dans `base.html` : **Bootstrap 5.3.0 vendorisé + JS sans framework**
  (ni React, ni Tailwind, ni htmx/Alpine) ; règles qui bornent tout choix : assets **LOCAUX**
  (`memory/reference_offline_assets_local`), UI **auto-générée depuis les métadonnées** (pas de
  HTML par app), **zéro duplication** dans `common/`, homogénéité = objectif de design.
  - ❌ **21st.dev** : composants React typés shadcn stylés Tailwind, « Magic MCP » qui génère du
    React → soit introduire React+Tailwind à côté de Bootstrap (contredit les 3 règles), soit
    retranscrire à la main en Bootstrap (= inspiration visuelle seulement). Son apport réel est
    l'esthétique, pas du code réutilisable ici. À garder comme **galerie de référence**, au même
    titre que Mobbin/Godly, pour la card v4 et les volets.
  - ✅ **Voies alignées, par rendement** : ① Bootstrap 5.3 mieux exploité (mode sombre natif
    `data-bs-theme`, offcanvas/toasts/accordéons, utilitaires) — zéro dépendance ; ② un **thème
    Bootstrap open source** déposé en local (Bootswatch ; **Tabler** = le plus proche de l'esprit
    « app dense à volets et cards » ; AdminLTE) ; ③ **web components sans framework** pour les
    briques que Bootstrap n'a pas (Shoelace / Web Awesome, Tom Select pour les sélecteurs riches)
    — vendorisables dans `staticfiles` ; ④ **htmx ou Alpine.js** = choix d'ARCHITECTURE à
    trancher par Fabien, pas un ajout de composant.
  - **Recommandation Claude** : ne rien importer avant d'avoir choisi UNE direction visuelle pour
    le système entier — thème Bootstrap cohérent + **tokens CSS dans `common/`** (c'est
    `CARD_DESIGN §9.3`, différé « fonctionnel d'abord ») appliqués aux cards et aux deux volets,
    puis quelques web components. Point de raccroche naturel : la card v4 (`CARD_DESIGN §11.11`),
    le skill `frontend-design` étant disponible pour cadrer la direction.
  - 🔄 **Tokens et thèmes : chantier OUVERT le 2026-10-17 → `§28`** (déclaration
    `common/themes.py`, valeurs `common/css/wama-theme.css`, card commune portée ; le mode natif
    `data-bs-theme` est son étape 2).

---

## 0. Dysfonctionnements connus — À corriger en priorité

> Niveau statut → suivi déplacé dans `PROJECT_STATUS.md` § « Bugs / dettes connus »
> (contrat des niveaux, 2026-07-20). Contenu d'origine archivé : `docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

## 1. Conformité UI — WAMA App Conventions

> Référence : `WAMA_APP_CONVENTIONS.md` · Règle : ordre boutons `[⚙ Params] [▶ Start] [⬇ DL] [⧉ Dup] [🗑 Del]`

### 1.1 Bouton Dupliquer

✅ Toutes les apps (vérifié ; Composer confirmé 2026-07-03). Table figée archivée :
`docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md` — source vivante : `/apps/`.

### 1.2 Features transversales manquantes
| Feature | Statut | Apps concernées |
|---------|--------|-----------------|
| Import dossier récursif | 🔄 | ✅ Upload de dossier FileManager (webkitdirectory, filemanager.js:1516) + montages locaux/distants (fix CIFS 2026-07-20). **Architecture cible (Fabien 2026-07-20)** : monter un dossier (local ou serveur) puis « Envoyer vers » une app AVEC sous-dossiers depuis le filemanager — pas de zone de dépôt par app ; le studio doit pouvoir consommer ces dossiers. Reste : « Envoyer vers » récursif (dossier entier), et (moins prioritaire) drag & drop de dossier |
| **Zone de staging (« À valider »)** | ⛔ **SUPPRIMÉE** | Décision 2026-06-29 (CARD_DESIGN §8.5) : PAS de staging — la card « nouveau » remplace ce besoin. Cette ligne annonçait à tort une généralisation à 9 apps (corrigé 2026-07-11). |
| **Transcriber — correction manuelle assistée IA** (éditeur onde + heatmap) | 🔄 Phase 1 LIVRÉE | Référence : **`wama/transcriber/TRANSCRIBER_CORRECTION.md`** (inspiré Whispurge/Sonal). Livré : page `/transcriber/edit/<pk>/` + save_correction/save_meta/suggest_speakers/waveform_peaks (`urls.py:29-33`), champs `corrected_segments_json`+`correction_status` (migration 0010), cohérence par segment pour la heatmap. Reste : Phase 2 heatmap (cf. doc de référence). **Fait aussi** : défaut ASR VibeVoice→**Whisper large-v3** (artefact d'ordre, pas benchmark ; diarisation=pyannote ; 10<16 GB) + **word_timestamps** conservés en mémoire/segment (non persistés — pas de `words_json`, cf. §8 Phase 1). À évaluer : WhisperX/Canary-Qwen-2.5B/Granite 3.3 ; réparer Qwen3-ASR. Mener le transcriber au bout avant généralisation. |
| **Architecture UI « card-centric »** (card auto-suffisante + volet droit = inspecteur) | 🔶 Décidée | **Décision projet 2026-06** : voir **`CARD_DESIGN.md`** (§1quinquies preview 3 niveaux + §8.6 zones de dépôt — absorbe `CARD_CENTRIC_UI.md`, archivé `docs/construction/archive/` 2026-07-25). Livré depuis : preview 3 niveaux (1ᵉʳ consommateur transcriber), volet=inspecteur généralisé (5 apps portées, PROJECT_STATUS §21). **Reste** : preview complète dans le volet, sélection en-têtes batch, généralisation aux 5 apps non portées. |
| **Drag & drop appartenance batch** (entrer/sortir une carte d'un batch) | ✅ **2026-09-04** | Brique COMMUNE `wama-queue-dnd.js` (4 gestes + multi-sélection Ctrl/Maj), héritée par les 12 apps. ⚠ **« reste l'UI » était FAUX** : il manquait aussi l'ordre de niveau supérieur — colonne comprise (`QueueOrderMixin.queue_index`, 13 migrations, 6ᵉ tri « Manuel »), un 5ᵉ endpoint (`reorder_queue`), un 6ᵉ (`merge`, fusion STRICTE ≠ `consolidate` qui RANGE par nature), l'exposition des URLs au DOM, l'id de lot des cards unitaires, et l'adoption de la fabrique par l'anonymizer. *Un backend complet pour le geste A ne dit rien du geste B* — cf. `CARD_DESIGN §3bis`. SortableJS écarté (motifs consignés) |

> Lignes ✅ archivées : `docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md` — conformité vivante : `/apps/` (`get_conformity_summary`).

---

## 2. Refactoring — Unification `common/`

> Principe : tout code utilisé par >1 app va dans `wama/common/`. Zéro duplication.

| Élément | Statut | Fichier cible | Impact |
|---------|--------|--------------|--------|
| `keep_loaded` singleton pattern | ⏳ | Généraliser depuis Reader (olmOCR) | Describer, Enhancer (Transcriber sorti de la liste : délégué à `select_model()` depuis 2026-07-24) |


> Briques ✅ archivées (`docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`) — registre vivant :
> `WAMA_APP_GENERATION_ROUTE.md` (l'ancien `COMMON_REFACTORING.md` y est consolidé, archivé `docs/construction/archive/`).
### Templating générique — paramètres & composition (discuté 2026-06-16)

> Constat : l'affichage des paramètres est **hardcodé par app ET par template**
> (modale item/batch vs volet card/batch/file) → divergences inévitables (déjà constatées).

**A. Schéma de paramètres single-source ⏳ (à faire — fort ROI, pilote Transcriber)**
- Décrire les paramètres comme **donnée** (`wama/<app>/params.py` : champs name/type/label/
  help/choices/default/contexts), et **rendre toutes les surfaces depuis un seul moteur**
  commun (`WamaParams.render(container, schema, {context, values})` + inclusion Django +
  `WamaParams.read/apply`). Une édition du schéma → répercutée partout.
- Les divergences modale (`name=` pour POST) vs volet (`data-*` + état Django) deviennent des
  **affaires de contexte du moteur**, pas du markup dupliqué. **C'est l'évolution correcte de
  la décision « pas de partial commun »** (le problème était de copier du markup, pas la donnée).

**B. Génération automatique de templates (queues/console/about/help) — REJETÉ tel quel**
- ❌ Pas de **générateur** méta→template : piège « inner-platform » (la config devient un
  template, en pire). Les apps ont des spécificités réelles (édition Transcriber, micro temps
  réel, onglets diarisation, galeries…).
- ✅ **Composition pilotée par capacités** : les méta-infos d'`app_registry` (types d'entrée,
  formats de sortie via converter, modèles via model_manager, boutons d'action, `has_realtime`,
  `has_edit_page`, `instant_preview`…) **paramètrent/assemblent** les briques communes
  (`app_modern_base.html` + partials), elles ne les **génèrent** pas. Incrémental, app par app.

**Ordre** : A (schéma params, pilote Transcriber) → étendre `app_registry` (capacités) →
composition par capacités. Voir aussi §10.B (Translator) et §5b (sélection/descriptions).

**État 2026-07-01 + TÂCHE 1 (consolidation) :** A est **partiellement** déployé et les divergences
prévues sont **réelles** → il faut les inventorier avant d'en porter d'autres :
### État des mécanismes d'UI — voir PROJECT_STATUS §20 (source vivante)

Bloc d'état 2026-07-11 archivé (`docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`). Corrections vérifiées 2026-07-20 :
- `UI_MECHANISMS_CONSOLIDATION.md` archivé (`docs/construction/archive/`, 2026-07-22) — consolidé dans
  `WAMA_APP_GENERATION_ROUTE.md` (facettes F1–F8). Reste = **dérouler** cette route (= H1.1 des Horizons).
- Plan « templating générique » (décision 2026-06-16 ci-dessus) : le volet **A est LIVRÉ**
  (`params.py` par app + `wama-params.js`/`WamaParams` + `initFromSchema` — vérifié 2026-07-20,
  briques présentes dans `common/static/common/js/`) ; ne restent que les convergences par app.
- Toujours ouvert : trancher le mécanisme de volet (initFromSchema vs render(panel)) pour
  synthesizer/avatarizer/composer ; `show_if` hardcodé enhancer à remplacer (WamaModelCaps
  niveau-champ) ; params.py anonymizer/imager consommés seulement par `apps.py` (détail
  inspecteur) — pas encore rendus par `WamaParams`.

---

## 3. Media Library

> ✅ Phases 1-4 + connecteurs providers **livrés** — état vivant : `PROJECT_STATUS.md §9`
> (NB divergence corrigée : Pexels/Openverse marqués ⏳ ici étaient livrés, vérifié 2026-07-09).
> Détail d'implémentation archivé : `docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`. Reste ouvert (repris tel quel) :

### Phase 5 — Connecteurs avancés (restants) ⏳
- Unsplash · ccMixter (musique CC) · Mozilla Data Collective (voix, si API stable)
  — Pexels/Openverse retirés : livrés (PROJECT_STATUS §9)

### Phase 6 — Intégration cross-apps ⏳
- Imager : sélecteur image de style depuis médiathèque
- Avatarizer : sélecteur portrait de référence

## 4. Intégrations modèles AI — Ollama

> ✅ **Livré** (modèles installés, sélection par tier, wama-dev-ai opérationnel) — état vivant :
> `PROJECT_STATUS.md §2/§3`. Détail archivé : `docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

## 5. Model Manager — Phase 2 : Veille automatique modèles

> Idée proposée le 2026-04-07. Complexité estimée : 2-3 semaines.

### Concept
Tâche Celery nocturne qui compare les modèles installés dans WAMA avec les dernières
versions disponibles sur HuggingFace Hub et Ollama, et génère un rapport de recommandations.

### Architecture envisagée
```
Celery beat : 0 2 * * *
  → model_watcher_task()
      ├── Lire model_registry.py (source de vérité WAMA)
      ├── Interroger HF API (httpx) : /api/models?author=<org>&sort=lastModified
      ├── Interroger Ollama API : GET /api/tags (local) + ollama.com/library (scraping)
      ├── Comparer versions : installé vs. disponible
      ├── Classifier complexité d'intégration :
      │     drop-in      → même famille, même architecture (ex: gemma3 → gemma4)
      │     new-backend  → nouveau format mais compatible pipeline (ex: qwen3-vl)
      │     arch-change  → rupture d'architecture (ex: diffusers → gguf)
      └── Générer rapport JSON + notification admin Django
```

### Champs du rapport
```json
{
  "date": "2026-04-08",
  "updates": [
    {
      "current_model": "deepseek-coder-v2:16b",
      "proposed_model": "qwen3-coder:30b",
      "reason": "Meilleure qualité code + contexte 256K vs 48K",
      "integration_complexity": "drop-in",
      "disk_delta_gb": +9,
      "vram_delta_gb": -5,
      "wama_files_to_modify": ["wama-dev-ai/config.py", "wama/views.py"],
      "validation_required": true
    }
  ]
}
```

### Prérequis
- `httpx` (déjà en dépendances)
- Section "Veille modèles" dans l'interface `model_manager/`
- Système de notification admin Django (email ou dashboard)

---

## 5b. Model Manager — Fiabilité du catalogue + sélection centralisée

> Décidé 2026-06-16. **Le catalogue est la source de vérité ; s'il ment, il trompe
> l'utilisateur (page de gestion).** model_manager = cerveau/données ; common = glu.

> **Restes repêchés du handoff `REPRISE_2026-08-04`** (archivé 2026-08-18, `docs/construction/archive/`) —
> jamais repris ailleurs : ① `_PLAFOND_TIER` (plafonds VRAM des tiers LLM) reste EN DUR dans
> `common/utils/llm_utils.py`, calibré pour CE PC — à sortir en constantes/configuration ;
> ② `vram_gb` des modèles Ollama devrait se lire depuis `ollama list` plutôt que `/api/show`
> (budget faux) ; ③ motif **`select_progressif`** (répondre tout de suite avec un modèle léger
> pendant que le meilleur se charge en parallèle — exige un microservice) : idée consignée dans
> le seul handoff, jamais tracée comme chantier.

### Fiabilité de la découverte — « constater, ne jamais deviner » (FAIT)
- **Bug whisper corrigé** : la détection devinait `faster-whisper-{model_id}` (=`...-large`)
  au lieu du réel `faster-whisper-large-v3` → faux négatif. Désormais via
  `_check_hf_model_downloaded("Systran/faster-whisper-<variante dérivée du hf_id>")`. ✅
- **Bug description Ollama corrigé** : `ollama list` a les colonnes `NAME ID SIZE`, le code
  prenait `parts[1]` (=ID) comme taille → `Ollama LLM (<hash>)` + `ram_gb=0`. Parsing
  robuste par regex (`\d+ (GB|MB|TB)`) + `disk_gb`/`ollama_id` dans extra_info. ✅
- **Principe à appliquer partout** : détecter par contenu (helper/`glob`/cache HF), jamais
  par reconstruction de nom. Audit fait : les autres apps utilisent déjà le helper/`glob`.

### Réconciliation automatique (FAIT)
- **Périodique (Celery Beat)** : `sync_models` toutes les `MODEL_SYNC_INTERVAL_SECONDS`
  (défaut 2 h, paramétrable/env), queue `default`. ✅
- **Au démarrage** : `model_manager.apps.ready()` dispatche une réconciliation non bloquante,
  dédupliquée multi-process (verrou cache Redis), prod-compatible (≠ `RUN_MAIN`). ✅
- **Watcher** : dev/`runserver` uniquement (prod couverte par démarrage + Beat). ✅
- **Commande `verify_models`** : rapport dry-run des écarts catalogue↔disque. ✅
- **Cache `transcriber_backends_info`** vidé au `ready()` du transcriber (descriptions
  fraîches après redémarrage, sans vidage manuel). ✅

### À NE JAMAIS faire / à robustifier (⏳)
- **Ne jamais auto-supprimer les orphelins d'une source RÉSEAU sur « non découvert »** :
  Ollama tourne **côté Windows, hors WAMA** ; s'il est injoignable un instant → 0 découvert
  → un `clean=True` aveugle **viderait le catalogue**. → `clean=False` conservé.
- **(b) Clean gardé** : ne supprimer les orphelins d'une source que si **sa** découverte a
  réussi (liste non vide). ⏳
- **(c) Normaliser les tags `:latest`** dans la découverte Ollama (canon = sans `:latest`)
  pour éliminer les doublons (`mxbai-embed-large` + `mxbai-embed-large:latest`). ⏳
  (entremêlé avec la gestion des orphelins → à faire ensemble)
- **Modèles RECOMMANDÉS / non téléchargés à conserver** : la veille wama-dev-ai (§5/§6)
  produira des cartes de modèles **recommandés** (non présents sur disque, à télécharger à
  la demande admin). Le catalogue doit les **conserver** malgré la réconciliation → prévoir
  un statut/flag (`recommended`/`keep`, distinct de `is_downloaded`) que `clean` ne touche
  jamais. **À concevoir avec le système de veille.**

### Emplacements & catégories des modèles (chantier — récurrent depuis le début)
**Cause racine des mauvais emplacements / doublons** (constaté : `speech/kokoro`=4.9 Go,
`vision/sam`=3.6 Go gonflés de modèles étrangers — Qwen3-ASR, olmOCR, musicgen, pyannote, t5) :
`os.environ['HF_HUB_CACHE']` est **global au process** mais muté par-modèle et **lu en
concurrence par plusieurs threads** (le thread de préchargement Kokoro le pose à `kokoro_dir`
pendant qu'un autre thread charge pyannote/qwen/olmOCR → tout atterrit dans kokoro). Le
`try/finally` de restauration **n'est pas thread-safe**. + dépendances partagées (t5, bert)
dupliquées par app.
**Déclencheur principal supprimé (FAIT)** : le thread de préchargement Kokoro (mutateur
concurrent de l'env) a été retiré (vocalisation → microservice TTS). Sans concurrence, les
mutations d'env restantes sont séquentielles → risque de re-dump déjà fortement réduit.

**Dédup/migration FAIT** : commande `dedup_models` (dry-run par défaut ; `--apply` supprime
les doublons en gardant ≥1 copie ; `--move-misplaced` déplace, jamais supprime). Exécutée :
~9,56 Go récupérés (musicgen/t5/kokoro doublons) + 4 pyannote déplacés `speech/kokoro`→
`speech/diarization` (là où le diariseur les attend). ✅

**Fix durable systémique (⏳ — à faire délibérément, design validé 2026-06-17)** — distinguer :
- **Modèles principaux (catalogue)** → restent **catégorisés** `models/{category}/{family}/`
  via `cache_dir=` explicite (thread-safe). La catégorisation est PRÉSERVÉE.
- **Sous-dépendances transitoires** (t5, bert, tokenizers tirées en interne par un pipeline,
  PAS dans le catalogue, partagées entre modèles) → un **cache partagé unique**. La lib ne
  les route que par la var d'env HF → poser **`HF_HOME` UNE SEULE FOIS au démarrage** sur
  `AI-models/cache/huggingface/` (jamais re-muté par-modèle) → fin de la course env.
- Résultat : modèles bien rangés par catégorie + sous-deps regroupées (pas éparpillées).
  NB : `cache_dir=` est déjà passé dans la plupart des backends ; reste à retirer la mutation
  per-modèle de `HF_HUB_CACHE` et poser `HF_HOME` au démarrage.

> **🔄 ÉTAT MESURÉ le 2026-09-03 — le socle EXISTE, la dette est ailleurs.**
> `HF_HOME`/`HF_HUB_CACHE`/`HUGGINGFACE_HUB_CACHE` sont **déjà posés une fois au démarrage**
> (`wama/settings.py:165-167`, en `setdefault` vers `AI-models/cache/huggingface`) et **rien
> ne les neutralise** — aucun export HF dans `.env` ni dans `start_wama_prod.sh` (vérifié).
> Le reste du chantier est donc uniquement le RETRAIT des mutations per-modèle :
> **38 lignes mesurées** (inventaire par AST, bacs à sable exclus), **37 après le 1ᵉʳ pas**.
>
> **⚠⚠ Le partage principal/sous-dépendance est PROUVÉ, pas supposé** (sonde non destructive
> sur `table-transformer`, process jetable) : le modèle PRINCIPAL se résout par `cache_dir=`
> (il est absent du cache partagé et le chargement passe), le **backbone timm** se résout par
> `HF_HUB_CACHE` (chargement en `LocalEntryNotFoundError` quand on pointe la variable sur un
> dossier vide, `cache_dir=` inchangé). *La var d'env emporte les sous-dépendances dans le
> dossier du modèle principal — c'est le mécanisme exact du défaut.*
>
> **1ᵉʳ pas livré** : `common/backends/table_transformer_backend.py` — mutation retirée,
> test sur poids réels **6/6 `OK` avant ET après**. Résidu créé par l'ancien routage :
> `REMOVAL_LEDGER R47`.
>
> **Garde livré** : `wama/common/tests/tests_hf_cache_routing.py` — compte les mutations **par AST**
> (un grep compterait les mentions en commentaire), budget **37**, **ne peut que descendre**,
> et vérifie que le socle pose bien les 3 variables. ⚠ Il TRIE, il ne conclut pas : « pas de
> `cache_dir=` dans la fonction » ≠ « non retirable » — chaque site se lit (triage : 12 lignes
> avec `cache_dir=` dans la même fonction, 25 sans).
>
> *Trois traces antérieures du même défaut, à citer si quelqu'un doute de l'enjeu* :
> `wama/views.py:223` (dump de modèles dans speech/kokoro), `start_wama_prod.sh:271`
> (`--workers 1` du service TTS déclaré STRUCTURANT à cause de cette course), et la commande
> `dedup_models` née comme « séquelle de la course `os.environ['HF_HUB_CACHE']` ».
>
> **🔴 CAUSE RACINE RETIRÉE le 2026-09-03 (soir) — elle était DOCUMENTAIRE.** `AGENTS.md`
> **prescrivait** la mutation comme « pattern obligatoire » tout en se déclarant transitoire :
> tout nouveau modèle réintroduisait donc le défaut **en étant conforme**. Le pattern est
> désormais `cache_dir=` seul, muter l'environnement est explicitement INTERDIT, et la ligne
> « laisser un modèle se télécharger dans le cache partagé = interdit » a été retirée — elle
> était FAUSSE pour les sous-dépendances, et c'est cette confusion qui justifiait la mutation.
>
> **DÉTECTEUR livré** : `manage.py check_model_layout` — « aucun snapshot ÉTRANGER dans un
> dossier de famille ». Il regarde le DISQUE, donc **sans GPU ni test par backend** : décisif,
> puisque **aucun des 18 backends porteurs d'une mutation n'a de test de chargement sur poids
> réels** (mesuré). C'est lui qui rend le portage prouvable — retirer, lancer l'app, rebalayer.
> Mesure à la livraison : **8 étrangers → 5** (restent `t5-base`/`t5-large` dans
> musicgen/audiogen, `Qwen2.5-1.5B` dans vibevoice, `resnet18` dans table-transformer) ; les
> composants légitimes sont DÉCLARÉS dans `common/utils/model_locations.COMPOSANTS_DECLARES`.
> Il révèle aussi **22 verrous `.locks` orphelins** — dont **11 dans `speech/kokoro`** — qui
> datent les contaminations passées : *on a nettoyé, la cause est restée, ça a repollué.*
>
> **Reste, dans l'ordre** : ① la brique commune côté CHARGEMENT (11 résolveurs maison
> coexistent, `model_dir()` ne sert que l'installeur) ; ② les 37 mutations ; ③ le ménage des
> 5 étrangers, APRÈS le portage de leur backend.
>
> ✅ **MESURÉ le 2026-09-14 — ② et ③ sont SOLDÉS** (le bloc ci-dessus est l'état du 03/09) :
> budget de mutations **0** (`tests_hf_cache_routing`, par AST, jeton compris) ; importer
> `wan_video_backend`/`hunyuan_video_backend` ne touche plus l'environnement (même test) ;
> `check_model_layout` : **aucun snapshot étranger**. **① reste** : les résolveurs maison côté
> chargement — les six `setup_hf_cache_for_*` de l'imager (ils ne rendaient plus qu'un chemin,
> AUCUN appelant dans le code versionné ; la jumelle `imager_01`, non versionnée, garde sa copie)
> sont retirés ce jour (`REMOVAL_LEDGER R61`).
> ⚠ **Relevé, NON corrigé** : `model_manager/services/bench.py:84-89` charge un candidat du banc
> par `hf_id` SANS `cache_dir=` — un modèle PRINCIPAL qui atterrirait dans le cache partagé
> (levier A non tenu) ; `model_manager/services/benchmark_sync.py` y tire des JEUX DE DONNÉES
> de classement (pas des modèles : hors du périmètre de la règle, à confirmer).
> ⚠ Soldé ≠ mort : les FAMILLES Wan (FastWan 2.2, 23 Go au catalogue) et Hunyuan
> (HunyuanImage 2.1, 50 Go) sont vivantes ; seules les classes VIDÉO sont `DEPRECATED`.

**Chemins dérivés de la CATÉGORIE** (⏳) : `models/{category}/{family}/` où `category` =
`ModelType` (source unique, model_manager). Helper unique `model_dir(category, family)` →
`MODEL_PATHS` + `model_config` + découverte + `cache_dir=` en sortent.
- **Enums `ModelType` unifiés** : `services/model_registry.py` avait déjà `MUSIC`/`OCR` ;
  ajoutés à l'enum DB `models.py` (migration 0004). ✅
- **Renommer pour coller à la catégorie** : `vision-language`→`vlm`, `reader`(=nom d'app)→`ocr`.
  `music` est déjà correct. YOLO garde sa nomenclature interne dans `vision/yolo/`. ⏳
- Speech reste une catégorie large (familles whisper/kokoro/diarization/qwen_asr) — **pas** de
  sous-catégorie TTS/ASR (peu de modèles, couche d'orga inutile à cette échelle).

### 🎛 Gouvernance des ressources (GPU/CPU/RAM) — `common/services/resource_governor.py`

> **DOMICILE UNIQUE de toute logique d'allocation.** Créé 2026-07-29 pour arrêter la dispersion
> (plafond CUDA posé sur UN chemin de chargement, registre d'unloaders local à un process,
> sérialisation GPU cachée dans un flag CLI de `start_wama`). Si tu cherches « où
> limiter/réserver/prioriser » : ce fichier, et nulle part ailleurs.

**Décision d'architecture — PAS d'outil externe (analysé 29/07/2026).** Ray / Slurm / Triton /
Kubernetes+Kueue ont été confrontés au besoin réel. La sérialisation GPU **existe déjà** (worker
`gpu` en `--pool=solo --prefetch-multiplier=1` : une tâche à la fois, 11 apps et tous utilisateurs
confondus). Le manque n'est pas un ordonnanceur mais le fait que ce verrou est **invisible, non
priorisable et percé**. Empiler un second runtime pour de la sémantique que Celery+Redis expriment
déjà coûterait plus qu'il ne rapporte. **Ray redevient le bon choix au passage multi-GPU /
multi-nœuds (R760xa)** — d'où l'intérêt de tout centraliser ici : la bascule se ferait dans ce
fichier, pas dans les 11 apps.

**✅ Livré 2026-07-29**
- `configure_cuda_process()` — plafond allocateur CUDA (95 % du physique) **par PROCESS**, câblé
  aux 3 familles : signal Celery `worker_process_init` (`wama/celery.py` — couvre le pool `solo`
  ET chaque enfant `prefork`), `common/apps.py::ready()` (workers gunicorn), `startup` du service
  TTS. Corrige le défaut de la v1, posée dans `MemoryManager.apply_memory_strategy` : elle ne
  couvrait que la voie diffusers de l'imager, alors que transcriber/vibevoice, reader/olmocr,
  describer, avatarizer et imager ltx/cogvideox font `.to('cuda')` en direct.
- **Registre VRAM PARTAGÉ (Redis)** — `reserve_vram` / `release_vram` / `reserved_gb` /
  `effective_free_gb`, visible de **tous** les process. Comble l'angle mort identifié : le service
  TTS (uvicorn:8001) détient de la VRAM hors du verrou Celery et échappait au reclaim. TTL
  d'expiration + purge des lignes d'un process mort sans libérer (kernel panic, kill -9).
- `ensure_free_vram()` consulte désormais ce registre (`MemoryManager._free_vram_gb`) : le pilote
  seul ne voit que le présent et ignore qu'un autre process s'apprête à prendre 18 Go.

**✅ Complété 2026-08-12 — le registre dit désormais QUOI, pas seulement COMBIEN**
- La clé d'owner porte le **modèle** (`<backend>:<pid>#<model_key>`) : le registre ne savait dire
  que « tel backend détient 8 Go dans tel process ». La clé catalogue se reconstitue sans table de
  correspondance (`AIModel.model_key` = `<source>:<model_id>`, `_app_of()` + `_current_model`).
  Séparateur `#` car les clés catalogue contiennent des `:` (`anonymizer:yolo:yolo11n.pt`).
  🔴 **CONSTAT PÉRIMÉ depuis le 2026-09-08 — MESURÉ le 2026-09-14.** `_app_of()` déduit la source
  du CHEMIN du module (`common/backends/base.py`) ; depuis `397cbe25` (« 11/11 au substrat ») tous
  les backends vivent sous `wama/common/backends/`. Mesure en lecture seule sur la base : **les
  101 modèles qui résolvent un backend publient `common:<id>`, 0 rejoint sa clé catalogue** ; le
  registre vivant portait `…KokoroOnnxBackend:9777#common:kokoro-onnx` quand le catalogue connaît
  `synthesizer:kokoro` et `huggingface:onnx-community/Kokoro-82M-v1.0-ONNX` (source ET identifiant
  divergent). Effets : `prefer_loaded`, le `is_loaded` rabattu du model_manager et
  `_overlay_residency` ne voient plus aucun backend du contrat ; l'unloader s'enregistre sous
  `common`, donc « décharger un modèle inactif » décharge TOUS les backends du process.
  ⚠ Le lien modèle → backend est sain (`backend_for_model` : moteur déclaré + `SUPPORTED_MODELS`) ;
  c'est le chemin INVERSE — la publication au registre — qui n'a pas suivi le déménagement.
  ✅ **Corrigé le 2026-09-14 (soir, GO Fabien).** Le backend publie ce qu'il sait — sa classe (déjà
  dans l'owner) et `@<nom local>` — et la clé se résout à la LECTURE
  (`backends.manager.catalog_keys_for_owner`) : le service TTS publie mais n'a pas d'ORM, tous les
  lecteurs de résidence en ont un. Règle = la moitié inverse du lien de `backend_for_model` : parmi
  les modèles que la classe exécute, celui que le nom désigne (identifiant, dernier segment,
  `hf_id`, fin de `hf_id`) ; une classe à un seul modèle le désigne d'office (23 classes sur 34).
  Le reclaim passe au grain du MODÈLE (`unload_live_backends`) : `release_vram(exclude=…)` épargne
  de nouveau le propriétaire. Détail : `PROJECT_STATUS §PALIER 2026-09-14 (soir) « CLÉ »`.
- `resident_models()` → `model_key` → Go, et `idle_models(seuil)` via `mark_used()` émis par
  `_wrap_process` (hash Redis **séparé** `wama:vram:last_used` : un 3ᵉ champ dans la ligne de
  réservation aurait été lu comme illisible → périmé → **purgé**, effaçant une réservation vivante).
- **Lecteurs branchés** : `select_model(prefer_loaded=True)` — inerte jusque-là, car
  `AIModel.is_loaded` n'est écrit par personne et un singleton Python ne traverse pas les process —
  et `api_models_db` / `api_idle_models`. Rabattu à la **LECTURE**, jamais écrit en base : un
  booléen en base resterait bloqué à `True` si un worker mourait en tenant un modèle.
- **Le service TTS déclare enfin** (il ne posait que `configure_cuda_process`, qui borne son process
  sans informer les autres) : empreinte mesurée + battement 10 min, faute de quoi un modèle résident
  sans limite de durée — Kokoro depuis le 12/08 — verrait sa ligne expirer au bout d'une heure.
- ⚠ **Reste** : le DÉCLENCHEMENT du déchargement demeure intra-process (`release_vram()` itère les
  unloaders du process courant), donc « Clean Idle » depuis le web ne peut pas décharger un modèle
  tenu par un worker Celery. Canal de requête inter-process : conçu, non implémenté.
- **Priorités CÂBLÉES** (2026-07-29) — `APP_TIERS` (paliers nommés `lab` / `haute` / `normale` /
  `basse`) + `celery_priority_for()`, injectées dans `CELERY_TASK_ROUTES` et activées par
  `CELERY_BROKER_TRANSPORT_OPTIONS = {queue_order_strategy: 'priority', priority_steps: …}`.
  **WAMA-Lab prioritaire** : cam_analyzer/face_analyzer passent devant tout, imager en dernier.
  ⚠ **PIÈGE MAJEUR — dans le transport Redis la priorité est INVERSÉE : `0` = LE PLUS
  PRIORITAIRE** (Kombu crée une liste par palier et consomme la première non vide), à l'inverse
  d'AMQP où 9 est le plus prioritaire. Une première version de la table écrivait `cam_analyzer: 9`
  en croyant le prioriser — c'était exactement l'inverse. D'où les **paliers NOMMÉS** : plus aucun
  nombre n'est écrit à la main, `celery_priority_for()` est le seul endroit qui connaît
  l'inversion. `priority_steps` et `sep` doivent rester identiques producteur/consommateur (tout
  vient de `settings.py`, donc garanti).
  ⚠ **La priorité RÉORDONNE la file, elle ne PRÉEMPTE PAS** : le worker `gpu` étant en
  `--pool=solo`, une tâche imager déjà EN COURS n'est pas interrompue par l'arrivée d'une tâche
  lab — celle-ci passe devant les tâches en ATTENTE.
- **Déclaration AUTOMATIQUE des empreintes** (`common/backends/base.py`) : `__init_subclass__`
  enveloppe les `load()` / `unload()` de **toute** sous-classe de `BaseModelBackend`, présente et
  à venir — un backend futur hérite du mécanisme sans que personne n'y pense. L'empreinte
  déclarée est **MESURÉE** (delta `torch.cuda.memory_allocated()`), avec repli sur
  `recommended_vram_gb` si la mesure n'est pas concluante (< 0,1 Go = chargement paresseux) ; la
  mesure prime volontairement sur le déclaratif, puisque c'est l'écart preset 16 Go / réel 38,1 Go
  qui a fait paniquer le noyau le 29/07. N'enveloppe que les méthodes définies par la classe
  elle-même (sinon un héritage à 2 niveaux — imager : Base → ImagerBase → concret — compterait
  l'empreinte deux fois). Aucune erreur du gouverneur ne peut faire échouer un chargement.
- 22 assertions (registre multi-process, non-double-comptage au rafraîchissement, purge des
  périmées, tolérance aux lignes corrompues, idempotence, enveloppe des backends, héritage à
  2 niveaux, chargement en échec).
  🔴 **INTROUVABLES le 2026-09-14** : aucun `tests*.py` versionné n'appelle `reserve_vram`, ne lit
  `wama:vram:*` ni n'enveloppe un backend pour observer le registre. Même constat pour les
  « 14 assertions » du routage ci-dessous. Première garde versionnée du registre :
  `wama/common/tests/tests_vram_ledger.py` (2026-09-14).

**✅ Revérifié et réparé 2026-09-14 — la COMPTABILITÉ** (cartographie approfondie demandée par
Fabien avant d'activer `vram_needed` ; détail et mesures : `PROJECT_STATUS §PALIER 2026-09-14
« GOUVERNEUR »`)
- **Double comptage soldé.** Le registre ne distinguait pas une ANNONCE (posée avant d'allouer :
  sous-processus, juge de prospection, embedder) d'une empreinte MESURÉE après chargement
  (`_wrap_load`). `effective_free_gb`, `MemoryManager._free_vram_gb` et `get_free_vram_gb`
  retranchaient tout, résidents compris, alors que leurs sondes les voyaient déjà. Désormais le
  hash séparé `wama:vram:allocated` (owner → pid) marque les empreintes mesurées par l'allocateur
  torch, et `unseen_reserved_gb(probe)` ne rend à chaque sonde que ce qu'elle ne voit pas :
  `'driver'` → les annonces ; `'process'` → tout sauf les empreintes de ce process. Ollama hôte,
  sous-processus et valeurs déclarées restent des annonces (prudence : sous WSL2, ce que
  `mem_get_info` voit des allocations de l'hôte n'est pas mesuré). L'exclusion
  `celery-gpu:<pid>` (clé jamais publiée) et `MemoryManager.vram_owner()` sont retirées. La piste
  `min(libre pilote, total − réservé)` notée le matin même a été ÉCARTÉE : elle surestimait le
  libre dès qu'une annonce coexistait avec une occupation hors registre.
- **TTL : un détenteur vivant ne perd plus sa ligne.** Battement commun
  `base.start_reservation_heartbeat` — service TTS ET `worker_process_init` des workers Celery,
  qui n'en avaient pas ; `vram_reservation` rafraîchit sa ligne tant que le bloc dure (audio.cpp
  dépassait le TTL) ; la réservation du rappel mémoire expire avec la résidence Ollama
  (`expires_in_s`, 5 min) au lieu de survivre une heure ; `MemoryManager.unload_model('ollama:…')`
  et olmOCR retirent la ligne du modèle qu'ils déchargent (convention unique `ollama_host_owner`) ;
  la résidence Ollama est rafraîchie toutes les 10 min (tâche `model_manager.refresh_ollama_residency`,
  beat) — la synchro du catalogue seule tournait toutes les 2 h, au-delà du TTL.
- **Inactivité.** Libérer ou purger une ligne emporte usage, marqueur et chargement : un modèle
  rechargé n'hérite plus de l'inactivité de sa vie antérieure ; un modèle jamais utilisé compte son
  inactivité depuis son CHARGEMENT (`wama:vram:loaded_at`), plus depuis l'horodatage que le
  battement réécrit.
- **`_wrap_load`.** Un rechargement idempotent garde la valeur mesurée (la déclarée l'écrasait) ;
  rien n'est réservé dans un process sans CUDA ni pour un backend qui se déclare sur CPU ; un
  `load()` refusé ne rend plus le backend résident. Un `unload()` qui lève GARDE sa ligne — voulu :
  rien ne prouve la VRAM rendue.
- **Gardes** : `wama/common/tests/tests_vram_ledger.py` (22 tests, sans GPU). Non-vacuité prouvée par
  3 mutants réinjectant chaque défaut (double comptage 7 rouges, libération sans annexes 4,
  ancienne logique `_wrap_load` 4) — la contre-épreuve a d'ailleurs révélé deux tests qui
  bouclaient sur la constante du code testé, corrigés.
- 🔴 **NOMMÉ, NON CORRIGÉ** :
  ① ~~**clé de modèle publiée** `common:<id>` pour les 101 modèles résolus (constat ci-dessus) —
    correctif GLOBAL : la clé doit venir du catalogue, pas du chemin du module~~ ✅ **corrigé le
    même soir** (résolution à la lecture, reclaim au grain du modèle — constat ci-dessus) ;
  ⓟ **provenance de la VRAM — ✅ le même soir (GO Fabien)** : la mesure au chargement est rendue
    au catalogue dans un champ SÉPARÉ, `extra_info['vram_measured']` (dernière, maximum, nombre
    de relevés, date ; clé collante de la synchro). `vram_gb` reste la valeur déclarée/estimée
    que la découverte réécrit et que le tirage lit. Chaîne : `_wrap_load` (mesure FRAÎCHE
    seulement) → `resource_governor.record_measured_vram` (survit au déchargement) → tâche
    `model_manager.persist_measured_vram` (10 min) → `ModelSyncService.persist_measured_vram`.
    Lecteurs : `check_model_completeness` (sort de `vram_never_measured`, axe `vram_under_declared`
    — les axes portaient des noms français jusqu'au 2026-09-20, traduits en BLOC sur décision de
    Fabien : « on n'introduit pas de français, on traduit l'ensemble »),
    inspecteur du model_manager. Brancher la mesure sur le TIRAGE reste une décision à part ;
  ② ~~le squelette ne pose jamais RUNNING (le commentaire « `progress(0)` bascule l'item en
    RUNNING » de `task_skeleton.py` est faux : `TaskContext.progress` n'écrit que cache et
    `progress`) — un item différé resterait affiché `AWAITING_RESOURCES` pendant son exécution~~
    ✅ **corrigé le même soir** : un item RE-LIVRÉ après un report bascule en RUNNING avant le
    traitement ; un report ANNULÉ entre-temps (plus en `AWAITING_RESOURCES`) n'est pas traité ;
    commentaire rectifié. ⚠ RUNNING reste posé par les VUES au premier lancement — c'est ce qui
    rendait ce défaut invisible sur les cards (`vram_needed` n'étant adopté par personne) ;
  ③ `vram_needed` : 0 appelant — suit le PORTAGE des 7 apps au squelette ;
  ④ « libérer avant de différer » et décharger le service TTS avant une tâche « toute la VRAM » :
    DÉCISIONS, pas réparations. Sur le poste de dev, le revert `1b1546d9` (24/07) a établi que
    décharger JUSTE avant une grosse allocation CUDA (churn sous WDDM) gelait l'hôte ; le service
    TTS n'a aucun endpoint de déchargement et garde Kokoro résident par déclaration
    (`keep_resident`). En Linux natif (la cible), la contrainte WDDM disparaît et la question se
    repose.
    ✅ **TRANCHÉ par Fabien le 16/09** (détail `PROJECT_STATUS §PALIER 2026-09-19 « GOUVERNEUR »`) :
    le déchargement COMPLET (TTS, assistant, résidents des workers) est PERMIS, mais **seulement si
    la VRAM est saturée** — jamais systématique ; sur un serveur de prod suffisamment doté, rien
    n'est déchargé. Séquence : attente `AWAITING_RESOURCES` tant qu'une tâche tourne ou qu'un
    service sert → tout décharger → attendre que le pilote rende la mémoire → exécuter → recharger.
    **Le gouverneur décide, tous les chemins passent par lui** ; les services se DÉCLARENT (occupé ?
    décharger ? recharger ?) — rien n'est câblé en dur, un service futur s'inscrit sans le toucher.
    Deux délais : attente avant démarrage ILLIMITÉE ; contrôle de durée d'un traitement, 30 min par
    défaut, réglable par utilisateur (et par type de tâche). Curseur rapide/qualité généralisé à
    toutes les apps média, « vision » (anonymizer) remonté au commun.
    ⭐ **B RESTRUCTURÉ EN TROIS ÉTAGES (Fabien, 2026-09-20) — et le « tout décharger » REFORMULÉ.**
    Cartographie préalable confrontée aux lignes : le registre partagé sait QUI tient QUOI
    (`resident_models` :358, `idle_models` :577) ; le déchargement existe mais reste LOCAL au process
    (`base.unload_live_backends` :93, `release_vram`/`ensure_free_vram`, `aggressive_cleanup`) — le
    canal inter-process est le trou central ; le service TTS n'a aucun endpoint de déchargement et
    garde ses `keep_resident` ; `_differer_faute_de_vram` ne libère rien, `vram_needed` a 0 appelant ;
    aucune limite de durée nulle part (`time_limit` : 0 occurrence) ; `fits_full_gpu` (R46, 0
    consommateur) porte le test « tiendrait seul ». **Angles morts mesurés** : le repli Kokoro de
    gunicorn charge `KModel` hors contrat (`wama/views.py:254`, aucune ligne au registre) ; les modèles
    hors contrat de `_VRAM_UNLOADERS` ; les DEUX Redis du PC de dev (D) ; et le registre connaît les
    MODÈLES résidents, pas les TÂCHES en cours (lues dans les statuts `RUNNING` des tables d'app).
    **③ reformulé par Fabien** — trois cas, pas deux : (a) le pic ne tient pas même SEUL (> VRAM
    totale) → **non sélectionnable** par l'auto-sélection (filtre sur le pic vs total) et **lancement
    refusé en le disant**, avant tout report ; (b) tient seul, pas maintenant → attente
    `AWAITING_RESOURCES` **automatique et illimitée**, résidences libérées d'elles-mêmes, la card dit
    POURQUOI (qui tient combien) ; (c) libérer TOUTE la carte → **sur demande et acceptation
    EXPLICITES de l'utilisateur** depuis la card en attente (« Libérer la carte et lancer »), jamais
    d'office — la saturation PROPOSE, elle n'autorise plus ; en prod un réglage d'instance restreint
    qui a ce bouton. *Le geste qui pouvait couper la voix de l'assistant à un collègue disparaît.*
    - **B1 — le socle (✅ LIVRÉ le 20/09 pour le commun — détail `PROJECT_STATUS §PALIER 2026-09-20
      « GOUVERNEUR B1 »` ; reste l'ADOPTION : `vram_needed` imager vidéo/composer, `app`/`pk` à
      l'include de card, champ « durée max » du profil ; angles morts Kokoro-gunicorn et
      `_VRAM_UNLOADERS`)** : registre COMPLET (angles morts + ligne « tâche en cours »
      posée par le squelette) ; canal de requête inter-process sur Redis, lu dans le battement déjà
      commun (`start_reservation_heartbeat`, TTS + workers) — un tenant se DÉCLARE en montant le
      battement (nom, occupé ?, résidents à recharger), aucun service en dur ; « occupé » = usage
      < N s (`last_used`) ou verrou déclaré (`_engine_lock` du TTS) ; attente illimitée ; libération
      explicite puis RESTAURATION (le TTS recharge ses `keep_resident`, Ollama/workers au prochain
      usage) ; assistant MUET par drapeau du gouverneur lu par `ai_chat`/`kokoro_tts` (message
      d'attente automatique) ; durée max d'UN traitement (table par type de tâche dans le gouverneur,
      à côté d'`APP_TIERS`, surcharge `UserAppSetting('common', 'max_task_minutes')`, 30 min) —
      `soft_time_limit` à MESURER avec `--pool=solo` avant de choisir, sinon garde-temps du
      squelette ; information systématique sur la card. Adoptants imager vidéo + composer :
      `vram_needed` dépend du pic (sœur) et du portage de ces apps (autres sessions).
    - **B2 — admission et ordonnancement (À CONCEVOIR ICI avec Fabien avant une ligne)** : le worker
      GPU est `--pool=solo` = UNE tâche à la fois, tous utilisateurs, FIFO (les paliers réordonnent,
      n'empilent pas). « Empiler des process en VRAM et jusqu'où », la file de files inter-utilisateurs
      (équité, reste n° 2), le budget PAR MACHINE, la co-résidence de modèles : plusieurs workers GPU
      ou pool concurrent, le gouverneur en guichet d'admission.
    - **B3 — local / cloud** : la brique existe (`select_model(cloud_keys=…)`, distant sans VRAM) ;
      « local saturé → proposer le distant à qui l'autorise » est une POLITIQUE à décider.
    Règle des trois étages : *sans registre complet, canal et information, ni B2 ni B3 ne peuvent
    être justes* — B1 d'abord, jusqu'au bout.

**🔴 Constat du 19/09 — le FILTRE du tirage écarte un modèle qui TIENT sur la carte.** Le filtre
(`model_selector._best_by_vram:241`, `vram_gb ≤ libre`) et le coût (`:248`) lisent le même
`vram_gb`, qui pour CogVideoX (21), Mochi (22), FastWan (23) est une SOMME DE COMPOSANTS. Dès qu'un
résident occupe la carte, ces modèles sont écartés — alors qu'un modèle de 21 Go tient sur une 4090
chargé seul, et tourne en déchargement CPU avec ~11 Go de jeu de travail. La table
`MODEL_SIZE_PRESETS` (qui SAIT que c'est une somme) ne sert qu'aux backends au chargement, jamais au
tirage. **Chantier A (décidé)** : deux chiffres par modèle — poids par composant lus dans les
fichiers sans charger, et pic selon la stratégie — c'est le pic que le filtre compare ; cascade de
provenance mesurée → source → estimée, jamais sous la source ; provenance marquée à la découverte.
Fait au passage : une seule règle de lecture de la table d'empreintes (`get_strategy_for_model` →
`preset_vram_gb`, hunk dans `14983834`, gardes `295c1ceb`).
✅ **Le PREMIER chiffre est au catalogue (19/09 soir, `e071966d` — détail `PROJECT_STATUS §PALIER
2026-09-19 (soir) « CHANTIER A »`)** : `extra_info['weights']` {components, total_gb, largest_gb,
source, variants/unresolved, signature, at} — clé collante, `vram_gb` intact —, écrit par
`ModelSyncService.persist_weights` après chaque `full_sync` et par la tâche beat
`model_manager.persist_weights` (1 h). Chaîne : `model_locations.installed_snapshots()` (hf_id →
snapshot) → `prospector.local_inventory` (blobs, une fois chacun — `7a50d8b6`) →
`model_installer.components_for_spec` (UN lecteur des poids, celui de l'installation ; la composition
DÉCLARÉE tranche, sinon `source='repo'` = borne). Provenance de `vram_gb` marquée à la découverte
(`2264a51c`). Mesuré sur le parc : Hunyuan 49,5/32,5 pour 16 déclarés ; LTX 44,4/24,3 pour 14 ;
Qwen 53,7/38,1 ; CogVideoX 20,2/10,5 ; FastWan 22,5/10,6 ; FLUX 31,4/22,2. ⏳ **Reste** : le SECOND
chiffre (pic par stratégie et dtype, marge 4 Go, `memory_manager`), la migration des mesures de
`MODEL_SIZE_PRESETS`, et le filtre du tirage sur le pic (`peak_offload` = admissibilité ;
`avoid_offload` = vitesse par `peak_full`). ⚠ Ouverts : LoRA sans dorsale déclarée (0,04 Go) ;
dépôts frères pesés par le réseau seul (`unresolved` bien qu'installés) ; les VARIANTES de précision
(cartographie vérifiée au même palier : seul LTX est représenté, FLUX seul se réduit automatiquement,
Kokoro ONNX porte 8 précisions dont 7 inatteignables) — plan validé, à construire sur `_best_by_vram`.

**⏳ Reste — à ajouter ICI, jamais dans les apps**
1. ~~Câbler les priorités dans le routage Celery~~ ✅ 2026-07-29 (ci-dessus, 14 assertions).
   **Reste à valider en charge réelle** : les tests vérifient la résolution du routage, pas le
   comportement du worker face à plusieurs paliers non vides simultanément.
2. **Équité inter-utilisateurs** : FIFO global aujourd'hui → un batch de 50 items d'un utilisateur
   affame tous les autres, y compris le lab. Viser un round-robin sur les items en attente.
3. **Admission CPU/RAM** sur la file `default` (`--autoscale=4,1` sans aucune conscience
   mémoire). D'autant plus nécessaire que WSL2 peut désormais prendre 48 Go et étrangler l'hôte.
   WAMA-Data sera surtout CPU → c'est là que ça se jouera.
4. ~~Appeler `reserve_vram()` aux points de chargement~~ ✅ 2026-07-29 via `BaseModelBackend`
   (ci-dessus). **Restriction connue** : ne couvre que les backends qui héritent de
   `BaseModelBackend` — **9 sous-classes directes** au 29/07 (imager `ImageGenerationBackend`,
   transcriber `SpeechToTextBackend` + `PyannoteDiarizerBackend`, anonymizer `DetectionBackend`,
   enhancer ×2, reader ×2, composer), soit **21 backends concrets**. Les 7 ajouts du 29/07 sont
   venus de **3 classes intermédiaires**, pas de 7 rattachements : `__init_subclass__` enveloppe
   les `load`/`unload` à n'importe quelle profondeur d'héritage — c'est le point de levier.
   **L'héritage ne couvre pas tout** : un modèle chargé dans un **sous-processus** ou un
   **service séparé** n'est résident dans aucun objet Python du worker. Pour ceux-là, la brique
   est `vram_reservation(owner, gb)` (contextmanager, réserve/libère autour du bloc) — adoptée
   par **avatarizer** (MuseTalk, CodeFormer) ✅ 29/07. ~~Reste le **service TTS**, dont la
   déclaration doit venir de l'intérieur du service~~ ✅ **fait le 12/08** (contrat de backend
   DANS le service + battement, cf. ci-dessus — la phrase n'avait pas suivi, relevé le
   2026-09-14). Cf. `PROJECT_STATUS.md` §0 (3bis → 3quinquies).

5. **ADMISSION D'UN MODÈLE ET CHOIX DE LA RÉDUCTION — le gouverneur décide, personne d'autre**
   (schéma demandé par Fabien le 2026-09-20 : « le gouverneur doit déterminer automatiquement
   quelle quantification appliquer », « il faut porter l'information à l'utilisateur pour qu'il ne
   renonce pas à installer un modèle »). Décision A du 16/09 (`PROJECT_STATUS §④A`) pour les deux
   chiffres, prolongée ici par la réduction et l'affichage.

   **a. Trois étages, un seul décideur.** Les FAITS du modèle ne décident de rien ; les CAPACITÉS
   de la machine non plus ; c'est leur rencontre qui décide, et elle a un seul domicile.

   | étage | qui le produit | état au 2026-09-20 |
   |---|---|---|
   | poids par composant, deux pics (somme / plus gros) | `model_installer.components_for_spec` → `extra_info['weights']` | ✅ 34 lignes mesurées |
   | précision par composant (params × octets du dtype) | `prospector.precision_of_files` (en-têtes safetensors) | ✅ livré 20/09 |
   | empreinte MESURÉE au chargement | `base.py:_wrap_load` → registre + `extra_info['vram_measured']` | ✅ mais c'est une RÉSIDENCE (cf. c) |
   | capacité de la machine, VRAM libre réelle | `resource_governor` (`total_vram_gb`, `effective_free_gb`, registre partagé) | ✅ depuis le 29/07 |
   | réductions que le MOTEUR sait appliquer | à DÉCLARER au contrat de backend (cf. d) | ⏳ |
   | la décision | `resource_governor` | ⏳ **c'est le reste** |

   **b. Ce que le gouverneur doit rendre**, en une réponse et non en un booléen :
   `{admissible, strategy, precision, reason, alternatives}`.
   * **admissible** = le pic de la meilleure combinaison (stratégie × précision) que le moteur
     sait appliquer tient sur la carte ENTIÈRE. Pas « tel quel en fp32 ».
   * **tient maintenant** = ce pic tient dans la VRAM effectivement LIBRE ; sinon la tâche
     ATTEND (décision B du 16/09), elle n'est jamais écartée.
   * **une seule marge.** Il en existe quatre aujourd'hui — `full_gpu_budget_gb(4.0)`,
     `fits_full_gpu(4.0)`, `get_memory_strategy(2.0)`, `FULL_GPU_MIN_FREE_GB = 1.5` — et une
     cinquième a failli naître dans le calcul du pic (`ACTIVATION_MARGIN_GB`, retirée le 20/09).
     🔴 **Une marge est une politique de la MACHINE, pas une propriété du modèle** : elle
     s'applique UNE fois, chez le gouverneur, jamais dans un chiffre de modèle.
     ⚠ Et elle ne se justifie PAS par les crashs hôte : le dépôt porte deux hypothèses
     contradictoires (28/08 « la puissance n'est pas le facteur, la montée VRAM l'est » ; rails
     instrumentés qui n'innocentent pas le bloc, onduleur pseudo-sinusoïde, alimentation 1000 W
     commandée). Le seul fait qui parle d'activations est un OOM torch (13/03, 570 Mio manquants
     après 20,34 Go alloués) — et il dit qu'il faut garder de la place, pas combien.

   **c. Le pic d'EXÉCUTION n'est pas instrumenté** — et c'est le trou qui reste sous la décision
   « mesure du pic » déjà actée. `base.py` relève `memory_allocated()` avant/après chargement :
   une RÉSIDENCE. `torch.cuda.max_memory_allocated()` / `reset_peak_memory_stats()` — les deux
   fonctions qui donnent le PIC réel, activations comprises — **n'apparaissent nulle part dans le
   dépôt**. La décision existe, l'instrument manque : l'ajouter autour du GESTE (pas du
   chargement) est le geste minimal, et c'est lui qui rendra la marge mesurable au lieu d'être
   choisie.

   **d. Les réductions — trois familles à ne pas confondre**, parce qu'elles n'agissent pas sur la
   même grandeur (pic = résidence + activations) :
   * **réduire les POIDS** — quantification appliquée LOCALEMENT au chargement (fp8 torchao,
     int8/int4 bitsandbytes) : aucun téléchargement. Ou poids ALTERNATIFS à installer (AWQ/GPTQ,
     GGUF, versions distillées, adaptateurs LoRA « lightning » posés sur la dorsale) : un
     téléchargement, et pour un adaptateur la dorsale reste requise ;
   * **réduire la RÉSIDENCE** — `MODEL_OFFLOAD`, `SEQUENTIAL_OFFLOAD`, group offload : les poids
     ne changent pas, ils ne sont pas tous présents en même temps ;
   * **réduire les ACTIVATIONS** — attention slicing, VAE slicing/tiling, résolution et durée du
     rendu : ni les poids ni la résidence ne changent.
   Le gouverneur choisit la combinaison la plus FIDÈLE qui tient (pas de réduction > bf16 > fp8 >
   int8 > int4 ; plein GPU > déchargement > séquentiel), en ne retenant que ce que le moteur
   DÉCLARE savoir faire — au contrat de backend, comme `recommended_vram_gb`, jamais deviné.

   **e. L'INFORMATION À L'UTILISATEUR** (le point neuf) : un modèle dont les poids pleins ne
   tiennent pas mais dont une variante tient ne doit pas s'afficher comme impossible — sans quoi
   l'utilisateur renonce à l'installer sans savoir. Trois états, DÉRIVÉS (rien à stocker) :
   ✅ tient tel quel (dire par quelle stratégie) · ⚙ tient EN RÉDUISANT (dire laquelle, son coût
   en téléchargement, et la perte attendue) · ⛔ ne tient pas même réduit. S'accroche au verdict
   d'exécutabilité existant (grisage + raison), qui a déjà la règle « sans moteur déclaré = NON
   condamné ».

   **f. Ordre imposé par la mesure — ne PAS brancher le filtre du tirage avant (c) et (d).**
   Relevé du 20/09, budget 20 Go : basculer le filtre sur le pic réadmettrait justement FastWan
   (29 → 14,6), CogVideoX (21 → 14,5) et higgs-audio (24 → 14,8), mais écarterait **à tort**
   LTX-distilled et sa variante fp8 (28,3 — leur transformer pèse 24,3 Go *en fp32 sur le
   disque*, la moitié une fois chargé en bf16), et admettrait `flux-lora-logo-design` à **4,04 Go**
   alors que cette LoRA exige les 26 Go de sa dorsale. Deux défauts neufs contre un défaut connu :
   la précision (d) et l'héritage d'empreinte d'un adaptateur sont des PRÉALABLES, pas des
   raffinements.

   **Décisions à prendre par Fabien** : (1) le schéma `composition` n'a aucun moyen de dire
   « hérite de sa dorsale » — champ à ajouter, ou règle dérivée de `base_model` ? (2) une
   réduction choisie automatiquement doit-elle être MÉMORISÉE par modèle (préférence
   utilisateur) ou recalculée à chaque tirage selon l'état de la carte ?

### Warm-loading VRAM — modèles temps réel chauds (chantier prod)
> But : sur serveur de prod (grosse VRAM), garder chargés les modèles **temps réel**
> (AI-Assistant LLM+vocalisation+traduction, preview synthesizer, speak Transcriber).

**Principe (comme vLLM/TGI/Triton/TorchServe/Ray Serve/Ollama)** : un modèle chaud vit dans
un **service d'inférence dédié persistant**, JAMAIS dans un thread du process Django/Celery
(fork, CUDA par process, course env = nos bugs). WAMA est **déjà à mi-chemin** :
- **Ollama** (LLM) tient déjà les LLM chauds (régler `keep_alive`).
- **Microservice TTS** (`tts_service.py`, port 8001) tient déjà Kokoro/XTTS/Bark préchargés.

**Fix Kokoro (⏳, avec soin — ne pas casser AI-assistant/synthesizer)** : le thread Kokoro de
`wama/views.py` est un **bug d'archi** (la vocalisation AI-assistant recharge Kokoro dans
Django au lieu d'appeler le microservice TTS déjà chaud). → **router la vocalisation vers le
microservice TTS + retirer le thread/`_get_kokoro`**. Élimine la course env ET garde l'instantané.

> ⚠⚠ **CORRECTION 2026-08-31 — ce fix était à MOITIÉ fait, et c'est la moitié manquante qui a
> masqué la panne pendant des mois.** Étape 1 (router vers le service) : ✅ faite le 28/08
> (client commun `common/tts/service_client.py`). Étape 2 (**retirer `_get_kokoro`**) :
> ❌ **jamais faite** — le repli en-process est resté. Or `.env` pose `HTTP_PROXY` sans
> `NO_PROXY` et `settings.load_dotenv()` l'injecte : `requests` proxifiait donc l'appel à
> `localhost:8001`, le proxy UGE répondait sa **page d'erreur HTML**, et CHAQUE vocalisation
> repartait en silence dans le chemin que cette ligne voulait supprimer — ~90 s d'attente et
> une charge GPU dans un worker gunicorn. Constat de Fabien : « je n'ai jamais eu de lecture
> instantanée ». **Prouvé** : même appel, `HTTP 503` + page proxy sans neutralisation,
> `HTTP 200` + JSON du service avec `http_proxy.local_proxies()` (brique généralisée depuis
> `ollama_proxies`, qui portait seule ce geste).
> **Leçon** : *un repli qui remplace silencieusement le chemin réparé cache l'échec de la
> réparation* — le ticket paraissait clos, il ne l'a jamais été en pratique. Le retrait de
> `_get_kokoro` reste à faire, APRÈS validation écran que le chemin normal tient (on ne retire
> pas un filet avant d'avoir vérifié le sol).
> ⚠ La ligne ci-dessus « le microservice tient déjà Kokoro/**XTTS**/Bark préchargés » explique
> le souvenir d'un « XTTS qui prend la relève » : le préchargement réel est `TTS_PRELOAD`
> (kokoro seul → **kokoro-onnx** depuis le 31/08, chargement mesuré **3,3 s** contre **87,9 s**
> pour le `.pt` — et le démarrage ATTEND ce préchargement). L'autre cause possible était un
> `engine_for_model()` qui renvoyait `'coqui'` pour TOUT nom inconnu : **corrigé**, il lève.

**Orchestration (`model_manager`)** : registre des modèles **épinglés/keep-warm** + budget
VRAM + **éviction LRU** des modèles à la demande (s'appuie sur memory_manager/cleaner existants).
**Reclaim VRAM inter-app** : ✅ brique livrée 2026-07-24 (`memory_manager.ensure_free_vram(needed_gb)`
+ registre `register_vram_unloader`, transcriber inscrit via `apps.py`) / ⏳ adoption = 0 appelant
applicatif (le call-site diariseur a été annulé par le revert `6cc37ec`).
Set temps réel : LLM→Ollama, vocalisation/preview→microservice TTS, speak→futur service Whisper
chaud, traduction→Ollama.

### Backup réseau (vrlescot) — ✅ FAIT, 4 domaines + tirage (2026-08-10)
- **Montage WSL en place et éprouvé** : `\\vrlescot\SAVES` → `/mnt/shares/SAVES`. Le point
  « à finir » de cette ligne est clos depuis le 27/07.
- **Moteur unique** `common/services/mirror_sync.py` (`mirror_tree`, `copy_file`,
  `remote_is_available`, `resolve_remote_root`, `purge_keep_latest`, `run_mirror_job`). Aucune
  autre implémentation de copie/miroir dans le projet — ne pas en réintroduire.
- **4 domaines** sous `DEEP_LEARNING/` : `MODELS`, `DB`, `MEDIAS`, `INSTALL` (secrets).
  Planification beat : config 02:20, médias 02:30, base 03:30, **avant** la purge de rétention
  de 04:00. Boutons « Backup DB / Models / Médias » dans les outils système du model_manager.
- **Tirage** : `manage.py restore_backup --domain models|media|config` (= `mirror_tree` dans
  l'autre sens) et `manage.py restore_db` (destructif, CLI uniquement).
- Garde-fous conservés : chemin UNC hors Windows non monté → sauvegarde **désactivée** sans créer
  de dossier-poubelle (constater, pas créer) ; jamais de suppression distante (archive cumulative).
- **Liens symboliques internes — reproduits comme liens, plus recopiés (2026-09-28)**.
  `is_file()` suivant les liens, un dépôt HF sauvegardé pour la PREMIÈRE fois par `mirror_tree`
  voyait chaque poids recopié une seconde fois via son lien `snapshots/` : **58,3 Go mesurés au
  distant, sur 4 dépôts** (FastWan 24,2, MiniMax-Music3 20,6, ACE-Step 10,1, Minimax-h3 3,3). Les
  dépôts plus anciens y portaient déjà de VRAIS liens (créés hors WSL), que le test « même
  taille » sautait. Un lien vers un fichier DE la source est désormais **reproduit comme lien**
  là où la destination l'accepte (disque local), **décrit dans `.wama_links.json`** là où elle le
  refuse — ⚠ c'est le cas du partage distant : il EXPOSE les liens anciens mais refuse d'en créer
  depuis WSL (`EPERM`, mesuré) ; pour la sauvegarde, le manifeste EST le mécanisme. Le tirage
  recrée les liens des deux formes et ne rapatrie PAS les copies pleines d'anciennes passes. Un
  lien vers l'EXTÉRIEUR reste copié (seule copie de sa cible). Tenu par `tests_mirror_sync` (7).
  Nettoyage des doubles déjà partis : `manage.py dedup_remote_links` (simulation par défaut ; un
  double n'est retiré que PROUVÉ — manifeste, ou blob unique de même taille ET mêmes octets de
  tête/queue — après inscription au manifeste ; **aucun blob n'est jamais retiré** : les modèles
  désinstallés restent entiers dans l'archive, décision de Fabien ; `tests_dedup_remote_links`,
  6). ✅ **`--apply` du 28/09 : 77 doubles retirés, 58,3 Go rendus, 0 erreur** ; 2 gardés (Kokoro :
  seule copie ; un GGUF MiniMax : blob désigné d'une autre taille). Revérifié après : les 73 liens
  locaux des 4 dépôts ont une entrée de manifeste vers un blob présent de même taille ; qwen-image,
  hunyuan, bark, chatterbox intacts au distant (54 / 50 / 13 / 13 Go).
  ⚠ **Rectification du même jour** : ce paragraphe annonçait d'abord « 480 liens = 333 Go
  recopiés pour rien, qwen-image 115 Go distants pour 54 » — FAUX : mon relevé faisait un `stat()`
  qui suivait les liens DISTANTS et comptait deux fois chaque poids. La première version du
  correctif, bâtie sur ce chiffre, décrivait tous les liens au lieu de les reproduire : appliquée
  au tirage, elle aurait rendu des snapshots VIDES pour tous les dépôts anciens.
- ⚠ Le dossier `llm/ollama` (lien vers `D:\.ollama`) n'est pas parcouru : `rglob` ne suit pas un
  dossier-lien. Voulu (Fabien, 2026-09-28) : les modèles Ollama se retirent de leur registre.
- Détail et procédure de réinstallation : **`PROJECT_STATUS.md` §42**.

### Sélection centralisée — `services/model_selector.py` (FAIT, étape 3 ⏳)
- `select_model(source, *, model_type, requires, classes, prefer_loaded, downloaded_only,
  vram_budget_gb, candidates, name_contains, priority, availability_probe)`.
- 3 concerns distincts : **téléchargé** (catalogue) ≠ **`availability_probe`** (dispo runtime,
  ex. import Python OK) ≠ **VRAM** (`get_free_vram_gb`). + règle **keep_loaded**.
- `priority` (préférence ordonnée, domine la VRAM) pour les apps « par moteur » (Transcriber
  whisper-first) ; logique VRAM-greedy (le plus gros qui tient) pour les apps « par variante ».
- **Descriptions à deux tiers** : `AIModel.description` (long) + `description_short` (court),
  dérivation auto, migration 0003. `WamaModelHelp` : court sous le sélecteur + long en ⓘ.
- **Étape 3 (🔄)** : 2 adopteurs — **composer** (2026-07-21, auto-model VRAM-greedy,
  `utils/auto_model.py`) + **transcriber** (2026-07-24, `backends/manager.py` via `priority`
  whisper-first — contrairement au plan initial qui l'excluait). Reste : app par-variante
  (describer/imager) + faire de l'anonymizer `ModelSelector` un fin adaptateur.

### Capacités des modèles → filtrage UI + sélection + cross-app (⏳ — unifié avec ci-dessus)
> Décidé 2026-06-17. **Pas un quick-win** : nécessite un schéma de **capacités par modèle**.
Définir, dans le catalogue (`AIModel.extra_info` ou champs dédiés), les **capacités** de chaque
modèle : `supports_cloning` (voix custom), `languages` supportées, modalités, taille/qualité,
aptitude par tâche… **Source UNIQUE** consommée par :
- **Filtrage UI dynamique** : n'afficher que les voix/langues **compatibles** avec le modèle
  choisi (ex. masquer « Mes voix » si le modèle ne clone pas ; restreindre les langues).
  Concerne **synthesizer** (voix/langues), **avatarizer** (voix TTS), **ai-assistant**
  (voix de vocalisation + capacités LLM), potentiellement **imager** (capacités modèle).
- **Sélection intelligente par tâche** (`select_model` + `requires`/capacités).
- **Description dynamique** (`WamaModelHelp`) déjà branchée.
→ À faire **en même temps que le model_manager intelligent** (mêmes métadonnées). Exposer via
l'endpoint catalogue + un helper commun `WamaModelCaps` (front) qui filtre les `<select>`
dépendants au `change` du modèle. Lié à [[project-assistant-vision]] (TTS auto-select).

---

## 6. wama-dev-ai — Phases

> Principe : Claude réfléchit · wama-dev-ai exécute · L'humain valide

### Phase 1 — Audit read-only 🔄
- [x] Prompt audit + format rapport JSON
- [x] `run_audit.py` avec AuditToolRegistry restreint
- [x] AGENTS.md enrichi (règles UI + section wama-dev-ai)
- [x] Fix VRAM (décharge Ollama + WAMA avant audit)
- [x] Fix format DeepSeek Coder V2 (Format 6 + strip hallucinations)
- [x] Migrer vers `qwen3-coder:30b` (remplace deepseek-coder-v2:16b — config.py + views.py mis à jour)
  — **révisé (2026-07-20, nuance Fabien)** : `qwen3-coder:30b` PAS exclu — simplement trop lourd
  pour l'agentique quand l'hôte 24 Go est partagé. Défaut fiabilisé = **`gemma4:e4b`** ; la
  sélection doit à terme être **pilotée par le model_manager** (VRAM dispo → choisir
  qwen3-coder:30b ou mieux selon la prospection), cf. `config.py::select_model_for_role()`
- [x] Mémoire persistante `memory.json` — bugs connus, règles, notes — + outil `write_memory` + injection prompt
- [x] Premier audit complet avec `write_report` appelé — **FAIT 2026-07-17** : campagne « état des
  lieux vision », 6 audits ciblés avec rapports écrits + contre-vérification Claude (fiabilité
  mesurée : positifs cités ~100 % exacts, affirmations d'absence fausses 4/6 → protocole consigné
  dans `docs/construction/archive/VISION_STATUS.md` annexe + mémoire projet)
- [ ] Cron nightly : `0 2 * * *`

### Phase 1b — Schémas d'architecture WAMA (read-only, tâche de fond) ⏳
> WAMA grossit vite et on perd la vue d'ensemble de ce qui est déjà en place. wama-dev-ai
> (accès lecture codebase, RAG) maintient en continu :
- **Schéma fonctionnel** : flux apps ↔ services (Ollama, microservice TTS, Celery/Redis) ↔
  modèles ↔ converter ↔ media_library ; queues GPU/default ; temps réel vs batch.
- **Schéma descriptif** : composants, dépendances, points d'injection communs (common/),
  inventaire des services persistants et des modèles chauds.
- Régénéré périodiquement (diff vs version précédente) → évite l'oubli de l'existant.
- **Gros chantier wama-dev-ai à prévoir** (au-delà de l'audit) : à cadrer.

### Phase 2 — Tests API nocturnes ⏳
- Outil `wama_api_call(endpoint, method, params)` dans AuditToolRegistry
- Auth wama-dev-ai via token DRF (compte dédié `wama-dev-ai`)
- Smoke tests par app : add → start → poll → verify result
- Rapport `api_health_YYYY-MM-DD.json`

### Phase 3 — Veille modèles (intégrée dans Model Manager §5) ⏳
- Outil `hf_search(query, task)` dans wama-dev-ai
- Intégration avec `model_watcher_task` du model_manager

### Phase 4 — MCP 💡
- Exposer `select_model_for_role()` via MCP
- Sélection de modèles unifiée WAMA ↔ wama-dev-ai

---

## 7. Converter — Conversion universelle de fichiers multimédias

> Équivalent FileConverter mais avec meilleure qualité de conversion.
> App WAMA standalone + menu contextuel Filemanager + chaîne cross-apps.
> Conventions WAMA complètes obligatoires : queue, duplicate, profils, batch.

### Principes d'intégration architecturale

**Le Converter est une librairie de backends autant qu'une app.**
Deux modes d'utilisation :

1. **Standalone / file d'attente** — app Converter classique (upload → paramètres → process)
2. **Inline depuis une autre app** — appel direct des backends Converter en fin de tâche,
   sans passer par la file du Converter

**Pattern inline (Imager, Enhancer, Synthesizer…) :**
```python
# En fin de tasks.py de chaque app, si output_format demandé :
if item.output_format and item.output_format != 'original':
    from wama.converter.backends.image_backend import convert_image
    result_path = convert_image(result_path, item.output_format, options)
```
L'utilisateur choisit le format de sortie directement dans le modal de paramètres de l'app,
sans avoir à placer le fichier dans la file du Converter.

**Registre des formats disponibles — extension de `app_registry.py` :**
```python
CONVERTER_OUTPUT_FORMATS = {
    'image': ['jpg', 'png', 'webp', 'tiff', 'avif', 'bmp'],
    'video': ['mp4', 'webm', 'mov', 'mkv', 'gif'],
    'audio': ['mp3', 'wav', 'ogg', 'flac', 'aac', 'm4a'],
    'txt':   ['pdf', 'docx', 'md', 'html'],
}
```
Chaque app lit `CONVERTER_OUTPUT_FORMATS[output_type]` pour peupler son dropdown de sortie.

**Deux modes depuis le Filemanager :**
- **"Ajouter au Converter"** → file d'attente Converter, contrôle complet des paramètres
- **"Conversion rapide"** → modal léger inline dans le Filemanager, `POST /converter/quick/`,
  conversion synchrone, lien de téléchargement direct — sans file d'attente

**Chaîne de process cross-apps dans un job Converter :**
- Image : format + upscaling Real-ESRGAN (Enhancer) + débruitage (Enhancer)
- Vidéo : format + enhancement audio DeepFilterNet (Enhancer)
- Outpainting (élargissement cadre) : redirect vers Imager (tâche générative)

### Architecture ✅ (2026-04-14)
```
wama/converter/
├── models.py              # ConversionJob + ConversionProfile (profils sauvegardables)
├── views.py               # index, upload, start, status, download, delete, duplicate, clear_all
├── tasks.py               # route type média → backend + chaîne options cross-apps
├── urls.py
├── backends/
│   ├── image_backend.py   # Pillow + Wand (ImageMagick)
│   ├── video_backend.py   # FFmpeg (ffmpeg-python)
│   ├── audio_backend.py   # FFmpeg + pydub
│   └── document_backend.py # HTML→PDF via brique commune common/utils/html_render.py ; fallback pandoc
└── utils/
    └── format_router.py   # détection type entrant → formats sortie + options cross-apps disponibles
```

### Features

| Feature | Statut | Notes |
|---------|--------|-------|
| Conversion image (format, qualité, resize) | ✅ | Pillow — `backends/image_backend.py` |
| Conversion vidéo (format, fps, résolution, CRF, extraction audio, GIF) | ✅ | FFmpeg — `backends/video_backend.py` |
| Conversion audio (format, bitrate, canaux, normalisation EBU R128) | ✅ | FFmpeg — `backends/audio_backend.py` |
| App standalone queue (upload, start, status, download, duplicate, clear_all) | ✅ | `views.py` + `tasks.py` + template + JS |
| Menu contextuel Filemanager — "Envoyer vers Converter" | ✅ (2026-06-01) | Mode file d'attente : `POST /converter/quick/` avec `queue_only=1` → job PENDING, params réglés ensuite sur la page Converter (modal item Phase 0). Aussi en multi-sélection. |
| Menu contextuel Filemanager — "Conversion rapide" | ✅ (2026-06-01) | Entrée top-level dédiée → modal `#converterQuickModal`. **Vraie conversion à la volée** (modèle FileConverter) : job **éphémère** (jamais dans la file, `ephemeral=True`), sortie écrite **à côté de la source** (`dest_dir`, anti-collision de nom), barre de progression inline, refresh auto de l'arbre, puis `dismiss` (ligne DB supprimée, fichier conservé). Presets qualité Web/Équilibré/Max. Visible pour tout type convertible. |
| Presets de qualité (Web/Équilibré/Maximum) | ✅ (2026-06-01) | `utils/quality_presets.py` — image (quality 80/90/98), vidéo (CRF 23/20/16 + preset x264), audio (160/224/320k). Appliqués en mode rapide ; l'explicite l'emporte. video_backend honore l'option `preset`. |
| Conversion rapide — annulation + robustesse | ✅ (2026-06-02) | Endpoint `cancel` (revoke Celery + suppression job éphémère) ; annulation à toute fermeture de modale (Annuler/X/Esc/backdrop via `hide.bs.modal`) ; **sortie atomique** (temp → move) → annuler/échouer ne laisse jamais de fichier corrompu près de la source ; **garde-fou** : worker muet >20 s → message "le worker ne répond pas" + revoke du job zombie. Tâches Celery désormais auto-découvertes (`autodiscover_tasks()`). |
| Modal Paramètres item (édition output_format + options sur job existant) | ✅ (2026-05-16) | Endpoint `POST /<pk>/update/` + form dynamique selon media_type ; bouton "Appliquer" et "Appliquer & (Re)lancer" |
| Profils de conversion sauvegardables | ✅ (2026-05-16) | Endpoints `profile_list/save/delete` ; dropdown filtré par media_type dans panneau settings ; bouton "Sauver comme profil…" dans modal item |
| Option upscaling ×2/×4 (Real-ESRGAN via Enhancer) | ✅ IMAGE (2026-08-18) / ⏳ vidéo | Wiring complet : schéma dérivé de `CROSS_APP_OPTIONS` (params.py), split `options`↔`cross_app_options` (views.update_job), application inline `utils/cross_app.py` (`upscale_image_file` enhancer ; x2=BSRGANx2, x4=RealESRGANx4, denoise IRCNN). **Upscale VIDÉO différé** : mécanisme à extraire de `enhancer/tasks.py::_enhance_video` (2ᵉ consommateur) APRÈS validation GPU du during enhancer |
| Format de sortie inline dans chaque app (Imager, Enhancer…) | ⏳ | `CONVERTER_OUTPUT_FORMATS` disponible depuis app_registry, UI P2 |
| Batch avec aperçu avant/après sur échantillon | ⏳ Phase 5 | Essentiel sur gros volumes |
| Conversion document (PDF ↔ DOCX ↔ MD ↔ HTML ↔ TXT) | ✅ Phase 4 (2026-06-01, chaîne PDF refondue 2026-07) | Pandoc + pypandoc 1.13 ; PDF input via PyMuPDF ; **HTML→PDF = brique commune `common/utils/html_render.py`** (Chromium headless → WeasyPrint → fallback pandoc/xelatex — commits 34e84af/8013f22/1329638) |
| Option enhancement audio lors conversion vidéo (Enhancer) | ✅ (2026-08-18) | DeepFilterNet via `cross_app_options` : audio direct (ré-encodage au format cible) + vidéo (demux → enhance → remux, flux vidéo copié) — `utils/cross_app.py` ; ⚠ validation GPU navigateur = Fabien |
| **Rotation** (90°/180°/270° + flip H/V) | ✅ Phase 6 (2026-05-16) | PIL `Image.Transpose` / ffmpeg `transpose,hflip,vflip` |
| **Crop de zone** (image + vidéo, UI canvas) | ⏳ Phase 7 | Vision initiale — canvas JS overlay + ffmpeg crop |
| Extraction de frames vidéo | ⏳ Phase 8 | Intervalle fixe ou détection de scène (PySceneDetect) |
| Concaténation (N fichiers → 1) | ⏳ Phase 9 | FFmpeg concat demuxer |
| Time-lapse / slow-motion (interpolation RIFE/DAIN) | ⏳ Phase 10 | Modèle ~500 MB, deps lourdes |
| **Watermarking invisible** (stéganographie) | ⏳ Phase 11 | Vision initiale (Claude) — lib `stegano` ou DWT |
| **Shell integration OS** (Win .reg / macOS Service / Linux .desktop) | ⏳ Phase 12 | Vision initiale — accès depuis explorateur natif |
| Option outpainting → redirect Imager | 💡 P3 | Tâche générative, Imager en est la maison (§7b) |

### Plan d'implémentation par phases (2026-05-16)

> Vision initiale → ce plan déroule les features manquantes par ordre de priorité et de risque.

| Phase | Sujet | Statut | Effort | Risque |
|---|---|---|---|---|
| **0** | Modal Paramètres item (édition output_format + options par job) | ✅ 2026-05-16 | ~110 l | Faible |
| **1** | Profils sauvegardables (ConversionProfile + UI) | ✅ 2026-05-16 | ~170 l | Faible |
| **2** | Options cross-app (upscale + audio enhance) | ✅ 2026-08-18 (sauf upscale vidéo, différé) | ~230 l | Moyen (perf vidéo) |
| **3** | `output_format` inline dans Imager / Enhancer / Synthesizer | ✅ 2026-06-02 | ~150 l + 3 mig | Moyen |
| **4** | Document backend (Pandoc) | ✅ 2026-06-01 | ~150 l + pypandoc + pandoc binaire | Moyen (binaire système) |
| **5** | Batch avec aperçu avant/après sur échantillon | ⏳ | ~200 l | Moyen |
| **6** | **Rotation** 90°/180°/270° + flip H/V (image + vidéo) | ✅ 2026-05-16 | ~120 l | Faible |
| **7** | **Crop de zone** (UI canvas overlay + ffmpeg crop) | ⏳ | ~250 l | Moyen |
| **8** | **Extraction de frames** (intervalle + détection de scène) | ⏳ | ~150 l + scenedetect | Faible |
| **9** | **Concaténation** N fichiers → 1 (FFmpeg concat) | ⏳ | ~120 l | Faible |
| **10** | **Time-lapse / slow-motion** (RIFE/DAIN interpolation) | ⏳ | ~200 l + modèle 500 MB | Élevé |
| **11** | **Watermarking invisible** (stéganographie) | ⏳ | ~100 l + lib stegano | Faible |
| **12** | **Shell integration OS** (Win .reg / macOS Service / .desktop) | 💡 | ~200 l/OS | Moyen |
| **13** | **Batch** : modèle `ConversionBatch`, multi-fichiers groupés par nature, fichier d'URLs (preview/Individuel), groupes UI + actions (start/réglages/delete) | ✅ 2026-06-03 | ~350 l + mig 0003 + `common/utils/batch_common.py` | Moyen |

### Intégration cross-apps (pattern tasks.py) ⏳
```python
# Exemple : conversion image + upscaling
result = image_backend.convert(input_path, output_format, options)
if options.get('upscale'):
    from wama.enhancer.utils.ai_upscaler import upscale_image
    result = upscale_image(result, model=options['upscale_model'])
```

### Dépendances — voir `requirements*.txt` + `start_wama_*.sh` (source vivante ; WeasyPrint +
### provisioning Chromium ajoutés 2026-07, ce bloc figé était périmé)
```
pip install ffmpeg-python pydub pypandoc Wand
# Wand nécessite ImageMagick installé système
# Pandoc nécessite pandoc binaire installé système
# Optionnel : py7zr (archives .7z), rarfile + unrar (lecture .rar),
#             Calibre 'ebook-convert' (mobi/azw3)
```

### Archives & Ebook (2026-06-01) ✅

| Capacité | Statut | Notes |
|---|---|---|
| Archives (zip ↔ tar ↔ tar.gz/bz2/xz ↔ 7z) | ✅ | `backends/archive_backend.py` — extract + repack. stdlib pour zip/tar ; `.7z` via py7zr (optionnel), `.rar` lecture via rarfile (optionnel) |
| Ebook epub/fb2 | ✅ | Via Pandoc (`document_backend`) |
| Ebook mobi/azw3/azw | ✅ (si Calibre) | Route Calibre `ebook-convert` ; erreur claire si binaire absent |

Parité FileConverter atteinte : image, vidéo, audio, document, ebook, archive.
Gaps restants mineurs : présets non exposés sur la page Converter (réservés au mode rapide), archives chiffrées non gérées.

### Articulation avec `wama/common/utils/video_compat.py` (décision 2026-05-12)

Le helper inline `ensure_h264()` (sync, blocking, sans UI) vit dans
`wama/common/utils/video_compat.py` — utilisé directement par les
pipelines en cours d'exécution (cam_analyzer.upload_camera, fallback
legacy quad-crop, anonymizer/enhancer si besoin futur de sources HEVC
iPhone, etc.).

Converter est la couche utilisateur **au-dessus** : async via Celery,
progress UI, choix de format/codec, batch. Quand l'utilisateur demande
explicitement une conversion .mov → .webm avec progression, c'est
Converter. Quand un pipeline interne a besoin d'un .mp4 H.264 playable
*maintenant*, c'est `common.video_compat.ensure_h264()`.

Converter consomme `common.video_compat` **en interne** pour son cas
trivial H.264 (pas de duplication de logique ffmpeg). À implémenter
quand l'app Converter sera reprise.

---

## 7b. Imager — Outpainting (élargissement de cadre) ⏳

> Tâche générative (diffusion) — appartient dans Imager, pas dans Enhancer ni Converter.
> Accessible depuis un bouton "Outpainting" dans Enhancer et depuis Converter (P3).

- Modèle : Stable Diffusion Inpaint via Diffusers, ou FLUX Inpaint
- LaMa (Large Mask) : alternative légère pour fonds simples sans contenu complexe
- ProPainter : référence open source pour l'outpainting vidéo
- Paramètres : direction d'extension (gauche/droite/haut/bas), ratio, prompt optionnel

---

## 8. Transcriber — Correction assistée

> Contexte : synchronisation audio/texte précise avec surlignage du mot courant,
> interface d'édition manuelle + suggestion IA. Inspiré de Whispurge / Sonal.
> WaveSurfer.js déjà présent dans WAMA (Composer). `coherence_suggestion` déjà en DB.

### État actuel
- `word_timestamps=True` passé à faster-whisper → `seg.words` disponible **pendant** la transcription mais **non sauvegardé**
- `TranscriptSegment` : granularité segment (phrases 5-15s), pas mot
- `Transcript.coherence_suggestion` : texte corrigé par LLM déjà en base
- SRT généré depuis les segments (suffisant pour sous-titrage, insuffisant pour clic-sur-mot)

### Phase 1 — Sauvegarde word timestamps ⏳

| Tâche | Fichier | Notes |
|-------|---------|-------|
| Extraire `seg.words` dans la boucle de collecte | `whisper_backend.py` | `[{word, start, end, probability}]` par segment |
| Nouveau champ `words_json = JSONField` | `models.py` + migration | Backup complet des timestamps mot |
| Adapter `qwen_asr_backend.py` | `qwen_asr_backend.py` | Quand dépendances résolues (cf. §0) |

### Phase 2 — Vue correction interactive ✅ LIVRÉE (autrement que planifié)

> Référence du domaine : `wama/transcriber/TRANSCRIBER_CORRECTION.md` (ne pas maintenir le
> détail ici). Réel livré : URL `GET /transcriber/edit/<pk>/` (+ `save_correction`/`save_meta`/
> `suggest_speakers`/`waveform_peaks`), champs `corrected_segments_json` (JSONField) +
> `correction_status` (`none/draft/done`), migration 0010. Le plan ci-dessous est HISTORIQUE.

**URL (plan initial) :** `GET /transcriber/<pk>/correct/`

| Fonctionnalité | Détail |
|----------------|--------|
| Waveform + playback | WaveSurfer.js (déjà dans Composer) |
| Surlignage mot courant | Basé sur `words_json` + `currentTime` player |
| Défilement auto | Fenêtre de ~5 lignes centrée sur le mot courant |
| Clic sur mot → seek | Click handler sur chaque `<span data-start>` |
| Édition inline | `contenteditable` par segment avec sauvegarde AJAX |
| Suggestion IA | Panneau `coherence_suggestion` — "Appliquer" par segment ou global |
| Export | Re-génération SRT/TXT corrigé + nouveau champ `corrected_text` |

**Nouveaux champs DB (plan initial — réel : `corrected_segments_json` + `correction_status` `none/draft/done`) :**
- `Transcript.corrected_text = TextField` (texte final validé)
- `Transcript.correction_status = CharField` (PENDING / IN_PROGRESS / DONE)

### Phase 3 — Enrichissements ⏳
- Highlight automatique des mots à faible confiance (probability < seuil → fond orange)
- Suggestions d'homophones pour les erreurs détectées (LLM local)
- Export WebVTT (sous-titres web)
- Mode "révision rapide" : navigation clavier entre segments à corriger

---

## 8b. Describer — Mode scientifique

> Contexte : WAMA développé au Lescot (laboratoire SHS, Ergonomie, Sciences Cognitives pour les Transports).
> Mode principalement orienté SHS / Sciences Cognitives / Ergonomie, mais architecture généraliste.
> `output_format = 'scientific'` existe déjà dans le modèle — résumé global uniquement.

### Phase 1 — Détection sections + résumés structurés ⏳

**Pipeline :**
```
PDF
  → PyMuPDF get_text("dict") → fontsize + bold flags → détection headings
  → Segmentation : Abstract / Introduction / Méthodes / Résultats /
                   Discussion / Conclusion / Références
      (tolérance regex pour structures non-IMRaD — fréquentes en SHS)
  → LLM Ollama (Qwen3.5) par section — prompt rôle-spécifique
  → Fiche structurée : titre, auteurs, année, mots-clés, résumé global + par section
```

**Points de vigilance :**
- PDFs multi-colonnes → ordre PyMuPDF incorrect → fallback GLM-OCR
- Articles SHS souvent sans structure IMRaD standard → regex flexible + fallback bloc
- Longueur > contexte LLM → chunking par section avec chevauchement 128 tokens

**Interface interactive :**

| Composant | Détail |
|-----------|--------|
| URL | `GET /describer/<pk>/scientific/` |
| Panneau gauche | PDF natif browser (iframe + PDF.js) |
| Panneau droit | Fiche par section en accordion Bootstrap |
| Navigation sync | Clic section → scroll PDF (via anchor page) |
| Chaque section | Résumé LLM + texte original expandable + bouton "Copier" |

### Phase 2 — Enrichissement externe ⏳
- **Semantic Scholar API** (gratuite) : papiers liés, nb citations, abstract, DOI
- **Isidore API** (SHS francophones) : source complémentaire pour corpus Lescot
- Affichage "Références" avec liens DOI cliquables

### Phase 3 — Intégration RAG ⏳
- Indexation automatique du papier dans le RAG utilisateur après analyse
- Q&A sur le papier depuis l'AI assistant WAMA avec citations de passages

---

## 8c. RAG WAMA + WAMA Notebook

> Stack retenu : **ChromaDB** (déjà utilisé dans un projet parallèle) + **nomic-embed-text** (Ollama).
> Fondation de l'AI assistant WAMA contextuel et du WAMA Notebook.

### Phase 1 — Fondation RAG ⏳

**Architecture :**
```
wama/rag/
├── store.py       # ChromaDB client + gestion collections par user
├── embedder.py    # nomic-embed-text via Ollama /api/embeddings
├── indexer.py     # chunking + indexation (Celery task)
└── retriever.py   # hybrid search : vectoriel + keyword fallback
```

**Stratégie de chunking :**
| Type de document | Stratégie |
|-----------------|-----------|
| Articles scientifiques | Chunk = section (via Describer §8b) |
| Documents généraux | 512 tokens, chevauchement 64 tokens |
| Transcriptions | Chunk = segment (start/end conservés pour référencement temporel) |
| PDFs scannés | Chunk post-OCR (GLM-OCR ou docTR) |

**Intégration Médiathèque :**
- Case "Ajouter au RAG" sur chaque asset (PDFs, transcriptions, notes)
- Tâche Celery `index_asset_task(asset_id)` → extract → chunk → embed → ChromaDB
- Vue `GET /rag/status/` : nb documents indexés, taille collection, dernière MàJ
- Indicateur visuel "indexé RAG" sur les cards de la Médiathèque

### Phase 2 — Modèles scientifiques ⏳

Benchmark après Phase 1 validée sur corpus Lescot réel :

| Modèle | Rôle | Taille | Source |
|--------|------|--------|--------|
| `OpenScholar_Retriever` | Embedding spécialisé scientifique | n.c. | HuggingFace/OpenSciLM |
| `OpenScholar_Reranker` | Reranking résultats RAG | 0.6B | HuggingFace/OpenSciLM |

Décision d'intégration basée sur mesure qualité retrieval vs `nomic-embed-text`.

### Phase 3 — WAMA Notebook ⏳

**Concept :** Vue "Notebook" dans la Médiathèque — sélection d'un corpus de sources →
session de travail Q&A + génération de contenu depuis ces sources.

| Fonctionnalité | Détail |
|----------------|--------|
| Sélection multi-sources | PDFs, transcriptions, notes, URLs |
| Q&A avec citations | Réponse + passage source + nom document + page |
| Résumé de collection | N documents → 1 synthèse (Describer) |

**Génération podcast depuis documents :**

| Étape | Outil WAMA |
|-------|-----------|
| Script LLM (1 narrateur) | Ollama (Qwen3.5) |
| TTS | Synthesizer WAMA (backend disponible — Higgs non fonctionnel pour l'instant, cf. §0) |
| Musique de fond + ambiance | Piste secondaire dans Composer — mix avec le speech |
| Export | MP3 + transcript du podcast |

> Evolution future : 2 voix (débat/analyse) une fois le TTS multi-voix stabilisé.

---

## 8d. LiteLLM — Couche LLM unifiée + Mode hybride WAMA

> Principe dual-mode : **Mode local** (défaut, 100% Ollama, pas de surprise) +
> **Mode hybride** (clés API utilisateur, cloud optionnel, jamais activé sans action explicite).
> LiteLLM sert de couche d'abstraction — même API, provider interchangeable.

### Phase 1 — Couche d'abstraction locale ✅ (2026-04-14)

✅ Livrée : `llm_chat()` (`wama/common/utils/llm_utils.py`), `LITELLM_PROVIDER='ollama'`
par défaut, zéro breaking change. Détail archivé : `docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

### Phase 2 — Mode hybride utilisateur ⏳

**Concept :** Chaque utilisateur peut configurer ses propres clés API cloud depuis son profil.
WAMA utilise alors le provider cloud à la place d'Ollama pour les tâches sélectionnées.

| Provider | Modèle conseillé | Cas d'usage |
|----------|-----------------|-------------|
| Grok (xAI) | `grok-3` | Généraliste, contexte long, coût modéré |
| OpenAI | `gpt-4o` | Vision, code, qualité référence |
| Anthropic | `claude-sonnet-4-6` | Raisonnement, SHS, longues analyses |
| Mistral AI | `mistral-large-latest` | Francophone, SHS, souveraineté EU |

**Architecture :**
- ⚠ **CORRECTION (vérifié 2026-08-01)** : « clés stockées via `UserProviderConfig` (déjà en place) »
  était **inexact**. `UserProviderConfig` (`media_library/models.py:196`) porte les clés des
  **banques de médias** (`MediaProvider` = Wikimedia / Pixabay / Freesound), pas des LLM. Il n'existe
  **aucun stockage de clé LLM par utilisateur** — c'est le PATRON à reproduire (`requires_api_key`,
  `api_key_label`, `api_key_help_url`, section dédiée du profil), pas une brique à réutiliser telle
  quelle. Le commentaire de `settings.py:587` induit la même erreur et reste à corriger.
- **Ce qui marche DÉJÀ** : LiteLLM lit les clés **nativement depuis l'environnement**
  (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `XAI_API_KEY`…). Passer `api_key=` n'est pas requis, et
  aucun appelant ne le fait. Preuve outillée : `python manage.py llm_gateway_check`
  (`--provider xai --model grok-3` = appel cloud réel). `ANTHROPIC_API_KEY` est renseignée dans
  `.env`. Le chemin cloud est donc fonctionnel **au niveau instance** ; ce qui manque est le
  **par-utilisateur** (multi-tenant) — optionnel pour un labo mono-instance.
- **Le vrai verrou pour « lever le goulot local »** : le choix du provider est **global**
  (`LITELLM_PROVIDER`, tout ou rien). Pour qu'un modèle cloud alimente une app, il doit se déclarer
  **par tâche**, dans la chaîne descriptive (registres) comme le reste — pas par un réglage global
  ni par un `if` dans chaque app. Sans ça : on connecte, mais on ne peut pas utiliser.
- **SECOND VERROU, mesuré le 2026-08-20 — le catalogue ne sait pas DÉCRIRE un modèle cloud.**
  `AIModel` n'a ni `execution` (local/cloud), ni provider cloud dans `ModelSource` (qui n'énumère
  que des apps WAMA + `ollama`/`huggingface`/`custom`), ni coût. Pire : `select_model()` filtre
  `is_downloaded=True` **par défaut** → tout modèle cloud serait mécaniquement exclu de la
  sélection automatique. C'est ce verrou-ci, plus que LiteLLM (déjà câblé), qui empêche
  d'étendre la sélection automatique au cloud. Chantier :
  ① champs `execution` + valeurs cloud de `ModelSource` + `cost_tier` (`free`/`metered`/
  `subscription`) ; un modèle cloud a `vram_gb=0` et sa disponibilité = clé API présente ;
  ② `select_model()` : VRAM et `is_downloaded` ne s'appliquent qu'aux locaux (le tri par
  `benchmark_index`/`quality_index` fonctionne déjà tel quel, le banc tiers note du cloud) ;
  ③ **politique de routage déclarative, par tâche** — *confidentialité d'abord* (un flag de
  sensibilité force le local, non négociable : c'est ce qui rend le cloud acceptable pour un
  labo SHS) — ✅ **TRANCHÉ par Fabien le 2026-10-02 : pas de verrou supplémentaire.** Le cloud est
  un CHOIX DE L'UTILISATEUR, déjà porté par son profil (`cloud_policy` : « 100 % local » / « cloud
  si saturé » / « cloud autorisé », garde `cloud_models.cloud_access`), et Albert est l'API de la
  DINUM, hébergement souverain français (SecNumCloud) : l'audio qui part chez Albert ne quitte pas
  la sphère publique française. Le « flag de sensibilité » par tâche n'est donc PAS à construire —,
  puis *gratuit d'abord* (`local → cloud free → cloud payant`, arbitrage Fabien),
  puis *capacité* (contexte/VRAM saturés → escalade cloud, dont `_route_model_by_context` est
  déjà l'embryon local) ; ④ override utilisateur `auto` par défaut (patron `resolve_auto_model`
  de l'imager). ⚠ Le choix manuel est un **override**, jamais le mécanisme principal.
- ⭐ **PLAN « SÉLECTION AUTOMATIQUE UNIVERSELLE » (2026-10-12, demande de Fabien)** — *« quelque
  chose de fiable, robuste, universel, applicable partout (toutes les apps, tous les mondes), qui
  tient compte de ce qui est en place en local et distant et qui, selon le geste utilisateur,
  privilégie ce qui ne sature ni WAMA en local ni les quotas »*. Reprend la conception de la
  session « bascule entre clouds » (close le même jour, question transférée ici).
  **État mesuré le 12/10** (lignes lues) :
  - « cloud si saturé » ne fait RIEN au tirage : `allowed_cloud_keys` rend l'ensemble vide hors
    « cloud autorisé » (`cloud_models.py`, `if policy == 'local_only' or (automatic and policy
    != 'cloud_allowed')`) ; aucun signal de saturation n'existe (`gpu_is_busy` et
    `global_queue.free_at` existent, personne ne les lit pour ça) ;
  - aucune bascule sur panne : un 429 attend `Retry-After` ou le délai de la source, retente UNE
    fois le MÊME fournisseur (`llm_utils._completion`, `RATE_LIMIT_RETRIES = 1`), puis le tour
    échoue. Mesuré : un modèle `:free` d'OpenRouter en 429 → **83,8 s** d'attente, puis l'erreur ;
  - aucun compte de quota par fournisseur (ni base, ni cache) ;
  - quatre règles d'admission parallèles : `allowed_cloud_keys`, `dev_cloud_keys`
    (`development_models.py`), `remote_stt_key` (`speech_input.py` — le PREMIER modèle distant
    par ordre alphabétique) et `role_utils.resolve_model` de wama-dev-ai (défaut fixe en cloud) ;
  - une app ne reçoit du cloud que si son schéma déclare `options_cloud`
    (`auto_model.declared_cloud_keys`) — c'est juste : un distant doit savoir faire la tâche.
  **Cible** : UN chemin — admission (profil : QUAND, JUSQU'OÙ, À QUEL COÛT) → candidats locaux et
  distants → ordre de PRÉFÉRENCE dérivé du profil → santé des fournisseurs → appel avec bascule
  par nouveau tirage. Aucune chaîne écrite à la main ; LiteLLM Router écarté (une seconde logique
  de choix à côté du catalogue).
  **Étapes, du plus sûr au plus structurant :**
  1. ✅ **Coût lu PAR MODÈLE à l'admission** (12/10) : les modèles gratuits d'un fournisseur
     facturé (19 chez OpenRouter) entrent au tirage sans le consentement « payant » ; ceux d'une
     source qui les sert à condition d'entraîner (`free_models_need_data_reuse`, mesuré : 404
     « Free model training » sous `deny`) n'y entrent qu'au dernier cran du plafond. Gardes :
     `tests_cloud_models.FreeModelsOfAMeteredSourceTest`.
  2. ✅ **Bascule sur panne** (13/10) : 429, 5xx, délai dépassé, connexion refusée → le
     fournisseur est noté SATURÉ (durée = `Retry-After`, sinon celle de la source ; 3 min pour une
     panne) et le tirage AUTOMATIQUE l'écarte le temps de la note — pour tout appelant, puisque
     tous lisent `allowed_cloud_keys`. Domicile : `cloud_models` (l'admission), pas
     `resource_governor`, qui gouverne les ressources LOCALES ; la note vit dans le cache partagé.
     L'assistant en est le premier utilisateur : modèle tiré → relais immédiat, sans l'attente de
     60 s, une source jamais reprise dans le même tour, bascule DITE ; modèle choisi → relais
     PROPOSÉ, joué en un clic sur le web. Détail et gardes : `WAMA_LLM.md` (§ limite de débit
     d'Albert). **Restes** : ① le relais EN COURS D'APPEL pour une app (une tâche qui a tiré son
     modèle puis échoue) attend l'étape 5 — un chemin d'appel commun « tirer puis appeler » ;
     d'ici là, une app profite de la note à son lancement SUIVANT ; ② la transcription d'Albert
     (`albert_asr_backend`, sa propre attente sur 429) ne pose pas encore la note ; ③ le relais
     peut être le modèle LOCAL, chargé à froid (jusqu'à ~2 min mesurées) — l'étape 4 dira quand
     le local est admis (GPU occupé, file longue).
     **Complété le 13/10 (relecture du harnais à la bascule)** : le relais garde les messages du
     tour — prompt, skill de rôle, contexte du labo, historique, outils joués —, donc le même
     harnais. Deux trous fermés : un relais vers le LOCAL est préparé comme un départ local
     (fenêtre ET traduction de la demande, `assistant_engine._prepare_local_model`) ; le DERNIER
     appel, après la limite d'outils, bascule aussi. La note et l'écart se lisent dans les
     journaux (`[cloud] … noté saturé`, `[cloud] écartées du tirage`) : sans eux, « quota ou
     défaut ? » ne se tranchait pas.
  3. ⏳ **Quotas comptés** : requêtes par (utilisateur, source) et par fenêtre, contre les quotas
     DÉCLARÉS sur la source (OpenRouter sans crédit : 20/min et 50/jour ; Albert) → la source est
     tenue pour saturée AVANT le 429.
     ➕ **Mesuré le 14/10** (une vraie réponse par fournisseur, compte `fabien.moreau`) :
     - **Albert** dit ses limites PAR MODÈLE sur `GET /v1/me/info` (`limits[]` : `router_id`,
       `type` ∈ rpm/rpd/tpm/tpd, `value`) — 11 groupes pour 11 modèles, de 10/min · 1000/jour à
       500/min · 50 000/jour ; et ce qui a été consommé sur `GET /v1/me/usage` (par tranche,
       filtrable par modèle, `requests` compris). ⚠ `/v1/models` ne porte pas le `router_id` :
       QUELLE limite vaut pour QUEL modèle ne se lit pas encore. Aucun en-tête de limite sur la
       réponse de chat ;
     - **ILaaS** (`llm.ilaas.fr`) : aucun en-tête de limite, pas de `/me/info` (404) — rien
       d'annoncé ; **ILaaS RAG** (même passerelle qu'Albert) : `gpt-oss-120b` sans aucune limite
       (rpm/rpd/tpm/tpd vides) ;
     - **OpenRouter** : pas mesuré (aucune clé sur ce compte) ; sa doc annonce `GET /api/v1/key`.
     **Tranché par Fabien le 14/10** : un quota peut dépendre du MODÈLE (Claude, Albert) ou être
     PARTAGÉ par un groupe de modèles (les gratuits d'OpenRouter) — la SOURCE le déclare par
     défaut, le modèle distant le surcharge (patron du coût, étape 1). Domicile : le registre des
     sources (`external_sources`) + UNE brique commune de comptage et de saturation, pour TOUT
     service externe — pas `llm_chat` seul : cinq endroits gèrent aujourd'hui un 429 chacun à sa
     façon (`llm_utils`, `albert_asr_backend`, `search_engines/base`, `prospector` pour le Hub et
     Artificial Analysis, GitHub). La note de saturation de l'étape 2 y déménage. Un service sans
     quota annoncé n'est jamais bloqué par le compte ; le 1ᵉʳ 429 réel apprend le plafond.
  4. ⏳ **Ordre de préférence décidé par le profil** (demande de Fabien) : au dernier cran
     (« commercial, même s'il garde mes données »), les modèles GRATUITS commerciaux passent
     d'abord, pour épargner le GPU local et les quotas souverains ; puis le souverain ; puis le
     local ; le payant seulement sur consentement. En dessous, l'ordre ③ (`local → cloud gratuit
     → payant`). « Cloud si saturé » devient effectif : GPU occupé / file trop longue / VRAM
     insuffisante → le distant est admis. Forme : un RANG de préférence par candidat, appliqué
     avant la qualité (patron de `priority` dans `select_model`), le plancher de capacité de
     l'appelant restant prioritaire (`agent_candidates` de l'assistant outillé).
     ➕ **Le curseur est INERTE entre distants** (mesuré le 13/10 sur un compte « cloud
     autorisé », 20 distants admis : la prévision rend `ilaas:qwen-3.8-27b` aux curseurs 0, 50
     et 100). Cause : un distant coûte **0** au score (`model_selector._best_by_vram`, `costs =
     {… 0.0 if is_cloud(m) …}`) ; entre distants seule la qualité départage, donc le meilleur
     gagne à tous les crans ; face à un local, le terme « légèreté » lui est toujours acquis.
     Le coût 0 est voulu (« il ne prend rien sur CETTE carte ») ; ce qui manque est un coût
     propre au distant — sa vitesse apprise (`eta_estimator.comparable_speeds`, lue seulement si
     TOUT le lot en a une) ou sa latence. À trancher avec le rang de préférence : décision de
     Fabien.
     ✅ **Tranché par Fabien le 14/10** :
     - l'ordre du dernier cran est CONFIRMÉ ; c'est le réglage « QUAND » qui décide de l'ordre
       (« en dessous » disparaît) : « cloud si saturé » → le local d'abord, le distant quand le
       local est saturé ; « cloud autorisé » → le distant gratuit d'abord (commercial puis
       souverain au dernier cran), puis le local, le payant sur consentement ;
     - SATURÉ = la demande ne tient pas tout de suite en VRAM (`resource_governor.
       effective_free_gb`) ET ne se traitera pas avant un délai réglable par l'utilisateur
       (`global_queue.free_at`) — **défaut 0** : qui a choisi « cloud si saturé » a accepté que
       ses données sortent, on ne le fait pas attendre ;
     - l'ASSISTANT n'est pas une tâche : il doit être toujours disponible — un distant admis
       passe avant tout chargement local, le local ne sert que si aucun distant n'est admis ;
     - le coût d'un distant au curseur : la VITESSE MESURÉE pour une tâche d'app, le TEMPS DE
       RÉPONSE (délai avant le 1ᵉʳ mot, chargement compris) pour l'assistant — ce dernier n'est
       pas encore chronométré ;
     - un modèle tiré en DISTANT ne prend ni la file GPU, ni de place au planning, ni de VRAM.
       ⚠ Mesuré : la file et la déclaration au gouverneur suivent aujourd'hui le PROCESS
       (`task_skeleton.queue_of`, `spec.gpu`, l. 726-743), pas le modèle tiré, et
       `auto_model.vram_needed_gb` ne regarde pas l'exécution : le gouverneur doit savoir si le
       modèle est local ou distant. ✅ **Livré le 14/10** (passation de la session du gouverneur
       au grain du process) : `ProcessSpec.card_model` + `task_skeleton._holds_the_card` — un
       process qui emploie le modèle de la card, tiré distant, ne tient pas la carte ; détail et
       restes à `ROUTE §10.6` 4.5 (bloc du 14/10).
     ⏳ **Ouvert** : séparer au profil l'assistant des traitements d'app (assistant en cloud,
     données traitées en local) — et ce qu'un assistant distant LIT d'un résultat traité en
     local. Mesuré le 14/10 : le FICHIER ne transite pas (l'assistant ne reçoit que
     `{id, name, path, size}`, `filemanager.services.enregistrer_fichier_utilisateur`, et l'app
     le lit sur le disque) ; le CONTENU du résultat, si : aperçus de 300 caractères dans les
     statuts et texte lu par l'outil de lecture de résultat (`tool_api.py:2722`).
  5. ⏳ **Un seul chemin partout** : `remote_stt_key`, `dev_cloud_keys` et `role_utils.resolve_model`
     passent par le même tirage ; les mondes Data et Lab l'héritent par `resolve_model_choice`.
     ➕ **L'enrichissement des prompts de génération** (relevé le 13/10 en relisant le harnais) :
     `prompt_enrichment.enrich_generative` appelle Ollama avec un modèle d'instance
     (`WAMA_PROMPT_ENRICH_MODEL`), hors du tirage — local seul, quel que soit le profil. Le
     rallier change ce que reçoivent les apps (un prompt enrichi par un distant) : décision de
     Fabien avant le geste.
  6. ⏳ **Médias générés par un distant** (images) : OpenRouter sert 12 modèles qui rendent des
     images, **aucun gratuit** (mesuré sur sa liste le 12/10) ; aucune vidéo. À ouvrir après
     2-5, comme une capacité de la source, et sur consentement « payant ».
  7. ⏳ **Embeddings distants** (2026-10-13, demande de Fabien : à reprendre ICI). **État mesuré :**
     - un seul embedder, LOCAL et FIXE : `bge-m3` par Ollama (`memory/embed.py:32`, `/api/embed`),
       appelé en direct, hors du tirage. Aucun appel du code ne demande `requires=['embedding']`,
       alors que `albert:bge-m3` porte le drapeau au catalogue (`cloud_models.abilities_for`) :
       listé, jamais utilisé ;
     - ILaaS sert ses embeddings sur un service À PART (`rag-api.ilaas.fr`, jeton à part), déclaré
       le 13/10 comme source `ilaas_rag`, famille `rag` et non `llm` (décision de Fabien) : sa clé
       se pose sur la page Sources, RIEN ne la lit, aucun modèle ne s'ouvre (garde
       `tests_api_keys.InstanceKeyTest.test_the_ilaas_rag_key_is_stored_but_opens_nothing_yet`,
       contre-épreuve faite). Lu SANS clé sur son `/openapi.json` public : c'est **OpenGateLLM**, la
       passerelle d'Albert — `/v1/embeddings`, `/v1/rerank`, `/v1/ocr`, `/v1/audio/transcriptions`,
       `/v1/chat/completions`, collections et `/v1/search`. **Clé posée par Fabien le 13/10, mesuré
       avec elle** : `/v1/models` rend **3 modèles**, tous à coût nul — `bge-m3`
       (`text-embeddings-inference`, contexte 8192), `bge-reranker-v2-m3` (`text-classification`) et
       `gpt-oss-120b` (`text-generation`, un modèle de chat que `llm.ilaas.fr` ne liste pas).
       `/v1/embeddings` sur `bge-m3` : **1024 dimensions**, et sur deux phrases le **cosinus avec
       notre `bge-m3` local vaut 0,99999** — c'est le MÊME espace de vecteurs : un index construit
       en local se lit avec le distant, et inversement ;
     - contraintes déjà dans le code : vecteurs de **1024** dimensions (`EXPECTED_DIMS`, sinon
       refusés) ; nom du modèle STOCKÉ par ligne (`Embedded.embedding_model`), donc changer
       d'embedder = réindex complet — même un `bge-m3` servi ailleurs porte un autre nom ;
       dégradation, jamais échec (en-tête d'`embed.py`) ; le réindex est le même geste que la
       bascule prévue vers `qwen3-embedding:4b` (§ en tête de ce fichier).
     **Ce qui diffère du chat** : l'embedder est aujourd'hui une constante d'INSTANCE — un même index
     ne mélange pas deux espaces de vecteurs —, donc le tirage par profil de 1-5 ne s'y applique
     pas tel quel. Et la mémoire porte les notes PRIVÉES des comptes : un embedder distant serait la
     première sortie de son contenu hors de la machine (plafond d'hébergement du profil, §8d ③).
     ⇒ la contrainte du réindex ne tient plus qu'au NOM stocké : un `bge-m3` distant sous le nom
     `bge-m3` rendrait le relais local ↔ distant possible sans réindex (à décider, pas à supposer :
     la mesure porte sur deux phrases).
     ⚠ **2026-10-19 — l'embedder LOCAL a changé** (bascule vers `qwen3-embedding:4b`, `WAMA_MEMORY §7`) :
     le `bge-m3` d'ILaaS partageait l'espace de l'ANCIEN local, plus celui de l'index. Un relais
     distant sans réindex exigerait désormais un Qwen3-Embedding servi ailleurs, aux mêmes
     1024 dimensions tronquées.
     **Suite** : ~~clé posée, `/v1/models` mesuré~~ (13/10) → décider si
     `ilaas_rag` devient un fournisseur `llm` comme Albert (ses modèles de chat entreraient alors au
     tirage, avec ceux de `llm.ilaas.fr`) → brancher ou non `embed.py` sur un modèle distant.
     ⚑ **Ces choix reviennent à la session de routage cloud** (signalé le 13/10 par la session
     d'intégration d'ILaaS) : l'usage d'ILaaS RAG — embeddings, classement (`bge-reranker-v2-m3`)
     et son modèle de chat `gpt-oss-120b` — se décide ici, avec l'ordre de préférence de l'étape 4.
  **Tranché par Fabien le 13/10** : ① un modèle CHOISI à la main qui sature ne bascule pas seul —
  on le dit et on propose le relais en un clic (le choix manuel est un consentement explicite) ;
  ② la bascule vit d'emblée dans la brique commune, l'assistant en premier utilisateur.
- **Duplicata à résorber** : `wama-dev-ai/config.py::select_model_for_role` réimplémente une
  sélection RAM-aware avec chaînes de fallback, et appelle Ollama en direct (pas LiteLLM). Une
  fois la politique ci-dessus en place, c'est à **lui d'adopter la brique** (il gagne le cloud
  au passage) — plus simple que le plan initial « exposer `config.py` via MCP ».
- `llm_chat(provider=user_provider, api_key=user_key)` → LiteLLM route vers le bon provider
- UI : section "Providers IA" dans le profil utilisateur + indicateur "mode hybride actif"
- ⚠️ À préciser dans l'UI : **abonnement ChatGPT Plus / Claude.ai ≠ accès API**
  (API = facturation séparée à la requête, nécessite une clé API distincte)
  — ⚠ **NUANCE VÉRIFIÉE 2026-08-20** : vrai pour l'API *au sens LiteLLM* (une clé reste
  requise pour router un provider ici). Mais il existe désormais un chemin **par
  l'abonnement**, hors LiteLLM : depuis juin 2026 le titulaire peut piloter Claude Code
  programmatiquement (token OAuth `claude setup-token` + `claude -p` headless ou Agent SDK),
  avec un crédit mensuel dédié. Ce n'est PAS un provider LiteLLM et ça ne remplace pas une
  clé API — c'est la brique du canal développeur (§19.3). Ne pas confondre les deux dans l'UI.

### Phase 3 — MCP Server WAMA 🔄 (ouvert le 2026-09-15 — « faire le MCP maintenant », Fabien)

**Concept :** Exposer les outils WAMA comme serveur MCP pour clients compatibles
(Claude Code, Claude Desktop, IDEs). Distincts de LiteLLM — MCP = protocole d'outils,
pas un routeur LLM.

**Pourquoi maintenant** : interagir avec WAMA de la MÊME manière quel que soit le cerveau —
Ollama local, Claude Code sur abonnement, Albert (DINUM) ou tout cloud ajouté. L'assistant avait
UN moteur et UN registre d'outils, mais chaque cerveau y accédait à sa façon (boucle JSON en
prompt pour Ollama/LiteLLM ; aucun outil WAMA pour `claude-abo`). MCP en fait un contrat unique.

**Décisions du 2026-09-15** (Fabien, sur questions posées) :
- **MCP = OUTILS** (`tool_api`, cadre §16) ; la SÉLECTION de modèle n'y passe pas —
  `select_model_for_role` adopte la brique commune (cf. ci-dessus). ⚠ Pas de contradiction avec
  `AGENTS.md` : wama-dev-ai est en phase 4, seul MCP restait à faire (précision Fabien).
- ~~Fournisseurs LLM déclarés dans un REGISTRE DÉDIÉ~~ — **REVU LE MÊME JOUR par Fabien : pas de
  nouveau registre, on LÈVE LE VERROU du catalogue (§8d ①②).** Ma question n'offrait que « registre
  dédié » ou « tout dans `external_sources` » et OMETTAIT l'option conforme à la doctrine des
  backends (« le MODÈLE porte son moteur, le backend s'en DÉRIVE ») : un modèle cloud entre dans
  `AIModel` par DÉCOUVERTE (`GET /v1/models`, comme `/api/tags` pour Ollama), porte son moteur
  (`composition.runtime.engine`) ; le moteur s'inscrit à l'inventaire des moteurs (exécutable =
  clé posée + service joignable, patron `ollama_host._MoteurOllama`) ; la façon d'appeler est un
  backend ; adresse et clé restent dans `external_sources`. Le « fournisseur » se DÉRIVE.
  Champs §8d ① : `execution` (local/cloud), valeurs cloud de `ModelSource`, `cost_tier`
  (free/metered/subscription) — + proposé : où partent les données (local / cloud souverain /
  cloud tiers). **Albert = DISTANT SOUVERAIN** (Fabien : une clé d'API suffit à le rendre distant).
- **Politique d'usage du cloud** (Fabien, 15/09 — conforme à §16 « plein local par défaut, mixte
  cloud opt-in » et à la vision « choix explicite ») : **100 % local par défaut** ; choix GLOBAL
  sur la page profil (patron `UserProfile.prompt_enrich`, `accounts/models.py:74-81`) + choix
  PONCTUEL dans l'app par le sélecteur de modèle EXISTANT (modèles cloud grisés avec la raison) ;
  tâches sensibles déclarées « local uniquement » dans les métadonnées d'app — pas un champ par
  app. ⚠ **Garde de non-régression** : un modèle cloud n'entre dans le tirage automatique
  (`select_model`) que si l'utilisateur l'autorise ET que la tâche le permet ; sans autorisation,
  le tirage est IDENTIQUE à aujourd'hui. Sans cette garde, les scores de banc des grands modèles
  cloud gagneraient tout le tirage en silence.
- **Le curseur rapide/qualité s'y aligne** (remarque de Fabien) : il informe déjà de la saturation
  VRAM ; il proposera « baisser la qualité » OU « passer en cloud » — l'escalade par capacité de
  §8d ③, trou ouvert depuis longtemps.
- **Clés d'API PAR UTILISATEUR, en base, CHIFFRÉES au repos** (Fabien) : sort les clés du `.env`,
  et RÉPARTIT les quotas — une clé Albert partagée (10 req/min sur certains modèles) serait
  épuisée par quelques utilisateurs d'un même labo. Tranche la question laissée ouverte par
  `PROJECT_STATUS` (« chiffre-t-on les jetons au repos ? » → oui). ⚠ Le patron médiathèque
  (`UserProviderConfig`) stocke en CLAIR (`media_library/models.py:234`) et WAMA n'a aucune brique
  de chiffrement : reprendre sa FORME (`requires_api_key`, `api_key_label`, `api_key_help_url`),
  pas son stockage. UI : dans le VOLET DROIT de la page profil, pour ne pas l'allonger.
  **Clé de chiffrement = DÉRIVÉE de `SECRET_KEY`** (Fabien, 15/09 — pas de clé de plus dans
  `.env`), avec une étiquette d'usage propre ; déchiffrement par la clé courante PUIS les
  `SECRET_KEY_FALLBACKS` ; ⚠ `rotate_secrets` ne garde que 3 fallbacks (`rotate_secrets.py:199`) :
  il doit RECHIFFRER les clés stockées à chaque rotation, sinon une clé sortie des fallbacks rend
  les données illisibles en silence. Refus d'enregistrer une clé si `SECRET_KEY` est le
  placeholder de dev. (Précision : la rotation est À LA DEMANDE, aucun planificateur ne la lance
  — `INFRA_WSL_VS_WINDOWS.md:128`.) Réglage de profil à **3 niveaux** : « 100 % local » (défaut),
  « cloud si WAMA est saturé », « cloud autorisé ».
- ✅ **SECOND AXE du cloud — décision de Fabien, 2026-10-03** : le niveau dit QUAND WAMA peut
  sortir du local, deux réglages de profil disent JUSQU'OÙ et À QUEL PRIX.
  **Mesure qui l'a déclenché** : profil « cloud autorisé » + une clé d'API Anthropic → le tirage
  automatique de l'assistant rendait `anthropic:claude-opus-4-6` (facturé au jeton) aux curseurs
  0, 50 ET 100 — un distant « coûte » 0 sur la carte, donc le bout « rapide » le choisit aussi.
  1. **Plafond d'hébergement** (`UserProfile.cloud_hosting_max`) sur une échelle ORDONNÉE, celle
     des anneaux de la présentation : `private` (infrastructure de l'établissement) <
     `sovereign` (État : Albert) < `third_party` (commercial) — `external_sources.HOSTING_SCALE`,
     `hosting_within`. « Local » n'est pas sur l'échelle : c'est l'exécution sur site, réglée par
     le niveau. Défaut **souverain** (« clouds commerciaux : seulement si on les choisit »).
     Vaut pour le tirage ET pour le choix manuel (`allowed_cloud_keys`, `cloud_refusal(user,
     source)`). ⏳ Aucune source ne se déclare `private` aujourd'hui : la valeur est posée pour
     que le profil et la présentation disent la même chose le jour où un serveur de
     l'université arrive.
  2. **Modèles facturés à l'usage au tirage automatique** (`cloud_metered_auto`, défaut NON) : un
     `cost_tier == 'metered'` n'entre au tirage que sur consentement ; le choix MANUEL reste
     ouvert (nommer un modèle payant est un consentement). C'est le consommateur que `cost_tier`
     n'avait pas — à l'ADMISSION, comme le voulait `model_selector` (« le sélecteur n'arbitre
     pas local/distant »).
  Migration `accounts 0024` : un profil qui avait quitté le « 100 % local » ET posé la clé d'un
  hébergeur tiers garde son accès (plafond relevé à commercial) ; le consentement au payant reste
  à donner. Après : tirage de Fabien = `albert:deepseek-v4-flash` (0, 50), `ollama:qwen3.8`
  (100). Gardes : `tests_cloud_models.HostingCeilingTest`, `tests_api_keys.NiveauCloudTest`.
- **Découverte des modèles cloud PAR LES CLÉS DES UTILISATEURS** (Fabien, 15/09) : à
  l'enregistrement d'une clé, puis périodiquement, WAMA lit les modèles ouverts à CE compte
  (`GET /v1/models`) et les garde avec la clé ; le catalogue porte l'union, chaque utilisateur ne
  choisit que ce que sa clé ouvre (mesuré : `mistral-medium` fermé au compte de Fabien). La
  synchro du disque ne supprime JAMAIS une ligne cloud : seule la découverte cloud réconcilie les
  siennes (sinon `delete_missing` les effacerait, ou un échec réseau suspendrait la réconciliation
  de TOUT le catalogue, `model_sync.py:112-128`).
  ✅ **Le « puis périodiquement » est câblé depuis le 2026-10-04** — il ne l'était pas : la liste
  n'était relue qu'au geste « Enregistrer » du profil. Mesuré ce jour : toutes les clés dataient
  leur découverte du 18/09, et Claude Opus 5.5 / Sonnet 5.5 n'existaient pas pour WAMA. Sonde
  NOCTURNE `model_manager.refresh_cloud_keys` (beat, 01:10 → `cloud_models.refresh_all_keys`) :
  un appel par clé, erreur gardée sur la ligne sans rien fermer, fournisseurs sans liste sautés.
  Première exécution réelle : `anthropic` +2 (`claude-opus-5-5`, `claude-sonnet-5-5`).
  ✅ **L'origine se DIT sous le sélecteur** (même jour) : `AIModel.origin_label`, dérivé de
  l'exécution, de la source, de son hébergement et du coût (« Cloud souverain · Albert API
  (DINUM) · gratuit », « Local · Ollama »), servi par l'API du catalogue et affiché par
  `WamaModelHelp` — pour un distant toujours, pour un local quand la liste mêle les deux.
  L'assistant déclare désormais `help_source` : son sélecteur n'avait AUCUNE aide contextuelle.
  ✅ **L'origine se lit DANS la liste (2026-10-05).** Sous le sélecteur elle n'apparaissait qu'une
  fois le modèle choisi ; remarque de Fabien : « on ne sait pas si on choisit un modèle local ou
  distant… c'est le cas partout ». La route commune des options (`api_model_options`) range
  désormais chaque liste sous l'origine de ses modèles — « WAMA local », « Albert API (DINUM) »,
  « API Anthropic (Claude) », « Claude Code (abonnement) » — local d'abord, puis l'échelle des
  hébergements (`external_sources.model_origin`, `_groups_by_origin`). Un groupe déjà nommé
  (tâche, catégorie) garde son nom suivi de l'origine ; « auto » reste en tête, hors groupe.
  Une règle, donc l'assistant et les dix sélecteurs de modèle des apps (tous sur la source
  `catalog`). ⏳ Seule liste encore écrite en dur : `diarization_model` du transcriber.
  ⚠ Non vu au navigateur : vérifié par la route réelle (4 groupes pour l'assistant) et par V8.
  ✅ **Abonnement Claude Code : le modèle se CHOISIT et se DIT** (2026-10-03, décision de Fabien).
  Le protocole `claude_cli` n'a toujours pas de liste : c'est la ligne DÉCLARÉE qui s'étend, pas
  un mécanisme neuf. La source déclare ses modèles (`ExternalSource.declared_models`) — `default`
  plus les alias que le CLI documente (`--model` : « alias for the latest model », relevé sur
  `claude --help` 2.1.286) : `fable`, `opus`, `sonnet`. `cloud_models.declared_listing` en fait
  des lignes de catalogue (`claude_code:opus`…), `claude_code.demander(model=…)` refuse un
  identifiant non déclaré et passe `--model` (rien pour `default`), et lit dans `modelUsage` le
  modèle qui a RÉELLEMENT servi. Le tour le dit : `claude-abo (opus → claude-opus-5-5)`.
  La sonde nocturne redéclare une source sans liste quand sa déclaration a changé — un alias
  ajouté au registre entre donc au catalogue sans geste. Mesuré sur le compte réel : 3 lignes
  ajoutées, appel `sonnet` → `claude-sonnet-5-5`. ⚠ « Auto » ne tire PAS l'abonnement tant que
  le plafond du profil est « souverain » (Albert l'emporte) : c'est le second axe, voulu.
  ⚠ Un alias suit le « plus récent » du fournisseur : la ligne ne porte donc aucune capacité
  mesurée propre, et `haiku` n'est pas déclaré faute d'être documenté par le CLI.
- **Clé d'instance (`.env`) : PAS de repli pour les utilisateurs** (Fabien, 15/09) — quotas
  répartis. Elle ne sert qu'aux usages SANS utilisateur (rôles wama-dev-ai en ligne de commande,
  tâches planifiées) ; lancé par le serveur MCP dev, un rôle utilise la clé du développeur qui le
  lance.
- ⏳ **Curseur « informe de la saturation » = INTENTION ACTÉE, pas encore construite** (corrigé le
  15/09 : je l'avais d'abord écrit « croyance corrigée », à tort). Le cahier des charges de Fabien
  du 14/09 soir (`PROJECT_STATUS` §PALIER « GOUVERNEUR : la CLÉ publiée rejoint le catalogue ») :
  une tâche qui exige toute la VRAM attend en `AWAITING_RESOURCES` qu'aucune tâche ne tourne ni que
  le service TTS ne serve, puis on décharge tout, on exécute, on relance le TTS ; le gouverneur
  décide ; **l'utilisateur est informé par le curseur** (le baisser pour lancer tout de suite) ; à
  mener avec l'achèvement du curseur et de la sélection bidirectionnelle. ÉTAT MESURÉ du code au
  15/09 : la prévision ne rend que le modèle prévu (`model_manager/views.py:1229-1252`),
  `_best_by_vram` rend le plus léger en silence (`model_selector.py:242-243`), aucune app ne passe
  `vram_needed` (portages en retard). Décisions en attente de Fabien (§PALIER « SQUELETTE ») :
  B. conception de l'attente « toute la VRAM », C. généralisation du curseur. **L'option cloud du
  curseur rejoint CE chantier**, elle ne s'écrit pas à part. ~~Les modèles cloud branchés au 15/09
  (Albert) ne servent que le TEXTE~~ — FAUX, mesuré le même jour (`GET /v1/models`, 11 modèles) :
  Albert sert aussi la vision (`image-text-to-text` : gemma-4-31b, mistral-small-3.2, ministral-3,
  lightonocr), la transcription (`whisper-large-v3`), les embeddings (bge-m3, qwen3-vl-embedding)
  et le reranking. OpenRouter reste l'option pour la GÉNÉRATION multimodale (image, voix, vidéo).
  **Comportement, dans les mots de Fabien (15/09 — ma formulation « libérer avant de différer »
  était FAUSSE)** : quand la tâche ne tient pas dans la VRAM, soit l'utilisateur BAISSE LA QUALITÉ
  pour tenir dans la VRAM disponible, soit il ATTEND que les process en cours se terminent pour
  que sa tâche se lance — et, si nécessaire, le service TTS est déchargé LE TEMPS DE LA TÂCHE, sinon
  elle ne passerait jamais (et désormais : soit il passe en CLOUD). ⚠ Comportement DÉGRADÉ du PC de
  dev (VRAM très limitée) : **en prod, le service TTS et l'assistant restent TOUJOURS actifs.**
  **C — TRANCHÉE (Fabien, 15/09)** : le curseur se GÉNÉRALISE (déjà décidé) ; le curseur de précision
  de l'anonymizer garde son fonctionnement mais REMONTE AU COMMUN avec sa spécificité VISION,
  réutilisable par d'autres apps (future app Detector…).
  ✅ **C LIVRÉ pour le commun le 20/09** (détail `PROJECT_STATUS §PALIER 2026-09-20 « CURSEUR C »`) :
  type `intent` borné par `coerce_params` ; `auto_model.quality_intent_of` (champ de l'item → réglage
  d'app durable → 50) lu d'office par `resolve_model_choice(item=)` ; `model_coverage.size_for_intent`
  / `segmentation_for_intent` (les seuils de l'anonymizer, inchangés au cran près — garde
  `tests_intent_vision`) et `couvrir_classes(quality_intent=)` ; grisage des classes sur « auto »
  (union des modèles de détection installés) ; reader rallié (curseur = réglage d'app) ; critère de
  grille `quality_intent` (97 critères, 846/913). ✅ **21/09 : converter (`013c8d59`), imager,
  composer puis enhancer ralliés** (enhancer = portage en deux commits, `bb301886` + suivant :
  ROUTES, squelette, modales au cycle commun, « auto » + curseur + facteur — détail
  `PROJECT_STATUS §PALIER « CURSEUR C » ⑧`) — mesuré par le critère : **8 apps VRAI**, describer n/a,
  **transcriber FAUX** — question ouverte : `priority` whisper-first reste l'ordre, le curseur
  arbitre dedans. ⚠ Le tirage « auto » de l'enhancer image/vidéo attend de la DÉCOUVERTE (session
  sœur) la projection de `vram_usage` et d'un `quality_index` a priori : sans eux le score des 7
  upscalers est plat. L'option cloud du curseur = B3.
  **B — réponses (Fabien, 15/09)** : ① ce n'est pas qu'une question de voix — quand la tâche libère
  TOUS les modèles de la VRAM, l'assistant MET L'UTILISATEUR EN ATTENTE avec un message d'attente.
  ÉTAT MESURÉ : un mot d'attente GÉNÉRIQUE existe, affiché après un délai sur l'accueil seulement
  (`assistant_skills.py:220-237` → `home.html:467-476`) ; Discord n'a que l'indicateur « écrit… »
  (`discord_bot.py:132`). Rien ne relie ce message au déchargement décidé par le gouverneur ⏳.
  ② toutes les apps passent au squelette de tâche commun, de toute façon : l'attente s'active avec
  ce portage. ③ une tâche NON DÉMARRÉE ne consomme aucun délai : le délai ne court qu'une fois le job
  démarré, et ne sert qu'à vérifier qu'il n'a pas échoué (pour ne pas rester bloqué). ⚠ Écart avec
  le code : `DIFFEREMENTS_MAX = 40` × `DIFFEREMENT_DELAI_S = 45` (`task_skeleton.py:118-123`) passe
  en FAILURE, au bout de ~30 min, une tâche qui n'a JAMAIS démarré ⏳ à corriger dans ce chantier.
  Reste ouvert : en prod (service TTS jamais déchargé), que devient une tâche qui ne tiendra jamais ?
  **4a — consigne (Fabien, 15/09)** : TOUT ce qui touche aux clés (fournisseurs LLM ET connecteurs
  de la médiathèque) va dans le VOLET DROIT de la page profil, par le mécanisme commun du volet
  (`common/utils/volet.py`, blocs `right_panel_*` de `base.html`) — on ne réinvente rien.
- **Curseur rapide/qualité → cloud MÊME SANS saturation** (Fabien, 15/09 : « sinon je ne peux pas
  l'utiliser pour éviter les crashs PC ») : le choix cloud est proposé dès que le profil n'est pas
  « 100 % local » et qu'une clé utilisable existe ; la saturation le MET EN AVANT. Les 3 niveaux
  gouvernent le tirage AUTOMATIQUE (jamais / sur saturation / normalement) ; le choix manuel reste
  ouvert dès le 2ᵉ niveau.
- **Claude Code = un FOURNISSEUR comme les autres** : il consomme les outils WAMA par MCP
  (`--mcp-config`). `ask_claude_code` reste l'outil de délégation d'une tâche au dépôt.
- **Le moteur de l'assistant devient CLIENT MCP pour tous les cerveaux** (outils prod ET dev).
- **Outils de dev ouverts à l'assistant** : rôles wama-dev-ai (propositions en attente de
  validation) ET bac à sable (`app_sandbox`, `app_regen_check`), dans le serveur SÉPARÉ.

**Étapes :**
1. ✅ **Installation propre du SDK** (15/09) — `mcp==1.30.0` par la route `library`
   (`manifests/libraries/mcp.json`). La route n'acceptait qu'UN spécificateur : `mcp` y aurait
   monté `starlette` 0.46.2 → 1.6.0 (via `sse-starlette`) et cassé `fastapi` 0.115 (`<0.47`, qui
   porte gradio/vibevoice/inference/imaginAIry). D'où `constraints.pip` du manifeste — champ
   projeté au registre depuis toujours et lu par PERSONNE — passé à pip par `-c`, en simulation
   comme à l'installation (`model_installer.pip_constraint_errors`,
   `tests_library_install.ContraintesPipTest`). Mesuré : 3 paquets ajoutés, 0 version déplacée.
   ⚠ `apply_manifests --kind library --apply` aurait EFFACÉ 4 licences enrichies à la main au
   registre (kokoro-onnx, pyannote-audio, torchaudio, vibevoice — le corpus les porte vides) :
   la projection a été faite pour `mcp` SEUL. Écart signalé, non traité.
2. ✅ **Serveur « wama »** (15/09) — `common/services/mcp_server.py` + `manage.py run_mcp_server`
   (HTTP streamable à l'adresse `external_sources['wama_mcp']`, ou stdio avec `WAMA_MCP_TOKEN`).
   `tools/list` = `TOOL_REGISTRY` filtré par `tool_accessible` ; `tools/call` = `execute_tool`
   (validation d'entrée du SDK COUPÉE : la porte fait foi) ; identité = jeton d'API DRF ;
   arguments = `tool_api.tool_input_schema` (JSON Schema dérivé du schéma d'app et de la
   signature, pendant typé de `tool_descriptions`). ⚠ La protection DNS rebinding est DÉSACTIVÉE
   par défaut dans le SDK : activée ici. Gardes : `tests_mcp_server` (protocole réel en mémoire).
   Smoke RÉEL (vrai process, vrai client, vrai jeton) : 69 outils, appel OK, outil inconnu →
   `isError`, sans jeton → 401.
3. ✅ **Serveur « wama-dev »** (15/09), process SÉPARÉ (§16) — `common/services/dev_tools.py`,
   servi par `run_mcp_server --surface dev` (adresse `external_sources['wama_mcp_dev']`). 7 outils :
   `dev_run_role` (librarian/model/scout/integrator/codegen — arguments ADMIS déclarés par rôle,
   valeur commençant par `-` ou multiligne refusée), `dev_sandbox` (create/substitute/revert/drop/
   list, le demandeur est le créateur de la jumelle), `dev_regen_check` (JAMAIS `--force` : sa
   garde dev/main reste entière), `dev_reload_web` (HUP gunicorn), `dev_job_status`,
   `dev_list_jobs`, `dev_read_output` (lecture confinée à `wama-dev-ai/outputs/`). Chaque
   lancement est une TÂCHE détachée (`logs/dev_jobs/`), qui survit au redémarrage du serveur.
   Droits vérifiés à CHAQUE appel : `accounts.permissions.is_developer`, domicile UNIQUE extrait
   de `claude_code.subscription_allowed` — ⚠ l'extraction a corrigé une branche MORTE : le tier
   était lu dans `profile.tier`, attribut inexistant (le champ est `account_tier`), donc un compte
   développeur par son seul tier était refusé en silence ; aucun test ne couvrait le tier.
   `mcp_server` n'importe `dev_tools` que pour la surface dev — prouvé dans un process NEUF.
   Gardes : `tests_mcp_dev_tools`. Smoke RÉEL : 7 outils, `dev_sandbox list` lancé et suivi
   jusqu'à `done rc=0`, `--force` injecté refusé.
   **→ Étape 5, MOITIÉ DEV, ✅ le 22/09 (demande de Fabien : « améliorer WAMA depuis l'assistant
   sans forcément passer par Claude, uniquement admins et devs »)** : le moteur de l'assistant est
   CLIENT MCP de cette surface (`common/services/mcp_client.py`). Pour un développeur, les 7 outils
   `dev_*` sont annoncés dans son prompt (même forme que `build_tools_list`, précédés des règles :
   proposition jamais appliquée, jumelles seulement, tâches de fond) et un appel `dev_*` est RELAYÉ
   par le protocole au serveur dev, avec le jeton d'API du compte — `execute_tool` ne les voit
   jamais, `dev_tools` n'est toujours pas importé (process neuf gardé par `tests_mcp_client`).
   Non-développeur : rien d'annoncé, aucune connexion ; serveur dev absent : rien d'annoncé,
   l'assistant répond. ⚠ Le serveur dev se LANCE à part (`run_mcp_server --surface dev`, port
   8771) — `start_wama_prod.sh` ne le démarre pas : sans lui l'assistant n'a que ses outils prod.
   Le skill `assistant-dev` dit désormais au modèle comment s'en servir. ⏳ Reste de l'étape 5 :
   la moitié PROD (le moteur client de la surface `wama` au lieu de `execute_tool` en direct) et
   le rôle « améliorer » avec sa page de bac à sable (décisions à prendre, `WAMA_LLM §1ter`).
4a. ✅ **Clés d'API personnelles + niveau cloud** (15/09) — `secret_crypto.EncryptedTextField`
   (chiffré au repos, clé dérivée de `SECRET_KEY`) ; `accounts.UserApiKey` (fournisseurs LLM =
   sources `external_sources` de type `llm`) et `accounts/api_keys.key_for` (un utilisateur n'a
   QUE sa clé ; la clé d'instance sert aux usages sans utilisateur) ; clés des connecteurs de la
   médiathèque CHIFFRÉES (elles étaient en clair — migration `media_library 0016` en SQL brut) ;
   `rotate_secrets` rechiffre toutes les clés stockées dans la même transaction que l'écriture du
   `.env` (`reencrypt_stored_secrets`, SQL brut) ; `UserProfile.cloud_policy` à 3 niveaux, défaut
   « 100 % local » — STOCKÉ, pas encore lu par la sélection (4b). Profil : jeton d'API, clés LLM et
   connecteurs dans la section Paramètres du volet droit (`volet(medias=False, actions=False)`),
   un seul rendu JS pour les deux listes. Gardes : `accounts/tests_api_keys` (chiffrement en base,
   pas de repli, 503 sur clé serveur non sûre, rechiffrement à la rotation, rendu dans le volet).
   ✅ **Jeton HuggingFace, même règle (27/09, décisions de Fabien)** : un jeton ne sert qu'à
   TÉLÉCHARGER — un modèle installé se charge par chemin local (SAM3 : `load_from_HF=False`) —, donc
   le téléchargement qu'une personne lance se fait avec SON jeton (`api_keys.download_token` :
   le sien, ou `False` = « aucun » s'il n'en a pas, pour que la lib ne retombe pas sur `HF_TOKEN`) ;
   sans utilisateur (sync, tâche planifiée, commande), celui de l'instance. Source `huggingface`
   `user_key=True` → saisi au profil ; `request_install(…, user=)` → tâches `install_*`
   (`user_id`, la clé relue dans la tâche, jamais passée au courtier) → `pull_hf_model(token=)` ;
   un dépôt « gated » refusé renvoie au profil (`GATED_REFUSAL`). Retirés : la page de jeton de
   l'anonymizer (qui l'écrivait dans le dossier personnel) et son « Config HF requise » ; la
   pastille SAM3 dit « prêt » si les poids sont installés, sinon renvoie au profil. Au passage :
   la découverte de modèles distants ne tourne plus que pour les sources `llm` (HF répondait une
   page HTML → 500 à l'enregistrement de la clé). Gardes : `DownloadTokenTest`,
   `HuggingFaceKeyTest` (contre-épreuve faite).
   ⏳ **Idée de Fabien, non tranchée — des QUOTAS sur les jetons système** : au lieu du refus
   actuel, laisser un utilisateur sans jeton télécharger avec celui de l'instance dans une limite
   (« x essais / heure »), en lui disant qu'il lève la limite en posant le sien.
4b. 🔄 **Verrou du catalogue levé — premier palier** (15/09) : `ModelSource.ALBERT`, champs
   `AIModel.execution` (local/cloud) et `cost_tier` ; hébergement et coût déclarés sur la source
   (`external_sources`, Albert = `sovereign`/`free`). DÉCOUVERTE par la clé de l'utilisateur
   (`model_manager/services/cloud_models.py`, appelée à l'enregistrement de la clé) : une ligne
   `albert:<id>` par modèle rangeable, moteur = la source (inventaire
   `external_sources.llm_engine_inventory`), liste gardée avec la clé (`UserApiKey.open_models`) ;
   les types sans catégorie (reranking) n'entrent pas. `select_model`/`get_registry_models` :
   paramètre `cloud_keys` — SANS lui, aucun distant n'entre (tirage et listes identiques) ;
   `allowed_cloud_keys(user, automatic)` le calcule d'après les 3 niveaux. La synchro du disque ne
   supprime ni ne désactive jamais un distant ; la désinstallation le refuse. Assistant : Albert
   avec la clé de l'UTILISATEUR (refus lisible sans elle), clé d'instance seulement sans
   utilisateur. Gardes : `model_manager/tests_cloud_models` (dont la contre-épreuve de
   non-régression). ⏳ Reste : les apps et l'assistant ne PASSENT pas encore `cloud_keys` (le
   sélecteur de l'assistant liste toujours ses fournisseurs à la main) ; redécouverte périodique ;
   coût distant dans `_best_by_vram` (VRAM 0 = pire coût aujourd'hui) ; le signal de saturation du
   niveau « cloud si WAMA est saturé » ; OpenRouter (types absents du `/models` OpenAI standard).
   **Étendu à Claude le même jour (demande de Fabien)** : sources `anthropic` (API facturée,
   fournisseur « claude » de l'assistant) et `claude_code` (abonnement, réservée aux développeurs,
   « clé » = jeton `claude setup-token`), protocole de liste de modèles DÉCLARÉ sur la source
   (`protocol`, `default_remote_type` — la liste d'Anthropic ne porte pas de tâche). L'abonnement
   suit la règle des clés : `claude_code.demander(user=…)` exige le jeton PERSONNEL et refuse avant
   de lancer le CLI, qui sinon retomberait sur les identifiants de la machine — l'abonnement d'une
   autre personne. Identifiants machine et jeton du `.env` : appels SANS utilisateur seulement.
   MESURÉ avec les clés de Fabien : API Anthropic → 11 modèles découverts ; le jeton d'abonnement
   est REFUSÉ par `GET /v1/models` (401) mais fait tourner le CLI (appel réel « OK », 0,50 $
   d'équivalent API à froid) — l'abonnement n'a donc pas de liste (`UNLISTABLE_PROTOCOLS`).
   **Sélecteur de l'assistant BRANCHÉ (15/09)** : les fournisseurs distants ne sont plus écrits
   dans `home.html` ; `assistant_engine.chat_provider_choices(user)` les lit du profil (niveau
   cloud, clés, prédicat développeur pour l'abonnement) et du catalogue (modèles ouverts à la clé,
   capables de conversation, plus « par défaut »). Garde serveur (web, API v1, Discord) :
   `cloud_models.cloud_refusal` — « 100 % local » refuse tout distant, `ask_claude_code` et `!code`
   compris — et un modèle nommé doit être ouvert par la clé. Reste la seule table à la main :
   `PROVIDER_SOURCES` (noms historiques de la surface → source). ⏳ Discord part toujours sur le
   fournisseur local (`gateway/core.py:208`) ; les apps ne passent pas encore `cloud_keys`.
   🔄 **Premier moteur d'APP distant (2026-09-30, demande de Fabien) — la transcription par
   Albert** (`albert:whisper-large-v3`, découvert au catalogue depuis le 15/09 sans qu'aucune app
   ne l'exécute) : `common/backends/albert_asr_backend.py` (`ENGINE='albert'`, protocole OpenAI
   `POST /audio/transcriptions`, `verbose_json`), résolu par le lien COMMUN modèle ↔ moteur ;
   garde d'appel extraite de l'assistant en brique (`cloud_models.cloud_access`, l'assistant
   l'adopte) ; `resolve_entry` gagne un filtre réservé aux moteurs DISTANTS (un fournisseur sert
   toutes ses tâches sous un même moteur — généralisé, il déplaçait 8 routages mesurés, dont
   `imager:qwen-image-edit`). Le transcriber résout une clé distante AVANT toute traduction par
   nom (`albert:whisper-large-v3` contient « whisper ») et refuse au lieu de se replier en local.
   But premier : **ÉVALUER** un modèle distant par la chaîne existante
   (`asr_eval_corpus --engines whisper albert:whisper-large-v3`). Gardes :
   `transcriber/tests_remote_transcription` (12, contre-épreuve 3 mutations / 3 rouges).
   Restes, même soir : ✅ **diarisation** — la liste pyannote du worker, écrite par NOM
   (`whisper`, `qwen_asr`), devient la CAPACITÉ déclarée (`supports_diarization`) : le distant
   est diarisé, et NeMo (Canary, Parakeet), qui ne l'était JAMAIS malgré sa déclaration, aussi
   (`ceb247e7`) ; ✅ **« auto » et les distants, AU COMMUN** (décision de Fabien) : toute app qui
   déclare `options_cloud` voit son tirage recevoir les distants que le profil ouvre à
   l'automatique, et la prévision dit ce tirage-là (`ROUTE §F4b`, brique d'auto-sélection) —
   effectif pour le transcriber dès que son select déclarera `options_cloud` ; ✅ au passage, les
   modèles installés « poids seulement » (FrWhisper, LinTO) ne sont plus confiés à Qwen3-ASR et
   sont GRISÉS (`ROUTE §F4b` ④). ✅ **Le SÉLECTEUR du transcriber au catalogue** : TRANCHÉ par
   Fabien (grain modèle, clés entières, domaine `transcription`, `options_cloud`), livré le 30/09
   après le commit du chantier diarisation qui occupait les mêmes fichiers (`ROUTE §F4b` étape
   ⑦) — Albert est au menu pour qui a une clé, et « auto » le tire pour un profil « cloud autorisé ».
   ✅ **Filtre de parole par CAPACITÉ** (2026-10-01) : `supports_vad_filter` au contrat commun
   (Whisper, Albert) — le worker ne le passait qu'au moteur nommé `whisper`. Mesuré : il aide Albert
   sur l'audio multilingue (44,5 → 39,8 %) mais ne comble pas l'écart en réunion, qui est dans son
   décodage (`WAMA_QUALITE §9bis`). Reprise sur la limite de débit (429). ✅ Le compte
   d'évaluation (`wama_evaluation`) a été ouvert au cloud par Fabien le 2026-10-02 (clé Albert).
   ⏳ **DIRE quand une donnée part dans le cloud** (idée de Fabien, 2026-10-02 — intention, rien
   construit) : le cloud reste un choix de l'utilisateur, WAMA le rend VISIBLE. (a) La prévision
   « Automatique → … » sous le select signale un modèle distant (« ☁ Albert (DINUM) — l'audio
   sera envoyé ») ; (b) au lancement, la console de la card dit « exécuté chez Albert », et la
   RAISON quand le tirage a basculé (« GPU saturé → Albert »). Le cas « cloud si saturé »
   attend le signal de saturation, qui n'existe pas encore.
4. ⏳ **Lever le verrou du catalogue** (§8d ①②, ordre fixé par Fabien le 15/09) — modèles cloud
   au catalogue par découverte, moteurs cloud à l'inventaire, `select_model` (VRAM/`is_downloaded`
   pour les locaux seulement, cloud seulement autorisé), réglage de profil, clés chiffrées par
   utilisateur (volet droit), curseur rapide/qualité → cloud. Reprend les tables Albert écrites à
   la main le 15/09 (`llm_utils.CLOUD_DEFAULT_MODELS`/`OPENAI_COMPATIBLE_PROVIDERS`, option de
   `home.html`).
4c. ⏳ **L'assistant devient une APP TRANSVERSALE du catalogue** (décision de Fabien, 15/09) —
   déclenché par un constat : Discord partait toujours en local faute de choix de fournisseur, et
   un correctif par surface a été refusé (« il ne faut pas faire de cas par cas : centraliser,
   universaliser, uniformiser »). L'assistant n'est déclaré nulle part comme app, d'où ses
   mécanismes à part. Cible : entrée au catalogue d'apps (TRANSVERSALE — « on veut pouvoir
   l'utiliser n'importe où et n'importe quand dans WAMA »), sélecteur de modèle COMMUN (auto en
   tête + curseur + choix manuel, qui coexistent — rien à remplacer ; les rôles de dev restent
   atteignables depuis l'accueil), modèle choisi = user setting persistant (brique `user_settings`
   rendue durable, §23.3bis) lu par TOUTES les surfaces, réglages dans le composant assistant là
   où il s'affiche. Préalable demandé : cartographie exhaustive assistant + wama-dev-ai, pour ne
   rien perdre des mécanismes en place — ✅ FAITE (`WAMA_LLM.md §Cartographie de l'assistant`), et
   brique `user_settings` rendue durable (commit `7a18d5dd`).
   **Réponses de Fabien sur la cartographie (15/09)** :
   ① déclaration : UNIFORMISER la déclaration des apps au catalogue et les CLASSER PAR MONDE —
   ⚠ chantier mené dans une AUTRE session : ne pas recouvrir ; les frictions mesurées (§D de la
   cartographie : régime transversal hors `APP_CATALOG`, catalogue JS vidé par une entrée
   incomplète, aide écrite pour une file, garde par app aveugle aux surfaces de l'assistant) lui
   sont transmises. ② RÔLES : le geste utilisateur reste « auto » ou un modèle ; le rôle est
   aujourd'hui affiché entre parenthèses derrière le modèle. Piste de Fabien : les rôles PORTÉS PAR
   LES MODÈLES (un modèle peut en porter plusieurs), avec un lien entre le registre des skills /
   prompts et les modèles ; les skills se chargent automatiquement par analyse de la requête (comme
   Claude — `charger_competence` en est déjà l'embryon). Les WORKFLOWS (rôles wama-dev-ai : librarian,
   scout, integrator, codegen, audit) restent en DEV ; à terme un kind de manifeste `workflow`
   (séquence d'actions LLM) ou leur entrée dans le kind `pipeline` s'il est compatible — ⚠ chantier
   mené dans une AUTRE session : ne pas recouvrir. ③ historique : un seul, en base, pour toutes les
   surfaces — Fabien pensait l'assistant web déjà branché ; MESURÉ : non, le web garde l'historique
   dans le `localStorage` du navigateur (`home.html:98-121`) et le renvoie à chaque tour
   (`views.ai_chat` → `run_assistant_turn`, sans store) ; seul Discord passe par `conversation_turn`.
   ④ TESTS des GESTES de l'assistant (aucun test de `ai_chat`, `AssistantChatView`, `kokoro_tts`) : à
   écrire dans le même temps.
   **Fait le 15/09 (après accord de Fabien, « schéma-driven, sans chemin parallèle »)** : historique en
   base pour le web (fil `web`, relu à l'accueil, « Effacer » = `conversation_store.clear`) et l'API
   (surface `api` ; `history` fourni = chemin sans état conservé) ; garde des fournisseurs non
   déclarés ; tests dans un cache séparé ; `tests_assistant_surfaces`. ⏳ Reste, dans cet ordre : le
   modèle choisi en réglage durable lu par toutes les surfaces + sélecteur COMMUN (schéma, source
   `catalog`, « auto » + curseur + manuel) — ✅ FAIT le 16/09 : `wama/assistant/params.py` (domaine
   `llm`), réglage durable
   `user_settings` app `assistant`, `resolve_turn_model` (surface > réglage > tirage « auto »), le
   FOURNISSEUR se dérive du modèle (`SOURCE_PROVIDERS`), `_ROLE_TIER` retiré (un ancien rôle vaut
   « auto »), accueil rendu par `WamaParams`, endpoint commun étendu (`cloud=1` comme `auto=1`,
   `model_type` multiple), abonnement Claude Code = ligne DÉCLARÉE du catalogue. ⚠ Garde corrigée au
   passage : `allowed_cloud_keys` ne retenait pas les sources OUVERTES à l'utilisateur — un compte
   ordinaire voyait le modèle d'abonnement.
   ⭐ **CORRECTION DE FOND au passage (Fabien, 16/09 : « pas un pansement — le problème est
   l'imprécision des catégories et des tâches »)**. Le smoke a montré le tirage « auto » retenant
   `ollama:glm-ocr:latest` (OCR) pour une conversation. Cause MESURÉE : la découverte Ollama
   écrivait `task='text-generation'` pour TOUT ce qui n'est pas un embedding et en déduisait
   `model_type='llm'` — un OCR déclarait donc la même chose qu'un modèle de chat, alors que WAMA le
   décrit précisément ailleurs (`reader:glm-ocr`, tâche `ocr`). Corrigé À LA SOURCE : table déclarée
   par famille `FAMILLES_OLLAMA` (tâche + spécialité), et **la CATÉGORIE se DÉRIVE de la TÂCHE**
   (`model_type_for_task`) dans les DEUX chemins de découverte, au lieu d'être posée à la main.
   Typage des modèles distants aligné sur la convention locale : un modèle de chat qui voit est
   `llm` + `vision` (comme `ollama:gemma4:12b`), plus `vlm`/`captioning`. Impact mesuré : 1 ligne
   sur 139 change (`ollama:glm-ocr:latest` → `ocr`) ; consommateurs de `model_type='llm'` : 4,
   tous voulus. ⚠ Défaut trouvé par le smoke et corrigé : `model_type_for_task` rend une CHAÎNE là
   où `ModelInfo` attend un membre `ModelType` — 2 modèles échouaient au sync en silence
   (`_type_ollama`, gardes `tests_taxonomie_ollama`). ✅ **Rôles PORTÉS PAR LES MODÈLES (17/09)** : le libellé d'une option porte les
   capacités DÉCLARÉES du modèle — « qwen3.8 (Vision, Outils, Raisonnement) » — et sa spécialité si
   elle est déclarée. Drapeau de schéma `options_aptitudes`, comme `options_auto` et
   `options_cloud` ; dérivation dans `model_selector.aptitudes_of`, donc un modèle qui gagne une
   capacité l'affiche au sync suivant. Les bancs restent HORS du libellé : ils pèsent déjà dans le
   tirage « auto », les afficher ferait un second vocabulaire. ⏳ Restent : gestes nocturnes de l'assistant
   déclarés au harnais `ui_smoke` (envoyer = charge Ollama → `vram_gb` déclaré, écarté du passage
   sans GPU).
   **Question de Fabien (15/09) : le choix automatique du modèle change-t-il la chaîne LLM ?**
   MESURÉ — non, sauf UN point. Enrichissement : sans objet pour l'assistant (il ne s'applique qu'au
   kind `generative`, `prompt_pipeline.py:145`, et la cible de l'assistant est `intent`,
   `app_metadata.py:69`). Hook B RAG de la chaîne : opt-in `rag=True` que `process_prompt_for` ne
   passe jamais (`app_metadata.py:150-155`) — aucune app ne l'active. Skills et rappel du labo :
   indépendants du modèle (domaine → skill ; `laboratory_context` sur la question). **Le seul
   couplage** : le ROUTAGE DE LANGUE lit les langues déclarées par le modèle RÉSOLU
   (`process_prompt_for(..., model_id=llm_model)`, `assistant_engine.py:676-683`) et ne tourne que
   sur le chemin LOCAL — changer le modèle peut donc changer la décision de traduire. À conserver
   quand la sélection passera au commun.
   **Chargement automatique des skills : CÂBLÉ, mais son déclenchement n'est pas mesuré.**
   L'annonce des compétences est injectée au prompt système (`assistant_engine.py:657`, garde
   `tests_assistant_skills.py:174`) ; l'outil `charger_competence` existe (`tool_api.py:3159`) et
   rend consigne de rôle + contexte du labo calculé sur la QUESTION (`tool_api.py:2533`,
   `tests_intake.py:165`). MAIS c'est le MODÈLE qui décide d'appeler l'outil, et aucun test ne
   montre qu'un modèle le fait réellement ; le domaine par défaut est `general`, déclaré `rag=False`
   (`assistant_skills.py:51-52`), donc sans appel de l'outil il n'y a AUCUN rappel du labo sur le
   web ni sur Discord. ⏳ À ajouter avec les tests des gestes : un tour de bout en bout où un faux
   LLM émet l'appel d'outil, pour prouver que la boucle charge bien le skill.
5. ⏳ **Moteur de l'assistant client MCP** — même chemin pour Ollama, Albert et Claude Code
   (`--mcp-config`) ; sélecteurs UI, API et Discord lus du catalogue (Discord est aujourd'hui figé
   sur `wama-dev-ai`, `gateway/core.py:208`). Ouvre aussi l'autre sens : WAMA CLIENT de serveurs
   MCP externes (mail, messagerie, dépôts…), chacun étant une question de confiance à trancher.
   **Précisé le 2026-09-30 (mesure du code, question de Fabien « on utilise déjà Albert, Ollama
   et Claude par le même chemin, non ? »)** — oui pour TROIS fournisseurs sur quatre, et ce reste
   est donc plus petit que la phrase ci-dessus :
   - ✅ **Ollama, Albert et l'API Anthropic partagent déjà UN chemin** : une seule boucle
     (`run_assistant_turn`, passage obligé des trois surfaces), le fournisseur ne changeant que le
     TRANSPORT (`assistant_engine._llm_call`), et chaque appel d'outil passe par la porte
     `execute_tool` (`assistant_engine.py:1120`) — **la même** que celle du serveur MCP
     (`mcp_server.py:150`). Les faire transiter par le protocole MCP ne changerait rien pour eux.
   - ⏳ **La seule exception est l'ABONNEMENT Claude Code** : il tourne sa PROPRE boucle et ne voit
     pas les outils de WAMA — lancé avec `--allowedTools`, sans `--mcp-config`
     (`claude_code.py:211-215`) ; son docstring le dit (`assistant_engine.py:557-563`). **Le reste
     « moitié prod » se réduit à lui passer le serveur `wama` par `--mcp-config`.**
   - ⏳ **WAMA client de serveurs MCP EXTERNES** : rien encore — `mcp_client` ne connaît que la
     surface dev (`dev_tools_for`, `call_dev_tool`).
   - ⚠ **Ne pas confondre avec les modèles cloud DANS LES APPS** : ce n'est pas du MCP (protocole
     d'OUTILS, pas routeur de modèles) mais le catalogue + `external_sources` + la garde
     `cloud_models.cloud_access` (4b). Premier moteur d'app distant : la transcription par Albert
     (`common/backends/albert_asr_backend.py`, 2026-09-30).
- Restent aussi : supervision dans `start_wama_prod.sh` ; config Claude Code du projet ;
  déclaration au registre des mécanismes — REPORTÉE, `mecanismes.py` étant en cours de
  modification par une autre instance le 15/09.

> ⚠ **Ce que MCP ne résout PAS** (question tranchée le 2026-08-20) : « lancer une requête à
> Claude Code depuis l'AI-Assistant » ne passe **pas** par MCP. `claude mcp serve` n'expose que
> les *outils* de Claude Code (Bash/Read/Edit…), **pas sa boucle d'agent** — l'orchestration
> resterait à notre charge. Le chemin est `claude -p` headless / Agent SDK avec le token
> d'abonnement (§19.3). MCP côté WAMA garde sa valeur propre : faire de **WAMA un serveur**
> d'outils pour des clients tiers — l'inverse du besoin ci-dessus, et complémentaire de
> `/api/v1/tools/` qui expose déjà les mêmes 48 outils en HTTP+token.

~~Exemples d'outils exposables : `wama_transcribe`, `wama_describe`, `wama_search_media`,
`wama_rag_query`.~~ **Dépassé par la décision du 15/09** : ce n'est pas une liste choisie qui est
exposée, c'est TOUT `TOOL_REGISTRY` — sinon MCP deviendrait une seconde surface qui dérive.

Stack : `mcp` Python SDK **1.30.0** (officiel Anthropic) + `uvicorn`, transport **HTTP
streamable** (port déclaré dans `external_sources`) ou **stdio**.

---

## 9. cam_analyzer (wama_lab)

### 9.0 Restes repêchés du handoff `REPRISE_2026-07-29` (archivé 2026-08-18, `docs/construction/archive/`)

> Pendings du handoff ortho/recalage qui n'étaient repris NULLE PART ailleurs (audit d'archivage
> 18/08) — consignés ici avant archivage du fichier. Détail complet dans l'archive.

- **2 contrôles UI de rayon** (rayon d'analyse / rayon d'intérêt) jamais créés.
- **Indicateurs de passage d'intersection À CONFIRMER** : fenêtres 26-245 s vs 12,5-71,9 s
  observées — croiser vitesse GPS, décider si `_det` se recalcule.
- **Branche perpendiculaire IGN** : tâche par fenêtre + rendu + filtre `nature` + mappage
  `nom=None` (`road_branches_at`).
- **Calibrer `FULL_TRUST_MASK_DEG`** (12° provisoire jamais confronté au réel).
- **Porter `ortho_correction` en `Binding.PURE`** ; **catégorie `SOURCE`** absente de
  `FunctionCategory`.
- **Rapport de sortie à revoir** ; **renommer** le profil `Intersections_yolo26s-segment` →
  `Complet_…` ; **validation navigateur** du rendu correction + z-order `bringToBack`.

✅ Livré — état vivant : `PROJECT_STATUS.md §5` (Cam Analyzer). Détail archivé :
`docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

### 9.2 Pipeline conflit / voie navette / vitesse-distance

**Décision archi (2026-05-07)** : YOLOPv2 pour drivable+lanes denses, YOLO+BoTSORT pour
détection+tracking, SAM3 pour marquages sparses dans les fenêtres d'intersection,
GPS+géométrie pour les estimations. SysCV/bdd100k-models et JiayuanWang-JW
**non retenus** (coût d'intégration MMCV vs gain marginal — voir analyse en
historique). Détection objets reste sur YOLOv11 (COCO/BDD), YOLOPv2 ne sert
que pour drivable+lanes.

| Phase | Description | Statut |
|-------|-------------|--------|
| **7** | Trottoirs (optionnel) : SAM3 prompt "sidewalk" en parallèle des marquages ; si insuffisant → mmseg + bdd100k-sem-seg en backend isolé | 💡 |


> Phases ✅ archivées : `docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md` — état vivant : `PROJECT_STATUS.md §5`.

### 9.2.ter Modularité incrémentale (Propositions A→F, 2026-05-14)

| Code | Sujet | Statut |
|---|---|---|
| **F** | Batching ffmpeg mini-clips → `model.track(stream=True)` natif par segment (5-10× speedup sur la part YOLO) | ✅ |
| **B** | Skip-if-done par caméra dans `process_session_task` ; `force_rerun` accepte un override | ✅ |
| **C** | Statut `PAUSED` (cancel = données partielles conservées au lieu de FAILED) ; idempotency guard COMPLETED inchangé | ✅ |
| **D** | Computers découplés en tâches Celery : `compute_lane_events_task`, `compute_temporal_segments_task`, `compute_conflict_events_task`. Orchestrateur `run_passes` dispatche selon les types demandés | ✅ |
| **A** | `AnalysisPass` accepte `camera` (per-camera granularity pour YOLO/YOLOPv2/SAM3) ; UI affiche `[front]` / `[rear]` séparés | ✅ |
| **E** | Bouton "Afficher détections actuelles" dans le pipeline panel — charge les DetectionFrames même en PROCESSING/PAUSED | ✅ |

Pattern de dépendances pour les computers découplés :
- `lane_events` : front YOLO requis
- `temporal_segments` : ≥1 caméra YOLO
- `conflicts` : LaneEvent requis (lane_events doit avoir tourné)

`_check_data_available(session, required_camera_positions)` vérifie la disponibilité des données avant de lancer un computer ; échoue proprement sinon avec un message clair.

### Phase 3 Converter (output_format inline) — état détaillé (2026-06-02)

Helper partagé `wama/converter/utils/inline_convert.py` : `apply_inline_conversion(src, fmt, preset)`
→ réutilise les backends + `quality_presets` du Converter. Appelé en fin de tâche de chaque app.

| App | Modèle (`output_format` + `output_quality`) | Câblage tâche | UI dropdowns |
|---|---|---|---|
| Synthesizer | ✅ migration 0012 | ✅ `_apply_output_format` (workers.py) | ✅ panneau (mp3/ogg/flac/m4a/aac/opus) |
| Enhancer | ✅ migration 0009 (image/vidéo + audio) | ✅ `_apply_enhancer_output_format` (tasks.py) | ✅ panneau (optgroups image/vidéo) |
| Imager | ✅ migration 0009 | ✅ conversion des images dans generate_image_task | ✅ panneau (jpg/webp/tiff/avif) |
| **Composer** | ✅ migration 0003 | ✅ dans compose_task | ✅ panneau (mp3/ogg/flac/m4a) |
| **Anonymizer** | ✅ migration 0020 | ✅ `_apply_anonymizer_output_format` (glob sortie floutée) | ✅ panneau + option **« Identique à l'entrée »** |

Backend testé et migré ; défaut `output_format='original'` = aucun changement (no-op), zéro régression.

**Anonymizer — option spéciale `'input'`** : reconvertit la sortie vers le format du fichier
SOURCE (utile si le pipeline a changé le format, ex. .mov → .mp4 imposé par le floutage → reconverti en .mov).

**Limites connues :** Imager = images uniquement (vidéo générative au format natif) ; câblage fait sur les
chemins de création (panneau) — modales settings par-item + globals `start_all` non couverts (suffit pour le cas d'usage principal).

### 9.2.bis Pass tracking — infrastructure incrémentale (à faire avant Phase 4)

Décision (2026-05-07) : tracer chaque traitement comme un `AnalysisPass`
distinct pour permettre l'analyse incrémentale, l'invalidation en cascade
(STALE) et un panneau pipeline UI clair.

> *Précisé le 2026-09-15* : ce modèle est **généralisé au commun** (ligne d'exécution par process,
> état `STALE` commun, cascade) — `WAMA_APP_GENERATION_ROUTE.md §10.6`. Granularité réelle du code :
> session × passe × **caméra** (colonne `camera`), et non « 1 row par session × pass_type » ci-dessous.

- **Storage YOLO toutes classes** : inférence à `confidence=0.10` au lieu du
  user setting, filtrage côté lecture par `target_classes` + `confidence`.
  Ajouter une classe = 0 re-inférence ; descendre conf < 0.10 = re-run.
- **Modèle `AnalysisPass`** : `(session, pass_type, status, parameters,
  output_summary, started_at, completed_at, duration_s, error_message)`.
  Granularité : 1 row par session × pass_type. Détails caméras/classes/
  paramètres dans `output_summary` JSON, exposés via tooltip + section
  repliable.
- **Détection STALE** : à chaque `save_profile` + `load_session`. Compare
  snapshot vs paramètres-watch listés dans 9.2 (model_path, road_model_path,
  prompts SAM3, low-conf 0.10). Cascade : si amont STALE, aval STALE.
- **API** : `GET /api/sessions/<id>/passes/`, `POST /api/sessions/<id>/passes/run/`
  `{types:[…], force:bool}` — orchestrateur Celery respectant les dépendances.
- **UI** : panneau "Pipeline" dans le volet droit, états ✅ ⚠ ❌ ⏵ 🛑, deux
  CTA principaux ("Compléter manquant + stale" / "Tout relancer"), section
  repliable avec un bouton ▶ par passe pour debug.

### 9.4 Production — Ingestion automatisée 💡

- Watch d'un dossier source contenant les données projet (~600 h × 1400
  parcours navette × 1 site = ~1 dataset complet par projet)
- Profil d'analyse appliqué automatiquement par session, sans intervention
  manuelle (config.profil par défaut + auto-création session)
- Throughput cible : à dimensionner ; queue Celery dédiée probablement
- Détails à préciser quand Phase 1-7 du pipeline sera stable

### 9.5 Production — Réinjection résultats dans BDD externe 💡

- Pousser les résultats d'analyse vers une autre BDD sur un autre serveur
  (probablement le data warehouse projet)
- Format de sortie à définir (JSON dump per-session ? Postgres logical
  replication ? Stream Kafka ? — décision dépendante du serveur cible)
- Schéma stable à définir : `LaneEvent`, `ConflictEvent`,
  `IntersectionWindow`, métadonnées session, GPS aggrégé
- Détails à préciser quand l'étape précédente (9.4) sera amorcée

### 9.3 Backlog & dette
- Sur-fragmentation segments temporels (`Arrêt intersection` × 200+ par session) — observée 2026-05-07. À résoudre par Phase 5 (consolidation par track_id + voie navette + intersection_window) plutôt que merge purement temporel.
- Statut session pendant `analyze_sam3_only_task` : géré (PROCESSING → COMPLETED) ✅
- `RoadSegmenter` ultralytics conservé pour fallback (modèles seg classiques) ✅
- Dispatcher tasks.py : `'yolopv2' in basename → YOLOPv2RoadSegmenter`, sinon `RoadSegmenter` ✅

---

## 10. Internationalisation (i18n) — Traduction multi-langues

> Base existante : `UserProfile.preferred_language` déjà en place dans `accounts/models.py`

> **Deux couches distinctes, à ne pas confondre :**
> - **10.A — i18n UI statique** : chaînes d'interface (`.po`/`.mo`), traduites *une fois* en batch, lookup microseconde au runtime, **zéro inférence**.
> - **10.B — Translator runtime (app)** : traduction + enrichissement *à la requête* des consignes utilisateur (AI-Assistant, prompts SAM3 / image / vidéo / musique) et des sorties textuelles trans-app, via LLM, **avec cache**.
> Un seul « cerveau » de traduction (même modèle/service) alimente les deux couches.

### 10.A — Approche retenue : Django i18n + translategemma en batch ⏳

**Principe :** translategemma:12b traduit les fichiers `.po` une seule fois en batch.
À runtime, Django sert depuis des fichiers `.mo` compilés — aucune inférence LLM.

```
Développeur ajoute une string → makemessages → .po source
translategemma traduit le .po → .po par langue (fr, en, de, es...)
compilemessages → .mo (lookup microseconde au runtime)
Middleware active la langue selon UserProfile.preferred_language
```

### État MESURÉ au 2026-08-29 — lire CECI avant la table d'étapes (qui a dérivé)

> Relevé à l'outil natif, sur demande de Fabien (« le mélange anglais/français du front-end,
> c'est consigné quelque part »). **C'est ici, §10.A.** Le chantier reste NON prioritaire : le
> portage des apps passe avant. Ce bloc existe pour qu'on le rouvre sur du mesuré, pas sur la
> table de 2026-06 dont la 1ʳᵉ ligne est déjà fausse.

| pièce | mesure |
|---|---|
| `USE_I18N` | `True` (`wama/settings.py:478`) — ⚠ **ce n'est PAS une réalisation** : c'est la valeur **par défaut de Django**, l'interrupteur qui *autorise* la machinerie gettext. Avec 0 `.po` et 2 gabarits taggés derrière, il ne traduit **rien**. Il ne rend périmée que la 1ʳᵉ ligne de la table d'étapes, pas le chantier (remarque de Fabien, 2026-08-30 : « j'ai vu passer un `True` en face de i18n, mais il n'est pas réalisé ») |
| `LANGUAGE_CODE` | `'en-us'` — alors que l'UI rendue est très majoritairement française |
| `LOCALE_PATHS` + dossier `locale/` de projet | **absents** (les milliers de `.po` du dépôt sont ceux de Django, dans le venv) |
| `LocaleMiddleware` / `UserLanguageMiddleware` | **aucun des deux installé** → le champ de profil ne pilote PAS la langue de l'**interface Django**. ⚠ Il pilote bien la langue du **contenu** : voir la ligne suivante |
| `UserProfile.preferred_language` | **LU, et par beaucoup de monde** (mesuré à l'outil natif le 2026-08-29) : `synthesizer/views.py` (langue par défaut d'une synthèse), `wama/views.py:89` + `home.html` (voix TTS, `VOICE_LANG`, `recognition.lang`), `common/services/assistant_engine.py`, `common/utils/prompt_pipeline.py:28`, `common/utils/app_metadata.py:276`, `common/views.py:63`, et il est exposé au contexte **global** par `accounts/context_processors.py:146`. C'est la source de langue du CONTENU dans toute la chaîne LLM |
| `{% trans %}` dans les gabarits | **16 occurrences, dans 2 fichiers sur 128** : `reader/_item_card.html` (15) et `common/_download_button.html` (1) |
| `gettext` en Python | 3 fichiers (`anonymizer/models.py`, `common/utils/export_formats.py`, `accounts/custom_validators.py`) |
| **gabarit GÉNÉRÉ** | `common/manifests/codegen/templates_gen.py` émet **8 libellés français EN DUR** et **zéro `{% trans %}`** — chaque app (re)générée en ajoute autant |

### ✅ CE QUI EXISTE DÉJÀ EN CODE — à lire avant le tableau ⏳, sinon il se lit « rien n'est fait »

> Précision demandée par Fabien (2026-08-30) : *« la traduction de l'UI est à 0, mais il me semble
> que le code, lui, est opérationnel ; ce qui manque c'est le corpus anglais avec les balises et le
> corpus traduit »*. **C'est exact pour l'essentiel**, et les ⏳ ci-dessus ne doivent pas laisser
> croire qu'il faudrait écrire un moteur. Ce qui manque se répartit en trois masses très inégales :

| pièce | état | à écrire |
|---|---|---|
| **Moteur de rendu** (lookup `.mo`, `{% trans %}`, `gettext`, `makemessages`/`compilemessages`) | ✅ **fourni par Django** | **rien** — il n'y a jamais eu de code à produire ici |
| **Cerveau de traduction** (ce qui remplira les `.po`) | ✅ **ÉCRIT** — `common/utils/translator.py` : `TranslatorService` (translategemma:12b via `llm_chat`), cache Django 30 j clé sha256, découpage ~4000 c, **glossaire « ne pas traduire »**, passthrough si source == cible. Plus `common/utils/lang_routing.py` (décideur) | **rien** — il est déjà utilisé en runtime par la traduction IN |
| **Plomberie de locale** | ⏳ **absente, mais MINUSCULE** : `LOCALE_PATHS` + dossier `locale/`, un middleware qui pose la langue depuis `preferred_language`, et un pilote `translate_po` (aucune commande de ce nom dans `common/management/commands/`) | ~1 j au total (cf. table d'étapes) |
| **LE CORPUS** — les `{% trans %}` à poser, puis les traductions à produire | ⏳ **c'est 95 % du chantier** : **2 gabarits sur 128** taggés, 3 fichiers Python, et le générateur d'apps qui en fabrique de nouveaux non taggés à chaque régénération | **3-6 semaines** |

⇒ **Le chantier n'est pas « écrire l'i18n », c'est « produire et maintenir le corpus »** — et c'est
précisément pour ça que la décision bloquante ci-dessous (la langue des `msgid`) coûte cher : elle
décide si ce corpus se **tague** (FR) ou se **tague ET se traduit deux fois** (EN source).
*Note de méthode : ne jamais réduire cet état à « rien n'existe » — c'était le glissement de la
formulation précédente, cf. [[feedback_un_releve_par_motif_ne_conclut_pas]] §corollaire 30/08.*

### ⚠ TROIS choses distinctes derrière « la langue » — ne pas les confondre (rectifié 2026-08-30)

> Rectification demandée par Fabien : une version antérieure de ce bloc écrivait que « rien ne lit
> `preferred_language` », phrase qui se lit comme « le champ ne sert à rien ». **C'est faux** — et la
> mesure ci-dessus le montre. Le champ est la **source de langue du contenu** ; ce qu'il ne pilote
> pas, c'est la locale Django de l'interface. Trois chantiers, trois états :

| # | ce que c'est | état RÉEL |
|---|---|---|
| 1 | **Langue de l'INTERFACE** (libellés de gabarits, boutons, en-têtes) | ⏳ **rien** — c'est le §10.A, le « mélange » visible à l'écran. Ni `.po`, ni middleware de locale |
| 2 | **Traduction IN** (consigne utilisateur → langue du modèle) | ✅ **EN PLACE** — `prompt_pipeline.py:129` appelle `TranslatorService.translate_input()` sur la décision de `lang_routing` ; la langue source vient de `preferred_language` |
| 3 | **Traduction OUT** (sortie du modèle → langue de l'utilisateur, avec surcharge possible) | ⏳ **MANQUANT** — `TranslatorService.translate_output()` **existe** (`common/utils/translator.py:67`) mais **aucun appelant** (vérifié : 0 consommateur hors du fichier lui-même). Voir §10.B |

**Placement décidé par Fabien (2026-08-30) : la traduction OUT part avec le chantier de génération
de l'app Translator (§10.B), qui vient APRÈS la fin du portage par auto-génération.** Elle applique
la langue du profil par défaut, **tout en laissant l'utilisateur choisir une autre langue de sortie**
— dans les apps qui le permettent et **où cela n'altère pas le résultat** (une transcription
verbatim, par exemple, n'est pas une sortie qu'on retraduit sans le dire).

### 🧭 Doctrine de langue (posée par Fabien, 2026-08-30)

> **L'anglais est la langue de référence dans tout WAMA, a minima pour tout le CODE.**
> **Les docs en français ne posent pas de problème tant qu'elles servent le suivi du développement.**

C'est le cadre au-dessus des deux frontières : `AGENTS.md` § « la LANGUE des identifiants » en est
l'application au code (et son critère « qui doit le lire ? » en découle), et la question des `msgid`
ci-dessous s'y rattache — un `msgid` est écrit **dans le code source**, ce qui penche pour l'anglais.

✅ **ARBITRAGE TRANCHÉ (Fabien, 2026-08-30)** : *« J'avais déjà décidé ça. L'anglais est la langue
de WAMA, même si la doc est en français par commodité. On doit se baser sur la langue
internationale. Donc `msgid` en anglais. Le français n'en est qu'une traduction. »* Les 16 tags
existants à `msgid` français (reader, `_download_button`) sont donc À RETOURNER quand le chantier
s'ouvrira — 16 occurrences, pas une dette. **ET le séquencement est décidé du même geste : la
traduction ATTEND LA FIN DU PORTAGE** — « on ne peut pas bloquer le portage pour la traduction ;
terminer le portage est la priorité : ça débloque ensuite le studio et le monde Data (en
parallèle) + le cam analyzer laissé en suspens ». Ce paragraphe lève le 🔴 ci-dessous en tant que
DÉCISION ; le chantier lui-même reste fermé jusqu'à la fin du portage.

### 🔴 CE QUI BLOQUE 10.A n'est pas l'effort, c'est une DÉCISION : la langue des `msgid`

Les 16 tags déjà posés portent des `msgid` **français** (`{% trans "Entrée" %}`). Le reste du
dépôt déclare l'inverse : `WAMA_MANIFEST_SPEC` « Langue du manifeste = ANGLAIS canonique […] en
anglais SOURCE », `WAMA_MANIFEST_ARCHITECTURE` « manifeste en EN canonique → registre i18n
central », et `LANGUAGE_CODE = 'en-us'`. Le désaccord ne se voit pas aujourd'hui : **sans `.mo`,
un `msgid` est rendu TEL QUEL** — le français passe donc *par accident*, et passera jusqu'au jour
où on compilera des traductions.

| option | coût | ce que ça heurte |
|---|---|---|
| **`msgid` = français** (entériner l'existant) | tagger les gabarits ; aucune traduction à écrire pour le FR | contredit le pivot EN déclaré côté manifestes ; `msgid` accentués, plus fragiles en outillage |
| **`msgid` = anglais** (doctrine déclarée) | tagger les gabarits **ET** traduire toute l'UI FR→EN pour *fabriquer la source*, avant de la retraduire en FR | rien de déclaré, mais l'effort de la table ci-dessous est ~doublé |

⚠ **Ce n'est PAS la frontière tranchée par `AGENTS.md` § « la LANGUE des identifiants »** (« qui
doit le lire ? »). Celle-là concerne les IDENTIFIANTS (modules, fonctions, fichiers `.js`, globals)
→ anglais. Ici il s'agit des **CHAÎNES AFFICHÉES**, l'autre versant : un identifiant anglais
affiche très bien un libellé français, et c'est même la cible. Les confondre ferait renommer du
code au motif d'une question de traduction, ou l'inverse.

**Assurance la moins chère tant que 10.A n'est pas ouvert** (et elle ne l'ouvre pas) : tagger
`codegen/templates_gen.py` — **un seul fichier, 8 libellés** — pour que les apps générées naissent
taggées. Sinon le portage en cours fabrique, gabarit après gabarit, la couche qu'il faudra reprendre.

### Étapes ⏳

| Étape | Effort | Fichier / Commande |
|-------|--------|-------------------|
| ~~`USE_I18N = True`~~ (**défaut Django, rien à faire — ne pas lire comme une étape franchie**) + `LOCALE_PATHS` + dossier `locale/` | 5 min | `wama/settings.py` |
| Middleware `UserLanguageMiddleware` | 30 min | `wama/common/middleware.py` |
| **Tagging strings templates** (`{% trans %}`) | **3-5 semaines** | ~60-80 fichiers HTML |
| Tagging strings Python (`_()`, `gettext_lazy`) | 1 semaine | models.py, forms.py, views.py |
| Script batch `translate_po.py` via translategemma | 1-2 jours | `wama-dev-ai/` ou `manage.py` cmd |
| Compilation + tests par langue | 1 jour | `compilemessages` |

### Langues cibles (à confirmer selon perf translategemma:12b)
FR · EN · ES · DE · IT · PT · NL · JA · ZH

### Notes techniques
- Le middleware doit s'exécuter **après** `AuthenticationMiddleware`
- Les strings JS nécessitent `{% trans %}` dans les templates ou `JavaScriptCatalog` view
- wama-dev-ai (Phase 2+) pourrait automatiser le tagging des templates via `search_content` + `edit_file`
- Régénération des `.po` à chaque ajout de string : intégrable dans le workflow CI ou wama-dev-ai nightly

---

### 10.B — Translator runtime : enrichissement + traduction des consignes & sorties ⏳

> **Vision.** L'utilisateur s'exprime et visualise WAMA **dans sa propre langue**. L'anglais (ou la langue
> optimale du modèle) n'est qu'un **pivot interne**. Toute consigne libre (AI-Assistant, prompt SAM3,
> prompts image/vidéo/musique/bruitages) passe par un workflow d'**enrichissement (prompt + RAG)**
> et de **traduction** afin d'optimiser la requête quels que soient la langue et le niveau de détail.

#### Principe directeur : l'anglais comme pivot interne
- L'utilisateur écrit et lit **toujours** dans sa langue.
- **Entrée** (consigne → modèle) : on optimise *vers* la langue cible du modèle.
- **Sortie** (modèle → utilisateur) : on retraduit *vers* la langue de l'utilisateur — sauf réglage
  « langue d'origine » ou demande explicite d'une cible de traduction en sortie.

#### Sens du workflow d'entrée — décision actée
Ne **pas** enchaîner deux traductions automatiques naïves. Préférence, dans l'ordre :

| Schéma | Verdict |
|--------|---------|
| Traduire d'abord, enrichir ensuite | ❌ perte d'intention sur prompt court, erreurs propagées |
| Enrichir en langue native, **traduire en dernier** | 🟡 fallback acceptable si réutilisation d'un service MT générique |
| **Passe LLM unique : comprendre → enrichir (RAG) → émettre directement dans la langue cible** | ✅ **retenu** — pas de double-traduction, prompt cible idiomatique |

→ **Retenu : passe LLM jointe** (détecter langue source → comprendre l'intention → récupérer RAG →
produire le prompt optimisé directement dans la langue/format du modèle cible). Équivaut au
« prompt upsampling » des générateurs modernes.

#### Garde-fous transversaux
- **Glossaire « ne pas traduire »** : noms propres, **termes métier Lescot (SHS / ergonomie / transports)**,
  hotwords, noms de fichiers, code, entités nommées → masquage par placeholders avant MT, restauration après.
- **Carte langue-cible par modèle** : SDXL / Flux / SAM3 / MusicGen / AudioGen → **EN** ;
  SAM3 = **nom de concept court EN** (pas une phrase d'instruction — cf. bug « Floutes les visages » → 0 masque) ;
  Qwen / describer multilingues → langue native possible.
- **Passthrough + cache** : si langue source == cible → skip ; cache `(texte, langue_cible, modèle) → résultat`
  pour éviter de ré-inférer (UI répétée, prompts identiques).
- **Détection de langue** rapide en amont (gate cheap : lingua / fasttext) avant tout appel LLM.
- **Tiering modèle** : détection + MT simple = modèle léger ; enrichissement = LLM fort (describer / Qwen).

#### Usages (une seule app `wama/translator/`, plusieurs points d'entrée)
1. **Traduction UI** — alimente la génération batch des `.po` (§10.A) avec le même cerveau.
2. **Optimisation de prompt** — pré-traitement des consignes de génération (image/vidéo/musique/SAM3).
3. **Traduction des consignes AI-Assistant** — comprendre l'intention quelle que soit la langue.
4. **Traduction trans-app des sorties textuelles** — transcriptions, descriptions, résumés, OCR…
   affichés/exportés dans la langue de l'utilisateur.

#### État MESURÉ au 2026-08-30 — la moitié IN est faite, la moitié OUT ne l'est pas

| pièce | état |
|---|---|
| `TranslatorService` (`common/utils/translator.py`) | ✅ existe — `translate()`, `translate_input()`, `translate_output()`, cache Redis 30 j, chunking, glossaire |
| **IN** — `translate_input()` | ✅ **branché** : `common/utils/prompt_pipeline.py:129`, sur décision de `lang_routing`. C'est l'auto-traduction des consignes, en place |
| **OUT** — `translate_output()` | ⏳ **écrit mais JAMAIS appelé** — `grep` natif : 0 consommateur hors du fichier. C'est LE trou de §10.B |
| Exposition assistant | ✅ `tool_api.py:2130 translate_text(...)` (appel manuel, pas la chaîne automatique) |

> **Ordre décidé (Fabien, 2026-08-30)** : la traduction OUT se fait **avec la génération de l'app
> Translator**, qui vient **après la fin du portage par auto-génération**. Ne pas la brancher au
> coup par coup app après app entre-temps : ce serait exactement le câblage dispersé que le portage
> est en train de supprimer.
>
> **Contrat de la sortie** : langue du profil par **défaut**, surcharge explicite possible par
> l'utilisateur, **uniquement dans les apps où retraduire n'altère pas le résultat** (⚠ contre-exemple :
> une transcription verbatim — cf. `project_transcription_fidelity_profiles`, « la cohérence détruit
> le verbatim »).

#### Étapes ⏳
| Étape | Effort | Fichier / Note |
|-------|--------|----------------|
| App `wama/translator/` + service `TranslatorService` (detect/translate/enrich) | 2-3 j | centralisé dans `common/` pour appel inter-app |
| API outil AI-Assistant (`translate`, `enrich_prompt`) | 0.5 j | `tool_api.py` |
| Glossaire « do-not-translate » + masquage placeholders | 1 j | terminologie Lescot configurable |
| Carte langue-cible par modèle + hook pré-génération (imager/composer/anonymizer SAM3…) | 1-2 j | point d'injection unique par app |
| Cache traductions/enrichissements (Redis) | 0.5 j | clé `(hash, lang, model)` |
| **Brancher `translate_output()` aux sorties textuelles** (le trou mesuré ci-dessus) | 1-2 j | point d'injection unique, comme `prompt_pipeline` l'est pour l'entrée |
| Réglage utilisateur « langue de sortie / langue d'origine » | 0.5 j | `UserProfile` (étend `preferred_language`) — défaut = profil, surcharge par run |

#### Décisions actées
- **Pivot interne = anglais** ; l'utilisateur ne le voit jamais sauf réglage explicite.
- **Workflow d'entrée = passe LLM jointe** (comprendre→enrichir→émettre en langue cible), pas de MT en chaîne.
- **i18n statique (10.A) et Translator runtime (10.B) restent deux couches** mais partagent le modèle de traduction.

#### Raffinements (décidés 2026-06-21)
- **La « carte langue-cible par modèle » = `AIModel.capabilities['languages']`** (la métadonnée déjà construite), PAS une carte codée en dur. L'orchestrateur lit les capacités du modèle choisi → décide direct/traduction. Unifie la traduction avec `model_selector` + la chaîne de gestion intelligente des modèles.
- **PAS de pivot EN forcé en runtime** : pivot **seulement si le modèle l'exige** (générateurs EN-only : SDXL/Flux/SAM3). Un modèle **multilingue** → rentrer **directement** dans la langue (> 2 traductions). (Le pivot EN reste pour 10.A / l'enrichissement de prompt des générateurs.)
- **🔑 Transparence pré-lancement (NOUVEAU)** : avant que l'utilisateur lance, afficher la décision résolue — « ⓘ média en *X*, le modèle *Y* ne gère pas *X* → traduction auto en amont/aval (qualité possiblement réduite) ». Consentement éclairé, jamais de dégradation silencieuse.
- **Médias non-textuels** : « traduire l'entrée » ne vaut que pour les entrées **textuelles** (docs/transcripts) ; pour image/audio/vidéo, seuls le **prompt** et la **sortie** ont une langue.
- **Caveat « universel » = best-effort** (FR/EN excellent, ZH/RU/ES correct, langues rares variables) → d'où la couche de transparence.

#### Graine posée (2026-06-21) — Describer
Branche « direct » de §10.B appliquée au Describer : `image_describer._vision_prompt(output_format, output_language, model)` prompte le modèle vision **dans `output_language`** si le modèle est multilingue (gemma4/qwen), sinon EN (reformaté en aval). Évite la chaîne « caption EN → reformatage FR ». Limite graine : FR/EN seulement (les autres langues → EN ; §10.B complet généralisera via translategemma). Lié au câblage gemma4:12b comme describer ([[project-intelligent-architecture]]).

#### Compréhension de documents ≠ traduction (décidé 2026-06-21)
**Distinction clé** : « comprendre un document scientifique (figures, schémas, layout) » n'est PAS un problème de traduction. Traduire le **texte** d'un PDF structuré **détruit** figures/mise en page/explications visuelles. Deux couches :
1. **Ingestion** : doc → contenu structuré (texte + **figures extraites comme images** + tableaux + ordre de lecture) → **Docling** (IBM). À brancher dans l'app **Reader** (déjà OCR olmOCR/doctr).
2. **Compréhension multimodale** : un modèle qui VOIT texte + figures et restitue **directement dans la langue cible** → gemma4:12b (multilingue + vision). Avec un bon modèle multilingue → sortie native, **AUCUNE traduction** (`lang_routing` renvoie `direct`).
- **🔴 Garde-fou** : NE JAMAIS « traduire le texte d'entrée » d'un document structuré (préprocessing). `input_translate` = prompts COURTS + sorties texte finales, PAS l'ingestion de documents.
- **Placement (corrigé)** : la description/synthèse de documents scientifiques est **GÉNÉRIQUE** → sous-page/mode « document » du **Describer** (tout chercheur peut l'utiliser). **OpenScholar** (synthèse de littérature RAG multi-papiers + citations) = sous-page du Describer. **WAMA Lab** est réservé au **spécifique métier** (données expérimentales labo, oculométrie, trajectoires Lescot), PAS la description scientifique générique.
- Architecture cible : **Reader/Docling** (parse) → **modèle multimodal multilingue** (gemma4:12b) → **synthèse FR directe**. `synthese-doc` à évaluer.

#### L'app Translator — décisions de Fabien du 2026-10-16

> Après un premier essai parti de LibreTranslate (un serveur Flask : 8 dépendances épinglées, un
> conflit `numpy<2`, 11 manquantes) : *« On a déjà des outils de traduction intégrés dans WAMA,
> dans le commun. Ne peut-on pas réutiliser ça ? »*

- **Nom : Translator**, clé `translator` — comme les autres apps (Transcriber, Describer…), jamais
  `translate`. La jumelle `translate_01` est retirée (16/10).
- **Moteur : la brique commune**, mécanisme `translator` (`common/utils/translator.py`, déclaré le
  16/10) — modèle désigné par une CLÉ DE CATALOGUE (défaut `ollama:translategemma:12b`), cache,
  glossaire, découpage, `on_chunk`. LibreTranslate n'est plus le moteur : au mieux un second backend
  plus tard (`library:libretranslate`, validée et vendorisée le 16/10, reste au registre). Ce qui
  avait été décidé le 12/08 (« LibreTranslate = backend dédié ») est donc remplacé, pas oublié.
- **Deux modes, une app** :
  1. **fichier** (file d'attente) : un document déposé, traduit en tâche ; l'aperçu « pendant » montre
     le texte qui se traduit (`preview_utils.publish_partial_text`, appelé par `on_chunk`) — la face
     qu'ont déjà le Transcriber et le Describer ;
  2. **saisie « à la DeepL »** : la traduction s'affiche PENDANT la frappe, sans passer par la file —
     le côté instantané. ✅ **Bâtie COMMUNE et DÉCLARÉE le 16/10** (`45e2cac6`) : capacité d'app
     `instant_preview` + route `instant` du manifeste, d'où dérivent la vue générée, sa route et
     le trou de glu `instant_result(item)` ; brique `wama-instant.js` (délai de saisie, seule la
     dernière réponse s'affiche) — `CARD_DESIGN §11.11 D bis`, mécanisme `instant_result`. Toute
     app texte → texte rapide peut la déclarer.
- **⚠ Le garde-fou du 21/06 ci-dessus reste vrai et ne s'oppose pas à ceci** : il interdit de
  traduire un document structuré EN PRÉTRAITEMENT d'une compréhension. Ici la traduction est le
  LIVRABLE, et elle doit justement préserver la structure.

##### Documents (PDF, DOCX…) : garder la forme d'origine — chantier progressif ⏳

Intention de Fabien : *« trouver petit à petit le moyen de conserver la mise en forme du document
d'origine tout en appliquant les traductions au texte, et aux contenus médias (graphes, images…).
Il y a tout ce qu'il faut ou presque dans WAMA. »* Conforme au 12/08 : un **pipeline** (extraction
des blocs → traduction segmentée → remise en forme → rendu), pas une app monolithique.

Ce qui EXISTE, vérifié dans le code le 16/10 :

| maillon | brique | état |
|---|---|---|
| découper un texte en sections, réécrire UNE section | `common/utils/document_sections.py` (`split_sections`, `patch_section`) | ✅ |
| DOCX / ODT / HTML / MD ↔ autres formats | `converter/backends/document_backend.py` (pandoc) | ✅ |
| HTML → PDF fidèle | `common/utils/html_render.py` (Chromium) | ✅ |
| séparer le FOND de la FORME, et appliquer une forme à un fond | Writer : process `write` / `layout`, port « Modèle de mise en page » (`reference_layout`, lu pour sa FORME) | ✅ |
| structure des tableaux d'un document | Reader : `table_transformer` | ✅ |
| texte d'une image (OCR), puis image rééditée | Reader (OCR) ; Imager (édition d'image, qwen-image-edit) | ✅ les deux apps, ⏳ leur enchaînement pour traduire le texte d'une figure |
| parse structuré des PDF (blocs, figures, ordre de lecture) | Docling, prévu le 21/06 | ⏳ **absent du code** (aucun import) |

Deux voies, complémentaires :
1. **Traduire, puis ENVOYER VERS le Writer** — EXISTE (« Envoyer vers », `common/services/
   send_to.py` → import du Writer) : le texte traduit arrive en ENTRÉE PRINCIPALE du Writer
   (`reference_document`, le FOND) ; le document d'origine se pose comme « Modèle de mise en page »
   (`reference_layout`) dans la card du Writer, à la main — le geste envoie vers l'entrée
   principale, sans choix de port. ⏳ Seule extension possible, non décidée : choisir le port
   d'arrivée à l'envoi. Rien d'autre à construire ; reste à le vérifier sur un vrai document.
2. **Traduction en place** : traduire chaque section/bloc et le réécrire dans le document
   (`patch_section` pour le texte ; DOCX par pandoc ; PDF par HTML + Chromium) ; les figures par
   OCR → traduction → réédition d'image. Plus fidèle, plus long : à construire maillon par maillon,
   chaque maillon jugé sur un document réel.

##### Naissance du Translator au bac à sable — 2026-10-16 (soir) 🔄

- **Brouillon** rédigé par le rôle `app` de wama-dev-ai (local, qwen3.8 ; `--like synthesizer
  --requires model:ollama:translategemma:12b`), trois essais. Deux défauts du RÔLE réparés en route :
  la génération à blanc ne jouait qu'en l'absence de faute de forme (un brouillon sans `processing`
  ne rapportait qu'une faute) ; et le modèle refermait `body` après `params`, posant `processing`,
  `models`, `inspector`, `access`, `studio` À LA RACINE — l'enveloppe les remet dans le corps et le
  dit (`run_app_manifest.enforce_envelope`, vocabulaire fermé `APP_FACETS`).
- **Corrections du superviseur**, chacune pour une raison vérifiée — le brouillon validé est
  `manifests/app_drafts/translator.json` : monde `media` (comme synthesizer/reader/writer) ; route
  `instant` en DOUBLE dans `extra_routes` retirée ; `prompts.targets` retiré (le pipeline de prompts
  traduirait ou enrichirait le texte AVANT de le traduire) ; la saisie déclarée en RÉGLAGE `prompt`,
  comme la consigne du Writer — c'est ce qui lui donne sa colonne, le port seul n'en crée aucune
  (mesuré : anonymizer, avatarizer et synthesizer ont un port `prompt` SANS colonne, donc pas de
  règle de gabarit « un port de consigne = une colonne ») ; sélecteur `options_query: {model_type:
  llm}` — translategemma est rangé `text-generation` + `specialisation: translation`, la requête
  `task: translation` ne trouvait rien et le repli servait… les modèles de l'imager.
- **Né** : `translator_01` (`app_sandbox create --from-manifest`, smoke de file habitée vert). Glu
  écrite par le superviseur sur les briques : `TranslatorService` (modèle tiré par
  `resolve_model_choice(..., specialisation='translation')` → translategemma), lecture du document
  par `reference_comprehension.read_document_text`, aperçu par `publish_partial_text`. Essayé pour
  de vrai : saisie (1,7 s, 0,05 s en cache) ; `.md` traduit en gardant titres et paragraphes, le
  terme du glossaire préservé. ⚠ La glu vit dans le bac à sable (non versionné) : la promotion reste
  un geste humain.
- **Brique `translator` corrigée** : « de « auto » vers « en » » rendait le texte INCHANGÉ. Les
  langues se nomment par code ISO 639-1 et une source inconnue se fait détecter — mesuré 9/9 puis
  16/16 (la forme « vers « en » » seule : 4 ratés sur 9) ; `PROMPT_VERSION` entre dans la clé de
  cache, pour qu'une consigne corrigée ne resserve pas 30 jours les traductions fausses.
- **Revérification du même jour** : la capacité, écrite `has_instant_result`, prend le nom que la
  spec réservait (`instant_preview`) ; les langues du brouillon, recopiées par le rôle en 13
  entrées, sont projetées du vocabulaire commun `common/tts/constants.LANGUAGE_CHOICES` (15).
  ⏳ Manque de mécanisme : un schéma d'app NÉE D'UN MANIFESTE ne porte que des choix LITTÉRAUX
  (une app réelle les dérive de son modèle, `derive_from_model`) — rien ne lui fait lire un
  vocabulaire déclaré ; la liste se re-projette donc à la main si le vocabulaire bouge.
- 🔴 **BLOQUANT, mesuré au smoke du 2026-10-17 après relance** : la route `instant` traduit, mais
  la page `/translator_01/` n'a NI saisie NI zone instantanée. `views_gen.prompt_entry` ne connaît
  que deux formes d'entrée (attache = consigne sans port de travail ; sinon dépôt), et la forme
  MIXTE (l'un OU l'autre crée un élément, celle du synthesizer) n'est déclarée nulle part — les dix
  pages réelles l'écrivent à la main. Même trou que `tests_codegen_templates`
  (`test_a_prompt_first_app_with_optional_cover_ports_stays_in_attach_mode`, en `expectedFailure`
  depuis le 03/10). Un critère par `modes.domains` a été essayé puis RETIRÉ : les domaines parlent
  le vocabulaire des slots, pas celui des ports (pansement). **Transmis le 2026-10-17 à la session
  « Portage apps media »** (décision de Fabien : c'est du portage) — la déclaration (par port « suffit
  à créer », `required`, ou capacité d'app) reste à soumettre à Fabien.
- ⏳ Reste : juger l'app à l'usage ; vérifier « Envoyer vers » le Writer sur un vrai document
  (voie 1 ci-dessus).

---

## 11. Déploiement — Migration vers serveur Linux dédié

> Détail DÉPLACÉ (2026-07-25, plan doc B9-§11) : la référence unique est
> **`INFRA_WSL_VS_WINDOWS.md` § « Implications pour le passage en prod full-Linux »** (systemd,
> chemins `/mnt/d` en dur, `OLLAMA_HOST`, secrets ✅ 2026-07-23). Plan serveur : `memory/
> project_deployment_roadmap.md`. Jalon macro : Apache Windows → Nginx Linux, LiteLLM orchestrateur.

## 12. Décisions actées

| Décision | Date | Raison |
|----------|------|--------|
| wama-analysis abandonné | 2026-04-07 | Code analysis + wama-dev-ai plus efficaces pour inventaire features et tests |
| gemini-3-flash-preview non intégré | 2026-04-07 | Modèle cloud (`:cloud` tag Ollama) — incompatible principe local-first |
| llava:34b supprimé d'Ollama | 2026-04-07 | Aucun usage production WAMA (dépendait de wama-analysis) |
| llama3.2-vision:11b supprimé d'Ollama | 2026-04-07 | Aucun usage production WAMA |
| gemma3:4b supprimé d'Ollama | 2026-04-07 | Remplacé par gemma4:e4b |
| LTX-Video (ancien) supprimé — 26.5GB | 2026-04-07 | Remplacé par LTX-Video-0.9.8-13B-distilled |
| amazing-logos-v2 supprimé — 3.6GB | 2026-04-07 | Obsolète SD1.5 2023, remplacé par FLUX LoRA Logo |
| LogoRedmond supprimé — 0.16GB | 2026-04-07 | Obsolète SDXL 2023, remplacé par FLUX LoRA Logo |

---

## 13. Backlog non priorisé

- **Anonymizer** : import dossier récursif avec détection récursive
- **Synthesizer** : ETA par item + ETA global batch
- **Reader** : export batch PDF résultats OCR
- **Imager** : galerie des générations passées par utilisateur
- **Model Manager** : UI affichage VRAM temps réel multi-GPU
- **AI assistant WAMA** : historique conversations par utilisateur (dépend RAG §8c)
- **Accounts** : 2FA optionnel
- **wama-dev-ai** : ajout outil `web_fetch(url)` pour veille modèles sans cron séparé
- **Describer** : intégration `Llama-3.1_OpenScholar-8B` — à benchmarker vs Qwen3.5:9b sur corpus Lescot avant décision
- **RAG** : connecteur Isidore API (SHS francophones) comme source d'enrichissement secondaire (§8c Phase 2+)

---

## 14. Couche MÉTADONNÉES d'app — la fondation transverse (PRIORITÉ stratégique)

> Insight clé (2026-06-17) : **5 chantiers majeurs consomment la MÊME métadonnée d'app.**
> La formaliser est le levier à plus fort impact ; tout le reste en découle.

Chaque app WAMA expose, en source unique :
- **Tool API** (`tool_api`, FAIT — 36 outils) ;
- **Capacités modèles** (cloning, langues, modalités, aptitude par tâche, VRAM) — cf. §5b ;
- **Schéma de paramètres** (`params.py` / `WamaParams`, amorcé Transcriber) ;
- **Capacités d'app** (`has_realtime`, `has_edit_page`, **types d'ENTRÉE/SORTIE + formats**) ;

Consommée par : **(1) UI** (modale/volet + filtrage voix/langues), **(2) Agent IA** (mode C
hybride : pilotage + choix outil/modèle par tâche), **(3) Méta-app pipeline** (§15), **(4)
orchestrateur de modèles** (§5b/§8d), **(5) génération/scaffold d'apps**.
→ **Règle de migration** : migrer une app = solidifier sa métadonnée (params + capacités +
I/O typés + tool API), pas seulement déplacer du HTML. À faire AVANT de migrer en masse.
Mode visé = **C (hybride chat ↔ UI synchronisés)**.

## 15. Méta-app « Pipeline » → livrée = **Studio**

> ✅ **LIVRÉE sous le nom STUDIO** (`wama/studio`, app dédiée) — la réalisation dépasse la
> spec d'origine (2026-06-17) : canvas nœuds-app métadonnée-driven, ports typés, persistance
> (`StudioPipeline`), **exécution réelle V1** (moteur Celery topologique via `tool_api`),
> cards d'entrée/sortie ↔ médiathèque, animation de flux. État vivant : `PROJECT_STATUS §15/§37`.
>
> Divergence assumée vs spec : le canvas est finalement **vanilla JS + SVG** (vérifié
> 2026-07-20 : aucune lib React Flow/Rete/LiteGraph), pas de réutilisation de lib node-graph.
> Restes ouverts (repris en Horizons H1.3) : runners restants, sorties → dossier studio,
> appliquer une chaîne à une file (batch), entrée « contexte » (gatée RAG §8c).
> *Précisé le 2026-09-15 → `WAMA_APP_GENERATION_ROUTE.md §10.6`* : les nœuds ne sont plus seulement
> des « nœuds-app » (fonctions et source `dataset_input` depuis le 09-09, type `pipeline` prévu) ;
> « appliquer une chaîne à une file » devient **charger un pipeline dans une card de file** (card =
> instance de pipeline) ; restes ajoutés : catalogue renommé « Catalogue » en sections repliables,
> pipelines sauvegardés visibles au catalogue, glisser-déposer (§10.6 point 5.4).
> Spec d'origine archivée : `docs/construction/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

## 16. Grappe IA de DEV + orchestrateur cloud/local (chantier infra — à cadrer)

> Vision : multi-agents dev (Claude Code + Codex UGE + Headroom) côté DEV ; orchestrateur de
> modèles cloud/local côté PROD pour l'AI-Assistant. Analyse externe reçue 2026-06-17.

**Décisions actées :**
- **Réutiliser, ne pas réécrire** : LiteLLM (routeur modèles, déjà §8d), MCP (exposer
  `tool_api` existant — PAS un protocole maison), Headroom (compression tokens, dev), cron/
  tâche planifiée (pas de scheduler maison). N'introduire LangGraph/CrewAI que si réel besoin.
- **3 couches, dépendance unidirectionnelle** : Dev Cluster (PC dev, moi seul) → lit/teste →
  Core AI prod (routeur+RAG+MCP+prefs) → apps. La prod ne connaît jamais le dev.
- **Plein local par défaut**, mixte cloud opt-in (consentement 1ère connexion, modifiable).
  L'orchestrateur = **extension de `model_selector`** (ajouter pool cloud + politique
  local/mixte + état VRAM live), pas un nouveau module.

**Corrections vs l'analyse externe (critique) :**
- **Sécurité MCP** : outils dev/admin (`run_tests`, `open_branch`…) dans un serveur MCP
  **séparé/process distinct**, JAMAIS chargés dans le process prod (défense en profondeur >
  simple scope de jeton).
- **Headroom ≠ filtre de confidentialité** : compression LOSSY (OK pour logs/dev). La privacy
  avant cloud = **Anonymizer** (déterministe), pas Headroom. Ne pas confondre les deux.
- **Sous-exploite l'existant WAMA** : `tool_api`=MCP-ready, `AIModel`=registre (105 entrées),
  `model_selector`=couche policy, RAG §8c, LiteLLM §8d déjà planifiés → **bridger**, pas rebâtir.
- **« 100+ modèles »** trompeur : ~10-15 modèles CORE réellement actifs (le reste = variantes
  YOLO/Ollama). Veille ciblée sur les core, pas sur 100+.
- **Concurrence (3 modèles + juge)** : gaspille les quotas → préférer **spécialisation** par
  type de tâche (Codex = implémentation bornée, Claude = archi/intégration).
- **Conventions** : `WAMA_APP_CONVENTIONS.md` existe déjà → l'étendre (PAS de nouveau fichier).

### 16.1 Auto-maintenance Ollama — détection vs prospection (décidé 2026-06-18)

> Ollama = bon pilote (pull sans risque de deps, déjà dans le catalogue `AIModel`).
> **« Automatisée » = détection + rapport ; JAMAIS l'action (pull/replace).**

| Couche | Quoi | LLM ? | Action |
|--------|------|-------|--------|
| **Détection** (faire en 1er) | tâche Beat : `ollama list` + registre Ollama → flag « MAJ dispo » sur les AIModel ollama (digest/tag plus récent) | ❌ déterministe | rapport, jamais auto-pull |
| **Prospection** (plus tard, wama-dev-ai fiabilisé) | recherche de modèles notables (coder, embedding FR, traduction) → **rapport CITÉ** + entrées catalogue `recommended` (non téléchargées) | ✅ guardé (cite ses sources) | admin relit + `ollama pull` |

- Réutilise l'existant : `AIModel` (registre), Celery Beat (planif), flag `recommended` (§5b).
- **Hallucinations** : la prospection LLM ne s'auto-applique JAMAIS (cf. deepseek-coder qui hallucinait). Propose-cite-tu-valides.
- **Quick-win qualité indépendant** : tester un embedding **multilingue** (`bge-m3` / `qwen3-embedding`) pour le RAG FR (Lescot) — `nomic`/`mxbai` sont anglo-centrés. Garder les anciens en comparaison.
- Les comparatifs coder (qwen3.x, gemma4…) reçus = **invérifiables/datés → tester soi-même**, ne rien basculer à l'aveugle.

### 16.2 Outils tiers évalués (scope WAMA, 2026-06-18)

> Principe : WAMA est un PRODUIT (apps + assistant + catalogue + Anonymizer). Ne prendre que
> ce qui comble un VRAI trou ; rejeter ce qui duplique/fragmente le cœur de WAMA.

- ✅ **Adoptés/alignés** : LiteLLM (§8d, routeur LLM), pgvector (RAG dans Postgres existant), Headroom (dev).
- 🟡 **À évaluer (gaps réels)** : Presidio (PII **texte** avant cloud — complète l'Anonymizer média) ; Docling (parsing PDF layout pour ingestion RAG) ; Langfuse (observabilité LLM, quand l'orchestrateur grossit) ; Kilo Code / Claude Code Router (économie de quota dev : router le routinier vers Codex-UGE/Ollama ; Kilo = plugin JetBrains/PyCharm).
- ❌ **Rejetés (dupliquent/fragmentent ou sur-ingénierie)** : Bifrost (LiteLLM couvre) ; LocalAI/BentoML/Triton (les apps WAMA + microservice TTS + Celery SONT la couche de service) ; Open WebUI/LibreChat (WAMA a déjà son assistant tool_api — adoption = perte d'intégration) ; MLflow — ⚠ **PRÉCISÉ le 2026-08-25 (Fabien), voir `WAMA_APPRENTISSAGE.md §4`. Le rejet TIENT et n'est pas amendé** : c'est un rejet **d'intégration / de réutilisation dans WAMA** (`AIModel` reste le registre unique de ce que WAMA sait exécuter ; **MLflow Projects** duplique les manifestes `pipeline` + le chaînage studio). Ce qu'il ne disait pas, faute d'objet à l'époque, c'est la **complémentarité** : le monde Data introduit des modèles **appris**, donc des runs d'entraînement à tracer — hors WAMA. D'où un **connecteur unidirectionnel en un seul point** (run MLflow terminé → manifeste `model` avec `trained_from` + `mlflow_run_uri` → `ingest()`). Complémentarité ≠ adoption ; LM Studio (Ollama couvre) ; MemPalace (Headroom fait la mémoire agents) ; Label Studio (pas d'annotation) ; OpenClaw/ollama-mcp (niche).
- **3 vrais gains** : pgvector (RAG), Presidio (privacy texte), CCR/Kilo (quota dev).

#### Précisions vérifiées (2026-06-18)
- **Cadre conceptuel** : les 100+ modèles WAMA (Detector/Anonymizer/…) ne sont **PAS** des fournisseurs interchangeables pour une même tâche (logique LiteLLM) — c'est **ton pipeline métier**. Le besoin n'est donc pas « LiteLLM pour le non-LLM » (routage entre concurrents) mais soit (a) **exposition standardisée** de tes propres modèles, soit (b) **routage local/cloud par tâche** pour les modèles non-LLM. → à trancher (§16.3).
- **LocalAI** (candidat sérieux) : ajouts 2026 = **reconnaissance faciale + liveness/antispoofing** (avr. 2026) et **détection objets vocabulaire ouvert** (`locate-anything.cpp`, juin 2026) → touche **directement Anonymizer/Detector**, pas que Whisper/SD/Llava. Premier pas peu coûteux : LocalAI en Docker derrière **Transcriber seul** (Whisper mature) et comparer maintenance+qualité vs l'intégration actuelle. Les modèles propres au Lescot (trajectoires, oculométrie, comportements) resteront du **code maison** quel que soit l'outil.
- **Bifrost** : dépôt exact = **maximhq/bifrost** (Go, ~11 µs overhead @5000 req/s). Son « multimodal » = transmet payloads image/audio aux **endpoints LLM** des fournisseurs — **ne fait pas tourner** Whisper/SD lui-même. = alternative à LiteLLM (même problème), pas une réponse au besoin non-LLM.
- **BentoML ⊃ Triton** : BentoML sait utiliser Triton comme moteur (`bentoml.triton.Runner`) → l'adopter ne ferme pas la porte à Triton. Triton seulement quand contention GPU multi-utilisateurs **prouvée** (config.pbtxt/ONNX/TensorRT = complexité d'exploitation).
- **Open WebUI vs LibreChat** : Open WebUI a changé de licence en 2025 (branding imposé >50 users/30 j) → **friction** avec « WAMA open source/gratuite ». **LibreChat = MIT pur**. Donc : WAMA garde son assistant (tool_api) ; SI un jour une UI chat prête-à-l'emploi est voulue → **LibreChat**, pas Open WebUI.
- **AnythingLLM** (Mintplex Labs, MIT, Node.js/React, v1.11.2 — relevé le 2026-09-30 sur sa doc publique, **code non lu**) : ❌ **rejeté comme composant ET comme UI**, même motif que LibreChat — chat + RAG + agents qui doublent l'assistant commun, `wama/common/memory/` (pgvector) et reader/transcriber ; ses espaces de travail + rôles admin/manager/user seraient un **second modèle de portée** à côté d'`OrgUnit`/`Project` (`WAMA_MEMORY §2`) ; télémétrie PostHog **active par défaut**. ✅ **Compatible comme CLIENT de WAMA, sans rien écrire** : son client MCP ne charge que les *outils* (ni resources, ni prompts, ni sampling) — exactement ce qu'expose `common/services/mcp_server.py:209,217` (transport accepté non vérifié). Idée retenue : la présélection des outils par requête → `WAMA_HARNESS` écart 3. ⚠ Écartée après examen avec Fabien : son « espace de travail » (sac de documents) **n'ajoute rien** — la sélection par niveau (`recall(rag_niveaux=…)`) couvre le choix du périmètre, et lire UN document entier passe déjà par `get_item_detail` (`wama/tool_api.py:2732`) ; ce n'est pas du RAG.
- **CCR / Kilo — alerte facturation** : « BYOK / zero markup » = paiement **au token** (pas l'abo Pro fixe). Vérifier l'auth Anthropic (clé API facturée vs passthrough abonnement) **avant** de migrer. Sinon : Claude Code pour Claude, CCR/Kilo réservés à Codex-UGE / locaux gratuits. Kilo = plugin **JetBrains** ; OpenClaw (agent planifié Slack/…) + revue PR = les briques « à construire » existent en produit → tester sur une tâche de veille secondaire avant d'arbitrer maison vs produit.
- **ollama-mcp** : préférer le fork **hyzhak/ollama-mcp-server** (NightTrek peu actif). N'a de sens que pour laisser Claude déléguer une sous-tâche à un modèle local **en pleine session** ; sinon un seul chemin vers Ollama.
- **LM Studio** : redondant avec Ollama pour le service ; à garder comme **bac à sable** d'exploration manuelle, pas comme composant servi.
- **MemPalace** : promesses contestées publiquement (« +34 % recall » = filtrage métadonnées classique ; « 30x sans perte » = ~12 % de perte de récupération mesurée). = **confort** (mémoire inter-sessions), pas brique critique ; Headroom couvre déjà ce besoin.

#### llmfit — confrontation au banc de modèles (2026-09-14, demande de Fabien)
> `github.com/AlexsJones/llmfit`, Rust MIT, binaire seul (le paquet PyPI n'embarque que le
> binaire). Adéquation matériel↔LLM : fit mémoire par taux de remplissage (60/85/98 %),
> estimation tok/s par bande passante (`bandwidth / taille × 0,55`), banc réel Ollama (3 passes,
> `num_predict` 300, temps natifs `eval_duration`), **provenance de chaque chiffre**
> (`measured_local > measured_community > calibrated > estimated`), rubrique qualité par rôle
> (YAML de regex, score 0-10) et partage communautaire par PR GitHub.
- ❌ **Non intégré** — redondant ou incompatible : fit mémoire (le curseur continu de
  `model_selector` + le gouverneur font mieux qu'un verdict à 4 crans) ; qualité par famille
  curée (WAMA a un banc tiers MESURÉ, `benchmark_sync`) ; catalogue scrappé HF (`AIModel` +
  prospection) ; **composite qualité×vitesse `(q×2 + tps/3)/3`** — contraire à « jamais deux
  échelles mélangées » et à « le rang, pas le score » ; partage par PR (dépôt public, labo).
- ✅ **Trou 1 comblé le jour même** : WAMA ne mesurait AUCUN débit LLM — `ModelRuntimeStat`
  portait une unité `token` a priori (0,03 s/jeton) et zéro enregistrement, aucune app LLM
  n'appelant `record_run`. → protocole `text-generation` dans `bench.py` (`_bench_generation`,
  repris du geste llmfit : chauffe + N passes, temps natifs Ollama, saturation au plafond),
  qui **persiste des durées** dans la boucle d'ETA existante, jamais une qualité ; respecte
  `WAMA_GPU_SAFE_MODE` (jumeau du triage VLM et du describer). Commande :
  `manage.py bench --task text-generation --media prompt.txt --models <un seul>`.
  ⚠ **Aucune mesure réelle prise par Claude** : le protocole charge un LLM sur l'Ollama hôte,
  la rampe qui tue l'hôte (règle du 31/08). Première passe = Fabien, un modèle à la fois.
  Au passage : `_bench_description` (légendage) lisait un dict comme une chaîne → chaque
  modèle sortait « en erreur » depuis sa création ; corrigé, testé.
- ✅ **Trou 2 — FAIT le 14/09 au soir par l'instance gouverneur** (`PROJECT_STATUS §PALIER
  2026-09-14 « GOUVERNEUR : la VRAM MESURÉE rendue au catalogue »`, GO Fabien, champ MESURÉ
  SÉPARÉ) : `_wrap_load` consigne une mesure fraîche au gouverneur (`record_measured_vram`), une
  tâche beat (600 s) l'écrit dans `extra_info['vram_measured']` = {last_gb, max_gb, n, at} ;
  `vram_gb` INTACT (la synchro le réécrit), clé collante ; lecteurs = `check_model_completeness`
  (axe `vram_under_declared`, ex-`vram_sous_declaree` — les huit axes ont été traduits en bloc le
  2026-09-20) et l'inspecteur du model_manager. **Ce qui reste, et n'est pas
  un manque** : le tirage lit toujours `vram_gb` (brancher la mesure sur le budget = décision à
  part) ; pas de vocabulaire de PROVENANCE sur `vram_gb` lui-même (déclaré / heuristique / estimé)
  ni de base exposée pour `eta_estimator.estimate()` — l'enum `estimate_confidence` de llmfit
  reste la référence si ces deux points s'ouvrent. ⚠ Cette ligne disait « non fait » jusqu'au
  19/09 : écrite le 16 sans relire le §PALIER du 14 au soir.
#### YuE2 / ACE-Step 1.5 — musique à RÉFÉRENCE et à PLAN ÉDITABLE (2026-09-19, question de Fabien)
> *« Il me semblait qu'on avait ajouté un modèle dans Composer pour générer de la musique à partir
> d'une référence »*, puis `github.com/multimodal-art-projection/YuE`.
> **Aucune décision prise, rien d'installé, aucun modèle chargé.**
> ✅ **MàJ 2026-10-01 — YuE2 INTÉGRÉ par les rôles** (décision de Fabien : « déjà YuE alors »,
> par les mécanismes de WAMA) : code vendorisé (`library:yue`), poids `huggingface:m-a-p/YuE2-3B`
> + VAE au catalogue (moteur `yue`), backend `yue2_3b_backend` sous le contrat neuf
> `MusicGenerationBackend` (tâche `text-to-music`). Chaîne et trous comblés :
> `PROSPECTION_PIPELINE §Session du 2026-10-01`. ⏳ Restent : la génération GPU (reportée — campagne
> d'évaluation en cours sur la carte), l'emploi par le composer (sélecteur F4b), et le PLAN
> éditable (D-b ci-dessous) — l'artefact ABC existe côté moteur (`SymbolicPlan`), rien ne le montre.

**Ce que le catalogue a déjà** (mesuré ce jour) : `composer:musicgen-melody`, conditionné par une
mélodie de référence mais **non téléchargé** — la génération par référence ne marche donc nulle
part aujourd'hui ; `composer:minimax-music3` (chansons avec paroles, GGUF audio.cpp) ;
musicgen-small/medium ; audiogen-medium ; et **`huggingface:ACE-Step/Ace-Step1.5`**, installé le
**02/09** par le mécanisme (132 s, 9,4 Go, MIT), `backend_ref` vide, **aucun backend ne le sert**,
retaggé `text-to-music` le 19/09 (il était catalogué en ambiance). C'est lui, le modèle « à
référence » de la question : style guidé par un audio, reprise, repeindre une portion.

**Ce que YuE2 apporte et que RIEN dans WAMA ne fait** : un **artefact intermédiaire éditable et
SYMBOLIQUE** entre la consigne et le son. Trois modes : créer (paroles + style → plan mélodie et
accords en notation ABC → chanson), reprendre (enregistrement → partition → autre interprétation),
éditer en conversation (retour musical → révision du plan, du style ou des paroles → nouvel
enregistrement). Le plan se lit, se corrige et se resoumet. ACE-Step, lui, édite dans le domaine
AUDIO : ce n'est pas la même chose qu'un plan qu'un humain relit AVANT que le son existe.

⚠⚠ **Trois affirmations FAUSSES de ma première réponse, corrigées par Fabien le jour même** —
écrites ici parce que chacune est un piège de méthode :
1. « YuE2 n'a plus de mode référence » : **le mode reprise existe**. J'avais lu le mécanisme
   correctement et l'ai présenté comme une perte.
2. J'ai classé ACE-Step devant **sur un tableau de COÛTS** (VRAM, vitesse, licence) présenté comme
   un verdict de choix, **sans aucune mesure de qualité** — Fabien place YuE2 parmi les meilleurs,
   devant Suno et ACE-Step. *C'est exactement le défaut que `WAMA_QUALITE.md` décrit : un composite
   de coût lu comme une note.*
3. « Licence non commerciale = bloquant » : **hors sujet** pour l'usage visé — outil de
   communication INTERNE, tests, supports d'induction d'émotions. `docs/construction/exploitation/LICENSING.md`
   ne s'applique pas ici.

| | YuE v1 (branche) | YuE2 (actuel) | ACE-Step 1.5 |
|---|---|---|---|
| référence audio | apprentissage en contexte, 1 ou 2 pistes | reprise par partition | style, reprise, repeindre |
| **plan éditable** | non | **oui (ABC)** | non (édition audio) |
| poids | Apache-2.0 | CC BY-NC-4.0 | MIT |
| VRAM | 24 Go = 2 sections ; 80 Go = morceau entier | 24 Go | < 4 Go possible |
| vitesse | 360 s pour 30 s sur RTX 4090 | non publiée | < 10 s par morceau sur RTX 3090 |
| installation | clone git | clone git + `pip install .` | clone git + `uv sync` |

**🔚 DEUX DÉCISIONS, DIFFÉRÉES** (Fabien : *« ça demande une décision que je ne veux pas prendre
tout de suite »*) :

- **D-a — comment un moteur avec son PROPRE runtime entre dans WAMA.** PARTAGÉE : ni YuE ni
  ACE-Step n'a de paquet PyPI (`yue2-infer` et `acestep` : 404 tous les deux), et la route
  `library` refuse **avant pip** tout ce qui n'est pas « nom==version »
  (`model_installer._PIP_SPEC_RE`, verrous §16.7) — **frontière voulue, pas trou d'outillage.**
  Trois voies existent dans le dépôt : **vendoriser** (patron `wama/common/backends/vendor/` :
  musetalk, codeformer), **venv isolé** (doctrine des venvs, seule voie propre retenue pour
  chatterbox), ou **attendre un paquet**. Tranchée une fois, elle sert les deux modèles — et c'est
  elle qui débloque ACE-Step, installé et inerte depuis 17 jours.
  **Piste examinée le 2026-09-30 (question de Fabien : « s'inspirer de la route de génération
  d'app qui tire modèles et librairies des dépôts GitHub »)** — non tranchée. La brique existe à
  moitié : le rôle `librarian --repo` lit déjà un dépôt GitHub (`sources_repo` : README,
  pyproject/setup, requirements, LICENSE) et produit un manifeste `library`. Il manque le CANAL
  d'installation : un manifeste `library` dont `install` porterait `vendor: {repo, commit}` au
  lieu de `pip`, installé par CLONE au commit exact sous `BACKEND_VENDOR_DIR/<moteur>` (le patron
  des 3 moteurs vendorisés, dont le README tient déjà dépôt + commit). Ce n'est PAS lever le
  verrou `git+` : pip n'installe rien depuis Git, le code n'est jamais importé par WAMA (sous-
  processus), et les verrous se TRANSPOSENT — dépôt `owner/nom` seul, SHA complet obligatoire
  (le pin exact d'un dépôt), allowlist `Library.is_allowed` et kill switch inchangés. Les
  `requirements.txt` d'amont ne s'installent JAMAIS tels quels (`setup_avatarizer.sh`
  rétrogradait le venv) : chaque dépendance manquante passe par la route `library` existante
  (`nom==version`, contraintes `-c`, simulation). Correctifs locaux déclarés (`patches/`).
  Premiers clients : musetalk, codeformer, triposr (leurs scripts de setup deviendraient des
  manifestes), puis YuE/ACE-Step et les avatars (LongCat, InfiniteTalk, SoulX-FlashHead).
  ✅ **TRANCHÉE puis LIVRÉE le 2026-09-30** (Fabien : *« la norme c'est pip […] uniquement pour
  les librairies qui ne s'installent pas directement avec pip […] à uniformiser, universaliser au
  passage »* ; un PROJET D'APPLICATION ne s'installe pas, il se GÉNÈRE en app WAMA). Forme :
  `install.vendor = {repo, commit, engine, patch?, ignore?}`, exclusif de `install.pip`
  (`library.vendor_spec_error`, même verrou à la validation et à l'installation) ; champ
  `Library.vendor` projeté ; exécuteur `model_manager/services/vendor_installer.py`, appelé par
  `install_library` — plan sans effet, allowlist, kill switch commun, clone au SHA dans un dossier
  temporaire renommé au succès, correctif appliqué, état CONSTATÉ (`vendor_state` : fins de ligne
  ignorées, chemins `ignore` déclarés), journal `install_history`, et **refus d'écraser toute
  modification locale non déclarée**. Les trois moteurs sont au corpus
  (`manifests/libraries/{musetalk,codeformer,triposr}.json`, manifestes AUTORÉS relus par
  `manifest_export`) ; MuseTalk et CodeFormer mesurés CONFORMES à leur déclaration sur ce poste,
  TripoSR cloné + corrigé de bout en bout par la route dans un dossier jetable (réseau réel). Le
  correctif TripoSR est sorti du script en `patches/triposr_pymcubes_lazy_rembg.diff` ;
  `setup_avatarizer.sh` et `tools/setup_triposr.sh` appellent la route. Uniformisé au passage :
  `BaseModelBackend.VENDORED` — un clone absent entre dans `missing_packages()` pour tout moteur
  vendorisé (seul TripoSR le disait). Tests : `model_manager/tests/tests_vendor_install.py` (faux
  dépôt git local, contre-épreuves CRLF / `ignore` / backend non vendorisé).
  ✅ Le même soir, le rôle `librarian --repo` pose le canal par les FAITS du dépôt, pas par le
  LLM (`role_utils.enforce_install_channel`) : sans `pyproject.toml`/`setup.py`/`setup.cfg` à la
  racine, `install.vendor` au commit MESURÉ par l'API GitHub (`github_head_sha`) ; un paquet
  reste sur pip. Joué sur TripoSR (Albert) : commit `107cefdc244c` mesuré — celui du corpus —,
  manifeste valide du premier coup.
  ✅ Les cinq clients pressentis (YuE, ACE-Step 1.5, LongCat-Video, InfiniteTalk, SoulX-FlashHead)
  passés au rôle : manifestes vendor valides, commit mesuré, et VERDICT DE DÉPENDANCES contre le
  venv de référence (`role_utils.requirements_verdict`) — tableau dans `PROSPECTION_PIPELINE`
  §Session du 2026-09-30. YuE seul n'exige aucune décision de venv ; `accelerate` 1.6.0 en
  bloque trois.
  ⏳ Restent (décisions) : entrer ces manifestes au corpus (validation humaine), la montée
  d'`accelerate`, puis un backend par moteur — sans lequel un moteur installé reste inerte.
- **D-b — un artefact intermédiaire ÉDITABLE dans une app de génération.** Propre à YuE2, et
  INDÉPENDANTE de D-a. Aucune app ne l'a : partout c'est consigne → sortie, en un coup. La forme
  existe pourtant ailleurs (transcriber : un master puis une correction humaine qui fait autorité).
  Ce qu'elle touche : la card et son cycle, l'inspecteur, et la question « ce plan est-il une
  sortie, une entrée, ou les deux ». Domicile de la question le jour où elle se tranche :
  `WAMA_APP_GENERATION_ROUTE.md §10.6` (une card = une instance de pipeline) — **pas avant.**

- ❌ **« Idée 3 » RETIRÉE le 2026-09-16** (une rubrique regex par rôle pour les seuls LLM) :
  trop étroite et à côté de la route actée (`ROUTE §F4b` : qualification comparative de TOUTES
  les tâches, sorties confrontées, réingestion en indice) — et « à réécrire en français » était
  faux (l'anglais est le pivot des consignes, §10.B). La démarche complète vit désormais dans
  **`docs/construction/ia/WAMA_QUALITE.md`** (méthodes M1-M10, matrice tâche × méthode, chaîne
  en 12 chaînons, décisions Q1-Q9) ; la rubrique y survit comme UNE métrique objective (M3).

#### LiveEdit — retouche VIDÉO par instruction dans l'Imager (2026-10-05, question de Fabien — consigné le 06/10)
> *« Peut-on intégrer live editor dans l'Imager de wama via les mécanismes de wama en utilisant
> albert ou qwen3.8 depuis l'assistant ? »* (`github.com/cp-cp/LiveEdit`, `live-edit.github.io`).
> Puis : *« je préfère qu'on consigne bien tout ça et on s'en occupe plus tard »*.
> **Aucune décision prise, rien d'installé, aucun code écrit.** Lu : README, `requirements.txt` et
> `inference-mm.py` du dépôt, arXiv 2606.26740 (résumé + HTML v2). Le site du projet et la fiche
> HF n'ont pas répondu (ECONNRESET, proxy probable) — **non lus**.

**Ce qu'est LiveEdit (lu, pas mesuré chez nous)** : éditeur vidéo CAUSAL (morceau par morceau)
distillé en 3 étapes depuis **Wan2.1-T2V-1.3B** ; 4 pas DMD (`[0, 250, 500, 750]`), morceaux de
3 images latentes ; vidéo source concaténée par CANAL au latent bruité (préservation du fond) ;
« Mask Cache » qui saute les zones inchangées. **12,66 i/s annoncés, GPU non précisé.** ECCV 2026,
code et poids Apache-2.0 (`cp-cp/LiveEdit`, `ar-forcing_002000.pt`).
- **Bornes** : 480×832 à 16 i/s, 81 images (~5 s) par défaut (`num_output_frames*4-3`) ; script
  « long » à fenêtre glissante (3 puits + 9 récentes). Entraîné sur **20 000 paires filtrées de
  Ditto-1M** : attributs, textures, remplacements d'objet ; consignes **en anglais**, forme
  impérative (« Change the red currants to deep purple grapes… »).
- ⚠ **« Temps réel » = un DÉBIT, pas un service** : le dépôt n'a que de l'inférence hors ligne
  (`inference-mm.py` : un seul `pipeline.inference(...)` puis `write_video`), aucun serveur de flux
  documenté (flask-socketio figure aux dépendances, `demo_utils/` non lu).
- ⚠ **Licence de Ditto-1M NON vérifiée** — celle des poids peut en hériter (règle de la
  prospection, licence HÉRITÉE).
- **VRAM** : le pic sera l'encodeur umT5 de Wan (5,68 Md, ~11,4 Go bf16 — déjà mesuré pour FastWan,
  `PROJECT_STATUS` §FastWan « Le modèle est-il le bon choix ? »), pas le DiT 1,3B. La consigne est
  fixe sur toute la vidéo : encoder une fois, puis décharger.

**Avis donné (à reprendre, pas tranché)** : pour une card de file qui attend son résultat, un
éditeur NON causal (ex. Wan2.1-VACE) ferait probablement mieux à qualité égale ; l'atout PROPRE de
LiveEdit est de produire **au fil de l'eau** — ce dont la face « pendant » et une future page
d'édition ont besoin. D'où : lancer `scout` sur « édition vidéo guidée par texte » et confronter
les candidats sur nos propres clips (`WAMA_QUALITE`) avant de choisir.

**Route d'intégration repérée — dans l'ordre, chaque point cité au code le 2026-10-05 :**
1. **Contrat de tâche AVANT le backend** (leçon YuE2) : `TASK_CONTRACTS`
   (`wama/common/services/backend_inventory.py:655-671`) n'a pas de `video-to-video`, et
   `GenerationParams` (`wama/common/backends/image_generation_base.py:55`) n'a aucun port vidéo
   d'entrée — seulement `reference_image` (l. 73). → **D-c** ci-dessous.
2. **Installation par les rôles, voie VENDOR** : `requirements.txt` épingle `torch==2.7.1` (nous :
   2.9.1), `diffusers==0.31.0`, `numpy==1.24.4`, `pydantic==2.10.6`, tire
   `git+https://github.com/openai/CLIP.git`, `pycuda`, `flash-attn` → route `library` refusée
   (verrou voulu, §16.7) ; `librarian --repo cp-cp/LiveEdit` → `install.vendor` au SHA. LiveEdit
   porte sa propre copie de Wan (`wan/`) : l'épingle diffusers ne le concerne probablement pas —
   **à établir par import réel + `pip install --dry-run`**, jamais en appliquant les épingles
   d'amont (leçon `setup_avatarizer.sh`, 07/09). Chemin de poids en dur
   (`wan_models/Wan2.1-T2V-1.3B/`) → correctif vendor vers `MODEL_PATHS` + `cache_dir=`. Puis rôle
   `model` (Wan2.1-1.3B + `cp-cp/LiveEdit`), rôle `backend`, **essai GPU réel avant « Valider »**
   (leçon des trois ASR, 01-02/10).
3. **Imager** : un 8ᵉ mode `vid2vid` (`GENERATION_MODE_CHOICES`, `wama/imager/models.py:123-131` —
   7 modes aujourd'hui, aucun vidéo→vidéo) ; port de travail = la vidéo, prompt = la consigne ;
   capacités DÉCLARÉES (480×832, 16 i/s, durée max) pour `INPUT_MODEL_MATCHING` ; `select_model`
   avec l'intention rapide/qualité.
4. **La consigne passe par la chaîne de prompts commune**, pas par l'app : `PROMPT_TARGETS['imager']`
   aiguille déjà par domaine (`wama/common/utils/app_metadata.py:46-48`, `domain_field:
   'output_type'` → skills `imager-image`/`imager-video`) → un skill **`imager-video-edit`**
   (traduire en anglais, forme impérative, nommer l'objet visé).
   **Le LLM** : **qwen3.8 local par défaut** — vision + outils déclarés
   (`model_manager/tests/tests_taxonomie_ollama.py:26`), il peut regarder une image de la vidéo
   par `look_at_image` (`wama/tool_api.py:1700`) pour ancrer la consigne ; **Albert en second
   axe**, réécriture TEXTE seule (montrer une image de la vidéo d'un utilisateur à un service
   distant relève du « verrou sensibilité », encore ouvert). Désigné par clé de catalogue, jamais
   en dur.
5. **L'assistant déclenche** : étendre `create_image` / `add_to_imager` (`wama/tool_api.py:319`,
   `:2057`) au mode `vid2vid` avec une vidéo d'entrée.
6. **Face « pendant »** : l'Imager n'émet rien aujourd'hui (`ROUTE §F3b`, « Aucune émission :
   imager, avatarizer ») ; un éditeur causal publie naturellement chaque morceau décodé
   (`publish_partial`), déjà lu par l'inspecteur (`_startDuring`).
7. **Page d'édition vidéo de l'Imager** : **PAS avant le chantier SURFACES** (`ROUTE §F3b`,
   élargissement du 2026-10-01) — candidate **second consommateur pilote** à côté de YuE2. Vues
   qu'elle ajouterait : image courante abonnée à l'axe (pas image fps-aware, déjà au cam_analyzer),
   avant/après, plus tard un masque de zone. Intention, rien d'établi : la causalité permettrait un
   geste « ré-éditer depuis *t* » qui ne périme que la fin de la sortie.

**🔚 TROIS DÉCISIONS, DIFFÉRÉES** (Fabien, 06/10 : *« on s'en occupe plus tard »*) :
- **D-c — contrat `video-to-video`** : étendre `ImageGenerationBackend` d'un port vidéo d'entrée,
  ou base dédiée.
- **D-d — choix du moteur** : LiveEdit directement (pour son flux), ou confrontation préalable à un
  éditeur non causal sur nos clips.
- **D-e — archétype de surface** pour la page vidéo : relève de `ROUTE §13`, à trancher en
  ouverture du chantier SURFACES.

### 16.3 Questions ouvertes — à trancher prochainement
1. **Routeur local/cloud pour modèles NON-LLM** (le vrai besoin reformulé par Fabien) : LiteLLM reste le routeur du cerveau LLM ; pour les modèles non-LLM, choisir entre (a) exposition standardisée OpenAI-compatible via **LocalAI** (couvre Whisper/SD/Flux/Llava + désormais visages/détection), (b) garder les apps WAMA comme couche de service et n'ajouter qu'un routeur local/cloud par-dessus. → décider après le test LocalAI/Transcriber.
2. **Privacy texte avant cloud** : **Presidio** (MS, NER + règles, masquage configurable) vs **openai/privacy-filter** (HF) — à comparer (couverture FR, perf, licence, intégration) comme pièce texte de la règle « anonymiser avant cloud », en complément de l'Anonymizer média.

### 16.4 Anonymisation multimodale — décision 2026-06-18 (recherche web)

> Objectif Fabien : généraliser l'Anonymizer (média) à **toutes les modalités** (documents + audio en plus des images/vidéos). Résout Q1 de §16.3.

- **`openai/privacy-filter`** CONFIRMÉ réel (22 avr. 2026, Apache 2.0, MoE 1.5B/50M actifs, classif. tokens, ~8 catégories, F1 96 % PII-Masking-300k) MAIS **anglo-centré** + ⚠️ **typosquat `Open-OSS/privacy-filter`** (vérifier l'org). Pattern industrie = « Presidio + Privacy Filter ensemble ».
- **DÉCISION : Presidio = colonne vertébrale** (framework multimodal MIT, cœur Analyzer/Anonymizer unique) ; les détecteurs neuronaux sont des *recognizers* branchés dedans.
  - **FR (Lescot)** : **GLiNER** multilingue (`GLiNER2-PII` / `knowledgator/gliner-pii-edge`, 40-60+ types) ou NER FR spaCy/transformers comme recognizer Presidio. `privacy-filter` = booster de rappel **anglais seulement**.
  - **Garanties** : regex+checksum (structuré = déterministe) + NER/modèle (rappel noms). Presidio prévient lui-même « no guarantee all PII found » → revue humaine pour high-stakes, **jamais un seul modèle pour une porte dure**.
- **Anonymizer = dispatcher par modalité** (pattern onglets type enhancer image/audio). WAMA déjà bien placé car il POSSÈDE les couches d'extraction dont Presidio a besoin (Transcriber, Reader/OCR) :
  - Image/vidéo visages/plaques : YOLO/SAM3 existant (inchangé).
  - Image/vidéo texte PII incrusté : `presidio-image-redactor` (OCR Tesseract) — NOUVEAU.
  - Document (PDF/scan/Office) : scanné→image-redactor ; natif→extraction (Reader/Docling)→Presidio texte — NOUVEAU.
  - **Audio — DEUX axes distincts (ne pas confondre)** : (a) **PII de contenu** (noms/numéros prononcés) = Transcriber existant → Presidio texte → bip/mute par timestamps (grosse synergie) ; (b) **identité vocale** (voix = biométrie) = anonymisation de locuteur **VoicePAT / VoicePrivacy** (DigitalPhonetics), conversion de voix — NOUVEL axe.
  - Texte (chat, docs RAG) : Presidio + GLiNER FR — mask/replace/cipher réversible.
- **CONVERGENCE Q1↔Q2** : le **mode « texte » de l'Anonymizer** ET la **porte privacy avant-cloud** (§16.3 / §16.2 routage cloud) = **LE MÊME composant** → construire une fois (Presidio + GLiNER FR), utiliser aux deux endroits.

### Transcriber — exports + archétype d'export (2026-06-19)
- **Bugs export corrigés** : DOCX (`HttpResponse` non importé dans `views.py`), PDF (curseur `multi_cell` qui dérive → `new_x="LMARGIN"` ; texte FR), diarisation rendue conditionnellement (labels si `speaker_id`, sinon timecode seul).
- **PDF = police Unicode DejaVuSans** bundlée (`wama/common/assets/fonts/`) enregistrée dans `_make_pdf` → français préservé (fini le `_sanitize_for_latin1` lossy, désormais passthrough quand DejaVu actif). Fallback Helvetica+sanitize si police absente.
- **« Télécharger tout » multi-format** : `download_all?format=` (txt/srt/pdf/docx) via le helper partagé `build_transcript_bytes` ; bouton transformé en dropdown.
- **Archétype d'export formalisé** : late-binding (master-based : Transcriber) vs early-binding (render-based : Imager/vidéo/Enhancer). Drapeau `export_binding`. Doc complète : `WAMA_APP_CONVENTIONS.md §6.4` (+ §2bis.3). Anonymizer = cas hybride migrable (lié §15/§16).
- Reste (data, serveur) : item 142 sans locuteurs = diarisation m4a échouée en amont (cf. décodage m4a), à re-tester côté serveur.

### 16.5 Runtime AI + couche QC + Gemma 4 (évalué 2026-06-20, avec accès repo)

**Principe directeur : NE PAS reconstruire le « runtime » — WAMA l'a déjà à ~70 %.** Une étude externe proposait de bâtir orchestrateur/scheduler/MCP/router/mémoire from scratch en 5 phases. Mapping réel de l'existant :
- Model Router → `model_selector.select_model()` (VRAM-aware, keep_loaded, capacités).
- `ModelCapability` → `AIModel.capabilities` (peuplé).
- MCP layer → `tool_api.py` (TOOL_REGISTRY, 36 outils).
- Scheduler → Celery Beat. Dev Cluster → `wama-dev-ai`. Exec cloud/local → LiteLLM (`llm_gateway_check`).
- Research agent (cœur) → détecteur `check_model_updates`. Memory → ChromaDB + MEMORY.md.
→ La vision 3-couches (Platform / Runtime AI / Dev Cluster) est un **cap**, pas un plan de construction. **Mapper, pas recréer.** Avancer en briques incrémentales sur l'existant.

**Couche QC / validation transversale (stratégique) — 3 garde-fous non négociables :**
1. **Validateur INDÉPENDANT du générateur** (sinon validation circulaire : un modèle corrige sa propre copie). Autre famille de modèle, ou contrôles déterministes.
2. **Score RELATIF** (régression N vs N+1, flag outliers → revue humaine), **PAS** un gate `accepted` automatique.
3. **JAMAIS le seul filet RGPD** (Anonymizer) : déterministe + échantillonnage d'audit humain = filet PRINCIPAL ; le LLM = alerte secondaire qui escalade vers l'humain. Faux négatif VLM = fuite de données personnelles (sujets humains Lescot).
→ Bonus USP : score qualité **versionné par run** = audit niveau recherche. Sert aussi à **évaluer les MAJ de modèles** (lien détecteur #3). Réutilise `capabilities`.

**Gemma 4 (vérifié sur ollama.com/library/gemma4) :**
- `e2b`/`e4b` : 128K, **texte+image+AUDIO** (e4b déjà installé). `12b`/`26b`/`31b` : 256K, **texte+image SANS audio**.
- Corrections vs étude externe : (1) le **12b n'a PAS l'audio** → pour l'audio = `gemma4:e4b` ; (2) licence = **Gemma Terms of Use**, PAS Apache 2.0 (restrictions d'usage, non-OSI) → vigilance « open/gratuit » + redistribution.
- `gemma4:12b` (7,6 Go, 256K, texte+image) = bon candidat **résident Describer/assistant**, tient large sur 4090. **À benchmarker sur inputs FR avant tout swap** (ne rien figer sur la hype).

**Autres :**
- **Concurrence « locale » = séquentielle** sur 1 GPU 24 Go (ne tient pas 3 modèles capables en VRAM). Vraie concurrence seulement sur le futur serveur 96 Go.
- **Reproductibilité** : enregistrer hash/version du modèle **par run** (renforce la traçabilité scientifique).
- Séquencement : prospection au-dessus du détecteur (#3) → QC v0 sur 1 app → bench Gemma. Tout incrémental.

### 16.6 Pipeline de prompt commune (métadonnée-driven) + hiérarchie des visions méta (décidé 2026-06-22)

**Constat (remarque Fabien)** : les traductions par app (imager prompt, SAM3 concept) sont de la GLU par app — v0 OK pour valider la chaîne, mais PAS la cible. **CIBLE = une `PromptPipeline` COMMUNE déclenchée par les métadonnées de l'app.**

**Principe** : chaque app DÉCLARE dans sa description ses « prompt targets » + leur **KIND** :
- imager → prompt `generative` (SDXL/Flux/…) ; anonymizer → `sam3_prompt` `concept` (SAM3, concepts EN) ; assistant → `intent`.
- Dès qu'un prompt arrive : TRIGGER → `PromptPipeline.process(prompt, kind, app_meta, target_model)` → *détection langue → traduction si besoin (lang_routing+translator) → enrichissement selon le KIND → RAG user/labo → compréhension fichiers de référence*. **AUCUNE fonction par app.** Le **KIND est essentiel** (enrichir un prompt génératif ≠ extraire un concept EN ≠ comprendre une intention).
- **Prochain consolidant** : refactorer la glu imager/SAM3 dans cette pipeline. Lié au layer métadonnée §2bis (capacités + types I/O + **KIND prompt**) et à `model_selector` (task→modèle).

**Hiérarchie des visions « méta »** (4 faces d'UN moteur : capacités + model_selector + PromptPipeline + contrats I/O) :
1. **Méta-app graphique à cards (§15)** — LA PLUS concrète (compose l'existant, zéro magie). Priorité interface.
2. **Assistant orchestrateur** (tool_api) — façade NL, existe déjà.
3. **Génération d'app = SCAFFOLD humain-in-loop** (méta-description + plan + boilerplate aux conventions), PAS usine autonome.
4. **Méta-app spec-driven unique** = PoC recherche, plus tard.

**Règles** :
- **« Capacité-first »** : si la capacité existe (modèle + pipeline + contrat I/O), l'assistant l'orchestre SANS app dédiée ; scaffolder une app seulement quand le besoin est **récurrent**.
- **« Généraliste > spécifique »** fait converger vers PEU d'apps généralistes + composition (évite la prolifération d'apps). WAMA Lab = spécifique métier uniquement.
- **Outils d'éval** (Promptfoo/DeepEval/Langfuse/lm-eval = réels ; Modelator/Evvl/Benchscope/etc. = invérifiables) : **sur-dimensionnés**. WAMA a déjà l'équivalent (registry=`AIModel.capabilities`, judge=QC, adaptateurs=LiteLLM/backends). NE PAS bâtir de plateforme d'éval ; Promptfoo/DeepEval éventuellement pour la régression plus tard.

**Séquencement** : fondation (métadonnée + `PromptPipeline` commune) AVANT les interfaces méta.

### 16.7 Hermes Agent (Nous Research) — évaluation + décision (2026-07-29)

> **DÉPLACÉ le 2026-09-19** vers **`docs/construction/ia/WAMA_HARNESS.md §7.1`** — le corps de
> cette évaluation (existence vérifiée, verdict runtime/mémoire procédurale, réserves LiteLLM,
> découverte de plugins, confrontation Hermes ↔ WAMA) y a été transporté **mot pour mot**, sans
> une reformulation. Motif : une évaluation de harnais n'est pas un jalon de roadmap, et la
> matière était éclatée sur quatre domiciles dont un hors du dépôt (`WAMA_HARNESS §1`).
> Le titre reste ici pour que les citations « §16.7 » aboutissent.
>
> ⚠ **Reste à re-domicilier** : ~60 lignes du bloc déplacé ne parlent pas d'Hermes mais de
> l'état des registres et de la couche capacités des librairies de WAMA — elles appartiennent
> à cette roadmap. Elles ont voyagé telles quelles plutôt que d'être découpées à la main : un
> déplacement qui trie n'est plus un déplacement. Décision D6 du nouveau document.

### 16.8 Twenty (CRM open source) — confrontation (2026-07-30)

Point de comparaison **plus pertinent qu'Hermes** : Twenty est métadonnée-driven de bout en bout et a
résolu en production ce qui nous bloque. **Il valide notre formalisme plutôt qu'il ne le conteste.**

**Convergence indépendante** : l'unité centrale de Twenty est un **manifeste** (`src/manifest.ts`,
typé `TwentyAppManifest` : `name`, `label`, `version`, `objects`, `functions`, `permissions`,
`settings`), avec des définitions **par unité** (`defineObject`, `defineField`, `defineLogicFunction`)
et des registres derrière. Un manifeste = une unité. Deux projets sans lien ont convergé vers la même
forme — c'est un argument fort pour ne PAS dévier du formalisme WAMA.

**NE PAS remplacer notre génération d'apps** : (a) l'unité d'extension de Twenty est un **objet de
données** (deal, person) + champs — la nôtre est une **capacité de traitement média** (empreinte GPU,
ports, file, ETA) : le modèle objet ne transfère pas ; (b) substrat TS/NestJS vs Python/Django/Celery
— la valeur de Twenty est dans son runtime, non transportable ; (c) `GENERIC_APPS` est à **10/10**,
remplacer jetterait un acquis mesuré. À écarter aussi : le DSL TypeScript et les conteneurs par app.

**À EXTRAIRE — 3 éléments, par valeur décroissante :**

**1. Le pipeline d'apply UNIFIÉ — la leçon de fond.** Twenty a *« a unified manifest apply pipeline
shared between application install and dev sync »* : **un seul chemin d'application, deux points
d'entrée** (installation d'app / synchro de développement). ⇒ **Diagnostic de notre blocage** : notre
projection est conçue comme une opération **rare et dangereuse**, donc jamais exercée, donc jamais
fiable, donc laissée en dry-run (1 kind/6, cf. §16.7 et `WAMA_MANIFEST_ARCHITECTURE.md` §7). Twenty la
rend **fréquente** : le dev-sync la déclenche en continu et toute non-idempotence saute aux yeux
immédiatement. **Inversion à adopter** : ne pas construire « la projection » comme un chantier à part,
mais **UN apply** branché d'abord sur le cas le moins risqué. Le live-sync n'est alors pas une
fonctionnalité de plus — c'est le **banc d'essai qui rend la projection sûre**.

**2. Permissions déclarées et granulaires — PRÉREQUIS, pas confort.** Twenty déclare dans le manifeste
ce que l'app demande : `permissions: [{ object: 'person', actions: ['read','write','delete'] }]`,
au-dessus d'un système multi-couches **objet / champ / ligne**. ⚠ Ne PAS dire que WAMA n'a rien :
`ScopedVisibility` (`common/models.py:184`) offre déjà 4 niveaux — `private` / `project` / `unit` /
`public` — avec hiérarchie `OrgUnit` (labo→équipes) et un scope **projet qui traverse les orgs**
(partenaires externes), filtré par `scoped_visible_q()`. C'est un modèle **ligne**, solide sur l'axe
**organisationnel**. Ce qui manque est ailleurs : **l'axe ACTION** (read / write / delete) et **l'axe
CHAMP**. Or c'est exactement l'axe action qu'un manifeste généré par LLM doit déclarer — « qui peut
voir » ne borne pas « ce que la capacité peut faire ». ⚠ **C'est un prérequis de la vision « l'assistant explore, un LLM
local écrit le manifeste, le reste est automatique »** : un manifeste écrit par un LLM **sans surface
de permission déclarée est une capacité non bornée**. Faisabilité favorable : la seule facette que
WAMA projette déjà est justement `access` → `AppAccessPolicy` ⇒ passer du binaire à des permissions
granulaires **réutilise le seul chemin d'apply qui fonctionne**. Extraction la moins risquée du lot.

**3. `settings` typés avec type `secret`** (`required`, `defaultValue`) — **même réponse que le
`requires_env` d'Hermes, atteinte indépendamment** : deux systèmes sans lien déclarent les secrets
**dans le manifeste**. Vu l'externalisation des secrets en `.env`, déclarer par manifeste ce qu'une
capacité exige ferme la boucle, à faible coût.

⚠ Non vérifié : mécanisme d'isolation exact de Twenty (les notes évoquent un *local function runner*
à IPC, donc plutôt processus séparé que V8 isolate). De toute façon besoin différent — Twenty est un
SaaS multi-tenant ; chez nous l'isolation est déjà au bon endroit (`UserFunction` + sandbox
`Manifest` + `ScopedVisibility`, F7).

**Décision** :
1. **PAS d'adoption comme couche d'orchestration de prod.** Un agent qui écrit et exécute son propre
   code, sur serveur UGE, sur données de recherche ⇒ revue RSSI, pas décision d'intégration.
2. **Pilote borné sur `wama-dev-ai` uniquement** — hôte de dev, read-only, aucune donnée sensible,
   doctrine « propose / l'humain valide » déjà écrite. Seul moyen de juger le framework empiriquement.
   **En mode CLI/TUI d'abord** (le bug gateway ci-dessus n'affecte apparemment pas ce chemin) ;
   n'ouvrir le mode gateway/messagerie qu'après reproduction et vérification sur `main`.
3. **Préalable indépendant d'Hermes** : brique `RunOutcome`/`ResultFeedback` dans `common/` — capture
   du signal (accepté / corrigé / rejeté / relancé). **Toutes** les boucles d'auto-amélioration
   visées (résultat, enrichissement de prompt, prospection de modèles) sont bloquées sur son absence,
   et aucun framework ne récupérera ce signal rétroactivement.
   ⚠ **Capture IMPLICITE obligatoire, jamais un formulaire de notation.** Leçon transposée d'un SI de
   labo réel : les chaînes qui vivent sont celles où le contributeur obtient quelque chose *au moment
   où il saisit* ; celles qui reposent sur la bonne volonté (« notez ce résultat pour améliorer le
   système ») meurent, même bien conçues. ⇒ `RunOutcome` se nourrit de ce que l'utilisateur fait
   **déjà** — téléchargé / relancé / supprimé / corrigé — et **jamais** d'un geste ajouté pour le
   bénéfice du système.
4. Garde-fous §16.5 applicables tels quels ; métrique d'abord, boucle ensuite, autonomie en dernier
   (un agent qui réécrit ses prompts sans métrique mesurée **dérive** au lieu de s'améliorer).

**Labels humains déjà jetés** (gisement, à capter par le point 3) : corrections manuelles Transcriber
(paires ASR→vérité), entités démasquées/ajoutées Anonymizer (FP/FN Presidio+GLiNER), générations
imager gardées vs supprimées (préférence), prompts enrichis acceptés vs réécrits.

---

### 16.9 Auto-maintenance de la BASE DE CONNAISSANCE — 2 outils (cadré 2026-08-02)

> **Cadrage Fabien** : l'auto-amélioration continue passe par **deux outils distincts** —
> ① un **générateur de documentation** complète de WAMA (qui nécessite un formalisme), et
> ② un **vérificateur de consistance** de l'arborescence et du code, par entité, capable de
> détecter erreurs et **redondances**.

**Le formalisme est déjà là : c'est le MANIFESTE.** Ne pas en définir un troisième. Les 6 kinds
(`app`, `model`, `dataset`, `function`, `pipeline`, `project` — plus `library` à créer) décrivent
déjà formellement chaque entité. Les deux outils sont donc des **CONSOMMATEURS** de la chaîne
existante `manifeste → ingest → registres → mécanismes`, pas de nouvelles sources. C'est ce qui
les empêche de devenir eux-mêmes des mécanismes concurrents.

#### ① Générateur de documentation — ✅ LIVRÉ le 2026-08-03 (`manage.py doc_facts`)

Frontière **impérative** (sans elle, l'outil détruit la valeur des docs) :

| Généré (jamais saisi à la main) | Écrit à la main (jamais généré) |
|---|---|
| chiffres et tableaux d'adoption : « 43 outils », « 75/75 params », « 91 références », « 1/11 facettes projetables » | l'intention, les décisions et leur **pourquoi** |
| inventaires : facettes par app, briques et leurs consommateurs, cibles de code-gen | les pièges, les leçons, les non-choix assumés |
| statuts ✅/🔄/⏳ dérivés d'une mesure | la route, les priorités, les arbitrages |

Mécanisme : **blocs délimités** dans les `.md` existants (surtout pas de nouveaux fichiers,
cf. règle « un domaine = un fichier »), régénérés par commande, avec `--check` refusant un bloc
périmé — même contrat que `manifest_export --check`.
**Motivation directe** : les chiffres recopiés à la main périment ET sont inventables. Constaté
le 2026-08-02 — « 42 » puis « 31/42 » annoncés par déduction ; le vrai chiffre était **91/91**.

**Livré (2026-08-03)** : `wama/common/management/commands/doc_facts.py` — 3 faits v1, chacun
dans SON doc de référence : `outils` → `WAMA_APP_GENERATION_ROUTE.md` (registre, décrits, args
documentés) ; `modeles` → `WAMA_MANIFEST_SPEC.md` (corpus, références résolues contre
`AIModel.model_key`) ; `roundtrip` → `WAMA_MANIFEST_ARCHITECTURE.md` (tableau des 10 apps via
`manifest_roundtrip._roundtrip`, consommé, pas recalculé). Marqueurs
`<!-- WAMA:FAITS(id) -->…<!-- /WAMA:FAITS(id) -->`, `--check` = sortie 1 si périmé, `--only <id>`.
Preuve immédiate de l'utilité : la première génération a mesuré **165 arguments documentés** là
où la prose du 02/08 en recopiait 157 (les 4 params converter avaient déjà déplacé le réel).
Ajouter un fait = une fonction + une entrée dans `FAITS` + poser les marqueurs dans le doc.

#### ② Vérificateur de consistance — ✅ LIVRÉ le 2026-08-03 (`manage.py check_redundancy`)

`check_app_conformity` (74 critères, F1–F8) couvre l'**ADOPTION** : cette app utilise-t-elle la
brique commune ? Il ne couvre PAS la **REDONDANCE** : une copie locale subsiste-t-elle À CÔTÉ de
la brique ? C'est précisément la classe d'erreurs de la session du 2026-08-02, toutes de la même
forme — *une implémentation locale vivant à côté d'un domicile unique déclaré* :

| Copie locale | Doublait | Conséquence réelle |
|---|---|---|
| `TOOL_DESCRIPTIONS` | `PARAMS_JSON` | 21 params décrits sur 71 ; composer non démarrable par l'assistant |
| `generic_runner._coerce` | `coerce_params` | le studio échappait aux **bornes** du schéma |
| `generic_runner._params_json` | `schema_for_app` | résolution recopiée |
| 14 clés d'options dans `converter/views.py` | schéma converter | `channels=1` → `ffmpeg -ac True` |
| clamp `1–30 s` dans `batch_parsers` | bornes du schéma (`10–600`) | import batch à 120 s ramené à 30 |
| liste de 4 styles dans `add_to_describer` | `choices` du schéma (5) | `meeting` proposé par l'UI, refusé par l'outil |

**Corpus d'acceptation** : ces 6 cas sont le jeu de test du détecteur. Il doit tous les retrouver
sur le code d'avant leurs correctifs. **Ne pas écrire le détecteur sans cette validation** — un
contrôle qui rate sa propre classe d'erreurs installe une fausse confiance, ce qui est pire.

**Livré (2026-08-03)** : `wama/common/management/commands/check_redundancy.py` — 3 classes :
A vocabulaire recopié (collections littérales ∩ noms de params / choices / TOOL_REGISTRY),
B bornes divergentes (clamp `max(a, min(b, x))` vs min/max du schéma), C brique doublée
(def privé en relation de préfixe avec une brique publique de `common/utils|services`, hors
modules qui la référencent déjà = adoptants ; + rechargement local du schéma via
`import_module`). Consommateur des registres LIVE (`APP_CATALOG`, `schema_for_app`,
`TOOL_REGISTRY`) — aucun vocabulaire recopié dans l'outil. **Acceptation : 6/6 retrouvés**
sur l'arbre pré-correctif reconstruit par `git show <commit>^:<fichier>` (+ 10 bonus réels,
dont les blocs par-app de `TOOL_DESCRIPTIONS` et `_ENHANCER_VALID_MODELS`).
Photo de l'arbre courant au 2026-08-03 : 73 trouvailles brutes (58 A / 0 B / 15 C), puis
**TRIAGE COMPLET le jour même → 5 restantes**, toutes = dette du port anonymizer (forms/views
pré-schéma), laissées VISIBLES exprès. Le triage a produit :
- **1 vrai bug trouvé et corrigé** : `document_export.py` lisait `description.output_format`
  (champ renommé `output_style` par la migration 0008) → `AttributeError` sur tout export
  PDF/DOCX de description — 4ᵉ consommateur raté par le correctif du 02/08 (validé : PDF réel) ;
- **résorptions** : `_ENHANCER_VALID_MODELS` → brique `schema_choice_values()` (aussi adoptée
  par la validation describer) ; `_probe_duration` du video_backend → `probe_duration_seconds`
  (passe par ffmpeg_utils, validé par un gif réel) ; 3 classifications d'extensions divergentes
  du describer → domicile unique `content_analyzer.DESCRIBER_*_EXTS` ; quadruplet voix recopié
  ×5 → `app_registry.VOICE_SAMPLE_EXTENSIONS` (+ migration avatarizer 0008) ;
- **précision du détecteur** : C(i) restreint au niveau module + couverture de tokens ≥ ½ +
  garde adoptant (brique OU son module référencés) ; kwargs Django mécaniques ignorés
  (`update_fields`, `list_display`…) ; domiciles reclassés sources (`app_registry`,
  `app_modes`, `model_registry`, `quality_presets`, `admin.py`) ; **pragma
  `# wama:redondance-ok — <raison>`** pour assumer explicitement un câblage déclaratif
  (mappings langue→voix, contrats de réglages utilisateur…) — jamais sans raison.
Lancer depuis Windows (`./venv_win/Scripts/python.exe`), comme `check_docs`.
**03/08, palier 1 du port anonymizer : les 5 dernières sont résorbées → « Aucune recopie
détectée », seuil nocturne `REDONDANCES_ASSUMEES = 0`** (toute trouvaille = nouvelle recopie).
**13/08 : 8 trouvailles apparues depuis (le vocabulaire de référence `imager.output_format`
s'est élargi, le détecteur n'a pas changé) → triage complet le jour même, retour à 0** :
1 résorption réelle (`_params` de la couche manifeste → domicile
`param_schema.declared_param_schemas()`, la déclaration COMPLÈTE tous-`*PARAMS_JSON` ;
validée par roundtrip 10 apps + corpus WSL2 à jour) ; anonymizer branché sur
`normalize_types` (app_registry) pour sa classification vidéo (2 sites — au passage la
recopie ratait flv/mpg/wmv…) ; `codeformer` exclu du scan (vendored, comme musetalk) ;
3 pragmas raisonnés (presets ffmpeg = info NOUVELLE par format ; capacités de sortie
converter et politique d'acceptation médiathèque = mêmes raisons que les lignes voisines
déjà triées).

**Déjà en place à réutiliser** : `check_app_conformity` (adoption), `check_docs` (intégrité
doc→code, 217 références), `manifest_roundtrip` (fidélité + round-trip ports), `manifest_export
--check` (corpus), `projection.studio_redundancy` (redondance APP_CATALOG⟷GENERIC_APPS).

### 16.10 Contrôles de SÉCURITÉ dans la nocturne — évaluation Aikido (2026-08-13)

**Contexte.** Fabien a soumis Aikido Security (plateforme SaaS belge : SCA/CVE, licences, secrets,
SAST, firewall runtime « Zen », gratuite pour l'open source — le repo est public donc éligible).
**Décision : équivalents LOCAUX d'abord**, dans le mécanisme de contrôle existant (scénarios
`consistency` de la nocturne), parce que (a) l'audit licences est déjà couvert EN MIEUX par
`license_audit` (Aikido ne voit pas les licences de poids de modèles), (b) les secrets sont déjà
purgés (historique réécrit 2026-07-23) — le besoin est la garde anti-récidive, pas le scan,
(c) un dashboard SaaS non relié à la nocturne serait un tableau de plus qui cesse d'être lu,
(d) « suggérer l'upgrade » est inapplicable sur la pile ML épinglée+patchée (`patches/`).

**✅ LIVRÉ (2026-08-13)** — deux commandes + leurs scénarios nocturnes, style cliquet :
- `manage.py check_dep_vulns` (`common.consistency.dep_vulns`) : CVE des paquets INSTALLÉS du
  venv courant via l'API OSV.dev (même base que pip-audit/Dependabot/Aikido), zéro dépendance
  nouvelle. Contrat = baseline versionnée `tools/security/osv_baseline.json` (une section par
  venv ; triage initial : 344 ids/venv_win, 354/venv_linux — surtout la pile ML) ; toute
  vulnérabilité nouvelle = rouge ; régénération = acte conscient (relire le diff git).
- `manage.py check_secret_leaks` (`common.consistency.secrets`) : gitleaks 8.30.1 (binaire
  provisionné par `scripts/fetch_security_tools.py`, git-ignoré) sur l'historique COMPLET
  (1034 commits ≈ 3 s, 0 fuite — réécriture du 23/07 confirmée empiriquement) + vérifie que le
  hook `scripts/git-hooks/pre-commit` (gitleaks sur le stagé) est installé et non dérivé :
  hook mort = ROUGE. Codes 3 = outillage/réseau absent → SKIP nocturne, pas un faux rouge.
  ⚠ **Trou relevé le 2026-10-12** : le hook ne voyait AUCUN de nos commits — la discipline
  multi-instances (`AGENTS.md`) commite par `git commit-tree`, qui n'exécute aucun hook ; seule
  la nocturne les balayait, après publication. ✅ Comblé le jour même, par des hooks GIT (donc
  valables pour tout agent et tout humain, pas pour un seul outil) : **`pre-push`** contrôle
  chaque commit qui part, quelle que soit sa fabrication (gitleaks + attribution), et
  **`commit-msg`** refuse une ligne d'attribution (`Co-Authored-By:`, « Generated with … ») dès
  `git commit`. Motifs : `scripts/git-hooks/attribution.pattern`, lus par les deux hooks ET par
  `check_secret_leaks`, qui vérifie désormais TOUS les hooks du dossier et l'absence
  d'attribution sur les branches (contrat 0 depuis la réécriture d'historique du 12/10).
  Configuration gitleaks versionnée : `.gitleaks.toml` (règles par défaut + une exception par
  ligne de faux positif lue).

**Dette actionnable relevée au triage initial (hors pile ML, upgrades patch-level possibles)** :
Django 5.2.6/5.2.8 (52-60 avis — patch release à passer au prochain palier de maintenance),
pillow 11.3.0 (36), aiohttp (48), cryptography, pyjwt, python-multipart, urllib3 1.26.20
(venv_win). À traiter par un palier d'upgrade AVEC smoke, jamais au fil de l'eau.

**⏳ Consigné, non ouvert (dans l'ordre de valeur)** :
1. **SAST local** (Opengrep, le fork open source de Semgrep qu'Aikido co-maintient — règles
   `p/django`) en 3ᵉ scénario `consistency`. À n'ouvrir QU'AVEC son triage initial (des dizaines
   de findings attendus sur 10 apps) — un scénario rouge en permanence devient aveugle.
2. **Aikido en second regard** : compte gratuit en lecture sur le repo public, si l'on veut le
   dashboard/auto-triage en plus de la nocturne. Compatible avec 1, pas un remplacement.
3. **Zen (firewall runtime Django)** : UNIQUEMENT au palier de déploiement exposé (§11), avec
   smoke gunicorn+Celery et question gouvernance RGPD (télémétrie vers le cloud Aikido) posée
   au labo. Prématuré tant que WAMA n'est pas servi hors du poste.
4. **Réputation de paquet à l'ingest `library`** (esprit Safe Chain) : interroger OSV.dev au
   moment d'ingérer un manifeste `library` (LibreTranslate…) — s'ajoutera au pipeline
   d'ingest des manifestes, pas comme wrapper de pip.

### 16.11 ComfyUI — cartographie de ses backends de modèles (ouverte le 2026-10-06)

> Demande de Fabien (2026-10-06), à l'occasion de l'aperçu des latents de l'imager, dont les
> coefficients viennent de ComfyUI (`common/utils/latent_rgb_factors.py`) : *« ComfyUI est
> opensource et a des backends pour plein de modèles image/vidéo. Pour l'intégration/génération
> de modèles présents dans ComfyUI, ne pourrait-on pas inspecter les backends ComfyUI, s'en
> inspirer ou les intégrer selon ce qui est possible ? »* — méthode `/cartographie` : la
> connaissance AVANT toute implémentation. **Rien n'est décidé ici ; rien n'est implémenté.**

**Les trois voies à départager (hypothèses, pas des décisions)** :

| voie | ce qu'elle apporterait | ce qu'elle coûterait |
|---|---|---|
| **S'inspirer** — lire ses implémentations quand on écrit un backend WAMA | précision (formats de latents, déjà adopté), astuces mémoire, « voisins » pour le rôle LLM `backend` (marche B2, vivier) | lecture ; aucune dépendance |
| **Moteur externe** — serveur ComfyUI sans interface, piloté par son API, vu comme un moteur (patron Ollama / audio.cpp) | accès à beaucoup de modèles et de workflows | deux processus sur le GPU (gouverneur) ; autre rangement des poids (doublons) ; nœuds tiers = risque (« allowlist d'abord », §10.3 de la ROUTE) |
| **Vendoriser** des morceaux | indépendance vis-à-vis de diffusers pour une famille | lourd ; code GPL-3.0 à entretenir (compatible AGPL) |

**Tableau des passes** (ordre `/cartographie` §2) :

| passe | objet | qui | état |
|---|---|---|---|
| 0 | inventaire structurel, périmètre retenu/écarté | moi | ✅ 2026-10-06 |
| 1 | noyau des modèles : détection (`model_detection`, `supported_models`), base (`model_base`), chargement single-file / quantifié, gestion VRAM (`model_management`, `model_patcher`) | moi (lecture déléguée, 5 points revérifiés à la ligne) | ✅ 2026-10-06 |
| 2 | noyau d'extension : contrat des nœuds (`comfy_api` v3), nœuds tiers, exécution (`comfy_execution`) — sécurité comprise | moi | 🔄 volet « gestionnaire des nœuds tiers » (ComfyUI-Manager) fait le 2026-10-19, ci-dessous ; contrat des nœuds et exécution ⏳ |
| 3 | implémentations par famille (`comfy/ldm/<famille>`) recoupant le catalogue WAMA | wama-dev-ai (volume, lecture seule) | ⏳ — exige de la VRAM libre (WAMA arrêté : moment à choisir par Fabien) |
| 4 | variantes / portages (nœuds `comfy_extras` par famille) | wama-dev-ai | ⏳ |
| 5 | confrontation à WAMA (contrat de backend, routes d'intégration, gouverneur, marche B2) + plan ordonné, décisions Dn | moi | ⏳ |

**Passe 0 — faits (2026-10-06)** :
- Corpus `comfyui` déclaré à `wama-dev-ai/corpus.py` : clone en lecture seule HORS du dépôt,
  `D:\tmp\corpora\ComfyUI`, commit `7d9e5a045c13c563a5dcd18c617a985efa6332da` (2026-10-06) ;
  `corpus.py` → **580 fichiers retenus**.
- Volumes : 962 fichiers Python ; `comfy/` ≈ 125 000 lignes, `comfy_extras/` ≈ 63 000.
- Retenu : `comfy` (modèles, détection, chargement, VRAM, latents), `comfy_extras` (nœuds par
  famille), `comfy_api` (contrat des nœuds), `comfy_execution` (graphe, cache, progression).
  Écarté : serveur web et frontal (`app`, `api_server`, `middleware`, `blueprints`), nœuds des
  services d'API payants (`comfy_api_nodes`), base (`alembic_db`), tests, exemples.
- **48 familles** sous `comfy/ldm`, dont beaucoup recoupent le catalogue WAMA : `flux`,
  `qwen_image`/`qwen_image21`, `wan`, `lightricks` (LTX), `hunyuan_video`, `genmo` (Mochi),
  `cogvideo`, `cosmos`, `hidream` ; `sam3` (anonymizer), `yue2` et `ace` (composer), `seedvr`
  (agrandissement), `trellis2` / `hunyuan3d` / `triposplat` (studio 3D), `mmaudio`.
- À lire en passe 1 : le dépôt porte son propre aperçu des latents (`latent_preview.py`, racine,
  hors périmètre du corpus — le relire à part) et un `AGENTS.md` (veille des harnais :
  `WAMA_HARNESS.md`), ainsi qu'un `comfyui:QUANTIZATION.md`.

**Passe 1 — faits (2026-10-06)** — références `comfyui:<chemin>:<ligne>` au commit `7d9e5a04` ;
lecture faite par un agent, **cinq points revérifiés à la ligne** (marqués ✓) :
- **Détection par les POIDS, jamais par une config** : `model_detection.detect_unet_config`
  (`comfyui:comfy/model_detection.py:44`) lit des clés « signature » et des formes de tenseurs
  (Wan : `head.modulation`, `:735-789` ; Flux : `double_blocks…key_norm`, `:263`), puis
  `model_config_from_unet_config` prend la première classe de `supported_models.models` qui
  correspond — l'ORDRE de la liste départage (`comfyui:supported_models.py:2604-2631`). Une déclaration
  de modèle (`supported_models_base.BASE`, `:31-124`) porte : clés de correspondance, réglages
  d'échantillonnage, format de latents, dtypes, facteur mémoire, encodeurs de texte, préfixes
  du VAE et des encodeurs dans le checkpoint unique.
- ✓ **Les dossiers diffusers ne sont lus que partiellement, par un chargeur DÉPRÉCIÉ** :
  `comfyui:comfy/diffusers_load.py:12-19` ne connaît que `unet/`, `vae/`, `text_encoder/`,
  `text_encoder_2/` — ni `transformer/`, ni fichiers fragmentés ; nœud `DiffusersLoader`
  marqué `DEPRECATED` (`comfyui:nodes.py:661`). Le format natif est le **checkpoint en un fichier**
  (safetensors, `comfyui:comfy/sd.py:2159-2326`).
- **Quantification** native fp8 / nvfp4 / mxfp8 / int8 par le paquet externe `comfy-kitchen`
  (`comfyui:comfy/quant_ops.py:7-46, 201-265` ; `comfyui:QUANTIZATION.md`) — ✓ **aucun chargeur GGUF dans le
  cœur** (motif `gguf`, insensible à la casse, sur tout le dépôt : seulement `main.py`,
  `comfyui:utils/mime_types.py` et des tests ; GGUF = nœud tiers).
- ✓ **VRAM mesurée sur tout le GPU**, autres processus compris (`comfyui:model_management.py:1848`,
  `mem_get_info`), ✓ réserve fixe de 400 à 700 Mo pour « les autres applications »
  (`:877-885`, `--reserve-vram`), pression NVML par défaut, déchargement partiel puis complet
  (`free_memory`, `:893-937`). Il ne suppose donc pas posséder le GPU — mais **aucun protocole
  de coordination** au-delà de ces réserves.
- ✓ **Aperçu des latents** : sur la PRÉDICTION de l'image propre (`denoised`, `comfyui:samplers.py:1003`)
  et la PREMIÈRE image d'une vidéo (`comfyui:latent_preview.py:77-80`) ; TAESD si un petit décodeur est
  installé, sinon la projection linéaire. WAMA projette les latents BRUITÉS (seuls exposés par
  diffusers) — consigné comme reste en `ROUTE §F3b`.
- **Sans interface** : `POST /prompt` (graphe au format « API »), suivi par `/ws`, résultats par
  `/history/{id}` et `/view`, `POST /free` pour décharger, `POST /interrupt`
  (`comfyui:server.py:1138-1265`) ; écoute sur `127.0.0.1` par défaut (`comfyui:cli_args.py:63`).

**Ce que la passe 1 CORRIGE de nos hypothèses** :
- « **Moteur externe = accès immédiat** à beaucoup de modèles » : faux pour NOS poids. WAMA range
  ses modèles en dossiers HuggingFace au format diffusers (`AI-models/`), que ComfyUI ne lit que
  pour les UNet de la famille SD, par un chargeur déprécié. Pour Flux, Wan, LTX, Qwen-Image…, il
  faudrait des checkpoints en un fichier : **une seconde copie des poids** (plusieurs centaines
  de Go au parc actuel), ou une conversion.
- « Deux processus sur le GPU = conflit » : à nuancer. ComfyUI mesure la mémoire de tout le GPU
  et garde une réserve ; la cohabitation est possible, mais elle échappe au gouverneur de WAMA
  tant qu'elle n'y est pas déclarée (patron des réservations de MuseTalk/TalkingHead).
- « S'inspirer » se confirme comme la voie sans coût : la détection par les poids et les
  déclarations de `supported_models` sont exactement ce qu'un rôle `backend` (marche B2)
  gagnerait à lire comme voisins.

**Passe 2, volet gestionnaire — ComfyUI-Manager confronté à WAMA (2026-10-19)** — question de
Fabien : *« le model manager de ComfyUI a-t-il des choses intéressantes à s'inspirer par rapport à
WAMA ? »*. ⚠ Source : le README officiel du gestionnaire (`github.com/comfy-org/ComfyUI-Manager`),
sa page de configuration (`docs.comfy.org/manager/configuration`) et le wiki d'installation des
nœuds — **pas son code** (dépôt distinct du cœur, hors du corpus `comfyui` de la passe 0). Les
lignes WAMA sont, elles, lues dans le code. **Rien n'est décidé ; rien n'est implémenté.**

*Ce que WAMA fait déjà, souvent plus strictement* :

| gestionnaire ComfyUI | WAMA |
|---|---|
| installe depuis une adresse Git ou par pip libre, permis sur un accès local selon le niveau de sécurité | refusé par principe : PyPI par nom, version exacte, ni `git+`, ni adresse, ni option (`model_installer.py:2046`, `pip_spec_error` ; verrous `§16.7`) |
| liste noire des rétrogradations, versions épinglées remises au démarrage (`pip_auto_fix`) | simulation `pip install --dry-run` AVANT, avec les mêmes contraintes, qui liste et refuse les rétrogradations (`model_installer.py:2198-2244`) |
| statut « Try Install » (installation non garantie) | `AIModel.is_installable` (`model_manager/models.py:878`) |
| « Fetch Updates » sans appliquer | prospection : « MAJ proposée », jugée puis validée par un humain |
| ligne de commande `cm-cli` | `pull_model`, `install_library`, outils de l'assistant |
| « installer les nœuds manquants » d'un workflow | au LANCEMENT, la route installe le modèle absent, prévient, la tâche attend (`studio/gpu_tasks.py:34-41` ; un nœud d'app passe par l'outil de l'app, `generic_runner.py:358`, `:376`, donc par son squelette — règle `AGENTS.md` « par la route ») |
| un nœud recréé garde les liens dont le nom correspond | un graphe ancien relie par identifiant de port, puis par rôle, puis au premier port (`wama-studio.js:726-732`) |

*Pistes à garder (hypothèses, chacune avec la ligne WAMA qui montre l'écart)* :
1. **Niveau de risque par GESTE.** Le gestionnaire classe ses actions (élevé : un poids qui n'est
   pas en `.safetensors` et hors de sa liste). WAMA décide par rôle du compte, et garde un `.pt`
   sans jumeau `.safetensors` (`model_installer.py:180-199`) ; or un `.pt`/`.bin` est du pickle,
   donc du code exécuté au chargement (`weights_metadata.py:110-120` ne le lit que sous
   `AI_MODELS_DIR`). Piste : « format pickle hors catalogue = geste à risque », dit à l'installation.
2. **Relevé de l'état pip avant chaque installation réelle**, pour annuler en un geste (le
   gestionnaire photographie avant « Update All » et restaure au redémarrage). WAMA date ses
   installations (`InstallEvent`, `model_manager/models.py:1143`) mais ne sait revenir en arrière
   que pour un modèle Ollama remplacé (`model_installer.py:1496-1526`).
3. **Vulnérabilités vérifiées AVANT d'installer**, pas seulement la nuit. `check_dep_vulns`
   interroge OSV.dev sur les paquets DÉJÀ installés (`mecanismes.py:996-1001`), lancé par la
   nocturne (`nightly_scenarios.py:192`) ; la simulation de la piste ci-dessus connaît les versions
   à venir et pourrait poser la même question.
4. **Dire ce qui manque à l'OUVERTURE d'un pipeline** (le gestionnaire liste les nœuds absents à
   l'import d'un workflow). Vérifié au studio le 2026-10-19 :
   - il n'existe **aucun import de pipeline venu d'ailleurs** : pas de route d'import
     (`studio/urls.py`), `manifests/pipelines/` = corpus EXPORTÉ du code, systèmes seuls
     (`manifest_export.py:42-47`, `:65-67`). ⚠ Mais le PARTAGE arrive : depuis l'étape 4 de
     `§29` (même jour, `f2060880`), `StudioPipeline` hérite de `ScopedVisibility`
     (`studio/models.py:29`) — le geste « Partager » d'un pipeline reste à poser
     (`WAMA_COLLABORATION.md`, marche 4) ;
   - ⚠ **et un nœud que la palette ne connaissait pas disparaissait EN SILENCE à l'ouverture**
     (constat du matin) : `addNode` rendait `null`, `loadGraph` sautait le nœud et ses liens. La
     palette filtre par accès à l'app et exécutabilité, une fonction suivant l'app qui la porte :
     ouvrir le sien après une perte d'accès — ou, demain, un pipeline partagé — l'amputait sans le
     dire, et l'enregistrer sous le même nom (`views.py:96`, mise à jour par nom) effaçait le nœud
     en base. (Un pipeline DÉCLARÉ dont un nœud est fermé au compte n'est, lui, plus proposé du
     tout depuis l'étape 4 : `_declared_pipelines`.)
     ✅ **Corrigé le 2026-10-19 (GO Fabien, après le commit de l'étape 4)** :
     - le canvas GARDE le nœud, marqué « indisponible pour ce compte », réglages et liens intacts
       — sa description se lit du graphe seul, ses liens disent ses ports
       (`wama-studio.js:749`, `describeUnavailable` ; `addNode`, `:300`) — et l'ouverture le dit
       (`warnUnavailable`, `:822` : pipeline ouvert ET brouillon restauré) ;
     - le lancement le refuse d'avance, relié ou non, par la MÊME règle que la palette : la
       construction de la palette est sortie d'`api_nodes` (`studio/services/palette.py:24`,
       `palette_nodes`) et `launch_graph` la lit (`launch.py:179`) — non accessible à ce compte,
       app non exécutable, ou inconnu de WAMA. Avant : une app fermée n'était refusée qu'au milieu
       du run (`execute_tool`), une fonction inconnue non reliée faisait échouer la tâche ;
     - garde : `studio/tests_unavailable_nodes.py` (6 tests, dont la description exécutée sous
       V8) ; cinq contre-épreuves, rouges.
     ✅ **La raison s'affiche SUR le nœud (décision de Fabien, 2026-10-19)** — elle n'était connue
     qu'au lancement. Une seule règle, lue des deux côtés : `palette.unavailable_reason`
     (`studio/services/palette.py:110`) rend `{code, label, message}` — le `message` est la phrase
     du refus au lancement, qui la lit désormais (`launch.py:179`) ; le canvas la demande à
     l'ouverture (`api/nodes/unavailable/`, `views.py:53`) et la pose sous l'en-tête du nœud, dans
     l'infobulle de son badge et dans l'inspecteur (`explainUnavailable`, `wama-studio.js:803`).
     Elle se garde pour la page : annuler / rétablir reconstruit le nœud sans la redemander.
     Garde : 3 tests de plus (9) ; quatre contre-épreuves, rouges (raison aveuglée, ligne non
     posée, raison oubliée à la reconstruction, `addNode` sans ligne).
5. **Mode réseau déclaré** (public / privé / hors-ligne) et relais pour Hugging Face et GitHub
   (`HF_ENDPOINT`, `GITHUB_ENDPOINT`) — utile derrière un proxy ou sans Internet ; aucune
   occurrence dans `wama/settings.py`. Secondaire.

*À ne PAS reprendre* : l'exécution automatique de l'`install.py` d'une extension (code arbitraire,
sans relecture) ; l'installation par adresse Git, le pip libre, un registre communautaire ouvert
(morts aux verrous `§16.7`) ; le niveau `weak`, que les guides font activer pour « débloquer » une
installation et qui retire toutes les protections d'un coup.

---

## 17. Capacité détection open-vocabulary — brique commune + LocateAnything (ouvert 2026-07-27)

> Décision (évaluation session 2026-07-27) : intégrer **NVIDIA LocateAnything-3B** comme
> **complément** de YOLO/SAM3 (pas remplaçant), en **capability-first** (règle §16.6 : pas d'app
> dédiée tant que le besoin récurrent n'est pas démontré).

**Le modèle** : VLM détecteur (MoonViT-SO-400M MIT + pont MLP + Qwen2.5-3B-Instruct) qui GÉNÈRE les
boîtes en tokens (`<box><x1><y1><x2><y2></box>`, coordonnées 0–1000). Tâches : detect (catégories
libres), ground_single/multi (referring expressions), point, detect_text, ground_gui. ~8 Go BF16
(4B params réels). Backend officiel = transformers 4.57.1 + `trust_remote_code` (venv_linux à
4.57.6 — écart mineur, tester AVANT de créer un venv isolé) ; TensorRT-LLM/Triton non supportés ;
Linux only (WSL2 OK). `generation_mode="hybrid"` + `max_new_tokens=8192` recommandés.

> ✅ **2026-09-08 — LA QUESTION DU VENV ISOLÉ EST TRANCHÉE : il n'en faut pas.** Ce paragraphe
> demandait de « tester AVANT de créer un venv isolé » ; le test est fait, sans charger un seul
> poids : `AutoConfig.from_pretrained(<snapshot local>, trust_remote_code=True)` rend
> `LocateAnythingConfig` avec le venv_linux actuel (transformers 4.57.6). L'écart à la pin
> officielle 4.57.1 n'a aucune conséquence.
> **Le backend est écrit** — `wama/common/backends/locate_anything_backend.py`, au contrat commun,
> qui ADAPTE la classe officielle NVIDIA gardée verbatim dans `scripts/locate_anything_worker.py`
> (« ne pas modifier ») et rend déjà la forme NORMALISÉE de l'étape 2 : `{boxes, answer, task}`
> en pixels. Le dossier des poids est désormais DÉCLARÉ (`MODEL_PATHS['vision']['locate_anything']`)
> au lieu d'être reconstruit ; il existait sans déclaration depuis le PoC du 27/07.
> ⚠ **NON ÉPROUVÉ DE BOUT EN BOUT** : ~9 Go de VRAM, et aucune charge GPU n'est lancée depuis le
> poste de dev (crashs hôte, cf. l'étape 1 ci-dessous, toujours SUSPENDUE). Sont vérifiés : la
> résolution modèle→backend, la disponibilité, la présence des poids, la résolution de la config,
> les refus d'entrée. Ne le sont pas : `load()` et `process()` en conditions réelles.
> ⚠ **C'est le SEUL des 6 modèles prospectés sans backend qui soit chargeable ici** — les autres
> (canary, parakeet, PP-DocLayout, FastWan, ACE-Step) exigent `transformers 5.x` ou un toolkit
> absent, et l'installation est refusée par le verrou : c'est une DÉCISION de venv, pas du code.

**⚠ Licence NVIDIA NON-COMMERCIALE** (+ Qwen Research License sur le LLM) : OK recherche Lescot,
**EXCLU pour livrables partenaires ou valorisation**. → Conséquence architecturale : déclarer
`license` en **métadonnée** (`AIModel`/`capabilities`) pour que `select_model()`/Studio filtrent ou
avertissent — métadonnée-driven, pas mémoire humaine.

**⚠ Latence VLM** (~1,5–7 s/image sur 3090 selon mode) : JAMAIS per-frame vidéo. Usages viables :
image unique, keyframes fenêtrés (patron `sam3_fps`), **auto-labeling/distillation** de classes
rares vers des YOLO spécialisés (le goulot actuel des modèles faces/plates).

**Séquencement** :
1. **PoC standalone** — `scripts/poc_locate_anything.py` + `scripts/locate_anything_worker.py`
   (poids dans `AI-models/models/vision/locate-anything/`, HF_HUB_CACHE posé avant import).
   ⚠ **2026-07-27 : partie GPU SUSPENDUE sur le poste dev** — 3 crashs hôte (hang GPU-PV WSL2,
   bug ouvert MS WSL #40732 : pression d'allocation CUDA → kernel panic Hyper-V). Déjà validés :
   compat transformers 4.57.6, chargement CPU (11 s), chargement CUDA (≈60 s, 7,3 Go VRAM).
   Valider l'inférence (qualité + latence sur cas anonymizer écrans/badges/documents + échantillon
   cam_analyzer) sur **Linux natif (serveur R760xa) ou venv Windows natif** — pas via WSL2 ici.
2. **Brique commune détection** dans `wama/common/` — contrat `BaseModelBackend`, sortie normalisée
   `{bbox, label, confidence, mask?, track_id?}`, en y absorbant D'ABORD les 2 wrappers SAM3
   dupliqués (`common/backends/sam3_processor.py` — au substrat depuis le 2026-09-07 — +
   `cam_analyzer/utils/sam3_road_analyzer.py`, dont l'import cross-app est soldé par ce
   déplacement). LocateAnything = backend supplémentaire.
3. **Manifeste `function`** « détection open-vocabulary » — port de sortie `DataType.DETECTIONS`,
   entrée `image + prompt` (champ déclaré dans `PROMPT_TARGETS`) = 1er nœud Studio natif.
4. **App detector** = UI prompt-first + file PAR-DESSUS la fonction — APRÈS anonymizer/imager, et
   seulement si l'usage via assistant/Studio le justifie (§16.6).

### 17bis. Detector — périmètre précisé par Fabien (2026-08-13)

**Ce que l'app doit permettre** : détecter/segmenter/localiser, puis **retirer, remplacer ou
déplacer un objet** — changer la couleur d'un feu tricolore, substituer un panneau — et
**fabriquer des séquences vidéo modifiées à partir de séquences réelles**, pilotées par une
**description en langage naturel**. Finalité : produire de façon automatisée des **supports
présentés à des participants** (recherche SHS). Inclut in-painting / out-painting / retouche.

⚠ **App SÉPARÉE de l'anonymizer, et pas pour des raisons d'organisation.** L'anonymizer
**détruit** de l'information de façon irréversible ; sa garantie est « rien d'identifiable ne
subsiste ». Le Detector **fabrique** du contenu ; sa garantie est inverse — « la modification est
délibérée et **traçable comme synthétique** ». Pour un support montré à des participants, cette
traçabilité est une exigence méthodologique, pas un confort. Deux promesses contradictoires ne
tiennent pas dans une même app.

**Ce qui est DÉJÀ commun** (acquis du 2026-08-12/13, rien à faire) : la couverture multi-modèles
(`common/services/model_coverage.py`) et le vocabulaire de classes avec ses alias
(`formes_equivalentes`).

**LA COUTURE À EXTRAIRE, le jour où le Detector existe** — et pas avant :
`common/backends/anonymize.py` (au substrat depuis le 2026-09-07) porte désormais un moteur *un décodage, N modèles, union des zones
frame par frame*, plus le **suivi de piste et l'interpolation**. C'est exactement ce qu'exige un
objet **déplacé** ou un feu **changé** de façon cohérente d'une frame à l'autre. La couture est
nette : **une fonction qui rend, par frame, l'image et les zones — l'appelant décide quoi en
faire.** L'anonymizer floute ; le Detector remplace.

⚠ **NE PAS extraire par anticipation.** C'est précisément ce qui a produit `couvrir_classes` :
brique excellente, écrite pour un besoin réel, restée **sans consommateur pendant 8 jours** parce
qu'on ne savait pas encore ce que l'appelant demanderait à une frame (masque ? boîte ? piste ?
profondeur ?). Extraire au **second consommateur** : la couture étant identifiée, ce sera une
heure, pas une redécouverte.

**Le floutage dans les fonctions du monde Data** (cf. `WAMA_DATA_FUNCTION_CARDS.md`) : oui, mais
**la primitive seulement** — `blur_detection` / `blur_segmentation`, déjà isolées dans
`wama/common/utils/blur_utils.py` (remonté au commun le 07/09), à E/S typées. L'*anonymisation* n'est pas une fonction : c'est
une chaîne détecter → suivre → interpoler → flouter → ré-encoder.

**Points d'appui existants** : **SAM3** est déjà dans l'anonymizer et **pilotable par prompt
texte** (c'est l'entrée « langage naturel ») ; **LocateAnything** est cadré ci-dessus pour le
vocabulaire ouvert (poids non téléchargés, GPU suspendu sur ce poste).

**Bénéficiaires** : anonymizer (le sélecteur maison de 1 140 l. a déjà fondu — voir
`PROJECT_STATUS §REPRISE 2026-08-13` : `parallel_detection.py` ne garde plus que la DÉCISION, un
open-vocab supprimerait le reste du problème de couverture de classes), cam_analyzer
(auto-labeling, requêtes fenêtrées), **detector** (ci-dessus).

**Alternatives libres** si la licence bloque : YOLO-World, MM-Grounding-DINO (Apache-2.0), OWLv2 —
la brique (2) est agnostique au backend, l'investissement reste bon dans tous les cas.

**⏳ État au 2026-09-27 — désignation par classes / par description (chantier anonymizer, décisions
de Fabien)** :
- L'anonymizer DÉSIGNE ce qu'il floute par un MODE déclaré (`app_modes`, `mode_param =
  target_mode`) : **Classes** (modèles à classes) ou **Description** (modèles qui consomment un
  prompt) — ex-« YOLO/SAM3 », qui confondait la désignation et le résultat. Le résultat (boîte /
  contour) reste au curseur rapide ↔ qualité en « auto » (segmentation à partir de 50), au choix
  du modèle sinon ; le menu est tiré du catalogue, `detect` + `segment`, groupé par tâche.
- **LocateAnything** : capacités complétées au catalogue (`inputs_required` + prompt,
  `text_promptable`) — mais **PAS proposé dans l'anonymizer** tant que trois conditions ne sont pas
  levées : branché au moteur de floutage (qui ne consomme que YOLO et SAM3), éprouvé de bout en
  bout sur GPU (jamais tourné sur ce poste), et grisé pour la VIDÉO par sa latence (1,5–7 s/image).
- **pose / classify / obb** : hors du menu de l'anonymizer (filtre par tâche, rien de supprimé) ;
  ils restent au catalogue pour le Detector — qui devra les chercher PAR TÂCHE, pas par app (leur
  `source` est encore `anonymizer`, héritage du rangement des poids).
- **Piste (non ouverte) — flouter des PARTIES DU CORPS par la pose** : un modèle de pose ne
  découpe pas la silhouette, il place 17 points (nez, yeux, oreilles, épaules, poignets…) et une
  boîte par personne. On pourrait en DÉDUIRE des zones — la tête depuis les cinq points du visage
  quand un détecteur de visages échoue (profil, distance), une main… : une 3ᵉ désignation
  (« parties du corps »), avec un travail moteur (points → zones). Pour une silhouette entière, la
  segmentation de la classe « personne » fait déjà mieux.

### 17ter. Reconstruction 2D→3D + chaîne objets 3D (consigné 2026-08-18 — NON ouvert)

> Cas d'usage moteur (Fabien 18/08, domicile = `STUDIO_VISION.md` chaîne 3) : photo de véhicule(s)
> → segmentation (detector §17bis) → reconstruction 3D → médiathèque → passerelle **virtualib**
> (librairie d'objets 3D existante hors WAMA) → simulation Unreal Engine ; retour 3D→2D via
> l'Imager (insertion dans un décor généré). Même règle qu'au §17 : **capability-first** (§16.6) —
> d'abord un manifeste `function` « image→3D » (nœud studio natif), une app dédiée seulement si
> l'usage le justifie.

**Candidats modèles (prospection à jouer — chaîne Ollama-first/HF existante)** : **TRELLIS**
(Microsoft, MIT), **TripoSR** (Stability+Tripo, MIT), **Hunyuan3D-2.x** (licence communauté
Tencent — OK recherche Lescot, à vérifier pour livrables partenaires/valorisation),
**Stable Fast 3D / SPAR3D** (Stability community). Mono-image → mesh texturé, VRAM ~6–16 Go
(passe sur la 4090). Licence+auteur en base comme d'habitude (politique licences).

**Conversions 3D au CONVERTER (intention Fabien, 2026-08-30 — formats À DÉFINIR)** : des
conversions d'objets 3D pourraient rejoindre le converter média — objets Blender, Unreal
Engine, formats d'impression 3D, etc. Rien n'est listé ici volontairement (« à définir ») :
le jour venu, le geste est balisé — la nature `3d` existe (`OBJECT3D_EXTENSIONS`, pivot GLB
déclaré ci-dessus), ajouter les formats = étendre `SUPPORTED_CONVERSIONS` du `format_router`
ET son miroir `DOCUMENT_EXTENSIONS`-like (une entrée `'3d'` d'`input_types`/`output_types` du
converter), la card/le menu « Envoyer vers » suivent PAR DÉRIVATION. ⚠ Le témoin
hors-vocabulaire de `tests_codegen_lot` est un `.glb` : il devra changer À NOUVEAU quand le
converter déclarera `3d` (l'invariant survit, pas le témoin — c'est prévu par son docstring).

**⚠ Reconstruction PLAUSIBLE, pas métrique** : les faces occultées sont HALLUCINÉES (un véhicule
partiellement visible sort complet mais inventé). Parfait pour des props de simulation ; EXCLU
pour toute reconstruction mesurée. → à déclarer en **métadonnée** du modèle/de la fonction
(même geste que la licence au §17), pas en mémoire humaine. **Niveau de qualité = PROGRESSIF
(décision Fabien 18/08)** : commencer par le plus facile (mono-image, props plausibles), puis
approfondir en testant jusqu'où on peut aller (multi-vues, fidélité au véhicule réel).

**Trous d'infrastructure (dans l'ordre)** :
1. ✅ **Taxonomie (fait 2026-08-18)** : catégorie `'3d'` + `OBJECT3D_EXTENSIONS` (pivot **GLB**)
   déclarées dans `common/app_registry.py` — `normalize_types`/`category_of_path`/ports studio/
   `TYPE_GROUPS` médiathèque en dérivent (validé : `glb→['3d']`) ; type d'asset `object3d`
   déclaré dans `media_library/models.py` (migration 0013, no-op SQL, appliquée WSL2).
2. ✅ **Médiathèque : ingest + aperçu des objets 3D — FAIT le 2026-09-13 (soir)**, sur A′ :
   - **ingest** : un `.glb`/`.gltf` déposé (ou rangé depuis une sortie d'app) reçoit ses
     `attributes` LUS du fichier par la sonde commune (`media_probe.probe_object3d` — table
     des matières glTF, sans décoder : format, faces, rig, animations) et un MIME `model/…`
     (`mime_utils`, qui PRIME sur la stdlib — elle ne connaît aucun format 3D) ; ce que
     l'utilisateur saisit prime sur la sonde (`services.enrich_asset_from_file`, posé sur les
     deux chemins d'entrée) ;
   - **aperçu** : `media-preview.js` ouvre pour `model/…` la visionneuse commune
     `common/js/wama-3d-viewer.js` (module ES, three vendorisé : GLTF/GLB et FBX, cadrage sur la
     boîte englobante, orbite, grille, 1ʳᵉ animation jouée, contexte WebGL libéré à la
     fermeture), chargée À LA DEMANDE par l'importmap — une page sans importmap retombe sur le
     téléchargement sans erreur. La médiathèque inclut l'importmap ; obj/stl/ply/usd sont
     acceptés à l'ingest mais restent au téléchargement (aucun loader vendorisé) ;
   - **attesté** : cube GLB fabriqué octet par octet (tests) → 12 faces, riggé, 1 animation
     lus ; dans le navigateur : card `fa-cube`, `<canvas>` WebGL monté dans la modale, méta
     « GLB • 1 maillage • 1 animation », canvas retiré à la fermeture, 0 erreur console (8/8).
   - ⚠ **TROUVÉ EN CHEMIN : `three.core.js` MANQUAIT sur disque depuis le vendoring du 21/08**
     (le build est scindé depuis r170, `three.module.js` n'est qu'une façade qui l'importe) :
     TOUT import de `three` — TalkingHead compris — tombait en 404 dans le navigateur, et la
     garde `VendoringTest` ne demandait que la façade. Récupéré depuis npm (0.180.0, façade
     vérifiée identique), versionné avec la LICENSE (MIT), `update_vendors.sh` et la garde
     complétés.
3. ✅ **Port studio 3D — le port existe, mais il nomme une NATURE MÉDIA** (rectifié le
   2026-09-17, décision de Fabien : *« on garde object_3d dans le monde média »*).
   ⚠ Ce point disait, du 13/09 au 17/09 : « `DataType.OBJECT_3D` déclaré, et la nature
   `object3d` le porte en `data_type` ». **Ce type était un JUMEAU** — la même chose nommée
   deux fois, une par monde — et le SEUL du dépôt. Mesuré avant retrait : **1 producteur**
   (`studio.image_to_3d`), **aucun consommateur**, **zéro occurrence dans le Lab**, et
   `Nature.data_type` n'était lu que par un test.
   **Ce qui tient désormais** : un objet 3D est un FICHIER média, sa nature est `3d`
   (`MEDIA_CATEGORIES`) ; le port de sortie de la fonction nomme cette nature, et le
   vocabulaire admis aux ports accepte déjà les natures média
   (`app_registry.known_port_types`) sans fusionner les deux taxonomies. Le futur nœud
   d'insertion (trou 6) attendra donc un port `3d`, pas un type de donnée.
4. 🔄 **Manifeste `function` « image→3D » + backend — ÉCRIT le 2026-09-13, NON EXÉCUTÉ**
   (le premier run GPU se fait avec Fabien — règle crashs hôte) :
   - **modèle** : `huggingface:triposr` au catalogue (`_discover_image_to_3d_models`, poids
     `stabilityai/TripoSR` MIT sous `MODEL_PATHS['vision']['triposr']`, moteur `triposr`,
     `capabilities.reconstruction='plausible'` — déclaré, pas en mémoire humaine). Retenu vs
     TRELLIS / Hunyuan3D-2 / SF3D parce que SEUL sans extension CUDA à compiler ;
   - **backend** `common/backends/image_to_3d_backend.TripoSRBackend` (contrat commun, ENGINE
     `triposr`, résolu par `backend_for_key`) sur le code VENDORISÉ (`tools/setup_triposr.sh` :
     clone épinglé + marching cubes → PyMCubes + `rembg` paresseux) ; poids ~~par
     `hf_hub_download(cache_dir=…)`~~ DÉCLARÉS et installés par le pilote `files` du model
     manager depuis le 2026-10-18 (`TRIPOSR_FILES`, règle « par la route » d'`AGENTS.md`), la
     tâche studio attendant l'installation (`model_readiness.ensure_installed`) ;
   - **fonction** `studio.image_to_3d` (`studio/function_specs.py`, ports `image` → `3d` —
     DEUX natures média depuis le 2026-09-17, cf. point 3 ci-dessus ; `OBJECT_3D` jusque-là,
     tâche GPU `studio.gpu_tasks:image_to_3d_task` routée sur la file `gpu`, pas
     `studio`) ; **l'exécuteur passe désormais les FICHIERS de l'amont par port** à une fonction
     app-bound, et reconnaît un résultat-fichier (le nœud « Sortie » le range en médiathèque avec
     ses attributs lus) ;
   - attesté sans GPU : 9 tests (spec, ports, impl, catalogue → backend, contrat, routage,
     fichiers par port) ; **reste** : `--allow --apply` de `trimesh` + `PyMCubes` par la route
     `library`, `setup_triposr.sh`, et le premier maillage — vérifier l'ORIENTATION des faces
     (permutation d'axes de torchmcubes reproduite, non attestée).
5. **Passerelle virtualib** : APRÈS collecte en médiathèque ; **IMPORT ET EXPORT (décision
   Fabien 18/08)**, export d'abord ; lien inter-mondes déclaré (manifeste), pas de glu ad hoc.
6. **Insertion dans une scène générée** (retour 3D→2D ET avatar-dans-décor, chaîne 4 studio) :
   couture PARTAGÉE — règle du second consommateur, cf. `STUDIO_VISION.md ⚑ Convergence`.
   NE PAS extraire par anticipation.

**SENS INVERSE 3D→2D — arbitrage à trancher (question Fabien 19/08) : avec ou sans modèle IA ?**
Le retour 3D→2D se décompose en DEUX étapes que rien n'oblige à traiter pareil :
  a. **Rendu** (objet 3D → image sous un point de vue) : **DÉTERMINISTE, aucun modèle IA
     nécessaire** — Blender headless (`bpy`, CLI) ou three.js offscreen, tous deux déjà dans
     l'orbite du projet (three.js sera vendorisé pour la preview médiathèque, trou 2). Un
     modèle IA ici serait une régression : on perd le contrôle exact de la pose, de la focale
     et de l'échelle, qui sont précisément ce qu'on veut MAÎTRISER pour une expérimentation.
  b. **Harmonisation** (le rendu doit *appartenir* au décor : lumière, ombre portée, grain,
     perspective) : **c'est là — et là seulement — qu'un modèle IA se justifie**. Candidats :
     img2img/inpainting à faible force conditionné par profondeur (qwen-image-edit est DÉJÀ
     actif), ou un modèle de compositing/relighting dédié si la qualité ne suit pas.
  → **Règle proposée** : commencer SANS modèle IA (rendu + collage), mesurer, n'ajouter le
  modèle qu'à l'étape (b) si le résultat ne tient pas — même discipline que « capability-first ».
  ⚠ Ne PAS confondre avec la **synthèse de vues nouvelles** (novel view synthesis) : elle sert
  à *fabriquer* des vues quand on n'a pas de 3D ; ici on A la 3D, donc elle est hors sujet.

**PoC sans attendre l'app detector** : SAM3 (déjà prompt-piloté dans l'anonymizer) → crop →
modèle 2D→3D → GLB. Partie GPU : **avec Fabien uniquement** (règle crashs hôte).

**AVATARS — deux usages déjà prospectés (ne pas re-prospecter)** : la veille complète est
`docs/construction/archive/PROSPECTION_AVATARS_2026-08-17.md`, **mise à jour le 2026-09-30 par
`docs/construction/archive/PROSPECTION_AVATARS_2026-09-30.md`** (cf. §Études/veille) (12+ candidats, licences vérifiées au fichier ;
⚠ Hunyuan EXCLUT l'UE). (a) **consignes offline** avec avatar « scientist » → EchoMimicV3-Flash
/ StableAvatar ; (b) **mode avatar temps réel de l'AI-Assistant** → 1ʳᵉ voie **TalkingHead**
(MIT, rendu NAVIGATEUR three.js, zéro VRAM serveur, visèmes FR). **Le lien avec le 3D est
direct et sous-exploité** : (b) rend un GLB dans le navigateur — c'est le MÊME moteur de rendu
que le trou 2 (preview médiathèque) et que le rendu (a) ci-dessus. Vendoriser three.js une
fois sert les trois. L'« avatar avancé intégré dans un décor » (chaîne 4 studio) est la
rencontre des deux chantiers : avatar rendu + insertion dans une scène générée (point 6).

## 18. Réorganisation de l'arbre en MONDES — **1ʳᵉ marche FAITE le 2026-08-22 (monde Data)**

- **Constat 2026-07-27** : `wama/common/` (14 sous-packages) mélange glu de plateforme (sa vraie
  vocation) et services de domaine qui préfigurent des mondes. Le problème n'est PAS la taille,
  c'est le mélange des étages.
- **Cible** : un monde = un package frère de `wama/` (précédent vivant : `wama_lab/`). Si le monde
  Data grossit → `wama_data/` à côté, PAS un éclatement de `common/`.

### ✅ Marche 1 — le monde DATA est sorti de `common/` (2026-08-22, demande de Fabien)

La cible ci-dessus était juste et a été suivie **à la lettre** : `wama_data/` est une racine sœur,
pas un éclatement de `common/`. Ce que la prévision n'avait pas tranché, c'est **où passe la
frontière** — et c'est la seule vraie décision :

> Le registre de fonctions et la taxonomie de types RESTENT dans `wama/common/catalog/`. Fait
> mesuré, pas doctrine : `wama_lab/cam_analyzer/function_specs.py` y déclare des fonctions du
> **Lab**, et les manifestes `function`/`dataset` du substrat en dépendent. Les loger dans
> `wama_data` ferait dépendre le Lab et le substrat du monde Data.

**Défaut trouvé et corrigé au passage** — c'est lui qui rendait le déport risqué : `load_all()`
citait `wama.common.data` ET `wama_lab.cam_analyzer` **en dur**. Le substrat nommait deux mondes,
donc le déport l'aurait cassé **silencieusement** (catalogue à moitié vide, aucune erreur). Le
registre parcourt maintenant les apps installées ; chaque monde se déclare dans son `ready()`.

⚠ **Les conditions d'ouverture n'étaient PAS remplies** (portage anonymizer/imager non fini) —
décision de Fabien, à qui la structure coûtait plus cher que l'attente. Ce que la condition
protégeait a donc été vérifié explicitement à la place : `check_app_conformity` re-passé après le
déménagement, **grille inchangée** (la grille analyse `wama/<app>/`, que le déport ne touche pas),
`conformity_report.json` identique. Reste vrai pour la suite : ne PAS enchaîner sur le monde
Médias tant qu'un chantier multi-instances est ouvert — un refactoring d'imports transverse casse
toutes les partitions à la fois.

- **Marches suivantes (non ouvertes)** : monde Médias (`wama/` confond encore plomberie projet +
  10 apps média + plateforme transverse), puis structuration interne de `common/` — `utils/`
  (61 fichiers, 9 859 lignes) et `static/` (8 384) sont les vrais blocs, pas `data/` (5 107, 13 %).
  **Sortir Data n'a PAS désengorgé `common/`** et ce n'était pas le but : la justification est
  doctrinale.

### 18.0bis Génération-MIROIR + surfaces de travail (idées Fabien 2026-08-03 soir, cadrées)

**① Génération-miroir (pilote)** — régénérer UNE app simple depuis son manifeste (bac à sable
worktree) et la CONFRONTER à l'app portée. Le diff devient un instrument qui sépare :
trou de PORTAGE (la générée l'a, la portée non) vs spécificité NON DÉCLARÉE (la portée l'a,
le manifeste l'ignore → trou du FORMALISME, à déclarer). Garde-fous : comparaison par le
COMPORTEMENT (grille + smoke Playwright + endpoints sur l'app générée), jamais par diff
textuel ; PROLONGEMENT du roundtrip existant (même corpus, même gate consistency), pas un
2ᵉ mécanisme. Candidat n°1 : converter (93 %, zéro modèle IA) ; sinon reader. Bénéfice :
même sans finir les ports à la main, la boucle générer→diff→corriger-le-manifeste converge.

**② Surfaces de TRAVAIL déclarées** — les apps exigent souvent une UI dédiée complémentaire
(édition médias, correction transcription, édition texte). Germe EXISTANT : la page de
correction du transcriber (TRANSCRIBER_CORRECTION.md) = première « surface de travail »
attachée à une card, hors file. Cible : la DÉCLARER comme facette du manifeste (type de média,
primitives requises — forme d'onde, synchro texte, recadrage, diff…) + petit catalogue de
primitives d'édition vendorées que les manifestes composent. Le pipeline « cloner une app
GitHub → l'observer au Playwright → transposer » = récolte de PRIOR-ART UX (précédent
MusicVideoGenerator), pas une transposition automatique (colle spéculative).

**③ Portage wama-lab** — EN DERNIER : la valeur des apps lab EST leur UI dédiée ; ② est le
prérequis (sinon on les aplatit dans le moule card-centric ou on re-code du spécifique).
**Séquence actée : imager → pilote ① → formalisme ② → lab.**

### 18.1 Analyse critique en anticipation du monde DATA (2026-08-03, revue avec Fabien)

**Ce qui est sain** : le précédent `wama_lab/` (monde = package frère) fonctionne ; l'enveloppe
des manifestes porte déjà `world` ; les kinds `dataset`/`function`/`pipeline` existent ; tout
l'outillage d'auto-maintenance (grille, redondances, faits, gate nocturne) est world-agnostique.

**Trois problèmes structurels du couple `wama/` + `common/`** :
1. **`wama/` confond trois étages** — plomberie projet (settings/celery/urls), monde MÉDIA
   (10 apps) et plateforme TRANSVERSE (`common`, `accounts`, `model_manager`, `media_library`,
   `studio`, `filemanager`, `api`). Décision ACTÉE : monde = package frère (`wama_data/` dès son
   premier commit, avec ses commons internes) ; `wama/` = plateforme + monde média ASSUMÉ et
   documenté (déplacer 10 apps portées serait un churn injustifié).
2. **`common/` mélange les étages, et le bon critère de tri n'est PAS le sujet** mais la
   **largeur de consommation** : ≥ 2 mondes = transverse (`ffmpeg_utils` : média + lab + data) ; 1 seul monde = ça appartient au monde (`tts/` : synthesizer + avatarizer = média).
   Étiqueter les sous-packages dans `common/README.md` AVANT la naissance de data — sinon les
   briques data (dataframes, map-matching — embryons déjà dans cam_analyzer) tomberont dans
   `common/` par gravité.
3. **`wama/tool_api.py` (~2 700 l.) confond moteur et implémentations** — moteur transverse
   (`execute_tool`, sanitize, bornes) + outils du monde média. Scission au fil du code-gen F6
   (chaque app générée possède son `tool_api.py`, la racine garde moteur + registre) — pas avant.

**Le risque data** : la médiathèque (`media_library`/`UserAsset`) est médiacentrée ; sans
généralisation en *bibliothèque d'assets typés* AVANT la première app data, un `data_library`
jumeau naîtra (duplication fondatrice). **La chance data** : premier monde **manifests-first** —
corpus, roundtrip, rôle librarian et grille existent AVANT sa première ligne ; écrire le
manifeste d'abord et développer le code-gen facette par facette contre lui, au lieu de créer un
4ᵉ legacy à porter.

### 18.2 Contrôle MÉCANIQUE de la structure — `check_structure` (outil ③ de l'auto-maintenance, à créer)

> Même patron que §16.9 : règles = contrats déclarés, vocabulaire consommé depuis les registres
> (`APP_CATALOG` — jamais recopié), corpus d'acceptation = les violations VIVANTES, pragma
> d'exception motivé (`wama:structure-ok — <raison>`), scénario au stage `consistency` nocturne.

Règles sur le graphe d'imports (AST, top-level ET locaux) — **état MESURÉ au 2026-08-03** :
| Règle | Mesure | Statut |
|---|---|---|
| `common/` n'importe JAMAIS d'une app (inversion d'étage) | **12 violations** (`app_registry`, `batch_parsers`, `batch_utils`, `document_export`, `llm_utils`, `reference_comprehension`…) | backlog de triage (comme les 73 du détecteur de redondance) |
| app média → app média interdit | **0** | acquis à VERROUILLER |
| monde → monde hors glu déclarée (common/tool_api/capacités) | **1** (`cam_analyzer/utils/sam3_road_analyzer.py` → anonymizer) | à instruire : la brique SAM3 est-elle transverse ? |
| module de `common/` consommé par UNE seule app | à mesurer | informatif : candidat au rapatriement (symétrique du détecteur de redondance) |

**Acceptation** : l'outil doit retrouver les 12+1 violations ci-dessus. Ne pas le livrer sans.
Création : idéalement AVANT l'ouverture du §18 (il mesure le point de départ du déménagement)
et AVANT la première app data (il garde la frontière du monde naissant).

---

## 19. Passerelle de canaux conversationnels (Tchap/Matrix, Discord) — OUVERT le 2026-08-20

> **Domicile de ce chantier.** Le sujet n'était qu'une ligne d'horizon H3 (« Connecteurs
> conversationnels (Mattermost/Matrix) — après modèle de menace de l'assistant »). Arbitrage
> Fabien du 2026-08-20 : **ouvert**, en commençant par le maillon interne (étape 0) qui ne
> dépend d'aucun tiers. La ligne H3 renvoie désormais ici.

**Intention.** Utiliser WAMA depuis un canal de discussion — deux usages distincts :
1. **Usage utilisateur (labo)** : déposer un fichier, lancer une tâche, suivre son statut,
   récupérer la sortie — soit exactement ce que l'AI-Assistant sait déjà faire (48 outils).
2. **Usage développeur (Fabien, depuis smartphone)** : lancer des audits/cartographies à
   wama-dev-ai, et déclencher des tâches Claude Code — surface SÉPARÉE et verrouillée.

**Ordre d'attaque (arbitré 20/08).** Tchap **d'abord** (souverain, DINUM, open source),
Discord ensuite (usage réel du labo). ⚠ Ce n'est pas un compromis : Tchap étant un fork
Element/Synapse, la DINUM confirme qu'« il n'y a pas de spécificité Tchap par rapport à
Matrix ayant un impact sur la création d'un bot ». Un adaptateur écrit contre **Matrix**
se développe et se teste sur un Synapse local, puis se pointe vers Tchap sans changement
de code. Précédents à lire AVANT d'écrire : le dépôt d'exemple **officiel**
[`tchapgouv/tchap-sample-bot`](https://github.com/tchapgouv/tchap-sample-bot),
[`etalab-ia/albert-tchapbot`](https://github.com/etalab-ia/albert-tchapbot) (bot LLM DINUM),
et le REX Insee (`simplematrixbotlib` / `matrix-nio`).
⛔ **Botpress abandonné** (piste 2025 non aboutie) : l'agent EST WAMA (boucle + outils) ;
Botpress n'ajouterait qu'une orchestration concurrente à maintenir.

> ⚠ **CORRECTION 2026-08-21 (reprise de Fabien — j'avais durci à tort).** J'avais écrit que la
> démarche DINUM était un préalable « à lancer tôt ». **C'est faux si le domaine est déjà
> autorisé** : on crée alors le compte du bot **comme un compte agent ordinaire, sans aucune
> démarche**. La demande à la DINUM (`tchap@beta.gouv.fr`) ne concerne QUE les domaines non
> encore référencés. Vérification à faire une fois, sur la page d'accueil de Tchap, avec
> l'adresse `@univ-eiffel.fr`. Les universités sont éligibles (établissements publics).
>
> **Ce qui EST une vraie contrainte, en revanche** (et que je n'avais pas vu) :
> - ⚠ **la notion de « compte de service » n'existe PAS sur Tchap** → le compte du bot est
>   soumis au **renouvellement périodique par email** (~11 mois). Il faut donc une **boîte mail
>   réellement accessible** pour le bot, et un rappel calendaire : sinon le bot meurt tout seul
>   au bout d'un an. À décider avec le service info du labo (alias ou vraie boîte).
> - ⚠ **l'inscription échoue SILENCIEUSEMENT** si l'adresse n'appartient pas à un domaine
>   référencé — un échec de création de compte ne dira pas pourquoi.
> - Bac à sable : `tchap.incubateur.net` accepte les adresses `*.gouv.fr`, mais les serveurs y
>   sont **instables et réinitialisables sans préavis** — ne rien y bâtir de durable.

**Bonnes pratiques Matrix/Synapse à intégrer DÈS l'écriture** (source : doc technique DINUM) :
- **`allowed_room_ids`** — restreindre le bot à une liste de salons explicite (patron du
  `config.toml` de `tchap-sample-bot`). C'est la garde la moins chère contre un bot invité
  n'importe où ; à poser dès le premier jet, pas après.
- **Ne JAMAIS se reconnecter à chaque appel** : partager l'access token. Sinon on crée des
  centaines de sessions et un volume de données considérable.
- **Délai entre invitations** en masse → rate-limits Synapse et frontaux web.
- Les droits ne s'accordent qu'à un compte **ayant déjà rejoint** le salon (à savoir pour
  promouvoir le bot administrateur).
- Un salon peut être créé directement (`POST /_matrix/client/v3/createRoom`) — l'invitation
  n'est pas obligatoire.

### 19.0 Extraction du moteur d'assistant — ✅ LIVRÉ 2026-08-20

Préalable à tout le reste, et bénéfique seul. La boucle agentique était enfermée dans une
vue session+CSRF (`views._chat_with_ollama`) : seule la page web pouvait converser.
Extraite en brique commune — **UN cerveau, N surfaces**.

| Livrable | État |
|---|---|
| `wama/common/services/assistant_engine.py` (`run_assistant_turn`) — mécanisme déclaré | ✅ |
| `POST /api/v1/assistant/chat/` (TokenAuthentication) = porte des canaux tiers | ✅ |
| `views.py` 750 → 332 lignes ; la vue web est un CLIENT du moteur | ✅ |
| Cloud passé par `llm_chat()`/LiteLLM **avec la boucle à outils** | ✅ |
| `_sanitize_history` — un client token ne peut pas injecter de tour `system` | ✅ |
| Validation bout-en-bout au navigateur (demande un LLM) | ⏳ **Fabien** |

**Deux défauts corrigés au passage** (trouvés en lisant le code déplacé) :
- `_chat_with_claude` **supprimée, pas déplacée** : elle appelait le SDK `anthropic` en
  direct sur un modèle FIGÉ (`claude-sonnet-4-20250514`, périmé) et **sans aucun outil** —
  choisir « claude » dans le sélecteur donnait un assistant amnésique de WAMA, incapable de
  lancer une tâche. Même piège que `_route_model_by_context` : un nom figé ne casse que le
  jour où l'on s'en sert.
- L'historique client n'était pas assaini — sans conséquence en même-origine+CSRF, mais
  inacceptable derrière un token.

**Persistance de conversation DIFFÉRÉE** (décision Fabien 20/08) : la brique mémoire/RAG est
en cours de livraison dans une autre instance (`WAMA_MEMORY.md`). `history` reste fourni par
le client à chaque tour (localStorage côté web, store du bot côté canal), exactement comme
avant. La jonction se fera **sans changer la signature** de `run_assistant_turn`.

### 19.0bis Portes FICHIERS de l'API v1 — ✅ LIVRÉ 2026-08-21

Trou trouvé **en vérifiant, pas en supposant** : `/filemanager/api/…` est écrit pour un
navigateur — aucune authentification par token, et son `get_user()`
(`filemanager/views.py:22`) retombe sur l'**utilisateur anonyme partagé** hors session. Un
bot porteur d'un token s'y voyait refuser par CSRF ; et dans tout montage contournant le
CSRF, il aurait déposé les fichiers dans l'espace **anonyme** au lieu de celui du membre du
labo, **sans aucune erreur**. Sans ces portes, la passerelle ne peut ni recevoir une pièce
jointe ni rendre un résultat — préalable **dur**, pas un confort.

| Livrable | État |
|---|---|
| `POST /api/v1/files/upload/` (multipart `file`) → `{id,name,path,size}` | ✅ |
| `GET /api/v1/files/download/?path=…` | ✅ |
| `filemanager/services.py` — geste de dépôt **partagé** avec la vue web, qui l'adopte | ✅ |
| Gardes prouvées : tiers → 403, traversée `..` → 403 (3 formes), non-régression vue web | ✅ |

⚠ La garde d'accès reste `is_path_allowed()` **réutilisée telle quelle** — dupliquer une
garde de sécurité est la pire espèce de duplication : les deux copies divergent, et c'est
la moins relue qui laisse passer. Corollaire préservé : ajouter une app à `APP_CATALOG`
continue de suffire pour que ses fichiers deviennent accessibles.

### 19.1 Passerelle — cœur commun + adaptateurs 🔄

```
Tchap/Matrix ──┐
Discord ───────┤→  passerelle (1 process, N adaptateurs)  →  /api/v1/assistant/chat/
(futur…) ──────┘                                             /api/v1/tools/run/
                                                             /api/v1/files/{upload,download}/
```

Un **cœur commun** (appariement d'identité, entrée/sortie de fichiers, formatage) + un
**adaptateur mince par protocole** — jamais de logique métier dans un adaptateur.

**✅ Appariement d'identité — LIVRÉ 2026-08-21** (`wama/gateway/`, mécanisme
`gateway_identity`). Le canal **propose**, WAMA **dispose** : la personne demande la liaison
dans le canal → code court ; elle le saisit **déjà connectée à WAMA** → c'est cette session
authentifiée qui apporte la preuve, et la liaison est scellée sur SON compte. Un code volé
dans une discussion ne sert donc qu'à se lier soi-même à l'identité du voleur — aucun accès.
`account_for()` est la garde que tout adaptateur appelle avant d'agir ; elle rend `None`
pour un inconnu, ce qui doit se traduire par une invitation à se lier, **jamais** par un
traitement « en anonyme » (le piège mesuré en 19.0bis). 16 assertions vertes, scénarios
d'attaque compris (usage unique, réappropriation, pilonnage, expiration, déliaison d'autrui).
Décisions structurantes : app **hors `APP_CATALOG`** (sinon 0/72 dans la grille), **pas**
nommée `channels` (collision Django Channels), **pas** de `ScopedVisibility` (un secret ne
se partage pas — patron `UserProfile`).

**✅ Cœur + adaptateur DISCORD + `run_gateway` — LIVRÉS 2026-08-21.** Ordre inversé sur
arbitrage Fabien : **Discord avant Tchap**, parce que c'est nettement plus simple (ni
adresse mail institutionnelle à demander, ni E2EE, ni renouvellement annuel). ⚠ Réserve
consignée : Discord est **propriétaire et hors UE** — pour des données de recherche SHS
sensibles, la cible reste **Tchap** ; Discord sert le confort d'usage et le développement.

| Livrable | État |
|---|---|
| `gateway/core.py` — décide tout, ne connaît aucun protocole | ✅ |
| `gateway/adapters/discord_bot.py` — traduit, ne décide rien | ✅ |
| `manage.py run_gateway <canal>` (+ `--check` qui valide sans se connecter) | ✅ |
| 16 assertions vertes (sans réseau, sans LLM, sans GPU) | ✅ |
| Bout en bout réel (jeton Discord, serveur du labo) | ✅ **ÉPROUVÉ le 2026-08-22** |

**✅ Épreuve réelle du 2026-08-22** — bot `WAMA#3080` connecté au serveur du labo, salon
**privé** dédié, appariement bouclé (`demande` 19:16:16 → `liaison confirmée … → fabien.moreau`
19:16:31). Chaque maillon a fonctionné pour de bon : Discord livre le **contenu** du message,
l'adaptateur route vers le cœur, l'ORM écrit, la réponse repart dans le canal, et l'écran du
profil scelle la liaison sur le compte de la **session** authentifiée.

**Modèle d'usage arrêté par Fabien (2026-08-22)** — *« WAMA n'ira pas dans les canaux Discord,
le labo ne sera jamais d'accord. WAMA aura son propre canal. »* WAMA a donc **son** salon, il
n'entre pas dans ceux du labo. D'où la règle du code : dans un **salon déclaré**
(`WAMA_DISCORD_ALLOWED_CHANNELS`) il répond **sans mention** ; **partout ailleurs il est muet,
mention comprise** — la liste blanche **prime sur** la mention. Sans liste blanche il retombe
sur « répond si mentionné », que `run_gateway` signale explicitement comme n'étant PAS le
modèle retenu.

**Autres gardes** : une réponse **privée** n'est jamais publiée dans un salon (DM fermés → on
le dit, on ne replie pas) ; plafond 25 Mo en entrée ; aucune réponse aux bots ; un inconnu
obtient une invitation à se lier, **jamais** un traitement « en anonyme ».

⚠ **Trois pièges d'exécution.** `handle_message` est **bloquant** et touche l'ORM → appelé via
`asyncio.to_thread`, sinon le bot fige pour tout le monde pendant qu'une personne attend.

⚠ **L'intent `message_content` est privilégié** — et la panne n'est **PAS** celle que ce
document annonçait. Il y était écrit « le bot reçoit les événements mais `message.content`
arrive vide, panne silencieuse ». **Faux, mesuré le 22/08** : `discord.py` lève
`PrivilegedIntentsRequired` **à la connexion** et le process **meurt**, message de remède
compris. La panne est explicite et immédiate — bien plus facile à traiter que ce qu'on
craignait. Remède : portail développeur → application → **Bot** → *Privileged Gateway Intents*
→ cocher **MESSAGE CONTENT** seul (ni Presence ni Server Members : le code n'en demande aucun).

⚠ **Salon privé = le rôle du bot doit y être autorisé explicitement**, sinon il ne voit rien,
ne reçoit rien et **ne dit rien** — aucune erreur nulle part. C'est LA panne silencieuse de ce
chantier, celle contre laquelle il faut prévenir quiconque déclare un salon privé.

**✅ QR d'appariement — LIVRÉ 2026-08-31.** Le bot joint au code un QR (brique commune
`common/utils/qr.py`, mécanisme `qr` — segno, BSD-3, licence lue au texte) encodant la page
de profil avec `?link_code=<code>` ; la page PRÉREMPLIT le champ sans jamais soumettre
seule. **Zéro changement au modèle de sécurité** : le QR épargne la retape, la preuve reste
le clic « Relier » de la session authentifiée. Exige `WAMA_PUBLIC_URL` (env, cf.
`.env.example`) — sans elle, comportement historique (code seul), repli DIT en log ; segno
cassé → code seul aussi (le QR est un confort, jamais le chemin). Livré avec :
`Reply.attachments` (pièces sortantes EN MÉMOIRE, jamais écrites dans `media/` — le
symétrique du `Attachment` entrant), envoi `discord.File(BytesIO)` dans l'adaptateur,
6 tests (dont scannabilité RÉELLE : PNG décodé par OpenCV, pas « le PNG existe »).
⚠ Garde à ne jamais lever : le QR n'encode JAMAIS un jeton qui connecterait le scanneur
(QRLjacking) — `pairing_url()` porte cette doctrine. Validation ÉCRAN restante : un `!lier`
réel en DM avec `WAMA_PUBLIC_URL` posée (le harnais ne couvre pas le rendu Discord).
↳ **Trou de trajectoire découvert ET réparé dans la foulée (2026-08-31)** : le champ caché
`next` des 3 gabarits de login valait `request.path` (la page de login ELLE-MÊME) — **aucun
lien profond n'était honoré après connexion**, pour tout `@login_required`, pas que le QR ;
et le lien « S'identifier » de l'accueil (`LOGIN_URL='/'`) perdait le `?next=` reçu. Réparé
(`firstof request.GET.next …` × 3, lien d'accueil, `login_view`) avec la garde
anti-redirection ouverte (`url_has_allowed_host_and_scheme`, hôte courant seul) posée dans
le MÊME geste — ouvrir le fil `next` sans elle aurait créé un redirecteur ouvert au moment
où le QR met des liens profonds en circulation. 4 tests : `accounts/tests_login_next.py`.
↳ ⚠ **RECTIFIÉ le 31/08 (revue de session)** : il était écrit ici que la trajectoire du QR se
perdait au lien « S'identifier » de l'accueil. **Faux — mauvaise maille.** Ce lien n'est rendu
que par `clearChatHistory()` (donc après un clic « Effacer ») ; au chargement, c'est un
placeholder codé en dur qui s'affiche. La maille porteuse est la **modale de login**, ouverte
automatiquement par la présence de `?next=`, dont le champ caché faisait partie des 3 corrigés.
La réparation était juste, l'explication non — *et c'est l'explication qu'on relit.*
↳ **Jumeau traité le 31/08** : `anonymizer/views.py::reset_user_settings` est le SEUL autre
consommateur de `next` du dépôt (balayage exhaustif) et n'avait **aucune** garde. Il a reçu la
même — c'est ce que « une garde se pose avec ses jumeaux » demandait, et qui manquait au geste
initial.

**⏳ Reste :**
- **Store de conversation** — le prochain vrai morceau (voir §19.5) : l'historique est
  aujourd'hui **en mémoire du process**, perdu au redémarrage.
- **Adaptateur Matrix/Tchap** (`matrix-nio[e2e]`, E2EE obligatoire — salons chiffrés).
- **Fichiers — sortie** : les `output_url` des `get_*_status` exigent une session → le bot
  re-télécharge via `/api/v1/files/download/` (✅ existe) et re-poste en pièce jointe. Le
  câblage `Reponse.fichiers` existe ; reste à le nourrir depuis les résultats d'outil.
- **Discord** : slash commands **générées depuis `TOOL_REGISTRY`** (métadonnée-driven
  jusque dans Discord), en remplacement des commandes texte `!lier`/`!aide`.
- **Rate-limit** par identité de canal (§19.4 ④) — l'appariement borne le *qui*, pas le
  *combien*.
- ✅ **SUPERVISION — LIVRÉE le 2026-08-22.** `run_gateway discord` est désormais lancé par
  `start_wama_prod.sh` avec la garde `if ! pgrep` des autres services, arrêté avec eux en
  tête de script (donc sur du code à jour, et journaux tournés fenêtre fermée), et journalisé
  dans `logs/gateway-discord.log` (ajouté à `RUNTIME_LOGS`). **`--check` conditionne le
  lancement** : une instance sans jeton, sans `discord.py` ou avec des NOMS de salon au lieu
  d'identifiants saute le bloc **en le disant**, au lieu d'envoyer l'échec dans un fichier que
  personne ne lit. Ce qui a motivé le correctif : le crash de l'hôte du 22/08 a emporté le bot
  et rien ne l'a relancé — *une passerelle morte ne se voit pas*.
  ⚠ **`start_wama_dev.sh` ne lance PAS le bot, délibérément** : un bot répondant à de vrais
  utilisateurs depuis un code en cours d'édition n'est pas souhaitable, et deux process sur le
  même jeton traiteraient chaque message deux fois. La passerelle appartient à la prod.

> ✅ **Périmé, retiré le 22/08.** Il était écrit ici que « `confirm_link()` n'a pas encore
> d'écran ». **Faux** : l'écran existe et a servi à l'épreuve réelle — `accounts/views.py:467`
> (`channel_link_confirm`, route `profile/channel/link/`) + section « Canaux de discussion »
> de `profile.html:276`. C'est précisément cet écran qui apporte la preuve d'identité.

> ✅ **Faux bloquant retiré (vérifié le 21/08).** J'avais écrit ici que
> `POST /filemanager/api/import/`, session-only, bloquerait le parcours. **C'est faux** :
> les outils `add_to_<app>(user, file_path, …)` prennent un **chemin** et copient
> eux-mêmes le fichier dans la file. Le parcours « envoie un fichier → transcris-le »
> fonctionne donc de bout en bout sans cet endpoint, qui ne sert que le bouton d'import
> de l'UI web. Le porter en v1 reste souhaitable, ce n'est pas un préalable.

### 19.5 Store de conversation — ✅ LIVRÉ le 2026-08-21

| Livrable | État |
|---|---|
| `common/models.py` — `Conversation` + `ConversationTurn` (migration `common.0008`) | ✅ |
| `common/services/conversation_store.py` — fil, historique, enregistrement, effacement | ✅ |
| `assistant_engine.conversation_turn()` — enveloppe ; le moteur reste **sans état** | ✅ |
| La passerelle **adopte** le store — `_HISTORIQUES` (dict en mémoire) **supprimé** | ✅ |
| 16 assertions vertes, dont **3 fils distincts** pour un même utilisateur | ✅ |
| UI (liste des conversations dans le chat web) | ⏳ |

**Un fil = `(user, surface, thread_key)`** — c'est ce qui fait qu'un DM Discord, un salon
Matrix et un onglet de navigateur sont trois conversations distinctes sans que le moteur ait
à le savoir. Décisions structurantes : **3ᵉ table** et surtout pas `MemoryItem` (deux natures
⇒ deux tables — l'accident du 19/08) ; contrainte d'unicité sur le fil (sinon deux messages
simultanés du même salon scindent l'historique **en silence**) ; historique servi en ordre
**chronologique** même tronqué (à l'envers, il produit des réponses incohérentes sans que
rien ne le signale) ; `tool_steps` et modèle tracés (une conversation doit rester
**vérifiable** : qu'a-t-il lancé, avec quels arguments) ; **best-effort sur le stockage,
jamais sur la réponse**.

Reste : l'UI web (liste des fils) et la **projection** vers la mémoire (fil clos → souvenir
de provenance `assistant`, non approuvé) — la seule jonction utile entre les deux chantiers.

<details><summary>Contexte d'origine (question de Fabien du 21/08) — conservé</summary>

> ⚠ **VÉRIFIÉ le 2026-08-21, à rebours d'une impression répandue : il n'existe RIEN.** Ni
> modèle, ni table, ni migration — grep exhaustif sur `Conversation|ChatMessage|Thread|
> Dialogue|Turn|Session` et sur toutes les migrations. `wama/common/migrations/` s'arrête à
> `0007_memoryitem_ragchunk`. Le chantier mémoire a livré `MemoryItem`/`RagChunk`, qui sont
> **autre chose** : des souvenirs et des fragments RAG, écrits par `sync_memory` — et
> `PROV_ASSISTANT` (`common/models.py:629`) n'a **aucun producteur**, donc aucun tour de chat
> n'y entre. Il ne faut pas compter sur un store déjà prêt : il est **entièrement à écrire**.
>
> Ce que le chantier mémoire apporte quand même, et qu'il faut réutiliser : `ScopedVisibility`
> (gouvernance multi-utilisateur héritée), `Embedded`, `content_hash`, et le `recall()`
> hybride. ⚠ Et sa **leçon à respecter** (`WAMA_MEMORY.md:44-58`) : deux natures de données
> ⇒ deux tables. Un tour de conversation (re-jouable, purgeable, volumineux) n'a rien à faire
> dans `MemoryItem` (non re-dérivable, jamais purgé) — c'est un **3ᵉ modèle**.
>
> **La jonction utile n'est donc pas le stockage, c'est la PROJECTION** : un fil clos peut
> produire un `MemoryItem` de provenance `assistant`, **non approuvé par défaut**
> (`WAMA_MEMORY.md §6`). C'est là que les deux chantiers se rejoignent, nulle part ailleurs.

Question de Fabien (21/08) : « plusieurs conversations en parallèle, et le multi-utilisateur ? »

- **Multi-utilisateur : déjà acquis.** Chaque appel porte son `user`, les outils filtrent
  tous sur `user=`, le gating F7 s'applique. Le seul point de contention est le **GPU**
  (Ollama sérialise) → de la latence arbitrée par le gouverneur, pas un défaut.
- **Multi-conversation : inexistant.** L'historique vit en `localStorage` côté web et **en
  mémoire du process** côté passerelle. ⚠ Et la brique mémoire livrée (`common/memory/`)
  **ne le couvre pas** : c'est `remember/recall/forget` sur des souvenirs et des fragments
  RAG — deux natures de données, deux tables (la leçon du 19/08 : une purge ciblée avait
  détruit 13 évaluations parce que deux natures cohabitaient).
- **Ampleur : modérée**, précisément parce que l'extraction du §19.0 a mis le moteur au bon
  endroit — `run_assistant_turn(user, message, history=…)` prend **déjà** l'historique en
  paramètre. On ajoute `conversation_id`, on résout l'historique en base au lieu de le
  recevoir du client, et **le moteur ne change pas d'une ligne**. Le travail est dans les
  modèles + l'UI (liste de conversations).
- **La passerelle le rend nécessaire, pas seulement souhaitable** : un DM Discord et un
  salon Matrix **sont** des conversations distinctes — `core.py` a déjà la notion de `fil`.
  `_thread_key()` donne la clé naturelle, et `_HISTORIQUES` était le seul appelant à remplacer.

</details>

### 19.7 Skills de RÔLE de l'assistant + contexte du laboratoire — ✅ LIVRÉ 2026-08-21

> **Recadrage de Fabien, justifié.** J'avais conclu « rien à câbler » après avoir vérifié que
> l'enrichissement des prompts de génération se faisait déjà dans les apps
> (`process_prompt_for`). C'était répondre à côté : il ne parlait pas d'enrichir des prompts,
> mais de donner à **l'assistant** un rôle, un domaine et la connaissance du laboratoire.

⚠ **Deux natures de skills, aux contrats opposés** — les confondre coûte une passe LLM
inutile (enrichir un prompt déjà enrichi) ou un assistant sans posture :

| Famille | Destinataire | Contrat | Où |
|---|---|---|---|
| **Enrichissement** (`imager-image`…) | LLM d'enrichissement, au lancement d'une tâche | transforme un prompt, rend le prompt seul | dans l'app (`process_prompt_for`) |
| **Rôle** (`assistant-*`) | l'assistant lui-même | ne transforme rien : posture, domaine, interdits | prompt système (`assistant_engine`) |

**4 domaines déclarés** (`common/utils/assistant_skills.py::DOMAINES`) : `general`,
`science` (RAG), `design` (RAG), `dev`. Ajouter un domaine = une entrée au registre + un
fichier `assistant-<clé>.md`, **aucune vue à modifier**.

**Le contexte du laboratoire** est ce qui rend l'assistant « du labo » plutôt que générique —
sans lui, « propose-moi un logo pour le Lescot » oblige à redécrire le laboratoire à chaque
demande, ce qui vide le RAG de sa raison d'être. Trois gardes : **déclaré** (seuls les
domaines `rag=True` paient la recherche — pas de vectoriel sur « où en est ma
transcription ? ») ; **data-gated** (aucun extrait pertinent → prompt **inchangé**, jamais de
bruit injecté) ; **fail-safe** (toute panne rend `''` — le RAG est un bonus de contexte, pas
une dépendance de la conversation). Chaque extrait porte sa **référence** : un contexte sans
provenance n'est pas vérifiable.

`domain` est propagé sur `run_assistant_turn`, `conversation_turn` et
`/api/v1/assistant/chat/`. Rétro-compatible : sans domaine, rôle `general`, aucun rappel.

**⏳ Reste** : le sélecteur de domaine dans l'UI web (`domains_for_ui()` est prêt et dérivé
du registre) et, côté passerelle, la déduction du domaine depuis le canal (un salon `#dev`
→ domaine `dev`). ⚠ L'UI touche `home.html`, fichier disputé — cf. §19.6 ②.

### 19.6 ⚠ CONTRAT À DÉFENDRE entre les 3 chantiers de l'assistant (posé le 2026-08-21)

Trois instances travaillent en parallèle sur l'assistant : **mémoire & RAG**, **avatar
parlant**, **passerelle de canaux**. Cartographie croisée faite ce jour — voici ce qui doit
être tenu, avant que quiconque code la suite.

**① Le moteur reste TEXTE.** `run_assistant_turn` rend du texte et des étapes d'outil ; il ne
doit jamais porter d'audio. Le risque est concret : pour synchroniser ses visèmes, l'avatar
pourrait être tenté de faire remonter le WAV dans le tour d'assistant — et un bot Discord se
retrouverait à recevoir du base64 dont il n'a rien à faire. **La TTS reste une étape CLIENTE
post-réponse** (ce que fait déjà `home.html` : il appelle `/api/tts-kokoro/` après coup). Si
l'avatar a besoin de timings de visèmes, ils viennent d'un **endpoint TTS distinct**, jamais
du tour d'assistant. C'est la contrepartie de « UN cerveau, N surfaces » : le contrat commun
ne porte que ce qui vaut pour toutes les surfaces.

**② `home.html` va devenir disputé.** Trois chantiers veulent y écrire la même semaine :
langues (fait), toggle avatar (annoncé §17ter), liste de conversations (§19.5). **Sortir le
JS du chat vers `common/static/` avant** d'y toucher à trois, sinon les conflits seront
mécaniques et répétés.

**③ Collisions — ⚠ ce ne sont PAS que des conflits git, c'est de la PERTE DE TRAVAIL.**
`wama/common/mecanismes.py` et `wama/tool_api.py` reçoivent des *append* des trois
chantiers : conflits mécaniques, à absorber. **Mais le 2026-08-21, deux éditions ont été
purement et simplement ÉCRASÉES** — `common/models.py` (les modèles `Conversation`
disparus, fichier revenu à sa taille d'avant) puis `assistant_engine.py`
(`conversation_turn` disparue). Cause : les instances partagent **le même arbre de
travail**, donc il n'y a ni merge ni conflit — la dernière écriture gagne, en silence.

> **Protocole à tenir tant que plusieurs instances travaillent sur l'assistant :**
> 1. **Commiter immédiatement** après chaque édition d'un fichier partagé — un fichier
>    commité se récupère, un fichier écrasé non commité est perdu.
> 2. **Relire juste avant d'écrire** (l'outil d'édition le signale, mais une réécriture
>    complète du fichier, elle, ne le signale pas).
> 3. **Vérifier après coup** que l'ajout est toujours là (`grep` du symbole), surtout avant
>    de bâtir dessus : les deux pertes ci-dessus ont été détectées par l'échec du test
>    suivant, pas par l'édition elle-même.
> 4. Fichiers actuellement disputés sur ce chantier : `common/models.py`,
>    `common/services/assistant_engine.py`, `common/mecanismes.py`, `tool_api.py`.

**④ État réel au 21/08** : l'avatar n'a livré que des **vendors** (three.js, TalkingHead) et
un partial d'importmap — **aucun template ne l'inclut encore**, donc zéro collision à ce jour
(et rien dans les docs de statut : invisible pour qui les lit). La mémoire **n'a pas touché**
`assistant_engine.py` ; son seul chemin vers l'assistant est l'outil `memory_recall`, déjà
scopé — donc rien à re-garder côté canal, il fonctionne dans le bot comme sur le web.

> ⚠ **CECI N'EST PLUS VRAI depuis le 2026-08-21 (instance mémoire).** J'ai touché
> `assistant_engine.py` — une seule fonction, `_ollama_call` : elle résolvait Ollama par un repli
> **codé en dur sur `127.0.0.1`**, qui sous WSL2 désigne la VM et non l'hôte. L'assistant ne
> marchait donc que parce que `start_wama_prod.sh:44` exporte `OLLAMA_HOST` — hors du script
> (commande de gestion, cron, test, shell) c'était un 503 systématique, alors que les 8 autres
> consommateurs d'Ollama passent par la brique `common/utils/ollama_host` et marchent partout.
> Trouvé en testant l'assistant de bout en bout. **Commité immédiatement** (protocole ③) ; diff
> vérifié comme exclusivement mien avant commit, aucune édition de l'autre chantier écrasée.

### 19.2 Notifications proactives — gain rapide, indépendant du bot ✅ (2026-10-06)

`notify_job()` (`common/utils/notifications.py`) est déjà LE point unique appelé par toutes
les apps en fin de tâche. Y brancher un fan-out vers les canaux (en plus de l'email) donne
« ✅ transcription terminée + fichier » en DM — **sans toucher une seule app**, et sans
polling. À faire dès que l'appariement d'identité existe.

✅ **LIVRÉ le 2026-10-06**, sous une forme qui suit l'intention mais pas la lettre — et la
différence est mesurée (Discord, card #1047 : « vous serez notifié dès la fin », rien n'est venu) :
- **Le point unique est `notify_job_end(item, app_id, …)`**, appelé par le squelette commun :
  `notify_job` n'avait ni l'élément ni l'app, donc rien pour retrouver une conversation. Le
  propriétaire reçoit désormais AUSSI la notification dans WAMA (`notify_on` seul) — seuls les
  collaborateurs l'avaient —, et elle DÉSIGNE l'élément (`app` + `object_type` + `object_id`,
  convention `RunOutcome`).
- **Pas un fan-out en DM, le FIL D'ORIGINE** (décision de Fabien) : la passerelle poste dans la
  conversation d'où la tâche a été créée ou lancée ; une tâche lancée du web n'y poste rien.
- **Pas « sans polling »** : le worker Celery ne parle pas à Discord, seul le process de la
  passerelle le fait. Elle RELÈVE donc `common.Notification` toutes les 15 s avec un curseur
  par canal (`ChannelCursor`) — le geste même de la cloche du web, qui relève toutes les 60 s.
- **L'origine est LUE, pas déclarée** : les étapes d'outils du store de conversation
  (`tool_api.items_of_step` — création = clé uniforme `item_id`, lancement = argument principal),
  la FAMILLE (clé du `DetailRegistry`) départageant les deux modèles de l'enhancer.
- **Le résultat rejoue le geste « statut »** (`get_<famille>_status` → `_produced_files` →
  légende de l'original), et l'échange s'enregistre au fil avec cette étape RÉELLE.
Détail, contrôles et contre-épreuves : `WAMA_LLM.md §2026-10-06`.

✅ **Le FIL WEB aussi, le 2026-10-18** — Fabien : *« l'assistant ne semble pas recevoir de trigger
quand un travail est terminé, alors qu'une notification arrive. Il doit manquer un câblage
ici »*. La ligne « une tâche lancée du web n'y poste rien » parlait des CANAUX ; le fil web n'avait
lui-même aucun récit de fin. Ce qui ne dépend pas de la surface (origine, geste « statut », sorties,
enregistrement au fil) est SORTI de `gateway/core.py` dans la brique commune
`common/services/job_follow_ups.py` (mécanisme `job_follow_ups`) ; la passerelle la lit, le web
aussi. Côté web, pas de relève de plus : la cloche annonce déjà chaque relève
(`wama:notifications`) ; le chat y poste les ids des fins de tâche (`api/ai-chat/follow-ups/`), le
serveur raconte au fil celles d'une tâche lancée DEPUIS ce fil — une fois, quel que soit le nombre
d'onglets —, et le chat les affiche et les DIT (sauf pendant une réponse ou une lecture en cours).
La sortie part en lien absolu (le chat ne fait des liens que des adresses http(s)).
⚠ Délai : celui de la cloche (60 s au plus). Gardes : `tests_job_follow_ups_web` (chaîne réelle,
une fois, contre-épreuves : tâche lancée depuis sa page, depuis un canal, notification d'un autre ;
V8 : une demande par relève, un seul chat parle) — cinq contre-épreuves par mutation, rouges.

✅ **Le même jour, le récit manquait encore** — Fabien : *« j'ai eu une notification de fin de
tâche, mais l'assistant n'a pas réagi »*. Mesuré en base (flou de l'élément anonymizer 1436, lancé
du fil web) : fin à **10:49:18**, tour enregistré à **10:49:19** — un tour s'enregistre à la FIN de
sa réponse, et la recherche d'origine, héritée de la passerelle (06/10), ne lisait que les tours
ANTÉRIEURS à la notification. Une tâche plus rapide que la réponse qui la lance n'était jamais
racontée, sur aucune surface. Deux défauts, deux gestes :
1. la borne est retirée (`_assistant_turns`) ;
2. la fenêtre qui restait — une relève passée PENDANT le tour ne trouve aucun fil et ne revoit plus
   la notification — se ferme au moment déterministe : `conversation_turn`, point commun des
   surfaces, joint au tour enregistré les fins arrivées pendant lui pour ce qu'il a désigné
   (`job_follow_ups.notices_of_turn`) ; le web les raconte par `web_follow_ups` et les rend avec la
   réponse (le chat les écrit à sa suite et les dit après elle), la passerelle les ajoute à sa
   réponse avec leurs fichiers. Le geste « trouver le fil, verrouiller, une seule fois, enregistrer »
   est sorti en `job_follow_ups.tell`, lu par les deux ; la relève d'un canal ne reposte pas une fin
   déjà racontée. Gardes : `tests_job_follow_ups_web` (+4), `gateway.tests.JobFollowUpTests` (+1) —
   sept contre-épreuves par mutation, rouges.

✅ **Le cas Discord MESURÉ le même jour** (demande de Fabien). Il restait une fenêtre de double récit
sur un CANAL : la fin du tour raconte par `tell` (verrou, « déjà racontée ? », enregistrement,
puis publication), mais la relève du canal (`gateway.core._follow_up`) vérifie « déjà racontée ? »
SANS verrou, publie, et n'enregistre qu'APRÈS (`record_follow_up`). Une relève qui tombe entre
l'enregistrement du tour et celui de son récit raconte donc la fin une seconde fois.
- **Reproduit** de façon déterministe (sonde jetable, relève forcée au milieu de `tell`) : 1 récit
  par la réponse du tour + 1 par la relève.
- **Chiffré** sur la base vivante, en lecture seule : les étapes de la fenêtre durent ~20 ms en
  médiane (sonde 1 ms, fil d'origine 5 à 9 ms, statut 6 ms) ; le seul récit de fin de tour réel
  mesuré est arrivé **60 ms** après son tour. La relève passe toutes les 15 s, et il faut en plus
  que la tâche ait fini moins de 15 s avant la fin du tour (sinon une relève l'a déjà consommée
  sans fil) : **≈ 0,4 %** de ces tâches rapides. Le web n'est pas concerné (sa cloche passe par
  `web_follow_ups` → `tell`, sous verrou).
- ✅ **Corrigé, décision de Fabien** : *« on aligne la relève sur tell, mais trouve une solution
  pour détecter une panne de Discord et renvoyer le message au retour »* — et *« on réutilise, on
  ne réinvente rien »*. La relève raconte par `tell` (verrou, « déjà racontée ? », enregistrement,
  PUIS publication) ; `record_follow_up` est retiré (`REMOVAL_LEDGER` R150). Le renvoi n'ajoute
  ni table ni file d'envoi : le FIL sait ce qui a été raconté (`job_follow_ups.told_since`, la
  lecture du fil posée à côté de son écriture `record` — revérification du 18/10 : elle vivait
  d'abord dans la passerelle, qui n'y ajoute que la forme du canal, `core.told_follow_ups`),
  l'HISTORIQUE du salon ce qui a été montré — lu comme le rattrapage des messages manqués lit le
  sien (`channel.history`, `_catch_up`). Un envoi qui échoue (5xx, coupure, client non
  prêt) se DIT (`_deliver_follow_up` rend False ; un fil supprimé n'est pas « à reprendre ») et
  marque l'état de santé de la passerelle (`health['undelivered_since']`, à côté de
  `disconnected_since`) ; une réponse de tour non publiée aussi (elle portait peut-être des fins
  racontées) ; le démarrage marque sa fenêtre (un arrêt a pu tomber entre l'enregistrement et la
  publication). Dès que le client est prêt, la relève publie ce que le fil a raconté et que le
  salon ne montre pas (`_redeliver_follow_ups`), jamais ce qu'il montre, dans la borne du
  rattrapage (`CATCH_UP_MAX_AGE_S`, 1 h), puis efface la marque. Gardes : `gateway.tests` (+7 :
  relève par `tell`, ordre inverse, reconstruction du fil, envoi refusé dit, écart seul publié,
  borne, reprise au tour suivant) — sept mutations rouges. ⚠ La course elle-même (deux connexions)
  n'est pas rejouée en test : un `TransactionTestCase` viderait la base de test PARTAGÉE en
  cascade ; elle est tenue par le verrou de ligne de Postgres, pris des deux côtés par `tell`.

### 19.3 Canal DÉVELOPPEUR (surface séparée, verrouillée) ⏳

- **wama-dev-ai** n'a **aucune API** (CLI pur : `run_audit.py`, `run_codegen.py`). Wrapper
  minimal = tâche Celery en file **basse priorité** qui lance le CLI `--non-interactive` et
  reposte le rapport de `wama-dev-ai/outputs/`. Reste Phase 1 read-only : le canal déclenche
  et lit, **jamais n'applique**. ⚠ Aucune charge GPU nocturne non gouvernée (crashs hôte).
- ✅ **Claude Code sur l'abonnement — LIVRÉ le 2026-08-21** (`common/services/claude_code.py`,
  outil `ask_claude_code`, mécanisme `claude_code`). Appel réel prouvé depuis Django/WSL2.
  Trois faits mesurés qu'il faut connaître avant de s'en servir :
  - ⚠⚠ **`ANTHROPIC_API_KEY` doit être retirée de l'environnement du sous-processus.** Claude
    Code la préfère à l'abonnement ; WAMA la renseigne dans `.env` pour LiteLLM. Hériter de
    l'environnement Django aurait **facturé l'API en croyant utiliser l'abonnement**, sans
    que rien ne le signale. L'environnement est donc construit explicitement.
  - ⚠ **Le CLI est un binaire Windows** (`~/.local/bin/claude.exe`) alors que Django tourne
    dans WSL2. L'interop le lance, mais **seulement avec un environnement propre** — sinon
    l'appel meurt sur `C:/Program: No such file or directory`. Même correctif que ci-dessus.
  - ~~⚠⚠ **Coût de base élevé** : « réponds uniquement OK » → `total_cost_usd ≈ 0,99`, le
    contexte du projet étant rechargé à chaque invocation ; le coût dépend du dépôt, pas de la
    question.~~ **RÉFUTÉ par la mesure du 31/08 — voir le tableau A/B/C plus bas.** Ce chiffre
    est le cas FROID : le cache de prompt traverse les invocations, et le régime courant est
    à ~0,03 $. ⚠ Cette puce est restée vraie-en-apparence dix jours et a servi d'argument
    CONTRE l'ajout d'un fournisseur, six lignes avant qu'on l'ajoute — *barrer un fait réfuté
    ne suffit pas s'il reste lisible comme un fait ; c'est pour ça qu'il est barré ET renvoyé.*
  - Sécurité : **lecture seule par défaut** (`Read/Grep/Glob`) ; `write=True` sur intention
    explicite ; garde **appelée dans le corps de la fonction** et non dans le gating d'app (un
    outil sans app est autorisé à tous) ; **trois** vocabulaires de rôle coexistent et le
    prédicat les accepte tous (groupes `dev`/`admin`/`developpeur`, tiers `developpeur`/`admin`,
    plus `is_staff` — cf. §8.9.2bis de `PROFILES_PERMISSIONS.md`). Domicile unique du prédicat :
    `claude_code.subscription_allowed`.
- **Contexte historique — VÉRIFIÉ POSSIBLE le 2026-08-20** (ça ne l'était pas lors du premier examen) :
  depuis juin 2026, l'usage programmatique par le titulaire de l'abonnement est supporté et
  couvert par les CGU, avec un crédit mensuel dédié qui n'entame pas l'usage interactif.
  Chemin : `claude setup-token` (token OAuth) → `claude -p "…" --output-format json` en
  headless, ou le **Claude Agent SDK** Python.
  ⚠ **MCP n'est PAS le levier ici** : `claude mcp serve` n'expose que les *outils* de Claude
  Code (Bash/Read/Edit…), pas la boucle d'agent — l'orchestration resterait à notre charge.
  ⚠ Bug connu : le refresh du token OAuth échoue en non-interactif (~10-15 min) → découper en
  invocations courtes plutôt qu'une session longue.

**📏 Vérification du 2026-08-31 (question de Fabien : « le chantier est-il bouclé ? »).**
Mesuré dans le code, pas déduit — **l'abonnement est atteignable, mais par UN SEUL chemin,
et il n'est écrit NULLE PART dans l'UI** :

| Surface | Chemin réel vers l'abonnement | État |
|---|---|---|
| Menu « Provider » de l'assistant | **aucun À CE MOMENT-LÀ** — 2 entrées : `wama-dev-ai (Local/Ollama)` et `claude (Anthropic API)` | ✅ **corrigé le jour même** : 3ᵉ entrée `claude-abo`, gatée |
| Assistant web ET Discord | l'outil `ask_claude_code` (`tool_api.py:2457`), appelé par le modèle | ✅ fonctionne, gardé dev/admin |
| Passerelle Discord | `core.py` appelle `conversation_turn()` **sans provider** → défaut `wama-dev-ai` | c'est le modèle **LOCAL** qui doit décider d'appeler l'outil |

- ⚠ **Ce n'est PAS un oubli de câblage, c'est la doctrine du module** : `claude_code.py`
  énonce en tête qu'il n'est **pas un fournisseur de plus** (ni LiteLLM, ni `llm_chat`) mais
  un OUTIL qui apporte des capacités que WAMA n'a pas (lecture du dépôt, recherche).
  ⚠ **L'argument de coût qui suivait ici est TOMBÉ** : il disait qu'en faire un provider
  ferait passer tout le bavardage par un appel à ~0,99 $. La mesure du 31/08 (plus bas) le
  réfute — c'est ~0,03 $ à cache chaud. Ce qui reste vrai est le plancher de latence
  (~3,3 s), le plafond de 900 s et le bug de refresh OAuth. **La décision (b) a donc été
  prise APRÈS que son principal contre-argument soit tombé, pas malgré lui.**
- 🔴 **Le trou RÉEL était d'ERGONOMIE** : rien dans l'UI ne disait que cet outil existe, et
  en Discord c'est un **petit modèle local** qui devait choisir de l'appeler — jamais mesuré.

**✅ (a) ET (b) LIVRÉS le 2026-08-31** (arbitrage Fabien : « pourquoi pas a et b, tant que
ce n'est visible que pour admin »). Les deux, parce qu'ils ne servent pas le même geste —
(a) rend le chemin DÉTERMINISTE là où il n'y a pas de menu, (b) donne le confort d'un fil
entier sur l'abonnement là où il y en a un.

| Livrable | Où |
|---|---|
| (a) geste `!code <question>` en Discord, annoncé dans `!aide` | `gateway/core.py` |
| (b) fournisseur `claude-abo`, visible admins/devs seulement | `home.html` + `assistant_engine` |
| Prédicat d'autorisation à DOMICILE UNIQUE (3 appelants) | `claude_code.subscription_allowed` |
| Garde au PASSAGE OBLIGÉ des 3 surfaces | `run_assistant_turn` (403) |
| 15 tests (dont l'invariant écran↔garde sur 5 profils) | `common/tests/tests_claude_subscription.py`, `gateway/tests.py` |

- ⚠⚠ **Deux avertissements distincts, longtemps confondus** (question de Fabien, tranchée le
  31/08) — ils ne parlent PAS de la même chose :
  1. **facturation** : si `ANTHROPIC_API_KEY` fuit dans l'environnement du sous-processus,
     Claude Code la PRÉFÈRE → **facture réelle** au lieu de l'abonnement. C'est ce que garde
     `_environnement()` ;
  2. **consommation** : `claude -p` est SANS ÉTAT — `demander()` fait un `subprocess.run`.
     Le premier transforme « gratuit » en « payant » ; le second ne parle que de crédit.

**📏 MESURE du 2026-08-31 — le levier n'est pas celui qu'on croyait, et `--resume` est
RÉFUTÉ** (test demandé par Fabien, 3 appels identiques sur le même dépôt) :

| Appel | Coût | Cache |
|---|---|---|
| A — frais, cache **froid** | **0,538 $** | création |
| B — **`--resume A`** | **0,392 $** | *re*-création (38 457 tokens `ephemeral_1h`) |
| C — frais, cache **chaud** | **0,033 $** | **lecture** de 53 143 tokens ← 6 % de A |

- ⚠⚠ **Ce que la note du 21/08 disait est FAUX en régime courant.** Elle affirmait « le
  contexte est rechargé à chaque invocation, ~0,99 $ le message » et en tirait qu'une
  question triviale coûte presque autant qu'une vraie. **Le cache de prompt (TTL 1 h)
  traverse les invocations** : deux appels rapprochés partagent le préfixe. Le coût réel
  d'un usage conversationnel est de l'ordre de **0,03 $**, pas de 1 $.
- ⚠⚠ **`--resume` coûte PLUS qu'un appel frais à cache chaud** — douze fois plus. La session
  reprise construit un préfixe DIFFÉRENT (elle inclut le tour précédent), rate le cache
  partagé et recrée le sien. **Ne pas l'implémenter en croyant amortir** : c'était
  l'hypothèse de départ, et la mesure l'a renversée. *Une intuition d'architecture qui ne
  coûte que 3 appels à vérifier ne se consigne pas sans les avoir passés.*
- Ce qui coûte est le **premier appel après une heure de silence** : espacer les questions
  est plus cher que les enchaîner — l'inverse de l'intuition, et l'inverse de ce qu'un
  utilisateur prudent ferait spontanément.
- **Conséquences appliquées** : libellé d'UI corrigé (« ~1 $/message » → « coût variable »
  — annoncer le pire cas comme cas courant dissuadait d'un chemin peu coûteux), pied de
  réponse `!code` enrichi des deux ordres de grandeur, docstrings de `claude_code.py` et
  `_claude_code_call` réécrites. **La garde admin reste**, mais justifiée par l'ACCÈS AU
  DÉPÔT et le crédit partagé — pas par un coût par message qui n'est vrai qu'à froid.
- ⚠ **Trois vocabulaires de rôle, pas deux** (trouvé en écrivant la ligne d'UI) : aux groupes
  `dev`/`admin`/`developpeur` et aux tiers de profil s'ajoute **`is_staff`**, que `views.home`
  utilisait pour son `is_admin`. Gater l'option dessus faisait diverger l'écran de la garde
  **dans les deux sens**. D'où `abonnement_visible`, calculé par le prédicat unique — et un
  test qui verrouille l'invariant sur 5 profils au lieu de le confier à la vigilance.
- ⚠ **`claude-abo` n'a PAS les outils WAMA** : Claude Code répond avec les SIENS (lecture du
  dépôt) et rend un texte final. « Ajoute ce fichier à l'imager » n'aboutira pas par ce
  chemin — c'est le fournisseur local ou `claude` qu'il faut. Consigné dans le module.
- ✅ `.env` complété le 31/08 : `CLAUDE_CODE_OAUTH_TOKEN` et `WAMA_CLAUDE_CLI` y figuraient
  dans `.env.example` mais **pas** dans le `.env` réel (constat de Fabien) — les deux lignes
  y sont désormais, commentées, avec le rappel du piège `ANTHROPIC_API_KEY`.

### 19.4 Ce qui reste à trancher avant de coder 19.1

1. **Où tourne la passerelle** : process séparé (`supervisor`/`systemd`) ou commande de
   gestion Django longue ? (Un bot Matrix/Discord est un client à socket persistant — il ne
   vit pas dans un worker Celery.)
2. **Dépendances à installer** : `matrix-nio[e2e]` (+ `simplematrixbotlib` ?), `discord.py`.
3. **Credentials** : compte Tchap du bot (⚠ **aucune** démarche DINUM si le domaine est déjà
   autorisé — cf. correction du 21/08 ; mais il faut une **boîte mail accessible** pour le
   renouvellement ~annuel, faute de compte de service natif), application/bot Discord du labo.
4. **Modèle de menace** (la condition posée par H3, toujours valable) : un canal ouvre
   l'assistant à des messages non sollicités — l'appariement obligatoire (19.1) en est la
   première réponse, à compléter par un rate-limit et une politique de fichiers entrants.

---

## 20. Dépôt officiel de WAMA + licence du dépôt — OUVERT le 2026-08-21

> **Doc de référence du domaine : [`LICENSING.md`](../exploitation/LICENSING.md)** (politique, licences
> traversées, code vendorisé, procédure de dépôt, §7 = décisions en attente). Cette section
> ne porte que **l'état du chantier** — ne pas y recopier la politique, elle divergerait.
> La vue **mesurée** reste la page `/common/licenses/` (`common/services/license_audit.py`).

**Ce qui est LIVRÉ (2026-08-21).**
- Inventaire **complété** : 65 → **102 licences établies sur 119**, **0 « à qualifier »**
  (les 6 licences maison `other` ont été LUES et cataloguées), 30 → **2** attributions
  sans auteur.
- `LICENSE` = **AGPL-3.0**, et `COPYRIGHT` nomme titulaire et auteur. Motif : 36 poids
  ultralytics/YOLOv12 AGPL sont servis **en réseau** ; une clause « non commercial » ne peut
  pas se greffer dessus (incompatible avec l'AGPL des composants liés), et l'effet NC reste
  porté par les licences des **modèles**.
- Nouvelle famille **« Interdite (territoire) »** (rang 6, au-dessus d'`INCONNUE`) : une
  licence LUE qui ne concède aucun droit chez nous interdit plus sûrement qu'une licence
  non lue. Premier cas : `hunyuan-image-2.1`.

**Ce qui reste — dans l'ordre.**
1. 🔴 **BLOQUANT pour tout dépôt : déclarer WAMA à la valorisation UGE** (agent public,
   art. L113-9 CPI → les droits patrimoniaux sont à l'établissement). C'est elle qui
   entérine l'AGPL-3.0 et signe un éventuel dépôt. Aucun dépôt ne se fait sans ça.
2. **`imager:hunyuan-image-2.1` : retirer ou désactiver** — la Tencent Hunyuan Community
   License **exclut textuellement l'Union européenne** (« excluding the territory of the
   European Union ») : aucun droit d'usage, **même en recherche**. Décision Fabien.
   ⚠ Réflexe déjà noté au §17ter pour HunyuanVideo-Avatar — il vaut pour **tout** modèle
   Hunyuan, y compris ceux déjà installés.
   ↳ **Ampleur mesurée** : « hunyuan » apparaît dans **15 fichiers** (`imager/params.py`,
   `models.py`, `views.py`, `tasks.py`, un backend dédié `hunyuan_video_backend.py`,
   `model_registry.py`, `settings.py`, `app_registry.py`…). Ce n'est donc pas une ligne à
   supprimer : prévoir un vrai retrait (modèle catalogué + backend + choix d'UI + poids sur
   disque), ou une **désactivation déclarative** si on veut garder la trace de la raison.
3. **Dépôt HAL + Software Heritage** (gratuit, standard recherche, SWHID citable) — ajouter
   un `codemeta.json` au moment du dépôt. APP et enveloppe Soleau = compléments, pas
   substituts (LICENSING.md §5).
4. **Marque « WAMA »** : recherche d'antériorité INPI puis dépôt au nom de l'UGE si le nom
   est libre. C'est le seul levier qui protège vraiment le **nom** ; « déposer l'idée »
   n'existe pas en droit (LICENSING.md §6).
5. **Trous d'inventaire résiduels** (LICENSING.md §4) : 8 poids `yolov8*_face_plate_*.pt`
   sans origine + 2 `yolov9*-lindevs` sans auteur (rejoint « 10 poids sans origine établie »
   du §5b) ; 9 médias utilisateur sans licence (à renseigner par leur propriétaire) ;
   `leaflet-rotate.js` sans en-tête de licence.
6. **Angle mort à combler un jour** : l'audit ne voit que les 4 registres — le **code
   vendorisé** (`static/vendors/`, `common/backends/vendor/codeformer/` = **NTU S-Lab NON COMMERCIAL**)
   a dû être inventorié à la main. Le rattacher au registre `Library` le rendrait mesuré.

---

## 21. App **Writer** (ex-« Editor ») — mise en forme assistée des sorties TEXTE (vision Fabien, 2026-09-01) → élargie le 2026-09-30 : documents HTML générés et hébergés (§21.5)

> **Consigné le jour où la question s'est posée, à faire APRÈS le portage du monde Médias.**
> Ne rien modifier d'ici là : la modale de texte du reader reste en l'état (cf. §21.1).

### 21.1 Le constat qui l'a déclenchée (mesuré, 2026-09-01)

Reader produit du **markdown** (c'est un de ses formats de sortie déclarés). Sur une même
card (constat Fabien, card 43, image PNG passée à SAM3) :

| surface | ce qui s'affiche | pourquoi |
|---|---|---|
| **card** | `SAM3 frame 5500 : 8 mask(s) stopline: 0.555 …` | l'extrait passe par le **compactage markdown COMMUN** (`wama-inspector.js::_compacteTexte` : retire `#`, `**`, `-`) — écrit pour tenir dans une piste de card |
| **modale texte intégral** | `# SAM3 frame 5500…` / `- **stop_line**: 0.555` | `showTextModal` → `showPreviewModal({text_content})` → **`pre.textContent = …`** (`media-preview.js:448`) : le texte EXACT, dans un `<pre>`, sans rendu |

**Ce n'est pas un choix, c'est un effet de bord** : le compactage a été écrit pour la card, la
modale n'a jamais eu de rendu. Les deux ont chacune leur logique (extrait lisible / résultat
exact et téléchargeable) — ce qui déroute, c'est que **rien ne dit à l'utilisateur qu'il
regarde une source markdown**. Trois issues étaient possibles : (a) laisser brut, (b) RENDRE
le markdown, (c) bascule « rendu / source ». ✅ **(c) RETENUE par Fabien le 2026-09-01** — la
seule qui n'enlève rien (le brut reste accessible, donc téléchargeable et vérifiable), et le
comportement naturel d'un éditeur. Elle se livre AVEC l'éditeur, pas avant : c'est déjà la
moitié de sa surface.
⚠ Ne PAS traiter ça comme « une spécificité reader à retirer » : le compactage est déjà
COMMUN, seul le rendu de la modale manque au parc entier.

### 21.2 La vision

**Un bouton ÉDITER sur toute app qui produit du TEXTE**, dans l'esprit de la correction
assistée du Transcriber (pilote livré : `wama/transcriber/TRANSCRIBER_CORRECTION.md`,
`ROADMAP §… Transcriber`) — mais pour la MISE EN FORME, pas la correction de contenu :

- l'utilisateur met en forme son texte **dans WAMA**, puis télécharge le résultat **mis en
  forme**, au lieu de récupérer un brut à retravailler ailleurs ;
- **optionnel** : le brut reste toujours disponible, personne n'est obligé de passer par là ;
- **éditeur ASSISTÉ par IA**, avec des **profils de mise en forme automatique** (rapport,
  compte-rendu, transcription verbatim, notes…) — le pendant « forme » des profils de
  fidélité déjà actés pour la transcription (`project_transcription_fidelity_profiles`) ;
- candidat naturel à devenir une **app Editor** du monde Médias (entrée = un texte produit
  par une autre app ou déposé ; sortie = un document mis en forme), donc consommatrice des
  mêmes briques : card d'entrée, file, volet, manifeste — et productrice pour le Converter
  (md → pdf/docx, chaîne déjà en place).

### 21.3 Pistes à ÉVALUER (aucune retenue — vérifier avant de choisir)

Éditeurs riches open-source déjà répandus : **TipTap** (sur ProseMirror), **Novel**
(WYSIWYG à complétion IA), **BlockNote**, **Milkdown**, **Toast UI Editor**, **Editor.js**.

⚠ **Trois filtres AVANT toute adoption** — ils ont déjà disqualifié des briques ailleurs :
1. **licence** compatible avec le dépôt (`LICENSING.md` : WAMA est **AGPL-3.0**) — et à
   inscrire au registre `Library`, comme toute dépendance ;
2. **hors-ligne** : assets servis en LOCAL, jamais par CDN (règle du dépôt, cf.
   `reference_offline_assets_local`) ;
3. **l'IA passe par la couche LLM commune** (`WAMA_LLM.md`) — pas d'appel direct à un
   service tiers depuis l'éditeur, et pas de second routage de modèle.

### 21.4 Séquencement

**APRÈS le portage du monde Médias.** D'ici là : ne rien changer au rendu de la modale
(décision Fabien du 2026-09-01), et ne pas « corriger » l'écart card/modale en isolé — il se
tranche avec la bascule rendu/source de l'éditeur.

### 21.5 Élargissement du 2026-09-30 — générer, mettre en forme, héberger (Fabien)

> **Le besoin.** Un espace où l'utilisateur fait générer par l'IA puis héberge dans WAMA ses
> présentations HTML (l'équivalent de ses pptx/pdf), ses rapports de traitements Data/Lab, et des
> pages web posées sur des pipelines (ex. une interface de bibliographie avancée). **La plus-value
> visée** : créer et héberger une présentation HTML **en quelques minutes, avec tout le contexte** —
> données, rapports d'analyse, tout ce que WAMA produit.
> ⚠ Cette section **complète** §21.1-21.4 : la séance du 30/09 est partie sans les avoir vues
> (relevé par grep le jour même, avant consignation). Rien de 21.1-21.4 n'est contredit ; 21.3 est
> recadré ci-dessous.

#### Décisions actées (2026-09-30)

1. **Une app du monde Médias, au format standard, schéma-driven** : 1 card = 1 document
   (présentation, rapport, page). Entrée = un **prompt** + des **cards envoyées** vers l'app (une
   card de pipeline d'analyse ou de génération) + le **RAG**. ▶ = générer / régénérer.
2. **Le fond et la forme sont séparés.**
   - **Fond** = un texte structuré en sections, rédigé par l'IA, corrigeable **à la main ou par
     prompt, section par section**.
   - **Forme** = un rendu par format, produit par un LLM à partir du fond et d'une **consigne de
     forme** (« ce tableau sur deux colonnes », « style sobre »).
   - **On édite le fond, on DEMANDE la forme, on n'édite JAMAIS l'aperçu.** Aucune barre d'outils de
     mise en forme : c'est ce qui sépare l'app d'un éditeur manuel auquel on aurait ajouté de l'IA.
     L'aperçu sert à voir et à naviguer (un clic renvoie à la section du fond).
3. **HTML d'abord, en préparant les autres formats** : le format de sortie est un paramètre
   DÉCLARÉ, dont HTML est la seule valeur du premier jet. PDF tiré du HTML par le navigateur intégré
   (`common/utils/html_render.py`, Chromium) ; docx et autres ensuite, par les chaînes déjà en place
   (Pandoc au converter). **Le LLM écrit dans le langage source d'un format (HTML/CSS…), jamais un
   binaire.**
4. **Héberger est une capacité COMMUNE, pas une fonction de l'app** : tout résultat de WAMA doit
   pouvoir se publier (rapport Cam Analyzer, transcription rendue…). Publier = rendre une **version**
   visible à une adresse de l'espace personnel, avec les crans de la ligne de partage
   (`WAMA_COLLABORATION.md §2.1`). WAMA reste **interne, non exposé sur Internet** ; le choix du LLM
   (local, Albert, cloud) **suit le niveau de publication** voulu par l'utilisateur.
5. **Une page hébergée = des fichiers STATIQUES + l'API WAMA.** WAMA sert les fichiers tels quels,
   le code s'exécute dans le navigateur du visiteur ; tout ce qui est dynamique passe par l'API
   existante (`tool_api`) **avec les droits du visiteur**. **Jamais de code serveur fourni par
   l'utilisateur** (du code généré par IA exécuté sur le serveur du labo). Exemple : la page de
   bibliographie est une interface ; la recherche, le dédoublonnage et les citations sont un
   **pipeline déclaré dans WAMA** que la page appelle.
6. **Versions** : chaque prompt de modification crée une révision DANS la card, sans polluer la
   file ; l'hébergement publie une version. Conception et ordre : `WAMA_COLLABORATION.md §7.1` et
   marche **8a**, passée en tête le même jour, avec **cette app comme premier consommateur**.

#### Recadrage de §21.2 / §21.3

- §21.2 tient : un texte produit par une autre app reste une entrée possible (bascule rendu/source
  de §21.1 comprise — le rendu est l'aperçu, la source est le fond).
- §21.3 : les éditeurs riches cités (TipTap, Novel, BlockNote…) ne concernent plus que l'éditeur
  **du fond**, sans mise en forme manuelle ; leurs trois filtres restent. Cet éditeur est la brique
  commune de `WAMA_COLLABORATION.md §6.3` (texte + code, suivi par auteur, l'IA auteur comme un
  autre).
- Recoupe **§8c Phase 3** (WAMA Notebook : génération de contenu depuis un corpus) — à réconcilier,
  pas à doubler.

#### Positionnement — état de l'art relevé le 2026-09-30

L'idée existe **par morceaux**, jamais réunie :

| famille | exemples | ce qui manque au regard de §21.5 |
|---|---|---|
| suite bureautique + IA | Copilot (Word/PowerPoint), Gemini (Docs), GenOffice (Apache-2.0) | éditeur manuel complet auquel on greffe l'IA — exactement ce qu'on écarte |
| générateurs IA d'abord | Gamma, Genspark, NextDocs ; **open source** : Presenton, ALLWEONE (Apache-2.0, auto-hébergeables, Ollama/Anthropic) | ne connaissent que ce qu'on colle dans le prompt |
| un fond, N rendus | Quarto (sur Pandoc) : html, revealjs, docx, pptx, pdf, beamer | tout à la main |
| document → diapositives | PPTAgent (EMNLP 2025), Paper2Slides | démonstrateurs, sans suite |
| rapports de données statiques | Observable Framework, Evidence | le modèle « statiques + API », écrit à la main |
| pages générées hébergées | artefacts Claude, Canvas ChatGPT | le geste « générer → publier à une URL » |

Convergence notable : tous finissent en **plan d'abord** (on valide le plan, l'IA rédige).
**Ce que seul WAMA peut faire** : (a) les **sources sont des cards** — chaque section sait d'où elle
vient (traçabilité) ; (b) le document **vit avec ses données** — un run refait passe les sections
dépendantes en `STALE` (`WAMA_APP_GENERATION_ROUTE.md §10.6`) ; (c) la **forme s'hérite** comme le RAG
(université → labo → équipe → utilisateur) ; (d) les **corrections nourrissent la mémoire**. Hors de
ce terrain (un document sans source WAMA), ne pas concurrencer ces outils ; Presenton serait à
évaluer comme moteur si le besoin se confirme.

#### Inventaire mesuré le 2026-09-30 (catalogue `AIModel` en base, 151 modèles)

**Aucun modèle de mise en forme** : la forme est un RÔLE confié à un LLM.
- **Rédiger + écrire le HTML** : Anthropic (Opus 5, 4.5→4.8, Sonnet 5, Fable 5/5.1, Haiku 4.5,
  `claude_code:default`), Albert (`qwen3-coder-30b`, `gpt-oss-120b`, `deepseek-v4-flash`,
  `mistral-small-3.2`, `gemma-4-31b`), local (`qwen3.8`, `gemma4`, `qwen3.5:4b`). ⚠ **Opus 5.5
  absent du catalogue** — à ajouter.
- **Regarder le rendu** (boucle rendu → capture → critique → correction) : les modèles
  image-texte (Anthropic, `gemma-4-31b`, `mistral-small-3.2`, `ministral-3-8b` sur Albert) + la
  capture Chromium déjà en place.
- **Illustrer** : `flux-1-dev`, `stable-diffusion-xl` (téléchargés), `hunyuan-image-2.1` et
  `qwen-image-2` (rendu de texte, non téléchargés). **Texte alternatif** : `describer:blip`.
  **RAG** : `bge-m3`, `qwen3-embedding:4b`.
- **Sens inverse** (pdf/pptx existant → fond) : `reader:olmocr`, `glm-ocr`, `doctr`,
  `albert:lightonocr-2-1b` ; `PP-DocLayoutV3` et `table-transformer` au catalogue, « en attente
  d'intégration ».
- **Plus tard** : présentation commentée (synthèse vocale + `avatarizer:talkinghead`).
- **Le manque est côté LIBRAIRIES** : rien de vendorisé pour les diapositives (reveal.js), les
  graphiques, les formules (KaTeX), les diagrammes (Mermaid) — à servir en local, filtres de §21.3.
  Les schémas : SVG/Mermaid écrits par le LLM plutôt qu'un modèle d'image. Le converter n'écrit ni
  pptx ni tex aujourd'hui (`converter/utils/format_router.py:40-41`).
- Au passage : deux doublons indisponibles au catalogue (`albert:openai/gpt-oss-120b`,
  `albert:qwen3-coder-30b-A3b-instruct`) à côté de leurs équivalents valides.

#### Risques connus

- **Les formats ne sont pas isomorphes** (une diapositive ≠ une page docx) : c'est pourquoi on
  n'édite que le fond.
- **Le rendu par LLM est instable** : régénérer change la disposition. Il faudra pouvoir **figer**
  le rendu d'une section (D3).
- **Le périmètre explose vite** (présentations, docx, tex, sites, bibliographie, Nextcloud) : un
  format, un usage à la fois.

#### Étapes proposées

1. Writer HTML : fond + forme + aperçu, cards envoyées, révisions (marche 8a). 🔄 2026-10-01 :
   créé DE ZÉRO au bac à sable (`writer_01`, `WAMA_APP_GENERATION_ROUTE §10.5`) — entrées par jetons
   (`prompt`, `reference_document`), consigne par le pipeline de prompts (`kind: 'intent'`,
   `reference_field`), UN process tant que P3 n'existe pas. ✅ Glu qwen3.8 appliquée, génération
   réelle (154 s) : le terme témoin du document de référence est dans le HTML, la révision 1 porte
   `result_text` et le modèle employé. Deux défauts d'outil corrigés en route : `ctx.app_id` absent
   du contrat (référence ignorée sans message), entrées comptées comme sorties de révision.
   ✅ Le soir, sur les remarques de Fabien à la page : bouton « Ajouter à la file » (le
   générateur ne savait pas faire une card à consigne — mode attache dérivé des ports, brique
   commune `WamaApp.addToQueue`), curseur rapide/qualité au manifeste, choix « auto » tiré par le
   seul chemin de la prévision, tuiles Importer · Médiathèque · URL sur tous les ports
   (`WAMA_APP_GENERATION_ROUTE §10.5`, fin du bloc REVÉRIFICATION). Mesuré : ajout consigne +
   référence, prévision = lancement (qwen3.8), réglage resté « auto ».
   ✅ 2026-10-05 — la référence de MISE EN PAGE, par la route : le Writer a DEUX process sur le
   patron du composer (`write` → le FOND dans `draft_file` ; `layout` → le HTML depuis le fond, la
   consigne de forme et le port `reference_layout`, lu en lecture `form` —
   `reference_comprehension.comprehend_files(reading=)`), déclarés par des manifestes `pipeline`
   et `function` autorés (`manifests/app_drafts/`). Le GÉNÉRATEUR a appris les apps à plusieurs
   process et les glus sont venues du rôle `codegen` (Albert), jamais écrites à la main
   (`WAMA_APP_GENERATION_ROUTE §10.6`, position commune du 05/10, bloc ✅). Mesuré : forme reprise
   sans le texte du modèle ; changer la forme ne rejoue que `layout`, le fond reste intact.
   🔚 Ensuite (décisions) : la RÉÉDITION d'un document produit ailleurs (comme la reprise d'une
   transcription : séparer `work_result`/`attach_result` de l'évaluation, puis la page d'édition
   — chantier SURFACES), les sources cards/RAG, l'hébergement, la promotion hors du bac à sable.
   ✅ 2026-10-13 — **la PAGE D'ÉDITION du fond, par les briques** (décisions de Fabien le jour
   même) : 2ᵉ surface du chantier SURFACES (`WAMA_APP_GENERATION_ROUTE §F3b`), DÉCLARÉE dans le
   manifeste (facette `surfaces`, `WAMA_MANIFEST_SPEC`) et GÉNÉRÉE (`surfaces_gen`) — règle D5.
   Le fond corrigé s'écrit **dans le fichier média du fond** (`draft_file`), comme le texte saisi
   du synthesizer devient son fichier de travail ; `layout` passe périmé par l'empreinte de sortie
   et « Appliquer » le rejoue ; une révision « corrigé à la main » (8a) garde la trace. Annuler /
   rétablir = l'historique COMMUN (`contenteditable` + rafales, la règle du Transcriber).
   Briques neuves, universelles : `text_sections`, `html_preview`. Refus 409 sur état périmé et
   verrou doux portés au noyau, donc à TOUTES les surfaces (`WAMA_COLLABORATION §2`).
   🔚 **Étape 2, décidée le même jour** : générer des paragraphes du fond PAR PROMPT et mettre à
   jour la forme PAR PROMPT — chacun un geste qui modifie la donnée, donc un process déclaré
   (`§10.6`), glue par le rôle `codegen`. Restent aussi : la consigne de forme sur la page (elle
   s'édite à la ⚙ et périme déjà `layout`) ; le clic dans l'aperçu → section du fond (impossible
   dans un cadre isolé sans script : à reprendre avec des ancres posées par `layout`).
   🔄 2026-10-13 (soir) — **retours de Fabien sur le live, et ses décisions** : *« Si à chaque
   modification du fond il faut régénérer, ça me paraît long »* → **les deux** : *« remise en forme
   par section si la section est complètement modifiée, forme réutilisée si seulement un bout de
   phrase est modifié — la quantité de modifications définit le process d'ajustement »* ;
   *« conserver les versions »* (le temps des versions de cards communes) ; *« conserver les
   styles HTML générés pour réappliquer un style à une autre présentation »*.
   - ✅ **Versions** : fichiers de révision GARDÉS pour le Writer (20 + publiées,
     `WAMA_COLLABORATION §7.2`), brique de surface « Versions » (reprendre = geste annulable).
   - ✅ **Briques d'ajustement** (`common/utils/document_sections.py`, mécanisme
     `document_layout`) : découpage du fond (règle de `text_sections`, tenue sous V8), plan par la
     part de mots changés (`text_metrics`, seuil `PATCH_CEILING` = 0,3), remplacement de texte dans
     la forme sans modèle, remise en forme d'UNE section par le modèle de la glu, repères
     `data-wama-section`, réponse sans « ```html » et avec `<meta charset>` (deux restes soldés).
     Base = copies gardées + photo de ce que le process surveille (`ctx.previous_snapshot`,
     squelette) : la forme demandée a changé → tout refaire. Montrées au rôle `codegen` pour le
     seul process qu'une surface rejoue. La GLU `layout` se régénère PAR LE RÔLE (D5).
     ✅ **Glu appliquée le 2026-10-13 et VALIDÉE SUR LE LIVE le 2026-10-14** (card du compte de
     test, trois « Appliquer » depuis la page d'édition) : bout de phrase → texte remplacé sans
     appel (6 s), section réécrite → elle seule remise en forme (6 s), rien changé → « Fond
     inchangé », HTML identique à l'octet (3 s). Il a fallu un correctif du squelette : la photo
     du dernier rendu se perdait au passage à la file GPU (`ROUTE §10.6` 4.5, `b20a3957`).
   - ✅ **Styles** : le chemin existe sans geste neuf — « Ajouter à la médiathèque » range le
     HTML rendu (Document), le port « Modèle de mise en page » en reprend la FORME, jamais le texte
     (`reference_comprehension`, lecture `form`). ⏳ Une nature « Style de présentation » à part
     (comme « Voix ») est possible : une entrée de `media_library/natures.py`, mais une migration
     des choix de la médiathèque et ses tests figés à mettre à jour — décision de Fabien.
2. Publier (capacité commune).
3. PDF par Chromium.
4. docx / tex / pptx par Pandoc.
5. Nuages de fichiers (Nextcloud, WebDAV) : nouveau type au registre des sources externes
   (`common/external_sources.py:88-102`, aucun type « stockage » aujourd'hui) + identifiants par
   utilisateur dans le profil ; lecture ET écriture.
   🔄 **Approche DÉCIDÉE le 2026-10-10 (Fabien) : rclone sous le « dossier connecté » du
   filemanager**, pas un serveur MCP. Le raisonnement, pour ne pas le refaire :
   - **Où** : la connexion se fait au FILEMANAGER, comme un partage réseau (décision de Fabien).
     Un `MountedFolder` n'est qu'un CHEMIN (`filemanager/models.py:55-66`) : l'arbre, l'aperçu et
     « Envoyer vers » le lisent comme un dossier (`filemanager/views.py:289-345`, `:2531-2557`).
     Tout ce qui fournit un chemin s'y branche donc sans toucher l'aval.
   - **Pourquoi rclone** (MIT) : plus de 70 stockages (WebDAV avec réglage Nextcloud, SMB, SFTP,
     S3, OneDrive…) sous UNE commande ; `rclone mount` (FUSE, présent dans WSL : `/dev/fuse`,
     `fusermount3` setuid, vérifié ce jour) rend le chemin qu'attend le montage. C'est la couche
     universelle et ouverte demandée ; `davfs2` ne ferait que WebDAV. Les options de chaque
     stockage sont publiées en JSON (`rclone config providers`) : la fenêtre de connexion pourra
     s'en GÉNÉRER pour les types suivants, au lieu d'un formulaire par type.
   - **Pourquoi pas MCP pour CET usage** : MCP donne des OUTILS à un LLM (décision du 15/09) ; le
     filemanager, les workers et l'aperçu d'une vidéo de 2 Go veulent un flux d'octets, pas un appel
     d'outil rendant du JSON. **L'un n'empêche pas l'autre** (Fabien, 10/10) : un serveur MCP
     Nextcloud (fichiers, Deck, agenda, Talk — plusieurs existent, tiers) servira l'ASSISTANT le
     jour où WAMA sera client de serveurs MCP externes (§8d Phase 3 étape 5, « rien encore »).
   - **Authentification** : Nextcloud derrière SSO / FIDO2 → un **mot de passe d'application**
     (Paramètres → Sécurité → Appareils & sessions), révocable à part, saisi dans la fenêtre de
     connexion avec l'URL WebDAV (`…/remote.php/dav/files/<identifiant>/`). FIDO2 ne vaut que pour
     la connexion du navigateur. Le secret est stocké CHIFFRÉ (`secret_crypto.EncryptedTextField`)
     — ce qui permet aussi le remontage au redémarrage, que le SMB n'a pas (mot de passe jamais
     gardé, `filemanager/views.py:2498-2502`).
   - **Réseau** : Nextcloud de l'établissement joint PAR L'EXTÉRIEUR, donc par le proxy sortant
     (`http_proxy.outbound_proxies`) passé à rclone. Source déclarée au registre en type
     `stockage`, hébergement `private` — la PREMIÈRE source de ce niveau (`external_sources.py:81-86`).
   - ✅ **L'ADRESSE se pose sur la page « Sources externes »** (Fabien, 10/10 : « pourquoi pas
     les champs à compléter directement dans l'interface du registre des sources, modifiable
     uniquement par l'admin ? ») — même ligne d'instance que la clé (`InstanceApiKey.base_url`),
     même résolution (page → réglage → `.env` → défaut). Ouvert aux sources qui le DÉCLARENT
     (`address_editable`) : Nextcloud, Albert, ILaaS, OpenRouter, SearXNG. Le Nextcloud déclare
     aussi `address_required` (son défaut n'est qu'un exemple) ; posé, le filemanager le PROPOSE
     dans « Connecter un dossier ».
     **Relevé du même jour, ce que la page ne tient PAS encore** (Fabien : « à vérifier si
     d'autres sources ne l'ont pas non plus ») :
     - adresses exclues À DESSEIN : Ollama (`assistant_engine.py:492` lit l'environnement
       d'abord, `ollama_host` réécrit pour WSL2), services locaux TTS/MCP/WAMA (l'adresse est
       celle où `start_wama_prod.sh` les LANCE) ;
     - jetons lus HORS du registre, donc ni visibles ni posables sur la page : `GITHUB_TOKEN`
       (`prospector.py:1601`, `benchmark_sync.py:827` — les sources `github` n'ont pas
       d'`api_key_env`) ; le REPLI du jeton HF de `pyannote_diarizer.py:154`
       (`settings.HUGGINGFACE_TOKEN` quand l'appelant n'en passe pas — la clé d'instance posée
       sur la page n'y est pas vue) ; le repli SANS utilisateur de `claude_code.py:168`, qui lit
       l'environnement et non `external_sources.api_key` ; `WAMA_DISCORD_TOKEN` (Discord n'est
       pas une source déclarée) ;
     - réglages d'INSTANCE qui ne sont pas des sources (SMTP, liaison LDAP, domaine SMB, proxy
       sortant, `WAMA_PUBLIC_URL`) : question à part — une page de réglages d'instance ?
   - ✅ **Premier essai réel réussi (10/10, Fabien) ; puis CONNEXION PAR LE NAVIGATEUR (11/10)** —
     Fabien : *« la clé est longue, ce n'est pas très pratique […] Login Flow v2 si c'est encore
     plus pratique »*. Nextcloud Login Flow v2 (`remote_mounts.login_flow_*`, vérifié sur le nuage
     de l'établissement par le proxy) : « Se connecter par le navigateur » ouvre un onglet du nuage
     — connexion de l'établissement et FIDO2 y marchent —, l'utilisateur ACCORDE l'accès, WAMA
     reçoit un mot de passe d'application nommé « WAMA » dans *Appareils & sessions*. Le jeton
     d'interrogation reste dans la SESSION ; l'adresse d'interrogation doit être sur l'hôte du
     nuage ; l'identifiant WebDAV est demandé au serveur (OCS `cloud/user`), distinct du nom de
     connexion ; le mot de passe est RÉVOQUÉ si le montage échoue et quand le dossier est retiré.
     Le mot de passe du COMPTE n'est jamais stocké par ce chemin. La saisie identifiant + mot de
     passe reste possible (tout mot de passe que le nuage accepte en WebDAV). Le premier essai
     avait rendu un 405 : adresse non complétée (page web) — corrigé dans `5bbeb349`.
     **Essai réel par le navigateur RÉUSSI le 11/10** (Fabien : « ça marche »). Tenu par
     `filemanager/tests.py::RemoteMountTests` (15 tests, dont 5 du flux : montage avec le mot de
     passe accordé, adresse d'interrogation étrangère refusée, révocation à l'échec et au retrait,
     mot de passe SAISI jamais révoqué, flux expiré abandonné sans interroger le nuage).
   - ✅ **TOUTES LES CONNEXIONS DISTANTES PAR rclone, en TYPES DÉCLARÉS (11/10)** — Fabien :
     *« si ça permet d'aligner et de centraliser tous les types de connexions distantes, c'est
     exactement ce qu'il nous faut. Par exemple, si on veut ajouter google drive »*. Avant :
     `remote_mounts.py` passait bien par rclone, mais pour le seul WebDAV (`:webdav:` et
     `RCLONE_WEBDAV_*` en dur), et le SMB restait au montage du noyau (`sudo mount -t cifs`,
     mot de passe jamais gardé, donc jamais remonté au redémarrage).
     - `remote_mounts.STORAGE_TYPES` : `webdav`, `smb`, `drive` (Google Drive), `onedrive`
       (OneDrive / SharePoint). Un type DÉCLARE ce que l'utilisateur saisit (champs, libellés)
       et sa connexion (invité, Login Flow, OAuth) ; rclone dit le reste (`rclone config
       providers` : stockage présent dans le binaire installé, options-mots de passe à
       obscurcir, aide). Chaque option part en `RCLONE_<STOCKAGE>_<OPTION>` ; montage, secret
       chiffré, proxy, vérification avant montage, refus expliqués, remontage, révocation :
       communs. La fenêtre « Connecter un dossier » GÉNÈRE ses champs depuis le type
       (`storage_form`) au lieu de trois champs écrits à la main.
     - **SMB par rclone** : sans `sudo` ni `cifs-utils`, mot de passe gardé chiffré → remonté au
       redémarrage ; même résolution des noms courts, même domaine du site, mêmes textes de refus
       (`views._mount_refusal`, partagé avec le repli). Le montage du noyau ne reste que le REPLI
       d'une installation sans rclone. Les deux partages existants (montés par le noyau) ne
       changent pas ; un partage RE-connecté passe par rclone.
     - **Google Drive, OneDrive** (OAuth 2, code + PKCE) : l'utilisateur accorde l'accès dans un
       onglet du fournisseur, le retour (`api/mounts/oauth/callback/`) échange le code, monte et
       enregistre ; la fenêtre de WAMA interroge la même route que le Login Flow. Le jeton est
       gardé chiffré, renouvelé avant chaque remontage, révoqué au retrait (Google ; Microsoft
       n'a pas de révocation par jeton). Le CLIENT OAuth est celui de l'établissement, posé par
       un admin sur la page Sources externes (sources `google_drive`, `onedrive`, clé
       `identifiant:secret` ; adresse de retour `<WAMA>/filemanager/api/mounts/oauth/callback/`,
       `WAMA_PUBLIC_URL` d'abord) ; sans client posé, le stockage n'est pas proposé. OneDrive :
       l'adresse de la source porte le tenant de l'établissement.
     - Tests : `StorageTypeTests` (3, dont « chaque option passée à rclone existe dans le rclone
       installé »), `SmbByRcloneTests` (5), `OAuthStorageTests` (7) ; mécanisme déclaré au
       registre (`mecanismes.py`, `remote_mounts`).
     - ✅ **SMB par rclone éprouvé en réel le 12/10** (partage de l'établissement, domaine,
       sous-dossier) — un serveur SMB de test (impacket) avait déclenché l'EDR du poste et a été
       retiré : l'essai s'est fait sur un vrai partage. Le premier refus (« identifiants
       refusés ») était juste : le navigateur avait rempli l'identifiant du NUAGE, distinct de
       celui de l'annuaire du partage. D'où : les champs d'identifiants de la fenêtre ne sont plus
       jamais remplis par le navigateur (`autocomplete` `off` / `new-password`).
       ⚠ Un shell `wsl.exe` ouvert à part n'a pas l'espace de noms de montage de gunicorn : un
       montage rclone vivant y paraît absent (`mountpoint` faux, dossier vide) — lire
       `/proc/<pid du démon>/mountinfo`.
     - ⏳ Google Drive et OneDrive attendent un client OAuth déclaré chez le fournisseur
       (décision de l'établissement : des données de recherche y transiteraient).
     - **12/10, premier essai réel après relance** : un dossier retiré « réapparaissait » et
       demandait un second retrait. Mesuré aux journaux : l'accès accordé dans le navigateur, le
       montage a pris 18 s, pendant lesquelles la fenêtre disait encore « en attente » — Fabien a
       cliqué « Connecter » avec les identifiants remplis par le navigateur : DEUX
       enregistrements du même montage. Corrigé : `views._save_remote_mount` n'enregistre jamais
       deux fois le même point de montage pour un utilisateur (réponse `already`, mot de passe
       d'application en trop révoqué, jeton OAuth neuf GARDÉ à la place de l'ancien — le révoquer
       retirerait l'autorisation entière) ; la fenêtre rend les deux voies EXCLUSIVES
       (identifiants repliés sous le bouton du navigateur, « Connecter » inactif pendant une
       connexion par le navigateur). ⚠ Et un défaut de SÉCURITÉ vu au passage :
       `remote_mounts.mount` prêtait un montage déjà vivant SANS revérifier les identifiants —
       or son nom vient du serveur, de l'identifiant et du chemin, pas du compte WAMA ; un autre
       compte tapant la même adresse et le même identifiant l'obtenait avec n'importe quel mot de
       passe. Les identifiants sont désormais vérifiés avant tout prêt. +4 tests.
       Puis la VRAIE cause de la lenteur, mesurée le même soir sur le nuage réel : monté en 2 s,
       mais `subprocess.run(rclone mount --daemon, capture_output=True)` attendait la fin des
       TUBES jusqu'au délai (90 s) — WAMA répondait « échec », révoquait le mot de passe
       d'application que le démon employait, et laissait un montage fantôme ; la connexion par
       identifiants « marchait » parce qu'elle tombait sur ce montage vivant. Sortie vers
       `DEVNULL`, erreurs vers un fichier temporaire : 1,7 s, monté au retour ; un délai dépassé
       démonte. +2 tests (aucun tube ; une erreur de montage reste lue et expliquée).
   - ⏳ Ensuite : écriture des RÉSULTATS vers le nuage (bute sur `-o`, jamais une destination —
     `MEDIA_STORAGE_TIERING §8.1` cas 5) ; serveur MCP Nextcloud pour l'assistant ; un type de
     plus = une entrée de `STORAGE_TYPES` (SFTP, S3, Dropbox… tous connus de rclone).
6. Pages statiques + API WAMA.

#### Décisions ouvertes

- ~~**D1 — Nom**~~ ✅ **TRANCHÉ le 2026-10-01 (Fabien) : `Writer`.** « Editor » était trop large (un
  futur éditeur vidéo ou audio) ; *Writer* suit la famille des apps en -er et fait la paire avec
  **Reader** (lire / écrire des documents). Le §21 garde « Editor » dans son récit daté.
- **D2 — Moteur de diapositives** à vendoriser (reveal.js ou autre) — licence, hors-ligne.
- **D3 — Figer un rendu** de section : comment, et que devient-il quand le fond change ?
- **D4 — Envoyer une CARD, pas un fichier** : l'app a besoin du contexte de la card (réglages,
  modèle, résultats, provenance — `to_dict()`), pas seulement de ses fichiers ; ce que transporte
  aujourd'hui `common/services/send_to.py` est **à mesurer**, non lu le 30/09.
- ~~**D5 — Séquencement**~~ ✅ **TRANCHÉ le 2026-09-30 (Fabien)** : *« ce que je veux, c'est
  qu'on complète la route en priorité. L'app n'est pas urgente du tout. Je veux éprouver la route
  de construction avec des LLM locaux comme qwen3.8 ou souverains comme gpt-oss (Albert). Je ne
  veux pas une construction par Claude. Mais si pour y arriver tu dois partir d'un manifeste que
  tu écris à la main, ok. »* Donc :
  - **l'Editor est le CAS D'ÉPREUVE de la route** « app de zéro » (`WAMA_APP_GENERATION_ROUTE.md
    §10.3`, cible actée jadis sur le Translator) — pas une app à livrer vite ;
  - **la construction est faite par les rôles de WAMA** (`wama-dev-ai`, modèles locaux ou
    souverains), jamais écrite par Claude ; seul le **manifeste `app` de départ** peut être écrit à
    la main (c'est le trou unique de `ROUTE §10.5`) ;
  - **la marche 8a part d'abord**, seule — premier jet livré le jour même
    (`WAMA_COLLABORATION.md §7.2`), capturé en service sur le Transcriber.


---

## 22. **Profils de réglages** — généraliser le mécanisme du converter à toutes les apps

> Décision Fabien du 2026-09-01, en réponse à la question « faut-il retirer la colonne
> `ConversionJob.profile` ? ». **Non : c'est l'inverse.** Le profil n'est pas un résidu,
> c'est une fonctionnalité à ÉTENDRE — « un utilisateur enregistre un profil de réglage
> pour le réappliquer ailleurs ».

### 22.1 L'existant (mesuré le 2026-09-01)

Le **converter est la seule app** à avoir des profils nommés : modèle `ConversionProfile`
(nom, description, `media_type`, `output_format`, `options`), 3 routes
(`profile_list`/`profile_save`/`profile_delete`) et l'UI dans son volet. Les 9 autres apps
n'ont rien d'équivalent — un utilisateur qui a trouvé ses bons réglages ne peut pas les
nommer ni les rejouer.

⚠ Deux limites de l'implémentation actuelle, à ne pas reproduire en généralisant :
- la colonne `ConversionJob.profile` (FK) n'est **jamais écrite ni lue** — un job ne se
  souvient pas du profil qui l'a produit. À **câbler** en même temps (une ligne au dépôt),
  pas à supprimer ;
- le profil s'applique **côté client** (le JS remplit les champs du volet), donc il n'existe
  aucune trace serveur de « ce job vient du profil X ».

### 22.2 Ce que la généralisation exige

1. **Un modèle COMMUN** (`common/`), pas un `<App>Profile` par app : un profil = `{app,
   user, nom, description, valeurs}` où `valeurs` est validé par le SCHÉMA de l'app
   (`params.py`) — même source que la modale, le volet et les défauts. Une app n'écrit rien.
2. **Les gestes** (enregistrer / appliquer / supprimer / renommer) sont les mêmes partout →
   briques communes + endpoints conventionnels, comme la famille `batch_*`.
3. **Portée** : un profil doit pouvoir être rejoué sur une AUTRE app quand les params se
   recouvrent (le format de sortie, la qualité…) — à trancher : profil par app (simple) ou
   profil transverse filtré par le schéma cible (plus riche, plus ambigu).
4. Le job garde une **trace** du profil appliqué (la colonne existante, enfin câblée).

### 22.3 🔴 Le vrai obstacle : l'UI/UX, pas la technique (point Fabien)

*« On empile des champs, il faudra trouver une façon de présenter ça sans surcharger l'UI. »*
Ajouter un sélecteur de profil + enregistrer/supprimer sur 10 apps, dans une modale et un
volet qui portent déjà 5 à 19 champs, sature l'écran.

**Piste déjà posée, à réutiliser** : les **sections `entrée / réglages / sortie`** actées
pour les paramètres (modale ET inspecteur), miroir des sections d'INFOS de la card v3
(`CARD_DESIGN §11`). Le profil devient alors une **ligne d'en-tête de la section RÉGLAGES**
(« Profil : ⟨aucun⟩ ▾ · 💾 »), pas un bloc de plus : il qualifie la section qu'il pilote.
À dessiner avec la maquette v4 (`CARD_DESIGN §11.10`), pas à improviser app par app.

### 22.4 Séquencement

APRÈS le portage du monde Médias (le mécanisme se déclare au schéma — donc après que les 10
apps aient un schéma homogène et des réglages en colonnes, cf. §22.2 point 1).

### 22.5 ⏳ Profils de réglages — ils se gèrent DANS L'APPLICATION, comme au converter

> Demande de Fabien (2026-09-26) : des profils d'usage pour le transcriber (entretien, réunion,
> sous-titrage), *« alignés sur la notion de profils systèmes et utilisateurs pour ne pas ajouter
> un nouveau chemin de profil »*, puis *« le converter a des profils système mais on ne les a pas
> identifiés comme tel »* et *« on ne réinvente rien, on porte au commun et on fait adopter »*.
> Le même jour, la première construction a été retirée et le chantier renvoyé en session dédiée.

⚠ **CORRECTION (2026-09-27, Fabien)** — cette section disait jusqu'ici « PLAN ALIGNÉ : les
profils vivent dans la MÉDIATHÈQUE » (`SystemAsset` / `UserAsset`, une nature `settings_profile`)
et l'attribuait à une décision de Fabien. **Il ne l'a jamais prise, et la récuse** : *« je ne
pense pas que ce soit une bonne idée de mettre les réglages dans la médiathèque… Les profils de
réglages se gèrent directement dans l'application. On l'a déjà mis en place dans le
converteur. »* L'orientation médiathèque venait d'une INTENTION de juillet
(`WAMA_APP_CONVENTIONS §2bis.3`, spec migrée d'un audit, jamais implémentée) promue en décision
par l'agent qui rédigeait. *Une intention citée n'est pas une décision ; l'attribuer à quelqu'un
sans sa phrase, c'est l'inventer.*

**La cible** : le mécanisme de profils du converter — gérés dans l'app, depuis sa modale
(`profile_list` / `profile_save` / `profile_delete`, `wama/converter/views.py:882-956` ; modèle
`ConversionProfile` : utilisateur, nom, contexte `media_type`, valeurs `options` en JSON,
`wama/converter/models.py:7`) — se **porte au commun** et s'adopte app par app. Les profils
SYSTÈME restent déclarés dans le code de l'app (au converter : ses préréglages de qualité, cf.
ci-dessous).

**Ce qui a été construit puis RETIRÉ le 2026-09-26.** Un modèle commun `SettingsProfile`
(système en code, utilisateur en base) avec une fabrique de vues, adopté par le converter et le
transcriber, testé — retiré avant tout commit (table vide, appliquée puis défaite sur la base
live). Le motif invoqué, « un second registre d'instances à côté de la médiathèque », tombe avec
la correction ci-dessus : cette construction était **dans la bonne direction**, et c'est elle
que le chantier reprendra.

**Ce qui est acquis (constats, à reprendre tels quels)** :
- **Les préréglages de qualité du converter SONT ses profils système** (`quality_presets`,
  web/balanced/max par type de média) — le §23.2quater le disait (« un preset = un profil GÉNÉRAL
  commun à tous »), sans que le code les nomme ainsi. Un profil système converter se déclare
  comme une **position du curseur** `quality_intent` (le réglage déclaré au schéma), que le
  serveur étale déjà en réglages d'encodage (`_quality_spread`) ; déclarer `quality_preset`,
  `preset` ou `optimize` n'est pas possible : le schéma ne les porte pas (relevé par la garde
  ci-dessous à sa première exécution).
- ⚠ **Constat converter, non corrigé** : les préréglages audio écrivent `audio_bitrate` `160k` et
  `224k`, que le select du schéma ne propose pas (128/192/256/320) — la modale affiche « Auto » sur
  une valeur réellement posée.
- `ConversionProfile` : **0 ligne** en base live (mesuré le 2026-09-26), aucun `ConversionJob`
  ne pointe un profil — la migration de données est gratuite.
- **Garde à reprendre** : pour toute app qui déclare des profils système, chaque valeur doit être
  un réglage que SON schéma déclare, et une valeur de ses choix.
- Le geste client : une ligne « Profil ▾ · 💾 · 🗑 » en tête de la section Réglages (§22.3),
  greffée par `WamaParams.settingsModal` — profils système puis « mes profils » (et partagés) ;
  choisir écrit dans le formulaire, Enregistrer écrit sur l'élément (§23.2quater).
- Les trois profils d'usage du transcriber, en réglages qui EXISTENT : *Entretien (verbatim)* —
  pas de prétraitement, filtre de parole `auto`, diarisation, ni résumé ni cohérence ; *Réunion
  (compte rendu)* — diarisation, résumé `meeting`, cohérence ; *Sous-titrage* — filtre de parole
  `on`, sans diarisation, ni résumé ni cohérence.

**Le chantier** (session dédiée) :
1. porter au commun le mécanisme du converter : un modèle de profil utilisateur (app, nom,
   contexte, valeurs du schéma en JSON), la fabrique des trois vues (`profile_list/save/delete`,
   mêmes routes que le converter) ; les profils système déclarés par l'app dans son code ;
2. la ligne cliente « Profil ▾ · 💾 · 🗑 » greffée par `WamaParams.settingsModal` ;
3. le converter l'adopte en gardant le contrat de son JS (migration de `ConversionProfile`
   gratuite : 0 ligne), puis le transcriber avec ses trois profils ; le générateur
   (`views_gen`, bouchons `profile_*` aujourd'hui) émet la fabrique ;
4. restes connus : trace du profil appliqué (§22.2 point 4), le volet (contexte `panel`), la
   politique de cohérence par usage (`TRANSCRIBER_CORRECTION §8.4`) qui n'a pas encore de réglage.

---

## 23. 🔴 Réglages en COLONNES : oui — défauts en BASE : **pas partout** (mesuré 2026-09-01)

> Découvert en préparant l'uniformisation demandée par Fabien (« il faut donc le faire dans
> les modèles Django ? »). **La réponse est OUI pour les colonnes, NON pour les défauts** —
> et l'ignorer tuerait une fonctionnalité en silence.

### 23.1 L'état RÉEL du parc (params de contexte `item`)

| | params | en colonnes | dont `default=` | hors colonne |
|---|---|---|---|---|
| **converter** | 19 | 2 | **0** | **17** |
| **enhancer** | 9 | 5 | 5 | **4** |
| les 8 autres | 4 à 18 | toutes | quasi toutes | 0 |

8 apps sur 10 sont donc **déjà** au standard « un réglage = une colonne, avec son défaut » —
Django pose les valeurs à la création, sans aucune cascade. Les seuls déviants sont le
**converter** (17) et l'**enhancer** (4). *(La mesure « 4 apps » d'abord annoncée comptait
les JSONField ; or ceux de transcriber/anonymizer/imager portent des RÉSULTATS — segments,
classes floutées, images générées — pas des réglages. Compter le conteneur ne dit rien de
ce qu'on y range.)*

### 23.2 ⚠ Pourquoi le converter ne doit PAS recevoir de défauts en base

Le converter a une couche que les autres n'ont pas : les **préréglages de qualité**
(`utils/quality_presets.py`) — `web`/`balanced`/`max` posent `quality` 80/90/98 (image),
`video_quality` 23/20/16, `audio_bitrate` 160k/224k/320k. Et l'arbitrage est :

```python
merged = dict(defaults_du_preset)
merged.update(base_options)      # ← une option EXPLICITE écrase le preset
```

Donc le preset ne s'applique **que sur ce que l'utilisateur n'a pas réglé**. Poser
`default=85` sur une colonne `quality` rendrait TOUS les jobs explicites → **les trois
préréglages cesseraient d'agir, sans erreur ni message**. Même effet pour `video_quality`
et `audio_bitrate`.

**La forme juste** : colonnes **NULLABLES** (`NULL` = « non réglé, le preset décide »), et
les défauts restent au **SCHÉMA** — ils y servent l'AFFICHAGE (ce que la modale propose),
pas la donnée. *Une couche qui arbitre a besoin de distinguer « absent » de « posé » ; un
default en base détruit cette distinction.*

**Corollaire pour la cascade générée** (`param_schema.applicable_defaults`, livrée le
31/08) : elle pose les défauts du schéma sur l'élément naissant. C'est juste pour une app
SANS couche d'arbitrage ; **la porter au converter tuerait ses presets de la même façon**.
À conditionner explicitement le jour du portage.

### 23.2bis ⚠ RETOURNEMENT (question de Fabien, 2026-09-01) — le converter est le seul CONFORME

> *« Disons qu'on ait des paramètres par défaut, l'utilisateur applique un preset, les
> paramètres sont surchargés par le preset. Ça ne règle pas le problème ? »*

**La cascade proposée est la bonne** — et c'est la formulation juste du besoin :

```
défauts (schéma)  <  preset choisi  <  réglages EXPLICITES de l'utilisateur
```

Mais elle exige une chose que le §23.2 n'avait pas nommée : **savoir ce qui est explicite**.
Un preset ne peut agir que sur ce que l'utilisateur n'a PAS réglé — encore faut-il pouvoir
les distinguer. Mesure du 2026-09-01, défauts en colonne des 8 apps « conformes » :

| app | défauts neutres (0/''/False) | défauts **significatifs** | exemples |
|---|---|---|---|
| anonymizer | 1 | **15** | `blur_ratio=25`, `detection_threshold=0.25` |
| imager | 2 | **10** | `guidance_scale=7.5`, `num_images=1` |
| synthesizer | 0 | **7** | `language='fr'`, `pitch=1.0` |
| composer | 0 | **4** | `duration=10.0`, `model='musicgen-small'` |
| reader · describer · transcriber · avatarizer | 1-4 | **3** chacune | `max_length=500`, `output_format=TXT` |

**Conséquence, contre-intuitive et importante** : dans ces 8 apps, la valeur en base (500,
7.5, `'fr'`) est **indiscernable** d'un choix délibéré de l'utilisateur. Le jour où on leur
généralise les profils/presets (§22), **leur preset ne pourra agir sur AUCUN de ces champs**
— exactement le défaut que le §23.2 décrivait pour le converter… sauf que le converter, lui,
ne stocke QUE l'explicite (son JSON `options` ne contient rien d'autre). **C'est pour cette
raison que ses presets fonctionnent, et il est donc le seul déjà conforme au besoin.**

**La forme cible n'est donc pas une exception du converter, c'est le STANDARD** :
- la **base** ne porte que ce que l'utilisateur a POSÉ (vide/NULL = « rien posé ») ;
- les **défauts** vivent au **schéma** (une seule déclaration, qui sert l'affichage ET la
  valeur effective) ;
- le **preset** s'insère entre les deux, et peut enfin agir.

**Brique commune à écrire** — `effective_settings(item, schema, preset=None)` : défauts du
schéma ← preset ← valeurs posées. Elle remplace trois couches qui font aujourd'hui le même
travail chacune dans son coin : `converter/utils/quality_presets.resolve_options`, les
défauts en dur des backends (`options.get('gif_fps', 12)`) et `param_schema.applicable_defaults`.

**Séquencement** : le converter d'abord (portage en cours — colonnes nullables, défauts au
schéma) ; les 8 autres **avec** la généralisation des profils (§22), pas avant — leur
comportement actuel est juste tant qu'aucun preset ne s'y applique. ⚠ Ne PAS le faire à
l'occasion d'un autre chantier : déplacer un défaut de la base au schéma change ce que les
tâches lisent, et se valide app par app.

### 23.2ter ⚠ Conflit RÉVÉLÉ par le portage (2026-09-01, à trancher avec Fabien)

La cascade GÉNÉRÉE du dépôt (`_reglages_du_depot`) **stocke** les défauts applicables du
schéma sur l'élément naissant — c'est ce que Fabien a demandé le 31/08 (« les chips de la
section RÉGLAGES ne doivent pas être vides »). Or le §23.2bis établit que **stocker un
défaut le rend indiscernable d'un choix** : sur un job ainsi créé (`quality=85` posé en
base), le préréglage de qualité ne pourra plus agir. Les deux exigences sont légitimes et
se contredisent sur UN point : *où* vivent les défauts affichés.

La sortie propre existe déjà : les chips et le volet peuvent afficher les valeurs
EFFECTIVES (`effective_settings` — défauts ← preset ← posé) sans les stocker. C'est un
changement du générateur (affichage calculé au lieu de valeurs posées à la création), pas
une ligne. **En attendant : le bac à sable stocke les défauts (sans conséquence — sa tâche
est un stub, aucun preset n'y agit), l'app réelle ne les stocke pas.** À trancher avant la
marche B (le jour où la tâche générée convertit vraiment).

### 23.2quater ✅ TRANCHÉ (Fabien, 02/09) — le MODÈLE ÉVÉNEMENTIEL remplace la cascade au lancement

> Ce paragraphe REMPLACE la doctrine des §23.2bis/ter : le « retournement » du 01/09 (ne
> stocker que l'explicite pour que le preset puisse arbitrer au lancement) est CADUC — non
> parce qu'il était faux, mais parce que le modèle qui le rendait nécessaire a changé.

**Le modèle : le dernier geste écrit ; les gestes globaux écrasent.**
- **Création** → l'élément naît COMPLET : les défauts applicables du schéma sont ÉCRITS en
  base (chips pleines dès la naissance — la demande du 31/08 et les presets enfin réconciliés) ;
- **Preset** = un profil GÉNÉRAL commun à tous (un profil = propre à l'utilisateur) : le
  choisir ÉCRIT ses valeurs dans les colonnes AU CLIC — l'utilisateur VOIT l'effet réel,
  le retouche à la volée, l'enregistre en profil s'il veut. La colonne `quality_preset`
  n'est plus qu'une TRACE ; **la tâche lit les colonnes, point** ;
- **Reset « ↺ Par défaut »** (brique commune `WamaParams.applyDefaults`) : remplit le
  FORMULAIRE des défauts — c'est Enregistrer/Appliquer qui écrit (l'utilisateur voit avant
  d'écraser) ; il remet TOUT à plat, réglages individuels compris ;
- **Lot** : mêmes règles sur les filles — un geste global du lot écrase toutes les filles,
  un réglage fait sur une fille individuelle survit jusqu'au prochain geste global.

**Livré le 02/09 (converter, mesuré au navigateur)** : naissance complète · preset au clic
(update/batch_update/quick_convert étalent `preset_values`) · `api_presets` (la table
SERVIE — l'effet réel du preset s'affiche dans la modale rapide du Filemanager, décision
Fabien : montrer l'effet sans devenir un formulaire) · 💾 « enregistrer comme profil » au
VOLET (il n'existait que dans la modale d'item) · type de média POSABLE À LA MAIN au volet
(composer un profil « à froid » exigeait un fichier) · « ↺ Par défaut » dans les modales
item ET lot · tests des presets recalés au nouveau modèle.

**Restes** : readMainPanelOptions lit aussi les champs MASQUÉS (un profil image embarque
gif_fps/gif_width inertes — mineur, à filtrer par visibilité) · l'étalement du preset au
clic côté GÉNÉRÉ s'émet avec la marche B · le reset des AUTRES apps (synthesizer a le sien,
maison, volet seul) converge sur la brique avec la généralisation des profils (§22).

### 23.3 Ce qui reste à trancher

- **converter** : 17 réglages → colonnes NULLABLES + migration des valeurs de `options`
  (properties `options`/`cross_app_options` reconstruites depuis les colonnes, pour que les
  ~8 lecteurs actuels — `resolve_options`, backends, `cross_app`, `gear_data`, chips —
  continuent sans modification) ; **enhancer** : ses 4, même forme.
- **enhancer + anonymizer** : seules apps sans `user_settings` commun (table `UserSettings`
  maison) — à porter ou à assumer comme variante déclarée.
  ✅ **Soldé** — la brique est durable depuis le 2026-09-15 (`UserAppSetting`, 2ᵉ issue
  ci-dessous) ; l'anonymizer y est passé le 2026-09-27, l'**enhancer le 2026-09-29** : sa table
  n'était en fait jamais ÉCRITE (7 lignes, toutes aux défauts du modèle — aucun choix perdu), et
  le modèle, le débruitage et le blend du volet ne partaient qu'avec « Tout démarrer ». Le dépôt
  les poste désormais, l'élément naît complet et le volet est mémorisé
  (`read_panel_settings` / `save_panel_settings`). Table à retirer après rechargement
  (`REMOVAL_LEDGER R83`).
- Validation par **régénération de `converter_01`** (la facette `data` porte alors les
  colonnes, le modèle généré les a).

#### 23.3bis CARTOGRAPHIE des réglages — mesurée en base le 2026-09-09 (demande de Fabien)

> Écrite parce que la question « porter enhancer + anonymizer ? » ci-dessus s'est discutée
> **quatre échanges durant sur un malentendu de vocabulaire** : « réglages utilisateur »
> désigne QUATRE choses dans WAMA, et une seule est concernée. Fabien : « les réglages
> utilisateurs sont persistés dans les cards. De quels réglages parles-tu ? » — il avait
> raison, et la carte manquait.

| couche | où | durabilité | mesure du 09/09 |
|---|---|---|---|
| **réglages d'un ÉLÉMENT** | colonnes SQL de la table de l'app | **durable** | le plus ancien transcript (20/11/2025) porte ses 7 réglages ; converter 20 ; synthesizer garde modèle et voix depuis 12/2025 |
| **préférences d'INTERFACE** | `accounts.UserProfile` | **durable** | 14 lignes, 23 champs (langue, unités, disposition, niveaux RAG) |
| **profils NOMMÉS** | `ConversionProfile`, `AnalysisProfile` | **durable** | converter 0, cam_analyzer 4 |
| **PRÉ-REMPLISSAGE du prochain dépôt** | `common/utils/user_settings.py` → **cache Redis** | **30 jours glissants** | 430 clés en base 1 ; 60 clés examinées, **0 sans expiration**, ~28,6 j restants ; Redis en instantanés (`appendonly no`) |

**Ce que la 4ᵉ couche porte réellement** (mesuré, `grep` des appels) : converter = le dernier
format de sortie par type de média ; describer et transcriber = quelques défauts de
formulaire. **Aucun réglage de job n'y passe.** C'est un confort, pas une donnée de travail —
d'où l'invisibilité totale du défaut. L'expiration n'a AUCUN rapport avec la rétention des
médias (`UserProfile.media_retention_days`, illimitée par défaut) : elle vient d'une ligne de
juillet, justifiée par analogie avec la durée de l'historique du transcriber.

**Conséquence pour la décision ci-dessus** : l'anonymizer (15 lignes) et l'enhancer (7 lignes)
sont les seuls dont le PRÉ-REMPLISSAGE est durable. Les porter tels quels le rendrait
périssable — on alignerait vers le régime le moins bon. Trois issues, au choix de Fabien :
aligner malgré tout (homogène, sans risque pour les jobs) · **rendre la brique durable
d'abord** (un modèle commun `{user, app, nom, valeur JSON}`, unicité sur les trois premiers,
mêmes signatures publiques donc zéro ligne changée dans les 11 apps, cache conservé en lecture
devant, 430 clés recopiées) · ne rien faire (variante assumée, ce que la ligne ci-dessus
autorise déjà). ✅ **TRANCHÉ par Fabien le 2026-09-15 : la brique devient DURABLE** (« les
réglages de cards sont bien persistés en base par utilisateur, mais les réglages globaux
utilisateur ne le sont pas ») — déclenché par le choix de modèle de l'assistant, qui doit être
une préférence persistante lue par toutes les surfaces (§8d Phase 3). ⚠ Dans tous les cas, la table de l'anonymizer demande un **TRI** : 8 champs
sont des préférences d'affichage (console, aperçu, boîtes, étiquettes) dont le domicile est
`UserProfile`, 8 autres sont du pré-remplissage (floutage, seuil, précision, invite SAM3).
**Précédent utile : l'imager a fait ce portage le 2026-08-11** — sa table a été supprimée par
migration (`0016_delete_usersettings`) au profit de la brique, défauts dérivés du schéma.


### 23.4 Présentation du REDIMENSIONNEMENT (question Fabien, 02/09) — à dessiner avec la card v4

État réel : deux champs px, et le **verrou de proportion existe déjà implicitement**
(`image_backend:44` — une seule dimension posée → l'autre suit le ratio ; le help le dit
depuis le 02/09, il affichait un « 0 = inchangé » trompeur). Pistes de Fabien, à trancher
en une passe de design (PAS champ par champ) : mode **relatif/absolu** (un % se prête au
SLIDER, des px non — 1 à 8000 px au curseur est imprécis) ; **unités** → renvoi au réglage
du profil utilisateur plutôt que dupliquer ici ; verrou de proportion à EXPLICITER (une
icône 🔗 entre les deux champs qui dit le comportement déjà réel). Concerne aussi
l'enhancer (mêmes gestes). À traiter avec la maquette v4.

### 23.5 Marche B — cadrage ACTÉ (Fabien, 02/09)

- **Étages 1-2 : GO.** ① glu générée (fait) ; ② composition DÉCLARÉE des backends
  EXISTANTS (converter d'abord — manifeste : routage nature→backend, le générateur émet
  la composition) + familles à GABARIT pour les modèles connus.
  ✅ **B1 CLOS le 02/09 au soir, MESURÉ** : `backends/__init__.ROUTES` (contrat commun
  normalisé sur les 5 backends) → manifeste (`processing.backend_routes`) → corps composé
  par `tasks_gen` (import RELATIF AU PAQUET — la jumelle résout SES copies) → **la jumelle
  a CONVERTI un PNG réel en JPEG lisible (SUCCESS, `converter_01/…/output/`)**. Le critère
  de sortie de la chaîne de génération est atteint.
  ✅ **B2 entamé le même soir** : backend Table Transformer (reader) — 1er des « CONNUS »
  de la liste installs, testé SUR LES POIDS RÉELS (6/6) ; restes au commit `0fcd6f3d`
  (câblage `extract_tables`, FastWan, TTS).
- **⚠ Fonctions data ≠ backends (précision de Fabien, retenue)** : le `function_catalog`
  est le catalogue des fonctions DATA (mondes Data/Lab — le floutage peut y être une
  fonction data). Un backend d'app média N'EST PAS une entrée de ce catalogue — la voie
  « backend = fonction du catalogue » un temps envisagée est ÉCARTÉE pour le monde Médias.
  La jonction avec les nouveaux backends (3ᵉ instance) reste le CONTRAT backend commun.
- **Étage 3 (code vraiment nouveau, wama-dev-ai assisté) : EN ATTENTE** — terminer ce qui
  est connu et en place avant de se lancer sur du neuf.
- Préalable à B1 : l'arbitrage **§23.2ter** (défauts affichés vs stockés).

---

## 24. ÉTAT CONSOLIDÉ DES CHANTIERS — relevé **MESURÉ** du 2026-09-10

> **Demande de Fabien (2026-09-10)** : « retrouver tout ce qui est en cours et non terminé,
> consigner où on en est, et évaluer l'avancement par rapport à la vision ».
>
> **Méthode — ce qui distingue ce §24 d'un résumé de docs** : chaque ligne ci-dessous est soit
> une **sortie de commande**, soit une **ligne de code citée**. Aucune n'est recopiée d'un `.md`.
> C'est délibéré : sur les 5 écarts trouvés en le construisant, **5 fois la doc était en retard,
> jamais le code** — dont deux dans la boussole des Horizons, qui se déclare pourtant « fait foi ».
>
> **Ce document ne remplace rien** : `PROJECT_STATUS §REPRISE` garde le récit jour par jour,
> `docs/construction/mondes/WAMA_VISION_COMPLET.md` garde le cap. Le §24 est la **photo transversale** qui manquait.

### 24.1 La plateforme est SAINE — les 8 contrôles, mesurés le 2026-09-10

| contrôle | mesure |
|---|---|
| suite complète (WSL2, `venv_linux`) | **1997 tests, `OK`** — 0 skip (venv_win en skippe 11 : Linux est le plus strict) |
| `check_docs` | 0 cassée / 0 périmée sur 1539 — **0 cible distincte** |
| `manifest_export --check` | corpus **à jour**, 202 manifestes + 1 autoré |
| `manifest_roundtrip --all` | **10/10** apps, fidélité OK |
| `check_templates` | 0 défaut / 152 |
| `check_skills` | 0 défaut franc · 2 candidats `n=1` (13 j) · 1 promu / 14 |
| `migrate --check` | aucune migration en attente |
| `check_app_conformity` | converter **100 %** · describer **100 %** · reader 97 % · enhancer/synthesizer/transcriber 95 % · anonymizer/avatarizer/composer 94 % · imager 92 % |

Registres : **14**. Catalogue de fonctions : **62**. Studio : **10 runners sur 11** (seul
`audio_enhancer` n'en a pas). Mémoire, base réelle : **28 `MemoryItem`** (souvenirs) et
**0 `RagChunk`** (fragments) — ⚠ **deux mécanismes distincts, tous deux implémentés**, et le 0
est l'état NORMAL (voir §24.5-7 : l'entrée au RAG est un geste, pas un balayage).

### 24.2 Les DEUX chantiers actifs — partition à respecter

| # | chantier | instance | fichiers à NE PAS toucher |
|---|---|---|---|
| 1 | portage / card d'entrée v4 / **ajustement des entrées selon les modèles disponibles** | active | `manifests/codegen/*`, `tests_codegen_*`, `filemanager/views.py`, `imager/{views,tests}.py`, `CARD_DESIGN.md`, `wama-subscription.js` |
| 2 | **cam_analyzer** — filtre des garés, D.3, accéléromètre | active | `wama_lab/cam_analyzer/**` |

### 24.3 🔴 CE QUI EST BLOQUÉ SUR UN ARBITRAGE DE FABIEN (rien n'avance sans)

| # | quoi | où | pourquoi c'est bloquant |
|---|---|---|---|
| B1 | **Le filtre des garés est à REFAIRE** | `§CLÔTURE 09/09` | verdict mesuré : **55 garés reconnus sur 3887 véhicules**, dans une session où la navette est à l'arrêt **77 % du temps**. Le seuil (4 s) est **en dur**, non réglable. Ne PAS le baisser tel quel. ⚠ Le vrai verrou est en AMONT : tant que le placement est à ±20 %, aucun critère d'étalement ne sépare un garé d'un mobile lent |
| B2 | **`fields_from_params`** — « pièce 3 » | `§CLÔTURE 09/09 ①` | une fonction dont les champs dépendent de ses paramètres ne peut pas les déclarer statiquement. La suite naturelle est une capacité sur `FunctionSpec`, **mais `WAMA_APPRENTISSAGE §9` interdit explicitement d'y toucher**. **Bloque toute fonction statistique** |
| B3 | diagnostic de chaînage : **refuser** ou **AVERTIR** ? | `§CLÔTURE 09/09 ②` | `diagnostiquer_chainage()` est écrit, testé (7 gardes), rend 0 refus sur le pipeline réel — et **n'est appelé par personne**. Une ligne dans `launch_graph` suffit. La question est de POLITIQUE, pas de code (~52 refus légitimes ailleurs au catalogue) |
| B4 | **25 souvenirs `dev-ai` validables, non validés** | `§REPRISE 09→10/09` | *(Fabien : « à moi de voir plus tard » — sorti de la file, gardé ici pour mémoire)* |
| B5 | `.gitignore:31 `build/`` avale `three.module.js` | reporté depuis le 07/09 | **un clone frais n'a pas le cœur du 3D**. Trou de VERSIONNEMENT, pas de test |
| B6 | régénérer les **jumelles de bac à sable** | `§REPRISE 06/07-09` | touche leurs tables (migrate zero + recréation) — GO explicite requis |

### 24.4 ⚠ TROIS TROUS MESURÉS CE JOUR, qui n'étaient consignés NULLE PART

**① L'API de l'assistant n'est pas « incomplète par app » — elle est incomplète par VERBE et par MONDE.**
Mesuré (`tool_descriptions()`, 59 outils) : la **triade `add_to`/`start`/`get_status` est
COMPLÈTE, 11 apps sur 11, zéro trou** — `TRIAD_SPECS` la GÉNÈRE (`tool_api.py:2710`). *Le relevé
par noms de fonctions donnait l'inverse : `start_describer` n'est écrit nulle part, il est
construit à l'import.* Ce qui manque est ailleurs, et vérifié **par le sens, pas par le préfixe** :

- **verbes absents** : aucun outil ne sait **supprimer**, **annuler**, **dupliquer**, ni **régler**
  un élément, ni **récupérer un résultat produit** comme fichier. L'assistant sait créer, lancer,
  observer — il ne sait pas défaire. *(Les seules occurrences de « télécharger » concernent
  l'entrée d'un fichier dans reader et l'état de téléchargement d'un modèle.)*
- **surfaces transversales absentes** : registres, permissions, rôles, journal, RAG, tests
  nocturnes → **aucun outil** ; la mémoire est en **lecture seule** (`memory_recall` — ni
  écriture, ni approbation) ; le Studio n'a que `list`/`run`/`status` de pipelines.

⚠ Cela nuance la philosophie §5 d'`AGENTS.md` (« chaque app expose son API à l'assistant IA
(`tool_api.py`) ») : il n'y a pas un `tool_api.py` par app mais **un seul fichier central**
(`wama/tool_api.py`, 3255 lignes).

**🔴 CADRAGE FABIEN (2026-09-10) — les mondes Lab et Data attendent** (trop de chantiers
ouverts). L'API se complète **sur le monde MÉDIA et sur le TRANSVERSAL**, quick wins d'abord.

**① bis — `add_to_*` n'est PAS aligné sur l'import de l'UI. Mesuré, à deux niveaux.**
*(Question de Fabien ; elle porte, parce que le chantier 1 révise CETTE chaîne en ce moment.)*

| niveau | ce que fait l'API | ce que fait l'UI | conséquence |
|---|---|---|---|
| **ce qu'il accepte** | **8 listes d'extensions EN DUR** (`tool_api.py:42-61` et `:679` — `_MEDIA_EXTS`, `_DESCRIBER_EXTS`, `_TRANSCRIBER_EXTS`, `_READER_EXTS`, `_AUDIO_ENHANCER_EXTS`…) | ports **déclarés**, appariement entrée↔modèle | un modèle installé ou un port ajouté **ne change rien** à ce que l'API accepte |
| **comment il copie** | `copy_into_app_input` : **0 appel** dans tout `tool_api.py` ; l'anonymizer recopie le geste à la main (`shutil.copy2` + boucle anti-collision, `:159-170`) | `copy_into_app_input` (`media_paths.py:150`), adopté par les vues d'app | provenance, dédup et contrat `WamaImport` **ne remonteront jamais** à l'assistant |

⭐ **Et la brique déclarative est DÉJÀ dans le fichier** : `inspect_user_file` appelle
`capabilities_for_path()` (`common/utils/intake.py:128`), qui compose les ports depuis les
déclarations. *Un grep étroit sur `input_slots`/`accepts` rend 0 et ferait écrire « l'API ne
consulte pas les ports » — c'est faux : elle le fait, dans UN outil sur 59.* Le geste est donc
un **raccordement**, pas une construction : brancher les `add_to_*` sur ce que `inspect_user_file`
sait déjà lire. ⚠ À faire **après** le chantier 1, ou avec lui — pas contre lui.

✅ **SOLDÉ le 2026-09-28, avec le chantier 1** (étape 1 du plan card v4, demande de Fabien :
*« ajoute l'assistant à l'étape 1 […] autant rendre les choses uniformes »*). Les deux niveaux :
- **ce qu'il accepte** : les listes d'extensions en dur sont RETIRÉES ; les outils lisent le
  catalogue (`accepts_file`, `category_of_path`) — l'anonymizer, le même filtre que sa vue ;
- **comment il copie** : il ne copie plus — `add_to_*` passe par `media_paths.designate`, la
  brique des vues d'upload (`received_inputs`) : un fichier du sas est POINTÉ, avec sa provenance.
- 🔴 **Et un trou de sécurité fermé au passage** : `_resolve_user_path` ne vérifiait que le
  confinement dans `MEDIA_ROOT`, où `users/<autre>/…` se trouve — l'assistant recopiait ou lisait
  (`inspect_user_file`, `look_at_image`) le fichier d'un AUTRE utilisateur. Garde :
  `media_paths.readable_by`. Contrat générique `tests_tool_api_designation` (les outils à
  `file_path` sont trouvés, pas nommés), contre-épreuve 2 mutations / 2 rouges.

**① ter — ce que les TESTS disent qu'il manque** (suggestion de Fabien : les scénarios
utilisateurs guident l'API). `run_nightly_tests --list` catalogue **14 familles de gestes ×
17 apps**. Recoupées avec les 59 outils :

| geste utilisateur (×17 apps) | couvert par l'API ? |
|---|---|
| `import` | ✅ `add_to_*` — mais désaligné (① bis) |
| `processing` / `batch_processing` | ✅ `start_*` + `get_*_status` |
| `batch_import` · `url_import` · `folder_import` · `send_to` | ❌ |
| `settings` · `duplicate_delete` · `clear_all` | ❌ |
| `queue_search` · `queue_dnd` · `inspector_actions` | ❌ |
| `batch_actions` · `batch_extract` | ❌ |

**2 familles couvertes sur 14.** C'est la mesure la plus parlante du trou, et elle ne doit rien
à une opinion : ce sont les gestes que le dépôt teste déjà comme étant ceux de l'utilisateur.

**① quater — ordre proposé (quick wins d'abord, à valider)**

1. ~~**Lectures transversales**~~ — ✅ **FAIT le 2026-09-11**, en deux incréments. **59 → 64
   outils**, **20 gardes** (`common/tests/tests_tool_api_lectures.py`) :
   `list_my_items` + `get_item_detail` (décision `WAMA_MEMORY §9ter`, jalon 12 — suivie telle
   quelle, ses 2 réserves traitées) · `list_registries` (les 14 registres avec leur `nature`) ·
   `get_my_access` (tier, rôles, apps permises **ET refusées** — un assistant qui ignore le
   refus ne peut qu'omettre une app en silence) · `list_my_memories`.
   🔴 **La garde qui compte** : `list_my_memories` n'expose JAMAIS `en_attente=True` — cette
   branche n'est **pas scopée** (`memory/store.py:686`, staff seulement côté vue) et rendrait
   des souvenirs d'autrui, non approuvés. Le test l'atteste, et **refuse d'être vacueux**
   (il échoue si la file de revue est vide, donc s'il n'exclut rien).
2. ⏸ **`url_import` / `folder_import` / `batch_import`** — les briques existent et sont testées
   par 17 scénarios chacune ; l'API n'en expose aucune. 🔴 **EN ATTENTE, cadrage Fabien du
   2026-09-11** : c'est le périmètre `import / connexion / montage` qu'une instance refond
   (domicile par utilisateur, en vue du chiffrement des dossiers). Ne pas l'ouvrir contre elle.
3. ~~**`preview` d'un job en cours**~~ — ✅ **FAIT le 2026-09-11** : `get_item_preview(app, pk,
   side)` avec `input` / `output` / **`during`**. `sides.has_during` dit qu'un job en cours a
   déjà quelque chose à montrer — « où en est mon job » se répond donc avec la sortie PARTIELLE
   réelle, pas un pourcentage. Réutilise `unified_preview` en entier (mêmes adapters, même
   permission). 🔴 Sa garde : les adapters appellent `build_absolute_uri()`, donc la requête
   synthétique fabrique un FAUX hôte — s'il fuitait, l'assistant proposerait un lien mort
   présenté comme valide. Deux tests, dont un qui ne peut pas être vacueux.
4. ~~**Verbes de cycle**~~ — ✅ **FAIT le 2026-09-11** : `delete_item`, `duplicate_item`,
   `clear_my_queue` (qui REFUSE sans `confirm=true` et compte avant de vider). Ils appellent la
   **vue de l'app** (route lue par `route_variants`), car les `reset_fields`/`clear_fields` sont
   spécifiques — les recopier eût créé une 2ᵉ vérité.
   🔴🔴 **Leur garde n'était portée par RIEN** : transverses par leur NOM, ils échappent à
   `tool_accessible` (app_id → None) **et**, passant par une requête synthétique, à
   `AppAccessMiddleware`. `_refus_app()` est donc écrit dans leur corps, et le test vérifie
   D'ABORD que les deux couches sont inertes — sinon il croirait tester la garde.
   ❌ **`settings` retiré de cette étape** : la route `update` n'existe que sur **2 apps sur 15**
   (converter + jumelle). C'est un trou côté APPS, pas côté API — rien construit dessus plutôt
   qu'une surface à moitié couverte qui mentirait sur ce qu'elle offre.
5. **Raccordement de `add_to_*`** (① bis) — ⏸ même attente que le point 2.
6. **Lancer les tests nocturnes** depuis l'assistant (`run_nightly_tests` est une commande de
   gestion ; ⚠ scénarios GPU exclus par défaut — ne pas ouvrir cette porte sans le gouverneur).

**① quinquies — le geste MÉDIATHÈQUE, hors de cette file (2026-09-11/12)**

Décision Fabien : *« on rend commun et on porte sur les apps de façon universelle ; c'est à
ajouter dans les "…", pas comme bouton d'action principal »*. Mesuré avant de coder : le geste
**existait déjà, écrit TROIS fois**, et **8 apps sur 10 ne l'avaient pas du tout**
(`composer/views.py:669`, sa jumelle, `synthesizer/views.py:897`).

- ✅ **Brique commune** `media_library/services.py::export_item_to_library` + une route unique,
  générique par construction (résultat lu au schéma canonique) — 20 gardes.
  ⭐ **Elle ne construit AUCUN chemin** : `upload_to` décide du domicile, donc elle **suivra** la
  refonte des dossiers utilisateur (chiffrement) au lieu de la figer. C'est précisément ce que
  les 3 copies font mal. Un test l'atteste ; mécanisme `library_export` au registre (138 → 139).
- ✅ **`add_to_media_library` devient TRANSVERSE**. Il était gaté sur `media_library` du seul fait
  de son nom. ⚠ Mesuré : la politique est `roles: []`, donc le gate était *permissif en pratique*
  — le défaut n'était pas un refus d'aujourd'hui, c'est que `AppAccessPolicy` est **éditable en
  base** : restreindre la médiathèque aurait cassé **en silence** un geste universel.
- ✅ **Deux entrées dans le « … »** (`CARD_DESIGN §2bis`) : « Ajouter à la médiathèque… » avec
  sous-menu des **rôles** rendus par le serveur (un `.mp3` peut être voix/musique/bruitage — le
  rôle est FOURNI, jamais deviné), et **« Ajouter au RAG »**, qui n'était que dans l'inspecteur.
  **Smoke navigateur** : les 4 entrées rendues, sous-menu `[Voix, Musique, Bruitage]`, **0 erreur
  console**, fixture nettoyée.
- ✅ **Dépréciation FAITE le 2026-09-12** — et le relevé du 11/09 qui annonçait « 3 copies »
  était **faux d'un tiers** : `synthesizer/views.py:897` n'est PAS le même geste, c'est
  l'**upload d'une voix personnalisée** (`request.FILES`, nom requis, extensions de voix), qui
  ne part d'aucun résultat d'app. *Compter une ressemblance de surface comme une duplication est
  la même faute que conclure d'un nom de route.* Les **2** vraies copies (composer + sa jumelle)
  délèguent ; leurs routes et leur contrat de réponse `{success}` sont **conservés** (leur front
  les consomme — on déprécie l'implémentation, pas la porte), et ce qui leur appartient reste
  chez elles : le rôle dérivé du `generation_type`, et le refus du double export.
  **Un gardien AST** refuse qu'une vue d'app recopie le geste — contre-épreuve faite sur la
  version d'avant : il accuse bien la ligne 688 qui vient d'être retirée.
- ✅ **3ᵉ surface** : `add_item_to_media_library` (assistant). Menu « … » · route d'app · outil —
  une seule brique, donc les mêmes refus partout.

**② Le Data Analyzer est DÉCIDÉ depuis le 2026-08-25 et n'existe pas.**
`WAMA_DATA_WORLD §11.8` le tranche (« l'app-file du monde Data, hérite de la file Médias »).
Mesure : **aucun fichier, aucun dossier** ne porte ce nom dans le dépôt. C'est le **point
d'entrée du monde Data** que Fabien nomme — donc le chantier qui débloque l'usage réel de tout
le socle Data déjà construit.

**③ Trois critères rouges reviennent sur PRESQUE TOUTES les apps** — ce sont eux, le reste du
portage, et non « 5 apps à porter » :

| critère | facette | ce qu'il dit | portée |
|---|---|---|---|
| `backend_routes` | F5 | paquet `backends/` présent **sans `ROUTES`** → `tasks_gen` laisse le stub `NotImplementedError` | ~toutes |
| `task_skeleton` | F5 | tâche d'item **hand-rolled** — gardes/progress/ETA réécrits au lieu de `run_item_task` | ~toutes |
| `detail_spec` / `triad_specs` | F3/F6 | détail en adapter CODE seul, **non projetable au manifeste** | ~toutes (🔶) |

### 24.5 Les chantiers OUVERTS, par ordre de dépendance (rien d'inventé : chaque ligne a sa source)

1. **Chaîne d'entrée** (chantier 1) — câblage `WamaImport` app par app ; port `live` encore
   littéral ; **provenance en base** (décidée « OUI, PROPREMENT » le 07/09 : 1ʳᵉ relation
   générique de WAMA, `grep` = zéro `GenericForeignKey` aujourd'hui) ; `-r` puis `-o` de lot
   (décision du 07/09 : **`-r` est le plus grave** — un lot de clonage de voix est impossible
   *en silence*) ; 6 lignes dans `RETENTION_MODELS` (D9).
2. **cam_analyzer** (chantier 2) — B1 puis bascules D.3, accéléromètre (MESURER l'axe avant),
   réétalonner σ, `ego_rotation`/`osm_control_nodes`, #7 bâtiments IGN, `locate_anything`.
3. **Studio** — exécuter un pipeline de fonctions **depuis le bouton ▶** (jamais fait) ;
   **marche E** : recharger un manifeste `pipeline` DANS le canvas (l'export existe, l'import
   non) ; batch orchestré et fan-out parallèle. ⚠ Aucun harnais JS n'existe : la seule
   attestation du JS Studio est le smoke navigateur. **+ (15/09)** moteur commun et card = instance
   de pipeline (`WAMA_APP_GENERATION_ROUTE.md §10.6`, marches P2-P5).
4. **Monde Data** — **Data Analyzer** (24.4② ; décision du 15/09 : app-file entrant dans
   `APP_CATALOG`, monde `data`) ; D16/D18/D19 ; audit SQLite→HDF5 (🔴 bloque `.wds`) ;
   2ᵉ manifeste + A2/A3/A4 du plan d'expérience.
5. **API — monde MÉDIA + TRANSVERSAL** (24.4① *quater*), dans cet ordre. ⚠ **Les mondes Lab et
   Data n'en font PAS partie** (cadrage Fabien 2026-09-10) : ils viendront après, quand il y
   aura moins de chantiers ouverts. Ne pas les rouvrir en croyant « compléter l'API ».
6. **MCP server** — 🔄 **OUVERT le 2026-09-15** (`§8d Phase 3` : étapes 1-2 livrées et mesurées,
   3-5 ⏳). Cadre `§16` appliqué (réutiliser MCP, outils dev/admin en **process séparé**).
   ~~Trancher d'abord la contradiction `AGENTS.md` / `§8d`~~ — **LEVÉE par Fabien le 15/09** :
   wama-dev-ai est en phase 4, seul MCP restait ; MCP = OUTILS, la sélection reste la brique.
   Reste valable : porter les chaînes de repli **RAM-aware** avant que `select_model_for_role`
   adopte la brique VRAM-aware, sinon on PERD une capacité.
7. **Mémoire & RAG — DEUX mécanismes, tous DEUX implémentés** (rectification Fabien 2026-09-10).
   ⚠ **Ne pas relire « 0 `RagChunk` » comme un manque** : l'entrée au RAG est un **GESTE de
   l'utilisateur, jamais un balayage** (`memory/index.py:2`). Une 1ʳᵉ version balayait les sorties
   de toutes les apps — **939 fragments écrits sans que personne n'ait rien demandé** — et a été
   PURGÉE le jour même sur objection de Fabien, sans perte (un `RagChunk` est re-dérivable par
   construction). Une base à 0 fragment est donc l'état NORMAL d'un compte qui n'a pas fait le
   geste. *Le trou serait un balayage automatique, pas son absence.*
   Restent : bascule d'embedder + réindex ; jalon 12.
8. **i18n** — `§10.A` ; ⚠ **fuite constatée le 09/09** : le générateur de gabarits émet du
   français **en dur, sans marquage de traduction** — toute app générée naîtra non traduisible.
9. **Dette nommée, non enterrée** — `folder_input_id` sur 3 cards (pending rendu explicitement
   par la session du 09/09) ; 6 gabarits incluent encore `wama-inspector-autofill.css` en local ;
   `start_analysis`/`start_sam3_only` servies sans appelant front ; geste 10 (progression qui
   AVANCE) ; scénarios GPU écrits et EN ATTENTE de la rampe CUDA.

### 24.6 Avancement par rapport à la VISION — la DISTRIBUTION, pas un pourcentage

`docs/construction/mondes/WAMA_VISION_COMPLET.md` porte déjà un marquage d'état par section. Relevé automatiquement
sur ses **50 sections** (2026-09-10) :

| état | sections | lecture |
|---|---|---|
| 📜 doctrine seule | 10 | principes — rien à « livrer » |
| ✅ livré | 6 | fermé |
| ✅🔄 livré + extension en cours | 9 | le socle tient, la couverture grandit |
| ✅⏳ livré + reste non commencé | 6 | |
| 🔄 en cours | 7 | |
| 🔄⏳ | 1 | |
| ⏳ non commencé | 10 | dont Story Director, SI labo, gouvernance des IA — **gatés volontairement** |
| (aucun marqueur) | 1 | §2.1, descriptif |

Sur **39 sections « à construire »** (hors doctrine pure) : **21 ont un socle livré** (6 + 9 + 6),
**8 sont en cours**, **10 ne sont pas commencées**.

🔴 **Pourquoi PAS un pourcentage unique.** Passer de cette distribution à « WAMA est à N % »
demande de **pondérer** un ✅🔄 contre un 🔄 — et cette pondération est une **DÉCISION**, pas une
mesure. Avec des poids plausibles on obtient de 45 % à 60 % **sur les mêmes données** : le nombre
dirait alors le poids choisi, pas l'état du projet. *Un nombre ne se trie pas sans son SENS.*
La distribution ci-dessus, elle, est vérifiable et ne bouge que si le code bouge.

### 24.7 Faut-il un mécanisme d'évaluation de la progression ? — **il en existe DÉJÀ trois**

Vérifié avant de proposer quoi que ce soit (`mecanismes.py` : **133 mécanismes**, aucun ne porte
sur la progression ; `vision_probe` concerne la capacité VISION d'un modèle, rien à voir).

| ce qui existe | ce qu'il mesure | généré ? |
|---|---|---|
| `check_app_conformity` | **89 critères** × 10 apps — l'ADOPTION du standard d'app | ✅ oui, écrase les booléens déclarés |
| `WAMA_VERIFICATION §3` | le catalogue des **GESTES** exécutables — le FONCTIONNEMENT | partiellement (nocturne) |
| marquage ✅/🔄/⏳ de la vision | l'avancement par section de vision | ❌ **écrit à la main** |

**Le trou réel est là** : le seul instrument qui parle de la VISION est le seul qui ne soit pas
généré — donc le seul qui dérive en silence. C'est exactement le défaut que `doc_facts` a corrigé
partout ailleurs (6 faits générés aujourd'hui : `conformite`, `mecanismes`, `modeles`, `outils`,
`roundtrip`, `wama_data`).

**Proposition (NON implémentée — arbitrage Fabien) : un 7ᵉ fait `doc_facts` = `vision`**, qui
relit les marqueurs des 50 sections et régénère le tableau du §24.6. Coût ≈ une fonction de
30 lignes, sur le patron exact de `_fait_conformite()`.

⚠ **Et sa limite, à dire d'emblée** : cela rendrait la DISTRIBUTION générée et infalsifiable,
mais **les marqueurs eux-mêmes resteraient déclaratifs**. Ce serait une grille d'**ADOPTION**,
jamais de **FONCTIONNEMENT** — la distinction que `WAMA_VERIFICATION §2` interdit de confondre.
Un ✅ posé à la main sur une section resterait une intention. **Le rendre vraiment mesuré**
supposerait d'accrocher chaque section de vision à un signal existant (un critère de grille, un
geste nocturne, un registre).

🔴 **SÉQUENCEMENT ET FORME — rectifié le 2026-09-12 par deux mesures.** J'avais présenté le choix
comme *« consolidée (peu coûteux) ou MESURÉE (coûteux) »*. **La seconde branche n'existe pas sous
cette forme**, et l'ensemble est à faire **APRÈS la refonte doc** (`§25`), pas avant :

1. **« Mesurée » n'est pas coûteux, c'est CONTRADICTOIRE.** Mesuré : **4 sections de vision sur
   50 citent du code**. Accrocher les 46 autres supposerait de réécrire la vision pour qu'elle
   cite du code — c'est-à-dire d'en faire un document de STATUT. Or le contrat de rôle des docs
   (en tête de ce fichier, 2026-07-20) pose *« Vision = le cap, marquage GROSSIER »* et *« chaque
   info vit à UN seul niveau »*. Ce n'était pas un arbitrage coût/bénéfice : c'était une option
   qui contredit le contrat.
2. **Le fait `vision` doit ATTENDRE `§25`.** Il écrirait un bloc dans
   `docs/construction/mondes/WAMA_VISION_COMPLET.md`, que la refonte va **trier en sous-dossiers** — or la table
   `doc_facts.FAITS` associe un fait à un CHEMIN. Écrire le fait maintenant, c'est livrer une
   entrée dont la cible bouge la semaine suivante, dans un fichier (`doc_facts.py`) que
   l'instance doc édite. Le coût d'attendre est ≈ nul : une vision à horizon années ne change
   pas de distribution en quinze jours.
3. **L'agrégation des mesures existantes N'EST PAS une nouvelle surface à créer — c'est la leur.**
   `wama/common/dev_docs.py` est déjà *« des générateurs qui rendent du markdown depuis un
   registre, que les PLANS de `docs_catalog.py` citent »*. Un `doc_facts` séparé ou une page
   `/common/etat/` de mon cru serait une **surface concurrente**, ce que `AGENTS.md` interdit.
4. ⚠ **Et leur doctrine tranche une chose que ma proposition ignorait** : un générateur cité par
   un plan *« n'écrit AUCUN nombre lu en base dans un fichier versionné — il changerait d'une
   installation à l'autre et le fichier serait toujours périmé »* (`dev_docs.py:13`). Or
   l'essentiel de ce que je voulais agréger EST lu en base (totaux de registres, mémoire, RAG).
   Donc cette moitié **ne peut pas être un doc versionné** : elle doit être une page **calculée à
   la lecture** — motif qu'ils ont déjà (`parcours`, `briques`, à reverser en plans, `§25.1 ⑥`).

**Forme retenue, à exécuter après `§25`** : ① un fait `vision` (≈30 lignes, patron
`_fait_conformite`) qui rend la DISTRIBUTION infalsifiable et datée — en disant dans le bloc
qu'elle consolide des DÉCLARATIONS, donc une grille d'ADOPTION ; ② l'état MESURÉ (grille, gestes,
registres, mécanismes) en **page calculée à la lecture**, dans la machinerie de `§25`.
⭐ **Et ne jamais les fondre en un seul chiffre** : ① dit *« où l'on se croit »*, ② dit *« ce qui
est vérifié »*. Les additionner reproduirait le défaut que `§24.6` refuse.

### 24.8 Balayage des blocs ANTÉRIEURS de `PROJECT_STATUS` — ce qu'il a appris (2026-09-10)

> Demande de Fabien : « balayer les blocs antérieurs en remontant, en vérifiant AU CODE ce qui
> est périmé dans la doc ». Passe faite ce jour sur les **sections de tête §0-§33** et par
> sondage ciblé sur le corps (33 affirmations falsifiables extraites au motif « à créer / n'existe
> pas / manquant / non construit », puis vérifiées une à une).

**🔴 Le résultat structurel — les deux moitiés du fichier ne vieillissent PAS pareil.**

| partie | nature | vieillissement | verdict du balayage |
|---|---|---|---|
| **§0-§33** (tête, juin-juillet) | se présentent comme **l'état courant** | 🔴 **mauvais** — un « reste à faire » de juillet se lit comme vrai aujourd'hui | 5 corrections sur 7 sections regardées |
| **§REPRISE / §CLÔTURE** (corps) | **instantanés DATÉS**, append-only | ✅ **bon** — un bloc daté ne prétend rien sur le présent | 1 correction sur 5 sondages |

⭐ **La leçon** : ce n'est pas l'âge qui périme une ligne, c'est sa **prétention au présent**.
Les blocs datés restent vrais *en tant que photos* ; les sections de tête deviennent fausses sans
qu'une seule ligne ne bouge. → Un avertissement a été posé **en tête de `PROJECT_STATUS.md`**,
et les sections non re-mesurées y sont **déclarées comme telles** plutôt que laissées pour bonnes.

**⚠ Et le biais va dans le sens INVERSE de celui qu'on redoute.** La doctrine met en garde
contre des statuts qui SURESTIMENT l'avancement. Ici, **quatre corrections sur cinq annonçaient
comme RESTANT une brique qui EXISTE** : `_batch_card.html`, l'UI de drag&drop, les runners
imager/converter, la fondation RAG. *Une doc qui sous-estime le code fait refaire ce qui est
fait — c'est aussi coûteux qu'un statut trop optimiste, et bien plus difficile à repérer.*

**Corrigé et daté** : §0 (gardes de redélivrance — périmé sur les DEUX termes, et le mécanisme a
changé : la garde est désormais héritée de `run_item_task`) · §1 (hook RAG « dépend de
`wama/rag/` » — paquet inexistant) · §6 (titre « non construit » contredisant son propre corps) ·
§9 (« RAG non démarré ») · §2bis (scores de grille faux de 20 à 50 points) · §15 (runners) ·
§18 (deux briques « à extraire » déjà extraites) · §23.2 (table des docs).

**Vérifié et CONFIRMÉ ENCORE VRAI** (ne pas rouvrir en croyant que c'est périmé) :
`manage.py check_structure` **toujours absent** (dû avant la 1ʳᵉ app data, `§18.2`) · **UI de
l'Explorer** à créer · `APP_CATALOG` = **14 entrées** (10 apps + 4 jumelles), `media_library`,
`cam_analyzer`, `face_analyzer`, `studio` et `model_manager` en sont bien absents · Presidio/
GLiNER (§7) **non construits** · le JS inline de `home.html` reste à extraire — ⚠ **631 lignes
mesurées, pas « ~500 »** : il a GROSSI depuis l'annonce.

**Reste à balayer** (non fait ce jour, déclaré) : les `§REPRISE` du **2026-08-29 au 09-03**, et
les sections §20bis-§33 en détail. Le sondage ci-dessus suggère un rendement faible — les blocs
datés vieillissent bien — mais il n'en fait pas la preuve.

## 25. Documentation — trois publics, UNE source de vérité (ouvert le 2026-09-11)

> **Cadre** : `AGENTS.md §Trois docs, trois publics` (la règle) et la règle CONSTAT / INTENTION
> (`AGENTS.md §VÉRIFIER LA ROUTE`). Ce § porte la MÉCANIQUE et son ordre de construction.

**La cible (Fabien, 2026-09-11).** Une seule source de vérité, qui tient par trois appuis : les
**registres** (la vérité tenue à jour de ce qu'utilise WAMA — mais pas exhaustive), la **doc de
construction à jour** (intentions, décisions, pourquoi, pièges) et la **confrontation au code**.
Les docs **développeur** et **utilisateur** DÉRIVENT de la doc de construction et y injectent les
faits des registres. Toutes sont des `.md`, lisibles depuis le dépôt ET depuis WAMA
(`/common/docs/`), rangées par audience puis par sous-catégorie. Les registres seuls ne suffisent
pas à les générer : ils disent ce qui existe, pas pourquoi ni comment s'en servir.

**Ce qui existe au 2026-09-11** : le catalogue des docs (`common/docs_catalog.py`, lecteur,
registre `docs`) ; `check_docs` (doc → code) ; `doc_facts` (blocs `WAMA:FAITS`) ; trois pages
développeur CALCULÉES à la lecture (`common/dev_docs.py`) — un amorçage, pas la cible.

### 25.1 La mécanique, dans l'ordre (on part des REGISTRES : la structure la plus stable)

| # | pièce | état |
|---|---|---|
| ① | **Faits en ligne** : `<!-- WAMA:FAIT(registre/clé/champ) -->valeur<!-- /WAMA:FAIT -->`, résolus depuis `Registry.entries`, régénérés par `doc_facts`, confrontés par `--check` (`common/fact_tags.py`). Le registre des registres en compte aujourd'hui <!-- WAMA:FAIT(registres) -->17<!-- /WAMA:FAIT --> | 🔄 livré le 2026-09-11 ; fiches déclarées pour quelques registres, les autres à suivre |
| ② | **Marquage des sections** de la doc de construction — par SECTION, pas par paragraphe (le coût connu de DITA) : `<!-- WAMA:SECTION(audience=developpeur,utilisateur; type=guide; nature=constat; etat=✅) -->` sur la ligne qui suit le titre ; une sous-section sans balise hérite. `type` ∈ tutoriel · guide · reference · explication (Diátaxis). **Double vérification** (Fabien) : `nature=constat` ⇒ ✅, `nature=intention` ⇒ 🔄 ou ⏳ — `check_docs` refuse les incohérences (`common/doc_sections.py`) | 🔄 livré le 2026-09-11 (syntaxe validée par Fabien) : marquage, contrôle, extraction ; pilote : `AGENTS.md §Trois docs` ; les docs de fond seront marqués à la révision (§25.2) |
| ③ | **Plans des docs dérivées** : un plan déclaré dans `docs_catalog.py` (étapes `Excerpt` = section marquée de la doc de construction, `Facts` = bloc calculé depuis un registre) → `.md` écrit par `doc_facts`, lisible hors WAMA (`common/doc_plans.py`). Refusé : source ou section introuvable, section non marquée pour ce public | 🔄 livré le 2026-09-11 ; pilote `docs/dev/registres.md` (« Les registres de WAMA ») |
| ④ | **Confrontation doc → doc** | ✅ **gratuite** : la dérivation étant MÉCANIQUE, une source modifiée change le fichier produit et `doc_facts --check` le voit. Une empreinte des sources ne servirait que si un humain ou un modèle réécrivait le texte |
| ⑤ | **Porte registre** pour la doc utilisateur : un fragment n'y apparaît que si le registre confirme ce qu'il décrit — la vision reste entière dans la doc de construction, et n'arrive chez l'utilisateur qu'une fois implémentée | 🔄 livré le 2026-09-14 : clé `porte=registre/clé[/champ]` du marquage, **obligatoire** pour une section qui parle à l'utilisateur (`check_docs` refuse aussi une porte qui vise un registre inconnu ou sans fiches). `doc_plans` n'y fait entrer ni une intention, ni un fragment dont le registre ne confirme pas l'objet : retenu, jamais cassé, et tracé en commentaire `WAMA:PORTE-FERMEE` (compté par `doc_facts`). Pilote : `docs/utilisateur/transcriber-correction.md`, dérivé de `TRANSCRIBER_CORRECTION.md §9` écrit et confronté au code ce jour, porte `apps/transcriber` ; l'intention de guidage (§9.4) y est retenue. ⚠ **Limite** : la porte a la granularité des registres — l'éditeur de correction n'a pas de fiche, c'est l'APP que le registre confirme |
| ⑥ | Reverser les pages calculées à la lecture en `.md` générés | ✅ fait le 2026-09-14 : `docs/dev/parcours.md` et `docs/dev/briques.md` rejoignent `docs/dev/registres.md`. Le mécanisme des pages calculées (champ `generator`, liens de site réservés) est RETIRÉ, faute d'usage. Les docs dérivées sortent de `check_docs` : leurs SOURCES y restent, et elles-mêmes sont confrontées par `doc_facts --check` |

### 25.1bis La REPRISE autrement — journal, handoff, état présent (orientation validée par Fabien le 2026-09-14)

`PROJECT_STATUS.md` fait **13 896 lignes** (relevé du 2026-09-14) et mêle deux natures qui ne
vieillissent pas pareil (`§24.8`) : des blocs DATÉS, vrais à leur date, et des sections qui se
présentent comme l'état courant. **À séparer en trois, AVANT la révision de fond (§25.2)** :

1. **Un journal** — en ajout seul, découpé par période (un fichier par mois, dans un dossier `journal` de `suivi`),
   sur le modèle de `CAM_ANALYZER_CHANGELOG.md` : une entrée datée ne se réécrit jamais.
2. **Un handoff COURT** — réécrit à chaque clôture : le point d'entrée 🔚 et les décisions en
   attente, rien d'autre. Ce qu'il contenait la veille part au journal.
3. **L'état présent** — plus de prose : généré ou mesuré (`§24`, blocs `doc_facts`, grille de
   conformité, registres).

⏳ À construire : le découpage de l'existant (les `§REPRISE` / `§CLÔTURE` vers le journal, SANS
réécriture), l'adaptation des skills `/reprise` et `/cloture`, la déclaration au catalogue des docs
(le journal avec `journal=True`).

### 25.2 Réviser la doc de construction — APRÈS la mécanique, quand le monde Médias sera abouti

1. **D'abord, vérifier qu'aucune INTENTION légitime n'a été supprimée** par le balayage de
   `PROJECT_STATUS` du 2026-09-10 (`§24.8`, confrontation au code). La règle constat/intention
   n'était pas écrite ce jour-là : relire ses corrections une à une, en particulier les « reste
   à faire » retirés, et remettre — marqué ⏳ — ce qui était une intention et non un constat.
   ✅ **Fait le 2026-09-14.** Relus : les 3 commits du balayage (`5263f337`, `96c101cc`,
   `819fe782`) et tout `.md` amputé du 10 au 12/09 (`c473ee1b`, `360d8e1b`, `60456ecc`,
   `3718293a`, `08c5f6b3`). Le balayage de `PROJECT_STATUS` n'a **rien perdu** : il barre et
   corrige en place, et garde les intentions (hook RAG, geste d'indexation, P2/P3 des cards —
   l'extraction de `_batch_card` visait la déduplication, tenue : 10 apps sur `_queue_entry.html`).
   **La perte était dans la boussole de ce fichier** (`c473ee1b`) : trois intentions retirées
   avec le constat faux voisin — consolidation des mécanismes d'UI, extraction des dernières
   briques communes, hiérarchie du RAG — **restaurées** en tête (H1, H2). L'archive supprimée
   par `08c5f6b3` était un doublon créé par la même session (contenu dans `archive/CONTEXT.md §5`).
   ⚠ **Reste une décision à Fabien** : le verbe `settings` de l'API a été écarté **sur mesure**
   (`§24.4① quater`, « route `update` sur 2 apps sur 15 ») — une intention sortie sans décision.
2. **Puis la révision de fond**, sur les seuls docs qui portent la connaissance (pas
   `PROJECT_STATUS`, pas les changelogs) : marquer audience × type par section, séparer
   constats et intentions, remplacer chaque chiffre recopié par une balise ①.
3. Ensuite, ajouter une app, une librairie, un modèle — tout ce qui vit dans un registre — ne
   pourra plus faire dériver la doc.

### 25.3 D'où vient cette approche (pour ne pas la réinventer)

Chaque pièce est éprouvée ailleurs ; l'assemblage l'est moins. **DITA** (OASIS) : attribut
`audience` et filtrage à la publication, *maps* = plans (③). **Markdoc** (Stripe) : variables et
conditions dans du Markdown. **tfplugindocs** (Terraform) et **Home Assistant** (manifestes
validés par `hassfest`) : gabarits écrits à la main, valeurs tirées d'un schéma (①). **Backstage**
TechDocs : catalogue d'éléments + `.md` à côté du code. **Diátaxis** : le type de doc compte autant
que le public (②). Moins courant : la doc de DÉCISIONS comme source des deux autres, la porte
registre (⑤), la confrontation dans les deux sens.

### 25.4 Décisions du 2026-09-11 (soir)

- **Plans des docs dérivées** (③) : déclarés dans `common/docs_catalog.py`, à côté de la
  déclaration du doc — une seule liste, contrôlable.
- **Pilote de ③** : la doc développeur « Les registres de WAMA ».
- **Emplacement — VALIDÉ par Fabien**, à faire dans une **session DÉDIÉE** (toutes les autres
  instances en pause) : toute la doc dans `docs/`, classée par audience, et un `README.md` racine
  qui porte l'arborescence et les liens.
  ```
  README.md  AGENTS.md  CLAUDE.md          ← seuls restent à la racine
  docs/construction/  architecture/ ui/ ia/ mondes/ exploitation/ suivi/ archive/
  docs/dev/            docs/utilisateur/    ← GÉNÉRÉS, ne pas éditer
  ```
  Trois exceptions : `AGENTS.md` et `CLAUDE.md` restent à la racine (lus là par les outils
  d'agents) ; les docs de MODULE restent à côté de leur code (le catalogue et le README les
  rendent visibles) ; l'archive va DANS `construction/` (d'anciens docs de construction — une doc
  générée ne s'archive pas, elle se régénère). Le sous-dossier pourra porter la FAMILLE, que le
  catalogue n'aura plus à déclarer.
  **Coût mesuré** (2026-09-11) : ~440 citations dans 175 fichiers de code, tests et skills, ~660
  dans 68 `.md` — dont les journaux et archives, qu'on ne réécrit PAS (faits d'histoire).
  **Premier geste de la session** (demande de Fabien, 2026-09-12) : relever la CARTE du jour —
  `python manage.py check_docs --carte` (les `.md` du dépôt, déclarés / non déclarés / déclarés
  mais absents). Des sessions écrivent d'ici là : un inventaire recopié serait faux au moment
  d'agir. C'est aussi la liste de ce qu'il faut DÉCLARER avant de déplacer quoi que ce soit.
  **Méthode** : `git mv` (historique conservé), skill `/renommage-api` (grep exhaustif des
  citations), `check_docs` en filet — ⚠ après avoir levé son exclusion de `docs/` dans l'index des
  noms, sans quoi toute citation par nom nu casserait. À faire AVANT la révision de fond §25.2.
  ✅ **FAIT le 2026-09-14** (session dédiée, seule active). **Palier A** `78b9bbe5` : la carte lit
  ce que git suit ; 8 docs de module déclarés. **Palier B** : 71 fichiers déplacés par `git mv`,
  citations recalées par un moteur à cinq règles — une par FORME de citation — lancé à blanc
  puis relu diff par diff. Deux formes n'ont été vues qu'en cours de route, et c'est la leçon :
  les COMMANDES écrites dans les skills (`git show HEAD:…`) et les champs `doc` suivis d'une
  ANCRE (`'…md §3'`, révélés par 46 échecs de test). Les noms nus en commentaire restent valides :
  les noms sont uniques, et `check_docs` indexe désormais `docs/`.
  ✅ **Palier C** (2026-09-14) : le `README.md` racine porte l'arborescence de la doc en bloc
  GÉNÉRÉ depuis le catalogue (`doc_facts`, fait `arborescence_docs`) — la table écrite à la main
  qu'il remplace citait 11 docs sur 45. Le README est déclaré : la carte n'a plus aucun `.md`
  non déclaré, et `check_docs` contrôle désormais ses liens.
- **Langue** : la doc reste en FRANÇAIS pour l'instant. Plus tard : l'harmoniser en anglais et la
  faire entrer dans l'i18n (`§10`) pour la traduction complète de WAMA.

## 26. Transparence des contenus GÉNÉRÉS et données PERSONNELLES des médias — chantier de réflexion GLOBAL (ouvert le 2026-09-30)

> Décision de Fabien, le 30/09, après l'état des lieux « voix personnalisées, droits, RGPD »
> (`MEDIA_STORAGE_TIERING §9.7`) : *« Pour le moment, pas de tampon audio. On attend de voir
> comment ça se met concrètement en place et on prévoit un chantier de réflexion complet sur le
> sujet pour tous les médias. C'est un chantier à faire globalement. »* ⏳ **Rien n'est tranché
> ici** : c'est le cadre des questions, pour ne pas les rouvrir app par app.

**Ce qui existe au 2026-09-30** (première marche, usage RECHERCHE) :
- la mention « Contenu généré par IA (WAMA <app>, modèle …) » dans les MÉTADONNÉES du fichier —
  brique `common/utils/generated_media.mark_as_generated` (copie de flux, ne fait jamais échouer
  un travail). Premier adopteur : le **synthesizer** (précise « voix clonée ») ;
- le **consentement au partage** d'un asset qui porte une personne (`Nature.personal` : voix,
  parole) et sa trace (`common.ShareConsent`) — `WAMA_COLLABORATION`, `MEDIA_STORAGE_TIERING §9.7`.

**Les questions du chantier** (à instruire, pas à trancher ici) :

| axe | question | point d'appui |
|---|---|---|
| portée | quelles apps produisent un contenu « généré » (imager, composer, avatarizer, synthesizer, enhancer ?) — et un contenu **transformé** (anonymizer, enhancer) l'est-il ? | registre d'apps (`APP_CATALOG`) — déclarer, ne pas lister en dur |
| forme | métadonnée seule (état actuel) · filigrane (audio : ex. AudioSeal ; image : filigrane invisible) · standard de provenance signé (C2PA) | adoption par `generated_media`, déclarée par nature de sortie |
| réglementaire | calendrier et exemptions du règlement européen sur l'IA (art. 50 : marquage des contenus synthétiques, mention des hypertrucages) ; l'exemption « recherche scientifique » couvre-t-elle les usages réels (rôle « communication ») ? | **DPO / juriste** — WAMA ne tranche pas |
| personnes | quelles natures portent une personne (visage d'un avatar, image, vidéo, parole) → `Nature.personal` ; consentement à l'AJOUT d'un média d'autrui, en plus du partage ? | `MEDIA_STORAGE_TIERING §9.7`, `PROFILES_PERMISSIONS` |
| licences | licence du MOTEUR héritée par la sortie (XTTS `cpml-1.0` = non commercial) — l'afficher sur le résultat ? | catalogue (`AIModel.license`), `LICENSING.md` |
| retrait | que deviennent les sorties produites avec une voix/un visage dont le consentement est retiré ? | aujourd'hui : elles restent, seules les FUTURES échouent (`VoiceUnavailable`) |
| registre RGPD | fiche de traitement « clonage de voix », AIPD | côté université : WAMA RÉFÉRENCE, n'absorbe pas (`WAMA_DATA_WORLD §13.16`) |

## 27. WAMA sur TABLETTE — relevé du 2026-10-10, trois étapes livrées (12 et 16/10)

> Question de Fabien, le 10/10 : *« Ce serait bien de pouvoir utiliser WAMA sur tablette
> aussi. Est-ce faisable rapidement ou un chantier à part ? »* Réponse mesurée : **un chantier à
> part, qui se découpe bien et commence par des corrections peu coûteuses.** Aucune doc n'en
> parlait avant ce relevé (seule trace : « mobile-friendly », `MODES_QUEUE_UX.md`).

**Le relevé** — profil iPad Pro 11 émulé par Chromium (tactile, portrait et paysage), 18 pages,
lecture seule sur le live, compte `wama_ui_smoke_v3`. Toutes en 200, **zéro erreur console,
aucun débordement horizontal**. Les défauts sont ailleurs :

| axe | mesuré | domicile |
|---|---|---|
| mise en page | trois colonnes fixes : centre 346 à 394 px sur 834 en portrait, 626 sur 1194 en paysage ; canvas du studio 158 px en portrait ; barre du haut qui se chevauche en portrait | `WAMA_VOLETS §9.5` |
| glisser au doigt | ✅ explorateur → app (jsTree : toucher pour sélectionner puis glisser, `filemanager.js:261`) · ✅ studio : relier deux ports (toucher, toucher) · ❌ studio : ajouter un nœud, défiler, déplacer, pincer · ❌ file `wama-queue-dnd` (fusionner, réordonner, sortir d'un lot) : le glisser ne démarre jamais, testé sur transcriber, imager, converter · ❌ éditeur du transcriber (lu dans le code, non joué) : onde, frontières et ordre des segments | brique de gestes à créer (étape 3) |
| cibles | presque toutes sous 44 px (59 sur 66 au transcriber) ; sous 24 px : 16 au transcriber, 12 à l'anonymizer, ports du studio à 11 px | étape 1 |
| survol | boutons-icônes expliqués par la seule infobulle : 16 à 24 par app, 45 à la médiathèque ; 14 règles CSS qui ne montrent une action qu'au survol (actions des cartes de la médiathèque, import d'un résultat de recherche, plein écran de l'aperçu) | étape 1 |

**L'ordre proposé** :
1. ✅ **Une règle commune pour les écrans tactiles** — **LIVRÉE le 2026-10-12** :
   `common/css/wama-touch.css`, montée par `base.html` en dernier, critère unique
   `(pointer: coarse)` ; convention `.wama-reveal-host` / `.wama-reveal` pour ce qui n'apparaît
   qu'au survol (montré aussi au clavier, toujours au doigt) ; forme d'emploi :
   `WAMA_APP_CONVENTIONS §23`, garde `tests_touch`. **Mesuré**, mêmes 16 pages en iPad portrait,
   1 247 cibles hors libellés et liens dans le texte (que la norme exempte) : sous 24 px
   **109 → 0**, sous 44 px **1 152 → 601** ; les deux pages du Lab, passées après, n'ajoutent
   aucune cible sous 24 px. Ce qui reste à 24-43 px est VOULU (cases, interrupteurs, curseurs au plancher de 24 ; lignes de l'explorateur à 32, la
   variante `large` de jsTree) ; aucun débordement horizontal, volets ouverts ou repliés ; à la
   souris, rien ne change (process 19 × 15, interrupteur 32 × 16, lignes à 24). Défaut induit
   trouvé et corrigé au passage : la saisie de l'assistant écrasée à 18 px par ses boutons
   agrandis (elle prend désormais sa ligne au doigt), la barre de zoom du studio rognée.
   ⚠ Précision du relevé du 10/10 : sur les « 14 règles » de survol, **quatre sites** cachaient
   vraiment une action (aperçu plein écran — défini DEUX fois, dans `media-preview.css` et
   `filemanager.css`, fusionnés —, actions et import de la médiathèque, pastille de la
   frontière) ; les autres changeaient l'apparence de l'élément survolé lui-même, ou venaient
   des bibliothèques tierces. ⏳ **Reste** : les boutons-icônes qui ne s'expliquent que par leur
   infobulle (`title`, invisible au doigt) — à traiter avec les gestes (étape 3).
   ✅ Traité à l'étape 3 (2026-10-16) : l'appui long sur une commande montre son `title`.
2. ✅ **Les volets et les barres** — **LIVRÉE le 2026-10-12** (le repli manuel par la
   frontière l'était le 10/10) : deux **contextes de largeur** sous le `lg` de Bootstrap
   (volets repliés d'office, un seul ouvert, mémoire à part — le choix fait en grand n'est
   jamais écrasé), volet ouvert qui POUSSE le centre plutôt qu'un tiroir qui le recouvre (glisser
   de l'explorateur, clic sur une card : le centre reste vivant) ; **barre du haut et pied** en
   grilles `1fr auto 1fr`, libellés effacés derrière leur icône par requête de conteneur.
   **Mesuré**, 6 pages × 6 profils : chevauchements de la barre **33/36 → 0** (le défaut existait
   aussi au BUREAU, dès 1 280 px volets ouverts), pied recouvert → 0, centre en portrait 394 →
   834 px. Gardes : `tests_panel_toggle` (amorce + brique jouées dans V8) et le scénario nocturne
   `common.layout.tablet`, vérifié rouge sur l'ancienne mise en page. Détail et raisons :
   `WAMA_VOLETS §9.5`.
3. ✅ **Une brique commune de gestes au pointeur** — **LIVRÉE le 2026-10-16** :
   `common/js/wama-gestures.js` (`WamaGestures`), montée par `base.html`. Trois choses :
   - **suivre un pointeur** (`WamaGestures.track`) sur une surface qui dessine elle-même :
     glisser avec seuil (un appui qui tremble reste un clic), PINCER à deux doigts ; Pointer
     Events, donc souris, stylet et doigt par le même code. Adoptée par le **studio** (nœud,
     fond, pincement) et l'**onde** de l'éditeur du transcriber (vue, borne — saisie à 16 px au
     doigt contre 6 à la souris —, lecture, mini-carte, pincement) : plus aucun
     mousedown/mousemove/mouseup chez eux ;
   - **le glisser HTML5 au doigt**, sur tout `[draggable="true"]` : appui long puis le doigt bouge
     → `dragstart`, `dragover` sous le doigt, `drop` seulement si accepté, `dragend`, avec un
     `dataTransfer` réel et une vignette qui suit ; la liste défile au bord. La **file**
     (`wama-queue-dnd`), la **palette** du studio et l'**ordre des segments** marchent au doigt
     SANS une ligne de plus chez eux. À la souris, la brique ne fait rien (glisser natif) ;
   - **l'appui long** : sur une commande qui porte un `title`, son INFOBULLE (le reste de l'étape 1)
     sans déclencher la commande ; ailleurs, un `contextmenu` — le menu de card et celui de l'arbre
     s'ouvrent comme au clic droit, ce que l'iPad n'offre pas ; sur ce qu'on glisse, l'appui long
     SOULÈVE : bouger glisse, relâcher ouvre le menu. Un appui seulement lent, qui n'a rien
     montré, garde son clic ; les champs de saisie gardent leur appui long natif.
   **Le cam_analyzer n'avait rien à porter** : ses deux glisser sont un dépôt de FICHIERS depuis
   le bureau et un marqueur Leaflet (qui gère le doigt lui-même). L'explorateur non plus
   (jsTree, ✅ au relevé).
   **Mesuré** sur de VRAIS événements tactiles (protocole de Chromium, iPad portrait) — scénario
   nocturne `common.gestures.touch`, écritures du navigateur interceptées : catalogue → canvas
   (+1 nœud), nœud déplacé, fond défilé, pincement 100 → 250 %, appui long « Zoomer » → infobulle
   sans zoomer ; card glissée sur une autre (cadre de fusion), lâchée dehors sans envoi, appui
   long → menu de card, appui long ⚙ → « Paramètres » sans modale ; onde pincée ×1,0 → ×4,7,
   lecture déplacée au toucher, segment glissé sur un autre (cible désignée). **Contre-épreuve**
   (brique remplacée par une coquille de même API) : les **dix** gestes rouges — dont ⚙ qui ouvre
   sa modale et « Zoomer » qui zoome à l'appui long. **À la souris rien ne change** : les neuf
   scénarios existants qui touchent ces pages verts sur le code neuf (`common.history.studio`,
   `transcriber.queue_dnd`, `common.correction_conflict`…), et une sonde souris (nœud, fond aux
   boutons gauche et du milieu, molette, désélection, onde glissée / cliquée / molette) 13/13.
   Garde : `tests_gestures` (la brique jouée dans V8 sur un faux DOM : séquence du glisser, refus
   du dépôt, balayage qui reste un défilement, menu, infobulle, clic gardé ou retenu ; `track` :
   seuil, boutons, pincement ; et aucun code tactile dans les pages). Forme d'emploi :
   `WAMA_APP_CONVENTIONS §23`.
   *Revérification sur le live relancé (même jour)* : le glisser du catalogue a échoué une fois
   sur cinq — le catalogue du studio se redessine à sa seconde réponse réseau, parfois PENDANT
   l'appui long, et l'élément tenu, retiré de la page, ne faisait plus remonter les mouvements du
   doigt jusqu'au document. La brique les écoute désormais aussi sur l'élément touché (garde V8
   `test_the_drag_survives_the_page_redrawing_the_held_element`, rouge sur la brique d'avant) ;
   3/3 verts sur le live ensuite.
   *Couverture des gestes complétée (même jour, question de Fabien : « tous les tests
   nécessaires, y compris les gestes utilisateurs ? »)* — la souris n'était gardée que par une
   sonde jetable. Nouveau scénario nocturne **`common.gestures.mouse`**, la garde du PC : studio
   (catalogue au glisser natif, nœud, fond aux boutons gauche et du milieu, molette, désélection),
   file (survol commun, case au clic, à Espace, plage Maj, décocher), onde (molette, glisser,
   clic), cloche (repos / survol) — 19/19 sur le live, contre-épreuve (brique vide, file et
   feuille d'avant la case) rouge sur chaque geste qui en dépend. `common.gestures.touch` gagne
   l'appui long sur l'ARBRE, la cloche au doigt, deux cases touchées, la liste qui défile au bord
   pendant un glisser et l'outil Bornes. Il a trouvé trois défauts de la brique, corrigés et
   gardés en V8 (chacun rouge sur la brique d'avant) : (1) au bas de l'écran le doigt est sur le
   PIED fixe et la page ne défile pas (son conteneur, si) — le défilement au bord ne se
   déclenchait jamais ; c'est désormais la liste de l'élément tenu qui défile ; (2) les entrées
   de l'arbre portent leur nom en `title` : l'appui long y montrait ce nom au lieu du MENU — un
   `title` qui redit le texte visible n'explique rien ; (3) la durée d'un appui se lit aux
   horodatages des événements, pas à la minuterie : sur une page occupée, un toucher bref passait
   pour un appui long et perdait son clic. Un faux rouge de l'instrument aussi, élucidé par trace :
   une borne lâchée EN MOUVEMENT lance une inertie, et le navigateur prend le toucher suivant
   pour l'arrêter, sans clic — le scénario immobilise le doigt avant de le lever, 4/4.
   ⏳ **Reste** : la sélection MULTIPLE de la file au doigt (aujourd'hui Ctrl/Maj ; au doigt on
   porte une card — les actions de groupe de l'inspecteur restent atteignables par le clavier) ;
   un essai sur une vraie tablette (ci-dessous).
   ✅ *Sélection multiple au doigt : soldée le jour même* par la CASE de sélection des cards
   (demande de Fabien, « comme dans Suno ») — cocher ajoute, comme Ctrl+clic, à la souris comme
   au doigt (`CARD_DESIGN §3bis`). Reste l'essai sur une vraie tablette.

**Ce que le relevé ne dit pas** : c'est Chromium qui émule, pas Safari sur un vrai iPad — Safari
gère peut-être le glisser HTML5 natif par appui long ; un essai sur une vraie tablette tranche ce
seul point. Les pages du Lab n'ont pas été passées (adresses non résolues par la sonde) ;
l'éditeur du transcriber a été lu, pas joué.
*(2026-10-16 : l'éditeur est désormais joué, au doigt et à la souris. Le glisser natif de Safari,
s'il démarre, est écarté pendant un appui suivi par la brique — deux glisser du même élément se
marcheraient dessus ; l'essai sur un vrai iPad reste le seul juge de ce point.)*

---

## 28. THÈMES — sombre, clair, UGE… (ouvert le 2026-10-17, demande de Fabien)

> *« On commence le chantier de thème »* — après le contrôle de contraste (`WAMA_VERIFICATION
> §10`), qui devait tenir quand WAMA aurait plusieurs thèmes ou modes (« sombre / clair / UGE /
> etc »). Ce paragraphe est le domicile du chantier ; il prolonge la recommandation « Voies
> alignées » (début du document : `data-bs-theme` de Bootstrap 5.3 + tokens CSS dans `common/`)
> et `CARD_DESIGN §9.3` (tokens des tuiles).

**Le modèle, posé le 2026-10-17 :**
- **Déclaration** : `wama/common/themes.py` — `THEMES` (clé, libellé, mode natif de Bootstrap),
  `DEFAULT`, `theme_for(request)`. Registre `themes` (DÉRIVÉ, page Registres). Le contexte
  (`context_processors.theme`) le passe à toute page ; `base.html` le pose sur `<html>` :
  `data-wama-theme` (les tokens) et `data-bs-theme` (le mode de Bootstrap).
- **Valeurs** : `common/css/wama-theme.css`, chargé avant toute autre feuille — un bloc
  `:root[data-wama-theme="<clé>"]` par thème, le thème par défaut aussi sur `:root` seul (une page
  hors de `base.html` reste lisible). Un composant ne pose plus de couleur, il lit un token
  (`var(--wama-text-label)`).
- **Mesure** : `common.contrast` joue chaque thème déclaré (`WAMA_VERIFICATION §10`).
- **Garde** (`tests_theme`) : chaque thème déclaré définit CHAQUE token ; aucun bloc sans thème
  déclaré ; aucun `var(--wama-…)` sans repli qui ne soit défini quelque part ; les fichiers portés
  restent à zéro couleur ; et le **budget des couleurs écrites en dur**, égal à la mesure, qui ne
  peut que descendre — **862** dans les feuilles CSS, **883** dans les gabarits au 2026-10-17
  (`app_modern.css` en tête, 163). Hors budget, chacun avec sa raison : `wama-theme.css` (le
  domicile), une copie de Bootstrap, les documents EXPORTÉS (palette `prefers-color-scheme`), les
  maquettes rangées en `docs/`. Le JS n'y est pas : ses couleurs sont surtout des palettes de
  dessin (canvas, graphes), mesurées au rendu.

**Ce que le premier palier a livré (2026-10-17)** : le socle ci-dessus et un premier adopteur, la
**card commune** (`wama-card-v3.css`, 17 couleurs → 0), dont les libellés faibles sont remontés
(`--wama-text-label`, 6,0:1 — décision de Fabien).

⚠ **Constat qui ordonne la suite** : le sombre d'aujourd'hui est PEINT À LA MAIN sur un Bootstrap
en mode CLAIR — d'où `bootstrap='light'` dans sa déclaration. Mesuré : poser `data-bs-theme="dark"`
sur les 30 pages de `common.contrast` ne change aucun rapport (un lien y gagne : `#0d6efd` →
`#6ea8fe`) et rien de visible sur les pages capturées — mais ces pages ne montrent pas les états
INTERACTIFS que le mode natif repeint : alertes (une `alert-warning` devient sombre, et l'exception
`btn-outline-dark` de `tests_contrast` deviendrait fausse), champs de formulaire, tableaux, modales,
listes déroulantes.

**Ordre retenu :**
1. ✅ Socle + card commune (ci-dessus).
2. ✅ **Basculer le sombre sur le mode natif** (`bootstrap='dark'`, 2026-10-17, GO de Fabien).
   *Mesuré avant de trancher* (site réel, lecture seule) : 166 états — les 30 pages de
   `common.contrast`, leurs menus déroulants ouverts, chacune de leurs modales ouverte tour à
   tour —, styles calculés de chaque élément visible comparés entre les deux modes (même DOM,
   transitions coupées) et contraste axe des deux modes. Aucun texte illisible ni avant ni après ;
   75 sortes de changements (3 087 éléments), presque tous des gains : liens `#0d6efd` → `#6ea8fe`,
   `code` éclairci, séparateurs et menus déroulants sombres (celui de la page Users était BLANC),
   onglets, croix `btn-close` blanche d'office. **Un seul défaut** : les alertes — `app_modern.css`
   forçait sur toutes les variantes le texte « emphasis » du mode CLAIR, en `!important` ; leur fond
   suivant le mode, `alert-secondary` des modales de lot (composer, describer) tombait à **1,88:1**.
   Les huit blocs deviennent une règle qui lit `--bs-alert-color` (mêmes valeurs en mode clair,
   justes en sombre) ; garde `tests_theme.ModeFollowingComponentsTest`. Le `btn-outline-dark` posé
   dans une alerte du transcriber devient `btn-outline-warning` (son exception de `tests_contrast`
   tombe), et `bg-body` sort des fonds clairs de la garde de code. Ce que la mesure ne voyait pas,
   relu dans le code : toasts et accordéon portent des fonds fixes (`bg-success`, `bg-dark`), aucune
   infobulle ni popover Bootstrap n'est employée. Joué ensuite sur serveur éphémère :
   `common.contrast` vert, plus aucun faible dans les modales, `transcriber.preview` et
   `anonymizer.preview` verts. Budget CSS 862 → 854.
3. ✅ **Porter les feuilles communes** sur les tokens (2026-10-18, GO de Fabien) — les seize
   feuilles de `common/css/` sauf `wama-catalog.css` (en cours dans une autre session à ce
   moment-là), ~560 couleurs : budget CSS 854 → **284**, ce qui reste est aux APPS (studio,
   gestionnaire de fichiers, présentation, enhancer, Lab) et à `wama-catalog.css`.
   *La règle du portage* : il ne change AUCUN rendu — chaque couleur prend un token dont la valeur
   sombre est la sienne au caractère près. Une couleur de la palette Bootstrap employée pour son
   sens lit la variable de Bootstrap (`--bs-primary`, `--bs-danger-rgb`…) ; un VOILE translucide
   lit les canaux d'un token (`rgba(var(--wama-overlay-rgb), .06)`, `--wama-accent-rgb`,
   `--wama-collab-rgb`…) au lieu d'un token par opacité — un thème clair inverse
   `--wama-overlay-rgb` et tous les voiles clairs suivent ; le reste prend un token NOMMÉ par son
   rôle, par section (visionneuse — `--wv-*` devenues des alias —, notifications, surfaces,
   réglages, assistant…). Les valeurs voisines (`#e5e7eb` / `#dee2e6`, `#198754` / `#28a745`…)
   restent distinctes : les fondre est une décision de charte.
   *Une seule famille de changements, VOLONTAIRE* : les textes gris `#6c757d` / `#7a838c` (3,3 et
   4,0:1 — la règle « jamais un gris moyen sur fond sombre », celle des libellés de la card), et
   `#555` / `#6b7280` d'un aperçu vide et d'un compteur, passent sur `--wama-text-label` (6:1) —
   état de l'assistant, heure du lecteur audio, onglets de port, titre de section de l'inspecteur,
   menu de card, filtre vide…
   *La preuve, à deux étages* : (1) statique, à chaque remplacement — l'outil de portage RÉSOUT
   le token lu (WAMA ou Bootstrap, mode sombre) et exige la valeur remplacée canal par canal,
   sinon rien n'est écrit ; (2) au navigateur, sur le site réel — les styles calculés de chaque
   élément visible (et de ses pseudo-éléments) comparés entre les feuilles de HEAD et les feuilles
   portées : 166 états (30 pages, menus ouverts, chaque modale), plus 41 rejoués DANS LE MÊME
   CHARGEMENT (feuilles permutées en place) pour neuf pages dont les données avaient bougé entre
   deux passages — **seul écart : l'état de l'assistant, une des remontées volontaires**. Ce que
   la preuve navigateur ne voit pas (pages d'édition, états non ouverts) repose sur l'étage 1.
   *Garde* : les seize feuilles inscrites à zéro couleur (`tests_theme.TOKENISED`), chaque token
   de canaux vaut trois entiers ; l'instrument a été affûté dans le même geste (une valeur citée
   en commentaire, une couleur aux canaux lus d'une variable ne comptent plus).
   ✅ *Feuilles d'APPS* (2026-10-18, GO de Fabien) : arbre de fichiers et volets
   (`filemanager.css`), Studio, Cam Analyzer, `wama-catalog.css`, accueil — 186 couleurs, mêmes
   règles et même double preuve ; sections neuves de `wama-theme.css` par app (`--wama-fm-*`,
   `--wama-studio-*`, `--wama-cam-*`, `--wama-cat-*`), un `--wama-indigo` partagé (arbre et
   canevas). Remontés à `--wama-text-label` dans le même geste : `#718096` de l'arbre (aide,
   chargement, substitut ; 4,2 et 4,0:1), `#6f7890` des sous-groupes de la palette du Studio
   (3,8:1) et `#6c757d` de la zone de dépôt et du libellé de navette du Cam Analyzer. Preuve
   navigateur rejouée DANS LE MÊME CHARGEMENT (feuilles permutées en place, serveur éphémère : la
   prod était arrêtée) sur 178 états — les 30 pages, le Studio, le Cam Analyzer, menus et modales :
   seuls écarts, ces remontées. **Deux feuilles MORTES supprimées au lieu d'être portées** (`REMOVAL_LEDGER` R145, R146) :
   `enhancer/css/style.css`, plus chargée depuis le 2025-12-13, et `composer/css/index.css`, jamais
   chargée. Budget CSS 284 → **54**.
   ⚠ *La présentation* (`wama-presentation.css`, 54) est une page AUTONOME : elle n'étend pas
   `base.html`, donc ne recevait pas `wama-theme.css`. Ses trois gabarits (présentation,
   architecture, archive v2) le chargent désormais avant sa feuille — garde
   `tests_theme…test_a_standalone_page_loads_the_tokens_before_a_sheet_that_reads_them`, contre-épreuve
   sur HEAD : les trois relevés. Sa feuille portée (tokens `--wama-pres-*`) n'a suivi qu'une fois
   les workers nés APRÈS l'édition des gabarits (relance de 12:06, gabarits de 11:53) : un
   gabarit est mis en cache par worker, et une feuille portée servie avec l'ancien gabarit aurait
   rendu la scène sans couleurs. Preuve : les trois pages RENDUES par leurs vues (le compte de test
   n'y a pas accès), feuilles permutées dans le même chargement — 2 003 éléments, **0 écart** ;
   contre-épreuve, sans `wama-theme.css` presque tous changent. **Budget CSS 0** : plus aucune
   feuille de WAMA n'écrit de couleur.
   ✅ *Les styles des PAGES* (2026-10-18, GO de Fabien) — blocs `<style>`, bloc `app_styles`,
   attributs `style=` et couleurs de DESSIN des `<script>`, dans 66 gabarits. L'instrument d'abord
   affûté : dans un gabarit, un commentaire se retire dans son langage (un `accept="video/*"`
   ouvrait un « commentaire » CSS qui avalait la page) — **871** couleurs, et non 795. Tokens par
   FAMILLE plutôt que par page : la palette « nuit » des pages du compte et d'Apps
   (`--wama-night-*`), les TONS des pastilles des pages catalogue (`--wama-tone-*`, `--wama-cat-*`),
   les natures de souvenir partagées avec les skills (`--wama-kind-*`), le lecteur de doc, la
   médiathèque, le model manager, l'éditeur du transcriber (qui retombe sur `--wama-edit-*`), la
   coquille des apps, la présentation v1 archivée. Un canvas ou un graphe Chart.js ne lit pas
   `var(--…)` : brique commune **`WamaApp.themeColor(token[, alpha])`** (`wama-app-base.js`), qui
   rend la valeur du thème actif (Face Analyzer). Remontés à `--wama-text-label` dans le même
   geste : les gris écrits dans les pages (`#6c757d`, `#555`, `#666`, `#6b7c89`, `#6c7a8a`), soit
   les derniers faibles de `WAMA_VERIFICATION §10` — de 57 à 4, ceux qui restent sont des
   composants Bootstrap et une couleur de donnée. Les pages autonomes qui lisent désormais les
   tokens (démo des modes, présentation et architecture v1) chargent `wama-theme.css` ; la garde
   des pages autonomes suit aussi leurs styles propres et leurs `{% include %}` (contre-épreuve :
   les deux archives v1 de HEAD relevées). *Preuve* : statique à chaque remplacement (même outil,
   étendu aux gabarits) ; au navigateur, chaque page RENDUE deux fois, par le code de HEAD (worktree
   jetable) et par l'arbre, puis comparée JS coupé (même DOM) — 39 pages, ~47 000 éléments, seuls
   écarts les remontées ; Apps, dont une section dépend de l'ordre des rendus, rejouée en premier
   rendu de deux processus. JS actif : aucune erreur de console, `themeColor` juste sur chaque page.
   Non couverts au navigateur (vérification statique seule) : l'éditeur du transcriber (aucune
   transcription au compte de test), Users et la matrice d'accès (refusées). **Budget gabarits
   0** : plus aucune couleur écrite dans WAMA, hors documents exportés et maquettes de la doc.
   ⏳ *Reste* (`WAMA_VERIFICATION §10`) : les boutons Bootstrap « outline » sur fond sombre
   (Apps, Profil) — une règle commune, décision de charte ; la couleur d'un événement du calendrier.
4. ✅ **Le thème CLAIR** (2026-10-18, demande de Fabien : « on passe au second thème clair
   d'abord », l'UGE ensuite, charte reçue) — `Theme('light', 'Clair', bootstrap='light')`.
   *Le sombre était aussi écrit dans les CLASSES* : ~1 400 `bg-dark`, `text-light`, `text-white(-50)`,
   `table-dark`, `btn-outline-light`, `dropdown-menu-dark`, `btn-close-white`, `navbar-dark` dans
   117 gabarits, JS et Python, portés par script vers leurs équivalents qui suivent le mode
   (`bg-body`, `text-body-emphasis`, `text-body-secondary`, `.table` seule, menu et croix natifs,
   `link-body-emphasis`, et une variante commune `btn-outline-emphasis`) — un texte blanc posé sur
   un fond de palette fixe (badge, toast, bouton plein) reste blanc. Le mode sombre NATIF du
   Bootstrap 5.3.0 de WAMA est plus terne que les classes `-dark` retirées (tables et menus en
   #adb5bd, texte secondaire à 4,9:1) : `.table`, `.dropdown-menu`, la barre du haut et
   `text-body-secondary` portent donc, lues sur les tokens, les valeurs de `table-dark`,
   `dropdown-menu-dark`, `navbar-dark` et du `text-white-50` éclairci — un seul menu dans WAMA, celui
   de la barre du haut. Le pied de page lit `--wama-footer-bg`, l'aperçu de la card du transcriber
   rejoint la zone commune `wcv3-preview`.
   *Les valeurs ne sont pas peintes à la main* : le clair est le **miroir de luminance** du sombre
   (`wama/common/theme_mirror.py`, Y' = 0,0525/(Y+0,05) − 0,05, teinte et chroma gardées), qui
   conserve EXACTEMENT chaque rapport de contraste WCAG — un texte lisible en sombre l'est en clair,
   la hiérarchie des gris aussi. Exceptions DÉCLARÉES avec leur raison dans `themes.py` :
   `LIGHT_SURFACES` (structure sur le Bootstrap clair : #fff, #f8f9fa…, jamais plus sombres que
   leur miroir), `LIGHT_FIXED` (ombres, papier, vidéo, carte, présentations autonomes, et les
   couleurs VIVES — accent, états, palette des badges — avec le texte qu'on y pose : leur
   identité ne change pas ; lues comme TEXTE, quatorze d'entre elles passent par un jumeau `-text`
   qui suit le miroir), `LIGHT_HAND` (`--wama-data-ink` : une couleur de DONNÉE, celle d'une app,
   assombrie de moitié quand elle est lue comme texte). Bootstrap clair : `text-warning`,
   `text-info` et leurs boutons à contour lisent la teinte « emphasis » du mode, le lien le miroir
   de `--wama-link`. Une région peut FIXER son thème (`data-wama-theme` + `data-bs-theme` : l'encart
   au dégradé de l'accueil) — les blocs ne sont plus limités à `:root`.
   *Gardes* : `tests_theme.LightThemeIsTheMirrorTest` (chaque token clair = le miroir, ou déclaré ;
   chaque exception nomme un token ; contre-épreuve de la règle elle-même) ;
   `tests_contrast.LightTextNeedsADarkBackgroundTest`, la forme symétrique annoncée — un texte clair
   fixe exige un fond sombre fixe dans sa liste de classes, et aucun fond sombre n'est plus écrit
   dans une classe (trois exemptions, fond venu d'un parent, chacune avec sa raison).
   *Preuves* : (1) sombre inchangé — 39 pages RENDUES par HEAD (worktree) et par l'arbre, feuilles
   servies de chaque côté, ~43 000 éléments : seul écart `text-light` #f8f9fa → #fff (cinq pages
   aux données qui suivent le code comparées par alignement des éléments) ; (2) `common.contrast`
   joue les DEUX thèmes, 60 pages : aucun texte illisible ; en clair, il est resté deux familles
   faibles, puis plus que les événements du calendrier (couleur de donnée, déjà faibles en sombre).
   ⏳ *Reste* : ~~choisir son thème (étape 5)~~ (✅ 2026-10-19) ; les boutons « outline » faibles et la couleur d'un
   événement (charte) ; ~~le thème UGE, qui partira de la charte (`claude/Charte_Gustave_Eiffel/`)~~
   (✅ 2026-10-19, étape 6).
5. ✅ **Le choix de l'utilisateur (2026-10-19)** — *« ok pour le Profil avec Auto »* (Fabien).
   *Où* : la page **Profil**, carte « Apparence », à côté de la langue et des unités — une
   préférence qu'on règle une fois ; la barre du haut reste aux gestes fréquents (mode simplifié,
   cloche). Le « menu du compte » prévu ici n'a pas été retenu.
   *Quoi* : **Automatique (suit le système)**, puis chaque thème déclaré (`themes.choices()` : la
   liste s'allonge seule avec UGE). ~~Automatique, le défaut de tout compte~~ → **le SOMBRE est le
   défaut** de tout compte et du visiteur sans compte (Fabien, 2026-10-19, le soir même : *« la
   plupart des gens ont leur système en clair, or le thème sombre est plus agréable
   actuellement »*) ; Automatique se choisit.
   *Comment* : un réglage durable `user_settings` (app `common`, nom `theme` — pas de migration),
   lu par `theme_choice(user)` ; un choix qui n'est plus déclaré retombe sur Automatique. Le serveur
   pose le thème d'un choix explicite ; « Automatique » ne se résout que dans le navigateur
   (`prefers-color-scheme`) : `common/js/wama-theme.js`, chargé SYNCHRONE dans le `<head>` avant
   toute feuille (pas d'éclair), lit `themes.declared_for_pages()` (`#wama-theme-declared`) et
   suit le système s'il change page ouverte. Au Profil, le choix se pose sur place
   (`WamaTheme.apply`) puis s'enregistre (`accounts:profile-theme`).
   *Gardes* : `tests_theme.ThemeChoiceTest` (défaut, choix lu par toute page, refus, choix périmé,
   route et carte du Profil, ordre dans `base.html`) et `ThemeScriptTest` (le script dans V8 :
   Automatique suit le système et ses changements, un choix explicite non ; contre-épreuves —
   écoute retirée, résolution retirée — rouges). Smoke navigateur sur le serveur éphémère : les
   deux modes du système, le changement page ouverte, le choix enregistré, aucune erreur JS.
   ~~⚠ *Conséquence* : Playwright émule un système CLAIR par défaut — les captures nocturnes
   (vignettes des briques UI, vidéo des gestes) passent en clair pour le compte de test~~ —
   **soldé par le défaut sombre** (Fabien : *« garde le sombre pour les captures nocturnes »*) :
   le compte de test ne choisit rien, il reçoit le sombre quel que soit le système que Playwright
   annonce. Garde : `test_nothing_chosen_means_dark_whatever_the_system`.
6. ✅ **Thèmes DÉRIVÉS d'une charte : Université Gustave Eiffel et La Suite numérique**
   (2026-10-19 — Fabien : *« on passe au thème UGE ? J'aimerais aussi un thème la suite
   numérique »*). Un thème dérivé déclare sa base (`Theme.base = 'light'`) : il figure dans la
   LISTE DE SÉLECTEURS du bloc clair de `wama-theme.css`, en reçoit les 421 valeurs, et son propre
   bloc ne redéfinit que l'identité (~20 propriétés : accent, liens, indigo/violet, page, défilement,
   et la primaire de Bootstrap `--bs-primary*`). Quand le clair se régénère, les dérivés suivent.
   *Chartes* : `themes.CHARTERS` — UGE depuis `claude/Charte_Gustave_Eiffel/…V2-4.pdf` p. 7
   (principale indigo #2f2a85 Pantone 2746C, dix secondaires, gris de page #f1f2f2 relevé sur ses
   pages) ; La Suite depuis **Cunningham**, son design system (github.com/suitenumerique/cunningham,
   **MIT**, un mode clair et un sombre), chaque couleur dans le rôle que Cunningham lui donne
   (fond de marque brand-550 #1167d4, texte de marque brand-700, lien brand-600, page gray-025).
   Les couleurs de SENS (succès, échec…) restent celles du clair. Polices non embarquées : TT Norms
   (UGE) est sous licence commerciale (nommée depuis, 6bis) ; Roboto Flex (La Suite) est libre, elle passerait par
   `tools/update_vendors.sh`. Ni Marianne ni logo de l'État (réservés aux services de l'État).
   *Bootstrap* : 5.3.0 écrit #0d6efd EN DUR dans `.btn-primary`, `.btn-outline-primary`,
   `.nav-pills`, `.pagination` — `app_modern.css` les fait lire `--bs-primary`, teintes de
   survol/appui calculées comme Bootstrap (`color-mix` avec `--bs-black`, 15/20/25 %) : même rendu
   en sombre et en clair, seul écart l'anneau de focus du bouton plein (13,110,253 au lieu de
   49,132,253). Les autres composants (champs, cases, barres, menus) lisaient déjà `--bs-primary`.
   *Gardes* : `tests_theme.DerivedThemeTest` — le dérivé est dans la liste de sa base (un seul
   niveau), reçoit chaque token, chaque couleur de son bloc vient de sa charte (hex, `rgba`,
   canaux), une teinte déclarée est le mélange qu'elle dit, ses textes passent 4,5:1 sur le blanc
   et sur sa page ; contre-épreuves : une couleur étrangère relevée, le dérivé retiré de la liste
   ne reçoit plus que 16 tokens sur 421. `common.contrast` joue chaque thème déclaré.
   ⏳ *Reste* : ~~une variante SOMBRE de La Suite~~ ; ~~le logo de l'université dans la barre du
   haut~~ (✅ 2026-10-19, 6bis) ; boutons « outline » et calendrier (charte).
6bis. ✅ **La Suite en sombre, le logo et la police de l'UGE** (2026-10-19 — Fabien : *« oui pour
   le logo UGE et La Suite en sombre, mais la suite de base en version claire »* ; *« TT Norms est
   payé par l'UGE pour être utilisé »*).
   *La Suite sombre* : `lasuite-dark`, `base='dark'` — dans la liste de sélecteurs du bloc SOMBRE,
   avec les rôles du thème sombre de Cunningham (`.cunningham-theme--dark`) : page gray-900, fond de
   marque brand-550 sous un texte blanc (5,1:1), textes de marque brand-100/250/300, palette
   brand-350/450. `Theme.charter` nomme la charte d'un dérivé (les deux La Suite partagent la leur).
   La garde de contraste lit désormais les fonds de la BASE : le blanc en clair, les surfaces du
   sombre en sombre ; la primaire, fond d'un bouton plein, passe 4,5:1 sous son texte blanc — en
   sombre elle n'est pas lue comme texte (aucune couleur ne passe 4,5:1 des deux côtés).
   *Logo* : `Theme.logo` (le fichier fourni `WEB/logo_univ_gustave_eiffel_rvb.svg`, tel quel →
   `common/images/themes/logo-uge.svg`) ; la barre du haut pose le logo de chaque thème qui en a un
   (`theme_logos`, contexte), `filemanager.css` ne montre que celui du thème actif — le Profil
   change le thème sans recharger. Charte p. 9-12 : à gauche, à l'écart du logo WAMA (interdit :
   « un nouveau principe d'endossement »), couleurs d'origine (#171c8f dans le fichier — la p. 7
   annonce #2f2a85 pour le même Pantone : le fichier n'est pas retouché, « interdit de modifier les
   couleurs »), 26 px de haut = 126 px de large (minimum 25 mm ≈ 95 px) ; sous 780 px de barre, il
   s'efface au lieu de rétrécir (mesuré : à 781 px, 12 px d'écart de chaque côté, aucun débordement).
   *Police* : la licence fournie avec TT Norms est un contrat Monotype **poste unique** (§4 : pas
   sur un serveur dont les postes ne sont pas tous licenciés ; §7 : pas de distribution ; §9 : pas
   de conversion, donc pas de `.woff2`) et le dépôt est PUBLIC : la police est **nommée, jamais
   servie** — `--bs-body-font-family: "TT Norms Pro", "TT Norms", Tahoma, …` ; un poste où
   l'université l'a installée l'affiche, ailleurs Tahoma, le repli que donne la charte (p. 8).
   `themes.LICENSED_FONTS` + garde : aucun fichier de ces polices dans les dossiers statiques, aucun
   `@font-face` qui les déclare. ⏳ Si l'université détient une licence **web** (webfont), la
   servir hors dépôt (dossier non versionné, comme `AI-models`) : décision de Fabien.
   *Gardes* : `DerivedThemeTest` (dérivé du sombre compris), `ThemeIdentityTest` (logo servi et
   copié dans `staticfiles/`, règle d'affichage par thème, police nommée et non servie) ;
   contre-épreuves rouges : dérivé sombre retiré de la liste, lien trop sombre, couleur hors charte,
   règle du logo retirée ; la garde de police sur des sources écrites pour elle.
   ⚠ *Vécu* : `context_processors.theme` lisait `t.logo` — un worker qui n'avait pas encore importé
   le context processor l'a lu neuf avec l'ancien `themes` : toutes ses pages en 500 (96 erreurs
   journalisées de 23 h 02 à 23 h 05, rechargement de gunicorn à 23 h 18 sur accord de Fabien). Lu
   désormais par `getattr`.
7. ⏳ **Personnaliser son thème** (question de Fabien, 2026-10-19 : charte complète ? palettes à
   cliquer ? une image dont un LLM tire le thème ?) — *proposition, rien de construit* : toutes les
   voies produisent la MÊME chose, quelques couleurs-graines (base claire ou sombre, primaire,
   secondaire, teinte de page), et UN générateur en dérive le bloc avec les gardes ci-dessus
   (contraste ajusté jusqu'à 4,5:1) — jamais 421 tokens édités à la main. Ordre proposé :
   (1) palettes et couleur d'accent à cliquer au Profil ; (2) import d'une CHARTE (PDF) pour un
   labo, une équipe, un établissement — le LLM lit les valeurs dans le texte (comme la p. 7 de la
   charte UGE), un humain valide, le thème est partagé selon la portée (même héritage que la
   visibilité, `§29`) ; (3) une image : la palette s'en extrait sans LLM (regroupement des
   couleurs en OKLab), le LLM ne sert au plus qu'à choisir les rôles.

## 29. PROVENANCE de tout ce qui entre dans WAMA — privé à son auteur, « Système » une fois promu (ouvert le 2026-10-18, demande de Fabien)

> *« Tout ce qui entre dans WAMA, les briques UI, les modèles, les librairies, les fonctions, etc.,
> suit la logique des droits, comme les apps. L'idée étant de pouvoir restreindre certains modèles
> ou éléments en privé. Les publics sont estampillés "système" comme pour les médias. Ça
> permettrait aux utilisateurs d'avoir leurs propres briques UI, notamment à la création d'app
> bac à sable. L'app reste à son auteur tant qu'elle n'est pas promue. On aligne ça sur toutes les
> capacités qui s'ajoutent dans WAMA. »* Intention ⏳ : rien n'est construit au-delà de l'existant
> relevé ci-dessous. Décisions a–d rendues le jour même (plus bas).

**Deux axes existent déjà, et ce ne sont pas les mêmes :**
- **qui a le DROIT** — profil et rôles : `accessible(user, kind, element_id)`, point unique de
  décision (`PROFILES_PERMISSIONS §8.2`) ;
- **à QUI c'est** — propriétaire et portée : `ScopedVisibility` + `scoped_visible_q`
  (`WAMA_COLLABORATION §4`).

Les INSTANCES (cards, lots, médiathèque, fonctions d'utilisateur, mémoire, RAG) ont le second. Les
éléments du CATALOGUE n'ont que le premier, et seule la famille `app` y est réellement gardée. La
demande revient à donner le second axe aux éléments du catalogue, **avec le même mixin et le même
vocabulaire**. On n'ajoute pas un troisième axe.

**Relevé du 2026-10-18 (lu dans le code) :**

| famille | ce qui existe | ce qui manque |
|---|---|---|
| médias | DEUX tables : `SystemAsset`, sans propriétaire, gérée par les admins (`media_library/models.py:161`), et `UserAsset`, `ScopedVisibility` (`:71`) | — c'est le modèle à suivre |
| apps et jumelles | `accessible(user, 'app', …)` ; le créateur d'une jumelle y accède quel que soit son profil (`accounts/permissions.py:432-445`), lu de `created_by` dans le registre gitignoré `sandbox_apps.json` (`common/sandbox.py:56`) | une provenance hors de `ScopedVisibility`, et aucun geste de promotion commun aux autres familles |
| modèle, librairie, fonction, skill | déclarées dans `KIND_DECISION` comme « S3 » (`accounts/permissions.py:135-142`) : `accessible()` répond OUI (`:420-421`) | tout : aucun propriétaire sur `AIModel` (`model_manager/models.py:509`) ni sur `Library` (`common/models.py:954`) ; `FunctionSpec.visibility/owner` sont déclarés mais jamais filtrés (`catalog/function_catalog.py:232-238`) |
| manifestes, la porte d'entrée de toute capacité | `owner` + `visibility` stockés, bac à sable = `private` (`common/models.py:905-909`) | jamais filtrés, et les portées sont des CODES (CharField) que `scoped_visible_q` ne sait pas lire (`PROFILES_PERMISSIONS §1.6`) |
| pipelines du Studio | propriétaire seul (`studio/models.py:30`) | la portée |
| briques UI | déclarées dans le code (`common/mecanismes.py`), donc système par construction | une brique d'UTILISATEUR n'a aucun lieu |
| sélection automatique | `select_model()` (`model_selector.py:505`) | elle ne reçoit pas le compte : un modèle privé y serait choisi pour n'importe qui |

**Le modèle proposé :**
1. **Tout élément du catalogue a une provenance.** Soit il est **système** : sans propriétaire,
   géré par les admins, comme `SystemAsset`. Soit il a **un auteur et une portée**
   (`private` / `unit` / `project` / `public`). Un élément qu'un utilisateur ajoute **naît privé**,
   comme toute chose dans WAMA (`WAMA_COLLABORATION`, principe 1).
2. **La décision reste UNIQUE.** `accessible(user, kind, id)` = *visible pour lui* (sa portée)
   **ET** *permis* (la politique de rôle ou de profil, puis `AccessGrant` à S3). Chaque famille
   déclare dans `KIND_DECISION` où vit sa provenance. Aucun lecteur ne la relit à sa façon.
3. **Promouvoir est UN geste, le même pour toutes les familles.** L'élément passe de privé à
   système, validé par un ADMIN (décision b) dans la file de `PROFILES_PERMISSIONS §8.7 S4`. L'auteur reste
   cité, pour l'attribution, mais ne possède plus l'élément. Pour du CODE (brique UI, backend, app
   jumelle), promouvoir revient à le DÉPLACER vers `common/` ou vers l'app réelle, et à le
   déclarer au registre. Ce geste de développement reste humain (`ROUTE §10.5`).
4. **Toute capacité NOUVELLE déclare sa provenance, et un contrôle la tient** : une garde parcourt
   les familles du catalogue (`registries.overview()`). Elle échoue si l'une d'elles n'a pas de
   porteur déclaré. La liste n'est pas close, et le contrôle ne la ferme pas.
5. **L'utilisateur voit la provenance partout de la même façon** : une pastille « Système »,
   « à moi » ou « partagé par X » sur chaque card du catalogue, comme celle de la médiathèque, et
   une facette standard dans la barre de filtres (« mes / système / partagés », celle de S1).

**Frontières voulues :**
- une **librairie** s'installe dans un venv PARTAGÉ : « privée » veut dire *non proposée aux
  autres*, jamais *isolée* ;
- les poids d'un **modèle** vivent dans `AI-models`, qui est partagé : « privé » veut dire
  invisible des catalogues, des sélecteurs des apps, de la palette du Studio, de l'assistant et de
  `select_model`. Ce sont autant de lecteurs à porter, et une seule lecture oubliée suffit à tout
  ouvrir (`WAMA_COLLABORATION §4.4`) : d'où un critère de conformité, comme `scoped_reads`.

**Décisions de Fabien (2026-10-18) :**
- a. **Système ≠ public partagé : OUI.** Un auteur qui partage en « public » garde la main sur
  l'élément ; un élément système est tenu par WAMA (la distinction `UserAsset` public /
  `SystemAsset`). L'enveloppe le dit déjà : `owner: None = système/builtin`
  (`manifests/envelope.py:36`).
- b. **Une promotion est validée par un ADMIN seul.**
- c. **Pour le moment, l'admin voit tout**, éléments privés d'autrui compris. On ajustera plus tard.
- d. **Le porteur de la provenance : LES DEUX**, le registre et le manifeste, puisque le manifeste
  est la projection des registres. Point vérifié en profondeur ci-dessous.

**Vérification du point d (2026-10-18, lue dans le code).** Le manifeste et le registre ne
s'échangent pas la provenance dans le même SENS pour chaque famille
(`WAMA_MANIFEST_ARCHITECTURE §7bis`). Donc « les deux » veut dire : **la ligne du registre porte la
provenance pour filtrer** (`visible_to`, rapide, au runtime), **l'enveloppe la porte pour voyager**
(export, ré-import, aller-retour), et `extract` comme `write_back` la transmettent dans les deux
sens. Ce qui change d'une famille à l'autre, c'est **d'où la provenance NAÎT** :

| famille | sens mesuré | la provenance aujourd'hui | où elle doit naître |
|---|---|---|---|
| fonction d'utilisateur | les deux sens | ✅ **déjà portée des deux côtés** : `extract` lit propriétaire, portée et scopes sur `UserFunction` (`builtin/function.py:102-115`), `write_back` les écrit et EXIGE un propriétaire (`:157-191`) | **le modèle à suivre** |
| librairie | ENTRANT (manifeste → `Library`) | perdue : `extract` écrit `public` en dur (`builtin/library.py:207`, `:282`), `Library` n'a aucun propriétaire | dans le manifeste, puis projetée sur la ligne |
| modèle | SORTANT (disque → `AIModel` → manifeste) | perdue : la ligne naît du disque, jamais d'un manifeste (`builtin/model.py:398-400`) ; `extract` écrit `public` en dur (`:259`) ; `install_from_spec(spec, token)` ne reçoit pas le compte (`model_installer.py:1879`) | au GESTE d'installation (qui l'a lancé), écrite sur la ligne, puis extraite |
| pipeline du Studio | SORTANT, pas de `write_back` | propriétaire extrait, portée `private` en dur (`builtin/pipeline.py:395-396`) | sur la ligne (`studio/models.py:30`) |
| app jumelle | fichier de manifeste → code généré | seulement `created_by` dans le registre gitignoré des jumelles (`app_sandbox.py:918-921`) ; les apps livrées sont `public` en dur (`builtin/app.py:324`) | au registre des jumelles ET dans l'enveloppe du brouillon |
| brique UI, skill | aucun kind de manifeste ; registre = le CODE (`mecanismes.py`) | système par construction ; une brique d'utilisateur n'a aucun lieu | proposition : une brique d'utilisateur vit dans le paquet de SA jumelle et en hérite la provenance — pas de registre neuf ; sa promotion la déplace vers `common/` et l'inscrit à `mecanismes.py` |

**Trois écarts que la vérification a trouvés, à refermer AVANT de rendre quoi que ce soit privé :**
1. **« privé » veut dire aujourd'hui « en attente de validation ».** `Manifest.is_sandbox` vaut
   `visibility == 'private'` (`common/models.py:927-929`), et `proposals.pending()` liste TOUT
   manifeste privé comme une proposition à valider (`manifests/proposals.py:85-91`). Le manifeste
   d'un modèle privé d'utilisateur tomberait donc dans « Propositions à valider » de l'admin. Il
   faut séparer les deux états : *privé* est une portée, *promotion demandée* est une demande (la
   file de S4).
2. **Une promotion donne aujourd'hui l'élément à l'admin qui valide, au lieu de le rendre
   système.** `proposals.apply` écrit `owner = <valideur>` puis promeut (`proposals.py:142-145`) ;
   `ingest.promote` ne change que la portée (`ingest.py:115-122`). Avec la décision a, promouvoir
   met `owner` à `None` et garde l'auteur pour l'attribution (dans `source`), sans écraser le
   proposant.
3. **Le corpus VERSIONNÉ suit le registre à chaud** (`manifests/corpus.py:3-5`) : l'installation
   réexporte le manifeste dans `manifests/`, qui est publié avec le dépôt PUBLIC. Un modèle privé y
   serait exporté. La règle existe déjà pour deux familles — les pipelines du canvas n'y vont
   jamais, les fonctions d'utilisateur seulement à la clé explicite
   (`commands/manifest_export.py:23-26`, `:60`). Elle se généralise : **seul un élément système
   entre au corpus versionné.** ⚠ Les brouillons d'app de `manifests/app_drafts/` sont déjà
   versionnés alors qu'ils sont `private` (`writer.json`, `translator.json`) : le brouillon d'un
   utilisateur ne doit pas y atterrir.

**Ordre proposé :**
1. ✅ **Le contrat (2026-10-18).** Aucune décision d'accès ne change. Ce qui a été posé :
   - **La déclaration vit sur le REGISTRE**, pas dans `KIND_DECISION` comme proposé plus haut :
     c'est lui qui liste les éléments, et un registre neuf ne peut pas naître sans passer par
     `register()`. Chaque `Registry` déclare `provenance` (`registries.PROVENANCES` : `system`,
     `owned`, `mixed`, `aggregate`, `to_carry`). La ligne porteuse est nommée par `owner_model`, et
     la famille d'accès par `access_kind`, le lien vers `KIND_DECISION`.
   - **`register()` refuse** une provenance inconnue, et un `owner_model` sans provenance portée
     (ou l'inverse).
   - **La garde `wama/common/tests/tests_registry_provenance.py`** échoue sur :
     - un registre qui ne déclare pas sa provenance ;
     - une ligne porteuse qui n'hérite pas de `ScopedVisibility` ;
     - une famille d'accès listée par zéro ou plusieurs registres ;
     - une famille gardée « par la portée » sans éléments portés.
   - **Le budget `TO_CARRY_BUDGET` ne peut que descendre** : `models`, `apps`, `libraries`,
     `skills`, `ui_bricks`.
   - **Mesuré** : 9 registres `system` (dont les trois du monde Data), `rag` et `memories`
     `owned`, `functions` `mixed` (`UserFunction`), `licenses` `aggregate`, et les cinq du budget.
   - **Affichage** : la provenance se lit sur la page des Registres et dans `docs/dev/registres.md`.
2. ✅ **`Manifest`, la porte d'entrée (2026-10-18).** Aucune décision d'accès d'un registre ne
   change ; ce qui a été posé :
   - **Écart 1 — privé ≠ promotion demandée.** La demande est un état
     (`Manifest.promotion_requested_at`, `is_pending`) que `proposals.propose` pose et que la file
     lit (`proposals.pending`, et la vue « Valider/Rejeter » du model manager). « Rejeter » close
     la demande : la proposition d'un rôle, qui n'est à personne, sort du magasin ; le manifeste
     d'un auteur lui reste, privé.
   - **Écart 2 — promouvoir rend au système.** `ingest.promote(obj, by=…)` vide le propriétaire,
     publie, close la demande, et nomme l'auteur et le valideur dans `source` (`proposed_by`,
     `promoted_by`). L'ancienne forme `promote(obj, visibility, scopes)` ne changeait que la
     portée, et `proposals.apply` donnait l'élément à l'admin qui validait : **8 des 13**
     manifestes du magasin, passés au système par la migration `common/0030` (valideur gardé).
   - **Écart 3 — seul le système entre au corpus versionné.** `manifest_export` refuse un manifeste
     qui a un propriétaire, extrait ou autoré, `--force` compris. Mesuré avant : les 539 fichiers du
     corpus sur disque sont tous sans propriétaire ; les brouillons `app_drafts/` aussi (privés, mais au
     projet). La garde relit tout le dossier `manifests/`.
   - **Portées lisibles par le filtre commun.** `Manifest.objects` est un `ScopedManager`, et
     `scoped_visible_q` compare les portées en CODES quand le modèle les porte en clair (lu sur le
     type du champ) : aucune seconde lecture des portées.
   - **La traduction propriétaire/portée** entre enveloppe et ligne de registre vit dans
     `common/manifests/ownership.py` (`envelope_of`, `row_fields`, `is_system`), tirée du kind
     `function`, le seul qui la faisait. Son `write_back` perdait au passage la portée PROJET.
   - **Gardes** : `tests_manifest_ownership` (aller-retour, quatre comptes sur le filtre, export
     refusé, corpus relu) et trois tests de plus dans `tests_manifest_proposals`. Six
     contre-épreuves, une par brique neutralisée : toutes rouges.
   - **Ce que l'étape ne fait PAS** : aucune page ne liste encore les manifestes d'un compte ; la
     promotion d'une FONCTION d'utilisateur passe le manifeste au système, mais sa ligne
     `UserFunction` reste à l'auteur (devenir système, pour une fonction, c'est entrer au catalogue
     CODE : étape 4). ⚠ **À trancher** : le geste « Valider » reste ouvert aux comptes
     admin **et dev** (décision du 2026-09-29), là où la décision b dit « admin seul » — à régler
     avec les quatre prédicats « gérer » à unifier (`PROFILES_PERMISSIONS`).
3. ✅ **`AIModel` et ses lecteurs (2026-10-18).** C'était la famille la plus exposée à une
   fuite. Ce qui a été posé :
   - **La ligne porte la provenance.** `AIModel` hérite de `ScopedVisibility` et gagne `owner`
     (vide = système). Sa portée vaut `public` par défaut, en base aussi (`db_default`) : une ligne
     naît du disque, sans auteur. La migration `model_manager/0025` est APPLIQUÉE à la base, et
     les 794 modèles sont système.
   - **La provenance naît au geste d'installation** (décision de Fabien, même jour) : un
     administrateur installe pour le système, puisqu'il est celui qui promeut ; un développeur
     garde le modèle qu'il fait naître, privé (`model_installer.install_owner`). Seule une ligne
     APPARUE prend un auteur : un modèle déclaré par une app, ou un système réinstallé, ne change
     jamais de main (`provenance.record_after_install`). L'auteur est posé AVANT l'identité,
     donc avant le réexport au corpus.
   - **Un filtre des catalogues, un seul** : `catalogue_visible_q` (`common/models.py`). Le
     système et le public sont vus de tous, ses propres modèles et sa portée de chacun, tout de
     l'administrateur (décision c, et c'est le seul lieu où elle s'ajustera). Sans compte, seul le
     système passe. « Administrateur » veut dire ici le niveau `admin` du profil, nommé une seule
     fois (`permissions.is_admin_tier`). C'est l'une des trois définitions qui coexistent
     (`PROJECT_STATUS`, clôture du 2026-10-16), et la décision de Fabien à leur sujet se
     reportera à cet endroit.
   - **La décision unique** : `KIND_DECISION['model'] = 'provenance'`. `accessible(user, 'model',
     clé)` lit la ligne que le registre déclare (`owner_model`, et le champ neuf `owner_key`), par
     `registries.carried_rows`, la même lecture que la promotion. Le registre `models` passe `mixed`
     et sort du budget `TO_CARRY`.
   - **Les lecteurs qui listent ou tirent pour un compte filtrent par lui** :
     - `select_model(user=…)`, `get_registry_models(user=…)` et `list_models(user=…)` ;
     - le tirage « auto » des apps, qui passe le compte de l'élément (`resolve_model_choice`) ;
     - la page du catalogue, l'API des selects et sa prévision ;
     - l'assistant (`list_ai_models`, `get_ai_model`, la recherche) ;
     - le tirage de développement et celui de l'assistant outillé ;
     - la couverture de classes (`couvrir_classes(user=…)`).
   - **Les dérivations au niveau de l'app s'en tiennent au système** : ports d'entrée, méta
     d'appariement, options côté serveur et couverture affichée par l'anonymizer. Un fait d'app
     vaut pour tous ses comptes.
   - **Manifeste** : `extract` lit la provenance sur la ligne (`ownership.envelope_of`), et un
     modèle système garde exactement l'enveloppe d'avant, donc le corpus ne bouge pas.
     `write_back` ne la projette pas (sens SORTANT). Un modèle privé n'est pas une cible du
     corpus (`manifest_export._model_keys`). **Promouvoir** le manifeste rend aussi la ligne au
     système (`ownership.promote_row`, trouvée par le registre du kind, pas codée par kind).
   - **Gardes** : `model_manager/tests/tests_model_provenance` (quatre comptes face à chaque
     lecteur, naissance de l'auteur, manifeste, corpus, promotion), et deux cas de plus dans
     `tests_registry_provenance`. **Quinze contre-épreuves, toutes rouges** (huit brèches en
     mémoire, sept mutations par édition).
   - **Ce que l'étape ne fait PAS** :
     - Les lectures PAR CLÉ restent ouvertes : faits d'un modèle déjà choisi, chargement par un
       backend, gestes de gestion du model manager (admin et dev). Une clé privée TAPÉE à la main
       au lancement n'est pas refusée ; `accessible(user, 'model', clé)` est prêt, sans appelant.
     - Les tirages sans compte (alignement du transcriber, extracteur de partition du composer,
       ensemble de l'anonymizer, repli de contexte de l'assistant) ne voient que le système : un
       auteur n'y retrouve pas son modèle privé.
     - Aucun geste « Demander la promotion » à l'écran : le service existe (`proposals.propose`),
       le bouton ira avec la pastille (étape 6).
     - Aucun critère de conformité ne mesure encore les lecteurs (le `scoped_reads` des
       catalogues).
4. ✅ **Les fonctions, les pipelines du Studio — les skills restent à porter (2026-10-19).**
   Décisions de Fabien le même jour : une fonction du code dérive sa provenance de son app ; un
   pipeline enregistré est un objet de TRAVAIL ; les skills restent « à porter ».
   - **Une fonction du CODE n'a pas d'auteur à elle, elle a l'app qui la porte.** Mesuré : 93 des
     143 fonctions nomment leur app, dont 35 dans des jumelles (le générateur n'émet que des
     process `binding: app`, `function_specs_gen.py:119`). Les 50 autres sont pures et vivent dans
     `wama_data`. Leur app se lit par `function_catalog.spec_app`, la lecture qui donnait déjà leur
     monde (`ROUTE §10.6` point 6.1). La fonction est système dans une app réelle, et à son créateur
     dans une jumelle, par la décision des apps (`_app_accessible`).
   - **Une seule règle, partout.** `accessible_specs(user, specs)` sert les listes, et
     `accessible(user, 'function', clé)` sert la décision : `KIND_DECISION['function'] =
     'provenance'`.
     - Le registre `functions` nomme la ligne d'une fonction d'utilisateur (`owner_key='key'`).
     - Il nomme aussi, par le champ neuf `Registry.element_app`, l'app d'une fonction du code :
       `registries.declaring_app`, lu par `_provenance_accessible` quand l'élément n'a pas de
       ligne.
     - Lecteurs : la palette du Studio, la page du catalogue de fonctions (elle listait à tous les
       process des jumelles), le lancement d'un graphe (`launch_graph`, qui sert aussi l'assistant),
       et l'export au corpus. Depuis `492f0df6` (même jour, `§16.11` piste 4), le lancement lit la
       palette du compte (`studio/services/palette.palette_nodes`) au lieu de sa propre boucle :
       même décision pour une fonction, et en plus l'app fermée et le nœud inconnu.
     - Une fonction PURE suit l'app Django qui la contient : les 50 sont dans `wama_data`, app
       commune et non publique. Revérifié le 2026-10-19 sur les politiques réelles : tout compte
       connecté les voit (52 fonctions sans rôle, 143 pour un développeur), aucun anonyme. Avant
       l'étape, aucun filtre ne s'appliquait à elles.
   - **Retrait de la seconde provenance.** `FunctionSpec.visibility` et `owner` sont retirés : rien
     ne les remplissait, et pourtant la palette les lisait. Les 112 manifestes du corpus perdent ces
     deux clés de leur `body` (`REMOVAL_LEDGER R154`).
   - **Une fonction d'UTILISATEUR** (`UserFunction`, gagne `ScopedManager`) passe le filtre des
     catalogues : son auteur et l'admin la voient. Promouvoir son manifeste ne touche pas la ligne,
     dont le propriétaire est obligatoire (`promote_row` le lit sur le champ) : sa promotion la fait
     entrer au catalogue code, un geste de développement (écrit à l'étape 2).
   - **Un pipeline ENREGISTRÉ est porté comme une card** (`WAMA_COLLABORATION §4.7`).
     - Le modèle : `StudioPipeline(ScopedVisibility)`, migration `studio/0004` APPLIQUÉE (naît
       privé ; défaut posé aussi en base, pour le code en service). Les 2 pipelines existants sont
       privés à leur auteur.
     - Les lectures : `listable_by` / `visible_or_404` pour la liste, le détail et l'assistant
       (par son nom, le sien d'abord). La suppression par `owned_or_404`. Enregistrer sous le nom
       d'un pipeline partagé en fait sa copie.
     - Le lancement refuse un pipeline que le compte ne voit pas, et le manifeste lit la provenance
       sur la ligne (`private` y était écrit en dur).
     - L'administrateur n'y voit pas tout.
   - **Un pipeline DÉCLARÉ en code** s'ouvre si chacun de ses nœuds est accessible
     (`studio.views._declared_pipelines`). Les pipelines des jumelles se disaient système et
     publics, donc listés à tous.
   - **Skills : toujours `TO_CARRY`** (budget de `tests_registry_provenance` inchangé). Un skill
     d'utilisateur est une intention (`WAMA_LLM §0bis`, « ❌ pas de skill par utilisateur ») sans
     porteur décidé. Deux pistes lues, à trancher : le souvenir de type `procedural` (`WAMA_MEMORY
     §11`, déjà propriétaire et portée), ou une ligne propre que le résolveur
     (`prompt_skills.resolve_skill`) lirait avant les fichiers.
   - **Constat corrigé** : la ligne « `FunctionSpec.visibility/owner` … jamais filtrés » du relevé
     ci-dessus était FAUSSE dès son écriture. La palette lisait le champ depuis le 2026-09-09
     (`061439cc`), et le commentaire du code le disait « sans lecteur » depuis le 21/09.
   - **Gardes** : `common/tests/tests_function_provenance` (10), `common/tests/tests_pipeline_provenance`
     (8), un cas de plus dans `tests_registry_provenance` ; le faux compte de
     `studio/tests_declared_pipelines` porte désormais un profil (le point d'accès décide). **Quinze
     contre-épreuves, toutes rouges** (neuf brèches en mémoire, six mutations par édition).
   - **Ce que l'étape ne fait PAS** :
     - Aucun geste « Partager » pour un pipeline : la nature n'est pas déclarée au geste commun
       (`WAMA_COLLABORATION` marche 3).
     - ~~Un nœud que la palette ne connaît pas disparaît en silence à l'ouverture d'un pipeline
       (relevé par une autre session, `ROADMAP §16.11` piste 4). L'étape le rend plus probable,
       puisqu'un pipeline pourra être partagé : à corriger AVANT le geste « Partager ».~~
       ✅ **Soldé le 2026-10-19 (`492f0df6`, autre session, GO de Fabien)** : le canvas garde le
       nœud, marqué indisponible, avec ses réglages et ses liens, et le lancement le refuse en le
       nommant (`§16.11` piste 4).
     - Une fonction d'utilisateur se crée toujours dans l'admin seule.
5. Les briques UI d'utilisateur et les jumelles : la provenance déclarée, et la promotion par
   déplacement vers `common/`.
6. La pastille et la facette.

Relation avec S3 (`AccessGrant`, `PROFILES_PERMISSIONS §8.7`) : S3 répond à « qui a le droit »,
ce chantier répond à « à qui c'est ». Les deux se composent dans `accessible()`, et aucun ne
remplace l'autre.
