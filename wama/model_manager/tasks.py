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


#: Clé de cache partagée entre la tâche (écrit l'avancement) et la vue de progression
#: (le lit). Passer par le cache plutôt que par l'AsyncResult permet de retrouver un
#: backup en cours après un simple F5 sur la page — le navigateur n'a plus le task_id.
BACKUP_ALL_CACHE_KEY = 'model_manager:backup_all_models'
BACKUP_ALL_TTL = 24 * 3600


@shared_task(bind=True, name='model_manager.backup_all_models')
def backup_all_models_task(self, overwrite: bool = False):
    """
    Sauvegarde globale AI-models/models/ → espace distant (incrémentale, sens unique).

    Ne supprime JAMAIS rien côté distant : celui-ci est une archive cumulative (il garde
    les formats d'origine que le local a pu retirer après conversion).

    Opération de plusieurs minutes à plusieurs heures selon le delta : d'où la tâche
    Celery. L'avancement est publié dans le cache Django (Redis) sous
    BACKUP_ALL_CACHE_KEY, lu par api_backup_models_progress.
    """
    from django.core.cache import cache
    from .services.remote_backup import get_backup_service

    def publish(state: str, payload: dict):
        cache.set(
            BACKUP_ALL_CACHE_KEY,
            dict(payload, state=state, task_id=self.request.id),
            BACKUP_ALL_TTL,
        )

    publish('RUNNING', {'phase': 'scan', 'total_files': 0, 'processed': 0,
                        'copied': 0, 'skipped': 0, 'failed': 0, 'copied_mb': 0.0})
    logger.info("Starting full model backup to remote storage")

    try:
        service = get_backup_service()
        result = service.backup_all_models(
            overwrite=overwrite,
            progress_cb=lambda p: publish('RUNNING', p),
        )
        publish('SUCCESS' if result['success'] else 'PARTIAL', result)
        logger.info(
            f"Model backup complete: +{result['copied']} copiés, "
            f"{result['skipped']} déjà présents, {result['failed']} échecs"
        )
        return result
    except Exception as e:
        logger.error(f"Full model backup failed: {e}")
        publish('FAILURE', {'errors': [str(e)]})
        raise


@shared_task(name='model_manager.backup_db')
def backup_db_task(keep: int = 10):
    """
    Sauvegarde quotidienne de la base (pg_dump) + copie NAS. Planifiée par Celery beat.

    Pendant PLANIFIÉ du bouton « Backup DB » (`api_backup_db`) et de
    `manage.py backup_db`, qui restent les entrées À LA DEMANDE. Toute la logique
    (dump, copie distante, rotation `keep` des deux côtés, vérification de taille)
    vit dans la commande : on l'APPELLE, on ne la réimplémente pas.

    Motif (2026-08-10) : la brique existait depuis le 27/07 mais n'était câblée à
    AUCUN ordonnanceur — ni cron, ni systemd, ni beat, ni tâche Windows. Résultat
    mesuré : un seul dump, celui du 29/07, alors que l'hôte a subi 7 coupures
    d'alimentation entre-temps.

    Queue `default` : pg_dump est CPU/IO pur, jamais de GPU — la règle « pas de job
    GPU nocturne » (crashs hôte) reste respectée.
    """
    from io import StringIO

    from django.core.management import call_command
    from django.core.management.base import CommandError

    out = StringIO()
    try:
        call_command('backup_db', keep=keep, stdout=out, stderr=out)
    except CommandError as exc:
        # NAS injoignable n'arrive PAS ici : la commande dégrade proprement (dump
        # local conservé, avertissement). Un CommandError = pg_dump absent ou en
        # échec, donc aucune sauvegarde du tout → doit remonter en échec Celery.
        logger.error("[backup_db] échec : %s", exc)
        raise

    report = out.getvalue().strip()
    logger.info("[backup_db] %s", report.replace("\n", " | "))
    return report


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
