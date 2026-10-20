"""
Registre des REGISTRES — l'actualisation devient un mécanisme, pas une page.

POURQUOI CE FICHIER EXISTE (demande de Fabien, 2026-08-22)

    WAMA construit une page catalogue par capacité (modèles, apps, fonctions, librairies, licences,
    RAG, skills). Chacune a besoin d'être actualisée, et **deux seulement l'étaient** — les modèles
    (`api/sync/`) et la grille de conformité (`api/conformity/refresh/`), chacune avec son endpoint,
    son bouton et son script inline recopiés. Écrire le huitième à la main garantissait la dérive :
    des libellés différents, des permissions différentes, des pages sans bouton du tout.

    D'où le geste habituel de WAMA : **un registre keyé et déclaratif**, comme `MANIFEST_KINDS`,
    `FUNCTION_CATALOG`, `mecanismes.py` ou `wama_data/modules.py`. Une page catalogue déclare la
    CLÉ de son registre et hérite du bouton, de l'endpoint, de la permission, du chronométrage et
    du compte-rendu. Un nouveau catalogue = une entrée ici, zéro ligne d'UI.

⚠ POURQUOI LA CLÉ N'EST PAS LE `manifest_kind` (question posée, tranchée par la mesure)

    L'intuition était de keyer sur le kind de manifeste, puisque les kinds sont auto-descriptifs.
    Le relevé du 2026-08-22 dit non : sur 7 surfaces catalogues, **4 seulement** correspondent à un
    kind (`app`, `function`, `library`, `model`) ; **3 kinds n'ont aucune page** (`dataset`,
    `pipeline`, `project`) ; et **3 pages ne sont pas des kinds** (licences, RAG, skills). Keyer sur
    le kind aurait couvert 4/7 en traînant 3 entrées mortes. On garde donc `manifest_kind` comme
    LIEN facultatif — l'information est vraie et utile, elle n'est simplement pas la clé.

⚠ QUATRE NATURES D'ACTUALISATION, et les confondre produit des boutons qui mentent

    Un bouton « Actualiser » sur une page qui recalcule déjà à chaque requête est un mensonge :
    il ne fait rien et laisse croire que le reste est périmé. La nature est donc DÉCLARÉE, et l'UI
    s'en sert pour montrer un bouton ou une mention « toujours à jour ».

⚠ IDENTIFIANTS RENOMMÉS EN ANGLAIS le 2026-08-29 (dette de nommage, plan validé Fabien —
    `PROJECT_STATUS §PENDING 2026-08-29`) : l'API s'importait en français (`rafraichir`, `lancer`,
    `etat`…) contre le critère de AGENTS.md §nommage. Prose et docstrings restent françaises.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Un scanner externe alimente un registre PERSISTANT (disque, `importlib`, LDAP → BDD).
#: Coûteux, potentiellement destructif (une entrée disparue du disque disparaît du registre).
SCAN = 'scan'
#: Un calcul dérive un rapport ÉCRIT (grille de conformité, redondances, faits de doc).
MEASURE = 'mesure'
#: Un registre en MÉMOIRE peuplé par import au démarrage. Actualiser = re-déclarer.
REDECLARATION = 'redeclaration'
#: Rien n'est stocké : la page recalcule à chaque requête. **Il n'y a rien à actualiser**, et c'est
#: une qualité — « une page qui DÉRIVE ne peut pas diverger de ses sources » (`licenses_catalog_view`).
DERIVED = 'derive'

#: ⚠ Les VALEURS ('mesure', 'derive'…) sont un VOCABULAIRE DE DONNÉE (déclarations, doc générée,
#: tests) — elles ne se renomment pas avec les identifiants (frontière du 2026-08-29 : ce qui est
#: stocké/déclaré reste, ce qui s'importe se renomme).
NATURES = {
    SCAN: "Scan d'une source externe vers un registre persistant",
    MEASURE: "Calcul qui produit un rapport écrit",
    REDECLARATION: "Registre en mémoire, peuplé par import",
    DERIVED: "Dérivé à chaque affichage — toujours à jour",
}

# ──────────────────────────────────────────────────────────────────────────────────────────────
# PROVENANCE — à QUI sont les éléments d'un registre (ROADMAP §29, ouvert le 2026-10-18)
#
# Deux axes de droits existent, et ce n'est pas le même : « qui a le DROIT » (profil, rôles :
# `accounts.permissions.accessible`) et « à QUI c'est » (propriétaire et portée : `ScopedVisibility`).
# Les instances portent le second ; les éléments d'un catalogue ne le portaient nulle part. Chaque
# registre DÉCLARE donc où vit la provenance de ses éléments — et ce qui n'a pas encore de porteur
# le DIT (`TO_CARRY`), au lieu de passer pour du système par omission. Un registre sans
# déclaration fait échouer `tests_registry_provenance` : une capacité nouvelle ne peut pas entrer sans dire
# à qui sont ses éléments. Le système = sans propriétaire, tenu par WAMA (`manifests/envelope.py`,
# `owner: None = système/builtin`) ; un élément partagé en « public » par son auteur reste à lui.
# ──────────────────────────────────────────────────────────────────────────────────────────────

#: Tout élément est déclaré par WAMA (code, admins) : aucun n'a d'auteur.
SYSTEM = 'system'
#: Chaque élément porte son propriétaire et sa portée sur sa ligne (`owner_model`, `ScopedVisibility`).
OWNED = 'owned'
#: Des éléments système (déclarés en code) ET des éléments d'utilisateurs portant leur provenance
#: sur la ligne de `owner_model`.
MIXED = 'mixed'
#: Aucun élément propre : le registre lit d'autres registres, leur provenance fait foi.
AGGREGATE = 'aggregate'
#: Des éléments d'utilisateurs sont VOULUS (§29) mais leur porteur n'existe pas encore. Un budget
#: qui ne peut que descendre (`tests_registry_provenance.TO_CARRY_BUDGET`).
TO_CARRY = 'to_carry'

PROVENANCES = {
    SYSTEM: "Système — déclaré par WAMA, sans auteur",
    OWNED: "À son auteur — propriétaire et portée sur chaque élément",
    MIXED: "Système et auteurs — des éléments système et des éléments d'utilisateurs",
    AGGREGATE: "Agrégat — lit d'autres registres",
    TO_CARRY: "À porter — éléments d'utilisateurs prévus, porteur à construire (ROADMAP §29)",
}
#: Les provenances dont les éléments d'utilisateurs ont une ligne qui les porte.
CARRIED = (OWNED, MIXED)

# ──────────────────────────────────────────────────────────────────────────────────────────────
# OÙ tourne l'actualisation — et ce n'est PAS un réglage libre : la nature l'impose.
# ──────────────────────────────────────────────────────────────────────────────────────────────

#: Tâche Celery, non bloquante. Le seul choix acceptable dès que l'état est PARTAGÉ (base, fichier
#: de rapport) : le résultat profite à tout le monde, et le worker web reste libre.
#: ⚠ Mesuré le 2026-08-22 : en synchrone, `apps` immobilisait un worker gunicorn **31,2 s** et
#: `modeles` **20,6 s** — sur 4 workers × 2 threads, soit 1/8 du serveur bloqué par un clic. Les
#: deux boutons d'origine faisaient déjà exactement cela (la docstring annonçait « ~1 s »).
CELERY = 'celery'
#: Dans le processus web qui reçoit la requête. OBLIGATOIRE pour un registre en MÉMOIRE : le faire
#: en Celery rechargerait les modules du worker Celery, pas ceux des processus qui servent les
#: pages — l'actualisation n'aurait littéralement aucun effet visible.
PROCESS = 'processus'
EXECUTIONS = {CELERY: "Tâche Celery (non bloquante)", PROCESS: "Dans le processus web"}


@dataclass
class RefreshResult:
    """Compte-rendu UNIFORME d'une actualisation, quelle que soit sa nature.

    Chaque rafraîchisseur natif rend ce qu'il veut (`SyncResult`, un dict de scores, un entier) ;
    l'adaptateur traduit ici. Sans ce contrat, l'UI devrait connaître sept formats.
    """
    ok: bool = True
    added: int = 0
    updated: int = 0
    removed: int = 0
    total: int = 0
    messages: Tuple[str, ...] = ()
    duration_s: float = 0.0

    def summary(self) -> str:
        """Phrase courte pour un toast. Le cas « rien n'a bougé » est DIT, pas laissé vide :
        un compte-rendu muet se lit comme un échec."""
        bouts = []
        if self.added:
            bouts.append(f"{self.added} ajouté{'s' if self.added > 1 else ''}")
        if self.updated:
            bouts.append(f"{self.updated} mis à jour")
        if self.removed:
            bouts.append(f"{self.removed} retiré{'s' if self.removed > 1 else ''}")
        if not bouts:
            bouts.append("aucun changement")
        if self.total:
            bouts.append(f"{self.total} au total")
        return ' · '.join(bouts)

    def as_dict(self) -> dict:
        return {'ok': self.ok, 'added': self.added, 'updated': self.updated,
                'removed': self.removed, 'total': self.total, 'messages': list(self.messages),
                'duration_s': round(self.duration_s, 3), 'summary': self.summary()}


@dataclass(frozen=True)
class Registry:
    """Ce qu'une page catalogue déclare pour hériter de l'actualisation."""
    key: str
    label: str
    nature: str
    #: D'où vient l'état — phrase courte affichée à l'utilisateur, qui répond à « actualiser quoi ? »
    source: str
    #: Le rafraîchisseur. `None` pour un registre DÉRIVÉ : il n'y a rien à actualiser.
    refresh: Optional[Callable[[], RefreshResult]] = None
    #: Où il tourne. Laissé vide, il est DÉDUIT de la nature — c'est le bon défaut, parce que la
    #: nature contraint réellement le lieu (état partagé → Celery ; mémoire du process → sur place).
    execution: str = ''
    #: Comptage courant, pour afficher un total sans lancer d'actualisation.
    count: Optional[Callable[[], int]] = None
    #: Les FICHES du registre, par clé — `{clé: dict | dataclass}`. Facultatif (2026-09-11).
    #: C'est ce qui rend un champ ADRESSABLE par une balise de doc (`fact_tags`,
    #: `<!-- WAMA:FAIT(registre/clé/champ) -->`) : un registre qui ne le déclare pas peut être
    #: compté, pas cité. Il ne fait PAS partie du contrat d'actualisation — il le lit.
    entries: Optional[Callable[[], Dict[str, object]]] = None
    url_name: str = ''
    #: 'staff' (une actualisation qui ÉCRIT) ou 'auth' (sans effet de bord partagé — ouverte aux
    #: développeurs : un compte utilisateur LIT les registres sans les actualiser, cf. `is_authorized`).
    permission: str = 'staff'
    #: Passé au démarrage du serveur. RÉSERVÉ aux rafraîchisseurs en mémoire et bon marché :
    #: un scan disque à chaque boot de worker gunicorn se paie ×4 et court après lui-même.
    on_startup: bool = False
    #: Nom de la tâche Celery Beat qui l'actualise périodiquement, s'il y en a une. Déclaratif :
    #: sert à MONTRER dans l'UI qu'un catalogue se tient à jour tout seul.
    periodic: str = ''
    #: Lien FACULTATIF vers le kind de manifeste correspondant (4 des 7 en ont un).
    manifest_kind: str = ''
    #: À QUI sont les éléments (`PROVENANCES`). Vide = NON DÉCLARÉ, ce que la garde
    #: `tests_registry_provenance` refuse ; pas de défaut, sinon tout registre passerait pour du
    #: système sans l'avoir dit.
    provenance: str = ''
    #: `app_label.Model` de la ligne qui porte propriétaire et portée — exigé pour OWNED / MIXED.
    owner_model: str = ''
    #: Le champ de cette ligne qui NOMME un élément — l'`element_id` que reçoit
    #: `accessible(user, access_kind, element_id)` quand la famille se décide par la provenance
    #: (`KIND_DECISION` = 'provenance' : `model_key` pour les modèles).
    owner_key: str = ''
    #: `clé → app` : l'app qui DÉCLARE un élément du CODE (`ROADMAP §29` étape 4). Un élément du
    #: code n'a pas de ligne : il n'a pas d'auteur à lui, il suit l'app qui le porte — système
    #: dans une app réelle, à son créateur dans une jumelle. '' : rien ne le restreint.
    element_app: Optional[Callable[[str], str]] = None
    #: `clé → bool` : la clé désigne-t-elle AUSSI un élément du CODE ? Pour une famille dont une
    #: ligne d'utilisateur peut porter le NOM d'un élément système (un skill de prompt remplace,
    #: pour son auteur, le fichier du même nom) : une ligne qu'un compte ne voit pas ne lui ôte
    #: pas l'élément système (`permissions._provenance_accessible`). None : les clés ne se
    #: recouvrent pas.
    in_code: Optional[Callable[[str], bool]] = None
    #: La famille d'`accounts.permissions.KIND_DECISION` dont ce registre liste les éléments : le
    #: lien entre « à qui c'est » (ici) et « qui a le droit » (là-bas), une famille par registre.
    access_kind: str = ''
    doc: str = ''
    description: str = ''


REGISTRIES: Dict[str, Registry] = {}

#: Lieu d'exécution IMPOSÉ par la nature. Ce n'est pas une préférence : un état partagé mis à jour
#: dans le worker web bloque le serveur, et un registre en mémoire actualisé en Celery n'a aucun
#: effet sur les processus qui servent les pages.
EXECUTION_BY_NATURE = {SCAN: CELERY, MEASURE: CELERY, REDECLARATION: PROCESS}


def execution_of(r: Registry) -> str:
    return r.execution or EXECUTION_BY_NATURE.get(r.nature, PROCESS)


def register(r: Registry) -> Registry:
    if r.key in REGISTRIES:
        raise ValueError(f"registre '{r.key}' déjà enregistré")
    if r.nature not in NATURES:
        raise ValueError(f"nature '{r.nature}' inconnue (attendu : {', '.join(NATURES)})")
    if r.execution and r.execution not in EXECUTIONS:
        raise ValueError(f"exécution '{r.execution}' inconnue (attendu : {', '.join(EXECUTIONS)})")
    if r.nature == REDECLARATION and r.execution == CELERY:
        raise ValueError(
            f"'{r.key}' : un registre en MÉMOIRE ne peut pas s'actualiser en Celery — le worker "
            f"rechargerait ses propres modules, pas ceux des processus qui servent les pages")
    if r.nature == DERIVED and r.refresh is not None:
        raise ValueError(
            f"'{r.key}' : un registre DÉRIVÉ ne peut pas avoir de rafraîchisseur — s'il en a un, "
            f"c'est qu'il stocke quelque chose, donc sa nature est mal déclarée")
    if r.nature != DERIVED and r.refresh is None:
        raise ValueError(
            f"'{r.key}' : nature '{r.nature}' sans rafraîchisseur — déclarer DERIVED si la page "
            f"recalcule à chaque affichage")
    if r.provenance and r.provenance not in PROVENANCES:
        raise ValueError(f"'{r.key}' : provenance '{r.provenance}' inconnue "
                         f"(attendu : {', '.join(PROVENANCES)})")
    if (r.provenance in CARRIED) != bool(r.owner_model):
        raise ValueError(
            f"'{r.key}' : `owner_model` se déclare avec la provenance {' ou '.join(CARRIED)}, et "
            f"seulement avec elle — c'est la ligne qui porte propriétaire et portée")
    if r.owner_key and not r.owner_model:
        raise ValueError(f"'{r.key}' : `owner_key` nomme un champ de `owner_model`, absent ici")
    if r.in_code and not r.owner_key:
        raise ValueError(f"'{r.key}' : `in_code` complète la ligne nommée par `owner_key` ; "
                         f"sans elle, rien ne le lirait")
    if r.element_app and not r.owner_key:
        raise ValueError(f"'{r.key}' : `element_app` complète la ligne nommée par `owner_key` "
                         f"(un élément sans ligne est du code) ; sans elle, rien ne le lirait")
    REGISTRIES[r.key] = r
    return r


def get(key: str) -> Registry:
    try:
        return REGISTRIES[key]
    except KeyError:
        raise KeyError(
            f"registre '{key}' inconnu (enregistrés : {', '.join(sorted(REGISTRIES)) or '—'})")


def _carrying_registry(access_kind: str = '', manifest_kind: str = ''):
    """Le registre porté qui nomme la ligne d'une famille d'accès ou d'un kind de manifeste."""
    return next((r for r in REGISTRIES.values()
                 if r.provenance in CARRIED and r.owner_key
                 and ((access_kind and r.access_kind == access_kind)
                      or (manifest_kind and r.manifest_kind == manifest_kind))), None)


