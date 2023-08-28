from django.urls import re_path

from . import views

app_name = 'mysite.accounts'

urlpatterns = [
    re_path(r'^logout/$', views.logout_view, name='logout'),
    re_path(r'^signup/$', views.signup_view, name='signup'),
    re_path(r'signin/$', views.login_view, name='login'),
    re_path(r'login/$', views.login_view, name='login'),
]
