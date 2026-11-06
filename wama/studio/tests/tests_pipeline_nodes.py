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
        """Its settings are those of its inner nodes, by id (the override, 2026-11-06): a setting
        of its own names no inner node and is refused by name."""
        with self.assertRaisesMessage(ValueError, 'réglages surchargés du nœud « text »'):
            expand([{'id': 'P', 'app': 'pipeline:1', 'params': {'text': 'x'}}])
        with self.assertRaisesMessage(ValueError, "« s » n'en est pas un ensemble"):
            expand([{'id': 'P', 'app': 'pipeline:1', 'params': {'s': 'x'}}])
        with self.assertRaisesMessage(ValueError, 'reçu list'):
            expand([{'id': 'P', 'app': 'pipeline:1', 'params': ['x']}])

    def test_a_dead_reference_is_refused_naming_the_node(self):
        with self.assertRaisesMessage(ValueError, 'Nœud « P » : pipeline 99 introuvable'):
            expand([{'id': 'P', 'app': 'pipeline:99'}])

    def test_an_identifier_longer_than_a_process_line_is_refused(self):
        with self.assertRaisesMessage(ValueError, f'> {NODE_ID_MAX} caractères'):
            expand([{'id': 'P' * (NODE_ID_MAX - 1), 'app': 'pipeline:1'}])


class PipelineNodeOverrideTest(SimpleTestCase):
    """The OVERRIDE (2026-11-06, Fabien's decision): the shape of a batch daughter's own values.
    The reference is the referenced pipeline, read at every launch; the node keeps only what
    differs, `{<deployed inner id>: {setting: value}}`, laid over the inner node's settings."""

    def test_an_override_is_laid_over_the_inner_settings_and_the_rest_follows(self):
        SAVED['9'] = ('nine', {'nodes': [{'id': 's', 'app': 'text_input',
                                          'params': {'text': 'ref', 'lang': 'fr'}}], 'links': []})
        try:
            out = expand([{'id': 'P', 'app': 'pipeline:9', 'params': {'s': {'text': 'mine'}}}])
            self.assertEqual({'text': 'mine', 'lang': 'fr'}, out['nodes'][0]['params'])
            SAVED['9'][1]['nodes'][0]['params']['lang'] = 'en'
            out = expand([{'id': 'P', 'app': 'pipeline:9', 'params': {'s': {'text': 'mine'}}}])
            self.assertEqual({'text': 'mine', 'lang': 'en'}, out['nodes'][0]['params'],
                             'what the author changes and the node did not override follows')
        finally:
            del SAVED['9']

    def test_an_override_never_touches_the_saved_reference(self):
        out = expand([{'id': 'P', 'app': 'pipeline:1', 'params': {'s': {'text': 'mine'}}}])
        self.assertEqual('mine', out['nodes'][0]['params']['text'])
        self.assertEqual({'text': 'kept'}, SAVED['1'][1]['nodes'][0]['params'])
        self.assertEqual({'text': 'kept'}, expand([{'id': 'P', 'app': 'pipeline:1'}])['nodes'][0]['params'])

    def test_a_deeper_node_is_overridden_by_its_path_above_its_own_pipeline(self):
        SAVED['8'] = ('eight', {'nodes': [{'id': 'in', 'app': 'pipeline:1',
                                           'params': {'s': {'text': 'author'}}}], 'links': []})
        try:
            self.assertEqual('author', expand([{'id': 'X', 'app': 'pipeline:8'}])['nodes'][0]['params']['text'])
            out = expand([{'id': 'X', 'app': 'pipeline:8', 'params': {'in/s': {'text': 'outer'}}}])
            self.assertEqual(('X/in/s', 'outer'), (out['nodes'][0]['id'], out['nodes'][0]['params']['text']),
                             'the outer node overrides the override of the level below')
        finally:
            del SAVED['8']

    def test_an_orphan_override_is_refused_naming_the_nodes_there_are(self):
        with self.assertRaises(ValueError) as refused:
            expand([{'id': 'P', 'app': 'pipeline:1', 'params': {'gone': {'text': 'x'}}}])
        self.assertIn('« gone », que le pipeline « one » n\'a pas', str(refused.exception))
        self.assertIn('nœuds : f, o, s', str(refused.exception))

    def test_an_override_on_a_node_a_link_replaces_is_refused(self):
        with self.assertRaisesMessage(ValueError, "« s », qu'un lien du pipeline remplace"):
            expand([{'id': 'd', 'app': 'dataset_input'},
                    {'id': 'P', 'app': 'pipeline:1', 'params': {'s': {'text': 'x'}}}],
                   [{'from': 'd', 'to': 'P', 'to_port': 's'}])
        out = expand([{'id': 'd', 'app': 'dataset_input'},
                      {'id': 'P', 'app': 'pipeline:1', 'params': {'s': {}}}],
                     [{'from': 'd', 'to': 'P', 'to_port': 's'}])
        self.assertNotIn('P/s', ids(out), 'an emptied override is no override')


