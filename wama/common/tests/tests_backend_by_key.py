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

    def run(self, file_path, mode='auto', language='', progress_cb=None, on_partial=None):
        self.seen = {'file_path': file_path, 'mode': mode, 'language': language}
        return f'text of {file_path}'


class WorkMethodTest(SimpleTestCase):

    def test_the_method_is_read_on_the_task_contract(self):
        from wama.common.backends.speech_to_text_base import SpeechToTextBackend
        self.assertEqual('run', manager._work_method(_FakeOCR))
        self.assertEqual('transcribe', manager._work_method(SpeechToTextBackend))
        # Without a task contract: the common entry point.
        self.assertEqual('process', manager._work_method(manager.BaseModelBackend))

    def test_values_reach_the_method_by_their_schema_name_and_the_rest_is_left_out(self):
        backend = _FakeOCR()
        text = manager.run_contract(backend, file_path='/doc.pdf', mode='printed',
                                    language='fr', backend='reader:olmocr', output_format='txt')
        self.assertEqual('text of /doc.pdf', text)
        self.assertEqual({'file_path': '/doc.pdf', 'mode': 'printed', 'language': 'fr'},
                         backend.seen)

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


class ValuesByRoleTest(SimpleTestCase):
    """What a GENERATED task body passes without knowing any contract: the input file, the
    progress callback, the model id — each under the name the contract declares."""

    def test_the_input_goes_under_the_name_the_contract_declares(self):
        backend = _FakeOCR()
        manager.run_contract(backend, input_path='/scan.png', mode='printed')
        self.assertEqual('/scan.png', backend.seen['file_path'])

    def test_speech_takes_its_input_as_audio(self):
        from wama.common.backends.speech_to_text_base import SpeechToTextBackend

        class _Speech(SpeechToTextBackend):
            def load(self, model_name=None):
                return True

            def unload(self):
                pass

            def transcribe(self, audio_path, language=None, hotwords=None, **kwargs):
                self.seen = dict(kwargs, audio_path=audio_path, language=language)
                return 'words'
        backend = _Speech()
        progress = object()
        manager.run_contract(backend, input_path='/talk.wav', progress=progress, language='fr')
        self.assertEqual('/talk.wav', backend.seen['audio_path'])
        # An open signature (`**kwargs`) gets the common callback name.
        self.assertIs(progress, backend.seen['progress_callback'])

    def test_progress_goes_under_the_name_the_method_carries(self):
        seen = {}

        class _Probe(_FakeOCR):
            def run(self, file_path, mode='auto', language='', progress_cb=None, on_partial=None):
                seen['progress_cb'] = progress_cb
                return ''
        progress = object()
        manager.run_contract(_Probe(), input_path='/a.pdf', progress=progress)
        self.assertIs(progress, seen['progress_cb'])

    def test_the_model_id_comes_from_the_key_when_the_method_asks_for_it(self):
        from wama.common.backends.score_extraction_base import ScoreExtractionBackend

        class _Score(ScoreExtractionBackend):
            ENGINE = 'fake-score-engine'

            def load(self, model_name=None):
                return True

            def unload(self):
                pass

            def extract_score(self, model_id, audio_path, output_dir=None, melody_only=True,
                              progress_callback=None):
                return f'{model_id}|{audio_path}'
        backend = _Score()
        backend.catalogue_key = 'composer:sheetsage2'
        self.assertEqual('sheetsage2|/song.wav',
                         manager.run_contract(backend, input_path='/song.wav'))

    def test_a_contract_without_a_declared_input_refuses(self):
        class _NoInput(manager.BaseModelBackend):
            def load(self, model=None):
                return True

            @property
            def is_loaded(self):
                return True

            def unload(self):
                pass

            def process(self, **kwargs):
                return kwargs
        with self.assertRaises(TypeError):
            manager.run_contract(_NoInput(), input_path='/x')


class DoorByKeyTest(TestCase):

    def setUp(self):
        manager._INSTANCES_BY_KEY = None
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
