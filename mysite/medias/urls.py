from django.urls import path, re_path

from . import views

app_name = 'mysite.medias'

urlpatterns = [
    path('upload_from_url/', views.upload_from_url, name='upload_from_url'),
    path('refresh_content/', views.refresh_content, name='refresh_content'),
    path('refresh_media_table/', views.refresh_media_table, name='refresh_media_table'),
    path('refresh_media_settings/', views.refresh_media_settings, name='refresh_media_settings'),
    path('refresh_global_settings/', views.refresh_global_settings, name='refresh_global_settings'),

    path('clear_database/', views.clear_database, name='clear_database'),
    path('clear_media/', views.clear_media, name='clear_media'),
    path('reset_media_settings/', views.reset_media_settings, name='reset_media_settings'),
    path('reset_user_settings/', views.reset_user_settings, name='reset_user_settings'),
    path('init_user_settings/', views.init_user_settings, name='init_user_settings'),
    path('init_global_settings/', views.init_global_settings, name='init_global_settings'),
    path('update_settings/', views.update_settings, name='update_settings'),

    path('download_media/<int:pk>/', views.download_media, name='download_media'),
    path('stop_process/', views.stop, name='stop_process'),
    path('expand_area/', views.expand_area, name='expand_area'),

    path('upload/', views.UploadView.as_view(), name='upload'),
    path('process/', views.ProcessView.as_view(), name='process'),
    path('display_console/', views.ProcessView.display_console, name='display_console'),

]
