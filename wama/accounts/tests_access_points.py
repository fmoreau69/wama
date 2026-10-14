"""Verrouille les POINTS D'APPLICATION du contrôle d'accès (S2, PROFILES_PERMISSIONS §8.9).

Ce que S1 avait prouvé, c'est que la DÉCISION est unique. Ce fichier prouve autre chose, et c'est
la leçon de S2 : **une décision unique ne garde rien tant qu'elle n'est pas APPLIQUÉE**. Les deux
défauts mesurés le 27/08 étaient tous les deux de cette famille, et tous les deux MUETS :

  1. `model_manager` était déclaré dans `DEFAULT_APP_ACCESS` mais monté sur `/model-manager/` : le
     middleware résout l'app_id par le 1er segment d'URL, et « model-manager » (tiret) n'est pas
     « model_manager » (souligné). La politique existait, personne ne la lisait.
  2. Ses 52 vues étaient gardées par un SECOND barème (`is_superuser | is_staff | Groups
     'admin'/'dev'`), hérité de la migration `accounts/0002`, antérieur aux tiers et ignorant
     `UserProfile.account_tier`.

Aucun des deux ne se serait vu à l'exécution : une politique jamais lue et un second barème qui
dit « oui » plus souvent que le premier ne lèvent aucune exception. D'où des tests de PROPRIÉTÉ,
qui portent sur l'ensemble des surfaces gardées et pas sur un cas relu à la main.
"""
import json

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from wama.accounts.models import UserProfile
from wama.accounts.permissions import (
    DEFAULT_APP_ACCESS, GROUP_PREFIX, KIND_DECISION, ROLES,
    accessible, all_gated_apps, app_id_for_path,
)


def _urls_des_surfaces_gardees():
    """`{app_id: url_name}` pour TOUT ce qui est soumis au contrôle d'accès.

    Deux gisements, parce que WAMA a deux natures de surface (cf. §8.8.1) : les cards
    d'`APP_CATALOG` (apps génériques de traitement de fichiers) et les surfaces déclarées hors
    catalogue (`register_surface` : studio, médiathèque, model_manager, Lab), dont la clé `gate`
    est l'identifiant d'app."""
    from wama.common.app_registry import APP_CATALOG, surfaces
    urls = {}
    for app_id, spec in APP_CATALOG.items():
        if spec.get('url_name'):
            urls[app_id] = spec['url_name']
    for lien in surfaces():
        urls.setdefault(lien['gate'], lien['url_name'])
    return urls


