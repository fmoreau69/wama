"""
WAMA Common — Manipulation DIRECTE de la file (CARD_DESIGN §3bis) : vues génériques.

Fabrique les 5 endpoints de manipulation de file — sortir une card d'un batch,
réordonner DANS un batch, déplacer dans un batch cible, consolider N cards en un batch,
et ordonner les entrées de la file elle-même —
généralisation des vues transcriber (seule app à les avoir, audit 2026-07-06).

⚠ Le 5ᵉ (`reorder_queue`) est arrivé le 2026-09-04, avec l'UI de drag&drop. Les 4 premiers
datent du 2026-06-29 et la roadmap en a conclu pendant deux mois qu'il ne « restait que
l'UI » : c'était faux, il manquait AUSSI l'ordre de niveau supérieur — colonne comprise
(`QueueOrderMixin`). *Un backend complet pour le geste A ne dit rien du geste B.*

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

══ DEUX OPÉRATIONS, DEUX NOMS : `consolidate` vs `merge` (2026-09-04) ══════════════════════

Elles prennent les mêmes ids et paraissent identiques. Elles ne le sont pas, et les confondre
produit un défaut SILENCIEUX — mesuré par le test le jour même :

  `consolidate` = « range ces éléments importés ensemble », PAR NATURE
      (`group_into_batches_by_nature` sur le `group_key` déclaré) : trois images et deux vidéos
      donnent DEUX lots. C'est le bon comportement à l'import — on vient de déposer un
      dossier mélangé, on veut qu'il se range. (Cinq apps le redéfinissaient pour cela jusqu'au
      2026-10-16 : la fabrique le fait désormais, cf. plus bas.)

  `merge` = « fusionne ces éléments en UN lot ». C'est le geste du glisser-déposer : on a
      visé une card précise. Si les natures ne cohabitent pas, la réponse est un REFUS
      (409 + motif), jamais un rangement.

Router le drag&drop sur `consolidate` semblait gratuit — même signature, même effet apparent.
Le résultat réel, dans les cinq apps à consolidate local : déposer une vidéo sur une image
rendait `{"consolidated": true}` après avoir créé deux lots-de-1… c'est-à-dire **rien de
visible**, avec un accusé de succès. Le pire des retours.

`merge` est donc rendu par la fabrique et **jamais redéfini par une app** — c'est ce qui
garantit qu'il reste strict partout.

══ LE REGROUPEMENT À L'ARRIVÉE EST COMMUN (2026-10-16, demande de Fabien) ══════════════════════

Jusque-là, `consolidate` de la fabrique ÉTAIT `merge` (strict) : quatre apps le redéfinissaient
pour ranger par nature (anonymizer, describer, enhancer ×2, converter), le synthesizer pour poser
le nom de sortie de sa liaison, et l'import du gestionnaire de fichiers gardait une liste écrite
à la main de SIX helpers `consolidate_*_into_batches` — imager et synthesizer, absents de la
liste, recevaient un envoi de N fichiers en N cards. Le besoin est UN : des éléments arrivés
ensemble forment un lot par nature, et la fabrique connaît déjà tout ce qu'il faut — le modèle
de lot, la liaison, `group_key` (la nature, jumelle de l'import), `batch_extra`, `item_extra`.

D'où `consolidate_arrival(modèle, ids, user)` : chaque fabrique INSCRIT son regroupement pour son
modèle d'élément, et tout chemin d'arrivée l'appelle — la vue `consolidate` (dépôt de N fichiers),
l'import du gestionnaire (« Envoyer vers », dossier, sélection), un fichier de lot. Une app
nouvelle, ou une jumelle générée, est couverte dès qu'elle déclare sa fabrique.
"""

import json

from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from wama.common.utils.batch_common import (attach_to_batch, consolidate_into_batch,
                                            delete_singleton_batches, group_into_batches_by_nature,
                                            load_in_import_order, wrap_in_batch)

#: Le regroupement À L'ARRIVÉE de chaque modèle d'élément, inscrit par sa fabrique.
_ARRIVALS = {}


