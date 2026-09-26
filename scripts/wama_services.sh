# shellcheck shell=bash
# ------------------------------------------------------------------------------------------
# WAMA — environnement d'exécution et lancement des workers Celery : UNE définition.
#
# Sourcé par `start_wama_prod.sh` (démarrage) et par `scripts/worker_watchdog.sh` (relance d'un
# worker mort). Avant le 2026-09-24, l'environnement vivait en ligne dans le script de
# démarrage : une relance à la main devait le recopier, et la copie du jour en avait oublié
# trois variables (OLLAMA_HOST, TZ, WAMA_MODEL_BACKUP_PATH). Une relance doit reproduire le
# démarrage À L'IDENTIQUE — d'où ce fichier.
#
# Suppose : PROJECT_DIR et LOG_DIR posés, répertoire courant = PROJECT_DIR, venv activé.
# Appelants : `start_wama_prod.sh`, `start_wama_dev.sh` (qui déclare WAMA_DEFAULT_WORKER_POOL=solo)
# et `scripts/worker_watchdog.sh` (qui hérite de cette variable du script qui l'a lancé).
# ------------------------------------------------------------------------------------------

#: Les processus Celery surveillés et relancés, dans l'ordre de lancement.
WAMA_CELERY_WORKERS="gpu default studio beat"

# Configuration commune à tous les process (gunicorn compris).
wama_runtime_env() {
    # Ollama tourne sous Windows — WSL2 ne joint pas 127.0.0.1:11434 directement : on résout
    # l'IP de l'hôte au démarrage (surcharger par OLLAMA_HOST si besoin).
    export OLLAMA_HOST=${OLLAMA_HOST:-http://$(ip route show | awk '/^default/{print $3; exit}'):11434}
    # Fuseau : Paris — aligne les horodatages des journaux Python/Celery sur l'heure locale.
    export TZ=Europe/Paris
    # Sauvegarde distante des modèles (model_manager/remote_backup.py) : point de MONTAGE WSL.
    # Sûr même si non monté : is_available() voit l'absence du dossier et désactive proprement.
    export WAMA_MODEL_BACKUP_PATH=${WAMA_MODEL_BACKUP_PATH:-/mnt/shares/SAVES/DEEP_LEARNING/MODELS}
}

# Environnement des workers (modèles d'IA).
wama_worker_env() {
    # Limite de descripteurs relevée à la limite dure (le démarrage tente d'abord `prlimit`).
    ulimit -Sn "$(ulimit -Hn)" 2>/dev/null || true
    export COQUI_TOS_AGREED=1
    export TTS_HOME=$PROJECT_DIR/AI-models/synthesizer/tts
    export CUDA_LAUNCH_BLOCKING=0
    # WAMA est 100 % PyTorch : on EMPÊCHE transformers d'importer TensorFlow/Flax. TF saisirait
    # un contexte CUDA parallèle → « CUDA error: unknown error » (cudaErrorUnknown) en WSL2.
    export USE_TF=0
    export USE_FLAX=0
    # expandable_segments : mémoire virtuelle CUDA (cuMemMap), instable sous WSL2 → assert
    # « !handles_.at(i) » qui fait planter les grosses générations (VibeVoice ASR).
    # DÉSACTIVÉ en WSL, GARDÉ sur Linux natif (anti-fragmentation des gros modèles).
    if grep -qiE 'microsoft|wsl' /proc/version 2>/dev/null; then
        export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:False
    else
        export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
    fi
    # Avertissements de frameworks bruyants mais inoffensifs.
    export TF_CPP_MIN_LOG_LEVEL=2
    export PYTHONWARNINGS="ignore::FutureWarning:keras,ignore::DeprecationWarning:keras"
}

# Motif `pgrep -f` d'un worker — les crochets l'empêchent de se trouver lui-même (un
# `pgrep -f "celery.*gpu@"` lancé par `bash -lc` matchait sa propre ligne : faux « vivant »).
celery_worker_pattern() {
    case "$1" in
        gpu)     echo 'celery.*--hostname=[g]pu@' ;;
        default) echo 'celery.*--hostname=[d]efault@' ;;
        studio)  echo 'celery.*--hostname=[s]tudio@' ;;
        beat)    echo 'celery -A wama [b]eat' ;;
        *)       return 1 ;;
    esac
}

# Nom de nœud Celery (celui qu'écrit le méta `STARTED` d'une tâche) ; beat n'en a pas.
celery_worker_node() {
    case "$1" in
        gpu|default|studio) echo "$1@$(hostname)" ;;
        *) echo "$1" ;;
    esac
}

celery_worker_alive() {
    local pattern
    pattern=$(celery_worker_pattern "$1") || return 1   # un motif VIDE ferait tout matcher
    pgrep -f "$pattern" > /dev/null
}

start_celery_worker() {
    case "$1" in
        # GPU : tout ce qui est lourd en IA, UNE tâche à la fois (anonymizer, imager, enhancer,
        # synthesizer, transcriber, describer…). `--prefetch-multiplier=1` : aucun message
        # préchargé, donc rien à redélivrer après un crash (boucle freeze-relance du 26/07).
        gpu)
            celery -A wama worker --pool=solo --queues=gpu --hostname=gpu@%h \
                --prefetch-multiplier=1 --statedb="$LOG_DIR/celery-gpu.state" \
                --loglevel=INFO --detach --logfile "$LOG_DIR/celery-gpu.log" ;;
        # Default : tâches légères (model_manager, périodiques), élastique 1 → 4 process. Le
        # script de DEV le lance en pool solo (compatibilité WSL) : WAMA_DEFAULT_WORKER_POOL=solo.
        default)
            if [ "${WAMA_DEFAULT_WORKER_POOL:-prefork}" = solo ]; then
                celery -A wama worker --pool=solo --queues=default,celery --hostname=default@%h \
                    --statedb="$LOG_DIR/celery-default.state" \
                    --loglevel=INFO --detach --logfile "$LOG_DIR/celery-default.log"
            else
                celery -A wama worker --pool=prefork --queues=default,celery --hostname=default@%h \
                    --autoscale=4,1 --statedb="$LOG_DIR/celery-default.state" \
                    --loglevel=INFO --detach --logfile "$LOG_DIR/celery-default.log"
            fi ;;
        # Studio : ORCHESTRATEUR de pipelines (`run_pipeline_task` retient le worker pendant
        # tout le run). File DÉDIÉE : sur une file partagée, N runs studio peuvent occuper tous
        # les slots et affamer la tâche d'app qu'ils attendent (deadlock, smoke 03/08).
        studio)
            celery -A wama worker --pool=solo --queues=studio --hostname=studio@%h \
                --statedb="$LOG_DIR/celery-studio.state" \
                --loglevel=INFO --detach --logfile "$LOG_DIR/celery-studio.log" ;;
        beat)
            celery -A wama beat --loglevel=INFO --detach --logfile "$LOG_DIR/celery-beat.log" ;;
        *)
            echo "worker Celery inconnu : $1" >&2
            return 1 ;;
    esac
}
