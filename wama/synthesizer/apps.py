from django.apps import AppConfig

class SynthesizerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.synthesizer'
    verbose_name = 'Synthesizer'

    def ready(self):
        # Import Celery tasks to ensure they are discovered
        import wama.synthesizer.workers

        # Inventaire des moteurs TTS exécutables (grisage automatique, 02/09) : la MÊME
        # table que le dispatch réel (`ENGINE_BACKENDS`) — un backend ajouté là-bas
        # ré-autorise son moteur partout, sans autre geste. Import PARESSEUX : l'inventaire
        # n'est lu qu'à la demande (les backends restent légers à importer, torch vit dans
        # leurs load(), mais la règle « rien de lourd dans ready() » vaut d'être tenue).
        try:
            from wama.common.backends.manager import register_engine_inventory

            def _tts_engines():
                # La table ENTIÈRE, CLASSES comprises : le commun en tire les DEUX
                # lectures — les moteurs EXÉCUTABLES (`known_engines`, qui applique
                # `missing_packages` là-bas) et la carte moteur→backend
                # (`engine_backends`), dont un manifeste de MODÈLE a besoin pour
                # déclarer la LIBRAIRIE que son moteur exige. Filtrer ICI privait le
                # commun de cette carte, et recopiait une politique commune (03/09).
                from wama.synthesizer.backends import ENGINE_BACKENDS
                return dict(ENGINE_BACKENDS)
            register_engine_inventory(_tts_engines)
        except Exception:
            pass

        # Batch unifié : total auto-réparé + suppression des batches vidés (cf. BATCH_MODEL_AUDIT.md)
        try:
            from wama.common.utils.batch_sync import register_batch_sync
            from .models import BatchSynthesisItem
            register_batch_sync(BatchSynthesisItem)
        except Exception:
            pass

        # Aperçu unifié : le registre porte le modèle et son propriétaire ; les faces Entrée et
        # Sortie se dérivent de la spec de détail ci-dessous (`source_file`/`source_text`,
        # `result_file`). Il déclarait jusqu'au 2026-10-12 la SORTIE audio comme fichier
        # d'entrée — la face Entrée montrait le résultat, ou une erreur avant lui.
        from wama.common.utils.preview_utils import register_app_preview
        from .models import VoiceSynthesis

        register_app_preview('synthesizer', VoiceSynthesis, file_field='text_file')

        # Détail inspecteur (schéma canonique INSPECTOR_DETAIL_FIELDS.md) — audit 2026-07-11.
        # Réglages spécifiques → labels de params.py (source unique), jamais relabellisés.
        # SPEC déclarative (A3a, portage 2026-10-03). Source = le fichier texte, à défaut la
        # voix de référence ; son type est « texte » dès qu'un texte existe (fichier ou saisie),
        # sinon « audio ». `source_text` : clé canonique de l'entrée-texte (aperçu face Entrée).
        from wama.common.utils.detail_registry import register_app_detail_spec
        register_app_detail_spec('synthesizer', VoiceSynthesis, {
            'source_file': ['text_file', 'voice_reference'],
            'source_type': {'when_any': ['text_file', 'text_content'],
                            'then': 'text', 'else': 'audio'},
            'engine': 'tts_model',
            'result_file': 'audio_output',
            'source_text': 'text_content',
            'extra_from_params': True,
        })