class PointDApplicationTests(TestCase):
    """Le middleware voit-il RÉELLEMENT chaque surface qu'une politique prétend garder ?"""

    def test_chaque_app_gardee_est_resolue_depuis_son_url_montee(self):
        # 🔴 LA propriété qui a manqué : `app_id_for_path()` doit retrouver l'app_id depuis
        # l'URL RÉELLEMENT montée. Un préfixe d'URL qui diffère de l'app_id (tiret vs souligné,
        # ou montage sous un parent comme `/lab/…`) rend la politique inapplicable EN SILENCE.
        urls = _urls_des_surfaces_gardees()
        self.assertTrue(urls, "aucune surface relevée : le test ne mesurerait rien")
        muettes = {}
        for app_id in sorted(all_gated_apps()):
            url_name = urls.get(app_id)
            if not url_name:
                continue  # couvert par tests_subscriptions (toute app gardée a une surface)
            resolu = app_id_for_path(reverse(url_name))
            if resolu != app_id:
                muettes[app_id] = (reverse(url_name), resolu)
        self.assertEqual(
            muettes, {},
            "politique déclarée mais JAMAIS appliquée par le middleware "
            "(app_id → url montée, app_id résolu) : "
            f"{muettes}. Ajouter le préfixe à PATH_APP_MAP.")

    def test_la_PAGE_du_model_manager_reste_gardee_malgre_l_exemption_de_ses_api(self):
        """L'exemption du substrat ne doit JAMAIS déborder sur les pages.

        `ROUTES_SUBSTRAT` ouvre `/model-manager/api/…` pour que l'UI des autres apps puisse
        lire le catalogue. La PAGE, elle, reste la surface de l'app — c'est exactement la
        frontière posée par Fabien (« seul l'accès au template doit être restreint »). Une
        exemption qui grignoterait la page rendrait la politique du model_manager décorative,
        sans que rien ne le signale.
        """
        # Depuis le 2026-10-13 le model manager est une page des REGISTRES : il se lit sous leur
        # droit — la page reste GARDÉE, c'est la propriété que ce test tient.
        self.assertEqual(app_id_for_path('/model-manager/'), 'registries')
        self.assertEqual(app_id_for_path('/model-manager/libraries/'), 'registries')
        self.assertEqual(app_id_for_path('/model-manager/functions/'), 'registries')
        # Les deux lectures dont dépend l'UI des autres apps : plus gardées par l'app.
        self.assertIsNone(app_id_for_path('/model-manager/api/models/db/'))
        self.assertIsNone(app_id_for_path('/model-manager/api/models/options/'))

    def test_aucune_route_API_qui_MUTE_ne_tient_par_la_seule_garde_d_app(self):
        """La condition de SÛRETÉ de `ROUTES_SUBSTRAT`, vérifiée mécaniquement.

        Exempter un préfixe API de la garde d'app n'est sûr QUE si chaque route mutante
        derrière lui porte sa propre garde (défense en profondeur). Mesuré à la main le
        2026-09-01 : 53 routes, 0 défaut. Ce test empêche qu'une route ajoutée demain,
        protégée par le seul gating d'app, se retrouve ouverte SANS QUE PERSONNE NE LE VOIE —
        c'est-à-dire la panne muette que l'exemption pourrait introduire à retard.
        """
        import inspect

        from wama.model_manager import urls as mm_urls, views as mm_views

        source = inspect.getsource(mm_views)
        nues = []
        for p in mm_urls.urlpatterns:
            motif = str(p.pattern)
            if not motif.startswith('api/'):
                continue
            nom_vue = getattr(p.callback, '__name__', '')
            idx = source.find(f"def {nom_vue}(")
            if idx <= 0:
                continue
            entete = source[max(0, idx - 400):idx]
            fin = source.find('\ndef ', idx + 1)
            corps = source[idx:fin if fin > 0 else None]
            mute = 'require_POST' in entete
            # Garde de RÔLE (décorateur) ou garde d'OBJET dans le corps : `owned_or_404`, la règle
            # commune des mutations (`scoping`) — une route qu'un utilisateur ordinaire doit
            # pouvoir appeler sur SES éléments (accord de libération VRAM, 2026-09-27).
            garde = ('is_admin_or_dev' in entete or 'user_passes_test' in entete
                     or 'staff_member_required' in entete or 'owned_or_404(' in corps)
            if mute and not garde:
                nues.append(motif)
        self.assertEqual(
            nues, [],
            "route(s) API MUTANTES sans garde propre, alors que `ROUTES_SUBSTRAT` exempte "
            f"leur préfixe de la garde d'app : {nues}. Leur poser un `is_admin_or_dev`, "
            "ou retirer l'exemption.")

    def test_toute_surface_gardee_a_bien_une_url_reversible(self):
        # Garde d'instrument : si un `url_name` cassait, le test précédent passerait en
        # n'examinant plus rien.
        from wama.common.app_registry import pageless_tools
        urls = _urls_des_surfaces_gardees()
        pageless = {t['gate'] for t in pageless_tools()}
        manquantes = sorted(all_gated_apps() - set(urls) - pageless)
        self.assertEqual(manquantes, [],
                         f"surfaces gardées sans url_name relevable : {manquantes}")

    def test_every_pageless_tool_is_guarded_on_its_own_routes(self):
        """A tool WITHOUT a page (2026-10-13) has no URL name to resolve: its declared probe — a
        real route of the tool — must resolve to the tool through the ONE path table
        (`app_id_for_path`: first segment, else `PATH_APP_MAP`)."""
        from wama.common.app_registry import pageless_tools
        tools = [t for t in pageless_tools() if t['gate'] in all_gated_apps()]
        self.assertTrue(tools, 'no pageless tool: the test would measure nothing')
        for tool in tools:
            self.assertEqual(tool['gate'], app_id_for_path(tool['probe']),
                             f"{tool['app']}: {tool['probe']} escapes the middleware")
        self.assertEqual('assistant', app_id_for_path(reverse('ai_chat_stream')))


