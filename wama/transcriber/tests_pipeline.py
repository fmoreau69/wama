"""The transcriber card carries FOUR processes — `WAMA_APP_GENERATION_ROUTE §10.6`, step P4 (second
pilot after the composer): transcribe (required) → diarize, summarize, coherence (optional, each
switched by a setting of the card).

What is held here, and why each point:

  * a launch replays ONLY what is no longer valid: changing the kind of summary must not
    transcribe again — the whole point of the split ;
  * the result of a process is erased when THAT process is replayed, no longer at the click of
    the launcher — otherwise replaying the summary would lose the transcription ;
  * an optional process that fails shows on ITS line and leaves the card « to be completed » —
    it used to be a console warning under a card that said « done » ;
  * an optional process switched off no longer weighs on the card ;
  * a process relaunched alone reads what the element kept (segments), not the memory of a task.
"""
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.test import Client, TestCase
from django.urls import reverse

from wama.common.models import JOB_FAILURE, JOB_PENDING, JOB_STALE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.transcriber import workers
from wama.transcriber.function_specs import PIPELINE
from wama.transcriber.models import Transcript


class _Pipeline(TestCase):
    """Shared fixture: one card, a stand-in ASR engine, pyannote and the LLM as stand-ins."""

    options = {'enable_diarization': True, 'generate_summary': True, 'verify_coherence': True}

    def setUp(self):
        from wama.common.services.ui_smoke import _wav_silence
        self.user = User.objects.create_user('transcriber_pipeline', password='x')
        self.item = Transcript(user=self.user, status='RUNNING', backend='auto', **self.options)
        self.item.audio.save('pipeline.wav', ContentFile(_wav_silence(1.0, 8000)), save=False)
        self.item.save()
        self.addCleanup(lambda: self.item.audio.delete(save=False))
        self.asr = self._asr()
        self.summaries, self.checks, self.diarized = [], [], []
        self.summary_error = None

    def _asr(self, native_diarization=False):
        from wama.common.backends.speech_to_text_base import TranscriptionResult, TranscriptionSegment
        asr = mock.MagicMock(display_name='Fake ASR', _current_model='fake-1')
        asr.name = 'fake'
        asr.supports_vad_filter = False
        asr.supports_diarization = native_diarization
        asr.load.return_value = True
        asr.transcribe.side_effect = lambda **kw: TranscriptionResult(
            success=True, text='bonjour à tous', language='fr',
            segments=[TranscriptionSegment('', 0.0, 0.5, 'bonjour'),
                      TranscriptionSegment('', 0.5, 1.0, 'à tous')])
        return asr

    def _diarize(self, audio_path, segments, **kwargs):
        self.diarized.append([s.text for s in segments])
        for index, segment in enumerate(segments):
            segment.speaker_id = f'SPEAKER_{index % 2:02d}'
        return segments

    def _summary(self, text, **kwargs):
        if self.summary_error:
            raise self.summary_error
        self.summaries.append(text)
        return {'summary': 'ils se saluent', 'key_points': ['salut'], 'action_items': []}

    def _check(self, text, *args, **kwargs):
        self.checks.append(text)
        return {'score': 80, 'notes': ['rien'], 'suggestion': ''}

    def _run(self, process=None):
        Transcript.objects.filter(pk=self.item.pk).update(status='RUNNING')
        with mock.patch.object(workers, 'get_backend', return_value=self.asr), \
                mock.patch.object(workers, 'compute_waveform_peaks'), \
                mock.patch.object(workers, '_save_output_files'), \
                mock.patch('wama.common.utils.spoken_language.probe_languages',
                           return_value=[('fr', 0.95)]), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.backends.pyannote_diarizer.is_available',
                           return_value=True), \
                mock.patch('wama.common.backends.pyannote_diarizer.diarize',
                           side_effect=self._diarize), \
                mock.patch('wama.common.utils.llm_utils.generate_structured_summary',
                           side_effect=self._summary), \
                mock.patch('wama.common.utils.llm_utils.generate_meeting_summary',
                           side_effect=lambda text, **kw: self._summary(text)['summary']), \
                mock.patch('wama.common.utils.llm_utils.verify_text_coherence',
                           side_effect=self._check), \
                mock.patch('wama.common.utils.llm_utils.analyze_segments_coherence',
                           return_value={}):
            workers.transcribe_without_preprocessing.run(self.item.pk, process)
        self.item.refresh_from_db()
        return self.item

    def _states(self):
        return {row.node_id: row.status for row in process_runs.lines(self.item)}

    def _counts(self):
        return (self.asr.transcribe.call_count, len(self.diarized), len(self.summaries),
                len(self.checks))


