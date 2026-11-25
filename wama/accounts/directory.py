"""
L'annuaire lu PAR UNITÉ, et les comptes préparés AVANT une première connexion (2026-11-25,
demande de Fabien). Doc : `PROFILES_PERMISSIONS.md §1.12`.

Jusqu'ici WAMA ne lisait l'annuaire qu'à la connexion d'une personne : un compte n'existait
qu'une fois sa titulaire venue, puis attendait sa validation. Ici un administrateur retrouve les
personnes d'une unité et PRÉ-INSCRIT celles qui n'ont pas de compte — inactif, sans mot de passe
local, sans prévenir personne. Il peut alors activer un compte avant que la personne ne vienne.

Trois règles, tenues par `accounts/tests/tests_directory.py` :
  - LECTURE SEULE côté annuaire, et par une liste FERMÉE d'attributs (`person_attributes`) :
    jamais « tout ce que la fiche porte ». Un annuaire rend bien plus que ce qu'un compte demande ;
  - le MINIMUM à la pré-inscription : identifiant, prénom, nom, adresse, unité principale. Le
    reste se complète avec la personne, à sa première connexion ;
  - tout ce qui DÉSIGNE l'annuaire (serveur, bases, liaison) vient des réglages, jamais d'ici.

La pré-inscription passe par le moteur de connexion lui-même (`WamaLDAPBackend.populate_user`,
la voie « remplir sans authentifier » de sa librairie) : le compte pré-inscrit est celui que la
première connexion aurait créé, pas un compte voisin.
"""
import logging
import re
from contextlib import contextmanager

from django.conf import settings
from django.contrib.auth import get_user_model

from .ldap import MAIN_UNIT_ATTRIBUTE
from .models import IDENTITY_FIELDS

logger = logging.getLogger(__name__)

#: Ce qu'on lit de la fiche d'une UNITÉ — et rien d'autre.
UNIT_ATTRIBUTES = ('supannCodeEntite', 'description', 'ou', 'supannTypeEntite',
                   'supannCodeEntiteParent')

#: Une personne de l'annuaire qui n'a PAS de compte WAMA. Les états d'un compte qui existe sont
#: ceux de `moderation.ACCOUNT_STATES` — une seule lecture pour la page et pour l'annuaire.
STATE_ABSENT = 'absent'
STATE_LABELS_ABSENT = {STATE_ABSENT: 'Sans compte'}

#: Le nombre de comptes qu'UN passage de pré-inscription crée au plus (commande, page, assistant).
#: Une unité plus large se fait en plusieurs passages, ou par ses sous-unités.
PREREGISTER_LIMIT = 100
#: La longueur minimale d'un texte qui désigne une unité (`lookup`).
MIN_QUERY_LENGTH = 3


class DirectoryUnavailable(Exception):
    """L'annuaire n'est pas réglé, ne répond pas ou refuse la question — motif pour l'opérateur."""


# ── Liaison ─────────────────────────────────────────────────────────────────────────────────

def connect():
    """Une liaison ouverte à l'annuaire des réglages — LA liaison de toute lecture hors connexion
    (cette brique, `sync_org_units`). Lève `DirectoryUnavailable`."""
    try:
        import ldap
    except ImportError as e:
        raise DirectoryUnavailable("la librairie d'annuaire n'est pas installée") from e
    uri = getattr(settings, 'AUTH_LDAP_SERVER_URI', '') or ''
    if not uri:
        raise DirectoryUnavailable("aucun annuaire n'est réglé")
    try:
        conn = ldap.initialize(uri)
        conn.set_option(ldap.OPT_NETWORK_TIMEOUT, 10)
        conn.set_option(ldap.OPT_TIMEOUT, 15)
        bind_dn = getattr(settings, 'AUTH_LDAP_BIND_DN', '') or ''
        if bind_dn:
            conn.simple_bind_s(bind_dn, getattr(settings, 'AUTH_LDAP_BIND_PASSWORD', ''))
        else:
            conn.simple_bind_s()
    except ldap.LDAPError as e:
        raise DirectoryUnavailable(f"l'annuaire ne répond pas ({type(e).__name__})") from e
    return conn


@contextmanager
def session(conn=None):
    """La liaison reçue, ou une liaison ouverte pour l'occasion et refermée ensuite."""
    if conn is not None:
        yield conn
        return
    conn = connect()
    try:
        yield conn
    finally:
        try:
            conn.unbind_s()
        except Exception:
            pass


def _values(attrs, key) -> list:
    return [v.decode('utf-8', 'ignore') if isinstance(v, bytes) else str(v)
            for v in (attrs.get(key) or [])]


def _first(attrs, key) -> str:
    values = _values(attrs, key)
    return values[0] if values else ''


def _escape(text: str) -> str:
    import ldap.filter
    return ldap.filter.escape_filter_chars(text)


