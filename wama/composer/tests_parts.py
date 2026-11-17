"""The composer's optional process `parts` (2026-10-16): the RENDERED song → its full score, one
part per instrument (task `audio-to-midi`, MuScriptor), written in ABC by the common notation
(`common/utils/midi_score.py`) and read on the score page under the melody.

What each test holds:
  * the process only runs when the card asks for it (`extract_parts`) AND a model of the task is
    installed ; it is a BRANCH of the render, beside the output (2026-10-26), and reads the
    render's audio — a new output format does not stale it ;
  * its model is not the card's: chosen on the card (`parts_model`, 2026-10-19) or drawn by task
    under « auto », asked from the route, released at once, named on its execution line ;
  * the MIDI is written as a score output of the card, never handed to the render ;
  * a failed transcription fails the card's line and releases the model.

No model, no GPU: the engines are stand-ins (the ones of `tests_pipeline`, plus a transcriber).
"""
import io
import json
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from wama.common.models import JOB_FAILURE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.composer import tasks
from wama.composer.models import ComposerGeneration
from wama.composer.tests_pipeline import (COVER_MODEL, ENGINES, PLAIN_MODEL, SFX_MODEL, _PlainEngine,
                                          catalogue_rows)
from wama.composer.tests_task import _celery_task

TRANSCRIBER = 'huggingface:MuScriptor/muscriptor-large'
#: A second model of the task, CHOSEN on the card (`parts_model`) — the draw never returns it.
OTHER_TRANSCRIBER = 'huggingface:org/other-transcriber'
#: The model of the `separate` process (2026-11-12), drawn by its task.
SEPARATOR = 'demucs:htdemucs_6s'


def _two_parts_midi() -> bytes:
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
    pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0))
    for name, pitch in (('voice', 67), ('electric bass', 40)):
        inst = pretty_midi.Instrument(program=0, name=name)
        inst.notes = [pretty_midi.Note(100, pitch, 0.0, 1.0)]
        pm.instruments.append(inst)
    buffer = io.BytesIO()
    pm.write(buffer)
    return buffer.getvalue()


class _Transcriber:
    """Stand-in of a MIDI-extraction backend (`MidiExtractionBackend`)."""
    built, unloaded, calls = 0, 0, []
    error = None

    def __init__(self):
        type(self).built += 1

    def unload(self):
        _Transcriber.unloaded += 1

    def extract_midi(self, **kwargs):
        _Transcriber.calls.append(kwargs)
        if _Transcriber.error:
            raise _Transcriber.error
        return _two_parts_midi()


class _Separator:
    """Stand-in of a source-separation backend (`SourceSeparationBackend`): two stems, written."""
    built, unloaded, calls = 0, 0, []

    def __init__(self):
        type(self).built += 1

    def unload(self):
        _Separator.unloaded += 1

    def separate_sources(self, model_id, audio_path, output_dir, progress_callback=None, stems=None):
        _Separator.calls.append({'model_id': model_id, 'audio_path': audio_path, 'stems': stems})
        out = {}
        for stem in ('vocals', 'drums'):
            path = Path(output_dir) / f'{stem}.wav'
            path.write_bytes(b'RIFF' + stem.encode() + b'\0' * 32)
            out[stem] = str(path)
        return out


