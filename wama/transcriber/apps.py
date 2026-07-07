from django.apps import AppConfig


class TranscriberConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.transcriber'
    verbose_name = 'Transcriber'

    def ready(self):
        # Import tasks for Celery autodiscovery
        try:
            import wama.transcriber.workers  # noqa: F401
        except Exception:
            pass

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchTranscriptItem
            register_batch_sync(BatchTranscriptItem)
        except Exception:
            pass

        # Enregistre les scénarios de test nocturne de l'app (gabarit de référence).
        try:
            from .nightly_scenarios import register_scenarios
            register_scenarios()
        except Exception:
            pass

        # Invalide le cache des infos backends (descriptions/disponibilité) à chaque
        # démarrage de process : un changement de code (description, libellé, nouveau
        # moteur) est ainsi répercuté au redémarrage sans vidage manuel. La vue
        # get_backends re-remplit le cache à la 1re requête. Voir views.get_backends.
        try:
            from django.core.cache import cache
            cache.delete('transcriber_backends_info')
        except Exception:
            pass

        # Register for unified preview
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.preview_utils import transcriber_preview_adapter
        from .models import Transcript

        PreviewRegistry.register(
            app_name='transcriber',
            model_class=Transcript,
            adapter=transcriber_preview_adapter,
            file_field='audio',
            user_field='user'
        )

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md).
        from wama.common.utils.detail_registry import register_app_detail, build_detail

        def _transcriber_detail(item):
            extra = {
                'Diarisation': 'Oui' if item.enable_diarization else None,
                'Résumé': 'Oui' if item.generate_summary else None,
                'Mots-clés': item.hotwords or None,
                'Cohérence': 'Oui' if item.verify_coherence else None,
            }
            return build_detail(item, source_file=item.audio, source_type='audio',
                                engine=item.backend, engine_effective=item.used_backend,
                                result_file=None, extra=extra)

        register_app_detail('transcriber', Transcript, _transcriber_detail)
