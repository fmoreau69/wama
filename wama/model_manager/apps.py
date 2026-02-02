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

    def ready(self):
        """
        Called when Django starts.
        Starts the file watcher for model directory monitoring.
        """
        # Only run in the main process (not in management commands or migrations)
        # RUN_MAIN is set by Django's runserver in the reloader process
        if os.environ.get('RUN_MAIN') != 'true':
            return

        # Don't start watcher during migrations or other management commands
        if any(cmd in sys.argv for cmd in [
            'migrate', 'makemigrations', 'collectstatic',
            'sync_models', 'shell', 'dbshell', 'test'
        ]):
            return

        # Start file watcher in a separate thread
        self._start_file_watcher()

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