class FoldedStatesTest(SimpleTestCase):
    """The state of a FOLDED node: the rule of the cards (`process_runs.aggregate`) read by the
    adapter of `AppPipeline.shown_state` — the run is the truth of what is IN FLIGHT."""

    GRAPH = {'nodes': [{'id': 'P/a'}, {'id': 'P/b'}, {'id': 'P/x/c'}, {'id': 'free'}]}

    def fold(self, states, run_status):
        from wama.studio.services.pipeline_nodes import folded_states
        return folded_states(self.GRAPH, states, run_status)

    def test_members_come_from_the_graph_and_one_never_started_is_pending(self):
        from wama.common.models import JOB_FAILURE, JOB_PENDING, JOB_SUCCESS
        out = self.fold({'P/a': {'status': JOB_SUCCESS}}, JOB_FAILURE)
        self.assertEqual(['P'], list(out), 'one group per top node, nested ids included')
        self.assertEqual(3, out['P']['nodes_total'])
        self.assertEqual(JOB_PENDING, out['P']['status'],
                         'one success and two never started is NOT a success')

    def test_between_two_members_of_a_running_run_it_is_running(self):
        from wama.common.models import JOB_AWAITING_RESOURCES, JOB_RUNNING, JOB_SUCCESS
        out = self.fold({'P/a': {'status': JOB_SUCCESS}}, JOB_RUNNING)
        self.assertEqual(JOB_RUNNING, out['P']['status'], 'never back to pending between members')
        waiting = self.fold({'P/a': {'status': JOB_SUCCESS},
                             'P/b': {'status': JOB_AWAITING_RESOURCES}}, JOB_RUNNING)
        self.assertEqual(JOB_AWAITING_RESOURCES, waiting['P']['status'])

    def test_not_started_stays_pending_and_done_is_the_aggregate(self):
        from wama.common.models import JOB_FAILURE, JOB_PENDING, JOB_RUNNING, JOB_SUCCESS
        self.assertEqual(JOB_PENDING, self.fold({}, JOB_RUNNING)['P']['status'])
        done = {m: {'status': JOB_SUCCESS} for m in ('P/a', 'P/b', 'P/x/c')}
        self.assertEqual(JOB_SUCCESS, self.fold(done, JOB_RUNNING)['P']['status'])
        failed = dict(done, **{'P/b': {'status': JOB_FAILURE}})
        self.assertEqual(JOB_FAILURE, self.fold(failed, JOB_RUNNING)['P']['status'])


