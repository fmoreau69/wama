"""Studio — une exécution SUIVIE comme un élément (2026-11-06, demande de Fabien : après
l'installation d'un modèle, le Studio, « quelque chose d'universel et pérenne »).

Rien n'est propre à un nœud : la ligne se lit sur ce que l'exécuteur publie déjà (`node_states`,
le résumé d'un run de lot, les lignes d'exécution communes), la fin passe par les points communs
des traitements (`notify_job_end`, `RunOutcome`), et la famille `studio` est inscrite au registre
des familles suivies — l'échange de l'assistant, sa fin racontée et le calendrier la lisent.
"""
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from wama.common.models import JOB_RUNNING, JOB_SUCCESS
from wama.studio import tasks
from wama.studio.models import StudioRun
from wama.studio.services.run_progress import job_row, run_progress

TWO_APPS = {'nodes': [{'id': 'in', 'app': 'file_input', 'params': {}},
                      {'id': 'a', 'app': 'demo_app', 'params': {}},
                      {'id': 'b', 'app': 'demo_app', 'params': {}}], 'links': []}


class TheRunLineTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('studio_follow', password='x')

    def test_progress_is_the_mean_of_the_working_nodes(self):
        run = StudioRun.objects.create(user=self.user, graph=TWO_APPS, status=JOB_RUNNING,
                                       node_states={'in': {'status': JOB_SUCCESS},
                                                    'a': {'status': JOB_SUCCESS},
                                                    'b': {'status': JOB_RUNNING, 'progress': 40}})
        with mock.patch('wama.common.manifests.builtin.pipeline.builtin_node',
                        side_effect=lambda key: object() if key == 'file_input' else None), \
                mock.patch('wama.common.manifests.builtin.pipeline._node_kind',
                           side_effect=lambda app: 'source' if app == 'file_input' else 'app'):
            self.assertEqual(70, run_progress(run), 'the input card passes in an instant')

    def test_a_lot_run_counts_its_successful_elements_like_a_parent_card(self):
        lot = StudioRun.objects.create(user=self.user, graph=TWO_APPS, status=JOB_RUNNING)
        for status in (JOB_SUCCESS, 'FAILURE', JOB_RUNNING, 'PENDING'):
            StudioRun.objects.create(user=self.user, graph=TWO_APPS, status=status, parent=lot)
        self.assertEqual(25, run_progress(lot), 'a failure does not advance the bar of a lot')

    def test_the_line_is_the_owners_and_says_when_the_run_started(self):
        from wama.common.services import process_runs
        run = StudioRun.objects.create(user=self.user, graph=TWO_APPS, status=JOB_RUNNING)
        process_runs.start(run, 'a', process_key='demo_app', kind='app')
        row = job_row(self.user, run.pk)
        self.assertEqual(('studio', run.pk, JOB_RUNNING, False), (row['family'], row['id'],
                                                                  row['status'], row['terminal']))
        self.assertIsNotNone(row['started_at'])
        stranger = get_user_model().objects.create_user('studio_stranger', password='x')
        self.assertIsNone(job_row(stranger, run.pk), "another person's run is not read")


class TheRunEndTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('studio_end', password='x')

    def _run(self, answer):
        run = StudioRun.objects.create(user=self.user, graph={
            'nodes': [{'id': 'n1', 'app': 'demo_app', 'params': {}}], 'links': []})
        runner = {'create': lambda user, inputs, params: 7, 'start': lambda user, item_id: None,
                  'poll': lambda user, item_id: answer, 'output_type': 'audio'}
        with mock.patch('wama.studio.services.runners.runner_for', return_value=runner), \
                mock.patch.object(tasks.time, 'sleep'):
            tasks.run_pipeline_task(run.pk)
        run.refresh_from_db()
        return run

    def test_the_end_is_the_common_end_and_dates_the_run(self):
        from wama.common.models import Notification, RunOutcome
        run = self._run({'status': 'SUCCESS', 'progress': 100, 'output': 'x/out.wav'})
        note = Notification.objects.get(recipient=self.user)
        self.assertEqual(('job_done', 'studio', 'StudioRun', str(run.pk)),
                         (note.kind, note.app, note.object_type, note.object_id))
        self.assertEqual(['produit'], list(RunOutcome.objects.filter(
            app='studio', object_id=run.pk).values_list('signal', flat=True)))

    def test_a_failed_run_says_it(self):
        from wama.common.models import Notification, RunOutcome
        run = self._run({'status': 'FAILURE', 'error': 'moteur absent'})
        note = Notification.objects.get(recipient=self.user)
        self.assertEqual('job_failed', note.kind)
        self.assertIn('moteur absent', note.body)
        self.assertEqual(['echec'], list(RunOutcome.objects.filter(
            app='studio', object_id=run.pk).values_list('signal', flat=True)))


