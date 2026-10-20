"""Studio — ce que le canvas voit de l'état d'un nœud `app` pendant son exécution.

`WAMA_APP_GENERATION_ROUTE.md §10.6` 4.2 : l'exécuteur ne montrait que « en cours » ; un élément
qui ATTEND des ressources (sa tâche a rendu le worker au gouverneur) se lit désormais tel quel
sur le nœud, et cette attente ne compte pas dans le délai du nœud.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.models import JOB_AWAITING_RESOURCES, JOB_RUNNING, JOB_SUCCESS
from wama.studio import tasks
from wama.studio.models import StudioRun


class WaitingForResourcesIsShownOnTheNodeTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('studio_node_states', password='x')

    def _run(self, answers, timeout_s=tasks.NODE_TIMEOUT_S):
        run = StudioRun.objects.create(user=self.user, graph={
            'nodes': [{'id': 'n1', 'app': 'demo_app', 'params': {}}], 'links': []})
        seen = []

        def poll(user, item_id):
            seen.append(StudioRun.objects.get(pk=run.pk).node_states['n1'].get('status'))
            return answers.pop(0)

        runner = {'create': lambda user, inputs, params: 7, 'start': lambda user, item_id: None,
                  'poll': poll, 'output_type': 'audio'}
        with mock.patch('wama.studio.services.runners.runner_for', return_value=runner), \
                mock.patch.object(tasks.time, 'sleep'), \
                mock.patch.object(tasks, 'NODE_TIMEOUT_S', timeout_s):
            tasks.run_pipeline_task(run.pk)
        run.refresh_from_db()
        return run, seen

    def test_the_node_shows_the_wait_then_the_run_then_the_result(self):
        run, seen = self._run([
            {'status': 'AWAITING_RESOURCES', 'progress': 0},
            {'status': 'AWAITING_RESOURCES', 'progress': 0},
            {'status': 'RUNNING', 'progress': 40},
            {'status': 'SUCCESS', 'progress': 100, 'output': 'x/out.wav'}])
        # Ce que le canvas lisait AVANT chaque réponse du runner.
        self.assertEqual([JOB_RUNNING, JOB_AWAITING_RESOURCES, JOB_AWAITING_RESOURCES, JOB_RUNNING],
                         seen)
        self.assertEqual(JOB_SUCCESS, run.status)
        self.assertEqual(JOB_SUCCESS, run.node_states['n1']['status'])

    def test_the_wait_does_not_count_in_the_delay_of_the_node(self):
        """Counter-proof with a delay of zero : a node that only WAITS is not timed out, a node
        that runs past its delay is."""
        import time as real_time
        clock = [real_time.time()]

        def sleep(seconds):                 # le temps n'avance QUE par les attentes de la boucle
            clock[0] += seconds

        done = [{'status': 'SUCCESS', 'output': 'x/out.wav'}]
        delay = 2 * tasks.POLL_INTERVAL_S
        with mock.patch.object(tasks.time, 'time', side_effect=lambda: clock[0]):
            with mock.patch.object(tasks.time, 'sleep', side_effect=sleep):
                run = StudioRun.objects.create(user=self.user, graph={
                    'nodes': [{'id': 'n1', 'app': 'demo_app', 'params': {}}], 'links': []})
                outcomes = {}
                for name, answers in (('waited', [{'status': 'AWAITING_RESOURCES'}] * 6 + done),
                                      ('late', [{'status': 'RUNNING'}] * 6 + done)):
                    run = StudioRun.objects.create(user=self.user, graph=run.graph)
                    runner = {'create': lambda user, inputs, params: 7,
                              'start': lambda user, item_id: None,
                              'poll': lambda user, item_id, a=answers: a.pop(0),
                              'output_type': 'audio'}
                    with mock.patch('wama.studio.services.runners.runner_for',
                                    return_value=runner), \
                            mock.patch.object(tasks, 'NODE_TIMEOUT_S', delay):
                        tasks.run_pipeline_task(run.pk)
                    run.refresh_from_db()
                    outcomes[name] = run
        self.assertEqual(JOB_SUCCESS, outcomes['waited'].status)
        self.assertEqual('FAILURE', outcomes['late'].status)
        self.assertIn('délai dépassé', outcomes['late'].error_message)
