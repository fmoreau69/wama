# WAMA — Roadmap

> Dernière mise à jour : 2026-04-14 (LiteLLM Phase 1, mode hybride WAMA, mémoire wama-dev-ai — ajoutés)
> Légende : ✅ Fait · 🔄 En cours · ⏳ Planifié · 💡 Proposé · ❌ Abandonné · 🐛 Bug bloquant

---

## 0. Dysfonctionnements connus — À corriger en priorité

| Composant | Symptôme | Statut | Piste |
|-----------|----------|--------|-------|
| **Qwen3-ASR** (Transcriber) | Backend implémenté (`qwen_asr_backend.py`) mais non fonctionnel — erreurs de dépendances à l'import | 🐛 Bloqué | Résoudre conflits deps pip (transformers, torchaudio, accelerate) |
| **Higgs Audio V2** (Synthesizer) | Audio généré inaudible, artefacts, bruits de fond — modèle inutilisable | 🐛 Bloqué | Nombreux patches appliqués + CUDA graphs désactivés (voir memory/). Prochaine étape : test sans voice reference pour isoler |

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
| ETA (barre de progression) | ⏳ | Toutes les apps |
| Import dossier récursif | ⏳ | Toutes les apps acceptant des fichiers |
| Download All (ZIP) | ✅ | Composer |
| Drag & drop zone | ✅ | Imager (prompt image, style ref, img2vid, description) |

---

## 2. Refactoring — Unification `common/`

> Principe : tout code utilisé par >1 app va dans `wama/common/`. Zéro duplication.

| Élément | Statut | Fichier cible | Impact |
|---------|--------|--------------|--------|
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
| Menu contextuel Filemanager — "Envoyer vers Converter" | ✅ | Via APP_CATALOG (même mécanique que les autres apps) |
| Menu contextuel Filemanager — "Conversion rapide" | ✅ | Modal `#converterQuickModal` + `POST /converter/quick/` |
| Profils de conversion sauvegardables | ⏳ | Model `ConversionProfile` créé, UI P2 |
| Option upscaling ×2/×4 (Real-ESRGAN via Enhancer) | ⏳ | `cross_app_options` model prêt, wiring tasks.py P2 |
| Format de sortie inline dans chaque app (Imager, Enhancer…) | ⏳ | `CONVERTER_OUTPUT_FORMATS` disponible depuis app_registry, UI P2 |
| Batch avec aperçu avant/après sur échantillon | ⏳ | P2 |
| Conversion document (PDF ↔ DOCX ↔ MD ↔ HTML ↔ TXT) | ⏳ | Pandoc — P2 |
| Batch avec aperçu avant/après sur échantillon | P2 | Essentiel sur gros volumes |
| Conversion document (PDF ↔ DOCX ↔ MD ↔ HTML ↔ TXT) | P2 | Pandoc |
| Option enhancement audio lors conversion vidéo (Enhancer) | P2 | DeepFilterNet/ResembleEnhance |
| Extraction de frames vidéo | P2 | Intervalle fixe ou détection de scène (PySceneDetect) |
| Concaténation (N fichiers → 1) | P2 | FFmpeg concat |
| Time-lapse / slow-motion (interpolation RIFE/DAIN) | P3 | |
| Option outpainting → redirect Imager | P3 | Tâche générative, Imager en est la maison |

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
```

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

### Détection insertions aux intersections ✅
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

---

## 10. Internationalisation (i18n) — Traduction multi-langues

> Base existante : `UserProfile.preferred_language` déjà en place dans `accounts/models.py`

### Approche retenue : Django i18n + translategemma en batch ⏳

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