class FamillesDElementsTests(TestCase):
    """La signature généralisée `accessible(user, kind, element_id)` (§8.2)."""

    def test_une_famille_inconnue_leve_au_lieu_d_autoriser(self):
        # Le défaut qu'on refuse : une faute de frappe qui AUTORISE. Un `kind` hors table doit
        # casser bruyamment, pas laisser passer.
        u = User.objects.create_user('kind_test', password='x')
        with self.assertRaises(ValueError):
            accessible(u, 'aap', 'imager')

    def test_une_famille_non_encore_gardee_le_DECLARE(self):
        # Elle renvoie True — mais parce que c'est écrit dans KIND_DECISION, pas par omission.
        u = User.objects.create_user('kind_test2', password='x')
        non_gardees = [k for k, d in KIND_DECISION.items() if d != 'ici']
        self.assertTrue(non_gardees, "aucune famille non gardée : le test ne mesurerait rien")
        for kind in non_gardees:
            self.assertTrue(accessible(u, kind, 'peu-importe'),
                            f"la famille {kind!r} est déclarée non gardée ici")

    def test_les_natures_abonnables_sont_des_familles_connues_du_droit(self):
        # On ne veut pas d'une PRÉFÉRENCE sur une famille dont le DROIT ignore l'existence : les
        # deux tables partagent le vocabulaire, elles doivent partager la réalité.
        from wama.common.services.subscriptions import KINDS
        inconnues = sorted(set(KINDS) - set(KIND_DECISION))
        self.assertEqual(inconnues, [],
                         f"natures abonnables absentes de KIND_DECISION : {inconnues}")


class ModelManagerGardeUniqueTests(TestCase):
    """`is_admin_or_dev` était un second barème : il doit désormais dire la MÊME chose.

    Depuis le 2026-10-13 la chose qu'il dit est la règle unique de GESTION des registres
    (`can_manage_registries`) : le model manager est un registre, le lire est ouvert à tout
    compte, le gérer reste au profil développeur."""

    def setUp(self):
        for k in ROLES:
            Group.objects.get_or_create(name=GROUP_PREFIX + k)

    def _compte(self, nom, tier, roles=()):
        u = User.objects.create_user(nom, password='x')
        UserProfile.objects.update_or_create(user=u, defaults={'account_tier': tier})
        u.groups.add(*[Group.objects.get(name=GROUP_PREFIX + r) for r in roles])
        return User.objects.get(pk=u.pk)

    def test_le_decorateur_dit_exactement_ce_que_dit_la_politique(self):
        from wama.model_manager.views import is_admin_or_dev
        cas = [
            self._compte('mm_dev', 'developpeur'),
            self._compte('mm_user', 'utilisateur', ['ingenierie']),
            self._compte('mm_nu', 'utilisateur'),
        ]
        from wama.accounts.permissions import can_manage_registries
        for u in cas:
            self.assertEqual(
                bool(is_admin_or_dev(u)), can_manage_registries(u),
                f"{u.username} : le décorateur et la règle de gestion des registres divergent")

    def test_un_group_herite_dev_n_ouvre_plus_rien_par_lui_meme(self):
        # Le barème retiré. Les Groups 'admin'/'dev' de la migration accounts/0002 sont
        # ANTÉRIEURS aux tiers : les laisser décider, c'était maintenir deux échelles qui ne
        # restent d'accord que par chance.
        from wama.model_manager.views import is_admin_or_dev
        u = self._compte('mm_legacy', 'utilisateur', ['ingenierie'])
        u.groups.add(Group.objects.get_or_create(name='dev')[0])
        u = User.objects.get(pk=u.pk)
        self.assertFalse(is_admin_or_dev(u),
                         "le Group hérité 'dev' ne doit plus être un axe d'accès")

    def test_le_tier_developpeur_declare_ouvre_bien_le_model_manager(self):
        # La contre-épreuve : sans elle, « tout est fermé » passerait le test précédent.
        from wama.model_manager.views import is_admin_or_dev
        self.assertTrue(is_admin_or_dev(self._compte('mm_dev2', 'developpeur')))
        self.assertFalse(is_admin_or_dev(self._compte('mm_user2', 'utilisateur', ['ingenierie'])))