def consolidate_arrival(work_model, ids, user) -> list:
    """Range des éléments arrivés ENSEMBLE (un dépôt, un import, un fichier de lot) : un lot PAR
    NATURE (`group_key` déclaré à la fabrique ; aucune nature = un seul lot), dans l'ordre des
    `ids` ; un élément seul est rangé dans son lot d'un. Rend les lots créés.

    La déclaration est celle que l'app donne à `make_queue_manipulation_views[_direct]` : la vue
    qui la porte est importée si besoin (un worker, l'assistant n'ont pas chargé les URLs)."""
    arrive = _ARRIVALS.get(work_model)
    if arrive is None:
        import importlib
        from django.apps import apps as django_apps
        importlib.import_module(f'{django_apps.get_app_config(work_model._meta.app_label).name}.views')
        arrive = _ARRIVALS.get(work_model)
    if arrive is None:
        raise LookupError(f"{work_model._meta.label} : aucune fabrique de file déclarée")
    return arrive(list(ids or []), user)


def _representatives(works, nature_of) -> dict:
    """Le premier élément de chaque nature — celui dont `batch_extra` tire les champs du lot."""
    firsts = {}
    for work in works:
        firsts.setdefault(nature_of(work), work)
    return firsts


def ids_from_request(request):
    """Identifiants postés — quelle que soit la FORME de la requête.

    ⚠ Ne JAMAIS toucher `request.body` sans avoir vérifié le type de contenu. Sur un POST
    **multipart** (ce qu'envoie tout `FormData`), Django a déjà consommé le flux pour peupler
    `request.POST`, et `request.body` lève alors `RawPostDataException` — qui n'est ni
    `ValueError` ni `TypeError`, donc que le `try/except` d'origine ne rattrapait pas. La vue
    partait en 500 dès qu'un navigateur l'appelait.

    Pourquoi ça n'avait pas été vu : c'est le middleware CSRF qui consomme le flux (il lit
    `request.POST` sur tout POST) — et le client de test Django ne l'applique pas, donc
    `request.body` y reste lisible. Le défaut ne se manifeste QUE depuis un vrai navigateur.
    Mesuré le 2026-08-22 au smoke Playwright de converter_01 (import multi-fichiers).

    ⚠⚠ RÉCIDIVE le 2026-09-07 : cette garde vivait ICI (fabrique commune) pendant que **quatre
    vues `consolidate` propres aux apps** (describer, synthesizer, enhancer ×2) gardaient le
    `try/except` d'origine — invisible tant que leur front postait du JSON. Le jour où la brique
    d'import commune (`WamaImport`, FormData) les a appelées, le lot de 2 fichiers a cessé de se
    former, en 500, sur les trois apps portées. « Une garde se pose avec ses JUMEAUX » : le
    lecteur est désormais PUBLIC et importé par ces vues — plus aucune ne lit `request.body`.
    Nom anglais parce qu'IMPORTÉ (règle de nommage). Le paramètre `field` (contrat historique
    `job_ids` du converter) et l'alias français `_ids_de_la_requete` sont retirés le 2026-10-17 :
    le converter lit `ids` depuis que sa `consolidate` est celle de la fabrique (R134), et l'alias
    n'a jamais eu de consommateur.

    Formes acceptées : JSON `{"ids": [...]}`, et champs répétés `ids` ou `ids[]`.
    """
    if (request.content_type or '').startswith('application/json'):
        try:
            return [int(i) for i in (json.loads(request.body or '{}').get('ids') or [])
                    if str(i).isdigit()]
        except (ValueError, TypeError):
            return []
    raw = request.POST.getlist('ids[]') or request.POST.getlist('ids')
    return [int(i) for i in raw if str(i).isdigit()]


