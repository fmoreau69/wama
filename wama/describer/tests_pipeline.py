"""The describer card carries a PIPELINE — `WAMA_APP_GENERATION_ROUTE §10.6`, decision of
Fabien (2026-10-13): « every application must work as a pipeline ». Until then its task chained
transcription, key-frame captions, writing, summary and coherence in one function, the last two
SWALLOWED on failure.

What is held here, and why each point:

  * the processes are those of the NATURE of the input: an image is described in one process, an
    audio is transcribed first, a video also captions its key frames ;
  * a launch replays ONLY what is no longer valid: changing the language model must not listen to
    the audio again — the whole point of the split ;
  * the description receives what its upstreams rendered and never redoes it ;
  * an optional process that fails shows on ITS line, the card stays a success ;
  * the result of a process is erased when THAT process is replayed, never at the click ;
  * the MODEL of each role is chosen: a designated one is used, never replaced in silence ;
  * the common transcription brick runs ANY transcription model of the catalogue, « auto » kept.
"""
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group, User
from django.core.files.base import ContentFile
from django.test import Client, RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse

from wama.common.models import JOB_FAILURE, JOB_STALE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.common.utils.whisper_utils import WhisperResult
from wama.describer import workers
from wama.describer.function_specs import PIPELINE
from wama.describer.models import Description


def _png() -> bytes:
    import io

    from PIL import Image
    buffer = io.BytesIO()
    Image.new('RGB', (8, 8), (200, 30, 30)).save(buffer, format='PNG')
    return buffer.getvalue()


class _Cards(TestCase):
    """One user, cards of each nature, the models as stand-ins."""

    def setUp(self):
        self.user = User.objects.create_user('describer_pipeline', password='x')
        self.heard, self.framed, self.summaries, self.checks, self.reports = [], [], [], [], []
        self.summary_error = None

    def _card(self, nature, name, content, **fields):
        fields.setdefault('output_language', 'en')       # no translation service in a test
        fields.setdefault('status', 'RUNNING')
        card = Description(user=self.user, detected_type=nature, filename=name, **fields)
        card.input_file.save(name, ContentFile(content), save=False)
        card.save()
        self.addCleanup(lambda: card.input_file.delete(save=False))
        return card

    def _audio(self, **fields):
        from wama.common.services.ui_smoke import _wav_silence
        return self._card('audio', 'talk.wav', _wav_silence(1.0, 8000), **fields)

    def _video(self, **fields):
        return self._card('video', 'clip.mp4', b'not really a video', **fields)

    # ── stand-ins ──────────────────────────────────────────────────────────────────────────
    def _whisper(self, path, **kwargs):
        self.heard.append(kwargs)
        return WhisperResult(text='hello everyone', language='en', duration=1.0)

    def _track(self, path, asr_model=None, console=None, user=None):
        self.heard.append({'model_key': asr_model, 'user': user})
        return 'hello from the track'

    def _frames(self, path, options=None, **kwargs):
        self.framed.append(options.get('vision_model'))
        return [{'frame': 1, 'time': 0, 'description': 'a red car'}]

    def _summary(self, text, **kwargs):
        if self.summary_error:
            raise self.summary_error
        self.summaries.append((text, kwargs.get('model'), kwargs.get('provider')))
        return {'summary': 'a greeting', 'key_points': [], 'action_items': []}

    def _check(self, text, **kwargs):
        self.checks.append(text)
        return {'score': 90, 'notes': ['fine'], 'suggestion': ''}

    def _meeting(self, text, **kwargs):
        self.reports.append((text, kwargs.get('model')))
        return '# Meeting report'

    def _run(self, card, process=None):
        Description.objects.filter(pk=card.pk).update(status='RUNNING')
        with mock.patch.object(workers, 'asr_key', return_value='transcriber:whisper'), \
                mock.patch('wama.common.utils.whisper_utils.transcribe_audio',
                           side_effect=self._whisper), \
                mock.patch('wama.describer.backends.video_backend.has_audio', return_value=True), \
                mock.patch('wama.describer.backends.video_backend.transcribe_track',
                           side_effect=self._track), \
                mock.patch('wama.describer.backends.video_backend.caption_frames',
                           side_effect=self._frames), \
                mock.patch('wama.common.utils.llm_utils.get_describer_model',
                           return_value='tier-llm'), \
                mock.patch('wama.common.utils.llm_utils.generate_structured_summary',
                           side_effect=self._summary), \
                mock.patch('wama.common.utils.llm_utils.verify_text_coherence',
                           side_effect=self._check), \
                mock.patch('wama.common.utils.llm_utils.generate_meeting_summary',
                           side_effect=self._meeting), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            workers.describe_content.run(card.pk, process)
        card.refresh_from_db()
        return card

    def _states(self, card):
        return {row.node_id: row.status for row in process_runs.lines(card)}


