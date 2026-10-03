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

    def _run(self, engine=None):
        with mock.patch.object(tasks, 'start_process', side_effect=engine or self._blurred) as started, \
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
        line = process_runs.line(self.media)
        self.assertEqual(('SUCCESS', self.media.output_file.name), (line.status, line.output_ref))

    def test_a_pending_media_sent_by_the_whole_queue_launcher_goes_running_first(self):
        seen = {}

        def engine(**kwargs):
            seen['status'] = Media.objects.get(pk=self.media.pk).status
            return self._blurred(**kwargs)
        self._run(engine)
        self.assertEqual('RUNNING', seen['status'])

    def test_a_failure_is_stated_on_the_media_and_the_locks_are_released(self):
        def broken(**kwargs):
            raise RuntimeError('the detector crashed')
        outcome, _ = self._run(broken)
        self.assertEqual('FAILURE', self.media.status)
        self.assertIn('the detector crashed', self.media.error_message)
        self.assertEqual('FAILURE', process_runs.line(self.media).status)
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
