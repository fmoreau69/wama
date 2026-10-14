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
        # Ses pages du menu du compte (2026-10-14) : le menu en est GÉNÉRÉ et l'assistant y
        # emmène. `access` = le décorateur de la vue (`login_required`, `admin_required`).
        from wama.common.app_registry import register_account_page
        register_account_page('profile', section='mine', label='Profil', icon='fa-user-edit',
                              tone='primary', access='account', url_name='accounts:profile',
                              order=70,
                              description="Votre compte : identité, langue, mode d'interface, "
                                          "usage des modèles distants, clés, rattachement.")
        register_account_page('users', section='mine', label='Users', icon='fa-users-cog',
                              tone='warning', access='admin', url_name='accounts:user-management',
                              order=90,
                              description="Gestion des comptes, de leurs profils et rôles, et "
                                          "des droits d'accès aux applications.")
