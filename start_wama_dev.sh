#!/bin/bash
set -e

# ------------------------------------------------------
# STOP DES PROCESS EXISTANTS
# ------------------------------------------------------
echo "=== Stopping old processes if any ==="
pkill -f "manage.py runserver" || true
pkill -f "celery" || true
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
# CELERY WORKER (mode solo pour Windows/WSL compatibility)
# ------------------------------------------------------
if ! pgrep -f "celery.*worker" > /dev/null; then
    echo "=== Starting Celery Worker (solo mode) ==="
    # Accept Coqui TTS terms of service for non-commercial use
    export COQUI_TOS_AGREED=1
    celery -A wama worker \
        --loglevel=INFO \
        --pool=solo \
        --detach \
        --logfile $LOG_DIR/celery-worker.log
else
    echo "Celery worker is already running."
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
echo "=== WAMA development stack stopped ==="
