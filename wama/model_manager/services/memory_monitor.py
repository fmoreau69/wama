"""
WAMA Memory Monitor - RAM and GPU memory monitoring.

Provides real-time monitoring of system memory usage including:
- System RAM usage
- Process-specific memory (RSS, VMS)
- GPU VRAM usage (CUDA)
- Memory trends and alerts
"""

import logging
import os
import sys
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime

logger = logging.getLogger(__name__)

# Check for psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available - memory monitoring will be limited")

# Check for torch
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("torch not available - GPU monitoring will be limited")


@dataclass
class RAMUsage:
    """RAM usage information."""
    total_gb: float
    available_gb: float
    used_gb: float
    percent: float
    process_rss_gb: float  # Resident Set Size
    process_vms_gb: float  # Virtual Memory Size
    process_percent: float  # Process percentage of total RAM


@dataclass
class GPUUsage:
    """GPU usage information."""
    device: int
    name: str
    allocated_gb: float
    reserved_gb: float
    total_gb: float
    free_gb: float
    utilization_percent: float
    temperature: Optional[int] = None


@dataclass
class MemorySnapshot:
    """A snapshot of memory state at a point in time."""
    timestamp: datetime
    label: str
    ram: RAMUsage
    gpus: List[GPUUsage]

    def to_dict(self) -> Dict:
        return {
            'timestamp': self.timestamp.isoformat(),
            'label': self.label,
            'ram': {
                'total_gb': self.ram.total_gb,
                'available_gb': self.ram.available_gb,
                'used_gb': self.ram.used_gb,
                'percent': self.ram.percent,
                'process_rss_gb': self.ram.process_rss_gb,
                'process_vms_gb': self.ram.process_vms_gb,
                'process_percent': self.ram.process_percent,
            },
            'gpus': [
                {
                    'device': gpu.device,
                    'name': gpu.name,
                    'allocated_gb': gpu.allocated_gb,
                    'reserved_gb': gpu.reserved_gb,
                    'total_gb': gpu.total_gb,
                    'free_gb': gpu.free_gb,
                    'utilization_percent': gpu.utilization_percent,
                    'temperature': gpu.temperature,
                }
                for gpu in self.gpus
            ]
        }


