from django.apps import AppConfig


class ImagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.imager'
    verbose_name = 'Imager - AI Image Generation'

    def ready(self):
        from . import signals  # noqa: F401  (enregistre les receivers de notification)

        # Batch unifié : `total` auto-réparé + suppression des batchs vidés (brique commune).
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import GenerationBatchItem
            register_batch_sync(GenerationBatchItem)
        except Exception:
            pass

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — audit 2026-07-11.
        # Réglages spécifiques → labels de params.py (source unique), jamais relabellisés.
        # Aperçu (2026-08-19) : la registration était différée sur « quelle image prévisualiser »
        # (generated_images = JSON multi-images) — décision DÉJÀ PRISE depuis le 2026-07-13 par
        # la clé canonique `result_file` ci-dessous (vidéo, sinon PREMIÈRE image). Comme la face
        # SORTIE est dérivée de cette clé (preview_utils._output_preview_data, zéro code par app),
        # il ne manquait que l'enregistrement : sans lui `unified_preview` répond 404 et le volet
        # reste vide (mesuré à la passe smoke du 19/08 — seul écart des 10 apps).
        # file_field = reference_image : MÊME source que `source_file` du détail (img2img/édition).
        from wama.common.utils.detail_registry import register_app_detail, build_detail
        from wama.common.utils.preview_utils import register_app_preview
        from .models import ImageGeneration

        def _imager_detail(g):
            from .params import IMAGE_PARAMS, VIDEO_PARAMS
            params = VIDEO_PARAMS if g.is_video_generation else IMAGE_PARAMS
            extra = {p.label: getattr(g, p.name, None) for p in params
                     if p.label and getattr(g, p.name, None) not in (None, '', False)}
            # Prompt en chip (même forme que composer/apps.py:41) : sans lui le volet d'une
            # app PROMPT-PRIMAIRE n'affiche NULLE PART l'entrée que la card met en avant.
            p_txt = (g.prompt or '').strip()
            if p_txt:
                extra['Prompt'] = (p_txt[:60] + '…') if len(p_txt) > 60 else p_txt
            d = build_detail(
                g,
                source_file=g.reference_image or g.prompt_file or None,
                source_type='video' if g.is_video_generation else 'image',
                engine=g.model,
                # result_file canonique COMPLÉTÉ (2026-07-13, contrat méta-app) : vidéo, ou
                # PREMIÈRE image générée.
                # ⚠ 2026-08-19 : `generated_images` contient des chemins ABSOLUS de disque
                # (tasks.py:308 `os.path.join(output_dir, …)`) — les servir tels quels
                # donnait un lien Sortie et une preview de sortie inexploitables. L'ACCESSEUR
                # existe : `ImageGeneration.output_images` (models.py:377) convertit en URL
                # MEDIA. On passe donc par lui (jamais de re-dérivation de chemin ici).
                result_file=(g.output_video or (g.output_images[0] if g.output_images else None)),
                # COLLECTION (2026-08-22) : une génération rend N images, pas une. `result_file`
                # ci-dessus reste le REPRÉSENTANT (inchangé, tous ses consommateurs aussi) ;
                # `result_files` ajoute la liste, d'où le rendu commun tire sa grille ET la
                # navigation de la visionneuse. Toujours via l'ACCESSEUR `output_images` (URL
                # MEDIA), jamais `generated_images` qui contient des chemins ABSOLUS de disque.
                result_files=(g.output_images or None),
                # App PROMPT-PRIMAIRE : le prompt est l'ENTRÉE (anatomie card v3 §11) —
                # clé CANONIQUE `source_text`, comme composer/synthesizer. Sans elle, la
                # section Entrée du volet resterait vide quand il n'y a pas d'image source.
                source_text=g.prompt,
                extra=extra,
            )
            if g.output_quality:
                d['output_quality'] = g.output_quality
            return d

        register_app_detail('imager', ImageGeneration, _imager_detail)
        register_app_preview(
            app_name='imager',
            model_class=ImageGeneration,
            file_field='reference_image',
            user_field='user',
        )
