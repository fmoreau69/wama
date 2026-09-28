from django.apps import AppConfig


class FaceAnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_lab.face_analyzer'
    verbose_name = 'Face Analyzer'

    def ready(self):
        """Initialize the face analyzer when Django starts."""
        # Le monde Lab entre au journal et au calendrier (WAMA_MEMORY §9bis.1).
        from wama.common.services.journal import MONDE_LAB, enregistrer_source
        from .models import AnalysisSession
        enregistrer_source('face_analyzer', AnalysisSession, monde=MONDE_LAB)