class ProcessesFollowTheNatureTest(_Cards):

    def _keys(self, card):
        return [spec.key for spec in PIPELINE.applicable(card, PIPELINE.requested_model(card))]

    def test_an_image_or_a_document_is_described_in_one_process(self):
        self.assertEqual(['describe'], self._keys(self._card('image', 'a.png', _png())))
        self.assertEqual(['describe'], self._keys(self._card('document', 'a.txt', b'some text')))

    def test_an_audio_is_transcribed_first_and_a_video_also_captions_its_key_frames(self):
        self.assertEqual(['transcribe', 'describe'], self._keys(self._audio()))
        self.assertEqual(['transcribe', 'frames', 'describe'], self._keys(self._video()))

    def test_the_options_take_place_when_switched_on(self):
        card = self._audio(generate_summary=True, verify_coherence=True)
        self.assertEqual(['transcribe', 'describe', 'summarize', 'coherence'], self._keys(card))

    def test_a_meeting_report_is_a_summary_type_the_video_is_still_described(self):
        card = self._video(summary_type='meeting', generate_summary=True)
        self.assertEqual(['transcribe', 'frames', 'describe', 'summarize'], self._keys(card))

    def test_a_historical_nature_is_read_through_its_alias(self):
        self.assertEqual(['describe'], self._keys(self._card('pdf', 'a.pdf', b'%PDF-1.4')))


class AudioCardRunTest(_Cards):

    def test_each_process_has_its_line_and_the_description_reuses_the_transcription(self):
        card = self._run(self._audio(generate_summary=True, verify_coherence=True))
        self.assertEqual('SUCCESS', card.status)
        self.assertEqual({'transcribe': JOB_SUCCESS, 'describe': JOB_SUCCESS,
                          'summarize': JOB_SUCCESS, 'coherence': JOB_SUCCESS}, self._states(card))
        self.assertEqual(1, len(self.heard), 'the audio was listened to once')
        self.assertEqual('transcriber:whisper', self.heard[0]['model_key'])
        self.assertEqual('hello everyone', card.transcript)
        self.assertIn('hello everyone', card.result_text)
        self.assertEqual(('a greeting', 90), (card.summary, card.coherence_score))
        self.assertIsNone(process_runs.line(card), 'a pipeline card has no « main » line')

    def test_changing_the_language_model_does_not_listen_to_the_audio_again(self):
        card = self._run(self._audio(generate_summary=True))
        Description.objects.filter(pk=card.pk).update(llm_model='ollama:qwen3.8:latest')
        card.refresh_from_db()
        self.assertEqual({'describe', 'summarize'}, PIPELINE.refresh(card))
        card = self._run(card)
        self.assertEqual(1, len(self.heard), 'the transcription was kept')
        self.assertEqual(('qwen3.8:latest', 'ollama'), self.summaries[-1][1:],
                         'the designated model wrote the summary')
        self.assertEqual(JOB_SUCCESS, PIPELINE.card_state(card))

    def test_changing_the_transcription_model_replays_the_transcription_and_what_follows(self):
        card = self._run(self._audio())
        Description.objects.filter(pk=card.pk).update(asr_model='transcriber:qwen3-asr-0.6b')
        card.refresh_from_db()
        self.assertEqual({'transcribe', 'describe'}, PIPELINE.refresh(card),
                         'the description reads a transcription that is no longer valid')
        self.assertEqual(['transcribe', 'describe'],
                         [s.key for s in PIPELINE.steps_to_run(card, PIPELINE.requested_model(card))])

    def test_a_failed_summary_shows_on_its_line_and_leaves_the_card_a_success(self):
        self.summary_error = RuntimeError('Ollama is down')
        card = self._run(self._audio(generate_summary=True))
        self.assertEqual('SUCCESS', card.status)
        self.assertEqual(JOB_FAILURE, self._states(card)['summarize'])
        self.assertIn('hello everyone', card.result_text, 'the description is kept')

    def test_the_summary_replayed_alone_keeps_the_transcription_and_the_description(self):
        card = self._run(self._audio(generate_summary=True))
        description = card.result_text
        card = self._run(card, process='summarize')
        self.assertEqual(1, len(self.heard))
        self.assertEqual(2, len(self.summaries))
        self.assertEqual(description, card.result_text)

    def test_the_launcher_no_longer_erases_what_the_processes_rendered(self):
        from wama.describer.views import _reset_for_relaunch
        card = self._run(self._audio(generate_summary=True))
        _reset_for_relaunch(card)
        self.assertTrue(card.result_text and card.summary and card.transcript)
        self.assertEqual((0, ''), (card.progress, card.error_message))


