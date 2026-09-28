from django.apps import AppConfig


class StudioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.studio'
    verbose_name = 'Studio - Méta-app (orchestration de pipelines)'

    def ready(self):
        # Scénario nocturne `output` (pipeline réel de bout en bout) — même motif que
        # l'enhancer : enregistré aussi pour les management commands (run_nightly_tests).
        try:
            from .nightly_scenarios import register_scenarios
            register_scenarios()
        except Exception:
            pass
        # Les exécutions de pipelines entrent au journal et au calendrier (WAMA_MEMORY §9bis.1).
        from wama.common.services.journal import MONDE_STUDIO, enregistrer_source
        from .models import StudioRun
        enregistrer_source('studio', StudioRun, monde=MONDE_STUDIO)
