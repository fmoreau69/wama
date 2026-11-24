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

from .registries import (AGGREGATE, DERIVED, MEASURE, MIXED, OWNED, REDECLARATION, SCAN, SYSTEM,
                         TO_CARRY, Registry, RefreshResult, register)


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
    key='models', label='Modèles IA', nature=SCAN,
    source="Fichiers de `AI-models/` + déclarations `model_config` des apps",
    refresh=_refresh_models, count=_count_models,
    url_name='model_manager:index', manifest_kind='model',
    periodic='model-manager-reconcile',
    # Système (déclarés par les apps, installés par un admin) ET modèles d'auteurs : la provenance
    # naît au geste d'installation et vit sur la ligne `AIModel` (ROADMAP §29, étape 3).
    provenance=MIXED, owner_model='model_manager.AIModel', owner_key='model_key',
    access_kind='model',
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
    # Chacun y gère SES abonnements et y lit les pages de ses apps (décision de Fabien, 2026-11-16).
    account_page=True,
    periodic='nightly-consistency',
    # Les jumelles ont un créateur (`created_by` de `sandbox.load_registry`, registre gitignoré), pas une portée
    # `ScopedVisibility` (ROADMAP §29, étape 5).
    provenance=TO_CARRY, access_kind='app',
    doc='docs/construction/architecture/WAMA_APP_CONVENTIONS.md',
    # ⚠ Cette description disait « 72 critères » : la grille en compte 89 (relevé du 2026-09-11).
    # Trouvé par la 1ʳᵉ doc dérivée (`docs/dev/registres.md`), qui la publie telle quelle — un
    # chiffre figé dans une chaîne ne se confronte à rien. Il sort ; le compte vit dans la grille.
    description="Le catalogue lui-même est déclaré en code — rien à y actualiser. Ce qui "
                "s'actualise est la GRILLE : ses critères re-mesurés par analyse du code.",
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
        # `rescan` : le balayage est mémorisé depuis le 2026-10-18 ; sans lui, un module
        # déclarant créé à chaud ne serait plus cherché.
        load_all(rescan=True)
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


def _function_app(key: str) -> str:
    """L'app qui porte la fonction du code `key` (`function_catalog.spec_app`), '' si inconnue."""
    from .catalog.function_catalog import get, load_all, spec_app
    load_all()
    spec = get(key)
    return spec_app(spec) if spec is not None else ''


