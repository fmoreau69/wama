from django.apps import AppConfig

class SynthesizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.synthesizer'
    verbose_name = 'Synthesizer'

    def ready(self):
        # Import Celery tasks to ensure they are discovered
        import wama.synthesizer.workers

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchSynthesisItem
            register_batch_sync(BatchSynthesisItem)
        except Exception:
            pass

        # Register for unified preview
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.preview_utils import synthesizer_preview_adapter
        from .models import VoiceSynthesis

        PreviewRegistry.register(
            app_name='synthesizer',
            model_class=VoiceSynthesis,
            adapter=synthesizer_preview_adapter,
            file_field='audio_output',
            user_field='user'
        )

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — audit 2026-07-11.
        # Réglages spécifiques → labels de params.py (source unique), jamais relabellisés.
        from wama.common.utils.detail_registry import register_app_detail, build_detail

        def _synth_detail(s):
            from .params import PARAMS
            extra = {p.label: getattr(s, p.name, None) for p in PARAMS
                     if p.label and getattr(s, p.name, None) not in (None, '', False)}
            d = build_detail(
                s,
                source_file=s.text_file or s.voice_reference,
                source_type='text' if (s.text_file or s.text_content) else 'audio',
                engine=s.tts_model,
                result_file=s.audio_output,
                extra=extra,
            )
            if s.output_quality:
                d['output_quality'] = s.output_quality
            return d

        register_app_detail('synthesizer', VoiceSynthesis, _synth_detail)