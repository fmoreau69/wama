"""
WAMA Common - URL patterns

Shared URL patterns for common functionality across apps.
"""

from django.urls import path
from .utils import preview_utils
from .utils import detail_registry
from . import views

app_name = 'common'

urlpatterns = [
    # Unified preview endpoint: /common/preview/<app_name>/<pk>/
    path('preview/<str:app_name>/<int:pk>/', preview_utils.unified_preview, name='unified_preview'),
    # Unified detail (infos inspecteur) : /common/detail/<app_name>/<pk>/
    path('detail/<str:app_name>/<int:pk>/', detail_registry.unified_detail, name='unified_detail'),

    # Enrichissement de prompt à la demande (✨) — générique {prompt, app, domain}, cf. PROMPT_PIPELINE.md §Skills
    path('api/enrich-prompt/', views.api_enrich_prompt, name='enrich_prompt'),

    # System stats endpoints
    path('api/system-stats/', views.system_stats, name='system_stats'),
    path('api/system-stats/full/', views.system_stats_full, name='system_stats_full'),

    # Centralized console endpoint (role-based filtering)
    path('api/console/', views.console_content, name='console'),

    # Options de voix communes (optgroups) — consommé par WamaParams options_source='voices'
    path('api/voices/', views.api_voices, name='api_voices'),

    # App registry
    path('api/apps/', views.api_apps, name='api_apps'),
    path('apps/', views.apps_catalog_view, name='apps_catalog'),

    # Schéma domaines→modes d'une app (clé de voûte UX, consommé par WamaModes JS)
    path('api/app-modes/<str:app>/', views.api_app_modes, name='api_app_modes'),
    path('modes-demo/', views.modes_demo, name='modes_demo'),

]
