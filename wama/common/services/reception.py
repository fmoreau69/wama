"""Le RANGEMENT d'une entrée reçue chez le destinataire — `WAMA_COLLABORATION §3bis.2` (2026-10-02).

Décision de Fabien (2026-09-30) : *une card reçue est indépendante dans SA file*. Le destinataire
la retire de sa file sans rien supprimer, l'y remet, et l'ordonne à sa façon — rien de tout cela
ne touche l'élément ni la file de son propriétaire.

La ligne (`common.ReceivedEntry`) ne porte AUCUN droit : avant chaque geste, on revérifie que
l'élément est VISIBLE par le destinataire (`scoping.listable_by`) et qu'il n'est PAS à lui
(`queue_duplication.is_received`). Ranger ce qu'on ne voit pas, ou ranger le sien par ce chemin,
est refusé — le sien se range par les gestes ordinaires de la file.

L'unité est l'ENTRÉE de file — le lot, ou la card sans lot (voir le modèle). Les constructeurs de
file (`batch_common.build_batches_list`, l'index du converter) lisent ces lignes une fois par page.
"""
from django.utils import timezone

from wama.common.models import ReceivedEntry


class NotReceived(Exception):
    """L'entrée n'est pas une entrée REÇUE par cet utilisateur (invisible pour lui, ou à lui)."""


def object_type_of(obj_or_model) -> str:
    return obj_or_model._meta.label


def _check_received(user, entry):
    from wama.common.utils.queue_duplication import is_received
    from wama.common.utils.scoping import listable_by
    model = type(entry)
    manager = model._default_manager
    if not hasattr(manager, 'visible_to'):
        raise NotReceived('élément non partageable')
    if not is_received(entry, user):
        raise NotReceived('cet élément est à vous')
    if not listable_by(manager.all(), user).filter(pk=entry.pk).exists():
        raise NotReceived('élément introuvable')


def _line(user, entry):
    line, _ = ReceivedEntry.objects.get_or_create(
        recipient=user, object_type=object_type_of(entry), object_id=entry.pk)
    return line


def hide(user, entry) -> ReceivedEntry:
    """Retire l'entrée reçue de la file de `user`. L'élément et la file du propriétaire : intacts."""
    _check_received(user, entry)
    line = _line(user, entry)
    if line.hidden_at is None:
        line.hidden_at = timezone.now()
        line.save(update_fields=['hidden_at'])
    return line


def show(user, entry) -> ReceivedEntry:
    """Remet dans la file de `user` une entrée reçue qu'il en avait retirée."""
    _check_received(user, entry)
    line = _line(user, entry)
    if line.hidden_at is not None:
        line.hidden_at = None
        line.save(update_fields=['hidden_at'])
    return line


def show_all(user, app_label: str) -> int:
    """Remet dans la file de `user` tout ce qu'il avait retiré dans une app. Rend le nombre."""
    return (ReceivedEntry.objects
            .filter(recipient=user, object_type__startswith=f'{app_label}.', hidden_at__isnull=False)
            .update(hidden_at=None))


def hidden_count(user, app_label: str) -> int:
    """Combien d'entrées reçues `user` a retirées de sa file dans cette app."""
    if not getattr(user, 'pk', None):
        return 0
    return ReceivedEntry.objects.filter(recipient=user, object_type__startswith=f'{app_label}.',
                                        hidden_at__isnull=False).count()


def lines_for(user, *models) -> dict:
    """{(object_type, object_id): ReceivedEntry} des lignes de `user` pour ces modèles d'entrée
    (le lot, et la card quand une entrée peut être sans lot) — UNE requête par page de file."""
    if not getattr(user, 'pk', None):
        return {}
    types = [object_type_of(m) for m in models]
    return {(line.object_type, line.object_id): line for line in
            ReceivedEntry.objects.filter(recipient=user, object_type__in=types)}


def entry_arrangement(user, entry, lines):
    """Ce que le RANGEMENT de `user` fait d'une entrée de sa file — la règle UNIQUE des trois
    constructeurs de file (`build_batches_list`, l'index du converter, l'index généré en FK directe).

    Rend None si l'entrée est REÇUE et retirée de sa file (à ne pas montrer) ; `{}` si elle est à
    lui ; sinon ce que sa ligne de file reçoit en plus : `received_from` (« reçue de … ») et SON
    ordre manuel `queue_index` (0 = jamais ordonné). `lines` vient de `lines_for`."""
    if getattr(entry, 'user_id', None) == getattr(user, 'pk', None):
        return {}
    line = lines.get((object_type_of(entry), entry.pk))
    if line is not None and line.hidden_at is not None:
        return None
    return {'received_from': owner_label(entry),
            'queue_index': line.queue_index if line is not None else 0}


def set_order(user, model, ordered_ids) -> int:
    """Pose l'ordre MANUEL de `user` sur ses entrées REÇUES (celles qu'il voit et qui ne sont pas à
    lui), dans l'ordre donné, en 1..N comme `reorder_queue` — jamais 0, qui veut dire « jamais
    ordonné ». Rend le nombre d'entrées reçues ordonnées. Un id étranger ou invisible est IGNORÉ."""
    from wama.common.utils.scoping import listable_by
    manager = model._default_manager
    if not hasattr(manager, 'visible_to') or not ordered_ids:
        return 0
    received = set(listable_by(manager.all(), user).filter(id__in=ordered_ids)
                   .exclude(user=user).values_list('id', flat=True))
    n = 0
    for idx, pk in enumerate(ordered_ids, start=1):
        if pk in received:
            ReceivedEntry.objects.update_or_create(
                recipient=user, object_type=object_type_of(model), object_id=pk,
                defaults={'queue_index': idx})
            n += 1
    return n


def owner_label(entry) -> str:
    """Le nom à afficher pour « reçue de … » : celui du propriétaire de l'entrée.

    Il est écrit dans une chaîne CSS (`--wama-received`, `_queue_entry.html`) : ni guillemet ni
    barre oblique inverse n'y entrent — l'apostrophe devient sa forme typographique."""
    owner = getattr(entry, 'user', None)
    if owner is None:
        return ''
    name = owner.get_full_name() or owner.username
    return name.replace("'", '’').replace('"', '').replace('\\', '')
