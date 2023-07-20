from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r'^clear/$', views.clear_database, name='clear_database'),
    re_path(r'^set_options/$', views.set_options, name='set_options'),

    re_path(r'^upload/$', views.UploadView.as_view(), name='upload'),
    re_path(r'^launch/$', views.UploadView.launch_process, name='launch'),

    re_path(r'^options/$', views.OptionsView.as_view(), name='options'),
    re_path(r'^reset_options/$', views.reset_options, name='reset_options'),
    re_path(r'^launch_with_options/$', views.OptionsView.launch_process_with_options, name='launch_with_options'),

    re_path(r'^process/$', views.ProcessView.as_view(), name='process')
]
