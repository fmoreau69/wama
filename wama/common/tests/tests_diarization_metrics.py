"""cpWER et DER (`diarization_metrics`, 2026-09-30) — textes et temps inventés.

⚠ Identifiants en anglais ; commentaires et docstrings en français.
"""
from django.test import SimpleTestCase

from wama.common.services.diarization_metrics import (
    UNATTRIBUTED, cp_word_error_rate, diarization_error_rate, is_diarized,
)


def seg(speaker, start, end, text):
    return {'speaker_id': speaker, 'start_time': start, 'end_time': end, 'text': text}


REFERENCE = [
    seg('SPEAKER_01', 0.0, 4.0, 'bonjour à tous merci d être venus'),
    seg('SPEAKER_02', 4.0, 7.0, 'merci pour l invitation'),
    seg('SPEAKER_01', 7.0, 10.0, 'commençons par le budget'),
]


class CpWerTest(SimpleTestCase):

    def test_a_perfect_diarization_costs_nothing_beyond_the_words(self):
        hypothesis = [
            seg('A', 0.0, 4.0, 'bonjour à tous merci d être venu'),       # une erreur de mot
            seg('B', 4.0, 7.0, 'merci pour l invitation'),
            seg('A', 7.0, 10.0, 'commençons par le budget'),
        ]
        measure = cp_word_error_rate(REFERENCE, hypothesis)
        self.assertEqual(1, measure.errors)
        self.assertEqual(1, measure.word_errors)
        self.assertEqual(0, measure.attribution_errors)
        self.assertEqual({'SPEAKER_01': 'A', 'SPEAKER_02': 'B'}, measure.mapping)

    def test_swapped_labels_are_matched_not_counted(self):
        hypothesis = [seg('SPEAKER_02' if s['speaker_id'] == 'SPEAKER_01' else 'SPEAKER_01',
                          s['start_time'], s['end_time'], s['text']) for s in REFERENCE]
        measure = cp_word_error_rate(REFERENCE, hypothesis)
        self.assertEqual(0, measure.errors)
        self.assertEqual(0.0, measure.rate)

    def test_a_turn_given_to_the_wrong_speaker_is_an_error_the_wer_does_not_see(self):
        hypothesis = [
            seg('A', 0.0, 4.0, 'bonjour à tous merci d être venus'),
            seg('A', 4.0, 7.0, 'merci pour l invitation'),                # prêté au mauvais
            seg('A', 7.0, 10.0, 'commençons par le budget'),
        ]
        measure = cp_word_error_rate(REFERENCE, hypothesis)
        self.assertEqual(0, measure.word_errors)
        # Les 4 mots de SPEAKER_02 sont manqués chez lui ET insérés chez SPEAKER_01.
        self.assertEqual(8, measure.errors)
        self.assertEqual(8, measure.attribution_errors)
        self.assertEqual('', measure.mapping['SPEAKER_02'])

    def test_unattributed_words_form_a_speaker_of_their_own(self):
        hypothesis = [dict(s) for s in REFERENCE]
        hypothesis[1]['speaker_id'] = ''
        measure = cp_word_error_rate(REFERENCE, hypothesis)
        self.assertEqual(UNATTRIBUTED, measure.mapping['SPEAKER_02'])
        self.assertEqual(0, measure.errors)

    def test_without_speakers_on_either_side_there_is_nothing_to_measure(self):
        undiarized = [dict(s, speaker_id='') for s in REFERENCE]
        self.assertIsNone(cp_word_error_rate(REFERENCE, undiarized))
        self.assertIsNone(cp_word_error_rate(undiarized, REFERENCE))
        self.assertFalse(is_diarized(undiarized))


class DerTest(SimpleTestCase):

    def test_the_same_turns_under_other_names_score_zero(self):
        hypothesis = [dict(s, speaker_id={'SPEAKER_01': 'x', 'SPEAKER_02': 'y'}[s['speaker_id']])
                      for s in REFERENCE]
        measure = diarization_error_rate(REFERENCE, hypothesis)
        self.assertEqual(0.0, measure.rate)
        self.assertEqual(10.0, measure.reference_length)

    def test_components_separate_missed_speech_from_confusion(self):
        hypothesis = [
            seg('x', 0.0, 4.0, '…'),
            seg('x', 4.0, 7.0, '…'),          # 3 s de confusion
            # 7 → 10 s : rien — 3 s de parole manquée
        ]
        measure = diarization_error_rate(REFERENCE, hypothesis)
        self.assertEqual(3.0, measure.confusion)
        self.assertEqual(3.0, measure.missed)
        self.assertEqual(0.0, measure.false_alarm)
        self.assertEqual(0.6, measure.rate)
        self.assertEqual(6.0, measure.as_dict()['errors'])

    def test_untimed_segments_have_no_der(self):
        untimed = [dict(s, start_time=None, end_time=None) for s in REFERENCE]
        self.assertIsNone(diarization_error_rate(untimed, REFERENCE))
