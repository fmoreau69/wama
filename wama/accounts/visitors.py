"""
Le VISITEUR sans compte, sur une app PUBLIQUE : une identité éphémère PAR SESSION.

LA DÉCISION (Fabien, 2026-08-30, puis « option 1, persistance par session » le 2026-10-04) : un
visiteur non connecté voit les pages, ne peut rien faire — sauf dans l'app d'essai, le converter.
Le compte `anonymous` de la base est UNIQUE : y ranger les fichiers des visiteurs les montrerait
à tous les autres. Chaque visiteur reçoit donc une identité à lui.

LE MÉCANISME — une identité, pas une étiquette. On aurait pu marquer chaque objet d'une clé de
session et filtrer vue par vue ; chaque vue oubliée devenait une fuite. Ici le visiteur EST un
compte technique (`wama_visitor_<jeton>`, inactif, sans mot de passe, tier `anonymous`, aucun
rôle), créé à son PREMIER GESTE et retenu par sa session. Toute la logique de propriété qui
existe — file, fichiers sous `users/<id>/`, réglages, garde de partage — vaut alors pour lui
sans qu'une seule vue d'app soit retouchée.

  • `attach(request, app_id)` — appelé par `AppAccessMiddleware` pour une requête SANS session
    de membre sur une app `public` : pose l'identité sur la requête, ou rend un refus.
  • Les routes de l'app reçoivent ce compte dans `request.user` ; la PAGE d'accueil de l'app
    garde un `AnonymousUser` (ses gabarits communs affichent l'en-tête d'un visiteur, pas le
    menu d'un membre) et lit l'identité dans `request.wama_visitor`.
  • Sans identité (aucun geste encore), une LECTURE reçoit le compte `anonymous` partagé, qui
    ne possède rien : les routes JSON de la page répondent vide au lieu de rediriger.
  • `purge_expired()` — battue par Celery : au-delà de `WAMA_VISITOR_TTL_HOURS` sans geste,
    l'identité part avec ses éléments ET ses fichiers.

LES BORNES (réglables dans `settings`) : taille d'un envoi, nombre d'éléments par visiteur,
nombre d'identités neuves par adresse et par heure. Les routes qui font travailler le serveur
pour le visiteur au-delà d'un fichier téléversé (import par URL ou par lot, conversion rapide
d'un chemin serveur) lui restent fermées.

Ce module ne connaît AUCUNE app : la liste des apps ouvertes est la politique `public`.
"""
from __future__ import annotations

import logging
import secrets
import shutil
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone

logger = logging.getLogger(__name__)

SESSION_KEY = 'wama_visitor_uid'
READ_METHODS = ('GET', 'HEAD', 'OPTIONS')

#: Noms de route d'une PAGE : rendue avec les gabarits communs, elle garde un `AnonymousUser`.
PAGE_ROUTES = ('index', 'about', 'help')
#: Routes qui CRÉENT un élément : comptées contre le plafond d'éléments du visiteur.
CREATION_ROUTES = ('upload', 'duplicate', 'batch_duplicate')
#: Routes fermées au visiteur : elles font lire au serveur une adresse ou un chemin qu'il nomme.
CLOSED_ROUTES = ('batch_create', 'batch_preview', 'quick_convert', 'consolidate')

#: Rafraîchissement de l'horodatage d'activité : une écriture par tranche, pas par requête.
_TOUCH_EVERY = timedelta(minutes=10)


def _setting(name: str, default):
    return getattr(settings, name, default)


def max_upload_bytes() -> int:
    return int(_setting('WAMA_VISITOR_MAX_UPLOAD_MB', 200)) * 1024 * 1024


def max_items() -> int:
    return int(_setting('WAMA_VISITOR_MAX_ITEMS', 20))


def ttl() -> timedelta:
    return timedelta(hours=int(_setting('WAMA_VISITOR_TTL_HOURS', 24)))


def new_identities_per_hour() -> int:
    return int(_setting('WAMA_VISITOR_NEW_PER_ADDRESS_HOUR', 30))


def is_visitor(user) -> bool:
    """Ce compte est-il l'identité éphémère d'un visiteur (pas le compte `anonymous` partagé) ?"""
    from wama.accounts.permissions import VISITOR_ACCOUNT_PREFIX
    return (getattr(user, 'username', '') or '').startswith(VISITOR_ACCOUNT_PREFIX)


def current(request):
    """L'identité de visiteur que porte la session de cette requête, ou None."""
    from django.contrib.auth import get_user_model
    session = getattr(request, 'session', None)
    uid = session.get(SESSION_KEY) if session is not None else None
    if not uid:
        return None
    user = get_user_model().objects.filter(pk=uid).first()
    if user is None or not is_visitor(user):
        session.pop(SESSION_KEY, None)          # identité purgée : la session repart à neuf
        return None
    return user