# ── Unités ──────────────────────────────────────────────────────────────────────────────────

def unit_record(attrs):
    """Fiche d'unité → `{code, name, type, parent}`, ou None sans code. Le libellé d'abord, le
    nom court en repli, le code en dernier ressort : certaines fiches n'ont aucun libellé."""
    code = _first(attrs, 'supannCodeEntite')
    if not code:
        return None
    return {'code': code,
            'name': _first(attrs, 'description') or _first(attrs, 'ou') or code,
            'type': _first(attrs, 'supannTypeEntite'),
            'parent': _first(attrs, 'supannCodeEntiteParent')}


def search_units(conn, filterstr: str) -> list:
    """Les fiches d'unité qui répondent à `filterstr`, dans la base des structures des réglages."""
    import ldap
    base = getattr(settings, 'LDAP_STRUCTURES_BASE_DN', None)
    if not base:
        raise DirectoryUnavailable("la base des unités n'est pas réglée")
    try:
        found = conn.search_s(base, ldap.SCOPE_SUBTREE, filterstr, list(UNIT_ATTRIBUTES))
    except ldap.LDAPError as e:
        raise DirectoryUnavailable(f"la lecture des unités a échoué ({type(e).__name__})") from e
    records = (unit_record(attrs) for dn, attrs in found if dn)
    return [r for r in records if r]


def find_units(text: str, *, exact: bool = False, conn=None) -> list:
    """Les unités que désigne `text` — contenu dans le code ou le libellé, ou le code EXACT —
    avec toutes leurs sous-unités, triées par code.

    Un code exact que la base des unités ne porte pas est gardé tel quel : une personne peut être
    rattachée à un code que seule sa fiche connaît."""
    text = (text or '').strip()
    if not text:
        return []
    esc = _escape(text)
    first = (f'(supannCodeEntite={esc})' if exact else
             f'(|(supannCodeEntite=*{esc}*)(description=*{esc}*)(ou=*{esc}*))')
    with session(conn) as c:
        found = {u['code']: u for u in search_units(c, first)}
        if exact and text not in found:
            found[text] = {'code': text, 'name': text, 'type': '', 'parent': ''}
        todo, guard = list(found), 0
        while todo and guard < 500:                # garde : une boucle d'annuaire ne tourne pas
            guard += 1
            parent = todo.pop()
            for child in search_units(c, f'(supannCodeEntiteParent={_escape(parent)})'):
                if child['code'] not in found:
                    found[child['code']] = child
                    todo.append(child['code'])
    return sorted(found.values(), key=lambda u: u['code'])


# ── Personnes ───────────────────────────────────────────────────────────────────────────────

def login_attribute() -> str:
    """L'attribut qui porte l'identifiant de connexion — lu du filtre de recherche des réglages
    (`AUTH_LDAP_USER_SEARCH`), pour que la lecture par unité rende les MÊMES identifiants que
    ceux qu'une connexion accepte."""
    search = getattr(settings, 'AUTH_LDAP_USER_SEARCH', None)
    found = re.search(r'\(\s*([\w-]+)\s*=\s*%\(user\)s\s*\)', getattr(search, 'filterstr', '') or '')
    return found.group(1) if found else 'uid'


def person_attributes() -> tuple:
    """La liste FERMÉE de ce qu'on lit d'une fiche de personne : son identifiant, les champs
    d'identité du compte, son unité principale. Rien d'autre ne sort de l'annuaire."""
    mapped = getattr(settings, 'AUTH_LDAP_USER_ATTR_MAP', {}) or {}
    identity = tuple(mapped[field] for field in IDENTITY_FIELDS if field in mapped)
    return (login_attribute(), *identity, MAIN_UNIT_ATTRIBUTE)


def people_of(codes, *, conn=None) -> list:
    """Les personnes dont l'unité PRINCIPALE est l'une des unités `codes`, triées par
    identifiant : `{username, first_name, last_name, email, main_unit}`. Une personne n'a
    qu'une appartenance dans WAMA, la principale (`common.models.profile_org_codes`) : la
    retrouver sous une unité où elle n'est que de passage préparerait un compte que cette unité
    ne verrait pas."""
    import ldap
    codes = [c for c in dict.fromkeys(codes) if c]
    search = getattr(settings, 'AUTH_LDAP_USER_SEARCH', None)
    if search is None:
        raise DirectoryUnavailable("la recherche des personnes n'est pas réglée")
    if not codes:
        return []
    mapped = getattr(settings, 'AUTH_LDAP_USER_ATTR_MAP', {}) or {}
    clauses = ''.join(f'({MAIN_UNIT_ATTRIBUTE}={_escape(code)})' for code in codes)
    with session(conn) as c:
        try:
            found = c.search_s(search.base_dn, search.scope, f'(|{clauses})',
                               list(person_attributes()))
        except ldap.SIZELIMIT_EXCEEDED as e:
            raise DirectoryUnavailable(
                "l'annuaire borne sa réponse : viser une unité plus fine") from e
        except ldap.LDAPError as e:
            raise DirectoryUnavailable(
                f"la lecture des personnes a échoué ({type(e).__name__})") from e
    login, people = login_attribute(), []
    for dn, attrs in found:
        username = _first(attrs, login) if dn else ''
        if not username:
            continue
        person = {'username': username, 'main_unit': _first(attrs, MAIN_UNIT_ATTRIBUTE)}
        person.update({field: _first(attrs, mapped[field]) if field in mapped else ''
                       for field in IDENTITY_FIELDS})
        people.append(person)
    return sorted(people, key=lambda p: p['username'].lower())


