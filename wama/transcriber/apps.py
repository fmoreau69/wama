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

        # Reclaim VRAM cross-app : déclare COMMENT libérer les modèles Transcriber.
        # Ne couvre QUE le pipeline pyannote, caché en variable de module donc invisible
        # du registre d'instances de BaseModelBackend. Les backends ASR (whisper /
        # qwen_asr / vibevoice) s'enregistrent SEULS au premier load depuis 2026-07-30 —
        # les redéclarer ici recréerait le doublon qu'on vient de supprimer.
        # Auparavant ce bloc pointait vers `MemoryManager._unload_transcriber_model`,
        # c'est-à-dire que l'app déléguait au model_manager la connaissance de ses
        # propres internes. L'app déclare, le model_manager orchestre.
        try:
            from wama.model_manager.services.memory_manager import register_vram_unloader

            def _unload_diarizer() -> bool:
                from wama.common.backends.pyannote_diarizer import unload_pipeline
                return bool(unload_pipeline())

            register_vram_unloader('transcriber-diarizer', _unload_diarizer)
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

        # Rendu des formats de sortie (late-binding, §6.4) — le MÊME que celui des trois
        # téléchargements ; déclaré pour que le geste commun « ranger en médiathèque » le
        # rende (2026-09-18). Chemin pointé : les vues ne s'importent pas au boot.
        from wama.common.utils.export_formats import register_export_builder
        register_export_builder('transcriber', 'wama.transcriber.views:build_transcript_bytes')

        # Évaluation contre une RÉFÉRENCE (port `reference_result`, capacité `has_reference_result`)
        # — la brique commune fait tout ; l'app ne dit que CE QUI se mesure et COMMENT se lit.
        from wama.common.services.result_evaluation import EvaluationSpec, register_evaluation
        from .utils.transcript_documents import SUPPORTED_EXTENSIONS

        def _asr_text(item):
            """Le texte PRODUIT par le moteur — jamais la correction humaine, qui écrase `text`
            (`save_correction`) : mesurer la correction contre une référence mesurerait l'humain."""
            if item.status != 'SUCCESS':
                return None
            segments = item.segments_json or []
            text = ' '.join((s.get('text') or '').strip() for s in segments
                            if isinstance(s, dict)).strip()
            if text:
                return text
            return (item.text or None) if not item.corrected_segments_json else None

        def _read_reference(path):
            from .utils.transcript_documents import read_transcript_document
            doc = read_transcript_document(path)
            return doc.text, {'format': doc.format, 'turns': len(doc.segments),
                              'timed': doc.is_timed, 'windows': len(doc.windows),
                              'outside_speech': len(doc.outside_speech)}

        register_evaluation(EvaluationSpec(
            surface='transcriber', reference_field='reference_result',
            result_text=_asr_text, read_reference=_read_reference,
            model_key=lambda item: item.model_key or (
                f'transcriber:{item.used_backend}' if item.used_backend else ''),
            reference_extensions=SUPPORTED_EXTENSIONS,
        ))

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
                                result_file=None, result_text=item.text or None, extra=extra)

        # ⚠ Le transcriber garde un adapter CODE (logique irréductible, chemin A3
        # assumé) — mais ses FACETTES de résultat, elles, sont une DONNÉE. On passe donc la
        # spec en plus de l'adapter : `DetailRegistry.register` accepte les deux depuis
        # l'origine, et c'est ce qui rend les onglets extractibles au manifeste sans exiger
        # d'abord la conversion complète de l'adapter.
        # Clés/ids INCHANGÉS : `resultText`, `diarisationContent`, `resumeContent`,
        # `coherenceContent` sont le contrat que son JS consomme déjà (R18, 2026-09-07).
        from wama.common.utils.detail_registry import DetailRegistry
        DetailRegistry.register('transcriber', Transcript, _transcriber_detail, spec={
            'result_tabs': [
                {'cle': 'transcription', 'label': 'Transcription', 'icone': 'fa-file-alt',
                 'cible': 'resultText', 'forme': 'pre', 'badge': True},
                # Visible d'emblée (pas de `cache`) : la diarisation se charge à l'ouverture,
                # d'où son texte d'attente — c'est ce que faisait le bloc en dur.
                {'cle': 'diarisation', 'label': 'Diarisation', 'icone': 'fa-users',
                 'cible': 'diarisationContent', 'forme': 'nu', 'attente': 'Chargement...'},
                {'cle': 'resume', 'label': 'Résumé', 'icone': 'fa-file-lines',
                 'cible': 'resumeContent', 'forme': 'html', 'badge': True, 'cache': True},
                {'cle': 'coherence', 'label': 'Cohérence', 'icone': 'fa-spell-check',
                 'cible': 'coherenceContent', 'forme': 'nu', 'badge': True, 'cache': True},
            ],
        })
