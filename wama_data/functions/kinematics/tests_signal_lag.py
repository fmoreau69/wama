"""`estimate_lag` — le retard d'un signal sur un autre, par corrélation (2026-10-13 : la latence du
GPS sur la vidéo du cam_analyzer)."""
import numpy as np
from django.test import SimpleTestCase

from wama_data.functions.kinematics.signal_lag import estimate_lag


def _signal(t):
    return np.sin(0.7 * t) + 0.5 * np.sin(1.9 * t + 1.0)


class EstimateLagTest(SimpleTestCase):

    def test_a_late_signal_gives_a_positive_lag(self):
        t = np.arange(0.0, 300.0, 0.1)
        res = estimate_lag(t, _signal(t), t, _signal(t - 0.4))
        self.assertAlmostEqual(res['lag_s'], 0.4, places=2)
        self.assertGreater(res['r'], res['r_at_zero'])

    def test_an_early_signal_gives_a_negative_lag(self):
        t = np.arange(0.0, 300.0, 0.1)
        self.assertAlmostEqual(estimate_lag(t, _signal(t), t, _signal(t + 0.6))['lag_s'], -0.6, places=2)

    def test_the_two_series_need_not_share_their_timestamps(self):
        tr, ts = np.arange(0.0, 300.0, 1 / 6), np.arange(0.3, 300.0, 1.0)
        res = estimate_lag(tr, _signal(tr), ts, _signal(ts - 0.5))
        self.assertLessEqual(abs(res['lag_s'] - 0.5), 0.1)

    def test_the_mask_restricts_the_counted_instants(self):
        t = np.arange(0.0, 300.0, 0.1)
        whole = estimate_lag(t, _signal(t), t, _signal(t - 0.4))
        res = estimate_lag(t, _signal(t), t, _signal(t - 0.4), mask=lambda g: g < 100)
        self.assertLess(res['samples'], whole['samples'] / 2)
        self.assertAlmostEqual(res['lag_s'], 0.4, places=2)

    def test_too_short_series_give_nothing(self):
        t = np.arange(0.0, 5.0, 0.1)
        self.assertIsNone(estimate_lag(t, _signal(t), t, _signal(t)))
