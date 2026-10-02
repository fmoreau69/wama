"""The composer's card carries TWO processes — pilot of `WAMA_APP_GENERATION_ROUTE §10.6` (P3).

`plan` writes a score, `render` plays it. What the pilot must show, and what each test holds:

  * the pipeline is written down like the cam_analyzer's (registry → `pipeline` manifest with
    `function` nodes of the catalogue) — decision n°11 ;
  * `plan` only exists for an engine that SAYS it writes its score first, and only when the user
    did not give his own — every other model keeps a single process and behaves as before ;
  * the score is an output of the card (a file field), the execution line only points at it ;
  * a relaunch replays what is no longer valid and nothing else, and a render replayed alone uses
    the model that wrote the score it follows — even under « auto » ;
  * the engine side: YuE2 does say it, and its two calls go through the vendored pipeline's own
    `plan()` then its « provided score » path.

No model, no GPU: the engine is a stand-in ; the last class drives the REAL backend class over a
stand-in of the vendored pipeline.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.models import JOB_FAILURE, JOB_STALE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.composer import tasks
from wama.composer.function_specs import PIPELINE
from wama.composer.models import ComposerGeneration
from wama.composer.tests_task import _celery_task

AUTO = 'auto:text-to-music'
SCORE_MODEL = 'huggingface:m-a-p/YuE2-3B'
PLAIN_MODEL = 'composer:musicgen-small'
SCORE = 'X:1\nK:C\nCDEF|GABc|'


class _ScoreEngine:
    """Stand-in of an engine that writes its score before playing it."""
    supports_score_planning = True
    built, unloaded, plans, renders = 0, 0, [], []
    error = None

    def __init__(self):
        type(self).built += 1

    def unload(self):
        _ScoreEngine.unloaded += 1

    def plan_score(self, **kwargs):
        _ScoreEngine.plans.append(kwargs)
        return SCORE

    def generate(self, **kwargs):
        _ScoreEngine.renders.append(kwargs)
        if _ScoreEngine.error:
            raise _ScoreEngine.error
        Path(kwargs['output_path']).write_bytes(b'RIFF')


class _PlainEngine:
    """Stand-in of an engine with a single step — every model but YuE2 today."""
    renders = []

    def unload(self):
        pass

    def generate(self, **kwargs):
        _PlainEngine.renders.append(kwargs)
        Path(kwargs['output_path']).write_bytes(b'RIFF')


class _Deferred(Exception):
    """What the stand-in task raises in place of Celery's `Retry`."""


def _deferring_task():
    task = _celery_task()
    task.retry = staticmethod(lambda **kwargs: _Deferred(kwargs))
    return task


ENGINES = {SCORE_MODEL: _ScoreEngine, PLAIN_MODEL: _PlainEngine}


class PlanThenRenderTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.user = get_user_model().objects.create_user('composer_pipeline', password='x')
        _ScoreEngine.built, _ScoreEngine.plans, _ScoreEngine.renders = 0, [], []
        _ScoreEngine.unloaded, _ScoreEngine.error = 0, None
        _PlainEngine.renders = []

    def _generation(self, **fields):
        fields.setdefault('model', SCORE_MODEL)
        return ComposerGeneration.objects.create(user=self.user, prompt='a calm piano\n[verse]\nla',
                                                 status='RUNNING', **fields)

    def _run(self, gen, drawn=SCORE_MODEL):
        """Runs the real task body on a FRESH instance (as a worker does) ; the draw, the prompt
        pipeline, the engines and the ETA record are stand-ins."""
        ComposerGeneration.objects.filter(pk=gen.pk).update(status='RUNNING')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.composer.utils.auto_model.resolve_auto_model',
                           return_value=drawn) as draw, \
                mock.patch('wama.common.backends.manager.backend_for_key',
                           side_effect=lambda key: ENGINES.get(key)), \
                mock.patch('wama.common.utils.app_metadata.process_prompt_for',
                           side_effect=lambda app, field, text, **kw: text) as routed, \
                mock.patch('wama.common.utils.model_readiness.warn_if_weights_missing'), \
                mock.patch('wama.composer.utils.model_config.clamp_duration',
                           side_effect=lambda value, model_id=None: value), \
                mock.patch('wama.model_manager.services.eta_estimator.record_run'):
            tasks.compose_task.run.__func__(_celery_task(), gen.pk)
        gen = ComposerGeneration.objects.get(pk=gen.pk)
        gen.draw, gen.routed = draw, routed
        return gen

    def _states(self, gen):
        return {row.node_id: row.status for row in process_runs.lines(gen)}

    # ── the two processes ───────────────────────────────────────────────────────────────────
    def test_a_model_that_writes_its_score_runs_plan_then_render(self):
        gen = self._run(self._generation())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}, self._states(gen))
        self.assertEqual((1, 1), (len(_ScoreEngine.plans), len(_ScoreEngine.renders)))
        self.assertEqual(1, _ScoreEngine.built, 'the engine loaded for the score serves the render')
        self.assertEqual(1, gen.routed.call_count, 'the prompt was routed once per process')

    def test_the_score_is_an_output_of_the_card_and_the_render_follows_it(self):
        from wama.common.utils.media_paths import app_media_dir
        gen = self._run(self._generation())
        home = app_media_dir('composer', self.user.id, 'output')
        self.assertTrue(gen.planned_score.name.startswith(home + '/'), gen.planned_score.name)
        self.assertTrue(gen.planned_score.name.endswith('.abc'))
        written = Path(self.tmp) / gen.planned_score.name
        self.assertEqual(SCORE, written.read_text(encoding='utf-8'))
        self.assertEqual(str(written), str(Path(_ScoreEngine.renders[0]['score_path'])))
        plan, render = (process_runs.line(gen, key) for key in ('plan', 'render'))
        self.assertEqual((gen.planned_score.name, gen.audio_output.name),
                         (plan.output_ref, render.output_ref))
        self.assertEqual(('composer.plan', 'composer.render'),
                         (plan.process_key, render.process_key))

    def test_a_model_with_a_single_step_keeps_a_single_process(self):
        gen = self._run(self._generation(model=PLAIN_MODEL))
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual({'render': JOB_SUCCESS}, self._states(gen))
        self.assertFalse(gen.planned_score)
        self.assertIsNone(_PlainEngine.renders[0]['score_path'])

    def test_a_score_the_user_gave_is_followed_and_none_is_planned(self):
        gen = self._generation()
        gen.reference_score.save('mine.abc', ContentFile(b'X:1\nK:G\nGABc|'))
        gen = self._run(gen)
        self.assertEqual({'render': JOB_SUCCESS}, self._states(gen))
        self.assertEqual([], _ScoreEngine.plans)
        self.assertTrue(_ScoreEngine.renders[0]['score_path'].replace('\\', '/')
                        .endswith(gen.reference_score.name))

    def test_an_old_planned_score_is_not_given_to_a_model_that_takes_none(self):
        """The card moved from a score model to a plain one: its `planned_score` is still in the
        base ; handing it over would make the plain engine refuse the render."""
        gen = self._run(self._generation())
        ComposerGeneration.objects.filter(pk=gen.pk).update(model=PLAIN_MODEL)
        gen = self._run(gen)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertIsNone(_PlainEngine.renders[0]['score_path'])

    # ── what a relaunch replays ─────────────────────────────────────────────────────────────
    def test_a_failed_render_is_relaunched_without_writing_the_score_again(self):
        _ScoreEngine.error = RuntimeError('engine down')
        gen = self._run(self._generation())
        self.assertEqual(('FAILURE', 0), (gen.status, gen.progress))
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(gen))
        self.assertTrue(gen.planned_score, 'the score of the process that succeeded was lost')
        _ScoreEngine.error = None
        gen = self._run(gen)
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual((1, 2), (len(_ScoreEngine.plans), len(_ScoreEngine.renders)))

    def test_a_render_setting_does_not_replay_the_score(self):
        gen = self._run(self._generation())
        ComposerGeneration.objects.filter(pk=gen.pk).update(duration=45)
        gen.refresh_from_db()
        self.assertEqual(JOB_STALE, PIPELINE.card_state(gen))
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_STALE}, self._states(gen))
        gen = self._run(gen)
        self.assertEqual((1, 2), (len(_ScoreEngine.plans), len(_ScoreEngine.renders)))
        self.assertEqual(45, _ScoreEngine.renders[1]['duration'])
        self.assertEqual(JOB_SUCCESS, PIPELINE.card_state(gen))

    def test_a_new_prompt_replays_both(self):
        gen = self._run(self._generation())
        ComposerGeneration.objects.filter(pk=gen.pk).update(prompt='a fast drum solo')
        gen = self._run(gen)
        self.assertEqual((2, 2), (len(_ScoreEngine.plans), len(_ScoreEngine.renders)))
        self.assertEqual('a fast drum solo', _ScoreEngine.plans[1]['prompt'])

    def test_a_score_corrected_by_hand_is_rendered_without_being_planned_again(self):
        gen = self._run(self._generation())
        (Path(self.tmp) / gen.planned_score.name).write_text(SCORE + 'c4|', encoding='utf-8')
        self.assertEqual(JOB_STALE, PIPELINE.card_state(gen))
        gen = self._run(gen)
        self.assertEqual((1, 2), (len(_ScoreEngine.plans), len(_ScoreEngine.renders)))
        self.assertEqual(SCORE + 'c4|',
                         Path(_ScoreEngine.renders[1]['score_path']).read_text(encoding='utf-8'))

    def test_a_valid_card_relaunched_replays_both_even_after_the_launcher_reset(self):
        from wama.composer.views import _reset_for_relaunch
        gen = self._run(self._generation())
        _reset_for_relaunch(gen)
        gen.save()
        self.assertTrue(gen.planned_score, 'the launcher must not drop the score')
        gen = self._run(gen)
        self.assertEqual((2, 2), (len(_ScoreEngine.plans), len(_ScoreEngine.renders)))

    # ── « auto » ────────────────────────────────────────────────────────────────────────────
    def test_auto_stays_auto_and_each_line_names_the_drawn_model(self):
        gen = self._run(self._generation(model=AUTO))
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual(AUTO, gen.model)
        gen.draw.assert_called_once()
        self.assertEqual({SCORE_MODEL},
                         {row.model_key for row in process_runs.lines(gen)})

    def test_a_render_replayed_alone_uses_the_model_that_wrote_the_score(self):
        """Under « auto » a relaunch draws again — except when it resumes from a score: another
        draw would hand the score of one model to a model that may not follow it."""
        _ScoreEngine.error = RuntimeError('engine down')
        gen = self._run(self._generation(model=AUTO))
        _ScoreEngine.error = None
        gen = self._run(gen, drawn=PLAIN_MODEL)
        gen.draw.assert_not_called()
        self.assertEqual('SUCCESS', gen.status, gen.error_message)
        self.assertEqual([], _PlainEngine.renders)
        self.assertEqual(SCORE_MODEL, process_runs.line(gen, 'render').model_key)

    def test_a_full_relaunch_under_auto_draws_again(self):
        """Counter-test: nothing is resumed, so the draw is the draw of the moment."""
        gen = self._run(self._generation(model=AUTO))
        gen = self._run(gen, drawn=PLAIN_MODEL)
        gen.draw.assert_called_once()
        self.assertEqual(1, len(_PlainEngine.renders))

    # ── around the card ─────────────────────────────────────────────────────────────────────
    def test_a_copy_of_the_card_does_not_carry_the_score_of_the_original(self):
        from wama.common.utils.queue_duplication import duplicate_instance
        gen = self._run(self._generation())
        copy = duplicate_instance(gen, for_user=self.user, reset_fields={'status': 'PENDING'},
                                  clear_fields=['audio_output', 'planned_score'])
        self.assertFalse(copy.planned_score)
        self.assertFalse(process_runs.lines(copy).exists(), 'a copy starts with no line')
        with mock.patch('wama.common.backends.manager.backend_for_key',
                        side_effect=lambda key: ENGINES.get(key)):
            self.assertEqual(['plan', 'render'],
                             [spec.key for spec in PIPELINE.steps_to_run(copy, SCORE_MODEL)])

    def test_removing_the_card_frees_the_score_like_its_audio(self):
        from wama.common.services.released_files import freed_by
        gen = self._run(self._generation())
        self.assertIn(gen.planned_score.name, [str(name) for name in freed_by([gen])])


