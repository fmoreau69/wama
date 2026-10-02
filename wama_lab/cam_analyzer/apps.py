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
        # L'app se DÉCLARE au substrat : son monde et sa page (menu, `/apps/`, journal, calendrier
        # la lisent — route §10.6 point 6.1). Le substrat ne cite plus le Lab par son nom.
        from wama.common.app_registry import register_surface
        register_surface('cam_analyzer', world='lab', label='Cam Analyzer',
                         url_name='wama_lab:cam_analyzer:index', icon='fa-video',
                         color='#ffc107', order=20)
        # Le monde Lab entre au journal et au calendrier (WAMA_MEMORY §9bis.1) : une card du
        # cam_analyzer est une SESSION d'analyse, datée de bout en bout (started/completed_at).
        from wama.common.services.journal import enregistrer_source
        from .models import AnalysisSession
        enregistrer_source('cam_analyzer', AnalysisSession)
