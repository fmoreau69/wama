# Gunicorn configuration file
import multiprocessing
import os
import logging
import threading

# Server socket
bind = "0.0.0.0:8000"

# Worker processes
workers = 9
worker_class = "sync"

# Timeout
# Increased to 120 seconds to allow for TTS model loading on first request
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

# Worker lifecycle hooks
def post_worker_init(worker):
    """
    Called just after a worker has been initialized.

    NOTE: TTS model preloading is DISABLED to avoid memory issues.
    With 9 workers × 1.8GB model = ~16GB RAM required.
    Models are loaded on-demand (lazy loading) instead.
    The 120s timeout allows first-request model loading.
    """
    logger = logging.getLogger('gunicorn.error')
    logger.info(f"[Worker {worker.pid}] Worker initialized (TTS preloading disabled)")
