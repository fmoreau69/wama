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
        # Le studio se DÉCLARE : son monde (`transverse`, décision n°9 de la route §10.6) et sa
        # page — c'est cette déclaration que lisent le menu, `/apps/`, le journal et le calendrier.
        from wama.common.app_registry import register_surface
        register_surface('studio', world='transverse', label='Studio', url_name='studio:index',
                         icon='fa-diagram-project', color='#fb923c', order=10,
                         description='Orchestration de pipelines : reliez les apps sur un canvas '
                                     '(sorties → entrées) pour composer des chaînes de traitement.')
        # Les exécutions de pipelines entrent au journal et au calendrier (WAMA_MEMORY §9bis.1).
        from wama.common.services.journal import enregistrer_source
        from .models import StudioRun
        enregistrer_source('studio', StudioRun)
