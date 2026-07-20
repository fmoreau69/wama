from django.apps import AppConfig


class CommonConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.common'

    def ready(self):
        # Enregistre les fonctions WAMA Data pures (toolbox tierce : map-matching, freinage…)
        # dans le catalogue au démarrage.
        try:
            from wama.common.data import functions  # noqa: F401
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                'wama.common.data functions non enregistrées', exc_info=True)
