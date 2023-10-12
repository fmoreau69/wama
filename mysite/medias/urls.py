from django.urls import path, re_path

from . import views

app_name = 'mysite.medias'

urlpatterns = [
    path('upload_from_url/', views.upload_from_url, name='upload_from_url'),
    path('clear/', views.clear_database, name='clear_database'),
    path('refresh_content/', views.refresh_content, name='refresh_content'),
    path('refresh_table/', views.refresh_table, name='refresh_table'),
    path('refresh_options/', views.refresh_options, name='refresh_options'),
    path('init_options/', views.init_options, name='init_options'),
    path('reset_options/', views.reset_options, name='reset_options'),
    path('update_options/', views.update_options, name='update_options'),
    path('download_media/<int:pk>/', views.download_media, name='download_media'),
    path('stop_process/', views.stop, name='stop_process'),
    path('show_ms/<int:pk>/', views.show_media_settings, name='show_ms'),
    path('show_gs/', views.show_global_settings, name='show_gs'),

    path('upload/', views.UploadView.as_view(), name='upload'),

    path('process/', views.ProcessView.as_view(), name='process'),
    path('display_console/', views.ProcessView.display_console, name='display_console'),

    # path('download_media/<int:pk>/', views.DownloadMediaView.as_view(), name='download_media'),
]
