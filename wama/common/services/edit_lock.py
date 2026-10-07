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


# ── ENREGISTREMENT PRÉPARÉ SUR UN ÉTAT PÉRIMÉ (2026-10-07, marche 1 du conflit, GO de Fabien) ──
# `WAMA_COLLABORATION §2.4` : *« un enregistrement dit sur quelle version il a été préparé ; si
# quelqu'un a enregistré entre-temps, le conflit est montré, jamais écrasé »*. Cette marche-ci le
# REFUSE (409) au lieu d'écraser en silence ; MONTRER la différence et laisser choisir attend les
# révisions sur tout le parc (marche 8a). Cas vécu qui l'a déclenchée : deux personnes corrigent
# la même transcription, l'enregistrement automatique de l'une renvoie TOUTE la liste des segments
# et efface la correction de l'autre, sans que personne le sache.

def state_token(value) -> str:
    """L'empreinte d'un état ÉDITÉ (liste, dictionnaire, texte) — ce que la page reçoit à
    l'ouverture et renvoie avec chaque enregistrement. L'empreinte de texte des révisions
    (`revisions.text_fingerprint`), sur le JSON trié : deux états égaux ont la même."""
    import json
    from wama.common.services.revisions import text_fingerprint
    return text_fingerprint(json.dumps(value, sort_keys=True, ensure_ascii=False, default=str))


def stale_edit(user, obj, base, current_value):
    """None si l'enregistrement part de l'état COURANT — ou ne dit pas de quel état il part (page
    ouverte avant que la règle n'existe) ; sinon ce que la réponse 409 dit : qui l'édite en ce
    moment s'il le sait (le verrou doux), et l'empreinte courante. À appeler sur l'élément
    VERROUILLÉ en base (`select_for_update`), sans quoi deux enregistrements simultanés passent."""
    if not base or base == state_token(current_value):
        return None
    other = holder(obj)
    by = other.get('name', '') if other and other.get('user_id') != getattr(user, 'pk', None) else ''
    return {'conflict': True, 'by': by, 'token': state_token(current_value),
            'reason': (f"{by} a modifié cet élément depuis votre ouverture" if by
                       else "cet élément a été modifié depuis votre ouverture")
                      + " — rechargez pour reprendre la dernière version."}
