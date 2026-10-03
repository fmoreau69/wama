"""The synthesis task runs through the COMMON skeleton (`run_item_task`) — step P6 of
`WAMA_APP_GENERATION_ROUTE §10.6`, 2026-10-03. The app keeps only its glue (`_synthesize`).

What is held here: a card ends in success with its audio, its execution line and its revision ;
a failure is stated on the card ; and a TTS service that is still LOADING is not a failure — the
task is delivered again (the policy the synthesizer held by hand around `self.retry()`).
"""
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import TestCase, override_settings

from wama.common.services import process_runs
from wama.synthesizer import workers
from wama.synthesizer.models import VoiceSynthesis

MODEL = 'synthesizer:kokoro'


class _Again(Exception):
    """What the stand-in `retry` raises in place of Celery's `Retry`."""


class SynthesisTaskOnSkeletonTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('synthesis_skeleton', password='x')
        self.item = VoiceSynthesis(user=self.user, tts_model=MODEL, voice_preset='default',
                                   language='fr', status='RUNNING')
        self.item.text_file.save('bonjour.txt', ContentFile('Bonjour à tous.'.encode()), save=False)
        self.item.save()

    def _run(self, render, **settings):
        VoiceSynthesis.objects.filter(pk=self.item.pk).update(status='RUNNING', **settings)
        with mock.patch.object(workers, 'render_speech', side_effect=render) as self.rendered, \
                mock.patch.object(workers, '_update_audio_properties'), \
                mock.patch('wama.common.utils.generated_media.mark_as_generated') as self.marked, \
                mock.patch('wama.common.tts.voice_refs.speaker_wav_for', return_value=None), \
                mock.patch('wama.converter.utils.inline_convert.apply_inline_conversion',
                           side_effect=self._convert), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            workers.synthesize_voice.run(self.item.pk)
        self.item.refresh_from_db()
        return self.item

    @staticmethod
    def _convert(path, fmt, preset='balanced', **_kw):
        """Stand-in for the converter : writes the target next to the source, removes the source."""
        import os
        converted = os.path.splitext(path)[0] + '.' + fmt
        os.replace(path, converted)
        return converted

    def _states(self):
        return {line.node_id: line.status for line in process_runs.lines(self.item)}

    @staticmethod
    def _spoken(text, output_path, **kwargs):
        with open(output_path, 'wb') as out:
            out.write(b'RIFF0000WAVE')
        return output_path

    def test_a_card_succeeds_through_the_skeleton_with_its_audio_its_line_and_its_revision(self):
        from wama.common.models import ItemRevision
        item = self._run(self._spoken)
        self.assertEqual(('SUCCESS', 100), (item.status, item.progress))
        self.assertTrue(item.audio_output.name.endswith('.wav'), item.audio_output.name)
        self.assertIsNotNone(item.processing_seconds)
        self.assertEqual('Bonjour à tous.', item.text_content)
        self.assertEqual({'generate': 'SUCCESS', 'output': 'SUCCESS'}, self._states())
        self.assertEqual(MODEL, process_runs.line(item, 'generate').model_key)
        self.assertEqual(item.audio_output.name, process_runs.line(item, 'output').output_ref)
        self.assertEqual([], item.native_outputs, 'nothing transformed : a single file')
        self.assertEqual(1, ItemRevision.objects.filter(
            app='synthesizer', object_type='VoiceSynthesis', object_id=item.pk).count())

    def test_changing_the_format_replays_the_output_alone_and_keeps_the_wav(self):
        self._run(self._spoken)
        item = self._run(self._spoken, output_format='mp3')
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.rendered.assert_not_called()                 # the voice was NOT synthesized again
        self.assertTrue(item.audio_output.name.endswith('.mp3'), item.audio_output.name)
        self.assertTrue(item.native_outputs[0].endswith('.native.wav'), item.native_outputs)
        self.assertEqual(1, self.marked.call_count, 'the FINAL file carries the « generated » mention')
        item = self._run(self._spoken, output_format='original')
        self.rendered.assert_not_called()
        self.assertTrue(item.audio_output.name.endswith('.wav'))
        self.assertEqual([], item.native_outputs)

    def test_changing_the_voice_synthesizes_again_under_the_same_name(self):
        first = self._run(self._spoken).audio_output.name
        item = self._run(self._spoken, speed=1.5)
        self.assertEqual(1, self.rendered.call_count)
        self.assertEqual(first, item.audio_output.name,
                         'the previous audio is replaced, not left next to a renamed one')

    def test_auto_stays_auto_and_the_line_names_the_drawn_model(self):
        with mock.patch.object(workers, 'resolve_tts_model', return_value=MODEL):
            item = self._run(self._spoken, tts_model='auto')
        self.assertEqual('SUCCESS', item.status, item.error_message)
        self.assertEqual('auto', item.tts_model)
        self.assertEqual(MODEL, process_runs.line(item, 'generate').model_key)
        self.assertEqual(MODEL, self.rendered.call_args.kwargs['model'])

    def test_a_failure_is_stated_on_the_card_and_the_bar_goes_back_to_zero(self):
        def broken(*args, **kwargs):
            raise RuntimeError('the voice model crashed')
        item = self._run(broken)
        self.assertEqual(('FAILURE', 0), (item.status, item.progress))
        self.assertIn('the voice model crashed', item.error_message)
        self.assertEqual({'generate': 'FAILURE'}, self._states())

    def test_a_tts_service_still_loading_is_not_a_failure_the_task_comes_back(self):
        from wama.common.tts.service_client import TTSServiceLoadingError

        def loading(*args, **kwargs):
            raise TTSServiceLoadingError('503 loading')
        asked = {}

        def retry(**kw):
            asked.update(kw)
            return _Again()
        with mock.patch.object(workers.synthesize_voice, 'retry', side_effect=retry), \
                self.assertRaises(_Again):
            self._run(loading)
        self.item.refresh_from_db()
        self.assertEqual({'countdown': 10, 'max_retries': 60}, asked)
        self.assertEqual('RUNNING', self.item.status)
        self.assertIn('Service TTS en chargement', self.item.error_message)
