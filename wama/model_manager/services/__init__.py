# Model Manager Services
from .model_registry import ModelRegistry, ModelInfo, ModelType, ModelSource
from .model_selector import (
    select_model,
    list_models,
    describe_model,
    get_free_vram_gb,
    get_registry_models,
)
from .memory_manager import MemoryManager, MemoryStrategy, MODEL_SIZE_PRESETS
from .format_converter import FormatConverter, ConversionResult, ConversionSuggestion
from .memory_monitor import WAMAMemoryMonitor, RAMUsage, GPUUsage, MemorySnapshot
from .memory_tracker import WAMAMemoryTracker, TrackedModel, IdleModel, LargeObject
from .memory_cleaner import (
    WAMAMemoryCleaner,
    CleanupResult,
    get_memory_cleaner,
    start_memory_cleaner,
    stop_memory_cleaner,
)
from .remote_backup import RemoteBackupService, BackupResult, get_backup_service
from .model_sync import ModelSyncService, SyncResult, get_sync_service
from .file_watcher import ModelFileWatcher, get_file_watcher, is_watchdog_available
from .update_checker import check_updates, apply_flags
from .model_installer import pull_ollama_model, register_after_install

__all__ = [
    # Model Registry
    'ModelRegistry',
    'ModelInfo',
    'ModelType',
    'ModelSource',
    # Model Selector (sélection intelligente centralisée)
    'select_model',
    'list_models',
    'describe_model',
    'get_free_vram_gb',
    # Update Checker (détecteur déterministe de MAJ, sans LLM)
    'check_updates',
    'apply_flags',
    # Registre → dropdowns d'app (verrou n°1)
    'get_registry_models',
    # Installation modèles (étape 2 : accept→download→register)
    'pull_ollama_model',
    'register_after_install',
    # Memory Manager
    'MemoryManager',
    'MemoryStrategy',
    'MODEL_SIZE_PRESETS',
    # Format Converter
    'FormatConverter',
    'ConversionResult',
    'ConversionSuggestion',
    # Memory Monitor
    'WAMAMemoryMonitor',
    'RAMUsage',
    'GPUUsage',
    'MemorySnapshot',
    # Memory Tracker
    'WAMAMemoryTracker',
    'TrackedModel',
    'IdleModel',
    'LargeObject',
    # Memory Cleaner
    'WAMAMemoryCleaner',
    'CleanupResult',
    'get_memory_cleaner',
    'start_memory_cleaner',
    'stop_memory_cleaner',
    # Remote Backup
    'RemoteBackupService',
    'BackupResult',
    'get_backup_service',
    # Model Sync
    'ModelSyncService',
    'SyncResult',
    'get_sync_service',
    # File Watcher
    'ModelFileWatcher',
    'get_file_watcher',
    'is_watchdog_available',
]