class FourProcessesTest(_Pipeline):

    def test_the_four_processes_run_in_order_and_each_has_its_line(self):
        item = self._run()
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual((1, 1, 1, 1), self._counts())
        self.assertEqual({'transcribe': JOB_SUCCESS, 'diarize': JOB_SUCCESS,
                          'summarize': JOB_SUCCESS, 'coherence': JOB_SUCCESS}, self._states())
        self.assertEqual('bonjour à tous', item.text)
        self.assertEqual(['SPEAKER_00', 'SPEAKER_01'], [s['speaker_id'] for s in item.segments_json])
        self.assertEqual(('ils se saluent', 80), (item.summary, item.coherence_score))
        self.assertIsNotNone(item.finished_at)
        self.assertEqual(JOB_SUCCESS, PIPELINE.card_state(item))
        self.assertIsNone(process_runs.line(item), 'a pipeline card has no « main » line')

    def test_a_card_without_any_option_has_a_single_process(self):
        Transcript.objects.filter(pk=self.item.pk).update(
            enable_diarization=False, generate_summary=False, verify_coherence=False)
        item = self._run()
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'transcribe': JOB_SUCCESS}, self._states())
        self.assertEqual((1, 0, 0, 0), self._counts())

    def test_changing_the_kind_of_summary_replays_the_summary_alone(self):
        self._run()
        Transcript.objects.filter(pk=self.item.pk).update(summary_type='meeting')
        self.item.refresh_from_db()
        self.assertEqual({'summarize'}, PIPELINE.refresh(self.item))
        self.assertEqual(JOB_STALE, PIPELINE.card_state(self.item))
        item = self._run()
        self.assertEqual((1, 1, 2, 1), self._counts(), 'neither the ASR nor pyannote ran again')
        self.assertEqual('bonjour à tous', item.text, 'the transcription was kept')
        self.assertEqual(JOB_SUCCESS, PIPELINE.card_state(item))

    def test_a_valid_card_relaunched_replays_everything(self):
        self._run()
        self._run()
        self.assertEqual((2, 2, 2, 2), self._counts())

    def test_the_launcher_no_longer_erases_what_the_launch_may_keep(self):
        from wama.transcriber.views import _reset_for_relaunch
        item = self._run()
        _reset_for_relaunch(item)
        self.assertEqual(('bonjour à tous', 0), (item.text, item.progress))
        self.assertTrue(item.segments_json)

    def test_a_model_that_tells_the_speakers_itself_does_not_go_through_pyannote(self):
        self.asr = self._asr(native_diarization=True)
        item = self._run()
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual([], self.diarized)
        self.assertEqual(JOB_SUCCESS, self._states().get('diarize'),
                         'the line says the speakers were attributed — by the engine')


