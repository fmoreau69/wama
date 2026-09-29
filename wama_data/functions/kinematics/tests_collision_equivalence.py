"""TTC/PET vectorisé (2026-09-29) — MÊMES verdicts que les boucles d'origine.

La passe Indicateurs du cam_analyzer passait ~75 % de son temps dans la collision (≈ 340 tests
SAT scalaires par instant évalué), le reste dans un Kalman 6×6 bloc-diagonal et dans une boucle
de conversion en empreintes. Les trois ont été réécrits en numpy SANS changer un seul résultat
— rejoué sur 17 670 détections de la session de référence : 0 divergence, ×4.
Ces tests gardent cette équivalence contre les implémentations d'ORIGINE, recopiées ici
telles quelles : c'est la seule définition du « même résultat » qui ne dépende pas du code testé.
"""
import unittest

import numpy as np

from ..geometry.shapes import (point_traj_to_shape, rect_intersect_sat,
                               rect_intersect_sat_matrix)
from .collision import collision_detection
from .extrapolation import _ca_kalman_smooth


# ── Implémentations d'ORIGINE (avant 2026-09-29), recopiées sans modification ──────────
def _reference_shape(traj, length_m, width_m, min_speed=1e-6):
    traj = np.asarray(traj, dtype=float)
    n = len(traj)
    out = np.zeros((n, 9))
    out[:, 0] = traj[:, 0]
    hl, hw = length_m / 2.0, width_m / 2.0
    local = np.array([[hl, -hw], [hl, hw], [-hl, hw], [-hl, -hw]])
    last_dir = np.array([1.0, 0.0])
    for i in range(n):
        v = (traj[i + 1, 1:3] - traj[i, 1:3]) if i < n - 1 else (traj[i, 1:3] - traj[i - 1, 1:3]) if i > 0 else np.zeros(2)
        speed = np.hypot(v[0], v[1])
        if speed >= min_speed:
            vx = v / speed
            last_dir = vx
        else:
            vx = last_dir
        vy = np.array([vx[1], -vx[0]])
        pos = traj[i, 1:3]
        for k in range(4):
            world = pos + local[k, 0] * vx + local[k, 1] * vy
            out[i, 1 + 2 * k] = world[0]
            out[i, 2 + 2 * k] = world[1]
    return out


def _reference_kalman(traj, q=1.0, r=0.5):
    traj = np.asarray(traj, dtype=float)
    x = np.zeros(6)
    x[0], x[3] = traj[0, 1], traj[0, 2]
    P = np.eye(6) * 10.0
    H = np.zeros((2, 6)); H[0, 0] = 1; H[1, 3] = 1
    R = np.eye(2) * r
    for i in range(1, len(traj)):
        dt = traj[i, 0] - traj[i - 1, 0]
        if dt <= 0:
            continue
        F = np.eye(6)
        for base in (0, 3):
            F[base, base + 1] = dt
            F[base, base + 2] = 0.5 * dt * dt
            F[base + 1, base + 2] = dt
        G = np.array([0.5 * dt * dt, dt, 1.0])
        Qb = np.outer(G, G) * q
        Q = np.zeros((6, 6)); Q[0:3, 0:3] = Qb; Q[3:6, 3:6] = Qb
        x = F @ x
        P = F @ P @ F.T + Q
        z = np.array([traj[i, 1], traj[i, 2]])
        y = z - H @ x
        S = H @ P @ H.T + R
        K = P @ H.T @ np.linalg.inv(S)
        x = x + K @ y
        P = (np.eye(6) - K @ H) @ P
    return np.array([x[0], x[3], x[1], x[4], x[2], x[5]])


def _reference_collision(shape1, shape2, compute_pet=True, max_pet_steps=None):
    from .collision import _common_times
    row = lambda r: np.array(r[1:9], dtype=float).reshape(4, 2)   # noqa: E731
    i1, i2 = _common_times(shape1[:, 0], shape2[:, 0])
    result = {'ttc': None, 'pet': None, 't_collision': None}
    if len(i1) < 1:
        return result
    t0 = shape1[i1[0], 0]
    for k in range(len(i1)):
        if rect_intersect_sat(row(shape1[i1[k]]), row(shape2[i2[k]])):
            result['ttc'] = float(shape1[i1[k], 0] - t0)
            result['t_collision'] = float(shape1[i1[k], 0])
            break
    if compute_pet:
        n = len(i1)
        max_delta = max_pet_steps if max_pet_steps is not None else n
        best_pet = None
        for k in range(n):
            r2 = row(shape2[i2[k]])
            for delta in range(1, max_delta):
                fa = i1[k] + delta
                if fa < len(shape1) and rect_intersect_sat(row(shape1[fa]), r2):
                    pet = abs(shape1[fa, 0] - shape1[i1[k], 0])
                    best_pet = pet if best_pet is None else min(best_pet, pet)
                    break
                fb = i1[k] - delta
                if fb >= 0 and rect_intersect_sat(row(shape1[fb]), r2):
                    pet = abs(shape1[fb, 0] - shape1[i1[k], 0])
                    best_pet = pet if best_pet is None else min(best_pet, pet)
                    break
        result['pet'] = float(best_pet) if best_pet is not None else None
    return result