def _refus_de_groupe(group_key, work, membres):
    """Le déplacement est-il REFUSÉ ? Retourne le motif, ou None si c'est permis.

    ⚠ Ce garde-fou est né avec le drag&drop (2026-09-04), et il n'est pas décoratif : DEUX
    apps groupent leurs lots **par nature** — converter (`ConversionBatch.media_type`, un lot
    = un format de sortie) et anonymizer (image / vidéo / audio). Leurs `move_to_batch` et
    `consolidate` étaient exposés SANS aucune vérification depuis le 2026-06-29 : glisser une
    vidéo dans un lot d'images produisait un lot incohérent, et le lot entier partait ensuite
    avec le mauvais réglage de sortie.

    Le défaut n'était pas visible parce que rien n'appelait ces endpoints — l'UI n'existait
    pas. *Une route sans appelant ne prouve rien sur sa solidité ; la construire, c'est la
    mettre à l'épreuve pour la première fois.*

    `group_key(work) -> hashable | None` est DÉCLARÉ par l'app (philosophie WAMA : une
    spécificité se déclare, elle ne se code pas en dur dans le commun). Non déclaré → aucune
    contrainte, ce qui est le bon défaut pour les 8 apps dont un lot est homogène par
    construction.
    """
    if group_key is None:
        return None
    k = group_key(work)
    for m in membres:
        if m is None:
            continue
        autre = group_key(m)
        if autre is not None and k is not None and autre != k:
            return f"nature différente ({k} vs {autre})"
    return None


def _make_reorder_queue(*, batch_model, get_user):
    """Vue `reorder_queue` — ordre MANUEL des entrées de file (niveau supérieur).

    Commune aux deux fabriques : l'entrée de file est le BATCH dans les deux modes (liaison
    comme FK directe), donc l'ordre ne dépend ni du modèle de liaison ni de la FK métier.

    POST : `order` = ids de BATCH, CSV, dans l'ordre d'affichage voulu.

    Écrit `1..N` et jamais 0 — cf. `QueueOrderMixin` : 0 signifie « jamais ordonné », et le
    tri manuel place ces entrées en tête par récence. Le client envoie TOUTES les entrées
    qu'il affiche, pas seulement celles qui ont bougé : c'est ce qui rend l'opération
    idempotente et insensible à un filtre de statut actif (les entrées masquées gardent leur
    index et se replacent quand le filtre tombe).

    ⚠ `filter(user=…)` puis boucle, jamais `get_object_or_404` par id : un id étranger dans la
    liste ne doit pas faire échouer le classement des autres — il doit être IGNORÉ. Un drag
    n'est pas une opération à laquelle on refuse tout parce qu'une ligne a été supprimée dans
    un autre onglet entretemps.
    """

    @require_POST
    def reorder_queue(request):
        user = get_user(request)
        order = [int(x) for x in (request.POST.get('order') or '').split(',') if x.strip().isdigit()]
        if not order:
            return JsonResponse({'reordered': False, 'reason': 'ordre vide'}, status=400)
        connus = set(batch_model.objects.filter(id__in=order, user=user).values_list('id', flat=True))
        n = 0
        for idx, bid in enumerate(order, start=1):
            if bid in connus:
                batch_model.objects.filter(pk=bid, user=user).update(queue_index=idx)
                n += 1
        # Les entrées REÇUES de la même liste (2026-10-02, `WAMA_COLLABORATION §3bis.2`) : leur
        # place va dans la ligne de rangement du destinataire, à la position qu'elles occupent dans
        # CETTE liste — l'ordre du lot, lui, reste celui de son propriétaire.
        from wama.common.services.reception import set_order
        n += set_order(user, batch_model, order)
        return JsonResponse({'reordered': True, 'count': n})

    return reorder_queue


