from django.urls import path

from . import views

app_name = 'studio'

urlpatterns = [
    path('', views.index, name='index'),
    path('api/nodes/', views.api_nodes, name='api_nodes'),
    # Persistance + exécution (2026-07-11)
    path('api/pipelines/', views.api_pipelines, name='api_pipelines'),
    path('api/pipelines/<int:pk>/', views.api_pipeline_detail, name='api_pipeline_detail'),
    path('api/run-options/', views.api_run_options, name='api_run_options'),
    path('api/run/', views.api_run, name='api_run'),
    path('api/run/<int:pk>/', views.api_run_status, name='api_run_status'),
]
