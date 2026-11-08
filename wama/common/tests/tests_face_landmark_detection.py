"""Le Face Landmarker au contrat commun (`face-landmark-detection`) — les repères du Face Analyzer.

Jusqu'au 2026-11-08, l'app (monde Lab) le chargeait elle-même (`preprocessing.FaceDetector`, un
`FaceLandmarker` par détecteur, donc par image en temps réel), sa ligne disait `loaded_by`. Le
backend vit au substrat et lit la déclaration de l'app par le passe-plat commun, ouvert ce jour-là
à tous les mondes (`model_declarations._app_package`). `mediapipe` sert aussi les gestes de la main,
au navigateur : ce backend ne doit jamais les recevoir.

⚠ Identifiants en anglais ; commentaires et docstrings en français. Aucun modèle chargé.
"""
from pathlib import Path
from unittest import mock

import numpy as np
from django.test import SimpleTestCase, TestCase

KEY = 'face_analyzer:mediapipe-face-landmarker'


def _row(key=KEY, task='face-landmark-detection', runtime=None, source='face_analyzer'):
    from wama.model_manager.models import AIModel
    return AIModel.objects.create(model_key=key, name=key, model_type='vision', source=source,
                                  is_downloaded=True, capabilities={'task': task},
                                  composition={'runtime': runtime or {'engine': 'mediapipe'}})


class FaceLandmarksThroughTheCommonContractTest(TestCase):

    def test_the_line_resolves_its_backend_of_the_contract(self):
        from wama.common.backends.manager import _work_method, backend_for_key
        from wama.common.backends.mediapipe_face_landmarker_backend import (
            MediaPipeFaceLandmarkerBackend)
        _row()
        self.assertIs(MediaPipeFaceLandmarkerBackend, backend_for_key(KEY))
        self.assertEqual('detect_face_landmarks', _work_method(MediaPipeFaceLandmarkerBackend))

    def test_the_task_has_its_binding_contract_and_the_backend_implements_it(self):
        from wama.common.backends.face_landmark_detection_base import FaceLandmarkDetectionBackend
        from wama.common.backends.mediapipe_face_landmarker_backend import (
            MediaPipeFaceLandmarkerBackend)
        from wama.common.services.backend_inventory import TASK_CONTRACTS
        self.assertEqual(('face_landmark_detection_base', 'FaceLandmarkDetectionBackend', True),
                         TASK_CONTRACTS['face-landmark-detection'])
        self.assertTrue(issubclass(MediaPipeFaceLandmarkerBackend, FaceLandmarkDetectionBackend))

    def test_the_hand_gestures_are_never_handed_to_it(self):
        """`mediapipe` sert aussi les gestes de la main, mais au NAVIGATEUR : leur ligne, telle
        que la découverte l'écrit, ne déclare aucun moteur — c'est ce qui la tient hors de ce
        backend. (Le filtre « un backend LIANT ne sert que sa tâche » est réservé aux moteurs
        distants, décision mesurée du 2026-09-30, `backend_inventory.resolve_entry`.)"""
        from wama.common.backends.manager import backend_for_key
        from wama.common.hand_gestures import GESTURE_KEY
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        registry = _registry()
        registry._discover_hand_gesture_models()
        line = registry._models[GESTURE_KEY]
        self.assertNotIn('engine', line.composition['runtime'])
        _row(GESTURE_KEY, line.capabilities['task'], line.composition['runtime'],
             source='mediapipe_models')
        self.assertIsNone(backend_for_key(GESTURE_KEY))

    def test_the_manifest_requires_the_library_of_its_backend(self):
        from wama.common.manifests.builtin.model import _requires_librairies
        body = {'composition': {'runtime': {'engine': 'mediapipe'}},
                'capabilities': {'task': 'face-landmark-detection'}}
        self.assertEqual(['mediapipe'], [r['key'] for r in _requires_librairies(body, KEY)])

    def test_the_discovery_retracts_the_loader_it_used_to_name(self):
        from wama.model_manager.services.model_sync import merged_composition
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        registry = _registry()
        registry._discover_face_analyzer_models()
        line = registry._models[KEY]
        prior = {'runtime': {'engine': 'mediapipe',
                             'loaded_by': 'wama_lab.face_analyzer.utils.preprocessing'}}
        self.assertEqual({'runtime': {'engine': 'mediapipe'}},
                         merged_composition(prior, line.composition))
        self.assertEqual(('face-landmark-detection', 'face_analyzer'),
                         (line.capabilities['task'], line.source.value))

    def test_an_anatomy_no_provenance_founds_is_retracted_a_declared_one_stays(self):
        """Vécu le 2026-11-08 : un worker démarré avant le portage (ancienne découverte, NOUVELLE
        déclaration) a posé sur le Face Landmarker le composant d'un poids DeepFace ; la synchro
        gardait ce que la découverte tait. Une clé émise à `None` est un retrait."""
        from wama.model_manager.services.model_sync import merged_composition
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        registry = _registry()
        registry._discover_face_analyzer_models()
        stale = {'runtime': {'engine': 'mediapipe'},
                 'components': [{'repo': 'serengil/deepface_models', 'role': 'face_landmarker.task'}]}
        self.assertEqual({'runtime': {'engine': 'mediapipe'}},
                         merged_composition(stale, registry._models[KEY].composition))
        deepface = registry._models['face_analyzer:deepface-expression'].composition
        merged = merged_composition({'runtime': {'engine': 'deepface'}}, deepface)
        self.assertEqual([{'repo': 'serengil/deepface_models',
                           'role': 'facial_expression_model_weights.h5'}], merged['components'])

    def test_the_app_gets_its_detector_from_the_common_gate_once(self):
        from wama.common.backends.mediapipe_face_landmarker_backend import (
            MediaPipeFaceLandmarkerBackend)
        from wama_lab.face_analyzer.utils.preprocessing import FaceDetector
        _row()
        portrait = np.zeros((40, 40, 3), dtype=np.uint8)
        face = np.array([[5.0, 6.0, 0.0], [30.0, 35.0, 0.1]])
        with mock.patch.object(MediaPipeFaceLandmarkerBackend, 'load', return_value=True) as load, \
                mock.patch.object(MediaPipeFaceLandmarkerBackend, 'detect_face_landmarks',
                                  return_value=[face]) as detect:
            first, second = FaceDetector(), FaceDetector()
            found = first.detect(portrait)
            second.detect(portrait)
        self.assertIs(first._backend, second._backend, 'one instance, kept by the common cache')
        load.assert_called_with(KEY)
        self.assertEqual((5, 6, 25, 29), found.bbox)
        self.assertEqual((40, 40, 3), detect.call_args.kwargs['image'].shape)


