"""The ETA of a card that carries SEVERAL processes — `WAMA_APP_GENERATION_ROUTE §10.6` point 4.5.

What is held here, and why each point:

  * a launch writes its PLAN on the lines (the processes it will play turn `PENDING` and carry its
    task) before the first one starts — it is what says, while it runs, what THIS launch plays : a
    ▶ bounded to one process only plays a part of the card ;
  * the estimate of a card is the SUM of the processes its launch plays, each by the rule the
    cam_analyzer held for its passes (`row_eta_seconds`: its last duration on this element, scaled,
    then what was learned) and then the a priori of the common estimator — none for a PROCESS key ;
  * a process already rendered during the launch counts its MEASURED duration ;
  * the size a line was measured on is kept, from the glue's ETA or from the declared one ;
  * every process of every app pipeline declares its ETA in its app's task module, the triplet its
    glue learns — one place, read by the estimate and by the learning.
"""
import ast
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.models import JOB_PENDING, JOB_RUNNING, JOB_SUCCESS
from wama.common.services import process_runs
from wama.common.services.process_pipeline import APP_PIPELINES, AppPipeline, ProcessSpec
from wama.common.tests.tests_process_pipeline import _Element
from wama.common.tests.tests_queue_delete_contract import _instance
from wama.common.tests.tests_task_skeleton_contract import _adopters, _task


def _learned(table):
    """A stand-in for `eta_estimator.estimate`: `table[key]` when learned ; otherwise the app's
    a priori when one is given, else the domain a priori (`prior:<key>`, 100 s)."""
    def estimate(key, size=1.0, unit='item', model_loaded=False, fallback_seconds=None):
        if key in table:
            return table[key] * size
        if fallback_seconds is not None:
            return fallback_seconds
        return 100.0
    return estimate


def _three_steps():
    return AppPipeline('demo_pipeline', (
        ProcessSpec('plan', eta=lambda item: ('demo:plan', 1.0, 'item', True, 0.0)),
        ProcessSpec('render', depends_on=('plan',), watched=('duration',),
                    eta=lambda item: ('demo:render', float(item.duration), 'audio_sec')),
        ProcessSpec('output', depends_on=('render',)),
    ), label='Demo')


class OneProcessEstimateTest(TestCase):
    """`step_eta_seconds` — the rule of the cam_analyzer passes, then the estimator's a priori."""

    def setUp(self):
        self.pipeline, self.item = _three_steps(), _Element(duration=30)
        patch = mock.patch('wama.model_manager.services.eta_estimator.estimate',
                           _learned({'demo:render': 2.0}))
        patch.start()
        self.addCleanup(patch.stop)

    def _estimate(self, key):
        return process_runs.step_eta_seconds(self.pipeline.spec(key), self.item,
                                             process_runs.line(self.item, key))

    def test_without_any_run_a_model_process_reads_what_was_learned(self):
        self.assertEqual(60.0, self._estimate('render'))

    def test_the_last_duration_on_this_element_prevails_scaled_to_the_new_size(self):
        process_runs.start(self.item, 'render')
        process_runs.succeed(self.item, 'render',
                             output_summary={process_runs.ETA_SIZE_KEY: 30.0})
        process_runs.lines(self.item).filter(node_id='render').update(duration_s=12.0)
        self.item.duration = 60
        self.assertEqual(24.0, self._estimate('render'))

    def test_a_process_key_has_no_domain_a_priori(self):
        """`plan` declares `0.0` as its a priori : nothing learned, nothing estimated."""
        self.assertIsNone(self._estimate('plan'))

    def test_a_model_key_falls_back_on_the_estimator_a_priori(self):
        self.pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('render', eta=lambda item: ('demo:never', 1.0, 'item')),), label='Demo')
        self.assertEqual(100.0, self._estimate('render'))

    def test_a_process_without_a_declared_eta_is_worth_its_last_duration(self):
        self.assertIsNone(self._estimate('output'))
        process_runs.start(self.item, 'output')
        process_runs.succeed(self.item, 'output')
        process_runs.lines(self.item).filter(node_id='output').update(duration_s=3.0)
        self.assertEqual(3.0, self._estimate('output'))

    def test_an_unreadable_declaration_estimates_nothing_and_raises_nothing(self):
        def broken(item):
            raise AttributeError('no such field')
        self.pipeline = AppPipeline('demo_pipeline', (ProcessSpec('render', eta=broken),),
                                    label='Demo')
        self.assertIsNone(process_runs.process_eta(self.pipeline.spec('render'), self.item))


