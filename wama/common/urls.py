"""
WAMA Common - URL patterns

Shared URL patterns for common functionality across apps.
"""

from django.urls import path
from django.views.generic import RedirectView

from .utils import preview_utils
from .utils import detail_registry
from . import views

app_name = 'common'

urlpatterns = [
    # Unified preview endpoint: /common/preview/<app_name>/<pk>/
    path('preview/<str:app_name>/<int:pk>/', preview_utils.unified_preview, name='unified_preview'),
    # Unified detail (infos inspecteur) : /common/detail/<app_name>/<pk>/
    path('detail/<str:app_name>/<int:pk>/', detail_registry.unified_detail, name='unified_detail'),

    # Enrichissement de prompt à la demande (✨) — générique {prompt, app, domain}, cf. WAMA_LLM.md §Skills
    path('api/enrich-prompt/', views.api_enrich_prompt, name='enrich_prompt'),

    # System stats endpoints
    path('api/system-stats/', views.system_stats, name='system_stats'),
    path('api/system-stats/full/', views.system_stats_full, name='system_stats_full'),

    # Centralized console endpoint (role-based filtering)
    path('api/console/', views.console_content, name='console'),

    # Options de voix communes (optgroups) — consommé par WamaParams options_source='voices'
    path('api/voices/', views.api_voices, name='api_voices'),

    # App registry
    path('api/apps/', views.api_apps, name='api_apps'),
    path('apps/', views.apps_catalog_view, name='apps_catalog'),
    # Actualisation UNIVERSELLE des catalogues : une route pour tous les registres.
    # La PAGE de supervision dérive du même `overview()` que l'API : ce que l'endpoint
    # annonçait servir existe enfin.
    # ⚠ Norme des pages registres (Fabien, 01/09) : chemins et noms en ANGLAIS pluriel,
    # alignés — `registres/` et `licences/` étaient les deux seuls chemins français sur 9.
    # L'ancien chemin REDIRIGE en permanent : aucun favori ni doc historique ne casse.
    # Les endpoints `api/registres/…` restent volontairement tels quels (internes, cohérents
    # entre eux, câblés dans wama-catalog-refresh.js — périmètre tranché : pages seules).
    path('registries/', views.registres_view, name='registries'),
    path('registres/', RedirectView.as_view(pattern_name='common:registries', permanent=True)),
    path('api/registres/', views.registres_etat, name='registres_etat'),
    path('api/registres/<str:cle>/refresh/', views.registre_refresh, name='registre_refresh'),
    path('api/registres/tache/<str:task_id>/', views.registre_tache, name='registre_tache'),
    # ⚠ Conservée comme ALIAS : des pages et des scripts l'appellent. Équivaut désormais à
    # `registre_refresh('apps')` — ne PAS en créer d'autres de ce genre.
    path('api/conformity/refresh/', views.conformity_refresh, name='conformity_refresh'),

    # Licences : vue TRANSVERSALE (modèles + librairies + médias + traversée par app).
    # Domiciliée dans `common` et non `model_manager` : elle recoupe quatre registres,
    # aucun ne la contient.
    path('licenses/', views.licenses_catalog_view, name='licenses_catalog'),
    path('licences/', RedirectView.as_view(pattern_name='common:licenses_catalog', permanent=True)),

    # ABONNEMENT aux éléments de catalogue — la couche PRÉFÉRENCE (PROFILES_PERMISSIONS §8).
    # UNE route pour toutes les natures (`kind` dans le corps) : c'est ce qui fera hériter les
    # autres catalogues sans nouvel endpoint. Elle ne peut RIEN ouvrir — un droit passe par
    # une modération, pas par ce bouton.
    path('api/abonnement/', views.api_subscription, name='api_subscription'),

    # Skills de prompt : la PAGE du registre `skills`, qui existait sans elle (seul registre
    # de la carte sans `url_name`). Elle DÉRIVE des fichiers + PROMPT_TARGETS + DOMAINES, et
    # dit surtout QUI consomme quoi — un skill que rien ne résout est un fichier inerte.
    path('skills/', views.skills_catalog_view, name='skills_catalog'),
    path('backends/', views.backends_catalog_view, name='backends_catalog'),

    # Sources externes : la PAGE du registre `sources_externes` (8ᵉ registre, 2026-09-01).
    # La déclaration dérive du code ; la sonde (clé, joignabilité) est le rapport écrit par
    # le bouton hérité — en Celery, jamais dans le rendu.
    path('sources/', views.external_sources_view, name='sources_catalog'),

    # Journal transversal de l'utilisateur (WAMA_MEMORY.md §9bis) — dérive de detail_registry,
    # aucune ligne dans les apps.
    path('journal/', views.journal_view, name='journal'),

    # RAG — SURFACES du geste (jalon 14, WAMA_MEMORY.md §7ter). `rag_ajouter` est la SEULE
    # porte d'écriture offerte à l'UI : il n'existe pas de route de balayage, par décision.
    path('rag/', views.rag_view, name='rag'),
    path('api/rag/ajouter/', views.rag_ajouter, name='rag_ajouter'),
    path('api/rag/retirer/', views.rag_retirer, name='rag_retirer'),
    path('api/rag/preference/', views.rag_preference, name='rag_preference'),

    # Schéma domaines→modes d'une app (clé de voûte UX, consommé par WamaModes JS)
    path('api/app-modes/<str:app>/', views.api_app_modes, name='api_app_modes'),
    path('modes-demo/', views.modes_demo, name='modes_demo'),

]
