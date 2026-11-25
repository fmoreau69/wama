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
        # Le champ de chaque port d'entrée qui ne porte pas son nom (`common/utils/port_fields`).
        # L'AVATAR (photo de MuseTalk OU objet 3D de TalkingHead, `models.AVATAR_PORTS`) vit dans la
        # table commune des entrées depuis le 2026-11-25 — la première app qui y passe. Son ancienne
        # colonne `avatar_upload` (qui gardait les DEUX ports) n'est plus lue qu'en REPLI (`legacy`),
        # le temps que la migration la recopie ; elle se retirera ensuite, avec cette clé.
        from wama.common.utils.port_fields import register_port_fields
        from .models import AVATAR_PORTS
        register_port_fields(AvatarJob, {'prompt': 'text_content', 'work_audio': 'audio_input'},
                             table=AVATAR_PORTS,
                             legacy={'work_image': 'avatar_upload', 'work_object3d': 'avatar_upload'})

        # L'aperçu montre l'AVATAR : le premier de ses ports qui porte un fichier (forme « premier
        # non vide » de la spec, lue au lecteur commun — `preview_registry.create_simple_adapter`).
        register_app_preview(
            app_name='avatarizer',
            model_class=AvatarJob,
            file_field=list(AVATAR_PORTS),
            user_field='user',
        )

        # SPEC déclarative (A3a, portage 2026-10-03). La source est l'avatar déposé, à défaut
        # l'audio (forme « premier champ non vide »). Moteur = celui qui fabrique la vidéo
        # (MuseTalk), pas le TTS : `engine=tts_model` affichait un modèle de VOIX pour un job
        # d'ANIMATION (incohérence relevée 2026-08-28) ; le TTS d'un job pipeline apparaît par
        # les réglages du schéma (chip « Modèle TTS »). La sortie est toujours une vidéo parlante.
        # `source_text` (2026-10-18) : le texte à dire est l'entrée-texte de l'élément, comme celle du
        # synthesizer — aperçu de la face Entrée, et champ que remplit le lien « Texte » d'un nœud
        # du Studio (`studio/services/graph_flow`, `generic_runner.port_argument_name`).
        # La source est l'AVATAR, nommé par ses PORTS (lus au lecteur commun, `spec_value`), à défaut
        # l'audio.
        register_app_detail_spec('avatarizer', AvatarJob, {
            'source_file': [*AVATAR_PORTS, 'audio_input'],
            'source_type': {'const': 'video'},
            'source_text': 'text_content',
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
