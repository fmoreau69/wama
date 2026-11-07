"""
Backend LDAP WAMA = django_auth_ldap + MODÉRATION à la première connexion.

Le login passe par le LDAP de l'université → SANS gate, tout membre UGE obtiendrait
un compte. Ici : un nouvel utilisateur LDAP est créé INACTIF (`is_active=False`), en
attente de validation par un admin (prévenu dans WAMA et par email, `moderation.request_moderation`).
Voir `PROFILES_PERMISSIONS.md §1.8` (modération à la première connexion).
"""
import logging

from django.conf import settings
from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import PermissionDenied
from django_auth_ldap.backend import LDAPBackend

logger = logging.getLogger(__name__)


class WamaLDAPBackend(LDAPBackend):
    def get_or_build_user(self, username, ldap_user):
        user, built = super().get_or_build_user(username, ldap_user)
        # `built=True` = utilisateur NOUVEAU (pas encore en base) → modération.
        if built and getattr(settings, 'WAMA_MODERATE_NEW_USERS', True):
            user.is_active = False           # en attente de validation admin
            user._wama_new_pending = True     # drapeau → notification après save
            logger.info('nouvel utilisateur LDAP %s → inactif (modération)', username)
        return user, built


class LoginBrakeBackend(ModelBackend):
    """Le FREIN de connexion (2026-11-06, audit de sécurité) — placé EN TÊTE de
    `AUTHENTICATION_BACKENDS`, il est lu par toute surface qui authentifie (formulaire, jeton
    d'API, site d'administration). Un identifiant qui a atteint la borne d'échecs récents
    (`moderation.login_braked`) arrête la chaîne : `PermissionDenied` fait renoncer
    `django.contrib.auth.authenticate` sans consulter l'annuaire. Sinon il ne décide rien.

    Il hérite de `ModelBackend` pour RELIRE une session (`get_user`) : premier de la liste, c'est
    lui qu'une connexion sans moteur nommé (`login`, `force_login`) inscrit dans la session — un
    `BaseBackend` y rendrait le compte anonyme. Il n'authentifie jamais lui-même."""

    def authenticate(self, request, username=None, **kwargs):
        from wama.accounts.moderation import login_braked
        if username and login_braked(username):
            logger.warning("connexion freinée pour %s (trop d'échecs récents)", username)
            raise PermissionDenied
        return None
