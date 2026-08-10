#!/bin/bash
set -e

# ------------------------------------------------------
# MODE : full (défaut) ou fast (--fast)
# Usage :
#   ./start_wama_prod.sh          → démarrage complet (migrations + collectstatic + attente TTS)
#   ./start_wama_prod.sh --fast   → redémarrage rapide (skip collectstatic, TTS fire&forget)
# ------------------------------------------------------
FAST=0
for arg in "$@"; do
    [ "$arg" = "--fast" ] && FAST=1
done
[ $FAST -eq 1 ] && echo "=== Mode FAST activé (skip collectstatic, TTS fire&forget) ===" || true

# ------------------------------------------------------
# STOP DES PROCESS EXISTANTS
# ------------------------------------------------------
echo "=== Stopping old processes if any ==="
pkill -f "gunicorn wama.wsgi" || true
pkill -f "celery" || true
# Graceful stop: SIGTERM first, then wait, then SIGKILL
if pkill -f "uvicorn tts_service" 2>/dev/null; then
    sleep 3
    pkill -9 -f "uvicorn tts_service" 2>/dev/null || true
fi
pkill -f "redis-server" || true

sleep 2

# ------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------
PROJECT_DIR=/mnt/d/WAMA/web-app-for-media-automation
VENV_DIR=$PROJECT_DIR/venv_linux
DJANGO_SETTINGS_MODULE=wama.settings
DJANGO_PORT=8000
GUNICORN_WORKERS=4
LOG_DIR=$PROJECT_DIR/logs

