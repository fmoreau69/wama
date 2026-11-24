"""The marks of a transcription, read through the tracks the app states (`apps.py`, step 1 of
`ROUTE §10.7`) : turns, sentences and words under the common names — the storage untouched.
Proper to the app : the shape of what it stores. The reader itself is kept in
`wama/common/tests/tests_marks.py`."""
from django.test import SimpleTestCase

from wama.common.catalog import marks
from wama.transcriber.models import Transcript

WORDS = [{'word': ' bonjour', 'start': 0.1, 'end': 0.6, 'probability': 0.9},
         {'word': ' à', 'start': 0.6, 'end': 0.7, 'timing': 'interpolated'},
         {'word': ' tous', 'start': 0.7, 'end': 1.2}]
ENGINE = [{'speaker_id': 'SPEAKER_00', 'start_time': 0.0, 'end_time': 1.5, 'text': 'bonjour à tous',
           'words': WORDS},
          {'speaker_id': 'SPEAKER_00', 'start_time': 2.0, 'end_time': 3.0, 'text': 'merci'},
          {'speaker_id': 'SPEAKER_01', 'start_time': 3.0, 'end_time': 4.5, 'text': 'de rien',
           'words': [{'word': ' de', 'start': 3.1, 'end': 3.4}, {'word': ' rien', 'start': 3.4, 'end': 4.2}]}]


class TracksOfATranscriptionTest(SimpleTestCase):

    def test_turns_sentences_and_words_are_read_under_the_common_names(self):
        read = marks.read_tracks(Transcript(segments_json=ENGINE))
        self.assertEqual(['turns', 'sentences', 'words'], list(read))
        self.assertEqual([(0.0, 3.0, 'SPEAKER_00'), (3.0, 4.5, 'SPEAKER_01')],
                         [(m['start'], m['end'], m['speaker']) for m in read['turns']],
                         'a turn : the consecutive sentences of one speaker')
        self.assertEqual([(0.0, 1.5, 0), (2.0, 3.0, 0), (3.0, 4.5, 1)],
                         [(m['start'], m['end'], m['parent']) for m in read['sentences']])
        first = read['sentences'][0]
        self.assertEqual(('bonjour à tous', 'SPEAKER_00', 'transcription'),
                         (first['text'], first['speaker'], first['origin']))
        self.assertFalse({'start_time', 'end_time', 'speaker_id', 'words'} & set(first))
        self.assertEqual([(' bonjour', 0, 'transcription'), (' à', 0, 'interpolated'),
                          (' tous', 0, 'transcription'), (' de', 2, 'transcription'),
                          (' rien', 2, 'transcription')],
                         [(m['text'], m['parent'], m['origin']) for m in read['words']],
                         'a word names its sentence ; `timing` is where its time comes from')
        self.assertEqual(0.9, read['words'][0]['probability'])
        card = Transcript(segments_json=ENGINE)
        self.assertEqual([], marks.violations(card, 'sentences') + marks.violations(card, 'words'))

    def test_the_corrected_sentences_are_the_ones_read(self):
        """The rule of the correction page (`views._editor_segments`) : corrected when they are."""
        corrected = [{'speaker_id': 'SPEAKER_00', 'start_time': 0.0, 'end_time': 1.5,
                      'text': 'Bonjour à tous.', 'words': WORDS}]
        read = marks.read_tracks(Transcript(segments_json=ENGINE, corrected_segments_json=corrected))
        self.assertEqual(['Bonjour à tous.'], [m['text'] for m in read['sentences']])
        self.assertEqual(3, len(read['words']))

    def test_a_text_without_times_has_no_marks(self):
        untimed = [{'speaker_id': '', 'start_time': None, 'end_time': None, 'text': 'importé'}]
        read = marks.read_tracks(Transcript(segments_json=untimed))
        self.assertEqual({'turns': [], 'sentences': [], 'words': []}, read)
