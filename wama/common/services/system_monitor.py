"""
System Monitor - Centralized system resource monitoring service.

This service provides unified access to system resources (CPU, RAM, GPU, Disk)
for use across all WAMA applications (footer stats, Model Manager, etc.).

Supports WSL detection and Windows host stats retrieval.
"""

import logging
import os
import shutil
import subprocess
import sys
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Try to import psutil
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not available - system monitoring will be limited")

# Detect if running in WSL
IS_WSL = False
try:
    if sys.platform == 'linux':
        with open('/proc/version', 'r') as f:
            if 'microsoft' in f.read().lower():
                IS_WSL = True
                logger.info("WSL environment detected - will fetch Windows host stats")
except Exception:
    pass


class SystemMonitor:
    """
    Centralized system resource monitor.

    Provides consistent resource information across all WAMA components.
    Automatically detects WSL and fetches Windows host stats when appropriate.
    """

    _instance = None

    def __new__(cls):
        """Singleton pattern."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def _get_windows_ram_from_wsl() -> Optional[Dict]:
        """
        Get Windows host RAM info when running in WSL.
        Uses PowerShell to query Windows memory.
        """
        if not IS_WSL:
            return None

        try:
            # Use PowerShell to get Windows memory info
            cmd = [
                'powershell.exe', '-NoProfile', '-Command',
                '(Get-CimInstance Win32_OperatingSystem | Select-Object TotalVisibleMemorySize, FreePhysicalMemory | ConvertTo-Json)'
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode == 0 and result.stdout.strip():
                import json
                data = json.loads(result.stdout.strip())
                # Values are in KB
                total_kb = data.get('TotalVisibleMemorySize', 0)
                free_kb = data.get('FreePhysicalMemory', 0)
                total_gb = round(total_kb / (1024 * 1024), 2)
                free_gb = round(free_kb / (1024 * 1024), 2)
                used_gb = round(total_gb - free_gb, 2)
                percent = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0

                return {
                    'total_gb': total_gb,
                    'used_gb': used_gb,
                    'available_gb': free_gb,
                    'free_gb': free_gb,
                    'percent': percent,
                    'source': 'windows_host',
                }
        except Exception as e:
            logger.debug(f"Could not get Windows RAM from WSL: {e}")

        return None

    @staticmethod
    def _get_windows_disk_from_wsl(drive: str = 'D') -> Optional[Dict]:
        """
        Get Windows host disk info when running in WSL.
        Uses PowerShell to query Windows disk.
        """
        if not IS_WSL:
            return None

        try:
            cmd = [
                'powershell.exe', '-NoProfile', '-Command',
                f'(Get-PSDrive {drive} | Select-Object Used, Free | ConvertTo-Json)'
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode == 0 and result.stdout.strip():
                import json
                data = json.loads(result.stdout.strip())
                used_bytes = data.get('Used', 0)
                free_bytes = data.get('Free', 0)
                total_bytes = used_bytes + free_bytes

                return {
                    'total_gb': round(total_bytes / (1024**3), 1),
                    'used_gb': round(used_bytes / (1024**3), 1),
                    'free_gb': round(free_bytes / (1024**3), 1),
                    'percent': round((used_bytes / total_bytes) * 100, 1) if total_bytes > 0 else 0,
                    'source': 'windows_host',
                    'drive': f'{drive}:',
                }
        except Exception as e:
            logger.debug(f"Could not get Windows disk from WSL: {e}")

        return None

    @staticmethod
    def _get_windows_cpu_from_wsl() -> Optional[Dict]:
        """
        Get Windows host CPU info when running in WSL.
        """
        if not IS_WSL:
            return None

        try:
            # Use wmic for faster response
            cmd = ['wmic.exe', 'cpu', 'get', 'loadpercentage', '/value']
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=3,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode == 0:
                for line in result.stdout.split('\n'):
                    if 'LoadPercentage' in line:
                        percent = int(line.split('=')[1].strip())
                        # Get CPU count from psutil (works in WSL)
                        cpu_count = psutil.cpu_count() if PSUTIL_AVAILABLE else None
                        return {
                            'percent': percent,
                            'count': cpu_count,
                            'freq_mhz': None,
                            'source': 'windows_host',
                        }
        except Exception as e:
            logger.debug(f"Could not get Windows CPU from WSL: {e}")

        return None

    @classmethod
    def get_cpu_info(cls) -> Optional[Dict]:
        """
        Get CPU usage information.
        In WSL, fetches Windows host CPU stats.

        Returns:
            Dict with 'percent', 'count', 'freq_mhz' or None if unavailable
        """
        # Try Windows host stats first if in WSL
        if IS_WSL:
            windows_cpu = cls._get_windows_cpu_from_wsl()
            if windows_cpu:
                return windows_cpu

        if not PSUTIL_AVAILABLE:
            return None

        try:
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()

            # Try to get CPU frequency
            freq_mhz = None
            try:
                freq = psutil.cpu_freq()
                if freq:
                    freq_mhz = round(freq.current, 0)
            except Exception:
                pass

            return {
                'percent': round(cpu_percent, 1),
                'count': cpu_count,
                'freq_mhz': freq_mhz,
            }
        except Exception as e:
            logger.error(f"Error getting CPU info: {e}")
            return None

    @classmethod
    def get_ram_info(cls) -> Optional[Dict]:
        """
        Get system RAM information.
        In WSL, fetches Windows host RAM stats.

        Returns:
            Dict with 'total_gb', 'used_gb', 'available_gb', 'percent' or None
        """
        # Try Windows host stats first if in WSL
        if IS_WSL:
            windows_ram = cls._get_windows_ram_from_wsl()
            if windows_ram:
                return windows_ram

        if not PSUTIL_AVAILABLE:
            return None

        try:
            mem = psutil.virtual_memory()

            return {
                'total_gb': round(mem.total / (1024 ** 3), 2),
                'used_gb': round(mem.used / (1024 ** 3), 2),
                'available_gb': round(mem.available / (1024 ** 3), 2),
                'free_gb': round(mem.available / (1024 ** 3), 2),
                'percent': round(mem.percent, 1),
            }
        except Exception as e:
            logger.error(f"Error getting RAM info: {e}")
            return None

    @staticmethod
    def get_gpu_info() -> Optional[List[Dict]]:
        """
        Get GPU information using nvidia-smi.

        Returns:
            List of GPU dicts with 'name', 'utilization', 'memory_used_mb',
            'memory_total_mb', 'memory_used_gb', 'memory_total_gb', 'memory_percent',
            'temperature' or None if no NVIDIA GPU
        """
        try:
            # Check if nvidia-smi is available
            if not shutil.which('nvidia-smi'):
                return None

            result = subprocess.run(
                ['nvidia-smi',
                 '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name',
                 '--format=csv,noheader,nounits'],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, 'CREATE_NO_WINDOW') else 0
            )

            if result.returncode != 0:
                return None

            gpus = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = [p.strip() for p in line.split(',')]
                    if len(parts) >= 5:
                        mem_used_mb = int(parts[1]) if parts[1].isdigit() else 0
                        mem_total_mb = int(parts[2]) if parts[2].isdigit() else 0

                        gpus.append({
                            'name': parts[4],
                            'utilization': int(parts[0]) if parts[0].isdigit() else 0,
                            'temperature': int(parts[3]) if parts[3].isdigit() else 0,
                            # Memory in MB (for footer compatibility)
                            'memory_used': mem_used_mb,
                            'memory_total': mem_total_mb,
                            # Memory in GB (for Model Manager)
                            'memory_used_gb': round(mem_used_mb / 1024, 2),
                            'memory_total_gb': round(mem_total_mb / 1024, 2),
                            'memory_free_gb': round((mem_total_mb - mem_used_mb) / 1024, 2),
                            'memory_percent': round((mem_used_mb / mem_total_mb) * 100, 1) if mem_total_mb > 0 else 0,
                        })

            return gpus if gpus else None

        except subprocess.TimeoutExpired:
            logger.warning("nvidia-smi timed out")
            return None
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.error(f"Error getting GPU info: {e}")
            return None

    @staticmethod
    def get_gpu_info_torch() -> Optional[Dict]:
        """
        Get GPU memory info using PyTorch (more accurate for VRAM used by Python).

        Returns:
            Dict with GPU memory stats or None
        """
        try:
            import torch
            if not torch.cuda.is_available():
                return None

            props = torch.cuda.get_device_properties(0)
            allocated = torch.cuda.memory_allocated(0)
            reserved = torch.cuda.memory_reserved(0)
            total = props.total_memory

            return {
                'device_name': props.name,
                'total_gb': round(total / (1024**3), 2),
                'allocated_gb': round(allocated / (1024**3), 2),
                'reserved_gb': round(reserved / (1024**3), 2),
                'free_gb': round((total - allocated) / (1024**3), 2),
                'utilization_percent': round((allocated / total) * 100, 1) if total > 0 else 0,
            }
        except ImportError:
            return None
        except Exception as e:
            logger.error(f"Error getting PyTorch GPU info: {e}")
            return None

    @classmethod
    def get_disk_info(cls, path: str = '/', drive: str = 'D') -> Optional[Dict]:
        """
        Get disk usage information.
        In WSL, fetches Windows host disk stats for the specified drive.

        Args:
            path: Path to check for psutil (default: root)
            drive: Windows drive letter for WSL (default: D)

        Returns:
            Dict with 'total_gb', 'used_gb', 'free_gb', 'percent' or None
        """
        # Try Windows host stats first if in WSL
        if IS_WSL:
            windows_disk = cls._get_windows_disk_from_wsl(drive)
            if windows_disk:
                return windows_disk

        if not PSUTIL_AVAILABLE:
            return None

        try:
            # On Windows, use C: if / doesn't work
            try:
                disk = psutil.disk_usage(path)
            except OSError:
                disk = psutil.disk_usage('C:/')

            return {
                'total_gb': round(disk.total / (1024 ** 3), 1),
                'used_gb': round(disk.used / (1024 ** 3), 1),
                'free_gb': round(disk.free / (1024 ** 3), 1),
                'percent': round(disk.percent, 1),
            }
        except Exception as e:
            logger.error(f"Error getting disk info: {e}")
            return None

    @classmethod
    def get_all_stats(cls) -> Dict:
        """
        Get all system statistics.

        Returns:
            Dict with 'cpu', 'ram', 'gpu', 'disk' sections
        """
        return {
            'cpu': cls.get_cpu_info(),
            'ram': cls.get_ram_info(),
            'gpu': cls.get_gpu_info(),
            'gpu_torch': cls.get_gpu_info_torch(),
            'disk': cls.get_disk_info(),
        }

    @classmethod
    def get_footer_stats(cls) -> Dict:
        """
        Get stats formatted for footer display.

        Returns:
            Dict compatible with system-stats.js expectations
        """
        stats = {
            'cpu': None,
            'ram': None,
            'gpu': None,
            'disk': None,
        }

        cpu = cls.get_cpu_info()
        if cpu:
            stats['cpu'] = {
                'percent': cpu['percent'],
                'count': cpu['count'],
            }

        ram = cls.get_ram_info()
        if ram:
            stats['ram'] = {
                'percent': ram['percent'],
                'used_gb': ram['used_gb'],
                'total_gb': ram['total_gb'],
            }

        gpu = cls.get_gpu_info()
        if gpu:
            stats['gpu'] = gpu  # List of GPUs

        disk = cls.get_disk_info()
        if disk:
            stats['disk'] = {
                'percent': disk['percent'],
                'used_gb': disk['used_gb'],
                'total_gb': disk['total_gb'],
            }

        return stats

    @classmethod
    def get_model_manager_stats(cls) -> Dict:
        """
        Get stats formatted for Model Manager display.

        Returns:
            Dict with 'gpu_info' and 'system_info' for template context
        """
        # For GPU, prefer nvidia-smi (shows actual VRAM usage including other apps)
        gpu_nvidia = cls.get_gpu_info()
        gpu_torch = cls.get_gpu_info_torch()

        gpu_info = None
        if gpu_nvidia and len(gpu_nvidia) > 0:
            g = gpu_nvidia[0]
            gpu_info = {
                'device_name': g['name'],
                'total_gb': g['memory_total_gb'],
                'allocated_gb': g['memory_used_gb'],
                'free_gb': g['memory_free_gb'],
                'utilization_percent': g['memory_percent'],
                'gpu_utilization': g['utilization'],
                'temperature': g['temperature'],
            }
        elif gpu_torch:
            gpu_info = gpu_torch

        ram = cls.get_ram_info()
        system_info = {
            'total_gb': ram['total_gb'] if ram else 0,
            'used_gb': ram['used_gb'] if ram else 0,
            'available_gb': ram['available_gb'] if ram else 0,
            'percent': ram['percent'] if ram else 0,
        } if ram else {}

        return {
            'gpu_info': gpu_info,
            'system_info': system_info,
        }
