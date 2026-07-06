"""
WAMA Common — Réglages UTILISATEUR par app (persistance cache, 30 jours glissants).

Généralise les clés artisanales ``user_{id}_transcriber_*`` (audit A5-22, 2026-07-06) :
UNE convention de nommage ``user_{user_id}_{app}_{clé}`` pour toutes les apps, avec
défauts déclarés par l'app (schéma-driven : les défauts viennent de params.py à terme).

Usage :
    from wama.common.utils.user_settings import get_user_app_settings, save_user_app_settings

    DEFAULTS = {'backend': 'auto', 'hotwords': '', 'diarization': True}
    settings = get_user_app_settings(user, 'transcriber', DEFAULTS)   # dict complet
    save_user_app_settings(user, 'transcriber', {'backend': 'whisper'})
"""

from django.core.cache import cache

# 30 jours glissants — même durée que l'historique transcriber (2592000 s).
DEFAULT_TIMEOUT = 30 * 24 * 3600


def _key(user, app, name):
    return f"user_{user.id}_{app}_{name}"


def get_user_app_settings(user, app, defaults):
    """Retourne le dict complet des réglages de ``user`` pour ``app``.

    ``defaults`` : dict clé→valeur par défaut — définit AUSSI l'ensemble des clés lues.
    """
    return {name: cache.get(_key(user, app, name), default)
            for name, default in defaults.items()}


def get_user_app_setting(user, app, name, default=None):
    """Lecture d'UN réglage."""
    return cache.get(_key(user, app, name), default)


def save_user_app_settings(user, app, values, *, timeout=DEFAULT_TIMEOUT):
    """Persiste (et re-arme le TTL de) chaque réglage fourni. Ignore les clés à valeur None
    si l'app veut « ne pas toucher » un réglage : filtrer AVANT l'appel (ici on écrit tel quel,
    None compris — c'est une valeur légitime)."""
    for name, value in values.items():
        cache.set(_key(user, app, name), value, timeout=timeout)
