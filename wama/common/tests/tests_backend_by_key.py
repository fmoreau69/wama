"""The common launch door of a chosen model (2026-10-07): key → backend → contract method, for
EVERY app — a model served out of process (Ollama, a provider) included, with no app glue.

Measured the day it was laid: routing of the whole catalogue before/after — only the two
GLM-OCR rows changed (now `GlmOcrBackend`); the Ollama chat models still resolve to nothing.
"""
from typing import Optional
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.common.backends import manager
from wama.common.backends.ocr_base import OCRBackend
from wama.model_manager.models import AIModel


class _FakeOCR(OCRBackend):
    ENGINE = 'fake-ocr-engine'
    loads = 0

    def __init__(self):
        type(self).loads += 1
        self.seen = None

    def load(self, model: Optional[str] = None) -> bool:
        return True

    @property
    def is_loaded(self) -> bool:
        return True

    def unload(self) -> None:
        pass

    def run(self, work_file, mode='auto', language='', progress_callback=None, on_partial=None):
        self.seen = {'work_file': work_file, 'mode': mode, 'language': language,
                     'progress_callback': progress_callback}
        return f'text of {work_file}'


class WorkMethodTest(SimpleTestCase):

    def test_the_method_is_read_on_the_task_contract(self):
        from wama.common.backends.speech_to_text_base import SpeechToTextBackend
        self.assertEqual('run', manager._work_method(_FakeOCR))
        self.assertEqual('transcribe', manager._work_method(SpeechToTextBackend))
        # Without a task contract: the common entry point.
        self.assertEqual('process', manager._work_method(manager.BaseModelBackend))

    def test_values_reach_the_method_by_their_name_and_the_rest_is_left_out(self):
        """The file by its PORT name (`work_file`), the settings by their schema name — the rule
        of the `add_to_<app>` tool (`generic_runner.port_arguments`), one level down."""
        backend = _FakeOCR()
        progress = object()
        text = manager.run_contract(backend, work_file='/doc.pdf', mode='printed',
                                    language='fr', progress_callback=progress,
                                    backend='reader:olmocr', output_format='txt')
        self.assertEqual('text of /doc.pdf', text)
        self.assertEqual({'work_file': '/doc.pdf', 'mode': 'printed', 'language': 'fr',
                          'progress_callback': progress}, backend.seen)

    def test_a_class_probe_is_not_the_work_method(self):
        """`ImageGenerationBackend` declares two abstract members: `generate` (the work) and
        `is_available` (a CLASS probe). Picking the first in alphabetical order happened to be
        right; the probe is now set aside by its nature."""
        from wama.common.backends.image_generation_base import ImageGenerationBackend
        self.assertEqual('generate', manager._work_method(ImageGenerationBackend))

    def test_an_ambiguous_contract_is_refused_not_guessed(self):
        from abc import abstractmethod
        with mock.patch.dict('wama.common.services.backend_inventory.TASK_CONTRACTS',
                             {'probe-task': ('ocr_base', '_TwoWorks', False)}):
            class _TwoWorks(manager.BaseModelBackend):
                @abstractmethod
                def first(self): ...

                @abstractmethod
                def second(self): ...
            with self.assertRaises(TypeError):
                manager._work_method(_TwoWorks)


class TheContractTakesItsPortTest(SimpleTestCase):
    """Read on the SIGNATURE, nothing declared beside it: does the work method take the file of a
    port under the port's name?"""

    def test_the_ocr_contract_takes_the_work_file_port(self):
        self.assertTrue(manager.work_method_accepts(OCRBackend, 'work_file'))

    def test_an_open_signature_does_not_count_as_taking_the_port(self):
        # `transcribe(audio_path, …, **kwargs)` would swallow `work_audio` without reading it.
        from wama.common.backends.speech_to_text_base import SpeechToTextBackend
        self.assertFalse(manager.work_method_accepts(SpeechToTextBackend, 'work_audio'))

    def test_every_ocr_engine_names_its_input_like_the_port_its_models_state(self):
        """The OCR models declare `inputs_required: ['work_file']` (catalogue discovery): each
        engine of the contract takes that name — a rename of one would break the generated body
        and the reader's launch without a word."""
        from wama.common.backends.doctr_backend import DocTRBackend
        from wama.common.backends.glm_ocr_backend import GlmOcrBackend
        from wama.common.backends.olmocr_backend import OlmOCRBackend
        for cls in (DocTRBackend, GlmOcrBackend, OlmOCRBackend):
            with self.subTest(engine=cls.__name__):
                self.assertTrue(manager.work_method_accepts(cls, 'work_file'))


