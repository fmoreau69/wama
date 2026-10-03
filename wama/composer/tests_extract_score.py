"""The composer's THIRD process — `extract_score` (2026-10-03): the audio of the song to cover →
its score (SheetSage2, task `audio-to-score`), which a model that covers BY THE SCORE (YuE2)
follows in the style of the prompt.

What each test holds:
  * the process only exists for a cover by a model that follows a score without taking the audio
    itself, when an extraction model is installed — and it REPLACES `plan` ;
  * the extraction model is not the card's: drawn by task, released before the render, named on
    its execution line ;
  * the score is an output of the card, followed by the render, which never receives the audio ;
  * the card, the creation view and the assistant tool accept the audio of a cover for such a model
    (`accepts_input`) ;
  * YuE2 plays a chord-free score in `melody`, a score with chords in `full`.

No model, no GPU: the engines are stand-ins (the ones of `tests_pipeline`, plus an extractor).
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.models import JOB_FAILURE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.composer import tasks
from wama.composer.models import ComposerGeneration
from wama.composer.tests_pipeline import (ENGINES, PLAIN_MODEL, SCORE_MODEL, _PlainEngine,
                                          _ScoreEngine, _VendoredPipeline)
from wama.composer.tests_task import _celery_task

EXTRACTOR = 'huggingface:m-a-p/SheetSage2'
MELODY_MODEL = 'composer:musicgen-melody'
#: What SheetSage2 returns with `melody_only=True` (shape measured on a real song, 2026-10-03).
MELODY_ABC = ('X:1\nM:4/4\nL:1/32\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nK:C\n'
              '% verse\nV: Vocal\nG4c4z4c4c4B4A4G2G2-|\n')
#: What YuE2 plans with `cot="full"` (shape of the real score of element #313): chords in quotes.
PLANNED_ABC = ('X:1\nM:4/4\nV: Vocal clef=treble name="Vocal Melody" snm="Vocal"\nK:F\n'
               'V: Vocal\n"F"f4c4B2AB2A3|"C"e4c4B2AB2A3|\n')


class _Extractor:
    """Stand-in of a score-extraction backend (`ScoreExtractionBackend`)."""
    built, unloaded, calls = 0, 0, []
    error = None

    def __init__(self):
        type(self).built += 1

    def unload(self):
        _Extractor.unloaded += 1

    def extract_score(self, **kwargs):
        _Extractor.calls.append(kwargs)
        if _Extractor.error:
            raise _Extractor.error
        return MELODY_ABC


def _consumes(value, token):
    """The catalogue facts of the stand-ins: YuE2 follows a score, MusicGen Melody takes audio."""
    return {SCORE_MODEL: {'work_score'}, MELODY_MODEL: {'work_audio'}}.get(value, set()) >= {token}


class ExtractThenRenderTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_extract', password='x')
        _ScoreEngine.built, _ScoreEngine.plans, _ScoreEngine.renders = 0, [], []
        _ScoreEngine.unloaded, _ScoreEngine.error = 0, None
        _PlainEngine.renders = []
        _Extractor.built, _Extractor.unloaded, _Extractor.calls, _Extractor.error = 0, 0, [], None
        self.extractor = EXTRACTOR

    def _cover(self, model=SCORE_MODEL, **fields):
        gen = ComposerGeneration.objects.create(user=self.user, prompt='jazz trio\n[verse]\nla',
                                                model=model, status='RUNNING', **fields)
        gen.melody_reference.save('song.wav', ContentFile(b'RIFF'))
        return gen

    def _run(self, gen, process=None):
        engines = {**ENGINES, MELODY_MODEL: _PlainEngine, EXTRACTOR: _Extractor}
        ComposerGeneration.objects.filter(pk=gen.pk).update(status='RUNNING')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.backends.manager.backend_for_key',
                           side_effect=lambda key: engines.get(key)), \
                mock.patch('wama.composer.utils.model_choice.consumes_input',
                           side_effect=_consumes), \
                mock.patch('wama.composer.utils.model_choice.score_extractor',
                           side_effect=lambda: self.extractor), \
                mock.patch('wama.composer.utils.model_choice.score_extraction_available',
                           side_effect=lambda: bool(self.extractor)), \
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

    # ── when the process exists ─────────────────────────────────────────────────────────────
    def test_a_cover_by_a_score_model_extracts_the_score_then_renders_it_instead_of_planning(self):
        gen = self._run(self._cover())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual({'extract_score': JOB_SUCCESS, 'render': JOB_SUCCESS, 'output': JOB_SUCCESS}, self._states(gen))
        self.assertEqual([], _ScoreEngine.plans, 'the score comes from the audio, not the prompt')
        self.assertTrue(_Extractor.calls[0]['melody_only'], 'a cover takes the melody only')
        self.assertTrue(_Extractor.calls[0]['audio_path'].replace('\\', '/')
                        .endswith(gen.melody_reference.name))

    def test_the_extracted_score_is_an_output_of_the_card_and_the_render_follows_it(self):
        gen = self._run(self._cover())
        self.assertIn(f'/score{gen.pk}_', gen.extracted_score.name)
        written = Path(self.tmp) / gen.extracted_score.name
        self.assertEqual(MELODY_ABC, written.read_text(encoding='utf-8'))
        render = _ScoreEngine.renders[0]
        self.assertEqual(str(written), str(Path(render['score_path'])))
        self.assertIsNone(render['melody_path'], 'YuE2 refuses the audio: it gets the score')
        line = process_runs.line(gen, 'extract_score')
        self.assertEqual((gen.extracted_score.name, 'composer.extract_score', EXTRACTOR),
                         (line.output_ref, line.process_key, line.model_key))

    def test_the_extraction_model_is_released_before_the_render(self):
        self._run(self._cover())
        self.assertEqual((1, 1), (_Extractor.built, _Extractor.unloaded))

    def test_a_model_that_takes_the_audio_itself_keeps_its_direct_path(self):
        gen = self._run(self._cover(model=MELODY_MODEL))
        self.assertEqual({'render': JOB_SUCCESS, 'output': JOB_SUCCESS}, self._states(gen))
        self.assertEqual([], _Extractor.calls)
        self.assertTrue(_PlainEngine.renders[0]['melody_path'].replace('\\', '/')
                        .endswith(gen.melody_reference.name))

    def test_a_score_the_user_gave_wins_over_the_audio(self):
        gen = self._cover()
        gen.reference_score.save('mine.abc', ContentFile(b'X:1\nK:G\nGABc|'))
        gen = self._run(gen)
        self.assertEqual({'render': JOB_SUCCESS, 'output': JOB_SUCCESS}, self._states(gen))
        self.assertEqual([], _Extractor.calls)

    def test_without_an_extraction_model_the_score_model_plans_as_before(self):
        self.extractor = ''
        gen = self._run(self._cover())
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS, 'output': JOB_SUCCESS}, self._states(gen))
        self.assertEqual([], _Extractor.calls)

    # ── failures and relaunches ─────────────────────────────────────────────────────────────
    def test_a_failed_extraction_stops_the_card_releases_the_model_and_renders_nothing(self):
        _Extractor.error = RuntimeError('no beat decoded')
        gen = self._run(self._cover())
        self.assertEqual('FAILURE', gen.status)
        self.assertEqual(JOB_FAILURE, self._states(gen)['extract_score'])
        self.assertEqual(([], 1), (_ScoreEngine.renders, _Extractor.unloaded))

    def test_a_failed_render_is_relaunched_without_extracting_the_score_again(self):
        _ScoreEngine.error = RuntimeError('engine down')
        gen = self._run(self._cover())
        self.assertEqual(JOB_SUCCESS, self._states(gen)['extract_score'])
        _ScoreEngine.error = None
        gen = self._run(gen)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual((1, 2), (len(_Extractor.calls), len(_ScoreEngine.renders)))

    def test_an_old_extracted_score_is_not_followed_once_the_cover_audio_is_gone(self):
        gen = self._run(self._cover())
        ComposerGeneration.objects.filter(pk=gen.pk).update(melody_reference=None)
        gen = self._run(gen)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertNotEqual(str(Path(self.tmp) / gen.extracted_score.name),
                            str(Path(_ScoreEngine.renders[-1]['score_path'])),
                            'without the audio, the card is no cover: YuE2 plans its own score')


class TheCoverAudioIsAcceptedTest(SimpleTestCase):
    """`accepts_input`: the question the creation view and the assistant tool ask — answered by
    the GENERIC rule of the pipeline (`AppPipeline.covering_inputs`), not by a composer rule."""

    def _accepts(self, model, token, installed=True):
        from wama.composer.utils import model_choice as mc
        with mock.patch.object(mc, 'consumes_input', side_effect=_consumes), \
                mock.patch.object(mc, 'score_extraction_available', return_value=installed):
            return mc.accepts_input(model, token)

    def test_a_score_model_takes_the_audio_of_a_cover_when_it_can_be_extracted(self):
        self.assertTrue(self._accepts(SCORE_MODEL, 'work_audio'))
        self.assertFalse(self._accepts(SCORE_MODEL, 'work_audio', installed=False))

    def test_the_other_inputs_are_the_model_s_own(self):
        self.assertTrue(self._accepts(MELODY_MODEL, 'work_audio'))
        self.assertTrue(self._accepts(SCORE_MODEL, 'work_score'))
        self.assertFalse(self._accepts(PLAIN_MODEL, 'work_audio'))

    def test_the_card_offers_the_cover_audio_to_a_score_model(self):
        """The card's per-model inputs (`_input_match_meta`) gain what the pipeline brings."""
        from wama.composer import views
        meta = {SCORE_MODEL: {'inputs_required': ['prompt'], 'inputs_optional': ['work_score'],
                              'task': 'text-to-music'},
                PLAIN_MODEL: {'inputs_required': ['prompt'], 'inputs_optional': [],
                              'task': 'text-to-music'}}
        with mock.patch('wama.common.utils.input_match.input_match_meta', return_value=meta), \
                mock.patch('wama.composer.utils.model_choice.score_extraction_available',
                           return_value=True):
            got = views._input_match_meta()
        self.assertIn('work_audio', got[SCORE_MODEL]['inputs_optional'])
        self.assertNotIn('work_audio', got[PLAIN_MODEL]['inputs_optional'])


