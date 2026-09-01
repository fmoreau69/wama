"""
Scénarios nocturnes de DROITS : ce que la décision AUTORISE vs ce que le serveur FAIT.

Demande de Fabien (2026-08-28) : « que les tests nocturnes fassent des tests utilisateurs avec des
droits variés pour détecter si les accès et restrictions sont bien appliqués en fonction de ce qui
est octroyé à chaque utilisateur ». Le modèle d'accès à deux axes (tier + rôles) a été refait en S2
(`wama/accounts/permissions.py`, `PROFILES_PERMISSIONS.md §8`) ; ce module en est la CONTRE-ÉPREUVE.

⚠⚠ CE QU'ON NE MESURE SURTOUT PAS : une matrice d'attendus ÉCRITE À LA MAIN.
    Recopier ici « imager → communication » ne ferait que redire `DEFAULT_APP_ACCESS` dans un
    second fichier : le test serait vert par construction, et le jour où la politique change en
    base (elle est DB-backed, `AppAccessPolicy`) il deviendrait faux sans rien apprendre. C'est la
    faute déjà payée deux fois ce mois-ci — une grille qui atteste une ADOPTION, jamais un
    FONCTIONNEMENT ; un menu et un serveur bâtis sur deux sources qui finissent par diverger.

    On confronte donc DEUX MOITIÉS que rien n'oblige à coïncider, et le défaut vit dans leur
    DÉSACCORD, jamais dans l'une des deux :
      · ATTENDU  = `accessible(user, 'app', app_id)` — la décision, telle qu'elle est CALCULÉE,
                   politique de base comprise ;
      · OBSERVÉ  = une vraie requête HTTP sur le serveur vivant, avec le cookie de session du
                   compte, redirections NON suivies (200 = accès ; 302/403 = refus).
    Un désaccord dit soit qu'un point d'application manque (une app qu'on entre alors que la
    décision la refuse), soit qu'il en fait trop (une app fermée à qui y a droit).

DEUX SCÉNARIOS, parce que les deux natures cassent séparément :
  · `common.rights_matrix`     — les comptes AUTHENTIFIÉS. Doit être vert.
  · `common.rights_anonymous`  — le VISITEUR sans session. Mesuré à part : `AppAccessMiddleware`
                                 ne garde QUE les requêtes authentifiées (c'est écrit dans sa
                                 docstring : l'anonyme est « laissé au `login_required` des
                                 vues »), donc l'anonyme n'est pas une ligne de plus de la même
                                 matrice — c'est une autre couche, avec un autre point
                                 d'application. Les noyer ensemble masquerait la première.

LES COMPTES SONT DES FIXTURES DÉCLARATIVES, jamais un coup de base à la main : même principe que
`get_test_user()`, pour que la mesure soit reproductible sur n'importe quelle base (poste neuf,
worktree de vérification, réinstallation). Ils sont créés sans mot de passe utilisable — on forge
leur session côté serveur, personne ne peut s'y connecter.

⚠ Lecture seule stricte : uniquement des GET, aucun POST, aucun traitement démarré. Le seul écrit
est la création des comptes de test et de leurs sessions — ces dernières sont supprimées à la fin,
par CLÉ (une session authentifiée n'est pas ramassée par `_drop_new_sessions`, qui ne touche que
les anonymes pour ne jamais déconnecter quelqu'un).
"""
from __future__ import annotations

import json as _json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Optional

from django.conf import settings

#: Même source déclarée que `ui_smoke` (`wama_self`) — le défaut ne vit plus dans les deux.
from wama.common.external_sources import base_url as _base_url

BASE_URL = _base_url('wama_self')
TIMEOUT_S = 15

