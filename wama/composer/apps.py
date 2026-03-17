from django.apps import AppConfig


class ComposerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.composer'
    verbose_name = 'Composer'

    def ready(self):
        try:
            import wama.composer.tasks  # noqa: F401
        except Exception:
            pass