def person_org(username: str, *, conn=None) -> dict:
    """Ce que l'annuaire porte AUJOURD'HUI du rattachement de `username` : les champs de profil
    que la connexion en tirerait (`ldap._parse_org`), lus par la liste fermée
    `ldap.ORG_ATTRIBUTES`. `{}` si l'annuaire ne connaît pas cet identifiant.

    Sert à PROPOSER ses données à la personne et à écrire celles qu'elle ajoute
    (`accounts/directory_consent.py`) — la valeur vient d'ici, jamais du navigateur."""
    import ldap

    from .ldap import ORG_ATTRIBUTES, _parse_org
    search = getattr(settings, 'AUTH_LDAP_USER_SEARCH', None)
    if search is None:
        raise DirectoryUnavailable("la recherche des personnes n'est pas réglée")
    username = (username or '').strip()
    if not username:
        return {}
    with session(conn) as c:
        try:
            found = c.search_s(search.base_dn, search.scope,
                               f'({login_attribute()}={_escape(username)})', list(ORG_ATTRIBUTES))
        except ldap.LDAPError as e:
            raise DirectoryUnavailable(
                f"la lecture de la fiche a échoué ({type(e).__name__})") from e
    for dn, attrs in found:
        if dn:
            return _parse_org({name: _values(attrs, name) for name in attrs})
    return {}


def accounts_named(usernames) -> dict:
    """Les comptes WAMA de ces identifiants, `{identifiant en minuscules: compte}` — sans la casse,
    comme à la connexion (l'annuaire écrit `Prenom.Nom` là où le compte est en minuscules)."""
    from django.db.models.functions import Lower
    names = {(name or '').strip().lower() for name in usernames} - {''}
    return {u.lowered: u for u in get_user_model().objects
            .annotate(lowered=Lower('username')).filter(lowered__in=names).order_by('username')}


def with_account_state(people) -> list:
    """Chaque personne avec l'état de son compte WAMA (`state`) : `STATE_ABSENT` sans compte,
    sinon l'état que la page des utilisateurs lit (`moderation.account_states` : actif,
    pré-inscrit, en attente, désactivé). Un identifiant se compare sans la casse, comme à la
    connexion."""
    from .moderation import account_states
    accounts = accounts_named(p['username'] for p in people)
    states = account_states(accounts.values())
    out = []
    for person in people:
        account = accounts.get(person['username'].lower())
        out.append({**person, 'state': STATE_ABSENT if account is None else states[account.pk]})
    return out


def lookup(text: str = '', codes=()) -> dict:
    """Les unités que désignent `text` (contenu dans le code ou le libellé) et `codes` (exacts),
    et leurs personnes avec l'état de leur compte : `{'units': […], 'people': […]}` — LA lecture
    de la commande, de la page des utilisateurs et de l'assistant. Une seule liaison.

    Un texte de moins de `MIN_QUERY_LENGTH` caractères est refusé : il désignerait la moitié
    d'un établissement."""
    text = (text or '').strip()
    if text and len(text) < MIN_QUERY_LENGTH:
        raise DirectoryUnavailable(
            f"désigner l'unité par au moins {MIN_QUERY_LENGTH} caractères")
    units = {}
    with session() as conn:
        for code in codes or ():
            units.update((u['code'], u) for u in find_units(code, exact=True, conn=conn))
        if text:
            units.update((u['code'], u) for u in find_units(text, conn=conn))
        people = with_account_state(people_of(list(units), conn=conn)) if units else []
    return {'units': sorted(units.values(), key=lambda u: u['code']), 'people': people}


def state_labels() -> dict:
    """Clé → libellé de tout état que `with_account_state` peut rendre."""
    from .moderation import ACCOUNT_STATES
    return {**STATE_LABELS_ABSENT, **ACCOUNT_STATES}


# ── Rapprochement périodique ────────────────────────────────────────────────────────────────

#: Type de la notification DANS WAMA d'un rapprochement qui a trouvé des arrivées ou des départs.
DIRECTORY_CHANGES_KIND = 'directory_changes'


