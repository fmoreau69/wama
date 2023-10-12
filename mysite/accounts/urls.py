from django.urls import path, re_path, reverse_lazy
from django.views.generic.base import RedirectView

from . import views

app_name = 'mysite.accounts'

urlpatterns = [
    re_path(r'^logout/$', views.logout_view, name='logout'),
    re_path(r'^signup/$', views.signup_view, name='signup'),
    re_path(r'signin/$', views.login_view, name='login'),
    re_path(r'login/$', views.login_view, name='login'),
    path('users/<int:pk>/', views.UserPage.as_view(), name='user-page'),
    path('users/add/', RedirectView.as_view(url=reverse_lazy('accounts:signup')), name='insert'),
    path('user/edit', views.UserEdit.as_view(), name='user-edit'),
    path('user/details/edit/', views.UserDetailsUpdate.as_view(), name='details-edit'),
    # re_path('user/link/add', views.UserLinkInsert.as_view(), name='user-link-add'),
    # re_path('user/link/edit/<int:pk>/', views.UserLinkUpdate.as_view(), name='user-link-edit'),
    # re_path('user/link/delete/<int:pk>/', views.UserLinkDelete.as_view(), name='user-link-delete'),
]
