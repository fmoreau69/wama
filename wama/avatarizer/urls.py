from django.urls import path
from . import views

app_name = 'avatarizer'

urlpatterns = [
    path('', views.IndexView.as_view(), name='index'),
    path('create/', views.create, name='create'),
    path('start/<int:pk>/', views.start, name='start'),
    path('progress/<int:pk>/', views.progress, name='progress'),
    path('delete/<int:pk>/', views.delete, name='delete'),
    path('download/<int:pk>/', views.download, name='download'),
    path('gallery/', views.gallery_list, name='gallery_list'),
    path('update-options/<int:pk>/', views.update_options, name='update_options'),
    path('extract-text/', views.extract_text, name='extract_text'),
]