class TheCardAndTheGraphicsCardTest(TestCase):
    """What the first REAL YuE2 generation showed on 2026-10-02 (element #281): the composer
    told the skeleton nothing about its need, so it started on a full card and ran out of memory ;
    and nobody released its engine, so the NEXT task of the worker ran out of memory too."""

    setUp = PlanThenRenderTest.setUp
    _generation = PlanThenRenderTest._generation
    _run = PlanThenRenderTest._run

    def test_the_engine_is_released_after_a_success(self):
        self._run(self._generation())
        self.assertEqual((1, 1), (_ScoreEngine.built, _ScoreEngine.unloaded))
        self.assertEqual({}, tasks._OPEN_BACKENDS)

    def test_the_engine_is_released_after_a_failure(self):
        _ScoreEngine.error = RuntimeError('CUDA out of memory')
        gen = self._run(self._generation())
        self.assertEqual('FAILURE', gen.status)
        self.assertEqual(1, _ScoreEngine.unloaded, 'a failed launch left its engine in the worker')
        self.assertEqual({}, tasks._OPEN_BACKENDS)

    def test_an_engine_that_cannot_unload_is_told_and_does_not_break_the_task(self):
        with mock.patch.object(_ScoreEngine, 'unload', side_effect=RuntimeError('stuck')), \
                self.assertLogs('wama.composer.tasks', level='WARNING'):
            gen = self._run(self._generation())
        self.assertEqual('SUCCESS', gen.status, gen.error_message)

    def test_the_need_is_the_one_of_the_model_of_this_launch(self):
        gen = self._generation(model=AUTO)
        with mock.patch('wama.composer.utils.auto_model.resolve_auto_model',
                        return_value=SCORE_MODEL), \
                mock.patch('wama.common.utils.auto_model.vram_needed_gb',
                           return_value=7.3) as need:
            self.assertEqual(7.3, tasks._vram_needed(gen))
        need.assert_called_once_with(SCORE_MODEL)

    def test_a_card_that_does_not_fit_now_waits_instead_of_starting(self):
        gen = self._generation()
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.backends.manager.backend_for_key',
                           side_effect=lambda key: ENGINES.get(key)), \
                mock.patch('wama.common.utils.auto_model.vram_needed_gb', return_value=7.3), \
                mock.patch('wama.common.services.resource_governor.effective_free_gb',
                           return_value=2.0), \
                mock.patch('wama.common.services.resource_governor.fits_alone',
                           return_value=True), \
                mock.patch('wama.common.services.resource_governor.release_granted',
                           return_value=None), \
                mock.patch('wama.common.services.resource_governor.holders_summary',
                           return_value='un modele de transcription'):
            with self.assertRaises(_Deferred):
                tasks.compose_task.run.__func__(_deferring_task(), gen.pk)
        gen.refresh_from_db()
        self.assertEqual('AWAITING_RESOURCES', gen.status)
        self.assertEqual((0, []), (_ScoreEngine.built, _ScoreEngine.plans),
                         'the engine was loaded although the card had no room')
        self.assertFalse(process_runs.lines(gen).exists(),
                         'the wait of a pipeline card is carried by the element, not by a line')


