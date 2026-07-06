from django.urls import path
from . import views

app_name = 'wama.composer'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('generate/', views.generate, name='generate'),
    path('import/', views.import_batch, name='import_batch'),
    path('batch/preview/', views.batch_preview, name='batch_preview'),
    path('batch/template/', views.batch_template, name='batch_template'),
    path('batch/<int:pk>/start/', views.batch_start, name='batch_start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('card/<int:pk>/html/', views.card_html, name='card_html'),
    path('download/<int:pk>/', views.download, name='download'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('settings/<int:pk>/', views.update_settings, name='update_settings'),
    path('start/<int:pk>/', views.start, name='start'),
    path('stop/<int:pk>/', views.stop, name='stop'),
    path('export/<int:pk>/', views.export_to_library, name='export_to_library'),
    path('duplicate/<int:pk>/', views.duplicate, name='duplicate'),
    path('download-all/', views.download_all, name='download_all'),
    path('batch/<int:pk>/update/', views.batch_update, name='batch_update'),
    path('batch/<int:pk>/delete/', views.batch_delete, name='batch_delete'),
    path('batch/<int:pk>/duplicate/', views.batch_duplicate, name='batch_duplicate'),
    path('batch/<int:pk>/download/', views.batch_download, name='batch_download'),
    # Manipulation directe (brique commune queue_manipulation, 2026-07-06)
    path('reorder/', views.reorder, name='reorder'),
    path('move-to-batch/<int:pk>/', views.move_to_batch, name='move_to_batch'),
    path('remove-from-batch/<int:pk>/', views.remove_from_batch, name='remove_from_batch'),
    path('consolidate/', views.consolidate, name='consolidate'),
    path('start_all/', views.start_all, name='start_all'),
    path('clear_all/', views.clear_all, name='clear_all'),
    path('console/', views.console_content, name='console'),
    path('global_progress/', views.global_progress, name='global_progress'),
]
