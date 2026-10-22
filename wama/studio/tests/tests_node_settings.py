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


def _shown_settings(app):
    """Les réglages que l'inspecteur MONTRE pour le nœud d'app : contexte `item` (celui du rendu),
    condition d'affichage satisfaite par les défauts (`param_schema._show_if_met`, le jumeau
    serveur du moteur — un champ « texte à dire » masqué tant qu'aucun texte n'est porté n'est pas
    montré), moins ceux qui construisent l'entrée principale (le prompt d'un nœud à entrée texte)
    et les réglages PROPRES au nœud (`extra_params_spec` : des entrées de création, pas des
    colonnes de l'élément)."""
    from wama.common.utils.param_schema import _show_if_met
    from wama.studio.services.generic_runner import GENERIC_APPS
    from wama.studio.services.node_params import node_schema
    conf = GENERIC_APPS[app]
    skipped = {e['name'] for e in conf.get('extra_params_spec') or []}
    if conf.get('primary_input') == 'prompt':
        skipped |= {'prompt', 'text', 'text_content'}
    params = node_schema(app)['params']
    defaults = {p['name']: p.get('default') for p in params}
    return [p for p in params
            if 'item' in (p.get('contexts') or ()) and p['name'] not in skipped
            and _show_if_met(p.get('show_if'), defaults)]


def _decided_value(p):
    """Une valeur que l'utilisateur DÉCIDE — jamais le défaut, sinon la mesure ne prouverait rien
    (le défaut du modèle passerait pour un réglage transmis). `None` = pas de valeur sûre à
    choisir hors du navigateur (liste servie par une source, champ libre sans défaut)."""
    default = p.get('default')
    kind = p.get('type')
    if p.get('options_source') or kind in ('hidden', 'media_picker'):
        return None
    values = [c[0] if isinstance(c, (list, tuple)) else c for c in (p.get('choices') or [])]
    if values:
        return next((v for v in values if v not in ('', None) and str(v) != str(default)), None)
    if kind == 'toggle':
        return not bool(default)
    if kind == 'intent':
        return 80 if default != 80 else 20
    if kind in ('number', 'range'):
        # La borne BASSE d'abord : un plafond de capacité du modèle (`cap_from`) borne le haut,
        # jamais le bas — la borne haute ferait mesurer la capacité du modèle par défaut.
        low, high = p.get('min'), p.get('max')
        if low is None or high is None or low == high:
            return None
        return low if default != low else high
    if kind in ('text', 'textarea'):
        return 'wama'           # court : une colonne texte peut être bornée (reader : 16)
    return None


def _same(expected, found):
    if isinstance(expected, bool) or isinstance(found, bool):
        return bool(expected) == bool(found)
    try:
        return float(expected) == float(found)
    except (TypeError, ValueError):
        return str(expected) == str(found)


#: Ce qu'une création EXIGE en plus du fichier — le même rôle que `TOOL_ARGS` de
#: `tests_tool_api_designation` (le converter veut un format de sortie valable pour une image).
CREATION_ARGS = {'converter': {'output_format': 'jpg'}}


