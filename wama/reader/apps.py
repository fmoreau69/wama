from django.apps import AppConfig


class ReaderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.reader'
    verbose_name = 'Reader — OCR Document'

    def ready(self):
        from wama.common.utils.preview_utils import register_app_preview
        from .models import ReadingItem
        register_app_preview('reader', ReadingItem, file_field='input_file')
