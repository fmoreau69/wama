"""
Backend LDAP WAMA = django_auth_ldap + MODÉRATION à la première connexion.

Le login passe par le LDAP de l'université → SANS gate, tout membre UGE obtiendrait
un compte. Ici : un nouvel utilisateur LDAP est créé INACTIF (`is_active=False`), en
attente de validation par un admin (notifié par email). Voir docs/VISION_STATUS.md
§Projets/manifestes/modération.
"""
import logging

from django.conf import settings
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
