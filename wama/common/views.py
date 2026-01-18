"""
WAMA Common - Views

Common views for system utilities.
"""

import json
import subprocess
import shutil
from django.http import JsonResponse
from django.views.decorators.http import require_GET

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


def get_gpu_stats():
    """
    Get GPU statistics using nvidia-smi.
    Returns None if no NVIDIA GPU is available.
    """
    try:
        # Check if nvidia-smi is available
        if not shutil.which('nvidia-smi'):
            return None

        result = subprocess.run(
            ['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu,name',
             '--format=csv,noheader,nounits'],
            capture_output=True,
            text=True,
            timeout=5
        )

        if result.returncode != 0:
            return None

        gpus = []
        for line in result.stdout.strip().split('\n'):
            if line:
                parts = [p.strip() for p in line.split(',')]
                if len(parts) >= 5:
                    gpus.append({
                        'utilization': int(parts[0]) if parts[0].isdigit() else 0,
                        'memory_used': int(parts[1]) if parts[1].isdigit() else 0,
                        'memory_total': int(parts[2]) if parts[2].isdigit() else 0,
                        'temperature': int(parts[3]) if parts[3].isdigit() else 0,
                        'name': parts[4]
                    })
        return gpus if gpus else None

    except Exception:
        return None


@require_GET
def system_stats(request):
    """
    Return current system resource usage.
    """
    stats = {
        'cpu': None,
        'ram': None,
        'gpu': None,
        'disk': None
    }

    if PSUTIL_AVAILABLE:
        # CPU usage (percentage)
        stats['cpu'] = {
            'percent': psutil.cpu_percent(interval=0.1),
            'count': psutil.cpu_count()
        }

        # RAM usage
        mem = psutil.virtual_memory()
        stats['ram'] = {
            'percent': mem.percent,
            'used_gb': round(mem.used / (1024 ** 3), 1),
            'total_gb': round(mem.total / (1024 ** 3), 1)
        }

        # Disk usage (root partition)
        try:
            disk = psutil.disk_usage('/')
            stats['disk'] = {
                'percent': disk.percent,
                'used_gb': round(disk.used / (1024 ** 3), 1),
                'total_gb': round(disk.total / (1024 ** 3), 1)
            }
        except Exception:
            pass

    # GPU stats
    gpu_stats = get_gpu_stats()
    if gpu_stats:
        stats['gpu'] = gpu_stats

    return JsonResponse(stats)
