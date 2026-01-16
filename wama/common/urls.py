"""
WAMA Common - URL patterns

Shared URL patterns for common functionality across apps.
"""

from django.urls import path
from .utils import preview_utils

app_name = 'common'

urlpatterns = [
    # Unified preview endpoint: /common/preview/<app_name>/<pk>/
    path('preview/<str:app_name>/<int:pk>/', preview_utils.unified_preview, name='unified_preview'),
]
