"""D13 — le nœud `function` du kind `pipeline`, de bout en bout (2026-09-09).

`WAMA_DATA_WORLD §9undecies.2` (tranchée le 24/08) : UN seul kind `pipeline`, étendu d'un
nœud `function` ; la différence app / fonction se traite dans l'EXÉCUTEUR. Ces tests attestent
les trois lieux où la décision devait être codée — le validateur du kind, le lancement, le
dispatch de `run_pipeline_task` — et le fait que la facette estimateur VOYAGE avec la donnée
d'un nœud à l'autre (c'est ce que `fuse_estimates` lit).

Le test qui compte est `LExecuteurDispatcheSurLeKindTest.test_une_chaine_de_fonctions_pures_
s_execute_en_process_et_range_sa_sortie` : sans lui, D13 serait « codée » dans le schéma
seulement, c'est-à-dire nulle part.
"""
import math
import os
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, RequestFactory


def _csv_trace(path, n=40):
    """Ligne droite à cap 37°, 1 fixe/s, sans bruit : le cap filtré doit converger vers 37."""
    lat0, lon0, m_lat = 45.7578, 4.8320, 111_320.0
    m_lon = m_lat * math.cos(math.radians(lat0))
    h = math.radians(37.0)
    with open(path, 'w', encoding='utf-8') as fh:
        fh.write('time,lat,lon\n')
        for i in range(n):
            e, n_ = 3.0 * i * math.sin(h), 3.0 * i * math.cos(h)
            fh.write(f'{float(i)},{lat0 + n_ / m_lat:.8f},{lon0 + e / m_lon:.8f}\n')


class LeKindPipelineAccepteUnNoeudFonctionTest(SimpleTestCase):
    def test_le_validateur_connait_le_kind_function_et_exige_sa_cle(self):
        from wama.common.manifests.builtin.pipeline import validate_pipeline_body
        ok = {'nodes': [{'id': 'a', 'kind': 'function', 'function': 'ego_track_filter'}], 'links': []}
        self.assertEqual(validate_pipeline_body(ok), [])
        sans_cle = {'nodes': [{'id': 'a', 'kind': 'function'}], 'links': []}
        errs = validate_pipeline_body(sans_cle)
        self.assertTrue(any("'function'" in e for e in errs), errs)
        inconnu = {'nodes': [{'id': 'a', 'kind': 'data_process', 'app': 'x'}], 'links': []}
        self.assertTrue(any('invalide' in e for e in validate_pipeline_body(inconnu)))

    def test_la_forme_canvas_se_traduit_en_kind_function_au_manifeste(self):
        """`function:<clé>` est une convention de PALETTE ; elle ne franchit pas le manifeste."""
        from wama.common.manifests.builtin.pipeline import graph_to_body, node_kind, function_key
        graph = {'nodes': [{'id': 'n1', 'app': 'dataset_input', 'x': 1, 'y': 2},
                           {'id': 'n2', 'app': 'function:ego_track_filter', 'params': {'sigma_m': '1'}},
                           {'id': 'n3', 'app': 'studio_output'}],
                 'links': [{'from': 'n1', 'to': 'n2', 'to_port': 'track'}, {'from': 'n2', 'to': 'n3'}]}
        body = graph_to_body(graph)
        kinds = [n['kind'] for n in body['nodes']]
        self.assertEqual(kinds, ['source', 'function', 'sink'])
        fn = body['nodes'][1]
        self.assertEqual((fn['function'], fn['app'], fn['params']), ('ego_track_filter', None, {'sigma_m': '1'}))
        self.assertEqual(body['layout'], {'n1': {'x': 1, 'y': 2}})
        # les deux formes se relisent par les MÊMES lecteurs
        self.assertEqual(node_kind(fn), 'function')
        self.assertEqual(function_key(fn), 'ego_track_filter')
        self.assertEqual(function_key(graph['nodes'][1]), 'ego_track_filter')
        self.assertEqual(node_kind({'app': 'imager'}), 'app')


class LeLancementAccepteUnNoeudFonctionTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('studio_fn', password='x')

    def _launch(self, graph):
        from wama.studio.services.launch import launch_graph
        with mock.patch('wama.studio.tasks.run_pipeline_task.delay') as delay:
            delay.return_value = mock.Mock(id='fake-task')
            return launch_graph(self.user, graph)

    def test_un_graphe_de_fonctions_seules_est_lancable(self):
        """Avant D13 : « Aucun nœud-app exécutable » — une fonction du catalogue n'était rien."""
        run, err = self._launch({
            'nodes': [{'id': 'n1', 'app': 'dataset_input', 'params': {}},
                      {'id': 'n2', 'app': 'function:ego_track_filter', 'params': {}}],
            'links': [{'from': 'n1', 'to': 'n2', 'to_port': 'track'}]})
        self.assertIsNone(err)
        self.assertEqual(run.task_id, 'fake-task')

    def test_une_fonction_inconnue_connectee_est_refusee_avant_dispatch(self):
        run, err = self._launch({
            'nodes': [{'id': 'n1', 'app': 'dataset_input'}, {'id': 'n2', 'app': 'function:nexiste.pas'}],
            'links': [{'from': 'n1', 'to': 'n2'}]})
        self.assertIsNone(run)
        self.assertIn('non exécutable', err)


