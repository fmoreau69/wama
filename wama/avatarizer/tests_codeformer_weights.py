"""
CodeFormer's weights are DECLARED by the app and installed by the catalogue route (2026-10-10).

`setup_avatarizer.sh` downloaded them itself, wrongly both ways: the vendored script wrote into
`./weights/` relative to the current directory (and pulled training weights), the `basicsr`
fallback put `codeformer.pth` FLAT and missed two files. The app now declares the four files the
vendored code reads; the discovery makes the row installable; `pull_model <key>` REQUESTS the
install like the button (`request_install`).
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.avatarizer.utils import model_config


class CodeFormerWeightsDeclarationTest(SimpleTestCase):

    def test_the_declared_files_pass_the_github_driver_lock(self):
        from wama.model_manager.services.model_installer import github_spec_error
        spec = {'kind': 'github', **model_config.CODEFORMER_RELEASE,
                'target_dir': str(model_config.CODEFORMER_MODELS_DIR)}
        self.assertIsNone(github_spec_error(spec))
        self.assertTrue(all(f.get('size') for f in spec['files']), 'sizes are measured facts')

    def test_the_subfolders_the_backend_links_are_the_declared_ones(self):
        """The backend names the folders it links (it cannot import the app) — they must be the
        ones the declared files live in."""
        from wama.common.backends.codeformer_backend import CODEFORMER_WEIGHTS_SUBDIRS
        declared = list(dict.fromkeys(f['path'].split('/', 1)[0]
                                      for f in model_config.CODEFORMER_RELEASE['files']))
        self.assertEqual(CODEFORMER_WEIGHTS_SUBDIRS, declared)

    def test_the_main_weight_is_where_the_discovery_looks(self):
        paths = [f['path'] for f in model_config.CODEFORMER_RELEASE['files']]
        self.assertIn('CodeFormer/codeformer.pth', paths)   # model_registry: is_downloaded

    def test_the_app_declares_it_on_its_model(self):
        self.assertIs(model_config.CODEFORMER_RELEASE,
                      model_config.AVATARIZER_MODELS['codeformer']['release'])


class SetupScriptGoesThroughTheCatalogueTest(SimpleTestCase):
    """The install script no longer downloads weights by itself."""

    def test_step_five_is_the_catalogue_route(self):
        script = (Path(settings.BASE_DIR) / 'wama' / 'avatarizer' / 'setup_avatarizer.sh'
                  ).read_text(encoding='utf-8')
        code = '\n'.join(l for l in script.splitlines() if not l.lstrip().startswith('#'))
        self.assertIn('python manage.py pull_model avatarizer:codeformer', code)
        for gone in ('load_file_from_url', 'download_pretrained_models.py',
                     'releases/download'):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, code)
