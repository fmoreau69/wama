"""PICS FINS de l'onde — un service COMMUN (2026-10-21, `common/utils/waveform.py`, ROUTE §F3b).

Ils vivaient au transcriber (un fichier par transcription, un champ d'état, une tâche, une route) ;
ils suivent désormais le chemin de la copie de lecture. Held here :
  * the file lands in the user's HIDDEN folder and maps back to its original — so the nightly
    sweep and the integrity audit count it as DERIVED, never as an orphan to delete ;
  * one task per version of the media ; « pending », « failed », « ready » are read, not stored
    on a card ; a failure is retried when a page OPENS, not when it polls ;
  * a file older than its original is not served ;
  * the transcriber's route answers from the common service.
"""
import json
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.utils import video_compat as vc
from wama.common.utils import waveform

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'dense-peaks-tests'}}


class DerivedPathTest(SimpleTestCase):

    def test_the_peaks_live_in_the_hidden_folder_and_map_back_to_their_original(self):
        for original, peaks in (
                ('users/7/transcriber/input/talk.m4a', 'users/7/.preview/transcriber/input/talk.m4a.peaks.json'),
                ('system_assets/clip.wav', '.preview/system_assets/clip.wav.peaks.json')):
            self.assertEqual(peaks, waveform.dense_peaks_rel(original))
            self.assertEqual(original, vc.original_of_copy(peaks))

    def test_the_playback_copy_keeps_its_path_and_other_files_are_not_derived(self):
        self.assertEqual('users/7/.preview/a/b.avi.mp4', vc.playback_copy_rel('users/7/a/b.avi'))
        self.assertEqual('users/7/a/b.avi', vc.original_of_copy('users/7/.preview/a/b.avi.mp4'))
        self.assertEqual('', vc.original_of_copy('users/7/.preview/a/notes.txt'))


@override_settings(CACHES=LOCMEM)
class DensePeaksServiceTest(TestCase):

    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root, True)
        media = override_settings(MEDIA_ROOT=self.root)
        media.enable()
        self.addCleanup(media.disable)
        self.rel = 'users/7/transcriber/input/talk.wav'
        os.makedirs(os.path.dirname(self._abs(self.rel)))
        with open(self._abs(self.rel), 'wb') as out:
            out.write(b'RIFF-not-really-audio')

    def _abs(self, rel):
        return os.path.join(self.root, rel)

    def _ask(self, **kwargs):
        with mock.patch('wama.common.tasks.make_dense_peaks_task.delay') as delay, \
                self.captureOnCommitCallbacks(execute=True):
            state = waveform.dense_peaks(self.rel, **kwargs)
        return state, delay

    def test_a_missing_media_has_no_peaks_and_queues_nothing(self):
        with mock.patch('wama.common.tasks.make_dense_peaks_task.delay') as delay:
            self.assertEqual({'status': 'none'}, waveform.dense_peaks('users/7/nothing.wav'))
        delay.assert_not_called()

    def test_the_first_ask_queues_one_task_per_version_and_says_pending(self):
        state, delay = self._ask()
        self.assertEqual({'status': 'pending'}, state)
        delay.assert_called_once_with(self.rel)
        state, again = self._ask()
        self.assertEqual({'status': 'pending'}, state)
        again.assert_not_called()

    def test_computed_peaks_are_served_until_the_original_is_replaced(self):
        with mock.patch.object(waveform, 'compute_peaks', return_value=([0, 128, 255], 2.5)):
            self.assertTrue(waveform.make_dense_peaks(self.rel))
        stored = self._abs(waveform.dense_peaks_rel(self.rel))
        with open(stored, encoding='utf-8') as source:
            self.assertEqual(50, json.load(source)['bps'])
        self.assertEqual({'status': 'ready', 'peaks': [0, 128, 255], 'duration': 2.5},
                         waveform.dense_peaks(self.rel))
        later = os.path.getmtime(stored) + 10
        os.utime(self._abs(self.rel), (later, later))
        state, delay = self._ask()
        self.assertEqual('pending', state['status'], 'older than its original : recomputed')
        delay.assert_called_once()

    def test_a_failure_is_said_while_polling_and_retried_when_a_page_opens(self):
        self._ask()
        with mock.patch.object(waveform, 'compute_peaks', return_value=(None, 0)):
            self.assertFalse(waveform.make_dense_peaks(self.rel))
        state, delay = self._ask()
        self.assertEqual({'status': 'failed'}, state)
        delay.assert_not_called()
        state, delay = self._ask(retry_failed=True)
        self.assertEqual({'status': 'pending'}, state)
        delay.assert_called_once_with(self.rel)

    def test_the_sweep_keeps_live_peaks_and_removes_orphans(self):
        with mock.patch.object(waveform, 'compute_peaks', return_value=([1, 2], 1.0)):
            waveform.make_dense_peaks(self.rel)
        self.assertEqual({'seen': 1, 'removed': 0}, vc.sweep_orphan_playback_copies())
        os.remove(self._abs(self.rel))
        self.assertEqual({'seen': 1, 'removed': 1}, vc.sweep_orphan_playback_copies())
        self.assertFalse(os.path.exists(self._abs(waveform.dense_peaks_rel(self.rel))))

    def test_the_peaks_go_with_their_original(self):
        """The same rule as the playback copy : when a card releases its file, what was drawn from
        it goes too (`drop_playback_copy`, called by `safe_delete_file`)."""
        with mock.patch.object(waveform, 'compute_peaks', return_value=([1, 2], 1.0)):
            waveform.make_dense_peaks(self.rel)
        stored = self._abs(waveform.dense_peaks_rel(self.rel))
        self.assertTrue(os.path.exists(stored))
        self.assertTrue(vc.drop_playback_copy(self.rel))
        self.assertFalse(os.path.exists(stored))

    def test_a_scenario_witness_holds_its_peaks_without_a_task(self):
        waveform.hold_dense_peaks(self.rel)
        state, delay = self._ask()
        self.assertEqual({'status': 'pending'}, state)
        delay.assert_not_called()


@override_settings(CACHES=LOCMEM)
class SurfacePeaksRouteTest(TestCase):
    """A surface serves the fine peaks of a medium it reads (`data/?only=peaks&role=…`) from the
    common service — the correction page of the transcriber had its own route, file and state."""

    def setUp(self):
        from django.contrib.auth.models import Group

        from wama.accounts.permissions import GROUP_PREFIX
        from wama.transcriber.models import Transcript
        user = get_user_model().objects.create_user('dense_peaks_owner', password='x')
        user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.t = Transcript.objects.create(user=user, status='SUCCESS',
                                           audio='users/0/transcriber/input/fictif.wav')
        self.client.force_login(user)
        self.url = f'/common/surface/transcriber/correct/{self.t.pk}/data/?only=peaks&role=audio'

    def test_the_route_answers_from_the_common_service(self):
        ready = {'status': 'ready', 'peaks': [3], 'duration': 1.0}
        with mock.patch.object(waveform, 'dense_peaks', return_value=ready) as asked:
            response = self.client.get(self.url)
        self.assertEqual(ready, response.json())
        asked.assert_called_once_with(self.t.audio.name, retry_failed=True)

    def test_a_polling_page_does_not_retry_a_failure(self):
        with mock.patch.object(waveform, 'dense_peaks', return_value={'status': 'failed'}) as asked:
            self.client.get(self.url + '&poll=1')
        asked.assert_called_once_with(self.t.audio.name, retry_failed=False)
