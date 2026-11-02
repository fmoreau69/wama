"""Verrouille la FERMETURE du compte de service anonyme.

Contexte (2026-08-22 puis 2026-08-27) : WAMA porte deux « anonymes » opposés — `AnonymousUser`
de Django, refusé partout, et l'utilisateur **`anonymous` EN BASE** que les vues substituent aux
requêtes non authentifiées. Le second portait les 4 rôles métier et le tier `utilisateur`, donc
il était **accepté partout** : `user_tier()` teste `is_authenticated`, propriété toujours vraie
sur une instance `User`.

La fermeture du 22/08 avait été faite À LA MAIN sur la base vivante. Mesuré le 27/08, ça ne
tenait pas : `UserProfile.account_tier` a pour défaut `utilisateur`, donc tout compte anonyme
recréé (installation neuve, restauration) revenait ouvert, et `grant_default_roles` — qui vise
les comptes SANS aucun rôle — lui rendait les 4 rôles. Ces tests prouvent que l'invariant vit
maintenant dans le CODE, où une réinstallation ne peut plus le défaire.
"""
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase

from wama.accounts.models import UserProfile
from wama.accounts.permissions import GROUP_PREFIX, ROLES, accessible, user_roles, user_tier
from wama.accounts.views import ANONYMOUS_USERNAME, get_or_create_anonymous_user
from wama.common.app_registry import APP_CATALOG


def _tous_les_groupes_de_role():
    return [Group.objects.get_or_create(name=GROUP_PREFIX + k)[0] for k in ROLES]


class FermetureDuCompteAnonymeTests(TestCase):

    def test_un_compte_anonyme_neuf_nait_ferme(self):
        # Le cas d'une installation neuve : rien n'a jamais été corrigé à la main.
        u = get_or_create_anonymous_user()
        self.assertEqual(user_tier(u), 'anonymous')
        self.assertEqual(user_roles(u), set())

    def test_a_fresh_anonymous_account_opens_only_the_trial_app(self):
        # Jusqu'au 2026-10-04 : AUCUNE app. Le converter est depuis l'app d'essai DÉCLARÉE
        # (`public`, décision du 30/08) — où le visiteur agit sous une identité de session, pas
        # sous ce compte partagé (`tests_visitors`). Toute autre app ouverte ici est une fuite.
        u = get_or_create_anonymous_user()
        ouvertes = [a for a in APP_CATALOG if accessible(u, 'app', a)]
        self.assertEqual(ouvertes, ['converter'], f"apps ouvertes à l'anonyme : {ouvertes}")

    def test_le_tier_pose_a_la_main_est_repose_au_prochain_appel(self):
        # La dérive qu'on veut rattraper : quelqu'un remonte le tier via l'admin.
        u = get_or_create_anonymous_user()
        UserProfile.objects.filter(user=u).update(account_tier='utilisateur')
        import wama.accounts.views as v
        v._CLOSURE_VERIFIEE = False          # simule un worker qui redémarre
        u = get_or_create_anonymous_user()
        self.assertEqual(user_tier(u), 'anonymous')

    def test_des_roles_rendus_a_la_main_sont_retires_au_prochain_appel(self):
        u = get_or_create_anonymous_user()
        u.groups.add(*_tous_les_groupes_de_role())
        import wama.accounts.views as v
        v._CLOSURE_VERIFIEE = False
        u = get_or_create_anonymous_user()
        self.assertEqual(user_roles(u), set())

    def test_grant_default_roles_ne_touche_jamais_le_compte_anonyme(self):
        # C'était le chemin de régression : la commande vise les users SANS rôle, c'est-à-dire
        # exactement l'anonyme depuis qu'on l'a fermé.
        _tous_les_groupes_de_role()
        anon = get_or_create_anonymous_user()
        autre = User.objects.create_user('quelquun', password='x')
        call_command('grant_default_roles', verbosity=0)
        self.assertEqual(user_roles(anon), set())
        self.assertTrue(user_roles(autre), "la commande doit rester utile aux autres comptes")

    def test_grant_default_roles_epargne_l_anonyme_meme_avec_all_users(self):
        # L'exclusion n'a pas d'échappatoire : `--all-users` ne doit pas la lever.
        _tous_les_groupes_de_role()
        anon = get_or_create_anonymous_user()
        call_command('grant_default_roles', '--all-users', verbosity=0)
        self.assertEqual(user_roles(anon), set())


class DeuxAxesDuModeleDAccesTests(TestCase):
    """Le modèle est à DEUX axes : on ne doit dépendre d'aucun des deux tout seul."""

    def setUp(self):
        _tous_les_groupes_de_role()
        self.u = get_or_create_anonymous_user()

    def test_the_tier_alone_closes_everything_but_the_public_app_even_with_every_role(self):
        self.u.groups.add(*_tous_les_groupes_de_role())
        ouvertes = [a for a in APP_CATALOG if accessible(self.u, 'app', a)]
        # `['converter']` depuis le 2026-10-04 : la seule app déclarée `public`. Les rôles
        # n'ouvrent RIEN de plus — c'est ce que ce test tient.
        self.assertEqual(ouvertes, ['converter'], "le tier `anonymous` doit trancher avant les rôles")

    def test_le_tier_seul_perdu_rouvre_deja_une_app(self):
        # La preuve que le second verrou (les rôles) n'est pas décoratif : sans le tier, la
        # branche « app commune » laisse passer converter — et avec les rôles, 10 apps sur 11.
        UserProfile.objects.filter(user=self.u).update(account_tier='utilisateur')
        u = User.objects.get(username=ANONYMOUS_USERNAME)
        sans_roles = {a for a in APP_CATALOG if accessible(u, 'app', a)}
        u.groups.add(*_tous_les_groupes_de_role())
        u = User.objects.get(username=ANONYMOUS_USERNAME)
        avec_roles = {a for a in APP_CATALOG if accessible(u, 'app', a)}
        self.assertLess(len(sans_roles), len(avec_roles),
                        "les rôles doivent élargir l'accès une fois le tier perdu")


