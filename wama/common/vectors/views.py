"""API de la recherche de la file par CONTENU — `WAMA_MEMORY.md §7sexies`."""
from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.http import require_POST

#: Fenêtre pendant laquelle une indexation déjà demandée par une recherche n'est pas redemandée :
#: une frappe au clavier en émet plusieurs, une seule tâche suffit.
QUEUED_LOCK = 'common.index_media.queued'
QUEUED_LOCK_SECONDS = 120


@login_required
@require_POST
def api_queue_content_search(request):
    """CHERCHER PAR LE CONTENU dans une file — POST `{q, cards: [{surface, pk}…]}`.

    `cards` = les cards que la page montre (adresse lue sur leur aperçu commun, comme
    l'inspecteur). Rend les éléments dont une image répond à `q` (`media_index.search`, droits de
    lecture du compte appliqués) et, quand certains ne sont pas encore indexés, met leur
    indexation en tâche — le GESTE qui la déclenche (`WAMA_MEMORY §5bis` : jamais de chargement
    de modèle hors d'une action de l'utilisateur ou du lot de nuit)."""
    import json

    from django.core.cache import cache

    from wama.common.tasks import index_media_task
    from wama.common.vectors import media_index

    # JSON lu ici et non par `batch_views.read_settings_payload` : celui-ci lit des RÉGLAGES (forme
    # d'un formulaire) et réduit toute liste à son premier élément — `cards` en est une.
    try:
        payload = json.loads(request.body or b'{}')
    except (TypeError, ValueError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    cards = [(c.get('surface'), c.get('pk')) for c in (payload.get('cards') or [])
             if isinstance(c, dict)]
    result = media_index.search(request.user, str(payload.get('q') or ''), cards)
    queued = False
    if result['pending'] and cache.add(QUEUED_LOCK, 1, timeout=QUEUED_LOCK_SECONDS):
        index_media_task.delay(addresses=[list(a) for a in result['pending']])
        queued = True
    return JsonResponse({'hits': result['hits'], 'pending': len(result['pending']),
                         'indexed': result['indexed'], 'queued': queued,
                         'unavailable': bool(result.get('unavailable'))})
