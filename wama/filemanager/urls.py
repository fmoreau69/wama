"""
FileManager URL configuration.
"""
from django.urls import path, re_path
from . import views

app_name = 'filemanager'

urlpatterns = [
    # API endpoints
    path('api/tree/', views.api_tree, name='api_tree'),
    path('api/search/', views.api_search, name='api_search'),
    path('api/upload/', views.api_upload, name='api_upload'),
    path('api/delete/', views.api_delete, name='api_delete'),
    path('api/delete-all/', views.api_delete_all, name='api_delete_all'),
    path('api/rename/', views.api_rename, name='api_rename'),
    path('api/move/', views.api_move, name='api_move'),
    path('api/info/', views.api_info, name='api_info'),
    path('api/preview/', views.api_preview, name='api_preview'),
    path('api/import/', views.api_import_to_app, name='api_import'),

    # Download with path parameter
    re_path(r'^api/download/(?P<path>.+)$', views.api_download, name='api_download'),
]
