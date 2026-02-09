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

# Restart workers after handling N requests (prevents memory leaks)
max_requests = 1000
max_requests_jitter = 50


# Worker lifecycle hooks
def post_worker_init(worker):
    """Called just after a worker has been initialized."""
    logger = logging.getLogger('gunicorn.error')
    logger.info(f"[Worker {worker.pid}] Worker initialized")
