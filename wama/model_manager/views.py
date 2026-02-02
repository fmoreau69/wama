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
from .services.format_converter import FormatConverter
from .services.memory_monitor import WAMAMemoryMonitor
from .services.memory_tracker import WAMAMemoryTracker
from .services.memory_cleaner import WAMAMemoryCleaner, get_memory_cleaner
from wama.common.services.system_monitor import SystemMonitor
from wama.common.utils.format_policy import get_policy_summary

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
                # Format policy fields
                'format': m.format,
                'preferred_format': m.preferred_format,
                'can_convert_to': m.can_convert_to,
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


# =============================================================================
# Format Conversion API Endpoints
# =============================================================================

@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_format_stats(request):
    """API: Get format statistics and policy compliance."""
    converter = FormatConverter()
    stats = converter.get_format_stats()

    return JsonResponse({
        'success': True,
        'formats': stats['formats'],
        'compliance': stats['compliance'],
        'by_category': stats['by_category'],
        'total_models': stats['total_models'],
        'policy': get_policy_summary(),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_conversion_suggestions(request):
    """API: Get suggested format conversions based on policy."""
    converter = FormatConverter()
    suggestions = converter.scan_and_suggest()

    return JsonResponse({
        'success': True,
        'suggestions': [
            {
                'model_id': s.model_id,
                'model_path': s.model_path,
                'current_format': s.current_format,
                'suggested_format': s.suggested_format,
                'category': s.category,
                'reason': s.reason,
                'priority': s.priority,
            }
            for s in suggestions
        ],
        'count': len(suggestions),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_convert_model(request):
    """API: Convert a model to a different format."""
    try:
        data = json.loads(request.body)
        model_path = data.get('model_path')
        target_format = data.get('target_format')
        model_type = data.get('model_type')
        keep_original = data.get('keep_original', True)

        if not model_path:
            return JsonResponse({'success': False, 'error': 'model_path required'}, status=400)
        if not target_format:
            return JsonResponse({'success': False, 'error': 'target_format required'}, status=400)

        converter = FormatConverter()
        result = converter.convert_model(
            model_path,
            target_format,
            model_type=model_type,
            keep_original=keep_original,
        )

        return JsonResponse({
            'success': result.success,
            'message': result.message,
            'source_path': result.source_path,
            'target_path': result.target_path,
            'source_format': result.source_format,
            'target_format': result.target_format,
            'size_before_mb': result.size_before_mb,
            'size_after_mb': result.size_after_mb,
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_convert_model: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_batch_convert(request):
    """API: Batch convert multiple models."""
    try:
        data = json.loads(request.body)
        model_paths = data.get('model_paths', [])
        target_format = data.get('target_format')
        model_type = data.get('model_type')
        keep_originals = data.get('keep_originals', True)

        if not model_paths:
            return JsonResponse({'success': False, 'error': 'model_paths required'}, status=400)
        if not target_format:
            return JsonResponse({'success': False, 'error': 'target_format required'}, status=400)

        converter = FormatConverter()
        results = converter.batch_convert(
            model_paths,
            target_format,
            model_type=model_type,
            keep_originals=keep_originals,
        )

        # Summarize results
        success_count = sum(1 for r in results.values() if r.success)
        failed_count = len(results) - success_count

        return JsonResponse({
            'success': True,
            'total': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'results': {
                path: {
                    'success': r.success,
                    'message': r.message,
                    'target_path': r.target_path,
                }
                for path, r in results.items()
            },
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_batch_convert: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_conversion_options(request):
    """API: Get available conversion options for a model."""
    model_path = request.GET.get('model_path')

    if not model_path:
        return JsonResponse({'success': False, 'error': 'model_path required'}, status=400)

    converter = FormatConverter()
    options = converter.get_conversion_options(model_path)

    from wama.common.utils.safetensors_utils import get_model_format
    current_format = get_model_format(model_path)

    return JsonResponse({
        'success': True,
        'model_path': model_path,
        'current_format': current_format,
        'available_conversions': options,
    })


# =============================================================================
# Memory Management API Endpoints
# =============================================================================

@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_memory_detailed(request):
    """API: Get detailed memory usage (RAM + GPU + Process)."""
    monitor = WAMAMemoryMonitor()
    summary = monitor.get_summary()

    return JsonResponse({
        'success': True,
        **summary,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_tracked_models(request):
    """API: Get all tracked models in memory."""
    tracker = WAMAMemoryTracker()
    summary = tracker.get_summary()

    return JsonResponse({
        'success': True,
        **summary,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_idle_models(request):
    """API: Get idle models that could be unloaded."""
    idle_threshold = int(request.GET.get('threshold', 300))  # Default 5 min

    tracker = WAMAMemoryTracker()
    idle_models = tracker.get_idle_models(idle_threshold)

    return JsonResponse({
        'success': True,
        'threshold_seconds': idle_threshold,
        'idle_models': [
            {
                'model_id': m.model_id,
                'idle_time_seconds': m.idle_time_seconds,
                'idle_time_minutes': round(m.idle_time_minutes, 1),
                'size_mb': m.size_mb,
                'use_count': m.use_count,
                'category': m.category,
                'source': m.source,
            }
            for m in idle_models
        ],
        'count': len(idle_models),
        'total_size_mb': sum(m.size_mb for m in idle_models),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_large_objects(request):
    """API: Get large objects in memory."""
    min_size_mb = float(request.GET.get('min_size_mb', 10))

    tracker = WAMAMemoryTracker()
    large_objects = tracker.find_large_objects(min_size_mb)

    return JsonResponse({
        'success': True,
        'min_size_mb': min_size_mb,
        'large_objects': [
            {
                'type': obj.obj_type,
                'size_mb': round(obj.size_mb, 2),
                'model_id': obj.model_id,
                'ref_count': obj.ref_count,
            }
            for obj in large_objects[:20]  # Limit to 20
        ],
        'count': len(large_objects),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_cleanup_idle(request):
    """API: Clean up idle models."""
    cleaner = get_memory_cleaner()
    result = cleaner.cleanup_idle_models()

    return JsonResponse({
        'success': result.success,
        'models_unloaded': result.models_unloaded,
        'memory_freed_mb': result.memory_freed_mb,
        'gc_collected': result.gc_collected,
        'ram_before_percent': result.ram_before_percent,
        'ram_after_percent': result.ram_after_percent,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_aggressive_cleanup(request):
    """API: Aggressive cleanup of all memory."""
    cleaner = get_memory_cleaner()
    result = cleaner.aggressive_cleanup()

    return JsonResponse({
        'success': result.success,
        'models_unloaded': result.models_unloaded,
        'memory_freed_mb': result.memory_freed_mb,
        'gc_collected': result.gc_collected,
        'gpu_cache_cleared': result.gpu_cache_cleared,
        'ram_before_percent': result.ram_before_percent,
        'ram_after_percent': result.ram_after_percent,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_clear_gpu_cache(request):
    """API: Clear GPU VRAM cache only."""
    cleaner = get_memory_cleaner()
    success = cleaner.clear_gpu_cache()

    monitor = WAMAMemoryMonitor()
    gpus = monitor.get_gpu_usage()

    return JsonResponse({
        'success': success,
        'message': 'GPU cache cleared' if success else 'Failed to clear GPU cache',
        'gpus': [
            {
                'device': gpu.device,
                'allocated_gb': gpu.allocated_gb,
                'free_gb': gpu.free_gb,
                'utilization_percent': gpu.utilization_percent,
            }
            for gpu in gpus
        ],
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_force_gc(request):
    """API: Force Python garbage collection."""
    cleaner = get_memory_cleaner()
    collected = cleaner.force_gc()

    monitor = WAMAMemoryMonitor()
    ram = monitor.get_ram_usage()

    return JsonResponse({
        'success': True,
        'gc_collected': collected,
        'ram_percent': ram.percent,
        'ram_available_gb': ram.available_gb,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_unload_model_by_id(request):
    """API: Unload a specific tracked model."""
    try:
        data = json.loads(request.body)
        model_id = data.get('model_id')

        if not model_id:
            return JsonResponse({'success': False, 'error': 'model_id required'}, status=400)

        cleaner = get_memory_cleaner()
        success = cleaner.unload_specific_model(model_id)

        return JsonResponse({
            'success': success,
            'model_id': model_id,
            'message': f'Model {model_id} unloaded' if success else f'Failed to unload {model_id}',
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_unload_model_by_id: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_cleaner_status(request):
    """API: Get memory cleaner status and history."""
    cleaner = get_memory_cleaner()
    status = cleaner.get_status()
    history = cleaner.get_history(limit=10)

    return JsonResponse({
        'success': True,
        'status': status,
        'history': history,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_cleaner_configure(request):
    """API: Configure the memory cleaner."""
    try:
        data = json.loads(request.body)

        cleaner = get_memory_cleaner()
        cleaner.configure(
            check_interval=data.get('check_interval'),
            idle_threshold=data.get('idle_threshold'),
            ram_warning_threshold=data.get('ram_warning_threshold'),
            ram_critical_threshold=data.get('ram_critical_threshold'),
        )

        return JsonResponse({
            'success': True,
            'status': cleaner.get_status(),
        })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_cleaner_configure: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_cleaner_start(request):
    """API: Start the automatic memory cleaner."""
    cleaner = get_memory_cleaner()
    cleaner.start()

    return JsonResponse({
        'success': True,
        'message': 'Memory cleaner started',
        'status': cleaner.get_status(),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_cleaner_stop(request):
    """API: Stop the automatic memory cleaner."""
    cleaner = get_memory_cleaner()
    cleaner.stop()

    return JsonResponse({
        'success': True,
        'message': 'Memory cleaner stopped',
        'status': cleaner.get_status(),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_memory_snapshot(request):
    """API: Take a memory snapshot for tracking."""
    label = request.GET.get('label', '')

    monitor = WAMAMemoryMonitor()
    snapshot = monitor.take_snapshot(label)

    return JsonResponse({
        'success': True,
        'snapshot': snapshot.to_dict(),
    })


# =============================================================================
# Remote Backup API Endpoints
# =============================================================================

@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_backup_status(request):
    """API: Get remote backup service status."""
    from .services.remote_backup import get_backup_service

    service = get_backup_service()
    status = service.get_status()

    return JsonResponse({
        'success': True,
        **status,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_backup_list(request):
    """API: List existing backups on remote storage."""
    from .services.remote_backup import get_backup_service

    format_type = request.GET.get('format')
    model_type = request.GET.get('type')

    service = get_backup_service()

    if not service.is_available():
        return JsonResponse({
            'success': False,
            'error': 'Remote backup path not accessible',
            'remote_path': str(service.remote_path),
        })

    backups = service.list_backups(format_type, model_type)

    return JsonResponse({
        'success': True,
        'backups': backups,
        'count': len(backups),
        'total_size_mb': sum(b['size_mb'] for b in backups),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_backup_model(request):
    """API: Backup a model to remote storage."""
    from .services.remote_backup import get_backup_service

    try:
        data = json.loads(request.body)
        source_path = data.get('source_path')
        model_type = data.get('model_type', 'unknown')
        model_name = data.get('model_name')
        format_type = data.get('format_type', 'safetensors')
        overwrite = data.get('overwrite', False)

        if not source_path:
            return JsonResponse({'success': False, 'error': 'source_path required'}, status=400)
        if not model_name:
            return JsonResponse({'success': False, 'error': 'model_name required'}, status=400)

        service = get_backup_service()

        if not service.is_available():
            return JsonResponse({
                'success': False,
                'error': 'Remote backup path not accessible',
            })

        import os
        if os.path.isdir(source_path):
            results = service.backup_directory(
                source_path, model_type, model_name, format_type,
                overwrite=overwrite
            )
            success_count = sum(1 for r in results if r.success)
            total_size = sum(r.size_mb for r in results if r.success)

            return JsonResponse({
                'success': success_count > 0,
                'files_backed_up': success_count,
                'total_files': len(results),
                'total_size_mb': total_size,
                'results': [
                    {
                        'source': r.source_path,
                        'dest': r.dest_path,
                        'success': r.success,
                        'size_mb': r.size_mb,
                        'error': r.error,
                    }
                    for r in results
                ],
            })
        else:
            result = service.backup_file(
                source_path, model_type, model_name, format_type,
                overwrite=overwrite
            )

            return JsonResponse({
                'success': result.success,
                'source_path': result.source_path,
                'dest_path': result.dest_path,
                'size_mb': result.size_mb,
                'duration_seconds': result.duration_seconds,
                'error': result.error,
            })

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_backup_model: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_convert_and_backup(request):
    """API: Convert a model and backup to remote storage."""
    from .services.remote_backup import get_backup_service

    try:
        data = json.loads(request.body)
        model_path = data.get('model_path')
        target_format = data.get('target_format', 'safetensors')
        model_type = data.get('model_type', 'unknown')
        model_name = data.get('model_name')
        backup_after = data.get('backup_after', True)

        if not model_path:
            return JsonResponse({'success': False, 'error': 'model_path required'}, status=400)

        # Extract model name from path if not provided
        if not model_name:
            from pathlib import Path
            model_name = Path(model_path).stem

        # Step 1: Convert the model
        converter = FormatConverter()
        conversion_result = converter.convert_model(model_path, target_format)

        if not conversion_result.success:
            return JsonResponse({
                'success': False,
                'error': f'Conversion failed: {conversion_result.message}',
                'conversion': {
                    'success': False,
                    'message': conversion_result.message,
                },
            })

        response = {
            'success': True,
            'conversion': {
                'success': True,
                'source_path': conversion_result.source_path,
                'target_path': conversion_result.target_path,
                'source_format': conversion_result.source_format,
                'target_format': conversion_result.target_format,
                'size_before_mb': conversion_result.size_before_mb,
                'size_after_mb': conversion_result.size_after_mb,
            },
        }

        # Step 2: Backup if requested
        if backup_after:
            backup_service = get_backup_service()

            if backup_service.is_available():
                backup_result = backup_service.backup_file(
                    conversion_result.target_path,
                    model_type,
                    model_name,
                    target_format,
                    overwrite=True
                )

                response['backup'] = {
                    'success': backup_result.success,
                    'dest_path': backup_result.dest_path,
                    'size_mb': backup_result.size_mb,
                    'error': backup_result.error,
                }
            else:
                response['backup'] = {
                    'success': False,
                    'error': 'Remote backup path not accessible',
                }

        return JsonResponse(response)

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_convert_and_backup: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# =============================================================================
# Database-Backed Model Catalog API Endpoints
# =============================================================================

@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_models_db(request):
    """
    API: Get all models from database (fast).
    This replaces api_models_list for production use.
    """
    from .models import AIModel

    # Optional filters
    source = request.GET.get('source')
    model_type = request.GET.get('type')
    downloaded_only = request.GET.get('downloaded') == 'true'
    format_filter = request.GET.get('format')

    queryset = AIModel.objects.filter(is_available=True)

    if source:
        queryset = queryset.filter(source=source)
    if model_type:
        queryset = queryset.filter(model_type=model_type)
    if downloaded_only:
        queryset = queryset.filter(is_downloaded=True)
    if format_filter:
        queryset = queryset.filter(format=format_filter)

    models = [model.to_dict() for model in queryset]

    # Log a sample for debugging
    if models:
        sample = models[0]
        logger.info(
            f"[api_models_db] Sample model: {sample.get('name')}, "
            f"format={sample.get('format')!r}, "
            f"preferred_format={sample.get('preferred_format')!r}, "
            f"vram_gb={sample.get('vram_gb')}"
        )

    return JsonResponse({
        'success': True,
        'models': models,
        'count': len(models),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_sync_models(request):
    """
    API: Trigger a manual model sync.
    """
    from .services.model_sync import get_sync_service

    try:
        data = json.loads(request.body) if request.body else {}
        clean = data.get('clean', False)

        sync_service = get_sync_service()
        result = sync_service.full_sync(remove_missing=clean)

        return JsonResponse({
            'success': result.success,
            'added': result.added,
            'updated': result.updated,
            'removed': result.removed,
            'errors': result.errors[:10] if result.errors else [],
        })

    except Exception as e:
        logger.error(f"Error in api_sync_models: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_catalog_stats(request):
    """
    API: Get catalog statistics.
    """
    from .services.model_sync import get_sync_service

    sync_service = get_sync_service()
    stats = sync_service.get_stats()

    return JsonResponse({
        'success': True,
        **stats,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_watcher_status(request):
    """
    API: Get file watcher status.
    """
    from .services.file_watcher import get_file_watcher, is_watchdog_available

    if not is_watchdog_available():
        return JsonResponse({
            'success': True,
            'available': False,
            'running': False,
            'message': 'watchdog not installed'
        })

    watcher = get_file_watcher()
    status = watcher.get_status()

    return JsonResponse({
        'success': True,
        **status,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_watcher_control(request):
    """
    API: Start/stop the file watcher.
    """
    from .services.file_watcher import get_file_watcher, is_watchdog_available

    if not is_watchdog_available():
        return JsonResponse({
            'success': False,
            'error': 'watchdog not installed'
        }, status=400)

    try:
        data = json.loads(request.body)
        action = data.get('action')

        watcher = get_file_watcher()

        if action == 'start':
            success = watcher.start()
            return JsonResponse({
                'success': success,
                'running': watcher.is_running(),
            })
        elif action == 'stop':
            watcher.stop()
            return JsonResponse({
                'success': True,
                'running': watcher.is_running(),
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Invalid action. Use "start" or "stop".'
            }, status=400)

    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in api_watcher_control: {e}")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_sync_logs(request):
    """
    API: Get recent sync logs.
    """
    from .models import ModelSyncLog

    limit = int(request.GET.get('limit', 20))
    logs = ModelSyncLog.objects.order_by('-started_at')[:limit]

    return JsonResponse({
        'success': True,
        'logs': [
            {
                'id': log.id,
                'sync_type': log.sync_type,
                'status': log.status,
                'models_added': log.models_added,
                'models_updated': log.models_updated,
                'models_removed': log.models_removed,
                'started_at': log.started_at.isoformat() if log.started_at else None,
                'completed_at': log.completed_at.isoformat() if log.completed_at else None,
                'duration_seconds': log.duration_seconds,
                'error_message': log.error_message,
            }
            for log in logs
        ],
        'count': len(logs),
    })


# =============================================================================
# Disk Space Check API Endpoints
# =============================================================================

@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_disk_space(request):
    """
    API: Get current disk space information.
    Returns disk space for the model storage drives.
    """
    disk_info = SystemMonitor.get_disk_info()

    if not disk_info:
        return JsonResponse({
            'success': False,
            'error': 'Could not get disk information',
        })

    return JsonResponse({
        'success': True,
        'disk': disk_info,
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_diagnose_models(request):
    """
    API: Diagnostic endpoint to check what's happening with model data.
    Shows both registry discovery and database state.
    """
    from .models import AIModel

    result = {
        'success': True,
        'diagnosis': {},
    }

    # 1. Check what format_policy returns
    try:
        from wama.common.utils.format_policy import get_preferred_format, get_category_for_model_type
        result['diagnosis']['format_policy'] = {
            'diffusion_category': get_category_for_model_type('diffusion'),
            'diffusion_preferred': get_preferred_format('diffusion'),
            'vision_category': get_category_for_model_type('vision'),
            'vision_preferred': get_preferred_format('vision'),
            'speech_preferred': get_preferred_format('speech'),
        }
    except Exception as e:
        result['diagnosis']['format_policy_error'] = str(e)

    # 2. Check registry discovery (fresh)
    try:
        registry = ModelRegistry()
        registry._models.clear()
        discovered = registry.discover_all_models()

        sample_models = []
        for key, model in list(discovered.items())[:5]:
            sample_models.append({
                'key': key,
                'name': model.name,
                'format': model.format,
                'preferred_format': model.preferred_format,
                'vram_gb': model.vram_gb,
                'is_downloaded': model.is_downloaded,
            })
        result['diagnosis']['registry'] = {
            'total_discovered': len(discovered),
            'sample_models': sample_models,
        }
    except Exception as e:
        result['diagnosis']['registry_error'] = str(e)
        import traceback
        result['diagnosis']['registry_traceback'] = traceback.format_exc()

    # 3. Check database state
    try:
        db_models = AIModel.objects.filter(is_available=True)[:5]
        db_sample = []
        for model in db_models:
            db_sample.append({
                'key': model.model_key,
                'name': model.name,
                'format': model.format,
                'preferred_format': model.preferred_format,
                'vram_gb': model.vram_gb,
                'is_downloaded': model.is_downloaded,
            })
        result['diagnosis']['database'] = {
            'total_in_db': AIModel.objects.filter(is_available=True).count(),
            'sample_models': db_sample,
            'formats_in_db': list(AIModel.objects.values_list('format', flat=True).distinct()),
            'preferred_formats_in_db': list(AIModel.objects.values_list('preferred_format', flat=True).distinct()),
        }
    except Exception as e:
        result['diagnosis']['database_error'] = str(e)

    # 4. Check if a sync would fix the data
    result['diagnosis']['recommendation'] = (
        "If format/preferred_format are empty in database but correct in registry, "
        "a sync is needed. Call POST /model-manager/api/sync/ to sync."
    )

    return JsonResponse(result)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_check_disk_space(request):
    """
    API: Check if there's enough disk space for a model download.

    Query params:
        required_gb: Required space in GB (float)
        safety_margin: Additional safety margin in GB (default: 5)

    Returns:
        has_space: Boolean indicating if enough space is available
        required_gb: Space required
        available_gb: Space available
        safety_margin_gb: Safety margin used
        message: Human-readable status message
    """
    try:
        required_gb = float(request.GET.get('required_gb', 0))
        safety_margin_gb = float(request.GET.get('safety_margin', 5))
    except ValueError:
        return JsonResponse({
            'success': False,
            'error': 'Invalid required_gb or safety_margin value',
        }, status=400)

    if required_gb <= 0:
        return JsonResponse({
            'success': False,
            'error': 'required_gb must be greater than 0',
        }, status=400)

    disk_info = SystemMonitor.get_disk_info()

    if not disk_info:
        return JsonResponse({
            'success': False,
            'error': 'Could not get disk information',
            'has_space': False,
        })

    available_gb = disk_info.get('free_gb', 0)
    total_required = required_gb + safety_margin_gb
    has_space = available_gb >= total_required

    if has_space:
        message = f"Sufficient space: {available_gb:.1f} GB available, {required_gb:.1f} GB required"
    else:
        message = (
            f"Insufficient disk space! "
            f"Available: {available_gb:.1f} GB, "
            f"Required: {required_gb:.1f} GB + {safety_margin_gb:.1f} GB safety margin = {total_required:.1f} GB"
        )

    return JsonResponse({
        'success': True,
        'has_space': has_space,
        'required_gb': required_gb,
        'available_gb': available_gb,
        'safety_margin_gb': safety_margin_gb,
        'total_required_gb': total_required,
        'message': message,
        'disk_percent': disk_info.get('percent', 0),
    })
