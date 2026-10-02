from django.apps import AppConfig


class FaceAnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_lab.face_analyzer'
    verbose_name = 'Face Analyzer'

    def ready(self):
        """Initialize the face analyzer when Django starts."""
        # L'app se DÉCLARE au substrat : son monde et sa page (menu, `/apps/`, journal, calendrier
        # la lisent — route §10.6 point 6.1).
        from wama.common.app_registry import register_surface
        register_surface('face_analyzer', world='lab', label='Face Analyzer',
                         url_name='wama_lab:face_analyzer:index', icon='fa-face-smile',
                         color='#0dcaf0', order=10,
                         description="Analyse non invasive de signaux physiologiques à partir "
                                     "d'une vidéo du visage : fréquence cardiaque et sa "
                                     "variabilité, suivi du regard, émotions, respiration.")
        # Le monde Lab entre au journal et au calendrier (WAMA_MEMORY §9bis.1).
        from wama.common.services.journal import enregistrer_source
        from .models import AnalysisSession
        enregistrer_source('face_analyzer', AnalysisSession)
