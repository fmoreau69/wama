from django.apps import AppConfig


class TranscriberConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.transcriber'
    verbose_name = 'Transcriber'

    def ready(self):
        # Import tasks for Celery autodiscovery
        try:
            import wama.transcriber.workers  # noqa: F401
        except Exception:
            pass

        # Register for unified preview
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.preview_utils import transcriber_preview_adapter
        from .models import Transcript

        PreviewRegistry.register(
            app_name='transcriber',
            model_class=Transcript,
            adapter=transcriber_preview_adapter,
            file_field='audio_file',
            user_field='user'
        )
