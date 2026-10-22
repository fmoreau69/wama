"""The common MIDI → ABC notation (`common/utils/midi_score.py`, 2026-10-16) and the robust tempo
of the MuScriptor backend (`robust_tempo`) — what turns a multi-instrument MIDI into the FULL score
the composer shows under the melody.

What each test holds:
  * chords, ties across a bar line, and accidentals written once per bar then cancelled (`=`) ;
  * drums on a percussion staff, each hit lasting until the next ;
  * a wide keyboard on two staves under one brace, the left hand unnamed ; labels in French ;
  * a MIDI without a metre is placed on the PLAYED beats of the audio, and a pickup before the
    first beat moves the whole score back by a whole bar ;
  * one missed beat and a section tracked on the off-beats do not change the tempo found ;
  * the transcription NAMES the instruments a first, quick pass heard (2026-10-22, #880).

No model, no GPU: the MIDI is built in memory.
"""
import io

import numpy as np
from django.test import SimpleTestCase

from wama.common.utils.midi_score import instrument_label, midi_to_abc


def _midi(instruments, metre=True, tempo=120.0, marker=None) -> bytes:
    """A MIDI of `(name, is_drum, [(start s, end s, pitch)])` ; `metre=False` writes NO time
    signature, as MuScriptor does when it finds no constant tempo ; `marker` adds a marker."""
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
    if metre and marker is None:
        return buffer.getvalue()
    buffer.seek(0)
    song = mido.MidiFile(file=buffer)
    for track in song.tracks:
        track[:] = [m for m in track if metre or m.type != 'time_signature']
    if marker is not None:
        song.tracks[0].insert(0, mido.MetaMessage('marker', text=marker, time=0))
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

    def test_the_bar_offset_the_engine_added_is_taken_back_before_placing(self):
        """MuScriptor delays every note so its bars land on downbeats, and says by how much in a
        marker. 2026-10-16 : read through `pretty_midi` (which keeps no markers), it was ignored
        and the full score of a song without a constant tempo came out shifted by it."""
        beats = [1.0 + 0.6 * i for i in range(12)]
        shifted = [(0.4 + 1.2, 1.0 + 1.2, 67), (1.0 + 1.2, 1.6 + 1.2, 69), (1.6 + 1.2, 2.2 + 1.2, 71)]
        abc = midi_to_abc(_midi([('voice', False, shifted)], metre=False,
                                marker='muscriptor:bar_offset=1.2000'), beat_times=beats)
        self.assertEqual('z12G4|A4B4z8|', _body(abc, 'I0'), 'the same score as without the delay')

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


class ReadMidiTest(SimpleTestCase):
    """`read_midi`, the MIDI reading shared by the notation and the YuE2 engine."""

    def _bytes(self, messages, ticks_per_beat=480) -> bytes:
        import mido
        song = mido.MidiFile(ticks_per_beat=ticks_per_beat, type=0)
        song.tracks.append(mido.MidiTrack(messages))
        out = io.BytesIO()
        song.save(file=out)
        return out.getvalue()

    def test_a_note_struck_again_as_the_previous_one_ends_is_kept(self):
        import mido
        from wama.common.utils.midi_score import read_midi
        song = read_midi(self._bytes([
            mido.Message('note_on', note=60, velocity=80, time=0),
            mido.Message('note_on', note=60, velocity=80, time=480),     # struck again…
            mido.Message('note_off', note=60, time=0),                   # …as the first one ends
            mido.Message('note_off', note=60, time=480)]))
        self.assertEqual([(0, 480, 60), (480, 960, 60)], song.parts[0].notes)

    def test_one_track_splits_by_channel_and_seconds_follow_the_tempo_map(self):
        import mido
        from wama.common.utils.midi_score import read_midi
        song = read_midi(self._bytes([
            mido.MetaMessage('set_tempo', tempo=500000, time=0),
            mido.Message('note_on', note=64, velocity=80, channel=0, time=0),
            mido.Message('note_on', note=36, velocity=80, channel=9, time=0),
            mido.Message('note_off', note=36, channel=9, time=240),
            mido.MetaMessage('set_tempo', tempo=1000000, time=240),
            mido.Message('note_off', note=64, channel=0, time=480)]))
        self.assertEqual([(False, [(0, 960, 64)]), (True, [(0, 240, 36)])],
                         [(p.is_drum, p.notes) for p in song.parts])
        self.assertEqual([(0, 500000), (480, 1000000)], song.tempi)
        self.assertAlmostEqual(0.5 + 1.0, song.seconds(960), msg='a beat at 120, then one at 60')
        self.assertEqual(2.0, song.quarters(960))


