"""Un véhicule qui ROULE n'est jamais garé (2026-10-01, demande de Fabien).

G2759 traversait l'intersection (25,6 m en 7,5 s) et était figé en garé : la branche « hors voies »
(⚑ parked_off_road) contournait la règle d'origine « jamais garé près d'une intersection », et sa
seule garde de mouvement (net/chemin > 0,8) ne voit pas un mobile dont le bruit allonge le chemin.
"""
import inspect
import math
import random

from django.test import SimpleTestCase

from wama_lab.cam_analyzer.utils import multicam_tracker as mt


def track(n, t0, step_t, x0, y0, vx, vy, noise, seed=1):
    rnd = random.Random(seed)
    return [(i, t0 + i * step_t, x0 + vx * i * step_t + rnd.gauss(0, noise),
             y0 + vy * i * step_t + rnd.gauss(0, noise), 'car') for i in range(n)]


class RobustDisplacementTest(SimpleTestCase):
    def test_a_parked_car_with_placement_noise_does_not_move(self):
        d, v = mt.robust_displacement(track(120, 0.0, 0.1, 10, 20, 0, 0, noise=1.5))
        self.assertLess(d, mt.PARKED_MOVE_M)

    def test_a_vehicle_crossing_the_intersection_moves(self):
        """Le profil de G2759 : ~4 m/s sur 7,5 s, avec un bruit qui ramène net/chemin bien sous 0,8."""
        hs = track(105, 2854.0, 0.072, 0, 0, 3.4, 0.0, noise=1.5)
        d, v = mt.robust_displacement(hs)
        self.assertGreaterEqual(d, mt.PARKED_MOVE_M)
        self.assertGreaterEqual(v, mt.PARKED_MOVE_MPS)
        self.assertLess(mt.track_descriptors(hs)['net_sur_chemin'], mt.MAX_NET_OVER_PATH,
                        "la garde net/chemin seule le laisserait passer : c'est le cas réel")

    def test_too_short_tracks_are_not_judged(self):
        self.assertEqual(mt.robust_displacement(track(2, 0, 1, 0, 0, 5, 0, 0)), (0.0, 0.0))


class OffRoadBranchGuardsTest(SimpleTestCase):
    def test_the_off_road_branch_applies_the_intersection_and_motion_guards(self):
        src = inspect.getsource(mt.annotate_global_tracks)
        branch = src[src.index('porte = off_road_gate('):src.index("_rejets[porte] += 1")]
        self.assertIn("_near_intersection(hs)", branch)
        self.assertIn("porte = 'pres_intersection'", branch)
        self.assertIn("parked_motion(hs, sh_traj)", branch)
        self.assertIn("is_moving(*_motion, vs_shuttle=_vs_shuttle)", branch)
        self.assertIn("porte = 'en_mouvement'", branch)
        self.assertIn("parked_motion_guard", branch)


def shuttle(t0, t1, speed, step=0.5, y=0.0):
    """Trace navette `shuttle_trajectory` en ligne droite vers l'est, cap 90°."""
    import numpy as np
    n = int((t1 - t0) / step) + 1
    return np.array([(t0 + i * step, speed * i * step, y, 90.0) for i in range(n)])


class MotionAgainstShuttleTest(SimpleTestCase):
    """⚑ parked_motion_vs_shuttle (2026-10-13) : la dérive de placement d'un garé, qui suit le passage de
    la navette, n'est plus prise pour un déplacement ; un vrai mobile reste mobile."""

    def test_the_shuttle_travel_is_the_length_of_its_path(self):
        sh = shuttle(0.0, 20.0, 5.0)
        self.assertAlmostEqual(mt.shuttle_travel_m(sh, 2.0, 10.0), 40.0, places=6)
        self.assertEqual(mt.shuttle_travel_m(sh, 10.0, 2.0), 0.0)

    def test_a_parked_car_drifting_while_the_shuttle_passes_is_parked(self):
        """6 m de dérive pendant que la navette parcourt ~50 m : la garde absolue le dit mobile."""
        sh = shuttle(0.0, 15.0, 5.0)
        hs = track(150, 0.0, 0.1, 30, 8, 0.6, 0.0, noise=0.8)
        motion = mt.parked_motion(hs, sh)
        self.assertTrue(mt.is_moving(*motion), 'le cas réel : la garde absolue le rejette')
        self.assertFalse(mt.is_moving(*motion, vs_shuttle=True))

    def test_a_vehicle_moving_while_the_shuttle_is_stopped_moves(self):
        sh = shuttle(0.0, 15.0, 0.0)
        motion = mt.parked_motion(track(105, 2.0, 0.072, 0, 0, 3.4, 0.0, noise=1.5), sh)
        self.assertTrue(mt.is_moving(*motion, vs_shuttle=True))

    def test_a_vehicle_driving_alongside_the_shuttle_moves(self):
        sh = shuttle(0.0, 15.0, 5.0)
        motion = mt.parked_motion(track(120, 0.0, 0.1, 0, 8, 4.5, 0.0, noise=1.0), sh)
        self.assertTrue(mt.is_moving(*motion, vs_shuttle=True))

    def test_the_toggle_off_keeps_the_absolute_guard(self):
        self.assertTrue(mt.is_moving(6.0, 0.8, 100.0))
        self.assertFalse(mt.is_moving(4.0, 0.8, 0.0))

    def test_the_measure_counts_what_each_share_would_keep_moving(self):
        motion = {1: (6.0, 0.8, 50.0), 2: (20.0, 3.0, 0.0), 3: (2.0, 0.2, 30.0)}
        gates = {1: 'en_mouvement', 2: 'en_mouvement', 3: 'retenu'}
        stats = mt.parked_motion_stats(motion, gates)
        self.assertEqual(stats['absolute_moving'], 2)
        self.assertEqual(stats['still_moving_vs_shuttle']['0.2'], 1)
        self.assertEqual(stats['share_by_gate']['en_mouvement']['shuttle_still'], 1)
        self.assertEqual(mt.parked_motion_stats({}, {}), {})

    def test_the_long_exposure_candidates_take_the_same_guard(self):
        src = inspect.getsource(mt.annotate_global_tracks)
        self.assertIn("moving=_moving if _vs_shuttle else None", src)
