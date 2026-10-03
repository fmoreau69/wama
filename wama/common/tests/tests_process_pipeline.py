"""A card that carries SEVERAL processes — `WAMA_APP_GENERATION_ROUTE §10.6`, step P3 stage B.

What is held here, and why each point:

  * an app writes its processes down the way the cam_analyzer writes its passes (a registry in
    code that becomes a `pipeline` manifest with `function` nodes) — the form is the one the
    studio already opens, so nothing new has to learn to read it ;
  * a launch replays ONLY what is no longer valid, plus everything downstream of it — that is
    the whole point of several processes: a setting of the last one must not replay the first ;
  * « no longer valid » has the three causes of point 4.3: a watched setting changed, the output
    of an upstream process was replaced, an upstream process is itself stale ;
  * a card whose processes are all valid, relaunched, replays everything — the user asks for
    another result — even though the launcher already removed the previous output ;
  * the task skeleton runs the retained processes one after the other in ONE task and keeps one
    execution line per process ; a failure closes the line of the process that failed and leaves
    the ones before it valid.
"""
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.models import JOB_FAILURE, JOB_PENDING, JOB_RUNNING, JOB_STALE, JOB_SUCCESS
from wama.common.services import process_runs
from wama.common.services.process_pipeline import (APP_PIPELINES, UPSTREAM_KEY, AppPipeline,
                                                   ProcessSpec, register_app_pipeline)
from wama.common.tests.tests_queue_delete_contract import _instance
from wama.common.tests.tests_task_skeleton_contract import _adopters, _task


class _Element:
    """Stand-in element: the lines address it by (app, type, pk) and read its settings."""

    class _meta:
        app_label = 'demo_pipeline'
        object_name = 'Element'

    _next = 0

    def __init__(self, **settings):
        type(self)._next += 1
        self.pk = type(self)._next
        self.prompt, self.duration, self.given_score = 'a calm piano', 30, ''
        self.__dict__.update(settings)


def _two_steps(**plan_options):
    return AppPipeline('demo_pipeline', (
        ProcessSpec('plan', watched=('prompt',), **plan_options),
        ProcessSpec('render', depends_on=('plan',), watched=('prompt', 'duration'), share=3),
    ), label='Demo')


def _keys(steps):
    return [spec.key for spec in steps]


