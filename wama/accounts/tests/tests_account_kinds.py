"""Comptes de PERSONNES et comptes de TEST, chacun dans sa section (2026-10-01, demande de Fabien).

CE QUE CES GARDES TIENNENT :
- la nature d'un compte se lit à son NOM : préfixe `wama_` (et le compte système anonyme) → section
  des comptes de test ; tout le reste → section des utilisateurs ;
- tout compte EXCLU des statistiques apprises (`nightly_tests.TEST_USERNAMES`) porte le préfixe —
  sinon un compte de test se rangerait parmi les personnes ; l'inverse n'est pas exigé
  (`wama_evaluation` nourrit l'ETA, décision de Fabien du 30/09) ;
- la page de gestion rend les deux sections et la barre COMMUNE de filtre / tri / recherche, avec
  ce que la brique lit sur chaque ligne (`data-f-*`, `data-s-*`).
"""
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from wama.accounts.permissions import TEST_ACCOUNT_PREFIX, account_kind


class TheAccountKindIsReadFromTheNameTest(SimpleTestCase):

    def test_prefixed_accounts_and_the_system_account_are_test_accounts(self):
        User = get_user_model()
        for name in ('wama_evaluation', 'wama_nightly_test', 'anonymous'):
            with self.subTest(name=name):
                self.assertEqual('test', account_kind(User(username=name)))

    def test_every_other_account_is_a_person(self):
        User = get_user_model()
        for name in ('regis.blanchet', 'Sophie', 'evaluation', 'wamafan'):
            with self.subTest(name=name):
                self.assertEqual('person', account_kind(User(username=name)))

    def test_every_account_kept_out_of_learned_statistics_carries_the_prefix(self):
        from wama.common.services.nightly_tests import TEST_USERNAMES
        self.assertEqual([], [n for n in TEST_USERNAMES if not n.startswith(TEST_ACCOUNT_PREFIX)])


class TheUserPageGroupsAccountsTest(TestCase):

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_superuser('kinds_admin', password='x')
        User.objects.create_user('wama_kinds_probe', password='x')
        User.objects.create_user('kinds.person', password='x')
        self.client.force_login(self.admin)

    def _sections(self):
        response = self.client.get(reverse('accounts:user-management'))
        self.assertEqual(200, response.status_code)
        return {s['kind']: [i['user'].username for i in s['users']]
                for s in response.context['sections']}, response.content.decode()

    def test_people_and_test_accounts_land_in_their_own_section(self):
        sections, _ = self._sections()
        self.assertIn('wama_kinds_probe', sections['test'])
        self.assertIn('kinds.person', sections['person'])
        self.assertNotIn('wama_kinds_probe', sections['person'])

    def test_the_common_filter_bar_is_mounted_with_what_each_row_carries(self):
        _, html = self._sections()
        self.assertIn('data-wama-filter-bar', html)
        self.assertIn('data-f-facette="tier"', html)
        self.assertIn('data-f-facette="statut"', html)
        self.assertIn('data-f-role="sort"', html)
        self.assertIn('data-f-groupe="test"', html)
        for attribute in ('data-f-tier="', 'data-f-statut="', 'data-s-username="',
                          'data-s-joined="', 'data-s-login="'):
            with self.subTest(attribute=attribute):
                self.assertIn(attribute, html)
