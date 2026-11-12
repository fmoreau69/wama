"""
Outils d'inspection admin (`dev_inspect`) : un succès et un refus de droits par outil, plus les
refus qui font la sécurité (`.env`, évasion de racine, lien symbolique, oracle de filtre, table
de comptes, colonne sensible).
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.accounts.permissions import set_account_tier
from wama.common.services import dev_inspect, dev_tools


class _Base(TestCase):

    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user('insp_admin', password='x')
        set_account_tier(self.admin, 'admin')
        self.dev = User.objects.create_user('insp_dev', password='x')
        set_account_tier(self.dev, 'developpeur')
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        (self.root / 'logs').mkdir()
        (self.root / 'pkg').mkdir()
        patcher = mock.patch.object(dev_inspect, 'base_dir', return_value=self.root)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _call(self, user, name, **kwargs):
        return dev_tools.call(user, name, kwargs)


class AdminGuardTest(_Base):

    def test_a_developer_neither_sees_nor_calls_the_admin_tools(self):
        seen = {t.name for t in dev_tools.tools_for(self.dev)}
        self.assertFalse(seen & dev_tools.ADMIN_ONLY)
        self.assertTrue(dev_tools.ADMIN_ONLY <= {t.name for t in dev_tools.tools_for(self.admin)})
        for name in dev_tools.ADMIN_ONLY:
            with self.subTest(tool=name):
                self.assertEqual('forbidden', self._call(self.dev, name, path='a', table='x.Y')['error'])

    def test_a_direct_call_stays_guarded(self):
        """La garde est dans le corps : contourner `call()` ne la lève pas."""
        for fn in (dev_inspect.dev_db_query, dev_inspect.dev_db_schema):
            self.assertEqual('forbidden', fn(self.dev, 'common.CalendarFeed')['error'])
        for fn in (dev_inspect.dev_read_log, dev_inspect.dev_read_code):
            self.assertEqual('forbidden', fn(self.dev, 'x')['error'])
        self.assertEqual('forbidden', dev_inspect.dev_list_code(self.dev)['error'])
        self.assertEqual('forbidden', dev_inspect.dev_search_code(self.dev, 'x')['error'])
        self.assertEqual('forbidden', dev_tools.dev_run_tests(self.dev, 'wama.common.tests')['error'])


class DatabaseTest(_Base):

    def test_dev_db_schema_lists_columns_and_flags_sensitive_ones(self):
        res = self._call(self.admin, 'dev_db_schema', table='model_manager.AIModel')
        names = {c['name'] for c in res['columns']}
        self.assertIn('id', names)

    def test_dev_db_query_returns_rows_without_sensitive_columns(self):
        res = self._call(self.admin, 'dev_db_query', table='model_manager.AIModel', limit=500)
        self.assertEqual(len(res['rows']), res['count'])
        self.assertLessEqual(res['count'], dev_inspect.MAX_ROWS)
        for row in res['rows']:
            self.assertFalse([k for k in row if dev_inspect.SENSITIVE_COLUMN.search(k)])

    def test_account_and_key_tables_are_refused(self):
        for table in ('auth.User', 'sessions.Session', 'accounts.UserProfile',
                      'accounts.UserApiKey', 'common.CalendarFeed'):
            with self.subTest(table=table):
                self.assertIn('error', self._call(self.admin, 'dev_db_query', table=table))

    def test_a_filter_on_a_sensitive_column_or_a_relation_is_refused(self):
        for flt in ('token__startswith="a"', 'user__password__startswith="a"',
                    'user__username="x"'):
            with self.subTest(filter=flt):
                res = self._call(self.admin, 'dev_db_query', table='model_manager.AIModel',
                                 filter=flt)
                self.assertIn('filtre refusé', res['error'])


class FilesTest(_Base):

    def test_dev_read_log_masks_secrets_and_filters(self):
        (self.root / 'logs' / 'gunicorn.log').write_text(
            'ok 1\nAuthorization: Bearer abc123\nerr 2\n', encoding='utf-8')
        res = self._call(self.admin, 'dev_read_log', path='gunicorn.log', grep='Bearer')
        self.assertIn('Bearer ***', res['text'])
        self.assertNotIn('abc123', res['text'])
        self.assertNotIn('ok 1', res['text'])

    def test_dev_read_log_refuses_outside_and_non_log(self):
        (self.root / 'logs' / 'notes.txt').write_text('x', encoding='utf-8')
        for path in ('/etc/passwd', '../pkg/a.py', 'notes.txt'):
            with self.subTest(path=path):
                self.assertIn('error', self._call(self.admin, 'dev_read_log', path=path))

    def test_dev_read_log_without_a_path_lists_the_journals_most_recent_first(self):
        import os
        for age, name in enumerate(('old.log', 'gunicorn-error.log', 'notes.txt')):
            f = self.root / 'logs' / name
            f.write_text('x', encoding='utf-8')
            os.utime(f, (1_700_000_000 - age * 100, 1_700_000_000 - age * 100))
        os.utime(self.root / 'logs' / 'gunicorn-error.log', (1_800_000_000, 1_800_000_000))
        listed = self._call(self.admin, 'dev_read_log')['journals']
        self.assertEqual(['gunicorn-error.log', 'old.log'], [j['name'] for j in listed])
        self.assertEqual(1, listed[0]['bytes'])

    def test_a_guessed_log_name_is_refused_with_the_real_ones(self):
        """2026-11-12 : « gunicorn.log » n'existe pas ; le refus nu a fait renoncer l'assistant."""
        (self.root / 'logs' / 'gunicorn-error.log').write_text('x', encoding='utf-8')
        error = self._call(self.admin, 'dev_read_log', path='gunicorn.log')['error']
        self.assertIn('gunicorn-error.log', error)

    def test_dev_search_code_finds_lines_and_skips_denied_places(self):
        (self.root / 'pkg' / 'a.py').write_text('x = 1\nraise Boom("no export")\n', encoding='utf-8')
        (self.root / 'pkg' / 'page.html').write_text('no export here\n', encoding='utf-8')
        (self.root / 'logs' / 'c.py').write_text('no export\n', encoding='utf-8')
        (self.root / '.env').write_text('no export\n', encoding='utf-8')
        found = self._call(self.admin, 'dev_search_code', pattern='no export')
        self.assertEqual(['pkg/a.py:2: raise Boom("no export")'], found['matches'])
        html = self._call(self.admin, 'dev_search_code', pattern='no export', glob='*')
        self.assertEqual({'pkg/a.py', 'pkg/page.html'}, {m.split(':')[0] for m in html['matches']})
        # A regular expression is one only when asked; a broken one is refused, not raised.
        self.assertEqual([], self._call(self.admin, 'dev_search_code', pattern='x = \\d')['matches'])
        self.assertEqual(1, len(self._call(self.admin, 'dev_search_code', pattern='x = \\d',
                                           regex=True)['matches']))
        self.assertIn('error', self._call(self.admin, 'dev_search_code', pattern='(', regex=True))
        for refused in ({'pattern': 'x', 'path': 'logs'}, {'pattern': 'x', 'path': '..'},
                        {'pattern': 'x', 'glob': '../*'}, {'pattern': ''}):
            with self.subTest(refused=refused):
                self.assertIn('error', self._call(self.admin, 'dev_search_code', **refused))

    def test_dev_run_tests_starts_one_label_and_never_the_whole_suite(self):
        with mock.patch.object(dev_tools, 'start_job', return_value={'job_id': 'j'}) as started:
            self.assertEqual({'job_id': 'j'}, self._call(self.admin, 'dev_run_tests',
                                                         label='wama.common.tests.tests_user_settings'))
            argv = started.call_args.args[2]
            self.assertEqual(['test', 'wama.common.tests.tests_user_settings', '--keepdb'], argv[2:])
            for label in ('', 'wama', 'os.system', 'wama.common; rm -rf x', '--help', 'wama..tests'):
                with self.subTest(label=label):
                    self.assertIn('error', self._call(self.admin, 'dev_run_tests', label=label))
            self.assertEqual(1, started.call_count)

    def test_dev_read_code_numbers_lines(self):
        (self.root / 'pkg' / 'a.py').write_text('x = 1\ny = 2\n', encoding='utf-8')
        res = self._call(self.admin, 'dev_read_code', path='pkg/a.py')
        self.assertEqual('    1\tx = 1\n    2\ty = 2', res['text'])

    def test_dev_read_code_refuses_secrets_escapes_and_symlinks(self):
        (self.root / '.env').write_text('SECRET=1', encoding='utf-8')
        (self.root / 'pkg' / 'blob.bin').write_bytes(b'\x00\x01')
        outside = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: [p.unlink() for p in outside.iterdir()] and outside.rmdir())
        (outside / 'x.txt').write_text('hors', encoding='utf-8')
        try:
            (self.root / 'pkg' / 'link.txt').symlink_to(outside / 'x.txt')
            (self.root / 'pkg' / 'envlink').symlink_to(self.root / '.env')
        except OSError:
            self.skipTest("liens symboliques indisponibles")
        for path in ('.env', '../x', 'pkg/link.txt', 'pkg/envlink', 'pkg/blob.bin'):
            with self.subTest(path=path):
                self.assertIn('error', self._call(self.admin, 'dev_read_code', path=path))

    def test_dev_list_code_lists_and_skips_denied_places(self):
        (self.root / 'pkg' / 'a.py').write_text('', encoding='utf-8')
        (self.root / 'pkg' / 'deep').mkdir()
        (self.root / 'pkg' / 'deep' / 'b.py').write_text('', encoding='utf-8')
        (self.root / 'logs' / 'c.py').write_text('', encoding='utf-8')
        (self.root / '.env').write_text('', encoding='utf-8')
        flat = self._call(self.admin, 'dev_list_code', path='pkg', pattern='*.py')
        self.assertEqual(['pkg/a.py'], flat['paths'])
        deep = self._call(self.admin, 'dev_list_code', pattern='**/*.py')
        self.assertEqual(['pkg/a.py', 'pkg/deep/b.py'], sorted(deep['paths']))
        self.assertIn('error', self._call(self.admin, 'dev_list_code', path='logs'))


class JobNotificationOpensSomewhereTest(TestCase):
    """2026-11-12: the end of a development task with no proposal had nothing to open (74
    notifications measured). It now opens the assistant's thread, where the end is told."""

    def test_a_task_without_a_proposal_opens_the_assistant_and_a_proposal_its_queue(self):
        from django.urls import reverse
        self.assertEqual(reverse('home'), dev_tools.job_open_url([]))
        with mock.patch.object(dev_tools, 'proposals_url', return_value='/models/#wamaProposals'):
            self.assertEqual('/models/#wamaProposals', dev_tools.job_open_url(['x.json']))
