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

        # Aperçu (volet inspecteur) : composer = text-to-music → l'aperçu est la SORTIE audio.
        try:
            from wama.common.utils.preview_utils import register_app_preview
            from .models import ComposerGeneration
            register_app_preview(
                app_name='composer',
                model_class=ComposerGeneration,
                file_field='audio_output',
                user_field='user',
            )

            # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md).
            from wama.common.utils.detail_registry import register_app_detail, build_detail

            def _composer_detail(item):
                p = item.prompt or ''
                extra = {
                    'Type': item.get_generation_type_display() if item.generation_type else None,
                    'Prompt': (p[:60] + '…') if len(p) > 60 else (p or None),
                }
                return build_detail(item, source_file=None, source_type=None,
                                    engine=item.model, result_file=item.audio_output, extra=extra)

            register_app_detail('composer', ComposerGeneration, _composer_detail)
        except Exception:
            pass
