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
| **Transcriber — correction manuelle assistée IA** (éditeur onde + heatmap) | 🔶 Spec | Spec : **`TRANSCRIBER_CORRECTION.md`** (inspiré Whispurge/Sonal). Page dédiée `/edit/<id>/`, guidage non destructif, heatmap cohérence(→confiance) par-segment, réutilise le lecteur d'onde commun. **Fait** : défaut ASR VibeVoice→**Whisper large-v3** (artefact d'ordre, pas benchmark ; diarisation=pyannote ; 10<16 GB) + **word_timestamps** conservés. À évaluer : WhisperX/Canary-Qwen-2.5B/Granite 3.3 ; réparer Qwen3-ASR. Mener le transcriber au bout avant généralisation. |
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
| `backend_selector.py` — sélection VRAM-aware | ⏳ | `common/utils/backend_selector.py` | Reader, Transcriber, Describer |
| `wama-app-base.js` — JS inter-apps | ⏳ | `common/static/common/js/wama-app-base.js` | Éliminerait ~70% duplication JS |
| `_settings_modal.html` — modal paramètres générique | ⏳ | `common/templates/common/_settings_modal.html` | Toutes les apps |
| `keep_loaded` singleton pattern | ⏳ | Généraliser depuis Reader (olmOCR) | Transcriber (Whisper), Describer, Enhancer |

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
