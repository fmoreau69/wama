from django.apps import AppConfig


class AvatarizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.avatarizer'
    verbose_name = 'Avatarizer'

    def ready(self):
        # Import Celery tasks to ensure they are discovered by the worker
        import wama.avatarizer.workers  # noqa

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchAvatarJobItem
            register_batch_sync(BatchAvatarJobItem)
        except Exception:
            pass
