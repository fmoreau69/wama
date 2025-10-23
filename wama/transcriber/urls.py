from django.urls import path
from . import views

app_name = 'wama.transcriber'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('upload/', views.upload, name='upload'),
    path('start/<int:pk>/', views.start, name='start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('download/<int:pk>/', views.download, name='download'),
    path('about/', views.AboutView.as_view(), name='about'),
    path('help/', views.HelpView.as_view(), name='help'),
]