# ── Les profils mesurés ─────────────────────────────────────────────────────
# Choisis pour que la matrice DISCRIMINE : chaque app gardée doit être ouverte à au moins un
# profil et fermée à au moins un autre. Une colonne uniforme ne prouve rien (elle passerait aussi
# bien si la garde était débranchée), et le scénario le VÉRIFIE plutôt que de l'espérer.
#   · `commun`        : le plancher — tier utilisateur, AUCUN rôle. N'ouvre que les apps à `roles`
#                       vide (converter, media_library). C'est le profil qui prouve qu'une garde
#                       ferme vraiment quelque chose.
#   · `communication` : ouvre la production (imager, composer, synthesizer, avatarizer, enhancer).
#   · `recherche`     : ouvre l'analyse (transcriber, describer, reader) + le Lab.
#   · `developpeur`   : tier de BYPASS — doit tout ouvrir, model_manager et jumelles de bac à
#                       sable comprises (elles portent `min_tier: developpeur`). C'est le seul
#                       profil qui éprouve le sens POSITIF sur les apps les plus fermées.
# Pas de compte `admin` : `_app_accessible` traite `admin` et `developpeur` par le même BYPASS
# (`BYPASS_TIERS`) — un second compte mesurerait exactement la même branche.
PROFILS = [
    {'cle': 'commun',        'username': 'wama_rights_commun',
     'tier': 'utilisateur',  'roles': []},
    {'cle': 'communication', 'username': 'wama_rights_communication',
     'tier': 'utilisateur',  'roles': ['communication']},
    {'cle': 'recherche',     'username': 'wama_rights_recherche',
     'tier': 'utilisateur',  'roles': ['recherche']},
    {'cle': 'developpeur',   'username': 'wama_rights_developpeur',
     'tier': 'developpeur',  'roles': []},
]


@dataclass
class Surface:
    """Une URL gardée + la FORME que doit prendre son refus.

    La forme fait partie du contrat : `_deny` du middleware rend un 403 JSON aux appels `/api/`
    et XHR, une redirection vers l'accueil au reste. Un refus de la bonne famille mais de la
    mauvaise forme (une redirection HTML servie à un appelant qui attend du JSON) n'est pas un
    trou de droits, mais c'est un défaut : le JS reçoit une page de login là où il lit un objet.
    On le RELÈVE sans le confondre avec un désaccord d'accès.
    """
    app_id: str
    url: str
    json: bool = False


@dataclass
class Cellule:
    profil: str
    app_id: str
    url: str
    attendu: bool                      # accessible() dit oui ?
    code: Optional[int] = None
    observe: Optional[bool] = None     # le serveur a-t-il laissé entrer ?
    forme: str = ''                    # 'redirection' | 'json-403' | 'html-403' | ''
    note: str = ''                     # rempli quand la réponse n'arbitre rien (5xx, 404…)

    @property
    def decidable(self) -> bool:
        return self.observe is not None

    @property
    def desaccord(self) -> bool:
        return self.decidable and self.observe != self.attendu


# ── Fixtures ────────────────────────────────────────────────────────────────

