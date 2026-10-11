"""
The enhancer's ONNX weights are DECLARED and installed by the route (2026-10-11).

Before, `apps.py` downloaded them at `runserver` start through `utils/model_downloader.py`
(QualityScaler GitHub « latest », then the `svjack/AI-onnx` mirror on its `main` branch) — a
second install path with no disk guard, no digest and no journal, whose primary source publishes
no file any more. The app now declares each file (path, measured size and digest, origin) and the
discovery lists every declared model, present or not: an absent one is INSTALLABLE.
"""
import importlib.util
import re
import tempfile
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.enhancer.utils import model_config


class DeclaredOnnxWeightsTest(SimpleTestCase):

    def test_each_model_names_its_own_file_with_size_digest_and_origin(self):
        from wama.model_manager.services.model_installer import declared_files_error
        for model_id, cfg in model_config.ENHANCER_MODELS.items():
            with self.subTest(model=model_id):
                files = cfg['files']
                self.assertEqual([cfg['file']], [f['path'] for f in files],
                                 'the declared file is the one the engine opens')
                self.assertIsNone(declared_files_error(
                    {'kind': 'files', 'ref': f'enhancer:{model_id}', 'files': files,
                     'target_dir': str(model_config.ONNX_MODELS_DIR)}))

    def test_every_file_comes_from_the_pinned_mirror(self):
        for cfg in model_config.ENHANCER_MODELS.values():
            origin = cfg['files'][0]['origin']
            self.assertEqual(model_config.ONNX_MIRROR,
                             {k: origin[k] for k in ('source', 'repo', 'revision')})

    def test_the_anime_file_has_another_name_on_the_mirror(self):
        anime = model_config.ENHANCER_MODELS['RealESR_Animex4']['files'][0]
        self.assertEqual(('RealESR_Animex4_fp16.onnx', 'RealSRx4_Anime_fp16.onnx'),
                         (anime['path'], anime['origin']['file']))


class DiscoveryListsDeclaredModelsTest(SimpleTestCase):
    """A declared model has a catalogue row even when its file is absent — and the route can
    install it into the folder the engine reads."""

    def _discover(self, root):
        from wama.model_manager.services.model_registry import ModelRegistry
        onnx_dir = Path(root) / 'models' / 'upscaling' / 'onnx'
        paths = {**settings.MODEL_PATHS,
                 'upscaling': {**settings.MODEL_PATHS.get('upscaling', {}), 'onnx': onnx_dir}}
        with self.settings(AI_MODELS_DIR=Path(root), MODEL_PATHS=paths):
            registry = ModelRegistry()
            registry._models = {}
            registry._discover_enhancer_models()
        return registry._models, onnx_dir

    def test_an_absent_model_is_listed_installable(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_installer import spec_for_catalog_row
        with tempfile.TemporaryDirectory() as root:
            models, onnx_dir = self._discover(root)
            info = models['enhancer:BSRGANx4']
            self.assertFalse(info.is_downloaded)
            with self.settings(AI_MODELS_DIR=Path(root)):
                spec = spec_for_catalog_row(AIModel(model_key='enhancer:BSRGANx4',
                                                    extra_info=info.extra_info))
        self.assertEqual('files', spec['kind'])
        self.assertEqual(str(onnx_dir), spec['target_dir'])
        self.assertEqual(model_config.ENHANCER_MODELS['BSRGANx4']['files'], spec['files'])
        self.assertAlmostEqual(33822821 / 1024 ** 2, info.extra_info['size_mb'], places=3)

    def test_a_present_file_is_installed_and_an_undeclared_one_still_listed(self):
        with tempfile.TemporaryDirectory() as root:
            onnx_dir = Path(root) / 'models' / 'upscaling' / 'onnx'
            onnx_dir.mkdir(parents=True)
            (onnx_dir / 'BSRGANx2_fp16.onnx').write_bytes(b'x')
            (onnx_dir / 'Handmade_x4.onnx').write_bytes(b'x' * 2048)
            models, _ = self._discover(root)
        self.assertTrue(models['enhancer:BSRGANx2'].is_downloaded)
        self.assertFalse(models['enhancer:BSRGANx4'].is_downloaded)
        handmade = models['enhancer:Handmade_x4']
        self.assertTrue(handmade.is_downloaded)
        self.assertNotIn('declared_files', handmade.extra_info,
                         'a file the app does not declare has no origin to install from')
        self.assertEqual(set(f'enhancer:{m}' for m in model_config.ENHANCER_MODELS)
                         | {'enhancer:Handmade_x4'},
                         {k for k in models if k not in ('enhancer:resemble',
                                                         'enhancer:deepfilternet')})


class NoParallelDownloaderTest(SimpleTestCase):
    """The startup download and its command are gone (REMOVAL_LEDGER R111)."""

    def test_the_downloader_and_its_command_are_gone(self):
        for module in ('wama.enhancer.utils.model_downloader',
                       'wama.enhancer.management.commands.download_enhancer_models'):
            with self.subTest(module=module):
                self.assertIsNone(importlib.util.find_spec(module))

    def test_nothing_calls_them_any_more(self):
        """Word-bounded: Cam Analyzer's `road_model_downloader` is another module. The `_01`
        sandboxes are regenerated copies, never the source."""
        base = Path(settings.BASE_DIR)
        gone = re.compile(r'\b(model_downloader|download_enhancer_models|'
                          r'check_and_download_essential_models)\b')
        found = []
        for root in ('wama', 'wama_lab', 'wama_data'):
            for path in (base / root).rglob('*.py'):
                rel = path.relative_to(base).as_posix()
                if path.name.startswith('tests') or re.search(r'/[a-z_]+_01/', rel):
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                found += [f'{rel}: {m}' for m in gone.findall(text)]
        self.assertEqual([], found)