class MeetingReportTest(_Cards):
    """The meeting report is a SUMMARY TYPE (2026-10-13), as in the transcriber — it was a
    description style, written by each backend in place of the description."""

    def test_the_report_is_written_from_the_whole_speech_not_from_the_description(self):
        card = self._run(self._audio(summary_type='meeting', generate_summary=True))
        self.assertEqual([('hello everyone', 'tier-llm')], self.reports)
        self.assertEqual([], self.summaries, 'no structured summary was asked')
        self.assertEqual('# Meeting report', card.summary)
        self.assertIn('hello everyone', card.result_text, 'the description stays a description')
        self.assertEqual('compte-rendu', process_runs.line(card, 'summarize').output_summary['label'])

    def test_a_document_report_reads_the_document_text(self):
        card = self._run(self._card('document', 'minutes.txt', b'Alice opens the meeting.',
                                    summary_type='meeting', generate_summary=True))
        self.assertEqual('Alice opens the meeting.', self.reports[0][0])

    def test_changing_the_summary_type_replays_the_summary_only(self):
        card = self._run(self._audio(generate_summary=True))
        Description.objects.filter(pk=card.pk).update(summary_type='meeting')
        card.refresh_from_db()
        self.assertEqual({'summarize'}, PIPELINE.refresh(card))
        card = self._run(card)
        self.assertEqual((1, 1), (len(self.heard), len(self.reports)))
        self.assertEqual('# Meeting report', card.summary)

    def test_a_card_posted_in_the_old_meeting_style_keeps_its_report_as_a_summary(self):
        import importlib

        from django.apps import apps
        migration = importlib.import_module('wama.describer.migrations.0016_description_summary_type')
        card = self._audio(output_style='meeting', result_text='# Old report', status='SUCCESS')
        migration.meeting_style_to_summary_type(apps, None)
        card.refresh_from_db()
        self.assertEqual(('detailed', 'meeting', True, '# Old report'),
                         (card.output_style, card.summary_type, card.generate_summary, card.summary))


class VideoCardRunTest(_Cards):

    def test_the_description_is_written_from_the_frames_and_the_track_the_upstreams_rendered(self):
        card = self._run(self._video())
        self.assertEqual({'transcribe': JOB_SUCCESS, 'frames': JOB_SUCCESS,
                          'describe': JOB_SUCCESS}, self._states(card))
        self.assertEqual((1, 1), (len(self.heard), len(self.framed)), 'nothing was redone')
        self.assertIn('a red car', card.result_text)
        self.assertIn('hello from the track', card.result_text)
        self.assertEqual(1, len(card.frame_captions))

    def test_changing_the_vision_model_does_not_listen_to_the_track_again(self):
        card = self._run(self._video())
        Description.objects.filter(pk=card.pk).update(vision_model='describer:blip')
        card.refresh_from_db()
        self.assertEqual({'frames', 'describe'}, PIPELINE.refresh(card))
        self._run(card)
        self.assertEqual((1, 2), (len(self.heard), len(self.framed)))
        self.assertEqual('describer:blip', self.framed[-1])