def carried_rows(element_id, *, access_kind: str = '', manifest_kind: str = ''):
    """Les lignes qui portent la provenance de l'élément `element_id` — `owner_model` filtré par
    `owner_key` —, trouvées par le registre de sa famille d'accès (`accounts.permissions.
    accessible`) ou de son kind de manifeste (`manifests.ownership.promote_row`). None quand aucun
    registre porté ne nomme sa ligne : l'appelant dit ce que cela vaut pour lui."""
    from django.apps import apps
    registry = _carrying_registry(access_kind, manifest_kind)
    if registry is None:
        return None
    return apps.get_model(registry.owner_model).objects.filter(**{registry.owner_key: element_id})


def declaring_app(element_id, *, access_kind: str) -> str:
    """L'app qui déclare l'élément du CODE `element_id`, lue par le registre de sa famille
    (`Registry.element_app`) — '' si le registre ne la déclare pas ou ne la trouve pas."""
    registry = _carrying_registry(access_kind=access_kind)
    if registry is None or registry.element_app is None:
        return ''
    return registry.element_app(element_id) or ''


def declared_in_code(element_id, *, access_kind: str) -> bool:
    """La clé `element_id` désigne-t-elle aussi un élément du CODE (`Registry.in_code`) ?"""
    registry = _carrying_registry(access_kind=access_kind)
    return bool(registry is not None and registry.in_code is not None
                and registry.in_code(element_id))


