"""
Synchronisation CENTRALISÉE du modèle batch unifié WAMA — cf. BATCH_MODEL_AUDIT.md.

Maintient, par signaux Django, l'invariant fondamental :
    batch.total == nombre réel de membres (batch.items.count())
et supprime les batches vidés (un batch sans membre n'existe pas).

Capté pour TOUS les chemins de mutation (vue, admin, cascade, bulk, shell) → plus aucun
recalcul manuel dans les vues (fini les pansements). `total` devient un champ AUTO-RÉPARÉ :
il ne peut plus diverger.

Usage — une fois, dans AppConfig.ready() de chaque app :
    from wama.common.utils.batch_sync import register_batch_sync
    register_batch_sync(BatchTranscriptItem)
    register_batch_sync(BatchSynthesisItem, batch_file_field='batch_file')  # nettoie le fichier batch partagé
"""
import logging

from django.db.models.signals import post_save, post_delete

logger = logging.getLogger(__name__)


def sync_batch_total(batch):
    """Recale `batch.total` sur `items.count()` ; supprime le batch vidé. Idempotent et défensif.
    Le nettoyage du fichier batch est porté par `BatchMixin.delete()` (single responsibility)."""
    if batch is None:
        return
    try:
        count = batch.items.count()
        if count == 0:
            batch.delete()  # BatchMixin.delete() nettoie le fichier batch partagé
        elif batch.total != count:
            batch.total = count
            batch.save(update_fields=['total'])
    except Exception as e:  # batch déjà supprimé (cascade), course, etc. → on ignore
        logger.debug("sync_batch_total ignoré: %s", e)


def resync_batches(batch_model):
    """Nettoyage one-shot d'un modèle Batch (Niveau 0) : recale tous les `total` sur le réel
    et supprime les batches vidés. À lancer une fois sur les données existantes (commande
    `cleanup_batches`). Renvoie (resynced, deleted)."""
    resynced, deleted = 0, 0
    for batch in list(batch_model.objects.all()):
        count = batch.items.count()
        if count == 0:
            batch.delete()  # BatchMixin.delete() nettoie le fichier batch
            deleted += 1
        elif batch.total != count:
            batch.total = count
            batch.save(update_fields=['total'])
            resynced += 1
    return resynced, deleted


#: Modèles de liaison branchés (A3b) — REGISTRE de mesure : permet à l'extract manifeste de
#: savoir quel modèle une app a déclaré (facette processing.batch_link_model), donc au gabarit
#: apps_gen de régénérer l'appel. Ne pilote rien au runtime.
SYNCED: list = []


def register_batch_sync(item_model, batch_attr='batch'):
    """Branche post_save + post_delete d'un modèle `BatchItem` pour maintenir l'invariant
    (total = items.count(), batch vidé supprimé). À appeler UNE fois (AppConfig.ready).
    dispatch_uid garantit l'idempotence du branchement."""
    if item_model not in SYNCED:
        SYNCED.append(item_model)
    name = item_model.__name__

    def _on_change(sender, instance, **kwargs):
        try:
            batch = getattr(instance, batch_attr, None)
        except Exception:
            batch = None  # parent déjà supprimé (cascade) → rien à recaler
        sync_batch_total(batch)

    post_save.connect(_on_change, sender=item_model, weak=False,
                      dispatch_uid=f'batchsync_save_{name}')
    post_delete.connect(_on_change, sender=item_model, weak=False,
                        dispatch_uid=f'batchsync_delete_{name}')
