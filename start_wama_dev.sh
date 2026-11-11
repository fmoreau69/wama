#!/bin/bash
set -e

# ------------------------------------------------------
# SERVICES LANCÉS AU DÉMARRAGE — la liste à ajuster
# ------------------------------------------------------
# Ceux-ci démarrent avec WAMA et la surveillance les relance s'ils tombent. Les autres services
# (`WAMA_SERVICES`, scripts/wama_services.sh) démarrent à la demande : au premier appelant, ou depuis
# le volet droit du model manager. Exporté : Django et la surveillance en héritent.
export WAMA_SERVICES_AT_START="tts_service vector_service privacy_service"

# ------------------------------------------------------
# STOP DES PROCESS EXISTANTS
# ------------------------------------------------------
echo "=== Stopping old processes if any ==="
# La définition commune d'abord : l'arrêt lit les motifs des services qu'elle déclare.
PROJECT_DIR=/mnt/d/WAMA/web-app-for-media-automation
source $PROJECT_DIR/scripts/wama_services.sh
pkill -f "manage.py runserver" || true
# La surveillance des workers d'abord : laissée en vie, elle relancerait ceux qu'on arrête.
pkill -f "scripts/[w]orker_watchdog.sh" || true
pkill -f "celery" || true
for s in $WAMA_SERVICES; do pkill -f "$(wama_service_pattern "$s")" || true; done
pkill -f "redis-server" || true

sleep 2

# ------------------------------------------------------
# CONFIGURATION
# ------------------------------------------------------
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

# Environnement d'exécution et lancement des workers : UNE définition, partagée avec la production
# et la surveillance des workers (scripts/wama_services.sh). En dev, le worker default tourne en
# pool solo (compatibilité WSL) — déclaré ici, hérité par la surveillance qui le relance. Les
# services lancés ici gardent leur sortie au terminal (non exporté : la surveillance écrit au journal).
WAMA_SERVICE_ON_TERMINAL=1
rm -f "$LOG_DIR"/service_wanted.* "$LOG_DIR"/service_stopped.* "$LOG_DIR"/service_held.* "$LOG_DIR"/service_launch.*
rm -f "$LOG_DIR"/wama_restart "$LOG_DIR"/worker_seen.*
export WAMA_DEFAULT_WORKER_POOL=solo
# Page d'erreur détaillée en développement seulement : la production tourne `DEBUG` éteint
# (`wama/settings.py`, 2026-11-08).
export WAMA_DEBUG=1
wama_runtime_env

echo "=== Starting WAMA development script ==="

# ------------------------------------------------------
# PostgreSQL
# ------------------------------------------------------
echo "=== Starting PostgreSQL ==="
sudo service postgresql start
sleep 3

# Extension pgvector — prérequis des tables mémoire/RAG (cf. WAMA_MEMORY.md §7). Posée ici parce
# que `.gitignore` exclut les migrations numérotées : celle qui porte `VectorExtension()` n'est pas
# versionnée et serait régénérée sans elle sur une base neuve. Idempotent.
sudo -u postgres psql -d "${WAMA_DB_NAME:-wama_db}" -c 'CREATE EXTENSION IF NOT EXISTS vector;' >/dev/null 2>&1 \
    || echo "AVERTISSEMENT: extension pgvector non verifiee — voir WAMA_MEMORY.md §7"

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

# Seeds idempotents (rôles + politiques d'accès, mots-clés de prompt) — sûrs à chaque démarrage.
echo "=== Seeding access policies + prompt keywords ==="
python manage.py seed_access --settings=$DJANGO_SETTINGS_MODULE || true
python manage.py seed_prompt_keywords --settings=$DJANGO_SETTINGS_MODULE || true

# Journaux : on DÉCALE (X.log → X.log.1 → …), on n'écrase pas — la trace d'un crash
# doit survivre au redémarrage qui suit. Services arrêtés ici, avant relance.
echo "=== Rotating logs (9 runs conservés) ==="
python manage.py rotate_logs --settings=$DJANGO_SETTINGS_MODULE || true

# Playwright Chromium (HTML→PDF fidèle, brique commune) — provisioning idempotent, non bloquant.
# Navigateur = cache Playwright par défaut (~/.cache/ms-playwright) ; fallback WeasyPrint si absent.
if python -c "import playwright" 2>/dev/null; then
    PW_DEPS_MARKER="$HOME/.cache/ms-playwright/.wama-os-deps-ok"
    if [ ! -f "$PW_DEPS_MARKER" ]; then
        echo "=== Provisioning Playwright Chromium (one-time) ==="
        if python -m playwright install --with-deps chromium; then
            mkdir -p "$(dirname "$PW_DEPS_MARKER")" && touch "$PW_DEPS_MARKER"
        else
            python -m playwright install chromium || echo "WARN: Chromium indisponible → fallback WeasyPrint"
        fi
    else
        python -m playwright install chromium >/dev/null 2>&1 || true
    fi
fi

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

# Environnement des process qui chargent des modèles (scripts/wama_services.sh), AVANT les
# services : ils chargent eux aussi des modèles (mêmes raisons que start_wama_prod.sh).
wama_worker_env

# ------------------------------------------------------
# TTS SERVICE (FastAPI, preloads XTTS v2)
# ------------------------------------------------------
if ! wama_service_at_start tts_service; then
    echo "TTS Service : à la demande (hors de WAMA_SERVICES_AT_START)"
elif ! wama_service_alive tts_service; then
    echo "=== Starting TTS Service (port 8001) ==="
    start_wama_service tts_service
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

# Les autres services de la liste (boucle locale seule) — mêmes rôles que dans start_wama_prod.sh.
for s in $WAMA_SERVICES_AT_START; do
    [ "$s" = tts_service ] && continue       # plus haut : il a son attente de préchargement
    if ! wama_service_alive "$s"; then
        echo "=== Starting $s ==="
        start_wama_service "$s"
    else
        echo "$s is already running."
    fi
done

# ------------------------------------------------------
# CELERY WORKERS (2 workers: gpu + default)
# ------------------------------------------------------
# Environnement des workers et lancements : scripts/wama_services.sh (mêmes que la production,
# worker default en pool solo par WAMA_DEFAULT_WORKER_POOL ci-dessus). L'environnement est posé
# plus haut, avant les services.
for w in $WAMA_CELERY_WORKERS; do
    if ! celery_worker_alive "$w"; then
        echo "=== Starting Celery $w ==="
        start_celery_worker "$w"
    else
        echo "Celery $w is already running."
    fi
done

# Surveillance des workers (relance d'un worker mort) — cf. start_wama_prod.sh.
if ! pgrep -f "scripts/[w]orker_watchdog.sh" > /dev/null; then
    echo "=== Starting worker watchdog ==="
    export WAMA_START_SCRIPT="$PROJECT_DIR/start_wama_dev.sh"
    nohup bash $PROJECT_DIR/scripts/worker_watchdog.sh >> $LOG_DIR/worker-watchdog.log 2>&1 &
    disown $!
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
for s in $WAMA_SERVICES; do pkill -f "$(wama_service_pattern "$s")" || true; done
echo "=== WAMA development stack stopped ==="