def is_authorized(r: Registry, user) -> bool:
    """Ce compte peut-il ACTUALISER ce registre ? Le lire relève de l'accès à l'outil « Registres »
    (`accounts.permissions`, tout compte) — actualiser est un geste à part.

    Décision de Fabien (2026-10-13) : un compte UTILISATEUR lit les registres sans les actualiser.
    Un registre 'auth' s'actualise donc à partir du profil développeur (`can_manage_registries`,
    la règle unique de gestion des registres), un registre 'staff' reste à l'administration.
    """
    if not (user and user.is_authenticated):
        return False
    if r.permission == 'staff':
        return bool(user.is_staff)
    from wama.accounts.permissions import can_manage_registries
    return can_manage_registries(user)


def refusal(r: Registry) -> str:
    """Le motif d'un refus d'actualisation, lisible tel quel (les vues y lisent « réservé »)."""
    if r.permission == 'staff':
        return "actualisation réservée aux administrateurs"
    return "actualisation réservée aux développeurs : un compte utilisateur lit les registres"


# ──────────────────────────────────────────────────────────────────────────────────────────────
# PROPAGATION entre processus — le trou qu'un registre en mémoire creuse forcément
# ──────────────────────────────────────────────────────────────────────────────────────────────

#: Version vue par CE processus, par clé. Comparée à un compteur partagé dans Redis.
_SEEN_VERSIONS: Dict[str, int] = {}


