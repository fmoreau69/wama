"""
Les RÉGLAGES D'UN LOT — ce que la card MÈRE tient pour référence (`MODES_QUEUE_UX §5ter`,
`WAMA_APP_GENERATION_ROUTE §10.6` 5.3 ; marche P5, 2026-10-03).

D'OÙ ÇA VIENT. Un lot n'a jamais porté de réglages : sa modale ⚙ les POSAIT sur toutes les
filles et ne gardait rien. Deux gestes décidés le 2026-08-25 restaient donc impossibles :
  • ↑ PROMOUVOIR — depuis une fille, faire remonter SES réglages à la mère, qui les applique à
    tout le lot (n'importe quelle card peut servir de référence ; régler plusieurs filles en
    parallèle, écouter, promouvoir la gagnante) ;
  • ↓ RÉALIGNER — depuis la mère, remettre toutes les filles sur la référence (effacer les
    écarts individuels).
Le second exige une MÉMOIRE : c'est elle. UNE ligne par lot (`BatchSettings`), réécrite à
chaque geste de la mère — sa ⚙ comme une promotion. Une table commune, adressée comme
`ProcessRun` (app + type + identifiant), plutôt qu'une colonne sur les dix modèles de lot.

CE QUE LA RÉFÉRENCE CONTIENT. La charge utile promue est le PIPELINE de la card (`§10.6` 5.3) :
pour une app Médias, ses réglages — lus de son SCHÉMA (`revisions.settings_snapshot`, la règle
que la révision applique déjà), jamais une liste de champs écrite par app ; pour le monde Data,
son protocole (à venir : `promote_payload` déclaré). Les deux sont deux cas du même objet.

CE QUE CE MODULE NE FAIT PAS. Il n'applique rien : poser des réglages sur les filles reste la
fabrique des vues de lot (`batch_views.make_batch_views`), par la fonction de réglage de l'app
(`apply_settings`) — la même que sa route d'élément. Il ne lève jamais.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def address(batch) -> dict:
    """Adresse d'un lot : `{app, batch_type, batch_id}` — dérivée du lot SEUL (convention de
    `ProcessRun`)."""
    meta = batch._meta
    return {'app': meta.app_label, 'batch_type': meta.object_name, 'batch_id': str(batch.pk)}


def stored(batch) -> dict | None:
    """Les réglages de référence du lot, ou None s'il n'en a jamais reçu."""
    from wama.common.models import BatchSettings
    row = BatchSettings.objects.filter(**address(batch)).first()
    return dict(row.settings or {}) if row is not None else None


def remember(batch, settings: dict, *, source_id='') -> None:
    """La mère RETIENT ces réglages comme référence — réécrits, jamais empilés. `source_id` : la
    fille promue, quand il y en a une (vide pour la ⚙ de la mère)."""
    from wama.common.models import BatchSettings
    try:
        BatchSettings.objects.update_or_create(
            **address(batch),
            defaults={'settings': dict(settings or {}), 'source_object_id': str(source_id or '')})
    except Exception:
        logger.warning("[batch_settings] référence du lot %s non écrite", address(batch),
                       exc_info=True)


def forget(batch) -> int:
    """Le lot disparaît : sa référence aussi. Rend le nombre de lignes retirées."""
    from wama.common.models import BatchSettings
    try:
        deleted, _detail = BatchSettings.objects.filter(**address(batch)).delete()
        return deleted
    except Exception:
        logger.warning("[batch_settings] référence du lot %s non retirée", address(batch),
                       exc_info=True)
        return 0


def references_for(batch_model, batch_ids) -> dict:
    """`{id de lot (int): id de la fille promue ('' pour la ⚙ de la mère)}` des lots de
    `batch_ids` qui ONT une référence — UNE requête pour une page de file
    (`build_batches_list`), c'est ce qui dit à la card mère si « ↓ réaligner » a un sens.
    `{}` sans table (migration pas encore passée) : la file se rend quand même."""
    from wama.common.models import BatchSettings
    ids = [str(i) for i in (batch_ids or ())]
    if not ids:
        return {}
    meta = batch_model._meta
    try:
        rows = (BatchSettings.objects
                .filter(app=meta.app_label, batch_type=meta.object_name, batch_id__in=ids)
                .values_list('batch_id', 'source_object_id'))
        return {int(b): s for b, s in rows}
    except Exception:
        logger.warning("[batch_settings] références de %s illisibles", meta.label, exc_info=True)
        return {}


def settings_of(item, schema=None) -> dict:
    """Les réglages d'UNE fille, prêts à être promus : ceux de son schéma d'app (contexte
    `item`), lus par la règle de la révision — restreints aux noms de `schema` quand il est
    donné (la fabrique connaît le sien). `{}` sans schéma déclaré."""
    from wama.common.services.revisions import settings_snapshot
    taken = settings_snapshot(item._meta.app_label, item)
    if schema:
        names = {p.get('name') for p in schema if isinstance(p, dict) and p.get('name')}
        taken = {k: v for k, v in taken.items() if k in names}
    return taken
