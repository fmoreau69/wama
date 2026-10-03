"""Both imager tasks run through the COMMON skeleton (`run_item_task`) — step P6 of
`WAMA_APP_GENERATION_ROUTE §10.6`, 2026-10-03, the last app that was outside it. The app keeps its
two glues (`_generate_image`, `_generate_video`) and its own guards (a generation already
finished, a ghost task delivered again after a reset).

The engines are stand-ins : the CHAINING is tested, not the diffusion.
"""
import os
import shutil
import tempfile
from types import SimpleNamespace
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.common.services import process_runs
from wama.common.services import resource_governor as gov
from wama.imager import tasks
from wama.imager.models import ImageGeneration

MODEL = 'imager:stable-diffusion-xl'


class _FakeImage:
    def save(self, path):
        with open(path, 'wb') as out:
            out.write(b'png')


class _FakeImageBackend:
    name, display_name, device = 'fake', 'Fake diffusion', 'cuda'
    loaded = None
    error = None

    def load(self, model):
        _FakeImageBackend.loaded = model
        return True

    def generate(self, params, progress):
        progress(50)
        if self.error:
            return SimpleNamespace(success=False, error=self.error, images=[], seed_used=None)
        return SimpleNamespace(success=True, error=None, seed_used=7,
                               images=[_FakeImage() for _ in range(params.num_images)])


