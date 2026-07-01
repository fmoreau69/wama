# WAMA — Roadmap

> Dernière mise à jour : 2026-05-16 (cam_analyzer Propositions A→F + Converter modal Paramètres item + profils sauvegardables)
> Légende : ✅ Fait · 🔄 En cours · ⏳ Planifié · 💡 Proposé · ❌ Abandonné · 🐛 Bug bloquant

---

## 0. Dysfonctionnements connus — À corriger en priorité

| Composant | Symptôme | Statut | Piste |
|-----------|----------|--------|-------|
| **Qwen3-ASR** (Transcriber) | Backend implémenté (`qwen_asr_backend.py`) mais non fonctionnel — erreurs de dépendances à l'import | 🐛 Bloqué | Résoudre conflits deps pip (transformers, torchaudio, accelerate) |
| **Higgs Audio V2** (Synthesizer) | Audio généré inaudible, artefacts, bruits de fond — modèle inutilisable | 🐛 Bloqué | Nombreux patches appliqués + CUDA graphs désactivés (voir memory/). Prochaine étape : test sans voice reference pour isoler |
| **Prétraitement audio** (Transcriber) | L'ancien pipeline (pydub + `noisereduce`/spectral-gating) dégradait l'ASR | ✅ Corrigé | Remplacé par débruitage IA **DeepFilterNet** (singleton keep_loaded partagé avec l'enhancer) + format ASR 16k mono. Optionnel, défaut OFF (Whisper robuste au bruit). Resemble Enhance possible en option « restauration » (générative, peut altérer l'ASR) — non câblé |

---

## 1. Conformité UI — WAMA App Conventions

> Référence : `WAMA_APP_CONVENTIONS.md` · Règle : ordre boutons `[⚙ Params] [▶ Start] [⬇ DL] [⧉ Dup] [🗑 Del]`

### 1.1 Bouton Dupliquer
| App | Statut | Notes |
|-----|--------|-------|
| Transcriber | ✅ | views.py + urls.py + template + JS |
| Synthesizer | ✅ | single + batch |
| Reader | ✅ | |
| Composer | ✅ | |
| Anonymizer | ✅ | |
| Describer | ✅ | |
| Imager | ✅ | |
| Enhancer | ✅ | image + audio (single + batch) |

