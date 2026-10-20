"""The GENERATED files of an app agree with each other (2026-10-20, step 3 of the app porting).

The twins regenerated on 2026-10-20 came back to their witness for reasons the generator owned, not
the apps (`PROJECT_STATUS §PALIER 2026-10-20 soir`, gaps ①–④):
  ① the transcriber's tasks reach the common skeleton through a module function — read as « not a
    lifecycle task », nothing was generated and the generated views imported a missing module;
  ② a route alias served by a FACTORY view (`download_all = _pv[…]`) was renamed only when written
    as a `def`: the anonymizer's `download_all_media` route had no view;
  ③ `function_specs` refused an app with two lifecycle tasks (reader, enhancer) instead of reading
    the task its processes DECLARE (`impl`), and did not emit the result readers it declares in its
    own module (describer, reader);
  ④ the views dispatched the FIRST declared task, not the lifecycle one (synthesizer:
    `download_voice_refs_task`, absent from the generated `tasks.py`).
Each test renders from the LIVE manifest of the real apps, as `app_sandbox substitute` does.
"""
import ast
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.app_registry import APP_CATALOG


def _generated_apps() -> list:
    """The real apps a twin is generated from: a package with views and a task module."""
    base = Path(settings.BASE_DIR) / 'wama'
    return sorted(a for a, spec in APP_CATALOG.items()
                  if not spec.get('sandbox') and (base / a / 'views.py').is_file()
                  and any((base / a / f).is_file() for f in ('tasks.py', 'workers.py')))


def _defined(source: str) -> set:
    """Module-level names a generated file defines (functions, classes, assignments)."""
    names = set()
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names |= {n.id for t in node.targets for n in ast.walk(t) if isinstance(n, ast.Name)}
    return names


_MANIFESTS = {}