def _version_key(key: str) -> str:
    return f"wama:registre:{key}:version"


def _cache():
    """Le cache Django — PAS un client Redis direct.

    ⚠ Première version écrite avec `django_redis.get_redis_connection` : le paquet **n'est pas
    installé** ici (WAMA emploie le backend Redis natif de Django, `CACHES` → `RedisCache`). La
    propagation se désactivait donc en silence, et seule la vérification l'a vu. Passer par l'API
    de cache la rend indépendante du backend — et si celui-ci devient local par processus, on perd
    la propagation sans rien casser d'autre.
    """
    try:
        from django.core.cache import cache
        return cache
    except Exception:
        return None


def _shared_version(key: str) -> Optional[int]:
    c = _cache()
    if c is None:
        return None
    try:
        return int(c.get(_version_key(key)) or 0)
    except Exception:
        return None


def mark_refreshed(key: str) -> None:
    """Signale aux AUTRES processus qu'ils sont périmés.

    ⚠ Sans cela, un registre en mémoire actualisé n'est à jour que dans le worker qui a reçu le
    clic. Gunicorn en fait tourner **4** : l'utilisateur verrait « 40 fonctions », rechargerait, et
    retomberait sur « 39 » une fois sur deux. Un mécanisme à moitié efficace est pire qu'aucun,
    parce qu'il donne l'impression d'avoir agi.
    """
    c = _cache()
    if c is None:
        return
    try:
        # `incr` lève si la clé n'existe pas — `add` ne l'écrase pas si un autre processus l'a
        # déjà posée entre-temps, ce qui rend l'amorçage sûr à plusieurs.
        c.add(_version_key(key), 0, timeout=None)
        _SEEN_VERSIONS[key] = int(c.incr(_version_key(key)))
    except Exception:
        logger.debug("propagation de '%s' impossible", key, exc_info=True)


