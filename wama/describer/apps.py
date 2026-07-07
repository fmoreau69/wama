from django.apps import AppConfig


class DescriberConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.describer'
    verbose_name = 'Describer - AI Content Description'

    def ready(self):
        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchDescriptionItem
            register_batch_sync(BatchDescriptionItem)
        except Exception:
            pass

        # Register for unified preview
        from wama.common.utils.preview_utils import register_app_preview
        from .models import Description

        register_app_preview(
            app_name='describer',
            model_class=Description,
            file_field='input_file',
            user_field='user',
            properties_field='properties'
        )

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md).
        from wama.common.utils.detail_registry import register_app_detail, build_detail

        def _describer_detail(item):
            extra = {
                'Format de sortie': item.output_style or None,
                'Langue de sortie': item.output_language or None,
                'Longueur max': item.max_length or None,
            }
            return build_detail(item, source_file=item.input_file,
                                source_type=(item.detected_type or item.content_type),
                                engine=None, result_file=item.result_file, extra=extra)

        register_app_detail('describer', Description, _describer_detail)
