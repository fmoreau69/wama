"""A card that carries SEVERAL processes — `WAMA_APP_GENERATION_ROUTE §10.6`, step P3 stage B.

What is held here, and why each point:

  * an app writes its processes down the way the cam_analyzer writes its passes (a registry in
    code that becomes a `pipeline` manifest with `function` nodes) — the form is the one the
    studio already opens, so nothing new has to learn to read it ;
  * a launch replays ONLY what is no longer valid, plus everything downstream of it — that is
    the whole point of several processes: a setting of the last one must not replay the first ;
  * « no longer valid » has the three causes of point 4.3: a watched setting changed, the output
    of an upstream process was replaced, an upstream process is itself stale ;
  * a card whose processes are all valid, relaunched, replays everything — the user asks for
    another result — even though the launcher already removed the previous output ;
  * the task skeleton runs the retained processes one after the other in ONE task and keeps one
    execution line per process ; a failure closes the line of the process that failed and leaves
    the ones before it valid.
"""
import json
import os
import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from wama.common.models import (JOB_FAILURE, JOB_PENDING, JOB_RUNNING, JOB_STALE, JOB_SUCCESS,
                                ProcessRun)
from wama.common.services import process_runs
from wama.common.services.process_pipeline import (APP_PIPELINES, UPSTREAM_KEY, AppPipeline,
                                                   ProcessSpec, register_app_pipeline)
from wama.common.tests.tests_queue_delete_contract import _instance
from wama.common.tests.tests_task_skeleton_contract import _adopters, _task


class _Element:
    """Stand-in element: the lines address it by (app, type, pk) and read its settings."""

    class _meta:
        app_label = 'demo_pipeline'
        object_name = 'Element'

    _next = 0

    def __init__(self, **settings):
        type(self)._next += 1
        self.pk = type(self)._next
        self.prompt, self.duration, self.given_score = 'a calm piano', 30, ''
        self.__dict__.update(settings)


def _two_steps(**plan_options):
    return AppPipeline('demo_pipeline', (
        ProcessSpec('plan', watched=('prompt',), **plan_options),
        ProcessSpec('render', depends_on=('plan',), watched=('prompt', 'duration'), share=3),
    ), label='Demo')


def _keys(steps):
    return [spec.key for spec in steps]


class WhatAProcessRequiresFromItsModelTest(TestCase):
    """`ProcessSpec.needs` (2026-11-05, Fabien : « quelle capacité du modèle rend ce réglage
    utile ? ») — what a process requires from the model of the card, as DATA : a `show_if`
    condition judged on the catalogue line (`model_capabilities.catalog_capabilities`), the same
    data the page reads to hide its settings. The element is still judged by `applies`."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        AIModel.objects.create(model_key='demo:singer', name='Singer', source='demo',
                               capabilities={'task': 'text-to-music', 'supports_vocals': True})
        AIModel.objects.create(model_key='demo:noise', name='Noise', source='demo',
                               capabilities={'task': 'text-to-audio'})

    def _pipeline(self, **lyrics):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('render'),
            ProcessSpec('lyrics', depends_on=('render',), needs='supports_vocals', **lyrics),
        ), label='Demo')

    def test_a_model_without_the_capability_does_not_serve_the_process(self):
        pipeline = self._pipeline()
        self.assertEqual(['render', 'lyrics'], _keys(pipeline.applicable(_Element(), 'demo:singer')))
        self.assertEqual(['render'], _keys(pipeline.applicable(_Element(), 'demo:noise')),
                         'an ABSENT capability is not satisfied : the catalogue is exhaustive')
        self.assertEqual(['render'], _keys(pipeline.applicable(_Element(), 'demo:unknown')))

    def test_under_auto_nothing_is_guessed(self):
        pipeline = self._pipeline()
        self.assertTrue(pipeline.model_serves(pipeline.spec('lyrics'), 'auto:text-to-music'))
        self.assertTrue(pipeline.model_serves(pipeline.spec('lyrics'), None))

    def test_the_element_is_still_judged_by_applies(self):
        """Counter-proof : the capability does not replace what is judged on the element."""
        pipeline = self._pipeline(applies=lambda item, model_key: not getattr(item, 'lyrics', ''))
        self.assertEqual(['render'], _keys(pipeline.applicable(_Element(lyrics='la la'), 'demo:singer')))
        self.assertEqual(['render', 'lyrics'], _keys(pipeline.applicable(_Element(lyrics=''), 'demo:singer')))

    def test_the_page_receives_what_each_process_requires_and_the_field_that_chooses_the_model(self):
        import json as _json
        from django.test import RequestFactory
        from wama.accounts.context_processors import user_role
        from wama.common.services import process_pipeline as pp
        request = RequestFactory().get('/composer/')
        request.user = get_user_model().objects.create_user('needs_page', password='x')
        processes = {p['key']: p for p in _json.loads(user_role(request)['current_app_processes_json'])}
        self.assertEqual({'needs': 'supports_vocals', 'model_field': 'model'},
                         {k: processes['rendered_lyrics'][k] for k in ('needs', 'model_field')})
        self.assertNotIn('needs', processes['render'], 'a process without requirement says nothing')
        self.assertEqual(pp.app_pipeline('composer').spec('rendered_parts').needs,
                         processes['rendered_parts']['needs'])


class WritingAPipelineDownTest(SimpleTestCase):

    def test_an_upstream_that_is_not_in_the_pipeline_is_refused(self):
        with self.assertRaisesMessage(ValueError, 'master'):
            AppPipeline('demo', (ProcessSpec('render', depends_on=('master',)),), label='x')

    def test_a_key_written_twice_is_refused(self):
        with self.assertRaises(ValueError):
            AppPipeline('demo', (ProcessSpec('render'), ProcessSpec('render')), label='x')

    def test_a_cycle_is_refused_when_the_pipeline_is_written_not_when_it_runs(self):
        with self.assertRaisesMessage(ValueError, 'cycle'):
            AppPipeline('demo', (ProcessSpec('a', depends_on=('b',)),
                                 ProcessSpec('b', depends_on=('a',))), label='x')

    def test_an_unknown_degree_is_refused(self):
        with self.assertRaises(ValueError):
            AppPipeline('demo', (ProcessSpec('render', degree='sometimes'),), label='x')

    def test_the_order_is_the_order_of_the_graph_whatever_the_writing_order(self):
        pipeline = AppPipeline('demo', (ProcessSpec('render', depends_on=('plan',)),
                                        ProcessSpec('plan')), label='x')
        self.assertEqual(['plan', 'render'], _keys(pipeline.ordered()))
        self.assertEqual(['render'], _keys(pipeline.ordered({'render'})))

    def test_the_graph_is_the_canvas_form_and_makes_a_valid_manifest_body(self):
        """Same form as the cam_analyzer registry: a process = a `function` node, a dependency =
        a link. That is what lets the studio open the pipeline of an app."""
        from wama.common.manifests.builtin.pipeline import (body_to_graph, graph_to_body,
                                                            validate_pipeline_body)
        pipeline = _two_steps()
        graph = pipeline.graph()
        self.assertEqual(['function:demo_pipeline.plan', 'function:demo_pipeline.render'],
                         [node['app'] for node in graph['nodes']])
        self.assertEqual([{'from': 'plan', 'to': 'render', 'to_port': None}], graph['links'])
        # The DECLARATION travels under `process`; `params` (the user's values) stays empty (D1).
        self.assertEqual(['prompt', 'duration'], graph['nodes'][1]['process']['watched'])
        self.assertEqual({}, graph['nodes'][1]['params'])
        body = graph_to_body(graph)
        self.assertEqual(graph['nodes'][1]['process'], body['nodes'][1]['process'])
        self.assertEqual([], validate_pipeline_body(body))
        self.assertEqual(['demo_pipeline.plan', 'demo_pipeline.render'],
                         [node['function'] for node in body['nodes']])
        self.assertEqual(['plan', 'render'], [n['id'] for n in body_to_graph(body)['nodes']])

    def test_a_function_key_can_be_named_when_it_is_not_the_default_one(self):
        pipeline = AppPipeline('demo', (ProcessSpec('render', function='demo.rendering'),),
                               label='x')
        self.assertEqual('demo.rendering', pipeline.function_key(pipeline.spec('render')))

    def test_registering_makes_the_pipeline_a_manifest_source_under_the_app_key(self):
        from wama.common.manifests.builtin.pipeline import PIPELINE_SOURCES
        self.addCleanup(APP_PIPELINES.pop, 'demo_registered', None)
        self.addCleanup(PIPELINE_SOURCES.pop, 'demo_registered', None)
        pipeline = register_app_pipeline('demo_registered', (ProcessSpec('render'),), label='Demo')
        self.assertIs(APP_PIPELINES['demo_registered'], pipeline)
        with mock.patch('wama.common.app_registry.app_world', return_value='media'):
            manifest = PIPELINE_SOURCES['demo_registered']()
        self.assertEqual(('pipeline', 'demo_registered', 'media'),
                         (manifest['manifest_kind'], manifest['key'], manifest['world']))
        self.assertIn('1 process', manifest['name'])


class ACardExtendedPipelineTest(SimpleTestCase):
    """`AppPipeline.extended` (ROUTE §10.6 3.2bis, 2026-10-29) : the pipeline of a card ADJUSTED by
    the user — the declared one, plus the processes the Studio graph adds. Nothing declared is
    rebuilt from the graph (its conditions are code), nothing is removed (rule 1), and a process
    is added downstream or as a branch, never before or between declared ones (rule 2)."""

    ADDED = 'demo_card_pipeline.measure'
    STEP = 'demo_card_other.step'

    def setUp(self):
        from wama.common.catalog.function_catalog import (FUNCTION_CATALOG, Binding, FunctionSpec,
                                                          PortSpec)
        FUNCTION_CATALOG[self.ADDED] = FunctionSpec(
            key=self.ADDED, name='measure', description='', category='indicator',
            inputs=[PortSpec('audio', 'audio')], outputs=[PortSpec('value', 'scalar')])
        FUNCTION_CATALOG[self.STEP] = FunctionSpec(
            key=self.STEP, name='step', description='', category='transform',
            binding=Binding.APP, app='demo_card_other')
        APP_PIPELINES['demo_card_other'] = AppPipeline(
            'demo_card_other', (ProcessSpec('step'),), label='Other')
        self.addCleanup(FUNCTION_CATALOG.pop, self.ADDED, None)
        self.addCleanup(FUNCTION_CATALOG.pop, self.STEP, None)
        self.addCleanup(APP_PIPELINES.pop, 'demo_card_other', None)
        self.pipeline = _two_steps(degree='optional', toggle='with_plan',
                                   applies=lambda item, model: model != 'no-plan')

    def _graph(self, *nodes, links=()):
        """The declared graph, plus `nodes` (id, function, process declaration) and `links`."""
        graph = self.pipeline.graph()
        graph['nodes'] += [{'id': key, 'app': f'function:{function}', 'params': {},
                            'process': dict(declared)} for key, function, declared in nodes]
        graph['links'] += [{'from': up, 'to': down, 'to_port': None} for up, down in links]
        return graph

    def test_a_graph_that_adds_nothing_gives_the_declared_pipeline_itself(self):
        self.assertIs(self.pipeline, self.pipeline.extended(self.pipeline.graph()))

    def test_a_process_added_downstream_leaves_the_declared_ones_as_they_are(self):
        card_pipeline = self.pipeline.extended(self._graph(('measure', self.ADDED, {}),
                                                    links=[('render', 'measure')]))
        self.assertIsNot(self.pipeline, card_pipeline)
        self.assertIs(self.pipeline, card_pipeline.base)
        self.assertEqual(frozenset({'measure'}), card_pipeline.added)
        self.assertEqual(['plan', 'render', 'measure'], _keys(card_pipeline.ordered()))
        # The declared specs are the SAME objects: their conditions are code, never rebuilt.
        for key in ('plan', 'render'):
            self.assertIs(self.pipeline.spec(key), card_pipeline.spec(key))
        added = card_pipeline.spec('measure')
        self.assertEqual((self.ADDED, ('render',), 'required'),
                         (added.function, added.depends_on, added.degree))
        # What takes place for an element follows the declared conditions, plus the addition.
        element = _Element(with_plan=True)
        self.assertEqual(['render'], _keys(self.pipeline.applicable(element, 'no-plan')))
        self.assertEqual(['render', 'measure'], _keys(card_pipeline.applicable(element, 'no-plan')))

    def test_a_branch_from_a_declared_process_is_allowed(self):
        card_pipeline = self.pipeline.extended(self._graph(
            ('measure', self.ADDED, {'degree': 'optional', 'label': 'Mesure'}),
            links=[('plan', 'measure')]))
        self.assertEqual((('plan',), 'optional', 'Mesure'),
                         (card_pipeline.spec('measure').depends_on, card_pipeline.spec('measure').degree,
                          card_pipeline.spec('measure').label))
        self.assertEqual(('plan',), card_pipeline.spec('render').depends_on)

    def test_a_declared_process_is_never_removed_not_even_an_optional_one(self):
        for removed in ('plan', 'render'):
            with self.subTest(removed=removed):
                graph = self.pipeline.graph()
                graph['nodes'] = [n for n in graph['nodes'] if n['id'] != removed]
                graph['links'] = [l for l in graph['links'] if removed not in (l['from'], l['to'])]
                with self.assertRaisesMessage(ValueError, f'ne se retire pas (un optionnel se '
                                                          f'décoche) — {removed}'):
                    self.pipeline.extended(graph)

    def test_nothing_is_added_before_or_between_declared_processes(self):
        before = self._graph(('measure', self.ADDED, {}), links=[('measure', 'plan')])
        between = self._graph(('measure', self.ADDED, {}),
                              links=[('plan', 'measure'), ('measure', 'render')])
        for name, graph in (('before', before), ('between', between)):
            with self.subTest(name), self.assertRaisesMessage(ValueError, 'jamais avant ni entre'):
                self.pipeline.extended(graph)

    def test_a_declared_process_keeps_its_function(self):
        graph = self.pipeline.graph()
        graph['nodes'][1]['app'] = f'function:{self.ADDED}'
        with self.assertRaisesMessage(ValueError, 'sa fonction ne se remplace pas'):
            self.pipeline.extended(graph)

    def test_an_added_process_is_a_function_of_the_catalogue(self):
        with self.assertRaisesMessage(ValueError, "« demo_card_pipeline.nowhere » n'est pas au catalogue"):
            self.pipeline.extended(self._graph(('measure', 'demo_card_pipeline.nowhere', {}),
                                              links=[('render', 'measure')]))

    def test_an_added_process_is_not_the_step_of_another_app(self):
        with self.assertRaisesMessage(ValueError, 'étape de card de demo_card_other'):
            self.pipeline.extended(self._graph(('step', self.STEP, {}),
                                              links=[('render', 'step')]))

    def test_an_added_process_carries_no_field_of_the_card(self):
        for name, value in (('toggle', 'with_measure'), ('outputs', ['measured']),
                            ('upstream_switch', 'reads'), ('card_model', True)):
            with self.subTest(name), self.assertRaisesMessage(ValueError, name):
                self.pipeline.extended(self._graph(('measure', self.ADDED, {name: value}),
                                                  links=[('render', 'measure')]))

    def test_only_processes_compose_a_card(self):
        graph = self.pipeline.graph()
        graph['nodes'].append({'id': 'sink', 'app': 'transcriber', 'params': {}})
        with self.assertRaisesMessage(ValueError, 'seuls des process'):
            self.pipeline.extended(graph)

    def test_two_nodes_with_one_identifier_are_refused(self):
        graph = self._graph(('render', self.ADDED, {}))
        with self.assertRaisesMessage(ValueError, "id 'render' dupliqué"):
            self.pipeline.extended(graph)

    def test_extending_an_extended_pipeline_starts_again_from_the_declared_one(self):
        graph = self._graph(('measure', self.ADDED, {}), links=[('render', 'measure')])
        card_pipeline = self.pipeline.extended(graph)
        self.assertIs(self.pipeline, card_pipeline.extended(self.pipeline.graph()))
        self.assertIs(self.pipeline, card_pipeline.extended(graph).base)

    def test_a_link_to_an_unknown_node_is_refused(self):
        graph = self._graph(('measure', self.ADDED, {}), links=[('render', 'nowhere')])
        with self.assertRaisesMessage(ValueError, "nœud inconnu 'nowhere'"):
            self.pipeline.extended(graph)

    def test_a_cycle_between_added_processes_is_refused_when_built(self):
        graph = self._graph(('measure', self.ADDED, {}), ('again', self.ADDED, {}),
                            links=[('render', 'measure'), ('measure', 'again'),
                                   ('again', 'measure')])
        with self.assertRaisesMessage(ValueError, 'cycle'):
            self.pipeline.extended(graph)

    def test_the_settings_of_an_added_process_are_kept_and_given_back_by_its_graph(self):
        """Marche 2-3 (2026-11-11) : the `params` of an added node are what the common glue gives
        the function — kept on the card pipeline, and given back by `graph()`, so that re-extending
        the card's own graph changes nothing."""
        graph = self._graph(('measure', self.ADDED, {}), links=[('render', 'measure')])
        graph['nodes'][-1]['params'] = {'factor': 2}
        card_pipeline = self.pipeline.extended(graph)
        self.assertEqual({'measure': {'factor': 2}}, card_pipeline.added_params)
        again = self.pipeline.extended(card_pipeline.graph())
        self.assertEqual(({'measure'}, {'factor': 2}),
                         (set(again.added), again.added_params['measure']))
        self.assertEqual({}, self.pipeline.added_params, 'the declared pipeline adds nothing')

    # ── A META-PROCESS : one `pipeline` node per module (validated by Fabien on 2026-11-10) ────
    def _module(self, *members, links=()):
        """A saved pipeline the card may reference : `resolve(key) -> (name, canvas graph)`."""
        sub = {'nodes': [{'id': mid, 'app': app, 'params': dict(params)}
                         for mid, app, params in members],
               'links': [{'from': up, 'to': down, 'to_port': None} for up, down in links]}

        def resolve(key):
            if key != '7':
                raise ValueError(f'pipeline {key} introuvable')
            return 'Module', sub
        return resolve

    def _with_module(self, **params):
        graph = self.pipeline.graph()
        graph['nodes'].append({'id': 'module', 'app': 'pipeline:7', 'params': dict(params)})
        graph['links'].append({'from': 'render', 'to': 'module', 'to_port': None})
        return graph

    def test_a_module_is_ONE_added_process_whose_members_are_catalogue_functions(self):
        resolve = self._module(('cut', f'function:{self.ADDED}', {'threshold': 1}),
                               ('count', f'function:{self.ADDED}', {}),
                               links=[('cut', 'count')])
        card_pipeline = self.pipeline.extended(self._with_module(cut={'threshold': 3}), resolve)
        module = card_pipeline.spec('module')
        self.assertEqual((('render',), '7', 'pipeline:7'),
                         (module.depends_on, module.pipeline, card_pipeline.function_key(module)))
        self.assertEqual(['plan', 'render', 'module'], _keys(card_pipeline.ordered()))
        deployed = card_pipeline.metas['module']
        self.assertEqual(['module/cut', 'module/count'], [n['id'] for n in deployed['nodes']])
        self.assertEqual({'threshold': 3}, deployed['nodes'][0]['params'],
                         'the node keeps only what it OVERRIDES, laid over the referenced one')
        # Its graph gives back the `pipeline` node and its override : the same card pipeline.
        again = self.pipeline.extended(card_pipeline.graph(), resolve)
        self.assertEqual(('7', {'cut': {'threshold': 3}}),
                         (again.spec('module').pipeline, again.added_params['module']))

    def test_a_module_is_read_for_the_account_of_the_card(self):
        with self.assertRaisesMessage(ValueError, 'aucun compte'):
            self.pipeline.extended(self._with_module())
        with self.assertRaisesMessage(ValueError, 'introuvable'):
            self.pipeline.extended(
                {**self._with_module(), 'nodes': self._with_module()['nodes'][:-1]
                 + [{'id': 'module', 'app': 'pipeline:8', 'params': {}}]},
                self._module(('cut', f'function:{self.ADDED}', {})))

    def test_a_module_composes_functions_only_under_the_rules_of_an_added_process(self):
        cases = {
            'ne compose que des fonctions': self._module(('in', 'dataset_input', {})),
            'module › module/step': self._module(('step', f'function:{self.STEP}', {})),
            "n'est pas au catalogue": self._module(('x', 'function:demo_card_pipeline.nowhere',
                                                    {})),
        }
        for message, resolve in cases.items():
            with self.subTest(message), self.assertRaisesMessage(ValueError, message):
                self.pipeline.extended(self._with_module(), resolve)


