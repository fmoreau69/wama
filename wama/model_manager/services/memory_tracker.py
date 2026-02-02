"""
WAMA Memory Tracker - Track loaded models and detect memory issues.

Provides tracking of:
- Loaded models and their memory usage
- Idle models that could be unloaded
- Large objects in memory
- Memory leaks via snapshot comparison
"""

import gc
import logging
import sys
import time
import tracemalloc
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class TrackedModel:
    """Information about a tracked model in memory."""
    model_id: str
    model_ref: Any  # Weak reference to the model object
    size_mb: float
    loaded_at: float  # timestamp
    last_used: float  # timestamp
    use_count: int
    status: str  # 'active', 'idle', 'unloaded'
    category: str  # 'diffusion', 'vision', 'speech', etc.
    source: str  # 'imager', 'anonymizer', etc.

    def to_dict(self) -> Dict:
        current_time = time.time()
        return {
            'model_id': self.model_id,
            'size_mb': self.size_mb,
            'loaded_at': datetime.fromtimestamp(self.loaded_at).isoformat(),
            'last_used': datetime.fromtimestamp(self.last_used).isoformat(),
            'idle_seconds': current_time - self.last_used,
            'idle_minutes': (current_time - self.last_used) / 60,
            'use_count': self.use_count,
            'status': self.status,
            'category': self.category,
            'source': self.source,
        }


@dataclass
class IdleModel:
    """Information about an idle model."""
    model_id: str
    idle_time_seconds: float
    idle_time_minutes: float
    size_mb: float
    use_count: int
    category: str
    source: str


@dataclass
class LargeObject:
    """Information about a large object in memory."""
    obj_type: str
    size_mb: float
    obj_id: int
    model_id: Optional[str]
    ref_count: int


