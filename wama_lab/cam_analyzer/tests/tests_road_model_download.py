"""YOLOPv2 is installed by the ROUTE of the model manager (2026-10-16, rule « libraries and models
through the route » of AGENTS.md).

Before : `road_model_downloader` fetched `yolopv2.pt` itself (through the common download, pinned
digest) — beside the installer : no catalogue row, no disk-space guard, no install log, no
uninstall. Now the file is DECLARED on its own catalogue row (`model_registry.YOLOPV2_KEY`), the
view ASKS for its installation (`request_install`), and an analysis whose profile points at it
WAITS until it is installed (`_await_road_model`, Celery re-delivery) instead of running without
lanes. The network is never touched.
"""
import importlib.util
import json
from unittest.mock import MagicMock, patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.model_manager.services.model_registry import YOLOPV2_FILES, YOLOPV2_KEY, yolopv2_folder

VIEW = 'wama_lab:cam_analyzer:download_road_model'


class TheOldDownloaderIsGoneTest(SimpleTestCase):

    def test_the_module_is_gone(self):
        self.assertIsNone(importlib.util.find_spec('wama_lab.cam_analyzer.utils.road_model_downloader'))

    def test_the_declaration_is_the_route_s_with_the_official_release(self):
        from wama.model_manager.services.model_installer import declared_files_error
        spec = {'kind': 'files', 'files': YOLOPV2_FILES, 'target_dir': str(yolopv2_folder())}
        self.assertIsNone(declared_files_error(spec))
        self.assertEqual({'source': 'github', 'release': 'CAIC-AD/YOLOPv2:V0.0.1', 'file': 'yolopv2.pt'},
                         YOLOPV2_FILES[0]['origin'])
        self.assertEqual('yolopv2.pt', YOLOPV2_FILES[0]['path'], 'the folder the profile reads')


class TheViewAsksTheRouteTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('road_model_user', password='x')

    def _post(self):
        """The view itself (the app's access policy is a middleware, tested elsewhere)."""
        from django.test import RequestFactory
        from django.urls import reverse
        from wama_lab.cam_analyzer import views
        request = RequestFactory().post(reverse(VIEW))
        request.user = self.user
        return views.download_road_model(request)

    def test_a_missing_model_is_installed_by_the_route_and_its_path_given(self):
        with patch('wama.model_manager.services.model_installer.request_install',
                   return_value={'ok': True, 'started': True}) as install:
            res = self._post()
        data = json.loads(res.content)
        self.assertTrue(data['success'], data)
        self.assertTrue(data['installing'])
        self.assertTrue(data['path'].endswith('vision/yolo/segment/yolopv2.pt'))
        self.assertEqual(YOLOPV2_KEY, install.call_args.args[0])
        self.assertEqual(self.user, install.call_args.kwargs['user'])

    def test_an_installed_model_is_not_requested_again(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key=YOLOPV2_KEY, name='YOLOPv2', model_type='vision',
                               source='github', is_downloaded=True)
        with patch('wama.model_manager.services.model_installer.request_install') as install:
            data = json.loads(self._post().content)
        self.assertTrue(data['success'])
        install.assert_not_called()

    def test_a_refusal_is_said(self):
        with patch('wama.model_manager.services.model_installer.request_install',
                   return_value={'ok': False, 'reason': 'insufficient_storage',
                                 'blocked': {'message': '3 Go libres'}}):
            res = self._post()
        self.assertEqual(507, res.status_code)
        self.assertIn('3 Go libres', json.loads(res.content)['error'])


