"""
WAMA Anonymizer - URLs Configuration
"""

from django.urls import path
from . import views

app_name = 'wama.anonymizer'

urlpatterns = [
    # Pages principales
    path('', views.IndexView.as_view(), name='index'),
    path('upload/', views.IndexView.as_view(), name='upload'),  # Alias pour upload (même page que index)
    path('process/', views.ProcessView.as_view(), name='process'),  # Endpoint pour lancer le traitement batch
    path('about/', views.AboutView.as_view(), name='about'),
    path('help/', views.HelpView.as_view(), name='help'),

    # Opérations
    path('refresh/', views.refresh, name='refresh'),
    path('update_settings/', views.update_settings, name='update_settings'),
    path('clear_media/', views.clear_media, name='clear_media'),
    path('reset_media_settings/', views.reset_media_settings, name='reset_media_settings'),
    path('reset_user_settings/', views.reset_user_settings, name='reset_user_settings'),
    path('process_progress/', views.get_process_progress, name='process_progress'),
    path('download_media/', views.download_media, name='download_media'),
    path('expand_area/', views.expand_area, name='expand_area'),
    path('stop_process/', views.stop_process_view, name='stop_process'),
    path('preview/<int:media_id>/', views.preview_media, name='preview_media'),

    # Opérations groupées
    path("check_all_processed/", views.check_all_processed, name="check_all_processed"),
    path('clear_all_media/', views.clear_all_media, name='clear_all_media'),
    path('download_all_media/', views.download_all_media, name='download_all_media'),

    # Console & Progress
    path('console/', views.console_content, name='console'),
    path('global_progress/', views.global_progress, name='global_progress'),

    # Model Management
    path('model-recommendations/', views.get_model_recommendations, name='model_recommendations'),

    # Modern Modal-Based Settings
    path('get_media_settings/<int:media_id>/', views.get_media_settings, name='get_media_settings'),
    path('save_media_settings/', views.save_media_settings, name='save_media_settings'),
    path('restart_media/', views.restart_media, name='restart_media'),

    # Unused
    # path('display_console/', views.ProcessView.display_console, name='display_console'),
]
