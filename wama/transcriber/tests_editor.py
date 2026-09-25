"""Correction editor — the « Bornes » tool (`retime_segments`): move a junction, cut a section."""
import json

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.transcriber.models import Transcript

User = get_user_model()

WORDS = [{'word': ' ' + w, 'start': s, 'end': e, 'probability': 0.9}
         for w, s, e in (('le', 0.0, 0.2), ('chien', 0.2, 0.6), ('dort', 0.6, 1.0),
                         ('sur', 1.2, 1.4), ('le', 1.4, 1.5), ('tapis', 1.5, 1.9))]


class RetimeSegmentsTest(TestCase):

    def setUp(self):
        # `AppAccessMiddleware` redirects any account without the app's role BEFORE the view:
        # a view test goes through the gate, it does not bypass it (cf. tests_import_contract).
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        self.user = User.objects.create_user('transcriber_editor', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        self.item = Transcript.objects.create(
            user=self.user, audio='users/0/transcriber/input/fictif.wav', status='SUCCESS',
            text='le chien dort sur le tapis',
            segments_json=[{'speaker_id': 'SPEAKER_00', 'text': 'le chien dort sur le tapis',
                            'start_time': 0.0, 'end_time': 1.9, 'words': WORDS}])

    def _post(self, payload, item=None):
        return self.client.post(f'/transcriber/edit/{(item or self.item).pk}/retime/',
                                json.dumps(payload), content_type='application/json')

    def _sections(self):
        return [{'speaker_id': 'SPEAKER_00', 'text': 'le chien dort', 'start_time': 0.0,
                 'end_time': 1.0, 'words': WORDS[:3], 'reviewed': True},
                {'speaker_id': 'SPEAKER_01', 'text': 'sur le tapis', 'start_time': 1.1,
                 'end_time': 1.9, 'words': WORDS[3:]}]

    def test_moving_a_junction_moves_the_words_and_closes_it_into_one_boundary(self):
        answer = self._post({'op': 'move', 'time': 0.62, 'segments': self._sections()}).json()
        self.assertTrue(answer['ok'], answer)
        left, right = answer['segments']
        self.assertEqual(('le chien', 'dort sur le tapis'), (left['text'], right['text']))
        self.assertEqual(0.6, left['end_time'])
        self.assertEqual(left['end_time'], right['start_time'])
        self.assertTrue(left['reviewed'], 'the other keys of a section are kept')

    def test_the_scissors_cut_a_corrected_section_on_the_asr_words(self):
        """The section says « chat » where the ASR heard « chien »: re-anchored, then cut."""
        section = {'speaker_id': 'SPEAKER_00', 'text': 'le chat dort sur le tapis',
                   'start_time': 0.0, 'end_time': 1.9, 'words': WORDS}
        answer = self._post({'op': 'split', 'time': 1.1, 'segments': [section]}).json()
        self.assertTrue(answer['ok'], answer)
        first, second = answer['segments']
        self.assertEqual(('le chat dort', 'sur le tapis'), (first['text'], second['text']))
        self.assertEqual(1.1, first['end_time'], 'dropped in a silence: the boundary stays there')

    def test_a_refused_gesture_says_why_and_changes_nothing(self):
        answer = self._post({'op': 'split', 'time': 0.1,
                             'segments': [{'text': 'oui', 'start_time': 0, 'end_time': 1}]})
        self.assertEqual(200, answer.status_code)
        self.assertFalse(answer.json()['ok'])
        self.assertIn('au moins un mot', answer.json()['reason'])
        self.item.refresh_from_db()
        self.assertIsNone(self.item.corrected_segments_json, 'the tool never writes: autosave does')

    def test_a_malformed_request_is_refused(self):
        self.assertEqual(400, self._post({'op': 'move', 'time': 'x', 'segments': []}).status_code)
        self.assertEqual(400, self._post({'op': 'swap', 'time': 1, 'segments': [{}]}).status_code)

    def test_another_users_transcript_is_not_reachable(self):
        other = User.objects.create_user('transcriber_editor_other', password='x')
        theirs = Transcript.objects.create(user=other, audio='users/1/x.wav', status='SUCCESS')
        self.assertEqual(404, self._post({'op': 'split', 'time': 1, 'segments': [{}]},
                                         item=theirs).status_code)

    def test_the_editor_page_carries_the_tool_and_its_route(self):
        page = self.client.get(f'/transcriber/edit/{self.item.pk}/').content.decode()
        self.assertIn('id="boundaryToolBtn"', page)
        self.assertIn(f'/transcriber/edit/{self.item.pk}/retime/', page)

    def test_replace_fills_a_gap_with_a_new_section_of_the_neighbours_speaker(self):
        answer = self._post({'op': 'replace', 'start': 1.0, 'end': 1.2, 'speaker_id': 'SPEAKER_01',
                             'segments': [],
                             'words': [{'word': ' euh', 'start': 1.02, 'end': 1.15}]}).json()
        self.assertEqual([('euh', 'SPEAKER_01')],
                         [(s['text'], s['speaker_id']) for s in answer['segments']])


from django.core.cache import cache  # noqa: E402
from django.test import override_settings  # noqa: E402

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'transcriber-write-tests'}}


