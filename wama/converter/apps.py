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

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md).
        from wama.common.utils.detail_registry import register_app_detail, build_detail

        def _converter_detail(job):
            # Réglages spécifiques → labels de params.py (source unique) : on ne relabellise pas.
            from .params import PARAMS
            opts = job.options or {}
            extra = {p.label: opts.get(p.name) for p in PARAMS
                     if p.label and opts.get(p.name) not in (None, '', False, 0)}
            d = build_detail(
                job,
                source_file=job.input_file,
                source_type=job.media_type,
                engine=None,               # pas de modèle IA (Pillow/FFmpeg/Pandoc)
                result_file=job.output_file,
                extra=extra,
            )
            # quality_preset → clé canonique output_quality (alias INSPECTOR_DETAIL_FIELDS.md)
            if job.quality_preset:
                d['output_quality'] = job.quality_preset
            return d

        register_app_detail('converter', ConversionJob, _converter_detail)
