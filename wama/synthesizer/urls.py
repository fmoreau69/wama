"""
WAMA Synthesizer - URLs Configuration
"""

from django.urls import path
from django.http import JsonResponse
from . import views

app_name = 'synthesizer'

urlpatterns = [
    # Pages principales
    path('', views.IndexView.as_view(), name='index'),
    path('about/', views.AboutView.as_view(), name='about'),
    path('help/', views.HelpView.as_view(), name='help'),

    # Opérations sur les synthèses
    path('upload/', views.upload, name='upload'),
    path('upload-text/', views.upload_text, name='upload_text'),
    path('text-preview/<int:pk>/', views.text_preview, name='text_preview'),
    path('voice-preview/', views.voice_preview, name='voice_preview'),
    path('voice-preview-stream/<str:preview_id>/', views.voice_preview_stream, name='voice_preview_stream'),
    path('voice-preview-stream-test/', lambda request: JsonResponse({'test': 'OK'}), name='voice_preview_stream_test'),
    path('voice-preview-diagnostic/<str:preview_id>/', lambda request, preview_id: JsonResponse({'status': 'OK', 'preview_id': preview_id}), name='voice_preview_diagnostic'),
    path('start/<int:pk>/', views.start, name='start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('global-progress/', views.global_progress, name='global_progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('preview/<int:pk>/', views.preview, name='preview'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('update-options/<int:pk>/', views.update_options, name='update_options'),

    # Opérations groupées
    path('start-all/', views.start_all, name='start_all'),
    path('clear-all/', views.clear_all, name='clear_all'),
    path('download-all/', views.download_all, name='download_all'),

    # Console
    path('console/', views.console_content, name='console'),

    # Voice Presets
    path('presets/', views.list_voice_presets, name='list_presets'),
    path('presets/create/', views.create_voice_preset, name='create_preset'),
    path('presets/delete/<int:pk>/', views.delete_voice_preset, name='delete_preset'),
]