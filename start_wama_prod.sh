#!/bin/bash
set -e

# ------------------------------------------------------
# STOP DES PROCESS EXISTANTS
# ------------------------------------------------------
echo "=== Stopping old processes if any ==="
pkill -f "gunicorn wama.wsgi" || true
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
CELERY_WORKERS=4
GUNICORN_WORKERS=9
LOG_DIR=$PROJECT_DIR/logs

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
        --bind 0.0.0.0:$DJANGO_PORT \
        --workers $GUNICORN_WORKERS \
        --daemon \
        --env DJANGO_SETTINGS_MODULE=$DJANGO_SETTINGS_MODULE \
        --access-logfile $LOG_DIR/gunicorn-access.log \
        --error-logfile $LOG_DIR/gunicorn-error.log
else
    echo "Gunicorn is already running."
fi

# ------------------------------------------------------
# CELERY WORKER
# ------------------------------------------------------
if ! pgrep -f "celery.*worker" > /dev/null; then
    echo "=== Starting Celery Worker ==="
    # Accept Coqui TTS terms of service for non-commercial use
    export COQUI_TOS_AGREED=1
    celery -A wama worker \
        --loglevel=INFO \
        --concurrency=$CELERY_WORKERS \
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
# FIN
# ------------------------------------------------------
echo "=== WAMA production stack started successfully ==="
echo "Django: http://localhost:$DJANGO_PORT"
echo "Logs: $LOG_DIR"
hostname -I