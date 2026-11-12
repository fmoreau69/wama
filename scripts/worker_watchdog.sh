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
# LES SERVICES uvicorn (2026-11-09, `WAMA_MANIFEST_SPEC §7.1`) suivent les mêmes règles, à une
# différence près : un service absent de la liste de démarrage (`WAMA_SERVICES_AT_START`) ne revient
# que si un appelant l'a trouvé éteint, et un arrêt voulu ne compte pas dans le budget. La
# surveillance exécute aussi les ordres du model manager (lancer, arrêter, relancer : 2026-11-10).
# Le passage sur un processus vit dans `scripts/wama_services.sh` (`supervise_one`).
#
# Pause (maintenance, arrêt volontaire d'un worker) : `touch logs/worker_watchdog.pause`.
# ------------------------------------------------------------------------------------------
PROJECT_DIR=${PROJECT_DIR:-/mnt/d/WAMA/web-app-for-media-automation}
LOG_DIR=${LOG_DIR:-$PROJECT_DIR/logs}
cd "$PROJECT_DIR" || exit 1
# shellcheck source=scripts/wama_services.sh
source "$PROJECT_DIR/scripts/wama_services.sh"
# Le venv de l'environnement de référence, celui que déclare la définition commune.
[ -n "$VIRTUAL_ENV" ] || source "$(wama_reference_venv)/bin/activate"
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

report() {   # $1 = processus, $2 = issue, $3 = relances dans la fenêtre, $4 = celery|service
    local node
    node=$(celery_worker_node "$1")
    # Seule la ligne de bilan de la commande (« <nœud>: <issue> ; … ») va au journal : le reste
    # de la sortie de Django (avertissements de bibliothèques) n'y a pas sa place.
    python manage.py worker_died --node "$node" --outcome "$2" --restarts "$3" --kind "$4" 2>&1 \
        | grep -F "$node: " | tail -1
}

log "surveillance démarrée : $WAMA_CELERY_WORKERS $WAMA_SERVICES — toutes les ${INTERVAL_S}s, " \
    "au plus $MAX_RESTARTS relances en ${WINDOW_S}s par processus"

# Le signe de vie que lit le model manager (`service_supervision.watchdog_state`) : un ordre déposé
# pour une surveillance absente ne serait jamais exécuté.
ALIVE_FILE=$LOG_DIR/worker_watchdog.alive
touch "$ALIVE_FILE"

while true; do
    sleep "$INTERVAL_S"
    touch "$ALIVE_FILE"
    [ -f "$PAUSE_FILE" ] && continue
    for w in $WAMA_CELERY_WORKERS; do supervise_one "$w" celery; done
    for s in $WAMA_SERVICES; do supervise_one "$s" service; done
    for c in $WAMA_COMPANIONS; do supervise_companion "$c"; done
    supervise_web
    supervise_wama_restart
done
