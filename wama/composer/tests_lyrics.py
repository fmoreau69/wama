"""The LYRICS of a song reach the card's « Paroles » field on their own (2026-11-03, Fabien).

  * `extract_lyrics`: the audio of a cover → the field, under the score's sections. YuE2 receives
    neither that audio nor its words, and its documentation prescribes this transcription;
  * `rendered_lyrics`: what the model sang by itself → the field, without staling what it sang;
  * lyrics that are there are never rewritten: it is what keeps a correction;
  * the voice « Instrumental » is the off switch; hearing nothing, or failing, holds nothing back;
  * the language goes first in the style, where the engine reads it (`vocals.sung_in`).

The scores are read by the ENGINE's own reader (`abc_tools`); the transcription is a stand-in.
"""
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.backends.yue2_3b_backend import YuE2Backend
from wama.common.models import JOB_FAILURE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.composer import tasks
from wama.composer.function_specs import PIPELINE
from wama.composer.models import ComposerGeneration
from wama.composer.tests_pipeline import ENGINES, SCORE, SCORE_MODEL, _ScoreEngine, catalogue_rows
from wama.composer.tests_task import _celery_task
from wama.composer.utils import vocals
from wama.composer.utils.lyrics import fit_to_duration, lyrics_from_segments

EAR = 'transcriber:whisper'
WORDS = 'la mer revient sur la plage quand le soir tombe doucement'
VENDORED = (Path(settings.BASE_DIR) / 'wama/common/backends/vendor/yue/skills/yue2-music/scripts/abc_tools.py').is_file()
#: The native two-voice dialect, as SheetSage2 writes it: 60 BPM, so a 4/4 bar lasts 4 s.
NATIVE = '\n'.join(['X:1', 'T:', 'M:4/4', 'L:1/16', 'Q:1/4=60',
                    'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"',
                    'V: Ins clef=treble name="Ins Melody" snm="Inst."', 'K:C',
                    '% intro', 'V: Vocal', 'Z2|', 'V: Ins', 'C16|D16|',
                    '% verse', 'V: Vocal', 'C16|D16|', 'V: Ins', 'Z2|',
                    'V: Vocal', 'E16|', 'V: Ins', 'Z|',
                    '% chorus', 'V: Vocal', 'G16|', 'V: Ins', 'Z|'])


def _segment(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text)


SECTIONS = [{'name': 'intro', 'start': 0.0, 'end': 8.0, 'sings': False},
            {'name': 'verse', 'start': 8.0, 'end': 20.0, 'sings': True},
            {'name': 'chorus', 'start': 20.0, 'end': 24.0, 'sings': True}]


class LyricsUnderTheirSectionsTest(SimpleTestCase):

    def test_each_line_goes_under_the_section_it_is_sung_in(self):
        got = lyrics_from_segments([_segment(9, 12, 'la mer revient sur la plage'),
                                    _segment(13, 16, 'quand le soir tombe'),
                                    _segment(21, 23, 'et le vent se lève encore')], SECTIONS)
        self.assertEqual('[Verse]\nla mer revient sur la plage\nquand le soir tombe\n\n'
                         '[Chorus]\net le vent se lève encore', got)

    def test_what_is_heard_where_the_voice_is_silent_is_dropped(self):
        """A transcription invents words over an instrumental: the score knows the voice rests."""
        got = lyrics_from_segments([_segment(1, 3, 'sous-titres par la communauté'),
                                    _segment(9, 12, WORDS)], SECTIONS)
        self.assertNotIn('sous-titres', got)
        self.assertIn(WORDS, got)

    def test_without_a_score_they_stay_in_one_verse(self):
        self.assertEqual(f'[Verse]\n{WORDS}', lyrics_from_segments([_segment(0, 5, WORDS)]))

    def test_a_few_stray_words_are_not_lyrics(self):
        self.assertEqual('', lyrics_from_segments([_segment(9, 10, 'merci')], SECTIONS))
        self.assertEqual('', lyrics_from_segments([], SECTIONS))

    def test_a_transcription_looping_on_music_is_not_lyrics(self):
        """Mesuré sur de vrais morceaux : Whisper rend 48 mots, dont 4 distincts."""
        self.assertEqual('', lyrics_from_segments([_segment(0, 200, 'Thank you for watching! ' * 12)]))

    def test_a_script_without_spaces_can_still_make_lyrics(self):
        self.assertTrue(lyrics_from_segments([_segment(0, 5, '海上明月共潮生滟滟随波千万里何处春江无月明江流宛转绕芳甸月照花林皆似霰空里流霜不觉飞')]))

    def test_a_long_passage_is_cut_into_lines_placed_by_where_they_fall(self):
        """Qwen3-ASR rend de longs passages sans le temps des mots : une phrase par ligne, sa section
        estimée à sa place dans le texte. Mesuré : 7 à 10 segments par chanson."""
        passage = _segment(8, 24, 'La mer revient sur la plage ce soir. Le vent se lève encore et encore.')
        self.assertEqual('[Verse]\nLa mer revient sur la plage ce soir.\n\n'
                         '[Chorus]\nLe vent se lève encore et encore.', lyrics_from_segments([passage], SECTIONS))

    def test_the_sections_are_fitted_to_the_real_duration(self):
        fitted = fit_to_duration(SECTIONS, 12.0)
        self.assertEqual((4.0, 10.0), (fitted[1]['start'], fitted[1]['end']))
        self.assertEqual(SECTIONS, fit_to_duration(SECTIONS, 0))


