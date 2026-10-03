"""VERROU DOUX sur une card partagée en collaboration — E4 (décision de Fabien, 2026-10-03).

*« Verrou doux + trace : "en cours d'édition par X", qui expire tout seul ; une relance est refusée
si la card tourne déjà ; le dernier enregistrement gagne, tracé au journal. »*

Doux : il ne REFUSE rien — il DIT, à celui qui ouvre les réglages, que quelqu'un d'autre les a
ouverts il y a moins de `TTL` secondes. Rien n'est écrit en base : un verrou qui survivrait à son
porteur (onglet fermé, réseau coupé) serait pire que pas de verrou ; le cache expire seul, et la
page le rafraîchit tant que la modale est ouverte. Le cache est Redis (`settings.CACHES`) : il est
partagé entre les processus du serveur, ce qu'un verrou exige.

La trace (« le dernier enregistrement gagne, TRACÉ ») est au journal des faits (`RunOutcome`) —
le journal de WAMA, pas un second (`mecanismes` : « un journal, pas deux »).
"""
from django.core.cache import cache

#: Durée de vie d'une prise, en secondes ; la page la renouvelle à mi-parcours.
TTL = 120


def _key(obj):
    return f'wama:edit-lock:{obj._meta.label}:{obj.pk}'


def holder(obj):
    """{'user_id', 'name'} de celui qui tient le verrou, ou None."""
    return cache.get(_key(obj))


def acquire(user, obj) -> dict:
    """Prend (ou renouvelle) le verrou si personne d'AUTRE ne le tient. Rend
    `{'held_by_other': bool, 'name': ...}` — `name` est l'autre porteur s'il y en a un."""
    current = holder(obj)
    if current and current.get('user_id') != user.pk:
        return {'held_by_other': True, 'name': current.get('name', '')}
    cache.set(_key(obj), {'user_id': user.pk, 'name': user.get_full_name() or user.username}, TTL)
    return {'held_by_other': False, 'name': ''}


def release(user, obj) -> None:
    """Rend le verrou s'il est à `user` (jamais celui d'un autre)."""
    current = holder(obj)
    if current and current.get('user_id') == user.pk:
        cache.delete(_key(obj))
