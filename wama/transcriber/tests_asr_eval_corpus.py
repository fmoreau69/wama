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


class MixTest(SimpleTestCase):

    def test_tracks_are_padded_summed_and_peak_normalised(self):
        import numpy as np
        mix = mix_tracks({'a': (np.array([0.5, 0.5, 0.5], dtype=np.float32), []),
                          'b': (np.array([0.5], dtype=np.float32), [])})
        self.assertEqual(3, len(mix))
        self.assertAlmostEqual(0.9, float(np.abs(mix).max()), places=5)
        self.assertAlmostEqual(0.45, float(mix[1]), places=5)
