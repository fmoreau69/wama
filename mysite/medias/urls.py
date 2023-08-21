from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r'^upload_from_url/$', views.upload_from_url, name='upload_from_url'),
    re_path(r'^clear/$', views.clear_database, name='clear_database'),
    re_path(r'^refresh_content/$', views.refresh_content, name='refresh_content'),
    re_path(r'^refresh_table/$', views.refresh_table, name='refresh_table'),
    re_path(r'^refresh_options/$', views.refresh_options, name='refresh_options'),
    re_path(r'^set_options/$', views.set_options, name='set_options'),
    re_path(r'^reset_options/$', views.reset_options, name='reset_options'),

    re_path(r'^upload/$', views.UploadView.as_view(), name='upload'),

    re_path(r'^process/$', views.ProcessView.as_view(), name='process'),
    # re_path(r'^launch/$', views.ProcessView.as_view(), name='launch'),
]
