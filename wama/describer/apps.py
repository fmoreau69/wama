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

        # Reclaim VRAM cross-app : le Describer garde BLIP en variables de MODULE
        # (`image_describer._blip_model/_blip_processor`), pas dans un backend — le registre
        # d'instances de BaseModelBackend ne peut donc pas le voir, d'où cette déclaration
        # explicite. Elle remplace `MemoryManager._unload_describer_model`, qui obligeait le
        # model_manager à connaître les internes de cette app.
        try:
            from wama.model_manager.services.memory_manager import register_vram_unloader

            def _unload_blip() -> bool:
                from .utils import image_describer
                freed = False
                for attr in ('_blip_model', '_blip_processor'):
                    if getattr(image_describer, attr, None) is not None:
                        setattr(image_describer, attr, None)
                        freed = True
                if freed:
                    import gc
                    gc.collect()
                    try:
                        import torch
                        if torch.cuda.is_available():
                            torch.cuda.empty_cache()
                    except Exception:
                        pass
                return freed

            register_vram_unloader('describer', _unload_blip)
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
                                engine=None, result_file=item.result_file,
                                result_text=item.result_text or None, extra=extra)

        register_app_detail('describer', Description, _describer_detail)
