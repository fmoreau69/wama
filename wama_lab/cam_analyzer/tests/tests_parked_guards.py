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
        self.assertIn("robust_displacement(hs)", branch)
        self.assertIn("porte = 'en_mouvement'", branch)
        self.assertIn("parked_motion_guard", branch)
