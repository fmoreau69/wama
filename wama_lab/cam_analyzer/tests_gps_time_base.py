"""La pose navette s'interroge en temps GPS, jamais en temps VIDÉO — garde générique.

La trajectoire navette (`shuttle_trajectory`) est indexée par le `ts` des fixes GPS ; une
détection porte le temps VIDÉO (`timestamp` = frame / fps). t_gps = t × gps_time_scale + offset
(0,961 et 0,72 s sur ENA : ~20 s d'écart à 8 min, ~5 min en fin de session). Le tracker et la
prédiction convertissaient ; la calib sol 2a et les marquages monde passaient le `timestamp` brut
jusqu'au 2026-09-28 (mesuré : étalement des stationnés 1,54 → 1,02 m à l'avant, 3,29 → 0,87 m à
l'arrière une fois corrigé). Même défaut que les fenêtres, corrigé le 2026-07-18 (`41bef1a`).
"""
import ast
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils.prediction_adapter import video_to_gps_time

APP_DIR = Path(__file__).resolve().parent


def raw_timestamp_position_calls(root=APP_DIR):
    """[(fichier, ligne)] des appels `_shuttle_pose_at(traj, <x>.timestamp)` — temps vidéo brut."""
    found = []
    for path in root.rglob('*.py'):
        if 'migrations' in path.parts or path.name.startswith('tests'):
            continue
        tree = ast.parse(path.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and getattr(node.func, 'id', None) == '_shuttle_pose_at'
                    and len(node.args) >= 2 and isinstance(node.args[1], ast.Attribute)
                    and node.args[1].attr == 'timestamp'):
                found.append((str(path.relative_to(root)), node.lineno))
    return found


class GpsTimeBaseTest(SimpleTestCase):
    def test_video_time_is_converted_with_the_session_sync(self):
        s = SimpleNamespace(gps_time_scale=0.96, gps_time_offset=0.72)
        self.assertAlmostEqual(video_to_gps_time(s, 518.7), 518.7 * 0.96 + 0.72)

    def test_a_session_without_sync_keeps_the_video_time(self):
        self.assertEqual(video_to_gps_time(SimpleNamespace(gps_time_scale=None, gps_time_offset=None), 12.5), 12.5)

    def test_no_shuttle_position_is_queried_with_a_raw_video_timestamp(self):
        self.assertEqual(raw_timestamp_position_calls(), [])

    def test_the_ground_calibration_stores_gps_time_for_its_static_observations(self):
        # Le balayage ci-dessus ne voit PAS ce site : le temps y transitait par un tuple
        # (`obs.append((u, v, df.timestamp, …))`) avant d'atteindre `_shuttle_pose_at(…, t)`.
        import inspect
        from wama_lab.cam_analyzer.utils import homography_estimator
        src = inspect.getsource(homography_estimator._collect_static_obs)
        self.assertIn('video_to_gps_time(session, df.timestamp)', src)

    def test_counterproof_the_scan_sees_a_raw_timestamp_call(self):
        # Contre-épreuve : la forme d'AVANT le correctif doit être vue par le balayage.
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            Path(d, 'bad.py').write_text('def f(df, t):\n    return _shuttle_pose_at(t, df.timestamp)\n',
                                         encoding='utf-8')
            self.assertEqual(raw_timestamp_position_calls(Path(d)), [('bad.py', 2)])
