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
    generated = 0

    def load(self, model):
        _FakeImageBackend.loaded = model
        return True

    def generate(self, params, progress):
        _FakeImageBackend.generated += 1
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
        _FakeImageBackend.generated = 0

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
            mock.patch('wama.converter.utils.inline_convert.apply_inline_conversion',
                       side_effect=self._convert))
        for p in patches:
            p.start()
        try:
            outcome = tasks.generate_image_task.run(generation.pk)
        finally:
            for p in patches:
                p.stop()
        generation.refresh_from_db()
        return outcome

    @staticmethod
    def _convert(path, fmt, preset='balanced', **_kw):
        """Stand-in for the converter : writes the target next to the source, removes the source."""
        converted = os.path.splitext(path)[0] + '.' + fmt
        with open(path, 'rb') as src, open(converted, 'wb') as out:
            out.write(src.read() + b'>' + fmt.encode())
        os.remove(path)
        return converted

    def _relaunch(self, generation, **settings):
        ImageGeneration.objects.filter(pk=generation.pk).update(status='RUNNING', **settings)
        generation.refresh_from_db()
        return self._run(generation)

    def _states(self, generation):
        return {line.node_id: line.status for line in process_runs.lines(generation)}

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
        self.assertEqual({'generate': 'SUCCESS', 'output': 'SUCCESS'}, self._states(generation))
        self.assertEqual(MODEL, process_runs.line(generation, 'generate').model_key)
        rendered = process_runs.line(generation, 'output').output_ref
        self.assertTrue(generation.generated_images[0].replace(os.sep, '/').endswith(rendered))
        self.assertEqual([], generation.native_outputs, 'nothing transformed : a single file per image')
        self.assertIsNone(process_runs.line(generation), 'a pipeline card has no « main » line')

    def test_changing_the_format_replays_the_output_alone_and_keeps_the_original(self):
        generation = self._generation(num_images=1)
        self._run(generation)
        native = generation.generated_images[0]
        self._relaunch(generation, output_format='webp')
        self.assertEqual('SUCCESS', generation.status, generation.error_message)
        self.assertEqual(1, _FakeImageBackend.generated, 'the model was NOT asked again')
        self.assertTrue(generation.generated_images[0].endswith('.webp'))
        kept = os.path.join(self.root, generation.native_outputs[0])
        self.assertTrue(kept.endswith('.native.png'))
        with open(kept, 'rb') as original:
            self.assertEqual(b'png', original.read())
        self.assertFalse(os.path.exists(native), 'the rendered file is the webp, the png is the kept one')

    def test_another_format_is_rendered_from_the_original_then_back_to_a_single_file(self):
        generation = self._generation(num_images=1)
        self._run(generation)
        self._relaunch(generation, output_format='webp')
        self._relaunch(generation, output_format='jpg')
        with open(generation.generated_images[0], 'rb') as rendered:
            self.assertEqual(b'png>jpg', rendered.read(), 'from the ORIGINAL, not from the webp')
        folder = os.path.dirname(generation.generated_images[0])
        self.assertEqual(2, len(os.listdir(folder)), os.listdir(folder))
        self._relaunch(generation, output_format='original')
        self.assertEqual([], generation.native_outputs)
        self.assertEqual(1, len(os.listdir(folder)), os.listdir(folder))
        self.assertTrue(generation.generated_images[0].endswith('.png'))
        self.assertEqual(1, _FakeImageBackend.generated)

    def test_changing_the_prompt_generates_again_and_drops_the_kept_original(self):
        generation = self._generation(num_images=1)
        self._run(generation)
        self._relaunch(generation, output_format='webp')
        self._relaunch(generation, prompt='a blue heron')
        self.assertEqual(2, _FakeImageBackend.generated)
        self.assertTrue(generation.generated_images[0].endswith('.webp'))
        folder = os.path.dirname(generation.generated_images[0])
        self.assertEqual(2, len(os.listdir(folder)), os.listdir(folder))

    def test_a_lost_original_makes_the_generation_play_again(self):
        generation = self._generation(num_images=1)
        self._run(generation)
        os.remove(generation.generated_images[0])
        self._relaunch(generation, output_format='webp')
        self.assertEqual('SUCCESS', generation.status, generation.error_message)
        self.assertEqual(2, _FakeImageBackend.generated)

    def test_an_upscaling_that_fails_stops_the_card_and_keeps_the_generation(self):
        generation = self._generation(num_images=1, output_upscale='x4')
        with mock.patch('wama.common.utils.output_formats.upscale_output_image',
                        side_effect=RuntimeError('no upscaler')):
            self._run(generation)
        self.assertEqual('FAILURE', generation.status)
        self.assertIn('no upscaler', generation.error_message)
        self.assertEqual({'generate': 'SUCCESS', 'output': 'FAILURE'}, self._states(generation))
        self._relaunch(generation, output_upscale='')
        self.assertEqual('SUCCESS', generation.status, generation.error_message)
        self.assertEqual(1, _FakeImageBackend.generated, 'only the output was played again')

    def test_a_backend_failure_is_stated_on_the_card_and_the_bar_goes_back_to_zero(self):
        _FakeImageBackend.error = 'out of memory'
        generation = self._generation()
        self._run(generation)
        self.assertEqual(('FAILURE', 0), (generation.status, generation.progress))
        self.assertIn('out of memory', generation.error_message)
        self.assertIsNotNone(generation.completed_at)
        self.assertEqual({'generate': 'FAILURE'}, self._states(generation))

    def test_a_pending_generation_sent_without_a_launcher_goes_running(self):
        generation = self._generation(status='PENDING')
        self._run(generation)
        self.assertEqual('SUCCESS', generation.status, generation.error_message)

    def test_a_finished_generation_is_not_played_again_by_a_late_task(self):
        generation = self._generation(status='SUCCESS')
        outcome = self._run(generation)
        self.assertEqual('already_success', outcome['reason'])
        self.assertEqual({}, self._states(generation))

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
        self.assertEqual(MODEL, process_runs.line(generation, 'generate').model_key)
        self.assertEqual('auto', generation.model, 'the drawn model is on the line, not in the setting')


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
        self.assertEqual('imager:test-video-model', process_runs.line(generation, 'generate').model_key)
        rendered = process_runs.line(generation, 'output')
        self.assertEqual(('SUCCESS', generation.output_video.name), (rendered.status, rendered.output_ref))

        # Changing the format replays the output alone, from the kept MP4.
        ImageGeneration.objects.filter(pk=generation.pk).update(status='RUNNING', output_format='webm')
        played = []
        self.Backend.generate_video = lambda self, params, progress: played.append(1)

        def convert(path, fmt, preset='balanced', **_kw):
            converted = os.path.splitext(path)[0] + '.' + fmt
            os.replace(path, converted)
            return converted
        with mock.patch('wama.converter.utils.inline_convert.apply_inline_conversion', side_effect=convert):
            tasks.generate_video_task.run(generation.pk)
        generation.refresh_from_db()
        self.assertEqual('SUCCESS', generation.status, generation.error_message)
        self.assertEqual([], played, 'the video was NOT generated again')
        self.assertTrue(generation.output_video.name.endswith('.webm'), generation.output_video.name)
        self.assertTrue(generation.native_outputs[0].endswith('.native.mp4'))

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


