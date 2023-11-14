"""https://docs.celeryproject.org/en/stable/django/first-steps-with-django.html
https://www.section.io/engineering-education/django-celery-tasks/
https://buildwithdjango.com/blog/post/celery-progress-bars/
https://github.com/czue/celery-progress
"""
import os
from celery import Celery
from . import settings

# set the default Django settings module for the 'celery' program.
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wama.settings')
# app = Celery('wama', broker='redis://127.0.0.1:6379//')
app = Celery('wama')

# Using a string here means the worker doesn't have to serialize
# the configuration object to child processes.
# - namespace='CELERY' means all celery-related configuration keys
#   should have a `CELERY_` prefix.
app.config_from_object('django.conf:settings', namespace='CELERY')

# Load task modules from all registered Django app configs.
# app.autodiscover_tasks()
app.autodiscover_tasks(lambda: settings.INSTALLED_APPS)


@app.task(bind=True)
def debug_task(self):
    print(f'Request: {self.request!r}')


@app.task
def do_work(self, list_of_work, progress_observer):
    total_work_to_do = len(list_of_work)
    for i, work_item in enumerate(list_of_work):
        # do_work_item(work_item)
        # tell the progress observer how many out of the total items we have processed
        progress_observer.set_progress(i, total_work_to_do)
    return 'work is complete'
