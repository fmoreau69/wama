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
    register_batch_sync(BatchTranscriptItem)              # membre = modèle de LIAISON (10 surfaces)
    register_batch_sync(ConversionJob, direct_fk=True)    # membre = l'ÉLÉMENT lui-même (FK directe)
Le nettoyage du fichier batch partagé est porté par `BatchMixin.delete()`, pas ici (un ancien
`batch_file_field=` documenté à cette place n'a jamais existé dans la signature).
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


def register_batch_sync(item_model, batch_attr='batch', direct_fk=False):
    """Branche post_save + post_delete d'un MEMBRE de lot pour maintenir l'invariant
    (total = items.count(), batch vidé supprimé). À appeler UNE fois (AppConfig.ready).
    dispatch_uid garantit l'idempotence du branchement.

    ⚠ « MEMBRE d'un lot », pas « modèle de liaison » — la nuance a coûté un défaut MUET.
    Le rattachement prend DEUX formes dans le dépôt (`batch_common.batch_model_for`) : par
    modèle de LIAISON (10 surfaces) et par FK DIRECTE, où l'élément EST le membre
    (converter). Les dix appels d'origine ne citaient que des liaisons : la forme directe
    restait donc hors de portée de l'invariant, et son lot vidé survivait — invisible,
    puisqu'un lot sans membre ne rend aucune card. Mesuré le 2026-08-28 par
    `converter.clear_all`, sur l'app dont la jumelle GÉNÉRÉE (`converter_01`) avait, elle,
    reçu la rustine à la main dans sa vue. Rien dans cette fonction n'exigeait une liaison :
    seul l'USAGE s'était restreint.

    ``direct_fk=True`` déclare cette seconde forme, et en tire les deux conséquences :
      • **hors de `SYNCED`** — ce registre de MESURE signifie « modèle de liaison de l'app »
        et le manifeste le publie tel quel (`processing.batch_link_model`, lu par `apps_gen`).
        Y inscrire un modèle d'ÉLÉMENT ne casserait rien à l'exécution : ça rendrait FAUX ce
        que l'app déclare d'elle-même, et le gabarit régénérerait un appel erroné.
      • **pas de `post_save`** — l'élément est ré-enregistré à chaque tick de progression ; un
        COUNT par tick pour un invariant que seule une SUPPRESSION peut rompre (aucun chemin
        ne re-parente un élément d'un lot vers un autre).
    ⏳ Reste dû : le manifeste ne sait pas encore DÉCLARER la forme directe, donc une app
    générée sur ce patron ne rebranchera pas l'invariant toute seule.
    """
    if not direct_fk and item_model not in SYNCED:
        SYNCED.append(item_model)
    name = item_model.__name__

    def _on_change(sender, instance, **kwargs):
        try:
            batch = getattr(instance, batch_attr, None)
        except Exception:
            batch = None  # parent déjà supprimé (cascade) → rien à recaler
        sync_batch_total(batch)

    if not direct_fk:
        post_save.connect(_on_change, sender=item_model, weak=False,
                          dispatch_uid=f'batchsync_save_{name}')
    post_delete.connect(_on_change, sender=item_model, weak=False,
                        dispatch_uid=f'batchsync_delete_{name}')
