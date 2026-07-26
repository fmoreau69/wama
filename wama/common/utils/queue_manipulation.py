"""
WAMA Common — Manipulation DIRECTE de la file (CARD_DESIGN §3bis) : vues génériques.

Fabrique les 4 endpoints de manipulation de batch — sortir une card d'un batch,
réordonner, déplacer dans un batch cible, consolider N cards en un batch —
généralisation des vues transcriber (seule app à les avoir, audit 2026-07-06).

Prérequis de convention (respectée par transcriber/composer/describer) :
  - batch.items       : related_name des items de liaison ;
  - work.batch_item   : reverse OneToOne de l'objet métier vers son item de liaison ;
  - item.row_index    : ordre dans le batch ;
  - signaux batch_sync branchés (recalage du total / purge du batch vidé à la
    suppression d'un item — ``register_batch_sync``).

Usage (urls.py de l'app) :
    from wama.common.utils.queue_manipulation import make_queue_manipulation_views
    _qm = make_queue_manipulation_views(work_model=Transcript, batch_model=BatchTranscript,
                                        item_model=BatchTranscriptItem, fk_name='transcript',
                                        get_user=_get_user)
    path('reorder/', _qm['reorder'], name='reorder'), ...

L'app peut ne consommer qu'une partie (ex. describer garde SON consolidate par nature).
"""

import json

from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from wama.common.utils.batch_common import wrap_in_batch, consolidate_into_batch


def make_queue_manipulation_views(*, work_model, batch_model, item_model, fk_name,
                                  get_user, item_extra=None):
    """Retourne {'remove_from_batch', 'reorder', 'move_to_batch', 'consolidate'} (vues Django).

    Args:
        fk_name    : nom de la FK métier sur le modèle de liaison ('transcript', 'generation'…).
        get_user   : callable(request) -> user (pattern anonyme inclus, propre à l'app).
        item_extra : dict|callable(work)->dict — champs supplémentaires du lien (cf. wrap_in_batch).
    """

    def _wrap(work):
        return wrap_in_batch(work, batch_model=batch_model, item_model=item_model,
                             fk_name=fk_name, item_extra=item_extra)

    @require_POST
    def remove_from_batch(request, pk: int):
        """Sort un élément de son batch → l'isole dans son propre batch-of-1."""
        user = get_user(request)
        work = get_object_or_404(work_model, pk=pk, user=user)
        item = getattr(work, 'batch_item', None)            # reverse OneToOne (None si hors batch)
        if item is None:
            return JsonResponse({'unwrapped': False, 'reason': 'pas dans un batch'}, status=400)
        if item.batch.total <= 1:
            return JsonResponse({'unwrapped': False, 'reason': 'déjà isolé'})
        item.delete()                                        # signal → recalc / suppression si vide
        _wrap(work)
        return JsonResponse({'unwrapped': True})

    @require_POST
    def reorder(request):
        """Réordonne les éléments d'un batch. POST : batch_id + order (ids CSV)."""
        user = get_user(request)
        batch = get_object_or_404(batch_model, pk=request.POST.get('batch_id'), user=user)
        order = [int(x) for x in (request.POST.get('order') or '').split(',') if x.strip().isdigit()]
        for idx, wid in enumerate(order):
            item_model.objects.filter(batch=batch, **{f'{fk_name}_id': wid}).update(row_index=idx)
        return JsonResponse({'reordered': True, 'count': len(order)})

    @require_POST
    def move_to_batch(request, pk: int):
        """Déplace un élément DANS un batch cible. POST : batch_id destination."""
        user = get_user(request)
        work = get_object_or_404(work_model, pk=pk, user=user)
        target = get_object_or_404(batch_model, pk=request.POST.get('batch_id'), user=user)
        item = getattr(work, 'batch_item', None)
        if item is not None and item.batch_id == target.id:
            return JsonResponse({'moved': False, 'reason': 'déjà dans ce batch'})
        if item is not None:
            item.delete()
        next_idx = (target.items.aggregate(m=Max('row_index'))['m'] or -1) + 1
        kwargs = {'batch': target, 'row_index': next_idx, fk_name: work}
        if item_extra:
            kwargs.update(item_extra(work) if callable(item_extra) else dict(item_extra))
        item_model.objects.create(**kwargs)
        return JsonResponse({'moved': True})

    @require_POST
    def consolidate(request):
        """Regroupe plusieurs éléments importés ensemble en UN batch-of-N.

        POST/JSON : ids (ordre d'import conservé). < 2 ids → no-op.
        Défait les batch-of-1 créés à l'upload puis crée le batch-of-N.
        """
        user = get_user(request)
        try:
            ids = json.loads(request.body or '{}').get('ids', [])
        except (ValueError, TypeError):
            ids = request.POST.getlist('ids[]') or request.POST.getlist('ids')
        ids = [int(i) for i in ids if str(i).isdigit()]

        works = list(work_model.objects.filter(id__in=ids, user=user))
        pos = {wid: p for p, wid in enumerate(ids)}
        works.sort(key=lambda w: pos.get(w.id, 0))
        if len(works) < 2:
            return JsonResponse({'consolidated': False})

        def _create(total):
            return batch_model.objects.create(user=user, total=total)

        def _link(batch, work, idx):
            kwargs = {'batch': batch, 'row_index': idx, fk_name: work}
            if item_extra:
                kwargs.update(item_extra(work) if callable(item_extra) else dict(item_extra))
            item_model.objects.create(**kwargs)

        def _unwrap(item_ids):
            # Supprime les batch-of-1 créés à l'upload (cascade sur leurs items ;
            # les objets métier ne sont pas supprimés).
            batch_model.objects.filter(
                user=user, total=1, **{f'items__{fk_name}_id__in': item_ids}
            ).distinct().delete()

        batch = consolidate_into_batch(works, create_batch=_create, link_item=_link,
                                       unwrap_singletons=_unwrap)
        return JsonResponse({'consolidated': True, 'batch_id': batch.id, 'count': len(works)})

    return {
        'remove_from_batch': remove_from_batch,
        'reorder': reorder,
        'move_to_batch': move_to_batch,
        'consolidate': consolidate,
    }