### 1.2 Features transversales manquantes
| Feature | Statut | Apps concernées |
|---------|--------|-----------------|
| ETA (barre de progression) | ✅ | Carte + globale + batch — toutes les apps (moteur commun `WamaEta`) |
| Auto-refresh filemanager (ajout input + sortie + suppression) | ✅ | **Commun** : `WamaFM` (`media:uploaded`/`processed`/`deleted`) + poll mtime non bloquant. **Triggers instantanés posés sur TOUTES les apps** (audit conventions §8). |
| Consolidation import multi-fichiers → batch | ✅ | converter, reader, transcriber, describer, enhancer, **anonymizer** (+ DnD filemanager multi-fichiers) ; composer/synthesizer = N/A (pas d'import média) |
| Mode batch anonymizer (groupes + consolidation) | ✅ | Modèles existants + `consolidate`/`_auto_wrap_orphans` + rendu groupé `media_table.html` + suppr. batch. Traitement reste global (pas de start par-batch) |
| Import dossier récursif | ⏳ | Toutes les apps acceptant des fichiers |
| Download All (ZIP) | ✅ | Composer |
| Drag & drop zone | ✅ | Imager (prompt image, style ref, img2vid, description) |
| Parité batch UI (⚙ batch + ⚙/⧉ par item + duplication in-batch) | ✅ | **Terminée** : transcriber, reader, synthesizer, describer, composer, enhancer, converter, anonymizer (⚙ batch = global). Group-by-nature commun (converter/describer/enhancer/anonymizer). Cf. conventions §9.8/§9.9. |
| **Phase B — Format batch unifié à balises** (`-i/-p/-r/-o`) | ✅ | Parseur commun `parse_unified_batch` + détection legacy + **`BATCH_FORMAT.md`**. **Câblé partout** : apps Type A (reader/describer/transcriber/converter/anonymizer/enhancer) via `parse_media_list_batch` rendu balise-aware (`-i`→path, `-o/-p/--opt` transportés) ; **imager** (`-p`→prompt, `--steps/--cfg/--model/--np`…) ; **synthesizer** (`-p`→texte, `--voice/--speed/-r/--language`) ; **composer** (réf. : auto-modèle musicgen-melody si `-r`) ; **avatarizer** (nouveau système de lots `BatchAvatarJob` + import par fichier balise + group-by-nature pipeline/standalone + UI groupes ▶/⬇/⧉/🗑). **Variante CSV à en-têtes** ✅ (centralisée : `is_csv_header_batch`/`parse_csv_header_batch`, gérée par `parse_unified_batch`/`parse_media_list_batch` → toutes les apps). Virgules dans une cellule gérées via guillemets (`csv.DictReader`). |
| Duplication d'un élément = DANS le batch (fix) | ✅ | Synthesizer + Transcriber (était hors groupe = bug) |
| **Zone de staging (« À valider »)** — import → réglage → file | 🔶 Pilote | **Transcriber ✅** (statut `DRAFT` serveur ; `stage_commit`/`commit_all`/`clear`/`update_all` ; zone UI + handlers). Décision : DRAFT serveur + pilote-puis-généralisation. Cf. conventions §8.X. **Reste** : généraliser (describer/enhancer/reader/synthesizer/converter/anonymizer/composer/imager/avatarizer) + extraire `common/staging.py` + `wama-staging.js`. |
| **Architecture UI « card-centric »** (card auto-suffisante + volet droit = inspecteur) | 🔶 Décidée | **Décision projet 2026-06** : voir **`CARD_CENTRIC_UI.md`** (spec + phases). Card de composition (dépôt/prompt/référence/RAG par card), volet droit reflète la sélection, 1 source (filemanager) + 1 destination (card) par app, RAG ponctuel isolé par card, modales conservées puis rationalisées. Bâtit sur le staging. Multi-drop→1 batch ✅ corrigé partout (dont enhancer audio). **Preview à 3 niveaux** (§5bis) : composant commun `.wama-card-preview` (double-clic → `wama:card-expand` ; apps média → overlay `unified_preview`) ✅ livré, **1ᵉʳ consommateur transcriber** (preview compacte + métriques sous la barre, bouton œil retiré, double-clic → modal résultat). **Niveau 2 (volet = inspecteur)** ✅ pilote transcriber (clic card → volet édite l'élément ; `[×]` revient aux défauts). Reste : preview complète dans le volet, sélection en-têtes batch, généralisation. WAMA Lab non impacté (composants communs additifs). |
| **Transcriber — correction manuelle assistée IA** (éditeur onde + heatmap) | 🔶 Spec | Spec : **`wama/transcriber/TRANSCRIBER_CORRECTION.md`** (inspiré Whispurge/Sonal). Page dédiée `/edit/<id>/`, guidage non destructif, heatmap cohérence(→confiance) par-segment, réutilise le lecteur d'onde commun. **Fait** : défaut ASR VibeVoice→**Whisper large-v3** (artefact d'ordre, pas benchmark ; diarisation=pyannote ; 10<16 GB) + **word_timestamps** conservés. À évaluer : WhisperX/Canary-Qwen-2.5B/Granite 3.3 ; réparer Qwen3-ASR. Mener le transcriber au bout avant généralisation. |
| **Drag & drop appartenance batch** (entrer/sortir une carte d'un batch) | ⏳ Phase 2 | Toutes les apps à batch — appartenance fluide |

---

## 2. Refactoring — Unification `common/`

> Principe : tout code utilisé par >1 app va dans `wama/common/`. Zéro duplication.

| Élément | Statut | Fichier cible | Impact |
|---------|--------|--------------|--------|
| `wama-eta.js` — moteur ETA commun | ✅ | `common/static/common/js/wama-eta.js` | Toutes les apps (carte/batch/globale) |
| `wama-global-progress.js` + `_global_progress.html` — barre globale | ✅ | `common/…` | converter, avatarizer (autres = barre maison) |
| `wama-fm-notify.js` — notify filemanager (`WamaFM`) | ✅ | `common/static/common/js/wama-fm-notify.js` | Auto-refresh homogène, toutes les apps |
| `batch_common.py` — consolidation import multi-fichiers | ✅ | `common/utils/batch_common.py` | converter, reader, transcriber, describer, enhancer |
| sélection VRAM-aware centralisée | ✅ | `model_manager/services/model_selector.py` | cf. §5b (PAS dans common : model_manager=source de vérité) |
| `wama-app-base.js` — JS inter-apps (Poller, csrf/url, emptyState) | ✅ | `common/static/common/js/wama-app-base.js` | Transcriber rebranché ; à adopter par les autres |
| `audio_decode.py` — décodage multi-format (PyAV/ffmpeg) | ✅ | `common/utils/audio_decode.py` | torchcodec cassé ; à faire converger voice_utils/enhancer/preprocessor |
| `wama-inspector.js`, `wama-model-help.js` | ✅ | `common/static/common/js/` | Volet inspecteur + descriptif modèle (court/long) |
| Briques card : `_card_progress`, `_card_state`, `_new_item_card`, `_queue_actions` | ✅ | `common/templates/common/` | Assemblées par app (pas de card monolithique) |
| `keep_loaded` singleton pattern | ⏳ | Généraliser depuis Reader (olmOCR) | Transcriber (Whisper), Describer, Enhancer |

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
- Modale item : `WamaParams.render(item)` = **4/10** (transcriber, converter, reader, describer) ;
  hand-built = synthesizer, avatarizer, composer ; **enhancer porté le 2026-07-01**.
- Volet : `WamaParams.render(panel)` (référence) vs `WamaInspector.initFromSchema` (synthesizer,
  avatarizer, composer, enhancer) — **à trancher**.
- `params.py` : **8/10** (manquent anonymizer, imager).
- Capacités→UI : `WamaModelCaps` (option-level) — **transcriber ne l'utilise pas**, enhancer a du
  `show_if` **hardcodé** à supprimer. Manque le **niveau-champ**. Modèles déclarent leurs params via
  `capabilities.params` (route existante ; moteurs audio enhancer enregistrés le 2026-07-01).
- ⏳ **TÂCHE 1 avant tout portage** : produire `UI_MECHANISMS_CONSOLIDATION.md` (mécanisme|apps|
  référence|à déprécier par axe + plan de convergence). Spec : `memory/project_ui_mechanisms_consolidation.md`,
  suivi PROJECT_STATUS §20. Contraintes : route existante, zéro réinvention, zéro hardcoding.

---

## 3. Media Library

### Phase 1 ✅ (2026-03-17)
- UserAsset, SystemAsset, page `/media-library/`, migration CustomVoice, intégration synthesizer

### Phase 2 ✅ (2026-03-17)
- Recherche/filtrage tags, pagination, preview modal, métadonnées éditables inline

### Phase 3+4 ✅ (2026-03-17)
- MediaProvider + UserProviderConfig, BaseProvider, connecteurs Wikimedia/Pixabay/Freesound
- Vue proxy `api_provider_search` + `api_provider_download` (clés jamais exposées en JS)

### Phase 5 — Connecteurs avancés ⏳
- Pexels, Unsplash, Openverse, ccMixter (musique CC)
- Mozilla Data Collective (voix, si API stable)

### Phase 6 — Intégration cross-apps ⏳
- Imager : sélecteur image de style depuis médiathèque
- Avatarizer : sélecteur portrait de référence
- Synthesizer : déjà fait ✅

---

## 4. Intégrations modèles AI — Ollama

### 4.1 qwen3-coder:30b (MoE 3.3B actifs, 256K ctx, 19GB) ✅ (2026-04-07)
- Remplace `deepseek-coder-v2:16b` dans wama-dev-ai (rôle `debug`) et `wama/views.py`
- `wama-dev-ai/config.py` : entrée debug mise à jour (context_length 262144, ram 19GB)
- `wama/views.py` : rôle debug + _MODEL_SAFE_CHARS mis à jour (512K chars = 128K tokens)

### 4.2 qwen3-vl:8b — backend vision Ollama pour Describer ✅ (2026-04-14)
- Cascade Ollama vision : qwen3-vl:8b > qwen3-vl > moondream2 > moondream > BLIP (local HF)
- Implémenté dans `wama/describer/utils/image_describer.py`
- `/api/chat` primary, `/api/generate` fallback pour moondream ancien
- Auto-détection des modèles disponibles, cache par worker process

### 4.3 glm-ocr:0.9b — backend OCR léger via Ollama ✅ (2026-04-14)
- Implémenté dans `wama/reader/backends/glm_ocr_backend.py`
- Cascade auto : olmOCR singleton > GLM-OCR (Ollama) > olmOCR-7B (VRAM) > docTR
- Gère PDF multi-pages (PyMuPDF → PNG temp) + images directes
- Migration `0006_alter_readingitem_backend.py` appliquée
- `ollama pull glm-ocr`

---

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
Set temps réel : LLM→Ollama, vocalisation/preview→microservice TTS, speak→futur service Whisper
chaud, traduction→Ollama.

### Backup réseau (vrlescot)
- `REMOTE_BACKUP_PATH` configurable par env `WAMA_MODEL_BACKUP_PATH` ; garde-fou : chemin UNC
  hors Windows non monté → backup **désactivé** sans créer de dossier-poubelle (constater, pas
  créer). ✅ **À finir** : monter le partage en WSL (`/mnt/...`) + tester (conversion .pt→.onnx).

### Sélection centralisée — `services/model_selector.py` (FAIT, étape 3 ⏳)
- `select_model(source, *, model_type, requires, classes, prefer_loaded, downloaded_only,
  vram_budget_gb, candidates, name_contains, priority, availability_probe)`.
- 3 concerns distincts : **téléchargé** (catalogue) ≠ **`availability_probe`** (dispo runtime,
  ex. import Python OK) ≠ **VRAM** (`get_free_vram_gb`). + règle **keep_loaded**.
- `priority` (préférence ordonnée, domine la VRAM) pour les apps « par moteur » (Transcriber
  whisper-first) ; logique VRAM-greedy (le plus gros qui tient) pour les apps « par variante ».
- **Descriptions à deux tiers** : `AIModel.description` (long) + `description_short` (court),
  dérivation auto, migration 0003. `WamaModelHelp` : court sous le sélecteur + long en ⓘ.
- **Étape 3 (⏳)** : faire de l'anonymizer `ModelSelector` / du transcriber `manager` de fins
  adaptateurs ; **piloter `select_model` sur une app par-variante** (describer/imager) plutôt
  que le Transcriber (qui a raison de garder sa sélection runtime backend-class).

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
- [x] Mémoire persistante `memory.json` — bugs connus, règles, notes — + outil `write_memory` + injection prompt
- [ ] Premier audit complet avec `write_report` appelé (3+ audits validés avant de monter en autonomie)
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
│   └── document_backend.py # Pandoc (pypandoc)
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
| Option upscaling ×2/×4 (Real-ESRGAN via Enhancer) | ⏳ | `cross_app_options` model prêt, wiring tasks.py P2 |
| Format de sortie inline dans chaque app (Imager, Enhancer…) | ⏳ | `CONVERTER_OUTPUT_FORMATS` disponible depuis app_registry, UI P2 |
| Batch avec aperçu avant/après sur échantillon | ⏳ Phase 5 | Essentiel sur gros volumes |
| Conversion document (PDF ↔ DOCX ↔ MD ↔ HTML ↔ TXT) | ✅ Phase 4 (2026-06-01) | Pandoc + pypandoc 1.13 ; PDF input via PyMuPDF ; PDF output via xelatex/wkhtmltopdf si dispo |
| Option enhancement audio lors conversion vidéo (Enhancer) | ⏳ Phase 2 | DeepFilterNet/ResembleEnhance via cross_app_options |
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
| **2** | Options cross-app (upscale + audio enhance) | ⏳ | ~180 l | Moyen (perf vidéo) |
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
| **13** | **Batch** : modèle `ConversionBatch`, multi-fichiers groupés par nature, fichier d'URLs (preview/Individuel), groupes UI + actions (start/réglages/delete) | ✅ 2026-06-03 | ~350 l + mig 0003 + `common/batch_common.py` | Moyen |

### Intégration cross-apps (pattern tasks.py) ⏳
```python
# Exemple : conversion image + upscaling
result = image_backend.convert(input_path, output_format, options)
if options.get('upscale'):
    from wama.enhancer.utils.ai_upscaler import upscale_image
    result = upscale_image(result, model=options['upscale_model'])
```

### Dépendances à installer ⏳
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

### Phase 2 — Vue correction interactive ⏳

**URL :** `GET /transcriber/<pk>/correct/`

| Fonctionnalité | Détail |
|----------------|--------|
| Waveform + playback | WaveSurfer.js (déjà dans Composer) |
| Surlignage mot courant | Basé sur `words_json` + `currentTime` player |
| Défilement auto | Fenêtre de ~5 lignes centrée sur le mot courant |
| Clic sur mot → seek | Click handler sur chaque `<span data-start>` |
| Édition inline | `contenteditable` par segment avec sauvegarde AJAX |
| Suggestion IA | Panneau `coherence_suggestion` — "Appliquer" par segment ou global |
| Export | Re-génération SRT/TXT corrigé + nouveau champ `corrected_text` |

**Nouveaux champs DB :**
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

- `llm_chat()` dans `wama/common/utils/llm_utils.py` — point d'entrée unifié
- `LITELLM_PROVIDER = 'ollama'` dans settings.py (défaut, aucun appel cloud)
- `ollama_chat()` conservée telle quelle — zéro breaking change pour les appelants existants
- `litellm` installé : `pip install litellm`

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
- Clés stockées via `UserProviderConfig` (déjà en place dans media_library)
- `llm_chat(provider=user_provider, api_key=user_key)` → LiteLLM route vers le bon provider
- UI : section "Providers IA" dans le profil utilisateur + indicateur "mode hybride actif"
- ⚠️ À préciser dans l'UI : **abonnement ChatGPT Plus / Claude.ai ≠ accès API**
  (API = facturation séparée à la requête, nécessite une clé API distincte)

### Phase 3 — MCP Server WAMA 💡 (long terme)

**Concept :** Exposer les outils WAMA comme serveur MCP pour clients compatibles
(Claude Code, Claude Desktop, IDEs). Distincts de LiteLLM — MCP = protocole d'outils,
pas un routeur LLM.

Exemples d'outils exposables :
- `wama_transcribe(file_path)` → lance une transcription WAMA
- `wama_describe(file_path, format)` → description d'un fichier via le Describer
- `wama_search_media(query)` → recherche dans la Médiathèque
- `wama_rag_query(question, collection)` → Q&A RAG sur un corpus WAMA

Stack : `mcp` Python SDK (officiel Anthropic) + `uvicorn` SSE server (port dédié)

---

## 9. cam_analyzer (wama_lab)

### 9.1 Détection insertions aux intersections ✅
| Composant | Statut | Fichier |
|-----------|--------|---------|
| `rtmaps_parser.py` | ✅ | `wama_lab/cam_analyzer/utils/` |
| `quadrature_video.py` | ✅ | `wama_lab/cam_analyzer/utils/` |
| `intersection_analyzer.py` | ✅ | `wama_lab/cam_analyzer/utils/` |
| Modèles DB (`intersections`, `source_type`, `gps_track`) | ✅ | `cam_analyzer/models.py` + migration |
| Tâche `extract_rtmaps_task` | ✅ | `cam_analyzer/tasks.py` |
| `_detect_intersection_insertion()` | ✅ | `cam_analyzer/tasks.py` |
| Vue `upload_rtmaps` + `rtmaps_status` | ✅ | `cam_analyzer/views.py` |
| UI : section RTMaps + intersections dans profil modal | ✅ | `cam_analyzer/index.html` + JS |

### 9.2 Pipeline conflit / voie navette / vitesse-distance

**Décision archi (2026-05-07)** : YOLOPv2 pour drivable+lanes denses, YOLO+BoTSORT pour
détection+tracking, SAM3 pour marquages sparses dans les fenêtres d'intersection,
GPS+géométrie pour les estimations. SysCV/bdd100k-models et JiayuanWang-JW
**non retenus** (coût d'intégration MMCV vs gain marginal — voir analyse en
historique). Détection objets reste sur YOLOv11 (COCO/BDD), YOLOPv2 ne sert
que pour drivable+lanes.

| Phase | Description | Statut |
|-------|-------------|--------|
| **1** | YOLOPv2 backend (`yolopv2_segmenter.py`), dispatcher dans `tasks.py`, validation thresholds | ✅ (2026-05-07) |
| **2** | Lane attribution : partition drivable→voies via lane lines, voie navette = bottom-center, attribution `lane_id` par détection (foot point) | ✅ (2026-05-07) |
| **3** | `LaneEvent` model (track_id, intersection_window_idx, t_enter, t_exit, lane_id) + computer post-loop + migration | ✅ (2026-05-07) |
| **4** | Distance/vitesse/TTC : pinhole + références normalisées (hauteur véhicule par classe, hauteur piéton 1.7m, FoV par caméra) ; persistés sur chaque détection (`distance_m`, `relative_speed_kmh`, `ttc_s`). Homographie sol auto-calibrée à reporter (Phase 4.bis si Phase 4 trop bruitée) | ✅ (2026-05-07) |
| **5** | `ConflictEvent` model (track_id, intersection_window, conflict_type, navette_passed_first, delta_t, min_distance, min_ttc, severity) + computer `_compute_conflict_events` qui croise LaneEvent (in_shuttle_lane=True) × intersection_window × distance/TTC | ✅ (2026-05-07) |
| **6** | UI : marqueur 🚌 sur détections in_shuttle_lane + bbox épaissie ; affichage distance/vitesse/TTC dans le label ; export CSV étendu (`type`, `lane_id`, `in_shuttle_lane`, `distance_m`, `relative_speed_kmh`, `ttc_s`) ; export JSON `lane_events`+`conflict_events`+`intersection_windows` ; nouvel export `Conflits (CSV)` trié par sévérité | ✅ (2026-05-07) |
| **7** | Trottoirs (optionnel) : SAM3 prompt "sidewalk" en parallèle des marquages ; si insuffisant → mmseg + bdd100k-sem-seg en backend isolé | 💡 |

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

### Étapes ⏳

| Étape | Effort | Fichier / Commande |
|-------|--------|-------------------|
| `USE_I18N = True` + `LOCALE_PATHS` dans settings.py | 5 min | `wama/settings.py` |
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

#### Étapes ⏳
| Étape | Effort | Fichier / Note |
|-------|--------|----------------|
| App `wama/translator/` + service `TranslatorService` (detect/translate/enrich) | 2-3 j | centralisé dans `common/` pour appel inter-app |
| API outil AI-Assistant (`translate`, `enrich_prompt`) | 0.5 j | `tool_api.py` |
| Glossaire « do-not-translate » + masquage placeholders | 1 j | terminologie Lescot configurable |
| Carte langue-cible par modèle + hook pré-génération (imager/composer/anonymizer SAM3…) | 1-2 j | point d'injection unique par app |
| Cache traductions/enrichissements (Redis) | 0.5 j | clé `(hash, lang, model)` |
| Réglage utilisateur « langue de sortie / langue d'origine » | 0.5 j | `UserProfile` (étend `preferred_language`) |

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

> Actuellement : Apache Windows + WSL2 (fonctionnel pour dev/prod local)

### Cible : Nginx full Linux ⏳
```
Client → Linux:80 (Nginx) → localhost:8000 (Gunicorn) → Django/DB/Redis
```
- Supprimer la dépendance Apache Windows + portproxy WSL2
- Créer systemd units : nginx, gunicorn, celery, redis, postgresql
- Remplacer `start_wama_prod.sh` par systemd/supervisord
- Branche dédiée : `deploy/linux-server`

---

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

## 15. Méta-app « Pipeline » — programmation graphique de chaînes (priorité basse)

> Idée 2026-06-17. ComfyUI-like **très simplifié**, orienté utilisateur. Dépend de §14.

Chaque app WAMA = une **card** avec tous ses paramètres (générés depuis sa métadonnée §14).
L'utilisateur glisse des **cards d'entrée** typées (`travail` = fichiers/prompts → batch 1/N,
`contexte` = RAG, `référence` = voix/photo…, + médiathèque/URL), les **chaîne** vers les
entrées compatibles d'une card d'app (**vérif systématique compat I/O**), paramètre, puis
chaîne la sortie vers une autre app (ex. synthesizer → avatarizer) ou un dossier/URL de sortie.
Sauvegarde de la chaîne ; à réfléchir : appliquer une chaîne à une file (batch).
- **C'est le frère VISUEL de l'agent** : tous deux orchestrent les apps via la même méta + tool API.
  La méta-app pourrait **simplifier le chaînage multi-apps de l'AI-Assistant** (abstraction « graphe »).
- **Ne PAS coder le canvas from scratch** : réutiliser une lib de node-graph (React Flow /
  Rete.js / LiteGraph.js / Drawflow).
- **Prérequis dur** : le **contrat de types I/O** des apps (audio/image/vidéo/texte-prompt/
  référence:voix/contexte:rag…) — à définir dans `WAMA_APP_CONVENTIONS.md`.

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
- ❌ **Rejetés (dupliquent/fragmentent ou sur-ingénierie)** : Bifrost (LiteLLM couvre) ; LocalAI/BentoML/Triton (les apps WAMA + microservice TTS + Celery SONT la couche de service) ; Open WebUI/LibreChat (WAMA a déjà son assistant tool_api — adoption = perte d'intégration) ; MLflow (AIModel=registre, pas d'entraînement) ; LM Studio (Ollama couvre) ; MemPalace (Headroom fait la mémoire agents) ; Label Studio (pas d'annotation) ; OpenClaw/ollama-mcp (niche).
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
