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

        # Inventaire des moteurs exécutables par le composer (grisage automatique, 02/09) :
        # `audio-cpp` = AudioCppBackend (backends/audiocpp_backend.py), le moteur que
        # `composition.runtime.engine` de MiniMax-Music3 déclare au catalogue.
        try:
            from wama.common.backends.manager import register_engine_inventory
            register_engine_inventory(lambda: {'audio-cpp'})
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
                                    engine=item.model, result_file=item.audio_output,
                                    source_text=item.prompt, extra=extra)

            register_app_detail('composer', ComposerGeneration, _composer_detail)
        except Exception:
            pass
