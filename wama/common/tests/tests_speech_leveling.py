"""Nivellement de la parole (`utils/speech_leveling.py`) — sur des signaux synthétiques.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
import numpy as np
from django.test import SimpleTestCase

from wama.common.utils.speech_leveling import level_speech

SR = 16000


def _tone(seconds, db, freq=220.0):
    """Une « voix » : sinusoïde au niveau moyen `db` dBFS."""
    t = np.arange(int(seconds * SR)) / SR
    amplitude = np.sqrt(2) * 10 ** (db / 20)
    return (amplitude * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def _db(x):
    return 10 * np.log10(np.mean(np.asarray(x, dtype=np.float64) ** 2) + 1e-12)


class LevelSpeechTest(SimpleTestCase):

    def setUp(self):
        rng = np.random.default_rng(0)
        self.noise = lambda s: (rng.standard_normal(int(s * SR)) * 10 ** (-60 / 20)).astype(np.float32)

    def test_a_quiet_voice_and_a_loud_one_end_near_the_target(self):
        quiet, loud = _tone(4, -38), _tone(4, -12)
        out = level_speech(np.concatenate([self.noise(1), quiet, self.noise(1), loud, self.noise(1)]))
        q = out[int(2 * SR):int(4 * SR)]            # cœur de chaque voix, loin des transitions
        l_ = out[int(7 * SR):int(9 * SR)]
        self.assertAlmostEqual(-20.0, _db(q), delta=2.0)
        self.assertAlmostEqual(-20.0, _db(l_), delta=2.0)

    def test_the_noise_of_a_silence_is_not_pumped_to_speech_level(self):
        """Dans un silence, le gain est celui des mots voisins — le bruit reste loin sous la voix."""
        out = level_speech(np.concatenate([_tone(3, -26), self.noise(3), _tone(3, -26)]))
        silence = out[int(3.8 * SR):int(5.2 * SR)]
        self.assertLess(_db(silence), -45.0)

    def test_the_peaks_stay_bounded_and_the_length_is_kept(self):
        wave = np.concatenate([_tone(2, -40), _tone(2, -2)])
        out = level_speech(wave)
        self.assertEqual(len(wave), len(out))
        self.assertLessEqual(float(np.abs(out).max()), 0.98 + 1e-6)

    def test_an_empty_signal_stays_empty(self):
        self.assertEqual(0, len(level_speech(np.zeros(0, dtype=np.float32))))
