"""
The DeepFace weights are DECLARED and installable by the route (2026-10-12).

They were catalogued since 2026-09-05 (moved out of `$HOME/.deepface`) but with no origin: the
route could neither install nor uninstall them. Each row now declares its file, the GitHub
release the library pulls, and the digest measured on the official asset.
"""
import re
from pathlib import Path

from django.test import SimpleTestCase

from wama_lab.face_analyzer.utils import model_config


class DeepFaceDeclarationTest(SimpleTestCase):

    def test_each_model_names_its_own_file_with_size_digest_and_origin(self):
        from wama.model_manager.services.model_installer import declared_files_error
        for model_id, cfg in model_config.FACE_ANALYZER_MODELS.items():
            with self.subTest(model=model_id):
                self.assertEqual([cfg['fichier']], [f['path'] for f in cfg['files']],
                                 'the declared file is the one the library opens')
                self.assertIsNone(declared_files_error(
                    {'kind': 'files', 'ref': f'face_analyzer:{model_id}', 'files': cfg['files'],
                     'target_dir': str(model_config.DEEPFACE_DIR)}))

    def test_the_release_is_the_one_the_installed_library_pulls(self):
        try:
            import deepface
        except ImportError:
            self.skipTest('deepface is not installed in this venv')
        demography = Path(deepface.__file__).parent / 'models' / 'demography'
        source = '\n'.join(p.read_text(encoding='utf-8') for p in demography.glob('*.py'))
        tags = set(re.findall(r'deepface_models/releases/download/([^/]+)/', source))
        self.assertEqual({model_config.DEEPFACE_RELEASE.split(':', 1)[1]}, tags)


class TheCatalogueRowsAreInstallableTest(SimpleTestCase):

    def test_each_row_derives_a_files_spec_into_the_deepface_folder(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_installer import spec_for_catalog_row
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_face_analyzer_models()
        for model_id, cfg in model_config.FACE_ANALYZER_MODELS.items():
            with self.subTest(model=model_id):
                key = f'face_analyzer:{model_id}'
                spec = spec_for_catalog_row(AIModel(model_key=key,
                                                    extra_info=registry._models[key].extra_info))
                self.assertEqual(('files', str(model_config.DEEPFACE_DIR), cfg['files']),
                                 (spec['kind'], spec['target_dir'], spec['files']))
