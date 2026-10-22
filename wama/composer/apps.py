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

        # Aperçu unifié : le registre porte le modèle et son propriétaire. Le composer part d'une
        # CONSIGNE, pas d'un fichier : aucun média d'entrée à décrire (`file_field=None`) — la
        # face Entrée est le prompt (`source_text`), la face Sortie l'audio (`result_file`), tous
        # deux lus dans la spec ci-dessous. Il déclarait jusqu'au 2026-10-12 sa SORTIE comme
        # fichier d'entrée : la face Entrée montrait le résultat.
        try:
            from wama.common.utils.preview_utils import register_app_preview
            from .models import ComposerGeneration
            register_app_preview(
                app_name='composer',
                model_class=ComposerGeneration,
                file_field=None,
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

        # Versions GARDÉES (2026-10-15, 2ᵉ app après le Writer — `WAMA_COLLABORATION §7.2`) :
        # chaque révision copie sa partition (planifiée, extraite, ou corrigée à la main sur la
        # surface « Éditer la partition ») ; la brique « Versions » les reprend. Même règle V3 que
        # le Writer : les 20 dernières + les publiées. La liste est déclarée à la rétention
        # (`retention.RETENTION_MODELS`, ligne du composer). La PARTITION seule : une copie du
        # rendu (≈ 100 Mo) par révision ne se garde pas — il se refait depuis sa partition.
        from wama.common.services.revisions import keep_outputs
        from .models import ComposerGeneration
        # La partition COMPLÈTE aussi depuis le 2026-10-22 : elle se corrige sur la même surface.
        keep_outputs('composer', keep=20,
                     fields=tuple(ComposerGeneration.SCORE_FIELDS) + ('parts_score',))
