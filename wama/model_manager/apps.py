"""
Model Manager App Configuration

Starts the file watcher for automatic model synchronization
when Django server starts.
"""

import os
import sys
import logging
from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ModelManagerConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.model_manager'
    verbose_name = 'Model Manager'

    # Commandes pendant lesquelles on NE déclenche aucune synchro/watcher.
    _SKIP_CMDS = [
        'migrate', 'makemigrations', 'collectstatic',
        'sync_models', 'verify_models', 'shell', 'dbshell', 'test', 'createsuperuser',
        'rotate_logs',  # pure manipulation de fichiers : aucune synchro à déclencher
    ]

    def ready(self):
        """
        Called when Django starts.
        - Déclenche une réconciliation du catalogue au démarrage (web + worker, prod
          incluse), dédupliquée entre process → catalogue frais après chaque redémarrage.
        - Démarre le file watcher en dev (runserver) uniquement.
        La réconciliation périodique est planifiée via Celery Beat (CELERY_BEAT_SCHEDULE).
        """
        # Enregistre le garde-fou anti-dérive des enums (registre ⊆ DB), cf. checks.py / F5.
        from . import checks  # noqa: F401  (l'import déclenche @register)

        # Journal DÉDIÉ pour la synchro du catalogue (brique COMMUNE) : `[ModelSync]`
        # émet une ligne par modèle à chaque réconciliation et représentait 71 % de
        # celery-default.log (138 328 lignes sur 194 328), noyant les traces de tâches
        # réelles. `propagate=False` : ces lignes ne remontent plus au logger racine.
        # La remise à zéro se fait par `manage.py rotate_logs` au démarrage, PAS ici
        # (ready() tourne dans chacun des ~7 process).
        self._attach_sync_log()

        if any(cmd in sys.argv for cmd in self._SKIP_CMDS):
            return

        # Sync au démarrage — prod-compatible (NE dépend PAS de RUN_MAIN, contrairement
        # au watcher), non bloquant (dispatch Celery), dédupliqué via un verrou cache.
        self._dispatch_startup_sync()

        # Le watcher ne tourne qu'en runserver (RUN_MAIN) : en prod multi-worker il
        # serait dupliqué et inutile → on s'appuie sur sync-démarrage + Beat.
        if os.environ.get('RUN_MAIN') == 'true':
            self._start_file_watcher()

    # Loggers de MAINTENANCE du catalogue : ils émettent une ligne par modèle à
    # chaque réconciliation (~97 modèles), ce qui noie les traces de tâches
    # réelles dans le journal du worker. Leur DÉTAIL part dans un journal dédié.
    #
    # Ce qui RESTE volontairement dans celery-default.log : la trace de niveau
    # tâche, qui vient d'autres loggers — « Task model_manager.sync_models
    # received », « Starting background model sync », le résumé « Model sync
    # complete: +0, ~97, -0 » et « succeeded ». On voit donc toujours que la
    # tâche a tourné et ce qu'elle a changé, sans le détail modèle par modèle.
    _SYNC_LOGGERS = (
        'wama.model_manager.services.model_sync',      # [ModelSync]
        'wama.model_manager.services.model_registry',  # [ModelRegistry]
    )

    def _attach_sync_log(self):
        """Route le détail de maintenance du catalogue vers `logs/model-sync.log`."""
        try:
            from wama.common.utils.log_rotation import attach_dedicated_log

            for name in self._SYNC_LOGGERS:
                attach_dedicated_log(name, 'model-sync.log')
        except Exception as exc:
            logger.debug(f"Journal dédié model-sync non attaché : {exc}")

    def _dispatch_startup_sync(self):
        """Dispatch (une seule fois, tous process confondus) une réconciliation au démarrage."""
        try:
            from django.core.cache import cache
            # Verrou court partagé (Redis) : seul le 1er process au démarrage dispatche.
            if not cache.add('model_manager_startup_sync', 1, timeout=300):
                return
            from .tasks import sync_models_task
            sync_models_task.apply_async(kwargs={'clean': False}, countdown=20)
            logger.info("Model catalog reconcile dispatched at startup")
        except Exception as e:
            # Broker down au démarrage, etc. : la réconciliation Beat prendra le relais.
            logger.debug(f"Startup model sync not dispatched: {e}")

    def _start_file_watcher(self):
        """Start the model file watcher."""
        try:
            from .services.file_watcher import get_file_watcher, is_watchdog_available

            if not is_watchdog_available():
                logger.info(
                    "Model file watcher disabled: watchdog not installed. "
                    "Install with: pip install watchdog"
                )
                return

            watcher = get_file_watcher()
            if watcher.start():
                dirs = watcher.get_watched_directories()
                logger.info(
                    f"Model file watcher started, watching {len(dirs)} directories"
                )
            else:
                logger.warning("Failed to start model file watcher")

        except Exception as e:
            logger.error(f"Error starting file watcher: {e}")
