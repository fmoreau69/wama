"""
WAMA — Tri + filtrage COMMUNS de la file unifiée (batches_list).

Extrait du pilote Transcriber (2026-06-29) pour héritage par toutes les apps.
Persisté en session (clés PARTAGÉES entre apps : la préférence de tri/filtre est
globale à WAMA — homogénéité UX, on retrouve le même ordre d'une app à l'autre).

Contrat d'entrée (structure batch unifiée transcriber/composer/synthesizer) :
    entry = {
        'obj': batch | None,     # .id, .total, .created_at — None si l'item est HORS LOT
                                 # (tri/filtre retombent alors sur `items`, cf. _cree_le/_total)
        'items': [...],
        'success_count': int,    # requis par le filtre
        'running_count': int,
        'failure_count': int,
        ...                      # champs propres à l'app, ignorés ici
    }

Usage (vue index) :
    from wama.common.utils.queue_view import apply_queue_sort_filter
    batches_list, q_sort, q_filter = apply_queue_sort_filter(
        request, batches_list, name_of=_name)   # _name(entry) -> str (tri 'name')
    # → passer q_sort / q_filter au template et inclure common/_queue_toolbar.html
"""
from datetime import datetime, timezone as dt_timezone


def apply_queue_sort_filter(request, batches_list, *, name_of):
    """Applique le tri + filtrage de file (persistés en session) et renvoie
    (batches_list, q_sort, q_filter). `name_of(entry)` fournit la clé du tri 'name'
    (spécifique app : nom de fichier, prompt…)."""
    # Défaut = CHRONOLOGIQUE récent (plus de « batchs d'abord » — décision 2026-06-29).
    q_sort = request.GET.get('sort') or request.session.get('q_sort') or 'recent'
    q_filter = request.GET.get('filter') or request.session.get('q_filter') or 'all'
    request.session['q_sort'] = q_sort
    request.session['q_filter'] = q_filter

    # `obj` est le LOT de l'entrée — et il vaut None pour un item ISOLÉ (hors lot). Le contrat
    # n'était écrit nulle part et la brique lisait `b['obj'].created_at` sans garde : la file
    # tombait en AttributeError dès qu'un item existait hors lot. Trouvé le 2026-08-22 sur la
    # jumelle converter_01, dont la vue générée crée des jobs isolés (son `upload` ne consolide
    # pas) — les apps en place ne le voyaient pas parce qu'elles consolident tout, y compris un
    # dépôt unique, en lot-de-1. Un défaut de brique COMMUNE, révélé par le bac à sable : il
    # frapperait n'importe quelle app générée. Les accesseurs ci-dessous retombent sur les
    # ITEMS, exactement comme le fait déjà la vue elle-même pour `is_group`
    # (`b.total if b else len(items)`).
    def _lot(b):
        return b.get('obj') if isinstance(b, dict) else getattr(b, 'obj', None)

    def _cree_le(b):
        o = _lot(b)
        d = getattr(o, 'created_at', None) if o is not None else None
        if d is None:
            items = (b.get('items') if isinstance(b, dict) else None) or []
            d = getattr(items[0], 'created_at', None) if items else None
        # Repli ULTIME : une date minimale AWARE (comparer naïf et aware lèverait TypeError).
        return d if d is not None else datetime.min.replace(tzinfo=dt_timezone.utc)

    def _total(b):
        o = _lot(b)
        t = getattr(o, 'total', None) if o is not None else None
        if t:
            return t
        items = (b.get('items') if isinstance(b, dict) else None) or []
        return len(items)

    def _matches(b, f):
        if f == 'running':
            return b['running_count'] > 0
        if f == 'failure':
            return b['failure_count'] > 0
        if f == 'success':
            return b['success_count'] > 0
        if f == 'draft':
            return (b['success_count'] + b['running_count'] + b['failure_count']) < _total(b)
        return True  # 'all'

    if q_filter != 'all':
        batches_list = [b for b in batches_list if _matches(b, q_filter)]

    _sorters = {
        'recent': (_cree_le, True),
        'oldest': (_cree_le, False),
        'name':   (name_of, False),
        # Groupé : type d'abord (batch vs card unique), chronologie récente en 2nd ordre.
        'batches_first': (lambda b: (0 if _total(b) > 1 else 1, -_cree_le(b).timestamp()), False),
        'singles_first': (lambda b: (0 if _total(b) == 1 else 1, -_cree_le(b).timestamp()), False),
    }
    _key, _rev = _sorters.get(q_sort, _sorters['recent'])
    batches_list.sort(key=_key, reverse=_rev)
    return batches_list, q_sort, q_filter
