from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r'^clear/$', views.clear_database, name='clear_database'),
    re_path(r'^refresh_table/$', views.refresh_table, name='refresh_table'),
    re_path(r'^set_options/$', views.set_options, name='set_options'),
    re_path(r'^reset_options/$', views.reset_options, name='reset_options'),

    re_path(r'^upload/$', views.UploadView.as_view(), name='upload'),
    re_path(r'^launch/$', views.UploadView.launch_process, name='launch'),
    # re_path(r'^update_options/$', views.UploadView.update_options, name='update_options'),
    re_path(r'^launch_with_options/$', views.UploadView.launch_process_with_options, name='launch_with_options'),

    re_path(r'^process/$', views.ProcessView.as_view(), name='process')
]
