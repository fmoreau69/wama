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

        # Reclaim VRAM cross-app : depuis 2026-08-17, BLIP est un backend sous contrat
        # (`describer/backends/blip_backend.py`) — l'unloader de l'app est enregistré
        # AUTOMATIQUEMENT à la première résidence réelle (voies légitimes, cf.
        # common/backends/base.py). L'ancienne déclaration explicite `_unload_blip`
        # (variables de module) est REMPLACÉE, pas doublée.

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

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — SPEC déclarative
        # (A3a, migrée 2026-09-03) : la facette inspector devient projetable. `source_type`
        # lit `detected_type` seul (posé à l'upload ET par la tâche — l'ancien repli
        # `content_type` ne couvrait que des lignes d'avant la détection à l'upload).
        from wama.common.utils.detail_registry import register_app_detail_spec
        register_app_detail_spec('describer', Description, {
            'source_file': 'input_file',
            'source_type': 'detected_type',
            'result_file': 'result_file',
            'result_text': 'result_text',
            'extra': [
                {'label': 'Format de sortie', 'field': 'output_style', 'display': True},
                {'label': 'Langue de sortie', 'field': 'output_language', 'display': True},
                {'label': 'Longueur max', 'field': 'max_length'},
            ],
        })