def ensure_rights_profiles():
    """Crée/aligne les comptes de mesure. Idempotent, déclaratif, sans mot de passe utilisable.

    `groups.set()` est volontaire : après un changement de `PROFILS`, un rôle RETIRÉ ici doit
    disparaître du compte, sinon la fixture dérive silencieusement et le compte « recherche »
    finit par tout ouvrir. On ne touche que les groupes `role:*` — un groupe d'une autre nature
    posé par ailleurs sur ces comptes n'est pas notre affaire.
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Group
    from wama.accounts.models import UserProfile
    from wama.accounts.permissions import GROUP_PREFIX

    User = get_user_model()
    sortie = []
    for spec in PROFILS:
        user, cree = User.objects.get_or_create(
            username=spec['username'],
            defaults={'email': f"{spec['username']}@wama.local",
                      'is_active': True, 'is_staff': False},
        )
        if cree:
            user.set_unusable_password()
            user.save(update_fields=['password'])
        prof, _ = UserProfile.objects.get_or_create(user=user)
        if prof.account_tier != spec['tier']:
            prof.account_tier = spec['tier']
            prof.save(update_fields=['account_tier'])
        voulus = [Group.objects.get_or_create(name=f"{GROUP_PREFIX}{r}")[0] for r in spec['roles']]
        actuels_roles = [g for g in user.groups.all() if g.name.startswith(GROUP_PREFIX)]
        autres = [g for g in user.groups.all() if not g.name.startswith(GROUP_PREFIX)]
        if {g.pk for g in actuels_roles} != {g.pk for g in voulus}:
            user.groups.set(voulus + autres)
        sortie.append({**spec, 'user': user})
    return sortie


# ── Surfaces mesurées ───────────────────────────────────────────────────────

def _namespaces_complets():
    """{namespace feuille: chemin de namespace COMPLET} — parcouru en largeur.

    ⚠ `reverse('cam_analyzer:index')` ne résout PAS : les apps du Lab sont montées sous un
    namespace parent (`wama_lab:cam_analyzer:index`). Le premier passage les a donc rangées en
    « app gardée sans index joignable », ce qui était un constat de l'INSTRUMENT présenté comme
    un constat sur le dépôt. Écrire `wama_lab:` en dur ici referait la faute à l'envers (le
    substrat citerait un monde) : on demande son arborescence au resolver, et n'importe quel
    montage futur suit. Parcours en LARGEUR pour qu'un namespace de surface l'emporte sur un
    homonyme imbriqué.
    """
    from collections import deque
    from django.urls import get_resolver

    trouve, file = {}, deque([(get_resolver(), '')])
    while file:
        resolver, prefixe = file.popleft()
        for ns, (_p, sous) in getattr(resolver, 'namespace_dict', {}).items():
            chemin = f'{prefixe}{ns}'
            trouve.setdefault(ns, chemin)
            file.append((sous, chemin + ':'))
    return trouve


def gated_surfaces():
    """Les URLs gardées, DÉDUITES du modèle d'accès et des URLs — aucune liste en dur.

    Source des apps : `all_gated_apps()` (donc `DEFAULT_APP_ACCESS`, jumelles de bac à sable
    injectées comprises). Source de l'URL : `reverse('<namespace complet>:index')`. Une app
    gardée sans index joignable est SIGNALÉE, pas silencieusement omise — c'est le genre d'écart
    (politique déclarée pour une app qu'aucune URL n'expose) qui vaut d'être vu.
    """
    from django.urls import NoReverseMatch, reverse
    from wama.accounts.permissions import all_gated_apps

    complets = _namespaces_complets()
    surfaces, sans_url = [], []
    for app_id in sorted(all_gated_apps()):
        try:
            surfaces.append(Surface(app_id=app_id,
                                    url=reverse(f'{complets.get(app_id, app_id)}:index')))
        except NoReverseMatch:
            sans_url.append(app_id)

    # Une surface d'API, pour éprouver l'AUTRE branche de `_deny` (403 JSON). Elle est choisie
    # parmi les URLs réellement appelées par les pages : mesuré le 28/08, sept pages d'app
    # appellent `/model-manager/api/models/db/` et sont silencieusement dégradées quand elle
    # refuse. Une app dont on ne mesurerait que l'index laisserait ce refus-là invisible.
    from django.urls import NoReverseMatch as _NRM
    try:
        api = reverse('model_manager:api_models_db')
    except _NRM:
        api = '/model-manager/api/models/db/'
    surfaces.append(Surface(app_id='model_manager', url=api, json=True))
    return surfaces, sans_url


# ── Observation : une vraie requête sur le serveur vivant ───────────────────

class _SansRedirection(urllib.request.HTTPRedirectHandler):
    """Ne SUIT PAS les redirections : une 302 vers l'accueil EST le refus qu'on veut lire.

    ⚠ C'est exactement la faute qui a rendu `<app>.ui` faux pendant des mois : `page.goto` suit
    les redirections et rapporte le statut de la page d'ARRIVÉE — le harnais mesurait la page de
    login en la comptant OK. Ici la redirection est le résultat, pas un détour.
    """
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# ⚠ `ProxyHandler({})` n'est PAS une précaution de style : sans lui, `urllib` lit `http_proxy`
# dans l'environnement et envoie la requête de BOUCLAGE au proxy de l'établissement, qui répond
# 403 (page « HAVP - Unknown Request »). Le premier passage a ainsi rapporté 19 « REFUS INDUS »
# sur des apps parfaitement ouvertes — un instrument qui accuse le code mesuré à sa place. Un
# proxy n'a rien à faire sur 127.0.0.1, et c'est le genre d'aveuglement qui donnerait aussi bien
# des FAUX VERTS le jour où il répondrait 200.
_OPENER = urllib.request.build_opener(_SansRedirection, urllib.request.ProxyHandler({}))


def _observer(url_path: str, session_key: Optional[str], attend_json: bool):
    """(code, forme, corps_court) d'un GET. Ne lève pas : une panne réseau remonte en (None, …)."""
    req = urllib.request.Request(f"{BASE_URL.rstrip('/')}{url_path}", method='GET')
    if attend_json:
        req.add_header('Accept', 'application/json')
        req.add_header('X-Requested-With', 'XMLHttpRequest')
    if session_key:
        req.add_header('Cookie', f'{settings.SESSION_COOKIE_NAME}={session_key}')
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            return r.status, 'ok', ''
    except urllib.error.HTTPError as e:
        corps = ''
        try:
            corps = (e.read() or b'')[:200].decode('utf-8', 'replace')
        except Exception:
            pass
        if e.code in (301, 302, 303, 307, 308):
            return e.code, f"redirection→{e.headers.get('Location', '?')}", corps
        if e.code == 403:
            est_json = 'application/json' in (e.headers.get('Content-Type') or '')
            if not est_json:
                try:
                    _json.loads(corps)
                    est_json = True
                except Exception:
                    est_json = False
            return 403, 'json-403' if est_json else 'html-403', corps
        return e.code, f'http-{e.code}', corps
    except Exception as e:
        return None, f'{type(e).__name__}: {str(e)[:120]}', ''


