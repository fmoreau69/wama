"""Orientation de montage par mouvement connu (`known_motion_yaw`) — sur scène SYNTHÉTIQUE.

La géométrie vraie est connue : un véhicule tourne puis roule droit, des points du décor sont vus
par une caméra de lacet / tangage / montage donnés. La mesure doit retrouver le lacet depuis un a
priori FAUX (c'est le cas réel : ±75° saisis, 67,5° mesurés), et le retard de la trace.
"""
import math
import unittest

import numpy as np

from .known_motion_yaw import fit_mount_yaw, _rot_camera_to_vehicle, _rot_vehicle_to_world

W, H, FX = 384.0, 244.0, 245.0


def _scene(yaw_deg, pitch_deg, mount, *, trace_lag_s=0.0, seed=0, turning=True):
    rng = np.random.default_rng(seed)
    dt = 0.05
    ts = np.arange(0.0, 70.0, dt)
    rate = (np.radians(12.0) * np.sin(2 * np.pi * ts / 35.0)) if turning else np.zeros_like(ts)
    h = np.cumsum(rate) * dt
    v = 5.0
    e = np.cumsum(v * np.sin(h)) * dt
    n = np.cumsum(v * np.cos(h)) * dt
    # décor : points le long du trajet, des deux côtés, à 3-25 m, hauteur 0-4 m
    k = rng.integers(0, len(ts), 6000)
    side = rng.choice([-1.0, 1.0], 6000)
    off = side * rng.uniform(3.0, 25.0, 6000)
    along = rng.uniform(-10.0, 10.0, 6000)
    pts = np.stack([e[k] + off * np.cos(h[k]) + along * np.sin(h[k]),
                    n[k] - off * np.sin(h[k]) + along * np.cos(h[k]),
                    rng.uniform(-2.4, 2.0, 6000)], axis=1)          # caméra à 2,4 m du sol
    Rvc = _rot_camera_to_vehicle(yaw_deg, pitch_deg)
    mnt = np.array([mount[0], mount[1], 0.0])

    def project(t):
        hh = np.interp(t, ts, h)
        p = np.array([np.interp(t, ts, e), np.interp(t, ts, n), 0.0])
        Rv = _rot_vehicle_to_world(np.array([hh]))[0]
        c = p + Rv @ mnt
        Xc = (pts - c) @ (Rv @ Rvc)
        ok = Xc[:, 2] > 1.0
        u = W / 2 + FX * Xc[:, 0] / np.where(ok, Xc[:, 2], 1)
        vv = H / 2 + FX * Xc[:, 1] / np.where(ok, Xc[:, 2], 1)
        ok &= (u >= 0) & (u < W) & (vv >= 0) & (vv < H)
        return u, vv, ok

    pairs = []
    for t0 in np.arange(2.0, 66.0, 0.25):
        t1 = t0 + 1.0 / 6.0
        u0, v0, ok0 = project(t0)
        u1, v1, ok1 = project(t1)
        ok = ok0 & ok1
        m = np.stack([u0[ok], v0[ok], u1[ok], v1[ok]], axis=1)
        m[:, 2:] += rng.normal(0, 0.3, m[:, 2:].shape)              # bruit de suivi
        pairs.append((t0, t1, m))
    # la trace fournie RETARDE de `trace_lag_s` : son instant t décrit l'état vrai en t − lag
    traj = np.stack([ts + trace_lag_s, e, n, np.degrees(h)], axis=1)
    return pairs, traj


class KnownMotionYawTest(unittest.TestCase):

    def test_a_side_camera_yaw_is_recovered_from_a_wrong_prior(self):
        pairs, traj = _scene(67.5, 20.0, (1.0, 3.4))
        r = fit_mount_yaw(pairs, traj, image_size=(W, H), focal_px=FX, mount=(1.0, 3.4),
                          yaw0_deg=75.0, pitch0_deg=20.0, k1_values=(0.0,), lags_s=(0.0,))
        self.assertTrue(r['measured'], r)
        self.assertAlmostEqual(r['yaw_deg'], 67.5, delta=0.7)
        self.assertLess(r['cost'], r['cost_prior'])

    def test_a_left_camera_and_a_front_control_are_recovered_too(self):
        for yaw, mount in ((-77.5, (-1.0, 3.4)), (0.0, (0.0, 4.5))):
            pairs, traj = _scene(yaw, 15.0, mount, seed=1)
            r = fit_mount_yaw(pairs, traj, image_size=(W, H), focal_px=FX, mount=mount,
                              yaw0_deg=yaw + 6.0, pitch0_deg=15.0, k1_values=(0.0,), lags_s=(0.0,))
            self.assertAlmostEqual(r['yaw_deg'], yaw, delta=0.7, msg=r)

    def test_the_trace_lag_is_estimated_before_the_yaw(self):
        pairs, traj = _scene(67.5, 20.0, (1.0, 3.4), trace_lag_s=0.5)
        r = fit_mount_yaw(pairs, traj, image_size=(W, H), focal_px=FX, mount=(1.0, 3.4),
                          yaw0_deg=70.0, pitch0_deg=20.0, k1_values=(0.0,))
        self.assertEqual(r['lag_s'], 0.5)
        self.assertAlmostEqual(r['yaw_deg'], 67.5, delta=0.7)

    def test_an_optimum_on_the_grid_edge_is_not_called_measured(self):
        pairs, traj = _scene(67.5, 20.0, (1.0, 3.4))
        r = fit_mount_yaw(pairs, traj, image_size=(W, H), focal_px=FX, mount=(1.0, 3.4),
                          yaw0_deg=90.0, pitch0_deg=20.0, yaw_span_deg=10.0, k1_values=(0.0,),
                          lags_s=(0.0,))
        self.assertTrue(r['at_bound'])
        self.assertFalse(r['measured'])

    def test_too_few_moving_pairs_return_nothing(self):
        pairs, traj = _scene(67.5, 20.0, (1.0, 3.4))
        self.assertIsNone(fit_mount_yaw(pairs[:10], traj, image_size=(W, H), focal_px=FX))


if __name__ == '__main__':
    unittest.main()
