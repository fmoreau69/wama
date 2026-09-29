"""`kalman_rts_bias_2d` — un biais lent (est, nord) observé seulement par projections latérales.

Motif (2026-09-29) : le recalage voie + carte ne mesure que la composante du biais GPS
PERPENDICULAIRE à la route ; entre deux ancres il retombait à zéro, et une boucle de
retournement sans ancre gardait le GPS brut. Le lisseur combine des routes d'orientations
différentes et porte l'estimation dans les trous.
"""
import numpy as np
from django.test import SimpleTestCase

from wama_data.functions.kinematics.rts_smoother import kalman_rts_bias_2d

TRUE_E, TRUE_N = 2.0, -3.0


def _lateral(t, normal):
    ne, nn = normal
    return (t, ne, nn, ne * TRUE_E + nn * TRUE_N)


NORTH_ROAD = (1.0, 0.0)          # droite d'un cap nord = est
EAST_ROAD = (0.0, -1.0)          # droite d'un cap est = sud


class BiasSmootherTest(SimpleTestCase):
    def test_two_road_orientations_make_both_components_observable(self):
        obs = [_lateral(t, NORTH_ROAD) for t in range(0, 20)] + [_lateral(t, EAST_ROAD) for t in range(20, 40)]
        be, bn, smin, smax, rej = kalman_rts_bias_2d(obs, [10.0, 30.0], sigma_m=0.3, q=0.001)
        self.assertEqual(rej, 0)
        for k in range(2):
            self.assertAlmostEqual(be[k], TRUE_E, delta=0.15)
            self.assertAlmostEqual(bn[k], TRUE_N, delta=0.15)
        self.assertLess(smax[0], 1.0)                 # le longitudinal aussi est connu

    def test_the_estimate_is_carried_through_a_gap_without_anchors(self):
        obs = ([_lateral(t, NORTH_ROAD) for t in range(0, 10)] + [_lateral(t, EAST_ROAD) for t in range(10, 20)]
               + [_lateral(t, NORTH_ROAD) for t in range(60, 70)])
        be, bn, smin, _, _ = kalman_rts_bias_2d(obs, [40.0], sigma_m=0.3, q=0.01)
        self.assertAlmostEqual(be[0], TRUE_E, delta=0.3)
        self.assertAlmostEqual(bn[0], TRUE_N, delta=0.6)
        self.assertLess(smin[0], 1.5)

    def test_an_outlier_anchor_is_rejected(self):
        obs = [_lateral(t, NORTH_ROAD) for t in range(0, 30)]
        obs.insert(15, (15.5, 1.0, 0.0, 14.0))        # ancre prise sur la mauvaise route
        be, _, _, _, rej = kalman_rts_bias_2d(obs, [15.5], sigma_m=0.3, q=0.001)
        self.assertEqual(rej, 1)
        self.assertAlmostEqual(be[0], TRUE_E, delta=0.2)

    def test_a_straight_road_does_not_invent_the_longitudinal_component(self):
        obs = [_lateral(t, NORTH_ROAD) for t in range(0, 30)]
        be, bn, smin, smax, _ = kalman_rts_bias_2d(obs, [15.0], sigma_m=0.3, q=0.001)
        self.assertAlmostEqual(bn[0], 0.0, delta=1e-6)   # a priori nul, jamais observé
        self.assertLess(smin[0], 0.3)
        self.assertGreater(smax[0], 5.0)