class _OnSkeleton(TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        media_root = override_settings(MEDIA_ROOT=self.root)
        media_root.enable()
        self.addCleanup(media_root.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        self.user = get_user_model().objects.create_user('imager_skeleton', password='x')
        _FakeImageBackend.error = None

    def _patches(self):
        return (mock.patch('wama.common.utils.task_skeleton.close_old_connections'),
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: text),
                mock.patch('wama.common.utils.model_readiness.warn_if_weights_missing'),
                mock.patch('wama.model_manager.services.eta_estimator.record_run'))


class ImageTaskOnSkeletonTest(_OnSkeleton):

    def _generation(self, **kw):
        values = dict(user=self.user, prompt='a red fox in the snow', model=MODEL,
                      generation_mode='txt2img', num_images=2, status='RUNNING')
        values.update(kw)
        return ImageGeneration.objects.create(**values)

    def _run(self, generation):
        patches = self._patches() + (
            mock.patch.object(tasks, '_image_backend_for', return_value=(_FakeImageBackend(), None)),
            mock.patch('wama.imager.backends.get_available_backends', return_value=['fake']),
            mock.patch('wama.common.utils.output_formats.apply_output_settings',
                       side_effect=lambda paths, *a, **kw: paths))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        outcome = tasks.generate_image_task.run(generation.pk)
        generation.refresh_from_db()
        return outcome

    def test_a_generation_succeeds_through_the_skeleton_with_its_images_and_its_line(self):
        generation = self._generation()
        self._run(generation)
        self.assertEqual(('SUCCESS', 100), (generation.status, generation.progress),
                         generation.error_message)
        self.assertEqual(2, len(generation.generated_images))
        self.assertTrue(all(os.path.exists(p) for p in generation.generated_images))
        self.assertIsNotNone(generation.completed_at)
        self.assertIsNotNone(generation.processing_seconds)
        self.assertEqual('stable-diffusion-xl', _FakeImageBackend.loaded)
        line = process_runs.line(generation)
        self.assertEqual(('SUCCESS', MODEL), (line.status, line.model_key))
        self.assertTrue(generation.generated_images[0].replace(os.sep, '/').endswith(line.output_ref))

    def test_a_backend_failure_is_stated_on_the_card_and_the_bar_goes_back_to_zero(self):
        _FakeImageBackend.error = 'out of memory'
        generation = self._generation()
        self._run(generation)
        self.assertEqual(('FAILURE', 0), (generation.status, generation.progress))
        self.assertIn('out of memory', generation.error_message)
        self.assertIsNotNone(generation.completed_at)
        self.assertEqual('FAILURE', process_runs.line(generation).status)

    def test_a_pending_generation_sent_without_a_launcher_goes_running(self):
        generation = self._generation(status='PENDING')
        self._run(generation)
        self.assertEqual('SUCCESS', generation.status, generation.error_message)

    def test_a_finished_generation_is_not_played_again_by_a_late_task(self):
        generation = self._generation(status='SUCCESS')
        outcome = self._run(generation)
        self.assertEqual('already_success', outcome['reason'])
        self.assertIsNone(process_runs.line(generation))

    def test_a_ghost_task_of_another_dispatch_is_skipped(self):
        generation = self._generation(task_id='the-fresh-dispatch')
        with mock.patch.object(tasks.generate_image_task, 'request_stack') as stack:
            stack.top = SimpleNamespace(id='an-old-task', retries=0, delivery_info={})
            outcome = self._run(generation)
        self.assertEqual('stale_task', outcome['reason'])
        self.assertEqual('RUNNING', generation.status)

    def test_auto_is_drawn_in_the_glue_and_named_on_the_line(self):
        generation = self._generation(model='auto')
        with mock.patch('wama.imager.utils.auto_model.resolve_auto_model', return_value=MODEL):
            self._run(generation)
        self.assertEqual('SUCCESS', generation.status, generation.error_message)
        self.assertEqual(MODEL, process_runs.line(generation).model_key)


class VideoTaskOnSkeletonTest(_OnSkeleton):

    class Backend:
        PARAMS = None
        exported = None

        @staticmethod
        def is_available():
            return True

        def load(self, model):
            return True

        def generate_video(self, params, progress):
            progress(50)
            return SimpleNamespace(success=True, error=None, seed_used=3,
                                   video_frames=[object()] * params.num_frames)

        def export_video(self, frames, path, fps):
            VideoTaskOnSkeletonTest.Backend.exported = (len(frames), fps)
            with open(path, 'wb') as out:
                out.write(b'mp4')
            return True

    def test_a_video_succeeds_through_the_skeleton_with_its_file_and_its_line(self):
        self.Backend.PARAMS = lambda **kw: SimpleNamespace(**kw)
        generation = ImageGeneration.objects.create(
            user=self.user, prompt='waves on a beach', model='imager:test-video-model',
            generation_mode='txt2vid', video_duration=2, video_fps=16, video_resolution='480p',
            status='RUNNING')
        patches = self._patches() + (
            mock.patch('wama.common.backends.manager.backend_for_key', return_value=self.Backend),
            mock.patch('wama.common.utils.model_declarations.declaration_for', return_value={}),
            mock.patch.object(tasks, '_report_effective_video_settings'))
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        tasks.generate_video_task.run(generation.pk)
        generation.refresh_from_db()
        self.assertEqual(('SUCCESS', 100), (generation.status, generation.progress),
                         generation.error_message)
        self.assertTrue(generation.output_video.name.endswith('.mp4'), generation.output_video.name)
        self.assertTrue(os.path.exists(os.path.join(self.root, generation.output_video.name)))
        self.assertEqual(16, self.Backend.exported[1])
        line = process_runs.line(generation)
        self.assertEqual(('SUCCESS', 'imager:test-video-model', generation.output_video.name),
                         (line.status, line.model_key, line.output_ref))

    def test_an_unresolved_video_model_fails_and_says_which(self):
        generation = ImageGeneration.objects.create(
            user=self.user, prompt='p', model='imager:ghost-video', generation_mode='txt2vid',
            video_duration=2, video_fps=16, video_resolution='480p', status='RUNNING')
        patches = self._patches() + (
            mock.patch('wama.common.backends.manager.backend_for_key', return_value=None),)
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        tasks.generate_video_task.run(generation.pk)
        generation.refresh_from_db()
        self.assertEqual('FAILURE', generation.status)
        self.assertIn('imager:ghost-video', generation.error_message)


class ImagerTimeLimitTest(TestCase):

    def test_the_imager_has_its_own_measured_limit_above_the_default(self):
        """The longest real video took 74.7 min : the 30 min default would have stopped it."""
        self.assertGreater(gov.task_time_limit_s('imager', None), 4481)
        self.assertEqual(1800, gov.task_time_limit_s('describer', None))