class WritingAPipelineDownTest(SimpleTestCase):

    def test_an_upstream_that_is_not_in_the_pipeline_is_refused(self):
        with self.assertRaisesMessage(ValueError, 'master'):
            AppPipeline('demo', (ProcessSpec('render', depends_on=('master',)),), label='x')

    def test_a_key_written_twice_is_refused(self):
        with self.assertRaises(ValueError):
            AppPipeline('demo', (ProcessSpec('render'), ProcessSpec('render')), label='x')

    def test_a_cycle_is_refused_when_the_pipeline_is_written_not_when_it_runs(self):
        with self.assertRaisesMessage(ValueError, 'cycle'):
            AppPipeline('demo', (ProcessSpec('a', depends_on=('b',)),
                                 ProcessSpec('b', depends_on=('a',))), label='x')

    def test_an_unknown_degree_is_refused(self):
        with self.assertRaises(ValueError):
            AppPipeline('demo', (ProcessSpec('render', degree='sometimes'),), label='x')

    def test_the_order_is_the_order_of_the_graph_whatever_the_writing_order(self):
        pipeline = AppPipeline('demo', (ProcessSpec('render', depends_on=('plan',)),
                                        ProcessSpec('plan')), label='x')
        self.assertEqual(['plan', 'render'], _keys(pipeline.ordered()))
        self.assertEqual(['render'], _keys(pipeline.ordered({'render'})))

    def test_the_graph_is_the_canvas_form_and_makes_a_valid_manifest_body(self):
        """Same form as the cam_analyzer registry: a process = a `function` node, a dependency =
        a link. That is what lets the studio open the pipeline of an app."""
        from wama.common.manifests.builtin.pipeline import (body_to_graph, graph_to_body,
                                                            validate_pipeline_body)
        pipeline = _two_steps()
        graph = pipeline.graph()
        self.assertEqual(['function:demo_pipeline.plan', 'function:demo_pipeline.render'],
                         [node['app'] for node in graph['nodes']])
        self.assertEqual([{'from': 'plan', 'to': 'render', 'to_port': None}], graph['links'])
        self.assertEqual(['prompt', 'duration'], graph['nodes'][1]['params']['watched'])
        body = graph_to_body(graph)
        self.assertEqual([], validate_pipeline_body(body))
        self.assertEqual(['demo_pipeline.plan', 'demo_pipeline.render'],
                         [node['function'] for node in body['nodes']])
        self.assertEqual(['plan', 'render'], [n['id'] for n in body_to_graph(body)['nodes']])

    def test_a_function_key_can_be_named_when_it_is_not_the_default_one(self):
        pipeline = AppPipeline('demo', (ProcessSpec('render', function='demo.rendering'),),
                               label='x')
        self.assertEqual('demo.rendering', pipeline.function_key(pipeline.spec('render')))

    def test_registering_makes_the_pipeline_a_manifest_source_under_the_app_key(self):
        from wama.common.manifests.builtin.pipeline import PIPELINE_SOURCES
        self.addCleanup(APP_PIPELINES.pop, 'demo_registered', None)
        self.addCleanup(PIPELINE_SOURCES.pop, 'demo_registered', None)
        pipeline = register_app_pipeline('demo_registered', (ProcessSpec('render'),), label='Demo')
        self.assertIs(APP_PIPELINES['demo_registered'], pipeline)
        with mock.patch('wama.common.app_registry.app_world', return_value='media'):
            manifest = PIPELINE_SOURCES['demo_registered']()
        self.assertEqual(('pipeline', 'demo_registered', 'media'),
                         (manifest['manifest_kind'], manifest['key'], manifest['world']))
        self.assertIn('1 process', manifest['name'])


class WhatALaunchReplaysTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _output(self, name, text='X:1'):
        (Path(self.tmp) / name).write_text(text, encoding='utf-8')
        return name

    def _played(self, pipeline, item, key, output=''):
        """Plays one process the way the skeleton does: snapshot at the start, output at the end."""
        spec = pipeline.spec(key)
        process_runs.start(item, key, settings_snapshot=pipeline.snapshot(spec, item))
        process_runs.succeed(item, key, output_ref=output)

    def _both_played(self, pipeline, item):
        self._played(pipeline, item, 'plan', self._output(f'score{item.pk}.abc'))
        self._played(pipeline, item, 'render', self._output(f'audio{item.pk}.wav', 'RIFF'))

    def test_a_card_that_never_ran_plays_every_process_in_order(self):
        pipeline, item = _two_steps(), _Element()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))

    def test_a_process_that_does_not_apply_to_this_element_is_not_played(self):
        pipeline = _two_steps(applies=lambda item, model_key: model_key == 'writes-scores')
        item = _Element()
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, 'plays-only')))
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item, 'writes-scores')))

    def test_a_failed_last_process_is_replayed_alone(self):
        pipeline, item = _two_steps(), _Element()
        self._played(pipeline, item, 'plan', self._output('score.abc'))
        process_runs.start(item, 'render')
        process_runs.fail(item, 'render', 'out of memory')
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))
        self.assertTrue(pipeline.resumes_from(item, 'plan'))
        self.assertEqual(JOB_FAILURE, pipeline.card_state(item))

    def test_a_setting_of_the_last_process_does_not_replay_the_first(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        item.duration = 60
        self.assertEqual({'render'}, pipeline.refresh(item))
        self.assertEqual(JOB_STALE, pipeline.card_state(item))
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'plan').status)

    def test_a_setting_of_the_first_process_replays_everything_downstream(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        item.prompt = 'a fast drum solo'
        self.assertEqual({'plan', 'render'}, pipeline.refresh(item))
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertFalse(pipeline.resumes_from(item, 'plan'))

    def test_an_upstream_output_that_was_replaced_makes_the_downstream_stale(self):
        """The third cause of point 4.3: nobody changed a setting, somebody rewrote the score."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertIn(UPSTREAM_KEY, process_runs.line(item, 'render').settings_snapshot)
        self.assertEqual(set(), pipeline.refresh(item), 'nothing changed, nothing is stale')
        self._output(f'score{item.pk}.abc', 'X:1 corrected by hand')
        self.assertEqual({'render'}, pipeline.refresh(item))
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))

    def test_a_valid_card_relaunched_replays_everything(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertFalse(pipeline.resumes_from(item, 'plan'))

    def test_it_still_replays_everything_once_the_launcher_removed_the_last_output(self):
        """The launcher resets the card BEFORE the task asks what to play (`begin_processing`):
        reading the missing file first would turn a full relaunch into a resume of the last
        process."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        (Path(self.tmp) / f'audio{item.pk}.wav').unlink()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))

    def test_a_result_whose_file_is_gone_is_not_resumed_from(self):
        pipeline, item = _two_steps(), _Element()
        self._played(pipeline, item, 'plan', self._output('score.abc'))
        process_runs.start(item, 'render')
        process_runs.fail(item, 'render', 'boom')
        (Path(self.tmp) / 'score.abc').unlink()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))

    def test_one_process_alone_takes_its_stale_upstreams_and_never_its_downstream(self):
        """▶ par process (P5) : the asked process always runs ; an upstream still valid is
        resumed from, a stale one is replayed first ; the downstream is left alone — it will
        turn stale by itself once its upstream output changed."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, only='render')))
        self.assertEqual(['plan'], _keys(pipeline.steps_to_run(item, only='plan')),
                         'the downstream render must not be dragged along')
        item.prompt = 'a fast drum solo'           # plan stale → render asked alone replays it first
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item, only='render')))

    def test_a_process_asked_alone_must_exist_and_apply(self):
        pipeline, item = _two_steps(applies=lambda item, model_key: False), _Element()
        with self.assertRaisesMessage(ValueError, 'plan'):
            pipeline.steps_to_run(item, only='plan')
        with self.assertRaisesMessage(ValueError, 'master'):
            pipeline.steps_to_run(item, only='master')

    def test_resetting_the_outputs_of_one_process_leaves_the_others(self):
        """Relaunching the score alone must not take the audio away."""
        class _File:
            def __init__(self, name):
                self.name = name
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('plan', outputs=('score_file',)),
            ProcessSpec('render', depends_on=('plan',), outputs=('audio_file',)),
        ), label='Demo')
        item = _Element(score_file=_File('s.abc'), audio_file=_File('a.wav'))
        with mock.patch('wama.common.utils.queue_duplication.safe_delete_file',
                        return_value=True) as deleted:
            self.assertEqual(['score_file'], pipeline.reset_outputs(item, ['plan']))
        deleted.assert_called_once_with(item, 'score_file')
        self.assertIsNone(item.score_file)
        self.assertEqual('a.wav', item.audio_file.name)

    def test_an_upstream_that_never_ran_makes_nobody_stale(self):
        """A process that did not apply (no line) is not a missing upstream."""
        pipeline, item = _two_steps(applies=lambda item, model_key: False), _Element()
        self._played(pipeline, item, 'render', self._output('audio.wav', 'RIFF'))
        self.assertEqual(set(), pipeline.refresh(item))
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))

    def test_the_line_of_a_single_process_card_is_not_one_of_the_pipeline(self):
        pipeline, item = _two_steps(), _Element()
        process_runs.start(item)
        process_runs.succeed(item)
        self.assertEqual({}, pipeline.rows(item))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))

    def test_a_file_setting_is_compared_by_its_path(self):
        """The snapshot is read back from JSON: a file field must be written as its path, or a
        card would be stale the moment it is read."""
        class _File:
            """Like a `FieldFile`: its text form is its path."""

            def __init__(self, name):
                self.name = name

            def __str__(self):
                return self.name
        pipeline = AppPipeline('demo_pipeline', (ProcessSpec('render', watched=('given_score',)),),
                               label='x')
        item = _Element(given_score=_File('users/1/in.abc'))
        self._played(pipeline, item, 'render')
        self.assertEqual({'given_score': 'users/1/in.abc'},
                         process_runs.line(item, 'render').settings_snapshot)
        self.assertEqual(set(), pipeline.refresh(item))
        item.given_score = _File('users/1/other.abc')
        self.assertEqual({'render'}, pipeline.refresh(item))


class WhatTheCardShowsTest(TestCase):
    """P5 — the card shows its processes and ONE state, read through the adapter
    (`shown_state`), never `item.status` alone: a stale render under a « successful » element
    is what the lines know and the element does not."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('plan', label='Partition', watched=('prompt',),
                        applies=lambda item, model_key: model_key == 'writes-scores'),
            ProcessSpec('render', label='Rendu', depends_on=('plan',), watched=('duration',)),
        ), label='Demo')

    def _played(self, item, key, output=''):
        spec = self.pipeline.spec(key)
        process_runs.start(item, key, settings_snapshot=self.pipeline.snapshot(spec, item),
                           model_key='family:m')
        process_runs.succeed(item, key, output_ref=output, output_summary={'label': key + '.out'})

    def test_an_element_in_flight_is_shown_as_the_element_says(self):
        item = _Element(status=JOB_RUNNING)
        self.assertEqual(JOB_RUNNING, self.pipeline.shown_state(item))
        item.status = 'AWAITING_RESOURCES'
        self.assertEqual('AWAITING_RESOURCES', self.pipeline.shown_state(item))

    def test_without_any_line_the_element_alone_is_shown(self):
        item = _Element(status=JOB_PENDING)
        self.assertEqual(JOB_PENDING, self.pipeline.shown_state(item))
        self.assertEqual([], self.pipeline.card_rows(item))

    def test_each_row_says_what_its_process_watches_for_its_own_gear(self):
        """⚙ par process (P5) : the gear of a row shows the settings the process WATCHES — read
        from the declaration, never a list written in a template."""
        item = _Element(status=JOB_SUCCESS)
        self._played(item, 'plan')
        self._played(item, 'render')
        rows = {r['key']: r['watched'] for r in self.pipeline.card_rows(item)}
        self.assertEqual({'plan': ['prompt'], 'render': ['duration']}, rows)

    def test_the_common_decoration_poses_the_view_only_for_an_app_with_a_pipeline(self):
        """`decorate` is the single attachment point of the GENERATED apps (5.2) : nothing
        without a declared pipeline (the card reads `status`), the three attributes with one."""
        from wama.common.services.process_pipeline import card_view, decorate
        item = _Element(status=JOB_SUCCESS)
        APP_PIPELINES.pop('demo_pipeline', None)
        self.assertIsNone(card_view(item))
        self.assertIsNone(decorate(item))
        self.assertFalse(hasattr(item, 'shown_state'))
        APP_PIPELINES['demo_pipeline'] = self.pipeline
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        self._played(item, 'plan')
        self._played(item, 'render')
        rows, state, label = decorate(item)
        self.assertEqual((['plan', 'render'], JOB_SUCCESS), ([r['key'] for r in rows], state))
        self.assertEqual((item.processes, item.shown_state, item.shown_state_label),
                         (rows, state, label))
        self.assertTrue(label)

    def test_a_stale_render_is_shown_under_a_successful_element(self):
        item = _Element(status=JOB_SUCCESS)
        (Path(self.tmp) / 'score.abc').write_text('X:1', encoding='utf-8')
        self._played(item, 'plan', 'score.abc')
        self._played(item, 'render')
        self.assertEqual(JOB_SUCCESS, self.pipeline.shown_state(item))
        item.duration = 60
        self.assertEqual(JOB_STALE, self.pipeline.shown_state(item))
        rows = self.pipeline.card_rows(item)
        self.assertEqual([('plan', 'Partition', JOB_SUCCESS), ('render', 'Rendu', JOB_STALE)],
                         [(r['key'], r['label'], r['status']) for r in rows])
        self.assertEqual('plan.out', rows[0]['output_label'])
        self.assertEqual('family:m', rows[0]['model_key'])

    def test_the_rows_show_what_ran_and_what_the_named_model_will_run(self):
        item = _Element(status=JOB_PENDING)
        self.assertEqual(['render'], [r['key'] for r in self.pipeline.card_rows(item, 'plays-only')])
        self.assertEqual(['plan', 'render'],
                         [r['key'] for r in self.pipeline.card_rows(item, 'writes-scores')])
        self.assertTrue(all(r['status'] == JOB_PENDING for r in
                            self.pipeline.card_rows(item, 'writes-scores')))

    def test_the_common_strip_renders_one_line_per_process_and_nothing_without_any(self):
        from django.template.loader import render_to_string
        html = render_to_string('common/_card_processes.html', {'processes': [
            {'key': 'plan', 'label': 'Partition', 'degree': 'required', 'status': JOB_SUCCESS,
             'duration_s': 159.1, 'model_key': 'family:m', 'output_label': 'a.abc', 'error': ''},
            {'key': 'render', 'label': 'Rendu', 'degree': 'required', 'status': JOB_STALE,
             'duration_s': 54.0, 'model_key': '', 'output_label': '', 'error': ''}]})
        self.assertIn('data-processes', html)
        self.assertIn('data-process="plan"', html)
        self.assertIn('data-s="STALE"', html)
        self.assertIn('159 s', html)
        self.assertIn('périmé', html)
        self.assertEqual('', render_to_string('common/_card_processes.html',
                                              {'processes': []}).strip())
        single = render_to_string('common/_card_processes.html', {'processes': [
            {'key': 'render', 'label': 'Rendu', 'degree': 'required', 'status': JOB_SUCCESS,
             'duration_s': 54.0, 'model_key': '', 'output_label': '', 'error': ''}]})
        self.assertEqual('', single.strip(), 'one process is not a pipeline to show')


