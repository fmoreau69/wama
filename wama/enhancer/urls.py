from django.urls import path
from . import views

app_name = 'enhancer'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('upload/', views.upload, name='upload'),
    path('start/<int:pk>/', views.start, name='start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('duplicate/<int:pk>/', views.duplicate, name='duplicate'),
    path('start_all/', views.start_all, name='start_all'),
    path('clear_all/', views.clear_all, name='clear_all'),
    path('download_all/', views.download_all, name='download_all'),
    path('update_settings/<int:pk>/', views.update_settings, name='update_settings'),
    path('console/', views.console_content, name='console'),
    path('global_progress/', views.global_progress, name='global_progress'),
    # Audio enhancement
    path('audio/upload/', views.audio_upload, name='audio_upload'),
    path('audio/start/<int:pk>/', views.audio_start, name='audio_start'),
    path('audio/progress/<int:pk>/', views.audio_progress, name='audio_progress'),
    path('audio/download/<int:pk>/', views.audio_download, name='audio_download'),
    path('audio/delete/<int:pk>/', views.audio_delete, name='audio_delete'),
    path('audio/duplicate/<int:pk>/', views.audio_duplicate, name='audio_duplicate'),
    path('audio/start_all/', views.audio_start_all, name='audio_start_all'),
    path('audio/clear_all/', views.audio_clear_all, name='audio_clear_all'),
    path('audio/download_all/', views.audio_download_all, name='audio_download_all'),
    path('audio/global_progress/', views.audio_global_progress, name='audio_global_progress'),
]
