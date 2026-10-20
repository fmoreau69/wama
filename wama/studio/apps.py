from django.apps import AppConfig


class StudioConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'wama.studio'
    verbose_name = 'Studio - Méta-app (orchestration de pipelines)'

    def ready(self):
        # Scénario nocturne `output` (pipeline réel de bout en bout) — même motif que
        # l'enhancer : DÉCLARÉ, joué au premier usage du registre (`add_registrar`, 2026-10-20 —
        # il importe `generic_runner`, qui dérive les ports de chaque app à l'import : 7,5 s).
        from wama.common.services.nightly_tests import add_registrar
        add_registrar('wama.studio.nightly_scenarios:register_scenarios')
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
