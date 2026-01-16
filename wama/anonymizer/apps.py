from django.apps import AppConfig

class AnonymizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.anonymizer'

    def ready(self):
        import wama.anonymizer.signals

        # Register for unified preview
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.preview_utils import anonymizer_preview_adapter
        from .models import Media

        PreviewRegistry.register(
            app_name='anonymizer',
            model_class=Media,
            adapter=anonymizer_preview_adapter,
            file_field='file',
            user_field='user'
        )