class WAMAMemoryTracker:
    """
    Track models loaded in memory and detect issues.

    Features:
    - Register/unregister models
    - Track model usage
    - Detect idle models
    - Find large objects
    - Memory leak detection via tracemalloc
    """

    _instance = None
    _lock = Lock()

    def __new__(cls):
        """Singleton pattern with thread safety."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._models: Dict[str, TrackedModel] = {}
        self._snapshots: List[tuple] = []  # (label, tracemalloc snapshot)
        self._unload_callbacks: Dict[str, Callable] = {}  # model_id -> unload function
        self._tracemalloc_started = False
        self._initialized = True

    def start_tracemalloc(self):
        """Start tracemalloc for memory leak detection."""
        if not self._tracemalloc_started:
            tracemalloc.start()
            self._tracemalloc_started = True
            logger.info("Tracemalloc started for memory tracking")

    def stop_tracemalloc(self):
        """Stop tracemalloc."""
        if self._tracemalloc_started:
            tracemalloc.stop()
            self._tracemalloc_started = False

    def register_model(
        self,
        model_id: str,
        model_obj: Any,
        size_mb: float,
        category: str = 'unknown',
        source: str = 'unknown',
        unload_callback: Optional[Callable] = None,
    ):
        """
        Register a model as loaded in memory.

        Args:
            model_id: Unique identifier for the model
            model_obj: The model object (or None if tracking externally)
            size_mb: Estimated size in MB
            category: Model category (diffusion, vision, speech, etc.)
            source: Source app (imager, anonymizer, etc.)
            unload_callback: Function to call to unload the model
        """
        with self._lock:
            current_time = time.time()

            self._models[model_id] = TrackedModel(
                model_id=model_id,
                model_ref=model_obj,
                size_mb=size_mb,
                loaded_at=current_time,
                last_used=current_time,
                use_count=0,
                status='active',
                category=category,
                source=source,
            )

            if unload_callback:
                self._unload_callbacks[model_id] = unload_callback

            logger.info(f"Model registered: {model_id} ({size_mb:.1f} MB, {category}/{source})")

    def unregister_model(self, model_id: str):
        """
        Unregister a model (mark as unloaded).

        Args:
            model_id: Model identifier
        """
        with self._lock:
            if model_id in self._models:
                self._models[model_id].status = 'unloaded'
                self._models[model_id].model_ref = None
                logger.info(f"Model unregistered: {model_id}")

            if model_id in self._unload_callbacks:
                del self._unload_callbacks[model_id]

    def mark_model_used(self, model_id: str):
        """
        Mark a model as recently used.

        Args:
            model_id: Model identifier
        """
        with self._lock:
            if model_id in self._models:
                self._models[model_id].last_used = time.time()
                self._models[model_id].use_count += 1
                self._models[model_id].status = 'active'

    def get_model(self, model_id: str) -> Optional[TrackedModel]:
        """Get tracked model info."""
        return self._models.get(model_id)

    def get_all_models(self) -> Dict[str, Dict]:
        """Get all tracked models as dicts."""
        return {
            model_id: model.to_dict()
            for model_id, model in self._models.items()
        }

    def get_active_models(self) -> List[TrackedModel]:
        """Get all active (loaded) models."""
        return [m for m in self._models.values() if m.status == 'active']

    def get_idle_models(self, idle_threshold_seconds: int = 300) -> List[IdleModel]:
        """
        Get models that have been idle for longer than threshold.

        Args:
            idle_threshold_seconds: Seconds of inactivity before considered idle

        Returns:
            List of IdleModel objects
        """
        current_time = time.time()
        idle_models = []

        for model in self._models.values():
            if model.status != 'active':
                continue

            idle_time = current_time - model.last_used
            if idle_time > idle_threshold_seconds:
                idle_models.append(IdleModel(
                    model_id=model.model_id,
                    idle_time_seconds=idle_time,
                    idle_time_minutes=idle_time / 60,
                    size_mb=model.size_mb,
                    use_count=model.use_count,
                    category=model.category,
                    source=model.source,
                ))

        # Sort by idle time (most idle first)
        idle_models.sort(key=lambda x: x.idle_time_seconds, reverse=True)
        return idle_models

    def get_total_tracked_memory(self) -> float:
        """Get total memory of all active tracked models in MB."""
        return sum(m.size_mb for m in self._models.values() if m.status == 'active')

    def take_tracemalloc_snapshot(self, label: str = "") -> Optional[Any]:
        """
        Take a tracemalloc snapshot for memory leak detection.

        Args:
            label: Label for this snapshot

        Returns:
            The snapshot object
        """
        if not self._tracemalloc_started:
            self.start_tracemalloc()

        try:
            snapshot = tracemalloc.take_snapshot()
            self._snapshots.append((label or f"snapshot_{len(self._snapshots)}", snapshot))

            # Keep only last 10 snapshots
            if len(self._snapshots) > 10:
                self._snapshots = self._snapshots[-10:]

            return snapshot
        except Exception as e:
            logger.error(f"Failed to take tracemalloc snapshot: {e}")
            return None

    def compare_snapshots(
        self,
        snapshot1_idx: int = -2,
        snapshot2_idx: int = -1,
        top_n: int = 10
    ) -> List[Dict]:
        """
        Compare two tracemalloc snapshots to find memory increases.

        Args:
            snapshot1_idx: Index of first snapshot
            snapshot2_idx: Index of second snapshot
            top_n: Number of top differences to return

        Returns:
            List of dicts with memory difference info
        """
        if len(self._snapshots) < 2:
            return []

        try:
            label1, snap1 = self._snapshots[snapshot1_idx]
            label2, snap2 = self._snapshots[snapshot2_idx]

            top_stats = snap2.compare_to(snap1, 'lineno')

            results = []
            for stat in top_stats[:top_n]:
                if stat.size_diff > 0:  # Only increases
                    results.append({
                        'file': str(stat.traceback),
                        'size_diff_mb': stat.size_diff / (1024**2),
                        'count_diff': stat.count_diff,
                        'size_mb': stat.size / (1024**2),
                    })

            return results
        except Exception as e:
            logger.error(f"Failed to compare snapshots: {e}")
            return []

    def find_large_objects(self, min_size_mb: float = 10) -> List[LargeObject]:
        """
        Find large objects in memory.

        Args:
            min_size_mb: Minimum size to consider

        Returns:
            List of LargeObject info
        """
        large_objects = []
        min_size_bytes = min_size_mb * 1024 * 1024

        try:
            for obj in gc.get_objects():
                try:
                    size = sys.getsizeof(obj)
                    if size > min_size_bytes:
                        obj_type = type(obj).__name__
                        obj_id = id(obj)

                        # Try to identify if it's a known model
                        model_id = None
                        for mid, info in self._models.items():
                            if info.model_ref is not None and id(info.model_ref) == obj_id:
                                model_id = mid
                                break

                        large_objects.append(LargeObject(
                            obj_type=obj_type,
                            size_mb=size / (1024**2),
                            obj_id=obj_id,
                            model_id=model_id,
                            ref_count=sys.getrefcount(obj),
                        ))
                except (TypeError, ReferenceError):
                    pass

            # Sort by size
            large_objects.sort(key=lambda x: x.size_mb, reverse=True)
            return large_objects[:50]  # Limit to top 50

        except Exception as e:
            logger.error(f"Error finding large objects: {e}")
            return []

    def get_unload_callback(self, model_id: str) -> Optional[Callable]:
        """Get the unload callback for a model."""
        return self._unload_callbacks.get(model_id)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of tracked memory."""
        active = self.get_active_models()
        idle = self.get_idle_models(300)  # 5 min threshold

        return {
            'total_tracked_mb': self.get_total_tracked_memory(),
            'active_count': len(active),
            'idle_count': len(idle),
            'total_registered': len(self._models),
            'models': {
                model_id: model.to_dict()
                for model_id, model in self._models.items()
                if model.status == 'active'
            },
            'idle_models': [
                {
                    'model_id': m.model_id,
                    'idle_minutes': round(m.idle_time_minutes, 1),
                    'size_mb': m.size_mb,
                    'use_count': m.use_count,
                    'category': m.category,
                }
                for m in idle
            ],
        }

    def print_summary(self):
        """Print a formatted summary to console."""
        summary = self.get_summary()

        print("\n" + "=" * 60)
        print("📦 MODÈLES TRACKÉS")
        print("=" * 60)
        print(f"Total trackés:  {summary['total_registered']}")
        print(f"Actifs:         {summary['active_count']}")
        print(f"Inactifs (>5m): {summary['idle_count']}")
        print(f"Mémoire totale: {summary['total_tracked_mb']:.1f} MB")

        if summary['models']:
            print("\n📦 Modèles actifs:")
            for model_id, info in summary['models'].items():
                print(f"  - {model_id}: {info['size_mb']:.1f} MB, "
                      f"utilisé {info['use_count']}x, "
                      f"idle {info['idle_minutes']:.1f} min")

        if summary['idle_models']:
            print("\n⏰ Modèles inactifs (> 5 min):")
            for m in summary['idle_models']:
                print(f"  - {m['model_id']}: {m['size_mb']:.1f} MB, "
                      f"idle {m['idle_minutes']:.1f} min")

        print("=" * 60 + "\n")
