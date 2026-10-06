"""COPIE DE LECTURE — une vidéo que le navigateur ne lit pas en reçoit une dès son import, servie
par l'aperçu seulement (2026-10-06, décision de Fabien ; `common/utils/video_compat.py`).

Held here, and above all what no error would reveal :
  * the ORIGINAL is never rewritten, moved or removed — imported or POINTED, its bytes stay ;
  * the copy lands in the user's HIDDEN folder (`users/<id>/.preview/…`), never next to the
    original, never in a connected folder ;
  * the verdict reads the container, the H.264 profile and the pixels — not the codec name alone
    (`SEQ08-01.mp4` : an AVI under a `.mp4` name, H.264 High 4:4:4, judged playable before) ;
  * the preview serves the copy only while it is up to date ; orphans are swept.
"""
import os
import shutil
import subprocess
import tempfile
from unittest import mock

import cv2
import numpy as np
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings

from wama.common.utils import video_compat as vc

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'playback-copy-tests'}}


def _write_avi(path, frames=10):
    """A short MJPG video in an AVI container — what a browser cannot read."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'MJPG'), 10, (64, 48))
    for i in range(frames):
        image = np.zeros((48, 64, 3), dtype=np.uint8)
        image[:, i * 4:(i + 1) * 4] = 255
        writer.write(image)
    writer.release()


class PlayabilityVerdictTest(SimpleTestCase):

    def test_the_seq08_case_is_not_playable_for_its_container_then_its_profile(self):
        seq08 = {'container': 'avi', 'codec': 'h264', 'profile': 'high 4:4:4 predictive',
                 'pix_fmt': 'yuv420p'}
        self.assertEqual((False, 'conteneur avi'), vc.playability(seq08))
        same_in_mp4 = dict(seq08, container='mov,mp4,m4a,3gp,3g2,mj2')
        self.assertEqual((False, 'profil H.264 high 4:4:4 predictive'), vc.playability(same_in_mp4))

    def test_what_browsers_read_is_playable_and_hevc_is_not_counted_on(self):
        mp4 = 'mov,mp4,m4a,3gp,3g2,mj2'
        self.assertEqual((True, ''), vc.playability(
            {'container': mp4, 'codec': 'h264', 'profile': 'high', 'pix_fmt': 'yuv420p'}))
        self.assertEqual((True, ''), vc.playability(
            {'container': 'matroska,webm', 'codec': 'vp9', 'profile': '', 'pix_fmt': 'yuv420p'}))
        self.assertFalse(vc.playability(
            {'container': mp4, 'codec': 'hevc', 'profile': 'main', 'pix_fmt': 'yuv420p'})[0])
        self.assertFalse(vc.playability(
            {'container': mp4, 'codec': 'h264', 'profile': 'high', 'pix_fmt': 'yuv444p'})[0])
        self.assertFalse(vc.playability(None)[0])

    def test_the_copy_lives_in_the_hidden_folder_and_maps_back_to_its_original(self):
        for original, copy in (
                ('users/7/anonymizer/input/SEQ08-01.mp4', 'users/7/.preview/anonymizer/input/SEQ08-01.mp4.mp4'),
                ('users/7/temp/rushes/a.avi', 'users/7/.preview/temp/rushes/a.avi.mp4'),
                ('system_assets/clip.avi', '.preview/system_assets/clip.avi.mp4')):
            self.assertEqual(copy, vc.playback_copy_rel(original))
            self.assertEqual(original, vc.original_of_copy(copy))


@override_settings(CACHES=LOCMEM)
class PlaybackCopyOnDiskTest(SimpleTestCase):

    def setUp(self):
        if not shutil.which('ffmpeg'):
            self.skipTest('ffmpeg absent')
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        self.rel = 'users/7/temp/rushes/clip.mp4'         # an AVI under a .mp4 name, like SEQ08
        _write_avi(os.path.join(self.root, self.rel))

    def _bytes(self, rel):
        with open(os.path.join(self.root, rel), 'rb') as fh:
            return fh.read()

    def test_a_copy_is_made_aside_playable_and_the_original_is_untouched(self):
        before = self._bytes(self.rel)
        copy = vc.make_playback_copy(self.rel)
        self.assertEqual('users/7/.preview/temp/rushes/clip.mp4.mp4', copy)
        self.assertTrue(vc.playability(vc.probe_video(os.path.join(self.root, copy)))[0])
        self.assertEqual(before, self._bytes(self.rel), 'the original keeps its bytes')
        self.assertEqual(['clip.mp4'], os.listdir(os.path.join(self.root, 'users/7/temp/rushes')),
                         'nothing written next to the original')
        stamp = os.path.getmtime(os.path.join(self.root, copy))
        self.assertEqual(copy, vc.make_playback_copy(self.rel), 'idempotent')
        self.assertEqual(stamp, os.path.getmtime(os.path.join(self.root, copy)))

    def test_a_playable_video_gets_no_copy(self):
        good = 'users/7/temp/good.mp4'
        subprocess.run(['ffmpeg', '-y', '-v', 'error', '-i', os.path.join(self.root, self.rel),
                        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', os.path.join(self.root, good)],
                       check=True)
        self.assertEqual('', vc.make_playback_copy(good))
        self.assertFalse(os.path.exists(os.path.join(self.root, 'users/7/.preview/temp/good.mp4.mp4')))

    def test_a_stale_copy_is_not_served_and_an_orphan_is_swept(self):
        copy = vc.make_playback_copy(self.rel)
        self.assertEqual(copy, vc.playback_copy_for(self.rel))
        later = os.path.getmtime(os.path.join(self.root, copy)) + 10
        os.utime(os.path.join(self.root, self.rel), (later, later))   # the original is replaced
        self.assertEqual('', vc.playback_copy_for(self.rel), 'older than its original : not served')
        os.remove(os.path.join(self.root, self.rel))
        self.assertEqual({'seen': 1, 'removed': 1}, vc.sweep_orphan_playback_copies())
        self.assertFalse(os.path.exists(os.path.join(self.root, copy)))

    def test_the_preview_swaps_a_video_url_for_its_fresh_copy_only(self):
        from wama.common.utils.preview_utils import with_playback_copy
        request = RequestFactory().get('/')
        url = 'http://testserver/media/' + self.rel
        untouched = with_playback_copy({'url': url, 'mime_type': 'video/mp4'}, request)
        self.assertEqual(url, untouched['url'], 'no copy yet : the original, as before')
        copy = vc.make_playback_copy(self.rel)
        served = with_playback_copy({'url': url + '?v=3', 'mime_type': 'video/mp4'}, request)
        self.assertEqual('http://testserver/media/' + copy, served['url'])
        self.assertTrue(served['playback_copy'])
        image = {'url': 'http://testserver/media/users/7/temp/a.png', 'mime_type': 'image/png'}
        self.assertEqual(image['url'], with_playback_copy(dict(image), request)['url'])


@override_settings(CACHES=LOCMEM)
class CreatedAtImportTest(TestCase):
    """The receiver : any card that CARRIES a video queues its copy once — whatever the import
    road ; a save that does not touch the file field (progress, status) queues nothing."""

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        self.user = get_user_model().objects.create_user('playback_copy_owner', password='x')
        # POINTED : the card designates a file of the user's temp, where it already lives.
        self.rel = f'users/{self.user.id}/temp/rushes/SEQ.mp4'
        _write_avi(os.path.join(self.root, self.rel))

    def _create(self):
        from wama.anonymizer.models import Media
        with mock.patch('wama.common.tasks.make_playback_copy_task.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            media = Media.objects.create(user=self.user, file=self.rel, file_ext='.mp4',
                                         media_type='video', status='PENDING')
        return media, delay

    def test_a_card_carrying_a_video_queues_its_copy_once(self):
        media, delay = self._create()
        delay.assert_called_once_with(self.rel)
        with mock.patch('wama.common.tasks.make_playback_copy_task.delay') as again, \
                self.captureOnCommitCallbacks(execute=True):
            media.save()                                  # same file version : not twice
        again.assert_not_called()

    def test_a_save_that_does_not_touch_the_file_is_not_even_looked_at(self):
        """Progress and status saves come every second : they must not stat the file."""
        media, _delay = self._create()
        with mock.patch.object(vc, 'schedule_playback_copy') as schedule:
            media.status = 'RUNNING'
            media.save(update_fields=['status'])
            schedule.assert_not_called()
            media.save(update_fields=['file'])
            schedule.assert_called_once_with(self.rel)

    def test_the_copy_of_a_pointed_file_never_lands_next_to_it(self):
        self._create()
        copy = vc.make_playback_copy(self.rel) if shutil.which('ffmpeg') else ''
        if copy:
            self.assertTrue(copy.startswith(f'users/{self.user.id}/.preview/temp/rushes/'))
        self.assertEqual(['SEQ.mp4'], os.listdir(os.path.join(
            self.root, f'users/{self.user.id}/temp/rushes')))

    def test_a_connected_folder_path_is_never_written(self):
        """A card never designates `mounts/…` (a connected folder is COPIED at import) ; even
        handed one, nothing is queued : the path does not exist under MEDIA_ROOT."""
        self.assertFalse(vc.schedule_playback_copy('mounts/3/rushes/SEQ.mp4'))


class TheTreeWalkersLeaveTheCopiesAloneTest(SimpleTestCase):
    """Walkers of the media tree must not take a copy for what it is not : an ORPHAN or a STRAY
    file (integrity — whose nightly budget of strays is 2), a DOUBLE to merge, or a file to back
    up (it derives from an original that is backed up)."""

    def test_integrity_counts_no_copy_as_orphan_or_stray(self):
        from wama.common.management.commands import check_media_integrity as integrity
        root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, root, True)
        for rel in ('users/7/.preview/anonymizer/input/a.avi.mp4', '.preview/media_library/system/b.avi.mp4'):
            os.makedirs(os.path.dirname(os.path.join(root, rel)), exist_ok=True)
            open(os.path.join(root, rel), 'wb').close()
        from pathlib import Path
        with mock.patch.object(integrity, '_references_vives', return_value={}):
            measured = integrity.measure(Path(root))
        self.assertEqual(([], []), (measured['orphans'], measured['stray']))

    def test_dedupe_and_backup_skip_the_hidden_folder(self):
        from wama.common.management.commands import dedupe_user_media
        self.assertIn(vc.PLAYBACK_DIR, dedupe_user_media.EXCLUS)
        from wama.common.services import media_backup
        with mock.patch.object(media_backup, 'mirror_tree') as mirror, \
                mock.patch.object(media_backup, 'media_root', return_value=mock.Mock(is_dir=lambda: True)), \
                mock.patch.object(media_backup, 'remote_media_path', return_value='/nas'):
            media_backup.backup_all_media()
        self.assertEqual((vc.PLAYBACK_DIR,), mirror.call_args.kwargs['exclude'])


class DeletionDropsTheCopyTest(TestCase):

    def test_safe_delete_file_takes_the_playback_copy_with_the_original(self):
        from wama.common.utils import queue_duplication
        instance = mock.Mock()
        instance.clip = mock.Mock()
        instance.clip.name = 'users/7/anonymizer/output/x.avi'
        with mock.patch.object(queue_duplication, 'owns_file', return_value=True), \
                mock.patch.object(queue_duplication, 'is_shared_elsewhere', return_value=False), \
                mock.patch('wama.common.utils.video_compat.drop_playback_copy') as drop:
            self.assertTrue(queue_duplication.safe_delete_file(instance, 'clip'))
        drop.assert_called_once_with('users/7/anonymizer/output/x.avi')
