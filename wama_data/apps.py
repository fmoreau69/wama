from django.apps import AppConfig


class WamaDataConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama_data'
    verbose_name = 'WAMA Data'

    def ready(self):
        """Déclare les fonctions du monde Data dans le catalogue commun.

        C'est le monde qui se déclare, jamais le registre qui va chercher ses producteurs : avant
        ce déport, `common/apps.py` importait les fonctions Data et `load_all()` citait
        `wama_lab.cam_analyzer` en dur — le substrat connaissait deux mondes par leur nom. Même
        geste que `cam_analyzer/apps.py`, qui faisait déjà les choses correctement.
        """
        try:
            from . import functions  # noqa: F401  (l'import enregistre les FunctionSpec)
        except Exception:
            import logging
            logging.getLogger(__name__).warning(
                'wama_data functions non enregistrées', exc_info=True)