class EveryShownSettingReachesTheElementTest(TestCase):
    """Un réglage AFFICHÉ par un nœud d'app arrive sur l'élément que le nœud CRÉE.

    Le nœud crée par l'outil `add_to_<app>` (même porte que l'assistant), qui ne garde que ce que
    sa signature accepte. Mesuré le 2026-10-18 : trois créateurs sans `**params` (enhancer,
    reader, avatarizer) perdaient en silence 11 des réglages que l'inspecteur montrait. Mesure
    de BOUT EN BOUT, aucune app nommée : le runner du Studio crée un élément réel avec chaque
    réglage rendu posé sur une valeur DÉCIDÉE (jamais son défaut), puis l'élément est relu."""

    def setUp(self):
        from wama.common.services.nightly_tests import get_test_user
        self.user = get_test_user()

    def _input(self, app):
        """L'entrée principale du nœud : un prompt, ou un témoin du premier type qu'il accepte."""
        from pathlib import Path
        from wama.common.app_registry import accepts_file
        from wama.common.tests.tests_import_contract import _WITNESSES
        from wama.studio.services.generic_runner import GENERIC_APPS
        conf = GENERIC_APPS[app]
        if conf.get('primary_input') == 'prompt':
            return {'prompt': 'wama node setting'}
        kind = next(k for k in conf['input_kinds']
                    if k in _WITNESSES and accepts_file(app, 'witness' + _WITNESSES[k][0]))
        ext, content = _WITNESSES[kind]
        rel = f'users/{self.user.id}/temp/node_{app}{ext}'
        path = Path(settings.MEDIA_ROOT) / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content())
        return {kind: rel}

    # Aucune tâche réelle : le converter LANCE la sienne à la création (`auto_start`).
    @mock.patch('celery.app.task.Task.apply_async', return_value=mock.Mock(id='no-task'))
    def test_every_shown_setting_reaches_the_element(self, _no_task):
        from django.db import transaction
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.detail_registry import DetailRegistry
        from wama.common.utils.media_paths import designate
        from wama.common.utils.param_schema import coerce_schema_values, schema_for_app
        from wama.studio.services.generic_runner import GENERIC_APPS, build_generic_runner
        measured, lost = [], {}
        # L'avatar NOMMÉ se résout dans la médiathèque de l'utilisateur ; ici, un témoin désigné.
        named_avatar = lambda name, user: designate(self._input('anonymizer')['image'], user, 'avatarizer')
        with mock.patch('wama.avatarizer.system_assets.designate_named_avatar', named_avatar):
            for app in sorted(GENERIC_APPS):
                if (APP_CATALOG.get(app) or {}).get('generated_from'):
                    continue      # jumelle : comparée à sa source, jamais mesurée seule
                decided = {p['name']: v for p in _shown_settings(app)
                           if (v := _decided_value(p)) is not None}
                decided.update(CREATION_ARGS.get(app, {}))
                # Les réglages propres au nœud sont des ENTRÉES de création (l'avatar nommé) :
                # posés pour que la création aboutisse, jamais relus comme des colonnes.
                own = {e['name']: 'witness'
                       for e in GENERIC_APPS[app].get('extra_params_spec') or []}
                with self.subTest(app=app), transaction.atomic():
                    item_id = build_generic_runner(app)['create'](self.user, self._input(app),
                                                                 {**decided, **own})
                    item = DetailRegistry.get(app)['model'].objects.get(pk=item_id)
                    expected = coerce_schema_values(schema_for_app(app), decided)
                    for name, value in decided.items():
                        measured.append((app, name))
                        want = expected.get(name, value)
                        found = getattr(item, name, '<absent de l’élément>')
                        if not _same(want, found):
                            lost.setdefault(app, []).append(
                                f'{name}: décidé {want!r}, élément {found!r}')
        self.assertGreater(len(measured), 50, 'non-vacuité : les apps du registre sont mesurées')
        self.assertEqual({}, lost, 'réglages affichés au Studio qui n’atteignent pas l’élément')

    @mock.patch('celery.app.task.Task.apply_async', return_value=mock.Mock(id='no-task'))
    def test_a_long_duration_is_capped_by_the_model_never_by_the_tool(self, _no_task):
        """Le créateur du composer réduisait toute durée à 30 s (`min(30.0, …)`) quand le schéma
        offre 10 min et que seul le MODÈLE plafonne (`clamp_duration`, capacité déclarée)."""
        from wama.composer.models import ComposerGeneration
        from wama.tool_api import compose_music
        long = compose_music(self.user, 'wama', model='auto:text-to-music', duration=120)
        self.assertFalse(long.get('error'), long)
        self.assertEqual(120, ComposerGeneration.objects.get(pk=long['item_id']).duration)
        short = compose_music(self.user, 'wama', model='musicgen-small', duration=120)
        self.assertEqual(30, ComposerGeneration.objects.get(pk=short['item_id']).duration,
                         'contre-épreuve : MusicGen déclare 30 s, il reste plafonné')


