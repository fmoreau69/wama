"""Non-régression de `smooth_track` après sa DÉLÉGATION à la brique commune (2026-09-05).

L'empreinte ci-dessous a été produite par l'implémentation d'ORIGINE (celle qui vivait dans
ce module), sur une trajectoire synthétique déterministe, AVANT le déplacement du code vers
`wama_data.functions.kinematics.rts_smoother`. Si un chiffre bouge, la délégation a changé
les objets — ce que ce déplacement promettait de ne pas faire.
"""
import math
import random
import unittest

from wama_lab.cam_analyzer.utils.trajectory_smoother import smooth_track

#: (index de sortie, t, x, y, vx, vy) — sortie de l'implémentation d'origine, 6 décimales.
EMPREINTE = [
    (0,  0.000000, 0.088816, -0.237054, 2.885893, 0.418319),
    (5,  0.416700, 1.296777, -0.058414, 2.909750, 0.447960),
    (10, 0.833300, 2.509849,  0.141101, 2.909624, 0.514288),
    (20, 1.666700, 4.913014,  0.652182, 2.858903, 0.711550),
    (39, 3.250000, 9.353180,  1.938277, 2.756057, 0.857157),
]


def _fixture():
    rng = random.Random(2026)
    pts = []
    for i in range(40):
        t = i / 12.0
        ang = (3.0 * t) / 20.0
        x = 20.0 * math.sin(ang) + rng.gauss(0, 0.4)
        y = 20.0 * (1 - math.cos(ang)) + rng.gauss(0, 0.4)
        pts.append((t, x, y))
    pts.insert(11, (pts[10][0], pts[10][1] + 0.3, pts[10][2] - 0.2))   # doublon de t
    return pts


class NonRegressionTest(unittest.TestCase):

    def test_les_chiffres_d_origine_sont_reproduits_a_1e6(self):
        out = smooth_track(_fixture())
        self.assertEqual(len(out), 40, "41 entrées, doublon moyenné → 40 sorties")
        for idx, *attendu in EMPREINTE:
            with self.subTest(index=idx):
                for v, a in zip(out[idx], attendu):
                    self.assertAlmostEqual(v, a, places=5)


if __name__ == '__main__':
    unittest.main(verbosity=2)
