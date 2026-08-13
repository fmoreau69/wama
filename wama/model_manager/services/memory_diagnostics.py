"""
Diagnostic mémoire du PROCESS COURANT — chasse aux fuites, pas suivi des modèles.

⚠ CE MODULE NE SUIT PLUS LES MODÈLES RÉSIDENTS (2026-08-13).

Il s'appelait `memory_tracker.py` et portait une classe `WAMAMemoryTracker` avec un registre
`{model_id → TrackedModel}` alimenté par `register_model()`. Ce registre était une **route
morte doublant le gouverneur** :

* `register_model()` n'avait **aucun appelant** dans le dépôt depuis sa création (2026-02-02,
  `470b5a3`) — le registre était donc **toujours vide** ;
* même alimenté, il n'aurait vu que le process courant, alors que les modèles vivent dans les
  workers Celery et le service TTS, et que les lecteurs (`api_tracked_models`,
  `api_idle_models`) tournent dans gunicorn : le registre n'aurait **jamais rien montré** ;
* trois consommateurs y croyaient et ne faisaient rien : `cleanup_idle_models()`,
  `aggressive_cleanup()` (appelée par `nightly_tests` ET `cam_analyzer`) et
  `unload_specific_model()` déchargeaient systématiquement **zéro modèle**.

La route unique du suivi des modèles résidents est **`wama/common/services/resource_governor.py`**
(registre Redis, tous process confondus, alimenté automatiquement par les enveloppes de
`BaseModelBackend`). Pour SAVOIR : `resident_models()` / `idle_models()`. Pour AGIR (décharger) :
`MemoryManager.unload_model()` / `release_vram()`, qui déroulent `_VRAM_UNLOADERS`.

Ce qui reste ici est **d'une autre nature** et ne doublonne rien : des sondes de diagnostic
in-process (tracemalloc, gros objets du GC) utiles pour chercher une fuite, indépendantes de
tout registre de modèles.
"""

import gc
import logging
import sys
import tracemalloc
from dataclasses import dataclass
from typing import Dict, List, Optional, Any
from threading import Lock

logger = logging.getLogger(__name__)


@dataclass
class LargeObject:
    """Un objet volumineux repéré dans le tas du process courant."""
    obj_type: str
    size_mb: float
    obj_id: int
    ref_count: int


class MemoryDiagnostics:
    """
    Sondes mémoire du process courant : snapshots tracemalloc et gros objets.

    Singleton parce que les snapshots tracemalloc n'ont de sens que comparés entre eux,
    donc accumulés dans un même porteur.
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

        self._snapshots: List[tuple] = []  # (label, tracemalloc snapshot)
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

        ⚠ Ne rattache PLUS l'objet à un `model_id` : ce rattachement se faisait par
        comparaison avec le registre `_models`, qui était toujours vide (cf. l'en-tête
        du module) — le champ valait donc `None` en toutes circonstances. Le poids d'un
        modèle résident se lit au gouverneur (`resident_models()`), pas ici : un modèle
        GPU pèse quelques centaines d'octets côté Python, `sys.getsizeof` ne voit pas
        sa VRAM.

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
                        large_objects.append(LargeObject(
                            obj_type=type(obj).__name__,
                            size_mb=size / (1024**2),
                            obj_id=id(obj),
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