class DeclarationsAcrossWorldsTest(SimpleTestCase):
    """Le passe-plat des déclarations trouve l'app par son `AppConfig`, quel que soit son monde ;
    hors du registre de Django (le service vocal), l'emplacement du monde Médias."""

    def test_a_lab_app_and_a_media_app_are_both_found(self):
        from wama.common.utils.model_declarations import declarations
        from wama_lab.face_analyzer.utils.model_config import FACE_ANALYZER_MODELS
        self.assertIs(FACE_ANALYZER_MODELS, declarations('face_analyzer'))
        self.assertTrue(declarations('composer'))
        self.assertEqual({}, declarations('huggingface'))

    def test_outside_the_app_registry_the_media_world_is_read(self):
        from wama.common.utils import model_declarations
        with mock.patch('django.apps.apps.get_app_config', side_effect=LookupError):
            self.assertEqual('wama.composer', model_declarations._app_package('composer'))
            self.assertTrue(model_declarations.declarations('composer'))

    def test_the_engine_overlay_reads_the_same_pass_through(self):
        """La passe qui reporte le moteur déclaré relisait la convention elle-même (`wama.` en
        dur) : une ligne du Lab sans moteur le reçoit désormais de sa déclaration."""
        from types import SimpleNamespace
        from wama.model_manager.tests.tests_model_loaded_by import _registry
        registry = _registry()
        registry._models = {KEY: SimpleNamespace(composition={})}
        with mock.patch.object(type(registry), '_overlay_engines_named_by_backends'), \
                mock.patch.object(type(registry), '_overlay_engines_derived_from_disk'), \
                mock.patch.object(type(registry), '_overlay_components_derived_from_disk'):
            registry._overlay_declared_engines()
        self.assertEqual({'engine': 'mediapipe'}, registry._models[KEY].composition['runtime'])


FAKE_LANDMARKER = '''
import numpy as np
from .face_landmark_detection_base import FaceLandmarkDetectionBackend


class FakeLandmarker(FaceLandmarkDetectionBackend):
    def load(self, model=None):
        self._loaded = True
        return True

    def unload(self):
        self._loaded = False

    def detect_face_landmarks(self, image):
        h, w = image.shape[:2]
        uniform = bool((image == image.flat[0]).all())
        return __ANSWER__
'''


class FaceLandmarksSmokeTest(SimpleTestCase):
    """L'essai du contrat (`backend_proposals.SMOKES`) : un détecteur que propose le rôle `backend`
    trouve le visage d'un portrait de la médiathèque système, en pixels, et rien sur une image unie."""

    def _smoke(self, answer: str):
        """`answer` : l'EXPRESSION que rend le faux détecteur (source du module proposé)."""
        import tempfile

        from PIL import Image
        from wama.common.services import backend_proposals
        with tempfile.TemporaryDirectory() as folder:
            portrait = Path(folder) / 'portrait.png'
            pixels = np.zeros((60, 80, 3), dtype=np.uint8)
            pixels[10:50, 20:60] = 200
            Image.fromarray(pixels).save(portrait)
            with mock.patch.object(backend_proposals, 'smoke_face_image', return_value=str(portrait)):
                return backend_proposals.SMOKES['FaceLandmarkDetectionBackend'](
                    FAKE_LANDMARKER.replace('__ANSWER__', answer),
                    module='fake_landmark_backend', model_key='huggingface:org/fake-landmarks',
                    out_dir=None)

    def test_a_face_in_pixels_and_nothing_on_a_blank_image_passes(self):
        out = self._smoke('[] if uniform else [np.array([[w * 0.5, h * 0.5, 0.0]] * 3)]')
        self.assertTrue(out['ok'], out)
        self.assertEqual([3], out['landmarks'])

    def test_an_answer_outside_the_contract_fails(self):
        cases = {
            'no face on the portrait': ('[]', 'aucun visage'),
            'normalised coordinates': ('[] if uniform else [np.array([[0.5, 0.5, 0.0]] * 3) * 1000]',
                                       'hors du cadre'),
            'a face on a blank image': ('[np.array([[w * 0.5, h * 0.5, 0.0]])]', 'image unie'),
            'not a list of (N, 3)': ('[] if uniform else [np.zeros((3, 2))]', 'hors contrat'),
        }
        for case, (answer, expected) in cases.items():
            with self.subTest(case=case):
                self.assertIn(expected, self._smoke(answer)['error'])
