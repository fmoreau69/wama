"""
The MediaPipe face landmarker is DECLARED and installed by the route (2026-10-11).

It used to be versioned in the app folder (`face_analyzer/models/`) and, when missing, fetched
there by `urllib` with no digest, no proxy rule and no catalogue row. It now lives under
`MODEL_PATHS['vision']['mediapipe']`, declared with its official origin, and the app never
downloads it.
"""
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from wama_lab.face_analyzer.utils import model_config

LANDMARKER = 'mediapipe-face-landmarker'


class FaceLandmarkerDeclarationTest(SimpleTestCase):

    def test_the_declaration_passes_the_files_driver_lock(self):
        from wama.model_manager.services.model_installer import declared_files_error
        self.assertIsNone(declared_files_error({
            'kind': 'files', 'ref': model_config.FACE_LANDMARKER_KEY,
            'files': model_config.FACE_LANDMARKER_FILES,
            'target_dir': str(model_config.MEDIAPIPE_DIR)}))

    def test_the_origin_is_googles_official_address(self):
        from wama.model_manager.services.model_installer import declared_file_url
        origin = model_config.FACE_LANDMARKER_FILES[0]['origin']
        self.assertEqual('https://storage.googleapis.com/mediapipe-models/face_landmarker/'
                         'face_landmarker/float16/1/face_landmarker.task',
                         declared_file_url(origin))

    def test_the_folder_is_the_declared_model_path(self):
        self.assertEqual(Path(settings.MODEL_PATHS['vision']['mediapipe']),
                         model_config.MEDIAPIPE_DIR)
        self.assertEqual(model_config.MEDIAPIPE_DIR / 'face_landmarker.task',
                         model_config.chemin_local(LANDMARKER))

    def test_the_backend_reads_the_same_declaration_through_the_common_pass_through(self):
        """The backend lives in the substrate and never imports the app : it reads
        `FACE_ANALYZER_MODELS` by the convention (`model_declarations`), across worlds."""
        from wama.common.backends.mediapipe_face_landmarker_backend import (
            MediaPipeFaceLandmarkerBackend)
        from wama.common.utils.model_declarations import declaration
        self.assertIs(model_config.FACE_ANALYZER_MODELS[LANDMARKER],
                      declaration('face_analyzer', LANDMARKER))
        self.assertEqual(model_config.chemin_local(LANDMARKER),
                         MediaPipeFaceLandmarkerBackend.model_file(model_config.FACE_LANDMARKER_KEY))
        self.assertEqual({LANDMARKER: {'model_key': model_config.FACE_LANDMARKER_KEY}},
                         MediaPipeFaceLandmarkerBackend.SUPPORTED_MODELS)

    def test_no_model_file_is_versioned_in_the_app_any_more(self):
        app = Path(settings.BASE_DIR) / 'wama_lab' / 'face_analyzer'
        self.assertEqual([], [str(p) for p in app.rglob('*.task')])


class TheCatalogueRowIsInstallableTest(SimpleTestCase):

    def test_the_row_derives_a_files_spec_into_the_mediapipe_folder(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_installer import spec_for_catalog_row
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_face_analyzer_models()
        info = registry._models[model_config.FACE_LANDMARKER_KEY]
        spec = spec_for_catalog_row(AIModel(model_key=model_config.FACE_LANDMARKER_KEY,
                                            extra_info=info.extra_info))
        self.assertEqual(('files', str(model_config.MEDIAPIPE_DIR)),
                         (spec['kind'], spec['target_dir']))
        self.assertEqual(model_config.FACE_LANDMARKER_FILES, spec['files'])


class TheAppNeverDownloadsItTest(SimpleTestCase):
    """Since 2026-11-08 the backend of the common contract opens the file (the app asks the common
    gate) : absent, its `load` says how to install it, and nothing is fetched."""

    def _backend(self):
        from wama.common.backends.mediapipe_face_landmarker_backend import (
            MediaPipeFaceLandmarkerBackend)
        return MediaPipeFaceLandmarkerBackend()

    def _paths(self, folder):
        return {**settings.MODEL_PATHS,
                'vision': {**settings.MODEL_PATHS['vision'], 'mediapipe': Path(folder)}}

    def test_an_absent_model_says_how_to_install_it(self):
        with tempfile.TemporaryDirectory() as empty, self.settings(MODEL_PATHS=self._paths(empty)), \
                patch('urllib.request.urlretrieve') as fetch, \
                patch('requests.get') as get, \
                patch('mediapipe.tasks.python.vision.FaceLandmarker.create_from_options') as create:
            with self.assertRaisesMessage(RuntimeError, model_config.FACE_LANDMARKER_KEY):
                self._backend().load(model_config.FACE_LANDMARKER_KEY)
        fetch.assert_not_called()
        get.assert_not_called()
        create.assert_not_called()

    def test_a_present_model_is_read_where_the_route_put_it(self):
        with tempfile.TemporaryDirectory() as folder, self.settings(MODEL_PATHS=self._paths(folder)), \
                patch('mediapipe.tasks.python.vision.FaceLandmarker.create_from_options') as create:
            (Path(folder) / 'face_landmarker.task').write_bytes(b'x')
            self.assertTrue(self._backend().load(model_config.FACE_LANDMARKER_KEY))
        options = create.call_args.args[0]
        self.assertEqual(str(Path(folder) / 'face_landmarker.task'),
                         options.base_options.model_asset_path)
        self.assertEqual(1, options.num_faces)