# Ollama runs on Windows — WSL2 cannot reach 127.0.0.1:11434 directly.
# The Windows host IP is resolved at startup; override with OLLAMA_HOST env var if needed.
export OLLAMA_HOST=${OLLAMA_HOST:-http://$(ip route show | awk '/^default/{print $3; exit}'):11434}

# Timezone : Paris — aligne les timestamps des logs Python/Celery sur l'heure locale.
# WSL2 hérite souvent UTC du noyau ; forcer TZ ici évite les logs décalés.
export TZ=Europe/Paris

# Backup distant des modèles (model_manager/remote_backup.py). Point de MONTAGE WSL,
# pas le chemin UNC : monter \\vrlescot\SAVES sur /mnt/shares/SAVES (drvfs ou /etc/fstab).
# Sûr même si non monté : is_available() voit que le dossier n'existe pas → backup désactivé proprement.
export WAMA_MODEL_BACKUP_PATH=${WAMA_MODEL_BACKUP_PATH:-/mnt/shares/SAVES/DEEP_LEARNING/MODELS}

# Resync WSL2 clock (dérive après sleep/hibernate — source du "substantial drift" Celery)
# `-n` : sans credentials sudo en cache, échouer AU LIEU de demander un mot de passe — lancé
# en non-interactif (session Claude, cron), le prompt est invisible (2>/dev/null) et bloque
# la séquence de démarrage indéfiniment (vécu 2026-08-11 : 16 min avant kill manuel).
sudo -n hwclock -s 2>/dev/null || true

mkdir -p $LOG_DIR

# ------------------------------------------------------
# ACTIVER L'ENVIRONNEMENT VIRTUEL
# ------------------------------------------------------
cd $PROJECT_DIR
source $VENV_DIR/bin/activate

echo "=== Starting WAMA production script ==="

# ── WSL2 port forwarding fix ──────────────────────────────────────────────────
# WSL2's automatic port proxy Windows→WSL2 breaks silently after sleep/hibernate.
# Force-reset it via netsh so Apache (Windows) can always reach gunicorn at :8000.
WSL2_IP=$(hostname -I | awk '{print $1}')
if [ -n "$WSL2_IP" ]; then
    # Capture netsh output to detect elevation error (netsh writes it to stdout, not stderr)
    NETSH_OUT=$(cmd.exe /c "netsh interface portproxy delete v4tov4 listenport=8000 listenaddress=0.0.0.0 >nul 2>nul & netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=${WSL2_IP}" 2>/dev/null || true)
    if echo "$NETSH_OUT" | grep -qiE "lev|admin"; then
        echo "INFO: netsh portproxy requires admin rights — lance WSL2 en tant qu'administrateur"
        echo "      ou exécute une fois en admin : netsh interface portproxy add v4tov4 listenport=8000 listenaddress=0.0.0.0 connectport=8000 connectaddress=${WSL2_IP}"
    else
        echo "WSL2 port proxy 0.0.0.0:8000 → ${WSL2_IP}:8000 configured"
    fi
fi
# ─────────────────────────────────────────────────────────────────────────────


# ------------------------------------------------------
# PostgreSQL
# ------------------------------------------------------
if ! pgrep -x "postgres" > /dev/null; then
    echo "=== Starting PostgreSQL ==="
    sudo service postgresql start
    sleep 3
else
    echo "PostgreSQL is already running."
fi

# ------------------------------------------------------
# REDIS
# ------------------------------------------------------
if ! pgrep -x "redis-server" > /dev/null; then
    echo "=== Starting Redis ==="
    redis-server --daemonize yes
else
    echo "Redis is already running."
fi

if ! redis-cli ping | grep -q PONG; then
    echo "Redis is not responding! Exiting..."
    exit 1
fi

# ------------------------------------------------------
# MIGRATIONS
# ------------------------------------------------------
echo "=== Applying Django migrations ==="
python manage.py migrate --settings=$DJANGO_SETTINGS_MODULE

# Seeds idempotents (rôles + politiques d'accès, mots-clés de prompt). get_or_create → sûrs à chaque démarrage.
echo "=== Seeding access policies + prompt keywords ==="
python manage.py seed_access --settings=$DJANGO_SETTINGS_MODULE || true
python manage.py seed_prompt_keywords --settings=$DJANGO_SETTINGS_MODULE || true

# ------------------------------------------------------
# JOURNAUX — rotation, PAS écrasement
# ------------------------------------------------------
# On DÉCALE les journaux du run précédent (X.log → X.log.1 → …) au lieu de les
# vider : après un crash, la trace qui l'explique doit survivre au redémarrage
# qui suit, sinon il faut reproduire le bug pour l'étudier (vécu 29/07/2026 :
# c'est celery-gpu.log conservé qui a identifié la boucle de crash WSL2).
# IMPÉRATIF : ici, services ARRÊTÉS (kill plus haut) et AVANT de les relancer —
# renommer un fichier encore ouvert ne détacherait pas le descripteur.
echo "=== Rotating logs (9 runs conservés) ==="
python manage.py rotate_logs --settings=$DJANGO_SETTINGS_MODULE || true

# ------------------------------------------------------
# PLAYWRIGHT CHROMIUM  (converter HTML→PDF fidèle)
# ------------------------------------------------------
# Le binaire navigateur + ses libs OS ne sont PAS couverts par pip (requirements).
# On les provisionne ici. Navigateur = cache Playwright par défaut
# (~/.cache/ms-playwright, régénérable — PAS un modèle, donc PAS dans AI-models).
# Idempotent : `install chromium` = no-op si présent ; marqueur pour l'apt (`--with-deps`,
# sudo, lent). NON BLOQUANT : si échec (réseau/proxy/sudo), le converter retombe sur
# WeasyPrint puis pandoc.
if python -c "import playwright" 2>/dev/null; then
    PW_DEPS_MARKER="$HOME/.cache/ms-playwright/.wama-os-deps-ok"
    if [ ! -f "$PW_DEPS_MARKER" ]; then
        echo "=== Provisioning Playwright Chromium (one-time : navigateur + libs apt) ==="
        if python -m playwright install --with-deps chromium; then
            mkdir -p "$(dirname "$PW_DEPS_MARKER")" && touch "$PW_DEPS_MARKER"
        else
            echo "WARN: 'playwright install --with-deps' a échoué (sudo/réseau/proxy) — tentative sans apt"
            python -m playwright install chromium || echo "WARN: Chromium indisponible → converter HTML→PDF via WeasyPrint (fallback)"
        fi
    else
        python -m playwright install chromium >/dev/null 2>&1 || true  # garde le navigateur, no-op si présent
    fi
fi

# ------------------------------------------------------
# STATIC FILES  (skipped in --fast mode)
# ------------------------------------------------------
if [ $FAST -eq 0 ]; then
    echo "=== Collecting static files ==="
    python manage.py collectstatic --noinput --settings=$DJANGO_SETTINGS_MODULE
else
    echo "=== Static files: skipped (--fast) ==="
fi

# ------------------------------------------------------
# GUNICORN
# ------------------------------------------------------
if ! pgrep -f "gunicorn wama.wsgi" > /dev/null; then
    echo "=== Starting Gunicorn ==="
    gunicorn wama.wsgi:application \
        --config gunicorn_conf.py \
        --env DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE
else
    echo "Gunicorn is already running."
fi

# ------------------------------------------------------
# GPU/CUDA CLEANUP  (skipped in --fast mode)
# ------------------------------------------------------
if [ $FAST -eq 0 ]; then
    echo "=== Clearing GPU memory and CUDA cache ==="
    python -c "
import torch
if torch.cuda.is_available():
    print(f'GPU detected: {torch.cuda.get_device_name(0)}')
    print(f'Memory before cleanup: {torch.cuda.memory_allocated()/1024**3:.2f}GB allocated')
    torch.cuda.empty_cache()
    torch.cuda.synchronize()
    print(f'Memory after cleanup: {torch.cuda.memory_allocated()/1024**3:.2f}GB allocated')
    print('CUDA cache cleared successfully')
else:
    print('No GPU detected, skipping CUDA cleanup')
" 2>/dev/null || echo "CUDA cleanup skipped (torch not available or no GPU)"
fi

# ------------------------------------------------------
# TTS SERVICE (FastAPI, preloads XTTS v2)
# ------------------------------------------------------
if ! pgrep -f "uvicorn tts_service" > /dev/null; then
    echo "=== Starting TTS Service (port 8001) ==="
    export TTS_SKIP_PRELOAD=1
    export HIGGS_DISABLE_CUDA_GRAPHS=1
    nohup python -m uvicorn tts_service:app \
        --host 0.0.0.0 \
        --port 8001 \
        --workers 1 \
        --log-level warning \
        >> $LOG_DIR/tts-service.log 2>&1 &
    TTS_PID=$!
    disown $TTS_PID
    if [ $FAST -eq 1 ]; then
        echo "TTS Service started (PID $TTS_PID) — fire & forget (--fast)"
    else
        echo "TTS Service started (PID $TTS_PID), waiting for service to be ready..."
        TTS_READY=0
        # Wait up to 10 minutes (300 × 2s). First pass: wait for uvicorn to respond at all,
        # then wait for status=="ok" (background model loading complete).
        for i in $(seq 1 300); do
            STATUS=$(curl -s http://localhost:8001/health 2>/dev/null \
                | python3 -c "import sys,json; print(json.load(sys.stdin).get('status',''))" 2>/dev/null) || true
            if [ "$STATUS" = "ok" ]; then
                echo -e "\rTTS Service ready! ($((i*2))s)                    "
                TTS_READY=1
                break
            elif [ "$STATUS" = "loading" ]; then
                printf "\rTTS Service loading... (%ds)   " $((i*2))
            else
                printf "\rTTS Service starting... (%ds)  " $((i*2))
            fi
            sleep 2
        done
        if [ $TTS_READY -eq 0 ]; then
            echo "WARNING: TTS Service did not become ready after 600s - check $LOG_DIR/tts-service.log"
        fi
    fi
else
    echo "TTS Service is already running."
fi

# ------------------------------------------------------
# REMONTAGE DES PARTAGES CIFS WAMA (partages réseau invités uniquement)
# ------------------------------------------------------
echo "=== Remounting WAMA CIFS shares (guest) ==="
curl -s --max-time 15 "http://127.0.0.1:$DJANGO_PORT/filemanager/api/mounts/remount/" \
    | python3 -c "import sys,json; d=json.load(sys.stdin); print(f'Remounted: {d.get(\"remounted\",0)}, Skipped: {d.get(\"skipped\",0)}')" 2>/dev/null \
    || echo "Remount skipped (gunicorn not ready yet or no CIFS shares)"

# ------------------------------------------------------
# CELERY WORKERS (gpu + default with autoscale)
# ------------------------------------------------------
# File descriptor limit — large ML models (20B+) open many shards/mmaps simultaneously.
# Write a persistent limits.d config (takes effect on next login; sudo required once).
LIMITS_FILE=/etc/security/limits.d/wama.conf
if [ ! -f "$LIMITS_FILE" ] || ! grep -q "nofile 65536" "$LIMITS_FILE" 2>/dev/null; then
    echo "=== Setting system file descriptor limits (requires sudo) ==="
    printf "* soft nofile 65536\n* hard nofile 65536\n" | sudo tee "$LIMITS_FILE" > /dev/null
fi
# Apply immediately to this shell (and all child processes, including Celery workers).
# prlimit can raise both soft+hard limits as root; fallback to hard limit if sudo fails.
sudo prlimit --nofile=65536:65536 --pid $$ 2>/dev/null \
    || ulimit -Sn "$(ulimit -Hn)" 2>/dev/null \
    || true
echo "File descriptor limit: $(ulimit -n)"

# Environment variables for AI models
export COQUI_TOS_AGREED=1
export TTS_HOME=$PROJECT_DIR/AI-models/synthesizer/tts
export CUDA_LAUNCH_BLOCKING=0
# WAMA est 100% PyTorch : on EMPÊCHE transformers d'importer TensorFlow/Flax. TF (installé mais inutile
# ici) saisirait un contexte CUDA parallèle → "CUDA error: unknown error" (cudaErrorUnknown) en WSL2.
export USE_TF=0
export USE_FLAX=0
# expandable_segments : mémoire virtuelle CUDA (cuMemMap), instable sous WSL2 → assert
# "!handles_.at(i)" (CUDACachingAllocator) qui fait planter les grosses générations (VibeVoice ASR).
# On le DÉSACTIVE en WSL, on le GARDE sur Linux natif (anti-fragmentation des gros modèles).
if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False
else
    export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
fi

# Suppress noisy but harmless framework warnings
export TF_CPP_MIN_LOG_LEVEL=2          # Suppress TensorFlow C++ INFO/WARNING messages
export PYTHONWARNINGS="ignore::FutureWarning:keras,ignore::DeprecationWarning:keras"  # Keras np.object FutureWarning

# GPU Worker: handles all GPU-intensive AI tasks (1 task at a time)
# Queue: gpu (anonymizer, imager, enhancer, synthesizer, transcriber, describer)
if ! pgrep -f "celery.*gpu@" > /dev/null; then
    echo "=== Starting Celery GPU Worker (solo) ==="
    celery -A wama worker \
        --pool=solo \
        --queues=gpu \
        --hostname=gpu@%h \
        --prefetch-multiplier=1 \
        --statedb=$LOG_DIR/celery-gpu.state \
        --loglevel=INFO \
        --detach \
        --logfile $LOG_DIR/celery-gpu.log
else
    echo "Celery GPU worker is already running."
fi

# Default Worker: handles light tasks (model_manager, periodic tasks)
# Elastic: starts with 1 process, scales up to 4 based on load
if ! pgrep -f "celery.*default@" > /dev/null; then
    echo "=== Starting Celery Default Worker (autoscale 1-4) ==="
    celery -A wama worker \
        --pool=prefork \
        --queues=default,celery \
        --hostname=default@%h \
        --autoscale=4,1 \
        --statedb=$LOG_DIR/celery-default.state \
        --loglevel=INFO \
        --detach \
        --logfile $LOG_DIR/celery-default.log
else
    echo "Celery Default worker is already running."
fi

# Studio Worker: ORCHESTRATEUR de pipelines (run_pipeline_task retient le worker pendant
# toute la durée du run — boucle de poll). File DÉDIÉE : sur une file partagée, N runs
# studio simultanés peuvent occuper tous les slots et affamer la tâche d'app qu'ils
# attendent (deadlock observé en dev/solo, smoke 03/08).
if ! pgrep -f "celery.*studio@" > /dev/null; then
    echo "=== Starting Celery Studio Worker (solo) ==="
    celery -A wama worker \
        --pool=solo \
        --queues=studio \
        --hostname=studio@%h \
        --statedb=$LOG_DIR/celery-studio.state \
        --loglevel=INFO \
        --detach \
        --logfile $LOG_DIR/celery-studio.log
else
    echo "Celery Studio worker is already running."
fi

# ------------------------------------------------------
# CELERY BEAT (optionnel)
# ------------------------------------------------------
if ! pgrep -f "celery.*beat" > /dev/null; then
    echo "=== Starting Celery Beat ==="
    celery -A wama beat \
        --loglevel=INFO \
        --detach \
        --logfile $LOG_DIR/celery-beat.log
else
    echo "Celery Beat is already running."
fi

# ------------------------------------------------------
# FIN
# ------------------------------------------------------
echo "=== WAMA production stack started successfully ==="
[ $FAST -eq 1 ] && echo "(fast mode — collectstatic skipped, TTS loading in background)"
echo "Django: http://localhost:$DJANGO_PORT"
echo "Logs: $LOG_DIR"
date
hostname -I
