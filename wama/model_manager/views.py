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
from .services.memory_diagnostics import MemoryDiagnostics
from .services.memory_cleaner import WAMAMemoryCleaner, get_memory_cleaner
from wama.common.services.system_monitor import SystemMonitor
from wama.common.utils.format_policy import get_policy_summary
from wama.common.utils.volet import VOLET_AUCUN

logger = logging.getLogger(__name__)


def is_admin_or_dev(user):
    """
    Garde des 52 vues du model_manager — DÉLÈGUE au point unique de décision.

    ⚠ Elle décidait seule jusqu'au 27/08 (S2, mesure « qui contourne `accessible()` ») :
    `is_superuser or is_staff or groups in ('admin','dev')`. C'était un SECOND barème, hérité des
    Groups de la migration `accounts/0002`, antérieur aux tiers — et il ignorait
    `UserProfile.account_tier`. Conséquence mesurable : un compte au tier **développeur**, que la
    politique déclarée autorise explicitement (`min_tier='developpeur'`), était refusé ici. Deux
    barèmes pour une même question ne restent d'accord que par chance.

    La forme est conservée (52 décorateurs inchangés) ; seule la DÉCISION change de domicile.
    """
    from wama.accounts.permissions import accessible
    return bool(getattr(user, 'is_authenticated', False)
                and accessible(user, 'app', 'model_manager'))