class WhatALaunchReplaysTest(TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _output(self, name, text='X:1'):
        (Path(self.tmp) / name).write_text(text, encoding='utf-8')
        return name

    def _played(self, pipeline, item, key, output=''):
        """Plays one process the way the skeleton does: snapshot at the start, output at the end."""
        spec = pipeline.spec(key)
        process_runs.start(item, key, settings_snapshot=pipeline.snapshot(spec, item))
        process_runs.succeed(item, key, output_ref=output)

    def _both_played(self, pipeline, item):
        self._played(pipeline, item, 'plan', self._output(f'score{item.pk}.abc'))
        self._played(pipeline, item, 'render', self._output(f'audio{item.pk}.wav', 'RIFF'))

    def test_a_card_that_never_ran_plays_every_process_in_order(self):
        pipeline, item = _two_steps(), _Element()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))

    def test_a_process_that_does_not_apply_to_this_element_is_not_played(self):
        pipeline = _two_steps(applies=lambda item, model_key: model_key == 'writes-scores')
        item = _Element()
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, 'plays-only')))
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item, 'writes-scores')))

    def test_a_failed_last_process_is_replayed_alone(self):
        pipeline, item = _two_steps(), _Element()
        self._played(pipeline, item, 'plan', self._output('score.abc'))
        process_runs.start(item, 'render')
        process_runs.fail(item, 'render', 'out of memory')
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))
        self.assertTrue(pipeline.resumes_from(item, 'plan'))
        self.assertEqual(JOB_FAILURE, pipeline.card_state(item))

    def test_a_setting_of_the_last_process_does_not_replay_the_first(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        item.duration = 60
        self.assertEqual({'render'}, pipeline.refresh(item))
        self.assertEqual(JOB_STALE, pipeline.card_state(item))
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'plan').status)

    def test_a_setting_of_the_first_process_replays_everything_downstream(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        item.prompt = 'a fast drum solo'
        self.assertEqual({'plan', 'render'}, pipeline.refresh(item))
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertFalse(pipeline.resumes_from(item, 'plan'))

    def test_an_upstream_output_that_was_replaced_makes_the_downstream_stale(self):
        """The third cause of point 4.3: nobody changed a setting, somebody rewrote the score."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertIn(UPSTREAM_KEY, process_runs.line(item, 'render').settings_snapshot)
        self.assertEqual(set(), pipeline.refresh(item), 'nothing changed, nothing is stale')
        self._output(f'score{item.pk}.abc', 'X:1 corrected by hand')
        self.assertEqual({'render'}, pipeline.refresh(item))
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item)))

    def test_an_upstream_output_gone_then_restored_identical_stales_nothing(self):
        """2026-10-27 : `media/` lost then restored — an absent file has no fingerprint, it is not
        a change ; only a DIFFERENT fingerprint stales. The lost output is replayed, not staled."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        score = Path(self.tmp) / f'score{item.pk}.abc'
        score.unlink()
        self.assertEqual(set(), pipeline.refresh(item), 'a missing file is not a new fingerprint')
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        from django.template.loader import render_to_string
        rows = pipeline.card_rows(item)
        self.assertEqual({'plan': True, 'render': False}, {r['key']: r['lost'] for r in rows},
                         'the band says which output is lost, and only that one')
        html = render_to_string('common/_card_processes.html', {'processes': rows, 'card_id': 7})
        self.assertEqual(1, html.count('>sortie perdue<'), html)
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item, only='render')),
                         'the lost score is replayed before its downstream')
        self._output(score.name)
        self.assertEqual(set(), pipeline.refresh(item), 'restored identical: still up to date')
        self.assertFalse(any(r['lost'] for r in pipeline.card_rows(item)))
        self._output(score.name, 'X:1 another score')
        self.assertEqual({'render'}, pipeline.refresh(item))

    def test_a_valid_card_relaunched_replays_everything(self):
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))
        self.assertFalse(pipeline.resumes_from(item, 'plan'))

    def test_it_still_replays_everything_once_the_launcher_removed_the_last_output(self):
        """The launcher resets the card BEFORE the task asks what to play (`begin_processing`):
        reading the missing file first would turn a full relaunch into a resume of the last
        process."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        (Path(self.tmp) / f'audio{item.pk}.wav').unlink()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))

    def test_a_result_whose_file_is_gone_is_not_resumed_from(self):
        pipeline, item = _two_steps(), _Element()
        self._played(pipeline, item, 'plan', self._output('score.abc'))
        process_runs.start(item, 'render')
        process_runs.fail(item, 'render', 'boom')
        (Path(self.tmp) / 'score.abc').unlink()
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item)))

    def test_one_process_alone_takes_its_stale_upstreams_and_never_its_downstream(self):
        """▶ par process (P5) : the asked process always runs ; an upstream still valid is
        resumed from, a stale one is replayed first ; the downstream is left alone — it will
        turn stale by itself once its upstream output changed."""
        pipeline, item = _two_steps(), _Element()
        self._both_played(pipeline, item)
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, only='render')))
        self.assertEqual(['plan'], _keys(pipeline.steps_to_run(item, only='plan')),
                         'the downstream render must not be dragged along')
        item.prompt = 'a fast drum solo'           # plan stale → render asked alone replays it first
        self.assertEqual(['plan', 'render'], _keys(pipeline.steps_to_run(item, only='render')))

    def test_a_process_asked_alone_must_exist_and_apply(self):
        pipeline, item = _two_steps(applies=lambda item, model_key: False), _Element()
        with self.assertRaisesMessage(ValueError, 'plan'):
            pipeline.steps_to_run(item, only='plan')
        with self.assertRaisesMessage(ValueError, 'master'):
            pipeline.steps_to_run(item, only='master')

    def test_resetting_the_outputs_of_one_process_leaves_the_others(self):
        """Relaunching the score alone must not take the audio away."""
        class _File:
            def __init__(self, name):
                self.name = name
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('plan', outputs=('score_file',)),
            ProcessSpec('render', depends_on=('plan',), outputs=('audio_file',)),
        ), label='Demo')
        item = _Element(score_file=_File('s.abc'), audio_file=_File('a.wav'))
        with mock.patch('wama.common.utils.queue_duplication.safe_delete_file',
                        return_value=True) as deleted:
            self.assertEqual(['score_file'], pipeline.reset_outputs(item, ['plan']))
        deleted.assert_called_once_with(item, 'score_file')
        self.assertIsNone(item.score_file)
        self.assertEqual('a.wav', item.audio_file.name)

    def test_an_upstream_that_never_ran_makes_nobody_stale(self):
        """A process that did not apply (no line) is not a missing upstream."""
        pipeline, item = _two_steps(applies=lambda item, model_key: False), _Element()
        self._played(pipeline, item, 'render', self._output('audio.wav', 'RIFF'))
        self.assertEqual(set(), pipeline.refresh(item))
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))

    def test_the_line_of_a_single_process_card_is_not_one_of_the_pipeline(self):
        pipeline, item = _two_steps(), _Element()
        process_runs.start(item)
        process_runs.succeed(item)
        self.assertEqual({}, pipeline.rows(item))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))

    def test_a_file_setting_is_compared_by_its_path(self):
        """The snapshot is read back from JSON: a file field must be written as its path, or a
        card would be stale the moment it is read."""
        class _File:
            """Like a `FieldFile`: its text form is its path."""

            def __init__(self, name):
                self.name = name

            def __str__(self):
                return self.name
        pipeline = AppPipeline('demo_pipeline', (ProcessSpec('render', watched=('given_score',)),),
                               label='x')
        item = _Element(given_score=_File('users/1/in.abc'))
        self._played(pipeline, item, 'render')
        self.assertEqual({'given_score': 'users/1/in.abc'},
                         process_runs.line(item, 'render').settings_snapshot)
        self.assertEqual(set(), pipeline.refresh(item))
        item.given_score = _File('users/1/other.abc')
        self.assertEqual({'render'}, pipeline.refresh(item))


class AnUpstreamThatNoLongerTakesPlaceTest(WhatALaunchReplaysTest):
    """2026-10-21 — measured before the fix: an upstream that stops taking place for the element
    (the leveling unticked, the cover audio removed) kept its line, made stale by the setting that
    removed it — and its downstream, replayed without it, was stale again at every read (`refresh`
    → {'render'} after the relaunch, the card « stale » for ever). A line counts as long as the
    ELEMENT asks for its process (`still_counts`) ; the downstream that read it is stale ONCE."""

    def _prepared(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('prep', watched=('level',), applies=lambda item, mk: bool(item.level)),
            ProcessSpec('render', depends_on=('prep',), watched=('prompt',)),
        ), label='Demo', model_of=lambda item: 'any')

    def test_the_downstream_is_stale_once_and_valid_again_once_replayed_without_it(self):
        pipeline, item = self._prepared(), _Element(level=True)
        self._played(pipeline, item, 'prep', self._output(f'prep{item.pk}.wav', 'RIFF1'))
        self._played(pipeline, item, 'render', self._output(f'out{item.pk}.txt', 'A'))
        item.level = False
        self.assertEqual({'render'}, pipeline.refresh(item), 'it was rendered from the prep')
        self.assertEqual(['render'], _keys(pipeline.steps_to_run(item, 'any')))
        self._played(pipeline, item, 'render', self._output(f'out{item.pk}.txt', 'B'))
        self.assertEqual(set(), pipeline.refresh(item))
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        # Since 2026-11-07 (Fabien: « toujours afficher toutes les étapes », greyed) the strip still
        # SHOWS the process the element no longer plays — as « sans objet », with its reason.
        rows = {row['key']: row for row in pipeline.card_rows(item, 'any')}
        self.assertEqual(['prep', 'render'], list(rows))
        self.assertEqual(('na', 'Sans objet pour cette card'), (rows['prep']['state'],
                                                                 rows['prep']['reason']))
        self.assertEqual('active', rows['render']['state'])

    def test_under_a_model_not_drawn_yet_only_the_switch_judges(self):
        """« auto » before the draw : `requested_model` is None — the line is not guessed away."""
        pipeline, item = self._prepared(), _Element(level=True)
        self._played(pipeline, item, 'prep', self._output(f'prep{item.pk}.wav', 'RIFF1'))
        self.assertTrue(pipeline.still_counts(pipeline.spec('prep'), _Element(level=False), None))

    def test_what_is_installed_does_not_judge_a_result(self):
        """Uninstalling a model does not change the card: its results stand."""
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('prep', available=lambda: False),
            ProcessSpec('render', depends_on=('prep',)),
        ), label='Demo')
        self.assertTrue(pipeline.still_counts(pipeline.spec('prep'), _Element(), 'any'))
        self.assertFalse(pipeline.takes_place(pipeline.spec('prep'), _Element(), 'any'))


class WhatADownstreamReadsTest(SimpleTestCase):
    """`AppPipeline.output_of` / `upstream_output` (2026-10-21) : a downstream reads the output of
    its upstream by ONE gesture — the file, while its process takes place — and the data follows
    the declared links: the nearest upstream that rendered the asked type, the one before it when
    it rendered nothing (its process failed), the card's input when none did."""

    class _File:
        def __init__(self, name):
            self.name = name

    def _chain(self):
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('level', applies=lambda item, mk: item.level, outputs=('leveled',)),
            ProcessSpec('denoise', depends_on=('level',), degree='optional', toggle='denoise_on',
                        outputs=('denoised',)),
            ProcessSpec('transcribe', depends_on=('level', 'denoise')),
            ProcessSpec('speakers', depends_on=('transcribe',)),
        ), label='Demo')
        types = {'level': 'audio', 'denoise': 'audio', 'transcribe': 'document'}
        patcher = mock.patch.object(AppPipeline, 'output_type',
                                    lambda self, spec: types.get(spec.key, ''))
        patcher.start()
        self.addCleanup(patcher.stop)
        return pipeline

    def test_the_nearest_upstream_that_rendered_the_type_is_read(self):
        pipeline = self._chain()
        item = _Element(level=True, denoise_on=True, leveled=self._File('l.wav'),
                        denoised=self._File('d.wav'))
        self.assertEqual('d.wav', pipeline.upstream_output(item, 'transcribe', 'audio'))
        self.assertEqual('d.wav', pipeline.upstream_output(item, 'speakers', 'audio'),
                         'through the transcription, which renders no audio')
        item.denoised = None                      # the denoising failed: its field stayed empty
        self.assertEqual('l.wav', pipeline.upstream_output(item, 'transcribe', 'audio'))

    def test_an_upstream_that_does_not_take_place_is_never_read_even_with_its_old_file(self):
        pipeline = self._chain()
        item = _Element(level=False, denoise_on=False, leveled=self._File('old.wav'),
                        denoised=None)
        self.assertEqual('', pipeline.output_of(item, 'level'))
        self.assertEqual('', pipeline.upstream_output(item, 'transcribe', 'audio'),
                         'the card input, then')


