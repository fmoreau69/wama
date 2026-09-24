"""Ancrage d'un texte sans temps sur des mots horodatés (`services/word_anchoring`)."""
from django.test import SimpleTestCase

from wama.common.services.word_anchoring import anchor_turns


def _words(*spec):
    """(« mot », début, fin) → forme Whisper."""
    return [{'word': ' ' + w, 'start': s, 'end': e, 'probability': 0.9} for w, s, e in spec]


ASR = _words(('le', 0.0, 0.2), ('chien', 0.2, 0.6), ('dort', 0.6, 1.0),
             ('sur', 1.0, 1.2), ('le', 1.2, 1.3), ('tapis', 1.3, 1.8))


class AnchorTurnsTest(SimpleTestCase):

    def test_a_word_heard_the_same_takes_the_asr_time_exactly(self):
        turns, report = anchor_turns([{'text': 'le chien dort'}], ASR)
        self.assertEqual([(0.0, 0.2), (0.2, 0.6), (0.6, 1.0)],
                         [(w['start'], w['end']) for w in turns[0]['words']])
        self.assertEqual((0.0, 1.0), (turns[0]['start_time'], turns[0]['end_time']))
        self.assertEqual(3, report['exact'])

    def test_a_corrected_word_takes_the_real_duration_of_what_the_asr_heard(self):
        """« chien » was really « chat »: the correction lives exactly where the ASR heard a word."""
        turns, report = anchor_turns([{'text': 'le chat dort'}], ASR)
        chat = turns[0]['words'][1]
        self.assertEqual((0.2, 0.6, 'estimated'), (chat['start'], chat['end'], chat['timing']))
        self.assertEqual(1, report['estimated'])

    def test_a_word_the_asr_missed_is_placed_between_its_anchored_neighbours(self):
        turns, _ = anchor_turns([{'text': 'le chien euh dort'}], ASR)
        euh = turns[0]['words'][2]
        self.assertEqual('interpolated', euh['timing'])
        self.assertTrue(0.6 <= euh['start'] <= euh['end'] <= 0.6, euh)

    def test_turns_keep_their_keys_and_split_the_timeline(self):
        turns, report = anchor_turns([{'text': 'le chien dort', 'speaker_id': 'SPEAKER_01'},
                                      {'text': 'sur le tapis.', 'speaker_id': 'SPEAKER_02'}], ASR)
        self.assertEqual(['SPEAKER_01', 'SPEAKER_02'], [t['speaker_id'] for t in turns])
        self.assertEqual((1.0, 1.8), (turns[1]['start_time'], turns[1]['end_time']))
        self.assertEqual(1.0, report['exact_ratio'])

    def test_the_words_join_back_into_the_text_as_whisper_does(self):
        turns, _ = anchor_turns([{'text': "Le chien, dort !"}], ASR)
        self.assertEqual("Le chien, dort !", ''.join(w['word'] for w in turns[0]['words']).strip())
        self.assertEqual(turns[0]['words'][2]['end'], turns[0]['words'][3]['start'],
                         'punctuation alone sits at the end of the previous word')

    def test_an_apostrophe_word_spans_its_tokens(self):
        asr = _words(('aujourd', 0.0, 0.3), ('hui', 0.3, 0.5), ('il', 0.5, 0.6))
        turns, report = anchor_turns([{'text': "aujourd'hui il"}], asr)
        self.assertEqual((0.0, 0.5, 'exact'), tuple(turns[0]['words'][0][k]
                                                    for k in ('start', 'end', 'timing')))

    def test_times_never_go_backwards(self):
        turns, _ = anchor_turns([{'text': 'tapis le chien le dort sur'}], ASR)
        starts = [w['start'] for w in turns[0]['words']]
        self.assertEqual(starts, sorted(starts))

    def test_nothing_to_anchor_on_gives_nothing(self):
        self.assertIsNone(anchor_turns([{'text': 'le chat'}], []))
        self.assertIsNone(anchor_turns([{'text': 'le chat'}], [{'word': 'x', 'start': None}]))
