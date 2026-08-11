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

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — SPEC déclarative
        # (A3a) : reader = OCR documents (source_type constant), sortie = texte (clé
        # canonique result_text), moteur demandé vs effectif.
        from wama.common.utils.detail_registry import register_app_detail_spec
        register_app_detail_spec('reader', ReadingItem, {
            'source_file': 'input_file',
            'source_type': {'const': 'document'},
            'engine': 'backend',
            'engine_effective': 'used_backend',
            'result_text': 'result_text',
            'extra': [
                {'label': 'Mode de lecture', 'field': 'mode', 'display': True},
                {'label': 'Langue', 'field': 'language'},
                {'label': 'Pages', 'field': 'page_count'},
            ],
        })
