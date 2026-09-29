"""Ouvrir au studio un pipeline DÉCLARÉ par une app (ROUTE §10.6 2.2, 2026-09-29).

« Tout ce qui s'exécute dans une file doit pouvoir s'ouvrir au studio » : le kind `pipeline`
savait traduire un graphe canvas en manifeste (`graph_to_body`), pas l'inverse, et le studio ne
listait que les pipelines de la base. 1ᵉʳ cas : les passes du cam_analyzer (complet + 2 étages).
"""
import json
from types import SimpleNamespace

from django.test import SimpleTestCase, RequestFactory

from wama.common.manifests.builtin.pipeline import body_to_graph, graph_to_body, extract_pipeline


class BodyToGraphTest(SimpleTestCase):
    BODY = {
        'nodes': [{'id': 'a', 'kind': 'function', 'app': None, 'function': 'cam_analyzer.extraction',
                   'params': {'stage': 'analyse'}},
                  {'id': 'b', 'kind': 'app', 'app': 'transcriber', 'params': {}},
                  {'id': 'c', 'kind': 'sink', 'app': 'studio_output', 'params': {}}],
        'links': [{'from': 'a', 'to': 'b', 'to_port': 'travail'},
                  {'from': 'b', 'to': 'c', 'to_port': None}],
        'layout': {'a': {'x': 10, 'y': 20}},
    }

    def test_the_canvas_form_translates_back_to_the_same_manifest(self):
        g = body_to_graph(self.BODY)
        self.assertEqual(g['nodes'][0]['app'], 'function:cam_analyzer.extraction')
        back = graph_to_body(g)
        self.assertEqual(back['nodes'], self.BODY['nodes'])
        self.assertEqual(back['links'], self.BODY['links'])
        self.assertEqual(back['layout']['a'], {'x': 10, 'y': 20})     # position déclarée gardée

    def test_nodes_without_layout_are_laid_out_by_depth_without_overlap(self):
        m = extract_pipeline('cam_analyzer')
        g = body_to_graph(m['body'])
        pos = {n['id']: (n['x'], n['y']) for n in g['nodes']}
        self.assertEqual(len(set(pos.values())), len(pos))           # aucun chevauchement
        for l in g['links']:                                          # l'aval à droite de l'amont
            self.assertLess(pos[l['from']][0], pos[l['to']][0], l)

    def test_a_dependency_link_lands_on_the_port_whose_type_matches(self):
        g = body_to_graph(extract_pipeline('cam_analyzer')['body'])
        ports = {(l['from'], l['to']): l['to_port'] for l in g['links']}
        # `depth` a deux entrées (vidéo, détections) : la dépendance à YOLO porte les détections
        self.assertEqual(ports[('yolo_detect', 'depth')], 'detections')


class DeclaredPipelinesApiTest(SimpleTestCase):
    def _get(self, view, *args):
        req = RequestFactory().get('/studio/api/declared-pipelines/')
        req.user = SimpleNamespace(is_authenticated=True, id=1)
        return view(req, *args)

    def test_the_studio_lists_the_cam_analyzer_pipelines(self):
        from wama.studio import views
        data = json.loads(self._get(views.api_declared_pipelines).content)
        keys = {p['key'] for p in data['pipelines']}
        self.assertTrue({'cam_analyzer', 'cam_analyzer.analyse', 'cam_analyzer.calcul'} <= keys)

    def test_a_declared_pipeline_opens_as_a_canvas_graph(self):
        from wama.studio import views
        from wama_lab.cam_analyzer.utils.pass_tracking import PASSES
        d = json.loads(self._get(views.api_declared_pipeline_detail, 'cam_analyzer').content)
        self.assertTrue(d['declared'])
        self.assertEqual(len(d['graph']['nodes']), len(PASSES))
        self.assertTrue(all(n['app'].startswith('function:cam_analyzer.') for n in d['graph']['nodes']))

    def test_an_unknown_key_is_a_404(self):
        from wama.studio import views
        self.assertEqual(self._get(views.api_declared_pipeline_detail, 'nope').status_code, 404)


class CamAnalyzerStagesTest(SimpleTestCase):
    def test_no_analysis_pass_depends_on_a_calculation(self):
        """Les deux étages se chaînent en sous-pipelines (ROUTE §10.6 3.4) : une ANALYSE qui
        dépend d'un CALCUL le rendrait impossible (cas d'`ortho_recalage` le 2026-09-28)."""
        from wama_lab.cam_analyzer.utils import pass_tracking as pt
        for p in pt.PASSES:
            if p.stage == 'analyse':
                for d in p.depends_on:
                    self.assertEqual(pt._STAGE[d], 'analyse', f'{p.key} ← {d}')

    def test_the_two_stages_cover_every_pass_exactly_once(self):
        from wama_lab.cam_analyzer.utils import pass_tracking as pt
        a = [n['id'] for n in extract_pipeline('cam_analyzer.analyse')['body']['nodes']]
        c = [n['id'] for n in extract_pipeline('cam_analyzer.calcul')['body']['nodes']]
        self.assertEqual(sorted(a + c), sorted(pt.ORDER))
        self.assertFalse(set(a) & set(c))

    def test_the_declared_keys_are_those_of_the_registry(self):
        from wama.common.manifests.builtin.pipeline import registered_pipeline_keys
        from wama_lab.cam_analyzer.utils.pass_tracking import PIPELINES
        self.assertTrue(set(PIPELINES) <= set(registered_pipeline_keys()))