class _InputProcessCase(TestCase):
    """What the processes that read the INPUT audio with a model of THEIR OWN task share (the full
    score, the separated stems) : the cover, the draw by task, the run with stand-in engines."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_parts', password='x')
        _PlainEngine.renders = []
        _Transcriber.built, _Transcriber.unloaded, _Transcriber.calls, _Transcriber.error = 0, 0, [], None
        _Separator.built, _Separator.unloaded, _Separator.calls = 0, 0, []
        self.installed = True
        self.draws, self.asked = [], []
        self.pulses = []                       # the audios whose played beats were asked for
        catalogue_rows()

    def _draw(self, source=None, requested=None, fallback=None, task=None, **domain):
        """The common selector's draw (`select_model_id`), stood in BELOW the composer's choice
        (`model_choice.parts_extractor`), which these tests hold : the installed model of the task."""
        self.draws.append({'task': task, **domain})
        drawn = {'audio-to-midi': TRANSCRIBER, 'audio-source-separation': SEPARATOR}.get(task)
        return drawn if (self.installed and drawn) else fallback

    def _cover(self) -> str:
        """An audio of the song to cover (`melody_reference`) : the INPUT the full score reads."""
        rel = 'users/1/temp/cover.wav'
        (Path(self.tmp) / rel).parent.mkdir(parents=True, exist_ok=True)
        (Path(self.tmp) / rel).write_bytes(b'RIFF' + b'\0' * 64)
        return rel

    def _run(self, gen=None, process=None, **fields):
        if gen is None:
            # A model that TAKES a cover (`ProcessSpec.needs` of `parts`, 2026-11-05) : the full
            # score of a cover has no object under a model that takes none.
            gen = ComposerGeneration.objects.create(user=self.user, prompt='pop song',
                                                    model=COVER_MODEL, status='RUNNING', **fields)
        engines = {**ENGINES, TRANSCRIBER: _Transcriber, OTHER_TRANSCRIBER: _Transcriber,
                   SEPARATOR: _Separator}
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.backends.manager.backend_for_key',
                           side_effect=lambda key: engines.get(key)), \
                mock.patch('wama.model_manager.services.select_model_id', side_effect=self._draw), \
                mock.patch('wama.common.utils.model_readiness.ensure_installed',
                           side_effect=lambda key, **kw: self.asked.append(key) or True), \
                mock.patch('wama.composer.utils.model_choice.parts_extraction_available',
                           side_effect=lambda: self.installed), \
                mock.patch('wama.composer.utils.model_choice.stem_separation_available',
                           side_effect=lambda: self.installed), \
                mock.patch('wama.common.utils.audio_rhythm.beat_grid',
                           side_effect=lambda path: self.pulses.append(path)), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: text), \
                mock.patch('wama.common.utils.model_readiness.warn_if_weights_missing'), \
                mock.patch('wama.composer.utils.model_config.clamp_duration',
                           side_effect=lambda value, model_id=None: value), \
                mock.patch('wama.model_manager.services.eta_estimator.record_run'):
            tasks.compose_task.run.__func__(_celery_task(), gen.pk, process)
        return ComposerGeneration.objects.get(pk=gen.pk)

    def _states(self, gen):
        return {row.node_id: row.status for row in process_runs.lines(gen)}


class FullScoreTest(_InputProcessCase):

    def test_the_full_score_reads_the_input_audio_when_the_card_asks(self):
        """2026-10-26, Fabien : « la partition devrait refléter cet audio d'entrée » — the full
        score describes the SAME audio as the reduced one : the cover, not the song produced."""
        from django.conf import settings
        cover = self._cover()
        gen = self._run(extract_parts=True, melody_reference=cover)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual(JOB_SUCCESS, self._states(gen)['parts'])
        self.assertEqual(str(Path(settings.MEDIA_ROOT) / cover),
                         str(Path(_Transcriber.calls[0]['audio_path'])), 'the cover is read')
        self.assertIn(f'/score{gen.pk}_', gen.parts_score.name, 'named by its nature : a score')
        written = (Path(self.tmp) / gen.parts_score.name).read_text(encoding='utf-8')
        self.assertIn('name="Voix"', written)
        self.assertIn('name="Basse électrique"', written)
        self.assertIn('\nT:cover\n', written, 'titled by its song, not by the number of the card')
        from wama.composer.function_specs import PIPELINE
        self.assertEqual([], list(PIPELINE.spec('parts').depends_on), 'an INPUT reading')

    def test_a_split_track_takes_the_pulse_of_its_mix(self):
        """2026-11-15, measured on « Plus d'eau » : a voice alone has no drums, its played beats
        drifted from 86 to 96 per minute where the mix holds 90.1 within 0.09 s. A track keeps the
        time of its mix to the sample : its full score is written on the beats of the mix."""
        from django.conf import settings
        mix = self._cover()
        source = ComposerGeneration.objects.create(user=self.user, prompt='pop song',
                                                   model=COVER_MODEL, melody_reference=mix)
        voice = 'users/1/temp/voice.wav'
        (Path(self.tmp) / voice).write_bytes(b'RIFF' + b'\0' * 64)
        track = ComposerGeneration.objects.create(
            user=self.user, prompt='pop song', model=COVER_MODEL, status='RUNNING',
            extract_parts=True, melody_reference=voice, derived_from=source, derived_role='vocals')
        gen = self._run(track)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual(str(Path(settings.MEDIA_ROOT) / voice),
                         str(Path(_Transcriber.calls[0]['audio_path'])), 'the notes : of the track')
        self.assertEqual([str(Path(settings.MEDIA_ROOT) / mix)], [str(Path(p)) for p in self.pulses],
                         'the beats : of the mix')
        self._run(extract_parts=True, melody_reference=mix)
        self.assertEqual(str(Path(settings.MEDIA_ROOT) / mix), str(Path(self.pulses[-1])),
                         'a card of its own reads its own pulse')

    def test_the_climb_to_the_origin_is_bounded(self):
        """2026-11-16 : a test double that makes up a new source at each access (`MagicMock`) sent
        `origin_of` climbing until the kernel killed the suite at 42 GB, without a verdict."""
        from wama.common.utils.derived_cards import ORIGIN_DEPTH, origin_of
        endless = mock.MagicMock()
        self.assertIsNotNone(origin_of(endless))
        depth, card = 0, endless
        while card is not origin_of(endless) and depth <= ORIGIN_DEPTH:
            card, depth = card.derived_from, depth + 1
        self.assertEqual(ORIGIN_DEPTH, depth, 'it stops at the bound, not before nor after')

    def test_without_a_cover_or_with_an_imported_score_there_is_nothing_to_read(self):
        gen = self._run(extract_parts=True)
        self.assertNotIn('parts', self._states(gen), 'no input audio')
        self.assertEqual([], _Transcriber.calls)
        from wama.composer.function_specs import PIPELINE
        imported = ComposerGeneration(melody_reference=self._cover(), reference_score='x.abc',
                                      extract_parts=True)
        self.assertFalse(PIPELINE.spec('parts').applies(imported, PLAIN_MODEL),
                         'an IMPORTED score is the input itself')

    def test_its_model_is_drawn_by_task_released_and_named_on_its_line(self):
        gen = self._run(extract_parts=True, melody_reference=self._cover())
        self.assertEqual((1, 1), (_Transcriber.built, _Transcriber.unloaded))
        line = process_runs.line(gen, 'parts')
        self.assertEqual((gen.parts_score.name, 'composer.parts', TRANSCRIBER),
                         (line.output_ref, line.process_key, line.model_key))

    def test_the_model_chosen_on_the_card_writes_the_full_score(self):
        """2026-10-19 : several models can write this process ; the card names one
        (`parts_model`). It is not drawn, it is asked from the ROUTE (absent, installed while the
        task waits), loaded and named on the line."""
        gen = self._run(extract_parts=True, parts_model=OTHER_TRANSCRIBER,
                        melody_reference=self._cover())
        self.assertEqual(JOB_SUCCESS, self._states(gen)['parts'], gen.error_message)
        self.assertEqual(OTHER_TRANSCRIBER, process_runs.line(gen, 'parts').model_key)
        self.assertEqual('org/other-transcriber', _Transcriber.calls[0]['model_id'])
        self.assertIn(OTHER_TRANSCRIBER, self.asked)
        self.assertEqual([], [d for d in self.draws if d['task'] == 'audio-to-midi'])

    def test_under_auto_the_draw_is_made_for_the_card(self):
        """« auto » : the common selector draws among the task's models FOR this card — its
        account and its quality cursor, the ones its select's forecast reads."""
        gen = self._run(extract_parts=True, quality_intent=10, melody_reference=self._cover())
        self.assertEqual(TRANSCRIBER, process_runs.line(gen, 'parts').model_key)
        (draw,) = [d for d in self.draws if d['task'] == 'audio-to-midi']
        self.assertEqual((10, self.user.pk), (draw.get('quality_intent'), draw['user'].pk))
        self.assertIn(TRANSCRIBER, self.asked)

    def test_without_the_toggle_nothing_is_transcribed(self):
        gen = self._run(melody_reference=self._cover())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertNotIn('parts', self._states(gen))
        self.assertNotIn('rendered_parts', self._states(gen))
        self.assertEqual([], _Transcriber.calls)

    def test_without_a_model_of_the_task_the_process_does_not_take_place(self):
        self.installed = False
        gen = self._run(extract_parts=True, extract_rendered_parts=True,
                        melody_reference=self._cover())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertNotIn('parts', self._states(gen))
        self.assertNotIn('rendered_parts', self._states(gen))
        self.assertEqual([], _Transcriber.calls)

    def test_turned_on_after_the_song_only_the_full_score_is_played(self):
        """The gesture of #849 (2026-10-19): a song rendered without the toggle, the toggle turned
        on, the card relaunched — the full score is written, the song is not rendered again."""
        gen = self._run(melody_reference=self._cover())
        self.assertNotIn('parts', self._states(gen))
        ComposerGeneration.objects.filter(pk=gen.pk).update(extract_parts=True, status='RUNNING')
        gen = self._run(ComposerGeneration.objects.get(pk=gen.pk))
        self.assertEqual(JOB_SUCCESS, self._states(gen)['parts'], gen.error_message)
        self.assertTrue(gen.parts_score)
        self.assertEqual(1, len(_PlainEngine.renders), 'the song is not rendered again')

    def test_the_score_of_the_render_reads_the_song_produced(self):
        """2026-10-26, Fabien : « on propose les deux, l'entrée et la sortie » — the score of the
        RENDER, a branch of it, written beside the input's full score, never in its place."""
        from wama.common.services.output_process import output_sources
        gen = self._run(extract_parts=True, extract_rendered_parts=True,
                        melody_reference=self._cover())
        self.assertEqual((JOB_SUCCESS, JOB_SUCCESS),
                         (self._states(gen)['parts'], self._states(gen)['rendered_parts']),
                         gen.error_message)
        read = {Path(call['audio_path']).name for call in _Transcriber.calls}
        self.assertIn(Path(output_sources(gen, 'audio_output')[0]).name, read,
                      "the render's audio, whatever the output did")
        self.assertIn('cover.wav', read, 'and the cover, for the input')
        self.assertIn(f'/render_score{gen.pk}_', gen.rendered_parts_score.name)
        self.assertNotEqual(gen.parts_score.name, gen.rendered_parts_score.name)

    def test_a_new_output_format_stales_the_output_never_the_score_of_the_render(self):
        """2026-10-26, Fabien : « je ne vois pas la logique d'avoir la partition complète après la
        sortie ». A BRANCH of the render : the output may be redone, its score stays."""
        from wama.composer.function_specs import PIPELINE
        gen = self._run(extract_rendered_parts=True)
        self.assertEqual(JOB_SUCCESS, self._states(gen)['rendered_parts'], gen.error_message)
        self.assertEqual(['render'], list(PIPELINE.spec('rendered_parts').depends_on))
        current = gen.output_format
        other = next(v for v in ('mp3', 'flac', 'wav', 'ogg') if v != current)
        ComposerGeneration.objects.filter(pk=gen.pk).update(output_format=other)
        gen = ComposerGeneration.objects.get(pk=gen.pk)
        stale = PIPELINE.refresh(gen)
        self.assertIn('output', stale, 'the output follows its format')
        self.assertNotIn('rendered_parts', stale, 'the score of the render does not depend on it')

    def test_a_sound_effect_has_neither_score_even_asked(self):
        """2026-11-05, Fabien : under the ambiance model, the music settings showed — and
        « Partition de sortie » had NO condition : a sound effect would have been transcribed into
        instrument parts. What a process requires from the model is a DECLARATION (`needs`), judged
        on the catalogue line : AudioGen makes no music and takes no cover."""
        gen = ComposerGeneration.objects.create(user=self.user, prompt='rain on a roof', model=SFX_MODEL,
                                                status='RUNNING', extract_parts=True,
                                                extract_rendered_parts=True, melody_reference=self._cover())
        gen = self._run(gen)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual((False, False), ('parts' in self._states(gen), 'rendered_parts' in self._states(gen)))
        self.assertEqual([], _Transcriber.calls)

    def test_a_failed_transcription_fails_its_line_and_releases_the_model(self):
        _Transcriber.error = RuntimeError('no beat decoded')
        gen = self._run(extract_parts=True, melody_reference=self._cover())
        self.assertEqual(JOB_FAILURE, self._states(gen)['parts'])
        self.assertEqual(JOB_SUCCESS, self._states(gen)['output'], 'the song itself is kept')
        self.assertEqual(1, _Transcriber.unloaded)
        self.assertFalse(gen.parts_score)


