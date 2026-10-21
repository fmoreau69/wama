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

    def test_a_quiet_voice_and_a_loud_one_end_at_the_same_level(self):
        """Les deux passages sont ÉGALISÉS (26 dB d'écart à l'entrée) — leur niveau absolu, lui,
        suit la normalisation de crête (2026-10-21)."""
        quiet, loud = _tone(4, -38), _tone(4, -12)
        out = level_speech(np.concatenate([self.noise(1), quiet, self.noise(1), loud, self.noise(1)]))
        q = out[int(2 * SR):int(4 * SR)]            # cœur de chaque voix, loin des transitions
        l_ = out[int(7 * SR):int(9 * SR)]
        self.assertAlmostEqual(_db(q), _db(l_), delta=2.0)

    def test_the_noise_of_a_silence_is_not_pumped_to_speech_level(self):
        """Dans un silence, le gain est celui des mots voisins — le bruit reste loin sous la voix."""
        out = level_speech(np.concatenate([_tone(3, -26), self.noise(3), _tone(3, -26)]))
        silence = out[int(3.8 * SR):int(5.2 * SR)]
        self.assertLess(_db(silence), _db(out[int(0.5 * SR):int(2.5 * SR)]) - 25.0)

    def test_a_loud_voice_is_never_brought_down(self):
        """« Être sûr qu'on n'abaisse jamais le niveau global » (Fabien, 2026-10-21) : une parole à
        −10 dBFS sortait à −20 dBFS, la cible du nivellement."""
        wave = np.concatenate([self.noise(1), _tone(4, -10), self.noise(1)])
        out = level_speech(wave)
        self.assertGreaterEqual(_db(out[int(1.5 * SR):int(4.5 * SR)]),
                                _db(wave[int(1.5 * SR):int(4.5 * SR)]) - 0.5)

    def test_the_headroom_is_used_up_to_the_peak_limit(self):
        """Une parole basse monte jusqu'à ce que sa crête touche 0,98 (−0,2 dBFS), sans la dépasser."""
        out = level_speech(np.concatenate([self.noise(1), _tone(4, -40), self.noise(1)]))
        self.assertAlmostEqual(0.98, float(np.abs(out).max()), delta=0.02)

    def test_the_peaks_stay_bounded_and_the_length_is_kept(self):
        wave = np.concatenate([_tone(2, -40), _tone(2, -2)])
        out = level_speech(wave)
        self.assertEqual(len(wave), len(out))
        self.assertLessEqual(float(np.abs(out).max()), 0.98 + 1e-6)

    def test_an_empty_signal_stays_empty(self):
        self.assertEqual(0, len(level_speech(np.zeros(0, dtype=np.float32))))
