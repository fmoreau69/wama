"""
WAMA Describer - URL Configuration
"""

from django.urls import path
from . import views

app_name = 'describer'

urlpatterns = [
    # Main page
    path('', views.IndexView.as_view(), name='index'),

    # File operations
    path('upload/', views.upload, name='upload'),
    path('start/<int:pk>/', views.start, name='start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('preview/<int:pk>/', views.preview, name='preview'),

    # Batch operations
    path('start-all/', views.start_all, name='start_all'),
    path('clear-all/', views.clear_all, name='clear_all'),
    path('download-all/', views.download_all, name='download_all'),

    # Utilities
    path('console/', views.console_content, name='console'),
    path('global-progress/', views.global_progress, name='global_progress'),
    path('update-options/<int:pk>/', views.update_options, name='update_options'),
]