class LeContexteNeMasquePasLeBaremeTests(TestCase):
    """
    Un SECOND BARÈME peut aussi arriver par le CONTEXTE DE GABARIT — la variante qui a
    échappé au balayage du 27/08, parce qu'aucun `is_staff` n'apparaissait dans une garde.

    Mesuré le 2026-08-31 : `views.home` reposait `is_admin` avec `request.user.is_staff`,
    or le context processor `user_role` le fournit déjà à TOUTES les pages avec le prédicat
    canonique — et le contexte d'une vue écrase celui d'un processor. Le menu
    « Users »/« Models » de `header.html` (inclus par `base.html`, donc rendu partout)
    suivait donc une règle sur `/` et une autre ailleurs. Aucune exception, aucun log : la
    panne muette habituelle.

    Le compte qui révèle l'écart est celui qui est `is_staff` SANS être superutilisateur ni
    membre du groupe `admin` — les deux barèmes ne se contredisent que là.
    """

    def test_is_admin_vaut_le_predicat_canonique_sur_l_accueil(self):
        from wama.accounts.views import is_admin as predicat
        user = User.objects.create_user('staff_non_admin', password='x', is_staff=True)
        self.client.force_login(user)
        contexte = self.client.get('/').context
        self.assertFalse(predicat(user), "prémisse : ce compte n'est PAS admin au sens WAMA")
        self.assertEqual(contexte['is_admin'], predicat(user),
                         "l'accueil réintroduit un second barème (is_staff) pour is_admin")

    def test_le_menu_admin_est_le_meme_sur_l_accueil_et_ailleurs(self):
        """La propriété qui compte pour l'utilisateur : le même menu, où qu'il soit."""
        user = User.objects.create_user('staff_non_admin2', password='x', is_staff=True)
        self.client.force_login(user)
        accueil = self.client.get('/').content.decode()
        ailleurs = self.client.get(reverse('accounts:profile')).content.decode()
        cible = reverse('accounts:user-management')
        self.assertEqual(cible in accueil, cible in ailleurs,
                         "le menu admin diverge entre l'accueil et le reste du site")


