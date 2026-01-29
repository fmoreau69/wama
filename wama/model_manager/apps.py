from django.apps import AppConfig


class ModelManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.model_manager'
    verbose_name = 'Model Manager'