class WAMAMemoryMonitor:
    """
    Centralized memory monitor for WAMA.

    Provides methods to query RAM and GPU memory usage,
    track memory over time, and detect memory issues.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._snapshots: List[MemorySnapshot] = []
        self._max_snapshots = 100  # Keep last 100 snapshots
        self._initialized = True

    @staticmethod
    def get_ram_usage() -> RAMUsage:
        """
        Get current RAM usage.

        Returns:
            RAMUsage object with system and process memory info
        """
        if not PSUTIL_AVAILABLE:
            return RAMUsage(
                total_gb=0, available_gb=0, used_gb=0, percent=0,
                process_rss_gb=0, process_vms_gb=0, process_percent=0
            )

        try:
            mem = psutil.virtual_memory()
            process = psutil.Process(os.getpid())
            mem_info = process.memory_info()

            total_gb = mem.total / (1024**3)
            process_rss_gb = mem_info.rss / (1024**3)

            return RAMUsage(
                total_gb=round(total_gb, 2),
                available_gb=round(mem.available / (1024**3), 2),
                used_gb=round(mem.used / (1024**3), 2),
                percent=round(mem.percent, 1),
                process_rss_gb=round(process_rss_gb, 2),
                process_vms_gb=round(mem_info.vms / (1024**3), 2),
                process_percent=round((process_rss_gb / total_gb) * 100, 1) if total_gb > 0 else 0,
            )
        except Exception as e:
            logger.error(f"Error getting RAM usage: {e}")
            return RAMUsage(
                total_gb=0, available_gb=0, used_gb=0, percent=0,
                process_rss_gb=0, process_vms_gb=0, process_percent=0
            )

    @staticmethod
    def get_gpu_usage() -> List[GPUUsage]:
        """
        Get current GPU (CUDA) usage.

        Returns:
            List of GPUUsage objects, one per GPU
        """
        if not TORCH_AVAILABLE or not torch.cuda.is_available():
            return []

        gpu_info = []

        try:
            for i in range(torch.cuda.device_count()):
                props = torch.cuda.get_device_properties(i)
                allocated = torch.cuda.memory_allocated(i)
                reserved = torch.cuda.memory_reserved(i)
                total = props.total_memory

                allocated_gb = allocated / (1024**3)
                total_gb = total / (1024**3)

                # Try to get temperature via nvidia-smi
                temperature = None
                try:
                    import subprocess
                    result = subprocess.run(
                        ['nvidia-smi', '--query-gpu=temperature.gpu', '--format=csv,noheader,nounits', f'--id={i}'],
                        capture_output=True, text=True, timeout=2
                    )
                    if result.returncode == 0:
                        temperature = int(result.stdout.strip())
                except:
                    pass

                gpu_info.append(GPUUsage(
                    device=i,
                    name=props.name,
                    allocated_gb=round(allocated_gb, 2),
                    reserved_gb=round(reserved / (1024**3), 2),
                    total_gb=round(total_gb, 2),
                    free_gb=round((total - allocated) / (1024**3), 2),
                    utilization_percent=round((allocated_gb / total_gb) * 100, 1) if total_gb > 0 else 0,
                    temperature=temperature,
                ))
        except Exception as e:
            logger.error(f"Error getting GPU usage: {e}")

        return gpu_info

    def take_snapshot(self, label: str = "") -> MemorySnapshot:
        """
        Take a snapshot of current memory state.

        Args:
            label: Optional label for the snapshot

        Returns:
            MemorySnapshot object
        """
        snapshot = MemorySnapshot(
            timestamp=datetime.now(),
            label=label or f"snapshot_{len(self._snapshots)}",
            ram=self.get_ram_usage(),
            gpus=self.get_gpu_usage(),
        )

        self._snapshots.append(snapshot)

        # Keep only last N snapshots
        if len(self._snapshots) > self._max_snapshots:
            self._snapshots = self._snapshots[-self._max_snapshots:]

        return snapshot

    def get_snapshots(self, limit: int = 10) -> List[MemorySnapshot]:
        """Get recent snapshots."""
        return self._snapshots[-limit:]

    def get_memory_trend(self, minutes: int = 5) -> Dict[str, Any]:
        """
        Get memory usage trend over the last N minutes.

        Args:
            minutes: Time window in minutes

        Returns:
            Dict with trend information
        """
        if not self._snapshots:
            return {'trend': 'unknown', 'change_percent': 0}

        cutoff = datetime.now().timestamp() - (minutes * 60)
        recent = [s for s in self._snapshots if s.timestamp.timestamp() > cutoff]

        if len(recent) < 2:
            return {'trend': 'insufficient_data', 'change_percent': 0}

        first_ram = recent[0].ram.percent
        last_ram = recent[-1].ram.percent
        change = last_ram - first_ram

        if change > 5:
            trend = 'increasing'
        elif change < -5:
            trend = 'decreasing'
        else:
            trend = 'stable'

        return {
            'trend': trend,
            'change_percent': round(change, 1),
            'first_percent': first_ram,
            'last_percent': last_ram,
            'samples': len(recent),
        }

    def get_summary(self) -> Dict[str, Any]:
        """
        Get a complete memory summary.

        Returns:
            Dict with RAM, GPU, and trend information
        """
        ram = self.get_ram_usage()
        gpus = self.get_gpu_usage()
        trend = self.get_memory_trend()

        # Determine overall status
        status = 'ok'
        warnings = []

        if ram.percent > 90:
            status = 'critical'
            warnings.append(f'RAM usage critical: {ram.percent}%')
        elif ram.percent > 80:
            status = 'warning'
            warnings.append(f'RAM usage high: {ram.percent}%')

        for gpu in gpus:
            if gpu.utilization_percent > 95:
                status = 'critical'
                warnings.append(f'GPU {gpu.device} VRAM critical: {gpu.utilization_percent}%')
            elif gpu.utilization_percent > 85:
                if status != 'critical':
                    status = 'warning'
                warnings.append(f'GPU {gpu.device} VRAM high: {gpu.utilization_percent}%')

        return {
            'status': status,
            'warnings': warnings,
            'ram': {
                'total_gb': ram.total_gb,
                'available_gb': ram.available_gb,
                'used_gb': ram.used_gb,
                'percent': ram.percent,
                'process_rss_gb': ram.process_rss_gb,
                'process_vms_gb': ram.process_vms_gb,
                'process_percent': ram.process_percent,
            },
            'gpus': [
                {
                    'device': gpu.device,
                    'name': gpu.name,
                    'allocated_gb': gpu.allocated_gb,
                    'reserved_gb': gpu.reserved_gb,
                    'total_gb': gpu.total_gb,
                    'free_gb': gpu.free_gb,
                    'utilization_percent': gpu.utilization_percent,
                    'temperature': gpu.temperature,
                }
                for gpu in gpus
            ],
            'trend': trend,
        }

    @staticmethod
    def print_summary():
        """Print a formatted memory summary to console."""
        monitor = WAMAMemoryMonitor()
        ram = monitor.get_ram_usage()
        gpus = monitor.get_gpu_usage()

        print("\n" + "=" * 60)
        print("🧠 MÉMOIRE RAM")
        print("=" * 60)
        print(f"Total:        {ram.total_gb:.2f} GB")
        print(f"Utilisée:     {ram.used_gb:.2f} GB ({ram.percent:.1f}%)")
        print(f"Disponible:   {ram.available_gb:.2f} GB")
        print(f"Process WAMA: {ram.process_rss_gb:.2f} GB (RSS)")
        print(f"Process VMS:  {ram.process_vms_gb:.2f} GB")

        if gpus:
            print("\n" + "=" * 60)
            print("🎮 MÉMOIRE GPU")
            print("=" * 60)
            for gpu in gpus:
                print(f"\nGPU {gpu.device}: {gpu.name}")
                print(f"  Allouée:     {gpu.allocated_gb:.2f} GB / {gpu.total_gb:.2f} GB")
                print(f"  Réservée:    {gpu.reserved_gb:.2f} GB")
                print(f"  Libre:       {gpu.free_gb:.2f} GB")
                print(f"  Utilisation: {gpu.utilization_percent:.1f}%")
                if gpu.temperature:
                    print(f"  Température: {gpu.temperature}°C")

        print("=" * 60 + "\n")
