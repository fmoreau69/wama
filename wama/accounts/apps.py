from django.apps import AppConfig


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "wama.accounts"

    def ready(self):
        import logging
        # Remontée de l'appartenance organisationnelle (SUPANN) du LDAP au profil.
        try:
            from . import ldap  # noqa: F401  (connecte les signaux)
        except Exception:
            logging.getLogger(__name__).warning('accounts.ldap non chargé', exc_info=True)
        # Modération des nouveaux comptes + journal d'accès.
        try:
            from . import moderation  # noqa: F401
        except Exception:
            logging.getLogger(__name__).warning('accounts.moderation non chargé', exc_info=True)