class ModelChoiceTest(SimpleTestCase):

    def test_the_language_model_is_the_style_tier_under_auto_and_the_designated_one_otherwise(self):
        from wama.describer.backends.model_choice import llm_for
        with mock.patch('wama.common.utils.llm_utils.get_describer_model',
                        return_value='tier-llm') as tier:
            self.assertEqual(('tier-llm', None), llm_for({'llm_model': 'auto'}, 'audio', 'summary'))
        tier.assert_called_once_with('audio', 'summary')
        self.assertEqual(('gemma4:12b', 'ollama'),
                         llm_for({'llm_model': 'ollama:gemma4:12b'}, 'audio', 'summary'))

    def test_a_remote_model_is_refused_rather_than_called_with_the_instance_key(self):
        from wama.describer.backends.model_choice import llm_for, vision_for
        with self.assertRaises(ValueError):
            llm_for({'llm_model': 'albert:gpt-oss-120b'}, 'text', 'detailed')
        with self.assertRaises(ValueError):
            vision_for({'vision_model': 'albert:some-vision'})

    def test_the_vision_model_is_the_cascade_under_auto_blip_or_the_designated_one(self):
        from wama.describer.backends.model_choice import BLIP, vision_for
        self.assertIsNone(vision_for({'vision_model': 'auto'}))
        self.assertEqual(BLIP, vision_for({'vision_model': 'describer:blip'}))
        self.assertEqual('gemma4:e4b', vision_for({'vision_model': 'ollama:gemma4:e4b'}))


class DesignatedVisionModelTest(TestCase):

    def setUp(self):
        import tempfile
        handle = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        handle.write(_png())
        handle.close()
        self.path = handle.name
        self.addCleanup(lambda: __import__('os').remove(self.path))

    def test_a_designated_model_that_does_not_answer_is_an_error_not_a_blip_fallback(self):
        from wama.describer.backends import image_backend
        with mock.patch.object(image_backend, '_describe_with_ollama_vision', return_value=None), \
                mock.patch('wama.describer.backends.get_blip') as blip:
            with self.assertRaises(RuntimeError):
                image_backend.describe_image(self.path, options={'vision_model': 'ollama:gemma4:e4b',
                                                                 'output_language': 'en'})
        blip.assert_not_called()

    def test_designating_blip_skips_the_ollama_cascade(self):
        from wama.describer.backends import image_backend
        fake = mock.MagicMock()
        fake.process.return_value = 'a red square'
        with mock.patch.object(image_backend, '_describe_with_ollama_vision') as ollama, \
                mock.patch('wama.describer.backends.get_blip', return_value=fake):
            text = image_backend.describe_image(self.path, options={
                'vision_model': 'describer:blip', 'output_language': 'en'})
        ollama.assert_not_called()
        self.assertIn('red square', text.lower())

    def test_under_auto_the_cascade_is_unchanged(self):
        from wama.describer.backends import image_backend
        with mock.patch.object(image_backend, '_best_ollama_vision_model', return_value='gemma4:12b'), \
                mock.patch.object(image_backend, '_gpu_safe_mode', return_value=False), \
                mock.patch.object(image_backend, '_describe_with_ollama_vision',
                                  return_value='a red square') as ollama:
            text = image_backend.describe_image(self.path, options={'output_language': 'en'})
        self.assertEqual('gemma4:12b', ollama.call_args[0][0])
        self.assertEqual('A red square.', text)


class StandaloneContractTest(SimpleTestCase):
    """The backends keep their common « text » contract (the twin calls them alone): without the
    upstream results in `options`, they make them themselves."""

    def test_an_audio_described_alone_is_transcribed_by_the_requested_model(self):
        from wama.describer.backends import audio_backend
        with mock.patch.object(audio_backend, 'transcribe_speech',
                               return_value='short words') as heard:
            text = audio_backend.describe_audio('x.wav', options={'asr_model': 'auto'})
        heard.assert_called_once()
        self.assertIn('short words', text)

    def test_an_audio_whose_transcription_is_given_is_not_listened_to(self):
        from wama.describer.backends import audio_backend
        with mock.patch.object(audio_backend, 'transcribe_speech') as heard:
            text = audio_backend.describe_audio('x.wav', options={'transcript': 'given words'})
        heard.assert_not_called()
        self.assertIn('given words', text)


