from django.urls import path, re_path, reverse_lazy
from django.views.generic.base import RedirectView

from . import views

app_name = 'accounts'

urlpatterns = [
    re_path(r'^logout/$', views.logout_view, name='logout'),
    re_path(r'^signup/$', views.signup_view, name='signup'),
    re_path(r'signin/$', views.login_view, name='login'),
    re_path(r'login/$', views.login_view, name='login'),
    path('users/<int:pk>/', views.UserPage.as_view(), name='user-page'),
    path('users/add/', RedirectView.as_view(url=reverse_lazy('accounts:signup')), name='insert'),
    path('user/edit', views.UserEdit.as_view(), name='user-edit'),
    path('user/settings/edit/', views.UserSettingsUpdate.as_view(), name='settings-edit'),

    # User Management (Admin only)
    path('users/', views.user_management, name='user-management'),
    path('users/new/', views.user_add, name='user-add'),
    path('users/<int:user_id>/delete/', views.user_delete, name='user-delete'),
    path('users/<int:user_id>/role/', views.user_update_role, name='user-update-role'),
    path('users/<int:user_id>/toggle-active/', views.user_toggle_active, name='user-toggle-active'),
]
