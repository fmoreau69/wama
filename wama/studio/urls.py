from django.urls import path

from . import views

app_name = 'studio'

urlpatterns = [
    path('', views.index, name='index'),
    path('api/nodes/', views.api_nodes, name='api_nodes'),
]
