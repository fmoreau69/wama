from django.urls import path
from wama.common.views import AppAboutView, AppHelpView
from . import views

app_name = 'converter'

urlpatterns = [
    path('',                            views.IndexView.as_view(),  name='index'),
    path('upload/',                     views.upload,               name='upload'),
    path('quick/',                      views.quick_convert,        name='quick_convert'),
    path('<int:pk>/dismiss/',           views.dismiss,              name='dismiss'),
    path('<int:pk>/cancel/',            views.cancel,               name='cancel'),
    path('start-all/',                  views.start_all,            name='start_all'),
    path('download-all/',               views.download_all,         name='download_all'),
    path('clear-all/',                  views.clear_all,            name='clear_all'),
    path('<int:pk>/start/',             views.start,                name='start'),
    path('<int:pk>/status/',            views.status,               name='status'),
    path('global_progress/',            views.global_progress,      name='global_progress'),
    path('<int:pk>/update/',            views.update_job,           name='update'),
    path('<int:pk>/download/',          views.download,             name='download'),
    path('<int:pk>/delete/',            views.delete,               name='delete'),
    path('<int:pk>/duplicate/',         views.duplicate,            name='duplicate'),
    # Card = partial serveur unique
    path('card/<int:pk>/html/',         views.card_html,            name='card_html'),
    # Console app (brique commune)
    path('console/',                    views.console_content,      name='console'),
    # Aide / À-propos (brique commune : redirection vers l'onglet du gabarit)
    path('about/',                      AppAboutView.as_view(),     name='about'),
    path('help/',                       AppHelpView.as_view(),      name='help'),
    # Manipulation directe de la file (fabrique commune, variante FK-directe)
    path('reorder/',                    views.reorder,              name='reorder'),
    path('reorder-queue/',              views.reorder_queue,        name='reorder_queue'),
    path('merge/',                      views.merge,                name='merge'),
    path('move-to-batch/<int:pk>/',     views.move_to_batch,        name='move_to_batch'),
    path('remove-from-batch/<int:pk>/', views.remove_from_batch,    name='remove_from_batch'),
    # Batch import
    path('consolidate/',                views.consolidate,          name='consolidate'),
    path('batch/template/',             views.batch_template,       name='batch_template'),
    path('batch/preview/',              views.batch_preview,        name='batch_preview'),
    path('batch/create/',               views.batch_create,         name='batch_create'),
    # Batch (groupe)
    path('batch/<int:pk>/start/',       views.batch_start,          name='batch_start'),
    path('batch/<int:pk>/update/',      views.batch_update,         name='batch_update'),
    path('batch/<int:pk>/delete/',      views.batch_delete,         name='batch_delete'),
    path('batch/<int:pk>/duplicate/',   views.batch_duplicate,      name='batch_duplicate'),
    path('batch/<int:pk>/download/',    views.batch_download,       name='batch_download'),
    # Profiles
    path('api/presets/',                views.api_presets,          name='api_presets'),
    path('profiles/',                   views.profile_list,         name='profile_list'),
    path('profiles/save/',              views.profile_save,         name='profile_save'),
    path('profiles/<int:pk>/delete/',   views.profile_delete,       name='profile_delete'),
]
