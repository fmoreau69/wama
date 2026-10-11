"""
MuseTalk's weights are DECLARED by the app and installed by the catalogue route (2026-10-11).

Measured in the vendored code: inference v1.5 reads eleven files from six origins — four Hub
repositories, torchvision's resnet18, face-alignment's S3FD detector (which `load_url` pulled into
`$HOME/.cache/torch`) — plus BiSeNet, published only on Google Drive (a Hub mirror, pinned to the
bytes in service). Nothing created the `vendor/musetalk/models` link the code reads through, and the
install script called a script that does not exist.
"""
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from wama.avatarizer.utils import model_config


class MuseTalkWeightsDeclarationTest(SimpleTestCase):

    def _spec(self):
        return {'kind': 'files', 'ref': 'avatarizer:musetalk-v1.5',
                'files': model_config.MUSETALK_FILES,
                'target_dir': str(model_config.MUSETALK_MODELS_DIR)}

    def test_the_declared_files_pass_the_files_driver_lock(self):
        from wama.model_manager.services.model_installer import declared_files_error
        self.assertIsNone(declared_files_error(self._spec()))

    def test_the_app_puts_them_on_its_model(self):
        self.assertIs(model_config.MUSETALK_FILES,
                      model_config.AVATARIZER_MODELS['musetalk-v1.5']['files'])

    def test_training_only_weights_are_not_declared(self):
        """SyncNet is read by `train.py` only (sync loss) — never by inference."""
        self.assertFalse([f for f in model_config.MUSETALK_FILES if 'syncnet' in f['path']])

    def test_the_backend_paths_are_declared(self):
        """The backend passes the unet and its config; the declaration must hold them."""
        from wama.common.backends import musetalk_backend as mb
        source = Path(mb.__file__).read_text(encoding='utf-8')
        passed = set(re.findall(r"'\./models/([^']+)'", source))
        self.assertEqual({'musetalkV15/unet.pth', 'musetalkV15/musetalk.json'}, passed)
        self.assertLessEqual(passed, {f['path'] for f in model_config.MUSETALK_FILES})

    def test_s3fd_lands_where_the_subprocess_torch_hub_looks(self):
        from wama.common.backends import musetalk_backend as mb
        s3fd = [f for f in model_config.MUSETALK_FILES if 's3fd' in f['path']]
        self.assertEqual(1, len(s3fd))
        torch_home = mb.MUSETALK_TORCH_HOME.relative_to(mb.MUSETALK_MODELS_DIR).as_posix()
        self.assertEqual(f"{torch_home}/hub/checkpoints/s3fd-619a316812.pth", s3fd[0]['path'])
        self.assertEqual(Path(mb.MUSETALK_MODELS_DIR), Path(model_config.MUSETALK_MODELS_DIR))

    def test_torch_hub_names_carry_the_digest_prefix(self):
        """torch.hub convention: the file name holds the start of its sha256 — checked against
        the pinned digest, an independent proof that the bytes are the official ones."""
        for f in model_config.MUSETALK_FILES:
            m = re.search(r'-([0-9a-f]{8,})\.pth$', f['path'])
            if m:
                with self.subTest(path=f['path']):
                    self.assertTrue(f['sha256'].startswith(m.group(1)))


class TheVendoredCodeReadsWhatIsDeclaredTest(SimpleTestCase):
    """Read the vendored sources: every `./models/…` path used at inference, and S3FD's address,
    must be the declared ones. A vendor update that moves a file turns this red."""

    def setUp(self):
        self.vendor = Path(settings.BACKEND_VENDOR_DIR) / 'musetalk'
        if not (self.vendor / 'musetalk').exists():
            self.skipTest('MuseTalk is not vendored on this tree (route `library`)')

    def test_preprocessing_and_face_parsing_paths_are_declared(self):
        declared = {f['path'] for f in model_config.MUSETALK_FILES}
        for rel in ('musetalk/utils/preprocessing.py', 'musetalk/utils/face_parsing/__init__.py'):
            source = (self.vendor / rel).read_text(encoding='utf-8')
            for path in re.findall(r"['\"]\./models/([^'\"]+)['\"]", source):
                with self.subTest(file=rel, path=path):
                    self.assertIn(path, declared)

    def test_s3fd_origin_is_the_address_the_library_uses(self):
        from wama.model_manager.services.model_installer import declared_file_url
        source = (self.vendor / 'musetalk/utils/face_detection/detection/sfd/sfd_detector.py'
                  ).read_text(encoding='utf-8')
        url = re.search(r"'s3fd':\s*'([^']+)'", source).group(1)
        s3fd = next(f for f in model_config.MUSETALK_FILES if 's3fd' in f['path'])
        self.assertEqual(url, declared_file_url(s3fd['origin']))


class TheCatalogueRowIsInstallableTest(SimpleTestCase):

    def _discover(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = ModelRegistry()
        registry._models = {}
        registry._discover_avatarizer_models()
        return registry._models['avatarizer:musetalk-v1.5']

    def test_the_row_derives_a_files_spec_into_the_musetalk_folder(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.model_installer import spec_for_catalog_row
        info = self._discover()
        spec = spec_for_catalog_row(AIModel(model_key='avatarizer:musetalk-v1.5',
                                            hf_id=info.hf_id, extra_info=info.extra_info))
        self.assertEqual(('files', str(model_config.MUSETALK_MODELS_DIR)),
                         (spec['kind'], spec['target_dir']),
                         'the declared files win over the hf_id (one repository of four)')

    def test_presence_needs_every_file_inference_reads(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(model_config, 'MUSETALK_MODELS_DIR', Path(root)):
                for f in model_config.MUSETALK_FILES[:-1]:
                    path = Path(root) / f['path']
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(b'x')
                self.assertFalse(self._discover().is_downloaded, 'S3FD is missing')
                last = Path(root) / model_config.MUSETALK_FILES[-1]['path']
                last.parent.mkdir(parents=True, exist_ok=True)
                last.write_bytes(b'x')
                self.assertTrue(self._discover().is_downloaded)


class SetupScriptStepFourGoesThroughTheCatalogueTest(SimpleTestCase):

    def test_step_four_is_the_catalogue_route(self):
        script = (Path(settings.BASE_DIR) / 'wama' / 'avatarizer' / 'setup_avatarizer.sh'
                  ).read_text(encoding='utf-8')
        code = '\n'.join(l for l in script.splitlines() if not l.lstrip().startswith('#'))
        self.assertIn('python manage.py pull_model avatarizer:musetalk-v1.5', code)
        for gone in ('download_weights.py', 'snapshot_download'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, code)