class AutoDrawsAmongWhatTakesTheCoverTest(TestCase):
    """Under « auto », a cover audio used to keep only the models that take the audio THEMSELVES:
    YuE2 was never a candidate, and with MusicGen Melody not installed the draw fell back on
    `musicgen-small`, which ignores the audio. The candidates are now those that accept it within
    the pipeline."""

    def test_the_candidates_are_the_models_that_accept_the_audio_within_the_pipeline(self):
        from wama.composer.utils import auto_model
        gen = ComposerGeneration(model='auto:text-to-music', prompt='jazz')
        gen.melody_reference.name = 'song.wav'
        with mock.patch('wama.composer.utils.model_choice.models_accepting',
                        return_value=[SCORE_MODEL, MELODY_MODEL]) as accepting, \
                mock.patch.object(auto_model, 'resolve_model_choice',
                                  return_value=SCORE_MODEL) as draw:
            self.assertEqual(SCORE_MODEL, auto_model.resolve_auto_model(gen))
        accepting.assert_called_once_with('work_audio', 'text-to-music')
        self.assertEqual([SCORE_MODEL, MELODY_MODEL], draw.call_args.kwargs['spec']['candidates'])

    def test_with_nobody_to_take_it_the_draw_says_so_through_the_model_filter(self):
        from wama.composer.utils import auto_model
        gen = ComposerGeneration(model='auto:text-to-music', prompt='jazz')
        gen.melody_reference.name = 'song.wav'
        with mock.patch('wama.composer.utils.model_choice.models_accepting', return_value=[]), \
                mock.patch.object(auto_model, 'resolve_model_choice', return_value='x') as draw:
            auto_model.resolve_auto_model(gen)
        spec = draw.call_args.kwargs['spec']
        self.assertNotIn('candidates', spec, 'an empty list would mean « no restriction »')
        self.assertEqual(['work_audio'], spec['consumes'])