class TheAnalysisWaitsForItTest(SimpleTestCase):

    def _profile(self, path):
        return MagicMock(road_model_path=path)

    def _task(self):
        task = MagicMock()
        task.request.retries = 0
        task.retry.side_effect = RuntimeError('re-delivered')
        return task

    def test_a_missing_yolopv2_makes_the_analysis_wait_through_a_redelivery(self):
        from wama.common.utils.task_skeleton import ServiceNotReady
        from wama_lab.cam_analyzer.tasks import _await_road_model
        task, session = self._task(), MagicMock(pk='s1', user_id=3)
        declared = str(yolopv2_folder() / 'yolopv2.pt')
        with patch('os.path.exists', return_value=False), \
                patch('wama.common.utils.model_readiness.ensure_installed',
                      side_effect=ServiceNotReady('installing', countdown=30, max_attempts=720)) as ensure, \
                patch('wama_lab.cam_analyzer.tasks.set_session_progress'):
            with self.assertRaisesMessage(RuntimeError, 're-delivered'):
                _await_road_model(task, session, self._profile(declared))
        self.assertEqual(YOLOPV2_KEY, ensure.call_args.args[0])
        self.assertEqual({'countdown': 30, 'max_retries': 720}, task.retry.call_args.kwargs)

    def test_an_exhausted_wait_fails_the_analysis_saying_why(self):
        from celery.exceptions import MaxRetriesExceededError
        from wama.common.utils.task_skeleton import ServiceNotReady
        from wama_lab.cam_analyzer.tasks import _await_road_model
        task, session = self._task(), MagicMock(pk='s1', user_id=3)
        task.retry.side_effect = MaxRetriesExceededError("Can't retry")
        declared = str(yolopv2_folder() / 'yolopv2.pt')
        with patch('os.path.exists', return_value=False), \
                patch('wama.common.utils.model_readiness.ensure_installed',
                      side_effect=ServiceNotReady('installing', gave_up='still not installed')), \
                patch('wama_lab.cam_analyzer.tasks.set_session_progress'):
            with self.assertRaisesMessage(RuntimeError, 'still not installed'):
                _await_road_model(task, session, self._profile(declared))

    def test_another_road_model_or_a_present_file_is_left_alone(self):
        from wama_lab.cam_analyzer.tasks import _await_road_model
        declared = str(yolopv2_folder() / 'yolopv2.pt')
        with patch('wama.common.utils.model_readiness.ensure_installed') as ensure:
            _await_road_model(self._task(), MagicMock(), self._profile('/elsewhere/best.pt'))
            _await_road_model(self._task(), MagicMock(), self._profile(''))
            with patch('os.path.exists', return_value=True):
                _await_road_model(self._task(), MagicMock(), self._profile(declared))
        ensure.assert_not_called()


class TheCatalogueDeclaresItOnceTest(SimpleTestCase):
    """YOLOPv2 has ONE row, its own : the anonymizer's YOLO scan no longer takes the file as an
    Ultralytics weight (its engine cannot load it, and its select is drawn by `detect,segment`)."""

    def _registry(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = object.__new__(ModelRegistry)
        registry._models, registry.discovery_errors = {}, []
        return registry

    def test_the_declared_row_is_a_road_segmentation(self):
        registry = self._registry()
        registry._discover_road_models()
        self.assertEqual([], registry.discovery_errors)
        info = registry._models[YOLOPV2_KEY]
        self.assertEqual('road-segmentation', info.capabilities['task'])
        self.assertEqual(YOLOPV2_FILES, info.extra_info['declared_files'])

    def test_the_anonymizer_scan_skips_the_declared_file(self):
        declared = str(yolopv2_folder() / 'yolopv2.pt')
        scanned = {'segment': [{'name': 'yolopv2.pt', 'path': declared, 'size': 1},
                               {'name': 'yolo11n-seg.pt', 'path': '/elsewhere/yolo11n-seg.pt', 'size': 1}]}
        registry = self._registry()
        with patch('wama.anonymizer.utils.model_config.list_available_yolo_models', return_value=scanned), \
                patch.object(type(registry), '_get_yolo_model_classes', return_value=[], create=True), \
                patch.object(type(registry), '_discover_anonymizer_frame_detectors', create=True):
            registry._discover_anonymizer_models()
        self.assertNotIn('anonymizer:yolo:yolopv2.pt', registry._models)
        self.assertIn('anonymizer:yolo:yolo11n-seg.pt', registry._models)


class TheAnalysisTaskCallsTheWaitTest(TestCase):
    """The wait is called by `process_session_task` itself, BEFORE anything is cleaned up, and a
    re-delivery is not turned into a failed session (`except Retry: raise`)."""

    def test_a_missing_yolopv2_redelivers_the_task_and_leaves_the_session_processing(self):
        from celery.exceptions import Retry
        from wama.common.utils.task_skeleton import ServiceNotReady
        from wama_lab.cam_analyzer import tasks
        from wama_lab.cam_analyzer.models import AnalysisProfile, AnalysisSession
        user = get_user_model().objects.create_user('road_model_wait', password='x')
        declared = str(yolopv2_folder() / 'yolopv2.pt')
        profile = AnalysisProfile.objects.create(user=user, name='p', model_path='yolo11n.pt',
                                                 road_model_path=declared)
        session = AnalysisSession.objects.create(user=user, profile=profile)
        task = MagicMock()
        task.request.retries = 0
        task.retry.side_effect = Retry('re-delivered')
        with patch('os.path.exists', return_value=False), \
                patch('wama.common.utils.model_readiness.ensure_installed',
                      side_effect=ServiceNotReady('installing', countdown=30, max_attempts=720)), \
                patch.object(tasks, 'close_old_connections'), \
                patch.object(tasks, 'set_session_progress'), \
                patch.object(tasks, '_console'):
            with self.assertRaises(Retry):
                tasks.process_session_task.run.__func__(task, str(session.pk))
        session.refresh_from_db()
        self.assertEqual(AnalysisSession.Status.PROCESSING, session.status)
