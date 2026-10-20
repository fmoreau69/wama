"""Monde Data dans le pipeline : l'ENTRÉE Connector et la SORTIE Exporter (2026-10-11).

`WAMA_DATA_WORLD §11.8 ⑨` (précisé par Fabien le 2026-09-15) et `WAMA_APP_GENERATION_ROUTE §10.6`
3.6 : l'Exporter est un NŒUD DE SORTIE qui porte ses `Declaration`s, et un pipeline SANS process
(« je connecte une base et j'en extrais les tables ») est valide. Ces tests attestent les trois
lieux où c'était refusé ou absent : le kind du nœud, le lancement (`launch_graph` exigeait un
process), l'exécuteur (aucune entrée ne savait brancher une base, aucune sortie l'exporter).
"""
import os
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

DECLARATION = ('[{"name": "situations", "identite": ["trip_id"], '
               '"colonnes": [{"stream": "situations", "field": "label"}]}]')


def _graph(path, **export_params):
    return {'nodes': [{'id': 'n1', 'app': 'data_connector', 'params': {'path': path}},
                      {'id': 'n2', 'app': 'data_export',
                       'params': {'declarations': DECLARATION, **export_params}}],
            'links': [{'from': 'n1', 'to': 'n2'}]}


class DataNodesAreASourceAndASinkTest(SimpleTestCase):
    def test_the_connector_is_a_source_and_the_export_a_sink(self):
        from wama.common.manifests.builtin.pipeline import graph_to_body
        body = graph_to_body(_graph('x'))
        self.assertEqual([n['kind'] for n in body['nodes']], ['source', 'sink'])


class LaunchAcceptsAPipelineWithoutProcessTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('studio_data', password='x')

    def _launch(self, graph):
        from wama.studio.services.launch import launch_graph
        with mock.patch('wama.studio.tasks.run_pipeline_task.delay') as delay:
            delay.return_value = mock.Mock(id='fake-task')
            return launch_graph(self.user, graph)

    def test_a_source_linked_to_a_sink_without_process_is_launchable(self):
        run, err = self._launch(_graph('users/1/temp/x.wdat'))
        self.assertIsNone(err)
        self.assertEqual(run.task_id, 'fake-task')

    def test_a_graph_that_does_nothing_is_still_refused(self):
        """Contre-épreuve : une entrée SEULE, ou une entrée et une sortie non reliées, ne sont
        pas « un pipeline sans process » — elles ne produisent rien."""
        alone = {'nodes': [{'id': 'n1', 'app': 'data_connector'}], 'links': []}
        run, err = self._launch(alone)
        self.assertIsNone(run)
        self.assertIn('Rien à exécuter', err)
        unlinked = dict(_graph('x'), links=[])
        run, err = self._launch(unlinked)
        self.assertIsNone(run)


class ExecutorConnectsAndExportsTest(TestCase):
    def setUp(self):
        from wama_data.functions.io.tests_connector import _base
        self.user = get_user_model().objects.create_user('studio_data_exec', password='x')
        self.rel_dir = f'users/{self.user.pk}/temp/donnees'
        self.abs_dir = Path(settings.MEDIA_ROOT) / self.rel_dir
        _base(self.abs_dir / 'P01' / 'essai_01.wdat', 'P01')
        _base(self.abs_dir / 'P02' / 'essai_02.wdat', 'P02')

    def _run(self, graph):
        from wama.studio.models import StudioRun
        from wama.studio.tasks import run_pipeline_task
        run = StudioRun.objects.create(user=self.user, graph=graph)
        run_pipeline_task(run.pk)
        run.refresh_from_db()
        return run

    def test_a_folder_of_bases_exports_next_to_its_data_by_default(self):
        run = self._run(_graph(self.rel_dir))
        self.assertEqual(run.status, 'SUCCESS', run.node_states)
        self.assertIn('2 base(s) connectée(s)', run.node_states['n1']['output'])
        self.assertTrue((self.abs_dir / 'situations_essai_01.csv').exists())
        self.assertTrue((self.abs_dir / 'situations_essai_02.csv').exists())

    def test_a_chosen_destination_is_honoured(self):
        dest = f'users/{self.user.pk}/temp/exports'
        os.makedirs(Path(settings.MEDIA_ROOT) / dest, exist_ok=True)
        run = self._run(_graph(self.rel_dir, destination=dest, concat_lots='1'))
        self.assertEqual(run.status, 'SUCCESS', run.node_states)
        self.assertTrue((Path(settings.MEDIA_ROOT) / dest / 'situations.csv').exists())

    def test_a_path_outside_the_user_space_is_refused(self):
        foreign = f'users/{self.user.pk + 1000}/temp/donnees'
        run = self._run(_graph(foreign))
        self.assertEqual(run.status, 'FAILURE')
        self.assertIn('Accès refusé', str(run.node_states))

    def test_rerunning_does_not_replace_an_export_unless_asked(self):
        self.assertEqual(self._run(_graph(self.rel_dir)).status, 'SUCCESS')
        second = self._run(_graph(self.rel_dir))
        self.assertEqual(second.status, 'FAILURE')
        self.assertIn('déjà présent', str(second.node_states))
        self.assertEqual(self._run(_graph(self.rel_dir, overwrite='1')).status, 'SUCCESS')

    def test_a_base_does_not_go_into_the_media_library_sink(self):
        graph = {'nodes': [{'id': 'n1', 'app': 'data_connector', 'params': {'path': self.rel_dir}},
                           {'id': 'n2', 'app': 'studio_output', 'params': {}}],
                 'links': [{'from': 'n1', 'to': 'n2'}]}
        run = self._run(graph)
        self.assertEqual(run.status, 'FAILURE')
        self.assertIn('Export de données', str(run.node_states))
