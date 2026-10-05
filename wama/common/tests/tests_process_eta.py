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
