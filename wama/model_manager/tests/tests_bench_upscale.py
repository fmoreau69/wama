"""The upscale bench BY CONSTRUCTION (2026-10-14) : each sharp image is reduced by the model's own
factor, enlarged by the model, and compared to the ORIGINAL (LPIPS, lower is better). The measure
is recorded as an internal scale per factor, the speed goes to the common ETA loop. The backend
and the metric are FAKES here : the test judges the protocol, not a GPU."""
import json
import os
import shutil
import tempfile
from unittest import mock

import numpy as np
from django.test import TestCase


class _ResizeUpscaler:
    """Stands for the catalogue-resolved backend : enlarges by `factor` with a bicubic resize."""
    factor = 4

    def __init__(self, model_name, tile_size=0):
        self.model_name = model_name

    def upscale_image(self, image, blend_factor=0.0):
        import cv2
        h, w = image.shape[:2]
        return cv2.resize(image, (w * self.factor, h * self.factor), interpolation=cv2.INTER_CUBIC)

    def close(self):
        pass


def _mean_abs(a, b):
    return (a - b).abs().mean()


class UpscaleBenchTest(TestCase):

    def setUp(self):
        import cv2
        from wama.model_manager.models import AIModel
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)
        images = os.path.join(self.folder, 'images')
        os.makedirs(images)
        rng = np.random.default_rng(0)
        for name in ('b.png', 'a.png', 'notes.txt'):
            if name.endswith('.png'):
                cv2.imwrite(os.path.join(images, name),
                            rng.integers(0, 255, (50, 66, 3), dtype=np.uint8))
            else:
                open(os.path.join(images, name), 'w').close()
        self.sample = os.path.join(self.folder, 'reference.json')
        with open(self.sample, 'w', encoding='utf-8') as f:
            json.dump({'name': 'tiny_v1', 'format': 'image_folder', 'images': 'images'}, f)
        self.model = AIModel.objects.create(
            model_key='enhancer:fake4', name='fake4', model_type='upscaling', source='enhancer',
            is_available=True, is_downloaded=True, capabilities={'task': 'upscale', 'scale': 4})

    def _run(self, upscaler=_ResizeUpscaler, **options):
        from wama.model_manager.services import bench
        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=upscaler), \
                mock.patch.object(bench, 'lpips_metric', return_value=_mean_abs), \
                mock.patch('wama.common.services.resource_governor.gpu_safe_mode',
                           return_value=False):
            return bench.run_bench('upscale', self.sample, **options)[0]

    def test_the_reference_lists_its_images_in_a_reproducible_order(self):
        from wama.model_manager.services.bench import read_image_reference
        self.assertEqual(['a.png', 'b.png'], read_image_reference(self.sample)['entries'],
                         'sorted, and only images')

    def test_the_measure_is_recorded_on_a_scale_named_by_the_factor(self):
        from wama.common.models import ResultEvaluation
        result = self._run(record=True)
        self.assertIsNone(result['error'])
        self.assertEqual(4, result['scale'])
        row = ResultEvaluation.objects.get(model_key='enhancer:fake4')
        self.assertEqual(('lpips', 'lower', 'bicubic_x4_v1'),
                         (row.metric, row.direction, row.protocol))
        self.assertEqual(2, row.detail['reference_length'])
        self.assertAlmostEqual(result['lpips'], row.value, places=4)

    def test_without_record_nothing_is_written(self):
        from wama.common.models import ResultEvaluation
        self._run()
        self.assertFalse(ResultEvaluation.objects.exists())

    def test_the_speed_goes_to_the_common_eta_loop_per_input_megapixel(self):
        from wama.model_manager.services.eta_estimator import learned_speed
        self._run()
        unit, _seconds, samples = learned_speed('enhancer:fake4')
        self.assertEqual(('megapixel', 1), (unit, samples))

    def test_an_output_of_the_wrong_size_is_an_error_not_a_score(self):
        class Twice(_ResizeUpscaler):
            factor = 2
        self.assertIn('au lieu de', self._run(upscaler=Twice)['error'])

    def test_a_model_without_a_factor_is_refused(self):
        self.model.capabilities = {'task': 'upscale'}
        self.model.save(update_fields=['capabilities'])
        self.assertIn('scale', self._run()['error'])

    def test_a_sample_is_another_population_than_the_whole_set(self):
        from wama.common.models import ResultEvaluation
        self._run(record=True)
        whole = ResultEvaluation.objects.get().reference_sha256
        self._run(record=True, limit=1)
        self.assertNotEqual(whole, ResultEvaluation.objects.get().reference_sha256)


class LpipsIsInstalledByTheRouteTest(TestCase):
    """2026-10-18 : LPIPS's AlexNet was pulled by `torch.hub` at the first bench, beside the
    installer. It has a catalogue row (`quality-metric`) the route installs ; the bench installs it
    and WAITS (a command), then loads the installed file."""

    def test_the_declared_file_passes_the_lock_of_the_files_driver(self):
        from wama.model_manager.services.bench import LPIPS_FILES, lpips_folder
        from wama.model_manager.services.model_installer import declared_files_error
        self.assertIsNone(declared_files_error(
            {'kind': 'files', 'files': LPIPS_FILES, 'target_dir': str(lpips_folder())}))
        self.assertEqual('pytorch_download', LPIPS_FILES[0]['origin']['source'])

    def test_the_row_is_a_quality_metric_no_app_selection_draws(self):
        from wama.model_manager.services.bench import LPIPS_KEY
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = object.__new__(ModelRegistry)
        registry._models, registry.discovery_errors = {}, []
        registry._discover_quality_metric_models()
        self.assertEqual([], registry.discovery_errors)
        self.assertEqual('quality-metric', registry._models[LPIPS_KEY].capabilities['task'])

    def test_a_missing_backbone_is_installed_by_the_route_and_awaited(self):
        from pathlib import Path
        from wama.model_manager.services import bench
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        bench._LPIPS.clear()
        with mock.patch.object(bench, 'lpips_folder', return_value=folder), \
                mock.patch('wama.common.utils.model_readiness.install_and_wait',
                           return_value=False) as install, \
                mock.patch('torch.hub.load_state_dict_from_url') as hub:
            with self.assertRaisesMessage(RuntimeError, 'pull_model pytorch_download:lpips-alexnet'):
                bench.lpips_metric('cpu')
        self.assertEqual(bench.LPIPS_KEY, install.call_args.args[0])
        hub.assert_not_called()
