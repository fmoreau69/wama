from django.apps import AppConfig


class CamAnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_lab.cam_analyzer'
    verbose_name = 'Cam Analyzer'

    def ready(self):
        """Initialize the cam analyzer when Django starts."""
        pass