class MuScriptorIsInstalledByTheRouteTest(SimpleTestCase):
    """2026-10-16 : the Beat This! checkpoint was fetched by the BACKEND at first use, beside the
    `files` driver that does exactly that. The model's three files are now DECLARED, installed and
    removed by the route ; the backend only reads them."""

    def test_every_declared_file_passes_the_lock_of_the_files_driver(self):
        from wama.common.backends.muscriptor_backend import MUSCRIPTOR_FILES, model_folder
        from wama.model_manager.services.model_installer import declared_files_error
        spec = {'kind': 'files', 'files': MUSCRIPTOR_FILES, 'target_dir': str(model_folder())}
        self.assertIsNone(declared_files_error(spec))
        self.assertEqual({'huggingface', 'beat_this'},
                         {f['origin']['source'] for f in MUSCRIPTOR_FILES})

    def test_the_discovery_makes_a_row_the_route_installs_with_its_files(self):
        from wama.common.backends.muscriptor_backend import MODEL_KEY, MUSCRIPTOR_FILES
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = object.__new__(ModelRegistry)       # not the process's singleton
        registry._models, registry.discovery_errors = {}, []
        registry._discover_midi_extraction_models()
        self.assertEqual([], registry.discovery_errors)
        info = registry._models[MODEL_KEY]
        self.assertEqual(MUSCRIPTOR_FILES, info.extra_info['declared_files'])
        self.assertEqual(('audio-to-midi', 'muscriptor'),
                         (info.capabilities['task'], info.composition['runtime']['engine']))

    def test_a_missing_file_says_to_install_it_and_downloads_nothing(self):
        import tempfile
        from unittest import mock
        from django.conf import settings
        from wama.common.backends import muscriptor_backend
        paths = {**settings.MODEL_PATHS, 'music': {'muscriptor': tempfile.mkdtemp()}}
        with self.settings(MODEL_PATHS=paths), \
                mock.patch('wama.model_manager.services.model_installer.download_asset') as dl:
            with self.assertRaisesMessage(RuntimeError, 'pull_model huggingface:MuScriptor'):
                muscriptor_backend.installed_file(muscriptor_backend.BEAT_CHECKPOINT)
        dl.assert_not_called()


class InstrumentsAreNamedToTheModelTest(SimpleTestCase):
    """2026-10-22, #880 : left free, MuScriptor wrote 61 notes of the VOICE of a YuE2 render (4
    windows of 10 s out of 22) ; told which instruments sound, 436 (20 windows). A first, quick
    pass finds the instruments present ; the transcription names them."""

    @staticmethod
    def _note(name, start):
        from types import SimpleNamespace
        return SimpleNamespace(instrument=name, start_time=start, pitch=60, index=0)

    def test_an_instrument_heard_in_one_chunk_only_is_not_named(self):
        from types import SimpleNamespace
        from wama.common.backends.muscriptor_backend import present_instruments
        events = [self._note('voice', 1), self._note('voice', 12), self._note('drums', 0),
                  self._note('drums', 6), self._note('distorted_electric_guitar', 30),
                  self._note('distorted_electric_guitar', 31), self._note('program_42', 0),
                  self._note('program_42', 20), SimpleNamespace(end_time=2.0)]
        self.assertEqual(['drums', 'voice'],
                         present_instruments(events, known={'voice', 'drums',
                                                            'distorted_electric_guitar'}),
                         'two notes in the same 5 s chunk are one chunk ; an unknown name is dropped')

    def test_the_transcription_names_the_instruments_the_first_pass_found(self):
        from unittest import mock
        import numpy as np
        from wama.common.backends import muscriptor_backend as mb
        calls = []

        class Model:
            _device = 'cpu'

            def transcribe(self, audio, **options):
                calls.append(options)
                return iter([InstrumentsAreNamedToTheModelTest._note(name, t)
                             for name in ('voice', 'electric_bass') for t in (0, 6)]
                            + [InstrumentsAreNamedToTheModelTest._note('flutes', 3)])

            def events_to_midi_bytes(self, events, beat_grid=None):
                list(events)
                return b'MThd'

        backend = mb.MuScriptorBackend()
        backend._model = Model()
        with mock.patch('wama.common.utils.audio_decode.decode_audio_at',
                        return_value=(np.zeros(16000, dtype=np.float32), mb.SAMPLE_RATE)), \
                mock.patch.object(mb, 'installed_file', return_value='ckpt'), \
                mock.patch.object(mb, 'beat_grid', return_value=None):
            self.assertEqual(b'MThd', backend.extract_midi(model_id=mb.HF_ID, audio_path='song.wav'))
        detection, transcription = calls
        self.assertEqual({'prelude_forcing': False, 'batch_size': mb.DETECTION_BATCH}, detection,
                         'the first pass is the quick one')
        self.assertEqual({'instruments': ['electric_bass', 'voice']}, transcription,
                         'the transcription names what the first pass heard, nothing else')


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
