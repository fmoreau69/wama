from django.urls import path
from . import views

app_name = 'wama.composer'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('generate/', views.generate, name='generate'),
    path('import/', views.import_batch, name='import_batch'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('settings/<int:pk>/', views.update_settings, name='update_settings'),
    path('export/<int:pk>/', views.export_to_library, name='export_to_library'),
    path('batch/<int:pk>/delete/', views.batch_delete, name='batch_delete'),
    path('start_all/', views.start_all, name='start_all'),
    path('clear_all/', views.clear_all, name='clear_all'),
    path('console/', views.console_content, name='console'),
    path('global_progress/', views.global_progress, name='global_progress'),
]
