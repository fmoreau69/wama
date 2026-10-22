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
import os
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
                mock.patch('wama.common.utils.waveform.schedule_dense_peaks'), \
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
        # Le débruitage (2026-10-21) se montre en CASE À COCHER, désactivé, comme tout optionnel
        # à interrupteur ; le nivellement, que la card ne demande pas, n'a pas lieu.
        self.assertEqual(['denoise', 'transcribe', 'diarize', 'summarize', 'coherence'],
                         [p['key'] for p in payload['processes']])
        self.assertFalse(payload['processes'][0]['enabled'])
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

    def _aligned(self, transcript, ctx=None):
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


class TheLaunchKeepsItsModelTest(_Pipeline):
    """2026-10-21, card #2522 : a transcription by a REMOTE model (Albert) plays on the default
    queue, the speakers on the GPU queue — the skeleton re-delivers the task and the next process
    runs in ANOTHER worker, whose `_RUNS` is empty. The model the launch drew is kept by the
    skeleton (`tests_process_governance.TheLaunchRemembersAcrossDeliveriesTest`) ; the audio the
    processes listen to is a declared output since the same day (`ThePreparationIsDeclaredTest`)."""

    options = {'enable_diarization': True, 'generate_summary': False, 'verify_coherence': False}

    def test_the_transcription_uses_the_model_the_launch_kept(self):
        """Re-delivered BEFORE the transcription (#2522 : GPU queue → default queue), the glue
        must not draw « auto » again — the skeleton already chose for the launch."""
        from wama.common.utils.task_skeleton import TaskContext, _close_launch
        self.addCleanup(workers._RUNS.clear)
        ctx = TaskContext('transcriber', Transcript, self.item)
        ctx.launch = 'launch-A'
        self.addCleanup(_close_launch, 'transcriber', self.item.pk)
        ctx.model_key = 'transcriber:kept-by-the-launch'
        with mock.patch('wama.transcriber.backends.manager.resolve_auto_key') as draw, \
                mock.patch.object(workers, 'get_backend', return_value=self.asr) as backend, \
                mock.patch('wama.common.utils.waveform.schedule_dense_peaks'), \
                mock.patch.object(workers, '_save_output_files'), \
                mock.patch('wama.common.utils.spoken_language.probe_languages',
                           return_value=[('fr', 0.95)]):
            workers._transcribe_step(self.item, ctx)
        draw.assert_not_called()
        self.assertEqual('transcriber:kept-by-the-launch', backend.call_args.args[0])


