"""Langues parlées d'un audio (`utils/spoken_language.py`) et leur étiquetage par Whisper.

⚠ Identifiants en anglais ; commentaires et docstrings en français. Aucun modèle chargé.
"""
from unittest import mock

import numpy as np
from django.test import SimpleTestCase

from wama.common.backends.speech_to_text_base import TranscriptionSegment
from wama.common.utils.spoken_language import (
    dominant_language, language_agreement, language_shares, languages_heard,
)


class LanguageAgreementTest(SimpleTestCase):
    REFERENCE = [{'start_time': 0.0, 'end_time': 10.0, 'language': 'en'},
                 {'start_time': 10.0, 'end_time': 20.0, 'language': 'fr'}]

    def test_time_in_the_right_language_is_agreement_the_rest_only_coverage(self):
        """Un seul segment « fr » sur 0-20 s : la moitié française est juste, l'anglaise non."""
        hypothesis = [{'start_time': 0.0, 'end_time': 20.0, 'language': 'fr'}]
        self.assertEqual({'agreement': 0.5, 'covered': 1.0},
                         language_agreement(self.REFERENCE, hypothesis))

    def test_what_is_not_transcribed_is_not_covered(self):
        hypothesis = [TranscriptionSegment('', 12.0, 20.0, 'x', language='fr')]
        self.assertEqual({'agreement': 0.4, 'covered': 0.4},
                         language_agreement(self.REFERENCE, hypothesis))

    def test_a_reference_without_languages_has_no_agreement(self):
        self.assertEqual({'agreement': None, 'covered': None},
                         language_agreement([{'start_time': 0, 'end_time': 5}], []))


class ProbeWindowsTest(SimpleTestCase):
    """La sonde écoute par fenêtres de 10 s (une phrase), pas 30 s (FLEURS-CS, 2026-09-29)."""

    def test_a_five_minute_file_is_heard_in_24_ten_second_windows_spread_over_it(self):
        from wama.common.utils import spoken_language
        windows = []

        def decode(path, target_sr, start_s, duration_s):
            windows.append((start_s, duration_s))
            return np.zeros(16000, dtype=np.float32), 16000
        with mock.patch('wama.common.utils.audio_decode.decode_window', side_effect=decode), \
                mock.patch.object(spoken_language, '_model') as model:
            model.return_value.detect_language.return_value = ('fr', 0.9, [])
            heard = spoken_language.probe_languages('x.wav', 300.0)
        self.assertEqual(24, len(heard))
        self.assertTrue(all(d == 10 for _, d in windows))
        self.assertLess(windows[0][0], 10)
        self.assertGreater(windows[-1][0], 280)


class LanguagesHeardTest(SimpleTestCase):

    def test_only_confident_windows_vote_and_the_most_frequent_comes_first(self):
        probe = [('fr', 0.9), ('en', 0.8), ('fr', 0.95), ('de', 0.4)]
        self.assertEqual(['fr', 'en'], languages_heard(probe))

    def test_a_silent_probe_hears_nothing(self):
        self.assertEqual([], languages_heard([('en', 0.3)]))


class DominantLanguageTest(SimpleTestCase):

    def test_the_most_spoken_language_wins_not_the_first_one(self):
        segments = [TranscriptionSegment('', 0.0, 5.0, 'intro', language='en'),
                    {'start_time': 5.0, 'end_time': 60.0, 'text': 'suite', 'language': 'fr'}]
        self.assertEqual({'en': 5.0, 'fr': 55.0}, language_shares(segments))
        self.assertEqual('fr', dominant_language(segments))

    def test_segments_without_language_leave_the_fallback(self):
        self.assertEqual('fr', dominant_language([TranscriptionSegment('', 0, 1, 'x')], 'fr'))


class WhisperWindowLanguagesTest(SimpleTestCase):
    """Whisper multilingue : chaque segment prend la langue de SA fenêtre de 30 s."""

    def _backend(self, by_window):
        from wama.common.backends.whisper_backend import WhisperBackend
        backend = WhisperBackend.__new__(WhisperBackend)
        calls = []

        def detect_language(audio):
            calls.append(int(audio[0]))
            return by_window[int(audio[0])], 0.9, []
        backend._model = mock.Mock(detect_language=detect_language)
        return backend, calls

    def test_each_segment_takes_the_language_of_its_window_detected_once(self):
        backend, calls = self._backend({0: 'fr', 2: 'en'})
        segments = [TranscriptionSegment('', 1.0, 4.0, 'a'), TranscriptionSegment('', 10.0, 20.0, 'b'),
                    TranscriptionSegment('', 61.0, 65.0, 'c')]
        # La fenêtre décodée porte son index en 1ᵉʳ échantillon : le faux modèle le lit.
        fake_window = lambda path, start_s, duration_s: (np.array([start_s // 30], dtype=np.float32), 16000)
        with mock.patch('wama.common.utils.audio_decode.decode_window', side_effect=fake_window):
            backend._label_window_languages('x.wav', segments, 'fr')
        self.assertEqual(['fr', 'fr', 'en'], [s.language for s in segments])
        self.assertEqual([0, 2], sorted(calls), 'une détection par fenêtre, pas par segment')

    def test_an_unreadable_window_falls_back_to_the_global_language(self):
        backend, _ = self._backend({})
        segments = [TranscriptionSegment('', 1.0, 2.0, 'a')]
        with mock.patch('wama.common.utils.audio_decode.decode_window',
                        side_effect=RuntimeError('ffmpeg')):
            backend._label_window_languages('x.wav', segments, 'de')
        self.assertEqual('de', segments[0].language)
