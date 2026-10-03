"""The avatarizer task runs through the COMMON skeleton as a two-process pipeline (`speak` →
`animate`) — step P6 of `WAMA_APP_GENERATION_ROUTE §10.6`, 2026-10-03.

What is held here: a text card plays both processes and keeps one execution line each ; a card
that brings its audio has no `speak` ; changing what only the animation watches does NOT call the
TTS service again ; and a TTS service that is still LOADING is not a failure — the task is
delivered again (the policy the avatarizer held by hand around `self.retry()`).

The engines are stand-ins (`FakeRender`) : the CHAINING is tested, not the render.
"""
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.avatarizer import workers
from wama.avatarizer.function_specs import PIPELINE
from wama.avatarizer.models import AvatarJob
from wama.avatarizer.tests_animation_model import _register_models
from wama.avatarizer.tests_talkinghead_engine import FakeRender, _media, _silent_wav
from wama.common.services import process_runs

User = get_user_model()


class _Again(Exception):
    """What the stand-in `retry` raises in place of Celery's `Retry`."""


class AvatarPipelineTest(TestCase):

    def setUp(self):
        FakeRender.calls = []
        _register_models()
        self.user = User.objects.create_user('avatar_pipeline_user', password='x')
        self.wav_dir = Path(settings.MEDIA_ROOT) / 'tmp_tests'
        self.wav_dir.mkdir(parents=True, exist_ok=True)
        keep_connection = patch('wama.common.utils.task_skeleton.close_old_connections')
        keep_connection.start()
        self.addCleanup(keep_connection.stop)

    def _text_job(self):
        return AvatarJob.objects.create(
            user=self.user, mode='pipeline', text_content='Bonjour.', status='RUNNING',
            tts_model='synthesizer:kokoro', avatar_source='upload',
            avatar_upload=_media(f'avatarizer/{self.user.id}/input/face.png'))

    def _run(self, job, tts=None, process=None):
        """Plays the task ; returns the job, the number of TTS calls and the engines called."""
        tts = tts or (lambda j: _silent_wav(self.wav_dir / f'tts{j.id}.wav'))
        with patch.object(workers, '_call_tts_service', side_effect=tts) as spoken, \
                patch.object(workers, '_backend', return_value=FakeRender()) as by_key, \
                patch('wama.common.utils.input_match.input_attribute_verdict',
                      return_value=(None, '')):
            workers.generate_avatar.run(job.id, process)
        job.refresh_from_db()
        return job, spoken.call_count, [c.args[0] for c in by_key.call_args_list]

    def _states(self, job):
        return {line.node_id: line.status for line in process_runs.lines(job)}

    def test_the_pipeline_chains_the_voice_then_the_animation(self):
        self.assertEqual(['speak', 'animate'], [p.key for p in PIPELINE.specs])
        self.assertEqual(set(workers.PROCESSES), {p.key for p in PIPELINE.specs})

    def test_a_text_card_plays_both_processes_and_keeps_a_line_for_each(self):
        job, spoken, engines = self._run(self._text_job())
        self.assertEqual(('SUCCESS', 100), (job.status, job.progress), job.error_message)
        self.assertEqual(1, spoken)
        self.assertEqual(['avatarizer:musetalk-v1.5'], engines)
        self.assertTrue(job.audio_input.name.endswith('.wav'), job.audio_input.name)
        self.assertTrue(job.output_video.name.endswith('.mp4'), job.output_video.name)
        self.assertEqual({'speak': 'SUCCESS', 'animate': 'SUCCESS'}, self._states(job))

    def test_the_drawn_tts_model_is_not_written_into_the_setting(self):
        job = self._text_job()
        AvatarJob.objects.filter(pk=job.pk).update(tts_model='auto')
        with patch('wama.common.utils.auto_model.resolve_model_choice',
                   return_value='synthesizer:kokoro'):
            job, spoken, _ = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual('auto', job.tts_model)

    def test_a_card_that_brings_its_audio_has_no_voice_process(self):
        job = AvatarJob.objects.create(
            user=self.user, mode='standalone', status='RUNNING', avatar_source='upload',
            avatar_upload=_media(f'avatarizer/{self.user.id}/input/face.png'),
            audio_input=_media(f'avatarizer/{self.user.id}/input/voice.wav',
                               Path(_silent_wav(self.wav_dir / 'v.wav')).read_bytes()))
        job, spoken, engines = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual(0, spoken)
        self.assertEqual({'animate': 'SUCCESS'}, self._states(job))

    def test_changing_only_the_animation_does_not_speak_again(self):
        job, _, _ = self._run(self._text_job())
        audio = job.audio_input.name
        AvatarJob.objects.filter(pk=job.pk).update(bbox_shift=7, status='RUNNING')
        job, spoken, engines = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual(0, spoken, 'the voice was up to date')
        self.assertEqual(['avatarizer:musetalk-v1.5'], engines)
        self.assertEqual(audio, job.audio_input.name)

    def test_changing_the_text_plays_the_voice_and_the_animation_again(self):
        job, _, _ = self._run(self._text_job())
        AvatarJob.objects.filter(pk=job.pk).update(text_content='Au revoir.', status='RUNNING')
        job, spoken, engines = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual(1, spoken)
        self.assertEqual(['avatarizer:musetalk-v1.5'], engines)

    def test_a_failing_animation_keeps_the_voice_and_is_stated_on_the_card(self):
        job = self._text_job()
        AvatarJob.objects.filter(pk=job.pk).update(animation_model='ghost-model')
        job, spoken, engines = self._run(job)
        self.assertEqual(('FAILURE', 0), (job.status, job.progress))
        self.assertIn('inconnu du catalogue', job.error_message)
        self.assertEqual({'speak': 'SUCCESS', 'animate': 'FAILURE'}, self._states(job))
        AvatarJob.objects.filter(pk=job.pk).update(animation_model='auto', status='RUNNING')
        job, spoken, engines = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual(0, spoken, 'the voice is not synthesized again')

    def test_a_tts_service_still_loading_is_not_a_failure_the_task_comes_back(self):
        from wama.common.tts.service_client import TTSServiceLoadingError

        def loading(job):
            raise TTSServiceLoadingError('503 loading')
        asked = {}

        def retry(**kw):
            asked.update(kw)
            return _Again()
        job = self._text_job()
        with patch.object(workers.generate_avatar, 'retry', side_effect=retry), \
                self.assertRaises(_Again):
            self._run(job, tts=loading)
        job.refresh_from_db()
        self.assertEqual({'countdown': 10, 'max_retries': 60}, asked)
        self.assertEqual('RUNNING', job.status)
        self.assertEqual([], FakeRender.calls)
