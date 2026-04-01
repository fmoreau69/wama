# WAMA — Web App for Media Automation

WAMA is a Django-based web application developed at **Lescot** (Université Gustave Eiffel) that provides AI-powered tools for media processing. It runs as a self-hosted platform with GPU acceleration, exposing each tool as a queue-based interface accessible from a browser.

---

## Applications

### Generic tools (`wama/`)

| App | Route | Description |
|-----|-------|-------------|
| **Anonymizer** | `/anonymizer/` | Automatic blurring of faces and licence plates in photos and videos. Supports YOLO detection + tracking, progressive blur, batch import. |
| **Avatarizer** | `/avatarizer/` | Talking avatar generation: lip-sync a portrait photo or video to an audio track. Pipeline: MuseTalk (lip-sync) + CodeFormer (face enhancement). Supports TTS synthesis directly from text. |
| **Composer** | `/composer/` | Music and sound effect generation from text prompts (Meta AudioCraft — MusicGen + AudioGen). |
| **Describer** | `/describer/` | AI-powered description and summarisation of images, videos and audio. Uses multimodal LLMs (Ollama local or cloud). |
| **Enhancer** | `/enhancer/` | Resolution upscaling for images/videos (Real-ESRGAN, HAT) and audio quality improvement (Resemble Enhance, DeepFilterNet). |
| **Imager** | `/imager/` | Text-to-image, image-to-image, text-to-video and logo generation. Models: HunyuanImage 2.1, Qwen2.5-VL, SDXL, Mochi-1, LTX-Video, CogVideoX-5B, Flux LoRA logo. |
| **Reader** | `/reader/` | OCR for printed and handwritten documents. Models: olmOCR (PDF-native, GPU), EasyOCR. Markdown output with optional LLM formatting. |
| **Synthesizer** | `/synthesizer/` | Text-to-speech voice synthesis with voice cloning. Models: Higgs Audio V2, Coqui XTTS v2. Batch import from text/CSV files. |
| **Transcriber** | `/transcriber/` | Automatic audio/video transcription (faster-Whisper). Outputs: plain text, SRT, VTT, JSON. Speaker diarisation via pyannote. |

### Lab tools (`wama_lab/`)

| App | Route | Description |
|-----|-------|-------------|
| **Face Analyzer** | `/lab/face-analyzer/` | Facial analysis in videos: age, gender, emotions, physiology, eye tracking. |
| **Cam Analyzer** | `/lab/cam-analyzer/` | Analysis of RTMaps camera recordings (Navya shuttle). Vehicle insertion detection at intersections using YOLO tracking + GPS. |

### Infrastructure apps

| App | Description |
|-----|-------------|
| **FileManager** | Persistent sidebar file browser. Supports drag & drop upload, folder creation, preview, rename/move/delete. Mounts network folders (CIFS/SMB) and local paths without copying files. |
| **Model Manager** | Discovery, download and status monitoring of all AI models. Registry of all models organised by domain (`detect`, `speech`, `vision`, `diffusion`, `segment`). |
| **Media Library** | Centralised asset library: custom voices, images, documents. Custom voices are shared across all synthesizer sessions. |
| **Accounts** | User management with LDAP authentication support. Per-user API tokens, language preference, password change (local accounts). |

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
- **OS**: Windows 11 + WSL2 (Ubuntu) for all ML workloads
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

### 1. Clone

```bash
git clone https://github.com/fmoreau69/web-app-for-media-automation.git
cd web-app-for-media-automation
```

### 2. Python environment (WSL2 — production)

```bash
python3.12 -m venv venv_linux
source venv_linux/bin/activate
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
pip install -r requirements_linux.txt
```

### 3. Python environment (Windows — Apache mod_wsgi only)

```bash
pip install mod_wsgi-4.9.2-cp311-cp311-win_amd64.whl
pip install python_ldap-3.4.4-cp311-cp311-win_amd64.whl
pip install -r requirements.txt
```

### 4. Database & initial data

```bash
python manage.py migrate
python manage.py init_wama
```

### 5. Create superuser

```bash
python manage.py createsuperuser
```

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

All models are stored under `AI-models/models/<domain>/<family>/` to avoid storing anything in the default HuggingFace cache. The rule — enforced in `CLAUDE.md` — is: **set `HF_HUB_CACHE` before importing `transformers` or `diffusers`**, and always pass `cache_dir` to `from_pretrained()`.

Download and status are managed via **Model Manager** (`/model-manager/`).

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

## Developer conventions

See [`WAMA_APP_CONVENTIONS.md`](WAMA_APP_CONVENTIONS.md) for the complete UI/architecture conventions, app creation checklist, action button order, queue component requirements, and per-app conformity table.

See [`CLAUDE.md`](CLAUDE.md) for AI model integration rules and collaboration guidelines.

---

## Licence

See [LICENSE](LICENSE).

---

*Developed at Lescot — Université Gustave Eiffel.*
