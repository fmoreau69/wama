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

    # Console
    path('console/', views.console_content, name='console'),

    # Preprocessing
    path('preprocessing/toggle/', views.toggle_preprocessing, name='toggle_preprocessing'),
    path('preprocessing/status/', views.preprocessing_status, name='preprocessing_status'),
    path('preprocessing/set/', views.set_preprocessing_preference, name='set_preprocessing'),
]