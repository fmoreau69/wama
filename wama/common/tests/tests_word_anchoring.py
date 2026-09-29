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


class _FakeAligner:
    """An aligner that 'hears' each word at a fixed absolute time, and records its windows."""

    def __init__(self, heard, fail=False):
        self.heard, self.fail, self.windows = heard, fail, []

    def __call__(self, start, end, words):
        from wama.common.backends.forced_alignment_base import AlignedWord
        self.windows.append((start, end, list(words)))
        if self.fail:
            raise RuntimeError('boom')
        out = []
        for w in words:
            if w not in self.heard:
                out.append(None)
                continue
            s, e = self.heard[w]
            out.append(AlignedWord(start=s - start, end=e - start, score=0.8))
        return out


class RefineTurnsTest(SimpleTestCase):
    """Stage B: only the words no model heard are handed to the acoustic aligner."""

    def _anchored(self, text):
        return anchor_turns([{'text': text}], ASR)[0]

    def test_only_unsure_words_are_realigned_and_guards_bound_the_window(self):
        from wama.common.services.word_anchoring import refine_turns
        aligner = _FakeAligner({'chat': (0.25, 0.55), 'le': (9, 9), 'dort': (9, 9)})
        turns, report = refine_turns(self._anchored('le chat dort'), aligner, max_seconds=60)
        words = turns[0]['words']
        self.assertEqual((0.25, 0.55, 'aligned', 0.8),
                         tuple(words[1][k] for k in ('start', 'end', 'timing', 'probability')))
        self.assertEqual([(0.0, 0.2, 'exact'), (0.6, 1.0, 'exact')],
                         [(w['start'], w['end'], w['timing']) for w in (words[0], words[2])],
                         'a guard keeps its own time whatever the aligner says')
        self.assertEqual([(0.0, 1.0, ['le', 'chat', 'dort'])], aligner.windows)
        self.assertEqual({'unsure': 1, 'aligned': 1, 'windows': 1, 'failed': 0, 'too_long': 0},
                         report)

    def test_a_failing_window_keeps_the_stage_a_estimate(self):
        from wama.common.services.word_anchoring import refine_turns
        before = self._anchored('le chat dort')
        turns, report = refine_turns(before, _FakeAligner({}, fail=True), max_seconds=60)
        self.assertEqual(before[0]['words'], turns[0]['words'])
        self.assertEqual(1, report['failed'])

    def test_a_word_the_aligner_cannot_spell_sits_between_aligned_neighbours(self):
        from wama.common.services.word_anchoring import refine_turns
        anchored = self._anchored('le chat 12 dort')
        turns, _ = refine_turns(anchored, _FakeAligner({'chat': (0.2, 0.4)}), max_seconds=60)
        number = turns[0]['words'][2]
        self.assertEqual('interpolated', number['timing'])
        self.assertTrue(0.4 <= number['start'] <= number['end'] <= 0.6, number)

    def test_a_run_longer_than_the_aligner_is_cut_between_words(self):
        from wama.common.services.word_anchoring import refine_turns
        asr = _words(('a', 0.0, 0.5), ('b', 100.0, 100.5))
        text = 'a ' + ' '.join(f'w{i}' for i in range(40)) + ' b'
        anchored = anchor_turns([{'text': text}], asr)[0]
        aligner = _FakeAligner({})
        refine_turns(anchored, aligner, max_seconds=20)
        self.assertGreater(len(aligner.windows), 1)
        for start, end, words in aligner.windows:
            self.assertLessEqual(end - start, 20)
        seen = {w for _, _, words in aligner.windows for w in words}
        self.assertLessEqual({f'w{i}' for i in range(40)}, seen, 'no word is left out of a window')

    def test_nothing_unsure_calls_nothing(self):
        from wama.common.services.word_anchoring import refine_turns
        aligner = _FakeAligner({})
        _, report = refine_turns(self._anchored('le chien dort'), aligner, max_seconds=60)
        self.assertEqual([], aligner.windows)
        self.assertEqual(0, report['unsure'])


