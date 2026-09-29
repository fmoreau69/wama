"""Live mode on the common `playhead_follow` loop (2026-09-24) — the wiring, with test doubles.

No GPU, no video: the YOLO model and the session are doubles, and the loop's idle delay is
shortened. What is checked is what the port could have broken — the task still loads its models
only once the lock is held, yields to a batch analysis, and leaves silently during a cooldown.
"""
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
                      'LOCATION': 'cam-live-follow-tests'}}


@override_settings(CACHES=LOCMEM)
class LiveTaskOnCommonLoopTest(SimpleTestCase):

    def setUp(self):
        cache.clear()

    def _run(self, status='completed'):
        from wama.common.services import playhead_follow
        from wama_lab.cam_analyzer import tasks
        from wama_lab.cam_analyzer.models import AnalysisSession

        profile = SimpleNamespace(model_path='/nowhere/yolo.pt', road_model_path='',
                                  iou_threshold=0.5)
        session = SimpleNamespace(profile=profile, user_id=1,
                                  cameras=SimpleNamespace(all=lambda: []))
        manager = mock.MagicMock()
        manager.select_related.return_value.get.return_value = session
        manager.filter.return_value.values_list.return_value.first.return_value = status
        real_follow = playhead_follow.follow
        fast = lambda *a, **kw: real_follow(*a, idle_seconds=0.05, poll_seconds=0.01, **kw)  # noqa: E731
        yolo = mock.MagicMock()
        with mock.patch.object(AnalysisSession, 'objects', manager), \
                mock.patch.object(playhead_follow, 'follow', fast), \
                mock.patch('ultralytics.YOLO', yolo), \
                mock.patch.object(tasks, '_console'), \
                mock.patch.object(tasks, 'close_old_connections'):
            outcome = tasks.live_analysis_task.run('abc')
        return outcome, yolo

    def test_the_loop_loads_the_model_follows_and_stops_when_idle(self):
        cache.set('cam_live_cursor_abc', {'t': 2.0, 'lookahead': 15.0}, 1)   # the listener leaves
        outcome, yolo = self._run()
        self.assertEqual({'session_id': 'abc', 'slices': 0}, outcome)
        yolo.assert_called_once_with('/nowhere/yolo.pt')
        self.assertIsNone(cache.get('cam_live_lock_abc'), 'lock released')

    def test_a_batch_analysis_takes_the_gpu_back(self):
        cache.set('cam_live_cursor_abc', {'t': 2.0}, 1)
        outcome, _ = self._run(status='pending')
        self.assertEqual({'session_id': 'abc', 'slices': 0}, outcome)
        self.assertEqual(1, cache.get('cam_live_cool_abc'), 'cooldown armed after yielding')

    def test_during_a_cooldown_the_task_leaves_silently_without_loading(self):
        cache.set('cam_live_cool_abc', 1, 30)
        outcome, yolo = self._run()
        self.assertEqual({'skipped': 'cooldown'}, outcome)
        yolo.assert_not_called()
