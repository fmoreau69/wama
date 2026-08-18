"""
Avancement d'une tâche Celery LONGUE publié dans le cache Redis — brique COMMUNE.

Motif : passer par le cache plutôt que par l'`AsyncResult` permet de retrouver une
opération en cours après un simple F5 — le navigateur n'a plus le task_id. Né avec les
miroirs de sauvegarde (`run_mirror_job`, 2026-08), EXTRAIT ici au 2ᵉ consommateur
(installation de modèles proposés, 2026-08-18) conformément à la règle zéro-duplication :
le « state/task_id gagnent sur le payload » et la vérification « le cache peut survivre
à un worker tué » étaient en train d'être recopiés.

Côté navigateur, le pendant est la brique `WamaApp.Poller` (wama-app-base.js).
"""
from __future__ import annotations

TTL_DEFAUT = 24 * 3600


def publier_progression(cache_key: str, task_id, state: str, payload: dict,
                        ttl: int = TTL_DEFAUT) -> None:
    """
    Publie l'avancement d'une tâche dans le cache. `state`/`task_id` en DERNIER :
    ils doivent gagner sur le contenu du payload, jamais l'inverse (une clé homonyme
    dans le payload écraserait l'état publié).
    """
    from django.core.cache import cache
    cache.set(cache_key, dict(payload, state=state, task_id=task_id), ttl)


def progression_en_cours(cache_key: str):
    """
    La progression publiée SI la tâche est encore vivante, sinon None.

    Le cache peut survivre à un worker tué : on ne croit un état RUNNING que si Celery
    confirme que la tâche l'est aussi (PENDING/STARTED/RETRY). C'est la garde des vues
    `*_start` : « déjà en cours » ⇒ renvoyer l'état au lieu d'enfiler un doublon.
    """
    from celery.result import AsyncResult
    from django.core.cache import cache

    current = cache.get(cache_key)
    if not (current and current.get('state') == 'RUNNING'):
        return None
    task_id = current.get('task_id')
    if task_id and AsyncResult(task_id).state in ('PENDING', 'STARTED', 'RETRY'):
        return current
    return None