@skipUnless(VENDORED, 'the vendored engine is not versioned: absent from a fresh clone')
class TheEngineReadsItsScoreTest(SimpleTestCase):

    def test_sections_come_with_their_times_and_whether_the_voice_sings(self):
        got = YuE2Backend.score_sections(NATIVE)
        self.assertEqual([('intro', 0.0, 8.0, False), ('verse', 8.0, 20.0, True), ('chorus', 20.0, 24.0, True)],
                         [(s['name'], s['start'], s['end'], s['sings']) for s in got])

    def test_a_score_outside_the_dialect_is_refused(self):
        with self.assertRaises(ValueError):
            YuE2Backend.score_sections(SCORE)


class TheLanguageGoesFirstInTheStyleTest(SimpleTestCase):

    def _sung(self, caption, language):
        with mock.patch('wama.common.utils.text_language.detect_text_language', return_value=language):
            return vocals.sung_in(caption, WORDS)

    def test_it_opens_the_style_as_the_engine_documents(self):
        self.assertEqual('French, folk nu-metal', self._sung('folk nu-metal', 'fr'))

    def test_a_style_that_names_it_is_left_alone(self):
        self.assertEqual('french folk', self._sung('french folk', 'fr'))

    def test_an_unsure_language_adds_nothing(self):
        self.assertEqual('folk', self._sung('folk', ''))

    def test_lyrics_kept_on_the_card_carry_it_to_the_engine(self):
        with mock.patch.object(vocals, 'sings', return_value=True), \
                mock.patch('wama.common.utils.text_language.detect_text_language', return_value='fr'):
            out, _new = vocals.prepare_prompt('auto', 'folk', SCORE_MODEL, stored_lyrics=f'[Verse]\n{WORDS}')
        self.assertEqual(f'French, folk\n\n[Verse]\n{WORDS}', out)


class LyricsProcessesTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_lyrics', password='x')
        _ScoreEngine.built, _ScoreEngine.plans, _ScoreEngine.renders = 0, [], []
        _ScoreEngine.unloaded, _ScoreEngine.error = 0, None
        self.heard = [_segment(0, 5, WORDS)]
        self.ear_error = None
        self.listened = []
        self.unloaded = []
        catalogue_rows()

    def _file(self, rel, content=b'RIFF'):
        path = Path(self.tmp) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return rel

    def _cover(self, **fields):
        """A cover whose score is supplied: the extraction of the score is another test's matter."""
        return self._generation(melody_reference=self._file('users/1/temp/song.mp3'),
                                reference_score=self._file('users/1/temp/song.abc', SCORE.encode()), **fields)

    def _generation(self, **fields):
        fields.setdefault('prompt', 'folk')
        return ComposerGeneration.objects.create(user=self.user, model=SCORE_MODEL, status='RUNNING', **fields)

    def _transcribe(self, path, **kwargs):
        self.listened.append((Path(path).name, kwargs))
        if self.ear_error:
            raise self.ear_error
        return SimpleNamespace(segments=self.heard, language='fr', text=WORDS)

    def _patches(self):
        return [mock.patch('wama.common.backends.manager.backend_for_key', side_effect=lambda key: ENGINES.get(key)),
                mock.patch('wama.composer.utils.model_choice.lyrics_transcriber', return_value=EAR),
                mock.patch('wama.composer.utils.model_choice.lyrics_transcription_available', return_value=True),
                mock.patch('wama.common.utils.whisper_utils.transcribe_audio', side_effect=self._transcribe),
                mock.patch('wama.common.utils.media_probe.probe_media', return_value={'duration': 5.0}),
                mock.patch('wama.model_manager.services.memory_manager.MemoryManager.unload_model',
                           side_effect=lambda key: self.unloaded.append(key) or True),
                mock.patch('wama.common.utils.model_readiness.ensure_installed', return_value=True),
                mock.patch('wama.common.utils.task_skeleton.close_old_connections'),
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: text),
                mock.patch('wama.common.utils.model_readiness.warn_if_weights_missing'),
                mock.patch('wama.composer.utils.model_config.clamp_duration',
                           side_effect=lambda value, model_id=None: value),
                mock.patch('wama.model_manager.services.eta_estimator.record_run')]

    def _run(self, gen):
        patches = self._patches()
        for patch in patches:
            patch.start()
        try:
            ComposerGeneration.objects.filter(pk=gen.pk).update(status='RUNNING')
            tasks.compose_task.run.__func__(_celery_task(), gen.pk, None)
        finally:
            for patch in patches:
                patch.stop()
        return ComposerGeneration.objects.get(pk=gen.pk)

    def _states(self, gen):
        return {row.node_id: row.status for row in process_runs.lines(gen)}

    def test_a_cover_gets_the_words_of_its_song_in_the_field(self):
        """LA demande de Fabien : récupérer les paroles d'une chanson, dans le champ Paroles."""
        gen = self._run(self._cover())
        self.assertEqual(f'[Verse]\n{WORDS}', gen.lyrics)
        self.assertEqual('song.mp3', self.listened[0][0], 'the INPUT is what is listened to')
        self.assertEqual(JOB_SUCCESS, self._states(gen)['extract_lyrics'])

    def test_the_render_then_sings_them(self):
        self._run(self._cover())
        self.assertIn(f'[Verse]\n{WORDS}', _ScoreEngine.renders[-1]['prompt'])

    def test_the_chant_is_not_filtered_out_and_the_ear_is_given_back(self):
        """Un filtre de parole écarte le chant ; la carte revient au rendu, qui suit."""
        self._run(self._cover())
        self.assertIs(False, self.listened[0][1]['vad_filter'])
        self.assertEqual([EAR], self.unloaded)

    def test_lyrics_already_there_are_never_rewritten(self):
        """C'est ce qui garde une correction de l'utilisateur."""
        gen = self._run(self._cover(lyrics='[Verse]\nmes paroles corrigées'))
        self.assertEqual('[Verse]\nmes paroles corrigées', gen.lyrics)
        self.assertEqual([], self.listened)

    def test_lyrics_in_the_prompt_are_not_doubled(self):
        gen = self._run(self._cover(**{'prompt': 'folk\n\n[Verse]\nla mer'}))
        self.assertEqual('', gen.lyrics)
        self.assertEqual([], self.listened)

    def test_instrumental_is_the_off_switch(self):
        gen = self._run(self._cover(vocals=vocals.INSTRUMENTAL))
        self.assertEqual(('', []), (gen.lyrics, self.listened))

    def test_a_model_that_does_not_sing_listens_to_nothing(self):
        """Who sings is the catalogue's word (`supports_vocals`, read by `ProcessSpec.needs`)."""
        from wama.composer.tests_pipeline import CATALOGUE
        catalogue_rows(**{SCORE_MODEL: {**CATALOGUE[SCORE_MODEL], 'supports_vocals': False}})
        gen = self._run(self._cover())
        self.assertEqual(('', []), (gen.lyrics, self.listened))

    def test_a_song_without_words_leaves_the_field_empty_and_goes_on(self):
        self.heard = []
        gen = self._run(self._cover())
        self.assertEqual('', gen.lyrics)
        self.assertEqual('SUCCESS', gen.status)

    def test_an_ear_that_fails_does_not_hold_the_song_back(self):
        self.ear_error = RuntimeError('no ear')
        gen = self._run(self._cover())
        self.assertEqual('SUCCESS', gen.status, 'optional: the render still plays')
        self.assertEqual(JOB_FAILURE, self._states(gen)['extract_lyrics'])
        self.assertEqual([EAR, EAR], self.unloaded, 'released even on failure, on both processes')

    def test_what_the_model_sang_by_itself_reaches_the_field(self):
        """Seconde demande : le modèle génère ses paroles lui-même, elles rejoignent le champ."""
        gen = self._run(self._generation())
        self.assertEqual(f'[Verse]\n{WORDS}', gen.lyrics)
        self.assertEqual(JOB_SUCCESS, self._states(gen)['rendered_lyrics'])
        self.assertTrue(self.listened[0][0].endswith('.wav'), 'the RENDER is what is listened to')

    def test_writing_them_does_not_stale_the_render_they_come_from(self):
        """Sans cela la card serait « périmée » par ses propres paroles, et ▶ rejouerait le morceau."""
        gen = self._run(self._generation())
        patches = self._patches()
        for patch in patches:
            patch.start()
        try:
            self.assertEqual(set(), PIPELINE.refresh(gen))
        finally:
            for patch in patches:
                patch.stop()

    def test_the_score_is_fitted_to_the_song_before_the_words_are_placed(self):
        """Le temps nominal d'une partition n'est pas celui du morceau : 5,5 s tombe dans l'intro
        muette de la partition (24 s), mais dans le couplet d'un morceau de 12 s."""
        self.heard = [_segment(5, 6, WORDS)]
        patches = self._patches()
        for patch in patches:
            patch.start()
        try:
            with mock.patch('wama.common.utils.media_probe.probe_media', return_value={'duration': 12.0}), \
                    mock.patch.object(tasks, '_score_sections', return_value=SECTIONS):
                got = tasks._heard_lyrics(self._cover(), mock.Mock(ensure_model=lambda key: key), 'song.mp3', score='s.abc')
        finally:
            for patch in patches:
                patch.stop()
        self.assertEqual(f'[Verse]\n{WORDS}', got['fields']['lyrics'])

    def test_a_cover_heard_once_does_not_listen_twice(self):
        self._run(self._cover())
        self.assertEqual(['song.mp3'], [name for name, _kwargs in self.listened])

    def test_lyrics_written_by_the_llm_are_kept_and_nothing_is_listened_to(self):
        """« Chanson » sans paroles : déjà gardées sur la card par `prepare_prompt`."""
        with mock.patch('wama.common.utils.app_metadata.write_lyrics_for', return_value='[Verse]\nécrites'):
            gen = self._run(self._generation(vocals=vocals.SONG))
        self.assertEqual('[Verse]\nécrites', gen.lyrics)
        self.assertEqual([], self.listened)