class SkeletonRunsThePipelineTest(TestCase):
    """The retained processes run one after the other in ONE task, one line each."""

    def setUp(self):
        self.app, self.model = _adopters()[0]
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',), share=3),
        ), label='Demo')
        self.calls = []

    def _element(self, name):
        user = get_user_model().objects.create_user(name, password='x')
        item = _instance(self.model, user)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        return item

    def _run(self, item, **glues):
        from wama.common.utils.task_skeleton import run_item_task

        def default(key):
            def glue(element, ctx):
                self.calls.append((key, ctx.step))
                return {'models': [f'family:{key}'], 'label': f'{key}.out'}
            return glue
        processes = {key: glues.get(key) or default(key) for key in ('plan', 'render')}
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes=processes,
                          model_key='family:announced')
        return self.model.objects.get(pk=item.pk)

    def _states(self, item):
        return {row.node_id: row.status for row in process_runs.lines(item)}

    def test_both_processes_run_in_order_and_each_has_its_line(self):
        item = self._run(self._element('pipeline_both'))
        self.assertEqual([('plan', 'plan'), ('render', 'render')], self.calls)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}, self._states(item))
        plan, render = (process_runs.line(item, key) for key in ('plan', 'render'))
        self.assertEqual((f'{self.app}.plan', 'function', 'family:plan'),
                         (plan.process_key, plan.process_kind, plan.model_key))
        self.assertEqual('family:render', render.model_key)
        self.assertEqual('plan.out', plan.output_summary.get('label'))
        self.assertIsNone(process_runs.line(item), 'a pipeline card has no « main » line')

    def test_the_card_reports_every_model_its_processes_employed(self):
        with mock.patch('wama.common.utils.task_skeleton._signal') as signal:
            self._run(self._element('pipeline_models'))
        produced = [call for call in signal.call_args_list if call.args[2] == 'produit']
        self.assertEqual(['family:plan', 'family:render'], produced[0].args[3])

    def test_a_failure_closes_the_line_of_the_process_that_failed_only(self):
        def broken(element, ctx):
            raise RuntimeError('render is down')
        item = self._run(self._element('pipeline_fails'), render=broken)
        self.assertEqual('FAILURE', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertIn('render is down', process_runs.line(item, 'render').error_message)

    def test_the_relaunch_after_a_failure_does_not_replay_what_succeeded(self):
        def broken(element, ctx):
            raise RuntimeError('render is down')
        item = self._run(self._element('pipeline_resumes'), render=broken)
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        item = self._run(item)
        self.assertEqual([('render', 'render')], self.calls)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}, self._states(item))

    def test_each_process_fills_its_own_share_of_the_bar(self):
        """`plan` weighs 1 and `render` 3: half of `plan` is an eighth of the card."""
        if not any(f.name == 'progress' for f in self.model._meta.get_fields()):
            self.skipTest(f'{self.app} has no progress column')
        seen = {}

        def half(key):
            def glue(element, ctx):
                ctx.progress(50)
                seen[key] = self.model.objects.get(pk=element.pk).progress
                return {}
            return glue
        self._run(self._element('pipeline_bar'), plan=half('plan'), render=half('render'))
        self.assertEqual({'plan': 12, 'render': 62}, seen)

    def test_each_process_learns_its_own_duration(self):
        """Point 4.5: the ETA is per PROCESS — the one of `plan` is recorded when `plan` returns,
        under its own key, not when the card ends."""
        def with_eta(key):
            def glue(element, ctx):
                return {'eta': (f'family:{key}', 2.0, 'audio_sec')}
            return glue
        with mock.patch('wama.model_manager.services.eta_estimator.record_run') as record:
            self._run(self._element('pipeline_eta'), plan=with_eta('plan'),
                      render=with_eta('render'))
        self.assertEqual(['family:plan', 'family:render'],
                         [call.args[0] for call in record.call_args_list])

    def test_the_time_limit_closes_the_line_of_the_process_it_interrupted(self):
        from wama.common.utils.task_skeleton import TaskTimeLimitExceeded

        def too_long(element, ctx):
            raise TaskTimeLimitExceeded(60)
        item = self._run(self._element('pipeline_limit'), render=too_long)
        self.assertEqual('FAILURE', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertIn('Durée maximale', process_runs.line(item, 'render').error_message)

    def test_a_wait_for_the_graphics_card_writes_no_main_line(self):
        """Before the draw nobody knows which process starts first, and « main » is not one of
        the processes of a pipeline: the wait is carried by the element alone."""
        from wama.common.utils.task_skeleton import run_item_task

        class Deferred(Exception):
            pass
        task = _task()
        task.retry = staticmethod(lambda **kwargs: Deferred(kwargs))
        item = self._element('pipeline_waits')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.services.resource_governor.effective_free_gb',
                           return_value=1.0), \
                mock.patch('wama.common.services.resource_governor.fits_alone',
                           return_value=True), \
                mock.patch('wama.common.services.resource_governor.release_granted',
                           return_value=None), \
                mock.patch('wama.common.services.resource_governor.holders_summary',
                           return_value=''):
            with self.assertRaises(Deferred):
                run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                              pipeline=self.pipeline, vram_needed=8.0,
                              processes={'plan': lambda e, c: {}, 'render': lambda e, c: {}})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('AWAITING_RESOURCES', item.status)
        self.assertFalse(process_runs.lines(item).exists())

    def test_the_skeleton_can_be_bounded_to_one_process(self):
        item = self._run(self._element('pipeline_bounded_first'))
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        from wama.common.utils.task_skeleton import run_item_task

        def glue(key):
            def inner(element, ctx):
                self.calls.append(key)
                return {}
            return inner
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, only='plan',
                          processes={'plan': glue('plan'), 'render': glue('render')})
        self.assertEqual(['plan'], self.calls)
        self.assertEqual('SUCCESS', self.model.objects.get(pk=item.pk).status)
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'plan').status)

    def test_a_process_without_its_glue_fails_the_card_and_says_so(self):
        from wama.common.utils.task_skeleton import run_item_task
        item = self._element('pipeline_no_glue')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes={'render': lambda e, c: {}})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('FAILURE', item.status)
        self.assertFalse(process_runs.lines(item).exists(), 'no process started, no line')