class CanvasPoseTheNodeFromPipelinesTest(SimpleTestCase):
    """The canvas: no second section — a saved pipeline of « Pipelines » is DRAGGED to pose it as
    a node, its click still opens it (ROUTE §10.6 5.4)."""

    def setUp(self):
        from django.conf import settings
        from pathlib import Path
        self.js = (Path(settings.BASE_DIR) / 'wama' / 'studio' / 'static' / 'studio' / 'js'
                   / 'wama-studio.js').read_text(encoding='utf-8')

    def _palette(self, apps, saved):
        import json
        import re
        from py_mini_racer import MiniRacer
        block = re.search(r'    var PALETTE_MIME = .*?\n    function renderPalette\(\) \{.*?\n    \}\n',
                          self.js, re.S).group(0)
        ctx = MiniRacer()
        ctx.eval("""
            function fakeEl(tag) { return { tag: tag, children: [], dataset: {}, style: { setProperty: function () {} },
                listeners: {}, appendChild: function (c) { this.children.push(c); return c; },
                addEventListener: function (k, f) { this.listeners[k] = f; },
                querySelectorAll: function () { return []; } }; }
            var document = { createElement: fakeEl };
            var localStorage = { getItem: function () { return null; }, setItem: function () {} };
            function el(tag, cls, html) { var e = fakeEl(tag); e.className = cls; e.innerHTML = html; return e; }
            function isBuiltin(a) { return a && (a.kind === 'source' || a.kind === 'sink'); }
            function openPipeline() {} function functionAppFilter() { return null; }
            function applyFunctionFilter() {} function appLabel(k) { return k; }
            var canvas = null, paletteList = fakeEl('div'), declaredPipelines = [];
        """)
        ctx.eval(f'var apps = {json.dumps(apps)}; var savedPipelines = {json.dumps(saved)};' + block)
        ctx.eval('renderPalette();')
        return ctx

    def test_a_pipeline_node_is_no_app_and_its_saved_pipeline_is_draggable(self):
        import importlib.util
        import json
        if importlib.util.find_spec('py_mini_racer') is None:
            self.skipTest('py_mini_racer absent de ce venv')
        apps = {'imager': {'label': 'Imager'},
                'pipeline:7': {'label': 'Mon pipeline', 'kind': 'pipeline', 'pipeline': '7'}}
        saved = [{'id': 7, 'name': 'Mon pipeline', 'nodes': 2, 'updated_at': ''},
                 {'id': 8, 'name': 'Pas offert', 'nodes': 1, 'updated_at': ''}]
        ctx = self._palette(apps, saved)
        sections = 'paletteList.children.map(function (s) { return s.dataset.section; })'
        self.assertEqual(['outputs', 'pipelines', 'apps'], json.loads(ctx.eval(f'JSON.stringify({sections})')),
                         'no second section for the pipeline nodes')
        app_items = ctx.eval("JSON.stringify(paletteList.children.filter(function (s) {"
                             " return s.dataset.section === 'apps'; })[0].children.slice(1)"
                             ".map(function (i) { return i.innerHTML; }))")
        self.assertNotIn('Mon pipeline', app_items, 'a pipeline node is not filed among the apps')
        pipes = "paletteList.children.filter(function (s) { return s.dataset.section === 'pipelines'; })[0].children.slice(1)"
        draggable = json.loads(ctx.eval(f"JSON.stringify({pipes}.map(function (i) {{ return !!i.draggable; }}))"))
        self.assertEqual([True, False], draggable, 'draggable only when the palette offers it as a node')
        dropped = ctx.eval(f"var got = null; {pipes}[0].listeners.dragstart({{ dataTransfer: {{ setData: "
                           f"function (t, v) {{ got = v; }} }} }}); got")
        self.assertEqual('pipeline:7', dropped, 'the drag poses the node, never a copy')
        self.assertIn('click', ctx.eval(f"JSON.stringify(Object.keys({pipes}[0].listeners))"),
                      'the click still opens it')

    def _overrides(self):
        import importlib.util
        import re
        if importlib.util.find_spec('py_mini_racer') is None:
            self.skipTest('py_mini_racer absent de ce venv')
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        for name in ('overrideAfterGesture', 'orphanOverrides'):
            ctx.eval(re.search(rf'    function {name}\(.*?\n    \}}\n', self.js, re.S).group(0))
        return ctx

    def test_the_inspector_keeps_only_what_differs_from_the_referenced_pipeline(self):
        import json
        ctx = self._overrides()

        def after(own, reference, name, value):
            return json.loads(ctx.eval(f'JSON.stringify(overrideAfterGesture({json.dumps(own)}, '
                                       f'{json.dumps(reference)}, {json.dumps(name)}, {json.dumps(value)}))'))
        self.assertEqual({'text': 'mine'}, after({}, {'text': 'ref'}, 'text', 'mine'))
        self.assertEqual({}, after({'text': 'mine'}, {'text': 'ref'}, 'text', 'ref'),
                         'back to the reference value: no longer its own')
        self.assertEqual({'steps': 8}, after({}, {}, 'steps', 8),
                         'a setting the pipeline leaves to the app is its own once decided')
        self.assertEqual({'text': 'mine'}, after({'text': 'mine'}, {'n': 3}, 'n', '3'),
                         'the reference compares as text, like `batch_settings.own_settings`')

    def test_the_inspector_names_an_orphan_override_before_the_launch(self):
        import json
        ctx = self._overrides()
        self.assertEqual(['gone'], json.loads(ctx.eval(
            "JSON.stringify(orphanOverrides({s: {text: 'x'}, gone: {a: 1}}, [{id: 's'}, {id: 'f'}]))")))
        self.assertIn("function mountPipelineOverrides(wrap, node)", self.js)
        self.assertIn("var members = metaOf(node).members;", self.js)

    def test_the_inspector_reads_the_content_and_opens_by_the_one_opener(self):
        self.assertIn("schema.push({ section: 'Contenu', rows: pipelineContentRows(node, a.pipeline) });",
                      self.js)
        self.assertIn("onClick: function () { openPipeline(a.pipeline); } });", self.js)
        self.assertIn("api('/studio/api/pipelines/' + encodeURIComponent(key) + '/')", self.js)
        self.assertIn("var st = lastNodeStates[node.id + '/' + n.id];", self.js)


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
        offered = palette_nodes(self.user)
        node = offered[self.key]
        self.assertEqual(('pipeline', 'Filtre de trace'), (node['kind'], node['label']))
        self.assertEqual(['n1'], [p['id'] for p in node['inputs']], 'one port per entry card')
        self.assertEqual(offered['dataset_input']['output']['types'], node['inputs'][0]['types'])
        self.assertIs(False, node['output'], 'no exit card fed: no output port')
        self.assertIsNone(unavailable_reason(self.user, {'app': self.key}, offered))

    def test_its_palette_entry_carries_the_reference_of_the_override(self):
        from wama.studio.services.palette import palette_nodes
        self.saved.graph['nodes'][1]['params'] = {'sigma_a': 2.0}
        self.saved.save()
        members = palette_nodes(self.user)[self.key]['members']
        self.assertEqual([('n1', 'source', {}), ('n2', 'function', {'sigma_a': 2.0})],
                         [(m['id'], m['role'], m['params']) for m in members])

    def test_the_launch_lays_the_override_and_freezes_it_in_the_run(self):
        run, err, _ = _launch(self.user, {'nodes': [
            {'id': 'P', 'app': self.key, 'params': {'n2': {'sigma_a': 3.5}}}], 'links': []})
        self.assertIsNone(err)
        deployed = {n['id']: n for n in run.graph['nodes']}
        self.assertEqual(3.5, deployed['P/n2']['params']['sigma_a'])
        self.saved.refresh_from_db()
        self.assertEqual({}, self.saved.graph['nodes'][1]['params'], 'the referenced pipeline is untouched')

    def test_launching_with_an_orphan_override_is_refused_by_name(self):
        run, err, delay = _launch(self.user, {'nodes': [
            {'id': 'P', 'app': self.key, 'params': {'gone': {'x': 1}}}], 'links': []})
        self.assertIsNone(run)
        self.assertIn('« gone »', err)
        delay.assert_not_called()

    def test_the_palette_offers_only_what_the_account_sees(self):
        from wama.studio.services.palette import palette_nodes
        self.assertIn(self.key, palette_nodes(self.user))
        self.assertNotIn(self.key, palette_nodes(self.other), 'a private pipeline of another account')

    def test_the_run_status_shows_the_folded_node(self):
        from wama.common.models import JOB_RUNNING, JOB_SUCCESS
        from wama.studio.models import StudioRun
        run = StudioRun.objects.create(
            user=self.user, status=JOB_RUNNING,
            graph={'nodes': [{'id': 'P/n1', 'app': 'dataset_input'}, {'id': 'P/n2', 'app': FN}],
                   'links': []},
            node_states={'P/n1': {'status': JOB_SUCCESS}})
        self.client.force_login(self.user)
        states = self.client.get(f'/studio/api/run/{run.pk}/').json()['node_states']
        self.assertEqual({'status': JOB_RUNNING, 'nodes_done': 1, 'nodes_total': 2}, states['P'])
        self.assertEqual(JOB_SUCCESS, states['P/n1']['status'], 'the inner states are kept')

    def test_saving_a_pipeline_that_contains_itself_is_refused(self):
        self.client.force_login(self.user)
        url = '/studio/api/pipelines/'
        cyclic = {'name': self.saved.name,
                  'graph': {'nodes': [{'id': 'P', 'app': self.key}], 'links': []}}
        response = self.client.post(url, cyclic, content_type='application/json')
        self.assertEqual(400, response.status_code)
        self.assertIn('se référence lui-même', response.json()['error'])
        self.saved.refresh_from_db()
        self.assertEqual('dataset_input', self.saved.graph['nodes'][0]['app'], 'nothing written')
        # Through another pipeline: B references A, then A is saved referencing B.
        b = self.client.post(url, {'name': 'B', 'graph': {'nodes': [{'id': 'x', 'app': self.key}],
                                                         'links': []}},
                             content_type='application/json').json()['id']
        through = {'name': self.saved.name,
                   'graph': {'nodes': [{'id': 'y', 'app': f'pipeline:{b}'}], 'links': []}}
        response = self.client.post(url, through, content_type='application/json')
        self.assertEqual(400, response.status_code)
        self.assertIn(f'{self.saved.pk} → {b} → {self.saved.pk}', response.json()['error'])

    def test_an_incomplete_draft_is_saved(self):
        self.client.force_login(self.user)
        draft = {'name': 'Brouillon', 'graph': {'nodes': [{'id': 'P', 'app': 'pipeline:999999'}],
                                                'links': []}}
        response = self.client.post('/studio/api/pipelines/', draft, content_type='application/json')
        self.assertEqual(200, response.status_code, 'a dead reference only breaks the launch')

    def test_an_unavailable_reference_says_why(self):
        from wama.studio.services.palette import unavailable_reason
        hidden = unavailable_reason(self.other, {'app': self.key}, {})
        self.assertEqual('inaccessible', hidden['code'])
        self.assertIn(f'pipeline « {self.saved.pk} »', hidden['message'])
        gone = unavailable_reason(self.user, {'app': 'pipeline:999999'}, {})
        self.assertEqual('unknown', gone['code'])

    def test_a_pipeline_that_does_not_deploy_says_the_launch_reason(self):
        from wama.studio.models import StudioPipeline
        from wama.studio.services.palette import palette_nodes, unavailable_reason
        looped = StudioPipeline.objects.create(user=self.user, name='Boucle', graph={})
        looped.graph = {'nodes': [{'id': 'x', 'app': f'pipeline:{looped.pk}'}], 'links': []}
        looped.save()
        key = f'pipeline:{looped.pk}'
        offered = palette_nodes(self.user)
        self.assertNotIn(key, offered)
        reason = unavailable_reason(self.user, {'app': key}, offered)
        self.assertEqual(('not_deployable', 'pipeline qui ne se déploie pas'),
                         (reason['code'], reason['label']))
        self.assertIn('se référence lui-même', reason['message'], 'the exact reason of the launch')
