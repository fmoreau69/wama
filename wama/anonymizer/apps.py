from django.apps import AppConfig

class AnonymizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.anonymizer'

    def ready(self):
        # `signals.py` RETIRÉ le 2026-09-27 : son seul `post_save` garantissait une ligne
        # `UserSettings` au déposant — table legacy, les réglages vivent dans `user_settings`.

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchAnonymizerItem
            register_batch_sync(BatchAnonymizerItem)
        except Exception:
            pass

        # Register for unified preview
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.preview_utils import anonymizer_preview_adapter
        from .models import Media

        PreviewRegistry.register(
            app_name='anonymizer',
            model_class=Media,
            adapter=anonymizer_preview_adapter,
            file_field='file',
            user_field='user'
        )

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — audit 2026-07-11.
        # Réglages spécifiques → labels de params.py (source unique), jamais relabellisés.
        # SPEC déclarative (A3a, portage 2026-10-03) — projetable au manifeste. L'adapter code
        # qu'elle remplace ne faisait rien d'autre : nommer des champs, traduire la catégorie
        # du média en rôle d'asset (table COMMUNE), lister les réglages posés du schéma.
        from wama.common.utils.detail_registry import (MEDIA_CATEGORY_ROLE,
                                                       register_app_detail_spec)
        register_app_detail_spec('anonymizer', Media, {
            'source_file': 'file',
            'source_type': 'media_type',
            'engine': 'model_to_use',
            'result_file': 'output_file',
            # Même catégorie que l'entrée (image → image, vidéo → vidéo) — table COMMUNE.
            'result_role': {'field': 'media_type', 'map': MEDIA_CATEGORY_ROLE},
            'extra_from_params': True,
        })
