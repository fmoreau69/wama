"""Execution lines of processes (`ProcessRun`) — `WAMA_APP_GENERATION_ROUTE §10.6` 4.1 to 4.4, step P3.

What is held here, and why each point:

  * the SERVICE writes one line per (element, node, instance key) and rewrites it at each launch —
    a state, not a journal ;
  * STALE is computed the way the cam_analyzer computes it (watched setting changed, then cascade
    downstream) — the semantics are taken from `pass_tracking.recompute_stale`, not reinvented ;
  * the state of a CARD is deduced from its processes by the rule validated on 2026-09-17 ;
  * the task skeleton writes the line of its single process at the SAME instants as the element —
    and every writer that takes an element out of « running » without its task (stop,
    reconciliation) closes the open line. Without that the line would stay RUNNING for a task that
    will never return, which is the divergence the element / line pair must not have.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.models import (JOB_AWAITING_RESOURCES, JOB_FAILURE, JOB_PENDING, JOB_RUNNING,
                                JOB_STALE, JOB_SUCCESS, ProcessRun)
from wama.common.services import process_runs
from wama.common.services.process_runs import OPTIONAL, REQUIRED
from wama.common.tests.tests_queue_delete_contract import _instance
from wama.common.tests.tests_task_skeleton_contract import _adopters, _task


def _studio_run(name='lines_owner'):
    from wama.studio.models import StudioRun
    user = get_user_model().objects.create_user(name, password='x')
    return StudioRun.objects.create(user=user, graph={})


def has_open_line_while_not_running(item) -> bool:
    """The divergence the pair must not have: the element left « running », a line did not."""
    item.refresh_from_db()
    return (item.status != JOB_RUNNING
            and process_runs.lines(item).filter(status__in=process_runs.OPEN_STATES).exists())


class ProcessRunServiceTest(TestCase):

    def test_a_launch_writes_a_running_line_with_its_snapshot_and_model(self):
        item = _studio_run()
        run = process_runs.start(item, 'render', process_key='composer.render',
                                 settings_snapshot={'model': 'auto', 'duration': 30},
                                 model_key='composer:musicgen-small', task_id='t-1')
        self.assertEqual((run.app, run.object_type, run.object_id),
                         ('studio', 'StudioRun', str(item.pk)))
        self.assertEqual(run.status, JOB_RUNNING)
        self.assertEqual(run.settings_snapshot, {'model': 'auto', 'duration': 30})
        self.assertEqual(run.model_key, 'composer:musicgen-small')
        self.assertIsNotNone(run.started_at)

    def test_a_relaunch_rewrites_the_same_line_and_keeps_the_previous_duration(self):
        item = _studio_run()
        process_runs.start(item, 'render')
        first = process_runs.succeed(item, 'render', output_ref='users/1/out.wav')
        self.assertEqual(first.status, JOB_SUCCESS)
        self.assertIsNotNone(first.duration_s)
        ProcessRun.objects.filter(pk=first.pk).update(duration_s=12.5)
        again = process_runs.start(item, 'render')
        self.assertEqual(again.pk, first.pk, 'a relaunch must not add a line')
        self.assertEqual(process_runs.lines(item).count(), 1)
        self.assertEqual(again.output_summary, {'previous_duration_s': 12.5})
        self.assertEqual((again.output_ref, again.duration_s, again.error_message), ('', None, ''))

    def test_a_failure_keeps_the_message_and_does_not_erase_the_previous_output(self):
        item = _studio_run()
        process_runs.start(item, 'plan')
        process_runs.succeed(item, 'plan', output_ref='users/1/score.abc')
        failed = process_runs.fail(item, 'plan', 'boom')
        self.assertEqual((failed.status, failed.error_message), (JOB_FAILURE, 'boom'))
        self.assertEqual(failed.output_ref, 'users/1/score.abc')

    def test_the_instance_key_tells_apart_two_runs_of_the_same_process(self):
        """Decision n°3: the cam_analyzer runs detection once PER CAMERA — one process, several
        lines. Each can fail and be relaunched alone."""
        item = _studio_run()
        process_runs.start(item, 'yolo_detect', instance_key='front')
        process_runs.start(item, 'yolo_detect', instance_key='rear')
        process_runs.succeed(item, 'yolo_detect', instance_key='front')
        process_runs.fail(item, 'yolo_detect', 'camera unreadable', instance_key='rear')
        states = {r.instance_key: r.status for r in process_runs.lines(item)}
        self.assertEqual(states, {'front': JOB_SUCCESS, 'rear': JOB_FAILURE})

    def test_an_element_with_a_uuid_key_is_addressed_like_any_other(self):
        from wama_lab.cam_analyzer.models import AnalysisSession
        user = get_user_model().objects.create_user('lines_lab', password='x')
        session = AnalysisSession.objects.create(user=user)
        run = process_runs.start(session, 'extraction')
        self.assertEqual((run.app, run.object_type, run.object_id),
                         ('cam_analyzer', 'AnalysisSession', str(session.pk)))
        self.assertEqual(process_runs.line(session, 'extraction').pk, run.pk)

    def test_closing_touches_only_the_open_lines(self):
        item = _studio_run()
        process_runs.start(item, 'plan')
        process_runs.succeed(item, 'plan')
        process_runs.start(item, 'render')
        process_runs.await_resources(item, 'master')
        self.assertEqual(process_runs.close_open(item, JOB_FAILURE, 'stopped'), 2)
        states = {r.node_id: (r.status, r.error_message) for r in process_runs.lines(item)}
        self.assertEqual(states, {'plan': (JOB_SUCCESS, ''), 'render': (JOB_FAILURE, 'stopped'),
                                  'master': (JOB_FAILURE, 'stopped')})

    def test_a_writer_that_breaks_is_told_and_never_raises(self):
        def broken(*_args, **_kwargs):
            raise RuntimeError('no table')
        with self.assertLogs('wama.common.services.process_runs', level='WARNING') as logs:
            self.assertIsNone(process_runs.safely(broken, object()))
        self.assertIn('broken', logs.output[0])


class StaleNodesTest(SimpleTestCase):
    """Point 4.3 — taken from `pass_tracking.recompute_stale`: direct mismatch, then cascade."""

    GRAPH = {'render': ['plan'], 'master': ['render']}

    def test_a_watched_setting_that_changed_makes_the_process_stale_and_its_downstream_too(self):
        states = {'plan': JOB_SUCCESS, 'render': JOB_SUCCESS, 'master': JOB_SUCCESS}
        stale = process_runs.stale_nodes(
            states, self.GRAPH,
            snapshots={'plan': {'prompt': 'jazz'}, 'render': {'score': 'a'}},
            current={'plan': {'prompt': 'jazz'}, 'render': {'score': 'b'}})
        self.assertEqual(stale, {'render', 'master'}, 'the plan itself is still up to date')

    def test_a_setting_nobody_watches_makes_nothing_stale(self):
        states = {'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}
        self.assertEqual(process_runs.stale_nodes(states, self.GRAPH, {'plan': {'p': 1}},
                                                  {'plan': {'p': 1}}), set())

    def test_an_upstream_that_failed_or_never_ran_makes_its_downstream_stale(self):
        self.assertEqual(process_runs.stale_nodes(
            {'plan': JOB_FAILURE, 'render': JOB_SUCCESS}, self.GRAPH), {'render'})
        self.assertEqual(process_runs.stale_nodes({'render': JOB_SUCCESS}, self.GRAPH),
                         {'render'})

    def test_a_process_that_returned_nothing_is_not_stale(self):
        states = {'plan': JOB_FAILURE, 'render': JOB_RUNNING, 'master': JOB_PENDING}
        self.assertEqual(process_runs.stale_nodes(states, self.GRAPH, {}, {'plan': {'p': 2}}),
                         set())


class AggregateTest(SimpleTestCase):
    """Point 4.4 — the rule validated as is on 2026-09-17."""

    def test_the_rule_in_its_order(self):
        cases = [
            ([(JOB_SUCCESS, REQUIRED), (JOB_RUNNING, REQUIRED)], JOB_RUNNING),
            ([(JOB_FAILURE, REQUIRED), (JOB_RUNNING, OPTIONAL)], JOB_RUNNING),
            ([(JOB_SUCCESS, REQUIRED), (JOB_AWAITING_RESOURCES, REQUIRED)], JOB_AWAITING_RESOURCES),
            ([(JOB_FAILURE, REQUIRED), (JOB_STALE, REQUIRED)], JOB_FAILURE),
            ([(JOB_SUCCESS, REQUIRED), (JOB_STALE, OPTIONAL)], JOB_STALE),
            ([(JOB_SUCCESS, REQUIRED), (JOB_SUCCESS, OPTIONAL)], JOB_SUCCESS),
            ([(JOB_SUCCESS, REQUIRED), (JOB_PENDING, REQUIRED)], JOB_PENDING),
            ([], JOB_PENDING),
        ]
        for processes, expected in cases:
            with self.subTest(processes=processes):
                self.assertEqual(process_runs.aggregate(processes), expected)

    def test_an_optional_process_that_failed_is_neither_a_failure_nor_a_success(self):
        """The transcriber swallowed exactly this: a failed summary, a card in success."""
        state = process_runs.aggregate([(JOB_SUCCESS, REQUIRED), (JOB_FAILURE, OPTIONAL)])
        self.assertEqual(state, JOB_PENDING)


class SkeletonWritesTheLineTest(TestCase):
    """The single process of an app on the skeleton has its line, written with the element."""

    def _run(self, app, model, glue, status='RUNNING'):
        from wama.common.utils.task_skeleton import run_item_task
        user = get_user_model().objects.create_user(f'line_{app}_{id(glue)}', password='x')
        item = _instance(model, user)
        model.objects.filter(pk=item.pk).update(status=status)
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=app, model=model, item_id=item.pk, process=glue,
                          model_key='family:declared-model')
        return model.objects.get(pk=item.pk)

    def test_the_fleet_is_measured(self):
        self.assertGreaterEqual(len(_adopters()), 4)

    def test_a_success_closes_the_line_with_the_model_the_glue_names(self):
        for app, model in _adopters():
            with self.subTest(app=app):
                item = self._run(app, model, lambda item, ctx: {'models': ['family:drawn-model'],
                                                                'label': 'out.bin'})
                run = process_runs.line(item)
                self.assertIsNotNone(run, 'the skeleton wrote no line')
                self.assertEqual((run.status, item.status), (JOB_SUCCESS, 'SUCCESS'))
                self.assertEqual(run.process_key, app)
                self.assertEqual(run.model_key, 'family:drawn-model',
                                 'the model EMPLOYED, not the one announced before the glue')
                self.assertEqual(run.task_id, 'tache-contrat')
                self.assertEqual(run.output_summary.get('label'), 'out.bin')
                self.assertIsNotNone(run.duration_s)

    def test_the_model_is_readable_while_the_process_runs(self):
        """What the element did not say under « auto »: the model of THIS launch."""
        seen = {}

        def glue(item, ctx):
            seen['run'] = process_runs.line(item)
            return {}
        for app, model in _adopters():
            with self.subTest(app=app):
                self._run(app, model, glue)
                self.assertEqual((seen['run'].status, seen['run'].model_key),
                                 (JOB_RUNNING, 'family:declared-model'))

    def test_a_failure_closes_the_line_with_its_message(self):
        def glue(item, ctx):
            raise RuntimeError('line contract failure')
        for app, model in _adopters():
            with self.subTest(app=app):
                item = self._run(app, model, glue)
                run = process_runs.line(item)
                self.assertEqual((run.status, item.status), (JOB_FAILURE, 'FAILURE'))
                self.assertIn('line contract failure', run.error_message)

    def test_a_stop_and_a_reconciliation_close_the_open_line(self):
        from wama.common.utils.process_control import _mark_reconciled, stop_instance
        for app, model in _adopters():
            for name, close in (
                    ('stop', lambda item: stop_instance(item)),
                    ('reconcile', lambda item: _mark_reconciled(
                        item, 'status', 'task_id', 'FAILURE', None, 'dead task'))):
                with self.subTest(app=app, writer=name):
                    user = get_user_model().objects.create_user(f'{name}_{app}', password='x')
                    item = _instance(model, user)
                    model.objects.filter(pk=item.pk).update(status='RUNNING')
                    item.refresh_from_db()
                    process_runs.start(item, process_key=app)
                    close(item)
                    self.assertFalse(has_open_line_while_not_running(item))
                    self.assertEqual(process_runs.line(item).status, JOB_FAILURE)

    def test_the_guard_sees_a_writer_that_forgets_the_line(self):
        """Counter-proof: with the closing neutralised, the divergence appears — so the test
        above does measure something."""
        from wama.common.utils.process_control import stop_instance
        app, model = _adopters()[0]
        user = get_user_model().objects.create_user('forgetful_writer', password='x')
        item = _instance(model, user)
        model.objects.filter(pk=item.pk).update(status='RUNNING')
        item.refresh_from_db()
        process_runs.start(item, process_key=app)
        with mock.patch('wama.common.services.process_runs.close_open', return_value=0):
            stop_instance(item)
        self.assertTrue(has_open_line_while_not_running(item))

    def test_removing_a_card_takes_its_lines_with_it(self):
        from wama.common.utils.queue_duplication import release_card_files
        app, model = _adopters()[0]
        user = get_user_model().objects.create_user('card_removed', password='x')
        item = _instance(model, user)
        process_runs.start(item, process_key=app)
        release_card_files(item)
        self.assertFalse(process_runs.lines(item).exists())