class TheSettingIsDeclaredLikeItsSiblingsTest(SimpleTestCase):

    def test_the_model_of_the_ear_is_a_card_setting_with_its_auto(self):
        from wama.composer.params import PARAMS
        from wama.composer.utils.model_choice import LYRICS_RESOLUTION, LYRICS_TASK
        (param,) = [p for p in PARAMS if p.name == 'lyrics_model']
        self.assertEqual(({'task': LYRICS_TASK}, True, LYRICS_RESOLUTION),
                         (param.options_query, param.options_auto, param.options_resolution))
        self.assertEqual('auto', ComposerGeneration().lyrics_model)

    def test_the_draw_hears_singing_first_not_speech(self):
        """Mesuré sur 3 chansons : Whisper invente, Qwen3-ASR entend. L'inverse du describer."""
        from wama.composer.utils.model_choice import LYRICS_RESOLUTION
        self.assertEqual('qwen', LYRICS_RESOLUTION['priority'][0])
        self.assertLess(LYRICS_RESOLUTION['priority'].index('qwen'), LYRICS_RESOLUTION['priority'].index('whisper'))

    def test_changing_it_only_stales_the_processes_that_listen(self):
        watchers = {s.key for s in PIPELINE.specs if 'lyrics_model' in PIPELINE.watched_of(s)}
        self.assertEqual({'extract_lyrics', 'rendered_lyrics'}, watchers)
