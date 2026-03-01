"""
WAMA REST API v1 — URL configuration

/api/v1/auth/token/  POST  → obtain auth token
/api/v1/tools/       GET   → list available tools
/api/v1/tools/run/   POST  → execute a tool
"""

from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from .views import ListToolsView, RunToolView

urlpatterns = [
    path('auth/token/', obtain_auth_token, name='api_v1_token'),
    path('tools/', ListToolsView.as_view(), name='api_v1_list_tools'),
    path('tools/run/', RunToolView.as_view(), name='api_v1_run_tool'),
]
