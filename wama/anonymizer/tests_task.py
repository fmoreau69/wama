"""The anonymizer task runs through the COMMON skeleton (`run_item_task`) — step P6 of
`WAMA_APP_GENERATION_ROUTE §10.6`, 2026-10-03. The app keeps its glue (`_anonymize`) and what is
its own : the deduplication lock and the stop asked by the user.

The engine is a stand-in (`start_process`) : the CHAINING is tested, not the blur.
"""
import os
import shutil
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import TestCase, override_settings

from wama.anonymizer import tasks
from wama.anonymizer.models import Media
from wama.common.services import process_runs
from wama.common.utils.media_paths import app_media_dir, get_app_media_path
from wama.common.tests.helpers import INLINE_CONVERSION, stand_in_conversion


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                                       'LOCATION': 'anonymizer-task-tests'}})
class AnonymizerTaskOnSkeletonTest(TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp()
        media_root = override_settings(MEDIA_ROOT=self.root)
        media_root.enable()
        self.addCleanup(media_root.disable)
        self.addCleanup(shutil.rmtree, self.root, True)
        cache.clear()
        self.user = get_user_model().objects.create_user('anonymizer_skeleton', password='x')
        folder = get_app_media_path('anonymizer', self.user.id, 'input')
        folder.mkdir(parents=True, exist_ok=True)
        (folder / 'street.png').write_bytes(b'img')
        self.media = Media.objects.create(
            user=self.user, file_ext='.png', status='PENDING', classes2blur=['face'],
            file=f"{app_media_dir('anonymizer', self.user.id, 'input')}/street.png")

    def _blurred(self, **kwargs):
        self.engine_kwargs = kwargs
        folder = get_app_media_path('anonymizer', self.user.id, 'output')
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"street_blurred_{kwargs['item_id']}.png"
        path.write_bytes(b'blurred')
        return str(path)

    _convert = staticmethod(stand_in_conversion)

    def _states(self):
        return {line.node_id: line.status for line in process_runs.lines(self.media)}

    def _run(self, engine=None, **settings):
        if settings:
            Media.objects.filter(pk=self.media.pk).update(status='RUNNING', **settings)
        with mock.patch.object(tasks, 'start_process', side_effect=engine or self._blurred) as started, \
                mock.patch(INLINE_CONVERSION,
                           side_effect=self._convert), \
                mock.patch.object(tasks, 'needs_parallel_detection',
                                  return_value={'parallel': False, 'models': []}), \
                mock.patch('wama.anonymizer.utils.model_selector.select_model_by_precision',
                           return_value=None), \
                mock.patch('wama.anonymizer.utils.yolo_utils.get_model_path',
                           side_effect=lambda name, *a, **kw: f'/models/{name}'), \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            outcome = tasks.process_single_media.run(self.media.pk)
        self.media.refresh_from_db()
        return outcome, started

    def test_a_media_succeeds_through_the_skeleton_with_its_output_and_its_line(self):
        outcome, started = self._run()
        self.assertEqual({'processed': self.media.pk}, outcome)
        self.assertEqual(('SUCCESS', 100), (self.media.status, self.media.blur_progress))
        self.assertTrue(self.media.output_file.name.endswith(f'street_blurred_{self.media.pk}.png'))
        self.assertTrue(os.path.exists(os.path.join(self.root, self.media.output_file.name)))
        self.assertIsNotNone(self.media.processing_seconds)
        self.assertEqual(['face'], self.engine_kwargs['classes2blur'])
        self.assertEqual({'generate': 'SUCCESS', 'output': 'SUCCESS'}, self._states())
        self.assertEqual(self.media.output_file.name,
                         process_runs.line(self.media, 'output').output_ref)
        self.assertEqual([], self.media.native_outputs, 'nothing transformed : a single file')

    def test_changing_the_format_replays_the_output_alone_and_keeps_the_blurred_original(self):
        self._run()
        outcome, started = self._run(output_format='webp')
        self.assertEqual('SUCCESS', self.media.status, self.media.error_message)
        started.assert_not_called()                      # the media was NOT blurred again
        self.assertTrue(self.media.output_file.name.endswith('.webp'), self.media.output_file.name)
        self.assertTrue(self.media.native_outputs[0].endswith('.native.png'))
        outcome, started = self._run(output_format='original')
        started.assert_not_called()
        self.assertTrue(self.media.output_file.name.endswith('.png'))
        self.assertEqual([], self.media.native_outputs)

    def test_the_format_of_the_input_is_resolved_by_the_app(self):
        """« input » is not a format : the app resolves it — here the engine already wrote a PNG
        for a PNG source, so nothing is transformed and nothing is kept twice."""
        self._run()
        outcome, started = self._run(output_format='input')
        started.assert_not_called()
        self.assertTrue(self.media.output_file.name.endswith('.png'))
        self.assertEqual([], self.media.native_outputs)
        self.assertEqual('webp', tasks._output_format_for(
            mock.Mock(output_format='input', file_ext='.webp'), '/x/street_blurred.png'))

    def test_changing_a_blur_setting_blurs_again(self):
        self._run()
        outcome, started = self._run(blur_ratio=31)
        started.assert_called_once()
        self.assertEqual({'generate': 'SUCCESS', 'output': 'SUCCESS'}, self._states())

    def test_the_whole_queue_launcher_sets_running_and_the_task_id_before_sending(self):
        sent = mock.Mock(id='queue-task-1')
        with mock.patch.object(tasks.process_single_media, 'delay', return_value=sent) as delay, \
                mock.patch.object(tasks, 'close_old_connections'):
            tasks.process_user_media_batch.run(self.user.id)
        self.media.refresh_from_db()
        delay.assert_called_once_with(self.media.pk)
        self.assertEqual(('RUNNING', 'queue-task-1'), (self.media.status, self.media.task_id))

    def test_a_stale_redelivered_message_leaves_a_finished_media_untouched(self):
        """Card #741 (2026-09-29) : the media was relaunched under ANOTHER task and succeeded ; the
        old message, redelivered later, must not put it back « running » for ever."""
        Media.objects.filter(pk=self.media.pk).update(status='SUCCESS', task_id='the-relaunch')
        task = tasks.process_single_media
        task.push_request(id='the-old-message', retries=0, delivery_info={'redelivered': True})
        self.addCleanup(task.pop_request)
        with mock.patch.object(tasks, 'start_process') as started, \
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            task.run(self.media.pk)
        self.media.refresh_from_db()
        started.assert_not_called()
        self.assertEqual(('SUCCESS', 'the-relaunch'), (self.media.status, self.media.task_id))

    def test_a_failure_is_stated_on_the_media_and_the_locks_are_released(self):
        def broken(**kwargs):
            raise RuntimeError('the detector crashed')
        outcome, _ = self._run(broken)
        self.assertEqual('FAILURE', self.media.status)
        self.assertIn('the detector crashed', self.media.error_message)
        self.assertEqual({'generate': 'FAILURE'}, self._states())
        self.assertIsNone(cache.get(f'anon_task_owner:media:{self.media.pk}'))
        self.assertIsNone(cache.get(f'anon_lock:media:{self.media.pk}'))

    def test_a_media_owned_by_another_task_is_skipped(self):
        cache.set(f'anon_task_owner:media:{self.media.pk}', 'another-task', timeout=60)
        outcome, started = self._run()
        self.assertEqual('duplicate', outcome['reason'])
        started.assert_not_called()
        self.assertEqual('PENDING', self.media.status)
        self.assertEqual('another-task', cache.get(f'anon_task_owner:media:{self.media.pk}'))

    def test_a_stop_asked_by_the_user_is_honoured_before_any_processing(self):
        tasks.stop_process(self.user.id)
        outcome, started = self._run()
        self.assertEqual({'stopped': self.media.pk}, outcome)
        started.assert_not_called()
        self.assertEqual('PENDING', self.media.status)
        self.assertIsNone(cache.get(f'anon_task_owner:media:{self.media.pk}'))

    def test_a_media_without_file_fails_and_says_why(self):
        Media.objects.filter(pk=self.media.pk).update(file='')
        outcome, started = self._run()
        started.assert_not_called()
        self.assertEqual('FAILURE', self.media.status)
        self.assertIn('sans fichier', self.media.error_message)