class AlignEmissionTest(SimpleTestCase):
    """The Viterbi core of the wav2vec2 aligner, on a hand-made emission (no network)."""

    def setUp(self):
        try:
            import torchaudio.functional  # noqa: F401
        except Exception:
            self.skipTest('torchaudio absent from this venv')

    def test_each_word_gets_the_frames_of_its_letters(self):
        import torch
        from wama.common.backends.wav2vec2_aligner_backend import align_emission
        # alphabet: 0 = blank, 1 = 'a', 2 = 'b' ; 10 frames of 0.1 s
        frames = [0, 1, 1, 0, 0, 0, 2, 2, 0, 0]
        emission = torch.full((1, len(frames), 3), -10.0)
        for t, k in enumerate(frames):
            emission[0, t, k] = 0.0
        out = align_emission(emission, [[1], [], [2]], blank=0, seconds_per_frame=0.1)
        self.assertEqual((0.1, 0.3), (out[0].start, out[0].end))
        self.assertIsNone(out[1], 'a word without letters is left to the caller')
        self.assertEqual((0.6, 0.8), (out[2].start, out[2].end))
        self.assertGreater(out[0].score, 0.9)

    def test_too_short_a_window_is_refused(self):
        import torch
        from wama.common.backends.wav2vec2_aligner_backend import align_emission
        with self.assertRaises(ValueError):
            align_emission(torch.zeros((1, 2, 3)), [[1, 1, 2]], blank=0, seconds_per_frame=0.02)


class BoundaryTest(SimpleTestCase):
    """One boundary per junction, two gestures (move, cut) — never a lost or halved word."""

    def _turns(self):
        return [{'speaker_id': 'SPEAKER_00', 'text': 'le chien dort', 'start_time': 0.0,
                 'end_time': 1.0, 'words': ASR[:3], 'confidence': -0.2},
                {'speaker_id': 'SPEAKER_01', 'text': 'sur le tapis', 'start_time': 1.0,
                 'end_time': 1.8, 'words': ASR[3:]}]

    def test_moving_a_boundary_carries_the_words_to_the_other_side(self):
        from wama.common.services.word_anchoring import move_boundary
        left, right = move_boundary(*self._turns(), at=0.25)
        self.assertEqual(('le', 'chien dort sur le tapis'), (left['text'], right['text']))
        self.assertEqual(left['end_time'], right['start_time'], 'one boundary per junction')
        self.assertEqual(0.2, left['end_time'], 'the boundary lands between two words')
        self.assertEqual(('SPEAKER_00', 'SPEAKER_01', -0.2),
                         (left['speaker_id'], right['speaker_id'], left['confidence']))

    def test_a_boundary_dropped_in_a_silence_stays_where_it_was_dropped(self):
        from wama.common.services.word_anchoring import move_boundary
        turns = self._turns()
        turns[1]['words'] = _words(('sur', 1.4, 1.5), ('le', 1.5, 1.6), ('tapis', 1.6, 1.8))
        left, right = move_boundary(*turns, at=1.2)
        self.assertEqual((1.2, 'le chien dort'), (left['end_time'], left['text']))

    def test_no_word_is_ever_lost_whatever_the_gesture(self):
        from wama.common.services.word_anchoring import move_boundary, split_turn
        before = ' '.join(t['text'] for t in self._turns())
        for at in (-5, 0.0, 0.33, 0.9, 1.25, 1.79, 9):
            pair = move_boundary(*self._turns(), at=at)
            self.assertEqual(before, ' '.join(t['text'] for t in pair), at)
            self.assertTrue(pair[0]['text'] and pair[1]['text'], 'each turn keeps a word')
        halves = split_turn(self._turns()[0], at=0.4)
        self.assertEqual(('le chien', 'dort'), (halves[0]['text'], halves[1]['text']))

    def test_an_edited_text_is_re_anchored_on_the_asr_before_the_cut(self):
        """The correction replaced « chien » by « chat » — its words no longer say its text."""
        from wama.common.services.word_anchoring import split_turn
        turn = dict(self._turns()[0], text='le chat dort')
        first, second = split_turn(turn, at=0.62, reference=ASR)
        self.assertEqual(('le chat', 'dort'), (first['text'], second['text']))
        self.assertEqual(0.6, second['start_time'])
        self.assertEqual('estimated', first['words'][1]['timing'])

    def test_without_any_timed_word_the_cut_still_falls_between_words(self):
        from wama.common.services.word_anchoring import split_turn
        turn = {'text': 'un deux trois quatre', 'start_time': 10.0, 'end_time': 14.0}
        first, second = split_turn(turn, at=11.5)
        self.assertEqual(('un deux', 'trois quatre'), (first['text'], second['text']))
        self.assertEqual('interpolated', second['words'][0]['timing'])

    def test_a_single_word_or_a_turn_without_time_cannot_be_cut(self):
        from wama.common.services.word_anchoring import split_turn
        self.assertIsNone(split_turn({'text': 'oui', 'start_time': 0, 'end_time': 1}, at=0.5))
        self.assertIsNone(split_turn({'text': 'oui non', 'start_time': None, 'end_time': None}, 0))

    def test_punctuation_alone_never_opens_a_turn(self):
        from wama.common.services.word_anchoring import split_turn
        turn = {'text': 'oui ! non', 'start_time': 0.0, 'end_time': 3.0}
        first, second = split_turn(turn, at=1.0)
        self.assertEqual(('oui !', 'non'), (first['text'], second['text']))