class TranscriptionBrickTest(SimpleTestCase):
    """`whisper_utils.transcribe_audio` runs any transcription model of the catalogue."""

    def _backend(self):
        from wama.common.backends.speech_to_text_base import TranscriptionResult
        backend = mock.MagicMock(max_audio_seconds=None)
        backend.load.return_value = True
        backend.transcribe.return_value = TranscriptionResult(success=True, text='hi',
                                                              language='en', segments=[])
        return backend

    def test_without_a_key_it_is_whisper_large_v3_as_before(self):
        from wama.common.utils import whisper_utils
        backend = self._backend()
        with mock.patch('wama.transcriber.backends.manager.get_backend',
                        return_value=backend) as get:
            self.assertEqual('hi', whisper_utils.transcribe_audio('x.wav').text)
        get.assert_called_once_with('whisper')
        backend.load.assert_called_once_with('large-v3')

    def test_a_designated_key_is_resolved_loaded_and_cut_by_the_transcriber_rule(self):
        from wama.common.utils import whisper_utils
        from wama.transcriber.backends.manager import TranscriberBackendManager
        backend, user = self._backend(), object()
        with mock.patch('wama.transcriber.backends.manager.get_backend',
                        return_value=backend) as get, \
                mock.patch.object(TranscriberBackendManager, 'model_for_request',
                                  return_value='Qwen3-ASR-0.6B'), \
                mock.patch('wama.transcriber.workers._transcribe_maybe_chunked',
                           return_value=backend.transcribe.return_value) as cut:
            whisper_utils.transcribe_audio('x.wav', model_key='transcriber:qwen3-asr-0.6b',
                                           user=user, duration=4000.0)
        get.assert_called_once_with('transcriber:qwen3-asr-0.6b', user=user)
        backend.load.assert_called_once_with('Qwen3-ASR-0.6B')
        self.assertEqual(4000.0, cut.call_args[0][2])

    def test_a_remote_model_without_a_user_is_refused(self):
        from wama.common.utils import whisper_utils
        from wama.transcriber.backends.manager import TranscriberBackendManager
        with mock.patch.object(TranscriberBackendManager, '_is_remote_key', return_value=True), \
                mock.patch('wama.transcriber.backends.manager.get_backend') as get:
            with self.assertRaises(RuntimeError):
                whisper_utils.transcribe_audio('x.wav', model_key='albert:whisper-large-v3')
        get.assert_not_called()


class TranscriptionDrawTest(TestCase):

    def test_auto_draws_in_the_transcription_domain_whisper_first_with_the_card_slider(self):
        user = User.objects.create_user('describer_draw', password='x')
        card = Description.objects.create(user=user, asr_model='auto', quality_intent=20)
        seen = {}

        def fake_select(source, **kwargs):
            seen.update(kwargs)
            return 'transcriber:whisper'

        with mock.patch('wama.model_manager.services.select_model_id', fake_select):
            self.assertEqual('transcriber:whisper', workers.asr_key(card))
        self.assertEqual('transcription', seen.get('task'))
        self.assertEqual(['whisper', 'vibevoice', 'qwen'], seen.get('priority'))
        self.assertEqual(['work_audio'], seen.get('available_inputs'))
        self.assertEqual(20, seen.get('quality_intent'))

    def test_a_designated_model_is_kept(self):
        user = User.objects.create_user('describer_draw2', password='x')
        card = Description.objects.create(user=user, asr_model='transcriber:canary-1b-v2')
        self.assertEqual('transcriber:canary-1b-v2', workers.asr_key(card))