class ThePipelineIsInTheCatalogueTest(SimpleTestCase):
    """Decision n°11: written like the cam_analyzer's — and exported like it."""

    def test_each_process_is_a_function_of_the_catalogue_bound_to_the_app(self):
        from wama.common.catalog import function_catalog as fc
        for spec in PIPELINE.specs:
            declared = fc.get(PIPELINE.function_key(spec))
            self.assertIsNotNone(declared, spec.key)
            self.assertEqual((fc.Binding.APP, 'composer'), (declared.binding, declared.app))

    def test_the_pipeline_is_extracted_as_a_valid_manifest_of_the_media_world(self):
        from wama.common.manifests.ingest import extract, validate
        manifest = extract('pipeline', 'composer')
        self.assertIsNotNone(manifest, 'the registry is not a pipeline source')
        self.assertEqual([], validate(manifest))
        self.assertEqual('media', manifest['world'])
        self.assertEqual([('plan', 'composer.plan'), ('render', 'composer.render')],
                         [(node['id'], node['function']) for node in manifest['body']['nodes']])
        self.assertEqual([{'from': 'plan', 'to': 'render', 'to_port': None}],
                         manifest['body']['links'])

    def test_the_export_command_lists_it(self):
        from wama.common.management.commands.manifest_export import _pipeline_keys
        self.assertIn('composer', _pipeline_keys())

    def test_the_task_has_a_glue_for_every_process(self):
        self.assertEqual({'plan', 'render'}, {spec.key for spec in PIPELINE.specs})
        for spec in PIPELINE.specs:
            self.assertTrue(callable(getattr(tasks, f'_{spec.key}')), spec.key)