class LExecuteurDispatcheSurLeKindTest(TestCase):
    def setUp(self):
        from django.conf import settings
        self.user = get_user_model().objects.create_user('studio_exec', password='x')
        rel = os.path.join('studio_tests', f'trace_{self.user.pk}.csv')
        abs_path = os.path.join(settings.MEDIA_ROOT, rel)
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        _csv_trace(abs_path)
        self.rel = rel.replace(os.sep, '/')

    def _run(self, graph):
        from wama.studio.models import StudioRun
        from wama.studio.tasks import run_pipeline_task
        run = StudioRun.objects.create(user=self.user, graph=graph)
        run_pipeline_task(run.pk)      # appel DIRECT (in-process), comme le scénario nocturne
        run.refresh_from_db()
        return run

    def test_une_chaine_de_fonctions_pures_s_execute_en_process_et_range_sa_sortie(self):
        """dataset_input → ego_track_filter (pure) → fuse_estimates (pure, lit la facette que
        l'exécuteur a posée) → Sortie (CSV en médiathèque). Aucune file Celery : un nœud
        fonction pure est une transformation SYNCHRONE."""
        from wama.media_library.models import UserAsset
        run = self._run({
            'nodes': [
                {'id': 'n1', 'app': 'dataset_input',
                 'params': {'asset_path': self.rel, 'data_type': 'geo_track'}},
                {'id': 'n2', 'app': 'function:ego_track_filter', 'params': {'sigma_m': '1.0'}},
                {'id': 'n3', 'app': 'function:fuse_estimates', 'params': {}},
                {'id': 'n4', 'app': 'studio_output', 'params': {'asset_name': 'cap-fusionne'}},
            ],
            'links': [{'from': 'n1', 'to': 'n2', 'to_port': 'track'},
                      {'from': 'n2', 'to': 'n3', 'to_port': 'estimates'},
                      {'from': 'n3', 'to': 'n4', 'to_port': 'work'}]})
        self.assertEqual(run.status, 'SUCCESS', run.error_message)
        etats = run.node_states
        self.assertTrue(etats['n2']['output'].startswith('geo_track · 40 ligne(s)'), etats['n2'])
        self.assertIn('heading_f', etats['n2']['output'])
        self.assertTrue(etats['n3']['output'].startswith('timeseries · '), etats['n3'])
        self.assertIn('heading_sigma', etats['n3']['output'])
        asset = UserAsset.objects.get(user=self.user, name='cap-fusionne')
        self.assertEqual(asset.asset_type, 'document')
        with open(asset.file.path, encoding='utf-8') as fh:
            header = fh.readline().strip()
            rows = [l.split(',') for l in fh.read().strip().splitlines()]
        self.assertEqual(header, 'time,heading,heading_sigma,n_sources')
        caps = [float(r[1]) for r in rows[5:]]
        self.assertTrue(all(abs(c - 37.0) < 1.0 for c in caps), caps[:5])
        self.assertTrue(all(float(r[2]) == 3.0 for r in rows), "σ = celle déclarée sur le port (held, 3°)")
        try:
            asset.file.delete(save=False)
        except Exception:
            pass
        asset.delete()

    def test_un_amont_non_type_est_refuse_avec_un_message_qui_nomme_la_porte(self):
        run = self._run({
            'nodes': [{'id': 'n1', 'app': 'text_input', 'params': {'text': 'bonjour'}},
                      {'id': 'n2', 'app': 'function:ego_track_filter', 'params': {}}],
            'links': [{'from': 'n1', 'to': 'n2', 'to_port': 'track'}]})
        self.assertEqual(run.status, 'FAILURE')
        self.assertIn('Jeu de données', run.error_message)

    def test_une_fonction_app_bound_est_un_job_qui_exige_ses_arguments(self):
        """`app`-bound → `impl` + poll. Sans `session_id`, rien ne part en file : l'erreur
        nomme l'argument requis, lu par introspection de la tâche."""
        run = self._run({
            'nodes': [{'id': 'n1', 'app': 'function:cam_analyzer.distance', 'params': {}}],
            'links': []})
        self.assertEqual(run.status, 'FAILURE')
        self.assertIn('session_id', run.error_message)


class LaPaletteServeLesFonctionsTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user('studio_pal', password='x')

    def test_api_nodes_expose_les_fonctions_avec_la_forme_des_apps_et_la_taxonomie(self):
        from wama.studio.views import api_nodes
        req = RequestFactory().get('/studio/api/nodes/')
        req.user = self.user
        data = api_nodes(req)
        import json
        d = json.loads(data.content)
        node = d['nodes']['function:ego_track_filter']
        self.assertEqual(node['kind'], 'function')
        self.assertEqual(node['binding'], 'pure')
        self.assertEqual([p['id'] for p in node['inputs']], ['track'])
        self.assertEqual(set(node['inputs'][0]) >= {'id', 'label', 'group', 'types', 'multi'}, True)
        self.assertIn('table', node['output']['types'], "super-types servis : geo_track entre dans table")
        self.assertIn('geo_track', d['data_types'])
        self.assertIn('function:cam_analyzer.distance', d['nodes'])

    def test_les_params_d_un_noeud_fonction_viennent_des_ParamSpec_et_de_la_signature(self):
        from wama.studio.views import function_node_params_specs
        specs = function_node_params_specs()
        pure = {p['name'] for p in specs['function:ego_track_filter']}
        self.assertEqual(pure, {'sigma_a', 'sigma_m', 'heading_min_speed_mps'})
        app = [p['name'] for p in specs['function:cam_analyzer.distance']]
        self.assertEqual(app[0], 'session_id', "l'argument requis de la tâche, par introspection")