def make_queue_manipulation_views_direct(*, work_model, batch_model,
                                         batch_fk='batch', row_field='batch_row_index',
                                         get_user, batch_extra=None):
    """Variante FK-DIRECTE de ``make_queue_manipulation_views`` — pour les apps dont
    l'objet métier porte LUI-MÊME la FK batch + l'index de ligne (converter), sans
    modèle de liaison. Mêmes endpoints, mêmes contrats JSON que la fabrique liaison.

    Prérequis de convention (mode direct) :
      - work.<batch_fk>    : FK vers le batch, related_name ``items`` ;
      - work.<row_field>   : ordre dans le batch ;
      - batch.total        : recalé INLINE ici (pas de signaux batch_sync en direct).

    ⚠ La FK est souvent ``on_delete=CASCADE`` (converter) : un batch n'est JAMAIS
    supprimé tant qu'il a des items — on re-parente d'abord, on purge les vides après.

    Args:
        batch_extra : dict|callable(work)->dict — champs supplémentaires du batch
                      créé (ex. ``lambda j: {'media_type': j.media_type}``).
    """

    def _batch_kwargs(user, work, total):
        kw = {'user': user, 'total': total}
        if batch_extra:
            kw.update(batch_extra(work) if callable(batch_extra) else dict(batch_extra))
        return kw

    def _recalc(batch):
        """Recale total ; supprime le batch UNIQUEMENT s'il est vide."""
        if batch is None:
            return
        n = batch.items.count()
        if n == 0:
            batch.delete()
        elif batch.total != n:
            batch.total = n
            batch.save(update_fields=['total'])

    @require_POST
    def remove_from_batch(request, pk: int):
        """Sort un élément de son batch → l'isole dans son propre batch-of-1."""
        user = get_user(request)
        work = get_object_or_404(work_model, pk=pk, user=user)
        old = getattr(work, batch_fk, None)
        if old is None:
            return JsonResponse({'unwrapped': False, 'reason': 'pas dans un batch'}, status=400)
        if old.total <= 1:
            return JsonResponse({'unwrapped': False, 'reason': 'déjà isolé'})
        new = batch_model.objects.create(**_batch_kwargs(user, work, 1))
        setattr(work, batch_fk, new)
        setattr(work, row_field, 0)
        work.save(update_fields=[batch_fk, row_field])
        _recalc(old)
        return JsonResponse({'unwrapped': True})

    @require_POST
    def reorder(request):
        """Réordonne les éléments d'un batch. POST : batch_id + order (ids CSV)."""
        user = get_user(request)
        batch = get_object_or_404(batch_model, pk=request.POST.get('batch_id'), user=user)
        order = [int(x) for x in (request.POST.get('order') or '').split(',') if x.strip().isdigit()]
        for idx, wid in enumerate(order):
            work_model.objects.filter(pk=wid, user=user, **{batch_fk: batch}).update(**{row_field: idx})
        return JsonResponse({'reordered': True, 'count': len(order)})

    @require_POST
    def move_to_batch(request, pk: int):
        """Déplace un élément DANS un batch cible. POST : batch_id destination."""
        user = get_user(request)
        work = get_object_or_404(work_model, pk=pk, user=user)
        target = get_object_or_404(batch_model, pk=request.POST.get('batch_id'), user=user)
        old = getattr(work, batch_fk, None)
        if old is not None and old.id == target.id:
            return JsonResponse({'moved': False, 'reason': 'déjà dans ce batch'})
        next_idx = (target.items.aggregate(m=Max(row_field))['m'] or -1) + 1
        setattr(work, batch_fk, target)
        setattr(work, row_field, next_idx)
        work.save(update_fields=[batch_fk, row_field])
        _recalc(target)
        _recalc(old)
        return JsonResponse({'moved': True})

    @require_POST
    def consolidate(request):
        """Regroupe plusieurs éléments en UN batch-of-N (ordre des ids conservé).

        Re-parente d'abord, purge les anciens batches VIDÉS ensuite (jamais de
        delete d'un batch encore peuplé — cf. CASCADE).
        """
        user = get_user(request)
        try:
            ids = json.loads(request.body or '{}').get('ids', [])
        except (ValueError, TypeError):
            ids = request.POST.getlist('ids[]') or request.POST.getlist('ids')
        ids = [int(i) for i in ids if str(i).isdigit()]

        works = list(work_model.objects.filter(id__in=ids, user=user))
        pos = {wid: p for p, wid in enumerate(ids)}
        works.sort(key=lambda w: pos.get(w.id, 0))
        if len(works) < 2:
            return JsonResponse({'consolidated': False})

        old_ids = {getattr(w, f'{batch_fk}_id') for w in works} - {None}
        batch = batch_model.objects.create(**_batch_kwargs(user, works[0], len(works)))
        for idx, w in enumerate(works):
            setattr(w, batch_fk, batch)
            setattr(w, row_field, idx)
            w.save(update_fields=[batch_fk, row_field])
        for old in batch_model.objects.filter(id__in=old_ids):
            _recalc(old)
        return JsonResponse({'consolidated': True, 'batch_id': batch.id, 'count': len(works)})

    return {
        'remove_from_batch': remove_from_batch,
        'reorder': reorder,
        'move_to_batch': move_to_batch,
        'consolidate': consolidate,
    }