class AProcessNodeIsTheStepOfItsCardTest(TestCase):
    """Un nœud `function:<app>.<process>` est une ÉTAPE de card (D2, 2026-10-18) : il montre les
    réglages de la ⚙ de cette étape, et il la lance comme le ▶ de l'étape sur la card. Avant, il
    montrait l'identifiant que réclame la tâche, en champ texte, et lançait la tâche entière."""

    def setUp(self):
        from wama.common.services.nightly_tests import get_test_user
        self.user = get_test_user()

    def test_every_step_node_shows_the_settings_of_its_card_step(self):
        """Générique, aucune app nommée : pour CHAQUE process de CHAQUE pipeline d'app, les
        réglages d'app du nœud sont exactement ceux de la ⚙ de l'étape sur la card — ce qu'elle
        surveille (`watched_of`), plus le champ qui COMMANDE un réglage retenu, plus les porteurs
        cachés (`scoped_names`, jumeau de `scopedSchema`, 2026-10-18). Une seconde règle,
        écrite pour le nœud seul, cachait l'interrupteur de l'étape et ne l'écrivait jamais."""
        from wama.common.services.process_pipeline import APP_PIPELINES, _load_declarations
        from wama.common.utils.param_schema import schema_for_app, scoped_names
        from wama.studio.services.node_params import node_schema
        _load_declarations()
        measured = 0
        for app, pipeline in sorted(APP_PIPELINES.items()):
            app_schema = schema_for_app(app)
            app_names = {p['name'] for p in app_schema}
            for process in pipeline.specs:
                schema = node_schema(f'function:{pipeline.function_key(process)}')
                if schema is None:
                    continue          # étape hors catalogue (le process « Sortie » commun)
                shown = {p['name'] for p in schema['params']} & app_names
                with self.subTest(step=f'{app}.{process.key}'):
                    self.assertEqual(set(scoped_names(app_schema, pipeline.watched_of(process))),
                                     shown)
                measured += 1
        self.assertGreater(measured, 15, 'non-vacuité : les étapes des pipelines d’app')

    def _composer_card(self, owner):
        """Une card du composer déjà produite (son créateur la lance aussitôt : elle est posée
        terminée, comme une card dont on relance une étape)."""
        from wama.composer.models import ComposerGeneration
        from wama.tool_api import compose_music
        with mock.patch('celery.app.task.Task.apply_async', return_value=mock.Mock(id='no-task')):
            item_id = compose_music(owner, 'wama', model='auto:text-to-music', duration=60)['item_id']
        ComposerGeneration.objects.filter(pk=item_id).update(status='SUCCESS')
        return item_id

    def _render_step(self):
        from wama.common.catalog import function_catalog as fc
        from wama.common.services.process_pipeline import process_of_function
        pipeline, process = process_of_function('composer.render')
        return pipeline, process, fc.get('composer.render')

    def test_the_decided_settings_reach_the_card_then_the_step_starts(self):
        from wama.composer.models import ComposerGeneration
        from wama.studio.tasks import _run_app_process
        from wama import tool_api
        pipeline, process, spec = self._render_step()
        self.assertIn('duration', pipeline.watched_of(process))
        item_id = self._composer_card(self.user)
        finished = mock.Mock(**{'ready.return_value': True, 'failed.return_value': False})
        with mock.patch('celery.app.task.Task.apply_async', return_value=mock.Mock(id='no-task')), \
                mock.patch('celery.result.AsyncResult', return_value=finished), \
                mock.patch.object(tool_api, 'execute_tool', wraps=tool_api.execute_tool) as call:
            _run_app_process(pipeline, process, spec, {'generation_id': str(item_id), 'duration': 120},
                             self.user, lambda **k: None, 5)
        self.assertEqual(120, ComposerGeneration.objects.get(pk=item_id).duration)
        tool, args, _user = call.call_args.args
        self.assertEqual(('start_composer', 'render'), (tool, args['process']))

    def test_the_switch_of_an_optional_step_decided_at_the_node_reaches_the_card(self):
        """Une étape FACULTATIVE n'a lieu que si son interrupteur est vrai sur l'élément
        (`AppPipeline.takes_place`). L'interrupteur est dans la ⚙ de l'étape (il commande le
        réglage retenu) : décidé au nœud, il est ÉCRIT, comme par la ⚙ de la card (2026-10-18 —
        une seconde règle le cachait au nœud et ne l'écrivait jamais : l'étape ne partait pas)."""
        from wama.common.catalog import function_catalog as fc
        from wama.common.services.process_pipeline import process_of_function
        from wama.studio.services.node_params import node_schema
        from wama.studio.tasks import _run_app_process
        from wama.transcriber.models import Transcript
        from wama import tool_api
        pipeline, process = process_of_function('transcriber.summarize')
        self.assertTrue(process.toggle)
        shown = {p['name']: p['type'] for p in node_schema('function:transcriber.summarize')['params']}
        self.assertEqual('toggle', shown.get(process.toggle), 'l’interrupteur est montré, décidable')
        item = Transcript.objects.create(user=self.user, status='SUCCESS',
                                         **{process.toggle: False})
        finished = mock.Mock(**{'ready.return_value': True, 'failed.return_value': False})
        with mock.patch('celery.result.AsyncResult', return_value=finished), \
                mock.patch.object(tool_api, 'execute_tool',
                                  return_value={'task_id': 'no-task'}):
            _run_app_process(pipeline, process, fc.get('transcriber.summarize'),
                             {'transcript_id': str(item.pk), process.toggle: True},
                             self.user, lambda **k: None, 5)
        item.refresh_from_db()
        self.assertTrue(getattr(item, process.toggle))

    def test_a_card_the_account_cannot_edit_is_refused_and_left_untouched(self):
        from django.contrib.auth import get_user_model
        from wama.composer.models import ComposerGeneration
        from wama.studio.tasks import _run_app_process
        pipeline, process, spec = self._render_step()
        other = get_user_model().objects.create_user('studio_step_owner', password='x')
        item_id = self._composer_card(other)
        with self.assertRaisesRegex(ValueError, 'introuvable'):
            _run_app_process(pipeline, process, spec, {'generation_id': item_id, 'duration': 120},
                             self.user, lambda **k: None, 5)
        self.assertEqual(60, ComposerGeneration.objects.get(pk=item_id).duration)


