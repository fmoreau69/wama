"""The catalogue sync: one at a time, never on a recycled web worker, never over a newer uninstall.

MEASURED ON 2026-10-11. Every recycled gunicorn worker (`max_requests`) re-ran the "startup"
reconcile once its 5-minute lock had expired: a sync every 5 to 10 minutes since 2026-10-09 at
least, each one 7 to 36 minutes long, up to four at once on the default worker. One of them, whose
discovery predated an uninstall, wrote PaddleOCR-VL-1.6 back as downloaded seven minutes later —
files gone, `uninstalled_at` erased — and the uninstall then refused to run again.
"""
import os
from datetime import timedelta
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from wama.model_manager.models import AIModel, ModelSource, ModelType


class OneSyncAtATimeTest(SimpleTestCase):

    def setUp(self):
        from wama.model_manager.tasks import SYNC_RUNNING_KEY
        self.key = SYNC_RUNNING_KEY
        cache.delete(self.key)
        self.addCleanup(cache.delete, self.key)

    def _run(self):
        from wama.model_manager.tasks import sync_models_task
        result = mock.Mock(success=True, added=0, updated=3, removed=0, errors=[])
        service = mock.Mock(**{'full_sync.return_value': result})
        with mock.patch('wama.model_manager.services.model_sync.get_sync_service',
                        return_value=service):
            return sync_models_task.apply().get(), service

    def test_a_sync_that_finds_another_running_stops(self):
        cache.add(self.key, 'other', timeout=60)
        out, service = self._run()
        self.assertEqual('running', out.get('skipped'))
        service.full_sync.assert_not_called()

    def test_counter_proof_a_lone_sync_runs_and_releases_the_lock(self):
        out, service = self._run()
        service.full_sync.assert_called_once()
        self.assertEqual(3, out['updated'])
        self.assertIsNone(cache.get(self.key), 'the next sync must be able to start')


class RecycledWebWorkerTest(SimpleTestCase):
    """A worker gunicorn replaces is not a WAMA start (`gunicorn_conf.post_fork`)."""

    def _ready(self, env):
        from django.apps import apps
        config = apps.get_app_config('model_manager')
        with override_settings(WAMA_TASKS_DISPATCHED=True), \
                mock.patch.dict(os.environ, env), \
                mock.patch('sys.argv', ['manage.py', 'runserver']), \
                mock.patch('django.core.cache.cache.add', return_value=True), \
                mock.patch('wama.model_manager.tasks.sync_models_task.apply_async') as dispatch, \
                mock.patch.object(type(config), '_start_file_watcher'):
            config.ready()
        return dispatch

    def test_a_recycled_worker_dispatches_no_startup_sync(self):
        self._ready({'WAMA_RECYCLED_WORKER': '1'}).assert_not_called()

    def test_the_hook_flags_only_workers_born_after_the_first_batch(self):
        import importlib.util
        from pathlib import Path

        from django.conf import settings
        spec = importlib.util.spec_from_file_location(
            'gunicorn_conf', Path(settings.BASE_DIR) / 'gunicorn_conf.py')
        conf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(conf)
        server = mock.Mock(num_workers=4)
        for age, flagged in ((4, False), (5, True)):
            with self.subTest(age=age), mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop('WAMA_RECYCLED_WORKER', None)
                conf.post_fork(server, mock.Mock(age=age))
                self.assertEqual(flagged, 'WAMA_RECYCLED_WORKER' in os.environ)


class NoStaleWriteOverAnUninstallTest(TestCase):

    def _info(self):
        from wama.model_manager.services.model_registry import ModelInfo
        return ModelInfo(id='Org/Gone', name='Gone', model_type=ModelType.OCR,
                         source=ModelSource.HUGGINGFACE, is_downloaded=True)

    def test_a_row_uninstalled_after_the_discovery_is_left_alone(self):
        from wama.model_manager.services.model_sync import ModelSyncService
        seen_at = timezone.now()
        stamp = (seen_at + timedelta(minutes=1)).isoformat()
        AIModel.objects.create(model_key='huggingface:Org/Gone', name='Gone', model_type='ocr',
                               source='huggingface', is_downloaded=False,
                               extra_info={'uninstalled_at': stamp})
        ModelSyncService()._sync_model('huggingface:Org/Gone', self._info(), seen_at=seen_at)
        row = AIModel.objects.get(model_key='huggingface:Org/Gone')
        self.assertFalse(row.is_downloaded)
        self.assertEqual(stamp, row.extra_info.get('uninstalled_at'))

    def test_counter_proof_a_reinstall_seen_after_the_uninstall_is_written(self):
        from wama.model_manager.services.model_sync import ModelSyncService
        seen_at = timezone.now()
        AIModel.objects.create(model_key='huggingface:Org/Gone', name='Gone', model_type='ocr',
                               source='huggingface', is_downloaded=False,
                               extra_info={'uninstalled_at': (seen_at - timedelta(hours=1)).isoformat()})
        ModelSyncService()._sync_model('huggingface:Org/Gone', self._info(), seen_at=seen_at)
        self.assertTrue(AIModel.objects.get(model_key='huggingface:Org/Gone').is_downloaded)
