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
    ]

    def ready(self):
        """
        Called when Django starts.
        - Déclenche une réconciliation du catalogue au démarrage (web + worker, prod
          incluse), dédupliquée entre process → catalogue frais après chaque redémarrage.
        - Démarre le file watcher en dev (runserver) uniquement.
        La réconciliation périodique est planifiée via Celery Beat (CELERY_BEAT_SCHEDULE).
        """
        if any(cmd in sys.argv for cmd in self._SKIP_CMDS):
            return

        # Sync au démarrage — prod-compatible (NE dépend PAS de RUN_MAIN, contrairement
        # au watcher), non bloquant (dispatch Celery), dédupliqué via un verrou cache.
        self._dispatch_startup_sync()

        # Le watcher ne tourne qu'en runserver (RUN_MAIN) : en prod multi-worker il
        # serait dupliqué et inutile → on s'appuie sur sync-démarrage + Beat.
        if os.environ.get('RUN_MAIN') == 'true':
            self._start_file_watcher()

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
