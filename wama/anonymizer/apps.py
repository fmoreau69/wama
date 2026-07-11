from django.apps import AppConfig

class AnonymizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.anonymizer'

    def ready(self):
        import wama.anonymizer.signals

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
        from wama.common.utils.detail_registry import register_app_detail, build_detail

        def _anonymizer_detail(m):
            from .params import PARAMS
            extra = {p.label: getattr(m, p.name, None) for p in PARAMS
                     if p.label and getattr(m, p.name, None) not in (None, '', False)}
            d = build_detail(
                m,
                source_file=m.file,
                source_type=m.media_type,
                engine=getattr(m, 'model_to_use', None),
                result_file=None,  # sortie = chemin dérivé (_blurred_*), pas un champ modèle
                extra=extra,
            )
            if getattr(m, 'output_quality', None):
                d['output_quality'] = m.output_quality
            return d

        register_app_detail('anonymizer', Media, _anonymizer_detail)