@login_required
@user_passes_test(is_admin_or_dev)
def index(request):
    """Main Model Manager dashboard - fast initial load, models loaded via AJAX."""
    # Get memory stats from centralized SystemMonitor
    stats = SystemMonitor.get_model_manager_stats()

    context = {
        'model_types': [t.value for t in ModelType],
        'cpu_info': stats['cpu_info'],
        'gpu_info': stats['gpu_info'],
        'system_info': stats['system_info'],
        # Models will be loaded via AJAX
        'total_models': 0,
        'available_models': 0,
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
        'cpu': stats['cpu_info'],
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
    """API: modèles RÉSIDENTS en VRAM, LUS DANS LE REGISTRE PARTAGÉ.

    Lisait `WAMAMemoryTracker.get_summary()`, un registre de process que personne
    n'alimentait : le panneau « modèles suivis » de `/model_manager/` affichait 0 en
    permanence. Même remède que `api_idle_models` — le gouverneur voit tous les
    process (workers Celery, service TTS, web).
    """
    from wama.common.services.resource_governor import (
        idle_models as idle_partages, resident_models,
    )

    residents = resident_models()
    inactifs = {m['model_key'] for m in idle_partages(300)}

    return JsonResponse({
        'success': True,
        'total_tracked_mb': round(sum(residents.values()) * 1024, 1),
        'total_registered': len(residents),
        'active_count': len(residents) - len(inactifs & set(residents)),
        'idle_count': len(inactifs & set(residents)),
        'models': {
            cle: {
                'model_id': cle,
                'size_mb': round(gb * 1024, 1),
                'vram_gb': gb,
                'source': cle.split(':', 1)[0],
                'status': 'idle' if cle in inactifs else 'active',
            }
            for cle, gb in residents.items()
        },
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_idle_models(request):
    """API: modèles résidents inactifs, LUS DANS LE REGISTRE PARTAGÉ.

    Lisait `WAMAMemoryTracker`, un singleton de process qui n'est alimenté par
    personne (aucun appel à `register_model` dans le dépôt) ET qui, même alimenté,
    ne verrait que le process courant — or cette vue tourne dans gunicorn tandis que
    les modèles vivent dans les workers Celery et le service TTS. La liste était donc
    vide en toutes circonstances.
    """
    from wama.common.services.resource_governor import idle_models as idle_partages

    idle_threshold = int(request.GET.get('threshold', 300))  # Default 5 min
    inactifs = idle_partages(idle_threshold)

    return JsonResponse({
        'success': True,
        'threshold_seconds': idle_threshold,
        'idle_models': [
            {
                'model_id': m['model_key'],
                'idle_time_seconds': m['idle_seconds'],
                'idle_time_minutes': m['idle_minutes'],
                'size_mb': round(m['vram_gb'] * 1024, 1),
                'vram_gb': m['vram_gb'],
                'never_used': m['jamais_utilise'],
                'owner': m['owner'],
                'source': m['model_key'].split(':', 1)[0],
            }
            for m in inactifs
        ],
        'count': len(inactifs),
        'total_size_mb': round(sum(m['vram_gb'] for m in inactifs) * 1024, 1),
    })


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_large_objects(request):
    """API: Get large objects in memory."""
    min_size_mb = float(request.GET.get('min_size_mb', 10))

    large_objects = MemoryDiagnostics().find_large_objects(min_size_mb)

    return JsonResponse({
        'success': True,
        'min_size_mb': min_size_mb,
        'large_objects': [
            {
                'type': obj.obj_type,
                'size_mb': round(obj.size_mb, 2),
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
def api_backup_db(request):
    """API: sauvegarde la base (pg_dump) + copie sur l'espace distant.

    Synchrone : suffisant tant que le dump reste de l'ordre de la dizaine de secondes.
    À basculer sur Celery si la base grossit au point de dépasser le timeout HTTP.
    """
    from io import StringIO
    from django.core.management import call_command
    from django.core.management.base import CommandError

    out = StringIO()
    try:
        call_command('backup_db', stdout=out, stderr=out)
    except CommandError as exc:
        return JsonResponse({'success': False, 'error': str(exc)}, status=500)

    lines = [l for l in out.getvalue().splitlines() if l.strip()]
    return JsonResponse({'success': True, 'lines': lines})


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


def _mirror_job_start(request, task, cache_key):
    """
    Démarrage d'un miroir long (modèles, médias…) — corps COMMUN des vues `*_start`.

    Sens unique : rien n'est jamais supprimé côté distant (archive cumulative).
    Idempotent : si une passe tourne déjà, on renvoie son état au lieu d'en lancer une
    seconde (deux passes concurrentes se marcheraient dessus sur le même arbre distant).
    """
    from wama.common.utils.task_progress import progression_en_cours

    current = progression_en_cours(cache_key)   # brique commune : cache + vérif Celery
    if current:
        return JsonResponse({
            'success': True, 'already_running': True, 'progress': current,
        })

    overwrite = bool(json.loads(request.body or '{}').get('overwrite', False))
    started = task.delay(overwrite=overwrite)
    return JsonResponse({'success': True, 'already_running': False, 'task_id': started.id})


def _mirror_job_progress(cache_key):
    """Avancement d'un miroir long — corps COMMUN des vues `*_progress`."""
    from django.core.cache import cache

    progress = cache.get(cache_key)
    return JsonResponse({'success': True, 'running': bool(progress), 'progress': progress})


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_backup_models_start(request):
    """API: lance la sauvegarde globale AI-models/models/ → espace distant (tâche Celery)."""
    from .tasks import backup_all_models_task, BACKUP_ALL_CACHE_KEY

    return _mirror_job_start(request, backup_all_models_task, BACKUP_ALL_CACHE_KEY)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_backup_models_progress(request):
    """API: avancement du miroir global des modèles (lu depuis le cache Redis)."""
    from .tasks import BACKUP_ALL_CACHE_KEY

    return _mirror_job_progress(BACKUP_ALL_CACHE_KEY)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_backup_media_start(request):
    """API: lance le miroir des médias `media/` → espace distant (tâche Celery)."""
    from wama.common.tasks import backup_media_task, BACKUP_MEDIA_CACHE_KEY

    return _mirror_job_start(request, backup_media_task, BACKUP_MEDIA_CACHE_KEY)


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_backup_media_progress(request):
    """API: avancement du miroir des médias (lu depuis le cache Redis)."""
    from wama.common.tasks import BACKUP_MEDIA_CACHE_KEY

    return _mirror_job_progress(BACKUP_MEDIA_CACHE_KEY)


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
        # Offload destructif du fichier SOURCE (ex. .pt) après conversion : OPT-IN explicite.
        delete_source_after_backup = data.get('delete_source_after_backup', False)

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

        # Step 3: Offload du fichier SOURCE (ex. .pt) — OPT-IN explicite, destructif.
        # Sauvegarde le source sur le remote (miroir), VÉRIFIE, puis supprime le local.
        # Ne supprime jamais si la vérification échoue (garde-fou dans offload_file).
        if delete_source_after_backup:
            response['offload'] = get_backup_service().offload_file(
                conversion_result.source_path
            )

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
@require_GET
def api_models_db(request):
    """
    API: Get all models from database (fast).
    This replaces api_models_list for production use.

    LECTURE ouverte à tout utilisateur AUTHENTIFIÉ (2026-08-17) : WamaModelHelp et
    WamaModelCaps se nourrissent d'ici depuis les selects de TOUTES les apps — le gate
    admin/dev rendait ces briques silencieusement INERTES pour un non-dev (302 avalé par
    le fetch ; constat P2, ROUTE §11 #18 ; même décision d'ouverture que list_ai_models
    côté tool_api). Les champs d'EXPLOITATION (local_path, extra_info, backend_ref)
    restent réservés admin/dev ; toute action d'ÉCRITURE reste gardée (api_sync_models…).
    """
    from .models import AIModel

    # Optional filters
    source = request.GET.get('source')
    model_type = request.GET.get('type')
    downloaded_only = request.GET.get('downloaded') == 'true'
    format_filter = request.GET.get('format')

    # Inclure les candidats de prospection (is_proposed) bien qu'ils ne soient
    # pas "available" — ils s'affichent comme cards sous le filtre « Proposés par IA ».
    from django.db.models import Q
    queryset = AIModel.objects.filter(Q(is_available=True) | Q(is_proposed=True))

    if source:
        queryset = queryset.filter(source=source)
    if model_type:
        queryset = queryset.filter(model_type=model_type)
    if downloaded_only:
        queryset = queryset.filter(is_downloaded=True)
    if format_filter:
        queryset = queryset.filter(format=format_filter)

    # Résidence rabattue à la LECTURE, jamais écrite en base. `AIModel.is_loaded` n'est
    # écrit nulle part dans le dépôt (mesuré) et ne POURRAIT pas l'être sainement : un
    # booléen en base ne se répare pas seul si un worker meurt en tenant un modèle, il
    # resterait bloqué à True. Le registre VRAM partagé, lui, expire ses lignes.
    try:
        from wama.common.services.resource_governor import resident_models
        residents = resident_models()
    except Exception:
        residents = {}

    models = []
    full = is_admin_or_dev(request.user)
    for model in queryset:
        data = model.to_dict()
        if not data.get('is_loaded') and model.model_key in residents:
            data['is_loaded'] = True
        if not full:
            # Expurgé hors admin/dev : chemins locaux et détails d'exploitation.
            for k in ('local_path', 'extra_info', 'backend_ref'):
                data.pop(k, None)
        models.append(data)

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

    Request body options:
        clean: bool - Mark missing models as unavailable (legacy)
        delete_missing: bool - Delete models that no longer exist on disk (default: True)
    """
    from .services.model_sync import get_sync_service

    try:
        data = json.loads(request.body) if request.body else {}
        clean = data.get('clean', False)
        # Delete missing models by default to avoid orphaned entries after rename/delete
        delete_missing = data.get('delete_missing', True)

        sync_service = get_sync_service()
        result = sync_service.full_sync(remove_missing=clean, delete_missing=delete_missing)

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


# ── Prospection (proposés par IA) — Ollama-first ─────────────────────────────

#: Marge à conserver APRÈS installation. Un disque système rempli à ras ne casse pas que le
#: téléchargement : il casse les journaux, les fichiers temporaires de conversion et Postgres.
MARGE_DISQUE_GO = 10.0


# `_modele_remplace` a déménagé dans `services/model_installer.py::modele_remplace`
# (2026-08-18) : la tâche Celery d'installation en a besoin autant que la garde d'espace.


def _garde_espace_disque(ref: str, *, reclaim_gb: float = 0.0, force: bool = False,
                         besoin_gb: float | None = None):
    """
    Refuse une installation qui saturerait le volume. Retourne None si l'installation peut
    passer, sinon le dict d'erreur à renvoyer tel quel.

    `reclaim_gb` : espace que la DÉSINSTALLATION préalable de l'ancien modèle rendra. Sans ce
    paramètre, le garde refusait un REMPLACEMENT pourtant légitime — cas réel mesuré :
    qwen3.5:35b-a3b (22,2 Go) → qwen3.6:35b (22,3 Go) sur 23,7 Go libres. Le calcul naïf
    (23,7 − 22,3 = 1,4 Go) refuse ; le calcul juste (23,7 + 22,2 − 22,3 = 23,6 Go) accepte.

    Réutilise `SystemMonitor.get_disk_info()` (brique existante, WSL-aware : elle interroge
    l'hôte Windows) — aucune mesure de stockage n'est réécrite ici. `AI-models` et
    `D:\\.ollama\\models` sont sur le MÊME volume, un seul contrôle suffit donc.

    Taille INDÉTERMINABLE = refus, pas passage en force : sur un volume déjà à 96 %, supposer
    une taille optimiste revient à remplir le disque.
    """
    from wama.common.services.system_monitor import SystemMonitor
    from .services.ollama_registry import taille_go

    # `besoin_gb` fourni (candidat HF : poids `usedStorage` relevé à la prospection) →
    # pas d'interrogation du registre Ollama, qui ne connaît pas ces modèles.
    if besoin_gb:
        besoin = float(besoin_gb)
    else:
        nom, _, tag = ref.partition(':')
        besoin = taille_go(nom, tag or 'latest')
    disque = SystemMonitor.get_disk_info()
    if disque is None:
        return None if force else {
            'success': False, 'error': "Espace disque non mesurable — installation refusée.",
            'raison': 'disque_inconnu', 'force_possible': True}

    libre = float(disque.get('free_gb') or 0)
    if besoin is None:
        return None if force else {
            'success': False,
            'error': (f"Taille de « {ref} » indéterminable (manifeste illisible) ; "
                      f"{libre:.1f} Go libres. Installation refusée par précaution."),
            'raison': 'taille_inconnue', 'free_gb': libre, 'force_possible': True}

    reste = libre + float(reclaim_gb or 0) - besoin
    if reste < MARGE_DISQUE_GO and not force:
        detail = (f" (après libération de {reclaim_gb:.1f} Go par l'ancien modèle)"
                  if reclaim_gb else "")
        return {
            'success': False,
            'error': (f"Espace insuffisant : « {ref} » pèse {besoin:.1f} Go, il reste "
                      f"{libre:.1f} Go sur {disque.get('drive', 'le volume')}{detail} — après "
                      f"installation il ne resterait que {reste:.1f} Go "
                      f"(marge requise : {MARGE_DISQUE_GO:.0f} Go)."),
            'raison': 'espace_insuffisant',
            'needed_gb': besoin, 'free_gb': libre, 'reclaim_gb': round(float(reclaim_gb or 0), 1),
            'after_gb': round(reste, 1),
            'margin_gb': MARGE_DISQUE_GO, 'force_possible': True}
    return None

@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_prospect_ollama(request):
    """On-demand : lance la prospection Ollama et écrit les candidats proposés.
    Enfile ensuite la passe d'ÉVALUATION LLM (fire-and-forget) : les candidats `new`
    naissent sans confiance (`confidence=None` — l'heuristique d'âge ne vaut que pour
    les `update`) ; la confrontation multi-agents la remplit au fil de l'eau et les
    badges apparaissent au rechargement des cards. Trou comblé le 2026-08-18."""
    from .services.prospect_ollama import prospect_ollama
    try:
        summary = prospect_ollama()
        # ── Balayage HuggingFace (génération, parole, détection, upscaling, musique,
        # OCR — table déclarative HF_TASKS) — même clic, périmètre séparé : une panne HF
        # ne doit pas faire échouer la prospection Ollama (et inversement).
        try:
            from .services.prospector import seed_hf_candidates
            summary['hf'] = seed_hf_candidates()
            summary['total'] = (summary.get('total') or 0) + summary['hf']['total']
        except Exception:
            logger.warning("balayage HuggingFace en échec", exc_info=True)
            summary['hf'] = {'error': 'indisponible'}
        # ⚠ ENFILAGE AUTO DÉSACTIVÉ PAR DÉFAUT (2026-08-19). La passe LLM enchaînée sur
        # l'Ollama hôte a déclenché un CRASH WINDOWS reproductible à chaque prospection
        # (1er verdict 01:57:44 → hôte tombé, Ollama relancé 01:59:02) — c'est le pattern
        # « Ollama hôte enchaîné » déjà proscrit sur cette machine (instabilité SOUS l'OS,
        # même à faible charge). La confiance s'évalue désormais sur ACTION EXPLICITE
        # (CLI `assess_models --proposed` à venir, ou réactivation via ce réglage quand
        # l'hôte sera stabilisé).
        from django.conf import settings as _settings
        if getattr(_settings, 'PROSPECT_ASSESS_AUTO', False):
            try:
                from .tasks import assess_proposed_task
                assess_proposed_task.delay()
                summary['assess_enqueued'] = True
            except Exception:
                # Broker indisponible : la prospection reste valable, la confiance attendra.
                logger.warning("assess_proposed_task non enfilée", exc_info=True)
                summary['assess_enqueued'] = False
        else:
            summary['assess_enqueued'] = False
        return JsonResponse({'success': True, 'summary': summary})
    except Exception as e:
        logger.exception("api_prospect_ollama failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_prospect_install(request):
    """Installe un candidat proposé (ollama pull) puis le retire de la liste proposée.
    Accepte aussi une installation VISION directe sans candidat :
    `{'source': 'yolo', 'name': 'yolo26s-seg'}` → poids officiels Ultralytics téléchargés
    dans `AI-models/models/vision/yolo/<task>/` + sync du catalogue."""
    from .models import AIModel
    from .services.model_installer import pull_yolo_weights, register_after_install
    try:
        data = json.loads(request.body or '{}')
        # ── Install par DESCRIPTEUR (point d'entrée générique — UI/prospection/assistant) ──
        if data.get('spec'):
            from .services.model_installer import install_from_spec
            res = install_from_spec(data['spec'])
            if not res.get('ok'):
                return JsonResponse({'success': False, 'error': res.get('error', 'échec')}, status=500)
            return JsonResponse({'success': True, 'installed': data['spec'].get('ref'),
                                 'path': res.get('path')})
        # ── Install d'un modèle DU CATALOGUE (non proposé, non téléchargé — 2026-08-27) ──
        # L'app déclare l'emplacement (extra_info.install_dir, posé par sa découverte) ; le
        # spec se dérive côté serveur, la séquence longue part en Celery (même suivi que les
        # candidats). Cas d'origine : musicgen-melody « Not downloaded » sans aucun geste.
        if data.get('catalog_key'):
            from wama.common.utils.task_progress import progression_en_cours

            from .services.model_installer import spec_for_catalog_row
            from .services.prospector import _poids_depot_go
            from .tasks import INSTALL_CACHE_PREFIX, install_catalog_task
            model = AIModel.objects.filter(model_key=data['catalog_key'],
                                           is_proposed=False).first()
            if model is None:
                return JsonResponse({'success': False, 'error': 'Modèle introuvable'}, status=404)
            if model.is_downloaded:
                return JsonResponse({'success': False, 'error': 'Déjà téléchargé'}, status=400)
            spec = spec_for_catalog_row(model)
            if spec is None:
                return JsonResponse(
                    {'success': False,
                     'error': "Ce modèle ne déclare pas d'emplacement d'installation "
                              "(hf_id/install_dir) — il se téléchargera au premier usage."},
                    status=400)
            besoin = model.disk_gb or _poids_depot_go(model.hf_id)
            garde = _garde_espace_disque(model.hf_id, force=bool(data.get('force')),
                                         besoin_gb=besoin)
            if garde is not None:
                return JsonResponse(garde, status=507)
            en_cours = progression_en_cours(INSTALL_CACHE_PREFIX + model.model_key)
            if en_cours:
                return JsonResponse({'success': True, 'already_running': True,
                                     'model_id': model.model_key, 'progress': en_cours})
            started = install_catalog_task.delay(model.model_key)
            return JsonResponse({'success': True, 'started': True,
                                 'model_id': model.model_key, 'task_id': started.id})

        # ── Raccourci YOLO conservé (équivaut à spec={'kind':'yolo','ref':name}) ──
        if data.get('source') == 'yolo':
            res = pull_yolo_weights(data.get('name') or '')
            if not res.get('ok'):
                return JsonResponse({'success': False, 'error': res.get('error', 'échec')}, status=500)
            try:
                register_after_install()
            except Exception:
                logger.warning("register_after_install a échoué (le sync périodique rattrapera)",
                               exc_info=True)
            return JsonResponse({'success': True, 'installed': data.get('name'),
                                 'path': res.get('path')})
        model_id = data.get('model_id')
        cand = AIModel.objects.filter(model_key=model_id, is_proposed=True).first()
        if not cand:
            return JsonResponse({'success': False, 'error': 'Candidat introuvable'}, status=404)
        cand_spec = (cand.extra_info or {}).get('prospect', {}).get('spec')
        if cand.source != 'ollama' and not cand_spec:
            return JsonResponse({'success': False,
                                 'error': "Candidat sans spec d'installation (source "
                                          f"{cand.source}) — non installable."}, status=400)

        # ── CHOIX DE VARIANTE (2026-08-27) : le juge évalue la faisabilité VRAM sur les
        # variantes quantisées, mais l'installation tirait TOUJOURS les poids pleins du
        # dépôt canonique (vécu MiniMax-Music3 : 54 Go inexploitables sur 24 Go de VRAM).
        # L'UI propose désormais les options (api_prospect_install_options) ; le choix
        # validé est PERSISTÉ dans le spec du candidat — la tâche Celery relit le candidat
        # en base, donc la sélection de l'utilisateur est respectée de bout en bout.
        besoin_hf = cand.disk_gb or None
        variant_ref = data.get('variant_ref')
        variant_file = data.get('variant_file')
        if variant_ref and cand.source != 'ollama':
            from .services.prospector import spec_pour_choix
            spec_choisi = spec_pour_choix(cand, variant_ref, variant_file)
            if spec_choisi is None:
                return JsonResponse({'success': False,
                                     'error': f"Choix inconnu ({variant_ref}"
                                              f"{' / ' + variant_file if variant_file else ''}) "
                                              "— recharger les options."}, status=400)
            info = dict(cand.extra_info or {})
            pr = dict(info.get('prospect') or {})
            pr['spec'] = spec_choisi
            pr['chosen_variant'] = {'ref': variant_ref, 'file': variant_file}
            info['prospect'] = pr
            cand.extra_info = info
            cand.save(update_fields=['extra_info'])
            # La garde d'espace se calcule sur le POIDS DU CHOIX, pas sur les poids pleins.
            variantes = {v['hf_id']: v for v in (pr.get('quant_variants') or [])}
            if variant_file:
                tailles = {f['file']: f['gb']
                           for f in (variantes.get(variant_ref, {}).get('files') or [])}
                besoin_hf = tailles.get(variant_file) or None
            elif variant_ref != cand.hf_id:
                besoin_hf = (variantes.get(variant_ref) or {}).get('disk_gb') or None

        # ── GARDE D'ESPACE DISQUE (SYNCHRONE : le 507/forçage est un dialogue) ──
        # `ollama pull` n'a AUCUN garde-fou : il télécharge jusqu'à saturer le volume. Mesuré le
        # 2026-08-04, D: était à 96 % (23,7 Go libres) alors que `qwen3.6:35b` pèse 22,3 Go —
        # une installation aurait laissé ~1,4 Go. Rien n'est libéré par ailleurs : l'ancien
        # modèle n'est pas supprimé et les modèles Ollama ne sont pas sauvegardés
        # (décision 2026-08-04, PROSPECTION_PIPELINE.md).
        # REMPLACEMENT : un candidat « successeur » connaît le modèle qu'il remplace. L'espace
        # du nouveau n'est disponible qu'APRÈS retrait de l'ancien — on le compte donc dans le
        # garde ; la séquence désinstallation → installation vit dans `installer_candidat`.
        from .services.model_installer import modele_remplace
        remplace, reclaim_gb = modele_remplace(cand)

        garde = _garde_espace_disque(cand.name, reclaim_gb=reclaim_gb,
                                     force=bool(data.get('force')),
                                     # HF : poids du CHOIX validé (variante quantisée : son
                                     # dépôt/fichier), sinon poids pleins relevés à la
                                     # prospection ; None = inconnu → refus prudent forçable.
                                     besoin_gb=besoin_hf
                                               if cand.source != 'ollama' else None)
        if garde is not None:
            garde['replaces'] = remplace
            return JsonResponse(garde, status=507)   # 507 Insufficient Storage

        # ── SÉQUENCE LONGUE → TÂCHE CELERY (2026-08-18) ─────────────────────
        # Un pull de 18 Go dans la requête dépassait le timeout du proxy Apache : le
        # navigateur recevait une page HTML d'erreur pendant que le worker continuait en
        # aveugle, et un re-clic ouvrait une requête CONCURRENTE. Désormais : réponse
        # immédiate + avancement pollable ; un re-clic REJOINT l'installation en cours
        # (même motif d'idempotence que `_mirror_job_start`).
        from wama.common.utils.task_progress import progression_en_cours

        from .tasks import INSTALL_CACHE_PREFIX, install_proposed_task
        en_cours = progression_en_cours(INSTALL_CACHE_PREFIX + model_id)
        if en_cours:
            return JsonResponse({'success': True, 'already_running': True,
                                 'model_id': model_id, 'progress': en_cours})

        started = install_proposed_task.delay(model_id)
        return JsonResponse({'success': True, 'started': True,
                             'model_id': model_id, 'task_id': started.id})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.exception("api_prospect_install failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
def api_prospect_install_options(request):
    """Options d'installation d'un candidat HF (poids pleins + variantes quantisées, tailles
    disque/VRAM) — à montrer AVANT d'installer. `?model_id=<model_key>`. Relevés réseau payés
    une fois (persistés au candidat). Candidat Ollama → {'choice': false} (pas de variantes)."""
    from .models import AIModel
    from .services.prospector import options_installation
    model_id = request.GET.get('model_id') or ''
    cand = AIModel.objects.filter(model_key=model_id, is_proposed=True).first()
    if not cand:
        return JsonResponse({'success': False, 'error': 'Candidat introuvable'}, status=404)
    try:
        return JsonResponse({'success': True, **options_installation(cand)})
    except Exception as e:
        logger.exception("api_prospect_install_options failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_prospect_assess(request):
    """Déclenchement EXPLICITE de la passe de confiance LLM — jamais auto depuis le
    crash hôte du 2026-08-19 (« Ollama hôte enchaîné »). La tâche est routée file
    `gpu` --pool=solo palier `basse` (sérialisée derrière tout traitement) et la passe
    est GOUVERNÉE (garde `effective_free_gb` + `vram_reservation`). Idempotent : une
    passe déjà vivante est rejointe au lieu d'être doublée."""
    from wama.common.utils.task_progress import progression_en_cours

    from .tasks import ASSESS_CACHE_KEY, assess_proposed_task
    en_cours = progression_en_cours(ASSESS_CACHE_KEY)
    if en_cours:
        return JsonResponse({'success': True, 'already_running': True, 'progress': en_cours})
    started = assess_proposed_task.delay()
    return JsonResponse({'success': True, 'started': True, 'task_id': started.id})


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_prospect_assess_progress(request):
    """Avancement de la passe de confiance (cache Redis, écrit par la tâche)."""
    from django.core.cache import cache

    from .tasks import ASSESS_CACHE_KEY
    progress = cache.get(ASSESS_CACHE_KEY)
    return JsonResponse({'success': True, 'running': bool(progress), 'progress': progress})


@login_required
@user_passes_test(is_admin_or_dev)
@require_GET
def api_prospect_install_progress(request):
    """Avancement d'une installation de candidat (cache Redis, écrit par la tâche).
    `?model_id=<model_key>` — F5-proof : le cache porte l'état, pas le navigateur."""
    from django.core.cache import cache

    from .tasks import INSTALL_CACHE_PREFIX
    model_id = request.GET.get('model_id') or ''
    progress = cache.get(INSTALL_CACHE_PREFIX + model_id)
    return JsonResponse({'success': True, 'running': bool(progress), 'progress': progress})


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_prospect_reject(request):
    """Rejette (supprime) un candidat proposé."""
    from .models import AIModel
    try:
        data = json.loads(request.body or '{}')
        model_id = data.get('model_id')
        n, _ = AIModel.objects.filter(model_key=model_id, is_proposed=True).delete()
        return JsonResponse({'success': bool(n)})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.exception("api_prospect_reject failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
@user_passes_test(is_admin_or_dev)
@require_POST
def api_model_uninstall(request):
    """Désinstalle un modèle INSTALLÉ : retrait des poids (Ollama ou snapshot HF), catalogue
    recalé, backend jamais touché. Miroir de l'installation — corps dans
    `model_installer.uninstall_model` (gardes : chargé → refus, candidat → refus)."""
    from .services.model_installer import uninstall_model
    try:
        data = json.loads(request.body or '{}')
        model_id = data.get('model_id')
        if not model_id:
            return JsonResponse({'success': False, 'error': 'model_id required'}, status=400)
        res = uninstall_model(model_id)
        if not res.get('ok'):
            return JsonResponse({'success': False, 'error': res.get('error')}, status=400)
        return JsonResponse({'success': True, 'freed_gb': res.get('freed_gb'),
                             'name': res.get('name'), 'kind': res.get('kind')})
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.exception("api_model_uninstall failed")
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@login_required
def function_catalog(request):
    """Catalogue des FONCTIONS de traitement WAMA Data (card-style, tri/filtre côté client).
    Lit `FUNCTION_CATALOG` (fonctions pures + app-bound déclarées par capacités)."""
    import json as _json
    from wama.common.catalog.function_catalog import load_all, catalog_dict
    load_all()
    cat = catalog_dict()
    funcs = list(cat.values())
    # + fonctions UTILISATEUR (BDD) visibles pour cet utilisateur (privé/unité/public).
    try:
        from wama.common.models import UserFunction, scoped_visible_q
        for uf in UserFunction.objects.filter(scoped_visible_q(request.user, owner_field='owner')):
            funcs.append(uf.to_dict())
    except Exception:
        pass
    funcs = sorted(funcs, key=lambda f: (f['binding'] != 'pure', f.get('app', ''), f['name']))
    stats = {
        'total': len(funcs),
        'pure': sum(1 for f in funcs if f['binding'] == 'pure'),
        'app': sum(1 for f in funcs if f['binding'] == 'app'),
        'categories': sorted({f['category'] for f in funcs}),
        'projects': sorted({p for f in funcs for p in (f.get('projects') or [])}),
        'apps': sorted({f['app'] for f in funcs if f['app']}),
    }
    # Catalogue = tableau plein cadre ; le volet n'y portait que 3 cadres vides (WAMA_VOLETS §2).
    return render(request, 'model_manager/function_catalog.html',
                  {'functions_json': _json.dumps(funcs), 'stats': stats,
                   'volet': VOLET_AUCUN})


@login_required
def library_catalog(request):
    """Catalogue des LIBRAIRIES externes — page de gestion du registre `common.models.Library`
    (né de la projection `write_back_library`, jamais édité main). La page LIT le registre et
    MESURE l'installation live (`importlib.metadata`) — elle n'écrit rien : `is_allowed` se
    décide dans l'admin (verrou n°2, hors write-back), l'installation via le provisionneur.
    Demandée par Fabien le 2026-08-11 (le registre existait sans surface)."""
    import importlib.metadata as im
    from wama.common.models import Library

    rows = []
    for lib in Library.objects.all():
        try:
            live = im.version(lib.key)
        except im.PackageNotFoundError:
            live = None
        declared = (lib.pip_spec.split('==', 1)[1] if '==' in (lib.pip_spec or '')
                    else lib.version or '')
        rows.append({
            'lib': lib,
            'live_version': live,
            'drift': bool(live and declared and live != declared),
        })
    stats = {
        'total': len(rows),
        'installed': sum(1 for r in rows if r['live_version']),
        'allowed': sum(1 for r in rows if r['lib'].is_allowed),
        'drift': sum(1 for r in rows if r['drift']),
    }
    # Facettes SANS options : en mode client la brique les dérive du DOM, et les valeurs y sont
    # déjà les libellés affichés (« installée »/« absente »…). Rien à déclarer, donc rien qui
    # puisse lister un état absent de la page.
    facettes = [
        {'cle': 'installee', 'label': 'Installation', 'tous': 'Toutes'},
        {'cle': 'allowlist', 'label': 'Allowlist', 'tous': 'Toutes'},
    ]

    return render(request, 'model_manager/library_catalog.html',
                  {'rows': rows, 'stats': stats, 'facettes_librairies': facettes,
                   'volet': VOLET_AUCUN})   # cf. function_catalog