def _lire_verdict(cell: Cellule, code, forme, surface: Surface):
    """Traduit une réponse en ACCÈS / REFUS, ou en « n'arbitre rien » (et le dit)."""
    cell.code, cell.forme = code, forme
    if code == 200:
        cell.observe = True
    elif code in (301, 302, 303, 307, 308) or code == 403:
        cell.observe = False
    elif code is None:
        cell.note = f'serveur injoignable ({forme})'
    else:
        # 404, 5xx… : la page n'a pas rendu de décision de droits. Le dire vaut mieux que de
        # compter un 500 comme un refus — ce serait un vert obtenu par une panne.
        cell.note = f"réponse {code} — n'arbitre aucun droit"
    return cell


# ── Sessions forgées (et retirées) ──────────────────────────────────────────

def _forger_session(user) -> str:
    from importlib import import_module
    SessionStore = import_module(settings.SESSION_ENGINE).SessionStore
    s = SessionStore()
    s['_auth_user_id'] = str(user.pk)
    s['_auth_user_backend'] = 'django.contrib.auth.backends.ModelBackend'
    s['_auth_user_hash'] = user.get_session_auth_hash()
    s.create()
    return s.session_key


def _retirer_sessions(cles):
    """Supprime NOS sessions, par clé. `_drop_new_sessions` ne le ferait pas : il épargne
    délibérément toute session portant `_auth_user_id` pour ne jamais déconnecter un vrai
    utilisateur — les nôtres en portent une, c'est à nous de les reprendre."""
    if not cles:
        return 0
    try:
        from django.contrib.sessions.models import Session
        return Session.objects.filter(session_key__in=list(cles)).delete()[0]
    except Exception:
        return 0


# ── Scénario 1 : la matrice des comptes authentifiés ────────────────────────

