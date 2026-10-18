"""The reader on route F4b step ⑤ (2026-10-07): its OCR select lists by TASK with catalogue
KEYS, and its task launches through the COMMON door (`backend_instance_for_key` + the OCR
contract) — the `if/elif` per engine is gone, so an OCR model served by Ollama or by a provider
needs no reader line."""
import importlib
from typing import Optional
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.backends.ocr_base import OCRBackend
from wama.reader.models import ReadingItem


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
        self.seen = {'mode': mode, 'language': language}
        if on_partial:
            on_partial('partial')
        return 'extracted text'


class _Ctx:
    def progress(self, *a, **k):
        pass

    def console(self, *a, **k):
        pass

    def ensure_model(self, key):
        return key


class LaunchThroughTheCommonDoorTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('reader_door', password='x')

    def _item(self, backend):
        return ReadingItem.objects.create(user=self.user, backend=backend, mode='printed',
                                          language='fr', input_file='reader/x/input/scan.png')

    def test_the_chosen_key_runs_with_the_item_settings_by_name(self):
        from wama.reader import tasks
        engine = _FakeOCR()
        with mock.patch('wama.common.backends.manager.backend_instance_for_key',
                        return_value=engine) as door, \
                mock.patch.object(tasks, '_format_as_markdown', side_effect=lambda t, l: t), \
                mock.patch('wama.common.utils.preview_utils.publish_partial_text'), \
                mock.patch('wama.common.utils.preview_utils.clear_partial'):
            result = tasks._read(self._item('ollama:glm-ocr:latest'), _Ctx())
        self.assertEqual('ollama:glm-ocr:latest', door.call_args.args[0])
        self.assertEqual({'mode': 'printed', 'language': 'fr'}, engine.seen)
        # The card shows the model that served (its key, resolved to a label by `card_chips`).
        self.assertEqual('ollama:glm-ocr:latest', result['fields']['used_backend'])
        # The ETA keeps learning under the identifier.
        self.assertEqual('reader:glm-ocr:latest', result['eta'][0])

    def test_auto_draws_in_the_declared_domain_by_task(self):
        from wama.reader import tasks
        seen = {}

        def fake(source, **kw):
            seen['source'], seen['task'] = source, kw.get('task')
            return 'reader:doctr'
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual('reader:doctr', tasks._select_best_backend(self._item('auto')))
        self.assertEqual((None, 'ocr'), (seen['source'], seen['task']))

    def test_a_catalogue_that_answers_nothing_falls_back_to_doctr(self):
        from wama.reader import tasks
        with mock.patch('wama.model_manager.services.select_model_id', return_value=None):
            self.assertEqual('reader:doctr', tasks._select_best_backend(self._item('auto')))


class BackendKeysMigrationTest(SimpleTestCase):
    """`0012_backend_catalog_keys`: pure rule — our prefix, the retired id under its source."""

    def _key(self):
        return importlib.import_module('wama.reader.migrations.0012_backend_catalog_keys')._key

    def test_each_value_of_before_gets_its_key(self):
        key = self._key()
        for given, expected in (('olmocr', 'reader:olmocr'), ('doctr', 'reader:doctr'),
                                ('glm-ocr', 'ollama:glm-ocr:latest'), ('auto', 'auto'),
                                ('', ''), ('fitz_direct', 'fitz_direct'),
                                ('reader:olmocr', 'reader:olmocr')):
            with self.subTest(given=given):
                self.assertEqual(expected, key(given))
