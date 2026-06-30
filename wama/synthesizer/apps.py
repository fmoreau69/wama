from django.apps import AppConfig

class SynthesizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.synthesizer'
    verbose_name = 'Synthesizer'

    def ready(self):
        # Import Celery tasks to ensure they are discovered
        import wama.synthesizer.workers

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchSynthesisItem
            register_batch_sync(BatchSynthesisItem)
        except Exception:
            pass

        # Register for unified preview
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.preview_utils import synthesizer_preview_adapter
        from .models import VoiceSynthesis

        PreviewRegistry.register(
            app_name='synthesizer',
            model_class=VoiceSynthesis,
            adapter=synthesizer_preview_adapter,
            file_field='audio_output',
            user_field='user'
        )