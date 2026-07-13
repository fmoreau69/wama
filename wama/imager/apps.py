from django.apps import AppConfig


class ImagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.imager'
    verbose_name = 'Imager - AI Image Generation'

    def ready(self):
        from . import signals  # noqa: F401  (enregistre les receivers de notification)

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — audit 2026-07-11.
        # Réglages spécifiques → labels de params.py (source unique), jamais relabellisés.
        # NB : PAS de register_app_preview pour l'instant — `generated_images` est un JSON
        # multi-images, le choix « quelle image prévisualiser » est une décision de design
        # à prendre au port complet (inspecteur imager = 0/4 à l'audit §31).
        from wama.common.utils.detail_registry import register_app_detail, build_detail
        from .models import ImageGeneration

        def _imager_detail(g):
            from .params import IMAGE_PARAMS, VIDEO_PARAMS
            params = VIDEO_PARAMS if g.is_video_generation else IMAGE_PARAMS
            extra = {p.label: getattr(g, p.name, None) for p in params
                     if p.label and getattr(g, p.name, None) not in (None, '', False)}
            d = build_detail(
                g,
                source_file=g.reference_image or g.prompt_file or None,
                source_type='video' if g.is_video_generation else 'image',
                engine=g.model,
                # result_file canonique COMPLÉTÉ (2026-07-13, contrat méta-app) : vidéo, ou
                # PREMIÈRE image générée (generated_images = liste JSON de chemins).
                result_file=(g.output_video or
                             ((g.generated_images or [None])[0]
                              if isinstance(g.generated_images, list) else None)),
                extra=extra,
            )
            if g.output_quality:
                d['output_quality'] = g.output_quality
            return d

        register_app_detail('imager', ImageGeneration, _imager_detail)