def make_queue_manipulation_views(*, work_model, batch_model, item_model, fk_name,
                                  get_user, item_extra=None, batch_extra=None,
                                  group_key=None):
    """Retourne {'remove_from_batch', 'reorder', 'reorder_queue', 'move_to_batch',
    'consolidate'} (vues Django).

    Args:
        fk_name     : nom de la FK métier sur le modèle de liaison ('transcript', 'generation'…).
        get_user    : callable(request) -> user (pattern anonyme inclus, propre à l'app).
        item_extra  : dict|callable(work)->dict — champs supplémentaires du LIEN (cf. wrap_in_batch).
        batch_extra : dict|callable(work)->dict — champs supplémentaires du BATCH créé lors
                      d'un `remove_from_batch` (ex. imager : `domain`, sa file étant scopée
                      par onglet — sans ça une vidéo isolée retombait dans l'onglet Images).
        group_key   : callable(work)->hashable|None — deux éléments ne peuvent cohabiter dans un
                      lot que s'ils rendent la MÊME clé. Non déclaré = aucune contrainte.
                      Voir `_refus_de_groupe`.
    """

    def _wrap(work):
        return wrap_in_batch(work, batch_model=batch_model, item_model=item_model,
                             fk_name=fk_name, item_extra=item_extra, batch_extra=batch_extra)

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
        motif = _refus_de_groupe(
            group_key, work,
            [getattr(i, fk_name, None) for i in target.items.all()])
        if motif:
            return JsonResponse({'moved': False, 'reason': motif}, status=409)
        if item is not None:
            item.delete()
        next_idx = (target.items.aggregate(m=Max('row_index'))['m'] or -1) + 1
        attach_to_batch(work, target, next_idx, item_model=item_model, fk_name=fk_name,
                        item_extra=item_extra)
        return JsonResponse({'moved': True})

    def _batch_kwargs(user, work, total):
        kw = {'user': user, 'total': total}
        if batch_extra:
            kw.update(batch_extra(work) if callable(batch_extra) else dict(batch_extra))
        return kw

    def _link(batch, work, idx):
        attach_to_batch(work, batch, idx, item_model=item_model, fk_name=fk_name,
                        item_extra=item_extra)

    def _unwrap(user):
        # Supprime les lots d'UN créés au dépôt (les objets métier survivent).
        return lambda item_ids: delete_singleton_batches(batch_model, fk_name, user, item_ids)

    def arrival(ids, user):
        """Le regroupement À L'ARRIVÉE de ce modèle (`consolidate_arrival`)."""
        works = load_in_import_order(work_model, ids, user)
        if not works:
            return []
        nature_of = group_key or (lambda _work: '')
        firsts = _representatives(works, nature_of)
        return group_into_batches_by_nature(
            works, nature_of=nature_of,
            create_batch=lambda nature, total: batch_model.objects.create(
                **_batch_kwargs(user, firsts[nature], total)),
            link_item=_link, unwrap_singletons=_unwrap(user))

    _ARRIVALS[work_model] = arrival

    @require_POST
    def consolidate(request):
        """« Range ces éléments importés ensemble » — un lot PAR NATURE (`consolidate_arrival`).

        POST/JSON : ids (ordre d'import conservé). < 2 éléments → no-op. Défait les lots d'un
        créés au dépôt puis crée les lots. Jamais un refus : c'est `merge` qui refuse.
        """
        user = get_user(request)
        ids = ids_from_request(request)
        if len(load_in_import_order(work_model, ids, user)) < 2:
            return JsonResponse({'consolidated': False})
        batches = arrival(ids, user)
        return JsonResponse({'consolidated': True, 'batch_ids': [b.id for b in batches],
                             'batch_id': batches[0].id, 'count': sum(b.total for b in batches)})

    @require_POST
    def merge(request):
        """FUSIONNE ces éléments en UN lot — le geste du glisser-déposer : des natures qui ne
        cohabitent pas sont REFUSÉES (409 + motif), jamais rangées.

        POST/JSON : ids (ordre conservé). < 2 ids → no-op.
        """
        user = get_user(request)
        ids = ids_from_request(request)

        works = load_in_import_order(work_model, ids, user)
        if len(works) < 2:
            return JsonResponse({'consolidated': False})
        motif = _refus_de_groupe(group_key, works[0], works[1:])
        if motif:
            return JsonResponse({'consolidated': False, 'reason': motif}, status=409)
        # Les éléments fusionnés appartiennent à la MÊME surface de file (on fusionne une
        # sélection d'un onglet) : le premier porte donc les champs du lot.
        batch = consolidate_into_batch(
            works, create_batch=lambda total: batch_model.objects.create(
                **_batch_kwargs(user, works[0], total)),
            link_item=_link, unwrap_singletons=_unwrap(user))
        return JsonResponse({'consolidated': True, 'batch_id': batch.id, 'count': len(works)})

    return {
        'remove_from_batch': remove_from_batch,
        'reorder': reorder,
        'reorder_queue': _make_reorder_queue(batch_model=batch_model, get_user=get_user),
        'move_to_batch': move_to_batch,
        'consolidate': consolidate,
        # `merge` : la fusion STRICTE, que les apps ne redéfinissent jamais. Voir le bloc
        # « DEUX OPÉRATIONS, DEUX NOMS » en tête de module.
        'merge': merge,
    }


