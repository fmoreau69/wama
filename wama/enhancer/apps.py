from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class EnhancerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.enhancer'
    verbose_name = 'Enhancer - AI Image/Video Upscaling'

    def ready(self):
        """Called when Django starts — registrations only (no model download)."""
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
        from wama.common.utils.detail_registry import (MEDIA_CATEGORY_ROLE,
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

        # Branche AUDIO : SPEC déclarative depuis le 2026-10-05 (adapter code avant : la spec ne
        # savait lire que le schéma PRINCIPAL de l'app, et celui de l'audio ne l'est pas). Le
        # schéma est NOMMÉ (`params_schema`), lu dans le module de l'app propriétaire du modèle.
        # Mesuré identique sur les 6 éléments réels avant bascule. Pas de `result_role` : un
        # audio amélioré peut être une voix, une musique ou un bruitage.
        register_app_detail_spec('audio_enhancer', AudioEnhancement, {
            'source_file': 'input_file',
            'source_type': {'const': 'audio'},
            'engine': 'engine',
            'result_file': 'output_file',
            'params_schema': {'const': 'AUDIO_PARAMS_JSON'},
            'extra_from_params': True,
        })

        # Déclare les scénarios de test nocturne (AVANT le guard RUN_MAIN : doit aussi valoir pour
        # les management commands comme run_nightly_tests), joués au premier usage du registre
        # (`add_registrar`, 2026-10-20).
        from wama.common.services.nightly_tests import add_registrar
        add_registrar('wama.enhancer.nightly_scenarios:register_scenarios')

        # ⚠ Plus de téléchargement de poids au démarrage (retiré le 2026-10-11, REMOVAL_LEDGER) :
        # les modèles ONNX sont DÉCLARÉS (`utils/model_config.ENHANCER_MODELS`, fichiers et
        # origine) et s'installent par la route — bouton « Installer » du model manager,
        # `pull_model enhancer:<id>` ou `install_requires enhancer`.