class LaunchEstimateTest(TestCase):
    """`launch_eta` — the sum of what the launch plays."""

    def setUp(self):
        self.pipeline = _three_steps()
        for patch in (mock.patch.dict(APP_PIPELINES, {'demo_pipeline': self.pipeline}),
                      mock.patch('wama.model_manager.services.eta_estimator.estimate',
                                 _learned({'demo:plan': 5.0, 'demo:render': 2.0}))):
            patch.start()
            self.addCleanup(patch.stop)

    def _done(self, item, key, seconds, task_id=''):
        process_runs.start(item, key, task_id=task_id)
        process_runs.succeed(item, key)
        process_runs.lines(item).filter(node_id=key).update(duration_s=seconds)

    def test_a_card_that_never_ran_is_estimated_at_the_sum_of_its_processes(self):
        self.assertEqual(5.0 + 60.0, process_runs.launch_eta(_Element(duration=30)))

    def test_a_relaunch_only_counts_what_it_will_replay_each_at_its_last_duration(self):
        """`plan` is valid, the render is stale (its duration changed) and the output after it :
        the render scaled to the new duration, the output at its last one — `plan` not at all."""
        item = _Element(duration=30)
        for key in ('plan', 'render', 'output'):
            process_runs.start(item, key, settings_snapshot=self.pipeline.snapshot(
                self.pipeline.spec(key), item))
            process_runs.succeed(item, key, output_summary={process_runs.ETA_SIZE_KEY: 30.0})
        process_runs.lines(item).filter(node_id='render').update(duration_s=12.0)
        process_runs.lines(item).filter(node_id='output').update(duration_s=1.0)
        item.duration = 60
        self.assertEqual(['render', 'output'],
                         [spec.key for spec in self.pipeline.steps_to_run(item)])
        self.assertEqual(24.0 + 1.0, process_runs.launch_eta(item))

    def test_during_the_launch_the_planned_lines_are_summed_and_a_done_one_counts_its_duration(
            self):
        item = _Element(duration=30, status=JOB_RUNNING, task_id='launch-1')
        process_runs.plan(item, [('plan', 'demo.plan', 'function'),
                                 ('render', 'demo.render', 'function')], task_id='launch-1')
        self._done(item, 'plan', 7.0, task_id='launch-1')
        process_runs.start(item, 'render', task_id='launch-1')
        self.assertEqual(7.0 + 60.0, process_runs.launch_eta(item))

    def test_a_launch_bounded_to_one_process_is_estimated_at_that_process(self):
        """The ▶ of `render` : the lines of this task say what is played — not the whole card."""
        item = _Element(duration=30, status=JOB_RUNNING, task_id='launch-2')
        self._done(item, 'plan', 7.0, task_id='an-older-launch')
        process_runs.plan(item, [('render', 'demo.render', 'function')], task_id='launch-2')
        self.assertEqual(60.0, process_runs.launch_eta(item))

    def test_an_app_whose_processes_name_no_eta_keeps_its_own_estimate(self):
        APP_PIPELINES['demo_pipeline'] = AppPipeline(
            'demo_pipeline', (ProcessSpec('render'),), label='Demo')
        self.assertIsNone(process_runs.launch_eta(_Element(duration=30)))