class YuE2PlaysWhatTheScoreSaysTest(SimpleTestCase):
    """`cot` follows the score: chord-free → `melody` (the cover chain of the engine's docs)."""

    def test_the_mode_is_read_from_the_score(self):
        from wama.common.backends.yue2_3b_backend import cot_for_score
        self.assertEqual('melody', cot_for_score(MELODY_ABC))
        self.assertEqual('full', cot_for_score(PLANNED_ABC))

    def test_the_quoted_names_of_the_header_are_not_chords(self):
        from wama.common.backends.yue2_3b_backend import cot_for_score
        self.assertIn('name="Vocal Melody"', MELODY_ABC)
        self.assertEqual('melody', cot_for_score(MELODY_ABC))

    def test_the_render_of_an_extracted_score_asks_the_vendored_pipeline_for_melody(self):
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        for abc, cot in ((MELODY_ABC, 'melody'), (PLANNED_ABC, 'full'), (None, 'full')):
            with self.subTest(cot=cot), tempfile.TemporaryDirectory() as folder:
                backend = YuE2Backend()
                backend._pipeline, backend._warm = _VendoredPipeline(), True
                score = None
                if abc:
                    score = Path(folder) / 'score.abc'
                    score.write_text(abc, encoding='utf-8')
                backend.generate(model_id='YuE2-3B', prompt='jazz trio\n[verse]\nla',
                                 duration=30, output_path=str(Path(folder) / 'out.wav'),
                                 score_path=str(score) if score else None)
                self.assertEqual(cot, backend._pipeline.called[0]['cot'])
