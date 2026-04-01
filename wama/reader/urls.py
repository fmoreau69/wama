from django.urls import path
from . import views

app_name = 'wama.reader'

urlpatterns = [
    path('',                        views.IndexView.as_view(), name='index'),
    path('upload/',                 views.upload,              name='upload'),
    path('start/<int:pk>/',         views.start,               name='start'),
    path('analyze/<int:pk>/',       views.analyze,             name='analyze'),
    path('settings/<int:pk>/',      views.save_settings,       name='save_settings'),
    path('progress/<int:pk>/',      views.progress,            name='progress'),
    path('text/<int:pk>/',          views.text_view,           name='text'),
    path('download/<int:pk>/',      views.download,            name='download'),
    path('delete/<int:pk>/',        views.delete,              name='delete'),
    path('duplicate/<int:pk>/',     views.duplicate,           name='duplicate'),
    path('start_all/',              views.start_all,           name='start_all'),
    path('clear_all/',              views.clear_all,           name='clear_all'),
    path('download-all/',           views.download_all,        name='download_all'),
    path('console/',                views.console_content,     name='console'),
    path('global-progress/',        views.global_progress,     name='global_progress'),
    # Batch
    path('batch/template/',                     views.batch_template,   name='batch_template'),
    path('batch/preview/',                      views.batch_preview,    name='batch_preview'),
    path('batch/create/',                       views.batch_create,     name='batch_create'),
    path('batch/list/',                         views.batch_list,       name='batch_list'),
    path('batch/<int:pk>/start/',               views.batch_start,      name='batch_start'),
    path('batch/<int:pk>/status/',              views.batch_status,     name='batch_status'),
    path('batch/<int:pk>/download/',            views.batch_download,   name='batch_download'),
    path('batch/<int:pk>/delete/',              views.batch_delete,     name='batch_delete'),
    path('batch/<int:pk>/duplicate/',           views.batch_duplicate,  name='batch_duplicate'),
    path('batch/<int:pk>/update/',              views.batch_update,     name='batch_update'),
]
