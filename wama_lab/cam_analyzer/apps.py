from django.apps import AppConfig


class CamAnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_lab.cam_analyzer'
    verbose_name = 'Cam Analyzer'

    def ready(self):
        """Initialize the cam analyzer when Django starts."""
        # Déclare les traitements cam_analyzer dans le catalogue WAMA Data (capabilities).
        try:
            from . import function_specs  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                'cam_analyzer function_specs non enregistrées', exc_info=True)
