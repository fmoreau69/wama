"""The PROCESS guard of the media (`common/utils/media_guard.py`, 2026-10-27) — no `rmtree` of
this process may wipe `media/` again, and no Django test starts outside the WAMA runner. Never
exercised on the real `media/` : the decision is read on the real paths, the refusal is exercised
on a throwaway root."""
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.utils import media_guard


class TheGuardIsInstalledInEveryDjangoProcessTest(SimpleTestCase):

    def test_rmtree_is_the_guarded_one(self):
        self.assertTrue(getattr(shutil.rmtree, 'wama_media_guard', False))

    def test_the_real_media_root_is_protected_even_when_the_runner_redirects_it(self):
        real = (Path(settings.BASE_DIR) / 'media').resolve()
        self.assertIn(real, media_guard._PROTECTED)
        self.assertNotEqual(real, Path(settings.MEDIA_ROOT).resolve(), 'the runner redirects MEDIA_ROOT')

    def test_the_real_paths_are_judged_without_deleting_anything(self):
        real = (Path(settings.BASE_DIR) / 'media').resolve()
        for refused in (real, real / 'users', real / 'media_library', real.parent, real.parent.parent):
            self.assertTrue(media_guard.refusal(refused), refused)
        for allowed in (real / 'users' / '424242', real / 'smoke_preview_during',
                        real / 'media_library' / 'system' / 'x', Path(tempfile.gettempdir()) / 'w'):
            self.assertEqual('', media_guard.refusal(allowed), allowed)


class TheGuardRejectsBeforeDeletingTest(SimpleTestCase):

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='wama_guard_'))
        self.root = self.base / 'media'
        for rel in ('users/1/a.txt', 'media_library/system/b.txt', 'smoke_preview_x/c.txt'):
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text('x')
        media_guard.install(self.root)
        self.addCleanup(media_guard._PROTECTED.remove, self.root.resolve())
        self.addCleanup(shutil.rmtree.original, self.base, True)

    def test_ignore_errors_does_not_swallow_the_refusal_and_nothing_is_deleted(self):
        for target in (self.root, self.root / 'users', self.root / 'media_library', self.base):
            with self.assertRaises(PermissionError, msg=str(target)):
                shutil.rmtree(target, ignore_errors=True)
        self.assertTrue((self.root / 'users/1/a.txt').exists())
        self.assertTrue((self.root / 'media_library/system/b.txt').exists())

    def test_a_user_folder_and_a_throwaway_folder_are_still_removable(self):
        shutil.rmtree(self.root / 'users' / '1')
        shutil.rmtree(self.root / 'smoke_preview_x')
        self.assertFalse((self.root / 'users' / '1').exists())
        self.assertFalse((self.root / 'smoke_preview_x').exists())
        self.assertTrue((self.root / 'media_library/system/b.txt').exists())


class NoDjangoTestStartsOutsideTheRunnerTest(SimpleTestCase):
    """The CAUSE of 2026-10-27 : a Django test played by `unittest` directly, on the real
    settings. Exercised on a throwaway root made « real » for the time of the test."""

    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix='wama_guard_'))
        self.addCleanup(shutil.rmtree, self.base, True)
        self.ran = []

    def _suite(self, base):
        ran = self.ran

        class Probe(base):
            def test_probe(self):
                ran.append(type(self).__mro__[1].__name__)
        return unittest.TestSuite([Probe('test_probe')])

    def _as_if_outside_the_runner(self):
        """MEDIA_ROOT is the protected root, as it is when nothing redirected it."""
        protected = mock.patch.object(media_guard, '_PROTECTED', [self.base.resolve()])
        protected.start()
        self.addCleanup(protected.stop)
        return override_settings(MEDIA_ROOT=str(self.base))

    def test_the_guard_wraps_suites_and_tests_in_every_django_process(self):
        self.assertTrue(getattr(unittest.TestSuite.run, 'wama_media_guard', False))
        self.assertTrue(getattr(unittest.TestCase.run, 'wama_media_guard', False))

    def test_a_django_suite_is_refused_before_its_first_test(self):
        with self._as_if_outside_the_runner():
            with self.assertRaises(PermissionError):
                unittest.TextTestRunner(stream=io.StringIO()).run(self._suite(SimpleTestCase))
            with self.assertRaises(PermissionError):
                self._suite(SimpleTestCase)._tests[0].run()
        self.assertEqual([], self.ran, 'the refused test never started')

    def test_a_process_that_is_not_manage_py_test_is_refused_even_with_media_and_base_isolated(self):
        """`get_runner(settings)` in a script isolates the media and the database, not the cache
        nor the Celery broker — decided at settings load on the command line (`runtime_side`)."""
        with override_settings(WAMA_RUNNING_TESTS=False):
            with self.assertRaises(PermissionError) as refused:
                unittest.TextTestRunner(stream=io.StringIO()).run(self._suite(SimpleTestCase))
        self.assertIn('manage.py test', str(refused.exception))
        self.assertEqual([], self.ran)

    def test_a_test_without_django_and_the_runner_itself_are_let_through(self):
        with self._as_if_outside_the_runner():
            result = unittest.TextTestRunner(stream=io.StringIO()).run(
                self._suite(unittest.TestCase))
        self.assertTrue(result.wasSuccessful())
        # Under the runner (this very test) : MEDIA_ROOT redirected, test database — let through.
        result = unittest.TextTestRunner(stream=io.StringIO()).run(self._suite(SimpleTestCase))
        self.assertTrue(result.wasSuccessful())
        self.assertEqual(['TestCase', 'SimpleTestCase'], self.ran)

    def test_a_test_with_a_database_is_refused_on_the_real_database(self):
        real = media_guard._REAL_DATABASES[0]
        probe = self._suite(TestCase)._tests[0]
        self.assertIn('vraie', media_guard.test_refusal(probe, str(self.base), real))
        self.assertEqual('', media_guard.test_refusal(probe, str(self.base), 'test_' + real))
        self.assertEqual('', media_guard.test_refusal(self._suite(SimpleTestCase)._tests[0],
                                                      str(self.base), real),
                         'a test without database does not need a test database')


class TheRealDatabaseIsReadAtStartupTest(TestCase):
    """A `TestCase` : the runner then always mounts a test database (a campaign of
    `SimpleTestCase` alone mounts none and keeps the real name — harmless, they cannot query)."""

    def test_the_real_database_is_read_before_the_runner_swaps_in_the_test_one(self):
        from django.db import connection
        self.assertTrue(media_guard._REAL_DATABASES)
        self.assertNotIn(connection.settings_dict['NAME'], media_guard._REAL_DATABASES)
