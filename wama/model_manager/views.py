"""
Model Manager Views - Dashboard and API endpoints.
"""

import json
import logging
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_GET, require_POST
from django.contrib.auth.decorators import login_required, user_passes_test

from .services.model_registry import ModelRegistry, ModelType
from .services.memory_manager import MemoryManager
from wama.common.services.system_monitor import SystemMonitor

logger = logging.getLogger(__name__)


def is_admin_or_dev(user):
    """Check if user is admin or developer."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    if user.groups.filter(name__in=['admin', 'dev']).exists():
        return True
    return False


@login_required
@user_passes_test(is_admin_or_dev)
def index(request):
    """Main Model Manager dashboard - fast initial load, models loaded via AJAX."""
    # Get memory stats from centralized SystemMonitor
    stats = SystemMonitor.get_model_manager_stats()

    context = {
        'model_types': [t.value for t in ModelType],
        'gpu_info': stats['gpu_info'],
        'system_info': stats['system_info'],
        # Models will be loaded via AJAX
        'total_models': 0,
        'loaded_models': 0,
        'downloaded_models': 0,
    }

    return render(request, 'model_manager/index.html', context)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_models_list(request):
    """API: Get all models with their status."""
    registry = ModelRegistry()
    models = registry.discover_all_models()

    return JsonResponse({
        'success': True,
        'models': [
            {
                'id': m.id,
                'name': m.name,
                'type': m.model_type.value,
                'source': m.source.value,
                'description': m.description,
                'hf_id': m.hf_id,
                'vram_gb': m.vram_gb,
                'ram_gb': m.ram_gb,
                'is_loaded': m.is_loaded,
                'is_downloaded': m.is_downloaded,
            }
            for m in models.values()
        ],
        'count': len(models),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_memory_stats(request):
    """API: Get current memory statistics from centralized SystemMonitor."""
    stats = SystemMonitor.get_model_manager_stats()
    return JsonResponse({
        'success': True,
        'gpu': stats['gpu_info'],
        'system': stats['system_info'],
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_unload_model(request):
    """API: Unload a specific model."""
    try:
        data = json.loads(request.body)
        model_id = data.get('model_id')

        if not model_id:
            return JsonResponse({'success': False, 'error': 'model_id required'}, status=400)

        success = MemoryManager.unload_model(model_id)

        # Get updated memory stats from centralized monitor
        stats = SystemMonitor.get_model_manager_stats()

        return JsonResponse({
            'success': success,
            'model_id': model_id,
            'message': f"Model {model_id} unloaded" if success else f"Failed to unload {model_id}",
            'memory': stats['gpu_info'],
        })
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_unload_model: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_clear_gpu(request):
    """API: Clear all GPU memory."""
    success = MemoryManager.clear_gpu_memory()

    # Get updated stats from centralized monitor
    stats = SystemMonitor.get_model_manager_stats()

    return JsonResponse({
        'success': success,
        'message': 'GPU memory cleared' if success else 'Failed to clear GPU memory',
        'memory': stats['gpu_info'],
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_refresh_models(request):
    """API: Refresh the model list."""
    registry = ModelRegistry()
    registry._models.clear()
    models = registry.discover_all_models()

    return JsonResponse({
        'success': True,
        'count': len(models),
        'message': f'Found {len(models)} models',
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_debug_stats(request):
    """API: Debug endpoint showing raw system stats."""
    import psutil
    import os
    import sys
    from wama.common.services.system_monitor import IS_WSL

    # Raw psutil values (WSL/Linux VM values)
    mem = psutil.virtual_memory()

    # Check all disk partitions visible to psutil
    disk_info = []
    try:
        for partition in psutil.disk_partitions():
            try:
                usage = psutil.disk_usage(partition.mountpoint)
                disk_info.append({
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'fstype': partition.fstype,
                    'total_gb': round(usage.total / (1024**3), 1),
                    'used_gb': round(usage.used / (1024**3), 1),
                    'free_gb': round(usage.free / (1024**3), 1),
                })
            except (PermissionError, OSError):
                disk_info.append({
                    'device': partition.device,
                    'mountpoint': partition.mountpoint,
                    'error': 'Cannot access',
                })
    except Exception as e:
        disk_info = [{'error': str(e)}]

    # All stats from SystemMonitor (will use Windows host stats if in WSL)
    all_stats = SystemMonitor.get_all_stats()

    return JsonResponse({
        'environment': {
            'python_executable': sys.executable,
            'cwd': os.getcwd(),
            'platform': sys.platform,
            'pid': os.getpid(),
            'is_wsl': IS_WSL,
        },
        'psutil_raw_wsl': {
            'note': 'These are WSL VM values, not Windows host values',
            'total_bytes': mem.total,
            'total_gb': round(mem.total / (1024**3), 2),
            'available_bytes': mem.available,
            'available_gb': round(mem.available / (1024**3), 2),
            'used_bytes': mem.used,
            'used_gb': round(mem.used / (1024**3), 2),
            'percent': mem.percent,
        },
        'wsl_disks': disk_info,
        'system_monitor': all_stats,
    })
