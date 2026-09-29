"""`manage.py asr_eval_corpus` — ce que la commande CALCULE (mixage, référence) ; le réseau et
la file ne sont pas rejoués ici (ils sont la chaîne existante : `designate`, `attach_reference`).

⚠ Identifiants en anglais ; commentaires et docstrings en français. Textes de test inventés.
"""
from django.test import SimpleTestCase

from wama.transcriber.management.commands.asr_eval_corpus import (
    merged_srt, mix_tracks, reference_name, srt_time,
)


class ReferenceTest(SimpleTestCase):

    def test_the_timecode_is_srt_shaped(self):
        self.assertEqual('01:02:03,450', srt_time(3723.45))
        self.assertEqual('00:00:00,000', srt_time(-1))

    def test_segments_of_all_tracks_are_merged_by_start_time(self):
        tracks = {
            '013': (None, [{'start': 4.0, 'end': 5.0, 'transcript': 'deuxième phrase'}]),
            '007': (None, [{'start': 1.0, 'end': 2.0, 'transcript': 'première  phrase'},
                           {'start': 6.0, 'end': 7.0, 'transcript': '   '}]),
        }
        srt = merged_srt(tracks)
        self.assertLess(srt.index('[Locuteur 007] première phrase'),
                        srt.index('[Locuteur 013] deuxième phrase'))
        self.assertEqual(2, srt.count('-->'), "un segment vide n'est pas une réplique")

    def test_the_transcriber_reader_keeps_the_words_and_drops_the_labels(self):
        """La référence produite est lue par le lecteur EXISTANT du transcriber, sans étiquettes
        dans le texte mesuré."""
        from wama.transcriber.utils.transcript_documents import parse_cues
        tracks = {'001': (None, [{'start': 0.5, 'end': 1.5, 'transcript': 'bonjour du_coup'}])}
        doc = parse_cues(merged_srt(tracks), 'srt')
        self.assertEqual('bonjour du_coup', doc.text)
        self.assertTrue(doc.is_timed)

    def test_the_reference_is_found_by_the_audio_name(self):
        self.assertEqual('summ-re_test_007a_ECRH_reference',
                         reference_name('summ-re', 'test', '007a_ECRH'))


class TaggedCorpusTest(SimpleTestCase):
    """FLEURS-CS : la langue de chaque phrase va jusqu'au segment de référence."""

    TAGGED = ('<en><start:0.00>everyone uses transport<end:11.64>'
              '<fr><start:11.64>la plupart des  îles<end:19.44>')

    def test_the_tagged_transcription_becomes_timed_language_spans(self):
        from wama.transcriber.management.commands.asr_eval_corpus import tagged_spans
        self.assertEqual([(0.0, 11.64, 'en', 'everyone uses transport'),
                          (11.64, 19.44, 'fr', 'la plupart des îles')], tagged_spans(self.TAGGED))

    def test_the_vtt_reference_keeps_each_language_out_of_the_measured_text(self):
        """Le lecteur EXISTANT du transcriber ôte `<lang xx>` du texte et le rend par segment."""
        from wama.transcriber.management.commands.asr_eval_corpus import language_vtt, tagged_spans
        from wama.transcriber.utils.transcript_documents import parse_cues
        doc = parse_cues(language_vtt(tagged_spans(self.TAGGED)), 'vtt')
        self.assertEqual('everyone uses transport la plupart des îles', doc.text)
        self.assertEqual(['en', 'fr'], [s['language'] for s in doc.segments])
        self.assertEqual(11.64, doc.segments[1]['start_time'])

    def test_the_most_spoken_language_comes_first(self):
        from wama.transcriber.management.commands.asr_eval_corpus import languages_by_time, tagged_spans
        self.assertEqual(['en', 'fr'], languages_by_time(tagged_spans(self.TAGGED)))

    def test_recordings_are_chosen_by_their_languages(self):
        from wama.transcriber.management.commands.asr_eval_corpus import Recording, select_by_languages
        pool = [Recording('a', languages=['en', 'fr']), Recording('b', languages=['de', 'fr']),
                Recording('c', languages=['en', 'es', 'fr']), Recording('d', languages=['de', 'en'])]
        ids = lambda rs: [r.recording_id for r in rs]
        self.assertEqual(['a'], ids(select_by_languages(pool, {'fr', 'en'}, exact=True)))
        self.assertEqual(['a', 'c'], ids(select_by_languages(pool, {'fr', 'en'}, exact=False)))
        self.assertEqual(['a', 'b'], ids(select_by_languages(pool, {'fr'}, False, count=2)))


class MixTest(SimpleTestCase):

    def test_tracks_are_padded_summed_and_peak_normalised(self):
        import numpy as np
        mix = mix_tracks({'a': (np.array([0.5, 0.5, 0.5], dtype=np.float32), []),
                          'b': (np.array([0.5], dtype=np.float32), [])})
        self.assertEqual(3, len(mix))
        self.assertAlmostEqual(0.9, float(np.abs(mix).max()), places=5)
        self.assertAlmostEqual(0.45, float(mix[1]), places=5)
