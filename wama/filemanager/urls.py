"""
FileManager URL configuration.
"""
from django.urls import path, re_path
from . import views

app_name = 'filemanager'

urlpatterns = [
    # API endpoints
    path('api/tree/', views.api_tree, name='api_tree'),
    path('api/children/', views.api_children, name='api_children'),
    path('api/tree/mtime/', views.api_tree_mtime, name='api_tree_mtime'),
    path('api/search/', views.api_search, name='api_search'),
    path('api/upload/', views.api_upload, name='api_upload'),
    path('api/delete/', views.api_delete, name='api_delete'),
    path('api/delete-all/', views.api_delete_all, name='api_delete_all'),
    path('api/rename/', views.api_rename, name='api_rename'),
    path('api/move/', views.api_move, name='api_move'),
    path('api/mkdir/', views.api_mkdir, name='api_mkdir'),
    path('api/info/', views.api_info, name='api_info'),
    path('api/preview/', views.api_preview, name='api_preview'),
    path('api/import/', views.api_import_to_app, name='api_import'),

    # Download with path parameter
    re_path(r'^api/download/(?P<path>.+)$', views.api_download, name='api_download'),

    # Mounted folders
    path('api/find-folder/', views.api_find_folder, name='api_find_folder'),
    path('api/validate-path/', views.api_validate_path, name='api_validate_path'),
    path('api/browse-fs/', views.api_browse_fs, name='api_browse_fs'),
    path('api/mounts/', views.api_mounts, name='api_mounts'),
    path('api/mounts/<int:pk>/delete/', views.api_mount_delete, name='api_mount_delete'),
    re_path(r'^api/mounts/(?P<pk>\d+)/serve/(?P<path>.*)$', views.api_mount_serve, name='api_mount_serve'),
]
