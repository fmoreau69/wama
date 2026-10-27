"""The PROCESS guard of the media (`common/utils/media_guard.py`, 2026-10-27) — no `rmtree` of
this process may wipe `media/` again. Never exercised on the real `media/` : the decision is read
on the real paths, the refusal is exercised on a throwaway root."""
import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

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


class TheGuardRefusesBeforeDeletingTest(SimpleTestCase):

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
