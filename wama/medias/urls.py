from django.urls import path

from . import views

app_name = 'wama.medias'

urlpatterns = [
    path('refresh/', views.refresh, name='refresh'),
    path('update_settings/', views.update_settings, name='update_settings'),
    path('clear_all_media/', views.clear_all_media, name='clear_all_media'),
    path('clear_media/', views.clear_media, name='clear_media'),
    path('reset_media_settings/', views.reset_media_settings, name='reset_media_settings'),
    path('reset_user_settings/', views.reset_user_settings, name='reset_user_settings'),
    path('process_progress/', views.get_process_progress, name='process_progress'),

    path("check_all_processed/", views.check_all_processed, name="check_all_processed"),
    path('download_all_media/', views.download_all_media, name='download_all_media'),
    path('download_media/', views.download_media, name='download_media'),
    path('expand_area/', views.expand_area, name='expand_area'),
    path('stop_process/', views.stop_process_view, name='stop_process'),
    path('console_content/', views.console_content, name='console_content'),
    path('preview/<int:media_id>/', views.preview_media, name='preview_media'),

    path('upload/', views.UploadView.as_view(), name='upload'),
    path('process/', views.ProcessView.as_view(), name='process'),
    path('about/', views.AboutView.as_view(), name='about'),
    path('help/', views.HelpView.as_view(), name='help'),
    path('display_console/', views.ProcessView.display_console, name='display_console'),
]
