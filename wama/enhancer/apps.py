from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class EnhancerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.enhancer'
    verbose_name = 'Enhancer - AI Image/Video Upscaling'

    def ready(self):
        """Called when Django starts - check and download models if needed."""
        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchEnhancementItem, BatchAudioEnhancementItem
            register_batch_sync(BatchEnhancementItem)
            register_batch_sync(BatchAudioEnhancementItem)
        except Exception:
            pass

        # Register for unified preview
        from wama.common.utils.preview_utils import register_app_preview
        from .models import Enhancement

        register_app_preview(
            app_name='enhancer',
            model_class=Enhancement,
            file_field='input_file',
            user_field='user',
            width_field='width',
            height_field='height'
        )

        from .models import AudioEnhancement
        register_app_preview(
            app_name='audio_enhancer',
            model_class=AudioEnhancement,
            file_field='input_file',
            user_field='user',
            duration_field='duration',
        )

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — audit 2026-07-11.
        # Réglages spécifiques → labels de params.py (source unique), jamais relabellisés.
        from wama.common.utils.detail_registry import register_app_detail, build_detail

        def _extra_from_params(obj, params):
            return {p.label: getattr(obj, p.name, None) for p in params
                    if p.label and getattr(obj, p.name, None) not in (None, '', False)}

        def _enhancer_detail(e):
            from .params import MEDIA_PARAMS
            return build_detail(
                e,
                source_file=e.input_file,
                source_type=e.media_type,
                engine=e.ai_model,
                result_file=e.output_file,
                extra=_extra_from_params(e, MEDIA_PARAMS),
            )

        def _audio_detail(ae):
            from .params import AUDIO_PARAMS
            return build_detail(
                ae,
                source_file=ae.input_file,
                source_type='audio',
                engine=ae.engine,
                result_file=ae.output_file,
                extra=_extra_from_params(ae, AUDIO_PARAMS),
            )

        register_app_detail('enhancer', Enhancement, _enhancer_detail)
        register_app_detail('audio_enhancer', AudioEnhancement, _audio_detail)

        # Enregistre les scénarios de test nocturne (AVANT le guard RUN_MAIN : doit aussi
        # s'enregistrer pour les management commands comme run_nightly_tests).
        try:
            from .nightly_scenarios import register_scenarios
            register_scenarios()
        except Exception:
            pass

        # Only run model download in main process (not in reloader or other subprocesses)
        import os
        if os.environ.get('RUN_MAIN') != 'true':
            return

        try:
            from .utils.model_downloader import check_and_download_essential_models
            logger.info("Checking AI models for Enhancer app...")
            check_and_download_essential_models()
        except Exception as e:
            logger.warning(f"Could not auto-download models: {e}")
            logger.info("Models can be downloaded manually from: https://github.com/Djdefrag/QualityScaler/releases")
