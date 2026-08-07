"""
WAMA Imager - URLs
"""

from django.urls import path
from . import views

app_name = 'imager'

urlpatterns = [
    # Main pages
    path('', views.index, name='index'),
    path('about/', views.about, name='about'),
    path('help/', views.help_page, name='help'),
    path('console/', views.console, name='console'),

    # Generation management
    path('create/', views.create_generation, name='create'),
    path('start/<int:generation_id>/', views.start_generation, name='start'),
    path('restart/<int:generation_id>/', views.restart_generation, name='restart'),
    path('start-all/', views.start_all_generations, name='start_all'),
    path('progress/<int:generation_id>/', views.progress, name='progress'),
    # Partial de card (contrat card_html/refreshCard — F5)
    path('card/<int:generation_id>/html/', views.card_html, name='card_html'),
    # Réglages appliqués à tout un batch (modale contexte 'batch')
    path('batch/<int:batch_id>/update/', views.batch_update, name='batch_update'),
    path('global-progress/', views.global_progress, name='global_progress'),

    # Download and delete
    path('download/<int:generation_id>/', views.download, name='download'),
    path('download-all/', views.download_all, name='download_all'),
    path('delete/<int:generation_id>/', views.delete_generation, name='delete'),
    path('duplicate/<int:generation_id>/', views.duplicate_generation, name='duplicate'),
    path('clear-all/', views.clear_all, name='clear_all'),

    # Console and settings
    path('console-content/', views.console_content, name='console_content'),

    # Individual generation settings
    path('settings/<int:generation_id>/', views.get_generation_settings, name='get_settings'),
    path('settings/<int:generation_id>/save/', views.save_generation_settings, name='save_settings'),
    path('force-reset/<int:generation_id>/', views.force_reset_generation, name='force_reset'),

    # Multi-modal generation endpoints
    path('auto-prompt/', views.generate_auto_prompt, name='auto_prompt'),
    path('batch/<int:batch_id>/children/', views.get_batch_children, name='batch_children'),
    path('batch/<int:batch_id>/start/', views.start_batch, name='start_batch'),

    # Prompt enhancement (Ollama)

    # API endpoints for model configuration
    path('api/model-resolutions/', views.api_model_resolutions, name='api_model_resolutions'),
    path('api/resolutions/', views.api_all_resolutions, name='api_all_resolutions'),
]