def run_rights_matrix(ctx):
    from wama.accounts.permissions import accessible
    from wama.common.services.nightly_tests import SkipScenario

    profils = ensure_rights_profiles()
    surfaces, sans_url = gated_surfaces()
    if not surfaces:
        raise SkipScenario('aucune app gardée n’expose d’index joignable')

    cellules, cles = [], []
    try:
        for p in profils:
            cle = _forger_session(p['user'])
            cles.append(cle)
            for s in surfaces:
                c = Cellule(profil=p['cle'], app_id=s.app_id, url=s.url,
                            attendu=accessible(p['user'], 'app', s.app_id))
                code, forme, _ = _observer(s.url, cle, s.json)
                cellules.append(_lire_verdict(c, code, forme, s))
    finally:
        _retirer_sessions(cles)

    decidables = [c for c in cellules if c.decidable]
    if not decidables:
        raise SkipScenario(
            'aucune cellule décidable — serveur injoignable ? '
            f'({cellules[0].note if cellules else "?"})')

    # ── La matrice DISCRIMINE-t-elle ? ──────────────────────────────────────
    # Une colonne où tous les profils sont attendus PASSANTS ne prouve rien : elle serait verte
    # même si la garde était débranchée. On compte les colonnes qui portent les deux verdicts —
    # c'est la force de la mesure, et elle se dit AVEC le résultat, jamais à côté.
    par_app = {}
    for c in decidables:
        par_app.setdefault(c.app_id, set()).add(c.attendu)
    discriminantes = [a for a, v in par_app.items() if v == {True, False}]
    uniformes = sorted(a for a in par_app if a not in discriminantes)

    desaccords = [c for c in decidables if c.desaccord]
    formes = [c for c in decidables if c.observe is False and (
        (c.forme.startswith('redirection') and _est_api(c, surfaces))
        or c.forme == 'html-403')]
    indecidables = [c for c in cellules if not c.decidable]

    lignes = [
        f"{len(decidables)} couples (compte × surface) mesurés sur {len(profils)} comptes "
        f"et {len(surfaces)} surfaces ; {len(discriminantes)}/{len(par_app)} apps DISCRIMINANTES "
        f"(ouvertes à un profil, fermées à un autre)",
    ]
    if uniformes:
        # Nommer les colonnes uniformes, sinon le ratio se lit comme un défaut. Une app COMMUNE
        # (`roles` vide) est ouverte aux quatre profils par construction : sa colonne ne peut pas
        # discriminer, et c'est la politique, pas un trou.
        lignes.append("apps au verdict uniforme sur les 4 profils (donc non discriminantes) : "
                      + ', '.join(uniformes))
    if sans_url:
        lignes.append("apps gardées sans index joignable (politique déclarée, aucune surface) : "
                      + ', '.join(sans_url))
    # Dire que la branche JSON a été EXERCÉE, pas seulement qu'elle n'a rien cassé. Une surface
    # d'API que tous les profils traverseraient laisserait `_deny`/JSON non mesuré, et le
    # scénario se dirait fort sans l'être.
    api_refus = [c for c in decidables if _est_api(c, surfaces) and c.observe is False]
    lignes.append(
        f"branche JSON de `_deny` : {sum(1 for c in api_refus if c.forme == 'json-403')} refus "
        f"403-JSON sur {len(api_refus)} refus d'API"
        if api_refus else
        "⚠ branche JSON de `_deny` NON exercée — aucun profil ne s'est vu refuser la surface d'API")
    if indecidables:
        lignes.append(f"{len(indecidables)} cellules n'arbitrent rien : "
                      + '; '.join(f"{c.profil}→{c.app_id} {c.note}" for c in indecidables[:4]))
    if formes:
        lignes.append("⚠ refus de la mauvaise FORME (le refus est juste, sa réponse ne l'est "
                      "pas) : " + '; '.join(f"{c.profil}→{c.url} {c.forme}" for c in formes[:4]))

    if desaccords:
        trop = [c for c in desaccords if c.observe and not c.attendu]
        pas_assez = [c for c in desaccords if c.attendu and not c.observe]
        if trop:
            lignes.append(f"❌ {len(trop)} ACCÈS NON DÛS (la décision refuse, le serveur laisse "
                          "entrer) : " + '; '.join(f"{c.profil}→{c.url} ({c.code})" for c in trop[:8]))
        if pas_assez:
            lignes.append(f"❌ {len(pas_assez)} REFUS INDUS (la décision autorise, le serveur "
                          "ferme) : " + '; '.join(f"{c.profil}→{c.url} ({c.code} {c.forme})"
                                                  for c in pas_assez[:8]))
        return False, ' | '.join(lignes)

    if not discriminantes:
        # Vert sans pouvoir discriminer = une mesure faible qui se dirait forte (leçon du 27/08).
        raise SkipScenario('aucune app ne sépare deux profils — la matrice ne prouverait rien : '
                           + ' | '.join(lignes))
    return True, 'accord complet décision↔serveur — ' + ' | '.join(lignes)