class EveryAppPipelineTest(SimpleTestCase):
    """Generic guard over EVERY pipeline an app registers (`APP_PIPELINES`) — written once, it
    holds for the next app without a test per app. What the cam_analyzer guards for its own
    registry (`tests_pass_registry.PipelineManifesteTest`), held here for the common one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG, load_all
        load_all()
        cls.catalogue = FUNCTION_CATALOG
        cls.pipelines = dict(APP_PIPELINES)

    def test_the_fleet_is_measured(self):
        self.assertIn('composer', self.pipelines)

    def test_each_process_is_a_function_of_the_catalogue_bound_to_its_app(self):
        from wama.common.catalog.function_catalog import Binding
        for app, pipeline in self.pipelines.items():
            for spec in pipeline.specs:
                with self.subTest(app=app, process=spec.key):
                    function = self.catalogue.get(pipeline.function_key(spec))
                    self.assertIsNotNone(function, 'a process without a FunctionSpec is no node')
                    self.assertEqual((Binding.APP, app), (function.binding, function.app))

    def test_the_manifest_is_valid_and_carries_the_world_the_app_states(self):
        from wama.common.app_registry import app_world
        from wama.common.manifests.ingest import extract, validate
        for app, pipeline in self.pipelines.items():
            with self.subTest(app=app):
                manifest = extract('pipeline', app)
                self.assertIsNotNone(manifest, 'the registry is not a pipeline source')
                self.assertEqual([], list(validate(manifest) or []))
                self.assertEqual(app_world(app), manifest['world'])
                self.assertEqual([spec.key for spec in pipeline.specs],
                                 [node['id'] for node in manifest['body']['nodes']])

    def test_the_exported_manifest_is_the_one_of_the_corpus(self):
        """The versioned file must be what the registry gives TODAY, and the export command must
        see the pipeline — or the corpus loses it silently (`--check` would say « up to date »)."""
        import json
        from django.conf import settings
        from wama.common.management.commands.manifest_export import _pipeline_keys
        from wama.common.manifests.ingest import extract
        for app in self.pipelines:
            with self.subTest(app=app):
                self.assertIn(app, _pipeline_keys())
                written = Path(settings.BASE_DIR) / 'manifests' / 'pipelines' / f'{app}.json'
                self.assertTrue(written.exists(), 'the pipeline is not in the corpus')
                corpus = json.loads(written.read_text(encoding='utf-8'))
                live = extract('pipeline', app)
                self.assertEqual(corpus['body'], live['body'])

    def test_it_opens_in_the_studio_and_each_link_lands_on_a_port(self):
        """« One representation, two editors »: the canvas form, with each dependency resolved
        to the input port whose type matches what the upstream process gives."""
        from wama.common.manifests.builtin.pipeline import body_to_graph
        from wama.common.manifests.ingest import extract
        for app, pipeline in self.pipelines.items():
            with self.subTest(app=app):
                graph = body_to_graph(extract('pipeline', app)['body'])
                self.assertEqual([spec.key for spec in pipeline.specs],
                                 [node['id'] for node in graph['nodes']])
                for link in graph['links']:
                    self.assertTrue(link['to_port'], f"{link['from']} -> {link['to']} has no port")
