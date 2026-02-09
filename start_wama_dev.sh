#!/bin/bash
set -e

# ------------------------------------------------------
# STOP DES PROCESS EXISTANTS
# ------------------------------------------------------
echo "=== Stopping old processes if any ==="
pkill -f "manage.py runserver" || true
pkill -f "celery" || true
pkill -f "uvicorn tts_service" || true
pkill -f "redis-server" || true

sleep 2

# ------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------
PROJECT_DIR=/mnt/d/WAMA/web-app-for-media-automation
VENV_DIR=$PROJECT_DIR/venv_linux
DJANGO_SETTINGS_MODULE=wama.settings
DJANGO_PORT=8000
LOG_DIR=$PROJECT_DIR/logs

mkdir -p $LOG_DIR

# ------------------------------------------------------
# ACTIVER L'ENVIRONNEMENT VIRTUEL
# ------------------------------------------------------
cd $PROJECT_DIR
source $VENV_DIR/bin/activate

echo "=== Starting WAMA development script ==="

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
# STATIC FILES (optionnel en dev, mais utile)
# ------------------------------------------------------
echo "=== Collecting static files ==="
python manage.py collectstatic --noinput --settings=$DJANGO_SETTINGS_MODULE

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
    python -m uvicorn tts_service:app \
        --host 0.0.0.0 \
        --port 8001 \
        --workers 1 \
        --log-level info &
    echo "Waiting for TTS Service to load model..."
    for i in $(seq 1 60); do
        if curl -s http://localhost:8001/health > /dev/null 2>&1; then
            echo "TTS Service ready!"
            break
        fi
        sleep 2
    done
else
    echo "TTS Service is already running."
fi

# ------------------------------------------------------
# CELERY WORKERS (2 workers: gpu + default)
# ------------------------------------------------------
# Environment variables for AI models
export COQUI_TOS_AGREED=1
export TTS_HOME=$PROJECT_DIR/AI-models/synthesizer/tts
export CUDA_LAUNCH_BLOCKING=0
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

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
# Pool solo for WSL compatibility
if ! pgrep -f "celery.*default@" > /dev/null; then
    echo "=== Starting Celery Default Worker (solo) ==="
    celery -A wama worker \
        --pool=solo \
        --queues=default,celery \
        --hostname=default@%h \
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
# DJANGO DEVELOPMENT SERVER (en foreground pour voir les logs)
# ------------------------------------------------------
echo "=== Starting Django Development Server ==="
echo "Django will run in FOREGROUND. Press Ctrl+C to stop."
echo "================================================================"
python manage.py runserver 0.0.0.0:$DJANGO_PORT --settings=$DJANGO_SETTINGS_MODULE

# ------------------------------------------------------
# CLEANUP (si on arrive ici après Ctrl+C)
# ------------------------------------------------------
echo ""
echo "=== Shutting down... ==="
pkill -f "celery" || true
pkill -f "uvicorn tts_service" || true
echo "=== WAMA development stack stopped ==="
