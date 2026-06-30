from django.apps import AppConfig


class StudioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.studio'
    verbose_name = 'Studio - Méta-app (orchestration de pipelines)'
