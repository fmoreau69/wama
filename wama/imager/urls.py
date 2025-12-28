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
    path('start-all/', views.start_all_generations, name='start_all'),
    path('progress/<int:generation_id>/', views.progress, name='progress'),
    path('global-progress/', views.global_progress, name='global_progress'),

    # Download and delete
    path('download/<int:generation_id>/', views.download, name='download'),
    path('delete/<int:generation_id>/', views.delete_generation, name='delete'),
    path('clear-all/', views.clear_all, name='clear_all'),

    # Console and settings
    path('console-content/', views.console_content, name='console_content'),
    path('update-settings/', views.update_settings, name='update_settings'),

    # Individual generation settings
    path('settings/<int:generation_id>/', views.get_generation_settings, name='get_settings'),
    path('settings/<int:generation_id>/save/', views.save_generation_settings, name='save_settings'),
]
