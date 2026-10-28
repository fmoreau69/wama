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