class SkeletonPlansTheLaunchTest(TestCase):
    """The skeleton writes the plan, and keeps the size each line was measured on."""

    def setUp(self):
        self.app, self.model = _adopters()[0]
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'),
            ProcessSpec('render', depends_on=('plan',),
                        eta=lambda item: ('demo:render', 42.0, 'audio_sec')),
        ), label='Demo')

    def _run(self, **glues):
        from wama.common.utils.task_skeleton import run_item_task
        user = get_user_model().objects.create_user(f'eta_plan_{len(glues)}', password='x')
        item = _instance(self.model, user)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        processes = {'plan': glues.get('plan') or (lambda e, c: {}),
                     'render': glues.get('render') or (lambda e, c: {})}
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes=processes)
        return item

    def test_the_processes_of_the_launch_are_pending_with_its_task_before_the_first_one_runs(self):
        seen = {}

        def plan(element, ctx):
            row = process_runs.line(element, 'render')
            seen['render'] = (row.status, row.task_id) if row else None
            return {}
        self._run(plan=plan)
        self.assertEqual((JOB_PENDING, _task().request.id), seen['render'])

    def test_a_line_keeps_the_size_of_the_glue_eta_else_the_declared_one(self):
        item = self._run(plan=lambda e, c: {'eta': ('demo:plan', 3.0, 'item')})
        self.assertEqual(3.0, process_runs.line(item, 'plan').output_summary[
            process_runs.ETA_SIZE_KEY])
        self.assertEqual(42.0, process_runs.line(item, 'render').output_summary[
            process_runs.ETA_SIZE_KEY])
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'render').status)

    def test_the_glue_may_return_the_declared_form_with_its_loaded_flag(self):
        with mock.patch('wama.model_manager.services.eta_estimator.record_run') as record:
            self._run(plan=lambda e, c: {'eta': ('demo:plan', 3.0, 'item', False, 0.0)})
        self.assertEqual(('demo:plan',), record.call_args_list[0].args)
        self.assertEqual(3.0, record.call_args_list[0].kwargs['size'])


class AppliesIsAskedOncePerReadTest(TestCase):
    """`applies` of the composer and the transcriber resolves the backend of the model — 0.56 s a
    call on this host. The process strip, the launch ETA and the card each asked it : the composer
    page went from 7.5 s to 15 s for 10 cards (2026-10-05). Within a `preload` window the answer is
    kept per (process, model) ; outside it (the task) it is asked again every time."""

    def setUp(self):
        self.calls = []

        def applies(item, model_key):
            self.calls.append(model_key)
            return True
        self.pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('render', applies=applies,
                        eta=lambda item: ('demo:render', 1.0, 'item')),
        ), label='Demo', model_of=lambda item: 'model-a')
        self.spec = self.pipeline.spec('render')

    def test_within_a_read_window_the_answer_is_kept_per_model(self):
        from wama.common.services.process_pipeline import preload
        item = _Element()
        preload([item])
        for _ in range(3):
            self.pipeline.takes_place(self.spec, item, 'model-a')
        self.pipeline.takes_place(self.spec, item, 'model-b')
        self.assertEqual(['model-a', 'model-b'], self.calls)

    def test_outside_the_window_and_after_release_it_is_asked_again(self):
        from wama.common.services.process_pipeline import preload, release
        item = _Element()
        self.pipeline.takes_place(self.spec, item, 'model-a')
        self.pipeline.takes_place(self.spec, item, 'model-a')
        preload([item])
        self.pipeline.takes_place(self.spec, item, 'model-a')
        release(item)
        self.pipeline.takes_place(self.spec, item, 'model-a')
        self.assertEqual(4, len(self.calls))

    def test_the_progress_view_reads_once_for_the_eta_and_the_strip(self):
        """One window in the progress view : the launch ETA and the process strip share it."""
        from wama.common.services.process_pipeline import card_view, preload, release
        item = _Element(duration=30)
        with mock.patch.dict(APP_PIPELINES, {'demo_pipeline': self.pipeline}), \
                mock.patch('wama.model_manager.services.eta_estimator.estimate',
                           _learned({'demo:render': 3.0})):
            preload([item])
            try:
                self.assertEqual(3.0, process_runs.launch_eta(item))
                card_view(item, preloaded=True)
            finally:
                release(item)
        self.assertEqual(['model-a'], self.calls, 'asked once for the ETA and the strip')


