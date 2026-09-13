# WAMA — Web App for Multimodal Automation

> ⚠️ **Under active development** — the platform evolves daily, the **Data world is under
> construction**, and APIs are **not stabilized** (breaking changes happen without notice).
> The media apps are operational and used in production at the lab; everything else should be
> read as work in progress.

WAMA is a Django-based web application developed at **Lescot** (Université Gustave Eiffel) that provides AI-powered tools for media processing. It runs as a self-hosted platform with GPU acceleration, exposing each tool as a queue-based interface accessible from a browser.

The platform is **metadata-driven**: each app declares its identity, ports (typed I/O), capabilities, parameters and models, and the common UI bricks (queues, cards, inspector, settings modals) are generated from those declarations. The same declarations feed the **Studio** (apps chained as pipeline nodes), the **AI assistant tool API**, and a **manifest layer** that can extract every app as a portable JSON manifest — and regenerate a growing share of it back into the registries.

---

## Applications

### Generic tools (`wama/`)

| App | Route | Description |
|-----|-------|-------------|
| **Anonymizer** | `/anonymizer/` | Automatic blurring of faces and licence plates in photos and videos. Supports YOLO detection + tracking, progressive blur, batch import. |
| **Avatarizer** | `/avatarizer/` | Talking avatar generation: lip-sync a portrait photo or video to an audio track. Pipeline: MuseTalk (lip-sync) + CodeFormer (face enhancement). Supports TTS synthesis directly from text. |
| **Composer** | `/composer/` | Music and sound effect generation from text prompts (Meta AudioCraft — MusicGen + AudioGen). |
| **Converter** | `/converter/` | Format conversion across **images, video, audio, documents and archives** (Pillow + FFmpeg + Pandoc + py7zr/rarfile), with quality presets. Also the shared conversion layer: other apps import its output formats and reuse `apply_inline_conversion` to convert their results inline. |
| **Describer** | `/describer/` | AI-powered description and summarisation of images, videos and audio. Uses multimodal LLMs (Ollama local or cloud). |
| **Enhancer** | `/enhancer/` | Resolution upscaling for images/videos (Real-ESRGAN, HAT) and audio quality improvement (Resemble Enhance, DeepFilterNet). |
| **Imager** | `/imager/` | Text-to-image, image-to-image, text-to-video and logo generation. Models: HunyuanImage 2.1, Qwen-Image 2 (+ Edit), SDXL, Mochi-1, LTX-Video, CogVideoX-5B I2V, Flux LoRA logo (live list: Model Manager catalogue). |
| **Reader** | `/reader/` | OCR for printed and handwritten documents. Models: olmOCR (PDF-native, GPU), EasyOCR. Markdown output with optional LLM formatting. |
| **Synthesizer** | `/synthesizer/` | Text-to-speech voice synthesis with voice cloning. Models: Higgs Audio V2, Coqui XTTS v2. Batch import from text/CSV files. |
| **Transcriber** | `/transcriber/` | Automatic audio/video transcription — three engines (faster-Whisper, VibeVoice ASR, Qwen3-ASR) with VRAM-aware selection, audio preprocessing (DeepFilterNet), speaker diarisation (pyannote) and an AI-assisted manual correction editor. Outputs: plain text, SRT, VTT, JSON. |

### Lab tools (`wama_lab/`)

| App | Route | Description |
|-----|-------|-------------|
| **Face Analyzer** | `/lab/face-analyzer/` | Facial analysis in videos: age, gender, emotions, physiology, eye tracking. |
| **Cam Analyzer** | `/lab/cam-analyzer/` | Analysis of RTMaps camera recordings (Navya shuttle). Vehicle insertion detection at intersections using YOLO tracking + GPS. |

### Platform apps

