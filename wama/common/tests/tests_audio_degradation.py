"""Dégradation contrôlée (`audio_degradation`, 2026-09-30) — signaux synthétiques.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
import numpy as np
from django.test import SimpleTestCase

from wama.common.utils import audio_degradation as degradation

SR = 16000


def _speech_like(seconds=6.0):
    """Des « mots » (sinus modulés) séparés de silences — une parole active ~2/3 du temps."""
    t = np.arange(int(seconds * SR)) / SR
    tone = 0.1 * np.sin(2 * np.pi * 220 * t) * (1 + 0.3 * np.sin(2 * np.pi * 3 * t))
    gate = (np.floor(t / 0.5) % 3 != 2).astype(np.float32)
    return (tone * gate).astype(np.float32)


class DegradationTest(SimpleTestCase):

    def test_the_noise_lands_at_the_declared_signal_to_noise_ratio(self):
        clean = _speech_like()
        noisy = degradation.add_noise(clean, SR, 10.0, np.random.default_rng(0))
        noise = noisy - clean
        snr = 10 * np.log10(degradation.active_power(clean, SR) / np.mean(noise ** 2))
        self.assertAlmostEqual(10.0, snr, delta=0.5)

    def test_a_profile_rebuilds_the_same_file(self):
        clean = _speech_like()
        np.testing.assert_array_equal(degradation.degrade(clean, SR, 'far_field'),
                                      degradation.degrade(clean, SR, 'far_field'))

    def test_two_profiles_are_two_different_signals(self):
        clean = _speech_like()
        self.assertFalse(np.allclose(degradation.degrade(clean, SR, 'noise_snr15'),
                                     degradation.degrade(clean, SR, 'noise_snr5')))

    def test_far_field_is_quieter_by_the_declared_attenuation(self):
        clean = _speech_like()
        far = degradation.degrade(clean, SR, 'far_field')
        drop = 10 * np.log10(degradation.active_power(clean, SR) / degradation.active_power(far, SR))
        self.assertAlmostEqual(20.0, drop, delta=1.5)

    def test_reverberation_keeps_the_speech_level(self):
        clean = _speech_like()
        wet = degradation.reverberate(clean, SR, 0.7, np.random.default_rng(0))
        self.assertAlmostEqual(degradation.active_power(clean, SR),
                               degradation.active_power(wet, SR), delta=0.1 * degradation.active_power(clean, SR))
        self.assertEqual(len(clean), len(wet))

    def test_peaks_stay_under_full_scale(self):
        loud = _speech_like() * 9.0
        self.assertLess(np.abs(degradation.degrade(loud, SR, 'noise_snr5')).max(), 1.0)