def _random_traj(rng, n, origin, speed, stop_at=None):
    """Trajectoire [t, x, y] à pas de 0,2 s, virage aléatoire, arrêt optionnel (orientation gardée)."""
    t = np.arange(n) * 0.2
    heading = rng.uniform(0, 2 * np.pi) + np.cumsum(rng.normal(0, 0.15, n))
    step = np.full(n, speed * 0.2)
    if stop_at is not None:
        step[stop_at:] = 0.0
    x = origin[0] + np.cumsum(step * np.cos(heading))
    y = origin[1] + np.cumsum(step * np.sin(heading))
    return np.column_stack([t, x, y])


class VectorizedSatMatchesScalarTest(unittest.TestCase):

    def test_every_pair_gets_the_scalar_verdict(self):
        rng = np.random.default_rng(7)
        centers = rng.uniform(-6, 6, (60, 2))
        rects = []
        for c in centers:
            a = rng.uniform(0, np.pi)
            u, v = np.array([np.cos(a), np.sin(a)]), np.array([-np.sin(a), np.cos(a)])
            hl, hw = rng.uniform(0.3, 3.0), rng.uniform(0.3, 1.5)
            rects.append([c + hl * u - hw * v, c + hl * u + hw * v,
                          c - hl * u + hw * v, c - hl * u - hw * v])
        rects = np.array(rects)
        matrix = rect_intersect_sat_matrix(rects, rects)
        expected = np.array([[rect_intersect_sat(a, b) for b in rects] for a in rects])
        self.assertTrue((matrix == expected).all())
        self.assertTrue(0 < expected.sum() < expected.size, "the sample must mix both verdicts")

    def test_degenerate_rectangle_skips_null_axes_like_the_scalar(self):
        point = np.zeros((4, 2))                              # toutes les arêtes nulles
        square = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]], float)
        far = square + 10
        for other in (square, far):
            with self.subTest(other=other[0].tolist()):
                self.assertEqual(bool(rect_intersect_sat_matrix(point[None], other[None])[0, 0]),
                                 rect_intersect_sat(point, other))


class ShapeConversionMatchesLoopTest(unittest.TestCase):

    def test_moving_stopping_and_tiny_trajectories_are_bit_identical(self):
        rng = np.random.default_rng(11)
        cases = [_random_traj(rng, 25, (0, 0), 8.0),
                 _random_traj(rng, 25, (3, -2), 5.0, stop_at=10),      # arrêt : cap conservé
                 np.array([[0.0, 1.0, 2.0]]),                            # un seul point
                 np.array([[0.0, 1.0, 2.0], [0.2, 1.0, 2.0]])]           # immobile dès le départ
        for traj in cases:
            with self.subTest(n=len(traj)):
                self.assertTrue(np.array_equal(point_traj_to_shape(traj, 4.5, 1.8),
                                               _reference_shape(traj, 4.5, 1.8)))


class SplitAxisKalmanMatchesSixStateTest(unittest.TestCase):

    def test_final_state_equals_the_block_diagonal_filter(self):
        rng = np.random.default_rng(3)
        for n in (2, 5, 11):
            traj = _random_traj(rng, n, (1, 1), 6.0)
            traj[:, 1:] += rng.normal(0, 0.3, (n, 2))
            with self.subTest(n=n):
                np.testing.assert_allclose(_ca_kalman_smooth(traj), _reference_kalman(traj),
                                           rtol=1e-12, atol=1e-12)

    def test_non_increasing_timestamps_are_skipped_as_before(self):
        traj = np.array([[0.0, 0.0, 0.0], [0.2, 1.0, 0.5], [0.2, 9.0, 9.0], [0.4, 2.0, 1.0]])
        np.testing.assert_allclose(_ca_kalman_smooth(traj), _reference_kalman(traj),
                                   rtol=1e-12, atol=1e-12)


class CollisionMatchesPairwiseLoopTest(unittest.TestCase):

    def test_ttc_and_pet_equal_the_original_on_random_encounters(self):
        rng = np.random.default_rng(5)
        hits = 0
        for _ in range(200):
            a = point_traj_to_shape(_random_traj(rng, 21, (0, 0), rng.uniform(0, 10)), 5.0, 2.2)
            b = point_traj_to_shape(_random_traj(rng, 21, rng.uniform(-8, 8, 2), rng.uniform(0, 10)),
                                    4.5, 1.8)
            for kw in ({'max_pet_steps': 12}, {}):
                got, want = collision_detection(a, b, **kw), _reference_collision(a, b, **kw)
                self.assertEqual(got, want)
            hits += want['pet'] is not None
        self.assertGreater(hits, 20, "the sample must contain real encounters")

    def test_no_common_instant_returns_nothing(self):
        a = point_traj_to_shape(np.array([[0.0, 0, 0], [0.2, 1, 0]]), 4, 2)
        b = point_traj_to_shape(np.array([[5.0, 0, 0], [5.2, 1, 0]]), 4, 2)
        self.assertEqual(collision_detection(a, b), {'ttc': None, 'pet': None, 't_collision': None})


if __name__ == '__main__':
    unittest.main(verbosity=2)