class TheProgressViewReadsInOneWindowTest(TestCase):
    """The REAL progress view (the factory, on the composer's model) : the launch ETA and the
    process strip ask `applies` once per request — what made each poll pay the backend
    resolution twice."""

    def test_one_progress_request_asks_applies_once(self):
        from django.test import RequestFactory
        from wama.common.utils.progress_views import make_progress_views
        from wama.composer.models import ComposerGeneration
        calls = []

        def applies(item, model_key):
            calls.append(model_key)
            return True
        pipeline = AppPipeline('composer', (
            ProcessSpec('render', applies=applies, eta=lambda item: ('demo:render', 1.0, 'item')),
        ), label='Demo', model_of=lambda item: 'model-a')
        user = get_user_model().objects.create_user('eta_one_window', password='x')
        gen = ComposerGeneration.objects.create(user=user, prompt='calm piano', duration=30,
                                                status='RUNNING')
        view = make_progress_views(work_model=ComposerGeneration, app_id='composer',
                                   get_user=lambda r: r.user)['progress']
        request = RequestFactory().get('/x/')
        request.user = user
        with mock.patch.dict(APP_PIPELINES, {'composer': pipeline}), \
                mock.patch('wama.model_manager.services.eta_estimator.estimate',
                           _learned({'demo:render': 3.0})):
            data = __import__('json').loads(view(request, gen.pk).content)
        self.assertEqual(3.0, data['estimated_seconds'])
        self.assertEqual(['model-a'], calls)


class ProcessKeysAreLearnedOnlyTest(TestCase):
    """A PROCESS key (`<app>:<process>…`, or a model key suffixed by the process) has no domain a
    priori — the estimator's describe MODELS (6 s per produced second of video : wrong by an order
    of magnitude for a blur). Each such declaration says `0.0` ; a MODEL key keeps the estimator's
    a priori (or the app's own, the composer catalogue's)."""

    def _eta(self, path, item):
        return process_runs.process_eta(ProcessSpec('x', eta=path), item)

    def test_every_process_key_declares_no_a_priori(self):
        from types import SimpleNamespace as NS
        media = NS(media_type='video', file_ext='mp4', duration_inSec=10.0, width=0, height=0)
        gen = NS(model='composer:musicgen-small', duration=30.0)
        transcript = NS(duration_seconds=60.0, diarization_model='community-1',
                        summary_type='meeting')
        cases = [('anonymizer.tasks:blur_eta', media, 'anonymizer:blur:'),
                 ('composer.tasks:plan_eta', gen, ':plan'),
                 ('composer.tasks:extract_score_eta', gen, 'composer:extract_score'),
                 ('transcriber.workers:align_eta', transcript, 'transcriber:align'),
                 ('transcriber.workers:diarize_eta', transcript, 'transcriber:diarize'),
                 ('transcriber.workers:summarize_eta', transcript, 'transcriber:summarize'),
                 ('transcriber.workers:coherence_eta', transcript, 'transcriber:coherence')]
        for path, item, marker in cases:
            with self.subTest(declaration=path):
                key, _size, _unit, _loaded, prior = self._eta(path, item)
                self.assertIn(marker, key)
                self.assertEqual(0.0, prior)

    def test_the_composer_render_keeps_the_catalogue_a_priori(self):
        from types import SimpleNamespace as NS
        from wama.composer.utils.model_config import estimate_seconds
        key, size, _unit, loaded, prior = self._eta(
            'composer.tasks:render_eta', NS(model='composer:musicgen-small', duration=30.0))
        self.assertEqual((False, estimate_seconds('musicgen-small', 30.0)), (loaded, prior))
        self.assertGreater(prior, 0)