class VisitorActionGuardTests(TestCase):
    """Le VISITEUR sans session voit les pages et ne peut rien FAIRE (garde du 2026-10-03).

    Mesuré avant sur le serveur en service : une requête sans session créait et LANÇAIT un job
    d'avatar sous le compte `anonymous`, et 9 vues d'ajout étaient atteintes
    (`common.rights_anonymous`). La décision (30/08) est une PROPRIÉTÉ de toutes les apps
    gardées, donc le test porte sur toutes — y compris celle qu'on ajoutera demain.
    """

    def _index_urls(self):
        urls = _urls_des_surfaces_gardees()
        return {app_id: reverse(urls[app_id]) for app_id in sorted(all_gated_apps()) if urls.get(app_id)}

    def test_a_visitor_cannot_act_on_any_gated_app(self):
        # Hors apps déclarées PUBLIQUES (le converter depuis le 2026-10-04) : le visiteur y agit
        # sous une identité de session — `tests_visitors`. Tout le reste doit refuser.
        from django.contrib.auth.models import AnonymousUser
        targets = {app_id: url for app_id, url in self._index_urls().items()
                   if not accessible(AnonymousUser(), 'app', app_id)}
        self.assertGreaterEqual(len(targets), 10, 'trop peu de surfaces : le test ne mesurerait rien')
        reached = {}
        for app_id, url in targets.items():
            for method in ('post', 'put', 'patch', 'delete'):
                response = getattr(self.client, method)(url)
                if response.status_code != 403:
                    reached[f'{app_id} {method.upper()}'] = response.status_code
        self.assertEqual({}, reached, 'un visiteur sans session atteint ces vues')

    def test_the_refusal_tells_the_visitor_to_log_in(self):
        response = self.client.post(reverse('avatarizer:create'), {'text_content': 'bonjour'})
        self.assertEqual(403, response.status_code)
        body = response.json()
        self.assertTrue(body['login_required'])
        self.assertIn('Connectez-vous', body['error'])

    def test_a_visitor_post_creates_nothing(self):
        from wama.avatarizer.models import AvatarJob
        before = AvatarJob.objects.count()
        self.client.post(reverse('avatarizer:create'), {'text_content': 'bonjour'})
        self.client.post(reverse('avatarizer:start', args=[1]))
        self.assertEqual(before, AvatarJob.objects.count())

    def test_pages_stay_visible_to_a_visitor(self):
        """Contre-épreuve : la garde ne ferme pas les PAGES (visiteur guidé) — un GET n'est
        jamais refusé par elle (200, ou la redirection de connexion propre à une vue)."""
        # Une page qui tombe pour une AUTRE raison (base de test en retard d'une migration de
        # jumelle…) n'est pas l'objet de ce test : seul un 403 de la garde le ferait échouer.
        from django.test import Client
        from wama.accounts.middleware import VISITOR_CLOSED_PREFIXES
        visitor = Client(raise_request_exception=False)
        # Sauf les pages FERMÉES au visiteur par décision, lecture comprise (les Registres,
        # 2026-10-13) : celles-là sont tenues par `RegistriesAccessTests`.
        refused = {app_id: visitor.get(url).status_code
                   for app_id, url in self._index_urls().items()
                   if not url.startswith(VISITOR_CLOSED_PREFIXES)}
        self.assertEqual({}, {a: c for a, c in refused.items() if c == 403})

    def test_an_app_declared_public_lets_the_visitor_through_the_guard(self):
        """L'exception se DÉCLARE (`AppAccessPolicy.public`) : la garde lit la même décision
        que le reste. Ce que la vue fait ensuite du visiteur est son affaire."""
        from wama.accounts.models import AppAccessPolicy
        AppAccessPolicy.objects.update_or_create(app_id='converter', defaults={'public': True})
        response = self.client.post(reverse('converter:upload'))
        self.assertNotEqual(403, response.status_code)
        # Et une app voisine reste fermée : l'exception ne déborde pas.
        self.assertEqual(403, self.client.post(reverse('avatarizer:create')).status_code)

    def test_a_logged_in_account_is_not_caught_by_the_visitor_guard(self):
        user = User.objects.create_user('guard_member', password='x')
        for role in (DEFAULT_APP_ACCESS.get('avatarizer') or {}).get('roles', []):
            user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(user)
        response = self.client.post(reverse('avatarizer:create'), {})
        self.assertNotEqual(403, response.status_code)       # la vue répond (400 : rien fourni)