def make_queue_manipulation_views_direct(*, work_model, batch_model,
                                         batch_fk='batch', row_field='batch_row_index',
                                         get_user, batch_extra=None, group_key=None):
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
        group_key   : callable(work)->hashable|None — contrainte de cohabitation dans un lot.
                      Voir `_refus_de_groupe`. ⚠ Une app qui passe `batch_extra` pour figer une
                      NATURE sur le lot doit presque toujours passer le `group_key` jumeau :
                      sans lui, `batch_extra` décide de la nature à la création et plus rien ne
                      la défend ensuite.
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
        attach_to_batch(work, new, 0, batch_attr=batch_fk, row_field=row_field)
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
        motif = _refus_de_groupe(group_key, work, list(target.items.all()))
        if motif:
            return JsonResponse({'moved': False, 'reason': motif}, status=409)
        next_idx = (target.items.aggregate(m=Max(row_field))['m'] or -1) + 1
        attach_to_batch(work, target, next_idx, batch_attr=batch_fk, row_field=row_field)
        _recalc(target)
        _recalc(old)
        return JsonResponse({'moved': True})

    def _link(batch, work, idx):
        attach_to_batch(work, batch, idx, batch_attr=batch_fk, row_field=row_field)

    def _purge(old_ids):
        # Re-parenter d'abord, purger les anciens lots VIDÉS ensuite — jamais la suppression
        # d'un lot encore peuplé (cf. CASCADE).
        for old in batch_model.objects.filter(id__in=old_ids):
            _recalc(old)

    def arrival(ids, user):
        """Le regroupement À L'ARRIVÉE de ce modèle (`consolidate_arrival`)."""
        works = load_in_import_order(work_model, ids, user)
        if not works:
            return []
        nature_of = group_key or (lambda _work: '')
        firsts = _representatives(works, nature_of)
        old_ids = {getattr(w, f'{batch_fk}_id') for w in works} - {None}
        batches = group_into_batches_by_nature(
            works, nature_of=nature_of,
            create_batch=lambda nature, total: batch_model.objects.create(
                **_batch_kwargs(user, firsts[nature], total)),
            link_item=_link)
        _purge(old_ids)
        return batches

    _ARRIVALS[work_model] = arrival

    @require_POST
    def consolidate(request):
        """« Range ces éléments importés ensemble » — un lot PAR NATURE (`consolidate_arrival`).
        < 2 éléments → no-op. Jamais un refus : c'est `merge` qui refuse."""
        user = get_user(request)
        ids = ids_from_request(request)
        if len(load_in_import_order(work_model, ids, user)) < 2:
            return JsonResponse({'consolidated': False})
        batches = arrival(ids, user)
        return JsonResponse({'consolidated': True, 'batch_ids': [b.id for b in batches],
                             'batch_id': batches[0].id, 'count': sum(b.total for b in batches)})

    @require_POST
    def merge(request):
        """FUSIONNE ces éléments en UN lot (ordre des ids conservé) — le geste du glisser-déposer :
        des natures qui ne cohabitent pas sont REFUSÉES (409 + motif)."""
        user = get_user(request)
        ids = ids_from_request(request)

        works = load_in_import_order(work_model, ids, user)
        if len(works) < 2:
            return JsonResponse({'consolidated': False})
        motif = _refus_de_groupe(group_key, works[0], works[1:])
        if motif:
            return JsonResponse({'consolidated': False, 'reason': motif}, status=409)

        old_ids = {getattr(w, f'{batch_fk}_id') for w in works} - {None}
        batch = batch_model.objects.create(**_batch_kwargs(user, works[0], len(works)))
        for idx, w in enumerate(works):
            _link(batch, w, idx)
        _purge(old_ids)
        return JsonResponse({'consolidated': True, 'batch_id': batch.id, 'count': len(works)})

    return {
        'remove_from_batch': remove_from_batch,
        'reorder': reorder,
        'reorder_queue': _make_reorder_queue(batch_model=batch_model, get_user=get_user),
        'move_to_batch': move_to_batch,
        'consolidate': consolidate,
        # `merge` : la fusion STRICTE, que les apps ne redéfinissent jamais. Voir le bloc
        # « DEUX OPÉRATIONS, DEUX NOMS » en tête de module.
        'merge': merge,
    }
