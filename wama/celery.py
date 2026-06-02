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

@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')
