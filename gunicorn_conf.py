# Gunicorn configuration file
import logging

# Server socket
bind = "0.0.0.0:8000"

# Worker processes - 4 stable workers, always available
workers = 4
worker_class = "gthread"
threads = 2  # 4 workers x 2 threads = 8 concurrent requests

# Timeout
# 120s to allow for first-request model loading via lazy imports
timeout = 120
graceful_timeout = 30
keepalive = 5

# Logging
accesslog = "logs/gunicorn-access.log"
errorlog = "logs/gunicorn-error.log"
loglevel = "info"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Process naming
proc_name = "wama"

# Server mechanics
daemon = True
pidfile = "logs/gunicorn.pid"

# `daemon = True` redirige stdout/stderr vers /dev/null (gunicorn/util.py:daemonize),
# et `errorlog` ne reçoit QUE les logs propres de gunicorn. Sans cette ligne, tout ce
# que l'application écrit sur stderr est perdu — mesuré le 2026-08-24 : 11 réponses 500
# en 36 h, ZÉRO traceback dans gunicorn-error.log (494 lignes, dont les 52 [ERROR] ne
# sont que des `Worker was sent SIGTERM` de recyclage `max_requests`).
capture_output = True

# Restart workers after handling N requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50


# Worker lifecycle hooks
def post_worker_init(worker):
    """Called just after a worker has been initialized."""
    logger = logging.getLogger('gunicorn.error')
    logger.info(f"[Worker {worker.pid}] Worker initialized")

    # Préchauffage de l'assistant, EN ARRIÈRE-PLAN (2026-10-04) : le premier tour d'un worker
    # payait ~20 s d'`import litellm` puis ~10 s de caches de processus — après chaque relance
    # et à chaque recyclage `max_requests`. Un fil démon : le worker sert tout de suite.
    # Dans le WORKER et non dans le maître : Django n'est chargé qu'ici (pas de `preload_app`),
    # et l'importer dans le maître retarderait de 20 s l'ouverture du port à chaque relance.
    import threading

    def _warm():
        try:
            from wama.common.services.assistant_engine import warm_up
            logger.info(f"[Worker {worker.pid}] assistant préchauffé : {warm_up()}")
        except Exception as e:
            logger.warning(f"[Worker {worker.pid}] préchauffage de l'assistant impossible : {e}")
        finally:
            # La connexion ouverte par CE fil (lecture du catalogue) : hors du cycle
            # requête/réponse, personne d'autre ne la rendrait.
            try:
                from django.db import connections
                connections.close_all()
            except Exception:
                pass

    threading.Thread(target=_warm, name='wama-assistant-warm-up', daemon=True).start()