class AProcessSplitFromItsDownstreamTest(WhatALaunchReplaysTest):
    """`ProcessSpec.split_from` (2026-10-21, the leveling taken out of the transcription) : a
    downstream line rendered BEFORE the split did the work itself — its photo still holds the
    settings of the split process. It stands for it while they did not change: an old card is
    not transcribed again for a changed kind of summary."""

    def _split(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('prep', watched=('level',), split_from='render'),
            ProcessSpec('render', depends_on=('prep',), watched=('prompt',)),
            ProcessSpec('summary', depends_on=('render',), watched=('kind',)),
        ), label='Demo')

    def _old_card(self, pipeline):
        item = _Element(level=True, kind='short')
        before = AppPipeline('demo_pipeline', (
            ProcessSpec('render', watched=('prompt', 'level')),
            ProcessSpec('summary', depends_on=('render',), watched=('kind',)),
        ), label='Demo')
        self._played(before, item, 'render', self._output(f'out{item.pk}.txt', 'A'))
        self._played(before, item, 'summary', self._output(f'sum{item.pk}.txt', 'S'))
        return item

    def test_the_old_line_stands_for_the_split_process(self):
        pipeline = self._split()
        item = self._old_card(pipeline)
        self.assertEqual(set(), pipeline.refresh(item))
        item.kind = 'long'
        self.assertEqual(['summary'], _keys(pipeline.steps_to_run(item, 'any')),
                         'the old render did the prep itself: neither is replayed')
        rows = {row['key']: row for row in pipeline.card_rows(item, 'any')}
        self.assertEqual(JOB_SUCCESS, rows['prep']['status'])
        self.assertIn('« render »', rows['prep']['output_label'], 'the strip says where it was done')

    def test_a_changed_setting_of_the_split_process_stales_the_old_line(self):
        pipeline = self._split()
        item = self._old_card(pipeline)
        item.level = False
        self.assertEqual({'render', 'summary'}, pipeline.refresh(item))
        self.assertEqual(['prep', 'render', 'summary'], _keys(pipeline.steps_to_run(item, 'any')))

    def test_a_line_rendered_after_the_split_holds_nothing(self):
        pipeline, item = self._split(), _Element(level=True, kind='short')
        self._played(pipeline, item, 'render', self._output(f'out{item.pk}.txt', 'A'))
        self.assertEqual(['prep', 'render', 'summary'], _keys(pipeline.steps_to_run(item, 'any')))

    def test_the_split_process_must_be_an_upstream_of_its_origin(self):
        with self.assertRaisesMessage(ValueError, 'split_from'):
            AppPipeline('demo', (ProcessSpec('prep', split_from='render'),
                                 ProcessSpec('render')), label='x')


class AResultOlderThanThePipelineTest(TestCase):
    """2026-10-13 — Fabien's transcript #739 (28/09) predates the transcriber pipeline (03/10): no
    line, so nothing was « up to date » and the ▶ of « Locuteurs » re-listened to the whole audio.
    A SUCCESSFUL element proves its `required` processes rendered: the first read of the element
    (a queue page, `preload`) or its launch (`begin_processing`) BACKFILLS them a line ; an
    `optional` one, unknown, stays to be played. Common to every app with a pipeline."""

    def _pipeline(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('transcribe', watched=('prompt',)),
            ProcessSpec('diarize', depends_on=('transcribe',), degree='optional',
                        toggle='wants_speakers'),
        ), label='Demo')

    def test_the_required_process_is_backfilled_and_the_option_alone_is_played(self):
        from wama.common.services import process_pipeline
        pipeline = self._pipeline()
        item = _Element(status=JOB_SUCCESS, wants_speakers=True)
        self.assertEqual(['transcribe', 'diarize'], _keys(pipeline.steps_to_run(item)),
                         'without the backfill, everything is replayed — the defect')
        with mock.patch.dict(APP_PIPELINES, {'demo_pipeline': pipeline}):
            process_pipeline.preload([item])
        process_pipeline.release(item)
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'transcribe').status)
        self.assertIsNone(process_runs.line(item, 'diarize'), 'an optional was invented')
        self.assertEqual(['diarize'], _keys(pipeline.steps_to_run(item, only='diarize')))
        self.assertEqual(['diarize'], _keys(pipeline.steps_to_run(item)))

    def test_nothing_is_backfilled_for_an_element_not_successful_or_already_tracked(self):
        pipeline = self._pipeline()
        self.assertEqual({}, pipeline.backfill_prior_runs(_Element(status=JOB_PENDING)))
        self.assertEqual({}, pipeline.backfill_prior_runs(_Element(status=JOB_RUNNING)))
        tracked = _Element(status=JOB_SUCCESS)
        process_runs.fail(tracked, 'transcribe', 'out of memory')
        self.assertEqual({}, pipeline.backfill_prior_runs(tracked))
        self.assertEqual(JOB_FAILURE, process_runs.line(tracked, 'transcribe').status)

    def test_a_setting_changed_after_the_backfill_makes_it_stale(self):
        pipeline = self._pipeline()
        item = _Element(status=JOB_SUCCESS)
        pipeline.backfill_prior_runs(item)
        item.prompt = 'another language'
        self.assertEqual(['transcribe'], _keys(pipeline.steps_to_run(item)))

    def test_a_launch_backfills_a_card_no_page_has_read(self):
        """2026-10-14 — the backfill only ran on a page read: a ▶ from the assistant or a
        scheduled action, on a card never displayed since, replayed everything. The launch
        (`begin_processing`, every app) backfills before RUNNING, while the element is still
        successful."""
        from wama.common.utils.process_control import begin_processing
        item = _Element(status=JOB_SUCCESS, task_id='', save=lambda: None)

        class _Model:
            class objects:
                @staticmethod
                def select_for_update():
                    return mock.Mock(get=lambda pk: item)

        with mock.patch.dict(APP_PIPELINES, {'demo_pipeline': self._pipeline()}):
            obj, err = begin_processing(_Model, item.pk)
        self.assertIsNone(err)
        self.assertEqual('RUNNING', obj.status)
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'transcribe').status)
        self.assertEqual({'backfilled': True}, process_runs.line(item, 'transcribe').output_summary)


