"""
WAMA Memory Cleaner - Automatic memory cleanup service.

Provides automatic cleanup of:
- Idle models (not used for N seconds)
- GPU cache
- Python garbage collection
- Aggressive cleanup when memory is critical
"""

import gc
import logging
import threading
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

# Check for torch
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False


@dataclass
class CleanupResult:
    """Result of a cleanup operation."""
    success: bool
    models_unloaded: List[str]
    memory_freed_mb: float
    gc_collected: int
    gpu_cache_cleared: bool
    ram_before_percent: float
    ram_after_percent: float
    timestamp: datetime

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'models_unloaded': self.models_unloaded,
            'memory_freed_mb': self.memory_freed_mb,
            'gc_collected': self.gc_collected,
            'gpu_cache_cleared': self.gpu_cache_cleared,
            'ram_before_percent': self.ram_before_percent,
            'ram_after_percent': self.ram_after_percent,
            'timestamp': self.timestamp.isoformat(),
        }


class WAMAMemoryCleaner:
    """
    Automatic memory cleaner for WAMA.

    Features:
    - Background thread for periodic cleanup
    - Idle model detection and unloading
    - GPU cache clearing
    - Aggressive cleanup when memory is critical
    - Manual cleanup triggers
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        # Configuration
        self.check_interval = 60  # Check every 60 seconds
        self.idle_threshold = 300  # 5 minutes idle before cleanup
        self.ram_warning_threshold = 80.0  # Warning at 80%
        self.ram_critical_threshold = 90.0  # Aggressive cleanup at 90%
        self.gpu_warning_threshold = 85.0
        self.gpu_critical_threshold = 95.0

        # State
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._cleanup_history: List[CleanupResult] = []
        self._max_history = 50
        self._last_cleanup_time = 0

        self._initialized = True

    def configure(
        self,
        check_interval: int = None,
        idle_threshold: int = None,
        ram_warning_threshold: float = None,
        ram_critical_threshold: float = None,
    ):
        """
        Configure the cleaner.

        Args:
            check_interval: Seconds between checks
            idle_threshold: Seconds before model is considered idle
            ram_warning_threshold: RAM % for warning
            ram_critical_threshold: RAM % for aggressive cleanup
        """
        if check_interval is not None:
            self.check_interval = check_interval
        if idle_threshold is not None:
            self.idle_threshold = idle_threshold
        if ram_warning_threshold is not None:
            self.ram_warning_threshold = ram_warning_threshold
        if ram_critical_threshold is not None:
            self.ram_critical_threshold = ram_critical_threshold

    def start(self):
        """Start the background cleanup thread."""
        if self._running:
            logger.warning("Memory cleaner already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self._thread.start()

        logger.info(
            f"🧹 Memory Cleaner started "
            f"(check: {self.check_interval}s, idle: {self.idle_threshold}s, "
            f"RAM threshold: {self.ram_critical_threshold}%)"
        )

    def stop(self):
        """Stop the background cleanup thread."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Memory Cleaner stopped")

    def is_running(self) -> bool:
        """Check if cleaner is running."""
        return self._running

    def _cleanup_loop(self):
        """Background cleanup loop."""
        while self._running:
            try:
                self._check_and_clean()
            except Exception as e:
                logger.error(f"Error in memory cleaner loop: {e}")

            time.sleep(self.check_interval)

    def _check_and_clean(self):
        """Check memory status and clean if necessary."""
        from .memory_monitor import WAMAMemoryMonitor

        monitor = WAMAMemoryMonitor()
        ram = monitor.get_ram_usage()
        gpus = monitor.get_gpu_usage()

        # Check RAM
        if ram.percent > self.ram_critical_threshold:
            logger.warning(f"⚠️ RAM critical: {ram.percent:.1f}% - Aggressive cleanup")
            self.aggressive_cleanup()
            return

        if ram.percent > self.ram_warning_threshold:
            logger.info(f"RAM warning: {ram.percent:.1f}% - Cleaning idle models")
            self.cleanup_idle_models()
            return

        # Check GPU
        for gpu in gpus:
            if gpu.utilization_percent > self.gpu_critical_threshold:
                logger.warning(f"⚠️ GPU {gpu.device} VRAM critical: {gpu.utilization_percent:.1f}%")
                self.clear_gpu_cache()
                return

        # Normal check - clean idle models periodically
        current_time = time.time()
        if current_time - self._last_cleanup_time > self.idle_threshold:
            self.cleanup_idle_models(quiet=True)
            self._last_cleanup_time = current_time

    def cleanup_idle_models(self, quiet: bool = False) -> CleanupResult:
        """
        Unload models that have been idle.

        Args:
            quiet: Don't log if nothing to clean

        Returns:
            CleanupResult with details
        """
        from .memory_monitor import WAMAMemoryMonitor
        from .memory_tracker import WAMAMemoryTracker

        monitor = WAMAMemoryMonitor()
        tracker = WAMAMemoryTracker()

        ram_before = monitor.get_ram_usage()
        models_unloaded = []
        memory_freed = 0

        idle_models = tracker.get_idle_models(self.idle_threshold)

        if not idle_models and not quiet:
            logger.info("No idle models to clean")

        for model_info in idle_models:
            success = self._unload_model(model_info.model_id, tracker)
            if success:
                models_unloaded.append(model_info.model_id)
                memory_freed += model_info.size_mb

        # Run garbage collection
        gc_collected = gc.collect()

        ram_after = monitor.get_ram_usage()

        result = CleanupResult(
            success=True,
            models_unloaded=models_unloaded,
            memory_freed_mb=memory_freed,
            gc_collected=gc_collected,
            gpu_cache_cleared=False,
            ram_before_percent=ram_before.percent,
            ram_after_percent=ram_after.percent,
            timestamp=datetime.now(),
        )

        self._add_to_history(result)

        if models_unloaded:
            logger.info(
                f"🧹 Cleaned {len(models_unloaded)} idle models, "
                f"freed ~{memory_freed:.1f} MB, "
                f"RAM: {ram_before.percent:.1f}% → {ram_after.percent:.1f}%"
            )

        return result

    def aggressive_cleanup(self) -> CleanupResult:
        """
        Aggressive cleanup - unload all idle models and clear caches.

        Returns:
            CleanupResult with details
        """
        from .memory_monitor import WAMAMemoryMonitor
        from .memory_tracker import WAMAMemoryTracker

        logger.info("🔥 AGGRESSIVE CLEANUP STARTED")

        monitor = WAMAMemoryMonitor()
        tracker = WAMAMemoryTracker()

        ram_before = monitor.get_ram_usage()
        models_unloaded = []
        memory_freed = 0

        # 1. Unload ALL idle models (even recently used)
        idle_models = tracker.get_idle_models(idle_threshold_seconds=0)
        for model_info in idle_models:
            success = self._unload_model(model_info.model_id, tracker)
            if success:
                models_unloaded.append(model_info.model_id)
                memory_freed += model_info.size_mb

        # 2. Force garbage collection multiple times
        gc_collected = 0
        for _ in range(3):
            gc_collected += gc.collect()

        # 3. Clear GPU cache
        gpu_cleared = self.clear_gpu_cache()

        # 4. Clear Python internal caches
        try:
            import linecache
            linecache.clearcache()
        except:
            pass

        try:
            import importlib
            importlib.invalidate_caches()
        except:
            pass

        ram_after = monitor.get_ram_usage()

        result = CleanupResult(
            success=True,
            models_unloaded=models_unloaded,
            memory_freed_mb=memory_freed,
            gc_collected=gc_collected,
            gpu_cache_cleared=gpu_cleared,
            ram_before_percent=ram_before.percent,
            ram_after_percent=ram_after.percent,
            timestamp=datetime.now(),
        )

        self._add_to_history(result)

        logger.info(
            f"✅ Aggressive cleanup done: "
            f"{len(models_unloaded)} models unloaded, "
            f"~{memory_freed:.1f} MB freed, "
            f"GC: {gc_collected} objects, "
            f"RAM: {ram_before.percent:.1f}% → {ram_after.percent:.1f}%"
        )

        return result

    def _unload_model(self, model_id: str, tracker) -> bool:
        """
        Unload a specific model.

        Args:
            model_id: Model identifier
            tracker: WAMAMemoryTracker instance

        Returns:
            True if successfully unloaded
        """
        try:
            # Try custom unload callback first
            callback = tracker.get_unload_callback(model_id)
            if callback:
                callback()

            # Mark as unloaded in tracker
            tracker.unregister_model(model_id)

            logger.info(f"  🗑️ Unloaded: {model_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to unload {model_id}: {e}")
            return False

    def clear_gpu_cache(self) -> bool:
        """
        Clear GPU VRAM cache.

        Returns:
            True if GPU cache was cleared
        """
        if not TORCH_AVAILABLE or not torch.cuda.is_available():
            return False

        try:
            for i in range(torch.cuda.device_count()):
                with torch.cuda.device(i):
                    torch.cuda.empty_cache()
                    torch.cuda.synchronize()

            logger.info("🎮 GPU cache cleared")
            return True

        except Exception as e:
            logger.error(f"Failed to clear GPU cache: {e}")
            return False

    def force_gc(self) -> int:
        """
        Force Python garbage collection.

        Returns:
            Number of objects collected
        """
        collected = 0
        for _ in range(3):
            collected += gc.collect()
        logger.info(f"♻️ GC collected {collected} objects")
        return collected

    def unload_specific_model(self, model_id: str) -> bool:
        """
        Manually unload a specific model.

        Args:
            model_id: Model to unload

        Returns:
            True if successfully unloaded
        """
        from .memory_tracker import WAMAMemoryTracker

        tracker = WAMAMemoryTracker()
        model = tracker.get_model(model_id)

        if not model:
            logger.warning(f"Model not found: {model_id}")
            return False

        success = self._unload_model(model_id, tracker)

        if success:
            gc.collect()
            if TORCH_AVAILABLE and torch.cuda.is_available():
                torch.cuda.empty_cache()

        return success

    def _add_to_history(self, result: CleanupResult):
        """Add cleanup result to history."""
        self._cleanup_history.append(result)
        if len(self._cleanup_history) > self._max_history:
            self._cleanup_history = self._cleanup_history[-self._max_history:]

    def get_history(self, limit: int = 10) -> List[Dict]:
        """Get cleanup history."""
        return [r.to_dict() for r in self._cleanup_history[-limit:]]

    def get_status(self) -> Dict[str, Any]:
        """Get cleaner status."""
        return {
            'running': self._running,
            'check_interval': self.check_interval,
            'idle_threshold': self.idle_threshold,
            'ram_warning_threshold': self.ram_warning_threshold,
            'ram_critical_threshold': self.ram_critical_threshold,
            'gpu_warning_threshold': self.gpu_warning_threshold,
            'gpu_critical_threshold': self.gpu_critical_threshold,
            'cleanup_count': len(self._cleanup_history),
            'last_cleanup': self._cleanup_history[-1].to_dict() if self._cleanup_history else None,
        }


# Global instance management
def get_memory_cleaner() -> WAMAMemoryCleaner:
    """Get the global memory cleaner instance."""
    return WAMAMemoryCleaner()


def start_memory_cleaner(
    check_interval: int = 60,
    idle_threshold: int = 300,
    ram_critical_threshold: float = 90.0,
):
    """
    Start the global memory cleaner.

    Args:
        check_interval: Seconds between checks
        idle_threshold: Seconds before model is considered idle
        ram_critical_threshold: RAM % for aggressive cleanup
    """
    cleaner = get_memory_cleaner()
    cleaner.configure(
        check_interval=check_interval,
        idle_threshold=idle_threshold,
        ram_critical_threshold=ram_critical_threshold,
    )
    cleaner.start()
    return cleaner


def stop_memory_cleaner():
    """Stop the global memory cleaner."""
    cleaner = get_memory_cleaner()
    cleaner.stop()