class OptionalProcessesTest(_Pipeline):

    def test_a_summary_that_fails_shows_on_its_line_and_leaves_the_card_to_be_completed(self):
        self.summary_error = RuntimeError('ollama is down')
        item = self._run()
        self.assertEqual('SUCCESS', item.status, 'the transcription is there: the element succeeded')
        states = self._states()
        self.assertEqual((JOB_SUCCESS, JOB_FAILURE, JOB_SUCCESS),
                         (states['transcribe'], states['summarize'], states['coherence']))
        self.assertIn('ollama is down', process_runs.line(item, 'summarize').error_message)
        self.assertEqual(JOB_PENDING, PIPELINE.card_state(item))
        # ▶ again completes ONLY what is missing.
        self.summary_error = None
        item = self._run()
        self.assertEqual((1, 1, 1, 1), self._counts())
        self.assertEqual(JOB_SUCCESS, PIPELINE.card_state(item))
        self.assertEqual('ils se saluent', item.summary)

    def test_switching_the_failed_option_off_makes_the_card_successful_again(self):
        self.summary_error = RuntimeError('ollama is down')
        item = self._run()
        Transcript.objects.filter(pk=item.pk).update(generate_summary=False)
        item.refresh_from_db()
        self.assertEqual(JOB_SUCCESS, PIPELINE.card_state(item))
        self.assertNotIn('summarize', [s.key for s in PIPELINE.applicable(item, 'auto')])

    def test_the_speakers_replayed_alone_read_the_kept_segments_and_stale_their_downstream(self):
        self._run()

        def other_voices(audio_path, segments, **kwargs):
            self.diarized.append([s.text for s in segments])
            for segment in segments:
                segment.speaker_id = 'SPEAKER_07'
            return segments
        self._diarize = other_voices
        item = self._run(process='diarize')
        self.assertEqual((1, 2, 1, 1), self._counts(), 'a bounded run never replays its downstream')
        self.assertEqual(['bonjour', 'à tous'], self.diarized[-1],
                         'the segments come from what the element kept, not from a task memory')
        self.assertEqual(['SPEAKER_07', 'SPEAKER_07'], [s['speaker_id'] for s in item.segments_json])
        self.assertEqual({'summarize', 'coherence'}, PIPELINE.refresh(item),
                         'who speaks changed: summary and coherence are stale')


class TheCardShowsItsFourProcessesTest(_Pipeline):

    def _card(self):
        from django.template.loader import render_to_string
        from wama.transcriber.views import _decorate_card
        return render_to_string('transcriber/_transcript_card.html',
                                {'elem': _decorate_card(self.item), 'in_batch': False})

    def test_the_strip_shows_the_four_processes_before_any_run_with_their_switches(self):
        Transcript.objects.filter(pk=self.item.pk).update(status='PENDING', verify_coherence=False)
        self.item.refresh_from_db()
        html = self._card()
        for key in ('transcribe', 'diarize', 'summarize', 'coherence'):
            self.assertIn(f'data-process="{key}"', html)
        self.assertRegex(html, r'wcv3-proc-toggle"[^>]*data-toggle-field="generate_summary"'
                               r'[^>]*data-settings-url="[^"]*/settings/\d+/"[^>]* checked')
        self.assertRegex(html, r'wcv3-proc--off"[^>]*data-process="coherence"')
        self.assertNotRegex(html, r'wcv3-proc-toggle"[^>]*data-toggle-field="transcribe"')
        self.assertIn('data-element-status="PENDING"', html)

    def test_a_card_to_be_completed_says_so_while_its_element_stays_successful(self):
        self.summary_error = RuntimeError('ollama is down')
        self._run()
        html = self._card()
        self.assertIn('data-status="PENDING"', html)
        self.assertIn('data-element-status="SUCCESS"', html,
                      'the page follows the ELEMENT: a finished card is not polled in a loop')
        self.assertRegex(html, r'data-process="summarize"[^>]*>\s*(<input[^>]*>\s*)?'
                               r'<span class="wama-status-dot" data-s="FAILURE"')

    def _client(self):
        """A client that goes THROUGH the app gate (the account carries a role)."""
        from wama.accounts.permissions import GROUP_PREFIX
        for role in ('communication', 'recherche'):     # les rôles du compte de test nocturne
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        client = Client(HTTP_HOST='localhost')
        client.force_login(self.user)
        return client

    def _press(self, process):
        from types import SimpleNamespace
        client = self._client()
        with mock.patch('wama.transcriber.workers.transcribe_without_preprocessing.apply_async',
                        return_value=SimpleNamespace(id='t-bounded')) as sent:
            r = client.post(reverse('transcriber:start_process', args=[self.item.pk, process]))
        self.item.refresh_from_db()
        return r, sent

    def test_the_button_of_a_process_sends_a_bounded_task_and_keeps_the_transcription(self):
        self._run()
        r, sent = self._press('summarize')
        self.assertEqual((200, 'summarize'), (r.status_code, r.json().get('process')))
        self.assertEqual({'process': 'summarize'}, sent.call_args.kwargs.get('kwargs'))
        self.assertEqual(('RUNNING', 'bonjour à tous'), (self.item.status, self.item.text))

    def test_an_unknown_or_switched_off_process_is_refused_and_nothing_is_sent(self):
        Transcript.objects.filter(pk=self.item.pk).update(status='PENDING', generate_summary=False)
        r, sent = self._press('mix')
        self.assertEqual(400, r.status_code)
        self.assertIn('inconnu', r.json()['error'])
        r, sent = self._press('summarize')
        self.assertEqual(400, r.status_code)
        self.assertIn("n'a pas lieu", r.json()['error'])
        sent.assert_not_called()
        self.assertEqual('PENDING', self.item.status)

    def test_the_progress_view_carries_the_processes_and_the_element_state(self):
        self._run()
        client = self._client()
        payload = client.get(reverse('transcriber:progress', args=[self.item.pk])).json()
        self.assertEqual(['transcribe', 'diarize', 'summarize', 'coherence'],
                         [p['key'] for p in payload['processes']])
        self.assertEqual(('SUCCESS', 'SUCCESS'), (payload['status'], payload['shown_state']))


