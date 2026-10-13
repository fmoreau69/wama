"""Les réglages d'un nœud du Studio : UNE forme (`Param`), UN rendu (`WamaParams`), UNE porte.

ROUTE §10.6 point 3.3bis, marche R1 (2026-10-12). Avant : trois projections vers un format propre
au Studio (`params_spec`), rendues par un renderer propre (`renderNodeParams`) qui faisait d'un
curseur un champ texte et perdait conditions, groupes, aides et bornes ; une coercition propre
qui ignorait les bornes ; des nœuds intégrés sans aucune. Ces tests tiennent :
  • la garde de la route — tout nœud que le Studio offre a un schéma que `WamaParams` sait rendre
    (aucun type inconnu, aucune source d'options non résolue) ;
  • la porte — au lancement (avant dispatch) comme à l'exécution, refus nommés ;
  • la non-régression — plus aucun rendu de réglages propre au Studio.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import re
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TestCase

BASE = Path(settings.BASE_DIR)
PARAMS_JS = BASE / 'wama/common/static/common/js/wama-params.js'
STUDIO_JS = BASE / 'wama/studio/static/studio/js/wama-studio.js'


def _registered_renderers() -> set:
    return set(re.findall(r"registerRenderer\('([a-z_]+)'", PARAMS_JS.read_text(encoding='utf-8')))


def _resolved_sources() -> set:
    """Les deux registres de sources d'options, lus tels qu'ils s'écrivent (même lecture que
    `tests_codegen_templates`) : endpoints `OPTION_SOURCES`, données de page `PAGE_OPTION_SOURCES`."""
    src = PARAMS_JS.read_text(encoding='utf-8')
    return (set(re.findall(r"^\s*(\w+):\s*'[^']+',", src, re.M))
            | set(re.findall(r'^\s*(\w+):\s*function', src, re.M)))


class EveryNodeRendersWithTheCommonEngineTest(TestCase):
    """LA garde de R1 : un nœud offert dont un réglage aurait un type que `WamaParams` ne connaît
    pas retomberait en champ texte — exactement ce que la route retire."""

    def test_every_offered_node_has_a_schema_the_common_renderer_knows(self):
        from wama.studio.services.node_params import offered_node_schemas
        renderers, sources = _registered_renderers(), _resolved_sources()
        schemas = offered_node_schemas()
        self.assertGreater(len(schemas), 100, 'apps, fonctions du catalogue et nœuds intégrés')
        problems = []
        for node, schema in schemas.items():
            for p in schema['params']:
                if p.get('type') not in renderers:
                    problems.append(f"{node}.{p.get('name')} : type « {p.get('type')} »")
                if p.get('options_source') and p['options_source'] not in sources:
                    problems.append(f"{node}.{p.get('name')} : source « {p['options_source']} »")
        self.assertEqual([], problems)

    def test_the_builtin_nodes_are_offered(self):
        from wama.studio.services.node_params import offered_node_schemas
        schemas = offered_node_schemas()
        for node in ('text_input', 'media_import', 'dataset_input', 'data_connector',
                     'data_export', 'studio_output'):
            self.assertIn(node, schemas)

    def test_the_avatar_of_the_avatarizer_node_is_a_declared_param(self):
        """L'ex-`extra_params_spec` à la main : un `Param`, sa liste servie par sa source."""
        from wama.studio.services.node_params import node_schema
        avatar = next(p for p in node_schema('avatarizer')['params']
                      if p['name'] == 'avatar_gallery_name')
        self.assertEqual(('select', 'avatar_gallery'), (avatar['type'], avatar['options_source']))


class TheNodeRegistryIsWhatTheCorpusDeclaresTest(SimpleTestCase):
    """Le registre des nœuds d'app (`GENERIC_APPS`) est ÉCRIT par la facette `studio` du manifeste
    d'app : il doit rester ce que le corpus déclare, sous une forme que la projection sait relire.
    Vécu le 2026-10-13 : R1 y avait posé une expression (`schema_to_dicts([Param(…)])`) — rendu
    juste, mais la projection la lisait « expression », annonçait un écart perpétuel et aurait
    refusé de l'écrire. Aucun test ne le voyait : la suite ne lisait que le rendu."""

    def test_projecting_each_app_manifest_onto_the_node_registry_changes_nothing(self):
        import json
        from wama.common.manifests.builtin.app import _project_studio
        drifts = {}
        for path in sorted((BASE / 'manifests/apps').glob('*.json')):
            manifest = json.loads(path.read_text(encoding='utf-8'))
            if not (manifest.get('body') or {}).get('studio'):
                continue
            plan = _project_studio(manifest, apply=False)
            if plan.get('op') != 'noop':
                drifts[path.stem] = (plan.get('op'), plan.get('would_change'))
        self.assertEqual({}, drifts)

    def test_every_node_own_setting_is_a_param(self):
        """`Param(**entrée)` refuse un champ inconnu : une faute de frappe ne passe pas en silence."""
        from wama.common.utils.param_schema import Param
        from wama.studio.services.generic_runner import GENERIC_APPS
        for app, conf in GENERIC_APPS.items():
            for entry in conf.get('extra_params_spec') or []:
                with self.subTest(app=app, setting=entry.get('name')):
                    Param(**entry)


