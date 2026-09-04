"""
WAMA — Tri + filtrage COMMUNS de la file unifiée (batches_list).

Extrait du pilote Transcriber (2026-06-29) pour héritage par toutes les apps.
Persisté en session (clés PARTAGÉES entre apps : la préférence de tri/filtre est
globale à WAMA — homogénéité UX, on retrouve le même ordre d'une app à l'autre).

Contrat d'entrée (structure batch unifiée transcriber/composer/synthesizer) :
    entry = {
        'obj': batch,            # .id, .total, .created_at
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


def apply_queue_sort_filter(request, batches_list, *, name_of):
    """Applique le tri + filtrage de file (persistés en session) et renvoie
    (batches_list, q_sort, q_filter). `name_of(entry)` fournit la clé du tri 'name'
    (spécifique app : nom de fichier, prompt…)."""
    # Défaut = CHRONOLOGIQUE récent (plus de « batchs d'abord » — décision 2026-06-29).
    q_sort = request.GET.get('sort') or request.session.get('q_sort') or 'recent'
    q_filter = request.GET.get('filter') or request.session.get('q_filter') or 'all'
    request.session['q_sort'] = q_sort
    request.session['q_filter'] = q_filter

    def _matches(b, f):
        if f == 'running':
            return b['running_count'] > 0
        if f == 'failure':
            return b['failure_count'] > 0
        if f == 'success':
            return b['success_count'] > 0
        # AWAITING_RESOURCES (02/09) : filtrable À PART — cet état appelle un geste
        # (baisser le curseur de qualité, ou attendre), le noyer dans « Brouillon »
        # le rendait introuvable. `.get()` : un batch construit hors de la brique
        # commune (compteur absent) ne fait pas tomber la file.
        if f == 'awaiting':
            return b.get('awaiting_count', 0) > 0
        if f == 'draft':
            return (b['success_count'] + b['running_count'] + b['failure_count']) < b['obj'].total
        return True  # 'all'

    if q_filter != 'all':
        batches_list = [b for b in batches_list if _matches(b, q_filter)]

    _sorters = {
        'recent': (lambda b: b['obj'].created_at, True),
        'oldest': (lambda b: b['obj'].created_at, False),
        'name':   (name_of, False),
        # Groupé : type d'abord (batch vs card unique), chronologie récente en 2nd ordre.
        'batches_first': (lambda b: (0 if b['obj'].total > 1 else 1, -b['obj'].created_at.timestamp()), False),
        'singles_first': (lambda b: (0 if b['obj'].total == 1 else 1, -b['obj'].created_at.timestamp()), False),
        # MANUEL — l'ordre que l'utilisateur a posé au drag (CARD_DESIGN §3bis). C'est le seul
        # tri qui LIT une colonne au lieu de la calculer : `QueueOrderMixin.queue_index`.
        #
        # `queue_index == 0` veut dire « jamais ordonné à la main » et passe EN TÊTE, par récence
        # — donc une file jamais manipulée s'affiche exactement comme en tri `recent`, et un
        # import arrivé après un classement manuel apparaît en haut plutôt qu'au milieu d'un
        # ordre qu'il n'a pas connu. `reorder_queue` écrit 1..N, jamais 0.
        #
        # ⚠ `getattr` et non `b['obj'].queue_index` : ce tri doit rester sûr pour une file
        # construite hors du contrat commun (monde Data, page de démo), sinon choisir « Manuel »
        # une fois ferait tomber la file en 500 dans TOUTE app dont le batch n'a pas le mixin —
        # et le tri est persisté en SESSION, donc l'erreur suivrait l'utilisateur d'app en app.
        'manual': (lambda b: (getattr(b['obj'], 'queue_index', 0) or 0,
                              -b['obj'].created_at.timestamp()), False),
    }
    _key, _rev = _sorters.get(q_sort, _sorters['recent'])
    batches_list.sort(key=_key, reverse=_rev)
    return batches_list, q_sort, q_filter
