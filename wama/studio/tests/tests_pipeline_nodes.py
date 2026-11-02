"""The `pipeline` node: a SAVED pipeline used as a node, referenced by its key and never copied
(ROUTE §10.6 3.1, decided 2026-09-15, coded 2026-11-02 — agreement Briques UI / Monde Data).

The node does not run: the launch DEPLOYS it (`builtin/pipeline.expand_pipeline_nodes`), so the
executor keeps seeing four node kinds, one table of states, unchanged `ProcessRun` lines. Its ports
are the inner entry and exit cards; every guess is refused by name (ambiguous port, ambiguous exit,
settings on the node, cycle, dead or hidden reference).
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.manifests.builtin.pipeline import (NODE_ID_MAX, body_to_graph,
                                                    expand_pipeline_nodes, graph_to_body,
                                                    node_kind, pipeline_key,
                                                    validate_pipeline_body)

FN = 'function:ego_track_filter'

#: Saved pipelines of the pure tests, by key: (name, canvas graph).
SAVED = {
    # an entry card feeding a function, the function feeding an exit card
    '1': ('one', {'nodes': [{'id': 's', 'app': 'text_input', 'params': {'text': 'kept'}},
                            {'id': 'f', 'app': FN},
                            {'id': 'o', 'app': 'studio_output'}],
                  'links': [{'from': 's', 'to': 'f', 'to_port': 'track'},
                            {'from': 'f', 'to': 'o', 'to_port': None}]}),
    # two entry cards
    '2': ('two', {'nodes': [{'id': 'a', 'app': 'text_input'}, {'id': 'b', 'app': 'text_input'},
                            {'id': 'f', 'app': FN}],
                  'links': [{'from': 'a', 'to': 'f', 'to_port': 'track'},
                            {'from': 'b', 'to': 'f', 'to_port': 'other'}]}),
    # two nodes feeding exit cards
    '3': ('three', {'nodes': [{'id': 'f', 'app': FN}, {'id': 'g', 'app': FN},
                              {'id': 'o', 'app': 'studio_output'},
                              {'id': 'p', 'app': 'studio_output'}],
                    'links': [{'from': 'f', 'to': 'o'}, {'from': 'g', 'to': 'p'}]}),
    # a pipeline that nests pipeline 1
    '4': ('four', {'nodes': [{'id': 'in', 'app': 'pipeline:1'}, {'id': 'g', 'app': FN}],
                   'links': [{'from': 'in', 'to': 'g', 'to_port': 'track'}]}),
    # cycles: 5 refers to itself, 6 → 7 → 6
    '5': ('five', {'nodes': [{'id': 'x', 'app': 'pipeline:5'}], 'links': []}),
    '6': ('six', {'nodes': [{'id': 'x', 'app': 'pipeline:7'}], 'links': []}),
    '7': ('seven', {'nodes': [{'id': 'y', 'app': 'pipeline:6'}], 'links': []}),
}


def resolve(key):
    if key not in SAVED:
        raise ValueError(f'pipeline {key} introuvable ou non visible pour ce compte.')
    name, graph = SAVED[key]
    return name, {'nodes': [dict(n) for n in graph['nodes']],
                  'links': [dict(l) for l in graph['links']]}


def expand(nodes, links=()):
    return expand_pipeline_nodes({'nodes': nodes, 'links': list(links)}, resolve)


def ids(graph):
    return [n['id'] for n in graph['nodes']]


def edges(graph):
    return {(l['from'], l['to'], l.get('to_port')) for l in graph['links']}


class PipelineNodeShapeTest(SimpleTestCase):
    def test_the_node_kind_and_its_key_are_read_in_both_forms(self):
        canvas = {'id': 'n', 'app': 'pipeline:12'}
        self.assertEqual(('pipeline', '12'), (node_kind(canvas), pipeline_key(canvas)))
        body = graph_to_body({'nodes': [canvas], 'links': []})
        self.assertEqual({'kind': 'pipeline', 'pipeline': '12', 'app': None},
                         {k: body['nodes'][0][k] for k in ('kind', 'pipeline', 'app')})
        self.assertEqual('pipeline:12', body_to_graph(body)['nodes'][0]['app'],
                         'the round trip gives the canvas node back')
        self.assertEqual([], validate_pipeline_body(body))
        self.assertTrue(any("'pipeline'" in e for e in validate_pipeline_body(
            {'nodes': [{'id': 'n', 'kind': 'pipeline'}], 'links': []})),
            'a pipeline node without its key is refused')

    def test_a_builtin_node_cannot_take_the_pipeline_prefix(self):
        from wama.common.manifests.builtin.pipeline import BuiltinNode, register_builtin_node
        with self.assertRaises(ValueError):
            register_builtin_node(BuiltinNode(key='pipeline:x', role='source', label='', icon='',
                                              color='', description='', run=lambda *a: None))


class ExpandPipelineNodesTest(SimpleTestCase):
    def test_a_graph_without_pipeline_node_is_left_as_it_is(self):
        graph = {'nodes': [{'id': 'f', 'app': FN}], 'links': []}
        self.assertEqual(graph['nodes'], expand_pipeline_nodes(graph, resolve)['nodes'])

    def test_an_unwired_entry_stays_and_keeps_its_settings(self):
        out = expand([{'id': 'P', 'app': 'pipeline:1'}])
        self.assertEqual(['P/s', 'P/f', 'P/o'], ids(out))
        self.assertEqual({'text': 'kept'}, out['nodes'][0]['params'])
        self.assertEqual({('P/s', 'P/f', 'track'), ('P/f', 'P/o', None)}, edges(out))

    def test_a_wired_entry_is_replaced_by_the_outer_upstream(self):
        out = expand([{'id': 'd', 'app': 'dataset_input'}, {'id': 'P', 'app': 'pipeline:1'}],
                     [{'from': 'd', 'to': 'P', 'to_port': 's'}])
        self.assertNotIn('P/s', ids(out))
        self.assertIn(('d', 'P/f', 'track'), edges(out), 'the inner port is kept')

    def test_a_link_naming_no_port_enters_the_only_entry(self):
        out = expand([{'id': 'd', 'app': 'dataset_input'}, {'id': 'P', 'app': 'pipeline:1'}],
                     [{'from': 'd', 'to': 'P'}])
        self.assertIn(('d', 'P/f', 'track'), edges(out))

    def test_an_entry_port_is_never_guessed(self):
        nodes = [{'id': 'd', 'app': 'dataset_input'}, {'id': 'P', 'app': 'pipeline:2'}]
        with self.assertRaisesMessage(ValueError, 'non précisé'):
            expand(nodes, [{'from': 'd', 'to': 'P'}])
        with self.assertRaises(ValueError) as unknown:
            expand(nodes, [{'from': 'd', 'to': 'P', 'to_port': 'zz'}])
        self.assertIn('« zz » inconnu', str(unknown.exception))
        self.assertIn('ports : a, b', str(unknown.exception), 'the possible ports are named')

    def test_exit_cards_stay_without_downstream_and_go_with_one(self):
        kept = expand([{'id': 'P', 'app': 'pipeline:1'}])
        self.assertIn('P/o', ids(kept))
        out = expand([{'id': 'P', 'app': 'pipeline:1'}, {'id': 'g', 'app': FN}],
                     [{'from': 'P', 'to': 'g', 'to_port': 'track'}])
        self.assertNotIn('P/o', ids(out))
        self.assertIn(('P/f', 'g', 'track'), edges(out), 'the node feeding the exit goes downstream')

    def test_an_exit_is_never_guessed(self):
        with self.assertRaisesMessage(ValueError, 'ambiguë (2 nœuds'):
            expand([{'id': 'P', 'app': 'pipeline:3'}, {'id': 'g', 'app': FN}],
                   [{'from': 'P', 'to': 'g'}])
        with self.assertRaisesMessage(ValueError, 'absente'):
            expand([{'id': 'P', 'app': 'pipeline:2'}, {'id': 'g', 'app': FN}],
                   [{'from': 'P', 'to': 'g'}])

    def test_nested_pipelines_are_deployed_with_their_path(self):
        out = expand([{'id': 'X', 'app': 'pipeline:4'}])
        self.assertEqual(['X/in/s', 'X/in/f', 'X/g'], ids(out),
                         'the nested exit card goes: its pipeline node has a downstream link')
        self.assertIn(('X/in/f', 'X/g', 'track'), edges(out))
        self.assertFalse([n for n in out['nodes'] if node_kind(n) == 'pipeline'])

    def test_a_nested_entry_is_reached_by_its_path(self):
        out = expand([{'id': 'd', 'app': 'dataset_input'}, {'id': 'X', 'app': 'pipeline:4'}],
                     [{'from': 'd', 'to': 'X', 'to_port': 'in/s'}])
        self.assertIn(('d', 'X/in/f', 'track'), edges(out))

    def test_a_cycle_is_refused_direct_or_through_another_pipeline(self):
        with self.assertRaisesMessage(ValueError, 'se référence lui-même (5 → 5)'):
            expand([{'id': 'P', 'app': 'pipeline:5'}])
        with self.assertRaisesMessage(ValueError, '6 → 7 → 6'):
            expand([{'id': 'P', 'app': 'pipeline:6'}])
        with self.assertRaisesMessage(ValueError, 'se référence lui-même'):
            expand_pipeline_nodes({'nodes': [{'id': 'P', 'app': 'pipeline:1'}], 'links': []},
                                  resolve, ('1',))

    def test_settings_on_the_node_itself_are_refused(self):
        with self.assertRaisesMessage(ValueError, 'ils se font dans le pipeline référencé'):
            expand([{'id': 'P', 'app': 'pipeline:1', 'params': {'text': 'x'}}])

    def test_a_dead_reference_is_refused_naming_the_node(self):
        with self.assertRaisesMessage(ValueError, 'Nœud « P » : pipeline 99 introuvable'):
            expand([{'id': 'P', 'app': 'pipeline:99'}])

    def test_an_identifier_longer_than_a_process_line_is_refused(self):
        with self.assertRaisesMessage(ValueError, f'> {NODE_ID_MAX} caractères'):
            expand([{'id': 'P' * (NODE_ID_MAX - 1), 'app': 'pipeline:1'}])


def _launch(user, graph, pipeline_id=None):
    from wama.studio.services.launch import launch_graph
    with mock.patch('wama.studio.tasks.run_pipeline_task.delay') as delay:
        delay.return_value = mock.Mock(id='fake-task')
        run, err = launch_graph(user, graph, pipeline_id=pipeline_id)
    return run, err, delay


class PipelineNodeInTheStudioTest(TestCase):
    def setUp(self):
        from wama.studio.models import StudioPipeline
        users = get_user_model().objects
        self.user = users.create_superuser('studio_pipeline_node', 'spn@example.invalid', 'x')
        self.other = users.create_user('studio_pipeline_node_other', 'spno@example.invalid', 'x')
        self.saved = StudioPipeline.objects.create(user=self.user, name='Filtre de trace', graph={
            'nodes': [{'id': 'n1', 'app': 'dataset_input', 'params': {}},
                      {'id': 'n2', 'app': FN, 'params': {}}],
            'links': [{'from': 'n1', 'to': 'n2', 'to_port': 'track'}]})
        self.key = f'pipeline:{self.saved.pk}'

    def test_the_launch_deploys_the_node_and_freezes_the_deployed_graph(self):
        run, err, delay = _launch(self.user, {'nodes': [{'id': 'P', 'app': self.key}],
                                              'links': []})
        self.assertIsNone(err)
        delay.assert_called_once()
        self.assertEqual(['P/n1', 'P/n2'], ids(run.graph))
        self.assertIn(('P/n1', 'P/n2', 'track'), edges(run.graph))

    def test_a_deleted_reference_is_refused_naming_node_and_key(self):
        pk = self.saved.pk
        self.saved.delete()
        run, err, delay = _launch(self.user, {'nodes': [{'id': 'P', 'app': self.key}],
                                              'links': []})
        self.assertIsNone(run)
        self.assertIn('Nœud « P »', err)
        self.assertIn(f'pipeline {pk} introuvable', err)
        delay.assert_not_called()

    def test_a_pipeline_the_account_does_not_see_is_not_resolved(self):
        from wama.studio.services.pipeline_nodes import resolver
        with self.assertRaisesMessage(ValueError, 'non visible pour ce compte'):
            resolver(self.other)(str(self.saved.pk))
        self.assertEqual('Filtre de trace', resolver(self.user)(str(self.saved.pk))[0])

    def test_only_a_saved_pipeline_is_a_pipeline_node(self):
        run, err, _ = _launch(self.user, {'nodes': [{'id': 'P', 'app': 'pipeline:cam_analyzer.analyse'}],
                                          'links': []})
        self.assertIsNone(run)
        self.assertIn("n'est pas un pipeline enregistré", err)

    def test_launching_a_saved_pipeline_that_contains_itself_is_refused(self):
        run, err, _ = _launch(self.user, {'nodes': [{'id': 'P', 'app': self.key}], 'links': []},
                              pipeline_id=self.saved.pk)
        self.assertIsNone(run)
        self.assertIn('se référence lui-même', err)

    def test_its_palette_entry_has_ports_derived_from_its_body(self):
        from wama.studio.services.palette import palette_nodes, unavailable_reason
        from wama.studio.services.pipeline_nodes import pipeline_palette_nodes
        offered = palette_nodes(self.user)
        offered.update(pipeline_palette_nodes(self.user, offered))
        node = offered[self.key]
        self.assertEqual(('pipeline', 'Filtre de trace'), (node['kind'], node['label']))
        self.assertEqual(['n1'], [p['id'] for p in node['inputs']], 'one port per entry card')
        self.assertEqual(offered['dataset_input']['output']['types'], node['inputs'][0]['types'])
        self.assertIs(False, node['output'], 'no exit card fed: no output port')
        self.assertIsNone(unavailable_reason(self.user, {'app': self.key}, offered))

    def test_the_palette_does_not_offer_it_before_the_canvas_knows_it(self):
        # Until step 2 (the « Pipelines » section and the aggregated state of a posed node), the
        # canvas would file these entries among the apps and show no state for them.
        from wama.studio.services.palette import palette_nodes
        self.assertFalse([k for k in palette_nodes(self.user) if k.startswith('pipeline:')])

    def test_an_unavailable_reference_says_why(self):
        from wama.studio.services.palette import unavailable_reason
        hidden = unavailable_reason(self.other, {'app': self.key}, {})
        self.assertEqual('inaccessible', hidden['code'])
        self.assertIn(f'pipeline « {self.saved.pk} »', hidden['message'])
        gone = unavailable_reason(self.user, {'app': 'pipeline:999999'}, {})
        self.assertEqual('unknown', gone['code'])
