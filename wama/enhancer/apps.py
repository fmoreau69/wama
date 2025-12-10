from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class EnhancerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.enhancer'
    verbose_name = 'Enhancer - AI Image/Video Upscaling'

    def ready(self):
        """Called when Django starts - check and download models if needed."""
        # Only run in main process (not in reloader or other subprocesses)
        import os
        if os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from .utils.model_downloader import check_and_download_essential_models
            logger.info("Checking AI models for Enhancer app...")
            check_and_download_essential_models()
        except Exception as e:
            logger.warning(f"Could not auto-download models: {e}")
            logger.info("Models can be downloaded manually from: https://github.com/Djdefrag/QualityScaler/releases")
