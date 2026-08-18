from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.common'

    def ready(self):
        # Journal APPLICATIF global `logs/wama.log` — comble le trou mesuré le 2026-08-18 :
        # `settings.LOGGING` n'existe que dans la branche LDAP (django_auth_ldap→console),
        # donc les loggers `wama.*` n'avaient AUCUN handler et le `logger.exception` de
        # l'install de modèle partait dans le vide (seul le toast navigateur portait l'erreur).
        # `propagate=True` — à l'INVERSE de model-sync.log : couper la propagation priverait
        # les `celery-*.log` des traces de tâches (c'est celery-gpu.log qui a permis
        # d'identifier la tâche imager responsable des kernel panics du 29/07).
        # Les loggers déjà cloisonnés (model-sync, console_utils) gardent leur quarantaine :
        # leur `propagate=False` est posé sur un logger PLUS PROFOND que 'wama'.
        try:
            from wama.common.utils.log_rotation import attach_dedicated_log
            attach_dedicated_log(
                'wama', 'wama.log', propagate=True,
                fmt='%(asctime)s [%(levelname)s] [%(name)s] %(message)s')
        except Exception:
            import logging
            logging.getLogger(__name__).debug('Journal wama.log non attaché', exc_info=True)

        # Gouverneur de ressources : plafonne l'allocateur CUDA de CE process.
        # Couvre les process Django (workers gunicorn) ; les workers Celery sont
        # couverts par le signal `worker_process_init` (wama/celery.py) et le
        # service TTS par son `startup`. Idempotent — un process déjà configuré
        # ne refait rien. Point d'entrée unique : common/services/resource_governor.py
        # Scénarios nocturnes `consistency` (AVANT le guard RUN_MAIN, comme l'enhancer :
        # ils doivent exister aussi pour les management commands, run_nightly_tests inclus).
        try:
            from .nightly_scenarios import register_scenarios
            register_scenarios()
        except Exception:
            pass

        try:
            from wama.common.services.resource_governor import configure_cuda_process
            configure_cuda_process()
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                'Gouverneur de ressources non initialisé', exc_info=True)

        # Branche l'enrichissement de prompt à l'INGESTION sur tout modèle DÉCLARÉ
        # enrichissable (PROMPT_TARGETS). Générique : aucune app n'écrit de récepteur.
        try:
            from wama.common.prompt_ingest import register_prompt_ingest_receivers
            register_prompt_ingest_receivers()
        except Exception:
            import logging
            logging.getLogger(__name__).debug(
                'Récepteurs prompt_ingest non enregistrés', exc_info=True)

        # Enregistre les fonctions WAMA Data pures (toolbox tierce : map-matching, freinage…)
        # dans le catalogue au démarrage.
        try:
            from wama.common.data import functions  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                'wama.common.data functions non enregistrées', exc_info=True)