class TheCardShowsItsProcessesTest(TestCase):
    """The imager card shows « Génération → Sortie » (common strip), each with its ▶ ; the page
    follows the ELEMENT status, the strip and the cycle button the SHOWN state."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.user = get_user_model().objects.create_user('imager_strip', password='x')
        for role in (DEFAULT_APP_ACCESS.get('imager') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)
        self.generation = ImageGeneration.objects.create(
            user=self.user, prompt='a red fox', model=MODEL, generation_mode='txt2img',
            status='SUCCESS')
        from wama.imager.function_specs import PIPELINE
        for key in ('generate', 'output'):
            process_runs.start(self.generation, key,
                               settings_snapshot=PIPELINE.snapshot(PIPELINE.spec(key), self.generation))
            process_runs.succeed(self.generation, key, output_summary={'fingerprint': key})

    def _card(self):
        from django.urls import reverse
        return self.client.get(reverse('imager:card_html', args=[self.generation.pk])).content.decode()

    def test_the_strip_shows_both_processes_with_their_buttons(self):
        html = self._card()
        for key in ('generate', 'output'):
            self.assertRegex(html, rf'wcv3-proc-run"[^>]*data-id="{self.generation.pk}"[^>]*data-process="{key}"')
        self.assertIn('data-status="SUCCESS"', html)

    def test_a_changed_format_shows_a_stale_output_under_a_finished_element(self):
        ImageGeneration.objects.filter(pk=self.generation.pk).update(output_format='webp')
        html = self._card()
        self.assertIn('data-status="STALE"', html)
        self.assertIn('data-element-status="SUCCESS"', html,
                      'the page follows the ELEMENT : a finished card is not polled in a loop')
        states = dict(__import__('re').findall(
            r'data-process="(\w+)"[^>]*>\s*<span class="wama-status-dot" data-s="(\w+)"', html))
        self.assertEqual({'generate': 'SUCCESS', 'output': 'STALE'}, states)

    def test_the_button_of_a_process_sends_a_bounded_task(self):
        from django.urls import reverse
        sent = {}
        with mock.patch.object(tasks.generate_image_task, 'apply_async',
                               side_effect=lambda **kw: sent.update(kw) or SimpleNamespace(id='t-1')):
            r = self.client.post(reverse('imager:start_process', args=[self.generation.pk, 'output']))
        self.assertEqual((200, 'output'), (r.status_code, r.json().get('process')))
        self.assertEqual({'process': 'output'}, sent.get('kwargs'))
        self.generation.refresh_from_db()
        self.assertEqual(('RUNNING', 't-1'), (self.generation.status, self.generation.task_id))
        r = self.client.post(reverse('imager:start_process', args=[self.generation.pk, 'mix']))
        self.assertEqual(400, r.status_code)

    def test_the_progress_view_carries_the_processes(self):
        from django.urls import reverse
        payload = self.client.get(reverse('imager:progress', args=[self.generation.pk])).json()
        self.assertEqual(['generate', 'output'], [p['key'] for p in payload['processes']])
        self.assertEqual('SUCCESS', payload['shown_state'])
