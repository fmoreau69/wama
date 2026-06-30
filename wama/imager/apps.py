from django.apps import AppConfig


class ImagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.imager'
    verbose_name = 'Imager - AI Image Generation'

    def ready(self):
        from . import signals  # noqa: F401  (enregistre les receivers de notification)