class BuiltinNodeGateTest(SimpleTestCase):

    def test_the_settings_of_a_builtin_node_are_typed(self):
        """Un interrupteur arrivait en '1'/'' jusqu'au 2026-10-12."""
        from wama.studio.tasks import builtin_node_values
        values = builtin_node_values({'app': 'data_export', 'params': {
            'concat_lots': '1', 'overwrite': '', 'destination': '', 'declarations': '[]'}})
        self.assertEqual({'concat_lots': True, 'declarations': '[]'}, values)

    def test_a_refusal_names_the_node_as_the_user_reads_it(self):
        from wama.studio.tasks import builtin_node_values
        with self.assertRaises(ValueError) as caught:
            builtin_node_values({'app': 'dataset_input', 'params': {'data_type': 'trajectoire'}})
        self.assertIn('Jeu de données', str(caught.exception))
        self.assertIn("data_type : 'trajectoire'", str(caught.exception))


class LaunchRefusesBeforeDispatchTest(TestCase):
    """Un réglage inapplicable se refuse AVANT le dispatch : rien ne part en file."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('studio_gate', password='x')

    def _launch(self, params):
        from wama.studio.models import StudioRun
        from wama.studio.services.launch import launch_graph
        before = StudioRun.objects.count()
        with mock.patch('wama.studio.tasks.run_pipeline_task.delay') as delay:
            delay.return_value = mock.Mock(id='fake-task')
            run, err = launch_graph(self.user, {
                'nodes': [{'id': 'n1', 'app': 'dataset_input', 'params': {}},
                          {'id': 'n2', 'app': 'function:lane_map_recalage', 'params': params}],
                'links': [{'from': 'n1', 'to': 'n2'}]})
        return run, err, delay.called, StudioRun.objects.count() - before

    def test_a_value_outside_the_choices_never_leaves(self):
        run, err, dispatched, created = self._launch({'bias_model': 'nope'})
        self.assertIsNone(run)
        self.assertIn('bias_model', err)
        self.assertIn("'nope'", err)
        self.assertEqual((False, 0), (dispatched, created))

    def test_applicable_values_are_dispatched(self):
        """Contre-épreuve : le même graphe, réglages applicables, part."""
        run, err, dispatched, created = self._launch({'bias_model': 'interpolate', 'radius_m': '30'})
        self.assertIsNone(err)
        self.assertEqual((True, 1), (dispatched, created))


class AvatarGallerySourceTest(TestCase):
    """La source `avatar_gallery` : la liste que résout `designate_named_avatar`, au domicile de
    ce résolveur — elle vivait dans la vue du Studio."""

    def test_a_3d_avatar_is_listed_only_if_it_speaks(self):
        from wama.avatarizer import system_assets
        calls = []

        def visible(user, nature, attributes=None):
            calls.append((nature, attributes))
            return {'avatar': ['face.png', 'twin.glb'], 'object3d': ['twin.glb', 'head.glb']}[nature]

        with mock.patch('wama.media_library.services.visible_asset_names', side_effect=visible):
            names = system_assets.nameable_avatars(None)
        self.assertEqual([('avatar', None), ('object3d', {'face_rig': 'arkit'})], calls)
        self.assertEqual(['face.png', 'twin.glb', 'head.glb'], names)

    def test_the_endpoint_speaks_the_common_options_form(self):
        from wama.avatarizer.views import api_avatar_gallery
        request = RequestFactory().get('/avatarizer/api/avatar-gallery/')
        request.user = get_user_model().objects.create_user('studio_avatar', password='x')
        with mock.patch('wama.avatarizer.system_assets.nameable_avatars', return_value=['face.png']):
            data = __import__('json').loads(api_avatar_gallery(request).content)
        self.assertEqual({'groups': [{'group': '', 'options': [['face.png', 'face.png']]}]}, data)


class TheStudioHasNoSettingsRendererOfItsOwnTest(SimpleTestCase):
    """Non-retour : le Studio rend ses réglages par `WamaParams`, et par lui seul."""

    def test_the_studio_script_mounts_the_common_engine(self):
        src = STUDIO_JS.read_text(encoding='utf-8')
        # Le nom retiré peut rester CITÉ dans un commentaire d'histoire ; il ne doit plus être
        # défini ni appelé, et le format propre au Studio ne doit plus être lu.
        for gone in (r'function\s+renderNodeParams', r'renderNodeParams\(', r'paramsSpecs\b',
                     r'params_specs', r'runOptions\b'):
            self.assertIsNone(re.search(gone, src), gone)
        self.assertIn('WamaParams.render(', src)
        self.assertIn('WamaParams.isGesture(', src)

    def test_the_page_loads_the_common_engine_before_the_studio(self):
        html = (BASE / 'wama/studio/templates/studio/index.html').read_text(encoding='utf-8')
        self.assertLess(html.index("common/js/wama-params.js"), html.index("studio/js/wama-studio.js"))

    def test_the_served_copies_match_their_source(self):
        for source, rel in ((STUDIO_JS, 'studio/js/wama-studio.js'),
                            (PARAMS_JS, 'common/js/wama-params.js')):
            served = BASE / 'staticfiles' / rel
            if served.exists():
                self.assertEqual(source.read_bytes(), served.read_bytes(), rel)

    def test_the_served_studio_script_parses(self):
        """Un `.js` ne casse pas à la compilation, il casse dans le navigateur : V8 en atteste
        la syntaxe sur le fichier SERVI, sans l'exécuter (AGENTS.md, « Le JS aussi »)."""
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8')
        served = BASE / 'staticfiles/studio/js/wama-studio.js'
        src = (served if served.exists() else STUDIO_JS).read_text(encoding='utf-8')
        MiniRacer().eval('(function(){' + src + '\n})')
