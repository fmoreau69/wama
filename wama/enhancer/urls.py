from django.urls import path
from . import views

app_name = 'enhancer'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('upload/', views.upload, name='upload'),
    path('start/<int:pk>/', views.start, name='start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('start_all/', views.start_all, name='start_all'),
    path('clear_all/', views.clear_all, name='clear_all'),
    path('download_all/', views.download_all, name='download_all'),
    path('update_settings/<int:pk>/', views.update_settings, name='update_settings'),
    path('console/', views.console_content, name='console'),
    path('global_progress/', views.global_progress, name='global_progress'),
]
