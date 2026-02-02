"""
Model Manager URL patterns.
"""

from django.urls import path
from . import views

app_name = 'model_manager'

urlpatterns = [
    # Dashboard
    path('', views.index, name='index'),

    # API endpoints - Models
    path('api/models/', views.api_models_list, name='api_models_list'),
    path('api/memory/', views.api_memory_stats, name='api_memory_stats'),
    path('api/unload/', views.api_unload_model, name='api_unload_model'),
    path('api/clear-gpu/', views.api_clear_gpu, name='api_clear_gpu'),
    path('api/refresh/', views.api_refresh_models, name='api_refresh_models'),
    path('api/debug/', views.api_debug_stats, name='api_debug_stats'),

    # API endpoints - Format Conversion
    path('api/formats/', views.api_format_stats, name='api_format_stats'),
    path('api/convert/', views.api_convert_model, name='api_convert_model'),
    path('api/convert/batch/', views.api_batch_convert, name='api_batch_convert'),
    path('api/convert/options/', views.api_conversion_options, name='api_conversion_options'),
    path('api/convert/suggestions/', views.api_conversion_suggestions, name='api_conversion_suggestions'),

    # API endpoints - Memory Management
    path('api/memory/detailed/', views.api_memory_detailed, name='api_memory_detailed'),
    path('api/memory/tracked/', views.api_tracked_models, name='api_tracked_models'),
    path('api/memory/idle/', views.api_idle_models, name='api_idle_models'),
    path('api/memory/large-objects/', views.api_large_objects, name='api_large_objects'),
    path('api/memory/snapshot/', views.api_memory_snapshot, name='api_memory_snapshot'),

    # API endpoints - Memory Cleanup
    path('api/cleanup/idle/', views.api_cleanup_idle, name='api_cleanup_idle'),
    path('api/cleanup/aggressive/', views.api_aggressive_cleanup, name='api_aggressive_cleanup'),
    path('api/cleanup/gpu-cache/', views.api_clear_gpu_cache, name='api_clear_gpu_cache'),
    path('api/cleanup/gc/', views.api_force_gc, name='api_force_gc'),
    path('api/cleanup/unload/', views.api_unload_model_by_id, name='api_unload_model_by_id'),

    # API endpoints - Memory Cleaner Control
    path('api/cleaner/status/', views.api_cleaner_status, name='api_cleaner_status'),
    path('api/cleaner/configure/', views.api_cleaner_configure, name='api_cleaner_configure'),
    path('api/cleaner/start/', views.api_cleaner_start, name='api_cleaner_start'),
    path('api/cleaner/stop/', views.api_cleaner_stop, name='api_cleaner_stop'),

    # API endpoints - Remote Backup
    path('api/backup/status/', views.api_backup_status, name='api_backup_status'),
    path('api/backup/list/', views.api_backup_list, name='api_backup_list'),
    path('api/backup/model/', views.api_backup_model, name='api_backup_model'),
    path('api/convert-and-backup/', views.api_convert_and_backup, name='api_convert_and_backup'),

    # API endpoints - Database Catalog (fast)
    path('api/models/db/', views.api_models_db, name='api_models_db'),
    path('api/sync/', views.api_sync_models, name='api_sync_models'),
    path('api/catalog/stats/', views.api_catalog_stats, name='api_catalog_stats'),
    path('api/sync/logs/', views.api_sync_logs, name='api_sync_logs'),

    # API endpoints - File Watcher
    path('api/watcher/status/', views.api_watcher_status, name='api_watcher_status'),
    path('api/watcher/control/', views.api_watcher_control, name='api_watcher_control'),

    # API endpoints - Disk Space
    path('api/disk/', views.api_disk_space, name='api_disk_space'),
    path('api/disk/check/', views.api_check_disk_space, name='api_check_disk_space'),

    # API endpoints - Diagnostics
    path('api/diagnose/', views.api_diagnose_models, name='api_diagnose_models'),
]
