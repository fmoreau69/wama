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

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — pilote.
        from wama.common.utils.detail_registry import register_app_detail, build_detail

        def _reader_detail(item):
            # Réglages spécifiques → labels de params.py (source unique) ; le reste = épine dorsale.
            extra = {
                'Mode de lecture': item.get_mode_display() if item.mode else None,
                'Langue': item.language or None,
                'Pages': item.page_count or None,
            }
            return build_detail(
                item,
                source_file=item.input_file,
                source_type='document',            # reader = OCR documents/images
                engine=item.backend,
                engine_effective=item.used_backend,
                result_file=None,                  # sortie = texte (result_text), pas un fichier
                extra=extra,
            )

        register_app_detail('reader', ReadingItem, _reader_detail)
