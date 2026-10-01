"""Creating an app FROM SCRATCH out of a hand-written manifest — the route « app de zéro »
(`WAMA_APP_GENERATION_ROUTE.md §10.5`, priority set by Fabien on 2026-09-30; test case: the
Editor, `manifests/app_drafts/editor.json`).

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

DRAFT = Path(settings.BASE_DIR) / 'manifests' / 'app_drafts' / 'editor.json'


def _class_fields(src: str, class_name: str) -> set:
    """Names assigned in the body of `class_name` in rendered source — the evaluated shape,
    not a substring (repository idiom, cf. `tests_process_states`)."""
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {t.id for stmt in node.body if isinstance(stmt, ast.Assign)
                    for t in stmt.targets if isinstance(t, ast.Name)}
    return set()


class DeclaredProcessesTest(SimpleTestCase):
    """The `pipelines` facet of an app manifest (§10.6 3.5, open decision n°11 formalised on the
    Editor, 2026-10-01): the processes an app proposes, each with what it reads, writes and
    watches. Measured on 2026-09-30: without DECLARED steps, the codegen role wrote the LLM's raw
    text into the `.html` — no model can guess an intention absent from its matter."""

    def _manifest(self):
        return json.loads(DRAFT.read_text(encoding='utf-8'))

    def test_the_editor_facet_is_valid_and_ordered(self):
        from wama.common.manifests.builtin.app import pipeline_process_order, validate_app_body
        manifest = self._manifest()
        self.assertEqual([], validate_app_body(manifest['body']))
        order, errors = pipeline_process_order(manifest['body']['pipelines'][0])
        self.assertEqual([], errors)
        self.assertEqual(['draft_content', 'render_format'], [n['id'] for n in order])

    def test_a_cycle_or_a_dangling_link_is_refused_at_ingest(self):
        from wama.common.manifests.builtin.app import validate_app_body
        manifest = self._manifest()
        pipeline = manifest['body']['pipelines'][0]
        for links, expected in (
                ([{'from': 'draft_content', 'to': 'render_format'},
                  {'from': 'render_format', 'to': 'draft_content'}], 'cycle'),
                ([{'from': 'draft_content', 'to': 'ghost'}], 'inconnu')):
            with self.subTest(expected=expected):
                pipeline['links'] = links
                errors = validate_app_body(manifest['body'])
                self.assertTrue(any(expected in e for e in errors), errors)

    def test_the_task_chains_the_declared_processes_and_leaves_one_hole_each(self):
        from wama.common.manifests.codegen.tasks_gen import render_tasks
        src, reason = render_tasks(self._manifest())
        self.assertIsNotNone(src, reason)
        tree = ast.parse(src)
        functions = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn('_process_draft_content', functions)
        self.assertIn('_process_render_format', functions)
        chain = ast.get_source_segment(src, functions['_process_generate_document_task'])
        self.assertIn('run_process_steps', chain)
        self.assertLess(chain.index('_process_draft_content'), chain.index('_process_render_format'),
                        'the declared order (links) is not the chained order')
        render_doc = ast.get_docstring(functions['_process_render_format'])
        self.assertIn('output_file', render_doc, 'the declaration (writes) is not in the hole')
        self.assertIn('HTML', render_doc, 'the declared intention is not in the hole')
        compile(src, 'tasks.py', 'exec')


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
        entry = {'label': 'editor_01', 'generated_from': '',
                 'from_manifest': 'manifests/app_drafts/editor.json',
                 'catalog': {'label': 'Editor', 'url_name': 'editor_01:index',
                             'input_types': ['prompt'], 'has_batch': True},
                 'created': '2026-09-30T20:00:00+00:00'}
        catalog = {'converter': {'label': 'Converter'}}
        with mock.patch.object(sandbox, 'load_registry', return_value=[entry]), \
                mock.patch.object(sandbox, 'sandbox_labels', return_value=['editor_01']):
            sandbox.inject_sandbox_catalog(catalog)
        born = catalog.get('editor_01')
        self.assertIsNotNone(born, 'the manifest-born app is missing from the catalog')
        self.assertTrue(born['sandbox'])
        self.assertIn('BAC À SABLE', born['label'])
        self.assertEqual('editor_01:index', born['url_name'])
        self.assertEqual('manifests/app_drafts/editor.json', born['from_manifest'])
        self.assertEqual(['converter', 'editor_01'], sorted(catalog))
        self.assertEqual(['converter'], sandbox.non_sandbox_apps(catalog),
                         'a sandbox app must stay out of the conformity grid')


class DeclaredResultFieldsAreGeneratedTest(SimpleTestCase):
    """A result field DECLARED by the manifest (`backend_result`, `detail_spec`, `preview`) is
    projected by the from-scratch skeleton — it is not a glue hole. Measured on 2026-09-30: the
    skeleton left them all to « TROU DE GLU » while `apps_gen` registered the preview on
    `output_file`, a field the generated model did not have."""

    def test_the_editor_draft_gets_its_declared_result_fields(self):
        from wama.common.manifests.codegen.models_gen import render_models
        manifest = json.loads(DRAFT.read_text(encoding='utf-8'))
        src, reason = render_models(manifest)
        self.assertIsNotNone(src, reason)
        fields = _class_fields(src, 'EditorDocument')
        self.assertIn('output_file', fields, 'the previewed output file is missing')
        self.assertIn('result_text', fields, 'the text result (the « fond ») is missing')
        self.assertEqual(1, src.count('source_document = '),
                         'the input field must not come back as a result field')
        compile(src, 'models.py', 'exec')

    def test_the_status_column_fits_every_state_it_declares(self):
        """Measured on the first real creation from scratch (Editor, 2026-09-30): the skeleton
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