class WhatTheCardShowsTest(TestCase):
    """P5 — the card shows its processes and ONE state, read through the adapter
    (`shown_state`), never `item.status` alone: a stale render under a « successful » element
    is what the lines know and the element does not."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        media = override_settings(MEDIA_ROOT=self.tmp)
        media.enable()
        self.addCleanup(media.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('plan', label='Partition', watched=('prompt',),
                        applies=lambda item, model_key: model_key == 'writes-scores'),
            ProcessSpec('render', label='Rendu', depends_on=('plan',), watched=('duration',)),
        ), label='Demo')

    def _played(self, item, key, output=''):
        spec = self.pipeline.spec(key)
        process_runs.start(item, key, settings_snapshot=self.pipeline.snapshot(spec, item),
                           model_key='family:m')
        process_runs.succeed(item, key, output_ref=output, output_summary={'label': key + '.out'})

    def test_an_element_in_flight_is_shown_as_the_element_says(self):
        item = _Element(status=JOB_RUNNING)
        self.assertEqual(JOB_RUNNING, self.pipeline.shown_state(item))
        item.status = 'AWAITING_RESOURCES'
        self.assertEqual('AWAITING_RESOURCES', self.pipeline.shown_state(item))

    def test_without_any_line_the_element_alone_is_shown(self):
        item = _Element(status=JOB_PENDING)
        self.assertEqual(JOB_PENDING, self.pipeline.shown_state(item))
        # Since 2026-11-07 every step is shown (Fabien: « toujours afficher toutes les étapes »):
        # the model unknown, the plan — which applies to one model only — is there, « sans
        # objet », and only the render can be launched.
        rows = {r['key']: r['state'] for r in self.pipeline.card_rows(item)}
        self.assertEqual({'plan': 'na', 'render': 'active'}, rows)

    def test_each_row_says_what_its_process_watches_for_its_own_gear(self):
        """⚙ par process (P5) : the gear of a row shows the settings the process WATCHES — read
        from the declaration, never a list written in a template."""
        item = _Element(status=JOB_SUCCESS)
        self._played(item, 'plan')
        self._played(item, 'render')
        rows = {r['key']: r['watched'] for r in self.pipeline.card_rows(item)}
        self.assertEqual({'plan': ['prompt'], 'render': ['duration']}, rows)

    def test_a_useless_step_leaves_the_flow_and_folds_at_the_end_of_the_strip(self):
        """2026-11-08, Fabien précise sa décision du 07/11 : « une étape inutile n'a pas lieu
        d'apparaître et il faut gérer ça dynamiquement en fonction des entrées/modèles ». Useless =
        no object because of the ELEMENT (or the designated model), nothing produced : out of the
        columns, folded in « + n sans objet ». Counter-proofs : a step the user switched off stays
        in the flow (he switches it back on) ; the same useless step that already HAS a line stays
        too (its result exists)."""
        from django.template.loader import render_to_string
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('cover', label='Lecture du cover', degree='optional',
                        applies=lambda item, model_key: bool(getattr(item, 'audio', ''))),
            ProcessSpec('render', label='Rendu', depends_on=('cover',)),
            ProcessSpec('summary', label='Résumé', depends_on=('render',), degree='optional',
                        toggle='wants_summary'),
        ), label='Demo')
        item = _Element(status=JOB_PENDING, audio='', wants_summary=False)
        rows = pipeline.card_rows(item)
        self.assertEqual([('render', False, 0), ('summary', False, 1), ('cover', True, None)],
                         [(r['key'], r['hidden'], r['column']) for r in rows],
                         'the columns count only what is shown ; the folded one comes last')
        html = render_to_string('common/_card_processes.html', {'processes': rows, 'card_id': 7})
        flow, folded = html.split('data-processes-folded')
        self.assertNotIn('data-process="cover"', flow)
        self.assertIn('data-process="summary"', flow, 'switched off by the user : still shown')
        self.assertIn('+ 1 sans objet', folded)
        self.assertIn('data-process="cover"', folded)
        process_runs.start(item, 'cover')
        process_runs.succeed(item, 'cover')
        self.assertFalse(next(r for r in pipeline.card_rows(item) if r['key'] == 'cover')['hidden'],
                         'a step that produced something is never folded')

    def test_the_gear_of_a_step_also_shows_what_it_writes_without_staling_it(self):
        """2026-11-08, Fabien : « la modale d'écrire les paroles devrait contenir le champ paroles et
        le bouton de génération ». What a step WRITES (`ProcessSpec.writes`) joins its gear — on the
        card (`settings` → `data-only`) and on the Studio node (`step_settings`) — but not what it
        watches : changing the lyrics does not stale the step that wrote them (counter-proof)."""
        from django.template.loader import render_to_string
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('write', label='Paroles écrites', watched=('prompt',), writes=('lyrics',)),
            ProcessSpec('render', label='Rendu', depends_on=('write',), watched=('duration',)),
        ), label='Demo')
        self.assertEqual(('prompt', 'lyrics'), pipeline.step_settings(pipeline.spec('write')))
        self.assertNotIn('lyrics', pipeline.watched_of(pipeline.spec('write')))
        item = _Element(status=JOB_PENDING, prompt='la mer', lyrics='')
        rows = {r['key']: r for r in pipeline.card_rows(item)}
        self.assertEqual(['prompt', 'lyrics'], rows['write']['settings'])
        self.assertEqual(['duration'], rows['render']['settings'], 'nothing written : the watched ones')
        html = render_to_string('common/_card_processes.html', {'processes': list(rows.values()),
                                                                'card_id': 7})
        self.assertRegex(html, r'data-process="write" data-only="prompt,lyrics"')
        self.assertIn('lyrics', [p for p in pipeline.graph()['nodes']
                                 if p['id'] == 'write'][0]['process']['writes'])

    # ── the switch of an optional process (3.2) and non-file outputs ───────────────────────────
    def _with_an_option(self):
        return AppPipeline('demo_pipeline', (
            ProcessSpec('render', label='Rendu', watched=('duration',)),
            ProcessSpec('summary', label='Résumé', depends_on=('render',), degree='optional',
                        toggle='wants_summary'),
        ), label='Demo')

    def test_a_required_process_may_carry_a_switch_and_stays_required_when_on(self):
        """2026-11-07 (Fabien: « rendu facultatif »): a REQUIRED process may carry a switch —
        required when on (its failure fails the card), ignored off. Declared `optional`, a failed
        render would have left the card « to be completed » instead of saying it failed."""
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('render', label='Rendu', toggle='wants_it'),), label='Demo')
        item = _Element(status=JOB_PENDING, wants_it=True)
        process_runs.start(item, 'render')
        process_runs.fail(item, 'render', 'out of memory')
        self.assertEqual(JOB_FAILURE, pipeline.card_state(item))
        item.wants_it = False
        self.assertEqual([], _keys(pipeline.applicable(item)))
        self.assertEqual('off', pipeline.card_rows(item)[0]['state'])

    def test_what_the_model_imposes_needs_a_switch_to_impose(self):
        with self.assertRaises(ValueError) as refused:
            AppPipeline('demo_pipeline', (ProcessSpec('score', degree='optional',
                                                      required_by='follows_a_score'),), label='Demo')
        self.assertIn('required_by', str(refused.exception))

    def test_an_option_switched_off_does_not_take_place_and_no_longer_weighs_on_the_card(self):
        """Rule 4.4: « les optional désactivés sont ignorés ». A failed summary keeps the card
        « to be completed » ; switching the summary OFF makes the card successful again, and the
        row stays in the strip — unchecked — so that it can be switched back on."""
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=True)
        process_runs.start(item, 'render', settings_snapshot=pipeline.snapshot(pipeline.spec('render'), item))
        process_runs.succeed(item, 'render')
        process_runs.start(item, 'summary')
        process_runs.fail(item, 'summary', 'model down')
        self.assertEqual(['render', 'summary'], _keys(pipeline.applicable(item)))
        self.assertEqual(JOB_PENDING, pipeline.card_state(item))
        item.wants_summary = False
        self.assertEqual(['render'], _keys(pipeline.applicable(item)))
        self.assertEqual(JOB_SUCCESS, pipeline.card_state(item))
        self.assertEqual(JOB_SUCCESS, pipeline.shown_state(item))
        rows = {r['key']: (r['toggle'], r['enabled']) for r in pipeline.card_rows(item)}
        self.assertEqual({'render': ('', True), 'summary': ('wants_summary', False)}, rows)

    def test_the_strip_gives_an_option_its_checkbox_and_dims_it_when_off(self):
        from django.template.loader import render_to_string
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=False)
        for key in ('render', 'summary'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        html = render_to_string('common/_card_processes.html', {
            'processes': pipeline.card_rows(item), 'card_id': 7, 'settings_url': '/demo/settings/7/'})
        self.assertRegex(html, r'wcv3-proc--off"[^>]*data-process="summary"')
        self.assertRegex(html, r'wcv3-proc-toggle"[^>]*data-toggle-field="wants_summary"'
                               r'[^>]*data-settings-url="/demo/settings/7/"')
        self.assertNotRegex(html, r'wcv3-proc-toggle"[^>]*\bchecked\b')
        self.assertNotRegex(html, r'wcv3-proc-run"[^>]*data-process="summary"',
                            'a process switched off has no ▶')
        self.assertRegex(html, r'wcv3-proc-run"[^>]*data-process="render"')

    # ── branches: the strip lays the graph out as the studio does (one column per depth) ───────
    def _branching(self):
        """The composer's shape: two roots, one of them a side output, and two processes that
        read the render. `full` is declared AFTER `render`: the strip still puts it beside the
        other root."""
        return AppPipeline('demo_pipeline', (
            ProcessSpec('score', label='Partition'),
            ProcessSpec('render', label='Rendu', depends_on=('score',)),
            ProcessSpec('full', label='Partition complète'),
            ProcessSpec('output', label='Sortie', depends_on=('render',)),
            ProcessSpec('render_score', label='Partition de sortie', depends_on=('render',)),
        ), label='Demo')

    def test_processes_of_the_same_depth_share_a_column_and_a_side_output_says_so(self):
        pipeline = self._branching()
        item = _Element(status=JOB_SUCCESS)
        for key in ('score', 'render', 'full', 'output', 'render_score'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        rows = pipeline.card_rows(item)
        self.assertEqual([('score', 0), ('full', 0), ('render', 1), ('output', 2),
                          ('render_score', 2)], [(r['key'], r['column']) for r in rows])
        by_key = {r['key']: r for r in rows}
        self.assertEqual(['Rendu'], by_key['render_score']['after'])
        self.assertEqual([], by_key['full']['after'])
        self.assertEqual({'full'}, {r['key'] for r in rows if r['branch_end']},
                         'only a process that feeds nothing while a column follows is a side '
                         'output — the last column ends every chain')

        from django.template.loader import render_to_string
        html = render_to_string('common/_card_processes.html', {'processes': rows, 'card_id': 7})
        self.assertEqual(3, html.count('class="wcv3-proc-col'))
        self.assertEqual(2, html.count('wcv3-proc-col--branches'))
        self.assertEqual(2, html.count('wcv3-proc-sep'), 'arrows go between columns only')
        self.assertRegex(html, r'data-process="full"[^>]*title="[^"]*branche')
        self.assertEqual(1, html.count('wcv3-proc-branch"'))

    def test_a_chain_without_branches_keeps_one_line(self):
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=True)
        for key in ('render', 'summary'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        from django.template.loader import render_to_string
        html = render_to_string('common/_card_processes.html',
                                {'processes': pipeline.card_rows(item), 'card_id': 7})
        self.assertNotIn('wcv3-proc-col--branches', html)
        self.assertNotIn('wcv3-proc-branch"', html)
        self.assertEqual(1, html.count('wcv3-proc-sep'))

    def test_under_auto_a_process_that_needs_no_model_shows_with_its_checkbox(self):
        """2026-10-26, Fabien : the composer's « Partition de sortie » was in the settings, not
        on the card. Under « auto » the model is unknown, so a never-played process whose taking
        place DEPENDS on the model (`applies`) stays hidden — nothing is guessed —, but one that
        declares no `applies` takes place whatever the draw : it shows, an optional one with its
        checkbox, so that it can be switched on from the card."""
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('score', label='Partition',
                        applies=lambda item, model_key: model_key == 'writes-scores'),
            ProcessSpec('render', label='Rendu', depends_on=('score',)),
            ProcessSpec('output', label='Sortie', depends_on=('render',)),
            ProcessSpec('render_score', label='Partition de sortie', depends_on=('render',),
                        degree='optional', toggle='wants_it'),
        ), label='Demo')
        item = _Element(status=JOB_SUCCESS, wants_it=False)
        for key in ('render', 'output'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        rows = {r['key']: r for r in pipeline.card_rows(item)}
        # Since 2026-11-07 every step shows; since 2026-11-08 one with no object FOLDS at the end
        # (Fabien : « une étape inutile n'a pas lieu d'apparaître ») — this `applies` reads the
        # model, which a real app declares as a `needs` (then it would be « dépend du tirage »).
        self.assertEqual(['render', 'output', 'render_score', 'score'], list(rows))
        self.assertEqual(('na', True), (rows['score']['state'], rows['score']['hidden']))
        self.assertFalse(rows['render_score']['hidden'], 'switched off by the user : in the flow')
        self.assertEqual(('wants_it', False, 'off'), (rows['render_score']['toggle'],
                                                      rows['render_score']['enabled'],
                                                      rows['render_score']['state']))

    def test_under_auto_an_option_the_element_allows_shows_before_any_launch(self):
        """2026-11-07, Fabien: « la partition complète activée ne s'affiche pas sur la card ». An
        optional process with a switch whose `applies` judges the ELEMENT (an input audio is there)
        is the user's choice: under « auto » it is ACTIVE when checked, OFF when not, before
        anything ran — so it can be launched alone. One the element rules out (no input audio) is
        « sans objet » with its reason — folded at the end since 2026-11-08, its reason kept, and
        so even when checked : the element decides before the switch."""
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('score', label='Partition',
                        applies=lambda item, model_key: model_key == 'writes-scores'),
            ProcessSpec('parts', label='Partition complète', degree='optional', toggle='wants_parts',
                        applies=lambda item, model_key: bool(item.has_audio)),
            ProcessSpec('render', label='Rendu', depends_on=('score',)),
        ), label='Demo')
        for wants, state in ((True, 'active'), (False, 'off')):
            rows = {r['key']: r for r in pipeline.card_rows(
                _Element(status=JOB_PENDING, wants_parts=wants, has_audio=True))}
            self.assertEqual(['parts', 'render', 'score'], list(rows), 'the useless one folds last')
            self.assertEqual(('wants_parts', wants, state), (rows['parts']['toggle'],
                                                             rows['parts']['enabled'],
                                                             rows['parts']['state']))
        rows = {r['key']: r for r in pipeline.card_rows(
            _Element(status=JOB_PENDING, wants_parts=True, has_audio=False))}
        self.assertEqual(('na', 'Sans objet pour cette card', True),
                         (rows['parts']['state'], rows['parts']['reason'], rows['parts']['hidden']),
                         'an option the element rules out is folded, with its reason')

    def test_a_cut_switch_starves_only_what_reads_a_link_from_it_in_every_real_app(self):
        """`starved` (2026-11-07, « rendu facultatif ») measured on the REAL pipelines : switching
        ONE switch off, only the steps that read nothing but a LINK from the cut step stop — the
        composer's output, output score and output lyrics without the render. A step that
        transforms an entry of the card (the anonymizer's reading of scanned pages, the
        transcriber's audio preparation) starves nothing : its downstream reads the original.
        Measured the same day, before the precision : cutting the OCR dropped the text detection.
        A new switch that starves something makes this fail — look at it, then write it here."""
        from types import SimpleNamespace
        from wama.common.services.process_pipeline import _load_declarations
        from wama.common.sandbox import sandbox_labels
        _load_declarations()
        twins = set(sandbox_labels())
        found = {}
        for app, pipeline in sorted(APP_PIPELINES.items()):
            if app in twins or app.startswith('demo'):
                continue
            base = {s.toggle: True for s in pipeline.specs if s.toggle}
            base.update({s.upstream_switch: True for s in pipeline.specs if s.upstream_switch})
            for toggle in sorted(t for t in base if any(s.toggle == t for s in pipeline.specs)):
                item = SimpleNamespace(**{**base, toggle: False})
                starved = [s.key for s in pipeline.specs if pipeline.starved(s, item, None)]
                if starved:
                    found[(app, toggle)] = starved
        self.assertEqual({('composer', 'generate_audio'): ['output', 'rendered_score', 'rendered_parts',
                                                            'rendered_lyrics']}, found)

    def test_a_cut_step_that_transforms_a_card_entry_starves_nothing(self):
        """The precision itself, on a fictitious pipeline : the upstream TAKES the `work_file` it
        hands on (it transforms the card's entry) — cut, its downstream reads the original."""
        from wama.common.catalog.function_catalog import (FUNCTION_CATALOG, Binding, FunctionSpec,
                                                          PortSpec)
        keys = ('demo_starve.ocr', 'demo_starve.detect', 'demo_starve.render', 'demo_starve.out')
        for key, inputs, outputs in (
                (keys[0], [PortSpec('work_file', 'document')], [PortSpec('read', 'document')]),
                (keys[1], [PortSpec('work_file', 'document')], [PortSpec('found', 'detections')]),
                (keys[2], [PortSpec('prompt', 'prompt')], [PortSpec('audio', 'audio')]),
                (keys[3], [PortSpec('native', 'audio')], [PortSpec('result', 'audio')])):
            FUNCTION_CATALOG[key] = FunctionSpec(
                key=key, name=key, description='', category='transform', binding=Binding.APP,
                app='demo_starve', inputs=inputs, outputs=outputs)
        self.addCleanup(lambda: [FUNCTION_CATALOG.pop(k, None) for k in keys])
        pipeline = AppPipeline('demo_starve', (
            ProcessSpec('ocr', function=keys[0], degree='optional', toggle='wants_ocr'),
            ProcessSpec('detect', function=keys[1], depends_on=('ocr',)),
            ProcessSpec('render', function=keys[2], toggle='wants_render'),
            ProcessSpec('out', function=keys[3], depends_on=('render',)),
        ), label='Demo')
        item = _Element(wants_ocr=False, wants_render=False)
        self.assertFalse(pipeline.starved(pipeline.spec('detect'), item))
        self.assertTrue(pipeline.starved(pipeline.spec('out'), item))
        self.assertEqual(['detect'], _keys(pipeline.applicable(item, 'any')))

    def test_each_cause_of_a_step_that_does_not_take_place_is_said(self):
        """The reasons the strip gives (`AppPipeline.REASONS`): nothing installed, its input cut
        by the user, the model, the draw still to come — never a hidden step."""
        from unittest import mock
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('extract', label='Extraction', available=lambda: False),
            ProcessSpec('render', label='Rendu', toggle='wants_render'),
            ProcessSpec('lyrics', label='Paroles', degree='optional', needs='supports_vocals'),
        ), label='Demo')
        item = _Element(status=JOB_PENDING, wants_render=True)
        with mock.patch.object(AppPipeline, 'model_serves', return_value=False):
            rows = {r['key']: (r['state'], r['reason']) for r in pipeline.card_rows(item, 'demo:noise')}
        self.assertEqual({'extract': ('na', AppPipeline.REASONS['unavailable']),
                          'render': ('active', ''),
                          'lyrics': ('na', AppPipeline.REASONS['model'])}, rows)
        rows = {r['key']: (r['state'], r['reason']) for r in pipeline.card_rows(item, None)}
        self.assertEqual(('active', AppPipeline.REASONS['draw']), rows['lyrics'],
                         'under « auto » nothing is guessed: the reason says it')

    def test_a_process_that_does_not_take_place_folds_and_the_chain_closes_up(self):
        """A → B → C with B absent for this card: 2026-11-07 showed B « sans objet » in the chain ;
        since 2026-11-08 (Fabien : « une étape inutile n'a pas lieu d'apparaître ») it FOLDS at the
        end, out of the columns — C follows A, read THROUGH B (`after`) —, still carried, with its
        state."""
        pipeline = AppPipeline('demo_pipeline', (
            ProcessSpec('first', label='A'),
            ProcessSpec('middle', label='B', depends_on=('first',),
                        applies=lambda item, model_key: False),
            ProcessSpec('last', label='C', depends_on=('middle',)),
        ), label='Demo')
        item = _Element(status=JOB_SUCCESS)
        for key in ('first', 'last'):
            process_runs.start(item, key)
            process_runs.succeed(item, key)
        rows = pipeline.card_rows(item, 'any')
        self.assertEqual([('first', 0, [], 'active'), ('last', 1, ['A'], 'active'),
                          ('middle', None, [], 'na')],
                         [(r['key'], r['column'], r['after'], r['state']) for r in rows])

    def test_an_output_that_is_not_a_file_makes_its_downstream_stale_when_it_changes(self):
        """A transcription is text in the base, not a file: its glue DECLARES a fingerprint
        (`output_fingerprint`), kept on the line — replaced, the downstream goes stale."""
        pipeline = self._with_an_option()
        item = _Element(status=JOB_SUCCESS, wants_summary=True)
        process_runs.start(item, 'render',
                           settings_snapshot=pipeline.snapshot(pipeline.spec('render'), item))
        process_runs.succeed(item, 'render', output_summary={'fingerprint': 'text-v1'})
        process_runs.start(item, 'summary',
                           settings_snapshot=pipeline.snapshot(pipeline.spec('summary'), item))
        process_runs.succeed(item, 'summary')
        self.assertEqual(set(), pipeline.refresh(item))
        process_runs.succeed(item, 'render', output_summary={'fingerprint': 'text-v2'})
        self.assertEqual({'summary'}, pipeline.refresh(item))

    def test_a_page_of_cards_reads_its_lines_in_one_query(self):
        """Measured on 2026-10-03: the strip cost six queries PER CARD (the lines were read again
        by `refresh`, `card_rows` and `shown_state`). A page preloads the lines of all its cards
        at once ; a card asked alone reads them once and leaves nothing on the instance."""
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from wama.common.services.process_pipeline import PRELOADED, card_view, preload
        APP_PIPELINES['demo_pipeline'] = self.pipeline
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        cards = [_Element(status=JOB_SUCCESS) for _ in range(3)]
        for card in cards:
            self._played(card, 'plan')
            self._played(card, 'render')
        with CaptureQueriesContext(connection) as page:
            preload(cards)
            views = [card_view(card, preloaded=True) for card in cards]
        # Two queries for the whole page : the lines, and what the cards ADD to their pipeline
        # (`card_pipelines`, 2026-11-11) — never one per card.
        self.assertEqual(2, len(page), [q['sql'][:80] for q in page])
        self.assertTrue(all(view[1] == JOB_SUCCESS and len(view[0]) == 2 for view in views))
        alone = _Element(status=JOB_SUCCESS)
        self._played(alone, 'render')
        with CaptureQueriesContext(connection) as single:
            card_view(alone)
        self.assertEqual(2, len(single))
        self.assertFalse(hasattr(alone, PRELOADED), 'nothing read stays on a kept instance')

    def test_a_fresh_process_loads_the_declarations_before_saying_there_is_no_pipeline(self):
        """Lived on 2026-10-03, 500 on the live composer page: a web process that had imported
        no `function_specs` yet read an EMPTY registry as « this app has no pipeline ». An
        unknown app makes the registry load the declarations of the installed apps, once."""
        from wama.common.services import process_pipeline
        item = _Element(status=JOB_SUCCESS)
        APP_PIPELINES.pop('demo_pipeline', None)

        def register_now():
            APP_PIPELINES['demo_pipeline'] = self.pipeline

        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        with mock.patch.object(process_pipeline, '_declarations_loaded', False), \
                mock.patch('wama.common.catalog.function_catalog.load_all',
                           side_effect=register_now) as loaded:
            self.assertIs(process_pipeline.pipeline_of(item), self.pipeline)
            process_pipeline.pipeline_of(item)
        self.assertEqual(1, loaded.call_count, 'loaded once per process, not at every card')

    def test_the_common_decoration_sets_the_view_only_for_an_app_with_a_pipeline(self):
        """`decorate` is the single attachment point of the GENERATED apps (5.2) : nothing
        without a declared pipeline (the card reads `status`), the three attributes with one."""
        from wama.common.services.process_pipeline import card_view, decorate
        item = _Element(status=JOB_SUCCESS)
        APP_PIPELINES.pop('demo_pipeline', None)
        self.assertIsNone(card_view(item))
        self.assertIsNone(decorate(item))
        self.assertFalse(hasattr(item, 'shown_state'))
        APP_PIPELINES['demo_pipeline'] = self.pipeline
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        self._played(item, 'plan')
        self._played(item, 'render')
        rows, state, label = decorate(item)
        self.assertEqual((['plan', 'render'], JOB_SUCCESS), ([r['key'] for r in rows], state))
        self.assertEqual((item.processes, item.shown_state, item.shown_state_label),
                         (rows, state, label))
        self.assertTrue(label)

    def test_the_card_shows_the_notices_of_its_successful_lines_without_another_query(self):
        """2026-10-29: what a process SAID about its result (`output_summary['notices']`) becomes a
        warning badge — once even if two processes say it, never from a failed line, and read on
        the lines a page already loaded (no query per card)."""
        from wama.common.services.process_pipeline import decorate, preload
        APP_PIPELINES['demo_pipeline'] = self.pipeline
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        notice = {'key': 'ocr_loop_cut', 'label': 'Lecture coupée', 'icon': 'fa-scissors',
                  'title': 'cut'}
        item = _Element(status=JOB_SUCCESS)
        self._played(item, 'plan')
        self._played(item, 'render')
        for key in ('plan', 'render'):
            process_runs.succeed(item, key, output_summary={'notices': [notice]})
        preload([item])
        with self.assertNumQueries(0):
            decorate(item, preloaded=True)
        self.assertEqual([{'label': 'Lecture coupée', 'icon': 'fa-scissors', 'title': 'cut',
                           'variant': 'warning'}], item.notice_chips)
        process_runs.fail(item, 'render', 'boom')
        process_runs.succeed(item, 'plan', output_summary={'notices': []})
        decorate(item)
        self.assertEqual([], item.notice_chips, 'a failed line says nothing of its old result')

    def test_the_requested_model_is_declared_once_and_read_by_the_card(self):
        """Each app told the strip, the progress view and the ▶ of a process which model the
        card asks for (2026-10-04). It is declared ONCE (`model_of`) ; `card_view` reads it when
        no key is passed, an explicit key still wins, a declaration that raises says « unknown »."""
        from wama.common.services.process_pipeline import card_view, decorate_cards
        declared = AppPipeline('demo_pipeline', self.pipeline.specs, label='Demo',
                               model_of=lambda item: item.model)
        APP_PIPELINES['demo_pipeline'] = declared
        self.addCleanup(APP_PIPELINES.pop, 'demo_pipeline', None)
        scored = _Element(status=JOB_SUCCESS, model='writes-scores')
        plain = _Element(status=JOB_SUCCESS, model='plain')
        # Every step shows (2026-11-07) : the declared model decides which are ACTIVE.
        states = lambda view: [(r['key'], r['state']) for r in view[0]]  # noqa: E731
        self.assertEqual([('plan', 'active'), ('render', 'active')], states(card_view(scored)))
        # The step the model does not serve folds at the end (2026-11-08).
        self.assertEqual([('render', 'active'), ('plan', 'na')], states(card_view(plain)))
        self.assertEqual([('plan', 'active'), ('render', 'active')],
                         states(card_view(plain, 'writes-scores')))
        self.assertIsNone(declared.requested_model(_Element(status=JOB_SUCCESS)),
                          'no `model` on the element : unknown, never an error')
        seen = []
        cards = decorate_cards([scored, None, plain],
                               lambda item, preloaded: seen.append((item.pk, preloaded)))
        self.assertEqual([(scored.pk, True), (plain.pk, True)], seen)
        self.assertEqual([scored, plain], cards)
        self.assertEqual([('render', 'active'), ('plan', 'na')],
                         [(r['key'], r['state']) for r in decorate_cards([plain])[0].processes])

    def test_a_stale_render_is_shown_under_a_successful_element(self):
        item = _Element(status=JOB_SUCCESS)
        (Path(self.tmp) / 'score.abc').write_text('X:1', encoding='utf-8')
        self._played(item, 'plan', 'score.abc')
        self._played(item, 'render')
        self.assertEqual(JOB_SUCCESS, self.pipeline.shown_state(item))
        item.duration = 60
        self.assertEqual(JOB_STALE, self.pipeline.shown_state(item))
        rows = self.pipeline.card_rows(item)
        self.assertEqual([('plan', 'Partition', JOB_SUCCESS), ('render', 'Rendu', JOB_STALE)],
                         [(r['key'], r['label'], r['status']) for r in rows])
        self.assertEqual('plan.out', rows[0]['output_label'])
        self.assertEqual('family:m', rows[0]['model_key'])

    def test_the_rows_show_what_ran_and_what_the_named_model_will_run(self):
        item = _Element(status=JOB_PENDING)
        self.assertEqual([('render', 'active'), ('plan', 'na')],
                         [(r['key'], r['state']) for r in self.pipeline.card_rows(item, 'plays-only')])
        self.assertEqual([('plan', 'active'), ('render', 'active')],
                         [(r['key'], r['state'])
                          for r in self.pipeline.card_rows(item, 'writes-scores')])
        self.assertTrue(all(r['status'] == JOB_PENDING for r in
                            self.pipeline.card_rows(item, 'writes-scores')))

    def test_the_common_strip_renders_one_line_per_process_and_nothing_without_any(self):
        from django.template.loader import render_to_string
        html = render_to_string('common/_card_processes.html', {'processes': [
            {'key': 'plan', 'label': 'Partition', 'degree': 'required', 'status': JOB_SUCCESS,
             'duration_s': 159.1, 'model_key': 'family:m', 'output_label': 'a.abc', 'error': ''},
            {'key': 'render', 'label': 'Rendu', 'degree': 'required', 'status': JOB_STALE,
             'duration_s': 54.0, 'model_key': '', 'output_label': '', 'error': ''}]})
        self.assertIn('data-processes', html)
        self.assertIn('data-process="plan"', html)
        self.assertIn('data-s="STALE"', html)
        self.assertIn('159 s', html)
        self.assertIn('périmé', html)
        self.assertEqual('', render_to_string('common/_card_processes.html',
                                              {'processes': []}).strip())
        single = render_to_string('common/_card_processes.html', {'processes': [
            {'key': 'render', 'label': 'Rendu', 'degree': 'required', 'status': JOB_SUCCESS,
             'duration_s': 54.0, 'model_key': '', 'output_label': '', 'error': ''}]})
        self.assertEqual('', single.strip(), 'one process is not a pipeline to show')

    def test_the_live_update_says_a_lost_output_like_the_template(self):
        """The JS twin of the band (`WamaApp.updateProcessRows`, during a treatment) applies the
        template's rule: a lost output says « sortie perdue » before its duration (2026-10-27)."""
        import importlib.util
        if importlib.util.find_spec('py_mini_racer') is None:
            self.skipTest('py_mini_racer absent de ce venv')
        from django.conf import settings
        from py_mini_racer import MiniRacer
        from wama.common.tests.tests_cap_from_js import FAKE_DOM
        from wama.common.tests.tests_poller_js import HARNESS
        v8 = MiniRacer()
        v8.eval(FAKE_DOM + HARNESS)
        v8.eval((Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
                 / 'wama-app-base.js').read_text(encoding='utf-8'))
        shown = json.loads(v8.eval('''
            var notes = {plan: fakeNote(), render: fakeNote()};
            var card = {querySelector: function (s) {
              var key = /data-process="([^"]+)"/.exec(s);
              return key ? {querySelector: function (q) {
                return q === '.wcv3-proc-note' ? notes[key[1]] : {dataset: {}}; }} : null; }};
            window.WamaApp.updateProcessRows(card, [
              {key: 'plan', status: 'SUCCESS', duration_s: 12, lost: true},
              {key: 'render', status: 'SUCCESS', duration_s: 7.4, lost: false}]);
            JSON.stringify([notes.plan.textContent, notes.plan.classList.contains('text-warning'),
                            notes.render.textContent, notes.render.classList.contains('text-warning')]);
        '''))
        self.assertEqual(['sortie perdue', True, '7 s', False], shown)


