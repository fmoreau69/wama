"""Champ des caméras MESURÉ (2026-09-30) — passe `camera_intrinsics`, ⚑ measured_camera_fov.

Deux mesures indépendantes ont contredit la fiche technique de la caméra avant (110°) : l'échelle
latérale du recalage voie + carte (×1,862) et la rotation vue contre le cap GPS (×1,87) — ~75°."""
import math
import unittest

from wama_lab.cam_analyzer.utils.camera_intrinsics import measured_fov, turn_windows


def _track(heading_of_t, speed=4.0, t_end=120.0, dt=1.0):
    """[(t, e, n, cap)] : trajet à vitesse constante suivant un cap donné en fonction du temps."""
    rows, e, n = [], 0.0, 0.0
    t = 0.0
    while t <= t_end:
        h = heading_of_t(t)
        rows.append((t, e, n, h % 360.0))
        e += speed * dt * math.sin(math.radians(h))
        n += speed * dt * math.cos(math.radians(h))
        t += dt
    return rows


class TurnWindowsTest(unittest.TestCase):

    def test_a_right_angle_turn_while_driving_is_found(self):
        tr = _track(lambda t: 0.0 if t < 50 else (90.0 if t > 60 else 9.0 * (t - 50)))
        w = turn_windows(tr)
        self.assertEqual(len(w), 1)
        t0, t1, turn = w[0]
        self.assertLessEqual(t0, 50.0)
        self.assertGreaterEqual(t1, 60.0)
        self.assertAlmostEqual(turn, 90.0, delta=1.0)

    def test_a_straight_road_gives_no_window(self):
        self.assertEqual(turn_windows(_track(lambda t: 30.0)), [])

    def test_a_turn_at_standstill_is_not_used(self):
        """À l'arrêt le cap GPS est TENU : le comparer à l'image fabriquerait un désaccord."""
        tr = _track(lambda t: 0.0 if t < 50 else 90.0, speed=0.2)
        self.assertEqual(turn_windows(tr), [])

    def test_windows_never_overlap(self):
        tr = _track(lambda t: 3.0 * t)                        # virage permanent
        w = turn_windows(tr)
        for (a0, a1, _), (b0, b1, _) in zip(w, w[1:]):
            self.assertLessEqual(a1, b0)


class MeasuredFovTest(unittest.TestCase):

    class _S:
        def __init__(self, rs):
            self.results_summary = rs

    def test_returns_the_measured_fields_or_nothing(self):
        s = self._S({'camera_intrinsics': {'front': {'fov_h': 74.7, 'fov_v': 53.0}}})
        self.assertEqual(measured_fov(s, 'front'), (74.7, 53.0))
        self.assertIsNone(measured_fov(s, 'rear'))
        self.assertIsNone(measured_fov(self._S({}), 'front'))

    def test_camera_geometry_applies_it_only_under_the_flag(self):
        from pathlib import Path
        from django.conf import settings
        src = (Path(settings.BASE_DIR) / 'wama_lab' / 'cam_analyzer' / 'utils'
               / 'prediction_adapter.py').read_text(encoding='utf-8')
        self.assertIn("if feat.get('measured_camera_fov', False):", src)
        from wama_lab.cam_analyzer.utils.features import FEATURES
        flag = {f.key: f for f in FEATURES}['measured_camera_fov']
        self.assertFalse(flag.default, "géométrie de TOUTE la chaîne : OFF tant que l'A/B n'a pas tranché")


if __name__ == '__main__':
    unittest.main(verbosity=2)