def _est_api(cell: Cellule, surfaces) -> bool:
    return any(s.url == cell.url and s.json for s in surfaces)


# ── Scénario 2 : le visiteur anonyme ────────────────────────────────────────

def _jeton_csrf():
    """(valeur du cookie csrftoken, ou None) — obtenu comme un navigateur : un GET sur une
    page publique qui pose le cookie. Sans lui, tout POST anonyme mourrait en 403 CSRF —
    c'est-à-dire AVANT les gardes qu'on veut mesurer : l'instrument rendrait un « refus »
    qui ne prouverait rien sur les droits."""
    req = urllib.request.Request(f"{BASE_URL.rstrip('/')}/converter/", method='GET')
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            en_tetes = r.headers.get_all('Set-Cookie') or []
    except urllib.error.HTTPError as e:
        en_tetes = e.headers.get_all('Set-Cookie') or []
    except Exception:
        return None
    for c in en_tetes:
        if c.startswith('csrftoken='):
            return c.split(';', 1)[0].split('=', 1)[1]
    return None


def _poster_vide(url_path: str, csrftoken):
    """(code, forme) d'un POST SANS CORPS ni session — la sonde mutante qui ne mute pas :
    une vue d'upload ATTEINTE répond « aucun fichier » (400), une vue GARDÉE redirige/403
    avant de lire quoi que ce soit. Aucune donnée n'est fournie, rien ne peut être créé."""
    req = urllib.request.Request(f"{BASE_URL.rstrip('/')}{url_path}", data=b'', method='POST')
    req.add_header('Accept', 'application/json')
    req.add_header('X-Requested-With', 'XMLHttpRequest')
    if csrftoken:
        req.add_header('Cookie', f'csrftoken={csrftoken}')
        req.add_header('X-CSRFToken', csrftoken)
    try:
        with _OPENER.open(req, timeout=TIMEOUT_S) as r:
            return r.status, 'ok'
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            return e.code, f"redirection→{e.headers.get('Location', '?')}"
        return e.code, f'http-{e.code}'
    except Exception as e:
        return None, f'{type(e).__name__}: {str(e)[:120]}'


