from django.urls import path
from . import views

app_name = 'media_library'

urlpatterns = [
    path('',                              views.index,           name='index'),

    # Assets utilisateur
    path('api/counts/',                   views.api_counts,           name='api_counts'),
    path('api/assets/',                   views.api_list,             name='api_list'),
    path('api/assets/upload/',            views.api_upload,           name='api_upload'),
    path('api/assets/<int:pk>/edit/',     views.api_edit,             name='api_edit'),
    path('api/assets/<int:pk>/delete/',   views.api_delete,           name='api_delete'),
    path('api/assets/<int:pk>/promote/',  views.api_promote,          name='api_promote'),

    # Assets système
    path('api/system/',                   views.api_system_list,      name='api_system_list'),

    # Bibliothèque de mots-clés de prompt (tronc commun + perso)
    path('api/keywords/',                 views.api_prompt_keywords,       name='api_prompt_keywords'),
    path('api/keywords/add/',             views.api_prompt_keyword_add,    name='api_prompt_keyword_add'),
    path('api/keywords/<int:pk>/delete/', views.api_prompt_keyword_delete, name='api_prompt_keyword_delete'),

    # Providers — Phase 3
    path('api/providers/',                views.api_providers_list,   name='api_providers_list'),
    path('api/providers/keys/',           views.api_provider_keys,    name='api_provider_keys'),
    path('api/providers/<slug:slug>/key/', views.api_provider_key_save, name='api_provider_key_save'),
    path('api/search/',                   views.api_provider_search,  name='api_provider_search'),
    path('api/search/download/',          views.api_provider_download, name='api_provider_download'),
]
