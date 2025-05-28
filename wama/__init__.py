from django.conf import settings

if getattr(settings, "ENABLE_CELERY", False):
    from .celery import app as celery_app
    __all__ = ('celery_app',)
