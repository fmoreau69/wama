from django.apps import AppConfig


class ReaderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.reader'
    verbose_name = 'Reader — OCR Document'

    def ready(self):
        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchReadingItemLink
            register_batch_sync(BatchReadingItemLink)
        except Exception:
            pass

        from wama.common.utils.preview_utils import register_app_preview
        from .models import ReadingItem
        register_app_preview('reader', ReadingItem, file_field='input_file')
