"""A node the account's palette does not offer is KEPT when a pipeline opens, and refused at launch
(2026-10-19, `ROADMAP §16.11` piste 4).

It used to vanish in silence with its links (`addNode` returned `null`, `loadGraph` skipped it),
and saving the pipeline under the same name erased it in the database. Two halves, one rule:
- the canvas keeps it, marked unavailable, its settings and links intact, and says so on opening;
- the launch refuses it, wired or not, by the SAME rule as the palette (`services/palette.py`):
  an app closed to the account was only refused in the middle of the run (`execute_tool`), an
  unwired unknown function made the run fail (`tasks.py`, « absent du catalogue »).
"""
import importlib.util
import re
from pathlib import Path
from unittest import mock, skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

STUDIO_JS = Path(settings.BASE_DIR) / 'wama' / 'studio' / 'static' / 'studio' / 'js' / 'wama-studio.js'
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None


def _launch(user, graph):
    from wama.studio.services.launch import launch_graph
    with mock.patch('wama.studio.tasks.run_pipeline_task.delay') as delay:
        delay.return_value = mock.Mock(id='fake-task')
        run, err = launch_graph(user, graph)
    return run, err, delay


class PaletteIsTheLaunchRuleTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            'studio_unavailable', 'studio_unavailable@example.invalid', 'x')

    def _offered_app(self):
        from wama.studio.services.palette import palette_nodes
        apps = [k for k, v in palette_nodes(self.user).items() if 'kind' not in v]
        self.assertTrue(apps, 'precondition: the account is offered at least one app node')
        return apps[0]

    def test_the_palette_route_serves_the_palette_of_the_account(self):
        from wama.studio.services.palette import palette_nodes
        self.client.force_login(self.user)
        served = self.client.get(reverse('studio:api_nodes')).json()['nodes']
        self.assertEqual(set(palette_nodes(self.user)), set(served))

    def test_an_app_closed_to_the_account_is_refused_before_dispatch_naming_it(self):
        from wama.accounts import permissions
        app = self._offered_app()
        real = permissions.accessible

        def closed(user, kind, key, *a, **kw):
            return False if (kind, key) == ('app', app) else real(user, kind, key, *a, **kw)
        with mock.patch.object(permissions, 'accessible', side_effect=closed):
            run, err, delay = _launch(self.user, {'nodes': [{'id': 'n1', 'app': app}], 'links': []})
        self.assertIsNone(run)
        self.assertIn(app, err)
        self.assertIn('non accessible à ce compte', err)
        delay.assert_not_called()

    def test_an_unwired_unknown_function_is_refused_before_dispatch(self):
        run, err, delay = _launch(self.user, {
            'nodes': [{'id': 'n1', 'app': 'function:gone.from_the_catalogue'}], 'links': []})
        self.assertIsNone(run)
        self.assertIn('gone.from_the_catalogue', err)
        self.assertIn('inconnu de WAMA', err)
        delay.assert_not_called()

    def test_a_graph_of_offered_nodes_still_launches(self):
        run, err, delay = _launch(self.user, {
            'nodes': [{'id': 'n1', 'app': 'dataset_input', 'params': {}},
                      {'id': 'n2', 'app': 'function:ego_track_filter', 'params': {}}],
            'links': [{'from': 'n1', 'to': 'n2', 'to_port': 'track'}]})
        self.assertIsNone(err)
        delay.assert_called_once()


class CanvasKeepsTheUnavailableNodeTest(SimpleTestCase):
    def setUp(self):
        self.js = STUDIO_JS.read_text(encoding='utf-8')

    def test_opening_keeps_the_node_and_says_which_are_unavailable(self):
        self.assertIn('var a = apps[appId] || unavailable[appId];', self.js,
                      'addNode builds a node the palette does not offer, from its description')
        self.assertIn('var missing = describeUnavailable(graph || {});', self.js)
        # Both openings say it: a pipeline opened, and the draft restored on coming back.
        self.assertEqual(2, self.js.count('warnUnavailable(missing);'))
        self.assertIn('return apps[node.app] || unavailable[node.app] || {};', self.js,
                      'the inspector reads the description of a kept node')

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_the_description_is_read_from_the_graph_alone(self):
        from py_mini_racer import MiniRacer
        body = re.search(r'    function describeUnavailable\(graph\) \{.*?\n    \}\n', self.js, re.S)
        self.assertIsNotNone(body, 'describeUnavailable not found')
        ctx = MiniRacer()
        ctx.eval("var apps = {dataset_input: {label: 'Jeu'}}; var unavailable = {};"
                 "var UNAVAILABLE_TEXT = 'x';" + body.group(0))
        graph = {'nodes': [{'id': 'n1', 'app': 'dataset_input'},
                           {'id': 'n2', 'app': 'function:gone', 'params': {'k': 1}},
                           {'id': 'n3', 'app': 'function:gone'},
                           {'id': 'n4', 'app': 'closed_app'}],
                 'links': [{'from': 'n1', 'to': 'n2', 'to_port': 'track'},
                           {'from': 'n2', 'to': 'n4', 'to_port': ''}]}
        import json
        missing = ctx.eval(f'JSON.stringify(describeUnavailable({json.dumps(graph)}))')
        self.assertEqual(['function:gone', 'closed_app'], json.loads(missing),
                         'each unavailable key once, a known one never')
        gone = json.loads(ctx.eval("JSON.stringify(unavailable['function:gone'])"))
        self.assertTrue(gone['unavailable'])
        self.assertEqual(['track'], [p['id'] for p in gone['inputs']], 'its ports come from its links')
        self.assertNotEqual(False, gone['output'], 'it feeds a node: it keeps an output')
        closed = json.loads(ctx.eval("JSON.stringify(unavailable['closed_app'])"))
        self.assertEqual(['travail'], [p['id'] for p in closed['inputs']],
                         'a link that names no port enters the first port, as on loading')
        self.assertIs(False, closed['output'], 'it feeds nothing: no output port')
        self.assertIsNone(json.loads(ctx.eval("JSON.stringify(unavailable['dataset_input'] || null)")))
