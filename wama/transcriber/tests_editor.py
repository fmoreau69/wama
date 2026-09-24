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
