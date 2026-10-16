"""The common MIDI → ABC notation (`common/utils/midi_score.py`, 2026-10-16) and the robust tempo
of the MuScriptor backend (`robust_tempo`) — what turns a multi-instrument MIDI into the FULL score
the composer shows under the melody.

What each test holds:
  * chords, ties across a bar line, and accidentals written once per bar then cancelled (`=`) ;
  * drums on a percussion staff, each hit lasting until the next ;
  * a wide keyboard on two staves under one brace, the left hand unnamed ; labels in French ;
  * a MIDI without a metre is placed on the PLAYED beats of the audio, and a pickup before the
    first beat moves the whole score back by a whole bar ;
  * one missed beat and a section tracked on the off-beats do not change the tempo found.

No model, no GPU: the MIDI is built in memory.
"""
import io

import numpy as np
from django.test import SimpleTestCase

from wama.common.utils.midi_score import instrument_label, midi_to_abc


def _midi(instruments, metre=True, tempo=120.0) -> bytes:
    """A MIDI of `(name, is_drum, [(start s, end s, pitch)])` ; `metre=False` writes NO time
    signature, as MuScriptor does when it finds no constant tempo."""
    import mido
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0))
    for name, drum, notes in instruments:
        inst = pretty_midi.Instrument(program=0, is_drum=drum, name=name)
        inst.notes = [pretty_midi.Note(100, p, s, e) for s, e, p in notes]
        pm.instruments.append(inst)
    buffer = io.BytesIO()
    pm.write(buffer)
    if metre:
        return buffer.getvalue()
    buffer.seek(0)
    song = mido.MidiFile(file=buffer)
    for track in song.tracks:
        track[:] = [m for m in track if m.type != 'time_signature']
    out = io.BytesIO()
    song.save(file=out)
    return out.getvalue()


def _body(abc: str, voice: str) -> str:
    """The music lines of one voice (after `K:`)."""
    lines = abc.split('K:C\n', 1)[1].splitlines()
    return ''.join(lines[i + 1] for i, line in enumerate(lines) if line == f'V:{voice}')


class MidiToAbcTest(SimpleTestCase):

    def test_chords_ties_and_accidentals_are_written_on_the_midi_metre(self):
        abc = midi_to_abc(_midi([('flutes', False, [
            (0, .5, 72), (.5, 1, 76), (.5, 1, 79),      # c, then the chord e+g
            (1.5, 2.5, 74),                             # d across the bar line
            (2.5, 2.75, 61), (2.75, 3, 60), (3, 3.5, 61)])]))
        self.assertIn('M:4/4\nL:1/16\nQ:1/4=120', abc, 'the metre and tempo of the MIDI')
        self.assertEqual('c4[eg]4z4d4-|d4^C2=C2^C4z4|', _body(abc, 'I0'),
                         'a sharp is written once per bar, cancelled by `=`, written again after')

    def test_drums_go_on_a_percussion_staff_and_a_hit_lasts_until_the_next(self):
        abc = midi_to_abc(_midi([('drums', True, [(0, .1, 36), (.5, .6, 38), (.5, .6, 42), (1, 1.1, 36)])]))
        self.assertIn('V:D0 clef=perc name="Batterie"', abc)
        self.assertIn('%%percmap F 36', abc)
        self.assertIn('%%percmap g 42 x', abc, 'cymbals are written with a cross head')
        self.assertEqual('F4[cg]4F8|', _body(abc, 'D0'), 'kick, snare + hi-hat, kick')

    def test_a_wide_keyboard_has_two_staves_under_one_brace(self):
        abc = midi_to_abc(_midi([('acoustic piano', False, [(0, 1, 76), (0, 1, 40)]),
                                 ('kazoo', False, [(0, 1, 67)])]))
        self.assertIn('%%score {P0R P0L} I1', abc)
        self.assertIn('V:P0R clef=treble name="Piano"', abc)
        self.assertIn('V:P0L clef=bass name=""', abc, 'the brace carries the name, once')
        self.assertEqual(('e8z8|', 'E,,8z8|'), (_body(abc, 'P0R'), _body(abc, 'P0L')))
        self.assertIn('name="Kazoo"', abc, 'an unknown instrument keeps its own name')

    def test_without_a_metre_the_notes_sit_on_the_played_beats(self):
        beats = [1.0 + 0.6 * i for i in range(12)]
        abc = midi_to_abc(_midi([('voice', False, [(0.4, 1.0, 67), (1.0, 1.6, 69), (1.6, 2.2, 71)])],
                                metre=False), beat_times=beats)
        self.assertIn('Q:1/4=100', abc, 'the tempo of the played beats, not a placeholder 120')
        self.assertEqual('z12G4|A4B4z8|', _body(abc, 'I0'),
                         'the pickup before the first beat moves the score back by a whole bar')

    def test_too_few_played_beats_keep_the_midi_tempo(self):
        abc = midi_to_abc(_midi([('voice', False, [(0, .5, 67)])], metre=False), beat_times=[0, .6, 1.2])
        self.assertIn('Q:1/4=120', abc)

    def test_a_midi_without_notes_is_refused(self):
        with self.assertRaises(ValueError):
            midi_to_abc(_midi([('voice', False, [])]))

    def test_the_labels_are_in_french(self):
        self.assertEqual('Basse électrique', instrument_label('electric bass'))
        self.assertEqual('Voix', instrument_label('Voice'))
        self.assertEqual('Guitare saturée', instrument_label('distorted_electric_guitar'))
        self.assertEqual('Kazoo', instrument_label('kazoo'))


class RobustTempoTest(SimpleTestCase):
    """`robust_tempo` renumbers the beats on their median interval, then keeps the dominant
    phase : measured on YuE2 renders, where the library's own fit refused a constant tempo."""

    def _tempo(self, beats):
        from wama.common.backends.muscriptor_backend import robust_tempo
        return robust_tempo(np.asarray(beats))

    def test_a_missed_beat_does_not_shift_the_tempo(self):
        beats = [0.5 * i for i in range(40) if i != 17]
        bpm, residual, share, _kept = self._tempo(beats)
        self.assertAlmostEqual(120.0, bpm, places=3)
        self.assertLess(residual, 1e-6)
        self.assertEqual(1.0, share)

    def test_a_section_tracked_on_the_off_beats_is_set_aside(self):
        on = [0.5 * i for i in range(30)]
        off = [15.24 + 0.5 * i for i in range(10)]          # ~half a beat late, the last quarter
        bpm, residual, share, kept = self._tempo(on + off)
        self.assertAlmostEqual(120.0, bpm, places=3)
        self.assertLess(residual, 1e-6)
        self.assertAlmostEqual(0.75, share, places=2)
        self.assertEqual(on, list(kept), 'the beats kept are the dominant phase')
