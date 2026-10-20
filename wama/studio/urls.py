from django.urls import path

from . import views

app_name = 'studio'

urlpatterns = [
    path('', views.index, name='index'),
    path('api/nodes/', views.api_nodes, name='api_nodes'),
    # Pourquoi un nœud d'un graphe ouvert n'est pas dans la palette du compte (2026-10-19)
    path('api/nodes/unavailable/', views.api_unavailable_nodes, name='api_unavailable_nodes'),
    # Ce que reçoit un nœud — le graphe porteur de valeurs (2026-10-18)
    path('api/node-context/', views.api_node_context, name='api_node_context'),
    # Persistance + exécution (2026-07-11)
    path('api/pipelines/', views.api_pipelines, name='api_pipelines'),
    path('api/pipelines/<int:pk>/', views.api_pipeline_detail, name='api_pipeline_detail'),
    path('api/declared-pipelines/', views.api_declared_pipelines, name='api_declared_pipelines'),
    path('api/declared-pipelines/<str:key>/', views.api_declared_pipeline_detail,
         name='api_declared_pipeline_detail'),
    # Les cards d'entrée médias : la card v4 de l'app alimentée, et la lecture d'un fichier de
    # lot (2026-10-20)
    path('api/entry-card/', views.api_entry_card, name='api_entry_card'),
    path('api/entry-lot/', views.api_entry_lot, name='api_entry_lot'),
    path('api/run/', views.api_run, name='api_run'),
    path('api/run/<int:pk>/', views.api_run_status, name='api_run_status'),
    # ⬇ les résultats d'un run en ZIP (2026-10-20)
    path('api/run/<int:pk>/download/', views.api_run_download, name='api_run_download'),
]
