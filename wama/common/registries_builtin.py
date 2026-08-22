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

from .registries import (DERIVE, MESURE, REDECLARATION, SCAN, Registre, Resultat, enregistrer)


# ──────────────────────────────────────────────────────────────────────────────────────────────
# MODÈLES — scan du disque vers le catalogue `AIModel`
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _rafraichir_modeles() -> Resultat:
    from wama.model_manager.services.model_sync import get_sync_service
    r = get_sync_service().full_sync(remove_missing=False, delete_missing=True)
    return Resultat(ok=bool(r.success), ajoutes=r.added, modifies=r.updated, retires=r.removed,
                    messages=tuple((r.errors or [])[:5]))


def _compter_modeles() -> int:
    from wama.model_manager.models import AIModel
    return AIModel.objects.count()


enregistrer(Registre(
    cle='modeles', nom='Modèles IA', nature=SCAN,
    source="Fichiers de `AI-models/` + déclarations `model_config` des apps",
    rafraichir=_rafraichir_modeles, compter=_compter_modeles,
    url_name='model_manager:index', manifest_kind='model',
    periodique='model-manager-reconcile',
    description="Réconcilie le catalogue avec ce qui est réellement présent sur le disque. "
                "Une entrée dont les fichiers ont disparu est supprimée — d'où la réserve staff.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# APPLICATIONS — la grille de conformité est la partie MESURÉE de la page
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _rafraichir_apps() -> Resultat:
    from .app_registry import measure_and_write_conformity
    rapport = measure_and_write_conformity()
    apps = rapport.get('apps', {})
    return Resultat(ok=True, modifies=len(apps), total=len(apps),
                    messages=(f"mesurée le {rapport.get('generated_at', '?')}",))


def _compter_apps() -> int:
    from .app_registry import APP_CATALOG
    return len(APP_CATALOG)


enregistrer(Registre(
    cle='apps', nom='Applications', nature=MESURE,
    source="`APP_CATALOG` (déclaré en code) + grille de conformité MESURÉE depuis le code réel",
    rafraichir=_rafraichir_apps, compter=_compter_apps,
    url_name='common:apps_catalog', manifest_kind='app',
    periodique='nightly-consistency',
    doc='WAMA_APP_CONVENTIONS.md',
    description="Le catalogue lui-même est déclaré en code — rien à y actualiser. Ce qui "
                "s'actualise est la GRILLE : 72 critères re-mesurés par analyse du code.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# FONCTIONS — registre en mémoire, peuplé par import au `ready()` de chaque monde
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _oublier(nom: str) -> None:
    """Désimporte VRAIMENT un module — `sys.modules` **et** l'attribut du paquet parent.

    ⚠ Retirer de `sys.modules` seul ne suffit pas, et l'oublier produit un bug qui ne se voit qu'à
    la deuxième actualisation : `from . import X` interroge d'abord l'ATTRIBUT du paquet parent.
    Tant qu'il pointe sur l'ancien module, l'import est court-circuité — le fichier réécrit n'est
    jamais relu et ses fonctions n'apparaissent pas. Mesuré : le test « ajoutée à chaud » passait
    seul et échouait après le test « supprimée à chaud ».
    """
    import sys
    sys.modules.pop(nom, None)
    parent, _, feuille = nom.rpartition('.')
    mod_parent = sys.modules.get(parent) if parent else None
    if mod_parent is not None and hasattr(mod_parent, feuille):
        try:
            delattr(mod_parent, feuille)
        except AttributeError:
            pass


def _rafraichir_fonctions() -> Resultat:
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
        for nom in modules:
            # Recharger le paquet déclarant ne recharge pas ses sous-modules : ce sont eux qui
            # portent les `register()`. On les recharge donc en profondeur, parents d'abord.
            for sous in sorted(m for m in list(sys.modules)
                               if m == nom or m.startswith(nom + '.')):
                mod = sys.modules.get(sous)
                if mod is None:
                    continue
                source = getattr(mod, '__file__', None)
                if source and not os.path.exists(source):
                    # ⚠ Fichier SUPPRIMÉ pendant que le serveur tourne. Le recharger lève, et une
                    # levée ici restaurerait l'instantané — donc les fonctions du fichier effacé
                    # survivraient à leur propre suppression.
                    _oublier(sous)
                    disparus += 1
                    continue
                importlib.reload(mod)
        load_all()
    except Exception:
        FUNCTION_CATALOG.clear()
        FUNCTION_CATALOG.update(avant)
        raise

    apres = dict(FUNCTION_CATALOG)
    ajoutes = len(set(apres) - set(avant))
    retires = len(set(avant) - set(apres))
    messages = [f"{len(modules)} module(s) déclarant(s) rechargé(s)"]
    if disparus:
        messages.append(f"{disparus} module(s) dont le fichier a disparu, retiré(s)")
    return Resultat(ok=True, ajoutes=ajoutes, retires=retires,
                    modifies=len(set(apres) & set(avant)), total=len(apres),
                    messages=tuple(messages))


def _compter_fonctions() -> int:
    from .catalog.function_catalog import FUNCTION_CATALOG
    return len(FUNCTION_CATALOG)


enregistrer(Registre(
    cle='fonctions', nom='Fonctions de traitement', nature=REDECLARATION,
    source="`apps.py:ready()` de chaque monde — `wama_data`, `wama_lab.cam_analyzer`…",
    rafraichir=_rafraichir_fonctions, compter=_compter_fonctions,
    url_name='model_manager:function_catalog', manifest_kind='function',
    doc='WAMA_DATA_FUNCTION_CARDS.md',
    description="Recharge les modules qui déclarent des `FunctionSpec`. Rend visibles les "
                "fonctions ajoutées pendant que le serveur tourne, sans redémarrage.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# SKILLS DE PROMPT — fichiers `.md` sur disque, lus avec cache
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _rafraichir_skills() -> Resultat:
    from .utils import prompt_skills
    avant = len(prompt_skills._cache)
    prompt_skills._cache.clear()
    catalogue = prompt_skills.skills_catalog()
    return Resultat(ok=True, retires=avant, total=len(catalogue),
                    messages=("cache vidé — les fichiers seront relus à la demande",))


def _compter_skills() -> int:
    from .utils import prompt_skills
    return len(prompt_skills.skills_catalog())


enregistrer(Registre(
    cle='skills', nom='Skills de prompt', nature=REDECLARATION,
    source="Fichiers `wama/common/prompt_skills/*.md`",
    rafraichir=_rafraichir_skills, compter=_compter_skills,
    permission='auth', au_demarrage=False,
    doc='WAMA_IA_TRANSVERSE.md',
    description="Vide le cache de lecture des skills : un `.md` modifié à chaud est repris sans "
                "redémarrage. Sans effet de bord partagé, donc ouvert à tout compte connecté.",
))


# ──────────────────────────────────────────────────────────────────────────────────────────────
# Les DÉRIVÉS — rien à actualiser, et c'est une PROPRIÉTÉ, pas un manque
# ──────────────────────────────────────────────────────────────────────────────────────────────

def _compter_librairies() -> int:
    from .models import Library
    return Library.objects.count()


enregistrer(Registre(
    cle='librairies', nom='Librairies externes', nature=DERIVE,
    source="Registre `Library` (projeté par les manifestes) + mesure live `importlib.metadata`",
    compter=_compter_librairies,
    url_name='model_manager:library_catalog', manifest_kind='library',
    doc='LICENSING.md',
    description="La page mesure l'installation réelle à CHAQUE affichage et compare au déclaré : "
                "l'écart affiché ne peut pas être périmé. Le registre lui-même s'alimente par la "
                "projection des manifestes, pas par un scan.",
))


enregistrer(Registre(
    cle='licences', nom='Licences', nature=DERIVE,
    source="Agrégation de `AIModel`, `Library`, médias et des `requires` des manifestes d'app",
    url_name='common:licenses_catalog',
    doc='LICENSING.md',
    description="Vue transversale sans registre propre — « une page qui DÉRIVE ne peut pas "
                "diverger de ses sources ». Un bouton d'actualisation y serait un mensonge : "
                "actualiser les licences, c'est actualiser modèles et librairies.",
))


enregistrer(Registre(
    cle='rag', nom='Mon RAG', nature=DERIVE,
    source="Ce que l'utilisateur a confié au RAG (`common/memory/`, Postgres + pgvector)",
    url_name='common:rag', permission='auth',
    doc='WAMA_MEMORY.md',
    description="Liste ce que CE compte a ajouté, lu en base à chaque affichage. L'entrée au RAG "
                "est un geste explicite : rien ne s'y ajoute par balayage, donc rien à réconcilier.",
))
