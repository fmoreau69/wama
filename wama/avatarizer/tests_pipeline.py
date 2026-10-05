"""The avatarizer task runs through the COMMON skeleton as a pipeline (`speak` → `animate` →
`enhance`) — step P6 of `WAMA_APP_GENERATION_ROUTE §10.6`, 2026-10-03 ; `enhance` (the face
enhancement, « Visage ») is its own process since 2026-10-04.

What is held here: a text card plays both processes and keeps one execution line each ; a card
that brings its audio has no `speak` ; changing what only the animation watches does NOT call the
TTS service again ; asking for the face enhancement, or dropping it, does NOT animate again (the
animated video is kept beside the enhanced one) ; and a TTS service that is still LOADING is not a failure — the task is
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
        self.assertEqual(['speak', 'animate', 'enhance'], [p.key for p in PIPELINE.specs])
        self.assertEqual(set(workers.PROCESSES), {p.key for p in PIPELINE.specs})

    def test_a_text_card_plays_both_processes_and_keeps_a_line_for_each(self):
        job, spoken, engines = self._run(self._text_job())
        self.assertEqual(('SUCCESS', 100), (job.status, job.progress), job.error_message)
        self.assertEqual(1, spoken)
        self.assertEqual(['avatarizer:musetalk-v1.5'], engines)
        self.assertTrue(job.audio_input.name.endswith('.wav'), job.audio_input.name)
        self.assertTrue(job.output_video.name.endswith('.mp4'), job.output_video.name)
        self.assertEqual({'speak': 'SUCCESS', 'animate': 'SUCCESS', 'enhance': 'SUCCESS'},
                         self._states(job))
        self.assertEqual([], job.native_outputs, 'no enhancement asked : nothing kept beside')

    def test_asking_for_the_face_enhancement_does_not_animate_again(self):
        job, _, _ = self._run(self._text_job())
        animated = job.output_video.name
        AvatarJob.objects.filter(pk=job.pk).update(use_enhancer=True, status='RUNNING')
        job, spoken, engines = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual((0, ['avatarizer:codeformer']), (spoken, engines))
        self.assertIn('codeformer', job.output_video.name)
        self.assertEqual(1, len(job.native_outputs), 'the animated video is kept beside')
        folder = Path(settings.MEDIA_ROOT) / Path(job.output_video.name).parent
        mine = sorted(p.name for p in folder.iterdir() if f'_{job.id}' in p.name)
        self.assertEqual(2, len(mine), mine)
        # Dropped : the animated video takes its place back, nothing is computed.
        AvatarJob.objects.filter(pk=job.pk).update(use_enhancer=False, status='RUNNING')
        job, spoken, engines = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual((0, []), (spoken, engines))
        self.assertEqual((animated, []), (job.output_video.name, job.native_outputs))
        mine = sorted(p.name for p in folder.iterdir() if f'_{job.id}' in p.name)
        self.assertEqual(1, len(mine), mine)

    def test_animating_again_under_an_enhanced_video_replaces_both(self):
        job = self._text_job()
        AvatarJob.objects.filter(pk=job.pk).update(use_enhancer=True)
        job, _, engines = self._run(job)
        self.assertEqual(['avatarizer:musetalk-v1.5', 'avatarizer:codeformer'], engines)
        AvatarJob.objects.filter(pk=job.pk).update(bbox_shift=9, status='RUNNING')
        job, spoken, engines = self._run(job)
        self.assertEqual('SUCCESS', job.status, job.error_message)
        self.assertEqual((0, ['avatarizer:musetalk-v1.5', 'avatarizer:codeformer']),
                         (spoken, engines))
        folder = Path(settings.MEDIA_ROOT) / Path(job.output_video.name).parent
        mine = sorted(p.name for p in folder.iterdir() if f'_{job.id}' in p.name)
        self.assertEqual(2, len(mine), mine)

    def test_a_3d_avatar_has_no_face_process(self):
        job = self._text_job()
        AvatarJob.objects.filter(pk=job.pk).update(avatar_upload='x/head.glb', use_enhancer=True)
        job.refresh_from_db()
        self.assertEqual(['speak', 'animate'], [p.key for p in PIPELINE.applicable(job, 'auto')])

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
        self.assertEqual({'animate': 'SUCCESS', 'enhance': 'SUCCESS'}, self._states(job))

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
        self.assertEqual('FAILURE', self._states(job)['animate'])
        self.assertEqual('SUCCESS', self._states(job)['speak'])
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


class OneEtaKeyForTheTaskAndTheViewTest(TestCase):
    """The ETA triplet lives in ONE place (`workers.avatarizer_eta_key_size`, ROUTE §11 #37). The
    view used to estimate a 3D avatar under the quality key, while the task learned it under
    `avatarizer:talkinghead` : the estimate never read what was learned."""

    def _job(self, avatar):
        user = User.objects.create_user(f'eta_{Path(avatar).suffix[1:]}', password='x')
        return AvatarJob.objects.create(user=user, mode='pipeline', text_content='x' * 150,
                                        quality_mode='fast', avatar_source='upload',
                                        avatar_upload=avatar)

    def test_a_3d_avatar_is_estimated_under_the_key_its_render_learns(self):
        key, size, unit = workers.avatarizer_eta_key_size(self._job('x/head.glb'))
        self.assertEqual(('avatarizer:talkinghead', 10.0, 'video_sec'), (key, size, unit))

    def test_a_photo_animation_is_estimated_under_the_key_its_render_learns_whatever_the_quality(
            self):
        """Since « Visage » is a process of its own (CodeFormer, `avatarizer:codeformer`), the
        animation learns under `avatarizer:fast` in BOTH qualities ; the view estimated a quality
        photo under `avatarizer:quality`, a key nothing learned any more (2026-10-05)."""
        job = self._job('x/face.png')
        job.quality_mode, job.use_enhancer = 'quality', True
        self.assertEqual('avatarizer:fast', workers.avatarizer_eta_key_size(job)[0])
        self.assertEqual(('avatarizer:codeformer', 10.0, 'video_sec'),
                         workers.enhance_eta_key_size(job))

    def test_each_process_names_the_triplet_its_glue_learns(self):
        from wama.avatarizer.function_specs import PIPELINE
        from wama.common.services.process_runs import process_eta
        job = self._job('x/face.png')
        job.use_enhancer = True
        for key, fn in (('speak', workers.speak_eta_key_size),
                        ('animate', workers.avatarizer_eta_key_size),
                        ('enhance', workers.enhance_eta_key_size)):
            with self.subTest(process=key):
                self.assertEqual(fn(job), process_eta(PIPELINE.spec(key), job)[:3])

    def test_the_voice_is_learned_under_the_common_tts_key(self):
        """« Voix » calls the same TTS service as the synthesizer : same key, same learning."""
        from wama.common.tts.service_client import tts_eta_key_size
        job = self._job('x/face.png')
        self.assertEqual(tts_eta_key_size(job.text_content, job.tts_model),
                         workers.speak_eta_key_size(job))


class TheCardShowsItsProcessesTest(TestCase):
    """The card of a text job shows « Voix → Animation → Visage » (common strip), each with its
    ▶ ; a job that brings its audio shows « Animation → Visage » ; a 3D avatar with its own audio
    has a single process, and no strip."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        _register_models()
        self.user = User.objects.create_user('avatar_strip_user', password='x')
        for role in (DEFAULT_APP_ACCESS.get('avatarizer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)

    def _job(self, **kw):
        values = dict(user=self.user, mode='pipeline', text_content='Bonjour.',
                      tts_model='synthesizer:kokoro', avatar_source='upload',
                      avatar_upload='x/face.png')
        values.update(kw)
        return AvatarJob.objects.create(**values)

    def _card(self, job):
        from django.urls import reverse
        return self.client.get(reverse('avatarizer:card_html', args=[job.pk])).content.decode()

    def test_a_text_card_shows_both_processes_with_their_buttons(self):
        job = self._job()
        html = self._card(job)
        for key in ('speak', 'animate', 'enhance'):
            self.assertRegex(html, rf'wcv3-proc-run"[^>]*data-id="{job.pk}"[^>]*data-process="{key}"')
        self.assertIn('data-status="PENDING"', html)

    def test_a_card_with_a_single_process_has_no_strip(self):
        html = self._card(self._job(mode='standalone', text_content='', audio_input='x/voice.wav',
                                    avatar_upload='x/head.glb'))
        self.assertNotIn('data-processes', html)
        photo = self._job(mode='standalone', text_content='', audio_input='x/voice.wav')
        html = self._card(photo)
        for key in ('animate', 'enhance'):
            self.assertRegex(html, rf'wcv3-proc-run"[^>]*data-id="{photo.pk}"[^>]*data-process="{key}"')

    def test_the_button_of_a_process_sends_a_bounded_task(self):
        from types import SimpleNamespace
        from django.urls import reverse
        job = self._job()
        task = SimpleNamespace(apply_async=lambda **kw: sent.update(kw) or SimpleNamespace(id='t-1'))
        sent = {}
        with patch('wama.avatarizer.views._ensure_workers_imported'), \
                patch('wama.avatarizer.views._generate_avatar', task, create=True):
            r = self.client.post(reverse('avatarizer:start_process', args=[job.pk, 'animate']))
        self.assertEqual((200, 'animate'), (r.status_code, r.json().get('process')))
        self.assertEqual({'process': 'animate'}, sent.get('kwargs'))
        job.refresh_from_db()
        self.assertEqual(('RUNNING', 't-1'), (job.status, job.task_id))

    def test_an_unknown_process_or_one_without_object_is_refused(self):
        from django.urls import reverse
        job = self._job(mode='standalone', text_content='', audio_input='x/voice.wav')
        r = self.client.post(reverse('avatarizer:start_process', args=[job.pk, 'mix']))
        self.assertEqual(400, r.status_code)
        r = self.client.post(reverse('avatarizer:start_process', args=[job.pk, 'speak']))
        self.assertEqual(400, r.status_code)
        self.assertIn("n'a pas lieu", r.json()['error'])
        job.refresh_from_db()
        self.assertEqual('PENDING', job.status)

    def test_the_progress_view_carries_the_processes(self):
        from django.urls import reverse
        job = self._job()
        payload = self.client.get(reverse('avatarizer:progress', args=[job.pk])).json()
        self.assertEqual(['speak', 'animate', 'enhance'],
                         [p['key'] for p in payload['processes']])
        self.assertEqual('PENDING', payload['shown_state'])