@override_settings(CACHES=LOCMEM)
class WriteModesTest(TestCase):
    """Write modes: the editor posts a cursor, a loop transcribes the wanted spans, the editor reads."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        cache.clear()
        self.user = User.objects.create_user('transcriber_writer', password='x')
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        self.item = Transcript.objects.create(
            user=self.user, audio='users/0/transcriber/input/fictif.wav', status='SUCCESS')

    def _cursor(self, payload):
        from unittest import mock
        with mock.patch('wama.transcriber.workers.live_write_task.delay') as delay:
            answer = self.client.post(f'/transcriber/edit/{self.item.pk}/write-cursor/',
                                      json.dumps(payload), content_type='application/json')
        return answer, delay

    def test_a_cursor_starts_one_loop_and_an_unknown_mode_is_refused(self):
        answer, delay = self._cursor({'mode': 'complement', 't': 3, 'wanted': [[4, 9]]})
        self.assertEqual({'ok': True, 'running': True, 'started': True}, answer.json())
        delay.assert_called_once_with(self.item.pk)
        self.assertEqual(400, self._cursor({'mode': 'erase', 't': 3})[0].status_code)

    def test_disabling_forgets_what_was_transcribed_so_a_new_pass_redoes_it(self):
        from wama.transcriber.workers import write_channel
        cache.set(write_channel(self.item.pk).key('done'), {'write': [[0, 5]]}, 60)
        self._cursor({'enabled': False})
        self.assertIsNone(cache.get(write_channel(self.item.pk).key('done')))

    def test_a_page_that_opens_does_not_replay_old_results(self):
        from wama.transcriber.workers import write_channel
        cache.set(write_channel(self.item.pk).key('results'), [{'id': 0}, {'id': 1}], 60)
        url = f'/transcriber/edit/{self.item.pk}/write-results/'
        self.assertEqual({'next': 2, 'running': False, 'results': []}, self.client.get(url).json())
        self.assertEqual([{'id': 1}], self.client.get(url + '?since=1').json()['results'])

    def _run_loop(self, cursor, busy=False):
        """The loop with a fake ASR that hears « bonjour » at the start of every span it is given."""
        from unittest import mock
        from wama.common.services import playhead_follow
        from wama.transcriber import workers

        spans = []

        def hear(backend, path, start, end, language=None):
            spans.append((start, end))
            return [{'word': ' bonjour', 'start': start + 0.1, 'end': start + 0.6, 'probability': 0.9}]

        asr = mock.MagicMock(display_name='fake')
        asr.load.return_value = True
        if busy:
            Transcript.objects.create(user=self.user, audio='x.wav', status='RUNNING')
        cache.set(workers.write_channel(self.item.pk).key('cursor'), cursor, 1)   # listener leaves
        real = playhead_follow.follow
        fast = lambda *a, **kw: real(*a, idle_seconds=0.05, poll_seconds=0.01, **kw)  # noqa: E731
        with mock.patch.object(workers, 'get_backend', return_value=asr),                 mock.patch.object(workers, '_transcribe_span', side_effect=hear),                 mock.patch.object(playhead_follow, 'follow', fast),                 mock.patch.object(workers, '_console'),                 mock.patch.object(workers, 'close_old_connections'):
            outcome = workers.live_write_task.run(self.item.pk)
        return outcome, spans, cache.get(workers.write_channel(self.item.pk).key('results')) or []

    def test_the_loop_transcribes_each_wanted_span_once_nearest_the_playhead_first(self):
        outcome, spans, results = self._run_loop(
            {'mode': 'write', 't': 10.0, 'wanted': [[0.0, 4.0], [12.0, 15.0]]})
        self.assertEqual({'ok': True, 'reason': 'idle'}, outcome)
        self.assertEqual([(12.0, 15.0), (0.0, 4.0)], spans, 'ahead of the playhead first, then behind')
        self.assertEqual(['bonjour', 'bonjour'], [r['text'] for r in results])
        self.assertEqual('write', results[0]['mode'])

    def test_a_long_span_is_transcribed_by_slices_of_the_whisper_window(self):
        _, spans, _ = self._run_loop({'mode': 'write', 't': 0.0, 'wanted': [[0.0, 70.0]]})
        self.assertEqual([(0.0, 30.0), (30.0, 60.0), (60.0, 70.0)], spans)

    def test_a_production_transcription_takes_the_gpu_back(self):
        outcome, spans, _ = self._run_loop({'mode': 'write', 't': 0.0, 'wanted': [[0.0, 4.0]]},
                                           busy=True)
        self.assertEqual('preempt', outcome['reason'])
        self.assertEqual([], spans)


class TranscriptionTaskOnSkeletonTest(TestCase):
    """The item task runs through the COMMON skeleton (`run_item_task`, 2026-09-25), and the ASR
    model stays loaded after a card (Fabien's decision: a batch on one engine no longer reloads)."""

    def setUp(self):
        from django.core.files.base import ContentFile
        from wama.common.services.ui_smoke import _wav_silence
        self.user = User.objects.create_user('transcriber_skeleton', password='x')
        self.item = Transcript(user=self.user, status='RUNNING', backend='auto',
                               enable_diarization=False)
        self.item.audio.save('skeleton.wav', ContentFile(_wav_silence(1.0, 8000)), save=False)
        self.item.save()
        self.addCleanup(lambda: self.item.audio.delete(save=False))

    def _run(self, asr):
        from unittest import mock
        from wama.transcriber import workers
        with mock.patch.object(workers, 'get_backend', return_value=asr), \
                mock.patch.object(workers, 'compute_waveform_peaks'), \
                mock.patch.object(workers, '_save_output_files'), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            workers.transcribe_without_preprocessing.run(self.item.pk)
        self.item.refresh_from_db()

    def _asr(self, fail=False):
        from unittest import mock
        from wama.common.backends.speech_to_text_base import TranscriptionResult, TranscriptionSegment
        asr = mock.MagicMock(display_name='Fake ASR', _current_model='fake-1')
        asr.name = 'fake'
        asr.load.return_value = True
        asr.transcribe.return_value = TranscriptionResult(
            success=not fail, text='bonjour à tous', language='fr', error='boom' if fail else None,
            segments=[TranscriptionSegment('', 0.0, 1.0, 'bonjour à tous')])
        return asr

    def test_a_card_succeeds_through_the_skeleton_and_the_model_stays_loaded(self):
        asr = self._asr()
        self._run(asr)
        self.assertEqual('SUCCESS', self.item.status)
        self.assertEqual(100, self.item.progress)
        self.assertEqual('bonjour à tous', self.item.text)
        self.assertEqual(1, len(self.item.segments_json))
        self.assertIsNotNone(self.item.finished_at)
        self.assertIsNotNone(self.item.processing_seconds)
        asr.unload.assert_not_called()

    def _vad_filter_passed(self, mode, rejects=False):
        from unittest import mock
        Transcript.objects.filter(pk=self.item.pk).update(vad_mode=mode, status='RUNNING')
        asr = self._asr()
        asr.name = 'whisper'
        probe = {'vad': 0.2, 'energy': 0.7, 'rejects': rejects}
        with mock.patch('wama.common.utils.speech_activity.vad_rejects_speech',
                        return_value=probe) as probed:
            self._run(asr)
        return asr.transcribe.call_args.kwargs.get('vad_filter'), probed.called

    def test_the_vad_setting_drives_the_whisper_filter(self):
        self.assertEqual((True, False), self._vad_filter_passed('on'))
        self.assertEqual((False, False), self._vad_filter_passed('off'))

    def test_auto_drops_the_filter_only_when_the_probe_says_it_rejects_speech(self):
        self.assertEqual((False, True), self._vad_filter_passed('auto', rejects=True))
        self.assertEqual((True, True), self._vad_filter_passed('auto', rejects=False))

    def test_a_probe_that_fails_keeps_the_filter(self):
        from unittest import mock
        from wama.transcriber.workers import _vad_filter_for
        self.item.vad_mode = 'auto'
        with mock.patch('wama.common.utils.speech_activity.vad_rejects_speech',
                        side_effect=RuntimeError('ffmpeg missing')):
            self.assertTrue(_vad_filter_for(self.item, self.item.audio.path))

    def test_the_settings_route_writes_the_vad_mode(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import GROUP_PREFIX
        self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')[0])
        self.client.force_login(self.user)
        resp = self.client.post(f'/transcriber/settings/{self.item.pk}/',
                                data=json.dumps({'vad_mode': 'off'}),
                                content_type='application/json')
        self.assertEqual(200, resp.status_code)
        self.assertEqual('off', resp.json()['vad_mode'])
        self.item.refresh_from_db()
        self.assertEqual('off', self.item.vad_mode)
        self.assertEqual('off', self.item.gear_data.get('vad-mode'))

    def test_an_engine_without_a_vad_filter_gets_no_such_argument(self):
        asr = self._asr()
        self._run(asr)
        self.assertNotIn('vad_filter', asr.transcribe.call_args.kwargs)

    def test_a_failed_transcription_is_a_failure_with_its_message(self):
        self._run(self._asr(fail=True))
        self.assertEqual('FAILURE', self.item.status)
        self.assertIn('boom', self.item.error_message)
        self.assertEqual(0, self.item.progress)
