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
            # SPEC déclarative (A3a, portage 2026-10-03). Le composer SAIT ce qu'il produit :
            # une génération `music` est une musique, `sfx` un bruitage — le rôle d'asset est
            # la traduction du type (schéma canonique, 2026-09-18 ; lu par le geste commun
            # « ranger en médiathèque »). Le prompt est l'ENTRÉE (`source_text`) et s'affiche
            # aussi en réglage, tronqué ; son libellé vient du schéma.
            from wama.common.utils.detail_registry import register_app_detail_spec
            register_app_detail_spec('composer', ComposerGeneration, {
                'engine': 'model',
                'result_file': 'audio_output',
                'result_role': {'field': 'generation_type',
                                'map': {'music': 'audio_music', 'sfx': 'audio_sfx'}},
                'source_text': 'prompt',
                'extra': [{'label': 'Type', 'field': 'generation_type', 'display': True},
                          {'field': 'prompt', 'max_chars': 60}],
            })
        except Exception:
            pass
