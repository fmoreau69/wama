from django.apps import AppConfig


class AvatarizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.avatarizer'
    verbose_name = 'Avatarizer'

    def ready(self):
        # Import Celery tasks to ensure they are discovered by the worker
        import wama.avatarizer.workers  # noqa

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchAvatarJobItem
            register_batch_sync(BatchAvatarJobItem)
        except Exception:
            pass

        # Aperçu + détail inspecteur (briques communes) — audit 2026-07-11 (0/2 avant).
        # Aperçu = l'avatar (identité visuelle du job) ; l'audio est secondaire.
        from wama.common.utils.preview_utils import register_app_preview
        from wama.common.utils.detail_registry import register_app_detail_spec
        from .models import AvatarJob

        register_app_preview(
            app_name='avatarizer',
            model_class=AvatarJob,
            file_field='avatar_upload',
            user_field='user',
        )

        # SPEC déclarative (A3a, portage 2026-10-03). La source est l'avatar déposé, à défaut
        # l'audio (forme « premier champ non vide »). Moteur = celui qui fabrique la vidéo
        # (MuseTalk), pas le TTS : `engine=tts_model` affichait un modèle de VOIX pour un job
        # d'ANIMATION (incohérence relevée 2026-08-28) ; le TTS d'un job pipeline apparaît par
        # les réglages du schéma (chip « Modèle TTS »). La sortie est toujours une vidéo parlante.
        register_app_detail_spec('avatarizer', AvatarJob, {
            'source_file': ['avatar_upload', 'audio_input'],
            'source_type': {'const': 'video'},
            'engine': {'const': 'musetalk'},
            'result_file': 'output_video',
            'result_role': {'const': 'video'},
            'extra_from_params': True,
        })

        # Un avatar de galerie est cité par son NOM : quand la médiathèque rend un asset système à
        # son auteur, ces travaux doivent suivre (2026-09-29, MEDIA_STORAGE_TIERING §8.6 D27).
        from wama.media_library.services import register_system_asset_name_holder
        from .system_assets import gallery_name_holder
        register_system_asset_name_holder('avatar', gallery_name_holder)