def create(request):
    """Crée l'identité du visiteur et l'attache à sa session."""
    from django.contrib.auth import get_user_model
    from wama.accounts.permissions import VISITOR_ACCOUNT_PREFIX
    from wama.accounts.views import enforce_anonymous_closure
    user = get_user_model().objects.create(
        username=f'{VISITOR_ACCOUNT_PREFIX}{secrets.token_hex(6)}',
        first_name='Visiteur', is_active=False, last_login=timezone.now())
    user.set_unusable_password()
    user.save(update_fields=['password'])
    enforce_anonymous_closure(user)             # tier `anonymous`, aucun rôle — comme `anonymous`
    request.session[SESSION_KEY] = user.pk
    logger.info('[visiteur] identité %s créée', user.username)
    return user


def _refusal(message: str, status: int) -> JsonResponse:
    return JsonResponse({'error': message, 'detail': message, 'visitor': True}, status=status)


def _address(request) -> str:
    forwarded = (request.META.get('HTTP_X_FORWARDED_FOR') or '').split(',')[0].strip()
    return forwarded or request.META.get('REMOTE_ADDR') or '?'


def _creation_refusal(request):
    """Trop d'identités neuves depuis cette adresse ? (frein à l'abus, pas un contrôle d'accès)"""
    from django.core.cache import cache
    key = f'wama_visitor_new:{_address(request)}'
    count = cache.get(key, 0)
    if count >= new_identities_per_hour():
        return _refusal("Trop de visites sans compte depuis cette adresse pour l'instant — "
                        "réessayez plus tard, ou connectez-vous.", 429)
    cache.set(key, count + 1, timeout=3600)
    return None


def _owned_count(user, app_id: str) -> int:
    try:
        from wama.common.utils.preview_registry import PreviewRegistry
        return PreviewRegistry.get_model(app_id).objects.filter(user=user).count()
    except Exception:
        return 0


def _gesture_refusal(request, user, app_id: str, route: str):
    if route in CLOSED_ROUTES:
        return _refusal("Connectez-vous pour importer par lot, par adresse web ou depuis vos "
                        "fichiers : sans compte, seul l'envoi d'un fichier est ouvert.", 403)
    try:
        size = int(request.META.get('CONTENT_LENGTH') or 0)
    except (TypeError, ValueError):
        size = 0
    if size > max_upload_bytes():
        return _refusal(f"Fichier trop lourd pour un essai sans compte "
                        f"(limite : {max_upload_bytes() // (1024 * 1024)} Mo). Connectez-vous "
                        "pour lever cette limite.", 413)
    if route in CREATION_ROUTES and user is not None and _owned_count(user, app_id) >= max_items():
        return _refusal(f"Limite de l'essai sans compte atteinte ({max_items()} éléments). "
                        "Supprimez-en, ou connectez-vous.", 429)
    return None


def _touch(user) -> None:
    now = timezone.now()
    if user.last_login is None or now - user.last_login > _TOUCH_EVERY:
        type(user).objects.filter(pk=user.pk).update(last_login=now)
        user.last_login = now


def attach(request, app_id: str):
    """Pose l'identité du visiteur sur la requête d'une app PUBLIQUE. Rend un refus, ou None.

    Lecture : l'identité de la session si elle existe, sinon le compte `anonymous` partagé (qui
    ne possède rien). Geste : l'identité est créée s'il le faut, les bornes sont vérifiées.
    """
    from django.urls import Resolver404, resolve
    try:
        route = resolve(request.path_info).url_name or ''
    except Resolver404:
        route = ''
    is_read = request.method in READ_METHODS
    identity = current(request)
    if not is_read:
        if identity is None:
            refusal = _creation_refusal(request)
            if refusal is not None:
                return refusal
        refusal = _gesture_refusal(request, identity, app_id, route)
        if refusal is not None:
            return refusal
        if identity is None:
            identity = create(request)
        _touch(identity)
    request.wama_visitor = identity
    if is_read and route in PAGE_ROUTES:
        return None                              # la page garde son `AnonymousUser`
    if identity is None:
        from wama.accounts.views import get_or_create_anonymous_user
        identity = get_or_create_anonymous_user()
    request.user = identity
    return None


def purge_expired(now=None, dry_run: bool = False) -> dict:
    """Détruit les identités de visiteur sans geste depuis `ttl()` : éléments (cascade) ET
    fichiers (`media/users/<id>/`). Rend {'purged': n, 'kept': k, 'dry_run': bool}."""
    from django.contrib.auth import get_user_model
    from wama.accounts.permissions import VISITOR_ACCOUNT_PREFIX
    now = now or timezone.now()
    cutoff = now - ttl()
    visitors = get_user_model().objects.filter(username__startswith=VISITOR_ACCOUNT_PREFIX)
    summary = {'purged': 0, 'kept': 0, 'dry_run': dry_run}
    for user in visitors:
        last_seen = user.last_login or user.date_joined
        if last_seen > cutoff:
            summary['kept'] += 1
            continue
        summary['purged'] += 1
        if dry_run:
            continue
        home = Path(settings.MEDIA_ROOT) / 'users' / str(user.pk)
        try:
            if home.is_dir():
                shutil.rmtree(home)
        except OSError as exc:
            logger.warning('[visiteur] dossier %s non supprimé : %s', home, exc)
        username = user.username
        user.delete()
        logger.info('[visiteur] identité %s purgée (dernier geste : %s)', username, last_seen)
    return summary
