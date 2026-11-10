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
WAMA_CELERY_WORKERS="gpu default studio nightly beat"

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

# Environnement des process qui chargent des modèles d'IA : les workers ET les services uvicorn
# (voix, vecteurs, confidentialité), que les scripts de démarrage lancent après lui (2026-11-04).
wama_worker_env() {
    # Limite de descripteurs relevée à la limite dure (le démarrage tente d'abord `prlimit`).
    ulimit -Sn "$(ulimit -Hn)" 2>/dev/null || true
    # `TTS_HOME` / `COQUI_TOS_AGREED` : posés par `settings.py` et l'amorce du service de voix
    # (2026-10-31). L'export qui vivait ici visait `AI-models/synthesizer/tts`, un dossier qui
    # n'existe plus — et, exporté, il aurait primé sur le `setdefault` de `settings.py`.
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
        nightly) echo 'celery.*--hostname=[n]ightly@' ;;
        beat)    echo 'celery -A wama [b]eat' ;;
        *)       return 1 ;;
    esac
}

# Nom de nœud Celery (celui qu'écrit le méta `STARTED` d'une tâche) ; beat n'en a pas.
celery_worker_node() {
    case "$1" in
        gpu|default|studio|nightly) echo "$1@$(hostname)" ;;
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
        # préchargé AU-DELÀ de celui qui s'exécute (boucle freeze-relance du 26/07). ⚠ Corrigé
        # le 2026-10-13 : « rien à redélivrer après un crash » était faux — en pool solo, le
        # message EN COURS reste non acquitté jusqu'à sa fin (mesuré) ; un crash le laisse dans
        # `unacked`, Redis le rend à l'échéance de visibilité (6 h). Un démarrage note son heure
        # (`global_queue.note_consumer_ready`) : la file globale y reconnaît les orphelins.
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
        # Nightly : ORCHESTRATEUR des tests nocturnes (`common.run_nightly_tests`, plusieurs heures
        # par campagne). File DÉDIÉE pour la même raison que le Studio : sur `gpu` (solo), les
        # traitements que ses gestes lancent n'étaient servis qu'après elle (2026-10-13).
        nightly)
            celery -A wama worker --pool=solo --queues=nightly --hostname=nightly@%h \
                --prefetch-multiplier=1 --statedb="$LOG_DIR/celery-nightly.state" \
                --loglevel=INFO --detach --logfile "$LOG_DIR/celery-nightly.log" ;;
        beat)
            celery -A wama beat --loglevel=INFO --detach --logfile "$LOG_DIR/celery-beat.log" ;;
        *)
            echo "worker Celery inconnu : $1" >&2
            return 1 ;;
    esac
}

# ------------------------------------------------------------------------------------------
# Les SERVICES uvicorn : mêmes règles que les workers, une définition (2026-11-09, service
# TensorFlow, `WAMA_MANIFEST_SPEC §7.1`). Chacun est aussi une source déclarée, sur le même port
# (`common/external_sources.py`, tenu par `tests_tensorflow_service`).
# ------------------------------------------------------------------------------------------

#: Les services surveillés et relancés, dans l'ordre de lancement.
WAMA_SERVICES="tts_service vector_service privacy_service tensorflow_service"

# "<module> <port> <journal> <politique>". Politique : `always` = relancé dès qu'il meurt ;
# `on_demand` = relancé seulement quand un appelant l'a trouvé éteint (`service_wanted`) — le
# service TensorFlow s'arrête pour rendre la carte, le relancer aussitôt la reprendrait.
wama_service_spec() {
    case "$1" in
        tts_service)        echo "wama.common.tts.service 8001 tts-service.log always" ;;
        vector_service)     echo "wama.common.vectors.service 8002 vector-service.log always" ;;
        privacy_service)    echo "wama.common.privacy.service 8003 privacy-service.log always" ;;
        tensorflow_service) echo "wama.common.tensorflow_service.service 8004 tensorflow-service.log on_demand" ;;
        *) return 1 ;;
    esac
}

# Motif `pgrep -f` : crochets comme pour les workers. La voix et les vecteurs reconnaissent AUSSI
# leur ancienne ligne de commande (modules de la racine, avant le 2026-10-28) : sans elle, un
# service lancé avant le déplacement survivrait à l'arrêt et garderait son port.
wama_service_pattern() {
    case "$1" in
        tts_service)        echo '[u]vicorn (wama\.common\.tts\.service|tts_service):app' ;;
        vector_service)     echo '[u]vicorn (wama\.common\.vectors\.service|vector_service):app' ;;
        privacy_service)    echo '[u]vicorn wama\.common\.privacy\.service:app' ;;
        tensorflow_service) echo '[u]vicorn wama\.common\.tensorflow_service\.service:app' ;;
        *) return 1 ;;
    esac
}