class SkeletonRunsThePipelineTest(TestCase):
    """The retained processes run one after the other in ONE task, one line each."""

    def setUp(self):
        self.app, self.model = _adopters()[0]
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',), share=3),
        ), label='Demo')
        self.calls = []

    def _element(self, name):
        user = get_user_model().objects.create_user(name, password='x')
        item = _instance(self.model, user)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        return item

    def _run(self, item, **glues):
        from wama.common.utils.task_skeleton import run_item_task

        def default(key):
            def glue(element, ctx):
                self.calls.append((key, ctx.step))
                return {'models': [f'family:{key}'], 'label': f'{key}.out'}
            return glue
        processes = {spec.key: glues.get(spec.key) or default(spec.key)
                     for spec in self.pipeline.specs}
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes=processes,
                          model_key='family:announced')
        return self.model.objects.get(pk=item.pk)

    def _states(self, item):
        return {row.node_id: row.status for row in process_runs.lines(item)}

    def test_both_processes_run_in_order_and_each_has_its_line(self):
        item = self._run(self._element('pipeline_both'))
        self.assertEqual([('plan', 'plan'), ('render', 'render')], self.calls)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}, self._states(item))
        plan, render = (process_runs.line(item, key) for key in ('plan', 'render'))
        self.assertEqual((f'{self.app}.plan', 'function', 'family:plan'),
                         (plan.process_key, plan.process_kind, plan.model_key))
        self.assertEqual('family:render', render.model_key)
        self.assertEqual('plan.out', plan.output_summary.get('label'))
        self.assertIsNone(process_runs.line(item), 'a pipeline card has no « main » line')

    def test_a_notice_is_kept_on_its_line_and_an_empty_list_clears_it(self):
        """The line keeps its summary from one render to the next (`succeed` completes it) : a
        glue's `notices` is written as soon as it is returned, an empty list included."""
        notice = {'key': 'ocr_loop_cut', 'label': 'Lecture coupée'}
        item = self._element('pipeline_notices')

        def saying(*notices):
            return lambda element, ctx: {'label': 'plan.out', 'notices': list(notices)}

        self._run(item, plan=saying(notice))
        self.assertEqual([notice], process_runs.line(item, 'plan').output_summary['notices'])
        self.assertNotIn('notices', process_runs.line(item, 'render').output_summary,
                         'a glue that says nothing writes nothing')
        process_runs.mark_stale(item, ['plan'])
        self._run(item, plan=saying())
        self.assertEqual([], process_runs.line(item, 'plan').output_summary['notices'])

    def test_the_card_reports_every_model_its_processes_employed(self):
        with mock.patch('wama.common.utils.task_skeleton._signal') as signal:
            self._run(self._element('pipeline_models'))
        produced = [call for call in signal.call_args_list if call.args[2] == 'produit']
        self.assertEqual(['family:plan', 'family:render'], produced[0].args[3])

    def test_a_glue_sees_what_it_watched_at_its_last_render(self):
        """`ctx.snapshot` / `ctx.previous_snapshot` (2026-10-13) : read BEFORE the launch plan sets
        the lines back to pending — what lets the Writer's layout know that only its upstream
        changed, and adjust its result instead of redoing it."""
        seen = []

        def render(element, ctx):
            seen.append((ctx.snapshot, ctx.previous_snapshot))
            return {}
        item = self._run(self._element('pipeline_snapshots'), render=render)
        self.assertIsNone(seen[0][1], 'never rendered : no previous photo')
        self.assertIn('@upstream', seen[0][0], 'the photo carries its upstream fingerprint')
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        self._run(item, render=render)
        self.assertEqual(seen[0][0], seen[1][1], 'the photo of its last render, not the new one')

    def test_a_handed_over_launch_still_sees_the_photo_of_its_last_render(self):
        """The Writer's « Appliquer » on the live (2026-10-14) : the launch plans its lines on the
        default queue, then is handed over to the GPU queue under the SAME task id ; the second
        delivery read the lines after that plan, found no render, and the layout redid it all."""
        seen = []

        def render(element, ctx):
            seen.append(ctx.previous_snapshot)
            return {}
        item = self._run(self._element('pipeline_handed_over'), render=render)
        rendered = dict(process_runs.line(item, 'render').settings_snapshot)
        task_id = _task().request.id
        process_runs.plan(item, [('render', 'render', 'function')], task_id=task_id)
        process_runs.plan(item, [('render', 'render', 'function')], task_id=task_id)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        self._run(item, render=render)
        self.assertEqual(rendered, seen[-1], 'the second delivery lost the last render')
        # Not a render : a line another launch announced, or one planned over a failure.
        line = process_runs.line(item, 'render')
        self.assertTrue(process_runs.rendered_before(line, task_id))
        process_runs.plan(item, [('render', 'render', 'function')], task_id='another-task')
        self.assertFalse(process_runs.rendered_before(process_runs.line(item, 'render'), task_id))
        # A launch stopped before its turn, then launched again : the line was already PENDING,
        # nothing rendered since — the new launch still sees the last render.
        self.assertTrue(process_runs.rendered_before(process_runs.line(item, 'render'),
                                                     'another-task'))
        ProcessRun.objects.filter(pk=line.pk).update(status=JOB_FAILURE)
        process_runs.plan(item, [('render', 'render', 'function')], task_id=task_id)
        self.assertFalse(process_runs.rendered_before(process_runs.line(item, 'render'), task_id))

    def test_a_failure_closes_the_line_of_the_process_that_failed_only(self):
        def broken(element, ctx):
            raise RuntimeError('render is down')
        item = self._run(self._element('pipeline_fails'), render=broken)
        self.assertEqual('FAILURE', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertIn('render is down', process_runs.line(item, 'render').error_message)

    def test_an_optional_process_that_fails_does_not_fail_the_card(self):
        """Rule 4.4: only a REQUIRED process in failure fails the card. An optional one says it
        on its own line, the card ends in success for the element and « to be completed » for
        the deduced state — what the transcriber used to swallow (summary failed, nothing shown)."""
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'),
            ProcessSpec('extra', depends_on=('plan',), degree='optional'),
            ProcessSpec('render', depends_on=('plan',)),
        ), label='Demo')

        def broken(element, ctx):
            raise RuntimeError('the summary model is down')
        item = self._run(self._element('pipeline_optional_mid'), extra=broken)
        self.assertEqual([('plan', 'plan'), ('render', 'render')], self.calls,
                         'the processes after the failed option still run')
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'extra': JOB_FAILURE, 'render': JOB_SUCCESS},
                         self._states(item))
        self.assertIn('summary model is down', process_runs.line(item, 'extra').error_message)
        self.assertEqual(JOB_PENDING, self.pipeline.card_state(item), 'the card is to be completed')
        # ▶ again replays ONLY what is missing.
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        item = self._run(item)
        self.assertEqual([('extra', 'extra')], self.calls)
        self.assertEqual(JOB_SUCCESS, self.pipeline.card_state(item))

    def test_an_optional_process_that_waits_redelivers_the_task_instead_of_failing(self):
        """2026-10-18 : a glue that installs its model (`ctx.ensure_model`) WAITS — even in an
        optional process, that is not a failure : the task is redelivered, the card keeps going."""
        from wama.common.utils.task_skeleton import ServiceNotReady
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'),
            ProcessSpec('extra', depends_on=('plan',), degree='optional'),
        ), label='Demo')

        def waiting(element, ctx):
            raise ServiceNotReady('Installation de « X » en cours', countdown=30, max_attempts=720)
        task = _task()
        task.retry = staticmethod(lambda **kw: RuntimeError(f"re-delivered {kw['countdown']}"))
        item = self._element('pipeline_optional_waits')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                self.assertRaisesMessage(RuntimeError, 're-delivered 30'):
            from wama.common.utils.task_skeleton import run_item_task
            run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline,
                          processes={'plan': lambda element, ctx: {}, 'extra': waiting})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('RUNNING', item.status)
        self.assertNotEqual(JOB_FAILURE, process_runs.line(item, 'extra').status)

    def test_a_glue_installs_its_model_through_the_context(self):
        """`ctx.ensure_model(key)` : the common brick with the card's user, console and redelivery
        — and the key back, to be written in line."""
        seen = []

        def render(element, ctx):
            seen.append(ctx.ensure_model('family:secondary'))
            return {}
        with mock.patch('wama.common.utils.model_readiness.ensure_installed') as ensure:
            item = self._run(self._element('pipeline_ensure_model'), render=render)
        self.assertEqual(['family:secondary'], seen)
        keys = [call.args[0] for call in ensure.call_args_list]
        self.assertEqual(['family:announced', 'family:secondary'], keys,
                         'the card model by the skeleton, then the glue its own')
        last = ensure.call_args_list[-1].kwargs
        self.assertEqual(item.user, last['user'])
        self.assertIs(False, last['redelivered'])
        self.assertTrue(callable(last['console']))

    def test_a_last_optional_process_that_fails_leaves_the_card_named_and_successful(self):
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',), degree='optional'),
        ), label='Demo')

        def broken(element, ctx):
            raise RuntimeError('render is down')
        with mock.patch('wama.common.utils.task_skeleton._notify') as notify:
            item = self._run(self._element('pipeline_optional_last'), render=broken)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertEqual(('plan.out', True), notify.call_args.args[2:4],
                         'the card keeps the name its last SUCCESSFUL process gave')

    def test_the_relaunch_after_a_failure_does_not_replay_what_succeeded(self):
        def broken(element, ctx):
            raise RuntimeError('render is down')
        item = self._run(self._element('pipeline_resumes'), render=broken)
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        item = self._run(item)
        self.assertEqual([('render', 'render')], self.calls)
        self.assertEqual('SUCCESS', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_SUCCESS}, self._states(item))

    def test_each_process_fills_its_own_share_of_the_bar(self):
        """`plan` weighs 1 and `render` 3: half of `plan` is an eighth of the card."""
        if not any(f.name == 'progress' for f in self.model._meta.get_fields()):
            self.skipTest(f'{self.app} has no progress column')
        seen = {}

        def half(key):
            def glue(element, ctx):
                ctx.progress(50)
                seen[key] = self.model.objects.get(pk=element.pk).progress
                return {}
            return glue
        self._run(self._element('pipeline_bar'), plan=half('plan'), render=half('render'))
        self.assertEqual({'plan': 12, 'render': 62}, seen)

    def test_each_process_learns_its_own_duration(self):
        """Point 4.5: the ETA is per PROCESS — the one of `plan` is recorded when `plan` returns,
        under its own key, not when the card ends."""
        def with_eta(key):
            def glue(element, ctx):
                return {'eta': (f'family:{key}', 2.0, 'audio_sec')}
            return glue
        with mock.patch('wama.model_manager.services.eta_estimator.record_run') as record:
            self._run(self._element('pipeline_eta'), plan=with_eta('plan'),
                      render=with_eta('render'))
        self.assertEqual(['family:plan', 'family:render'],
                         [call.args[0] for call in record.call_args_list])

    def test_the_time_limit_closes_the_line_of_the_process_it_interrupted(self):
        from wama.common.utils.task_skeleton import TaskTimeLimitExceeded

        def too_long(element, ctx):
            raise TaskTimeLimitExceeded(60)
        item = self._run(self._element('pipeline_limit'), render=too_long)
        self.assertEqual('FAILURE', item.status)
        self.assertEqual({'plan': JOB_SUCCESS, 'render': JOB_FAILURE}, self._states(item))
        self.assertIn('Durée maximale', process_runs.line(item, 'render').error_message)

    def test_the_wait_for_the_graphics_card_is_decided_at_the_gpu_process_on_its_line(self):
        """2026-10-14 (Fabien: the governor at the grain of the PROCESS): a process that does not
        use the card plays without waiting; the GPU process that follows waits, and its OWN line
        says so — no « main » line. Until then the wait was decided before the card, and a
        pipeline card wrote no line at all (« nobody knows which process starts first »)."""
        from wama.common.utils.task_skeleton import run_item_task
        self.pipeline = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',), gpu=True),
        ), label='Demo')

        class Deferred(Exception):
            pass
        task = _task()
        task.retry = staticmethod(lambda **kwargs: Deferred(kwargs))
        item = self._element('pipeline_waits')

        def glue(key):
            def inner(element, ctx):
                self.calls.append(key)
                return {}
            return inner
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'), \
                mock.patch('wama.common.services.resource_governor.effective_free_gb',
                           return_value=1.0), \
                mock.patch('wama.common.services.resource_governor.fits_alone',
                           return_value=True), \
                mock.patch('wama.common.services.resource_governor.release_granted',
                           return_value=None), \
                mock.patch('wama.common.services.resource_governor.holders_summary',
                           return_value=''):
            with self.assertRaises(Deferred):
                run_item_task(task, app_id=self.app, model=self.model, item_id=item.pk,
                              pipeline=self.pipeline, vram_needed=8.0,
                              processes={'plan': glue('plan'), 'render': glue('render')})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('AWAITING_RESOURCES', item.status)
        self.assertEqual(['plan'], self.calls, 'the process without GPU did not wait')
        self.assertEqual({'plan': JOB_SUCCESS, 'render': 'AWAITING_RESOURCES'}, self._states(item))
        self.assertIsNone(process_runs.line(item), 'still no « main » line')

    def test_the_skeleton_can_be_bounded_to_one_process(self):
        item = self._run(self._element('pipeline_bounded_first'))
        self.calls.clear()
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        from wama.common.utils.task_skeleton import run_item_task

        def glue(key):
            def inner(element, ctx):
                self.calls.append(key)
                return {}
            return inner
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, only='plan',
                          processes={'plan': glue('plan'), 'render': glue('render')})
        self.assertEqual(['plan'], self.calls)
        self.assertEqual('SUCCESS', self.model.objects.get(pk=item.pk).status)
        self.assertEqual(JOB_SUCCESS, process_runs.line(item, 'plan').status)

    def test_a_process_without_its_glue_fails_the_card_and_says_so(self):
        from wama.common.utils.task_skeleton import run_item_task
        item = self._element('pipeline_no_glue')
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.pipeline, processes={'render': lambda e, c: {}})
        item = self.model.objects.get(pk=item.pk)
        self.assertEqual('FAILURE', item.status)
        self.assertFalse(process_runs.lines(item).exists(), 'no process started, no line')


