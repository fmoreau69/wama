from django.apps import AppConfig


class ComposerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.composer'
    verbose_name = 'Composer'

    def ready(self):
        try:
            import wama.composer.tasks  # noqa: F401
        except Exception:
            pass

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import ComposerBatchItem
            register_batch_sync(ComposerBatchItem)
        except Exception:
            pass