register(Registry(
    key='functions', label='Fonctions de traitement', nature=REDECLARATION,
    source="`apps.py:ready()` de chaque monde — `wama_data`, `wama_lab.cam_analyzer`…",
    refresh=_refresh_functions, count=_count_functions, entries=_entries_functions,
    url_name='model_manager:functions_catalog', manifest_kind='function',
    # Une fonction d'UTILISATEUR porte propriétaire et portée sur sa ligne ; une fonction du CODE
    # n'a pas d'auteur à elle, elle suit l'app qui la porte — système dans une app réelle, à son
    # créateur dans une jumelle (`ROADMAP §29` étape 4).
    provenance=MIXED, owner_model='common.UserFunction', owner_key='key',
    element_app=_function_app, access_kind='function',
    doc='docs/construction/mondes/WAMA_DATA_FUNCTION_CARDS.md',
    description="Recharge les modules qui déclarent des `FunctionSpec`. Rend visibles les "
                "fonctions ajoutées pendant que le serveur tourne, sans redémarrage.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# NŒUDS INTÉGRÉS DU PIPELINE — cards d'entrée et de sortie, déclarées par leur monde (R2)
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _refresh_pipeline_nodes() -> RefreshResult:
    """Re-déclare les nœuds intégrés en RECHARGEANT les modules qui les ont inscrits (lus sur le
    registre lui-même : le module de l'exécuteur de chaque nœud), puis en rebalayant les modules
    déclarants — un monde qui inscrit un nœud depuis un module créé à chaud est ainsi trouvé.
    Même séquence que les fonctions : instantané, purge, rechargement, restauration sur échec."""
    import importlib
    import sys
    from .catalog.function_catalog import load_all
    from .manifests.builtin.pipeline import BUILTIN_NODES
    importlib.invalidate_caches()
    before = dict(BUILTIN_NODES)
    modules = sorted({node.run.__module__ for node in before.values()})
    BUILTIN_NODES.clear()
    try:
        for name in modules:
            if name in sys.modules:
                importlib.reload(sys.modules[name])
        load_all(rescan=True)
    except Exception:
        BUILTIN_NODES.clear()
        BUILTIN_NODES.update(before)
        raise
    after = dict(BUILTIN_NODES)
    return RefreshResult(ok=True, added=len(set(after) - set(before)),
                         removed=len(set(before) - set(after)),
                         updated=len(set(after) & set(before)), total=len(after),
                         messages=(f"{len(modules)} module(s) déclarant(s) rechargé(s)",))


def _entries_pipeline_nodes() -> dict:
    from .manifests.builtin.pipeline import builtin_nodes
    return builtin_nodes()


register(Registry(
    key='pipeline_nodes', label='Nœuds intégrés du pipeline', nature=REDECLARATION,
    source="le module déclarant de chaque monde — le Studio (texte, médiathèque, jeu de données, "
           "sortie), `wama_data` (base connectée, export)…",
    refresh=_refresh_pipeline_nodes, count=lambda: len(_entries_pipeline_nodes()),
    # Pas de page catalogue à soi (`url_name`) : la palette du Studio les montre.
    entries=_entries_pipeline_nodes, manifest_kind='pipeline',
    # Déclarés par le code des mondes : système (ROADMAP §29). Un nœud créé par un utilisateur
    # serait `to_carry`, au budget du test de provenance.
    provenance=SYSTEM,
    doc='docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
    description="Les cards d'ENTRÉE et de SORTIE d'un pipeline (ni l'une ni l'autre n'est un "
                "process), chacune déclarée UNE fois par son monde : rôle, libellé, ports, réglages "
                "`Param` et exécuteur. La palette du Studio, son inspecteur, la validation au "
                "lancement et l'exécuteur les lisent ici (ROUTE §10.6 3.3bis, R2).",
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


def _file_skill_names() -> list:
    from .utils import prompt_skills
    return prompt_skills.file_skill_names()


register(Registry(
    key='skills', label='Skills de prompt', nature=REDECLARATION,
    source="Fichiers `wama/common/prompt_skills/*.md` (système) et lignes `common.PromptSkill` "
           "(un auteur et une portée ; système une fois promues)",
    refresh=_refresh_skills, count=_count_skills,
    permission='auth', on_startup=False,
    # Sa page, enfin (27/08). Il était le seul registre de la carte à n'en désigner aucune :
    # le catalogue n'était lisible que par l'assistant et wama-dev-ai.
    url_name='common:skills_catalog',
    # Les fichiers du dépôt sont système ; un skill d'utilisateur a sa ligne `PromptSkill`
    # (`ROADMAP §29`, 2026-10-20). Une ligne peut porter le nom d'un fichier : `in_code` le dit.
    provenance=MIXED, owner_model='common.PromptSkill', owner_key='name',
    in_code=lambda name: name in _file_skill_names(), access_kind='skill',
    doc='docs/construction/ia/WAMA_LLM.md',
    description="Vide le cache de lecture des skills : un `.md` modifié à chaud est repris sans "
                "redémarrage. Sans effet de bord partagé, donc ouvert à tout compte connecté.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# PRONONCIATIONS et MOTS-CLÉS DE PROMPT — deux listes de TERMES à auteur (2026-10-27)
# ──────────────────────────────────────────────────────────────────────────────────────────────
# Fabien, le jour du lexique : « Est-ce que ce genre de liste a sa place parmi les registres ? […]
# dans l'idée de ce qu'on a fait pour les mots-clés ? » — puis « lance-le, et aligne aussi les
# mots-clés ». Les deux suivent la route des skills (`ROADMAP §29`) : système, et lignes d'auteur.

def _count_pronunciations() -> int:
    from .services.user_pronunciations import system_entries
    from .models import Pronunciation
    return len(system_entries()) + Pronunciation.objects.count()


def _entries_pronunciations() -> dict:
    """Les entrées SYSTÈME du fichier, par `langue:terme` — celles qu'une balise de doc peut citer."""
    from .services.user_pronunciations import system_entries
    return {f"{e['language']}:{e['term']}": e for e in system_entries()}


register(Registry(
    key='pronunciations', label='Prononciations', nature=DERIVED,
    source="Fichier `wama/common/tts/pronunciations.json` (système) et lignes "
           "`common.Pronunciation` (un auteur et une portée ; système une fois promues)",
    count=_count_pronunciations, entries=_entries_pronunciations,
    permission='auth', url_name='common:pronunciations_catalog',
    # Le fichier est relu à chaque CHANGEMENT (`tts_text._file_lexicons`), par les processus web
    # comme par le service vocal : rien à actualiser, d'où DÉRIVÉ.
    provenance=MIXED, owner_model='common.Pronunciation', owner_key='term',
    in_code=lambda term: _pronunciation_in_file(term),
    doc='docs/construction/ia/WAMA_LLM.md',
    description="Comment la voix dit un terme : une orthographe à dire (tout moteur), ou des "
                "phonèmes (Kokoro). Le texte affiché n'est jamais touché. Le fichier du dépôt est "
                "le lexique système ; l'entrée d'un compte passe devant pour lui, se partage, se "
                "copie, et un administrateur la rend système.",
))


def _pronunciation_in_file(term: str) -> bool:
    from .services.user_pronunciations import in_file
    return in_file(term)


def _count_prompt_keywords() -> int:
    from wama.media_library.models import PromptKeyword
    return PromptKeyword.objects.count()


register(Registry(
    key='prompt_keywords', label='Mots-clés de prompt', nature=DERIVED,
    source="Lignes `media_library.PromptKeyword` : le tronc commun (système, `seed_prompt_keywords`) "
           "et les mots-clés d'auteur (une portée ; système une fois promus)",
    count=_count_prompt_keywords, permission='auth',
    # Sa page est l'onglet « Mots-clés » de la médiathèque, là où ils se gèrent depuis juin.
    url_name='media_library:index',
    provenance=MIXED, owner_model='media_library.PromptKeyword',
    doc='docs/construction/ia/WAMA_LLM.md',
    description="Les mots-clés cliquables sous un champ-prompt (palette `WamaPromptChips`), "
                "gardés VERBATIM à l'enrichissement. Le tronc commun est système ; un mot-clé "
                "d'auteur naît privé, se partage, se copie, et un administrateur le rend système.",
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
    key='external_sources', label='Sources externes', nature=MEASURE,
    source="Registre déclaratif `common/external_sources.py` + sonde réseau (clé, joignabilité)",
    refresh=_refresh_external_sources, count=_count_external_sources,
    entries=_entries_external_sources,
    url_name='common:sources_catalog',
    # La clé d'un utilisateur se pose à son profil : ce n'est pas un élément du registre.
    provenance=SYSTEM,
    doc='docs/construction/architecture/WAMA_MECANISMES.md',
    description="Sonde chaque source déclarée : clé d'API de l'instance posée ? adresse "
                "joignable (proxy UGE compris) ? Une clé de CHAQUE utilisateur (fournisseurs LLM, "
                "banques de médias) se pose au profil, pas ici. La déclaration, elle, ne "
                "s'actualise pas — elle vit en code. "
                "Réservé au staff : la sonde émet des requêtes sortantes et écrit un rapport.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Les DÉRIVÉS — rien à actualiser, et c'est une PROPRIÉTÉ, pas un manque
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _count_libraries() -> int:
    from .models import Library
    return Library.objects.count()


register(Registry(
    key='libraries', label='Librairies externes', nature=DERIVED,
    source="Registre `Library` (projeté par les manifestes) + mesure live `importlib.metadata`",
    count=_count_libraries,
    url_name='model_manager:libraries_catalog', manifest_kind='library',
    # `Library` n'a aucun propriétaire ; « privée » voudra dire « non proposée », jamais
    # « isolée » — le venv est partagé (§29).
    provenance=TO_CARRY, access_kind='library',
    doc='docs/construction/exploitation/LICENSING.md',
    description="La page mesure l'installation réelle à CHAQUE affichage et compare au déclaré : "
                "l'écart affiché ne peut pas être périmé. Le registre lui-même s'alimente par la "
                "projection des manifestes, pas par un scan — le RÔLE d'une librairie (socle, "
                "moteur, app, brique) compris : déclaré au manifeste, jamais calculé.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# FORMATS MÉDIAS — la contrepartie qui manquait aux trois registres de formats du monde Data
# (demande de Fabien, 2026-09-17 : « ne faut-il pas une page pour consulter tous les formats
# médias pris en charge ? »).
#
# ⚠ CE N'EST PAS UN REVIREMENT SUR LA NATURE DU VOCABULAIRE. `WAMA_DATA_WORLD §9quinquies.2` a
# tranché que `MEDIA_CATEGORIES` reste une TAXONOMIE et non un registre extensible par dépôt de
# greffon — et c'est toujours vrai : côté Médias, ajouter un format, c'est ajouter la LIBRAIRIE
# qui sait le lire, puis son extension à la nature ; côté Data, c'est déposer un LECTEUR, donc du
# code qui sait faire. Ce qui change ici est la QUATRIÈME question du même critère (« l'utilisateur
# doit-il en voir l'état ? »), qui n'avait jamais été posée aux vocabulaires média. C'est la porte
# de sortie que `MEDIA_STORAGE_TIERING §9` avait elle-même écrite : « une entrée DÉRIVÉE suffira ».
#
# ⚠ PAS de distinction entrée/sortie (arbitrage Fabien) : un `.mp4` est un `.mp4` des deux côtés.
# Ce que le CONVERTER sait écrire est une facette de la nature, pas un second registre.
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _count_media_formats() -> int:
    from .app_registry import media_extensions
    return sum(len(exts) for exts in media_extensions().values())


def _entries_media_formats() -> dict:
    """Une fiche par NATURE — adressable par une balise de doc (`fact_tags`)."""
    from .app_registry import CONVERTER_OUTPUT_FORMATS, media_extensions
    return {nature: {'extensions': exts,
                     'nombre': len(exts),
                     'sorties_converter': sorted(CONVERTER_OUTPUT_FORMATS.get(nature, []))}
            for nature, exts in media_extensions().items()}


register(Registry(
    key='media_formats', label='Formats médias', nature=DERIVED,
    source="`app_registry` — natures (`MEDIA_CATEGORIES`) et extensions, y compris celles qu'un "
           "MONDE pousse au démarrage (`register_category_extensions`)",
    count=_count_media_formats, entries=_entries_media_formats,
    url_name='common:media_formats_catalog', provenance=SYSTEM,
    doc='docs/construction/mondes/WAMA_DATA_WORLD.md §9quinquies',
    description="Ce que WAMA sait RECONNAÎTRE, en entrée comme en sortie — la distinction n'aurait "
                "pas de sens : un fichier a la même nature des deux côtés. La page dérive du code à "
                "chaque affichage, donc elle ne peut pas être périmée ; elle rend CONSULTABLE un "
                "vocabulaire qui reste une taxonomie, sans changer son domicile.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# BRIQUES UI (2026-10-10, ouverture du chantier SURFACES) — décision de Fabien : un CATALOGUE des
# briques (« consulter ce qui existe »), pas une ressource de la médiathèque. Universelles :
# Médias, Data, Lab, Studio. Le Studio lira la même liste pour sa palette de diagramme.

def _ui_bricks():
    from wama.common.surfaces import BRICKS, load_all
    load_all()
    return BRICKS


register(Registry(
    key='ui_bricks', label='Briques UI', nature=DERIVED,
    source="`common/surfaces.py` — briques déclarées (ce qu'elles consomment, émettent, leur "
           "script) ; les surfaces des apps les composent, ou une page d'app les monte (card "
           "d'entrée, inspecteur, visionneuse)",
    count=lambda: len(_ui_bricks()),
    entries=lambda: {key: brick.to_dict() for key, brick in _ui_bricks().items()},
    url_name='common:ui_bricks_catalog',
    # Chacun y règle SES touches, brique par brique (`WAMA_VOLETS §3-ter`).
    account_page=True,
    # Les briques du code sont système ; une brique d'utilisateur (écrite dans sa jumelle) n'a
    # encore aucun lieu (§29, étape 5).
    provenance=TO_CARRY,
    doc='docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §F3b',
    description="Les briques dont une page se COMPOSE — une surface d'édition (déplaçables, "
                "redimensionnables) ou la page d'une app —, communes à tous les mondes. Déclarées "
                "par le code : la liste ne peut pas être périmée, il n'y a rien à actualiser.",
))


def _themes():
    from wama.common.themes import THEMES
    return THEMES


register(Registry(
    key='themes', label='Thèmes', nature=DERIVED,
    source="`common/themes.py` — les thèmes déclarés ; leurs valeurs dans `common/css/wama-theme.css`",
    count=lambda: len(_themes()),
    entries=lambda: {t.key: t.to_dict() for t in _themes()},
    # Les thèmes DÉCLARÉS sont système ; un thème tiré d'une CHARTE a un auteur et une portée sur
    # sa ligne `UserTheme`, système une fois promu par un admin (`ROADMAP §28` étape 7, §29).
    provenance=MIXED, owner_model='common.UserTheme',
    doc='docs/construction/suivi/ROADMAP.md §28',
    description="Les thèmes que WAMA sait poser sur une page. Un thème est un jeu de TOKENS (un "
                "composant lit `var(--wama-…)`, il n'écrit plus de couleur) et le mode de Bootstrap "
                "qu'il prend pour base. Le scénario de contraste mesure chaque thème de cette liste. "
                "Un thème de CHARTE (lue au Profil) n'en garde que les graines, sur sa ligne.",
))


register(Registry(
    key='licenses', label='Licences', nature=DERIVED,
    source="Agrégation de `AIModel`, `Library`, médias, des conditions d'usage des services "
           "distants (`external_sources`), des distributions installées hors registre et des "
           "`requires` des manifestes d'app",
    url_name='common:licenses_catalog', provenance=AGGREGATE,
    doc='docs/construction/exploitation/LICENSING.md',
    description="Vue transversale sans registre propre — « une page qui DÉRIVE ne peut pas "
                "diverger de ses sources ». Un bouton d'actualisation y serait un mensonge : "
                "actualiser les licences, c'est actualiser modèles et librairies.",
))


register(Registry(
    key='rag', label='Mon RAG', nature=DERIVED,
    source="Ce que l'utilisateur a confié au RAG (`common/memory/`, Postgres + pgvector)",
    url_name='common:rag', permission='auth',
    provenance=OWNED, owner_model='common.RagChunk', access_kind='rag_scope',
    doc='docs/construction/ia/WAMA_MEMORY.md',
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
    provenance=OWNED, owner_model='common.MemoryItem',
    doc='docs/construction/ia/WAMA_MEMORY.md',
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
    url_name='common:skills_catalog', permission='auth', provenance=SYSTEM,
    doc='docs/construction/ia/WAMA_LLM.md',
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
    # Un backend proposé par un rôle n'entre qu'après validation humaine, écrit dans le code.
    provenance=SYSTEM,
    doc='docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md',
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
    # 'auth' depuis le 2026-09-14 : la page s'ouvre à tout compte connecté (doc utilisateur), et
    # un registre DÉRIVÉ n'a aucune actualisation à réserver. Qui lit QUOI : `visible_to`.
    url_name='common:docs_catalog', permission='auth', provenance=SYSTEM,
    doc='AGENTS.md',
    description="La doc de WAMA en lecture seule. Chaque doc déclare son AUDIENCE : la doc de "
                "CONSTRUCTION (doctrine, décisions, vision, chantiers) est écrite à la main ; la "
                "doc DÉVELOPPEUR en DÉRIVE, avec les faits des registres, écrite en `.md` par "
                "`doc_facts` — jamais rédigée en parallèle. `check_docs` dérive sa liste de la même "
                "déclaration : un doc ajouté ici est contrôlé sans rien toucher d'autre.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# OUTILS — l'API de l'assistant, NOMMÉE (2026-11-18, `WAMA_HARNESS §9` « Plan du 2026-11-18 », A)
#
# POURQUOI. Interrogé sur lui-même (fil Discord, tour 894), l'assistant a dit « ~90 outils » : il
# l'avait lu dans la doc (`search_docs`), qui recopiait une mesure du 2026-10-28. Le registre en
# comptait 168. Un chiffre recopié se périme ; un registre DÉRIVÉ ne le peut pas. Celui-ci lit
# `TOOL_REGISTRY` — dont dérivent l'API REST v1, le serveur MCP et l'exécuteur du Studio — et
# n'écrit rien : l'effet est celui que chaque outil DÉCLARE (`tool_effect`), la famille celle de la
# trace (`tool_trace.family` : l'app qui garde l'outil, ou `transverse`), l'origine celle de l'app
# au catalogue (`sandbox.app_origin`). Une famille qui n'est pas une app du catalogue (registres,
# Studio, médiathèque, model manager) est une page du SUBSTRAT.
# ──────────────────────────────────────────────────────────────────────────────────────────────

#: L'origine d'un outil dont la famille n'est pas une app du catalogue : transverse (aucune app ne
#: le garde), ou une SURFACE hors catalogue (Studio, médiathèque, registres… — `app_registry`,
#: « une surface transversale n'entre pas dans APP_CATALOG »).
TOOL_ORIGIN_TRANSVERSE, TOOL_ORIGIN_SURFACE = 'transverse', 'surface'

#: Le libellé de chaque origine d'outil — lu par le fait `outils` (`doc_facts`).
TOOL_ORIGIN_LABELS = {
    TOOL_ORIGIN_TRANSVERSE: 'transverses',
    'wama': 'apps de WAMA',
    TOOL_ORIGIN_SURFACE: 'surfaces hors catalogue',
    'twin': 'jumelles du bac à sable',
    'born': "apps nées d'un manifeste (en construction)",
}


def tool_origin(family: str) -> str:
    """L'origine d'un outil de la famille `family` : `transverse`, celle de son app au catalogue
    (`sandbox.app_origin` : wama, twin, born), `surface` pour une app hors catalogue que
    l'identité DÉCLARE (`app_identity` : `register_surface`, `register_pageless_tool`), '' sinon —
    une famille que rien ne déclare est un défaut, que `tests_tool_api_coverage` refuse."""
    from .app_registry import APP_CATALOG, app_identity
    from .sandbox import app_origin
    if family == TOOL_ORIGIN_TRANSVERSE:
        return TOOL_ORIGIN_TRANSVERSE
    if family in APP_CATALOG:
        return app_origin(APP_CATALOG[family])
    return TOOL_ORIGIN_SURFACE if app_identity(family)['declared'] else ''


def _entries_tools() -> dict:
    """Les outils de `TOOL_REGISTRY`, par nom : effet, famille, origine."""
    from wama.common.services.tool_trace import family
    from wama.tool_api import TOOL_REGISTRY, effect_of
    out = {}
    for name in sorted(TOOL_REGISTRY):
        fam = family(name)
        out[name] = {'effect': (effect_of(name) or {}).get('effect', ''), 'family': fam,
                     'origin': tool_origin(fam)}
    return out


def _count_tools() -> int:
    from wama.tool_api import TOOL_REGISTRY
    return len(TOOL_REGISTRY)


register(Registry(
    key='tools', label="Outils de l'assistant", nature=DERIVED,
    source="`tool_api.TOOL_REGISTRY` (l'effet que chaque outil déclare) et `APP_CATALOG` (l'origine "
           "de l'app qui le garde)",
    count=_count_tools, entries=_entries_tools,
    permission='auth', provenance=SYSTEM,
    doc='docs/construction/ia/WAMA_LLM.md',
    description="L'API de l'assistant — la même pour l'API REST, le serveur MCP et le Studio. Chaque "
                "outil dit son effet (lecture, écriture, destruction) et son origine : transverse, "
                "app de WAMA, jumelle du bac à sable, app née d'un manifeste (en construction), ou "
                "surface hors catalogue (Studio, médiathèque, registres…). Les outils du bac à "
                "sable n'existent que là où il est installé. "
                "Hors de cette liste : les outils de développement (surface à part) et la "
                "délégation à des sous-agents (un verbe de la boucle).",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# PISTES — les marques temporelles qu'une card porte, NOMMÉES (2026-11-24, `ROUTE §10.7`, marche 1)
#
# Une app DÉCLARE ses pistes (`catalog/marks.register_tracks`, dans son `ready()`), un seul lecteur
# les rend. Ce registre lit ces déclarations et n'écrit rien : c'est ce qui permet à une surface —
# la zone temporelle d'une card, l'assistant, un nœud du Studio — de demander « quelles pistes
# porte ce type de card, sur quel axe, sous quelle piste parente ? » sans connaître l'app.
#
# ⚠ Seules les pistes DÉCLARÉES y figurent. Celles d'un fichier de données (`.wdat`, `.trip`) sont
# dites par le fichier lui-même (`wama_data.frames.referential_tracks`) : elles appartiennent à un
# essai, pas à WAMA, et n'ont pas à entrer dans un registre du code.
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _entries_tracks() -> dict:
    """Les pistes déclarées, par `app.modèle.piste` : ce que dit la déclaration (axe, famille,
    piste parente, contrainte, piste principale, couleur, gestes) et la façon dont ses lignes se
    trouvent (`rows` : `stored`, rangées par l'app ; `nested`, écrites dans la marque parente ;
    `derived`, déduites d'une autre piste)."""
    from .catalog.marks import registered
    out = {}
    for label, tracks in sorted(registered().items()):
        for track in tracks:
            out[f'{label}.{track.key}'] = {
                'app': label.partition('.')[0], 'model': label, 'label': track.label,
                'kind': track.kind, 'axis': track.axis, 'parent': track.parent,
                'constraint': track.constraint,
                'rows': 'derived' if track.runs_of else 'nested' if track.within else 'stored',
                # Ce que l'écran et les gestes ont à savoir (`ROUTE §10.7.14`) : la piste de la
                # ligne segmentée, sa couleur, ce qu'on peut y faire et où vont les gestes.
                'main': track.main, 'color_by': track.color_by, 'scale': track.scale,
                'steps': list(track.steps), 'gestures': list(track.gestures),
                'edits': track.edits,
            }
    return out


register(Registry(
    key='tracks', label='Pistes de marques', nature=DERIVED,
    source="Déclarations `register_tracks` des apps (`common/catalog/marks.py`), portées par la "
           "facette `inspector.tracks` de leur manifeste",
    count=lambda: len(_entries_tracks()), entries=_entries_tracks,
    permission='auth', provenance=SYSTEM,
    doc='docs/construction/architecture/WAMA_APP_GENERATION_ROUTE.md §10.7',
    description="Les événements et les segments qu'une card porte sur son axe (les phrases et les "
                "mots d'une transcription, les fenêtres et les conflits d'une analyse), tous lus "
                "sous les mêmes noms par un seul lecteur. Une piste dit son axe, sa famille "
                "(segments ou événements), sa piste parente et ce que ses marques lui doivent ; "
                "et, pour l'écran, si elle est la piste principale de la card, ce qui colore ses "
                "marques et les gestes qu'elle permet. "
                "Les pistes d'un fichier de données sont dites par le fichier, pas ici.",
))
