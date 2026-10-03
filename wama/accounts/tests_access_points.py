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
        self.assertEqual(app_id_for_path('/model-manager/'), 'model_manager')
        self.assertEqual(app_id_for_path('/model-manager/libraries/'), 'model_manager')
        self.assertEqual(app_id_for_path('/model-manager/functions/'), 'model_manager')
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
        urls = _urls_des_surfaces_gardees()
        manquantes = sorted(all_gated_apps() - set(urls))
        self.assertEqual(manquantes, [],
                         f"surfaces gardées sans url_name relevable : {manquantes}")


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
    """`is_admin_or_dev` était un second barème : il doit désormais dire la MÊME chose."""

    def setUp(self):
        for k in ROLES:
            Group.objects.get_or_create(name=GROUP_PREFIX + k)
        self.pol = DEFAULT_APP_ACCESS['model_manager']

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
        for u in cas:
            self.assertEqual(
                bool(is_admin_or_dev(u)), accessible(u, 'app', 'model_manager'),
                f"{u.username} : le décorateur et `accessible()` divergent")

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
        self.assertEqual(self.pol.get('min_tier'), 'developpeur',
                         "prémisse du test : la politique exige le tier développeur")
        self.assertTrue(is_admin_or_dev(self._compte('mm_dev2', 'developpeur')))


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
        visitor = Client(raise_request_exception=False)
        refused = {app_id: visitor.get(url).status_code
                   for app_id, url in self._index_urls().items()}
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
