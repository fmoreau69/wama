"""
Les registres catalogués de WAMA — DÉCLARATIONS.

Chaque entrée branche un rafraîchisseur qui **existait déjà** : ce fichier ne réécrit aucune
mécanique de synchronisation, il les rend uniformes et joignables par une clé. C'est le seul
travail qu'il restait à faire — les deux tiers du mécanisme étaient là, éparpillés.

Relevé du 2026-08-22 avant écriture :
  • 7 surfaces catalogues, **2 seulement** avaient un bouton (modèles, grille de conformité) ;
  • **1 seule** était actualisée périodiquement (modèles, via Celery Beat) ;
  • chaque bouton avait son endpoint, son script inline et ses libellés propres.
"""
from __future__ import annotations

from .registries import (DERIVED, MEASURE, REDECLARATION, SCAN, Registry, RefreshResult, register)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# MODÈLES — scan du disque vers le catalogue `AIModel`
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _refresh_models() -> RefreshResult:
    from wama.model_manager.services.model_sync import get_sync_service
    r = get_sync_service().full_sync(remove_missing=False, delete_missing=True)
    return RefreshResult(ok=bool(r.success), added=r.added, updated=r.updated, removed=r.removed,
                    messages=tuple((r.errors or [])[:5]))


def _count_models() -> int:
    from wama.model_manager.models import AIModel
    return AIModel.objects.count()


