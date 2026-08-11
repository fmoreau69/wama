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