class OneTripletPerFamilyTest(TestCase):
    """The shared triplets : the synthesizer and the voice of the avatarizer learn under the
    common TTS key ; the enhancer's one pipeline estimates each queue by its own triplet."""

    def test_the_synthesizer_learns_under_the_common_tts_key(self):
        from types import SimpleNamespace as NS
        from wama.common.tts.service_client import tts_eta_key_size
        from wama.synthesizer.workers import synthesizer_eta_key_size
        synthesis = NS(text_content='Bonjour à tous.', tts_model='synthesizer:kokoro')
        self.assertEqual(tts_eta_key_size('Bonjour à tous.', 'synthesizer:kokoro'),
                         synthesizer_eta_key_size(synthesis))
        self.assertIsNone(tts_eta_key_size('', 'synthesizer:kokoro'), 'no text, no estimate')

    def test_the_enhancer_estimates_each_queue_by_its_own_triplet(self):
        from wama.enhancer.models import AudioEnhancement, Enhancement
        from wama.enhancer.tasks import generate_eta_key_size
        self.assertTrue(generate_eta_key_size(AudioEnhancement())[0].startswith('enhancer:audio:'))
        self.assertTrue(generate_eta_key_size(Enhancement())[0].startswith('enhancer:img:'))

    def test_a_glue_that_learns_the_load_apart_declares_its_model_not_loaded(self):
        """The imager and the transcriber measure the cold load apart and learn it : their
        declaration says « model not loaded », the load counts at the start (the old views did)."""
        from types import SimpleNamespace as NS
        from wama.imager.models import ImageGeneration
        imager = process_runs.process_eta(ProcessSpec('generate', eta='imager.tasks:generate_eta'),
                                          ImageGeneration(model='auto', steps=20, num_images=2))
        transcript = NS(used_backend='whisper', backend='whisper', duration_seconds=60.0)
        transcriber = process_runs.process_eta(
            ProcessSpec('transcribe', eta='transcriber.workers:transcribe_eta'), transcript)
        self.assertEqual(('imager:img:auto', 40, 'step', False),
                         (imager[0], imager[1], imager[2], imager[3]))
        self.assertEqual((60.0, 'audio_sec', False), transcriber[1:4])

    def test_the_composer_card_shows_the_launch_estimate_else_the_catalogue_one(self):
        from wama.composer.models import ComposerGeneration
        from wama.composer.utils.model_config import estimate_seconds
        user = get_user_model().objects.create_user('eta_composer_card', password='x')
        gen = ComposerGeneration.objects.create(user=user, prompt='calm piano', duration=30,
                                                model='composer:musicgen-small')
        with mock.patch('wama.common.services.process_runs.launch_eta', return_value=42.4):
            self.assertEqual(42, ComposerGeneration.objects.get(pk=gen.pk).estimated_seconds)
        with mock.patch('wama.common.services.process_runs.launch_eta', return_value=None):
            self.assertEqual(estimate_seconds('musicgen-small', 30),
                             ComposerGeneration.objects.get(pk=gen.pk).estimated_seconds)


class EtaSeededCriterionReadsTheDeclaredFormTest(SimpleTestCase):
    """The `eta_seeded` criterion knew two forms (`estimate(` in the views, `eta_for=` at the
    factory) : with the per-process ETA, the seven pipeline apps have neither — it would have
    turned them partial and pushed them back to the old form (2026-10-05)."""

    def test_a_pipeline_app_is_seen_through_its_declared_process_eta(self):
        from wama.common.services import conformity_checker as cc
        state, proof = cc._eta_seeded(cc._AppFiles('anonymizer'))
        self.assertIs(True, state)
        self.assertIn('function_specs.py', proof)

    def test_a_single_process_app_is_still_seen_through_its_view_hook(self):
        """Counter-proof : the converter keeps `eta_for=` and stays green by it."""
        from wama.common.services import conformity_checker as cc
        state, proof = cc._eta_seeded(cc._AppFiles('converter'))
        self.assertIs(True, state)
        self.assertIn('views.py', proof)


