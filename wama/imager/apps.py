from django.apps import AppConfig


class ImagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.imager'
    verbose_name = 'Imager - AI Image Generation'

    def ready(self):
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
        from wama.common.utils.detail_registry import register_app_detail_spec
        from wama.common.utils.preview_utils import register_app_preview
        from .models import ImageGeneration

        # SPEC déclarative (A3a, portage 2026-10-05 — dernier adapter code de l'app, mesuré
        # identique sur les 31 générations réelles avant bascule ; seul l'ORDRE des réglages
        # change : le prompt en tête, comme le composer). Ce que disait l'adapter :
        #   • `result_file` : la vidéo, sinon la PREMIÈRE image (2026-07-13). Toujours par
        #     l'ACCESSEUR `output_images` (URL MEDIA, 2026-08-19), jamais `generated_images`
        #     qui porte des chemins ABSOLUS de disque ;
        #   • `result_files` : la COLLECTION — une génération rend N images (2026-08-22) ; le
        #     rendu commun en tire sa grille et la navigation de la visionneuse ;
        #   • `result_role` : ce qui EST sorti (la vidéo produite, sinon des images), pas le
        #     mode demandé — jamais « avatar », nature d'usage (2026-09-18) ;
        #   • `source_text` : app PROMPT-PRIMAIRE, le prompt est l'ENTRÉE (anatomie card §11) ;
        #     il est aussi rappelé en chip parmi les réglages, comme au composer ;
        #   • les réglages posés du schéma DE L'ÉLÉMENT (image ou vidéo), sans le modèle (rendu
        #     « Moteur / Modèle ») ni le format/qualité (section Sortie).
        register_app_detail_spec('imager', ImageGeneration, {
            'source_file': ['reference_image', 'prompt_file'],
            'source_type': {'when_any': ['is_video_generation'], 'then': 'video', 'else': 'image'},
            'engine': 'model',
            'result_file': ['output_video', 'output_images'],
            'result_files': 'output_images',
            'result_role': {'when_any': ['output_video'], 'then': 'video', 'else': 'image'},
            'source_text': 'prompt',
            'extra': [{'label': 'Prompt', 'field': 'prompt', 'max_chars': 60}],
            'params_schema': {'when_any': ['is_video_generation'],
                              'then': 'VIDEO_PARAMS_JSON', 'else': 'IMAGE_PARAMS_JSON'},
            'extra_from_params': True,
        })
        register_app_preview(
            app_name='imager',
            model_class=ImageGeneration,
            file_field='reference_image',
            user_field='user',
        )
