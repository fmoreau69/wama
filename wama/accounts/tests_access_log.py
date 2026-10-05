"""
Journal des connexions (`accounts.AccessLog`) — décisions de Fabien du 2026-10-05 : MARQUER les
connexions qui ne sont pas des personnes (plutôt que les exclure), conserver SIX MOIS.

Mesuré avant : 1 087 lignes, dont 24 de personnes ; aucun refus n'avait de nom ; rien n'était
jamais purgé. Ces gardes tiennent ce qui ne se voit pas à l'usage — un journal qui marque mal ou
qui ne purge pas fonctionne très bien, jusqu'au jour où on le lit.
"""
from datetime import timedelta

from django.contrib.auth import authenticate, get_user_model
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from wama.accounts import moderation
from wama.accounts.models import AccessLog

User = get_user_model()
BROWSER = {'REMOTE_ADDR': '10.1.2.3', 'HTTP_USER_AGENT': 'Mozilla/5.0'}


class AccessKindTests(TestCase):

    def setUp(self):
        self.person = User.objects.create_user('jane.doe', password='right')
        self.factory = RequestFactory()

    def test_a_browser_login_is_a_person(self):
        self.assertEqual('person', moderation.access_kind(self.person, self.factory.get('/', **BROWSER)))

    def test_a_login_without_address_nor_browser_is_a_script(self):
        self.assertEqual('script', moderation.access_kind(self.person, None))
        bare = self.factory.get('/')
        bare.META.pop('REMOTE_ADDR', None)
        self.assertEqual('script', moderation.access_kind(self.person, bare))

    def test_a_test_account_stays_a_test_account_even_through_a_browser(self):
        from wama.common.services.nightly_tests import TEST_USERNAME
        tester = User.objects.create_user(TEST_USERNAME, password='x')
        self.assertEqual('test', moderation.access_kind(tester, self.factory.get('/', **BROWSER)))

    def test_a_visitor_identity_is_marked_as_such(self):
        from wama.accounts.permissions import VISITOR_ACCOUNT_PREFIX
        visitor = User.objects.create_user(VISITOR_ACCOUNT_PREFIX + 'abc', password='x')
        self.assertEqual('visitor', moderation.access_kind(visitor, self.factory.get('/', **BROWSER)))

    def test_the_real_login_route_writes_a_marked_line(self):
        self.client.post('/accounts/login/', {'username': 'jane.doe', 'password': 'right'}, **BROWSER)
        row = AccessLog.objects.filter(event='login').latest('pk')
        self.assertEqual(('jane.doe', 'person', 'local', '10.1.2.3'),
                         (row.username, row.kind, row.auth_backend, row.ip))

    def test_a_forced_login_is_seen_as_a_script(self):
        self.client.force_login(self.person)
        self.assertEqual('script', AccessLog.objects.filter(event='login').latest('pk').kind)


class DeniedLoginTests(TestCase):

    def setUp(self):
        User.objects.create_user('jane.doe', password='right')
        User.objects.create_user('pending.user', password='right', is_active=False)

    def _denied(self, username, password='wrong'):
        self.assertIsNone(authenticate(username=username, password=password))
        return AccessLog.objects.filter(event='login_denied').latest('pk')

    def test_a_rejected_attempt_keeps_the_name_and_says_why(self):
        self.assertEqual(('jane.doe', 'bad_credentials'),
                         (lambda r: (r.username, r.reason))(self._denied('jane.doe')))
        self.assertEqual('inactive', self._denied('pending.user', 'right').reason)
        self.assertEqual(('nobody.here', 'unknown_account'),
                         (lambda r: (r.username, r.reason))(self._denied('nobody.here')))

    def test_the_attempted_password_is_written_nowhere(self):
        row = self._denied('jane.doe', password='S3cret-Attempt!')
        for field in ('username', 'reason', 'user_agent', 'auth_backend', 'kind', 'event'):
            self.assertNotIn('S3cret', str(getattr(row, field)))

    def test_an_overlong_name_does_not_lose_the_line(self):
        self.assertEqual(150, len(self._denied('x' * 400).username))


class RetentionTests(TestCase):

    def _row(self, days_ago):
        row = AccessLog.objects.create(username='jane.doe', event='login')
        AccessLog.objects.filter(pk=row.pk).update(timestamp=timezone.now() - timedelta(days=days_ago))
        return row.pk

    def test_lines_older_than_six_months_leave_and_the_others_stay(self):
        old, recent = self._row(200), self._row(100)
        summary = moderation.purge_access_log()
        self.assertEqual(1, summary['purged'])
        self.assertFalse(AccessLog.objects.filter(pk=old).exists())
        self.assertTrue(AccessLog.objects.filter(pk=recent).exists())

    def test_a_dry_run_counts_without_deleting(self):
        old = self._row(400)
        self.assertEqual(1, moderation.purge_access_log(dry_run=True)['purged'])
        self.assertTrue(AccessLog.objects.filter(pk=old).exists())

    @override_settings(WAMA_ACCESS_LOG_RETENTION_DAYS=30)
    def test_the_duration_is_the_declared_setting(self):
        kept, gone = self._row(10), self._row(60)
        moderation.purge_access_log()
        self.assertEqual([kept], list(AccessLog.objects.values_list('pk', flat=True)))
        self.assertFalse(AccessLog.objects.filter(pk=gone).exists())

    def test_the_default_duration_is_six_months(self):
        from django.conf import settings
        self.assertEqual(183, settings.WAMA_ACCESS_LOG_RETENTION_DAYS)

    def test_the_nightly_task_runs_the_same_purge(self):
        from wama.common.tasks import purge_access_log_task
        self._row(300)
        self.assertEqual(1, purge_access_log_task()['purged'])


class ProfileSurfaceTests(TestCase):

    def test_the_holder_sees_the_last_accesses_to_the_account_rejections_included(self):
        user = User.objects.create_user('jane.doe', password='right')
        other = User.objects.create_user('john.roe', password='right')
        authenticate(username='jane.doe', password='wrong')
        authenticate(username='john.roe', password='wrong')
        self.client.force_login(user)
        from wama.accounts.views import recent_access
        rows = recent_access(user)
        self.assertEqual({'jane.doe'}, {r.username for r in rows})
        self.assertIn('login_denied', {r.event for r in rows})
        page = self.client.get('/accounts/profile/')
        self.assertEqual(200, page.status_code)
        self.assertContains(page, 'Derniers accès à mon compte')
        self.assertContains(page, 'Identifiants refusés')
        self.assertFalse(other.access_logs.exists())
