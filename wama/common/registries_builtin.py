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


def _entries_apps() -> dict:
    """Les fiches d'`APP_CATALOG`, adressables par une balise de doc (`fact_tags`)."""
    from .app_registry import APP_CATALOG
    return APP_CATALOG


register(Registry(
    key='apps', label='Applications', nature=MEASURE,
    source="`APP_CATALOG` (déclaré en code) + grille de conformité MESURÉE depuis le code réel",
    refresh=_refresh_apps, count=_count_apps, entries=_entries_apps,
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


def _entries_functions() -> dict:
    """Les `FunctionSpec` par clé, adressables par une balise de doc (`fact_tags`)."""
    from .catalog.function_catalog import FUNCTION_CATALOG
    return FUNCTION_CATALOG


register(Registry(
    key='fonctions', label='Fonctions de traitement', nature=REDECLARATION,
    source="`apps.py:ready()` de chaque monde — `wama_data`, `wama_lab.cam_analyzer`…",
    refresh=_refresh_functions, count=_count_functions, entries=_entries_functions,
    url_name='model_manager:functions_catalog', manifest_kind='function',
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


def _entries_external_sources() -> dict:
    """Les `ExternalSource` par clé — la DÉCLARATION seule, jamais le rapport de sonde (une
    balise de doc qui citerait « joignable » serait fausse le lendemain d'une coupure)."""
    from .external_sources import SOURCES
    return {s.key: s for s in SOURCES}


register(Registry(
    key='sources_externes', label='Sources externes', nature=MEASURE,
    source="Registre déclaratif `common/external_sources.py` + sonde réseau (clé, joignabilité)",
    refresh=_refresh_external_sources, count=_count_external_sources,
    entries=_entries_external_sources,
    url_name='common:sources_catalog',
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
    url_name='model_manager:libraries_catalog', manifest_kind='library',
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


# ──────────────────────────────────────────────────────────────────────────────────────────────
# SOUVENIRS — le JUMEAU manquant du RAG (13ᵉ registre, 2026-09-09)
#
# `MemoryItem` et `RagChunk` héritent des MÊMES `Embedded` + `ScopedVisibility` et partagent UN
# seul `recall()`. Le fragment avait sa page et son entrée ici ; le souvenir n'avait NI l'une NI
# l'autre — son seul accès était `memory_recall` (tool_api), c'est-à-dire l'assistant en langage
# naturel. Personne ne pouvait LISTER ses souvenirs.
#
# Deux jumeaux aux surfaces asymétriques finissent par se lire comme deux natures différentes,
# ce qui est faux. Et l'absence de surface a un coût mesuré : la gouvernance (`WAMA_MEMORY §6`)
# EXIGE une validation humaine, mais 25 souvenirs importés de `memory.json` attendaient sans
# qu'aucun écran ne les montre. Une file de revue illisible n'est pas une garde.
#
# ⚠ Pas de `count` : comme `rag`, la page est PAR UTILISATEUR — un total global ne voudrait rien
# dire sur la carte des registres.
# ──────────────────────────────────────────────────────────────────────────────────────────────

register(Registry(
    key='memories', label='Mes souvenirs', nature=DERIVED,
    source="`MemoryItem` (`common/memory/`, Postgres + pgvector) — le jumeau du fragment RAG",
    url_name='common:memories', permission='auth',
    doc='WAMA_MEMORY.md',
    description="Ce que WAMA retient : faits, événements, procédures. Lu en base à chaque "
                "affichage — rien à actualiser. La liste ACTIVE est exactement ce que `recall()` "
                "peut rendre (même requête, jamais une seconde vérité) ; la FILE DE REVUE des "
                "souvenirs non approuvés est réservée au staff.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# PROMPTS — la déclaration qui manquait à la carte (14ᵉ registre, 2026-09-09)
#
# `PROMPT_TARGETS` dit QUEL champ de QUELLE app est un prompt, son KIND, son modèle cible et son
# domaine. C'est le pivot métadonnée-driven de toute la couche LLM — et il était le seul
# mécanisme de ce genre SANS surface : ni entrée, ni compteur, ni page. Il n'était que LU, par la
# page des skills, pour calculer les liens.
#
# Le déclarer ici fait de la page `skills_catalog` ce qu'elle est déjà en pratique : la vue
# « Prompts & Skills » — les DÉCLARATIONS d'un côté, les CONSIGNES de l'autre, et le lien calculé
# entre les deux (avec ses deux écarts : skill orphelin, target sans skill).
#
# Nature DERIVED : c'est un dict figé dans le code, relu à chaque import. Il n'y a rien à
# actualiser, et un bouton le prétendant serait le « bouton qui ment » que ce module combat.
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _count_prompt_targets() -> int:
    """Nombre de CHAMPS-prompt déclarés, toutes apps confondues — pas le nombre d'apps."""
    from .utils.app_metadata import PROMPT_TARGETS
    return sum(len(t) for t in PROMPT_TARGETS.values())


register(Registry(
    key='prompts', label='Prompts déclarés', nature=DERIVED,
    source="`PROMPT_TARGETS` (`common/utils/app_metadata.py`) — un champ-prompt déclaré par app, "
           "avec son KIND, son modèle cible et son domaine",
    count=_count_prompt_targets,
    url_name='common:skills_catalog', permission='auth',
    doc='WAMA_LLM.md',
    description="La DÉCLARATION que la pipeline de prompts consomme : quel champ est un prompt, "
                "de quel KIND, vers quel modèle. Figé dans le code, donc toujours à jour. Partage "
                "sa page avec les skills : c'est le même écran qui montre la déclaration, la "
                "consigne, et le lien calculé entre les deux.",
))


def _count_backends() -> int:
    from .services.backend_inventory import count
    return count()


# ⚠ LIBELLÉ CORRIGÉ le 2026-09-09 (relevé de Fabien) : il disait « Backends (moteurs) », et le
# parenthésage valait ÉQUIVALENCE. C'est faux depuis le 2026-09-07, où le sens du lien a été
# écrit partout (`PROJECT_STATUS §backends`, « rappelé trois fois par Fabien ») :
#
#     le MODÈLE porte son moteur (`composition.runtime.engine`)
#       → le BACKEND s'en DÉRIVE (`ENGINE`, départagé par `SUPPORTED_MODELS`)
#         → l'app appelle son MODÈLE et obtient son backend.
#
# Un backend est donc **la méthode qui APPELLE un moteur**, et un moteur est une **librairie**
# (`whisper`, `diffusers`, `pyannote`…). Les confondre efface le seul objet qui porte la
# décision — le modèle — et laisse croire qu'une app « a » des moteurs.
#
# ⚠⚠ Ce libellé était CITÉ COMME AUTORITÉ dans `AGENTS.md` (« un simple LIBELLÉ tranche parfois
# la question : le registre "Backends (moteurs)" dit que WAMA ne distingue pas le backend du
# moteur »). Un libellé périmé promu en source de vérité fait trancher une question dans le
# mauvais sens — corrigé là-bas dans le même commit.
register(Registry(
    key='backends', label='Backends', nature=DERIVED,
    source="Déclarations des paquets `wama/<app>/backends/` (ROUTES/RESULT/NATURE_FIELD + "
           "classes BaseModelBackend : ENGINE, ISOLATION, REQUIRED_PACKAGES, VRAM) recoupées "
           "au catalogue `AIModel` (source, backend_ref, composition.runtime.engine)",
    count=_count_backends,
    url_name='common:backends_catalog', permission='auth',
    doc='WAMA_APP_GENERATION_ROUTE.md',
    description="Le VIVIER des BACKENDS — la méthode qui appelle un moteur, jamais le moteur "
                "lui-même : le MODÈLE porte son moteur, le backend s'en DÉRIVE, et un moteur "
                "est une LIBRAIRIE. On y lit ce que chaque app sait exécuter, la nature "
                "d'entrée qui y mène, la SAVEUR de sortie (fichier/texte), les paquets requis, "
                "la VRAM et les modèles servis. Dit aussi l'ENVIRONNEMENT d'exécution : le "
                "défaut est un venv unique, et un backend qui tourne ailleurs le déclare "
                "(`ISOLATION`) — sans quoi le verdict de disponibilité confondrait « paquet "
                "absent » et « backend qui vit ailleurs ». Deux usages : la vision d'ensemble, "
                "et le voisinage dont le LLM de la marche B a besoin pour s'inspirer du backend "
                "le plus approchant. Dérivé à chaque affichage — un backend ajouté y apparaît "
                "sans qu'on déclare rien ici.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# DOCUMENTATION — la doc de WAMA lisible depuis WAMA (15ᵉ registre, 2026-09-11)
#
# Demande de Fabien : un accès en lecture seule à la doc depuis le menu du profil. La liste des
# docs de référence existait déjà deux fois à la main (table d'AGENTS.md, `check_docs.DOCS`) :
# ce registre ne porte PAS la sienne, il lit `docs_catalog.py`, que `check_docs` lit aussi.
#
# Nature DERIVED : les fiches sont relues sur le disque à chaque affichage (cache sur l'empreinte
# du fichier). Permission 'staff' : réservé aux administrateurs pour l'instant (décision 11/09) —
# la VUE applique `admin_required`, le même prédicat que le menu.
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _count_docs() -> int:
    from .docs_catalog import DOCS
    return len(DOCS)


def _entries_docs() -> dict:
    """Les docs déclarés par clé, adressables par une balise de doc (`fact_tags`)."""
    from .docs_catalog import BY_KEY
    return BY_KEY


register(Registry(
    key='docs', label='Documentation', nature=DERIVED,
    source="Déclaration `common/docs_catalog.py` (docs de référence d'AGENTS.md), lus sur le "
           "disque à chaque affichage",
    count=_count_docs, entries=_entries_docs,
    url_name='common:docs_catalog', permission='staff',
    doc='AGENTS.md',
    description="La doc de WAMA en lecture seule. Chaque doc déclare son AUDIENCE : la doc de "
                "CONSTRUCTION (doctrine, décisions, vision, chantiers) est faite de fichiers ; la "
                "doc DÉVELOPPEUR est GÉNÉRÉE à la lecture depuis les registres (`dev_docs.py`), "
                "jamais rédigée en parallèle. `check_docs` dérive sa liste de la même "
                "déclaration : un doc ajouté ici est contrôlé sans rien toucher d'autre.",
))