class CardAndViewsTest(_Cards):

    def _client(self):
        from wama.accounts.permissions import GROUP_PREFIX
        for role in ('communication', 'recherche'):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        client = Client(HTTP_HOST='localhost')
        client.force_login(self.user)
        return client

    def test_a_process_is_launched_alone_by_its_button_and_refused_where_it_has_no_object(self):
        audio = self._run(self._audio(generate_summary=True))
        image = self._card('image', 'a.png', _png(), status='SUCCESS')
        client = self._client()
        with mock.patch('wama.describer.workers.describe_content.apply_async',
                        return_value=SimpleNamespace(id='t-bounded')) as sent:
            ok = client.post(reverse('describer:start_process', args=[audio.pk, 'summarize']))
            refused = client.post(reverse('describer:start_process', args=[image.pk, 'frames']))
        self.assertEqual(200, ok.status_code)
        self.assertEqual({'process': 'summarize'}, sent.call_args.kwargs['kwargs'])
        self.assertEqual(400, refused.status_code)
        audio.refresh_from_db()
        self.assertTrue(audio.result_text, 'the button of one process erases nothing')

    def test_the_card_shows_its_processes_with_a_checkbox_for_each_option(self):
        card = self._audio(generate_summary=False, verify_coherence=True, status='PENDING')
        html = self._client().get(reverse('describer:card_html', args=[card.pk])).content.decode()
        for key in ('transcribe', 'describe', 'summarize', 'coherence'):
            self.assertIn(f'data-process="{key}"', html)
        self.assertIn('data-toggle-field="generate_summary"', html)
        self.assertIn('data-element-status="PENDING"', html)

    def test_a_summary_switched_off_is_no_longer_served(self):
        card = self._run(self._audio(generate_summary=True))
        Description.objects.filter(pk=card.pk).update(generate_summary=False)
        payload = self._client().get(reverse('describer:progress', args=[card.pk])).json()
        self.assertEqual('', payload['summary'])
        # An option switched off stays on the strip, as its checkbox.
        self.assertEqual(['transcribe', 'describe', 'summarize', 'coherence'],
                         [p['key'] for p in payload['processes']])
        self.assertEqual([True, True, False, False], [p['enabled'] for p in payload['processes']])

    def test_the_settings_route_writes_the_model_of_each_role(self):
        card = self._audio(status='PENDING')
        r = self._client().post(reverse('describer:update_settings', args=[card.pk]),
                                {'asr_model': 'transcriber:canary-1b-v2',
                                 'llm_model': 'ollama:gemma4:12b', 'quality_intent': '80'})
        self.assertEqual(200, r.status_code)
        card.refresh_from_db()
        self.assertEqual(('transcriber:canary-1b-v2', 'ollama:gemma4:12b', 80),
                         (card.asr_model, card.llm_model, card.quality_intent))
        self.assertEqual('ollama:gemma4:12b', r.json()['llm_model'])

    def test_a_duplicate_carries_none_of_the_results(self):
        card = self._run(self._video(generate_summary=True))
        r = self._client().post(reverse('describer:duplicate', args=[card.pk]))
        copy = Description.objects.get(pk=r.json()['duplicated'])
        self.addCleanup(lambda: Description.objects.filter(pk=copy.pk).delete())
        self.assertEqual(('', '', [], ''), (copy.result_text, copy.transcript,
                                            copy.frame_captions, copy.summary))

    def test_the_assistant_launches_with_the_reset_of_the_card_button(self):
        from wama.tool_api import TRIAD_SPECS
        self.assertEqual('wama.describer.views._reset_and_clear_progress',
                         TRIAD_SPECS['describer']['reset'])


class FacesOfTheDescriberTest(_Cards):
    """The common preview shows the describer processes as faces — the transcription, the
    key-frame captions, the summary; the description IS the output and is not repeated."""

    def test_the_faces_are_the_processes_that_rendered_something(self):
        from wama.common.utils.preview_utils import _process_faces
        card = self._run(self._video(generate_summary=True))
        output = {'name': 'description', 'mime_type': 'text/plain', 'content': card.result_text}
        faces = _process_faces('describer', card, RequestFactory().get('/'), None, output)
        self.assertEqual(['transcribe', 'frames', 'summarize'], list(faces))
        self.assertEqual('hello from the track', faces['transcribe'][1]['content'])
        self.assertIn('a red car', faces['frames'][1]['content'])

    def test_a_coherence_report_reads_its_score_notes_and_proposal(self):
        from wama.describer.function_specs import coherence_text
        card = self._run(self._audio(verify_coherence=True))
        self.assertIn('90/100', coherence_text(card))
        Description.objects.filter(pk=card.pk).update(verify_coherence=False)
        card.refresh_from_db()
        self.assertIsNone(coherence_text(card), 'an option switched off shows nothing')
