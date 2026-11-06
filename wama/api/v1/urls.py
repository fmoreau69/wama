"""
WAMA REST API v1 — URL configuration

/api/v1/auth/token/       POST  → obtain auth token
/api/v1/tools/            GET   → list available tools
/api/v1/tools/run/        POST  → execute a tool
/api/v1/assistant/chat/   POST  → one assistant conversation turn (agentic loop)
/api/v1/assistant/model/  GET/POST → read / change the assistant's LLM (thread untouched)
/api/v1/files/upload/     POST  → deposit a file (multipart, field `file`)
/api/v1/files/download/   GET   → read back a file (?path=…)
"""

from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from .views import (
    AssistantChatView,
    AssistantModelView,
    FileDownloadView,
    FileUploadView,
    ListToolsView,
    RunToolView,
)

urlpatterns = [
    path('auth/token/', obtain_auth_token, name='api_v1_token'),
    path('tools/', ListToolsView.as_view(), name='api_v1_list_tools'),
    path('tools/run/', RunToolView.as_view(), name='api_v1_run_tool'),
    path('assistant/chat/', AssistantChatView.as_view(), name='api_v1_assistant_chat'),
    path('assistant/model/', AssistantModelView.as_view(), name='api_v1_assistant_model'),
    path('files/upload/', FileUploadView.as_view(), name='api_v1_file_upload'),
    path('files/download/', FileDownloadView.as_view(), name='api_v1_file_download'),
]
