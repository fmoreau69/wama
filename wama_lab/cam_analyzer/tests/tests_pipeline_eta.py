"""ETA PAR PROCESS du pipeline (2026-10-01, demande de Fabien) — service commun `eta_estimator`
(apprentissage par matériel, comptes de test exclus), rendu commun `WamaEta`. Rien de neuf : la clé
est `cam_analyzer:<passe>`, l'unité `video_sec`, l'apprentissage se fait en UN point, `mark_completed`.
"""
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings

from wama_lab.cam_analyzer.utils import pass_tracking as pt


def session(windows=(), cams=(('front', 8000.0), ('rear', 8000.0)), ranges=None):
    cameras = [SimpleNamespace(position=p, duration=d) for p, d in cams]
    return SimpleNamespace(id='s-eta', intersection_windows=list(windows),
                           config={'analyzed_ranges': ranges or {}},
                           cameras=SimpleNamespace(all=lambda: cameras), user=None)


class PassSizeTest(SimpleTestCase):
    def test_every_pass_declares_a_known_size(self):
        for p in pt.PASSES:
            self.assertIn(p.eta_size, ('analysed', 'windows', 'video'), p.key)

    def test_windows_size_is_the_total_window_duration(self):
        s = session(windows=[{'t_enter': 10, 't_exit': 40}, {'t_enter': 100, 't_exit': 150}])
        self.assertEqual(pt.pass_size_s(s, 'sam3_markings', 'front'), 80.0)

    def test_analysed_size_follows_the_coverage_of_each_camera(self):
        s = session(ranges={'front': [[0, 100], [200, 300]], 'rear': [[0, 50]]})
        self.assertEqual(pt.pass_size_s(s, 'yolo_detect', 'rear'), 50.0)
        self.assertEqual(pt.pass_size_s(s, 'global_tracking'), 200.0)    # la plus longue

    def test_without_coverage_the_whole_video_counts(self):
        self.assertEqual(pt.pass_size_s(session(), 'indicators'), 8000.0)
        self.assertEqual(pt.pass_size_s(session(), 'camera_intrinsics', 'front'), 8000.0)


class RowEtaTest(SimpleTestCase):
    def test_the_last_run_on_this_session_is_reused(self):
        self.assertEqual(pt.row_eta_seconds(8000.0, 240.0, 8000.0, learned_seconds=999), 240.0)

    def test_it_is_scaled_when_the_size_changed(self):
        self.assertEqual(pt.row_eta_seconds(4000.0, 240.0, 8000.0, None), 120.0)

    def test_never_run_here_falls_back_on_the_learned_value_or_nothing(self):
        self.assertEqual(pt.row_eta_seconds(8000.0, None, None, 300.0), 300.0)
        self.assertIsNone(pt.row_eta_seconds(8000.0, None, None, 0.0),
                          "sans apprentissage : rien, pas un a priori d'un autre domaine")
        self.assertIsNone(pt.row_eta_seconds(None, 240.0, None, None))


@override_settings(CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}})
class ChainEtaTest(SimpleTestCase):
    def setUp(self):
        cache.clear()

    def test_running_plus_not_yet_played_plus_queued(self):
        s = session()
        t0 = time.time()
        cache.set(pt.chain_passes_key(s.id), {'passes': ['depth_calc', 'lane_map_recalage', 'indicators'],
                                              'started': t0}, 60)
        done = datetime.fromtimestamp(t0 + 5, tz=timezone.utc).isoformat()
        rows = [   # le panneau parle le vocabulaire commun (lignes `ProcessRun`) depuis le 2026-10-04
            {'pass_type': 'depth_calc', 'status': 'SUCCESS', 'completed_at': done, 'eta_seconds': 90},
            {'pass_type': 'lane_map_recalage', 'status': 'RUNNING', 'eta_remaining_s': 30, 'eta_seconds': 60},
            {'pass_type': 'indicators', 'status': 'STALE', 'completed_at': None, 'eta_seconds': 200},
            {'pass_type': 'conflicts', 'status': 'STALE', 'eta_seconds': 50},   # en file
            {'pass_type': 'visual_yaw', 'status': 'SUCCESS', 'eta_seconds': 999},   # hors chaîne
        ]
        self.assertEqual(pt.chain_eta_remaining(s, rows, queued=['conflicts']), 30 + 200 + 50)

    def test_nothing_running_nothing_queued_gives_no_total(self):
        self.assertIsNone(pt.chain_eta_remaining(session(), [{'pass_type': 'indicators', 'eta_seconds': 9}]))


class LearningPointTest(SimpleTestCase):
    def test_mark_completed_feeds_the_common_estimator(self):
        s = session(ranges={'front': [[0, 600]]})
        written = {}

        def succeed(session, pass_type, **kw):          # la ligne commune mesure la durée
            written.update(kw)
            return SimpleNamespace(duration_s=42.0)
        with mock.patch.object(pt, '_common_runs', return_value=SimpleNamespace(succeed=succeed)), \
                mock.patch('wama.model_manager.services.eta_estimator.record_run') as rec:
            pt.mark_completed(s, 'global_tracking', output_summary={'tracks': 1})
        args, kw = rec.call_args
        self.assertEqual(args[0], 'cam_analyzer:global_tracking')
        self.assertEqual((kw['size'], kw['unit']), (600.0, 'video_sec'))
        self.assertEqual(kw['process_seconds'], 42.0)
        self.assertEqual(written['output_summary'], {'tracks': 1, 'eta_size_s': 600.0},
                         "la taille voyage avec la durée, pour la réutiliser à la relance")
