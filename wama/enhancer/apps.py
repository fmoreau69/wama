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
        from wama.common.utils.detail_registry import (MEDIA_CATEGORY_ROLE, build_detail,
                                                       register_app_detail,
                                                       register_app_detail_spec)

        # Branche MÉDIA : SPEC déclarative (A3a, portage 2026-09-21) — projetable au manifeste.
        # `extra_from_params=True` = les champs individuels du schéma principal de l'app
        # (`schema_for_app('enhancer')` → MEDIA_PARAMS_JSON, le pointeur de GENERIC_APPS).
        # Même catégorie que l'entrée pour le rôle d'asset (table COMMUNE).
        register_app_detail_spec('enhancer', Enhancement, {
            'source_file': 'input_file',
            'source_type': 'media_type',
            'engine': 'ai_model',
            'result_file': 'output_file',
            'result_role': {'field': 'media_type', 'map': MEDIA_CATEGORY_ROLE},
            'extra_from_params': True,
        })

        def _extra_from_params(obj, params):
            return {p.label: getattr(obj, p.name, None) for p in params
                    if p.label and getattr(obj, p.name, None) not in (None, '', False)}

        # Branche AUDIO : adapter CODE, à dessein — la spec ne sait nommer qu'UN schéma par
        # nom d'app (`schema_for_app`), et celui de l'audio (`AUDIO_PARAMS`) n'est pas le
        # principal. Rien à déclarer : un audio amélioré peut être une voix, une musique ou
        # un bruitage (pas de `result_role`).
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