def synchronize(key: str) -> bool:
    """Recharge SI un autre processus a actualisé depuis notre dernier passage. Rend True s'il a
    fallu recharger.

    Appelé au rendu de chaque page catalogue (via le tag `refresh_button`) : une lecture Redis,
    et un rechargement seulement quand quelqu'un a réellement actualisé. C'est le prix minimal pour
    que la même déclaration donne le bouton ET la cohérence entre workers.
    """
    r = REGISTRIES.get(key)
    if r is None or r.nature != REDECLARATION:
        return False           # les autres écrivent dans un état partagé : rien à propager
    shared = _shared_version(key)
    if shared is None or shared <= _SEEN_VERSIONS.get(key, 0):
        return False
    try:
        r.refresh()
        _SEEN_VERSIONS[key] = shared
        logger.info("registre '%s' resynchronisé depuis un autre processus (v%s)", key, shared)
        return True
    except Exception:
        logger.warning("resynchronisation de '%s' en échec", key, exc_info=True)
        return False


def refresh(key: str, *, user=None) -> RefreshResult:
    """Exécute l'actualisation ICI, en synchrone. Chronomètre et uniformise le compte-rendu.

    ⚠ Ce n'est PAS le point d'entrée des vues : pour un registre en Celery, la vue doit passer par
    `launch()`, sinon elle bloque un worker web (31 s mesurées pour `apps`). Cette fonction est
    ce que la tâche Celery appelle, et ce que les registres en mémoire utilisent directement.

    Une exception du rafraîchisseur devient un `RefreshResult` en échec plutôt qu'une 500 : une
    actualisation qui plante ne doit pas emporter la page qu'elle sert.
    """
    r = get(key)
    if user is not None and not is_authorized(r, user):
        return RefreshResult(ok=False, messages=(refusal(r),))
    if r.nature == DERIVED:
        return RefreshResult(ok=True, total=_count(r),
                             messages=("dérivé à chaque affichage — rien à actualiser",))
    t0 = time.monotonic()
    try:
        res = r.refresh()
    except Exception as e:                       # noqa: BLE001 — on RAPPORTE, on ne propage pas
        logger.warning("actualisation de '%s' en échec", key, exc_info=True)
        return RefreshResult(ok=False, duration_s=time.monotonic() - t0,
                             messages=(str(e)[:300],))
    if not isinstance(res, RefreshResult):
        res = RefreshResult(ok=True, messages=(str(res)[:300],) if res else ())
    res.duration_s = time.monotonic() - t0
    if not res.total:
        res.total = _count(r)
    if res.ok and r.nature == REDECLARATION:
        mark_refreshed(key)
    return res


