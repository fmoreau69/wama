from django.apps import AppConfig


class ConverterConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.converter'
    verbose_name = 'Converter'

    def ready(self):
        # Aperçu inline inspecteur (brique commune) — banc d'essai « tous types de fichiers ».
        from wama.common.utils.preview_utils import register_app_preview
        from .models import ConversionJob
        register_app_preview('converter', ConversionJob, file_field='input_file')

        # Invariant « un lot sans membre n'existe pas ». Le converter est la seule app à
        # rattacher par FK DIRECTE (`ConversionJob.batch`) : il n'a pas de modèle de liaison
        # à brancher, et il était donc resté HORS de l'invariant que les neuf autres tiennent
        # — son lot vidé survivait en base sans qu'aucune card ne le trahisse (mesuré le
        # 2026-08-28 par `converter.clear_all`). `direct_fk=True` DÉCLARE cette forme : le job
        # n'entre pas au registre des modèles de LIAISON (que le manifeste publie tel quel) et
        # seule sa SUPPRESSION est branchée — un job est ré-enregistré à chaque tick de
        # progression, or seule une suppression peut vider un lot.
        from wama.common.utils.batch_sync import register_batch_sync
        register_batch_sync(ConversionJob, direct_fk=True)

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — SPEC déclarative
        # (A3a) : les réglages viennent des labels du schéma (source unique, champ JSON
        # `options`), `quality_preset` s'aligne sur la clé canonique ; pas de moteur IA
        # (Pillow/FFmpeg/Pandoc) donc pas d'`engine`.
        from wama.common.utils.detail_registry import register_app_detail_spec
        register_app_detail_spec('converter', ConversionJob, {
            'source_file': 'input_file',
            'source_type': 'media_type',
            'result_file': 'output_file',
            'extra_from_params': 'options',
            'aliases': {'quality_preset': 'output_quality'},
        })
