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
    path('synthesis/<int:pk>/card/', views.synthesis_card_html, name='synthesis_card_html'),
    path('global-progress/', views.global_progress, name='global_progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('preview/<int:pk>/', views.preview, name='preview'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('duplicate/<int:pk>/', views.duplicate, name='duplicate'),
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

    # Custom Voices (persistent cloning)
    path('custom-voices/', views.list_custom_voices, name='list_custom_voices'),
    path('custom-voices/upload/', views.upload_custom_voice, name='upload_custom_voice'),
    path('custom-voices/delete/<int:pk>/', views.delete_custom_voice, name='delete_custom_voice'),

    # Import individual from server path (FileManager batch bypass)
    path('import-individual-from-path/', views.import_individual_from_path, name='import_individual_from_path'),

    # Batch synthesis
    path('batch/', views.batch_list, name='batch_list'),
    path('batch/template/', views.batch_template, name='batch_template'),
    path('batch/preview/', views.batch_preview, name='batch_preview'),
    path('batch/create/', views.batch_create, name='batch_create'),
    path('batch/<int:pk>/start/', views.batch_start, name='batch_start'),
    path('batch/<int:pk>/status/', views.batch_status, name='batch_status'),
    path('batch/<int:pk>/download/', views.batch_download, name='batch_download'),
    path('batch/<int:pk>/delete/', views.batch_delete, name='batch_delete'),
    path('batch/<int:pk>/settings/', views.batch_update_settings, name='batch_update_settings'),
    path('batch/<int:pk>/duplicate/', views.batch_duplicate, name='batch_duplicate'),
]