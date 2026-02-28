from django.apps import AppConfig


class AvatarizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.avatarizer'
    verbose_name = 'Avatarizer'

    def ready(self):
        # Import Celery tasks to ensure they are discovered by the worker
        import wama.avatarizer.workers  # noqa
