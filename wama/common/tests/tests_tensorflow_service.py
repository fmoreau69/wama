"""The TensorFlow service (2026-11-09, WAMA_MANIFEST_SPEC §7.1) — boundary, contract, fallback, supervision.

TensorFlow never gives its card memory back before its process ends, and does not share the card
with PyTorch in one process: DeepFace and FER run in a service of their own, which stops when the
governor asks for the card and comes back on demand. No GPU here, except one real subprocess.
"""
import ast
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path
from unittest import mock

import numpy as np
from django.conf import settings
from django.test import SimpleTestCase, override_settings

from wama.common.backends import base
from wama.common.services import resource_governor as gov
from wama.common.tensorflow_service import engine, runtime, service_client
from wama.common.tests.tests_vram_governance import _WithRegistry

BASE = Path(settings.BASE_DIR)
SERVICES_SH = BASE / 'scripts' / 'wama_services.sh'
TASK = 'face-analysis'


def _fake_deepface(answer):
    """Fake `deepface` modules: `analyze` answers `answer`, `build_model` records its calls."""
    built = mock.Mock()
    package = types.ModuleType('deepface')
    package.DeepFace = types.SimpleNamespace(analyze=mock.Mock(return_value=[answer]))
    modules = types.ModuleType('deepface.modules')
    modeling = types.ModuleType('deepface.modules.modeling')
    modeling.build_model = mock.Mock(return_value=built)
    modeling.cached_models = {'facial_attribute': {'Emotion': built, 'Age': built}}
    package.modules = modules
    modules.modeling = modeling
    return mock.patch.dict(sys.modules, {'deepface': package, 'deepface.DeepFace': package.DeepFace,
                                         'deepface.modules': modules,
                                         'deepface.modules.modeling': modeling}), package


class ContractTest(SimpleTestCase):

    def test_the_task_has_its_binding_contract(self):
        from wama.common.services.backend_inventory import TASK_CONTRACTS
        self.assertEqual(('face_analysis_base', 'FaceAnalysisBackend', True), TASK_CONTRACTS[TASK])

    def test_each_weight_resolves_to_its_own_class_and_the_engine_is_never_guessed(self):
        from wama.common.backends.deepface_backend import (
            DeepFaceAgeBackend, DeepFaceBackend, DeepFaceGenderBackend)
        from wama.common.backends.manager import backend_for_engine
        self.assertIs(DeepFaceBackend, backend_for_engine('deepface', 'deepface-expression', task=TASK))
        self.assertIs(DeepFaceAgeBackend, backend_for_engine('deepface', 'deepface-age', task=TASK))
        self.assertIs(DeepFaceGenderBackend, backend_for_engine('deepface', 'deepface-gender', task=TASK))
        self.assertIsNone(backend_for_engine('deepface', 'deepface-race', task=TASK))

    def test_fer_is_found_by_its_engine_without_a_catalogue_line(self):
        from wama.common.backends.fer_backend import FERBackend
        from wama.common.backends.manager import backend_for_engine
        self.assertIs(FERBackend, backend_for_engine('fer', '', task=TASK))
        self.assertEqual(0, FERBackend.recommended_vram_gb)

    def test_every_tensorflow_backend_is_served_by_the_declared_service(self):
        from wama.common import external_sources
        from wama.common.backends.deepface_backend import DeepFaceAgeBackend
        from wama.common.backends.fer_backend import FERBackend
        from wama.common.backends.tensorflow_base import TENSORFLOW_SERVICE
        self.assertEqual(TENSORFLOW_SERVICE, DeepFaceAgeBackend.SERVED_BY)
        self.assertEqual(TENSORFLOW_SERVICE, FERBackend.SERVED_BY)
        declared = [s.key for s in external_sources.SOURCES if s.kind == 'service']
        self.assertIn(TENSORFLOW_SERVICE, declared)

    def test_a_backend_without_a_line_says_why_and_is_not_a_silent_orphan(self):
        from wama.common.services.backend_inventory import BackendEntry, orphelins
        said = BackendEntry(app='a', name='A', path='p', kind='classe', bundled_weights='in the wheel')
        forgotten = BackendEntry(app='a', name='B', path='p', kind='classe')
        silent, explained = orphelins([said, forgotten], [])
        self.assertEqual([forgotten], silent)
        self.assertEqual([said], explained)

    def test_fer_names_its_bundled_weights_to_the_static_inventory(self):
        from wama.common.services.backend_inventory import resolvable_entries
        entry = next(e for e in resolvable_entries() if e.name == 'FERBackend')
        self.assertTrue(entry.bundled_weights)