class ThePreparationIsDeclaredTest(_Pipeline):
    """2026-10-21, decision of Fabien — « rendre le pré-traitement en tant que process déclaré » :
    the leveling and the denoising were done INSIDE `transcribe`, in a temporary file, once per
    delivery (#2522 : leveled twice). They are two declared optional processes (`level`, CPU ;
    `denoise`, GPU, switched by `preprocess_audio`), each KEEPS its audio on the card as any
    process output — the transcription and the speakers listen to it, the preview and the
    correction page make it heard. Held here:

      * the order of the preprocessing bench (level, then denoise ; never denoise unleveled audio) ;
      * the engine and pyannote hear the audio of the nearest upstream that rendered one ;
      * a denoising that fails says so on ITS line and the transcription hears the leveled audio ;
      * switching the leveling off makes the transcription stale ONCE, and the relaunch hears the
        original — the common engine used to keep it stale forever ;
      * a card transcribed BEFORE the split (no line of the new processes, the leveling in the
        photo of its transcription) stays valid : changing its kind of summary does not
        transcribe again (`ProcessSpec.split_from`) ;
      * the kept audio is a face of the preview, and a duplicate does not inherit it."""

    options = {'enable_diarization': True, 'generate_summary': True, 'verify_coherence': False}
    _client = TheCardShowsItsFourProcessesTest._client

    def setUp(self):
        import shutil
        import tempfile
        from django.test import override_settings
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        super().setUp()
        self.leveled, self.denoised, self.denoise_error = [], [], None

    def _level(self, src, dst):
        self.leveled.append(src)
        with open(dst, 'wb') as handle:
            handle.write(b'RIFF leveled')
        return dst

    def _denoise(self, preprocessor, src, dst):
        if self.denoise_error:
            raise self.denoise_error
        self.denoised.append(src)
        with open(dst, 'wb') as handle:
            handle.write(b'RIFF denoised')
        return dst

    def _set(self, **fields):
        Transcript.objects.filter(pk=self.item.pk).update(**fields)
        self.item.refresh_from_db()

    def _run(self, process=None, task=None):
        from wama.transcriber.utils.audio_preprocessor import AudioPreprocessor
        heard = []
        diarize = self._diarize

        def listening(audio_path, segments, **kwargs):
            heard.append(('diarize', audio_path))
            return diarize(audio_path, segments, **kwargs)
        self._diarize = listening
        self.asr.transcribe.reset_mock()          # what THIS launch made the engine hear
        with mock.patch('wama.common.utils.speech_leveling.level_file', side_effect=self._level), \
                mock.patch.object(AudioPreprocessor, 'preprocess', autospec=True,
                                  side_effect=self._denoise), \
                mock.patch('wama.common.utils.model_readiness.ensure_installed'), \
                mock.patch.object(workers, 'transcribe_without_preprocessing',
                                  getattr(workers, task or 'transcribe')):
            item = super()._run(process)
        self._diarize = diarize
        self.heard = [('transcribe', call.kwargs['audio_path'])
                      for call in self.asr.transcribe.call_args_list] + heard
        return item

    def _abs(self, field):
        return os.path.join(self.tmp, getattr(self.item, field).name)

    def test_the_leveled_audio_is_kept_and_is_what_the_engine_and_pyannote_hear(self):
        self._set(level_speech=True)
        item = self._run()
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual(JOB_SUCCESS, self._states()['level'])
        self.assertNotIn('denoise', self._states(), 'the denoising was not asked for')
        self.assertTrue(os.path.isfile(self._abs('leveled_audio')), 'the leveled audio is kept')
        self.assertEqual([item.audio.path], self.leveled, 'leveled once, from the original')
        self.assertEqual([('transcribe', self._abs('leveled_audio')),
                          ('diarize', self._abs('leveled_audio'))], self.heard)
        self.assertEqual(f'users/{self.user.pk}/transcriber/output',
                         os.path.dirname(item.leveled_audio.name), 'an output of the card')

    def test_denoising_comes_after_leveling_and_is_what_the_engine_hears(self):
        """Order fixed by the preprocessing bench (2026-10-01): DeepFilterNet erases speech
        recorded low, so asking for it levels first — even without the leveling option."""
        self._set(preprocess_audio=True, level_speech=False)
        item = self._run()
        self.assertEqual(['level', 'denoise', 'transcribe'],
                         [k for k in ('level', 'denoise', 'transcribe') if k in self._states()])
        self.assertEqual([self._abs('leveled_audio')], self.denoised,
                         'the denoiser gets the LEVELED audio')
        self.assertEqual(('transcribe', self._abs('denoised_audio')), self.heard[0])
        self.assertEqual(['enhancer:deepfilternet'],
                         process_runs.line(item, 'denoise').output_summary.get('models')
                         or [process_runs.line(item, 'denoise').model_key])

    def test_a_failed_denoising_says_so_and_the_engine_hears_the_leveled_audio(self):
        self._set(preprocess_audio=True)
        self.denoise_error = RuntimeError("DeepFilterNet indisponible : l'audio n'est pas débruité")
        item = self._run()
        self.assertEqual('SUCCESS', item.status, 'an optional process does not fail the card')
        self.assertEqual(JOB_FAILURE, process_runs.line(item, 'denoise').status)
        self.assertIn('DeepFilterNet', process_runs.line(item, 'denoise').error_message)
        self.assertEqual(('transcribe', self._abs('leveled_audio')), self.heard[0])
        self.assertIn('transcribe', PIPELINE.refresh(item),
                      'the transcription does not reflect what the card asks : stale')

    def test_without_the_options_nothing_is_prepared(self):
        item = self._run()
        self.assertEqual([], self.leveled)
        self.assertNotIn('level', self._states())
        self.assertEqual(('transcribe', item.audio.path), self.heard[0])

    def test_leveling_added_later_and_run_alone_then_feeds_the_next_steps(self):
        """Fabien's case (2026-10-22) : the full task ran WITHOUT preparation ; the leveling is
        switched on and ONLY it is run (its ▶) — the leveled audio is produced, kept, readable ;
        the transcription, rendered from the original, is then stale, and its ▶ (or the card's)
        transcribes the leveled audio without leveling again."""
        self._run()
        self.assertNotIn('level', self._states())
        self._set(level_speech=True)
        self.assertIn('level', [row['key'] for row in PIPELINE.card_rows(self.item, 'auto')],
                      'the strip offers the new step, with its ▶')
        self.assertEqual(['level'], [s.key for s in PIPELINE.steps_to_run(self.item, 'auto',
                                                                         only='level')])
        item = self._run(process='level')
        self.assertTrue(os.path.isfile(self._abs('leveled_audio')), 'produced and kept')
        self.assertEqual([], self.heard, 'run alone : nothing downstream was replayed')
        self.assertIn('transcribe', PIPELINE.refresh(item),
                      'the transcription was rendered from the original : stale')
        item = self._run(process='transcribe')
        self.assertEqual(('transcribe', self._abs('leveled_audio')), self.heard[0])
        self.assertEqual(1, len(self.leveled), 'the leveling is resumed, not redone')

    def test_the_prepared_audio_can_be_heard_without_being_transcribed(self):
        """Fabien (2026-10-22) : the preparation also serves the human ear. « Transcrire l'audio
        préparé » unticked : the leveled audio is produced, kept and offered to listen to, while
        the engine and pyannote hear the original ; ticking it back stales the transcription
        ONCE, and the relaunch hears the leveled audio (`ProcessSpec.upstream_switch`)."""
        from wama.common.surfaces import surface
        self._set(level_speech=True, use_prepared_audio=False)
        item = self._run()
        self.assertTrue(os.path.isfile(self._abs('leveled_audio')), 'produced and kept')
        self.assertEqual([('transcribe', item.audio.path), ('diarize', item.audio.path)], self.heard)
        self.assertEqual(['', 'level'],
                         [v['key'] for v in surface('transcriber', 'correct').sources_of(item, 'audio')],
                         'offered to the ear all the same')
        self.assertEqual(set(), PIPELINE.refresh(item), 'nothing it reads changed')
        self._set(use_prepared_audio=True)
        self.assertIn('transcribe', PIPELINE.refresh(self.item), 'now it should hear the leveled audio')
        item = self._run()
        self.assertEqual(('transcribe', self._abs('leveled_audio')), self.heard[0])
        self.assertEqual(1, len(self.leveled), 'the leveling is resumed, not redone')
        self.assertEqual(set(), PIPELINE.refresh(item))

    def test_a_full_relaunch_releases_the_audio_of_a_preparation_switched_off(self):
        """Fabien (2026-10-22) : leveling switched off, FULL relaunch → the leveled audio leaves
        the card — RELEASED (still on disk, the user is told), never erased ; its line goes. A
        bounded run (one process's ▶) keeps it."""
        from wama.common.models import ReleasedFile
        self._set(level_speech=True)
        self._run()
        leveled = self._abs('leveled_audio')
        rel = self.item.leveled_audio.name
        self._set(level_speech=False)
        self._run(process='transcribe')
        self.assertEqual(rel, self.item.leveled_audio.name, 'a bounded run keeps it')
        self.assertIn('level', self._states())
        item = self._run()
        self.assertFalse(item.leveled_audio, 'the full relaunch takes it off the card')
        self.assertNotIn('level', self._states(), 'its line goes with it')
        self.assertTrue(os.path.isfile(leveled), 'released, not erased')
        self.assertTrue(ReleasedFile.objects.filter(path=rel).exists(), 'the user is told')

    def test_switching_the_leveling_off_stales_the_transcription_once(self):
        self._set(level_speech=True)
        self._run()
        self._set(level_speech=False)
        self.assertIn('transcribe', PIPELINE.refresh(self.item),
                      'the transcription heard a leveling the card no longer asks for')
        item = self._run()
        self.assertEqual(('transcribe', item.audio.path), self.heard[0], 'the original, now')
        self.assertEqual(1, len(self.leveled), 'nothing was leveled again')
        self.assertEqual(set(), PIPELINE.refresh(item), 'replayed without it: valid again')
        self.assertEqual(JOB_SUCCESS, PIPELINE.card_state(item))
        self.assertNotIn('level', [row['key'] for row in PIPELINE.card_rows(item, 'auto')],
                         'the strip no longer shows a process the card no longer plays')

    def test_a_card_transcribed_before_the_split_stays_valid(self):
        """Its transcription leveled the audio itself : its photo holds the leveling settings,
        it has no line of `level`. Changing the kind of summary replays the summary alone."""
        self._set(level_speech=True)
        self._run()
        process_runs.lines(self.item).filter(node_id='level').delete()
        row = process_runs.line(self.item, 'transcribe')
        photo = {k: v for k, v in row.settings_snapshot.items() if not k.startswith('@')}
        photo.update(level_speech=True, preprocess_audio=False)
        row.settings_snapshot = photo
        row.save(update_fields=['settings_snapshot'])
        for later in ('diarize', 'summarize'):          # rendered then, without `level` either
            line = process_runs.line(self.item, later)
            photo = dict(line.settings_snapshot)
            photo['@upstream'] = {k: v for k, v in photo.get('@upstream', {}).items()
                                  if k != 'level'}
            line.settings_snapshot = photo
            line.save(update_fields=['settings_snapshot'])
        self._set(leveled_audio=None)
        self.assertEqual(set(), PIPELINE.refresh(self.item), 'nothing changed: valid')
        self._set(summary_type='meeting')
        self.assertEqual(['summarize'],
                         [s.key for s in PIPELINE.steps_to_run(self.item, 'auto')])
        strip = {row['key']: row for row in PIPELINE.card_rows(self.item, 'auto')}
        self.assertEqual(JOB_SUCCESS, strip['level']['status'], 'done within the transcription')
        self._set(summary_type='structured', level_speech=False)
        self.assertIn('transcribe', PIPELINE.refresh(self.item),
                      'its leveling is no longer asked for: its transcription is stale')

    def test_the_prepared_audio_switch_is_a_setting_the_card_shows_and_writes(self):
        """« Transcrire l'audio préparé » had its process switch (`upstream_switch`) and an
        override, but no place in the schema (`include`) : neither the ⚙ modal nor the route knew
        it (found on 2026-10-22). `derive_from_model` now refuses such an override."""
        from wama.common.utils.param_schema import schema_for_app
        param = next((p for p in schema_for_app('transcriber')
                      if p['name'] == 'use_prepared_audio'), None)
        self.assertIsNotNone(param, 'the switch is not in the schema')
        self.assertIn('item', param['contexts'], 'the ⚙ modal shows it')
        response = self._client().post(reverse('transcriber:update_settings', args=[self.item.pk]),
                                       {'use_prepared_audio': 'false'})
        self.assertEqual(200, response.status_code, response.content[:200])
        self.item.refresh_from_db()
        self.assertFalse(self.item.use_prepared_audio, 'the route does not write it')

    def test_the_version_listened_to_is_kept_on_the_card(self):
        """« Persister le choix de version de l'audio dans la card » (Fabien, 2026-10-22) : the
        page writes it through the common settings route (`Surface.sources_setting`), and reads it
        back at the next opening ; « Original » again notes nothing."""
        import json
        from wama.common.surfaces import surface
        self._set(preprocess_audio=True)
        item = self._run()
        found = surface('transcriber', 'correct')
        self.assertEqual('listened_sources', found.sources_setting)
        self.assertEqual('listened_sources', found.to_dict()['sources_setting'],
                         'the page knows where to keep it')
        client = self._client()
        url = reverse('transcriber:update_settings', args=[item.pk])
        response = client.post(url, json.dumps({'listened_sources': {'audio': 'level'}}),
                               content_type='application/json')
        self.assertEqual(200, response.status_code, response.content[:200])
        item.refresh_from_db()
        self.assertEqual({'audio': 'level'}, item.listened_sources)
        with mock.patch('wama.common.surface_views._server_peaks', return_value=None):
            data = client.get(f'/common/surface/transcriber/correct/{item.pk}/data/').json()
        self.assertEqual({'audio': 'level'}, data['settings']['values']['listened_sources'],
                         'the next opening reads it back')
        page = client.get(f'/common/surface/transcriber/correct/{item.pk}/')
        self.assertContains(page, '"sources_setting": "listened_sources"',
                            msg_prefix='the SERVED page tells the core where to keep it')
        client.post(url, json.dumps({'listened_sources': {}}), content_type='application/json')
        item.refresh_from_db()
        self.assertFalse(item.listened_sources, '« Original » again: nothing kept')

    def test_the_kept_audio_is_a_face_of_the_preview_and_a_duplicate_starts_without_it(self):
        """⧉ « Dupliquer » : la copie repart sans résultat, audio préparé compris — ce que ses
        process ont écrit (`AppPipeline.produced_fields`) ; son entrée, elle, est partagée."""
        from django.test import RequestFactory
        from wama.common.utils.preview_utils import _process_faces
        self._set(level_speech=True, preprocess_audio=True)
        item = self._run()
        faces = _process_faces('transcriber', item, RequestFactory().get('/'), None, None)
        meta, data = faces['level']
        self.assertEqual(('Nivellement', 'fa-volume-high'), (meta['label'], meta['icon']))
        self.assertIn(os.path.basename(item.leveled_audio.name), data['url'])
        self.assertIn('denoise', faces)
        response = self._client().post(reverse('transcriber:duplicate', args=[item.pk]))
        self.assertEqual(200, response.status_code, response.content[:200])
        copy = Transcript.objects.exclude(pk=item.pk).get(user=self.user)
        self.assertEqual((False, False), (bool(copy.leveled_audio), bool(copy.denoised_audio)),
                         'the copy has no line: it keeps no prepared audio')
        self.assertEqual(item.audio.name, copy.audio.name, 'its input is shared, as before')

    def test_the_correction_page_lets_one_listen_to_each_version(self):
        """« Se rendre compte à l'oreille » (Fabien, 2026-10-21) : the surface offers the
        original and the prepared audio — DERIVED from the pipeline (`Surface.sources_of`), the
        transcriber names nothing — and serves the peaks of the chosen one only."""
        from django.test import Client
        from wama.common.surfaces import surface
        self._set(preprocess_audio=True)
        item = self._run()
        found = surface('transcriber', 'correct')
        self.assertEqual([('', 'Original'), ('level', 'Nivellement'), ('denoise', 'Débruitage')],
                         [(v['key'], v['label']) for v in found.sources_of(item, 'audio')])
        self.assertEqual([], found.sources_of(item, 'latest'), 'a document has no versions')
        client = Client(HTTP_HOST='localhost')
        client.force_login(self.user)
        base = f'/common/surface/transcriber/correct/{item.pk}/data/'
        with mock.patch('wama.common.surface_views._server_peaks', return_value=None):
            data = client.get(base).json()
        self.assertEqual(['', 'level', 'denoise'], [v['key'] for v in data['sources']['audio']])
        self.assertTrue(data['sources']['audio'][1]['url'].endswith(
            os.path.basename(item.leveled_audio.name)))
        with mock.patch('wama.common.utils.waveform.dense_peaks',
                        return_value={'status': 'pending'}) as peaks:
            client.get(base + '?only=peaks&role=audio&source=level')
            client.get(base + '?only=peaks&role=audio&source=leveled_audio')
        self.assertEqual([item.leveled_audio.name, ''], [c.args[0] for c in peaks.call_args_list],
                         'only a version the surface offers — never a field the page names')
        self._set(preprocess_audio=False, level_speech=False)
        self.assertEqual([], found.sources_of(self.item, 'audio'),
                         'a preparation the card no longer asks for is not offered')


