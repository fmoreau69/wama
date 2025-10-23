from django.apps import AppConfig


class TranscriberConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.transcriber'
    verbose_name = 'Transcriber'

    def ready(self):
        # Import tasks for Celery autodiscovery
        try:
            import wama.transcriber.workers  # noqa: F401
        except Exception:
            pass