class VisitorFileManagerClosedTests(TestCase):
    """2026-10-12: the file manager is closed to a visitor, reads included. Measured before:
    without a session every route fell back on the SHARED `anonymous` account — one tree that
    every visitor could read, fill and empty, an import into ten apps outside the app guard, and
    the mounting of ANY local server folder, then downloadable by everyone."""

    @staticmethod
    def _routes():
        """Every file-manager route, as a concrete path — tomorrow's route included."""
        import re
        from wama.filemanager.urls import urlpatterns
        paths = []
        for pattern in urlpatterns:
            raw = str(pattern.pattern).lstrip('^').rstrip('$')
            raw = re.sub(r'<int:\w+>|\(\?P<pk>\\d\+\)', '1', raw)
            raw = re.sub(r'<str:\w+>|\(\?P<path>\.[+*]\)', 'x.txt', raw)
            paths.append('/filemanager/' + raw)
        return paths

    def test_no_file_manager_route_serves_a_visitor(self):
        routes = self._routes()
        self.assertGreaterEqual(len(routes), 20, 'too few routes: the test would measure nothing')
        reached = {f'{method.upper()} {url}': code
                   for url in routes for method in ('get', 'post')
                   for code in [getattr(self.client, method)(url).status_code] if code != 403}
        self.assertEqual({}, reached, 'a visitor without a session reaches these routes')

    def test_a_visitor_cannot_mount_a_server_folder(self):
        from wama.filemanager.models import MountedFolder
        before = MountedFolder.objects.count()
        response = self.client.post('/filemanager/api/mounts/',
                                    json.dumps({'name': 'x', 'local_path': '/'}),
                                    content_type='application/json')
        self.assertEqual(403, response.status_code)
        self.assertTrue(response.json()['login_required'])
        self.assertEqual(before, MountedFolder.objects.count())

    def test_a_session_visitor_identity_is_refused_too(self):
        from wama.accounts.permissions import VISITOR_ACCOUNT_PREFIX
        self.client.force_login(User.objects.create_user(f'{VISITOR_ACCOUNT_PREFIX}t', password='x'))
        self.assertEqual(403, self.client.get('/filemanager/api/tree/').status_code)

    def test_a_member_still_reaches_the_file_manager_and_sees_the_tree(self):
        """Counter-test: only the visitor is closed out."""
        self.assertNotIn('id="filemanager-tree"', self.client.get('/').content.decode())
        self.client.force_login(User.objects.create_user('fm_member', password='x'))
        self.assertNotEqual(403, self.client.get('/filemanager/api/tree/').status_code)
        self.assertIn('id="filemanager-tree"', self.client.get('/').content.decode())


class RegistriesAccessTests(TestCase):
    """2026-10-13 (Fabien's decision): the Registries enter the access policy as a common
    transversal tool. They had no guard at all: every account reads them, a visitor never does,
    and only a developer refreshes a registry an account may refresh."""

    def _account(self, name, tier):
        user = User.objects.create_user(name, password='x')
        UserProfile.objects.update_or_create(user=user, defaults={'account_tier': tier})
        return User.objects.get(pk=user.pk)

    @staticmethod
    def _shared_registry():
        """A registry whose refresh is open beyond the staff, and cheap to run in a test."""
        from wama.common.registries import DERIVED, REGISTRIES
        return next(r.key for r in REGISTRIES.values() if r.permission == 'auth' and r.nature == DERIVED)

    def test_the_registries_are_a_gated_column_of_the_transversal_world(self):
        from wama.accounts.permissions import access_cases, app_id_for_path
        columns = {a['id']: a for a in access_cases()['apps']}
        self.assertIn('registries', columns, 'the registries are missing from the access scene')
        self.assertEqual('transverse', columns['registries']['world'])
        self.assertEqual('registries', app_id_for_path('/common/registries/'))
        self.assertEqual('registries', app_id_for_path('/common/api/registres/apps/refresh/'))

    def test_a_visitor_never_reads_the_registries(self):
        for url in (reverse('common:registries'), reverse('common:registres_etat')):
            response = self.client.get(url)
            self.assertEqual(403, response.status_code, url)
            self.assertTrue(response.json()['login_required'])

    def test_a_member_reads_the_registries_but_never_refreshes_them(self):
        self.client.force_login(self._account('reg_member', 'utilisateur'))
        self.assertEqual(200, self.client.get(reverse('common:registries')).status_code)
        response = self.client.post(reverse('common:registre_refresh', args=[self._shared_registry()]))
        self.assertEqual(403, response.status_code)
        self.assertIn('développeurs', response.json()['error'])

    def test_a_developer_refreshes_a_shared_registry(self):
        """Counter-test: the refusal above is the member's, not the route's."""
        self.client.force_login(self._account('reg_developer', 'developpeur'))
        response = self.client.post(reverse('common:registre_refresh', args=[self._shared_registry()]))
        self.assertEqual(200, response.status_code, response.content[:200])

    def test_the_model_manager_is_a_registry_page_and_not_a_column_of_its_own(self):
        from wama.accounts.permissions import access_cases, all_gated_apps
        self.assertNotIn('model_manager', all_gated_apps(), 'no separate right any more')
        self.assertNotIn('model_manager', [a['id'] for a in access_cases()['apps']])
        self.assertEqual(403, self.client.get(reverse('model_manager:index')).status_code,
                         'a visitor never reads the model registry')

    def test_a_member_reads_the_model_manager_without_any_management_gesture(self):
        self.client.force_login(self._account('mm_reader', 'utilisateur'))
        page = self.client.get(reverse('model_manager:index'))
        self.assertEqual(200, page.status_code)
        self.assertFalse(page.context['can_manage'])
        self.assertIn('const CAN_MANAGE = false;', page.content.decode())
        self.assertEqual(200, self.client.get(reverse('model_manager:api_models_db')).status_code)
        refused = self.client.post(reverse('model_manager:api_clear_gpu'))
        self.assertIn(refused.status_code, (302, 403), 'a member never frees the graphics card')

    def test_a_developer_manages_the_model_manager(self):
        """Counter-test: the read-only page is the member's, not everyone's."""
        self.client.force_login(self._account('mm_manager', 'developpeur'))
        page = self.client.get(reverse('model_manager:index'))
        self.assertEqual(200, page.status_code)
        self.assertTrue(page.context['can_manage'])
        self.assertIn('const CAN_MANAGE = true;', page.content.decode())