class _Rendered(SimpleTestCase):
    """The live manifests, extracted ONCE for the module (an extraction costs seconds)."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.manifests.ingest import extract
        if not _MANIFESTS:
            _MANIFESTS.update({a: extract('app', a) for a in _generated_apps()})
        cls.manifests = _MANIFESTS


class LifecycleThroughAModuleFunctionTest(SimpleTestCase):
    """①: a task that reaches `run_item_task` through a function of its module is a lifecycle task;
    an attribute call of the same name (`backend.transcribe(...)`) is not that function."""

    SOURCE = '''
from wama.common.utils.task_skeleton import run_item_task

def _run(task, pk):
    run_item_task(task, app_id='x', model=None, item_id=pk, glue=None)

@shared_task(bind=True)
def work(self, pk):
    _run(self, pk)

def _span(backend):
    return backend.work()

@shared_task(bind=True)
def listen(self, pk):
    return _span(None)
'''

    def test_the_skeleton_reached_through_a_helper_counts(self):
        from wama.common.manifests.codegen.tasks_gen import _functions_reaching_skeleton
        reaching = _functions_reaching_skeleton(ast.parse(self.SOURCE))
        self.assertIn('work', reaching)
        self.assertNotIn('listen', reaching, 'an attribute call is not the module function')

    def test_the_transcriber_tasks_are_read_as_they_run(self):
        from wama.common.manifests.codegen.tasks_gen import app_tasks
        lifecycle = {t['function']: t['lifecycle'] for t in app_tasks('transcriber')}
        self.assertTrue(lifecycle['transcribe'])
        self.assertTrue(lifecycle['transcribe_without_preprocessing'])
        self.assertFalse(lifecycle['live_write_task'])
        self.assertFalse(lifecycle['enrich_transcript'])


class ViewsDispatchAGeneratedTaskTest(_Rendered):
    """①④: the task the generated views import is one the generated `tasks.py` defines."""

    def test_every_app_imports_a_task_its_generated_tasks_define(self):
        from wama.common.manifests.codegen.tasks_gen import render_tasks
        from wama.common.manifests.codegen.views_gen import render_views
        wrong = {}
        for app, manifest in self.manifests.items():
            views, _ = render_views(manifest)
            tasks, _ = render_tasks(manifest)
            if views is None:
                continue
            imported = re.findall(r'^from \.tasks import (\w+)', views, re.M)
            defined = _defined(tasks) if tasks else set()
            missing = [t for t in imported if t not in defined]
            if missing or not tasks:
                wrong[app] = missing or 'no generated tasks.py'
        self.assertEqual({}, wrong)

    def test_the_synthesizer_dispatches_its_synthesis_not_its_download(self):
        from wama.common.manifests.codegen.views_gen import render_views
        views, _ = render_views(self.manifests['synthesizer'])
        self.assertIn('from .tasks import synthesize_voice', views)
        self.assertNotIn('download_voice_refs_task', views)


class RoutesHaveTheirViewsTest(_Rendered):
    """②: every view the generated `urls.py` routes to is defined by the generated views."""

    def test_no_generated_route_lacks_its_view(self):
        from wama.common.manifests.codegen.urls_gen import render_urls
        from wama.common.manifests.codegen.views_gen import render_views
        wrong = {}
        for app, manifest in self.manifests.items():
            urls, _ = render_urls(manifest)
            views, _ = render_views(manifest)
            if urls is None or views is None:
                continue
            missing = sorted(set(re.findall(r'views\.(\w+)', urls)) - _defined(views))
            if missing:
                wrong[app] = missing
        self.assertEqual({}, wrong)

    def test_an_alias_of_a_factory_view_is_its_own_name(self):
        from wama.common.manifests.codegen.views_gen import render_views
        views, _ = render_views(self.manifests['anonymizer'])
        self.assertRegex(views, r"(?m)^download_all_media = _pv\['download_all'\]")


class TheGeneratedCardReadsWhatTheViewsSetTest(_Rendered):
    """The generated card titles itself with `elem.input_filename` and names its output with
    `elem.output_filename`; on a real model both are @property glue the generated model loses
    (describer_01, 2026-10-20) — the generated views set them, as they set `gear_data`."""

    def test_every_app_sets_both_names_on_its_elements(self):
        from wama.common.manifests.codegen.views_gen import render_views
        missing = {}
        for app, manifest in self.manifests.items():
            views, _ = render_views(manifest)
            if views is None:
                continue
            names = [n for n in ('input_filename', 'output_filename')
                     if f"_set_unless_property(item, '{n}'" not in views]
            # The input name follows the COMMON rule of an element's readable name.
            if 'element_label(item)' not in views:
                names.append('element_label')
            if names:
                missing[app] = names
        self.assertEqual({}, missing)


class GeneratedModelsNeverImportThemselvesTest(_Rendered):
    """A callable field `default` of the app's own module was serialized as
    `wama.<app>.models.<fn>`: the generated models imported themselves (anonymizer_01, `check` KO,
    2026-10-20) and the function the migrations name existed nowhere."""

    def test_no_generated_models_imports_its_own_module(self):
        from wama.common.manifests.codegen.models_gen import render_models
        from wama.common.management.commands.app_sandbox import render_payload
        wrong = {}
        for app, manifest in self.manifests.items():
            source, _ = render_models(render_payload(manifest, 'models', False))
            if source and (f'wama.{app}.models' in source):
                wrong[app] = 'imports itself'
            elif source:
                compile(source, f'{app}/models.py', 'exec')
        self.assertEqual({}, wrong)

    def test_the_own_default_returns_what_the_source_returns(self):
        from wama.anonymizer.models import default_classes2blur
        from wama.common.manifests.codegen.models_gen import render_models
        from wama.common.management.commands.app_sandbox import render_payload
        source, _ = render_models(render_payload(self.manifests['anonymizer'], 'models', False))
        node = next(n for n in ast.parse(source).body
                    if isinstance(n, ast.FunctionDef) and n.name == 'default_classes2blur')
        space = {}
        exec(compile(ast.Module(body=[node], type_ignores=[]), 'models', 'exec'), space)
        self.assertEqual(default_classes2blur(), space['default_classes2blur']())
        self.assertIn('default=default_classes2blur', source)


class OwnDefaultRenderedAsLiteralTest(SimpleTestCase):
    """The re-emitted `default` writes what a LITERAL can write — the rule of `params_gen._literal`:
    an enum member returned by the source comes out as its value, never as an unknown name."""

    def test_an_enum_member_is_written_as_its_value(self):
        import sys
        import types
        from django.db import models
        from wama.common.manifests.codegen.models_gen import _own_default

        class Kind(models.TextChoices):
            AUTO = 'auto', 'Auto'

        module = types.ModuleType('wama_test_own_default')
        module.default_kinds = lambda: [Kind.AUTO]
        sys.modules['wama_test_own_default'] = module
        self.addCleanup(sys.modules.pop, 'wama_test_own_default', None)
        source = _own_default('wama_test_own_default', 'default_kinds', '[mark]')
        self.assertIn("return ['auto']", source)
        self.assertNotIn('TROU DE GLU', source)


class FunctionSpecsReadTheDeclaredTaskTest(_Rendered):
    """③: the pipeline is carried by the task its processes declare, and the result readers the
    pipeline declares in `function_specs` are generated as glue holes."""

    def test_each_app_with_a_pipeline_gets_its_function_specs(self):
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs
        refused = {}
        for app, manifest in self.manifests.items():
            pipeline, _ = declared_pipeline(app)
            if not pipeline or len(process_specs(pipeline)) < 2:
                continue
            source, reason = render_function_specs(manifest)
            if source is None:
                refused[app] = reason
        self.assertEqual({}, refused)

    def test_the_reader_pipeline_is_carried_by_its_declared_task(self):
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        source, _ = render_function_specs(self.manifests['reader'])
        self.assertIn("_IMPL = f'{_APP}.tasks:read_document_task'", source)

    def test_the_results_declared_in_the_module_are_defined_there(self):
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs
        from wama.common.manifests.codegen.tasks_gen import split_declared_path
        for app in ('describer', 'reader'):
            source, _ = render_function_specs(self.manifests[app])
            declared = {split_declared_path(s['result'])[1]
                        for s in process_specs(declared_pipeline(app)[0])
                        if split_declared_path(s['result'])[0] == f'{app}.function_specs'}
            self.assertTrue(declared, app)
            self.assertEqual(set(), declared - _defined(source), app)
            for name in declared:
                self.assertIn('TROU DE GLU', source.split(f'def {name}(')[1].split('def ')[0])
