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

    #: Ce que la sonde des langues « entend » (jamais le vrai modèle `tiny` dans un test).
    heard = [('fr', 0.95)]

    def _run(self, asr, task='transcribe_without_preprocessing'):
        from unittest import mock
        from wama.transcriber import workers
        with mock.patch.object(workers, 'get_backend', return_value=asr), \
                mock.patch.object(workers, 'compute_waveform_peaks'), \
                mock.patch.object(workers, '_save_output_files'), \
                mock.patch('wama.common.utils.spoken_language.probe_languages',
                           return_value=self.heard) as self.probed, \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            getattr(workers, task).run(self.item.pk)
        self.item.refresh_from_db()

    def _asr(self, fail=False):
        from unittest import mock
        from wama.common.backends.speech_to_text_base import TranscriptionResult, TranscriptionSegment
        asr = mock.MagicMock(display_name='Fake ASR', _current_model='fake-1')
        asr.name = 'fake'
        # Une capacité se DÉCLARE : un MagicMock répondrait « vrai » à toute question.
        asr.supports_vad_filter = False
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
        asr.supports_vad_filter = True
        probe = {'vad': 0.2, 'energy': 0.7, 'rejects': rejects}
        with mock.patch('wama.common.utils.speech_activity.vad_rejects_speech',
                        return_value=probe) as probed:
            self._run(asr)
        return asr.transcribe.call_args.kwargs.get('vad_filter'), probed.called

    def test_every_engine_without_native_diarization_goes_through_pyannote(self):
        """The DECLARED capability decides, no longer a list of names — the March list
        (`whisper`, `qwen_asr`) left NeMo undiarized and would have left out any remote engine."""
        from unittest import mock
        diarized = []
        for engine, native in (('nemo', False), ('albert', False), ('whisper', False),
                               ('vibevoice', True)):
            Transcript.objects.filter(pk=self.item.pk).update(enable_diarization=True,
                                                              status='RUNNING')
            asr = self._asr()
            asr.name = engine
            asr.supports_diarization = native
            with mock.patch('wama.common.backends.pyannote_diarizer.is_available',
                            return_value=True), \
                    mock.patch('wama.common.backends.pyannote_diarizer.diarize',
                               side_effect=lambda path, segments, *a, **k: segments) as diarize:
                self._run(asr)
            if diarize.called:
                diarized.append(engine)
        self.assertEqual(['nemo', 'albert', 'whisper'], diarized)

    def test_the_vad_setting_drives_the_whisper_filter(self):
        self.assertEqual((True, False), self._vad_filter_passed('on'))
        self.assertEqual((False, False), self._vad_filter_passed('off'))

    def test_auto_drops_the_filter_only_when_the_probe_says_it_rejects_speech(self):
        self.assertEqual((False, True), self._vad_filter_passed('auto', rejects=True))
        self.assertEqual((True, True), self._vad_filter_passed('auto', rejects=False))

    def test_the_auto_decision_is_written_both_ways_with_its_rates(self):
        """A filter KEPT used to leave no trace (lot #489, 2026-09-30)."""
        from unittest import mock
        from wama.transcriber.workers import _vad_filter_for
        self.item.vad_mode = 'auto'
        for rejects, expected in ((False, 'Filtre de parole gardé'),
                                  (True, 'Filtre de parole désactivé')):
            probe = {'vad': 0.41, 'energy': 0.62, 'rejects': rejects, 'windows': 12}
            with mock.patch('wama.common.utils.speech_activity.vad_rejects_speech',
                            return_value=probe), \
                    mock.patch('wama.transcriber.workers._console') as console:
                _vad_filter_for(self.item, self.item.audio.path)
            said = console.call_args.args[1]
            self.assertIn(expected, said)
            self.assertIn('41 %', said.replace('41%', '41 %'))
            self.assertIn('12 passages', said)

    def test_a_probe_that_fails_keeps_the_filter(self):
        from unittest import mock
        from wama.transcriber.workers import _vad_filter_for
        self.item.vad_mode = 'auto'
        with mock.patch('wama.common.utils.speech_activity.vad_rejects_speech',
                        side_effect=RuntimeError('ffmpeg missing')):
            self.assertTrue(_vad_filter_for(self.item, self.item.audio.path))

    def test_an_engine_without_a_vad_filter_gets_no_such_argument(self):
        asr = self._asr()
        self._run(asr)
        self.assertNotIn('vad_filter', asr.transcribe.call_args.kwargs)

    def test_the_declared_capability_decides_not_the_engine_name(self):
        """Until 2026-10-01 only the engine NAMED `whisper` got the filter: Albert, which can
        filter, never received it — the cause measured of its extra omissions."""
        from unittest import mock
        received = {}
        for engine, capable in (('albert', True), ('whisper', False)):
            Transcript.objects.filter(pk=self.item.pk).update(vad_mode='on', status='RUNNING')
            asr = self._asr()
            asr.name = engine
            asr.supports_vad_filter = capable
            with mock.patch('wama.common.utils.speech_activity.vad_rejects_speech'):
                self._run(asr)
            received[engine] = asr.transcribe.call_args.kwargs.get('vad_filter')
        self.assertEqual({'albert': True, 'whisper': None}, received)

    def _language_kwargs(self, mode, engine='whisper', heard=None, in_passes=False):
        Transcript.objects.filter(pk=self.item.pk).update(language_mode=mode, status='RUNNING')
        asr = self._asr()
        asr.name = engine
        asr.max_audio_seconds = 30 if in_passes else None
        self.heard = heard or [('fr', 0.95)]
        self._run(asr)
        kwargs = asr.transcribe.call_args.kwargs
        return kwargs.get('multilingual'), kwargs.get('language'), self.probed.called

    def test_several_languages_heard_switch_whisper_to_multilingual(self):
        self.assertEqual((True, None, True), self._language_kwargs(
            'auto', heard=[('fr', 0.9), ('en', 0.92), ('fr', 0.8), ('en', 0.85)]))

    def test_an_unsure_window_does_not_count_as_a_second_language(self):
        """Une fenêtre à 0,5 (bruit, rires) ne vote pas : l'audio reste monolingue."""
        self.assertEqual((None, None, True), self._language_kwargs(
            'auto', heard=[('fr', 0.9), ('en', 0.5)]))

    def test_multi_needs_no_probe_and_single_whisper_decides_alone(self):
        self.assertEqual((True, None, False), self._language_kwargs('multi'))
        self.assertEqual((None, None, False), self._language_kwargs('single'))

    def test_an_engine_in_passes_gets_one_language_for_all_of_them(self):
        """Sans elle, Canary redétecte à chaque passage — et TRADUIT un passage mal détecté."""
        self.assertEqual((None, 'fr', True), self._language_kwargs(
            'single', engine='nemo', in_passes=True))

    def test_canary_in_multi_gets_the_probe_language_as_fallback(self):
        """#904 : un passage incertain faisait échouer la card — le repli vient de la sonde."""
        Transcript.objects.filter(pk=self.item.pk).update(language_mode='multi', status='RUNNING')
        asr = self._asr()
        asr.name = 'nemo'
        asr.max_audio_seconds = 30
        self.heard = [('fr', 0.95), ('en', 0.9), ('fr', 0.9), ('en', 0.9), ('fr', 0.9)]
        self._run(asr)
        kwargs = asr.transcribe.call_args.kwargs
        self.assertEqual(('fr', None), (kwargs.get('fallback_language'), kwargs.get('language')))
        self.assertTrue(self.probed.called)

    def test_a_forced_language_needs_no_fallback(self):
        Transcript.objects.filter(pk=self.item.pk).update(language_mode='single', status='RUNNING')
        asr = self._asr()
        asr.name = 'nemo'
        asr.max_audio_seconds = 30
        self._run(asr)
        kwargs = asr.transcribe.call_args.kwargs
        self.assertEqual(('fr', None), (kwargs.get('language'), kwargs.get('fallback_language')))

    def test_each_pass_hands_its_language_to_the_next_one(self):
        from types import SimpleNamespace
        from unittest import mock
        from wama.common.backends.speech_to_text_base import TranscriptionResult, TranscriptionSegment
        from wama.transcriber import workers
        seen = []

        def transcribe(audio_path, **kwargs):
            seen.append(kwargs.get('fallback_language'))
            lang = ['en', 'fr'][len(seen) - 1]
            return TranscriptionResult(True, 'x', language=lang,
                                       segments=[TranscriptionSegment('', 0.0, 1.0, 'x')])
        backend = SimpleNamespace(max_audio_seconds=30, transcribe=transcribe)
        with mock.patch.object(workers, '_split_audio_chunks',
                               return_value=[('a.wav', 0.0), ('b.wav', 30.0)]):
            result = workers._transcribe_maybe_chunked(backend, 'x.wav', 60.0,
                                                       {'fallback_language': 'de'})
        self.assertEqual(['de', 'en'], seen, "le 2ᵉ passage reprend la langue du 1ᵉʳ")
        self.assertEqual(['en', 'fr'], [s.language for s in result.segments])

    def test_long_audio_is_cut_in_a_pause_not_at_a_fixed_interval(self):
        """2026-10-02: fixed 30 s cuts sliced a word at every limit; LinTO, trained on utterances
        of 30 s at most, needs 30 s passes. A loud signal with ONE pause at 27–27.4 s → the first
        piece ends in that pause; nothing is lost between pieces."""
        import tempfile

        import numpy as np
        import soundfile as sf
        from wama.transcriber import workers
        rate = 16000
        wave = np.random.default_rng(3).normal(0, 0.3, 70 * rate).astype('float32')
        wave[int(27.0 * rate):int(27.4 * rate)] = 0.0
        with tempfile.TemporaryDirectory() as folder:
            path = f'{folder}/long.wav'
            sf.write(path, wave, rate)
            chunks = workers._split_audio_chunks(path, 30.0, folder)
            lengths = [len(sf.read(p)[0]) for p, _ in chunks]
        offsets = [offset for _, offset in chunks]
        self.assertTrue(27.0 <= offsets[1] <= 27.4, offsets)
        self.assertEqual(len(wave), sum(lengths), 'every sample lands in exactly one piece')
        self.assertTrue(all(n <= 30 * rate for n in lengths), lengths)

    def test_each_segment_keeps_its_language_and_the_card_the_most_spoken(self):
        from wama.common.backends.speech_to_text_base import TranscriptionSegment
        asr = self._asr()
        asr.transcribe.return_value.segments = [
            TranscriptionSegment('', 0.0, 2.0, 'hello everyone', language='en'),
            TranscriptionSegment('', 2.0, 9.0, 'bonjour à tous'),
        ]
        self._run(asr)
        self.assertEqual(['en', 'fr'], [s.get('language') for s in self.item.segments_json])
        self.assertEqual('fr', self.item.language)

    def test_the_leveled_audio_is_what_the_engine_hears(self):
        from unittest import mock
        Transcript.objects.filter(pk=self.item.pk).update(level_speech=True, status='RUNNING')
        asr = self._asr()
        with mock.patch('wama.common.utils.speech_leveling.level_file',
                        side_effect=lambda src, dst: dst) as leveled:
            self._run(asr)
        self.assertTrue(leveled.called)
        self.assertTrue(asr.transcribe.call_args.kwargs['audio_path'].endswith('_leveled.wav'))

    def test_denoising_always_comes_after_leveling(self):
        """Order fixed by the preprocessing bench (2026-10-01): DeepFilterNet erases speech
        recorded low, so asking for it levels first — even without the leveling option."""
        from unittest import mock
        Transcript.objects.filter(pk=self.item.pk).update(preprocess_audio=True, level_speech=False,
                                                          status='RUNNING')
        asr = self._asr()
        calls = []

        def denoise(t, path):
            calls.append(('denoise', path))
            return path.replace('.wav', '_cleaned.wav')
        with mock.patch('wama.common.utils.speech_leveling.level_file',
                        side_effect=lambda src, dst: calls.append(('level', src)) or dst), \
                mock.patch('wama.transcriber.workers._preprocess_audio', side_effect=denoise):
            self._run(asr, task='transcribe')       # la tâche qui GARDE le prétraitement
        self.assertEqual(['level', 'denoise'], [step for step, _ in calls])
        self.assertTrue(calls[1][1].endswith('_leveled.wav'), 'the denoiser gets the LEVELED audio')
        self.assertTrue(asr.transcribe.call_args.kwargs['audio_path'].endswith('_leveled_cleaned.wav'))

    def test_without_the_option_nothing_is_leveled(self):
        from unittest import mock
        asr = self._asr()
        with mock.patch('wama.common.utils.speech_leveling.level_file') as leveled:
            self._run(asr)
        leveled.assert_not_called()

    def test_a_failed_transcription_is_a_failure_with_its_message(self):
        self._run(self._asr(fail=True))
        self.assertEqual('FAILURE', self.item.status)
        self.assertIn('boom', self.item.error_message)
        self.assertEqual(0, self.item.progress)
