from django.urls import re_path

from . import views

urlpatterns = [
    re_path(r'^clear/$', views.clear_database, name='clear_database'),
    re_path(r'^upload/$', views.UploadView.as_view(), name='upload'),
    re_path(r'^options/$', views.OptionsView.as_view(), name='options'),
    re_path(r'^process/$', views.ProcessView.as_view(), name='process')
]
