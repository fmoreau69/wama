"""
Celery tasks for Model Manager.

Provides background sync capabilities and periodic tasks.
"""

import logging
from celery import shared_task

logger = logging.getLogger(__name__)


@shared_task(bind=True, name='model_manager.sync_models')
def sync_models_task(self, clean: bool = False):
    """
    Background task to sync models.
    Can be scheduled via Celery Beat for periodic sync.

    Args:
        clean: If True, mark models not found as unavailable

    Returns:
        Dict with sync results
    """
    from .services.model_sync import get_sync_service

    logger.info("Starting background model sync")

    sync_service = get_sync_service()
    result = sync_service.full_sync(remove_missing=clean)

    logger.info(
        f"Model sync complete: +{result.added}, ~{result.updated}, -{result.removed}"
    )

    return {
        'success': result.success,
        'added': result.added,
        'updated': result.updated,
        'removed': result.removed,
        'errors': result.errors[:10] if result.errors else [],
    }


@shared_task(name='model_manager.sync_ollama')
def sync_ollama_models():
    """
    Periodic task to check Ollama models status.
    Run this less frequently as it calls external service.

    Returns:
        Dict with sync count
    """
    from .models import AIModel, ModelSource, ModelType
    from .services.model_registry import ModelRegistry
    from django.utils import timezone

    logger.info("Checking Ollama models")

    try:
        # Use registry to discover Ollama models
        registry = ModelRegistry()
        registry._models.clear()
        registry._discover_ollama_models()

        ollama_models = {
            k: v for k, v in registry._models.items()
            if k.startswith('ollama:')
        }

        # Sync to database
        synced = 0
        for model_key, model_info in ollama_models.items():
            obj, created = AIModel.objects.update_or_create(
                model_key=model_key,
                defaults={
                    'name': model_info.name,
                    'model_type': ModelType.LLM,
                    'source': ModelSource.OLLAMA,
                    'description': model_info.description or '',
                    'ram_gb': model_info.ram_gb or 0,
                    'is_downloaded': True,
                    'is_available': True,
                    'last_synced_at': timezone.now(),
                    'extra_info': model_info.extra_info or {},
                }
            )
            synced += 1

        logger.info(f"Synced {synced} Ollama models")
        return {'synced': synced}

    except Exception as e:
        logger.error(f"Error syncing Ollama models: {e}")
        return {'error': str(e), 'synced': 0}


@shared_task(name='model_manager.update_loaded_status')
def update_loaded_status_task(model_key: str, is_loaded: bool):
    """
    Update the loaded status of a model.
    Called when models are loaded/unloaded.

    Args:
        model_key: The model identifier
        is_loaded: Whether the model is loaded

    Returns:
        Dict with success status
    """
    from .services.model_sync import get_sync_service

    sync_service = get_sync_service()
    success = sync_service.update_loaded_status(model_key, is_loaded)

    return {'success': success, 'model_key': model_key, 'is_loaded': is_loaded}
