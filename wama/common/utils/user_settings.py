"""
WAMA Common — Réglages UTILISATEUR par app, DURABLES en base (cache en lecture devant).

Généralise les clés artisanales ``user_{id}_transcriber_*`` (audit A5-22, 2026-07-06) :
UNE convention pour toutes les apps, avec défauts déclarés par l'app (schéma-driven : les
défauts viennent de params.py à terme).

⭐ DURABLE depuis le 2026-09-15 (décision de Fabien, `ROADMAP §23.3bis`) : la base
(`common.UserAppSetting`) fait foi ; le cache n'est plus qu'une lecture rapide devant elle. Avant,
les réglages vivaient dans le seul cache Redis — 30 jours glissants, et perdus à un redémarrage
sans instantané. Les SIGNATURES n'ont pas changé : aucune app n'a eu une ligne à modifier.

Usage :
    from wama.common.utils.user_settings import get_user_app_settings, save_user_app_settings

    DEFAULTS = {'backend': 'auto', 'hotwords': '', 'diarization': True}
    settings = get_user_app_settings(user, 'transcriber', DEFAULTS)   # dict complet
    save_user_app_settings(user, 'transcriber', {'backend': 'whisper'})

⚠ Une valeur doit être sérialisable en JSON pour être durable. Sinon elle reste en cache seul,
avec un avertissement au journal : l'appelant n'échoue jamais pour un réglage de confort.
⚠ Un utilisateur sans identifiant (anonyme non enregistré) garde le comportement historique :
cache seul.
"""
import json
import logging

from django.core.cache import cache

logger = logging.getLogger(__name__)

#: Durée de la copie en CACHE (lecture rapide). La donnée elle-même est durable en base.
DEFAULT_TIMEOUT = 30 * 24 * 3600

#: Enveloppe des valeurs en cache : distingue « réglage posé à None » de « absent du cache ».
_CACHED = 'v'


def _key(user, app, name):
    return f"user_{user.id}_{app}_{name}"


def _durable(user) -> bool:
    return bool(getattr(user, 'pk', None))


def _read(user, app, names) -> dict:
    """{nom: valeur} des réglages POSÉS parmi `names` — cache d'abord, puis la base."""
    keys = {_key(user, app, n): n for n in names}
    found = {}
    for key, wrapped in cache.get_many(list(keys)).items():
        if isinstance(wrapped, tuple) and len(wrapped) == 2 and wrapped[0] == _CACHED:
            found[keys[key]] = wrapped[1]
    missing = [n for n in names if n not in found]
    if missing and _durable(user):
        from wama.common.models import UserAppSetting
        rows = dict(UserAppSetting.objects.filter(user=user, app=app, name__in=missing)
                    .values_list('name', 'value'))
        if rows:
            cache.set_many({_key(user, app, n): (_CACHED, v) for n, v in rows.items()},
                           timeout=DEFAULT_TIMEOUT)
            found.update(rows)
    return found


def get_user_app_settings(user, app, defaults):
    """Retourne le dict complet des réglages de ``user`` pour ``app``.

    ``defaults`` : dict clé→valeur par défaut — définit AUSSI l'ensemble des clés lues.
    """
    stored = _read(user, app, list(defaults))
    return {name: stored.get(name, default) for name, default in defaults.items()}


def get_user_app_setting(user, app, name, default=None):
    """Lecture d'UN réglage."""
    return _read(user, app, [name]).get(name, default)


def save_user_app_settings(user, app, values, *, timeout=DEFAULT_TIMEOUT):
    """Persiste chaque réglage fourni (en base, et en cache pour la lecture).

    Ignore les clés à valeur None si l'app veut « ne pas toucher » un réglage : filtrer AVANT
    l'appel (ici on écrit tel quel, None compris — c'est une valeur légitime). `timeout` ne
    règle plus que la copie en cache.
    """
    if not values:
        return
    durable = _durable(user)
    if durable:
        from wama.common.models import UserAppSetting
    for name, value in values.items():
        if durable:
            try:
                json.dumps(value)
            except (TypeError, ValueError):
                logger.warning("[user_settings] %s.%s non sérialisable en JSON : cache seul",
                               app, name)
            else:
                UserAppSetting.objects.update_or_create(
                    user=user, app=app, name=name, defaults={'value': value})
        cache.set(_key(user, app, name), (_CACHED, value), timeout=timeout)
