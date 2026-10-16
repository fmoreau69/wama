"""Les pages du menu du COMPTE (2026-10-14, demande de Fabien) : déclarées
(`app_registry.register_account_page`), le menu en est GÉNÉRÉ, l'assistant y emmène
(`open_page`) et les lit (`get_my_calendar`, `list_my_notifications`, `list_my_shares`,
`list_my_rag`, `get_my_profile`).

La garde qui porte tout est la PARITÉ : pour chaque page déclarée et chaque sorte de compte, ce
que l'assistant et le menu proposent (`permissions.can_open_page`) est ce que la vue RÉPOND
vraiment. Une vue qui change de décorateur sans que sa déclaration suive la fait échouer.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.test import TestCase
from django.urls import reverse

from wama import tool_api
from wama.accounts.permissions import ANONYMOUS_USERNAME, can_open_page
from wama.common.app_registry import account_pages
from wama.common.services.navigation import account_menu, find_page, navigable_pages

User = get_user_model()


def _declared_urls():
    """`{key: (access, url)}` des pages déclarées dont la route se résout."""
    out = {}
    for page in account_pages():
        if page['url_name']:
            out[page['key']] = (page['access'], reverse(page['url_name']))
    return out


class AccountPagesDeclarationTest(TestCase):

    def test_every_page_of_the_former_menu_is_declared(self):
        """Les 18 entrées du menu écrit à la main jusqu'au 2026-10-14, et la cloche."""
        keys = {p['key'] for p in account_pages()}
        self.assertTrue({'functions', 'calendar', 'journal', 'rag', 'memories', 'shares',
                         'profile', 'skills', 'users', 'apps', 'docs', 'libraries', 'licenses',
                         'models', 'backends', 'media_formats', 'registries', 'sources',
                         'notifications'} <= keys)

    def test_every_declared_page_resolves(self):
        unresolved = [p['key'] for p in account_pages() if not p['url_name']]
        self.assertEqual([], unresolved, 'a page points at a surface that is not declared')
        self.assertEqual(len(account_pages()), len(_declared_urls()))

    def test_a_page_that_is_a_surface_reads_its_route_there(self):
        by_key = {p['key']: p for p in account_pages()}
        self.assertEqual('common:registries', by_key['registries']['url_name'])
        self.assertEqual('model_manager:index', by_key['models']['url_name'])


class AccountPagesParityTest(TestCase):
    """Ce qui est proposé = ce que la vue répond, page par page, compte par compte."""

    def setUp(self):
        from wama.accounts.models import AppAccessPolicy
        self.member = User.objects.create_user('acct_member', password='x')
        self.admin = User.objects.create_superuser('acct_admin', password='x')
        self.guest, _ = User.objects.get_or_create(username=ANONYMOUS_USERNAME)
        # Un membre à qui la politique RETIRE les registres : leurs pages lui sont refusées.
        self.restricted = User.objects.create_user('acct_restricted', password='x')
        self.policy = AppAccessPolicy

    def _answers(self, user, url):
        self.client.logout()
        if user is not None:
            self.client.force_login(user)
        status = self.client.get(url).status_code
        self.assertIn(status, (200, 302, 403), f'{url} answered {status}')
        return status == 200

    def _check(self, label, user, request_user=None):
        for key, (access, url) in _declared_urls().items():
            with self.subTest(account=label, page=key):
                expected = can_open_page(request_user or user or AnonymousUser(), access, url)
                self.assertEqual(expected, self._answers(user, url),
                                 f"{key}: the assistant and the page disagree for {label}")

    def test_a_visitor(self):
        self._check('visitor', None)

    def test_a_guest_service_account(self):
        self._check('guest', self.guest)

    def test_a_member(self):
        self._check('member', self.member)

    def test_an_administrator(self):
        self._check('admin', self.admin)

    def test_a_member_whose_policy_withdraws_the_registries(self):
        self.policy.objects.create(app_id='registries', min_tier='developpeur')
        self._check('restricted member', self.restricted)


class AccountMenuTest(TestCase):

    def setUp(self):
        self.member = User.objects.create_user('menu_member', password='x')
        self.admin = User.objects.create_superuser('menu_admin', password='x')

    def test_the_menu_keeps_its_two_sections_in_order(self):
        menu = account_menu(self.admin)
        self.assertEqual(['Mon espace', 'WAMA'], [s['label'] for s in menu])
        self.assertEqual(['Fonctions', 'Mon calendrier', 'Mon journal', 'Mon RAG', 'Mes souvenirs',
                          'Mes partages', 'Profil', 'Skills', 'Users'],
                         [p['label'] for p in menu[0]['pages']])
        self.assertEqual(['Apps', 'Documentation', 'Librairies', 'Licences', 'Models', 'Backends',
                          'Formats médias', 'Briques UI', 'Registres', 'Sources'],
                         [p['label'] for p in menu[1]['pages']])

    def test_the_bell_page_is_openable_but_not_in_the_menu(self):
        labels = [p['label'] for s in account_menu(self.admin) for p in s['pages']]
        self.assertNotIn('Notifications', labels)
        self.assertIsNotNone(find_page(self.admin, 'notifications')[0])

    def test_the_rendered_header_follows_the_rights(self):
        users_url = reverse('accounts:user-management')
        self.client.force_login(self.admin)
        admin_page = self.client.get(reverse('accounts:profile')).content.decode()
        self.client.force_login(self.member)
        member_page = self.client.get(reverse('accounts:profile')).content.decode()
        self.assertIn(users_url, admin_page)
        self.assertNotIn(users_url, member_page, 'a member sees the administrators entry')
        for url in (reverse('common:journal'), reverse('accounts:profile'), '/common/shares/'):
            self.assertIn(f'href="{url}"', member_page)
        self.assertIn(reverse('accounts:logout'), member_page)