def run_rights_anonymous(ctx):
    """Le VISITEUR, mesuré sur les ACTIONS — recalé le 2026-09-02 sur la décision de Fabien.

    ⚠ HISTORIQUE, pour ne pas dé-recaler : la V1 mesurait les INDEX et les trouvait
    « ouverts » — mais c'est la POLITIQUE (« visiteur GUIDÉ », tranché le 30/08 : les pages
    se VOIENT, ce sont les GESTES qui se gardent — `WAMA_VERIFICATION §3`,
    `PROFILES_PERMISSIONS §1.4`). Une V2 au GET sur les routes `@require_POST` a été
    RÉFUTÉE à sa première contre-vérification : `@require_POST` est posé DEVANT la garde
    d'accès, donc son 405 répond à tout GET — gardé ou pas, il ne discrimine rien.

    MESURE (V3) — le CONTRAT de la décision, tel quel : un **POST anonyme à VIDE** sur la
    route mutante universelle (`upload`), muni d'un jeton CSRF réel (sinon le 403 CSRF
    tombe AVANT les gardes et le refus ne prouve rien). Aucune donnée fournie → rien ne
    peut être créé ; une ceinture ORM le VÉRIFIE (aucun compteur d'objets ne doit bouger).
      · 302 → login / 403 : l'action est GARDÉE ;
      · toute autre réponse (400 « aucun fichier », 200…) : la vue a été ATTEINTE — un
        visiteur muni d'un vrai fichier AGIRAIT.
    Attendu de la décision : refusé PARTOUT **sauf le converter** (app d'essai sans GPU) —
    l'exception est mesurée dans les DEUX sens : un converter gardé serait aussi un écart.
    ⚠ La garde serveur s'exécute avec le chantier avatar/accueil (APRÈS portage) : ce
    scénario code le contrat CIBLE et reste rouge d'ici là — rouge ASSUMÉ, documenté
    (`PROJECT_STATUS` : « l'échec attendu tant que la garde n'est pas construite »).
    """
    from django.urls import NoReverseMatch, reverse
    from wama.accounts.permissions import all_gated_apps
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.utils.preview_registry import PreviewRegistry

    complets = _namespaces_complets()
    cibles = []
    for app_id in sorted(all_gated_apps()):
        try:
            cibles.append((app_id, reverse(f'{complets.get(app_id, app_id)}:upload')))
        except NoReverseMatch:
            continue              # pas de route upload (model_manager, studio…) : hors contrat
    if not cibles:
        raise SkipScenario("aucune route d'upload résolue — instrument aveugle")

    jeton = _jeton_csrf()
    if jeton is None:
        raise SkipScenario('impossible d’obtenir un jeton CSRF — serveur injoignable ?')

    # Ceinture d'instrument : un POST à vide ne doit RIEN créer. Compter avant/après —
    # si un objet naissait quand même, le supprimer et le DIRE (jamais en silence).
    def _compte(app_id):
        try:
            m = PreviewRegistry.get_model(app_id)
            return m, set(m.objects.values_list('id', flat=True))
        except Exception:
            return None, set()
    avant = {app_id: _compte(app_id) for app_id, _ in cibles}

    atteintes, refusees, injoignables = [], [], []
    for app_id, url in cibles:
        code, forme = _poster_vide(url, jeton)
        if code is None:
            injoignables.append(f'{app_id} ({forme})')
        elif code in (301, 302, 303, 307, 308) or code == 403:
            refusees.append(app_id)
        else:
            atteintes.append(f'{app_id} ({code})')

    fuites = []
    for app_id, (modele, ids) in avant.items():
        if modele is None:
            continue
        nouveaux = set(modele.objects.values_list('id', flat=True)) - ids
        if nouveaux:
            modele.objects.filter(id__in=nouveaux).delete()
            fuites.append(f'{app_id}: {len(nouveaux)} objet(s) créé(s) par la sonde À VIDE — supprimés')

    if injoignables and not atteintes and not refusees:
        raise SkipScenario('serveur injoignable — ' + '; '.join(injoignables[:3]))

    # Le CONTRAT dans les deux sens : hors converter tout doit refuser, et le converter
    # (app d'essai de la décision) doit rester atteignable.
    apps_atteintes = {a.split(' ')[0] for a in atteintes}
    ecarts = sorted(apps_atteintes - {'converter'})
    converter_garde = 'converter' in refusees
    base = (f"{len(cibles)} routes d'upload sondées par POST anonyme À VIDE (jeton CSRF réel, "
            f"aucune donnée → aucune mutation possible) : {len(refusees)} refus")
    if fuites:
        base += ' ; ⚠ CEINTURE : ' + '; '.join(fuites)
    if injoignables:
        base += f" ; {len(injoignables)} injoignables"

    if ecarts or converter_garde:
        morceaux = []
        if ecarts:
            morceaux.append(f"{len(ecarts)} apps où un visiteur POURRAIT AGIR (contrat : "
                            "refus partout sauf converter) : " + ', '.join(
                                a for a in atteintes if a.split(' ')[0] != 'converter')[:400])
        if converter_garde:
            morceaux.append("le CONVERTER refuse le visiteur — l'app d'essai de la décision "
                            "n'est plus une exception")
        return False, f"❌ {base} — " + ' | '.join(morceaux) + \
            " (garde serveur planifiée avec le chantier avatar/accueil — rouge attendu d'ici là)"
    return True, base + " — contrat « visiteur guidé » TENU : refus partout, converter seul ouvert"


# ── Enregistrement ──────────────────────────────────────────────────────────

def register_rights_scenarios() -> None:
    from wama.common.services.nightly_tests import register

    register(id='common.rights_matrix', app='common', stage='ui', timeout_s=300,
             description="Droits — accord entre la DÉCISION (accessible()) et le SERVEUR, "
                         "sur 4 comptes de droits variés × toutes les apps gardées",
             run=run_rights_matrix)
    register(id='common.rights_anonymous', app='common', stage='ui', timeout_s=180,
             description="Droits — un visiteur sans session ne peut AGIR nulle part (les pages "
                         "se voient — politique « visiteur guidé » —, les gestes se gardent)",
             run=run_rights_anonymous)