class StemSeparationTest(_InputProcessCase):
    """The optional process `separate` (2026-11-12, Fabien : « découper l'audio en stems, que ça
    devienne un lot contenant les stems séparés ») : the INPUT audio → one stem per source, each
    stem a card of the source's lot (`common/utils/derived_cards.py`) — the card BECOMES the lot,
    the mix staying first."""

    def _stems(self, gen):
        return {c.derived_role: c for c in ComposerGeneration.objects.filter(derived_from=gen)}

    def _separator_reads_a_list(self, reads: bool):
        from wama.model_manager.models import AIModel
        AIModel.objects.update_or_create(model_key=SEPARATOR, defaults={
            'name': SEPARATOR, 'source': 'demucs',
            'capabilities': {'task': 'audio-source-separation', 'stems_by_query': reads}})

    def test_a_query_separator_receives_the_stems_typed_in_french(self):
        """2026-11-13, SAM Audio : un modèle PAR REQUÊTE (`stems_by_query`) reçoit les pistes que la
        card nomme — les libellés français du vocabulaire commun deviennent ses clés, un nom inconnu
        passe tel quel."""
        self._separator_reads_a_list(True)
        gen = self._run(separate_stems=True, melody_reference=self._cover(),
                        separation_stems='Voix, Cordes ; theremin')
        self.assertEqual(JOB_SUCCESS, self._states(gen)['separate'], gen.error_message)
        self.assertEqual(['vocals', 'string ensemble', 'theremin'], _Separator.calls[0]['stems'])

    def test_a_fixed_stem_separator_ignores_the_list(self):
        """Contre-épreuve : un modèle à pistes fixes (Demucs) rend les siennes — la liste saisie ne
        lui est pas passée."""
        self._separator_reads_a_list(False)
        self._run(separate_stems=True, melody_reference=self._cover(), separation_stems='Voix')
        self.assertIsNone(_Separator.calls[0]['stems'])

    def test_the_input_becomes_a_lot_of_stem_cards(self):
        from django.conf import settings
        from wama.common.utils.batch_common import batch_of
        cover = self._cover()
        gen = self._run(separate_stems=True, extract_parts=True, melody_reference=cover)
        self.assertEqual(JOB_SUCCESS, self._states(gen)['separate'], gen.error_message)
        self.assertEqual(str(Path(settings.MEDIA_ROOT) / cover), _Separator.calls[0]['audio_path'])
        self.assertEqual((1, 1), (_Separator.built, _Separator.unloaded), 'released at once')
        stems = self._stems(gen)
        self.assertEqual({'vocals', 'drums'}, set(stems))
        lot = batch_of(gen)
        self.assertEqual(3, lot.items.count(), 'the mix and its two stems')
        self.assertEqual(3, lot.total)
        rows = {link.generation_id: link.row_index for link in lot.items.all()}
        self.assertEqual(0, rows[gen.pk], 'the mix stays first')
        names = {link.generation_id: link.output_filename for link in lot.items.all()}
        self.assertEqual(len(names), len(set(names.values())), 'each line named after its own input')
        for role, card in stems.items():
            with self.subTest(role=role):
                self.assertEqual(lot.pk, batch_of(card).pk)
                self.assertTrue((Path(self.tmp) / card.melody_reference.name).is_file())
                self.assertIn('/composer/input/', card.melody_reference.name, 'an INPUT of its card')
                self.assertIn(f'_{role}_', card.melody_reference.name)
                self.assertIn(f'_{role}_', names[card.pk], 'its line is named after its stem')
                self.assertEqual(('PENDING', False, True, ''),
                                 (card.status, card.separate_stems, card.extract_parts, card.source_url),
                                 "its own settings from the source's, not launched, not split again")
                self.assertFalse(card.parts_score, "never the source's results")
        index = json.loads((Path(self.tmp) / gen.stems_index.name).read_text(encoding='utf-8'))
        self.assertEqual((SEPARATOR, {stems['vocals'].pk, stems['drums'].pk}),
                         (index['model'], {s['card'] for s in index['stems']}))
        self.assertEqual(SEPARATOR, process_runs.line(gen, 'separate').model_key)

    def _real_audio(self, gen):
        """The cover and its two stems as REAL signals (the stub separator writes stand-ins) : the
        cover is voice + drums, stereo ; each stem is its part alone."""
        import numpy as np
        import soundfile as sf
        rate = 22050
        t = np.arange(rate) / rate
        voice = 0.3 * np.sin(2 * np.pi * 440 * t)
        drums = 0.3 * np.sign(np.sin(2 * np.pi * 3 * t))
        sf.write(str(Path(self.tmp) / gen.melody_reference.name), np.stack([voice + drums] * 2, axis=1), rate,
                 format='WAV')
        index = json.loads((Path(self.tmp) / gen.stems_index.name).read_text(encoding='utf-8'))
        for s in index['stems']:
            sf.write(str(Path(self.tmp) / s['path']), {'vocals': voice, 'drums': drums}[s['stem']], rate,
                     format='WAV')
        return voice, rate

    def test_a_remix_without_the_drums_is_the_original_minus_the_drums(self):
        """2026-11-16, Fabien : « refusionner en retirant seulement une piste, la batterie » — and
        without degrading what is kept : the ORIGINAL minus the removed stem
        (`common/utils/stem_mix.py`), here exactly the voice. The result is the card's output and
        one more card of the lot."""
        import numpy as np
        import soundfile as sf
        from wama.common.utils.stem_mix import mix
        gen = self._run(separate_stems=True, melody_reference=self._cover())
        voice, rate = self._real_audio(gen)
        ComposerGeneration.objects.filter(pk=gen.pk).update(status='RUNNING', remix_stems=True,
                                                            remix_without='Batterie')
        gen = self._run(ComposerGeneration.objects.get(pk=gen.pk), process='remix')
        self.assertEqual(JOB_SUCCESS, self._states(gen)['remix'], gen.error_message)
        out, out_rate = sf.read(str(Path(self.tmp) / gen.remix_audio.name), always_2d=True)
        self.assertEqual((44100, 2), (out_rate, out.shape[1]), 'stereo, at the rate of the mix')
        heard = out[:, 0][::2]
        n = min(len(heard), len(voice))
        self.assertLess(float(np.abs(heard[200:n - 200] - voice[200:n - 200]).max()), 0.02,
                        'the voice alone (away from the edges the resampling rings on)')
        remix = self._stems(gen)['remix']
        self.assertIn('/composer/input/', remix.melody_reference.name, 'an INPUT of its own card')
        self.assertNotEqual(remix.melody_reference.name, gen.remix_audio.name, 'its own copy')
        self.assertEqual({'vocals', 'drums', 'remix'}, set(self._stems(gen)), 'the stems are kept')
        # Every gain at 1 : the original itself, nothing re-synthesised.
        stems = {'vocals': str(Path(self.tmp) / remix.melody_reference.name)}
        same, _ = mix(str(Path(self.tmp) / gen.melody_reference.name), stems, {'vocals': 1.0}, rate)
        original, _ = sf.read(str(Path(self.tmp) / gen.melody_reference.name), always_2d=True)
        self.assertLess(float(np.abs(same.T - original).max()), 1e-6)

    def test_chosen_stems_are_remixed_from_a_right_click_on_them(self):
        """2026-11-16, Fabien : « sélection multiple des pistes à refusionner et le clic droit ». The
        common route (`api_process_on_selection`) reads what the step DECLARES it takes from a
        selection (`ProcessSpec.from_selection`) : the chosen stems stay, the others go
        (`remix_without`, written by the ⚙'s writer), then the ▶ of the step on the ORIGIN card.
        Refused, and said : cards from two songs, a card that is no stem, every stem chosen, and
        a step that does not start from a selection."""
        from django.urls import reverse
        from wama.common.utils import process_views
        gen = self._run(separate_stems=True, melody_reference=self._cover())
        # Levels of an earlier live mix : the chosen stems stay AS THEY ARE, they no longer apply.
        ComposerGeneration.objects.filter(pk=gen.pk).update(remix_levels={'vocals': '0.5'})
        stems = self._stems(gen)
        self.client.force_login(self.user)
        url = lambda process: reverse('common:api_process_on_selection', args=['composer', process])
        started = []
        with mock.patch.object(process_views, 'start_one_process',
                               side_effect=lambda model, pk, process, **kw: started.append((pk, process))
                               or (ComposerGeneration.objects.get(pk=pk), mock.Mock(id='t1'), None)):
            res = self.client.post(url('remix'), {'ids': [stems['vocals'].pk]})
            self.assertEqual(200, res.status_code, res.content)
            self.assertEqual([(gen.pk, 'remix')], started, 'the step of the ORIGIN card')
            gen.refresh_from_db()
            self.assertEqual((True, 'Batterie', None),
                             (gen.remix_stems, gen.remix_without, gen.remix_levels))
            refused = {
                'all stems': self.client.post(url('remix'), {'ids': [c.pk for c in stems.values()]}),
                'not derived': self.client.post(url('remix'), {'ids': [gen.pk]}),
                'not from a selection': self.client.post(url('separate'), {'ids': [stems['drums'].pk]}),
            }
            self.assertEqual(1, len(started), 'nothing started when refused')
        for case, res in refused.items():
            with self.subTest(case=case):
                self.assertEqual(400, res.status_code)
                self.assertTrue(res.json()['error'])
        self.assertIn("morceau d'origine", refused['all stems'].json()['error'])
        with self.assertRaisesRegex(ValueError, 'Pas une piste'):
            tasks.remix_from_selection(gen, ['vocals', 'remix'])
        # The right click offers it : the queue declares the step, with its route.
        from wama.common.templatetags.wama_actions import _selection_processes
        offered = json.loads(_selection_processes('composer'))
        self.assertEqual([('remix', url('remix'))], [(p['key'], p['url']) for p in offered])

    def test_a_stem_the_card_does_not_have_is_said_never_silently_ignored(self):
        from wama.composer.tasks import remix_gains
        stems = {'vocals': 'v.wav', 'drums': 'd.wav'}
        self.assertEqual({'vocals': 1.0, 'drums': 0.0}, remix_gains(stems, 'batterie'))
        self.assertEqual({'vocals': 1.0, 'drums': 1.0}, remix_gains(stems, ''), 'nothing removed')
        with self.assertRaisesRegex(RuntimeError, 'Piano'):
            remix_gains(stems, 'Piano')
        # The LEVELS of the live mix (2026-11-17) : a gain per stem, written as text ; a removed
        # stem stays removed, a stem the separation no longer gives is nothing to set.
        self.assertEqual({'vocals': 0.5, 'drums': 1.25},
                         remix_gains(stems, '', {'vocals': '0,5', 'drums': '1.25', 'piano': '2'}))
        self.assertEqual({'vocals': 1.5, 'drums': 0.0}, remix_gains(stems, 'Batterie',
                                                                    {'vocals': '1.5', 'drums': '0.7'}))
        for unreadable in ('beaucoup', '9', '-1'):
            with self.subTest(level=unreadable), self.assertRaisesRegex(RuntimeError, 'Voix'):
                remix_gains(stems, '', {'vocals': unreadable})

    def test_the_page_mixes_what_the_remix_renders(self):
        """2026-11-17, Fabien : « le mixage temps réel va dans la page d'édition, la card porte les
        process ». The page reads the original and its stems with the gain the remix would give
        them (`stem_tracks`, the context of the composer surface) and writes the levels the remix
        reads (`remix_levels`, `remix_without`) : what is rendered is what was heard — here the
        voice plus HALF the drums. A card that only has its stems opens the page."""
        import numpy as np
        import soundfile as sf
        from wama.common.surfaces import surface
        gen = self._run(separate_stems=True, melody_reference=self._cover())
        voice, rate = self._real_audio(gen)
        ComposerGeneration.objects.filter(pk=gen.pk).update(status='RUNNING', remix_stems=True,
                                                            remix_levels={'drums': '0.5'})
        gen = ComposerGeneration.objects.get(pk=gen.pk)
        page = surface('composer', 'score')
        self.assertEqual((True, ''), page.can_open(gen), 'its stems open the page, no score needed')
        tracks = page.context_of(gen)['stems']
        self.assertEqual({'vocals': 1.0, 'drums': 0.5}, {t['key']: t['gain'] for t in tracks['tracks']})
        self.assertTrue(tracks['original'].endswith(gen.melody_reference.name.rsplit('/', 1)[-1]))
        self.assertEqual({'remix_levels', 'remix_without'}, set(page.page_settings()))
        gen = self._run(gen, process='remix')
        self.assertEqual(JOB_SUCCESS, self._states(gen)['remix'], gen.error_message)
        out, _rate = sf.read(str(Path(self.tmp) / gen.remix_audio.name), always_2d=True)
        drums = 0.3 * np.sign(np.sin(2 * np.pi * 3 * np.arange(rate) / rate))
        heard, wanted = out[:, 0][::2], voice + 0.5 * drums
        n = min(len(heard), len(wanted))
        # Away from the edges, and from the steps of the square wave the resampling rings on.
        steady = np.abs(np.diff(np.concatenate([[0], drums]))) == 0
        steady[:200] = steady[n - 200:] = False
        self.assertLess(float(np.abs(heard[:n] - wanted[:n])[steady[:n]].max()), 0.02)
        remix = self._stems(gen)['remix']
        self.assertEqual((None, '', False), (remix.remix_levels, remix.remix_without, remix.remix_stems),
                         'the mixed card starts from its own song, at 100 %')
        # A card without stems : the context says so, the page needs its score.
        plain = self._run(melody_reference=self._cover())
        self.assertIsNone(page.context_of(plain)['stems'])

    def test_a_relaunch_replaces_the_stems_never_adds_cards(self):
        gen = self._run(separate_stems=True, melody_reference=self._cover())
        first = {role: card.pk for role, card in self._stems(gen).items()}
        ComposerGeneration.objects.filter(pk=gen.pk).update(status='RUNNING')
        gen = self._run(ComposerGeneration.objects.get(pk=gen.pk), process='separate')
        self.assertEqual(JOB_SUCCESS, self._states(gen)['separate'], gen.error_message)
        self.assertEqual(2, len(_Separator.calls))
        from wama.common.utils.batch_common import batch_of
        # COUNTED, not read by role : a dict by role keeps one card per stem and would hide doubles.
        self.assertEqual(2, ComposerGeneration.objects.filter(derived_from=gen).count())
        self.assertEqual(3, batch_of(gen).items.count())
        self.assertEqual(first, {role: card.pk for role, card in self._stems(gen).items()})

    def test_a_stem_card_is_not_split_again(self):
        from wama.composer.function_specs import PIPELINE
        gen = self._run(separate_stems=True, melody_reference=self._cover())
        stem = self._stems(gen)['vocals']
        stem.separate_stems = True
        self.assertFalse(PIPELINE.spec('separate').applies(stem, None))
        self.assertTrue(PIPELINE.spec('separate').applies(gen, None))

    def test_without_the_toggle_or_a_model_nothing_is_separated(self):
        gen = self._run(melody_reference=self._cover())
        self.assertNotIn('separate', self._states(gen))
        self.installed = False
        gen = self._run(separate_stems=True, melody_reference=self._cover())
        self.assertNotIn('separate', self._states(gen))
        self.assertEqual(([], {}), (_Separator.calls, self._stems(gen)))