class AnInterruptedRunIsSettledTest(TestCase):
    """2026-11-06 : a run whose worker dies is settled by the common reconciliation, which knows
    an element by its `status` + `task_id` (`process_control.work_models`) — so every element of a
    lot carries the task that executes it (only the launched run had it), and the Studio page
    reconciles at its opening, like the page of every app."""

    def setUp(self):
        self.user = get_user_model().objects.create_superuser('studio_settle', 's@x.fr', 'x')

    def test_each_element_of_a_lot_carries_the_task_that_runs_it(self):
        graph = {'nodes': [{'id': 'n1', 'app': 'demo_app', 'params': {}}], 'links': []}
        lot = StudioRun.objects.create(user=self.user, graph=graph, task_id='lot-task')
        elements = [StudioRun.objects.create(user=self.user, graph=graph, parent=lot)
                    for _ in range(2)]
        runner = {'create': lambda user, inputs, params: 7, 'start': lambda user, item_id: None,
                  'poll': lambda user, item_id: {'status': 'SUCCESS', 'progress': 100,
                                                 'output': 'x/out.wav'},
                  'output_type': 'audio'}
        with mock.patch('wama.studio.services.runners.runner_for', return_value=runner), \
                mock.patch.object(tasks.time, 'sleep'):
            tasks._execute_lot(lot, elements, 'lot-task')
        self.assertEqual(['lot-task', 'lot-task'], list(
            StudioRun.objects.filter(parent=lot).order_by('pk').values_list('task_id', flat=True)))

    def test_the_studio_page_reconciles_its_runs_at_its_opening(self):
        from django.urls import reverse
        self.client.force_login(self.user)
        with mock.patch('wama.common.utils.process_control.reconcile_queue_of') as reconcile:
            self.assertEqual(200, self.client.get(reverse('studio:index')).status_code)
        self.assertTrue(reconcile.called, 'the Studio page does not reconcile')
        model, user = reconcile.call_args.args
        self.assertEqual((StudioRun, self.user.pk), (model, user.pk))


class TheAssistantFollowsTheRunTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_superuser('studio_asst', 'a@x.fr', 'x')

    def test_the_launched_run_is_designated_read_and_its_end_told_in_its_thread(self):
        from wama.common.models import Notification
        from wama.common.services import conversation_store
        from wama.common.services.job_follow_ups import origin_conversation, status_step
        from wama.common.utils.notifications import notify_job_end
        from wama.tool_api import items_of_step, job_progress
        run = StudioRun.objects.create(user=self.user, graph=TWO_APPS, status=JOB_RUNNING)
        result = {'run_id': run.pk, 'item_id': run.pk, 'status': 'started', 'pipeline': 'p'}
        self.assertEqual([('studio', run.pk)], items_of_step('run_studio_pipeline', {}, result))
        self.assertEqual(run.pk, job_progress(self.user, 'studio', run.pk)['id'])
        conversation = conversation_store.thread(self.user, surface='web')
        conversation_store.record_exchange(conversation, 'lance mon pipeline', {
            'response': 'Lancé.', 'tool_steps': [{'tool': 'run_studio_pipeline', 'args': {},
                                                  'result': result}]})
        notify_job_end(run, 'studio', 'Studio', str(run), True)
        note = Notification.objects.get(recipient=self.user)
        self.assertEqual(conversation.pk, origin_conversation(note, 'web').pk)
        step = status_step(note, self.user)
        self.assertEqual(('get_studio_run_status', {'run_id': run.pk}), (step['tool'], step['args']))


class TheCalendarDatesARunningRunTest(TestCase):

    def test_a_running_run_starts_at_its_first_line_and_ends_by_its_observed_rate(self):
        from wama.common.services import process_runs
        from wama.common.services.calendar import observed_events
        user = get_user_model().objects.create_user('studio_cal', password='x')
        run = StudioRun.objects.create(user=user, graph={
            'nodes': [{'id': 'a', 'app': 'demo_app', 'params': {}}], 'links': []},
            status=JOB_RUNNING, node_states={'a': {'status': JOB_RUNNING, 'progress': 50}})
        process_runs.start(run, 'a', process_key='demo_app', kind='app')
        started = timezone.now() - timedelta(minutes=20)
        process_runs.lines(run).update(started_at=started)
        now = timezone.now()
        (ev,) = [e for e in observed_events(user, now - timedelta(hours=1),
                                             now + timedelta(hours=1), now=now)
                 if e.app == 'studio']
        self.assertEqual(('predicted', started), (ev.nature, ev.start))
        self.assertAlmostEqual(20, (ev.end - now).total_seconds() / 60, delta=1,
                               msg='20 min for 50 % leaves 20 min')