class ReplaceSpanTest(SimpleTestCase):
    """The write modes' gesture: a re-transcribed span replaces what was said there, or fills a gap."""

    def _turns(self):
        return [{'speaker_id': 'SPEAKER_00', 'text': 'le chien dort', 'start_time': 0.0,
                 'end_time': 1.0, 'words': ASR[:3]},
                {'speaker_id': 'SPEAKER_01', 'text': 'sur le tapis', 'start_time': 3.0,
                 'end_time': 3.8, 'words': _words(('sur', 3.0, 3.2), ('le', 3.2, 3.3),
                                                  ('tapis', 3.3, 3.8))}]

    def test_an_accepted_proposal_replaces_only_the_words_of_its_span(self):
        from wama.common.services.word_anchoring import replace_span
        out = replace_span(self._turns(), 0.2, 0.6, _words(('chat', 0.25, 0.55)))
        self.assertEqual(['le chat dort', 'sur le tapis'], [t['text'] for t in out])
        self.assertEqual('SPEAKER_00', out[0]['speaker_id'])

    def test_words_heard_in_a_gap_become_a_new_turn(self):
        from wama.common.services.word_anchoring import replace_span
        out = replace_span(self._turns(), 1.2, 2.8, _words(('oui', 1.5, 1.8), ('bien', 1.9, 2.2)),
                           new_turn={'speaker_id': ''})
        self.assertEqual(['le chien dort', 'oui bien', 'sur le tapis'], [t['text'] for t in out])
        self.assertEqual((1.2, 2.8), (out[1]['start_time'], out[1]['end_time']))

    def test_an_empty_section_is_filled_where_it_stands(self):
        from wama.common.services.word_anchoring import replace_span
        turns = self._turns()
        turns.insert(1, {'speaker_id': 'SPEAKER_00', 'text': '', 'start_time': 1.2,
                         'end_time': 2.8, 'words': []})
        out = replace_span(turns, 1.2, 2.8, _words(('oui', 1.5, 1.8)))
        self.assertEqual(['le chien dort', 'oui', 'sur le tapis'], [t['text'] for t in out])
        self.assertEqual('SPEAKER_00', out[1]['speaker_id'])

    def test_nothing_heard_changes_nothing_and_an_empty_section_stays(self):
        from wama.common.services.word_anchoring import replace_span
        turns = self._turns() + [{'text': '', 'start_time': 5, 'end_time': 6, 'words': []}]
        out = replace_span(turns, 5, 6, [])
        self.assertEqual(['le chien dort', 'sur le tapis', ''], [t['text'] for t in out])

    def test_a_whole_turn_can_be_rewritten(self):
        from wama.common.services.word_anchoring import replace_span
        out = replace_span(self._turns(), 2.9, 3.9, _words(('tapis', 3.4, 3.8)))
        self.assertEqual(['le chien dort', 'tapis'], [t['text'] for t in out])
