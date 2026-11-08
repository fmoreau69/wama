"""Stage B of forced alignment, LOADED (`common/services/acoustic_alignment.py`, 2026-11-03).

The catalogue aligner re-listens to the words whose time is not sure — the words a document
anchoring could only estimate (transcriber), and the words Whisper dated ACROSS a pause of the voice
(avatar 3D, card #1532: « faisant » dated 3.78-4.78 s, said from 4.5 s on).
"""
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, TestCase

SR = 16000


def _voice(pattern):
    """A wave of 100 ms frames: '#' a loud tone, '.' near silence."""
    t = np.arange(SR // 10) / SR
    loud = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    quiet = np.full(SR // 10, 1e-4, dtype=np.float32)
    return np.concatenate([loud if c == '#' else quiet for c in pattern])


def _turns(*words):
    return [{'text': ' '.join(w[0] for w in words),
             'words': [dict({'word': ' ' + w, 'start': s, 'end': e}, **({'timing': k} if k else {}))
                       for w, s, e, k in words]}]


class DoubtWordsOverSilenceTest(SimpleTestCase):

    def _doubt(self, pattern, turns):
        from wama.common.services import acoustic_alignment
        with mock.patch('wama.common.utils.audio_decode.decode_audio_at',
                        return_value=(_voice(pattern), SR)):
            return acoustic_alignment.doubt_words_over_silence(turns, 'voice.wav')

    def test_a_word_dated_across_a_pause_of_the_voice_becomes_estimated(self):
        #          0    .    1    .    2
        pattern = '####......####.####'
        turns = _turns(('sécurité', 0.0, 0.4, 'exact'), ('faisant', 0.4, 1.4, 'exact'),
                       ('face', 1.4, 1.9, 'exact'))
        self.assertEqual(1, self._doubt(pattern, turns))
        self.assertEqual(['exact', 'estimated', 'exact'], [w['timing'] for w in turns[0]['words']])

    def test_a_short_dip_inside_a_word_is_not_a_pause(self):
        """One quiet frame (a consonant closure) stays a sure word."""
        turns = _turns(('apprendre', 0.0, 0.9, None))
        self.assertEqual(0, self._doubt('####.####', turns))
        self.assertNotIn('timing', turns[0]['words'][0], 'a sure word is left untouched')

    def test_a_word_already_unsure_or_aligned_is_left_to_its_stage(self):
        turns = _turns(('voici', 0.0, 1.0, 'aligned'), ('une', 1.0, 2.0, 'interpolated'))
        self.assertEqual(0, self._doubt('##......##.......##', turns))
        self.assertEqual(['aligned', 'interpolated'], [w['timing'] for w in turns[0]['words']])

    def test_a_silent_audio_doubts_nothing(self):
        turns = _turns(('bonjour', 0.0, 1.0, 'exact'))
        self.assertEqual(0, self._doubt('..........', turns))


class RefineWithCatalogueAlignerTest(TestCase):

    def _aligner_in_catalogue(self):
        from wama.model_manager.models import AIModel
        return AIModel.objects.create(
            model_key='transcriber:wav2vec2-fr-aligner', name='aligneur', source='transcriber',
            platform_ref='huggingface:org/aligneur',
            capabilities={'task': 'alignment', 'languages': ['fr']},
            composition={'runtime': {'engine': 'transformers'}})

    def _refine(self, turns, language='fr', ctx=None, heard=None, call=None):
        from wama.common.backends.forced_alignment_base import AlignedWord
        from wama.common.services import acoustic_alignment
        heard = heard or {}
        call = call or (lambda: acoustic_alignment.refine(turns, 'voice.wav', language, ctx=ctx))
        events = []

        class FakeAligner:
            sample_rate, max_audio_seconds = SR, 60.0

            def load(self, repo):
                events.append(('load', repo))
                return True

            def unload(self):
                events.append(('unload',))

            def align(self, start, words):
                return [AlignedWord(heard[w][0] - start, heard[w][1] - start, 0.8)
                        if w in heard else None for w in words]

        with mock.patch('wama.common.backends.manager.backend_for_model', return_value=FakeAligner), \
                mock.patch('wama.common.utils.audio_decode.decode_window',
                           side_effect=lambda path, sr, start, duration: (start, sr)), \
                mock.patch('wama.model_manager.services.select_model',
                           side_effect=lambda **kw: __import__('wama.model_manager.models', fromlist=['x'])
                           .AIModel.objects.filter(model_key__in=kw['candidates']).first()):
            return call(), events

    def test_without_an_aligner_for_the_language_nothing_is_loaded(self):
        self._aligner_in_catalogue()
        outcome, events = self._refine(_turns(('hello', 0.0, 1.0, 'estimated')), language='en')
        self.assertIsNone(outcome)
        self.assertEqual([], events)

    def test_the_doubted_word_takes_the_time_the_aligner_hears_and_its_neighbours_keep_theirs(self):
        self._aligner_in_catalogue()
        installed = []
        ctx = SimpleNamespace(ensure_model=installed.append)
        turns = _turns(('sécurité', 3.08, 3.5, 'exact'), ('faisant', 3.78, 4.78, 'estimated'),
                       ('face', 4.78, 5.02, 'exact'))
        outcome, events = self._refine(turns, ctx=ctx, heard={
            'sécurité': (3.0, 3.4), 'faisant': (4.6, 4.88), 'face': (4.9, 5.1)})
        turns, report, model = outcome
        self.assertEqual(['transcriber:wav2vec2-fr-aligner'], installed,
                         'the route installs a missing aligner before it is loaded')
        self.assertEqual(('load', 'org/aligneur'), events[0])
        self.assertEqual(('unload',), events[-1])
        self.assertEqual(1, report['aligned'])
        self.assertEqual([(3.08, 3.5, 'exact'), (4.6, 4.88, 'aligned'), (4.78, 5.02, 'exact')],
                         [(w['start'], w['end'], w['timing']) for w in turns[0]['words']])
        self.assertEqual('transcriber:wav2vec2-fr-aligner', model.model_key)

    def test_timed_words_of_a_segment_without_words_are_spread_then_aligned(self):
        """`timed_words` (2026-11-08, the composer's lyrics — 3rd consumer of the composition) : a
        segment dated as a whole (Qwen3-ASR : 30 s slices, no word times) has its words spread in
        its interval, then the catalogue aligner re-listens to them ; a dated word is kept."""
        from wama.common.services import acoustic_alignment
        self._aligner_in_catalogue()
        segments = [SimpleNamespace(start=0.0, end=4.0, text='la mer revient', words=[]),
                    {'start_time': 4.0, 'end_time': 5.0, 'text': 'encore',
                     'words': [{'word': ' encore', 'start': 4.2, 'end': 4.7}]}]
        heard = {'la': (0.5, 0.7), 'mer': (0.8, 1.4), 'revient': (2.0, 2.6)}
        got, _events = self._refine(None, heard=heard, call=lambda: acoustic_alignment.timed_words(
            segments, 'song.wav', 'fr', ctx=None))
        self.assertEqual(['la', 'mer', 'revient', 'encore'], [w['word'] for w in got['words']])
        self.assertEqual([(0.5, 0.7), (0.8, 1.4), (2.0, 2.6), (4.2, 4.7)],
                         [(w['start'], w['end']) for w in got['words']])
        self.assertEqual(['aligned', 'aligned', 'aligned', 'exact'], [w['timing'] for w in got['words']])
        self.assertEqual('transcriber:wav2vec2-fr-aligner', got['aligner'])
        self.assertTrue(got['said'].startswith('Alignement acoustique (aligneur) : 3 mot(s) recalé(s)'),
                        'the sentence of every caller of the stage B (`alignment_said`)')

    def test_without_an_aligner_the_estimate_stays_and_says_why(self):
        from wama.common.services import acoustic_alignment
        segments = [SimpleNamespace(start=0.0, end=3.0, text='la mer revient', words=None)]
        got = acoustic_alignment.timed_words(segments, 'song.wav', 'xx')
        self.assertEqual('', got['aligner'])
        self.assertIn('aucun aligneur', got['reason'])
        self.assertIn('les heures restent estimées', got['said'])
        self.assertEqual(['interpolated'] * 3, [w['timing'] for w in got['words']])
        self.assertTrue(all(0.0 <= w['start'] <= w['end'] <= 3.0 for w in got['words']))