class OpenAccountPageTest(TestCase):

    def setUp(self):
        self.member = User.objects.create_user('nav_member', password='x')
        self.admin = User.objects.create_superuser('nav_admin', password='x')

    def test_the_assistant_opens_a_page_of_the_account_menu(self):
        for name, url_name in (('Profil', 'accounts:profile'), ('mon journal', 'common:journal'),
                               ('mes partages', 'common:shares'), ('Documentation', 'common:docs_catalog')):
            with self.subTest(name=name):
                result = tool_api.open_page(self.member, name)
                self.assertEqual(('navigate', reverse(url_name)), (result['action'], result['url']))

    def test_an_administrators_page_is_never_offered_to_a_member(self):
        refused = tool_api.open_page(self.member, 'Users')
        self.assertIn('error', refused)
        self.assertNotIn('users', [p['key'] for p in refused['pages']])
        self.assertEqual(reverse('accounts:user-management'),
                         tool_api.open_page(self.admin, 'Users')['url'])

    def test_a_menu_name_of_a_surface_opens_that_surface_once(self):
        """« Registres » et « Models » sont des surfaces : leur libellé de menu est un alias, la
        page n'est pas listée deux fois."""
        self.assertEqual(reverse('model_manager:index'),
                         tool_api.open_page(self.member, 'Models')['url'])
        urls = [p['url'] for p in navigable_pages(self.member)]
        self.assertEqual(len(urls), len(set(urls)), 'a page is offered twice')

    def test_a_withdrawn_registry_right_closes_its_pages(self):
        from wama.accounts.models import AppAccessPolicy
        AppAccessPolicy.objects.create(app_id='registries', min_tier='developpeur')
        for name in ('Registres', 'Fonctions', 'Librairies', 'Models'):
            with self.subTest(name=name):
                self.assertIn('error', tool_api.open_page(self.member, name))
        self.assertNotIn('error', tool_api.open_page(self.member, 'Profil'), 'contre-épreuve')


class AccountReadingToolsTest(TestCase):

    def setUp(self):
        self.user = User.objects.create_user('read_me', password='x', first_name='Ada')
        self.other = User.objects.create_user('read_other', password='x')

    def test_each_reading_refuses_a_visitor(self):
        for tool in ('get_my_calendar', 'list_my_notifications', 'list_my_shares', 'list_my_rag',
                     'get_my_profile'):
            with self.subTest(tool=tool):
                self.assertIn('error', getattr(tool_api, tool)(AnonymousUser()))

    def test_each_reading_is_registered_and_answers_without_arguments(self):
        for tool in ('get_my_calendar', 'list_my_notifications', 'list_my_shares', 'list_my_rag',
                     'get_my_profile'):
            with self.subTest(tool=tool):
                self.assertIn(tool, tool_api.TOOL_REGISTRY)
                self.assertIsNone(tool_api.app_id_for_tool(tool), 'no app guards it')
                self.assertNotIn('error', tool_api.execute_tool(tool, {}, self.user))

    def test_notifications_are_the_users_own_newest_first(self):
        from wama.common.models import Notification
        Notification.objects.create(recipient=self.user, kind='job_done', title='premier')
        Notification.objects.create(recipient=self.user, kind='job_failed', title='second')
        Notification.objects.create(recipient=self.other, kind='job_done', title="d'autrui")
        out = tool_api.list_my_notifications(self.user)
        self.assertEqual(['second', 'premier'], [n['title'] for n in out['notifications']])
        self.assertEqual(2, out['unread'])
        self.assertNotIn('actions', out['notifications'][0], 'panel buttons are not tool output')

    def test_the_profile_reads_every_setting_by_its_label_and_no_secret(self):
        from wama.accounts.models import UserProfile
        UserProfile.objects.get_or_create(user=self.user)
        out = tool_api.get_my_profile(self.user)
        self.assertEqual('Ada', out['first_name'])
        self.assertEqual({'label', 'value'}, set(out['settings']['ui_mode']))
        self.assertIn('cloud_policy', out['settings'])
        flat = repr(out).lower()
        for secret in ('token', 'api_key', 'password'):
            self.assertNotIn(secret, flat)

    def test_the_calendar_window_is_bounded_and_dated(self):
        out = tool_api.get_my_calendar(self.user, start='2026-01-01', end='2030-01-01')
        self.assertEqual('2026-01-01', out['window']['start'][:10])
        self.assertEqual('2027-02-05', out['window']['end'][:10], 'capped at 400 days')
        self.assertIn('error', tool_api.get_my_calendar(self.user, start='2026-13-45'))

    def test_the_rag_listing_applies_the_pages_filters(self):
        from unittest import mock
        docs = [{'source_id': 'file:a', 'source_ref': 'users/1/rapport.pdf', 'fragments': 3,
                 'vectorises': 2, 'niveau': 'user', 'ajoute_le': None}]
        with mock.patch('wama.common.memory.index.list_rag', return_value=docs) as listing:
            out = tool_api.list_my_rag(self.user, level='user', query='rapport')
        listing.assert_called_once_with(self.user, level='user', query='rapport')
        self.assertTrue(out['documents'][0]['reindex_due'])
