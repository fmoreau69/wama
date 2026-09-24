#!/bin/bash
# ------------------------------------------------------------------------------------------
# SURVEILLANCE DES WORKERS CELERY — relance d'un worker mort (2026-09-24, décision de Fabien).
#
# Lancée par `start_wama_prod.sh` (qui l'arrête avant de tuer les workers au redémarrage).
# Même précédent que la passerelle Discord : un process que le démarrage lance ET surveille.
# Le MODE de supervision de production (systemd ou conteneurs) reste la décision ouverte
# d'INFRA_WSL_VS_WINDOWS point 5 ; ce script la précède, il ne la tranche pas.
#
# Trois règles, chacune née d'un piège mesuré :
#   • MORT = le PROCESSUS a disparu (`pgrep`). Jamais `celery inspect ping` : le worker gpu, en
#     pool solo, ne répond pas pendant une tâche — un worker OCCUPÉ ressemble à un worker mort
#     (le signal inversé du 25/07, `process_control.is_task_orphaned`).
#   • RELANCE = la fonction du démarrage (`scripts/wama_services.sh`), environnement compris :
#     la relance à la main du 24/09 avait oublié trois variables.
#   • BUDGET : au plus 3 relances d'un même worker en 30 min (fenêtre GLISSANTE — un arrêt
#     plus ancien ne compte plus). Au-delà, une tâche qui tue le worker à chaque reprise ferait
#     tourner la relance en boucle : on s'arrête et on le DIT.
# Après chaque mort : `manage.py worker_died` (traitements interrompus soldés, administrateurs
# prévenus dans WAMA et par e-mail). Le worker relancé solde lui-même, à son démarrage, les
# tâches de son prédécesseur (`wama/celery.py`, `worker_ready`) : les cards basculent en échec
# relançable à leur prochain rafraîchissement, sans recharger la page.
#
# Pause (maintenance, arrêt volontaire d'un worker) : `touch logs/worker_watchdog.pause`.
# ------------------------------------------------------------------------------------------
PROJECT_DIR=${PROJECT_DIR:-/mnt/d/WAMA/web-app-for-media-automation}
LOG_DIR=${LOG_DIR:-$PROJECT_DIR/logs}
cd "$PROJECT_DIR" || exit 1
[ -n "$VIRTUAL_ENV" ] || source "$PROJECT_DIR/venv_linux/bin/activate"
# shellcheck source=scripts/wama_services.sh
source "$PROJECT_DIR/scripts/wama_services.sh"
wama_runtime_env
wama_worker_env

INTERVAL_S=${WAMA_WATCHDOG_INTERVAL_S:-30}
MAX_RESTARTS=${WAMA_WATCHDOG_MAX_RESTARTS:-3}
WINDOW_S=${WAMA_WATCHDOG_WINDOW_S:-1800}
READY_WAIT_S=${WAMA_WATCHDOG_READY_WAIT_S:-60}
PAUSE_FILE=$LOG_DIR/worker_watchdog.pause

declare -A RESTARTS   # worker → horodatages (epoch) des relances de la fenêtre
declare -A GAVE_UP    # worker → 1 quand le budget est épuisé

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*"; }

report() {   # $1 = worker, $2 = issue, $3 = relances dans la fenêtre
    python manage.py worker_died --node "$(celery_worker_node "$1")" --outcome "$2" \
        --restarts "$3" 2>&1 | grep -vE 'pynvml|FutureWarning' | tail -1
}

log "surveillance démarrée : $WAMA_CELERY_WORKERS — toutes les ${INTERVAL_S}s, " \
    "au plus $MAX_RESTARTS relances en ${WINDOW_S}s par worker"

while true; do
    sleep "$INTERVAL_S"
    [ -f "$PAUSE_FILE" ] && continue
    for w in $WAMA_CELERY_WORKERS; do
        if celery_worker_alive "$w"; then
            GAVE_UP[$w]=''            # relancé à la main après une suspension : on reprend
            continue
        fi
        [ -n "${GAVE_UP[$w]}" ] && continue

        now=$(date +%s)
        recent=''
        n=0
        for t in ${RESTARTS[$w]}; do
            if [ $((now - t)) -lt "$WINDOW_S" ]; then recent="$recent $t"; n=$((n + 1)); fi
        done
        RESTARTS[$w]=$recent

        if [ "$n" -ge "$MAX_RESTARTS" ]; then
            GAVE_UP[$w]=1
            log "$w MORT — $n relances en ${WINDOW_S}s : relances SUSPENDUES"
            report "$w" gave_up "$n"
            continue
        fi

        log "$w MORT — relance ($((n + 1))/$MAX_RESTARTS dans la fenêtre)"
        start_celery_worker "$w"
        RESTARTS[$w]="${RESTARTS[$w]} $now"
        outcome=restart_failed
        waited=0
        while [ "$waited" -lt "$READY_WAIT_S" ]; do
            sleep 2
            waited=$((waited + 2))
            if celery_worker_alive "$w"; then outcome=restarted; break; fi
        done
        log "$w : $outcome"
        report "$w" "$outcome" "$((n + 1))"
    done
done
