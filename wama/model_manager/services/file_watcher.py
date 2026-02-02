"""
File Watcher Service - Monitors AI-models directory for changes.

Uses watchdog with debouncing to prevent excessive DB updates.
Automatically syncs file system changes to the PostgreSQL catalog.
"""

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Set, Optional, List

from django.conf import settings

logger = logging.getLogger(__name__)

# Check if watchdog is available
try:
    from watchdog.observers import Observer
    from watchdog.events import (
        FileSystemEventHandler,
        FileCreatedEvent,
        FileDeletedEvent,
        FileMovedEvent,
    )
    WATCHDOG_AVAILABLE = True
except ImportError:
    WATCHDOG_AVAILABLE = False
    logger.warning("watchdog not installed. File watching disabled. Install with: pip install watchdog")


if WATCHDOG_AVAILABLE:
    class DebouncedHandler(FileSystemEventHandler):
        """
        File system event handler with debouncing.
        Collects events and processes them in batches after a quiet period.
        """

        # Model file extensions to watch
        MODEL_EXTENSIONS = {'.onnx', '.pt', '.pth', '.safetensors', '.bin', '.gguf', '.ckpt'}

        def __init__(
            self,
            callback: Callable[[Set[Path], Set[Path]], None],
            debounce_seconds: float = 2.0
        ):
            """
            Args:
                callback: Function called with (added_paths, removed_paths)
                debounce_seconds: Wait time after last event before processing
            """
            super().__init__()
            self._callback = callback
            self._debounce_seconds = debounce_seconds

            # Pending changes
            self._added: Set[Path] = set()
            self._removed: Set[Path] = set()

            # Debounce timer
            self._timer: Optional[threading.Timer] = None
            self._lock = threading.Lock()

        def _is_model_file(self, path: str) -> bool:
            """Check if path is a model file."""
            return Path(path).suffix.lower() in self.MODEL_EXTENSIONS

        def _schedule_callback(self):
            """Schedule the callback after debounce period."""
            with self._lock:
                if self._timer:
                    self._timer.cancel()

                self._timer = threading.Timer(
                    self._debounce_seconds,
                    self._execute_callback
                )
                self._timer.daemon = True
                self._timer.start()

        def _execute_callback(self):
            """Execute callback with collected changes."""
            with self._lock:
                added = self._added.copy()
                removed = self._removed.copy()
                self._added.clear()
                self._removed.clear()
                self._timer = None

            if added or removed:
                logger.info(f"File watcher: {len(added)} added, {len(removed)} removed")
                try:
                    self._callback(added, removed)
                except Exception as e:
                    logger.error(f"File watcher callback error: {e}")

        def on_created(self, event):
            """Handle file created event."""
            if event.is_directory:
                return

            if self._is_model_file(event.src_path):
                with self._lock:
                    path = Path(event.src_path)
                    self._added.add(path)
                    self._removed.discard(path)
                self._schedule_callback()

        def on_deleted(self, event):
            """Handle file deleted event."""
            if event.is_directory:
                return

            if self._is_model_file(event.src_path):
                with self._lock:
                    path = Path(event.src_path)
                    self._removed.add(path)
                    self._added.discard(path)
                self._schedule_callback()

        def on_moved(self, event):
            """Handle file moved event."""
            if event.is_directory:
                return

            src_is_model = self._is_model_file(event.src_path)
            dest_is_model = self._is_model_file(event.dest_path)

            with self._lock:
                if src_is_model:
                    self._removed.add(Path(event.src_path))
                if dest_is_model:
                    self._added.add(Path(event.dest_path))

            if src_is_model or dest_is_model:
                self._schedule_callback()


