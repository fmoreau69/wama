# Model Manager Services
#
# Chargés À LA DEMANDE (PEP 562, 2026-10-20) : un nom exporté n'importe son module qu'au premier
# accès. Ce `__init__` importait d'office ses vingt modules — installeur, prospection, sauvegardes,
# surveillance de fichiers, sondes mémoire (torch) — et tout `from wama.model_manager.services.<x>
# import …` exécute d'abord le paquet : un processus qui ne voulait que `register_vram_unloader`
# chargeait torch (≈ 10–13 s sous WSL). Mesuré sur le démarrage de Django, payé par chaque
# processus WAMA. Les noms et `__all__` sont inchangés.
import importlib

_EXPORTS = {
    'model_registry': ('ModelRegistry', 'ModelInfo', 'ModelType', 'ModelSource'),
    'model_selector': ('select_model', 'select_model_id', 'full_gpu_budget_gb', 'matches_inputs',
                       'list_models', 'describe_model', 'get_free_vram_gb', 'get_registry_models',
                       'QUALITY_PRESETS', 'QUALITY_DEFAULT'),
    'memory_manager': ('MemoryManager', 'MemoryStrategy', 'MODEL_SIZE_PRESETS'),
    'format_converter': ('FormatConverter', 'ConversionResult', 'ConversionSuggestion'),
    'memory_monitor': ('WAMAMemoryMonitor', 'RAMUsage', 'GPUUsage', 'MemorySnapshot'),
    'memory_diagnostics': ('MemoryDiagnostics', 'LargeObject'),
    'memory_cleaner': ('WAMAMemoryCleaner', 'CleanupResult', 'get_memory_cleaner',
                       'start_memory_cleaner', 'stop_memory_cleaner'),
    'remote_backup': ('RemoteBackupService', 'BackupResult', 'get_backup_service'),
    'model_sync': ('ModelSyncService', 'SyncResult', 'get_sync_service'),
    'file_watcher': ('ModelFileWatcher', 'get_file_watcher', 'is_watchdog_available'),
    'update_checker': ('check_updates', 'apply_flags'),
    'model_installer': ('pull_ollama_model', 'pull_hf_model', 'register_after_install'),
    'prospector': ('prospect_hf', 'apply_recommendations', 'APP_TASKS'),
    'prospect_agents': ('assess_candidate', 'parse_agents'),
    'vision_probe': ('describe_image_ollama',),
}
_MODULE_OF = {name: module for module, names in _EXPORTS.items() for name in names}


def __getattr__(name):
    module = _MODULE_OF.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(f'{__name__}.{module}'), name)
    globals()[name] = value
    return value


__all__ = [
    # Model Registry
    'ModelRegistry',
    'ModelInfo',
    'ModelType',
    'ModelSource',
    # Model Selector (sélection intelligente centralisée)
    'select_model',
    'select_model_id',
    'full_gpu_budget_gb',
    'matches_inputs',
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
    'pull_hf_model',
    'register_after_install',
    # Prospection déterministe (socle veille, sans LLM)
    'prospect_hf',
    'apply_recommendations',
    'APP_TASKS',
    # Prospection multi-agents (LLM, au-dessus du déterministe)
    'assess_candidate',
    'parse_agents',
    # Sonde vision (bench Describer)
    'describe_image_ollama',
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
    # Memory Diagnostics (sondes in-process ; le SUIVI des modèles résidents
    # est au gouverneur : common/services/resource_governor.py)
    'MemoryDiagnostics',
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
