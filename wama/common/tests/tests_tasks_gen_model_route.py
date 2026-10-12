"""`tasks_gen`, flavour MODEL (2026-10-08): an app whose schema picks a catalogue model BY TASK
gets its task body COMPOSED on the common launch door — no launch glue left to write. The body is
rendered from the reader's live manifest, then RUN against a real card with a fake engine: a
generated body that merely compiles proves nothing."""
import types
from typing import Optional
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import TestCase

from wama.common.backends.ocr_base import OCRBackend
from wama.common.manifests.codegen.tasks_gen import model_route, render_tasks


def _seed_ocr_models():
    """The reader's OCR models as the catalogue declares them: their task, and the PORT they read
    (`inputs_required`). The card's ports DERIVE from them — an empty test catalogue gives the
    app only the generic fallback port `work`, which no contract takes (measured)."""
    from wama.model_manager.models import AIModel
    for key in ('reader:olmocr', 'reader:doctr', 'ollama:glm-ocr:latest'):
        AIModel.objects.create(model_key=key, name=key, model_type='ocr', source=key.split(':')[0],
                               vram_gb=1.0, is_available=True, is_downloaded=True,
                               is_proposed=False,
                               capabilities={'task': 'ocr', 'inputs_required': ['work_file']})


def _reader_manifest():
    """A COPY: the manifest holds the very objects of the app's schema (`PARAMS_JSON`), and the
    cases below mutate what they get — the first one poisoned the next ones before this copy
    (measured)."""
    import copy
    from wama.common.manifests.ingest import extract
    return copy.deepcopy(extract('app', 'reader'))


class _FakeOCR(OCRBackend):
    ENGINE = 'fake-ocr-engine'

    def load(self, model: Optional[str] = None) -> bool:
        return True

    @property
    def is_loaded(self) -> bool:
        return True

    def unload(self) -> None:
        pass

    def run(self, work_file, mode='auto', language='', progress_callback=None, on_partial=None):
        self.seen = {'work_file': work_file, 'mode': mode, 'language': language}
        if on_partial:
            on_partial('partial')
        return 'extracted text'


class _Ctx:
    def __init__(self):
        self.lines = []

    def progress(self, *a, **k):
        pass

    def console(self, line, *a, **k):
        self.lines.append(line)


def _load_generated(source: str):
    """The rendered file as a module of the reader's package (its relative imports resolve), the
    Celery decorator neutralised: the real task keeps its name in the registry."""
    module = types.ModuleType('wama.reader.generated_probe')
    module.__package__ = 'wama.reader'
    with mock.patch('celery.shared_task', lambda *a, **k: (lambda f: f)):
        exec(compile(source, '<generated tasks.py>', 'exec'), module.__dict__)
    return module


class TheRouteIsReadFromTheManifestTest(TestCase):
    """The extraction reads the database (model spec, catalogue): a `SimpleTestCase` gets a
    partial manifest — and the negative cases below would then pass VACUOUSLY. Hence `setUp`."""

    def setUp(self):
        _seed_ocr_models()
        self.assertIsNotNone(model_route(_reader_manifest()),
                             'the intact manifest must yield the route, or the cases prove nothing')

    def test_the_reader_states_everything_the_flavour_needs(self):
        route = model_route(_reader_manifest())
        self.assertEqual({'param': 'backend', 'task': 'ocr', 'domain': {'task': 'ocr'},
                          'port': 'work_file', 'input_field': 'input_file',
                          'result_field': 'result_text'},
                         {k: route[k] for k in ('param', 'task', 'domain', 'port', 'input_field',
                                                'result_field')})

    def test_a_work_port_the_contract_does_not_take_stays_a_hole(self):
        # The file reaches the contract under its PORT name: a port the OCR method does not name
        # would be swallowed or refused — no body rather than a body that loses its input.
        manifest = _reader_manifest()
        next(p for p in manifest['body']['ports']['inputs']
             if p.get('group') == 'travail')['id'] = 'work_audio'
        self.assertIsNone(model_route(manifest))

    def test_a_domain_over_several_tasks_is_not_one_body(self):
        manifest = _reader_manifest()
        schema = manifest['body']['params']['schemas'][manifest['body']['params']['primary']]
        select = next(p for p in schema if p.get('options_source') == 'catalog')
        select['options_query'] = {'task': 'upscale,denoise'}
        self.assertIsNone(model_route(manifest))

    def test_a_task_whose_contract_does_not_take_the_port_stays_a_hole(self):
        # `text-to-image` : `generate(params, …)` — no `work_file` in its signature.
        manifest = _reader_manifest()
        schema = manifest['body']['params']['schemas'][manifest['body']['params']['primary']]
        next(p for p in schema if p.get('options_source') == 'catalog')['options_query'] = {
            'task': 'text-to-image'}
        self.assertIsNone(model_route(manifest))

    def test_without_a_text_result_declared_there_is_no_body(self):
        manifest = _reader_manifest()
        manifest['body'].get('inspector', {}).get('detail_spec', {}).pop('result_text', None)
        manifest['body']['processing'].pop('backend_result', None)
        self.assertIsNone(model_route(manifest))


class TheComposedBodyRunsTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('gen_model_route', password='x')
        _seed_ocr_models()
        source, reason = render_tasks(_reader_manifest())
        self.assertIsNone(reason)
        self.source = source
        self.module = _load_generated(source)

    def _item(self, backend):
        from wama.reader.models import ReadingItem
        return ReadingItem.objects.create(user=self.user, backend=backend, mode='printed',
                                          language='fr', input_file='reader/x/input/scan.png')

    def test_the_lifecycle_task_is_composed_not_a_hole(self):
        body = self.source.split('def _process_read_document_task', 1)[1]
        self.assertIn('backend_instance_for_key', body)
        self.assertNotIn('NotImplementedError', body)

    def test_the_chosen_key_runs_through_the_door_with_the_card_settings(self):
        engine = _FakeOCR()
        item = self._item('ollama:glm-ocr:latest')
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        return_value=engine) as door, \
                mock.patch('wama.common.utils.preview_utils.publish_partial_text') as partial:
            result = self.module._process_read_document_task(item, _Ctx())
        self.assertEqual('ollama:glm-ocr:latest', door.call_args.args[0])
        self.assertEqual(self.user, door.call_args.kwargs['user'])
        self.assertTrue(engine.seen['work_file'].endswith('scan.png'))
        self.assertEqual(('printed', 'fr'), (engine.seen['mode'], engine.seen['language']))
        self.assertEqual({'fields': {'result_text': 'extracted text'},
                          'models': ['ollama:glm-ocr:latest']}, result)
        partial.assert_called_once_with('reader', item.pk, 'partial')

    def test_auto_draws_in_the_declared_domain(self):
        engine = _FakeOCR()
        seen = {}

        def fake(requested, **kw):
            seen.update(requested=requested, app_id=kw.get('app_id'), spec=kw.get('spec'))
            return 'reader:doctr'
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        return_value=engine) as door, \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice', fake), \
                mock.patch('wama.common.utils.preview_utils.publish_partial_text'):
            result = self.module._process_read_document_task(self._item('auto'), _Ctx())
        # The domain of the select the body uses, not the app's first select (`catalog_domain`).
        self.assertEqual({'requested': 'auto', 'app_id': 'reader', 'spec': {'task': 'ocr'}}, seen)
        self.assertEqual('reader:doctr', door.call_args.args[0])
        self.assertEqual(['reader:doctr'], result['models'])

    def test_a_catalogue_that_answers_nothing_stops_with_the_reason(self):
        with mock.patch('wama.common.utils.auto_model.resolve_model_choice', return_value=None):
            with self.assertRaisesRegex(ValueError, 'ocr'):
                self.module._process_read_document_task(self._item('auto'), _Ctx())


class TheNatureFlavourIsUntouchedTest(TestCase):
    """Counter-check: an app that routes by NATURE (`ROUTES`) keeps its B1 body."""

    def test_the_converter_body_still_routes_by_nature(self):
        from wama.common.manifests.ingest import extract
        source, _ = render_tasks(extract('app', 'converter'))
        self.assertIn('route_for_nature', source)
        self.assertNotIn('backend_instance_for_key', source)
