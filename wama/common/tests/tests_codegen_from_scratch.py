"""Creating an app FROM SCRATCH out of a hand-written manifest — the route « app de zéro »
(`WAMA_APP_GENERATION_ROUTE.md §10.5`, priority set by Fabien on 2026-09-30; test case: the
Writer, `manifests/app_drafts/writer.json`).

The generators were written against EXISTING apps (a twin copies its source, then swaps files
for generated ones). Creating from scratch has no source to lean on: whatever the manifest
declares must be projected, or the app is born broken.
"""
import ast
import copy
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

DRAFT = Path(settings.BASE_DIR) / 'manifests' / 'app_drafts' / 'writer.json'


def _class_fields(src: str, class_name: str) -> set:
    """Names assigned in the body of `class_name` in rendered source — the evaluated shape,
    not a substring (repository idiom, cf. `tests_process_states`)."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {t.id for stmt in node.body if isinstance(stmt, ast.Assign)
                    for t in stmt.targets if isinstance(t, ast.Name)}
    return set()


class ApplyingAGlueTest(SimpleTestCase):
    """`app_sandbox glue` — the « validate → apply » gesture the route lacked for an app's glue
    (it existed for models and backends). Held here: a hole is replaced, a written glue is never
    overwritten, and a result that does not compile is refused."""

    SOURCE = ('def _process_x(item, ctx):\n'
              '    """TROU DE GLU [manifest-gen app:demo] — process x."""\n'
              "    raise NotImplementedError('x')\n\n\n"
              'def other():\n    return 1\n')

    def test_the_hole_is_replaced_and_the_rest_kept(self):
        from wama.common.management.commands.app_sandbox import replace_glue_hole
        out = replace_glue_hole(self.SOURCE, '_process_x',
                                "def _process_x(item, ctx):\n    return {'fields': {}}\n")
        self.assertNotIn('TROU DE GLU', out)
        self.assertIn("return {'fields': {}}", out)
        self.assertIn('def other():', out)

    def test_a_written_glue_is_never_overwritten(self):
        from wama.common.management.commands.app_sandbox import replace_glue_hole
        written = replace_glue_hole(self.SOURCE, '_process_x', 'def _process_x(item, ctx):\n    return {}\n')
        with self.assertRaises(ValueError):
            replace_glue_hole(written, '_process_x', 'def _process_x(item, ctx):\n    return None\n')

    def test_a_glue_that_does_not_compile_is_refused(self):
        from wama.common.management.commands.app_sandbox import replace_glue_hole
        with self.assertRaises(ValueError):
            replace_glue_hole(self.SOURCE, '_process_x', 'def _process_x(item, ctx:\n    pass\n')


class ManifestBornAppJoinsTheCatalogTest(SimpleTestCase):
    """An app created from scratch has no source to clone: its catalog entry is computed at
    creation (Django loaded) and stored in the registry; the boot-time injection only reads it —
    `sandbox.py` stays pure."""

    def test_the_stored_entry_is_injected_marked_as_sandbox(self):
        from unittest import mock

        from wama.common import sandbox
        entry = {'label': 'writer_01', 'generated_from': '',
                 'from_manifest': 'manifests/app_drafts/writer.json',
                 'catalog': {'label': 'Writer', 'url_name': 'writer_01:index',
                             'input_types': ['prompt'], 'has_batch': True},
                 'created': '2026-09-30T20:00:00+00:00'}
        catalog = {'converter': {'label': 'Converter'}}
        with mock.patch.object(sandbox, 'load_registry', return_value=[entry]), \
                mock.patch.object(sandbox, 'sandbox_labels', return_value=['writer_01']):
            sandbox.inject_sandbox_catalog(catalog)
        born = catalog.get('writer_01')
        self.assertIsNotNone(born, 'the manifest-born app is missing from the catalog')
        self.assertTrue(born['sandbox'])
        self.assertIn('BAC À SABLE', born['label'])
        self.assertEqual('writer_01:index', born['url_name'])
        self.assertEqual('manifests/app_drafts/writer.json', born['from_manifest'])
        self.assertEqual(['converter', 'writer_01'], sorted(catalog))
        self.assertEqual(['converter'], sandbox.non_sandbox_apps(catalog),
                         'a sandbox app must stay out of the conformity grid')


class DeclaredResultFieldsAreGeneratedTest(SimpleTestCase):
    """A result field DECLARED by the manifest (`backend_result`, `detail_spec`, `preview`) is
    projected by the from-scratch skeleton — it is not a glue hole. Measured on 2026-09-30: the
    skeleton left them all to « TROU DE GLU » while `apps_gen` registered the preview on
    `output_file`, a field the generated model did not have."""

    def test_the_writer_draft_gets_its_declared_result_fields(self):
        from wama.common.manifests.codegen.models_gen import render_models
        manifest = json.loads(DRAFT.read_text(encoding='utf-8'))
        src, reason = render_models(manifest)
        self.assertIsNotNone(src, reason)
        fields = _class_fields(src, 'WriterDocument')
        self.assertIn('output_file', fields, 'the previewed output file is missing')
        # The « fond » is no longer a text column: since 2026-10-05 it is the FILE written by the
        # `write` process (`draft_file`, AnAppWithSeveralProcessesIsGeneratedTest).
        self.assertIn('draft_file', fields, 'the « fond » written by `write` is missing')
        self.assertEqual(1, src.count('reference_document = '),
                         'the input field must not come back as a result field')
        compile(src, 'models.py', 'exec')

    def test_the_status_column_fits_every_state_it_lists(self):
        """Measured on the first real creation from scratch (the Editor, now the Writer, 2026-09-30): the skeleton
        froze `max_length=16` while the common vocabulary has `AWAITING_RESOURCES` (18) —
        `makemigrations` refused the app (fields.E009). Reading the choices never showed it."""
        from wama.common.manifests.codegen.models_gen import render_models
        src, reason = render_models(json.loads(DRAFT.read_text(encoding='utf-8')))
        self.assertIsNotNone(src, reason)
        tree = ast.parse(src)
        states = next(ast.literal_eval(n.value) for n in ast.walk(tree)
                      if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'STATUS_CHOICES')
        call = next(n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Assign) and getattr(n.targets[0], 'id', '') == 'status'
                    and isinstance(n.value, ast.Call))
        max_length = next(ast.literal_eval(k.value) for k in call.keywords if k.arg == 'max_length')
        self.assertGreaterEqual(max_length, max(len(v) for v, _ in states))

    def test_both_generation_paths_give_a_real_app_its_declared_result_fields(self):
        """Regenerating an app and creating it from scratch must give the SAME app: for every
        real app, the skeleton (data removed) emits each declared result field that the real
        item model actually has."""
        from django.apps import apps as django_apps

        from wama.common.app_registry import APP_CATALOG
        from wama.common.manifests.codegen.models_gen import (declared_preview_field,
                                                               declared_result_fields,
                                                               render_models)
        from wama.common.manifests.ingest import extract
        from wama.common.sandbox import non_sandbox_apps
        measured = 0
        for app in non_sandbox_apps(APP_CATALOG):
            manifest = extract('app', app)
            body = (manifest or {}).get('body') or {}
            spec = ((body.get('processing') or {}).get('model_spec') or {}).get('item') or {}
            if not spec.get('name'):
                continue
            try:
                model = django_apps.get_model(app, spec['name'])
            except LookupError:
                continue
            real = {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}
            expected = {n for n, _k in declared_result_fields(
                body, spec.get('input_field') or '') if n in real}
            # The preview file is registered as is by `apps_gen`: it must exist too — whether it
            # is a result or an INPUT (the avatarizer's avatar, the imager's reference image).
            if declared_preview_field(body) in real:
                expected.add(declared_preview_field(body))
            if not expected:
                continue
            scratch = copy.deepcopy(manifest)
            scratch['body'].pop('data', None)
            src, reason = render_models(scratch)
            if src is None:          # a skeleton refusal is another test's business
                continue
            with self.subTest(app=app):
                measured += 1
                missing = expected - _class_fields(src, spec['name'])
                self.assertFalse(missing, f'{app}: declared result fields not generated {missing}')
        self.assertGreaterEqual(measured, 3, 'too few apps measured to say anything')


def _calls(src: str, name: str) -> list:
    """Calls to `name` in rendered source, as AST nodes (the evaluated shape, not a substring)."""
    return [n for n in ast.walk(ast.parse(src))
            if isinstance(n, ast.Call) and getattr(n.func, 'id', None) == name]


class AnAppWithSeveralProcessesIsGeneratedTest(SimpleTestCase):
    """An app with several processes is generated on the composer pattern (decision n°11, ROUTE
    §10.6, common position of 2026-10-05): each process a `FunctionSpec binding: app`, the
    registry declared by `register_app_pipeline`, one glue hole per process. The pipeline is found
    by the app KEY (`pipeline_decl`), never by a facet of the `app` manifest. Test case: the
    Writer — writing the content, then laying it out."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manifest = json.loads(DRAFT.read_text(encoding='utf-8'))

    def test_the_declared_pipeline_is_read_by_the_app_key(self):
        from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs
        pipeline, functions = declared_pipeline('writer')
        specs = process_specs(pipeline)
        self.assertEqual(['write', 'layout'], [s['key'] for s in specs])
        self.assertEqual(['write'], specs[1]['depends_on'], 'the dependency comes from the link')
        self.assertEqual(['draft_file'], specs[0]['outputs'])
        self.assertEqual({'writer.write', 'writer.layout'}, set(functions))

    def test_function_specs_declares_one_function_and_one_process_per_node(self):
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        src, reason = render_function_specs(self.manifest)
        self.assertIsNotNone(src, reason)
        self.assertEqual(['write', 'layout'],
                         [c.args[0].value for c in _calls(src, 'ProcessSpec')])
        self.assertEqual(2, len(_calls(src, 'FunctionSpec')))
        self.assertEqual(1, len(_calls(src, 'register_app_pipeline')))

    def test_every_setting_says_what_it_makes_stale_and_is_never_copied_into_watched(self):
        """The rule `tests_process_watched` holds for real apps (`Param.stales`, 2026-10-05),
        applied to an app BORN from a manifest — that guard skips sandbox twins, so the draft is
        held here: each element setting names the processes it makes stale (or `[]`), a stale
        names a declared process, and the generated `ProcessSpec.watched` keeps only the fields
        OFF the schema."""
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        from wama.common.manifests.codegen.pipeline_decl import (declared_pipeline,
                                                                 process_specs, schema_stales)
        from wama.common.utils.output_formats import OUTPUT_PARAM_NAMES
        keys = {s['key'] for s in process_specs(declared_pipeline('writer')[0])}
        settings_ = {p['name']: p for schema in self.manifest['body']['params']['schemas'].values()
                     for p in schema if 'item' in (p.get('contexts') or ())}
        for name, p in settings_.items():
            with self.subTest(setting=name):
                self.assertTrue(p.get('stales') is not None or name in OUTPUT_PARAM_NAMES,
                                'declare `stales` (or `[]` for a display setting)')
        self.assertLessEqual(set(schema_stales(self.manifest)), keys)
        src, reason = render_function_specs(self.manifest)
        self.assertIsNotNone(src, reason)
        for call in _calls(src, 'ProcessSpec'):
            watched = next((ast.literal_eval(k.value) for k in call.keywords if k.arg == 'watched'), ())
            self.assertEqual([], [w for w in watched if w in settings_], call.args[0].value)

    def test_an_app_without_a_declared_pipeline_gets_no_function_specs(self):
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        src, _reason = render_function_specs({**self.manifest, 'key': 'no_such_app'})
        self.assertIsNone(src)

    def test_the_task_plays_the_pipeline_with_one_hole_per_process(self):
        from wama.common.manifests.codegen.tasks_gen import render_tasks
        src, reason = render_tasks(self.manifest)
        self.assertIsNotNone(src, reason)
        tree = ast.parse(src)
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn('process', [a.arg for a in functions['write_document_task'].args.args],
                      'the ▶ of ONE process needs the bounded launch')
        for key in ('write', 'layout'):
            self.assertIn(f'_process_write_document_task_{key}', functions)
        run = _calls(src, 'run_item_task')[0]
        self.assertEqual({'pipeline', 'processes', 'only'} - {k.arg for k in run.keywords}, set())

    def test_the_model_gets_the_step_outputs_and_every_file_port(self):
        from wama.common.manifests.codegen.models_gen import render_models
        src, reason = render_models(self.manifest)
        self.assertIsNotNone(src, reason)
        fields = _class_fields(src, 'WriterDocument')
        self.assertIn('draft_file', fields, 'the output of `write` is a FILE of the card')
        self.assertIn('reference_layout', fields, 'the second reference port must be stored')

    def test_the_secondary_port_is_received_under_its_name(self):
        from wama.common.manifests.codegen.views_gen import _donnees
        manifest = copy.deepcopy(self.manifest)
        manifest['body']['data'] = {'models': [{'name': 'WriterDocument', 'fields': [
            {'name': n, 'class': 'django.db.models.FileField'}
            for n in ('reference_document', 'reference_layout', 'draft_file', 'output_file')]}]}
        self.assertEqual(['reference_layout'], _donnees(manifest)['secondary_ports'])

    def test_the_common_output_process_is_declared_by_its_brick(self):
        """The « Sortie » process of a real app (the composer) is the common one: declared by
        `output_spec`, never copied field by field into a `ProcessSpec`."""
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        from wama.common.services.output_process import OUTPUT_KEY
        composer = json.loads((Path(settings.BASE_DIR) / 'manifests' / 'apps' / 'composer.json')
                              .read_text(encoding='utf-8'))
        src, reason = render_function_specs(composer)
        self.assertIsNotNone(src, reason)
        self.assertEqual(1, len(_calls(src, 'output_spec')))
        self.assertNotIn(OUTPUT_KEY, [c.args[0].value for c in _calls(src, 'ProcessSpec')])
