from django.urls import path
from . import views

app_name = 'avatarizer'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('create/', views.create, name='create'),
    path('start/<int:pk>/', views.start, name='start'),
    path('stop/<int:pk>/', views.stop, name='stop'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('global_progress/', views.global_progress, name='global_progress'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('download/<int:pk>/', views.download, name='download'),
    path('gallery/', views.gallery_list, name='gallery_list'),
    path('update-options/<int:pk>/', views.update_options, name='update_options'),
    path('duplicate/<int:pk>/', views.duplicate, name='duplicate'),
    path('extract-text/', views.extract_text, name='extract_text'),

    # Batch — import par fichier + opérations de lot
    path('batch/template/', views.batch_template, name='batch_template'),
    path('batch/preview/', views.batch_preview, name='batch_preview'),
    path('batch/create/', views.batch_create, name='batch_create'),
    path('batch/consolidate/', views.consolidate, name='consolidate'),
    path('batch/<int:pk>/start/', views.batch_start, name='batch_start'),
    path('batch/<int:pk>/update/', views.batch_update, name='batch_update'),
    path('batch/<int:pk>/duplicate/', views.batch_duplicate, name='batch_duplicate'),
    path('batch/<int:pk>/download/', views.batch_download, name='batch_download'),
    path('batch/<int:pk>/delete/', views.batch_delete, name='batch_delete'),
]