class TheEstimateLineIsBootstrappedFromTheRunsTest(_Pipeline):
    """`eta_estimator.relearn_lines_from_runs` (2026-10-21) : the one-shot that seeded the « fixed +
    per unit » line of the process keys from the kept process rows — played once on the live base.
    Held here on REAL transcriber rows : only real accounts are replayed (the rule of
    `record_run`), and a key that already has its line is never replayed (no run counted twice)."""

    options = {'enable_diarization': True, 'generate_summary': False, 'verify_coherence': False}

    def _card(self, user, seconds):
        from wama.common.services.ui_smoke import _wav_silence
        item = Transcript(user=user, status='RUNNING', backend='auto', duration_seconds=seconds,
                          **self.options)
        item.audio.save('bootstrap.wav', ContentFile(_wav_silence(1.0, 8000)), save=False)
        item.save()
        self.addCleanup(lambda: item.audio.delete(save=False))
        return item

    def test_real_runs_are_replayed_once_and_test_accounts_never(self):
        from wama.common.services.nightly_tests import TEST_USERNAME
        from wama.model_manager.models import ModelRuntimeStat
        from wama.model_manager.services.eta_estimator import relearn_lines_from_runs
        robot = User.objects.create_user(TEST_USERNAME, password='x')
        self.asr.max_audio_seconds = None           # a stand-in engine without a length limit
        for user, seconds in ((self.user, 20.0), (self.user, 8000.0), (robot, 5.0)):
            self.item = self._card(user, seconds)
            self._run()
        key = workers.step_eta_key_size(self.item, 'diarize', self.item.diarization_model)[0]
        ModelRuntimeStat.objects.filter(model_key=key).update(
            size_ema=None, seconds_ema=None, size_sq_ema=None, size_seconds_ema=None)
        self.assertEqual(2, relearn_lines_from_runs(apply=False).get(key),
                         'the test account run must not be replayed')
        relearn_lines_from_runs(apply=True)
        stat = ModelRuntimeStat.objects.get(model_key=key)
        self.assertIsNotNone(stat.size_seconds_ema)
        self.assertNotIn(key, relearn_lines_from_runs(apply=False), 'a run counted twice')