def _app_dir(app) -> Path:
    for root in ('wama', 'wama_lab', 'wama_data'):
        candidate = Path(settings.BASE_DIR) / root / app
        if candidate.is_dir():
            return candidate
    return Path(settings.BASE_DIR) / 'wama' / app


def _real_pipelines():
    """The pipelines of the REAL apps — a sandbox twin is generated, it carries what its source
    declares (the rule of `tests_task_skeleton_contract._adopters`)."""
    from wama.common.app_registry import APP_CATALOG
    return {app: pipeline for app, pipeline in APP_PIPELINES.items()
            if app in APP_CATALOG and not (APP_CATALOG[app] or {}).get('sandbox')}


class EveryAppProcessNamesItsEtaTest(SimpleTestCase):
    """Held for every app pipeline at once, without a test per app."""

    #: Processes that have NO estimate of their own, with the reason — their last duration on the
    #: card is what they weigh. `output` : the common output process, whose cost depends on files
    #: the engine has not written yet when the card is estimated.
    WITHOUT_ETA = {'output': "process de sortie commun : la taille de l'entrée n'existe pas avant "
                             "le moteur",
                   'transcriber.import': "relit un document — quelques secondes"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.catalog import function_catalog
        function_catalog.load_all()

    def test_every_process_names_an_eta_in_the_task_module_of_its_app(self):
        from wama.common.catalog.function_catalog import resolve_impl
        self.assertTrue(_real_pipelines())
        for app, pipeline in _real_pipelines().items():
            for spec in pipeline.specs:
                with self.subTest(process=f'{app}.{spec.key}'):
                    if spec.key in self.WITHOUT_ETA or f'{app}.{spec.key}' in self.WITHOUT_ETA:
                        self.assertFalse(spec.eta, 'exempted, yet declared : drop the exemption')
                        continue
                    self.assertIsInstance(spec.eta, str, 'a `module:attr` path, exported as is')
                    module = spec.eta.split(':', 1)[0]
                    self.assertRegex(module, rf'^{app}\.(tasks|workers)$')
                    self.assertTrue(callable(resolve_impl(spec.eta)))

    def test_a_pipeline_app_estimates_by_its_processes_not_by_a_view_triplet(self):
        for app, pipeline in _real_pipelines().items():
            if not any(spec.eta for spec in pipeline.specs):
                continue
            with self.subTest(app=app):
                src = (_app_dir(app) / 'views.py').read_text(encoding='utf-8')
                calls = [node for node in ast.walk(ast.parse(src)) if isinstance(node, ast.Call)
                         and getattr(node.func, 'id', '') == 'make_progress_views']
                self.assertTrue(calls)
                for call in calls:
                    self.assertFalse({'eta_for', 'eta_fallback'} & {kw.arg for kw in call.keywords},
                                     'two estimates for one card')

    def test_no_glue_writes_an_eta_key_by_hand(self):
        """A literal `(key, size, unit)` in a glue is a SECOND place for the triplet : the
        avatarizer learned `avatarizer:codeformer` from a literal while its view estimated under
        `avatarizer:quality`, which nothing learned (2026-10-05)."""
        for app in _real_pipelines():
            for name in ('tasks.py', 'workers.py'):
                path = _app_dir(app) / name
                if not path.exists():
                    continue
                for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
                    literal = None
                    if isinstance(node, ast.Dict):
                        literal = next((v for k, v in zip(node.keys, node.values)
                                        if isinstance(k, ast.Constant) and k.value == 'eta'), None)
                    elif isinstance(node, ast.keyword) and node.arg == 'eta':
                        literal = node.value
                    elif isinstance(node, ast.Assign) and any(
                            isinstance(t, ast.Subscript) and isinstance(t.slice, ast.Constant)
                            and t.slice.value == 'eta' for t in node.targets):
                        literal = node.value
                    with self.subTest(file=f'{app}/{name}', line=getattr(node, 'lineno', 0)):
                        self.assertNotIsInstance(literal, ast.Tuple)
