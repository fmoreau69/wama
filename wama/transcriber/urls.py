from django.urls import path
from . import views

app_name = 'wama.transcriber'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('upload/', views.upload, name='upload'),
    path('start/<int:pk>/', views.start, name='start'),
    path('start_all/', views.start_all, name='start_all'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('download_all/', views.download_all, name='download_all'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('clear_all/', views.clear_all, name='clear_all'),
    path('console/', views.console_content, name='console'),
    path('about/', views.AboutView.as_view(), name='about'),
    path('help/', views.HelpView.as_view(), name='help'),
    path('preprocessing/toggle/', views.toggle_preprocessing, name='toggle_preprocessing'),
    path('preprocessing/status/', views.preprocessing_status, name='preprocessing_status'),
    path('preprocessing/set/', views.set_preprocessing_preference, name='set_preprocessing'),
]