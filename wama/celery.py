"""
https://docs.celeryproject.org/en/stable/django/first-steps-with-django.html
https://www.section.io/engineering-education/django-celery-tasks/
https://buildwithdjango.com/blog/post/celery-progress-bars/
https://github.com/czue/celery-progress
"""

# import eventlet
# eventlet.monkey_patch()

import os
from celery import Celery

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')

app = Celery('wama')
app.config_from_object('django.conf:settings', namespace='CELERY')
# Pool and concurrency are configured per-worker via CLI flags in start scripts
# (gpu worker = solo/1, default worker = prefork/autoscale)

# Auto-discover tasks across ALL installed apps — no manual list to maintain.
# A new app's Celery tasks are picked up automatically as long as they live in
# a `tasks.py` or a `workers.py` module (the two conventions used in WAMA).
#   tasks.py   : anonymizer, composer, converter, enhancer, imager,
#                model_manager, reader, cam_analyzer, face_analyzer, …
#   workers.py : avatarizer, describer, synthesizer, transcriber, …
app.autodiscover_tasks()
app.autodiscover_tasks(related_name='workers')


# ---------------------------------------------------------------------------
# Garde ressources — posée UNE FOIS PAR PROCESS WORKER, pas par tâche
# ---------------------------------------------------------------------------
# `worker_process_init` est émis dans CHAQUE process d'exécution : le process
# unique du pool `solo` (worker gpu) comme chacun des enfants `prefork` (worker
# default, autoscale 1-4). C'est le seul point qui couvre tous les backends,
# y compris ceux qui font `.to('cuda')` sans passer par le model_manager
# (transcriber/vibevoice, reader/olmocr, describer, avatarizer, imager ltx…).
#
# Sans ça, le plafond de l'allocateur CUDA ne protégeait que la voie diffusers
# de l'imager — et un débordement VRAM depuis une autre app pouvait encore faire
# paniquer le noyau WSL2 (4 kernel panics le 29/07/2026).
from celery.signals import worker_process_init  # noqa: E402


@worker_process_init.connect
def _wama_configure_worker_resources(**_kwargs):
    try:
        from wama.common.services.resource_governor import configure_cuda_process
        configure_cuda_process()
    except Exception:  # jamais bloquant pour le démarrage d'un worker
        pass

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