SRT_DOCUMENT = ('1\n00:00:00,000 --> 00:00:01,000\nBonjour à tous.\n\n'
                '2\n00:00:01,000 --> 00:00:02,000\nMerci.\n')


class ExistingResultPlaysTheImportProcessTest(_Pipeline):
    """A card that carries a document (port `work_result`) plays the pipeline with « import » in
    place of « transcribe » : speakers, summary and coherence run on the imported text, and no
    transcription engine is ever loaded (2026-10-03)."""

    options = {'enable_diarization': False, 'generate_summary': True, 'verify_coherence': False}

    def _deposit(self, content=SRT_DOCUMENT, name='other_tool.srt'):
        self.item.work_result.save(name, ContentFile(content.encode()), save=True)
        self.addCleanup(lambda: self.item.work_result.delete(save=False))
        workers.import_existing_result(self.item)
        self.item.refresh_from_db()
        return self.item

    def _run(self, process=None):
        with mock.patch.object(workers, 'transcribe_without_preprocessing', workers.transcribe), \
                mock.patch.object(workers, '_align_document', side_effect=self._aligned) as self.align:
            return super()._run(process)

    align_error = None

    def _aligned(self, transcript):
        if self.align_error:
            raise self.align_error
        return {'aligned': 3, 'failed': 0, 'too_long': 0, 'model_key': 'transcriber:fake-aligner'}

    def test_the_deposit_writes_the_import_line_and_forgets_the_engine_line(self):
        super()._run()                               # the card was first transcribed by an engine
        self.assertIn('transcribe', self._states())
        item = self._deposit()
        self.assertEqual(('SUCCESS', 'external:' + item.work_result.name.rsplit('/', 1)[-1][:-4]),
                         (item.status, item.model_key))
        states = self._states()
        self.assertEqual(JOB_SUCCESS, states['import'])
        self.assertNotIn('transcribe', states)

    def test_a_refused_document_leaves_no_line(self):
        self.item.work_result.save('empty.srt', ContentFile(b'WEBVTT\n'), save=True)
        self.addCleanup(lambda: self.item.work_result.delete(save=False))
        with self.assertRaises(ValueError):
            workers.import_existing_result(self.item)
        self.assertEqual({}, self._states())

    def test_the_summary_runs_on_the_imported_text_without_any_transcription_engine(self):
        self._deposit()
        item = self._run()
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.assertEqual((0, 0, 1, 0), self._counts())
        self.asr.load.assert_not_called()
        self.assertEqual(['Bonjour à tous. Merci.'], self.summaries)
        self.assertEqual('ils se saluent', item.summary)
        self.assertEqual({'import': JOB_SUCCESS, 'summarize': JOB_SUCCESS}, self._states())
        self.assertTrue(item.model_key.startswith('external:'))
        self.align.assert_not_called()        # a timed document (SRT) has nothing to align

    def test_an_unchanged_document_is_not_imported_again_for_a_summary(self):
        self._deposit()
        with mock.patch.object(workers, '_import_document',
                               side_effect=workers._import_document) as imported:
            self._run()
            self.assertEqual(0, imported.call_count, 'the deposit already imported it')
            self._run()                              # everything up to date : the user asks again
            self.assertEqual(1, imported.call_count)

    def test_the_speakers_are_decided_by_the_switch_alone(self):
        Transcript.objects.filter(pk=self.item.pk).update(enable_diarization=True, backend='vibevoice')
        self.item.refresh_from_db()
        self._deposit()
        item = self._run()
        self.assertEqual((0, 1, 1, 0), self._counts())
        self.assertEqual(['SPEAKER_00', 'SPEAKER_01'], [s['speaker_id'] for s in item.segments_json])

    def test_an_untimed_document_has_no_speakers_to_tell_and_does_not_fail(self):
        Transcript.objects.filter(pk=self.item.pk).update(enable_diarization=True)
        self.item.refresh_from_db()
        self._deposit('Titre\nSpeaker 0:\nBonjour à tous.\n', 'tool.txt')
        item = self._run()
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.assertEqual(0, len(self.diarized))
        self.assertEqual(JOB_SUCCESS, self._states()['diarize'])

    UNTIMED = 'Titre\nSpeaker 0:\nBonjour à tous.\n'

    def test_the_deposit_of_an_untimed_document_never_starts_the_alignment(self):
        """A card that is never launched must not use the GPU (Fabien, 2026-10-03)."""
        with self.captureOnCommitCallbacks() as queued, \
                mock.patch.object(workers, '_align_document') as align:
            self._deposit(self.UNTIMED, 'tool.txt')
        self.assertEqual([], queued)
        align.assert_not_called()
        self.assertEqual({'import': JOB_SUCCESS}, self._states())

    def test_an_untimed_document_is_aligned_at_launch_before_the_speakers(self):
        Transcript.objects.filter(pk=self.item.pk).update(enable_diarization=True)
        self.item.refresh_from_db()
        self._deposit(self.UNTIMED, 'tool.txt')
        item = self._run()
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.assertEqual(1, self.align.call_count)
        states = self._states()
        self.assertEqual((JOB_SUCCESS, JOB_SUCCESS), (states['align'], states['diarize']))
        self.assertEqual('transcriber:fake-aligner', process_runs.line(item, 'align').model_key)
        played = [s.key for s in PIPELINE.ordered() if s.key in states]
        self.assertLess(played.index('align'), played.index('diarize'))
        self.assertLess(process_runs.line(item, 'align').finished_at,
                        process_runs.line(item, 'diarize').started_at)

    def test_an_alignment_that_fails_keeps_the_card_and_shows_on_its_line(self):
        self._deposit(self.UNTIMED, 'tool.txt')
        self.align_error = RuntimeError('aligner is down')
        item = self._run()
        self.assertEqual('SUCCESS', item.status, 'optional : the estimated times stay')
        states = self._states()
        self.assertEqual((JOB_FAILURE, JOB_SUCCESS), (states['align'], states['summarize']))
        self.assertIn('aligner is down', process_runs.line(item, 'align').error_message)

    def test_the_alignment_can_be_replayed_alone(self):
        self._deposit(self.UNTIMED, 'tool.txt')
        self._run()
        self._run('align')
        self.assertEqual(1, self.align.call_count, 'played again by the bounded launch')
        self.assertEqual(1, len(self.summaries), 'its downstream is not replayed by a bounded launch')

    def test_an_unreadable_document_fails_the_card_and_says_why(self):
        self._deposit()
        self.item.work_result.save('broken.srt', ContentFile(b'WEBVTT\n'), save=True)
        item = self._run()
        self.assertEqual('FAILURE', item.status)
        self.assertIn('Résultat existant illisible', item.error_message)
        self.assertEqual(JOB_FAILURE, self._states()['import'])

    def test_the_strip_shows_import_in_place_of_transcription(self):
        from django.template.loader import render_to_string
        from wama.transcriber.views import _decorate_card, _task_for
        self._deposit()
        html = render_to_string('transcriber/_transcript_card.html',
                                {'elem': _decorate_card(self.item), 'in_batch': False})
        self.assertIn('data-process="import"', html)
        self.assertNotIn('data-process="transcribe"', html)
        self.assertNotIn('data-process="align"', html)       # a timed document : nothing to align
        self.assertIn('data-process="summarize"', html)
        self.assertIs(workers.transcribe, _task_for(self.item))
        self.assertFalse(Transcript.objects.get(pk=self.item.pk).preprocess_audio)
