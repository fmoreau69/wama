from django.urls import path, re_path, reverse_lazy
from django.views.generic.base import RedirectView

from . import views

app_name = 'wama.accounts'

urlpatterns = [
    re_path(r'^logout/$', views.logout_view, name='logout'),
    re_path(r'^signup/$', views.signup_view, name='signup'),
    re_path(r'signin/$', views.login_view, name='login'),
    re_path(r'login/$', views.login_view, name='login'),
    path('users/<int:pk>/', views.UserPage.as_view(), name='user-page'),
    path('users/add/', RedirectView.as_view(url=reverse_lazy('accounts:signup')), name='insert'),
    path('user/edit', views.UserEdit.as_view(), name='user-edit'),
    path('user/settings/edit/', views.UserSettingsUpdate.as_view(), name='settings-edit'),
    # path('<str:app>/insert', views.new_item, name='insert'),
    # path('<str:app>/insert/<str:item_id>', views.new_item, name='insert'),
]