class TheBuiltinNodesAreDeclaredOnceByTheirWorldTest(TestCase):
    """R2 (ROUTE §10.6 3.3bis, 2026-10-18) : un nœud INTÉGRÉ — card d'entrée ou de sortie — est
    déclaré UNE fois, par son monde, au registre commun ; la palette, l'inspecteur, le lancement et
    l'exécuteur le lisent. Il se déclarait à six endroits, qui divergeaient (la palette offrait un
    « Batch de prompts » que rien n'exécutait)."""

    def test_the_palette_offers_exactly_the_registered_builtin_nodes(self):
        from django.urls import reverse
        from wama.common.manifests.builtin.pipeline import builtin_nodes
        from wama.common.services.nightly_tests import get_test_user
        self.client.force_login(get_test_user())
        served = self.client.get(reverse('studio:api_nodes')).json()['nodes']
        offered = {k: v['kind'] for k, v in served.items() if v.get('kind') in ('source', 'sink')}
        self.assertEqual({k: b.role for k, b in builtin_nodes().items()}, offered)

    def test_each_world_registers_its_own_nodes(self):
        """Un nœud DÉCLARE son monde (`BuiltinNode.world`) et c'est CE monde qui l'inscrit — lu au
        module qui l'a inscrit, jamais à une liste. Le substrat héberge le monde Médias et les
        nœuds transverses (le Studio) ; tout autre monde inscrit les siens. « Jeu de données » se
        déclarait `data` et restait inscrit par le Studio, avec son propre décodeur de fichier
        (corrigé le 2026-10-22) — la liste qui tenait ce test ne pouvait pas le voir."""
        from django.apps import apps
        from wama.common.app_registry import app_world
        from wama.common.manifests.builtin.pipeline import builtin_nodes
        checked = 0
        for key, node in builtin_nodes().items():
            module = node.run.__module__
            with self.subTest(node=key, module=module):
                if node.world in ('', 'media'):
                    self.assertEqual('wama', module.split('.')[0])
                    continue
                config = apps.get_containing_app_config(module)
                self.assertEqual(node.world, app_world(config.label) if config else None)
                checked += 1
        self.assertGreaterEqual(checked, 3, 'the data world registers its three nodes')

    def test_every_builtin_node_is_runnable_and_its_settings_render(self):
        from wama.common.manifests.builtin.pipeline import builtin_nodes, node_kind
        from wama.studio.services.node_params import node_label, node_schema
        renderers, sources = _registered_renderers(), _resolved_sources()
        self.assertGreaterEqual(len(builtin_nodes()), 6)
        for key, node in builtin_nodes().items():
            with self.subTest(node=key):
                self.assertTrue(callable(node.run))
                self.assertEqual(node.role, node_kind({'app': key}))
                self.assertEqual(node.label, node_label(key))
                for p in node_schema(key)['params']:
                    self.assertIn(p['type'], renderers)
                    if p.get('options_source'):
                        self.assertIn(p['options_source'], sources)

    def test_the_launch_refusal_names_the_registered_nodes(self):
        """Le message de refus disait une liste de libellés recopiée : il lit le registre."""
        from wama.common.manifests.builtin.pipeline import builtin_nodes
        from wama.studio.services.launch import launch_graph
        from wama.common.services.nightly_tests import get_test_user
        run, err = launch_graph(get_test_user(), {
            'nodes': [{'id': 'n1', 'app': 'text_input', 'params': {'text': 'x'}},
                      {'id': 'n2', 'app': 'no_such_node', 'params': {}}],
            'links': [{'from': 'n1', 'to': 'n2'}]})
        self.assertIsNone(run)
        for node in builtin_nodes().values():
            self.assertIn(node.label, err)

    def test_the_studio_script_holds_no_builtin_node(self):
        src = STUDIO_JS.read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'var\s+BUILTINS\s*=', src))
        self.assertIsNone(re.search(r'BUILTINS\[', src))
        self.assertNotIn('prompt_batch', src)
        self.assertNotIn('installDatasetSource', src)

    def test_setting_a_node_is_measured_every_night_end_to_end(self):
        """Le geste de bout en bout (point 6 de R2) : réglage → enregistré → rechargé → porté par
        l'élément. Joué le 2026-10-18 sur un serveur de dev au code neuf : vert ; rouge sur le
        script d'avant (contre-épreuve)."""
        from wama.common.services import nightly_tests
        scenarios = {s.id: s for s in nightly_tests.REGISTRY}
        self.assertIn('studio.node_settings', scenarios)
        self.assertEqual('ui', scenarios['studio.node_settings'].stage)

    def test_the_studio_substrate_no_longer_imports_the_data_world(self):
        """Le monde Data inscrit ses nœuds ; le Studio n'importe plus `wama_data` pour eux."""
        for rel in ('wama/studio/tasks.py', 'wama/studio/services/node_params.py',
                    'wama/studio/services/launch.py', 'wama/studio/views.py'):
            src = (BASE / rel).read_text(encoding='utf-8')
            with self.subTest(file=rel):
                self.assertIsNone(re.search(r'^\s*(from|import)\s+wama_data', src, re.M))


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

    def test_the_output_node_offers_every_declared_nature(self):
        """Read from the natures declared once (A′), never a list of its own: the list written
        here until 2026-10-13 offered six natures out of ten."""
        from wama.media_library.natures import ASSET_NATURES
        from wama.studio.services.node_params import node_schema
        field = next(p for p in node_schema('studio_output')['params'] if p['name'] == 'asset_type')
        # « Automatique » en tête (2026-10-18), puis les natures déclarées, chacune une fois.
        self.assertEqual('', field['choices'][0][0])
        self.assertEqual(list(ASSET_NATURES), [c[0] for c in field['choices'][1:]])
        grouped = [v for _label, options in field['option_groups'] for v, _l in options]
        self.assertCountEqual([c[0] for c in field['choices']], grouped,
                              'le rendu (groupes) et la porte (choices) ne disent plus les mêmes valeurs')

    def test_every_output_type_a_studio_scenario_writes_passes_the_node_gate(self):
        """The nightly pipeline wrote the CATEGORY `audio`: refused by the common gate of node
        settings since 2026-10-12, `studio.pipeline.converter` was red every night."""
        import ast
        from pathlib import Path
        from wama.studio.tasks import builtin_node_values
        source = Path(__file__).parent.parent.joinpath('nightly_scenarios.py').read_text(encoding='utf-8')
        written = [node.values[i].value for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.Dict)
                   for i, key in enumerate(node.keys)
                   if isinstance(key, ast.Constant) and key.value == 'asset_type'
                   and isinstance(node.values[i], ast.Constant)]
        self.assertTrue(written, 'no output type found: nothing measured')
        for value in written:
            with self.subTest(asset_type=value):
                builtin_node_values({'app': 'studio_output', 'params': {'asset_type': value}})


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

    def test_a_settings_gesture_records_only_the_decided_setting(self):
        """Un geste n'enregistre que le réglage TOUCHÉ (R2, 2026-10-18), sans effacer les autres
        clés du nœud. Deux défauts tenus : l'instantané de tous les champs rendus, qui figeait les
        défauts de l'app au premier geste ; le remplacement du dict, qui effaçait la déclaration du
        process d'un pipeline déclaré (R1, rattrapé le 2026-10-13)."""
        src = STUDIO_JS.read_text(encoding='utf-8')
        self.assertIsNone(re.search(r'node\.params\s*=\s*WamaParams\.read\(', src))
        self.assertIsNone(re.search(r'Object\.assign\([^)]*WamaParams\.read\(', src),
                          'un instantané de tous les champs rendus est enregistré')
        self.assertRegex(src, r'node\.params\s*=\s*Object\.assign\(\{\},\s*node\.params\s*\|\|\s*\{\}\)')
        self.assertRegex(src, r'node\.params\[name\]\s*=\s*values\[name\]')

    def test_the_canvas_keeps_a_declared_process_apart_from_the_settings(self):
        """D1 (2026-10-18) : la déclaration d'un process (`process`) se charge et se sérialise avec
        le nœud, à part de ses réglages — sinon un pipeline déclaré ouvert puis enregistré au
        Studio la perdrait."""
        src = STUDIO_JS.read_text(encoding='utf-8')
        self.assertRegex(src, r'if \(opts\.process\) node\.process = opts\.process')
        self.assertRegex(src, r'if \(n\.process\) out\.process = n\.process')

    def test_the_settings_arrive_with_the_catalogue_and_their_state_is_always_said(self):
        """Une seule requête (R143) ; et l'inspecteur DIT toujours où en sont les réglages — un
        nœud sans réglages affichés était indiscernable d'un chargement (constat live du
        2026-10-18 : 0 champ, aucun message, pendant 10 à 15 s)."""
        src = STUDIO_JS.read_text(encoding='utf-8')
        self.assertNotIn('run-options', src)
        self.assertRegex(src, r'nodeSchemas\s*=\s*d\.schemas')
        for state in ('Chargement des réglages', 'Réglages indisponibles', 'n’a pas de réglage'):
            self.assertIn(state, src)
        self.assertRegex(src, r"\.catch\(function \(err\) \{\s*settingsState = 'error'",
                         'un échec du catalogue doit se dire dans l’inspecteur')

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