def launch(key: str, *, user=None) -> dict:
    """LE point d'entrée des vues. Décide où l'actualisation tourne et rend une réponse immédiate.

    - registre en Celery  → met la tâche en file, rend `{'async': True, 'task_id': …}` ;
    - registre en mémoire → exécute sur place (mesuré < 0,4 s) et rend le compte-rendu complet.

    Si le courtier Celery est injoignable, on le DIT au lieu de basculer en synchrone : un repli
    silencieux rendrait la page muette 31 secondes, ce qui ressemble à une panne réseau.
    """
    r = get(key)
    if user is not None and not is_authorized(r, user):
        return {'ok': False, 'error': refusal(r)}
    if r.nature == DERIVED:
        return dict(refresh(key).as_dict(), **{'async': False})

    if execution_of(r) == PROCESS:
        return dict(refresh(key).as_dict(), **{'async': False})

    try:
        from .tasks import refresh_registry
        tache = refresh_registry.delay(key)
    except Exception as e:                       # noqa: BLE001
        logger.warning("mise en file de '%s' impossible", key, exc_info=True)
        return {'ok': False, 'async': True,
                'error': f"file de tâches injoignable — actualisation non lancée ({str(e)[:120]})"}
    return {'ok': True, 'async': True, 'task_id': tache.id,
            'summary': f"{r.label} : actualisation lancée en arrière-plan"}


