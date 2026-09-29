"""The speech-activity probe: does the VAD keep what the signal carries? (2026-09-25)"""
import contextlib
from unittest import mock

import numpy as np
from django.test import SimpleTestCase

from wama.common.utils import speech_activity

SR = 16000


def _bursts(seconds=120.0, level=0.3, on_s=1.0, off_s=0.5, seed=0):
    """Noise bursts over a quiet floor: ~2/3 of the frames are active to the energy measure."""
    rng = np.random.default_rng(seed)
    wave = rng.normal(0, 0.001, int(seconds * SR)).astype('float32')
    period = int((on_s + off_s) * SR)
    for start in range(0, len(wave), period):
        end = min(len(wave), start + int(on_s * SR))
        wave[start:end] += rng.normal(0, level, end - start).astype('float32')
    return wave


class SpeechActivityTest(SimpleTestCase):

    def _probe(self, wave, vad_ratio=None, duration=600.0):
        calls = []

        def decode(path, sr, start, duration_s):
            calls.append(start)
            return wave, SR
        patch = (mock.patch.object(speech_activity, 'vad_speech_ratio', return_value=vad_ratio)
                 if vad_ratio is not None else contextlib.nullcontext())
        with patch:
            result = speech_activity.vad_rejects_speech('x.wav', duration, decode=decode)
        return result, calls

    def test_the_energy_measure_sees_the_active_frames_over_the_noise_floor(self):
        ratio = speech_activity.energy_active_ratio(_bursts(), SR)
        self.assertAlmostEqual(2 / 3, ratio, delta=0.05)

    def test_a_vad_that_keeps_little_of_an_active_signal_rejects_speech(self):
        result, _ = self._probe(_bursts(), vad_ratio=0.2)
        self.assertTrue(result['rejects'])

    def test_a_vad_that_keeps_what_the_signal_carries_is_kept(self):
        result, _ = self._probe(_bursts(), vad_ratio=0.7)
        self.assertFalse(result['rejects'])

    def test_a_mostly_silent_recording_has_nothing_to_decide(self):
        quiet = np.random.default_rng(1).normal(0, 0.001, 120 * SR).astype('float32')
        result, _ = self._probe(quiet, vad_ratio=0.0)
        self.assertFalse(result['rejects'])

    def test_three_windows_spread_across_a_long_recording_one_for_a_short_one(self):
        _, calls = self._probe(_bursts(), vad_ratio=0.7, duration=600.0)
        self.assertEqual(3, len(calls))
        self.assertTrue(calls[0] < calls[1] < calls[2] < 600.0)
        _, calls = self._probe(_bursts(), vad_ratio=0.7, duration=60.0)
        self.assertEqual([0.0], calls)

    def test_the_real_silero_vad_does_not_take_noise_bursts_for_speech(self):
        """Contre-épreuve sur le vrai VAD : du bruit actif n'est pas de la parole — c'est le cas
        où le VAD rejette, et la sonde le dit."""
        result, _ = self._probe(_bursts(), vad_ratio=None)
        self.assertLess(result['vad'], 0.3)
        self.assertTrue(result['rejects'])
