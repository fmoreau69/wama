from django.urls import path
from . import views

app_name = 'media_library'

urlpatterns = [
    path('',                              views.index,           name='index'),
    path('api/assets/',                   views.api_list,        name='api_list'),
    path('api/assets/upload/',            views.api_upload,      name='api_upload'),
    path('api/assets/<int:pk>/delete/',   views.api_delete,      name='api_delete'),
    path('api/system/',                   views.api_system_list, name='api_system_list'),
]
