from django.apps import AppConfig


class FaceAnalyzerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_lab.face_analyzer'
    verbose_name = 'Face Analyzer'

    def ready(self):
        """Initialize the face analyzer when Django starts."""
        pass