class TheToggleReachesTheCardTest(TestCase):
    """« Partition complète » set on, the card must carry it (2026-10-19, #849: set on, then seen
    back off — the panel's add-to-queue posted a hand list without it, and the ⚙ route dropped
    it). The ⚙ modal and the inspector are held by the common contract
    (`tests_item_settings_contract`, every writable setting); here the creation and the panel."""

    def setUp(self):
        from django.contrib.auth.models import Group
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        self.user = get_user_model().objects.create_user('composer_parts_toggle', password='x')
        for role in (DEFAULT_APP_ACCESS.get('composer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)

    def test_the_toggle_posted_at_creation_is_on_the_new_card(self):
        from django.urls import reverse
        for posted, expected in (('true', True), ('false', False)):
            with self.subTest(posted=posted):
                response = self.client.post(reverse('composer:generate'),
                                            {'prompt': 'a song', 'model': 'musicgen-small',
                                             'duration': '5', 'extract_parts': posted,
                                             'parts_model': OTHER_TRANSCRIBER})
                self.assertEqual(200, response.status_code, response.content[:300])
                gen = ComposerGeneration.objects.get(pk=response.json()['id'])
                self.assertIs(expected, gen.extract_parts)
                self.assertEqual(OTHER_TRANSCRIBER, gen.parts_model)

    def test_the_model_setting_follows_its_process(self):
        """Its select : the catalogue models of the task the glue draws in, « auto » first ; it
        serves the two full-score processes (the input's, the render's — 2026-10-26) and stales
        them alone ; no `show_if`, which names a single toggle."""
        from wama.composer.function_specs import PIPELINE
        from wama.composer.params import PARAMS
        from wama.composer.utils.model_choice import PARTS_EXTRACTION_TASK
        (param,) = [p for p in PARAMS if p.name == 'parts_model']
        self.assertEqual(('catalog', {'task': PARTS_EXTRACTION_TASK}, True, None),
                         (param.options_source, param.options_query, param.options_auto,
                          param.show_if))
        others = [s.key for s in PIPELINE.specs if 'parts_model' in PIPELINE.watched_of(s)]
        self.assertEqual(['parts', 'rendered_parts'], others)
        self.assertEqual('auto', ComposerGeneration().parts_model)

    def test_the_panel_posts_its_whole_host_not_a_hand_list(self):
        """Every panel setting travels with the deposit because the add-to-queue reads the panel
        HOST (`WamaApp.addToQueue` `paramsHostId`), which the template renders from the schema."""
        from django.conf import settings
        from wama.composer.params import PARAMS
        root = Path(settings.BASE_DIR) / 'wama' / 'composer'
        script = (root / 'static' / 'composer' / 'js' / 'index.js').read_text(encoding='utf-8')
        template = (root / 'templates' / 'composer' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("paramsHostId: 'composerPanelHost'", script)
        self.assertIn('id="composerPanelHost"', template)
        self.assertNotIn('extraFields', script, 'a hand list of panel settings forgets the next one')
        panel = {p.name for p in PARAMS if 'panel' in (p.contexts or ())}
        self.assertIn('extract_parts', panel)


class TheCoverIsTheInputTest(TestCase):
    """2026-10-26, Fabien on #880 : « si on fournit un audio cover en entrée, il devrait être en
    preview d'entrée » — the Input face was EMPTY (a cover has no prompt, nothing named the file).
    The common rule of the preview : the WORK port first, the prompt otherwise."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_cover_input', password='x')

    def _input(self, gen):
        """The Input face. The composer's WORK ports come from the models of the CATALOGUE (empty
        in the test base) : set to what the live catalogue gives (measured 2026-10-26 : group
        `travail`, natures audio and score) — what is held here is which FILE is the input."""
        from django.test import RequestFactory
        from wama.common.utils import preview_utils
        with mock.patch.object(preview_utils, '_input_port_group', return_value='travail'), \
                mock.patch.object(preview_utils, '_work_natures', return_value={'audio', 'score'}):
            return preview_utils._input_preview(
                'composer', gen, RequestFactory().get('/', HTTP_HOST='localhost')) or {}

    def test_the_cover_audio_is_the_input_face_the_prompt_otherwise(self):
        rel = 'users/1/temp/cover.mp3'
        (Path(self.tmp) / rel).parent.mkdir(parents=True)
        (Path(self.tmp) / rel).write_bytes(b'ID3' + b'\0' * 64)
        cover = ComposerGeneration.objects.create(user=self.user, prompt='', melody_reference=rel)
        face = self._input(cover)
        self.assertEqual(('cover.mp3', 'audio/mpeg'), (face.get('name'), face.get('mime_type')))
        plain = ComposerGeneration.objects.create(user=self.user, prompt='pop song')
        self.assertEqual('pop song', self._input(plain).get('content'), 'no work file : the prompt')