register(Registry(
    key='modeles', label='Modèles IA', nature=SCAN,
    source="Fichiers de `AI-models/` + déclarations `model_config` des apps",
    refresh=_refresh_models, count=_count_models,
    url_name='model_manager:index', manifest_kind='model',
    periodic='model-manager-reconcile',
    description="Réconcilie le catalogue avec ce qui est réellement présent sur le disque. "
                "Une entrée dont les fichiers ont disparu est supprimée — d'où la réserve staff.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# APPLICATIONS — la grille de conformité est la partie MESURÉE de la page
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _refresh_apps() -> RefreshResult:
    from .app_registry import measure_and_write_conformity
    rapport = measure_and_write_conformity()
    apps = rapport.get('apps', {})
    return RefreshResult(ok=True, updated=len(apps), total=len(apps),
                    messages=(f"mesurée le {rapport.get('generated_at', '?')}",))


def _count_apps() -> int:
    from .app_registry import APP_CATALOG
    return len(APP_CATALOG)


register(Registry(
    key='apps', label='Applications', nature=MEASURE,
    source="`APP_CATALOG` (déclaré en code) + grille de conformité MESURÉE depuis le code réel",
    refresh=_refresh_apps, count=_count_apps,
    url_name='common:apps_catalog', manifest_kind='app',
    periodic='nightly-consistency',
    doc='WAMA_APP_CONVENTIONS.md',
    description="Le catalogue lui-même est déclaré en code — rien à y actualiser. Ce qui "
                "s'actualise est la GRILLE : 72 critères re-mesurés par analyse du code.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# FONCTIONS — registre en mémoire, peuplé par import au `ready()` de chaque monde
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _forget_module(module_name: str) -> None:
    """Désimporte VRAIMENT un module — `sys.modules` **et** l'attribut du paquet parent.

    ⚠ Retirer de `sys.modules` seul ne suffit pas, et l'oublier produit un bug qui ne se voit qu'à
    la deuxième actualisation : `from . import X` interroge d'abord l'ATTRIBUT du paquet parent.
    Tant qu'il pointe sur l'ancien module, l'import est court-circuité — le fichier réécrit n'est
    jamais relu et ses fonctions n'apparaissent pas. Mesuré : le test « ajoutée à chaud » passait
    seul et échouait après le test « supprimée à chaud ».
    """
    import sys
    sys.modules.pop(module_name, None)
    parent, _, feuille = module_name.rpartition('.')
    mod_parent = sys.modules.get(parent) if parent else None
    if mod_parent is not None and hasattr(mod_parent, feuille):
        try:
            delattr(mod_parent, feuille)
        except AttributeError:
            pass


def _refresh_functions() -> RefreshResult:
    """Re-déclare le catalogue de fonctions en RECHARGEANT les modules déclarants.

    ⚠ `load_all()` ne suffit pas et c'est le piège : `importlib.import_module` rend le module
    DÉJÀ importé, donc une fonction ajoutée pendant que le serveur tourne reste invisible. Il faut
    `reload`. Mais `register()` lève sur clé dupliquée — recharger sans vider ferait donc échouer
    le premier module rechargé.

    D'où la séquence : instantané → purge → rechargement → restauration si quoi que ce soit casse.
    Un catalogue à moitié rechargé serait pire que pas de rechargement du tout.
    """
    import importlib
    import os
    import sys
    from django.apps import apps as django_apps
    from .catalog.function_catalog import FUNCTION_CATALOG, MODULES_DECLARANTS, load_all

    # ⚠ SANS ceci, un fichier CRÉÉ pendant que le serveur tourne reste invisible : le chercheur de
    # modules garde en cache le listing du répertoire, et `from . import nouveau` échoue ou ne fait
    # rien. C'est la condition documentée pour importer du code apparu après le démarrage — et le
    # cas exact que cette actualisation existe pour couvrir.
    importlib.invalidate_caches()

    avant = dict(FUNCTION_CATALOG)
    modules = [f'{c.name}.{m}' for c in django_apps.get_app_configs()
               for m in MODULES_DECLARANTS if f'{c.name}.{m}' in sys.modules]
    FUNCTION_CATALOG.clear()
    disparus = 0
    try:
        for module_name in modules:
            # Recharger le paquet déclarant ne recharge pas ses sous-modules : ce sont eux qui
            # portent les `register()`. On les recharge donc en profondeur, parents d'abord.
            for sous in sorted(m for m in list(sys.modules)
                               if m == module_name or m.startswith(module_name + '.')):
                mod = sys.modules.get(sous)
                if mod is None:
                    continue
                source = getattr(mod, '__file__', None)
                if source and not os.path.exists(source):
                    # ⚠ Fichier SUPPRIMÉ pendant que le serveur tourne. Le recharger lève, et une
                    # levée ici restaurerait l'instantané — donc les fonctions du fichier effacé
                    # survivraient à leur propre suppression.
                    _forget_module(sous)
                    disparus += 1
                    continue
                importlib.reload(mod)
        load_all()
    except Exception:
        FUNCTION_CATALOG.clear()
        FUNCTION_CATALOG.update(avant)
        raise

    apres = dict(FUNCTION_CATALOG)
    added = len(set(apres) - set(avant))
    removed = len(set(avant) - set(apres))
    messages = [f"{len(modules)} module(s) déclarant(s) rechargé(s)"]
    if disparus:
        messages.append(f"{disparus} module(s) dont le fichier a disparu, retiré(s)")
    return RefreshResult(ok=True, added=added, removed=removed,
                    updated=len(set(apres) & set(avant)), total=len(apres),
                    messages=tuple(messages))


def _count_functions() -> int:
    from .catalog.function_catalog import FUNCTION_CATALOG
    return len(FUNCTION_CATALOG)


register(Registry(
    key='fonctions', label='Fonctions de traitement', nature=REDECLARATION,
    source="`apps.py:ready()` de chaque monde — `wama_data`, `wama_lab.cam_analyzer`…",
    refresh=_refresh_functions, count=_count_functions,
    url_name='model_manager:function_catalog', manifest_kind='function',
    doc='WAMA_DATA_FUNCTION_CARDS.md',
    description="Recharge les modules qui déclarent des `FunctionSpec`. Rend visibles les "
                "fonctions ajoutées pendant que le serveur tourne, sans redémarrage.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# SKILLS DE PROMPT — fichiers `.md` sur disque, lus avec cache
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _refresh_skills() -> RefreshResult:
    """⚠ `removed` compte les entrées perdues par le REGISTRE, jamais les lignes de cache vidées.

    Première version : elle rendait `removed = len(cache)`, donc « 10 retirés » à chaque passage
    alors qu'aucun skill ne disparaissait — un compte-rendu qui alarme sans raison. Trouvé par le
    contrôle générique d'idempotence, pas à la lecture : les deux passages rendaient le même
    chiffre, ce qui ressemblait à un résultat stable.
    """
    from .utils import prompt_skills
    avant = set(prompt_skills.skills_catalog())
    vidées = len(prompt_skills._cache)
    prompt_skills._cache.clear()
    apres = set(prompt_skills.skills_catalog())
    return RefreshResult(ok=True, added=len(apres - avant), removed=len(avant - apres),
                    updated=len(apres & avant), total=len(apres),
                    messages=(f"cache vidé ({vidées} entrée(s)) — fichiers relus à la demande",))


def _count_skills() -> int:
    from .utils import prompt_skills
    return len(prompt_skills.skills_catalog())


register(Registry(
    key='skills', label='Skills de prompt', nature=REDECLARATION,
    source="Fichiers `wama/common/prompt_skills/*.md`",
    refresh=_refresh_skills, count=_count_skills,
    permission='auth', on_startup=False,
    # Sa page, enfin (27/08). Il était le seul registre de la carte à n'en désigner aucune :
    # le catalogue n'était lisible que par l'assistant et wama-dev-ai.
    url_name='common:skills_catalog',
    doc='WAMA_LLM.md',
    description="Vide le cache de lecture des skills : un `.md` modifié à chaud est repris sans "
                "redémarrage. Sans effet de bord partagé, donc ouvert à tout compte connecté.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# SOURCES EXTERNES — la sonde est la valeur de la page (8ᵉ registre, 2026-09-01)
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _refresh_external_sources() -> RefreshResult:
    """Sonde chaque source déclarée (clé posée ? joignable ?) et écrit le rapport.

    Nature `mesure`, PAS `derive` : la déclaration est bien dérivable à chaque requête, mais la
    valeur de la page est la SONDE — quatorze requêtes réseau qui n'ont rien à faire dans un
    rendu de page ni dans un worker web. D'où Celery, comme la grille de conformité.
    """
    from .external_sources import probe_all
    rapport = probe_all(write=True)
    c = rapport['counts']
    morceaux = [f"{c['reachable']} joignable(s)"]
    if c['unreachable']:
        morceaux.append(f"{c['unreachable']} injoignable(s)")
    if c['unconfigured']:
        morceaux.append(f"{c['unconfigured']} sans clé")
    return RefreshResult(ok=True, updated=c['total'], total=c['total'],
                    messages=(' · '.join(morceaux),))


def _count_external_sources() -> int:
    from .external_sources import SOURCES
    return len(SOURCES)


register(Registry(
    key='sources_externes', label='Sources externes', nature=MEASURE,
    source="Registre déclaratif `common/external_sources.py` + sonde réseau (clé, joignabilité)",
    refresh=_refresh_external_sources, count=_count_external_sources,
    url_name='common:external_sources_catalog',
    doc='WAMA_MECANISMES.md',
    description="Sonde chaque source déclarée : clé d'API posée ? adresse joignable (proxy UGE "
                "compris) ? La déclaration, elle, ne s'actualise pas — elle vit en code. "
                "Réservé au staff : la sonde émet des requêtes sortantes et écrit un rapport.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Les DÉRIVÉS — rien à actualiser, et c'est une PROPRIÉTÉ, pas un manque
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _count_libraries() -> int:
    from .models import Library
    return Library.objects.count()


register(Registry(
    key='librairies', label='Librairies externes', nature=DERIVED,
    source="Registre `Library` (projeté par les manifestes) + mesure live `importlib.metadata`",
    count=_count_libraries,
    url_name='model_manager:library_catalog', manifest_kind='library',
    doc='LICENSING.md',
    description="La page mesure l'installation réelle à CHAQUE affichage et compare au déclaré : "
                "l'écart affiché ne peut pas être périmé. Le registre lui-même s'alimente par la "
                "projection des manifestes, pas par un scan.",
))


register(Registry(
    key='licences', label='Licences', nature=DERIVED,
    source="Agrégation de `AIModel`, `Library`, médias et des `requires` des manifestes d'app",
    url_name='common:licenses_catalog',
    doc='LICENSING.md',
    description="Vue transversale sans registre propre — « une page qui DÉRIVE ne peut pas "
                "diverger de ses sources ». Un bouton d'actualisation y serait un mensonge : "
                "actualiser les licences, c'est actualiser modèles et librairies.",
))


register(Registry(
    key='rag', label='Mon RAG', nature=DERIVED,
    source="Ce que l'utilisateur a confié au RAG (`common/memory/`, Postgres + pgvector)",
    url_name='common:rag', permission='auth',
    doc='WAMA_MEMORY.md',
    description="Liste ce que CE compte a ajouté, lu en base à chaque affichage. L'entrée au RAG "
                "est un geste explicite : rien ne s'y ajoute par balayage, donc rien à réconcilier.",
))
