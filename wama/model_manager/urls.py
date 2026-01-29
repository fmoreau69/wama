"""
Model Manager URL patterns.
"""

from django.urls import path
from . import views

app_name = 'model_manager'

urlpatterns = [
    # Dashboard
    path('', views.index, name='index'),

    # API endpoints
    path('api/models/', views.api_models_list, name='api_models_list'),
    path('api/memory/', views.api_memory_stats, name='api_memory_stats'),
    path('api/unload/', views.api_unload_model, name='api_unload_model'),
    path('api/clear-gpu/', views.api_clear_gpu, name='api_clear_gpu'),
    path('api/refresh/', views.api_refresh_models, name='api_refresh_models'),
    path('api/debug/', views.api_debug_stats, name='api_debug_stats'),
]
