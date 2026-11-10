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
And the three of 2026-11-10 (`reader_01` regenerated, `ROUTE §11 #47`):
  ⑤ the manifest extracted from an existing app had no `surfaces` facet — `surfaces.py` stayed
    COPIED, and the copy imported glue the generated files do not emit;
  ⑥ a hook a declaration NAMES in another generated module (`function_specs`) had no glue hole;
  ⑦ the introspected `models.py` lost the name of the spine (`__str__`, `filename`) the skeleton
    renders, and the literal constants of the source module (`SCORE_TITLE_MAX`).
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


def _surface(manifest: dict, key: str) -> dict:
    return next(s for s in manifest['body']['surfaces'] if s['key'] == key)


class TheSurfacesOfAnExistingAppAreExtractedTest(_Rendered):
    """⑤: the surfaces of an existing app are EXTRACTED, their code hooks by dotted path — the
    app's own become glue holes of the generated `surfaces.py`, the common ones are imported."""

    def test_the_reader_surfaces_are_extracted_with_their_hooks_by_path(self):
        surfaces = self.manifests['reader']['body']['surfaces']
        self.assertEqual(['score', 'text'], [s['key'] for s in surfaces])
        self.assertEqual('wama.reader.surfaces._score_available',
                         _surface(self.manifests['reader'], 'score')['available'])
        self.assertEqual('wama.common.surfaces.validate_text',
                         _surface(self.manifests['reader'], 'text')['validate'])
        self.assertNotIn('model', surfaces[0], 'the item model is the one of `processing`')

    def test_the_reader_surfaces_render_with_their_holes_and_common_imports(self):
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        source, reason = render_surfaces(self.manifests['reader'])
        self.assertIsNone(reason)
        compile(source, 'reader/surfaces.py', 'exec')
        self.assertIn('from wama.common.surfaces import validate_text', source)
        for hole in ('_score_available', '_text_available'):
            self.assertIn('TROU DE GLU', source.split(f'def {hole}(item):')[1].split('register_surface')[0])
            self.assertIn(f'available={hole}', source)
        self.assertNotIn('holds_score', source, 'the glue of the source is never copied')

    def test_an_anonymous_hook_is_named_never_guessed(self):
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        review = _surface(self.manifests['anonymizer'], 'review')
        self.assertIn('context.classes', review['_unsupported'])
        self.assertEqual(['detections'], review['documents'], 'its data are extracted all the same')
        self.assertIn('fonction anonyme', render_surfaces(self.manifests['anonymizer'])[1])

    def test_the_other_data_of_a_surface_are_rendered_with_the_type_of_their_field(self):
        """Read on the `Surface` dataclass, never listed again: a tuple field comes out a tuple."""
        import copy
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        manifest = copy.deepcopy(self.manifests['reader'])
        _surface(manifest, 'score').update(texts=['rendered'], autosave=True,
                                           routes={'retime': 'retime_segments'})
        source, reason = render_surfaces(manifest)
        self.assertIsNone(reason)
        for expected in ("texts=('rendered',)", 'autosave=True', "routes={'retime': 'retime_segments'}"):
            self.assertIn(expected, source)

    def test_what_the_template_does_not_render_is_refused_with_its_reason(self):
        import copy
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        cases = {'available': ('wama.composer.surfaces._score_available', "hors de l'app et du commun"),
                 'value': ('wama.reader.surfaces._value', 'non généré(s) par ce gabarit')}
        for hook, (path, expected) in cases.items():
            with self.subTest(hook=hook):
                manifest = copy.deepcopy(self.manifests['reader'])
                _surface(manifest, 'score')[hook] = path
                self.assertIn(expected, render_surfaces(manifest)[1])

    def test_a_data_field_is_rendered_only_with_its_validation_path(self):
        import copy
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        manifest = copy.deepcopy(self.manifests['reader'])
        del _surface(manifest, 'text')['validate']
        self.assertIn("« result_text » n'est la sortie d'aucun process", render_surfaces(manifest)[1])


class AHookNamedInAnotherModuleGetsItsHoleThereTest(_Rendered):
    """⑥: a surface hook declared in the app's `function_specs` is imported RELATIVELY by the
    generated `surfaces.py` (a twin reads its own) and becomes a glue hole of `function_specs`."""

    def test_the_hook_is_imported_and_defined_where_it_is_named(self):
        import copy
        from wama.common.manifests.codegen.function_specs_gen import render_function_specs
        from wama.common.manifests.codegen.surfaces_gen import render_surfaces
        manifest = copy.deepcopy(self.manifests['reader'])
        _surface(manifest, 'score')['available'] = 'wama.reader.function_specs.can_edit_score'
        surfaces, _ = render_surfaces(manifest)
        self.assertIn('from .function_specs import can_edit_score', surfaces)
        specs, _ = render_function_specs(manifest)
        self.assertIn('can_edit_score', _defined(specs))
        self.assertIn('TROU DE GLU', specs.split('def can_edit_score(item):')[1].split('def ')[0])


class TheModelSpineIsNamedOnBothPathsTest(_Rendered):
    """⑦: the introspected `models.py` names its item like the skeleton does, and re-emits the
    literal constants of the source module."""

    def _item(self, app):
        from wama.common.manifests.codegen.models_gen import render_models
        from wama.common.management.commands.app_sandbox import render_payload
        manifest = self.manifests[app]
        source, _ = render_models(render_payload(manifest, 'models', False))
        name = manifest['body']['processing']['model_spec']['item']['name']
        item = next(n for n in ast.parse(source).body if isinstance(n, ast.ClassDef) and n.name == name)
        return source, {n.name for n in item.body if isinstance(n, ast.FunctionDef)}

    def test_the_item_has_its_name_and_a_filename_field_is_never_shadowed(self):
        _source, methods = self._item('reader')
        self.assertLessEqual({'__str__', 'filename'}, methods)
        _source, methods = self._item('describer')
        self.assertIn('__str__', methods)
        self.assertNotIn('filename', methods, 'the describer stores its file name in a field')

    def test_the_literal_constants_of_the_source_module_are_rendered(self):
        from wama.reader.models import SCORE_TITLE_MAX
        source, _ = self._item('reader')
        self.assertIn(f'SCORE_TITLE_MAX = {SCORE_TITLE_MAX!r}', source)

    def test_only_module_level_literal_constants_are_rendered(self):
        import importlib
        import sys
        import tempfile
        from wama.common.manifests.codegen.models_gen import _own_constants
        import shutil
        folder = tempfile.mkdtemp(prefix='wama-own-constants-')
        self.addCleanup(shutil.rmtree, folder, True)
        Path(folder, 'wama_test_constants.py').write_text(
            'from os import SEEK_END as IMPORTED\n'
            'LIMIT = 200\n'
            'FIELDS = ("a", "b")\n'
            'MARKER = object()\n'
            '_PRIVATE = 1\n'
            'lower = 2\n'
            'try:\n'
            '    GUARDED = 4\n'
            'except ImportError:\n'
            '    GUARDED = 5\n'
            'class Item:\n'
            '    INNER = 3\n', encoding='utf-8')
        sys.path.insert(0, folder)
        self.addCleanup(sys.path.remove, folder)
        self.addCleanup(sys.modules.pop, 'wama_test_constants', None)
        importlib.invalidate_caches()
        self.assertEqual("LIMIT = 200\nFIELDS = ('a', 'b')\nGUARDED = 4",
                         _own_constants('wama_test_constants'),
                         'a constant set in a head block counts once, with the value of the module')
