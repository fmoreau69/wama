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

    def test_a_guessed_table_name_is_refused_with_the_real_ones(self):
        """2026-11-17, relevé de `tool_usage` : `wama.Model`, `wama.ModelItem`, `django_migrations`
        — trois appels sur trois en échec le 30/10, et le diagnostic abandonné. Le refus dit les
        tables proches et la voie ; sans `table`, dev_db_schema les liste (comme dev_read_log)."""
        error = self._call(self.admin, 'dev_db_query', table='wama.Model')['error']
        self.assertIn('model_manager.AIModel', error)
        self.assertIn('dev_db_schema', error)
        self.assertIn('dev_db_schema', self._call(self.admin, 'dev_db_query',
                                                  table='django_migrations')['error'])
        listed = {row['table'] for row in self._call(self.admin, 'dev_db_schema')['tables']}
        self.assertIn('model_manager.AIModel', listed)
        self.assertFalse(listed & {'auth.User', 'accounts.UserProfile', 'common.CalendarFeed'})
        # Une colonne devinée suit LE MÊME refus (une seule lecture des noms proches).
        error = self._call(self.admin, 'dev_db_query', table='model_manager.AIModel',
                           fields='modelkey')['error']
        self.assertIn('model_key', error)
        self.assertIn('dev_db_schema', error)

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
        self.assertIn('dev_read_log sans `path`', error)

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

    def test_dev_search_code_reads_a_path_pattern_as_dev_list_code_does(self):
        """2026-11-17, relevé de `tool_usage` : 4 de ses 7 appels réels refusés (`**/*.py`,
        `composer/**/*.py`) quand dev_list_code lisait déjà ce motif. Un motif à « / » se lit sur
        le chemin relatif à `path` ; aucun fichier lu se DIT, il ne passe pas pour « absent »."""
        (self.root / 'pkg' / 'a.py').write_text('needle\n', encoding='utf-8')
        (self.root / 'pkg' / 'deep').mkdir()
        (self.root / 'pkg' / 'deep' / 'b.py').write_text('needle\n', encoding='utf-8')
        (self.root / 'pkg' / 'deep' / 'c.js').write_text('needle\n', encoding='utf-8')

        def files(**kwargs):
            found = self._call(self.admin, 'dev_search_code', pattern='needle', **kwargs)
            return sorted(m.split(':')[0] for m in found['matches'])
        self.assertEqual(['pkg/a.py', 'pkg/deep/b.py'], files(glob='**/*.py'))
        self.assertEqual(['pkg/deep/b.py'], files(glob='deep/*.py', path='pkg'))
        self.assertEqual(['pkg/deep/b.py', 'pkg/deep/c.js'], files(glob='**/deep/*'))
        nothing = self._call(self.admin, 'dev_search_code', pattern='needle', glob='composer/**/*.py')
        self.assertEqual(([], 0), (nothing['matches'], nothing['files_scanned']))
        self.assertIn('composer/**/*.py', nothing['note'])
        self.assertNotIn('note', self._call(self.admin, 'dev_search_code', pattern='absent'))
        listed = self._call(self.admin, 'dev_list_code', path='pkg', pattern='deep/*.py')
        self.assertEqual(['pkg/deep/b.py'], listed['paths'])

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