def task_state(task_id: str) -> dict:
    """État d'une actualisation lancée en Celery — de quoi faire patienter l'utilisateur."""
    try:
        from celery.result import AsyncResult
        res = AsyncResult(task_id)
    except Exception as e:                       # noqa: BLE001
        return {'ok': False, 'done': True, 'error': str(e)[:200]}
    if not res.ready():
        return {'ok': True, 'done': False, 'state': res.state}
    if res.failed():
        return {'ok': False, 'done': True, 'state': res.state,
                'error': str(res.result)[:300]}
    charge = res.result if isinstance(res.result, dict) else {}
    return dict({'ok': True, 'done': True, 'state': res.state}, **charge)


def _count(r: Registry) -> int:
    if not r.count:
        return 0
    try:
        return int(r.count())
    except Exception:
        return 0


def overview(with_coverage: bool = False) -> List[dict]:
    """Photo de tous les registres, pour l'UI et pour la documentation générée.

    `with_coverage` ajoute la couverture de test MESURÉE (`registries_coverage`). Optionnel et
    désactivé par défaut à dessein : le calcul lit et analyse les fichiers de test, ce qui n'a rien
    à faire dans un appel qui ne veut que l'inventaire. La page de supervision, elle, l'active.
    """
    couvertures = {}
    if with_coverage:
        try:
            from .registries_coverage import coverage
            couvertures = {c['key']: c for c in coverage()}
        except Exception:
            logger.debug("couverture de test indisponible", exc_info=True)

    out = []
    for r in sorted(REGISTRIES.values(), key=lambda x: x.label):
        c = couvertures.get(r.key) or {}
        out.append({
            # Couverture : présente uniquement si demandée. `tests_specifiques` vaut None quand la
            # mesure n'a pas tourné — à distinguer de 0, qui affirmerait « aucun test » à tort.
            'tests_specifiques': c.get('nb_specifiques') if c else None,
            'tests_noms': c.get('specifiques') or [],
            'tests_manquants': bool(c.get('manquant')),
            'key': r.key, 'label': r.label, 'nature': r.nature,
            'nature_label': NATURES[r.nature], 'source': r.source,
            'refreshable': r.nature != DERIVED, 'permission': r.permission,
            'url_name': r.url_name, 'on_startup': r.on_startup,
            'periodic': r.periodic, 'manifest_kind': r.manifest_kind,
            'provenance': r.provenance, 'provenance_label': PROVENANCES.get(r.provenance, ''),
            'owner_model': r.owner_model, 'access_kind': r.access_kind,
            'total': _count(r), 'doc': r.doc, 'description': r.description,
        })
    return out


def run_startup() -> Dict[str, RefreshResult]:
    """Passe les registres marqués `on_startup`. Appelé une fois par processus.

    ⚠ N'y mettre QUE des rafraîchisseurs en mémoire. Gunicorn lance plusieurs workers : un scan
    disque ici se paierait autant de fois, et deux scans concurrents sur le même registre
    persistant se marchent dessus. Le bon domicile d'un SCAN périodique est Celery Beat, déclaré
    dans le champ `periodic` — pas le démarrage.
    """
    out = {}
    for r in REGISTRIES.values():
        if not r.on_startup or r.nature == DERIVED:
            continue
        if r.nature == SCAN:
            logger.warning(
                "registre '%s' : on_startup ignoré — un SCAN ne se lance pas au boot "
                "(voir `periodic`)", r.key)
            continue
        out[r.key] = refresh(r.key)
    return out