class _Planned:
    def __init__(self, abc):
        self.abc = abc


class _Song:
    audio, sample_rate = [0.0], 48000

    def save(self, path):
        Path(path).write_bytes(b'RIFF')
        return path


class _VendoredPipeline:
    """Stand-in of `yue2.pipeline.YuE2Pipeline`: `plan()` and the call that takes `abc=`."""

    def __init__(self):
        self.planned, self.called = [], []

    def plan(self, **kwargs):
        self.planned.append(kwargs)
        return _Planned(SCORE)

    def __call__(self, **kwargs):
        self.called.append(kwargs)
        return _Song()


class TheEngineSaysItPlansTest(SimpleTestCase):
    """The REAL backend class, over a stand-in of its vendored pipeline."""

    def _backend(self):
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        backend = YuE2Backend()
        backend._pipeline, backend._warm = _VendoredPipeline(), True
        return backend

    def test_yue2_says_it_and_the_other_music_engines_do_not(self):
        from wama.common.backends.base import BaseModelBackend
        from wama.common.backends.music_generation_base import MusicGenerationBackend
        from wama.common.backends.yue2_3b_backend import YuE2Backend
        from wama.common.utils.model_capabilities import declared_engine_flag
        self.assertTrue(declared_engine_flag(YuE2Backend, 'supports_score_planning'))
        self.assertFalse(BaseModelBackend.supports_score_planning)
        self.assertFalse(MusicGenerationBackend.supports_score_planning)

    def test_the_flag_is_in_the_common_vocabulary(self):
        from wama.common.utils import model_capabilities
        self.assertIn('supports_score_planning', model_capabilities.CANONICAL_CAPABILITIES)

    def test_the_score_comes_from_the_plan_step_of_the_vendored_pipeline(self):
        backend = self._backend()
        text = backend.plan_score(model_id='YuE2-3B', prompt='a calm piano\n[verse]\nla la')
        self.assertEqual(SCORE, text)
        asked = backend._pipeline.planned[0]
        self.assertEqual(('a calm piano', '[verse]\nla la', 'full', backend.SEED),
                         (asked['style'], asked['lyrics'], asked['cot'], asked['seed']))
        self.assertEqual([], backend._pipeline.called, 'planning must not render')

    def test_the_render_hands_the_planned_score_back_to_the_pipeline(self):
        with tempfile.TemporaryDirectory() as folder:
            score = Path(folder) / 'score.abc'
            score.write_text(SCORE, encoding='utf-8')
            backend = self._backend()
            backend.generate(model_id='YuE2-3B', prompt='a calm piano\n[verse]\nla la',
                             duration=30, output_path=str(Path(folder) / 'out.wav'),
                             score_path=str(score))
            given = backend._pipeline.called[0]
            self.assertEqual((SCORE, backend.SEED), (given['abc'], given['seed']))
            self.assertEqual([], backend._pipeline.planned)

    def test_unloading_closes_the_pipeline_and_gives_the_process_its_cap_back(self):
        """The vendored pipeline lowers the cap of the PROCESS when it is built ; unloading must
        hand back the governor's cap, not 1.0 — without it an allocation beyond the card spills
        into host RAM under WSL2 instead of failing."""
        import torch
        from wama.common.services.resource_governor import ALLOCATOR_CAP_FRACTION
        backend = self._backend()
        pipeline = backend._pipeline
        pipeline.closed = 0

        def close():
            pipeline.closed += 1
        pipeline.close = close
        with mock.patch.object(torch.cuda, 'is_available', return_value=True), \
                mock.patch.object(torch.cuda, 'set_per_process_memory_fraction') as cap, \
                mock.patch.object(torch.cuda, 'empty_cache') as emptied:
            backend.unload()
        self.assertEqual(1, pipeline.closed)
        self.assertFalse(backend.is_loaded)
        self.assertIsNone(backend._pipeline)
        cap.assert_called_once_with(ALLOCATOR_CAP_FRACTION)
        emptied.assert_called_once()

    def test_an_engine_that_does_not_plan_says_so(self):
        from wama.common.backends.music_generation_base import MusicGenerationBackend
        with self.assertRaisesMessage(NotImplementedError, 'supports_score_planning'):
            MusicGenerationBackend.plan_score(mock.Mock(), 'm', 'a prompt')
