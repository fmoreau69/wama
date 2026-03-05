#!/bin/bash
set -e

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

mkdir -p $LOG_DIR

# ------------------------------------------------------
# ACTIVER L'ENVIRONNEMENT VIRTUEL
# ------------------------------------------------------
cd $PROJECT_DIR
source $VENV_DIR/bin/activate

echo "=== Starting WAMA production script ==="

# ------------------------------------------------------
# PostgreSQL
# ------------------------------------------------------
echo "=== Starting PostgreSQL ==="
sudo service postgresql start
sleep 3

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

# ------------------------------------------------------
# STATIC FILES
# ------------------------------------------------------
echo "=== Collecting static files ==="
python manage.py collectstatic --noinput --settings=$DJANGO_SETTINGS_MODULE

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
# GPU/CUDA CLEANUP (important pour HunyuanImage et autres modèles lourds)
# ------------------------------------------------------
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
        > $LOG_DIR/tts-service.log 2>&1 &
    TTS_PID=$!
    disown $TTS_PID
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
else
    echo "TTS Service is already running."
fi

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
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

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
        --loglevel=INFO \
        --detach \
        --logfile $LOG_DIR/celery-default.log
else
    echo "Celery Default worker is already running."
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
echo "Django: http://localhost:$DJANGO_PORT"
echo "Logs: $LOG_DIR"
date
hostname -I