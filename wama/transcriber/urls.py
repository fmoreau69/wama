from django.urls import path
from . import views

app_name = 'wama.transcriber'

urlpatterns = [
    # Pages principales
    path('', views.IndexView.as_view(), name='index'),
    path('about/', views.AboutView.as_view(), name='about'),
    path('help/', views.HelpView.as_view(), name='help'),

    # Opérations
    path('upload/', views.upload, name='upload'),
    path('upload_youtube/', views.upload_youtube, name='upload_youtube'),
    path('start/<int:pk>/', views.start, name='start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('delete/<int:pk>/', views.delete, name='delete'),

    # Opérations groupées
    path('start_all/', views.start_all, name='start_all'),
    path('clear_all/', views.clear_all, name='clear_all'),
    path('download_all/', views.download_all, name='download_all'),

    # Console & Progress
    path('console/', views.console_content, name='console'),
    path('global_progress/', views.global_progress, name='global_progress'),

    # Preprocessing
    path('preprocessing/toggle/', views.toggle_preprocessing, name='toggle_preprocessing'),
    path('preprocessing/status/', views.preprocessing_status, name='preprocessing_status'),
    path('preprocessing/set/', views.set_preprocessing_preference, name='set_preprocessing'),

    # VibeVoice-related endpoints
    path('backends/', views.get_backends, name='backends'),
    path('segments/<int:pk>/', views.get_segments, name='segments'),
    path('download_srt/<int:pk>/', views.download_srt, name='download_srt'),
    path('settings/<int:pk>/', views.save_settings, name='save_settings'),

    # User-level settings
    path('user_settings/', views.get_user_transcriber_settings, name='get_user_settings'),
    path('user_settings/save/', views.save_user_transcriber_settings, name='save_user_settings'),
]