class InputsThePipelineBringsTest(SimpleTestCase):
    """EXTENDED inputs (2026-10-03): an upstream process can make one of the model's inputs out of
    another — the composer's `extract_score` turns the audio of a cover into the score YuE2
    follows. Derived from the declarations (port types of the `FunctionSpec`s, `available`), never
    rewritten by an app. A fictitious pipeline: extract (audio → score), plan (prompt → score),
    render (prompt + score)."""

    KEYS = ('demo_bridge.extract', 'demo_bridge.plan', 'demo_bridge.render', 'demo_bridge.output')

    def setUp(self):
        from wama.common.catalog.function_catalog import (FUNCTION_CATALOG, Binding, FunctionSpec,
                                                          PortSpec)

        def declare(key, inputs, outputs):
            FUNCTION_CATALOG[key] = FunctionSpec(
                key=key, name=key, description='', category='transform', binding=Binding.APP,
                app='demo_bridge', inputs=[PortSpec(k, t, optional=True) for k, t in inputs],
                outputs=[PortSpec(k, t) for k, t in outputs])
        declare(self.KEYS[0], [('work_audio', 'audio')], [('score', 'score')])
        declare(self.KEYS[1], [('prompt', 'prompt')], [('score', 'score')])
        declare(self.KEYS[2], [('prompt', 'prompt'), ('work_score', 'score')], [('audio', 'audio')])
        declare(self.KEYS[3], [('rendered', 'audio')], [('audio', 'audio')])
        self.addCleanup(lambda: [FUNCTION_CATALOG.pop(k, None) for k in self.KEYS])
        self.installed = True

    def _pipeline(self, extract_function='demo_bridge.extract', with_output=False):
        specs = [
            ProcessSpec('extract', function=extract_function, available=lambda: self.installed,
                        applies=lambda item, model: True),
            ProcessSpec('plan', function='demo_bridge.plan'),
            ProcessSpec('render', function='demo_bridge.render', depends_on=('extract', 'plan')),
        ]
        if with_output:
            specs.append(ProcessSpec('output', function='demo_bridge.output',
                                     depends_on=('render',)))
        return AppPipeline('demo_bridge', tuple(specs), label='Demo')

    def test_a_process_downstream_of_the_model_s_one_changes_nothing(self):
        """The composer's `output` process (format, quality) comes after the render: the model's
        process is no longer the last one, and the extended inputs must not move."""
        pipeline = self._pipeline(with_output=True)
        self.assertTrue({'work_audio', 'work_score'} <= pipeline.covering_inputs('work_audio'))
        self.assertEqual({'prompt', 'work_score', 'work_audio'},
                         pipeline.extended_inputs({'prompt', 'work_score'}))

    def test_a_model_that_follows_a_score_takes_the_audio_the_score_is_extracted_from(self):
        pipeline = self._pipeline()
        self.assertEqual({'work_audio', 'work_score'}, pipeline.covering_inputs('work_audio'))
        self.assertEqual({'prompt', 'work_score', 'work_audio'},
                         pipeline.extended_inputs({'prompt', 'work_score'}))

    def test_a_model_without_the_bridged_port_gains_nothing(self):
        self.assertEqual({'prompt'}, self._pipeline().extended_inputs({'prompt'}))

    def test_an_upstream_that_feeds_a_required_input_extends_no_model(self):
        """Every model of the render reads its prompt: an upstream that turns the cover audio into
        words of the prompt (the composer's lyrics of the input, 2026-11-04) says nothing about
        WHICH model takes the audio. Until 2026-11-07 it made every model accept it — the
        bidirectional filter was dead, « auto » drew for a cover a model that ignores the audio."""
        from wama.common.catalog.function_catalog import (FUNCTION_CATALOG, Binding, FunctionSpec,
                                                          PortSpec)
        keys = ('demo_bridge.lyrics', 'demo_bridge.sing')
        for key, inputs, outputs in (
                (keys[0], [PortSpec('work_audio', 'audio')], [PortSpec('lyrics', 'prompt')]),
                (keys[1], [PortSpec('prompt', 'prompt'),
                           PortSpec('work_score', 'score', optional=True)],
                 [PortSpec('audio', 'audio')])):
            FUNCTION_CATALOG[key] = FunctionSpec(
                key=key, name=key, description='', category='transform', binding=Binding.APP,
                app='demo_bridge', inputs=inputs, outputs=outputs)
        self.addCleanup(lambda: [FUNCTION_CATALOG.pop(k, None) for k in keys])
        pipeline = AppPipeline('demo_bridge', (
            ProcessSpec('lyrics', function=keys[0]),
            ProcessSpec('render', function=keys[1], depends_on=('lyrics',)),
        ), label='Demo')
        self.assertEqual({'work_audio'}, pipeline.covering_inputs('work_audio'))
        self.assertEqual({'prompt'}, pipeline.extended_inputs({'prompt'}))

    def test_an_unavailable_upstream_extends_nothing_and_does_not_take_place(self):
        self.installed = False
        pipeline = self._pipeline()
        self.assertEqual({'work_audio'}, pipeline.covering_inputs('work_audio'))
        self.assertNotIn('work_audio', pipeline.extended_inputs({'prompt', 'work_score'}))
        self.assertEqual(['plan', 'render'], _keys(pipeline.applicable(_Element(), 'any')))

    def test_an_availability_that_cannot_be_read_counts_as_no(self):
        def broken():
            raise RuntimeError('catalogue down')
        spec = ProcessSpec('extract', available=broken)
        self.assertFalse(AppPipeline.can_run(spec))

    def test_a_process_whose_function_is_not_declared_yields_the_port_alone(self):
        pipeline = self._pipeline(extract_function='demo_bridge.nowhere')
        self.assertEqual({'work_audio'}, pipeline.covering_inputs('work_audio'))

    def test_availability_never_reaches_the_manifest(self):
        declared = [node['process'] for node in self._pipeline().graph()['nodes']]
        self.assertTrue(all('available' not in p for p in declared), declared)


