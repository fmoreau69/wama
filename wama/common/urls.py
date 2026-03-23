"""
WAMA Common - URL patterns

Shared URL patterns for common functionality across apps.
"""

from django.urls import path
from .utils import preview_utils
from . import views

app_name = 'common'

urlpatterns = [
    # Unified preview endpoint: /common/preview/<app_name>/<pk>/
    path('preview/<str:app_name>/<int:pk>/', preview_utils.unified_preview, name='unified_preview'),

    # System stats endpoints
    path('api/system-stats/', views.system_stats, name='system_stats'),
    path('api/system-stats/full/', views.system_stats_full, name='system_stats_full'),

    # Centralized console endpoint (role-based filtering)
    path('api/console/', views.console_content, name='console'),

    # App registry
    path('api/apps/', views.api_apps, name='api_apps'),
    path('apps/', views.apps_catalog_view, name='apps_catalog'),
]
