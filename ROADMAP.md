# WAMA — Roadmap

> Dernière mise à jour : 2026-07-20 (Horizons + GNM ; **dédoublonnage exécuté** : sections actées → archive + renvois PROJECT_STATUS, bugs §0 → PROJECT_STATUS). Précédent : 2026-07-11 (audit conformité — PROJECT_STATUS §31 ; l'en-tête « 2026-05-16 » mentait, le contenu allait jusqu'à 2026-07-01)
> Légende : ✅ Fait · 🔄 En cours · ⏳ Planifié · 💡 Proposé · ❌ Abandonné · 🐛 Bug bloquant

---

## Horizons — boussole de priorités (2026-07-20)

> Hiérarchise TOUT le document par horizon pour ne pas s'éparpiller. Vision + statut vision ↔ code :
> `docs/WAMA_VISION_COMPLET.md` (document unique depuis 2026-08-27 ; marquage ✅/🔄/⏳ par section,
> non-objectifs en Partie 13). En cas de conflit avec une priorité plus ancienne citée ailleurs dans ce
> fichier, CETTE section fait foi.
>
> **Rôles des documents de suivi (contrat 2026-07-20, amendé 2026-08-27)** — chaque info vit à UN
> seul niveau, les autres pointent : **Vision** (`docs/WAMA_VISION_COMPLET.md`) = le cap, horizon
> années, avec un marquage d'état GROSSIER par section (l'ex-VISION_STATUS, fusionné) ; **ROADMAP**
> (ce fichier) = les chantiers macro et leur ordre, horizon trimestres ; **PROJECT_STATUS** = l'état
> d'avancement au jour le jour (fait/en cours/détails). Le dédoublonnage à venir = redescendre au
> bon niveau ce qui a dérivé (statuts et checklists détaillées présents ici → PROJECT_STATUS).

### H1 — Maintenant (finir avant d'ouvrir quoi que ce soit)
1. Consolidation des mécanismes d'UI + port schéma-driven des 5 apps restantes
   (enhancer, anonymizer, synthesizer, imager, avatarizer) — LE goulot qui gate manifestes,
   génération d'apps et prospection Phase B.
2. Transcriber 100 % (gold standard) + extraction des dernières briques communes.
3. Studio — suites V1 : sorties → filemanager studio, specs montage/mixage (runners : 10/10 apps
   génériques sur le runner générique depuis 2026-07-13, cf. PROJECT_STATUS §37.10 ; restent les
   apps wama_lab).
4. Cam Analyzer Phase 3 (calibration vitesses) — livrable labo concret.

### H2 — Ensuite (dès H1 stabilisé)
1. Fondation RAG **mono-niveau** (`wama/rag/`, ChromaDB + bge-m3, branchée sur l'étape `enrich`) —
   la hiérarchie univ/labo/équipe attendra la preuve d'usage.
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
  URLs, VRAM, pièges) : [`docs/PROSPECTION_AVATARS_2026-08-17.md`](docs/PROSPECTION_AVATARS_2026-08-17.md).**
  Deux cas, deux podiums :
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

---

## 0. Dysfonctionnements connus — À corriger en priorité

> Niveau statut → suivi déplacé dans `PROJECT_STATUS.md` § « Bugs / dettes connus »
> (contrat des niveaux, 2026-07-20). Contenu d'origine archivé : `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

## 1. Conformité UI — WAMA App Conventions

> Référence : `WAMA_APP_CONVENTIONS.md` · Règle : ordre boutons `[⚙ Params] [▶ Start] [⬇ DL] [⧉ Dup] [🗑 Del]`

### 1.1 Bouton Dupliquer

✅ Toutes les apps (vérifié ; Composer confirmé 2026-07-03). Table figée archivée :
`docs/archive/ROADMAP_ARCHIVE_2026-07-20.md` — source vivante : `/apps/`.