class StatelessBackendTest(SimpleTestCase):

    def _loaded(self, cls):
        instance = cls()
        instance._loaded = True
        return instance

    def test_two_images_answer_alike_there_is_no_memory_of_the_flow(self):
        from wama.common.backends.deepface_backend import DeepFaceBackend
        patcher, _ = _fake_deepface({'emotion': {'Happy': 75.0, 'neutral': 25.0}})
        with patcher:
            backend = self._loaded(DeepFaceBackend)
            first = backend.analyze_face(np.zeros((4, 4, 3), np.uint8))
            second = backend.analyze_face(np.zeros((4, 4, 3), np.uint8))
        self.assertEqual({'emotions': {'happy': 0.75, 'neutral': 0.25}}, first)
        self.assertEqual(first, second)

    def test_each_model_answers_only_for_its_attribute(self):
        from wama.common.backends.deepface_backend import DeepFaceAgeBackend, DeepFaceGenderBackend
        answer = {'age': 31.0, 'gender': {'Man': 90.0, 'Woman': 10.0}, 'dominant_gender': 'Man',
                  'emotion': {'happy': 1.0}}
        patcher, package = _fake_deepface(answer)
        with patcher:
            age = self._loaded(DeepFaceAgeBackend).analyze_face(np.zeros((4, 4, 3), np.uint8))
            gender = self._loaded(DeepFaceGenderBackend).analyze_face(np.zeros((4, 4, 3), np.uint8))
        self.assertEqual({'age': 31}, age)
        self.assertEqual({'gender': 'Man', 'gender_confidence': 0.9}, gender)
        self.assertEqual(['age'], package.DeepFace.analyze.call_args_list[0].kwargs['actions'])

    def test_absent_weights_are_said_never_pulled_by_the_library(self):
        from wama.common.backends.deepface_backend import DeepFaceBackend
        patcher, package = _fake_deepface({})
        with patcher, mock.patch.object(DeepFaceBackend, 'weights_file',
                                        return_value=BASE / 'no-such-weights.h5'):
            with self.assertRaisesMessage(RuntimeError, 'pull_model'):
                DeepFaceBackend().load()
        package.modules.modeling.build_model.assert_not_called()

    def test_the_declared_weights_file_is_where_the_library_reads_it(self):
        from wama.common.backends.deepface_backend import DeepFaceBackend
        self.assertEqual('facial_expression_model_weights.h5', DeepFaceBackend.weights_file().name)
        self.assertEqual('weights', DeepFaceBackend.weights_file().parent.name)


class TensorFlowBoundaryTest(SimpleTestCase):
    """Nothing imports a TensorFlow library outside its doors: that is what keeps it off the card."""

    ROOTS = {'tensorflow', 'tf_keras', 'keras', 'deepface', 'fer'}
    ALLOWED = {'wama/common/tensorflow_service/runtime.py', 'wama/common/backends/deepface_backend.py',
               'wama/common/backends/fer_backend.py'}

    def _offenders(self):
        found = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (BASE / root).rglob('*.py'):
                rel = path.relative_to(BASE).as_posix()
                if 'vendor/' in rel or '/tests' in rel or path.name.startswith('tests') or 'venv' in rel:
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding='utf-8'))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                for node in ast.walk(tree):
                    names = ([a.name for a in node.names] if isinstance(node, ast.Import)
                             else [node.module or ''] if isinstance(node, ast.ImportFrom) and not node.level
                             else [])
                    if any(n.split('.')[0] in self.ROOTS for n in names) and rel not in self.ALLOWED:
                        found.append(f'{rel}:{node.lineno}')
        return found

    def test_only_the_three_doors_import_a_tensorflow_library(self):
        self.assertEqual([], self._offenders())