class ModelFileWatcher:
    """
    Watches AI-models directories for changes and syncs to database.

    Usage:
        watcher = get_file_watcher()
        watcher.start()
        # ... application runs ...
        watcher.stop()
    """

    def __init__(self):
        self._observer = None
        self._running = False
        self._lock = threading.Lock()

        # Directories to watch
        self._watch_dirs: List[Path] = []

    def _get_watch_directories(self) -> List[Path]:
        """Get list of directories to watch."""
        dirs = []

        # Main AI-models directory
        ai_models_dir = getattr(settings, 'AI_MODELS_DIR', None)
        if ai_models_dir:
            models_path = Path(ai_models_dir) / 'models'
            if models_path.exists():
                dirs.append(models_path)

        # MODEL_PATHS subdirectories
        model_paths = getattr(settings, 'MODEL_PATHS', {})
        for category, paths in model_paths.items():
            if category == 'cache':
                continue  # Skip cache directories for now

            if isinstance(paths, dict):
                for key, path in paths.items():
                    if path:
                        p = Path(path)
                        if p.exists():
                            dirs.append(p)
            elif paths:
                p = Path(paths)
                if p.exists():
                    dirs.append(p)

        # Remove duplicates while preserving order
        unique_dirs = []
        seen = set()
        for d in dirs:
            resolved = d.resolve()
            if str(resolved) not in seen:
                unique_dirs.append(resolved)
                seen.add(str(resolved))

        return unique_dirs

    def _on_file_changes(self, added: Set[Path], removed: Set[Path]):
        """Handle file system changes - sync to database."""
        from .model_sync import get_sync_service
        from ..models import ModelSyncLog

        logger.info(f"Processing file changes: {len(added)} added, {len(removed)} removed")

        # Create sync log
        log = ModelSyncLog.objects.create(
            sync_type='watchdog',
            details={
                'added': [str(p) for p in added],
                'removed': [str(p) for p in removed]
            }
        )

        try:
            sync_service = get_sync_service()

            # Process added files
            for path in added:
                try:
                    if sync_service.sync_file_change(path, is_added=True):
                        log.models_added += 1
                except Exception as e:
                    logger.error(f"Error syncing added file {path}: {e}")

            # Process removed files
            for path in removed:
                try:
                    if sync_service.sync_file_change(path, is_added=False):
                        log.models_removed += 1
                except Exception as e:
                    logger.error(f"Error syncing removed file {path}: {e}")

            log.status = 'completed'

        except Exception as e:
            logger.error(f"Error processing file changes: {e}")
            log.status = 'failed'
            log.error_message = str(e)

        from django.utils import timezone
        log.completed_at = timezone.now()
        log.save()

    def start(self) -> bool:
        """Start the file watcher."""
        if not WATCHDOG_AVAILABLE:
            logger.warning("Cannot start file watcher: watchdog not installed")
            return False

        with self._lock:
            if self._running:
                logger.warning("File watcher already running")
                return False

            self._watch_dirs = self._get_watch_directories()

            if not self._watch_dirs:
                logger.warning("No directories to watch")
                return False

            self._observer = Observer()
            handler = DebouncedHandler(
                callback=self._on_file_changes,
                debounce_seconds=2.0
            )

            watched_count = 0
            for watch_dir in self._watch_dirs:
                try:
                    self._observer.schedule(
                        handler,
                        str(watch_dir),
                        recursive=True
                    )
                    logger.info(f"Watching directory: {watch_dir}")
                    watched_count += 1
                except Exception as e:
                    logger.error(f"Failed to watch {watch_dir}: {e}")

            if watched_count == 0:
                logger.error("Failed to watch any directories")
                return False

            self._observer.start()
            self._running = True
            logger.info(f"File watcher started, watching {watched_count} directories")

            return True

    def stop(self):
        """Stop the file watcher."""
        with self._lock:
            if not self._running:
                return

            if self._observer:
                self._observer.stop()
                self._observer.join(timeout=5)
                self._observer = None

            self._running = False
            logger.info("File watcher stopped")

    def is_running(self) -> bool:
        """Check if watcher is running."""
        return self._running

    def get_watched_directories(self) -> List[str]:
        """Get list of watched directories."""
        return [str(d) for d in self._watch_dirs]

    def get_status(self) -> dict:
        """Get watcher status."""
        return {
            'available': WATCHDOG_AVAILABLE,
            'running': self._running,
            'watched_directories': self.get_watched_directories(),
        }


# Singleton instance
_file_watcher: Optional[ModelFileWatcher] = None
_watcher_lock = threading.Lock()


def get_file_watcher() -> ModelFileWatcher:
    """Get the singleton file watcher instance."""
    global _file_watcher
    with _watcher_lock:
        if _file_watcher is None:
            _file_watcher = ModelFileWatcher()
    return _file_watcher


def is_watchdog_available() -> bool:
    """Check if watchdog is installed."""
    return WATCHDOG_AVAILABLE