class PagelessToolsTests(TestCase):
    """2026-10-13 (Fabien's decision): the file manager (a side panel) and the assistant (a
    conversation) are tools WITHOUT a page. They enter the access policy all the same — the
    same decision, editable on the access admin page, shown by the rights scene."""

    def _member(self, name):
        user = User.objects.create_user(name, password='x')
        UserProfile.objects.update_or_create(user=user, defaults={'account_tier': 'utilisateur'})
        return User.objects.get(pk=user.pk)

    def _restrict(self, tool, role='recherche'):
        """A policy edited in WAMA: the tool now needs a role the member does not hold."""
        from wama.accounts.models import AppAccessPolicy
        policy, _ = AppAccessPolicy.objects.get_or_create(app_id=tool)
        policy.roles.add(Group.objects.get_or_create(name=GROUP_PREFIX + role)[0])

    def test_both_tools_are_columns_of_the_transversal_world(self):
        from wama.accounts.permissions import access_cases
        columns = {a['id']: a for a in access_cases()['apps']}
        for tool in ('filemanager', 'assistant'):
            self.assertIn(tool, columns, f'{tool} is missing from the access scene')
            self.assertEqual('transverse', columns[tool]['world'])

    def test_a_member_reaches_both_tools_by_default(self):
        self.client.force_login(self._member('pageless_member'))
        self.assertEqual(200, self.client.get('/filemanager/api/tree/').status_code)
        self.assertEqual(200, self.client.get(reverse('ai_chat_thread')).status_code)

    def test_the_policy_edited_in_wama_closes_the_file_manager(self):
        self._restrict('filemanager')
        self.client.force_login(self._member('fm_closed'))
        self.assertEqual(403, self.client.get('/filemanager/api/tree/').status_code)

    def test_the_policy_closes_the_assistant_on_every_surface(self):
        """The web routes are closed by the middleware; Discord and the API go through
        `conversation_turn`, which is guarded too — no model is called."""
        from unittest import mock
        from wama.common.services import assistant_engine
        self._restrict('assistant')
        member = self._member('assistant_closed')
        self.client.force_login(member)
        self.assertEqual(403, self.client.get(reverse('ai_chat_thread')).status_code)
        with mock.patch.object(assistant_engine, 'run_assistant_turn') as engine:
            result = assistant_engine.conversation_turn(member, 'bonjour', surface='api')
        self.assertIn('error', result)
        engine.assert_not_called()