class RuntimeTest(SimpleTestCase):

    def setUp(self):
        for name, value in (('_tensorflow', None), ('_on_the_card', False)):
            patcher = mock.patch.object(runtime, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _fake_tf(self, gpus=('GPU:0',)):
        fake = types.ModuleType('tensorflow')
        fake.config = mock.Mock()
        fake.config.list_physical_devices.return_value = list(gpus)
        return mock.patch.dict(sys.modules, {'tensorflow': fake}), fake

    def test_a_caller_keeps_tensorflow_off_the_card(self):
        patcher, fake = self._fake_tf()
        with patcher, mock.patch.object(runtime, 'preload_wheel_nvjitlink') as preload:
            self.assertIs(fake, runtime.tensorflow())
        fake.config.set_visible_devices.assert_called_once_with([], 'GPU')
        preload.assert_not_called()

    def test_the_service_preloads_the_library_of_the_wheel_and_keeps_the_card(self):
        patcher, fake = self._fake_tf()
        runtime.use_the_card()
        with patcher, mock.patch.object(runtime, 'preload_wheel_nvjitlink') as preload:
            runtime.tensorflow()
        preload.assert_called_once_with()
        fake.config.set_visible_devices.assert_not_called()
        self.assertTrue(runtime.on_the_card())

    def test_a_service_that_sees_no_card_says_it_runs_on_the_processor(self):
        patcher, _fake = self._fake_tf(gpus=())
        runtime.use_the_card()
        with patcher, mock.patch.object(runtime, 'preload_wheel_nvjitlink'):
            runtime.tensorflow()
        self.assertFalse(runtime.on_the_card())

    def test_the_card_cannot_be_claimed_once_tensorflow_is_imported(self):
        patcher, _fake = self._fake_tf()
        with patcher:
            runtime.tensorflow()
            with self.assertRaises(RuntimeError):
                runtime.use_the_card()

    def test_the_preload_finds_the_file_of_the_distribution(self):
        entry = mock.Mock()
        entry.name = 'libnvJitLink.so.12'
        entry.locate.return_value = '/wheel/libnvJitLink.so.12'
        other = mock.Mock()
        other.name = 'METADATA'
        with mock.patch('importlib.metadata.files', return_value=[other, entry]), \
                mock.patch.object(runtime.ctypes, 'CDLL') as cdll:
            self.assertTrue(runtime.preload_wheel_nvjitlink())
        cdll.assert_called_once_with('/wheel/libnvJitLink.so.12', mode=runtime.ctypes.RTLD_GLOBAL)


class _Backend(base.BaseModelBackend):
    """A TensorFlow-like backend, off the real library."""
    NO_TORCH_IN_PROCESS = True
    recommended_vram_gb = 2.0
    _current_model = 'm'

    @property
    def is_loaded(self):
        return True

    def load(self, model=None):
        return True

    def unload(self):
        return None

    def process(self, **kwargs):
        return None


class CardMeasureTest(_WithRegistry):

    def _load(self, before, after, *, backend=None):
        instance = backend or _Backend()
        self.addCleanup(base._untrack_live, instance)
        with mock.patch.object(gov, '_card_reading', side_effect=[(0.0, before), (0.0, after), (0.0, after)]), \
                mock.patch.object(base, '_vram_snapshot') as snapshot, \
                mock.patch.object(base, 'start_reservation_heartbeat'), \
                mock.patch.object(gov, 'record_measured_vram'):
            instance.load()
        snapshot.assert_not_called()               # no measure that would import PyTorch
        return gov.reservations()

    def test_the_load_is_measured_on_the_card_and_marked_outside_torch(self):
        published = self._load(10.0, 12.5)
        self.assertEqual([2.5], list(published.values()))
        owner = next(iter(published))
        self.assertEqual(str(gov._OUTSIDE_TORCH_PID), str(self.redis.hget(gov._ALLOC_KEY, owner)))

    def test_an_inconclusive_reading_falls_back_on_the_declaration(self):
        self.assertEqual([2.0], list(self._load(10.0, 10.0).values()))

    def test_a_model_that_fits_in_the_reserve_of_the_process_is_not_counted_twice(self):
        """Measured 2026-11-09: age then gender, the second added nothing to the card."""
        first = _Backend()
        setattr(first, base._GOV_GB, 2.5)
        base._track_live(first)
        self.addCleanup(base._untrack_live, first)
        self.assertEqual([0.1], list(self._load(12.5, 12.5).values()))

    def test_a_delta_measured_inside_a_shared_reserve_never_reaches_the_catalogue(self):
        first = _Backend()
        setattr(first, base._GOV_GB, 2.5)
        base._track_live(first)
        self.addCleanup(base._untrack_live, first)
        with mock.patch.object(gov, 'record_measured_vram') as recorded:
            second = _Backend()
            self.addCleanup(base._untrack_live, second)
            with mock.patch.object(gov, '_card_reading', side_effect=[(0.0, 10.0), (0.0, 15.0), (0.0, 15.0)]), \
                    mock.patch.object(base, 'start_reservation_heartbeat'):
                second.load()
        recorded.assert_not_called()

    def test_a_model_alone_on_the_card_reports_its_measure_to_the_catalogue(self):
        instance = _Backend()
        self.addCleanup(base._untrack_live, instance)
        with mock.patch.object(gov, 'record_measured_vram') as recorded, \
                mock.patch.object(gov, '_card_reading', side_effect=[(0.0, 10.0), (0.0, 12.5), (0.0, 12.5)]), \
                mock.patch.object(base, 'start_reservation_heartbeat'):
            instance.load()
        self.assertEqual(2.5, recorded.call_args.args[1])

    def test_the_line_of_a_service_without_torch_names_its_catalogue_key_without_importing_the_park(self):
        """`catalog_keys_for_owner` imports every backend, PyTorch included (the real release of
        2026-11-09 took 20 s and loaded the Diffusers backend into the service)."""
        class Declared(_Backend):
            SUPPORTED_MODELS = {'m': {'model_key': 'app:m'}}
        instance = Declared()
        self.addCleanup(base._untrack_live, instance)
        with mock.patch.object(gov, '_card_reading', side_effect=[(0.0, 10.0), (0.0, 12.0), (0.0, 12.0)]), \
                mock.patch.object(gov, 'record_measured_vram'), \
                mock.patch.object(base, 'start_reservation_heartbeat'):
            instance.load()
        (owner,) = gov.reservations()
        with mock.patch('wama.common.backends.manager.catalog_keys_for_owner') as catalog:
            self.assertEqual(['app:m'], gov.model_keys_of(owner))
        catalog.assert_not_called()

    def test_a_backend_off_the_card_publishes_nothing(self):
        instance = _Backend()
        instance.recommended_vram_gb = 0
        self.addCleanup(base._untrack_live, instance)
        with mock.patch.object(gov, '_card_reading') as reading, \
                mock.patch.object(base, '_vram_snapshot') as snapshot, \
                mock.patch.object(base, 'start_reservation_heartbeat'):
            instance.load()
        reading.assert_not_called()
        snapshot.assert_not_called()
        self.assertEqual({}, gov.reservations())


class ClientTest(SimpleTestCase):
    """The service answers, or the same engine runs here — and the service is asked for."""

    def setUp(self):
        folder = tempfile.mkdtemp(prefix='wama-tf-client-')
        self.addCleanup(shutil.rmtree, folder, True)
        os.mkdir(os.path.join(folder, 'logs'))
        self.flag = Path(folder) / 'logs' / 'service_wanted.tensorflow_service'
        settings_patcher = override_settings(BASE_DIR=Path(folder))
        settings_patcher.enable()
        self.addCleanup(settings_patcher.disable)
        patcher = mock.patch.object(service_client.local_engine, 'run', return_value={'emotions': 'local'})
        self.local = patcher.start()
        self.addCleanup(patcher.stop)

    def _call(self, **post):
        with mock.patch('requests.post', **post) as sent:
            result = service_client.run(TASK, engine='fer', models=[''], image=np.zeros((2, 2, 3), np.uint8))
        return result, sent

    def test_the_answer_of_the_service_is_used_and_nothing_runs_here(self):
        response = mock.Mock(status_code=200)
        response.json.return_value = {'result': {'emotions': 'service'}}
        result, sent = self._call(return_value=response)
        self.assertEqual({'emotions': 'service'}, result)
        self.local.assert_not_called()
        self.assertFalse(self.flag.exists())
        image = np.load(io.BytesIO(sent.call_args.kwargs['data']), allow_pickle=False)
        self.assertEqual((2, 2, 3), image.shape)        # lossless: the array itself
        self.assertEqual('fer', json.loads(sent.call_args.kwargs['params']['params'])['engine'])

    def test_a_stopped_service_runs_the_engine_here_and_is_asked_for(self):
        import requests
        result, _ = self._call(side_effect=requests.ConnectionError)
        self.assertEqual({'emotions': 'local'}, result)
        self.assertTrue(self.flag.exists())

    def test_a_service_starting_or_without_room_runs_the_engine_here_without_asking_for_it(self):
        result, _ = self._call(return_value=mock.Mock(status_code=503))
        self.assertEqual({'emotions': 'local'}, result)
        self.assertFalse(self.flag.exists())

    def test_an_error_of_the_analysis_is_an_error_not_an_absent_face(self):
        with self.assertRaises(service_client.TensorFlowServiceError):
            self._call(return_value=mock.Mock(status_code=500, text='boom'))
        self.local.assert_not_called()


class EngineTest(SimpleTestCase):

    def test_the_answers_of_the_models_are_merged_each_model_loaded_once_on_demand(self):
        age, gender = mock.Mock(), mock.Mock()
        age.process.return_value = {'age': 30}
        gender.process.return_value = {'gender': 'Man'}
        with mock.patch.object(engine, 'backend', side_effect=[age, gender]):
            merged = engine.run(TASK, 'deepface', ['deepface-age', 'deepface-gender'], 'img', {'detector': 'd'})
        self.assertEqual({'age': 30, 'gender': 'Man'}, merged)
        age.ensure_loaded.assert_called_once_with('deepface-age')
        age.process.assert_called_once_with(image='img', detector='d')

    def test_no_model_finding_anything_is_no_answer(self):
        backend = mock.Mock()
        backend.process.return_value = None
        with mock.patch.object(engine, 'backend', return_value=backend):
            self.assertIsNone(engine.run(TASK, 'fer', [''], 'img'))
        backend.ensure_loaded.assert_called_once_with(None)

    def test_an_unserved_model_stops_with_a_reason(self):
        from wama.common.backends.manager import ModelNotServed
        with self.assertRaises(ModelNotServed):
            engine.run(TASK, 'no-such-engine', [''], 'img')


class EmotionRecognizerTest(SimpleTestCase):
    """The recognizer keeps the flow (smoothing); the models are the service's."""

    def test_it_asks_for_the_models_of_its_settings_through_the_client(self):
        from wama.common.backends.emotions import EmotionRecognizer
        answer = {'emotions': {'happy': 1.0}, 'age': 30, 'gender': 'Man', 'gender_confidence': 0.9}
        with mock.patch('wama.common.tensorflow_service.service_client.run', return_value=answer) as run, \
                mock.patch('importlib.util.find_spec', return_value=object()):
            result = EmotionRecognizer(backend='deepface', enable_age_gender=True).process(
                np.zeros((2, 2, 3), np.uint8), 0.0)
        self.assertEqual(['deepface-expression', 'deepface-age', 'deepface-gender'],
                         run.call_args.kwargs['models'])
        self.assertEqual(('happy', 30, 'Man'), (result.dominant_emotion, result.age, result.gender))

    def test_smoothing_stays_with_the_flow(self):
        from wama.common.backends.emotions import EmotionRecognizer
        answers = [{'emotions': {'happy': 1.0}}, {'emotions': {'sad': 1.0}}]
        with mock.patch('wama.common.tensorflow_service.service_client.run', side_effect=answers):
            recognizer = EmotionRecognizer(backend='fer', smoothing_window=2)
            recognizer.process(np.zeros((2, 2, 3), np.uint8), 0.0)
            second = recognizer.process(np.zeros((2, 2, 3), np.uint8), 0.1)
        self.assertAlmostEqual(0.5, second.happy)
        self.assertAlmostEqual(0.5, second.sad)

    def test_a_failed_analysis_reads_as_no_result(self):
        from wama.common.backends.emotions import EmotionRecognizer
        with mock.patch('wama.common.tensorflow_service.service_client.run', side_effect=RuntimeError('boom')):
            self.assertIsNone(EmotionRecognizer(backend='fer').process(np.zeros((2, 2, 3), np.uint8), 0.0))

    def test_without_deepface_it_falls_back_on_fer_and_stops_asking_for_age(self):
        from wama.common.backends.emotions import EmotionRecognizer
        with mock.patch('importlib.util.find_spec', return_value=None), \
                mock.patch('wama.common.tensorflow_service.service_client.run',
                           return_value={'emotions': {'happy': 1.0}}) as run:
            EmotionRecognizer(backend='deepface', enable_age_gender=True).process(
                np.zeros((2, 2, 3), np.uint8), 0.0)
        self.assertEqual(('fer', ['']), (run.call_args.kwargs['engine'], run.call_args.kwargs['models']))


class ServiceTest(SimpleTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from wama.common.tensorflow_service import service
        cls.service = service

    def setUp(self):
        from fastapi.testclient import TestClient
        self.client = TestClient(self.service.app)
        self.service._ready.clear()
        self.service._loading.clear()
        self.service._stopping.clear()
        self.addCleanup(self.service._stopping.clear)
        self.addCleanup(self.service._ready.clear)
        buffer = io.BytesIO()
        np.save(buffer, np.zeros((2, 2, 3), np.uint8), allow_pickle=False)
        self.body = buffer.getvalue()
        self.params = {'params': json.dumps({'task': TASK, 'engine': 'fer', 'models': [''], 'options': {}})}

    def _post(self):
        return self.client.post('/run', params=self.params, content=self.body,
                                headers={'Content-Type': 'application/octet-stream'})

    def test_it_answers_503_while_loading_or_stopping_so_the_caller_falls_back(self):
        self.assertEqual(503, self._post().status_code)
        self.assertEqual('loading', self.client.get('/health').json()['status'])
        self.service._ready.set()
        self.service._stopping.set()
        self.assertEqual('stopping', self._post().json()['detail']['status'])

    def test_a_request_reaches_the_engine_with_the_array_itself(self):
        self.service._ready.set()
        with mock.patch.object(self.service.engine, 'run', return_value={'emotions': {'happy': 1.0}}) as run:
            response = self._post()
        self.assertEqual(200, response.status_code)
        self.assertEqual({'emotions': {'happy': 1.0}}, response.json()['result'])
        self.assertEqual((2, 2, 3), run.call_args.args[3].shape)

    def test_a_model_the_card_cannot_take_is_refused_before_it_loads(self):
        self.service._ready.set()
        backend = mock.Mock(is_loaded=False, recommended_vram_gb=2.6)
        with mock.patch.object(runtime, 'on_the_card', return_value=True), \
                mock.patch.object(self.service, '_on_card_backends', return_value=[]), \
                mock.patch.object(self.service.engine, 'backend', return_value=backend), \
                mock.patch.object(gov, 'card_free_gb', return_value=1.0), \
                mock.patch.object(self.service.engine, 'run') as run:
            response = self._post()
        self.assertEqual('no_room', response.json()['detail']['status'])
        run.assert_not_called()

    def test_the_reserve_already_held_counts_towards_the_room_of_the_next_model(self):
        held = mock.Mock(recommended_vram_gb=6.6)
        with mock.patch.object(self.service, '_on_card_backends', return_value=[held]), \
                mock.patch.object(gov, 'card_free_gb', return_value=0.2):
            self.assertTrue(self.service._card_can_take(mock.Mock(recommended_vram_gb=6.5)))
        with mock.patch.object(self.service, '_on_card_backends', return_value=[]), \
                mock.patch.object(gov, 'card_free_gb', return_value=0.2):
            self.assertFalse(self.service._card_can_take(mock.Mock(recommended_vram_gb=6.5)))

    def test_an_analysis_that_fails_is_an_error(self):
        self.service._ready.set()
        with mock.patch.object(self.service.engine, 'run', side_effect=RuntimeError('boom')):
            self.assertEqual(500, self._post().status_code)

    def test_releasing_stops_the_process_only_if_it_holds_the_card(self):
        with mock.patch.object(self.service, '_on_card_backends', return_value=[]), \
                mock.patch.object(self.service.threading, 'Timer') as timer:
            self.assertEqual(0, self.service._stop_for_the_card())
        timer.assert_not_called()

    def test_stopping_gives_its_lines_back_says_it_is_on_purpose_and_exits_after_the_answer(self):
        backend = mock.Mock()
        with mock.patch.object(self.service, '_on_card_backends', return_value=[backend]), \
                mock.patch('wama.common.backends.base._LIVE_BACKENDS', [backend]), \
                mock.patch.object(self.service.threading, 'Timer') as timer:
            self.assertEqual(1, self.service._stop_for_the_card())
        backend.unload.assert_called_once_with()
        self.assertIs(self.service._leave, timer.call_args.args[1])
        timer.return_value.start.assert_called_once_with()
        self.assertTrue(self.service._stopping.is_set())
        with mock.patch('wama.common.utils.service_supervision.note_stopped_on_purpose') as noted, \
                mock.patch.object(self.service.os, '_exit') as left:
            self.service._leave()
        noted.assert_called_once_with('tensorflow_service')
        left.assert_called_once_with(0)

    def test_a_model_that_fails_to_unload_does_not_keep_the_process_from_leaving(self):
        broken, other = mock.Mock(), mock.Mock()
        broken.unload.side_effect = RuntimeError('boom')
        with mock.patch.object(self.service, '_on_card_backends', return_value=[broken, other]), \
                mock.patch('wama.common.backends.base._LIVE_BACKENDS', [broken, other]), \
                mock.patch.object(self.service.threading, 'Timer') as timer:
            self.assertEqual(2, self.service._stop_for_the_card())
        other.unload.assert_called_once_with()
        timer.return_value.start.assert_called_once_with()

    def test_it_is_busy_while_it_loads_or_serves_the_flow_of_images(self):
        with mock.patch.object(gov, 'busy_tenants', return_value=set()):
            self.assertFalse(self.service._is_busy())
            self.service._loading.set()
            self.addCleanup(self.service._loading.clear)
            self.assertTrue(self.service._is_busy())
        self.service._loading.clear()
        with mock.patch.object(gov, 'busy_tenants', return_value={gov.tenant_id()}):
            self.assertTrue(self.service._is_busy())

    def test_it_registers_as_a_tenant_with_its_stop_as_its_unload(self):
        with mock.patch.object(self.service.threading, 'Thread'), \
                mock.patch('wama.common.services.resource_governor.start_release_listener') as listener, \
                mock.patch.object(self.service, '_stop_for_the_card', return_value=2), \
                mock.patch.object(runtime, 'use_the_card') as claimed:
            self.service._startup()
            tenant = listener.call_args.args[0]
            self.assertEqual('tensorflow_service', tenant.name)
            self.assertEqual(2, tenant.unload())
        claimed.assert_called_once_with()

    def test_a_restart_waits_while_a_task_claims_the_card_and_loads_nothing_there(self):
        backend = mock.Mock(is_loaded=False, recommended_vram_gb=0.7)
        looks = iter([True, False])
        self.addCleanup(self.service._ready.clear)
        with mock.patch.object(runtime, 'tensorflow'), \
                mock.patch.object(runtime, 'on_the_card', return_value=True), \
                mock.patch.object(self.service.engine, 'backend', return_value=backend), \
                mock.patch.object(self.service, '_release_requested', side_effect=lambda: next(looks)), \
                mock.patch.object(self.service, '_card_can_take', return_value=True), \
                mock.patch.object(self.service.time, 'sleep') as slept:
            self.service._warm_up()
        slept.assert_called_once()
        backend.ensure_loaded.assert_called_once_with('deepface-expression')
        self.assertTrue(self.service._ready.is_set())

    def test_targeted_requests_do_not_hold_the_warm_up(self):
        with mock.patch.object(gov, 'pending_release_requests',
                               return_value={'a': {'models': ['x'], 'requester': '1'}}):
            self.assertFalse(self.service._release_requested())
        with mock.patch.object(gov, 'pending_release_requests', return_value={'a': {'requester': '1'}}):
            self.assertTrue(self.service._release_requested())


class SupervisionFlagsTest(SimpleTestCase):

    def test_the_flags_are_the_files_the_watchdog_reads(self):
        from wama.common.utils.service_supervision import ask_for_service, note_stopped_on_purpose
        with tempfile.TemporaryDirectory() as folder, override_settings(BASE_DIR=Path(folder)):
            os.mkdir(os.path.join(folder, 'logs'))
            ask_for_service('x_service')
            note_stopped_on_purpose('x_service')
            self.assertEqual({'service_wanted.x_service', 'service_stopped.x_service'},
                             set(os.listdir(os.path.join(folder, 'logs'))))


class ServiceDeathReportTest(SimpleTestCase):

    def test_a_service_has_no_task_to_settle_and_is_named_as_a_service(self):
        from django.core.management import call_command
        with mock.patch('wama.common.utils.process_control.reconcile_dead_worker_tasks') as settled, \
                mock.patch('wama.common.utils.notifications.notify_admins', return_value=(1, True)) as told:
            call_command('worker_died', node='privacy_service', outcome='restarted', kind='service',
                         stdout=io.StringIO())
        settled.assert_not_called()
        self.assertIn('Le service privacy_service', told.call_args.args[2])


class SupervisionShellTest(SimpleTestCase):
    """The supervision of the services, executed by bash with stubs — skipped without bash (Windows)."""

    def setUp(self):
        self.bash = shutil.which('bash')
        if not self.bash or not Path('/proc/version').exists():
            self.skipTest('bash (Linux) required')
        folder = tempfile.mkdtemp(prefix='wama-supervision-')
        self.addCleanup(shutil.rmtree, folder, True)
        self.logs = Path(folder)

    def _pass(self, service, *, alive=False, passes=1, wanted=False, stopped=False, comes_up=True):
        """`passes` supervision passes on `service`; stub start/report/log print what happens."""
        if wanted:
            (self.logs / f'service_wanted.{service}').touch()
        if stopped:
            (self.logs / f'service_stopped.{service}').touch()
        script = f'''
            PROJECT_DIR="{BASE}"; LOG_DIR="{self.logs}"; source "{SERVICES_SH}"
            declare -A RESTARTS GAVE_UP
            MAX_RESTARTS=2; WINDOW_S=1800; READY_WAIT_S=2; UP={'1' if alive else '0'}
            wama_service_alive() {{ [ "$UP" = 1 ]; }}
            start_wama_service() {{ echo "START $1"; {'UP=1' if comes_up else ':'}; }}
            log() {{ :; }}
            report() {{ echo "REPORT $1 $2 $4"; }}
            sleep() {{ :; }}
            for i in $(seq 1 {passes}); do
                supervise_one {service} service
                [ "{passes}" -gt 1 ] && UP=0 || true
            done
        '''
        return subprocess.run([self.bash, '-c', script], capture_output=True, text=True, timeout=30)

    def test_a_service_on_demand_stays_stopped_until_someone_asks_for_it(self):
        out = self._pass('tensorflow_service')
        self.assertEqual('', out.stdout, out.stderr)

    def test_asked_for_it_comes_back_and_an_ordinary_death_is_reported(self):
        out = self._pass('tensorflow_service', wanted=True)
        self.assertEqual('START tensorflow_service\nREPORT tensorflow_service restarted service\n',
                         out.stdout, out.stderr)

    def test_a_stop_on_purpose_is_neither_reported_nor_counted_against_the_budget(self):
        out = self._pass('tensorflow_service', wanted=True, stopped=True)
        self.assertEqual('START tensorflow_service\n', out.stdout, out.stderr)
        self.assertFalse((self.logs / 'service_stopped.tensorflow_service').exists())

    def test_a_service_alive_again_clears_the_demand(self):
        out = self._pass('tensorflow_service', alive=True, wanted=True, stopped=True)
        self.assertEqual('', out.stdout, out.stderr)
        self.assertEqual([], [p.name for p in self.logs.iterdir()])

    def test_a_service_that_keeps_dying_exhausts_its_budget(self):
        out = self._pass('tensorflow_service', wanted=True, passes=4)
        self.assertEqual(2, out.stdout.count('START'), out.stdout + out.stderr)
        self.assertEqual(1, out.stdout.count('REPORT tensorflow_service gave_up service'), out.stdout)

    def test_a_service_of_the_always_family_is_restarted_without_being_asked(self):
        out = self._pass('privacy_service')
        self.assertIn('START privacy_service', out.stdout, out.stderr)

    def _source(self, command):
        return subprocess.run([self.bash, '-c', f'PROJECT_DIR="{BASE}"; LOG_DIR=/tmp; source "{SERVICES_SH}"; {command}'],
                              capture_output=True, text=True, timeout=30, cwd=str(BASE))

    def test_every_service_is_the_declared_source_on_its_declared_port_and_its_module_exists(self):
        from urllib.parse import urlparse
        from wama.common import external_sources
        names = self._source('echo $WAMA_SERVICES').stdout.split()
        self.assertTrue(names)
        sources = {s.key: s for s in external_sources.SOURCES}
        for name in names:
            spec = self._source(f'wama_service_spec {name}').stdout.split()
            module, port = spec[0], int(spec[1])
            self.assertEqual(port, urlparse(sources[name].base).port, name)
            self.assertTrue((BASE / (module.replace('.', '/') + '.py')).is_file(), module)

    def test_every_service_pattern_is_bracketed_and_an_unknown_one_is_never_alive(self):
        names = self._source('echo $WAMA_SERVICES').stdout.split()
        for name in names:
            self.assertRegex(self._source(f'wama_service_pattern {name}').stdout, r'\[\w\]', name)
        self.assertIn('DEAD', self._source('wama_service_alive bogus && echo ALIVE || echo DEAD').stdout)

    def test_the_start_is_a_local_uvicorn_with_one_worker(self):
        log = self.logs / 'tensorflow-service.log'
        out = self._source(f'python() {{ echo "$*"; }}; nohup() {{ "$@"; }}; LOG_DIR="{self.logs}"; '
                           f'start_wama_service tensorflow_service; '
                           f'for i in $(seq 50); do [ -s "{log}" ] && break; sleep 0.1; done')
        self.assertIn('-m uvicorn wama.common.tensorflow_service.service:app --host 127.0.0.1 '
                      '--port 8004 --workers 1', log.read_text(), out.stderr)


class TensorFlowOffTheCardRealTest(SimpleTestCase):
    """A real TensorFlow, in a child process: the fallback shows it no card."""

    def test_the_fallback_really_hides_the_card(self):
        import importlib.util
        if importlib.util.find_spec('tensorflow') is None:
            self.skipTest('tensorflow is not installed in this venv')
        code = ("from wama.common.tensorflow_service import runtime; tf = runtime.tensorflow(); "
                "print(tf.config.get_visible_devices('GPU'), runtime.on_the_card())")
        env = dict(os.environ, DJANGO_SETTINGS_MODULE='wama.settings', PYTHONPATH=str(BASE))
        out = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True,
                             cwd=str(BASE), env=env, timeout=280)
        self.assertEqual(0, out.returncode, out.stderr[-2000:])
        self.assertEqual('[] False', out.stdout.strip().splitlines()[-1])