class DoorByKeyTest(TestCase):

    def setUp(self):
        manager._INSTANCES_BY_CLASS = None
        _FakeOCR.loads = 0

    def _row(self, key, execution='local'):
        return AIModel.objects.create(model_key=key, name=key, model_type='ocr',
                                      source=key.split(':')[0], execution=execution,
                                      capabilities={'task': 'ocr'})

    def test_a_key_nothing_serves_stops_with_the_reason(self):
        with mock.patch.object(manager, 'backend_for_key', return_value=None):
            with self.assertRaisesRegex(manager.ModelNotServed, 'ghost:x'):
                manager.backend_instance_for_key('ghost:x')

    def test_the_instance_carries_its_key_and_stays_loaded(self):
        self._row('reader:fake')
        with mock.patch.object(manager, 'backend_for_key', return_value=_FakeOCR):
            first = manager.backend_instance_for_key('reader:fake')
            again = manager.backend_instance_for_key('reader:fake')
        self.assertIs(first, again, 'a heavy engine stays loaded from one item to the next')
        self.assertEqual(1, _FakeOCR.loads)
        self.assertEqual('reader:fake', first.catalogue_key)

    def test_two_models_of_one_engine_share_its_instance(self):
        """One instance per CLASS — the established use (the transcriber's engine instance, the
        reader's olmOCR singleton): an engine serving several models switches at `load(model)`;
        one instance per key would have loaded both side by side on the GPU."""
        self._row('transcriber:small')
        self._row('transcriber:large')
        with mock.patch.object(manager, 'backend_for_key', return_value=_FakeOCR):
            small = manager.backend_instance_for_key('transcriber:small')
            large = manager.backend_instance_for_key('transcriber:large')
        self.assertIs(small, large)
        self.assertEqual(1, _FakeOCR.loads)
        self.assertEqual('transcriber:large', large.catalogue_key)

    def test_an_instance_taken_without_a_key_never_keeps_the_previous_one(self):
        # The shared instance must not report the model of the call before it.
        self._row('reader:fake')
        with mock.patch.object(manager, 'backend_for_key', return_value=_FakeOCR):
            manager.backend_instance_for_key('reader:fake')
        self.assertEqual('', manager.backend_instance(_FakeOCR).catalogue_key)

    def test_a_provider_model_is_authorized_by_the_common_guard(self):
        self._row('albert:ocr-model', execution='cloud')
        with mock.patch.object(manager, 'backend_for_key', return_value=_FakeOCR), \
                mock.patch('wama.model_manager.services.cloud_models.cloud_access',
                           return_value='sk-user') as guard:
            instance = manager.backend_instance_for_key('albert:ocr-model', user='someone')
        guard.assert_called_once_with('someone', 'albert', 'ocr-model')
        self.assertEqual('sk-user', instance._api_key)

    def test_a_local_model_is_never_sent_to_the_guard(self):
        # Counter-check: no provider key is asked for a model that runs here.
        self._row('reader:fake')
        with mock.patch.object(manager, 'backend_for_key', return_value=_FakeOCR), \
                mock.patch('wama.model_manager.services.cloud_models.cloud_access') as guard:
            manager.backend_instance_for_key('reader:fake')
        guard.assert_not_called()


class OllamaServesSeveralTasksTest(TestCase):
    """Ollama hosts chat AND OCR under one engine. Declared multi-task in the sources registry,
    the OCR backend serves its task only — without the declaration it would be « the only backend
    of the engine » for every Ollama chat model."""

    def setUp(self):
        for key, task in (('ollama:glm-ocr:latest', 'ocr'),
                          ('ollama:chat-model:8b', 'text-generation')):
            AIModel.objects.create(model_key=key, name=key, model_type='llm', source='ollama',
                                   composition={'runtime': {'engine': 'ollama'}},
                                   capabilities={'task': task})

    def _resolved(self, key):
        cls = manager.backend_for_key(key)
        return getattr(cls, '__name__', None)

    def test_the_ocr_model_is_served_and_the_chat_model_is_not(self):
        self.assertEqual('GlmOcrBackend', self._resolved('ollama:glm-ocr:latest'))
        self.assertIsNone(self._resolved('ollama:chat-model:8b'))

    def test_without_the_declaration_the_chat_model_would_go_to_the_ocr_backend(self):
        # Counter-check: the declaration is what bounds the task backend.
        with mock.patch('wama.common.external_sources.serves_many_tasks', return_value=False):
            self.assertEqual('GlmOcrBackend', self._resolved('ollama:chat-model:8b'))