class ADuplicateStartsWithoutWhatItsProcessesWroteTest(TestCase):
    """`duplicate_instance` + `AppPipeline.produced_fields` (2026-10-21) : a copy SHARES what the
    user gave (the brick's contract) and starts without what the source's processes WROTE — the
    declared output of a process that takes place, or that one of its lines rendered. Every app's
    views copied these lists by hand, twice (card view, batch factory), and they had drifted
    (`parts_score`). A declared output is not always a result: the audio of an avatarizer job is
    `speak`'s output in « pipeline » mode, and the user's own audio in « standalone » mode."""

    def setUp(self):
        from django.contrib.auth import get_user_model
        from wama.common.catalog.function_catalog import load_all
        load_all()
        self.user = get_user_model().objects.create_user('duplicate_produced', password='x')

    def _filled(self, model, **fields):
        item = _instance(model, self.user)
        names = [f.name for f in model._meta.concrete_fields
                 if f.get_internal_type() in ('FileField', 'ImageField')]
        model.objects.filter(pk=item.pk).update(
            **{n: f'users/{self.user.pk}/{n}_{item.pk}.bin' for n in names}, **fields)
        item.refresh_from_db()
        return item, names

    def test_every_app_with_a_pipeline_drops_what_it_produced_and_shares_the_rest(self):
        from wama.common.utils.preview_registry import PreviewRegistry
        from wama.common.utils.queue_duplication import duplicate_instance
        produced_somewhere = []
        for app, pipeline in APP_PIPELINES.items():
            model = PreviewRegistry.get_model(app)
            if model is None:
                continue
            with self.subTest(app=app):
                item, names = self._filled(model)
                produced = pipeline.produced_fields(item)
                copy = duplicate_instance(item)
                self.assertEqual([], [n for n in produced if getattr(copy, n)],
                                 'the copy keeps a result of the source')
                self.assertEqual([], [n for n in names if n not in produced
                                      and getattr(copy, n).name != getattr(item, n).name],
                                 'the copy lost something the user gave')
                produced_somewhere += produced
        self.assertTrue(produced_somewhere, 'nothing produced anywhere: the guard measures nothing')

    def test_the_avatar_s_audio_goes_when_spoken_and_stays_when_given(self):
        from wama.avatarizer.models import AvatarJob
        from wama.common.utils.queue_duplication import duplicate_instance
        spoken, _ = self._filled(AvatarJob, mode='pipeline')
        given, _ = self._filled(AvatarJob, mode='standalone')
        self.assertFalse(duplicate_instance(spoken).audio_input, 'the TTS audio is a result')
        self.assertEqual(given.audio_input.name, duplicate_instance(given).audio_input.name,
                         "the user's own audio is an input: the copy keeps it")

    def test_an_old_result_goes_even_when_its_process_no_longer_takes_place(self):
        from wama.common.utils.queue_duplication import duplicate_instance
        from wama.transcriber.models import Transcript
        item, _ = self._filled(Transcript, level_speech=False, preprocess_audio=False)
        process_runs.succeed(item, 'level', output_ref=item.leveled_audio.name)
        self.assertIn('leveled_audio', APP_PIPELINES['transcriber'].produced_fields(item))
        self.assertFalse(duplicate_instance(item).leveled_audio)

    def test_no_duplicate_list_names_a_field_the_pipeline_derives(self):
        """One path: a view's `clear_fields` / `output_fields` names only what no process declares
        (a text, an error message) — never a declared output, which the brick derives. Held on the
        app's views AND on the views the GENERATOR renders from its manifest (the sandbox twins) :
        `views_gen.champs_sortie` derived its own list until 2026-10-22."""
        import ast
        from pathlib import Path
        from django.conf import settings
        from wama.common.manifests.codegen.views_gen import render_views
        from wama.common.manifests.ingest import extract
        from wama.common.sandbox import sandbox_labels
        twins = set(sandbox_labels())
        found, generated = [], 0
        for app, pipeline in APP_PIPELINES.items():
            if app in twins:
                continue
            declared = {f for spec in pipeline.specs for f in spec.outputs}
            views = Path(settings.BASE_DIR) / 'wama' / app / 'views.py'
            if not declared or not views.exists():
                continue
            rendered, _why = render_views(extract('app', app))
            generated += bool(rendered)
            for origin, source in (('app', views.read_text(encoding='utf-8')),
                                   ('généré', rendered or '')):
                for node in ast.walk(ast.parse(source)):
                    if isinstance(node, ast.keyword) and node.arg in ('clear_fields',
                                                                     'output_fields'):
                        try:
                            listed = set(ast.literal_eval(node.value))
                        except ValueError:
                            found.append(f'{app} ({origin}): {node.arg} non littéral '
                                         f'({ast.unparse(node.value)})')
                            continue
                        found += [f'{app} ({origin}): {node.arg} nomme {f}'
                                  for f in sorted(listed & declared)]
        self.assertTrue(generated, 'no generated views: the generator side measures nothing')
        self.assertEqual([], found)


