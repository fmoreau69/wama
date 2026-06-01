from django.urls import path
from . import views

app_name = 'converter'

urlpatterns = [
    path('',                            views.IndexView.as_view(),  name='index'),
    path('upload/',                     views.upload,               name='upload'),
    path('quick/',                      views.quick_convert,        name='quick_convert'),
    path('start-all/',                  views.start_all,            name='start_all'),
    path('clear-all/',                  views.clear_all,            name='clear_all'),
    path('<int:pk>/start/',             views.start,                name='start'),
    path('<int:pk>/status/',            views.status,               name='status'),
    path('<int:pk>/update/',            views.update_job,           name='update'),
    path('<int:pk>/download/',          views.download,             name='download'),
    path('<int:pk>/delete/',            views.delete,               name='delete'),
    path('<int:pk>/duplicate/',         views.duplicate,            name='duplicate'),
    # Profiles
    path('profiles/',                   views.profile_list,         name='profile_list'),
    path('profiles/save/',              views.profile_save,         name='profile_save'),
    path('profiles/<int:pk>/delete/',   views.profile_delete,       name='profile_delete'),
]
