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
        from wama.common.utils.detail_registry import register_app_detail, build_detail
        from .models import AvatarJob

        register_app_preview(
            app_name='avatarizer',
            model_class=AvatarJob,
            file_field='avatar_upload',
            user_field='user',
        )

        def _avatarizer_detail(job):
            from .params import PARAMS
            extra = {p.label: getattr(job, p.name, None) for p in PARAMS
                     if p.label and getattr(job, p.name, None) not in (None, '', False)}
            return build_detail(
                job,
                source_file=job.avatar_upload or job.audio_input or None,
                source_type='video',
                engine=job.tts_model,
                result_file=job.output_video or None,
                extra=extra,
            )

        register_app_detail('avatarizer', AvatarJob, _avatarizer_detail)
