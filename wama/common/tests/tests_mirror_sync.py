"""
`mirror_tree` et les liens symboliques INTERNES (2026-09-28).

Un cache HuggingFace porte chaque poids dans `blobs/` et un LIEN vers lui dans `snapshots/` ;
`is_file()` suit les liens, et un dépôt sauvegardé pour la première fois voyait chaque poids
recopié une seconde fois (58 Go mesurés au distant). Un lien vers un fichier DE la source est
désormais REPRODUIT comme lien ; il n'est décrit dans `LINKS_MANIFEST` que si la destination
refuse les liens, et le tirage le recrée. Ces tests tiennent les DEUX sens — une sauvegarde qui
ne se restaure pas n'en est pas une : la première version de ce correctif, qui décrivait tous les
liens au lieu de les reproduire, aurait rendu des snapshots VIDES au tirage.
"""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase

from wama.common.services.mirror_sync import LINKS_MANIFEST, mirror_tree


def _can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        try:
            os.symlink('x', Path(tmp) / 'probe')
            return True
        except (OSError, NotImplementedError):
            return False


def _refuse_links(*args, **kwargs):
    raise OSError('symlinks not supported on this destination')


@unittest.skipUnless(_can_symlink(), "symlinks unavailable on this host (Windows without developer mode)")
class InternalLinksTest(SimpleTestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.base = Path(self._tmp.name)
        self.src = self.base / 'src'
        self.dest = self.base / 'dest'
        self.dest.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _hf_snapshot(self, root: Path):
        """The real huggingface_hub layout: one blob, one snapshot link pointing at it."""
        repo = root / 'diffusion' / 'fam' / 'models--Org--Name'
        (repo / 'blobs').mkdir(parents=True)
        (repo / 'blobs' / 'abc').write_bytes(b'w' * 4096)
        (repo / 'snapshots' / 'rev').mkdir(parents=True)
        os.symlink('../../blobs/abc', repo / 'snapshots' / 'rev' / 'model.safetensors')
        return repo

    def _link_rel(self, repo, root):
        return (repo.relative_to(root) / 'snapshots' / 'rev' / 'model.safetensors').as_posix()

    def test_an_internal_link_is_reproduced_as_a_link_not_copied_again(self):
        repo = self._hf_snapshot(self.src)
        summary = mirror_tree(self.src, self.dest)
        link = self.dest / self._link_rel(repo, self.src)
        self.assertTrue((self.dest / repo.relative_to(self.src) / 'blobs' / 'abc').is_file())
        self.assertTrue(link.is_symlink(), "the snapshot entry must stay a LINK, not a second copy")
        self.assertEqual('../../blobs/abc', os.readlink(link))
        self.assertFalse((self.dest / LINKS_MANIFEST).exists(), "no manifest when links are accepted")
        self.assertEqual((1, 1, 1), (summary['copied'], summary['linked'], summary['total_files']))

    def test_a_destination_refusing_links_gets_them_described_merged_in_the_manifest(self):
        (self.dest / LINKS_MANIFEST).write_text(json.dumps({'old/link': '../blob'}), encoding='utf-8')
        repo = self._hf_snapshot(self.src)
        with patch('wama.common.services.mirror_sync.os.symlink', _refuse_links):
            summary = mirror_tree(self.src, self.dest)
        manifest = json.loads((self.dest / LINKS_MANIFEST).read_text(encoding='utf-8'))
        self.assertEqual('../../blobs/abc', manifest[self._link_rel(repo, self.src)])
        self.assertIn('old/link', manifest, "the archive is cumulative: earlier entries stay")
        self.assertFalse((self.dest / self._link_rel(repo, self.src)).exists())
        self.assertTrue(summary['success'])

    def test_a_link_already_on_the_remote_comes_back_as_a_link_on_restore(self):
        """THE case the first version broke: the remote already holds real links (older repos)."""
        remote = self.base / 'remote'
        repo = self._hf_snapshot(remote)
        summary = mirror_tree(remote, self.dest)
        restored = self.dest / self._link_rel(repo, remote)
        self.assertTrue(restored.is_symlink())
        self.assertEqual(b'w' * 4096, restored.read_bytes())
        self.assertEqual(1, summary['copied'], "only the blob travels")
        self.assertFalse((self.dest / LINKS_MANIFEST).exists(), "no manifest written into the local tree")

    def test_a_restore_recreates_manifest_links_and_ignores_an_old_full_copy(self):
        """A remote that could not hold links: blob + manifest + the full copy an older pass left
        at the link's path. The link comes back as a LINK — the old copy is not pulled."""
        remote = self.base / 'remote'
        repo = remote / 'diffusion' / 'fam' / 'models--Org--Name'
        (repo / 'blobs').mkdir(parents=True)
        (repo / 'blobs' / 'abc').write_bytes(b'w' * 4096)
        rel_link = self._link_rel(repo, remote)
        (remote / rel_link).parent.mkdir(parents=True)
        (remote / rel_link).write_bytes(b'w' * 4096)                   # the pre-fix duplicate
        (remote / LINKS_MANIFEST).write_text(json.dumps({rel_link: '../../blobs/abc'}))
        summary = mirror_tree(remote, self.dest)
        restored = self.dest / rel_link
        self.assertTrue(restored.is_symlink())
        self.assertEqual(b'w' * 4096, restored.read_bytes())
        self.assertEqual(1, summary['copied'], "only the blob travels")
        self.assertFalse((self.dest / LINKS_MANIFEST).exists())

    def test_a_link_pointing_outside_the_source_is_still_copied(self):
        """No other copy of an EXTERNAL target exists in the archive: its content must travel."""
        outside = self.base / 'elsewhere.bin'
        outside.write_bytes(b'e' * 100)
        self.src.mkdir()
        os.symlink(outside, self.src / 'pointer.bin')
        summary = mirror_tree(self.src, self.dest)
        self.assertEqual(b'e' * 100, (self.dest / 'pointer.bin').read_bytes())
        self.assertFalse((self.dest / 'pointer.bin').is_symlink())
        self.assertEqual(0, summary['linked'])

    def test_an_old_full_copy_at_the_link_path_is_left_alone(self):
        """Backup direction: a full copy from an older pass is not overwritten nor removed —
        the mirror never deletes remotely; `dedup_remote_links` is the explicit gesture."""
        repo = self._hf_snapshot(self.src)
        old = self.dest / self._link_rel(repo, self.src)
        old.parent.mkdir(parents=True)
        old.write_bytes(b'w' * 4096)
        mirror_tree(self.src, self.dest)
        self.assertFalse(old.is_symlink())
        self.assertEqual(b'w' * 4096, old.read_bytes())

    def test_a_dry_run_counts_links_and_writes_nothing(self):
        self._hf_snapshot(self.src)
        summary = mirror_tree(self.src, self.dest, dry_run=True)
        self.assertEqual(1, summary['linked'])
        self.assertEqual([], [p for p in self.dest.iterdir() if p.name != '.wama_test'])


class PartialLossRestoreTest(SimpleTestCase):
    """The pull of a PARTIAL loss (2026-10-27, `media/` wiped then restored) : a local file
    changed since the backup must never be replaced by its older version."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.remote, self.local = base / 'remote', base / 'local'
        for rel, data in (('users/1/kept.abc', b'X:1'), ('users/1/edited.abc', b'X:1'),
                          ('users/1/lost.wav', b'RIFF')):
            (self.remote / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.remote / rel).write_bytes(data)
        (self.local / 'users/1').mkdir(parents=True)
        (self.local / 'users/1/kept.abc').write_bytes(b'X:1')
        (self.local / 'users/1/edited.abc').write_bytes(b'X:1 corrected by hand since')

    def test_missing_only_brings_back_the_lost_and_never_touches_what_is_there(self):
        summary = mirror_tree(self.remote, self.local, keep_existing=True)
        self.assertEqual(b'RIFF', (self.local / 'users/1/lost.wav').read_bytes())
        self.assertEqual(b'X:1 corrected by hand since',
                         (self.local / 'users/1/edited.abc').read_bytes())
        self.assertEqual((1, 2), (summary['copied'], summary['skipped']))

    def test_counter_proof_the_default_pull_replaces_a_file_changed_since_the_backup(self):
        mirror_tree(self.remote, self.local)
        self.assertEqual(b'X:1', (self.local / 'users/1/edited.abc').read_bytes())

    def test_overwrite_and_keep_existing_exclude_each_other(self):
        with self.assertRaises(ValueError):
            mirror_tree(self.remote, self.local, overwrite=True, keep_existing=True)

    def test_the_command_pulls_the_missing_only_without_asking_for_yes(self):
        from io import StringIO

        from django.core.management import call_command
        from django.test import override_settings
        with patch.dict(os.environ, {'WAMA_MEDIA_BACKUP_PATH': str(self.remote)}), \
                override_settings(MEDIA_ROOT=str(self.local)):
            call_command('restore_backup', domain='media', missing_only=True, stdout=StringIO())
        self.assertTrue((self.local / 'users/1/lost.wav').is_file())
        self.assertEqual(b'X:1 corrected by hand since',
                         (self.local / 'users/1/edited.abc').read_bytes())


class KnownOnlyRestoreTest(TestCase):
    """The pull BOUNDED to what the database still knows (`restore_backup --known-only`, Fabien's
    decision of 2026-10-28) : the backup never deletes, so it keeps test accounts, deleted
    accounts and old app folders."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from wama.common.services.nightly_tests import TEST_USERNAME
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        base = Path(self._tmp.name)
        self.remote, self.local = base / 'remote', base / 'local'
        self.local.mkdir()
        from django.db import models
        from wama.common.tests.tests_queue_delete_contract import _instance
        from wama.common.utils.preview_registry import PreviewRegistry
        users = get_user_model().objects
        real = users.create_user('known_only_real', password='x')
        test = users.get_or_create(username=TEST_USERNAME)[0]
        # Real cards, in the OLD layout `<app>/<id>/output/` : one of a real account (it travels),
        # one of the test account (its witness never does, wherever it is stored).
        model = PreviewRegistry.get_model('converter')
        field = next(f.name for f in model._meta.concrete_fields if isinstance(f, models.FileField))
        for account, rel in ((real, 'legacyapp/1/output/still_referenced.png'),
                             (test, 'legacyapp/2/output/witness.png')):
            card = _instance(model, account)
            setattr(card, field, rel)
            card.save()
        self.files = {
            f'users/{real.pk}/composer/output/score.abc': True,
            f'users/{test.pk}/composer/output/witness.abc': False,
            'users/999999/composer/output/gone_account.abc': False,
            'media_library/system/voices/default.wav': True,
            'legacyapp/1/output/still_referenced.png': True,
            'legacyapp/2/output/witness.png': False,
            'legacyapp/1/output/unreferenced.png': False,
            '~Archives/old.txt': False,
            # A file at the ROOT belongs to no app and no account : the user put it there (the
            # two `WAMA_Presentation*.wav` of 2026-10-27 — the unreferenced one had been missed).
            'Presentation_voice.wav': True,
        }
        for rel in self.files:
            (self.remote / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.remote / rel).write_bytes(b'x')

    def test_only_what_the_database_knows_comes_back(self):
        from io import StringIO

        from django.core.management import call_command
        from django.test import override_settings
        with patch.dict(os.environ, {'WAMA_MEDIA_BACKUP_PATH': str(self.remote)}), \
                override_settings(MEDIA_ROOT=str(self.local)):
            call_command('restore_backup', domain='media', known_only=True, missing_only=True,
                         stdout=StringIO())
        self.assertEqual({rel: kept for rel, kept in self.files.items()},
                         {rel: (self.local / rel).is_file() for rel in self.files})

    def test_known_only_is_refused_outside_the_media(self):
        from django.core.management import CommandError, call_command
        with self.assertRaises(CommandError):
            call_command('restore_backup', domain='models', known_only=True, dry_run=True)


class LastRunKeptTest(SimpleTestCase):
    """The last FINISHED run of a mirror is kept without expiry (2026-09-30): progress lives 24 h,
    and the « Backup models » line vanished a day after a manual run while the nightly media
    one stayed."""

    KEY = 'tests:mirror_last_run'

    def setUp(self):
        from django.core.cache import cache
        cache.delete(self.KEY)
        cache.delete(self.KEY + ':last')

    tearDown = setUp   # une clé sans expiration ne doit pas rester dans le cache réel

    def _run(self, runner):
        from wama.common.services.mirror_sync import run_mirror_job
        return run_mirror_job(runner, cache_key=self.KEY, task_id='t', label='test', ttl=60)

    def test_a_success_is_remembered_with_its_date_and_counts(self):
        from wama.common.services.mirror_sync import last_mirror_run
        self._run(lambda cb: {'success': True, 'copied': 3, 'skipped': 7, 'failed': 0,
                              'copied_mb': 1.5, 'total_files': 10})
        last = last_mirror_run(self.KEY)
        self.assertEqual(('SUCCESS', 3, 7), (last['state'], last['copied'], last['skipped']))
        self.assertIn('finished_at', last)

    def test_a_failure_is_remembered_too(self):
        from wama.common.services.mirror_sync import last_mirror_run

        def boom(cb):
            raise OSError('NAS injoignable')
        with self.assertRaises(OSError):
            self._run(boom)
        last = last_mirror_run(self.KEY)
        self.assertEqual('FAILURE', last['state'])
        self.assertIn('NAS injoignable', last['errors'][0])

    def test_a_running_state_does_not_overwrite_the_last_run(self):
        from wama.common.services.mirror_sync import last_mirror_run
        self._run(lambda cb: {'success': True, 'copied': 1, 'skipped': 0, 'failed': 0,
                              'copied_mb': 0.0})
        seen = {}
        self._run(lambda cb: (cb({'processed': 1}), seen.update(last=last_mirror_run(self.KEY)),
                              {'success': True, 'copied': 2, 'skipped': 0, 'failed': 0,
                               'copied_mb': 0.0})[-1])
        self.assertEqual(1, seen['last']['copied'], 'while running, the screen keeps the last run')

    def test_the_models_backup_is_scheduled_every_night(self):
        from django.conf import settings
        entry = settings.CELERY_BEAT_SCHEDULE.get('backup-models-daily') or {}
        self.assertEqual('model_manager.backup_all_models', entry.get('task'))