def followed_units() -> list:
    """Les codes EXACTS des unités que cette instance suit (réglage
    `WAMA_DIRECTORY_FOLLOWED_UNITS`, posé dans l'environnement de l'instance — jamais au dépôt)."""
    return [code for code in (getattr(settings, 'WAMA_DIRECTORY_FOLLOWED_UNITS', None) or []) if code]


def reconcile(codes=None, *, conn=None) -> dict:
    """Rapproche WAMA de l'annuaire pour les unités `codes` (défaut : `followed_units`), sous-unités
    comprises. LECTURE SEULE des deux côtés. Rend `{'units', 'arrivals', 'departures'}` :
    `arrivals`, les personnes de ces unités qui n'ont pas de compte ; `departures`, les comptes
    d'annuaire que WAMA range dans ces unités et que l'annuaire n'y compte plus (partis, ou
    passés à une autre unité)."""
    from .permissions import is_directory_account
    codes = list(dict.fromkeys(followed_units() if codes is None else codes))
    if not codes:
        return {'units': [], 'arrivals': [], 'departures': []}
    units = {}
    with session(conn) as c:
        for code in codes:
            units.update((u['code'], u) for u in find_units(code, exact=True, conn=c))
        people = people_of(list(units), conn=c)
    listed = {p['username'].lower() for p in people}
    known = accounts_named(listed)
    holders = get_user_model().objects.filter(profile__org_entity_code__in=list(units))
    return {'units': sorted(units),
            'arrivals': sorted(p['username'] for p in people if p['username'].lower() not in known),
            'departures': sorted(u.get_username() for u in holders
                                 if is_directory_account(u) and u.get_username().lower() not in listed)}


def report_reconciliation(report: dict) -> int:
    """Prévient les administrateurs, DANS WAMA, de ce qu'un rapprochement a trouvé — rien s'il n'a
    rien trouvé, et rien de plus tant qu'une notification de ce type attend encore d'être lue.
    Rend le nombre de notifications posées."""
    from django.urls import reverse

    from wama.common.models import Notification
    from wama.common.utils.notifications import notify_in_app

    from .permissions import administrators
    arrivals, departures = report.get('arrivals') or [], report.get('departures') or []
    if not (arrivals or departures):
        return 0
    if Notification.objects.filter(kind=DIRECTORY_CHANGES_KIND, read_at__isnull=True).exists():
        return 0
    lines = []
    if arrivals:
        lines.append(f"{len(arrivals)} personne(s) des unités suivies n'ont pas de compte : "
                     "« Importer depuis l'annuaire » les prépare.")
    if departures:
        shown = ', '.join(departures[:20]) + ('…' if len(departures) > 20 else '')
        lines.append(f"{len(departures)} compte(s) ne sont plus dans leur unité d'après "
                     f"l'annuaire : {shown}.")
    return notify_in_app(administrators(), DIRECTORY_CHANGES_KIND,
                         f"Annuaire : {len(arrivals)} arrivée(s), {len(departures)} départ(s)",
                         body='\n'.join(lines), url=reverse('accounts:user-management'))


# ── Pré-inscription ─────────────────────────────────────────────────────────────────────────

def preregister(usernames, *, limit: int = PREREGISTER_LIMIT) -> dict:
    """Crée, INACTIF, le compte de chaque identifiant qui n'en a pas ; rend
    `{'created': […], 'existing': […], 'missing': […]}`.

    Un compte qui existe n'est PAS touché (ni relu, ni rempli) : ce qu'il porte se met à jour
    avec sa titulaire. `missing` : l'annuaire ne connaît pas cet identifiant. Rejouable — un
    second passage ne trouve que de l'existant. Au plus `limit` identifiants par passage
    (`PREREGISTER_LIMIT`) : au-delà, `ValueError`, et rien n'est créé."""
    from .ldap_backend import WamaLDAPBackend
    usernames = [name for name in dict.fromkeys((u or '').strip() for u in usernames) if name]
    if len(usernames) > limit:
        raise ValueError(f"{len(usernames)} comptes demandés : un passage en crée au plus {limit} "
                         f"— viser une unité plus fine")
    accounts = get_user_model().objects
    backend = WamaLDAPBackend()
    backend.preregistering = True
    report = {'created': [], 'existing': [], 'missing': []}
    for username in usernames:
        if accounts.filter(username__iexact=username).exists():
            report['existing'].append(username)
            continue
        user = backend.populate_user(username)
        if user is None or not user.pk:
            report['missing'].append(username)
        else:
            report['created'].append(user.get_username())
    logger.info('pré-inscription : %s créé(s), %s déjà là, %s inconnu(s) de l\'annuaire',
                len(report['created']), len(report['existing']), len(report['missing']))
    return report