### 1.2 Features transversales manquantes
| Feature | Statut | Apps concernées |
|---------|--------|-----------------|
| Import dossier récursif | 🔄 | ✅ Upload de dossier FileManager (webkitdirectory, filemanager.js:1516) + montages locaux/distants (fix CIFS 2026-07-20). **Architecture cible (Fabien 2026-07-20)** : monter un dossier (local ou serveur) puis « Envoyer vers » une app AVEC sous-dossiers depuis le filemanager — pas de zone de dépôt par app ; le studio doit pouvoir consommer ces dossiers. Reste : « Envoyer vers » récursif (dossier entier), et (moins prioritaire) drag & drop de dossier |
| **Zone de staging (« À valider »)** | ⛔ **SUPPRIMÉE** | Décision 2026-06-29 (CARD_DESIGN §8.5) : PAS de staging — la card « nouveau » remplace ce besoin. Cette ligne annonçait à tort une généralisation à 9 apps (corrigé 2026-07-11). |
| **Transcriber — correction manuelle assistée IA** (éditeur onde + heatmap) | 🔄 Phase 1 LIVRÉE | Référence : **`wama/transcriber/TRANSCRIBER_CORRECTION.md`** (inspiré Whispurge/Sonal). Livré : page `/transcriber/edit/<pk>/` + save_correction/save_meta/suggest_speakers/waveform_peaks (`urls.py:29-33`), champs `corrected_segments_json`+`correction_status` (migration 0010), cohérence par segment pour la heatmap. Reste : Phase 2 heatmap (cf. doc de référence). **Fait aussi** : défaut ASR VibeVoice→**Whisper large-v3** (artefact d'ordre, pas benchmark ; diarisation=pyannote ; 10<16 GB) + **word_timestamps** conservés en mémoire/segment (non persistés — pas de `words_json`, cf. §8 Phase 1). À évaluer : WhisperX/Canary-Qwen-2.5B/Granite 3.3 ; réparer Qwen3-ASR. Mener le transcriber au bout avant généralisation. |
| **Architecture UI « card-centric »** (card auto-suffisante + volet droit = inspecteur) | 🔶 Décidée | **Décision projet 2026-06** : voir **`CARD_DESIGN.md`** (§1quinquies preview 3 niveaux + §8.6 zones de dépôt — absorbe `CARD_CENTRIC_UI.md`, archivé `docs/archive/` 2026-07-25). Livré depuis : preview 3 niveaux (1ᵉʳ consommateur transcriber), volet=inspecteur généralisé (5 apps portées, PROJECT_STATUS §21). **Reste** : preview complète dans le volet, sélection en-têtes batch, généralisation aux 5 apps non portées. |
| **Drag & drop appartenance batch** (entrer/sortir une carte d'un batch) | ⏳ UI seule | Backend COMPLET + validé 2026-06-29 (`remove_from_batch`/`reorder`/`move_to_batch`/`consolidate`) ; reste l'UI SortableJS — vérifié 2026-07-20 : seul un commentaire l'annonce (`transcriber/static/transcriber/js/index.js:172`) |

> Lignes ✅ archivées : `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md` — conformité vivante : `/apps/` (`get_conformity_summary`).

---

## 2. Refactoring — Unification `common/`

> Principe : tout code utilisé par >1 app va dans `wama/common/`. Zéro duplication.

| Élément | Statut | Fichier cible | Impact |
|---------|--------|--------------|--------|
| `keep_loaded` singleton pattern | ⏳ | Généraliser depuis Reader (olmOCR) | Describer, Enhancer (Transcriber sorti de la liste : délégué à `select_model()` depuis 2026-07-24) |


> Briques ✅ archivées (`docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`) — registre vivant :
> `WAMA_APP_GENERATION_ROUTE.md` (l'ancien `COMMON_REFACTORING.md` y est consolidé, archivé `docs/archive/`).
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

Bloc d'état 2026-07-11 archivé (`docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`). Corrections vérifiées 2026-07-20 :
- `UI_MECHANISMS_CONSOLIDATION.md` archivé (`docs/archive/`, 2026-07-22) — consolidé dans
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
> Détail d'implémentation archivé : `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`. Reste ouvert (repris tel quel) :

### Phase 5 — Connecteurs avancés (restants) ⏳
- Unsplash · ccMixter (musique CC) · Mozilla Data Collective (voix, si API stable)
  — Pexels/Openverse retirés : livrés (PROJECT_STATUS §9)

### Phase 6 — Intégration cross-apps ⏳
- Imager : sélecteur image de style depuis médiathèque
- Avatarizer : sélecteur portrait de référence

## 4. Intégrations modèles AI — Ollama

> ✅ **Livré** (modèles installés, sélection par tier, wama-dev-ai opérationnel) — état vivant :
> `PROJECT_STATUS.md §2/§3`. Détail archivé : `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

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

> **Restes repêchés du handoff `REPRISE_2026-08-04`** (archivé 2026-08-18, `docs/archive/`) —
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
   par **avatarizer** (MuseTalk, CodeFormer) ✅ 29/07. Reste le **service TTS**, dont la
   déclaration doit venir de l'intérieur du service (son modèle reste résident entre deux
   appels). Cf. `PROJECT_STATUS.md` §0 (3bis → 3quinquies).

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
- [x] CLAUDE.md enrichi (règles UI + section wama-dev-ai)
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
  dans `docs/archive/VISION_STATUS.md` annexe + mémoire projet)
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
par défaut, zéro breaking change. Détail archivé : `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

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
  labo SHS), puis *gratuit d'abord* (`local → cloud free → cloud payant`, arbitrage Fabien),
  puis *capacité* (contexte/VRAM saturés → escalade cloud, dont `_route_model_by_context` est
  déjà l'embryon local) ; ④ override utilisateur `auto` par défaut (patron `resolve_auto_model`
  de l'imager). ⚠ Le choix manuel est un **override**, jamais le mécanisme principal.
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

### Phase 3 — MCP Server WAMA 💡 (long terme)

**Concept :** Exposer les outils WAMA comme serveur MCP pour clients compatibles
(Claude Code, Claude Desktop, IDEs). Distincts de LiteLLM — MCP = protocole d'outils,
pas un routeur LLM.

> ⚠ **Ce que MCP ne résout PAS** (question tranchée le 2026-08-20) : « lancer une requête à
> Claude Code depuis l'AI-Assistant » ne passe **pas** par MCP. `claude mcp serve` n'expose que
> les *outils* de Claude Code (Bash/Read/Edit…), **pas sa boucle d'agent** — l'orchestration
> resterait à notre charge. Le chemin est `claude -p` headless / Agent SDK avec le token
> d'abonnement (§19.3). MCP côté WAMA garde sa valeur propre : faire de **WAMA un serveur**
> d'outils pour des clients tiers — l'inverse du besoin ci-dessus, et complémentaire de
> `/api/v1/tools/` qui expose déjà les mêmes 48 outils en HTTP+token.

Exemples d'outils exposables :
- `wama_transcribe(file_path)` → lance une transcription WAMA
- `wama_describe(file_path, format)` → description d'un fichier via le Describer
- `wama_search_media(query)` → recherche dans la Médiathèque
- `wama_rag_query(question, collection)` → Q&A RAG sur un corpus WAMA

Stack : `mcp` Python SDK (officiel Anthropic) + `uvicorn` SSE server (port dédié)

---

## 9. cam_analyzer (wama_lab)

### 9.0 Restes repêchés du handoff `REPRISE_2026-07-29` (archivé 2026-08-18, `docs/archive/`)

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
`docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

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


> Phases ✅ archivées : `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md` — état vivant : `PROJECT_STATUS.md §5`.

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

C'est le cadre au-dessus des deux frontières : `CLAUDE.md` § « la LANGUE des identifiants » en est
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

⚠ **Ce n'est PAS la frontière tranchée par `CLAUDE.md` § « la LANGUE des identifiants »** (« qui
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
> Spec d'origine archivée : `docs/archive/ROADMAP_ARCHIVE_2026-07-20.md`.

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
- **CCR / Kilo — alerte facturation** : « BYOK / zero markup » = paiement **au token** (pas l'abo Pro fixe). Vérifier l'auth Anthropic (clé API facturée vs passthrough abonnement) **avant** de migrer. Sinon : Claude Code pour Claude, CCR/Kilo réservés à Codex-UGE / locaux gratuits. Kilo = plugin **JetBrains** ; OpenClaw (agent planifié Slack/…) + revue PR = les briques « à construire » existent en produit → tester sur une tâche de veille secondaire avant d'arbitrer maison vs produit.
- **ollama-mcp** : préférer le fork **hyzhak/ollama-mcp-server** (NightTrek peu actif). N'a de sens que pour laisser Claude déléguer une sous-tâche à un modèle local **en pleine session** ; sinon un seul chemin vers Ollama.
- **LM Studio** : redondant avec Ollama pour le service ; à garder comme **bac à sable** d'exploration manuelle, pas comme composant servi.
- **MemPalace** : promesses contestées publiquement (« +34 % recall » = filtrage métadonnées classique ; « 30x sans perte » = ~12 % de perte de récupération mesurée). = **confort** (mémoire inter-sessions), pas brique critique ; Headroom couvre déjà ce besoin.

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
- **« Télécharger tout » multi-format** : `download_all?format=` (txt/srt/pdf/docx) via le helper partagé `_build_transcript_bytes` ; bouton transformé en dropdown.
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

**Existence vérifiée** (recherche web) : MIT, sorti fév. 2026, ~46k stars, v0.18.2 en juillet.
Runtime d'agent auto-hébergé, sans télémétrie, mémoire persistante inter-sessions, **skills générés
depuis l'expérience** dans `~/.hermes/skills/`, plugins découverts via `entry_points`/`~/.hermes/plugins/`,
LLM-agnostique (tout endpoint compatible OpenAI). Le « MCP natif » annoncé par certaines sources
**n'a pas pu être confirmé** — à vérifier avant de s'appuyer dessus.

**Ce qui est retenu / ce qui est écarté** — il faut séparer deux objets :

| Couche Hermes | Verdict | Pourquoi |
|---|---|---|
| **Runtime** (boucle, backends d'exécution Docker/SSH/Modal, ~20 passerelles de messagerie) | **ÉCARTÉ en prod** | WAMA a déjà Django+Celery+`resource_governor` (domicile UNIQUE GPU/CPU/RAM). Un 2e ordonnanceur lançant de la charge GPU à côté du gouverneur = corps étranger (cf. 4 kernel panics WSL2 du 29/07). Les passerelles de messagerie sont hors sujet. |
| **Mémoire procédurale** (distiller une tâche résolue en skill réutilisable) | **IDÉE RETENUE** | C'est le seul apport réel. `common/prompt_skills/` est **déjà** le format de stockage ; ce qui manque n'est pas le dossier mais **l'écrivain** (rien ne génère ces fichiers depuis l'expérience). |

**Point LiteLLM** — LiteLLM est documenté comme provider de référence côté Hermes (proxy
OpenAI-compatible, ~100 fournisseurs, load balancing, fallback, contrôle budgétaire). Câblage :

```yaml
model:
  default: <nom-du-modele>
  provider: custom
  base_url: http://localhost:4000/v1
  api_key: <clé-ou-vide-en-local>
```
Bascule en cours de session à 3 niveaux : `/model custom:local:qwen-2.5`,
`/model custom:work:llama3-70b` → le routage LiteLLM local+cloud existant (§8d) reste inchangé, on
change juste de modèle selon la tâche.

⚠ **DEUX RÉSERVES — ne pas répéter la formule « un seul catalogue à maintenir », elle est fausse
aujourd'hui :**
1. **Bug ouvert sur ce couplage précis** : Hermes + endpoint OpenAI-compatible custom via LiteLLM sur
   `localhost:4000` ⇒ **les requêtes du gateway n'atteignent pas l'endpoint**. Reproductible par
   config CLI, fichier de config, ou `HERMES_INFERENCE_PROVIDER=custom`. Signalé sur v2026.4.3
   (peut-être corrigé sur `main`). Le chemin de code affecté semble être le **gateway
   (mode messagerie/API)** — **pas** le mode **CLI/TUI**. ⇒ **tester en TUI d'abord**, gateway
   seulement après vérification.
2. **Pas d'auto-découverte** : le sélecteur `/model` n'affiche que les modèles **listés manuellement**
   dans le `config.yaml` d'Hermes. Ajouter/retirer un modèle côté LiteLLM ⇒ **mise à jour manuelle**
   de la config Hermes. L'objection « énième config modèles à tenir à jour » n'est donc **PAS levée** —
   elle est seulement *réductible*, en générant ce `config.yaml` depuis le catalogue `AIModel`.

**Découverte de plugins Hermes — 4 sources** (vérifié sur la doc du dépôt, 2026-07-30) : **bundled**,
`~/.hermes/plugins/` (user), `.hermes/plugins/` (projet), et les **`entry_points` pip**. C'est la 3e qui est le vrai point d'accroche : le registre WAMA peut
**piloter la génération des `entry_points` exposés à Hermes**, avec correspondance directe
`fonctions_exposées` → outils découverts par Hermes. (Il ne s'agit donc pas d'un symlink de
manifestes mais d'une génération de points d'entrée.)

**Débat capacités** (recadrage utilisateur, retenu) : la philosophie WAMA **est** l'agrégation de
capacités, et le mécanisme de plugins d'Hermes relève de la même logique — l'objection initiale
« corps étranger » ne vaut que pour le runtime, pas pour l'agrégation. **Convergence** : le registre
WAMA reste **source unique** ; les manifestes de plugins Hermes sont **générés depuis lui**, jamais
saisis en double. Deux consommateurs (UI WAMA + Hermes), un seul inventaire.

**Manifeste ≠ registre — articulation WAMA** (corrige une inversion commise en séance) : le
**manifeste est le point d'entrée** de toute nouvelle capacité (1 manifeste = 1 unité : une lib, un
modèle, une app) ; les **registres** (`model_manager`, `app_registry`, `TOOL_REGISTRY`) maintiennent
la connaissance en base et servent les pages de gestion. Les deux coexistent — le kind ne remplace
pas le registre, il en décrit l'unité. ~~Il manque donc **les deux** côté librairies~~ **FAIT
(2026-08)** : le registre `common.models.Library` (né de la projection `write_back_library`,
migration 0004) ET le kind `library` existent (1er lien transcriber→faster-whisper).

**Registres — état réel (mis à jour 2026-08-11, deux « fonctions » à NE PAS confondre)** :
modèles (`AIModel`/`model_registry.py`) ✅ · apps (`app_registry.py`/`APP_CATALOG`) ✅ ·
**outils assistant** (`TOOL_REGISTRY`/`tool_api.py` — surface de PILOTAGE des apps, facette F6) ✅ ·
**fonctions DATA** (fonctions-cartes appliquées aux données, ex. cam_analyzer :
`common/catalog/function_catalog.py::FUNCTION_CATALOG` + `UserFunction` DB scopée — kind `function`
les EXTRAIT, page `/model-manager/functions/`) ✅ ·
bibliothèques (`common.models.Library` + kind `library`) ✅.
~~⚠ Trou write-back côté fonctions data~~ **FERMÉ (2026-08-11 soir)** : `write_back_function`
projette un manifeste `function` `binding=user` vers `UserFunction` (idempotent, owner résolu,
tag `_manifest-gen` bornant la révocation — une fonction autorée en UI n'est jamais retirée) ;
les fonctions `pure`/`app` du catalogue code restent du code-gen.
~~Ce qui manquait côté librairies : la PAGE~~ **PAGE LIVRÉE (2026-08-11 soir, signalée le
matin)** : `/model-manager/libraries/` (patron `function_catalog` — cards du registre +
installation MESURÉE live `importlib.metadata`, dérive vs `pip_spec` signalée, `is_allowed`
lisible) + entrée « Librairies » au menu utilisateur. La page LIT le registre ; `is_allowed`
se décide dans l'admin (allowlist hors write-back, verrou n°2 Hermes) ; le bouton
d'installation viendra avec le provisionneur (plan → validation humaine →
`apply_patches.py` en post-étape).

Besoin réel : savoir **quelle app dépend de quelle librairie** (`opencv`, `ffmpeg-python`…), ce qui
casse si on met à jour, et **quel environnement a quelle version** (dev/prod, machines différentes —
un `pip freeze` ne répond qu'à la 3e question, sur une seule machine).

**Deux couches à ne pas confondre :**

| Couche | Contenu | Maintenance |
|---|---|---|
| **1. Inventaire technique** | version installée par environnement, dérive entre machines | **AUTOMATISABLE** — `importlib.metadata.distributions()` + cron de détection de dérive |
| **2. Couche capacités** | à quoi sert la lib, qui en dépend, ce qu'elle expose | **MANUELLE — c'est celle qui a de la valeur** |

Schéma d'entrée (couche 2) :
```yaml
- nom: opencv-python
  version_min: "4.9"
  catégorie: vision
  apps_dépendantes: [cam_analyzer, anonymizer, avatarizer]
  fonctions_exposées: [lecture_video, détection_contours]
  criticité: haute
  dernier_audit: 2026-07-29
  licence: Apache-2.0        # ex. pandas → BSD-3 ; utile pour un labo public
```

Justification WAMA-spécifique en plus de « qui dépend de quoi » : les champs `version_min` +
`criticité` + un patch associé serviraient directement `patches/apply_patches.py` (patches venv
perdus silencieusement au `pip install --upgrade`), les pins connus (`setuptools<81`, torchcodec
cassé, xformers/torch 2.9) et la charpente de tests nocturnes.

**Boucle** : c'est le manifeste — pas Hermes — qui est la source. Une fois `apps_dépendantes` et
`fonctions_exposées` remplis, ils alimentent à la fois l'UI WAMA et la génération des `entry_points`
consommés par Hermes. Sans eux, un agent qui « auto-maintient les libs » travaille à l'aveugle.

#### Confrontation Hermes ↔ WAMA (vérifiée sur code + doc du dépôt, 2026-07-30)

**Convergence de formalisme** : Hermes impose lui aussi un **manifeste par plugin** (YAML, « Step 2:
Write the manifest », « Manifest declares what the plugin is ») avec un champ **`kind`** discriminant
(`kind: platform` pour un adaptateur de gateway ; `kind: exclusive` auto-détecté pour un fournisseur
de mémoire, routé via `memory.provider` au lieu de `plugins.enabled`). Deux équipes ont convergé vers
l'union discriminée. Découverte par **scan** des 4 sources, registre peuplé à l'exécution par
`ctx.register_tool()` (collisions refusées sauf `override=True`).

**Renversement source/dérivé — le point structurant :**

| | Source de vérité | Dérivé |
|---|---|---|
| **WAMA** | le **manifeste** (cible architecturale) ; **en pratique le registre** pour 5 kinds/6 | manifeste via `extract` |
| **Hermes** | le **manifeste** (fichier disque) | le **registre**, reconstruit par scan à chaque démarrage |

⚠ **État réel de la projection WAMA (vérifié dans `builtin/*.py`, pas seulement dans la doc)** :
`app` = seul kind avec `project`/`un_project` ; `function` a `project=None` ; `model`, `pipeline`,
`project`, `dataset` n'ont **aucune** projection. Soit **1 kind sur 6**, et côté `app` une seule
facette (`access` → `AppAccessPolicy`) en **dry-run par défaut** (`apply=False`). Autrement dit : le
formalisme, l'enveloppe et l'ingest sont là, **c'est la projection qui manque** — un manifeste de
modèle ne crée aujourd'hui aucun `AIModel`.

**Pourquoi c'est plus dur chez nous que chez eux** : le registre d'Hermes est **éphémère** (rebâti par
scan au démarrage) ⇒ rien à écrire en retour, ni idempotence ni réversibilité à garantir. Nos
registres sont des modèles Django **persistés et vivants** qui servent les pages de gestion ⇒ la
projection doit être idempotente **et** réversible. **Notre difficulté est la contrepartie de notre
persistance**, pas un retard de travail.

**Modèles — Hermes ne le fait PAS.** Son plugin modèle est `register_provider(ProviderProfile(...))`
(+ `auth_type`) : il ajoute un **fournisseur**, pas un catalogue ; et `/model` n'affiche que ce qui est
écrit à la main dans son `config.yaml`. ⇒ **`AIModel`/`model_registry.py` est en AVANCE sur Hermes.**
Ne pas aller y chercher une solution qui n'existe pas.

**Librairies — Hermes le fait réellement**, via `tools.lazy_deps.ensure(...)` (install à la première
utilisation), avec **4 verrous superposés à transposer** :
1. **Kill switch global** `security.allow_lazy_installs: false` ⇒ `FeatureUnavailable` + indice de
   remédiation, et le plugin doit **se dégrader proprement** (erreur retournée, pas de crash de la
   boucle d'outils) ;
2. **Allowlist `LAZY_DEPS` en dur dans l'arbre** — motif cité : *« prevents a malicious config from
   coaxing Hermes into installing arbitrary packages — only specs Hermes itself ships are eligible »*
   (la config utilisateur ne peut pas élargir le périmètre) ;
3. **PyPI par nom uniquement** — ni `--index-url`, ni `git+https://`, ni `file:` ;
4. **Pin PEP 440 dans l'entrée d'allowlist** (`"my-sdk>=1.2,<2"`).
Les plugins **tiers** sont volontairement **exclus** de l'auto-install (extras
`[project.optional-dependencies]`) ; le lazy-install ne sert qu'aux plugins *bundled*.

⚠ **Transposer les VERROUS, pas le CYCLE DE VIE.** Hermes installe *à la première utilisation*,
capacité jetable, optimisé pour « ne jamais être bloqué par une dépendance manquante » — modèle
d'assistant personnel. WAMA est un **outil de labo** : l'ingestion est **progressive et cumulative**,
une capacité ingérée **reste intégrée**. On n'installe/désinstalle pas au fil de l'eau. Le moment de
l'installation est donc **l'ingestion du manifeste** (une fois, sous validation), pas l'appel d'outil.
Raison de fond : **reproductibilité scientifique** — un résultat de recherche doit rester
re-productible des mois plus tard, ce qu'un parc de dépendances volatil rend impossible. C'est ce qui
justifie `version_min`, les pins et `dernier_audit` : traçabilité de l'état d'environnement, pas
seulement hygiène.

**Trois protections supplémentaires à voler** : (a) **`requires_env`** dans le manifeste — conditionne
le chargement à des variables d'env, **demandées interactivement** à l'installation et écrites dans
`.env`, avec description + URL d'inscription (utile vu l'externalisation des secrets) ; (b)
**`pre_tool_call`** peut retourner `{"action": "block"}` (veto) ou `{"action": "approve"}` (**escalade
vers validation humaine**) = notre doctrine « l'agent propose, l'humain valide » câblée dans le
runtime ; (c) **aucune porte dérobée** — `ctx.dispatch_tool()` passe par *« the normal approval,
redaction, and budget pipelines — not a shortcut around them »* ⇒ toute capacité ajoutée par
manifeste doit passer par le `resource_governor` et le chemin de permission normal, sans exception
privilégiée.

**Recommandation — `library` = kind PILOTE du manifeste-first**, parce qu'il n'a **aucun registre
hérité à réconcilier** : son registre naîtrait *de* la projection au lieu de la précéder. C'est un
terrain vierge pour prouver la chaîne manifeste → ingest → registre → capacité → studio, avant
d'attaquer la projection des 5 kinds hérités.

⚠ **NE PAS importer le régime Hermes ici** — le registre éphémère « recalculé à la lecture » viole la
**propriété de sûreté `WAMA_MANIFEST_SPEC.md` §2.1** (*rien ne lit le manifeste en direct ; ingest =
seul pont gaté ; état committé = les registres ; un manifeste corrompu ou supprimé ne corrompt pas
l'aval*). Hermes peut se le permettre parce qu'un plugin absent ne casse qu'une capacité optionnelle ;
chez nous un registre volatil casserait les pages de gestion. ⇒ `library` obtient un **vrai registre
persisté, écrit par l'ingest** comme les autres kinds. L'avantage du terrain vierge subsiste (rien à
rattraper), la garantie de sûreté aussi.

⚠ Non vérifié : nom de fichier exact et liste complète des champs du manifeste de plugin Hermes, et
nom du groupe d'`entry_points` (le site coupe la connexion ; lu via le dépôt uniquement).

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
   dupliqués (`anonymizer/core/sam3_processor.py` + `cam_analyzer/utils/sam3_road_analyzer.py`,
   dont l'import cross-app l.126 est une dette). LocateAnything = backend supplémentaire.
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
`anonymizer/core/anonymize.py` porte désormais un moteur *un décodage, N modèles, union des zones
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
`anonymizer/core/blur_utils.py`, à E/S typées. L'*anonymisation* n'est pas une fonction : c'est
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
2. **Médiathèque** : ingest + preview des objets 3D (viewer three.js **vendorisé local**, règle
   pas-de-CDN) ; collecte dans la médiathèque D'ABORD.
3. **Port studio `object_3d`** (DataType) pour câbler detector → 2D→3D → médiathèque.
4. **Manifeste `function` « image→3D »** + backend (contrat `BaseModelBackend`).
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
`docs/PROSPECTION_AVATARS_2026-08-17.md` (12+ candidats, licences vérifiées au fichier ;
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

### 19.2 Notifications proactives — gain rapide, indépendant du bot ⏳

`notify_job()` (`common/utils/notifications.py`) est déjà LE point unique appelé par toutes
les apps en fin de tâche. Y brancher un fan-out vers les canaux (en plus de l'email) donne
« ✅ transcription terminée + fichier » en DM — **sans toucher une seule app**, et sans
polling. À faire dès que l'appariement d'identité existe.

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
  - ⚠⚠ **Coût de base élevé** : « réponds uniquement OK » → `total_cost_usd ≈ 0,99` en 3,3 s,
    parce que Claude Code charge le **contexte du projet** (CLAUDE.md + arborescence) à chaque
    invocation. Le coût dépend donc du **dépôt**, pas de la longueur de la question : réserver
    l'outil aux tâches qui valent ce contexte (audit, cartographie), pas au bavardage.
  - Sécurité : **lecture seule par défaut** (`Read/Grep/Glob`) ; `write=True` sur intention
    explicite ; garde **écrite dans le corps de la fonction** et non dans le gating d'app (un
    outil sans app est autorisé à tous) ; les **deux vocabulaires de rôle** sont acceptés
    (groupes `dev`/`developpeur`, tiers `developpeur`/`admin` — homonymes trompeurs).
- **Contexte historique — VÉRIFIÉ POSSIBLE le 2026-08-20** (ça ne l'était pas lors du premier examen) :
  depuis juin 2026, l'usage programmatique par le titulaire de l'abonnement est supporté et
  couvert par les CGU, avec un crédit mensuel dédié qui n'entame pas l'usage interactif.
  Chemin : `claude setup-token` (token OAuth) → `claude -p "…" --output-format json` en
  headless, ou le **Claude Agent SDK** Python.
  ⚠ **MCP n'est PAS le levier ici** : `claude mcp serve` n'expose que les *outils* de Claude
  Code (Bash/Read/Edit…), pas la boucle d'agent — l'orchestration resterait à notre charge.
  ⚠ Bug connu : le refresh du token OAuth échoue en non-interactif (~10-15 min) → découper en
  invocations courtes plutôt qu'une session longue.

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

> **Doc de référence du domaine : [`LICENSING.md`](LICENSING.md)** (politique, licences
> traversées, code vendorisé, procédure de dépôt, §7 = décisions en attente). Cette section
> ne porte que **l'état du chantier** — ne pas y recopier la politique, elle divergerait.
> La vue **mesurée** reste la page `/common/licences/` (`common/services/license_audit.py`).

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
   vendorisé** (`static/vendors/`, `avatarizer/codeformer/` = **NTU S-Lab NON COMMERCIAL**)
   a dû être inventorié à la main. Le rattacher au registre `Library` le rendrait mesuré.
