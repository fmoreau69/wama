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


def clear_user_app_settings(user, app, names):
    """Retire les réglages `names` de ``user`` pour ``app`` : ils reprennent le défaut que
    l'app déclare. C'est la RÉINITIALISATION — écrire les défauts à la place les figerait, et
    un défaut changé plus tard dans le schéma n'atteindrait plus cet utilisateur."""
    names = list(names)
    if _durable(user):
        from wama.common.models import UserAppSetting
        UserAppSetting.objects.filter(user=user, app=app, name__in=names).delete()
    cache.delete_many([_key(user, app, n) for n in names])


# ── Les réglages du VOLET d'une app, dérivés de son schéma (2026-09-27) ────────────────────
# Le volet EST la surface des défauts de l'utilisateur. Lire, garder, remettre à zéro et faire
# naître un élément avec ces défauts s'écrivait dans chaque app (transcriber, anonymizer,
# imager) : c'est ici, une fois. L'app DÉCLARE seulement, dans son params.py :
#   • `params`  — son schéma (seuls les params du contexte `panel` sont gardés) ;
#   • `key`     — la clé de stockage d'un param (défaut : `panel_dom_id`), pour les clés déjà en
#                 base sous un autre nom (frontière des données) ;
#   • `extra`   — {nom: défaut} des réglages du volet HORS schéma (anonymizer : `classes2blur`),
#                 et `clean` — {nom: fonction} qui assainit une valeur postée avant de la garder.
# Toutes les fonctions acceptent la même déclaration (l'app la passe telle quelle, `**`).

#: Types de param pour qui `''` EST une valeur (un prompt vidé, un choix remis sur « auto ») ;
#: pour les autres (nombres, interrupteurs), `''` veut dire « non fourni ».
_EMPTY_IS_VALUE = ('text', 'textarea', 'select')


def _panel_defaults(params, key, extra):
    from wama.common.utils.param_schema import panel_defaults
    return {**panel_defaults(params, key=key), **dict(extra or {})}


def read_panel_settings(user, app, params, *, key=None, extra=None, clean=None) -> dict:
    """Les réglages du volet de ``user``, par NOM de param (ce que `WamaParams.render` attend),
    défauts du schéma sous ce que l'utilisateur a posé — réglages hors schéma compris."""
    from wama.common.utils.param_schema import panel_values_by_name
    stored = get_user_app_settings(user, app, _panel_defaults(params, key, extra))
    values = panel_values_by_name(stored, params, key=key)
    values.update({name: stored[name] for name in (extra or {})})
    return values


def save_panel_settings(user, app, params, data, *, key=None, extra=None, clean=None) -> dict:
    """Garde comme préférences les réglages du volet présents dans `data` (par NOM), coercés par
    le schéma. Une clé absente n'écrase rien ; un nombre ou un interrupteur vide non plus.
    Rend ce qui a été gardé, par clé de stockage."""
    from wama.common.utils.param_schema import (_pget, coerce_schema_values,
                                                panel_prefs_from_post)
    typed = {**data, **coerce_schema_values(params, data)}
    textual = {_pget(p, 'name') for p in params if _pget(p, 'type') in _EMPTY_IS_VALUE}
    prefs = {}
    for p in params:
        stored_as = panel_prefs_from_post(typed, [p], key=key)
        for k, v in stored_as.items():
            if v not in (None, '') or _pget(p, 'name') in textual:
                prefs[k] = v
    for name in (extra or {}):
        if name in data:
            fix = (clean or {}).get(name)
            prefs[name] = fix(data[name]) if fix else data[name]
    if prefs:
        save_user_app_settings(user, app, prefs)
    return prefs


def reset_panel_settings(user, app, params, *, key=None, extra=None, clean=None) -> dict:
    """Remet le volet de ``user`` sur les défauts : ses préférences sont RETIRÉES (jamais
    réécrites avec les défauts du jour). Rend les réglages tels qu'ils sont alors lus."""
    clear_user_app_settings(user, app, _panel_defaults(params, key, extra))
    return read_panel_settings(user, app, params, key=key, extra=extra)


def new_element_settings(user, app, params, model, *, key=None, extra=None,
                         clean=None) -> dict:
    """Les colonnes de réglage d'un élément NAISSANT : les réglages du volet de son auteur,
    restreints aux champs concrets de `model` — il naît complet (`ROADMAP §23.2quater`), et sa
    tâche ne lit plus que ses colonnes."""
    concrete = {f.name for f in model._meta.concrete_fields}
    values = read_panel_settings(user, app, params, key=key, extra=extra)
    return {k: v for k, v in values.items() if k in concrete}


def make_panel_settings_views(app, params, *, key=None, extra=None, clean=None):
    """Les deux vues JSON du volet — lecture (GET) et enregistrement (POST, JSON par NOM, clés
    absentes inchangées) —, identiques d'une app à l'autre. Rend `(get_view, save_view)`,
    à router sur `user_settings/` et `user_settings/save/`."""
    import json as _json

    from django.http import JsonResponse
    from django.views.decorators.http import require_POST

    def _user(request):
        if request.user.is_authenticated:
            return request.user
        from wama.accounts.views import get_or_create_anonymous_user
        return get_or_create_anonymous_user()

    def get_view(request):
        return JsonResponse(read_panel_settings(_user(request), app, params,
                                                key=key, extra=extra))

    @require_POST
    def save_view(request):
        user = _user(request)
        try:
            data = _json.loads(request.body.decode('utf-8'))
        except (ValueError, UnicodeDecodeError):
            data = {}
        save_panel_settings(user, app, params, data if isinstance(data, dict) else {},
                            key=key, extra=extra, clean=clean)
        return JsonResponse(read_panel_settings(user, app, params, key=key, extra=extra))

    return get_view, save_view


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