class VisibiliteDesJumellesDeBacASableTests(TestCase):
    """Le bac à sable a UNE règle (décisions de Fabien, 2026-11-02) : un administrateur voit toutes
    ses apps, un développeur les siennes (et celles qu'on lui ouvre), un utilisateur simple aucune —
    « s'il souhaite y accéder ou développer une application, il demande à devenir développeur ».
    La dérogation du 2026-09-03 (le CRÉATEUR y accédait quel que soit son niveau) est retirée, et
    une politique éditée en base ne la rouvre pas. Le menu regroupe les jumelles visibles dans un
    groupe dédié en queue (« Bac à sable »).
    """

    def _account(self, name, tier='utilisateur'):
        u = User.objects.create_user(name, password='x')
        profile, _ = UserProfile.objects.get_or_create(user=u)
        profile.account_tier = tier
        profile.save()
        return User.objects.get(pk=u.pk)

    def _sandbox_posed(self, policy=None):
        """Registre et politique de la jumelle POSÉS PAR LE TEST — le registre
        sandbox_apps.json est GITIGNORÉ : sur un arbre frais (worktree HEAD, clone), il est
        absent. Mesuré le 2026-09-03 : la V1 de ces tests lisait l'arbre COURANT et échouait sur
        HEAD — un test qui dépend d'un fichier gitignoré mesure l'arbre, pas la logique."""
        from contextlib import ExitStack
        from unittest.mock import patch
        from wama.accounts.permissions import DEFAULT_APP_ACCESS
        stack = ExitStack()
        stack.enter_context(patch.dict(DEFAULT_APP_ACCESS, {'converter_01': policy or {
            'roles': ['ingenierie'], 'min_tier': 'developpeur'}}))
        stack.enter_context(patch('wama.common.sandbox.load_registry', return_value=[
            {'label': 'converter_01', 'generated_from': 'converter', 'created_by': 'sandbox_creator'}]))
        return stack

    def test_a_plain_user_does_not_see_the_sandbox_even_one_they_created(self):
        from wama.accounts.permissions import accessible_apps
        creator = self._account('sandbox_creator')
        self.assertEqual(user_tier(creator), 'utilisateur')
        with self._sandbox_posed():
            self.assertFalse(accessible(creator, 'app', 'converter_01'))
            self.assertEqual([], accessible_apps(creator, ['converter_01']), 'the grouped read too')

    def test_a_policy_edited_in_the_database_does_not_open_it_to_a_plain_user(self):
        plain = self._account('sandbox_plain')
        with self._sandbox_posed({'roles': [], 'public': True, 'min_tier': None}):
            self.assertFalse(accessible(plain, 'app', 'converter_01'))

    def test_its_developer_and_the_administrators_see_it_another_developer_does_not(self):
        """« Une seule règle partout, un dev ne voit que ses propres apps, admin toutes »
        (Fabien, 2026-11-02) — l'accès qu'on ouvre à un autre : `tests_app_access`."""
        creator = self._account('sandbox_creator', 'developpeur')
        with self._sandbox_posed():
            self.assertTrue(accessible(creator, 'app', 'converter_01'))
            self.assertTrue(accessible(self._account('sandbox_admin', 'admin'), 'app', 'converter_01'))
            self.assertFalse(accessible(self._account('sandbox_other_dev', 'developpeur'), 'app',
                                        'converter_01'))

    def test_le_menu_range_les_jumelles_dans_un_groupe_dedie_en_queue(self):
        from django.test import RequestFactory
        from wama.accounts.context_processors import user_role
        req = RequestFactory().get('/')
        # Un administrateur : il voit TOUT le bac à sable (un développeur, ses seules apps).
        req.user = self._account('sandbox_menu_admin', 'admin')
        groupes = user_role(req)['nav_apps_grouped']
        ids = [g['id'] for g in groupes]
        if 'sandbox' not in ids:
            self.skipTest('aucune jumelle enregistrée sur cet arbre (registre gitignoré)')
        self.assertEqual(ids[-1], 'sandbox', 'le groupe Bac à sable ferme le menu')
        for g in groupes:
            if g['id'] == 'sandbox':
                continue
            for a in g['apps']:
                self.assertNotIn('BAC À SABLE', a['label'],
                                 'aucune jumelle ne doit rester dans les catégories normales')


    def test_le_catalogue_JS_ne_revele_pas_les_jumelles_a_qui_n_y_a_pas_droit(self):
        """Constat Fabien 2026-09-03 : « le bac à sable a des permissions utilisateur (admin +
        utilisateur propriétaire) ». `window.WAMA_APP_CATALOG` listait pourtant TOUTES les
        jumelles pour tout le monde : les pages restaient gardées, mais l'EXISTENCE fuitait.
        La garde repasse par `accessible()` — jamais une seconde politique."""
        from django.test import RequestFactory
        from wama.accounts.context_processors import user_role
        from wama.common.app_registry import APP_CATALOG
        jumelles = [n for n, s in APP_CATALOG.items() if s.get('sandbox')]
        if not jumelles:
            self.skipTest('aucune jumelle enregistrée sur cet arbre (registre gitignoré)')
        req = RequestFactory().get('/')
        req.user = self._account('temoin_catalogue_js')
        catalogue = user_role(req)['app_catalog_json']
        for label in jumelles:
            self.assertNotIn(label, catalogue,
                             f"{label} ne doit pas être exposé au JS d'un compte sans droit")