| App | Route | Description |
|-----|-------|-------------|
| **Studio** | `/studio/` | Meta-app: chain the apps above as **nodes on a canvas** (typed ports derived from each app's declared I/O), save pipelines, run them through Celery with per-node status. Also drivable by the AI assistant (`list_studio_pipelines` / `run_studio_pipeline` / `get_studio_run_status`). |
| **FileManager** | `/filemanager/` | Persistent sidebar file browser. Supports drag & drop upload, folder creation, preview, rename/move/delete. Mounts network folders (CIFS/SMB) and local paths without copying files. |
| **Model Manager** | `/model-manager/` | Discovery, download and status monitoring of all AI models. Registry of all models organised by domain (`detect`, `speech`, `vision`, `diffusion`, `segment`), with canonical capabilities (task, modalities, required inputs). |
| **Media Library** | `/media-library/` | Centralised asset library: custom voices, images, documents. Custom voices are shared across all synthesizer sessions. |
| **Accounts** | `/accounts/` | User management with LDAP authentication support. Role/tier-based app access policies (also enforced on the assistant tool surface), per-user API tokens, language preference. |

### AI assistant & tool API

Every app exposes its actions to the built-in AI assistant through **`wama/tool_api.py`** (46 tools):
a canonical triad per app — `add_to_<app>` / `start_<app>` / `get_<app>_status` — plus primary verbs
(`create_image`, `compose_music`, `convert_file`, `synthesize_text`, `translate_text`), media-library
and studio tools. Tools are listed and executed via `GET/POST /api/v1/tools/`, with descriptions
**derived** from the app catalogue, docstrings and parameter schemas, and access gated by the same
role/tier policies as the navigation.

---

## Architecture

```
Browser
  │
  ▼
Apache HTTP Server (Windows, port 80)    ← reverse proxy
  │  ProxyPass → 127.0.0.1:8000
  │  netsh portproxy → WSL2 IP:8000
  ▼
Gunicorn (WSL2, port 8000)               ← 4 workers × 2 threads
  │
  ▼
Django 5.2  ──── PostgreSQL (WSL2)
  │          └── Redis (WSL2)
  │
  ├── Celery GPU worker  (queue: gpu)     ← 1 task at a time, solo pool
  │     anonymizer · imager · enhancer · synthesizer · transcriber · describer · reader
  │
  ├── Celery Default worker (queue: default, celery)  ← autoscale 1–4, prefork
  │     model_manager · periodic tasks
  │
  ├── Celery Beat                         ← scheduled tasks
  │
  └── TTS Service — FastAPI/uvicorn (port 8001)
        Higgs Audio V2 · Coqui XTTS v2

Ollama (Windows, port 11434)             ← local LLMs for Describer / Reader
```

**Key paths:**
- Project: `D:/WAMA/web-app-for-media-automation/` (Windows) = `/mnt/d/WAMA/web-app-for-media-automation/` (WSL2)
- Virtual env (production): `venv_linux/` (WSL2 Python 3.12)
- Virtual env (Windows): `venv_win/` (Python 3.11, for Apache mod_wsgi only)
- AI models: `AI-models/models/<domain>/<family>/`
- Logs: `logs/` (gunicorn-access, gunicorn-error, celery-gpu, celery-default, tts-service)
- Static files: `wama/<app>/static/` → collected to `staticfiles/`

---

## Hardware target

- **GPU**: NVIDIA RTX 4090 24 GB VRAM
- **OS**: Windows 10 + WSL2 (Ubuntu) for all ML workloads
- Python 3.12 (WSL2), Python 3.11 (Windows/Apache)

---

## Production startup

```bash
# Full start (after code changes, fresh boot)
./start_wama_prod.sh

# Fast restart (daily use — skips collectstatic and TTS wait)
./start_wama_prod.sh --fast
```

The script handles: stop of existing processes · WSL2 clock resync · WSL2→Windows portproxy (netsh) · PostgreSQL · Redis · Django migrations · collectstatic · Gunicorn · GPU CUDA cleanup · TTS service · CIFS share remount · Celery workers (gpu + default) · Celery Beat.

---

## Development startup

```bash
./start_wama_dev.sh
```

Uses `python manage.py runserver` instead of Gunicorn. No daemon mode — logs printed to terminal.

---

## Initial setup

> **Raccourci — un seul script.** `tools/install_wama.sh` enchaîne toutes les étapes ci-dessous
> dans le bon ordre (l'ordre compte : `requirements_torch` **avant** `requirements_linux`, les
> patches **après** pip) et appelle les setups qu'aucun texte ne reliait jusqu'ici
> (`update_vendors.sh`, `apply_patches.py`, `setup_avatarizer.sh`).
>
> ```bash
> git clone https://github.com/fmoreau69/wama.git
> cd wama
> bash tools/install_wama.sh --dry-run     # voir le plan sans rien exécuter
> bash tools/install_wama.sh               # installer
> ```
>
> Options : `--skip-venv`, `--skip-vendors`, `--with-avatarizer` (MuseTalk + CodeFormer, lourd),
> `--help`. Le script est **idempotent** (relançable sans dégât) et ne fait **pas** les deux
> gestes qui demandent une décision humaine : remplir `.env` et créer le superutilisateur — il
> les rappelle à la fin. **Réseau requis** (contrairement au démarrage, qui reste hors-ligne).
>
> Les sections qui suivent détaillent chaque étape, pour comprendre ce que fait le script ou
> pour installer à la main.

### 1. Clone

```bash
git clone https://github.com/fmoreau69/wama.git
cd wama
```

### 2. Python environment (WSL2 — production)

```bash
python3.12 -m venv venv_linux
source venv_linux/bin/activate
pip install -r requirements_torch.txt    # PyTorch GPU (CUDA 12.8) — EN PREMIER, pins +cu128
pip install -r requirements_linux.txt    # doit passer APRÈS (rétablit le pin setuptools<81)
```

### 3. Python environment (Windows — Apache mod_wsgi only)

```bash
pip install mod_wsgi-4.9.2-cp311-cp311-win_amd64.whl
pip install python_ldap-3.4.4-cp311-cp311-win_amd64.whl
pip install -r requirements.txt
```

### 4. Environment variables (`.env`)

```bash
cp .env.example .env
# Fill DJANGO_SECRET_KEY:
#   python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
# and WAMA_DB_PASSWORD (matching your PostgreSQL role).
```

Secrets (Django key, DB password, proxy, LDAP…) are **read from the environment / `.env`**, never
hardcoded in `settings.py`. `.env` is gitignored — **never commit it**. To rotate secrets later
(dev or prod): `python manage.py rotate_secrets --all --also-wsl` (see `INFRA_WSL_VS_WINDOWS.md`).

### 5. Database & initial data

```bash
python manage.py migrate
python manage.py init_wama
```

### 6. Create superuser

```bash
python manage.py createsuperuser
```

### 7. Apply compatibility patches

Third-party libraries installed via pip have version conflicts with recent PyTorch / torchaudio.
Run the patch script once after setup, and again after any `pip install --upgrade`:

```bash
python patches/apply_patches.py
```

| # | Target file | Issue | Fix |
|---|-------------|-------|-----|
| 1 | `site-packages/boson_multimodal/.../modeling_higgs_audio.py` | `transformers 4.57+` API breaks (attention unpacking, inference_mode, cache_position…) | 7 targeted search-replace patches |
| 2 | `site-packages/df/io.py` (deepfilternet) | `torchaudio.backend.common.AudioMetaData` removed in torchaudio 2.x | `try/except` + dataclass stub |
| 3 | `tts_service.py` | In-repo patches (usage dict, temperature, CUDA graphs, audio trim) | Verified, not re-applied |
| 4 | `start_wama_prod.sh` | `HIGGS_DISABLE_CUDA_GRAPHS=1` must be exported | Verified, not re-applied |
| 5 | `site-packages/xformers/ops/seqpar.py` | `GroupName` removed from `torch.distributed` in torch 2.9.x | `try/except` fallback import |
| 6 | `site-packages/vibevoice/.../modeling_vibevoice_asr.py` | `lm_head` int32 GEMM overflow on long audio (CUDA `cudaErrorUnknown`) | logits computed on last token only |

> **Adding a new patch:** use `apply_patch(path, search, replace, description)` in `patches/apply_patches.py`.
> Every manual fix applied to a file in `venv_linux/` must be recorded here so it survives future `pip upgrade`.

---

## Apache configuration (Windows)

File: `C:/Apache24/conf/httpd.conf` (or equivalent)

```apache
SetEnv http_proxy  "http://<proxy>:<port>"
SetEnv https_proxy "http://<proxy>:<port>"
SetEnv no_proxy    "127.0.0.1,localhost"   ← required to avoid routing local proxy through corporate proxy

<VirtualHost *:80>
    ServerName wama.local
    ProxyPreserveHost On
    ProxyTimeout 120
    Alias /media/ "D:/WAMA/web-app-for-media-automation/media/"
    <Directory "D:/WAMA/web-app-for-media-automation/media/">
        Require all granted
        Options -Indexes
    </Directory>
    ProxyPass /media/ !
    ProxyPass        / http://127.0.0.1:8000/ retry=0 timeout=130
    ProxyPassReverse / http://127.0.0.1:8000/
    ErrorDocument 502 "<html><body><h2>WAMA en cours de démarrage...</h2><p>Rechargez dans quelques secondes.</p></body></html>"
    ErrorLog  "logs/wama-error.log"
    CustomLog "logs/wama-access.log" common
</VirtualHost>
```

> **Note :** `SetEnv no_proxy` is critical — without it, Apache routes `ProxyPass` requests to `127.0.0.1` through the corporate proxy and fails with `AH01114 ECONNREFUSED`.
> `retry=0` prevents Apache from blacklisting gunicorn for 60 s after a transient error.

### WSL2 port forwarding

Apache (Windows) cannot reach gunicorn (WSL2) on `127.0.0.1:8000` unless a portproxy rule is active. `start_wama_prod.sh` resets this rule automatically at startup. To set it manually (requires admin PowerShell):

```powershell
$wsl = (wsl hostname -I).Trim().Split()[0]
netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=$wsl
```

---

## AI model management

All models are stored under `AI-models/models/<domain>/<family>/` to avoid storing anything in the default HuggingFace cache. The rule — enforced in `AGENTS.md` — is: **set `HF_HUB_CACHE` before importing `transformers` or `diffusers`**, and always pass `cache_dir` to `from_pretrained()`.

Download and status are managed via **Model Manager** (`/model-manager/`).

---

## Manifest layer & app generation

Every app can be **extracted as a consolidated JSON manifest** (12 facets: identity, ports,
capabilities, modes, params, inspector, models, processing, prompts, tool_api, access, studio) —
the corpus lives in `manifests/` (10 apps + libraries). Seven manifest kinds exist (`app`,
`library`, `model`, `function`, `pipeline`, `project`, `dataset`), composable through `requires`
references (an app cites its models and libraries).

The reverse direction — **write-back** — regenerates registries from the manifest, as an explicit,
idempotent and reversible gesture (dry-run by default, generated entries are marked and can be
removed; hand-written entries are never overwritten). As of 2026-08-11, 7 facets project back
(`access` → DB policy; `identity`/`ports`/`capabilities` → app catalogue; `studio` → pipeline
runner; `modes`; `prompts`); the remaining facets (`params`, `inspector`, `processing`,
`tool_api`) are the code-generation frontier. Derived values (app colours, node I/O) and measured
values (conformity flags) are never written back — they are recomputed or re-measured.

Instrumentation (all read-only):

```bash
python manage.py manifest_export --check   # is the manifest corpus up to date?
python manage.py manifest_roundtrip --all  # extract → validate → verify → write-back dry-run
python manage.py check_app_conformity      # measured conformity grid (74 criteria, 8 facets)
python manage.py check_docs                # doc → code reference integrity
```

---

## Key dependencies

| Package | Purpose |
|---------|---------|
| Django 5.2 + DRF | Web framework + REST API |
| Celery 5 + Redis | Async task queue |
| faster-Whisper | Speech transcription |
| pyannote.audio | Speaker diarisation |
| ultralytics (YOLO) | Object detection and tracking |
| diffusers / transformers | Image/video generation models |
| Coqui TTS / Higgs Audio | Voice synthesis |
| olmOCR | PDF/document OCR (GPU) |
| EasyOCR | Lightweight OCR |
| AudioCraft | Music and SFX generation |
| Resemble Enhance / DeepFilterNet | Audio enhancement |
| Ollama | Local LLM inference (Windows host) |
| django-auth-ldap | LDAP/AD authentication |
| psycopg2 | PostgreSQL adapter |

Full dependency list: `requirements.txt` (Windows) / `requirements_linux.txt` (WSL2).

---

## Developer conventions & documentation

The documentation is written in French for now (English and full i18n come later). It serves
three audiences: **construction** — the hand-written source, tracing what WAMA is and why —,
**developer** and **user**, both *generated* from it and from the registries. It is also readable
inside WAMA (`/common/docs/`, administrators).

The tree below is **generated** from the documentation catalogue (`wama/common/docs_catalog.py`)
by `python manage.py doc_facts` — do not edit it by hand; declare a document in the catalogue.

<!-- WAMA:FAITS(arborescence_docs) — généré par « python manage.py doc_facts », ne pas éditer -->
- **À la racine** — la doctrine, lue par tout agent et par un humain
  - [AGENTS — la doctrine](AGENTS.md) — Source unique des règles de développement : philosophie, règles obligatoires, conventions, table des fichiers de référence. Lue par tout agent et par un humain.
  - [CLAUDE — le harnais Claude Code](CLAUDE.md) — Les seules règles propres au harnais Claude Code (permissions, hooks). Importe AGENTS.md et n'en recopie rien.
- **`docs/construction/`** — la doc de CONSTRUCTION, écrite à la main : la source des deux autres
  - **`architecture/`** — Architecture & génération
    - [Carte des mécanismes](docs/construction/architecture/WAMA_MECANISMES.md) — Index des briques transversales : où vit quoi, qui l'utilise. Sa table est générée depuis le registre des mécanismes.
    - [Route d'auto-génération des apps](docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md) — Facettes F1–F8, briques communes, chaîne dépôt → app, et ce qu'une génération ne doit plus redécouvrir. À lire avant de créer ou modifier une app.
    - [Conventions d'app](docs/construction/architecture/WAMA_APP_CONVENTIONS.md) — Conventions UI et architecture de toutes les apps, capacités d'app, checklist de création.
    - [Manifestes — formalisme](docs/construction/architecture/WAMA_MANIFEST_SPEC.md) — Le formalisme des sept kinds de manifestes : app, library, model, function, pipeline, project, dataset.
    - [Manifestes — flux et schéma](docs/construction/architecture/WAMA_MANIFEST_ARCHITECTURE.md) — Comment circulent les manifestes : extraction, composition, projection vers les registres.
    - [Audit de l'app de référence](docs/construction/architecture/TRANSCRIBER_REFERENCE_AUDIT.md) — Le Transcriber comme étalon : audit de conformité et checklist de fin d'app.
    - [Vérification](docs/construction/architecture/WAMA_VERIFICATION.md) — Comment on sait que ça marche : grille d'adoption contre grille fonctionnelle, catalogue des gestes, couverture.
  - **`ui/`** — Interface & file
    - [Formalisme de card](docs/construction/ui/CARD_DESIGN.md) — Anatomie des cards, trois densités, lots.
    - [File et modes applicatifs](docs/construction/ui/MODES_QUEUE_UX.md) — UX de la file d'attente et des modes d'app.
    - [Volets gauche et droit](docs/construction/ui/WAMA_VOLETS.md) — Ossature des volets, états contextuels, mode simplifié, repli — état mesuré des pages.
    - [Champs de l'inspecteur](docs/construction/ui/INSPECTOR_DETAIL_FIELDS.md) — Schéma canonique des champs de détail affichés par l'inspecteur.
    - [Appariement entrée ↔ modèle](docs/construction/ui/INPUT_MODEL_MATCHING.md) — Quel modèle accepte quelle entrée, et comment l'interface le montre.
    - [Format des fichiers de lot](docs/construction/ui/BATCH_FORMAT.md) — Le format des fichiers batch (txt, csv, pdf, docx).
  - **`ia/`** — Couche IA
    - [Couche LLM](docs/construction/ia/WAMA_LLM.md) — Prompts, skills, traduction et enrichissement, routage de modèle, surfaces de l'assistant.
    - [Mémoire & RAG](docs/construction/ia/WAMA_MEMORY.md) — Mémoire d'agent, mémoire de travail et RAG comme un seul mécanisme, plus le journal utilisateur.
    - [Apprentissage (ML/DL)](docs/construction/ia/WAMA_APPRENTISSAGE.md) — Modèles appris, couche statistique, MLflow — WAMA déclare, déclenche et réingère ; il n'entraîne pas.
  - **`mondes/`** — Mondes & apps
    - [Vision d'ensemble](docs/construction/mondes/WAMA_VISION_COMPLET.md) — La vision produit, unique, confrontée au réel section par section.
    - [Studio & production AV](docs/construction/mondes/STUDIO_VISION.md) — Vision du studio et de la production audiovisuelle.
    - [Monde Data](docs/construction/mondes/WAMA_DATA_WORLD.md) — Périmètre du monde Data et cartographie de corpus.
    - [Fonctions Data — catalogue](docs/construction/mondes/WAMA_DATA_FUNCTION_CARDS.md) — Le catalogue des fonctions de traitement du monde Data.
  - **`exploitation/`** — Infra, droits & données
    - [Profils, permissions, rétention](docs/construction/exploitation/PROFILES_PERMISSIONS.md) — Profils, droits d'accès, notifications, rétention.
    - [Infra WSL2 ↔ Windows](docs/construction/exploitation/INFRA_WSL_VS_WINDOWS.md) — Ce qui tourne où, entre WSL2 et Windows.
    - [Médias : stockage et import](docs/construction/exploitation/MEDIA_STORAGE_TIERING.md) — Stockage, tiering, intégrité et voies d'import des médias.
    - [Licences & dépôt](docs/construction/exploitation/LICENSING.md) — Licence du dépôt, politique, code vendorisé, dépôt officiel.
  - **`suivi/`** — Suivi des chantiers
    - [Point d'étape des chantiers](docs/construction/suivi/PROJECT_STATUS.md) — Photo des chantiers et handoffs de session. Journal daté : ce qui y est écrit était vrai à sa date.
    - [Roadmap](docs/construction/suivi/ROADMAP.md) — Les chantiers ouverts et leur ordre.
    - [Registre des retraits](docs/construction/suivi/REMOVAL_LEDGER.md) — Ce qui a été retiré, et pourquoi.
  - **`archive/`** — 44 documents archivés, consultables pour retrouver un oubli ; jamais déclarés ni réécrits
- **`docs/dev/`** — la doc DÉVELOPPEUR, GÉNÉRÉE depuis la doc de construction et les registres : ne pas éditer
  - [Les registres de WAMA](docs/dev/registres.md) — Quand une chose mérite un registre, les natures d'actualisation, et chaque registre de WAMA — dérivé de la doc de construction et des registres eux-mêmes.
  - *et, calculées à la lecture dans WAMA :* Parcours d'entrée · Briques communes — API
- **`docs/utilisateur/`** — la doc UTILISATEUR, générée elle aussi : à venir
- **Docs de module** — ils restent à côté de leur code
  - [Briques communes — carte](wama/common/README.md) — Carte d'entrée du dossier des briques communes.
  - [Prospection de modèles](wama/model_manager/PROSPECTION_PIPELINE.md) — Veille et prospection de modèles : la chaîne et ses juges.
  - [Cam Analyzer — chaîne de traitement](wama_lab/cam_analyzer/CAM_ANALYZER_CHAINE_TRAITEMENT.md) — La chaîne de traitement de Cam Analyzer et sa conception.
  - [Cam Analyzer — historique](wama_lab/cam_analyzer/CAM_ANALYZER_CHANGELOG.md) — Journal des évolutions de Cam Analyzer.
  - [Cam Analyzer — carte](wama_lab/cam_analyzer/README.md) — Carte d'entrée de l'app Lab.
  - [Transcriber — correction assistée](wama/transcriber/TRANSCRIBER_CORRECTION.md) — La page de correction manuelle assistée par IA.
  - [Enhancer](wama/enhancer/README.md) — Upscaling image et vidéo, et branche audio.
  - [Patches de compatibilité des venvs](patches/README.md) — Les correctifs des librairies tierces à réappliquer après une installation propre du venv, et leur registre.
  - [AI-models — le dossier des poids](AI-models/README.md) — Où vivent les poids des modèles de WAMA, et comment le dossier s'organise.
  - [AI-models — arborescence par domaine](AI-models/models/README.md) — L'arborescence des modèles, rangés par domaine.
  - [Moteurs vendorisés](wama/common/backends/vendor/README.md) — Les moteurs livrés en code source (dépôts tiers clonés à l'installation, exécutés en sous-processus) — rien n'y est du code WAMA.
  - [wama-dev-ai — agent de développement local](wama-dev-ai/README.md) — L'agent local (Ollama) : audits en lecture seule, génération bornée, rôles producteurs de manifestes. Claude réfléchit, wama-dev-ai exécute, l'humain valide.
  - [Imager](wama/imager/README.md) — Génération d'images et de vidéos : backends interchangeables, fichiers de référence, mots-clés imposés, enrichissement de prompt.
  - [Face Analyzer](wama_lab/face_analyzer/README.md) — Analyse faciale en vidéo expérimentale (monde Lab) : variables comportementales et physiologiques, croisables avec les autres données du laboratoire.
  - [Cam Analyzer — un projet (ENA_CASA)](wama_lab/cam_analyzer/projects/ENA_CASA.md) — Les spécificités d'un projet cam_analyzer : données, calibration, rig. Une configuration de l'app, pas une propriété — façonné comme le futur manifeste.
<!-- /WAMA:FAITS(arborescence_docs) -->

---

## Licence

Copyright (C) 2023-2026 **Université Gustave Eiffel** — auteur : **Fabien Moreau**
(laboratoire Lescot). Voir [COPYRIGHT](COPYRIGHT) : les droits d'exploitation sont à
l'établissement (art. L113-9 CPI), la qualité d'auteur reste à la personne.

WAMA est distribué sous **GNU AGPL-3.0** — texte intégral dans [LICENSE](LICENSE). Toute
personne utilisant WAMA **à distance via le réseau** a droit d'en obtenir le code source
(AGPL art. 13).

Les modèles d'IA et composants embarqués conservent **leurs** licences propres, dont
certaines sont non commerciales ou territorialement restreintes — inventaire vivant sur
`/common/licenses/`, politique et procédure de dépôt dans [LICENSING.md](docs/construction/exploitation/LICENSING.md).

---

*Developed at Lescot — Université Gustave Eiffel.*