class EveryAppPipelineTest(SimpleTestCase):
    """Generic guard over EVERY pipeline an app registers (`APP_PIPELINES`) — written once, it
    holds for the next app without a test per app. What the cam_analyzer guards for its own
    registry (`tests_pass_registry.PipelineManifesteTest`), held here for the common one."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG, load_all
        load_all()
        cls.catalogue = FUNCTION_CATALOG
        cls.pipelines = dict(APP_PIPELINES)

    def test_the_fleet_is_measured(self):
        self.assertIn('composer', self.pipelines)

    def test_a_card_with_a_switch_or_a_check_passes_its_settings_route_to_the_strip(self):
        """The checkbox of an optional process (`ProcessSpec.toggle`) and the « Relancer avec »
        of a short check (`checks`) are only drawn with `settings_url` (`_card_processes.html`).
        2026-10-26 : the composer card did not pass it — its « Partition de sortie » could only
        be switched on in the settings. Every app whose pipeline declares one passes it, from
        every template of its own that includes the strip. A sandbox TWIN carries what the
        generator emitted when it was generated : the generator is held by
        `tests_codegen_templates.EmissionsDuGabaritTest`, the twins follow at their next
        regeneration (the rule of `tests_process_watched`)."""
        import re
        from django.conf import settings
        from wama.common.sandbox import sandbox_labels
        root = Path(settings.BASE_DIR) / 'wama'
        twins = set(sandbox_labels())
        missing, measured = [], 0
        for app, pipeline in sorted(self.pipelines.items()):
            if app in twins or not any(spec.toggle or spec.checks for spec in pipeline.specs):
                continue
            templates = root / app / 'templates'
            for path in (templates.rglob('*.html') if templates.exists() else ()):
                for line in path.read_text(encoding='utf-8').splitlines():
                    if re.search(r"\{%\s*include\s+'common/_card_processes\.html'", line):
                        measured += 1
                        if 'settings_url=' not in line:
                            missing.append(f'{path.relative_to(root)}')
        self.assertGreaterEqual(measured, 4, 'the guard reads no card')
        self.assertEqual([], missing)

    def test_each_process_is_a_function_of_the_catalogue_bound_to_its_app(self):
        from wama.common.catalog.function_catalog import Binding
        for app, pipeline in self.pipelines.items():
            for spec in pipeline.specs:
                with self.subTest(app=app, process=spec.key):
                    function = self.catalogue.get(pipeline.function_key(spec))
                    self.assertIsNotNone(function, 'a process without a FunctionSpec is no node')
                    self.assertEqual((Binding.APP, app), (function.binding, function.app))

    def test_the_manifest_is_valid_and_carries_the_world_the_app_states(self):
        from wama.common.app_registry import app_world
        from wama.common.manifests.ingest import extract, validate
        for app, pipeline in self.pipelines.items():
            with self.subTest(app=app):
                manifest = extract('pipeline', app)
                self.assertIsNotNone(manifest, 'the registry is not a pipeline source')
                self.assertEqual([], list(validate(manifest) or []))
                self.assertEqual(app_world(app), manifest['world'])
                self.assertEqual([spec.key for spec in pipeline.specs],
                                 [node['id'] for node in manifest['body']['nodes']])

    def test_the_exported_manifest_is_the_one_of_the_corpus(self):
        """The versioned file must be what the registry gives TODAY, and the export command must
        see the pipeline — or the corpus loses it silently (`--check` would say « up to date »)."""
        import json
        from django.conf import settings
        from wama.common.management.commands.manifest_export import _pipeline_keys
        from wama.common.manifests.ingest import extract
        from wama.common.sandbox import sandbox_labels
        twins = set(sandbox_labels())
        for app in self.pipelines:
            if app in twins:
                # A sandbox twin is never versioned (`non_sandbox_apps`): the corpus holds real
                # apps. Its pipeline must stay OUT of the export instead.
                self.assertNotIn(app, _pipeline_keys())
                continue
            with self.subTest(app=app):
                self.assertIn(app, _pipeline_keys())
                written = Path(settings.BASE_DIR) / 'manifests' / 'pipelines' / f'{app}.json'
                self.assertTrue(written.exists(), 'the pipeline is not in the corpus')
                corpus = json.loads(written.read_text(encoding='utf-8'))
                live = extract('pipeline', app)
                self.assertEqual(corpus['body'], live['body'])

    def test_opened_in_the_studio_and_saved_unchanged_it_gives_the_card_the_same_pipeline(self):
        """ROUTE §10.6 3.2bis : a card whose pipeline is opened in the studio (the canvas form of
        the manifest) and saved as it is receives the DECLARED pipeline itself — the same object,
        not an equal copy. That is what makes the extended pipeline unable to change a card nobody
        adjusted."""
        from wama.common.manifests.builtin.pipeline import body_to_graph
        from wama.common.manifests.ingest import extract
        for app, pipeline in self.pipelines.items():
            with self.subTest(app=app):
                self.assertIs(pipeline, pipeline.extended(pipeline.graph()))
                opened = body_to_graph(extract('pipeline', app)['body'])
                self.assertIs(pipeline, pipeline.extended(opened))

    def test_it_opens_in_the_studio_and_each_link_lands_on_a_port(self):
        """« One representation, two editors »: the canvas form, with each dependency resolved
        to the input port whose type matches what the upstream process gives."""
        from wama.common.manifests.builtin.pipeline import body_to_graph
        from wama.common.manifests.ingest import extract
        for app, pipeline in self.pipelines.items():
            with self.subTest(app=app):
                graph = body_to_graph(extract('pipeline', app)['body'])
                self.assertEqual([spec.key for spec in pipeline.specs],
                                 [node['id'] for node in graph['nodes']])
                for link in graph['links']:
                    self.assertTrue(link['to_port'], f"{link['from']} -> {link['to']} has no port")


# ── ROUTE §10.6 3.2bis, marches 2 et 3 (2026-11-11) — the card CARRIES its pipeline ─────────────

class _MemoryWorkStore:
    """A work store kept in memory — the contract of `function_process.register_work_store`, so
    the substrate is tested without any world. The file is TOUCHED : a line keeps its address,
    and a lost file is a lost output (`process_runs.output_lost`)."""

    extension = '.mem'

    def __init__(self):
        self.tables = {}

    def write(self, path, name, frame):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).touch()
        self.tables.setdefault(os.path.normpath(str(path)), {})[name] = frame
        return {'table': name, 'fingerprint': f"{name}:{frame.df.to_csv(index=False)}"}

    def read(self, path, table):
        return self.tables[os.path.normpath(str(path))][table]


def _card_functions():
    """Two PURE functions of the catalogue (table → table) and one bound to an app — registered
    for the test, removed by the caller."""
    import pandas as pd
    from wama.common.catalog.data_types import TypedFrame
    from wama.common.catalog.function_catalog import (FUNCTION_CATALOG, Binding, FunctionSpec,
                                                      ParamSpec, PortSpec)

    def scaled(frame, factor=2.0):
        return TypedFrame(frame.df.assign(value=frame.df['value'] * factor), 'table')

    def total(frame):
        return TypedFrame(pd.DataFrame({'total': [float(frame.df['value'].sum())]}), 'table')

    specs = {
        'demo_card_glue.scaled': FunctionSpec(
            key='demo_card_glue.scaled', name='scaled', description='', category='transform',
            fn=scaled, inputs=[PortSpec('rows', 'table')], outputs=[PortSpec('rows', 'table')],
            params=[ParamSpec('factor', 'float', default=2.0)]),
        'demo_card_glue.total': FunctionSpec(
            key='demo_card_glue.total', name='total', description='', category='aggregate',
            fn=total, inputs=[PortSpec('rows', 'table')], outputs=[PortSpec('total', 'table')]),
        'demo_card_glue.job': FunctionSpec(
            key='demo_card_glue.job', name='job', description='', category='transform',
            binding=Binding.APP, impl='nowhere:task', inputs=[PortSpec('rows', 'table')]),
    }
    FUNCTION_CATALOG.update(specs)
    return specs


class ACardCarriesItsPipelineTest(TestCase):
    """Marche 2 : what a card ADDS to its declared pipeline is kept on a common table addressed like
    `ProcessRun` (`PipelineExtension`, `card_pipelines`) — only the addition, recomposed with the
    declared pipeline of the MOMENT by `extended` ; `pipeline_of(item)` gives it ; it follows a
    duplication, goes with the card, and an orphan is swept."""

    def setUp(self):
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG
        self.app, self.model = _adopters()[0]
        self.declared = AppPipeline(self.app, (
            ProcessSpec('plan'), ProcessSpec('render', depends_on=('plan',)),
        ), label='Demo')
        from wama.common.services.process_pipeline import _load_declarations
        _load_declarations()      # restored as it is NOW : the fleet stays for the next tests
        patched = mock.patch.dict(APP_PIPELINES, {self.app: self.declared})
        patched.start()
        self.addCleanup(patched.stop)
        for key in _card_functions():
            self.addCleanup(FUNCTION_CATALOG.pop, key, None)
        self.user = get_user_model().objects.create_user('card_pipeline', password='x')

    def _graph(self, factor=3):
        graph = self.declared.graph()
        graph['nodes'].append({'id': 'scaled', 'app': 'function:demo_card_glue.scaled',
                               'params': {'factor': factor}})
        graph['links'].append({'from': 'render', 'to': 'scaled', 'to_port': None})
        return graph

    def _card(self):
        return _instance(self.model, self.user)

    def test_the_card_keeps_only_what_it_adds_and_pipeline_of_gives_it(self):
        from wama.common.models import PipelineExtension
        from wama.common.services import card_pipelines
        from wama.common.services.process_pipeline import pipeline_of
        item = self._card()
        self.assertIs(self.declared, pipeline_of(item), 'nothing added : the declared pipeline')
        card_pipelines.set_added(item, self._graph(), source={'type': 'studio', 'ref': '12'})
        row = PipelineExtension.objects.get(**card_pipelines.address(item))
        self.assertEqual((['scaled'], {'type': 'studio', 'ref': '12'}),
                         ([n['id'] for n in row.body['nodes']], row.source))
        self.assertEqual(['render'], [l['from'] for l in row.body['links']],
                         'a declared process is not copied, only the link that reaches the addition')
        fresh = self.model.objects.get(pk=item.pk)
        card_pipeline = pipeline_of(fresh)
        self.assertIs(self.declared, card_pipeline.base)
        self.assertEqual((['plan', 'render', 'scaled'], {'factor': 3}),
                         (_keys(card_pipeline.ordered()), card_pipeline.added_params['scaled']))
        self.assertIs(card_pipeline, pipeline_of(fresh), 'built once per instance')

    def test_saving_the_declared_pipeline_as_it_is_removes_the_addition(self):
        from wama.common.models import PipelineExtension
        from wama.common.services import card_pipelines
        item = self._card()
        card_pipelines.set_added(item, self._graph())
        self.assertIs(self.declared, card_pipelines.set_added(item, self.declared.graph()))
        self.assertFalse(PipelineExtension.objects.filter(**card_pipelines.address(item)).exists())

    def test_a_refused_addition_is_named_and_nothing_is_kept(self):
        from wama.common.models import PipelineExtension
        from wama.common.services import card_pipelines
        item = self._card()
        graph = self._graph()
        graph['links'].append({'from': 'scaled', 'to': 'plan', 'to_port': None})
        with self.assertRaisesMessage(ValueError, 'jamais avant ni entre'):
            card_pipelines.set_added(item, graph)
        self.assertFalse(PipelineExtension.objects.exists())

    def test_an_addition_that_no_longer_composes_fails_its_launch_by_name(self):
        """An app evolution can make an addition invalid (an added key now declared) : the card is
        read with its declared pipeline, and a launch fails SAYING it (`strict`)."""
        from wama.common.models import PipelineExtension
        from wama.common.services import card_pipelines
        item = self._card()
        PipelineExtension.objects.create(
            **card_pipelines.address(item),
            body={'nodes': [{'id': 'render', 'kind': 'function',
                             'function': 'demo_card_glue.scaled', 'params': {}}], 'links': []})
        self.assertIs(self.declared, card_pipelines.card_pipeline(item, self.declared))
        card_pipelines.release(item)
        with self.assertRaisesMessage(ValueError, 'ne se compose plus'):
            card_pipelines.card_pipeline(item, self.declared, strict=True)

    def test_the_addition_follows_a_duplicate_and_goes_with_the_card(self):
        from wama.common.models import PipelineExtension
        from wama.common.services import card_pipelines
        from wama.common.utils.queue_duplication import duplicate_instance, release_card_files
        item = self._card()
        card_pipelines.set_added(item, self._graph(factor=5))
        copy = duplicate_instance(item)
        self.assertEqual({'factor': 5}, card_pipelines.added(copy)['nodes'][0]['params'])
        release_card_files(item)
        self.assertFalse(PipelineExtension.objects.filter(**card_pipelines.address(item)).exists())
        self.assertTrue(PipelineExtension.objects.filter(**card_pipelines.address(copy)).exists())

    def test_an_orphan_addition_is_swept_with_the_orphan_lines(self):
        from datetime import timedelta
        from django.utils import timezone
        from wama.common.models import PipelineExtension
        from wama.common.services import card_pipelines
        item = self._card()
        card_pipelines.set_added(item, self._graph())
        address = card_pipelines.address(item)
        self.model.objects.filter(pk=item.pk).delete()
        PipelineExtension.objects.filter(**address).update(
            updated_at=timezone.now() - timedelta(seconds=process_runs.ORPHAN_GRACE_SECONDS + 60))
        self.assertGreaterEqual(process_runs.forget_orphans(dry_run=True)['orphans'], 1)
        self.assertTrue(PipelineExtension.objects.filter(**address).exists(), 'dry run')
        process_runs.forget_orphans()
        self.assertFalse(PipelineExtension.objects.filter(**address).exists())

    def test_a_page_reads_the_additions_of_all_its_cards_in_one_query(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        from wama.common.services import card_pipelines
        from wama.common.services.process_pipeline import pipeline_of, preload
        cards = [self._card() for _ in range(3)]
        card_pipelines.set_added(cards[1], self._graph())
        page = [self.model.objects.get(pk=c.pk) for c in cards]
        with CaptureQueriesContext(connection) as queries:
            preload(page)
            pipelines = [pipeline_of(c) for c in page]
        self.assertEqual(2, len(queries), [q['sql'][:80] for q in queries])
        self.assertEqual([False, True, False], [p is not self.declared for p in pipelines])


class AnAddedProcessRunsByTheCommonGlueTest(TestCase):
    """Marche 3 : a process the card adds is played by the task skeleton like the others, through
    the COMMON glue (`function_process`) — the function of the catalogue by the Studio's door
    (`run_pure_function`), its typed inputs read from what its upstreams STORED in the card's work
    file, its output stored there : the line keeps its ADDRESS (file, table) and the fingerprint of
    its CONTENT, never a value in WAMA's base. Which world stores is registered
    (`register_work_store`) : here a store in memory."""

    def setUp(self):
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG, FunctionSpec, PortSpec
        from wama.common.services import function_process
        self.app, self.model = _adopters()[0]
        self.load_spec = f'{self.app}.load'
        self._register_load('table')
        self.addCleanup(FUNCTION_CATALOG.pop, self.load_spec, None)
        for key in _card_functions():
            self.addCleanup(FUNCTION_CATALOG.pop, key, None)
        self.declared = AppPipeline(self.app, (ProcessSpec('load'),), label='Demo')
        from wama.common.services.process_pipeline import _load_declarations
        _load_declarations()      # restored as it is NOW : the fleet stays for the next tests
        patched = mock.patch.dict(APP_PIPELINES, {self.app: self.declared})
        patched.start()
        self.addCleanup(patched.stop)
        self.store = _MemoryWorkStore()
        stored = mock.patch.object(function_process, '_STORE', self.store)
        stored.start()
        self.addCleanup(stored.stop)
        self.user = get_user_model().objects.create_user('card_glue', password='x')
        self.load = self._stores_rows

    def _register_load(self, data_type):
        from wama.common.catalog.function_catalog import FUNCTION_CATALOG, FunctionSpec, PortSpec
        FUNCTION_CATALOG[self.load_spec] = FunctionSpec(
            key=self.load_spec, name='load', description='', category='transform',
            outputs=[PortSpec('rows', data_type)])

    def _stores_rows(self, element, ctx):
        """A DECLARED process that stores typed data in the work file — what a source process
        of the Data Analyzer will do ; the contract the added processes read."""
        import pandas as pd
        from django.conf import settings
        from wama.common.catalog.data_types import TypedFrame
        from wama.common.services import function_process
        rel = function_process.work_file(element, self.store.extension)
        self.addCleanup(Path(settings.MEDIA_ROOT, rel).unlink, missing_ok=True)
        done = self.store.write(Path(settings.MEDIA_ROOT, rel), 'load',
                                TypedFrame(pd.DataFrame({'value': [1.0, 2.0, 3.0]}), 'table'))
        return {'output_ref': rel, 'output_table': done['table'],
                'output_fingerprint': done['fingerprint'], 'label': 'load'}

    def _card(self, *added):
        """A card whose pipeline adds `added` : (id, canvas app, params, upstream)."""
        from wama.common.services import card_pipelines
        item = _instance(self.model, self.user)
        self.model.objects.filter(pk=item.pk).update(status='RUNNING')
        graph = self.declared.graph()
        for key, app, params, upstream in added:
            graph['nodes'].append({'id': key, 'app': app, 'params': params})
            graph['links'].append({'from': upstream, 'to': key, 'to_port': None})
        card_pipelines.set_added(item, graph)
        return item

    def _run(self, item):
        from wama.common.utils.task_skeleton import run_item_task
        with mock.patch('wama.common.utils.task_skeleton.close_old_connections'):
            run_item_task(_task(), app_id=self.app, model=self.model, item_id=item.pk,
                          pipeline=self.declared, processes={'load': self.load})
        return self.model.objects.get(pk=item.pk)

    def _stored(self, row, table):
        from django.conf import settings
        return self.store.read(Path(settings.MEDIA_ROOT, row.output_ref), table)

    def test_the_added_processes_run_after_the_declared_one_and_store_their_output(self):
        item = self._run(self._card(
            ('scaled', 'function:demo_card_glue.scaled', {'factor': 10}, 'load'),
            ('total', 'function:demo_card_glue.total', {}, 'scaled')))
        self.assertEqual('SUCCESS', item.status,
                         {r.node_id: r.error_message for r in process_runs.lines(item)})
        lines = {row.node_id: row for row in process_runs.lines(item)}
        self.assertEqual({'load', 'scaled', 'total'}, set(lines))
        scaled, total = lines['scaled'], lines['total']
        self.assertEqual(('function', 'demo_card_glue.scaled', JOB_SUCCESS, 'scaled'),
                         (scaled.process_kind, scaled.process_key, scaled.status,
                          scaled.output_summary.get('table')))
        self.assertEqual(scaled.output_ref, total.output_ref, 'ONE work file per card')
        self.assertIn(f'users/{self.user.pk}/temp/work/', scaled.output_ref)
        self.assertEqual([60.0], self._stored(total, 'total').df['total'].tolist(),
                         'its setting reached the function, its upstream fed the next one')
        self.assertTrue(scaled.output_summary.get('fingerprint'),
                        'the fingerprint of the CONTENT, not of the shared file')

    def test_a_port_no_upstream_feeds_is_refused_by_name(self):
        """The added process downstream of nothing typed (a media process) : its required port is
        not fed, and the card fails SAYING which port."""
        self._register_load('audio')
        self.load = lambda element, ctx: {'label': 'a media'}
        item = self._run(self._card(('scaled', 'function:demo_card_glue.scaled', {}, 'load')))
        self.assertEqual('FAILURE', item.status)
        self.assertIn('port « rows »', process_runs.line(item, 'scaled').error_message)

    def test_an_added_process_bound_to_an_app_has_no_glue_and_is_refused_by_name(self):
        item = self._run(self._card(('job', 'function:demo_card_glue.job', {}, 'load')))
        self.assertEqual('FAILURE', item.status)
        self.assertIn('process sans glu : job', getattr(item, 'error_message', ''))

    def test_without_a_world_that_stores_typed_data_the_process_is_refused_by_name(self):
        from wama.common.services import function_process
        item = self._card(('scaled', 'function:demo_card_glue.scaled', {}, 'load'))
        self.load = lambda element, ctx: {'label': 'load'}
        with mock.patch.object(function_process, '_STORE', None):
            item = self._run(item)
        self.assertEqual('FAILURE', item.status)
        self.assertIn('aucun monde ne range', process_runs.line(item, 'scaled').error_message)

    def test_a_module_plays_its_members_in_order_on_ONE_line(self):
        """A META-PROCESS (one `pipeline` node per module) : its members run in the order of its
        deployed graph, data in memory from one to the next, ONE line of kind `pipeline` whose
        table is the output of its terminal member."""
        from wama.common.services import card_pipelines
        sub = {'nodes': [{'id': 'scale', 'app': 'function:demo_card_glue.scaled',
                          'params': {'factor': 2}},
                         {'id': 'sum', 'app': 'function:demo_card_glue.total', 'params': {}}],
               'links': [{'from': 'scale', 'to': 'sum', 'to_port': None}]}
        with mock.patch.object(card_pipelines, 'resolver_for',
                               lambda item: (lambda key: ('Module', sub))):
            item = self._run(self._card(('module', 'pipeline:7', {'scale': {'factor': 5}},
                                         'load')))
        self.assertEqual('SUCCESS', item.status,
                         {r.node_id: r.error_message for r in process_runs.lines(item)})
        line = process_runs.line(item, 'module')
        self.assertEqual(('pipeline', 'pipeline:7', 'module/sum'),
                         (line.process_kind, line.process_key, line.output_summary.get('table')))
        self.assertEqual([30.0], self._stored(line, 'module/sum').df['total'].tolist(),
                         'the override reached its member : (1 + 2 + 3) × 5')
