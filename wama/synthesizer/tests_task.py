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

    def _run(self, render):
        with mock.patch.object(workers, 'render_speech', side_effect=render), \
                mock.patch.object(workers, '_update_audio_properties'), \
                mock.patch('wama.common.utils.generated_media.mark_as_generated'), \
                mock.patch('wama.common.tts.voice_refs.speaker_wav_for', return_value=None), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            workers.synthesize_voice.run(self.item.pk)
        self.item.refresh_from_db()
        return self.item

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
        line = process_runs.line(item)
        self.assertEqual(('SUCCESS', MODEL, item.audio_output.name),
                         (line.status, line.model_key, line.output_ref))
        self.assertEqual(1, ItemRevision.objects.filter(
            app='synthesizer', object_type='VoiceSynthesis', object_id=item.pk).count())

    def test_a_failure_is_stated_on_the_card_and_the_bar_goes_back_to_zero(self):
        def broken(*args, **kwargs):
            raise RuntimeError('the voice model crashed')
        item = self._run(broken)
        self.assertEqual(('FAILURE', 0), (item.status, item.progress))
        self.assertIn('the voice model crashed', item.error_message)
        self.assertEqual('FAILURE', process_runs.line(item).status)

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