wama_service_alive() {
    local pattern
    pattern=$(wama_service_pattern "$1") || return 1    # un motif VIDE ferait tout matcher
    pgrep -f "$pattern" > /dev/null
}

# Boucle locale SEULE, aucun service n'a d'authentification. `--workers 1` est structurant : N
# processus tiendraient N fois les modèles. `WAMA_SERVICE_ON_TERMINAL` (non exportée, posée par le
# script de développement) laisse la sortie au terminal : la surveillance, elle, écrit au journal.
start_wama_service() {
    local spec module port log_file _policy
    spec=$(wama_service_spec "$1") || { echo "service inconnu : $1" >&2; return 1; }
    read -r module port log_file _policy <<< "$spec"
    if [ -n "${WAMA_SERVICE_ON_TERMINAL:-}" ]; then
        python -m uvicorn "$module:app" --host 127.0.0.1 --port "$port" --workers 1 \
            --log-level "${WAMA_SERVICE_LOG_LEVEL:-info}" &
    else
        nohup python -m uvicorn "$module:app" --host 127.0.0.1 --port "$port" --workers 1 \
            --log-level "${WAMA_SERVICE_LOG_LEVEL:-warning}" >> "$LOG_DIR/$log_file" 2>&1 &
        disown $!
    fi
}

# UN passage de la surveillance sur UN processus ($1 = nom, $2 = celery|service). Ici et pas dans
# `worker_watchdog.sh` pour s'exécuter sous test. L'appelant fournit `log`, `report`, `RESTARTS`,
# `GAVE_UP`, `MAX_RESTARTS`, `WINDOW_S` et `READY_WAIT_S`.
# Drapeaux d'un service (`common/utils/service_supervision.py`) : `service_wanted` = un appelant
# l'a trouvé éteint ; `service_stopped` = arrêt VOULU, sa relance est hors budget et sans rapport.
supervise_one() {
    local w=$1 kind=$2 alive=celery_worker_alive start=start_celery_worker policy=always
    local _module _port _log wanted="$LOG_DIR/service_wanted.$1" stopped="$LOG_DIR/service_stopped.$1"
    if [ "$kind" = service ]; then
        alive=wama_service_alive
        start=start_wama_service
        read -r _module _port _log policy <<< "$(wama_service_spec "$w")"
    fi

    if "$alive" "$w"; then
        GAVE_UP[$w]=''            # relancé à la main après une suspension : on reprend
        [ "$policy" = on_demand ] && rm -f "$wanted" "$stopped"
        return 0
    fi
    # Personne n'en a besoin : un service arrêté pour rendre la carte reste arrêté.
    [ "$policy" = on_demand ] && [ ! -f "$wanted" ] && return 0
    [ -n "${GAVE_UP[$w]}" ] && return 0

    local on_purpose='' now recent='' n=0 t outcome=restart_failed waited=0
    [ "$kind" = service ] && [ -f "$stopped" ] && on_purpose=1
    now=$(date +%s)
    for t in ${RESTARTS[$w]}; do
        if [ $((now - t)) -lt "$WINDOW_S" ]; then recent="$recent $t"; n=$((n + 1)); fi
    done
    RESTARTS[$w]=$recent

    if [ -z "$on_purpose" ] && [ "$n" -ge "$MAX_RESTARTS" ]; then
        GAVE_UP[$w]=1
        log "$w MORT — $n relances en ${WINDOW_S}s : relances SUSPENDUES"
        report "$w" gave_up "$n" "$kind"
        return 0
    fi

    if [ -n "$on_purpose" ]; then
        log "$w : arrêt voulu, relance à la demande"
    else
        log "$w MORT — relance ($((n + 1))/$MAX_RESTARTS dans la fenêtre)"
        RESTARTS[$w]="${RESTARTS[$w]} $now"
    fi
    "$start" "$w"
    while [ "$waited" -lt "$READY_WAIT_S" ]; do
        sleep 2
        waited=$((waited + 2))
        if "$alive" "$w"; then outcome=restarted; break; fi
    done
    log "$w : $outcome"
    rm -f "$stopped"
    # Une relance voulue et réussie n'est pas un incident : on ne prévient personne.
    if [ -z "$on_purpose" ] || [ "$outcome" != restarted ]; then
        report "$w" "$outcome" "$((n + 1))" "$kind"
    fi
}
