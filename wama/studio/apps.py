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
