from django.urls import path
from . import views

app_name = 'converter'

urlpatterns = [
    path('',                            views.IndexView.as_view(),  name='index'),
    path('upload/',                     views.upload,               name='upload'),
    path('quick/',                      views.quick_convert,        name='quick_convert'),
    path('<int:pk>/dismiss/',           views.dismiss,              name='dismiss'),
    path('<int:pk>/cancel/',            views.cancel,               name='cancel'),
    path('start-all/',                  views.start_all,            name='start_all'),
    path('clear-all/',                  views.clear_all,            name='clear_all'),
    path('<int:pk>/start/',             views.start,                name='start'),
    path('<int:pk>/status/',            views.status,               name='status'),
    path('<int:pk>/update/',            views.update_job,           name='update'),
    path('<int:pk>/download/',          views.download,             name='download'),
    path('<int:pk>/delete/',            views.delete,               name='delete'),
    path('<int:pk>/duplicate/',         views.duplicate,            name='duplicate'),
    # Batch import
    path('consolidate/',                views.consolidate,          name='consolidate'),
    path('batch/preview/',              views.batch_preview,        name='batch_preview'),
    path('batch/create/',               views.batch_create,         name='batch_create'),
    # Batch (groupe)
    path('batch/<int:pk>/start/',       views.batch_start,          name='batch_start'),
    path('batch/<int:pk>/update/',      views.batch_update,         name='batch_update'),
    path('batch/<int:pk>/delete/',      views.batch_delete,         name='batch_delete'),
    # Profiles
    path('profiles/',                   views.profile_list,         name='profile_list'),
    path('profiles/save/',              views.profile_save,         name='profile_save'),
    path('profiles/<int:pk>/delete/',   views.profile_delete,       name='profile_delete'),
]
