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
    # Battement des réservations (2026-09-14) : un modèle résident d'un worker voyait sa
    # ligne de registre expirer au bout du TTL (1 h) — seul le service TTS la rafraîchissait.
    # Il redevenait invisible du gouverneur tout en occupant la VRAM. Même brique que le TTS.
    try:
        from wama.common.backends.base import start_reservation_heartbeat
        start_reservation_heartbeat()
    except Exception:
        pass
    # Le worker se DÉCLARE tenant (B1, 2026-09-20) : il sert les demandes de libération des
    # autres process — le déchargement ne restait jusque-là possible qu'à l'intérieur du process
    # qui le demandait. Le tenant par défaut du contrat : décharge ses backends résidents, ne
    # recharge rien (ils reviennent au prochain usage), n'est jamais « occupé » de lui-même —
    # sa tâche en cours est déclarée par le squelette, c'est elle qui compte.
    try:
        from wama.common.services.resource_governor import (
            contract_tenant, start_release_listener, tenant_id)
        start_release_listener(contract_tenant(f"celery:{tenant_id()}"))
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Un worker qui DÉMARRE solde les tâches de son prédécesseur mort (2026-09-24)
# ---------------------------------------------------------------------------
# Un worker tué en pleine tâche laissait ses éléments RUNNING à vie : la réconciliation
# commune ne tournait qu'au CHARGEMENT d'une page d'app, et seulement si le worker répondait à
# `inspect()`. Le worker relancé — par la surveillance, le script de démarrage ou à la main —
# détient la preuve positive : son nom, et les processus de SA machine. `worker_ready` est émis
# une fois, dans le processus principal. Les cards le voient à leur prochain rafraîchissement.
from celery.signals import worker_ready  # noqa: E402


@worker_ready.connect
def _wama_settle_dead_predecessor(sender=None, **_kwargs):
    try:
        from wama.common.utils.process_control import reconcile_dead_worker_tasks
        hostname = getattr(sender, 'hostname', '') or ''
        done = reconcile_dead_worker_tasks(hostname)
    except Exception:
        return                          # jamais bloquant pour le démarrage d'un worker
    if not done:
        return
    try:
        from wama.common.utils.notifications import notify_admins
        items = ', '.join(f"{label} #{pk}" for label, _model, pk in done[:20])
        more = f" (+{len(done) - 20})" if len(done) > 20 else ''
        notify_admins(
            'worker_tasks_interrupted',
            f"{len(done)} traitement(s) interrompu(s) par l'arrêt du worker {hostname}",
            f"Le worker {hostname} s'était arrêté pendant ces traitements : {items}{more}.\n"
            "Ils sont passés en échec relançable ; les relancer depuis leur card.")
    except Exception:
        pass


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
