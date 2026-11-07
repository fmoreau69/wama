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


class _MeanAbsMetric:
    """Stands for the metric backend (`quality-metric` contract) : a distance, lower is better."""
    direction = 'lower'

    def score(self, image, reference):
        return float(np.abs(image.astype(np.float64) - reference.astype(np.float64)).mean())


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
                mock.patch.object(bench, '_quality_metric', return_value=_MeanAbsMetric()), \
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
        with mock.patch.object(bench, 'lpips_folder', return_value=folder), \
                mock.patch('wama.common.utils.model_readiness.install_and_wait',
                           return_value=False) as install, \
                mock.patch('torch.hub.load_state_dict_from_url') as hub:
            with self.assertRaisesMessage(RuntimeError, 'pull_model pytorch_download:lpips-alexnet'):
                bench._quality_metric()
        self.assertEqual(bench.LPIPS_KEY, install.call_args.args[0])
        hub.assert_not_called()


class LpipsThroughTheCommonContractTest(TestCase):
    """2026-11-07 : the bench loaded LPIPS itself (`lpips_metric`, a module dict per device, on the
    GPU), outside the launch gate, the governor's envelope and the common unloading (`loaded_by`).
    It is now the backend of the `quality-metric` contract, reached through the common gate."""

    def setUp(self):
        from wama.model_manager.models import AIModel
        from wama.model_manager.services.bench import LPIPS_KEY
        self.key = LPIPS_KEY
        AIModel.objects.create(model_key=LPIPS_KEY, name='lpips', model_type='vision',
                               source='pytorch_download', is_downloaded=True,
                               capabilities={'task': 'quality-metric'},
                               composition={'runtime': {'engine': 'lpips'}})

    def test_the_line_resolves_its_backend_of_the_contract(self):
        from wama.common.backends.lpips_backend import LPIPSBackend
        from wama.common.backends.manager import _work_method, backend_for_key
        self.assertIs(LPIPSBackend, backend_for_key(self.key))
        self.assertEqual('score', _work_method(LPIPSBackend))
        self.assertIn(LPIPSBackend.direction, ('lower', 'higher'))

    def test_the_bench_gets_its_metric_from_the_common_gate(self):
        from pathlib import Path
        from wama.common.backends.lpips_backend import LPIPSBackend
        from wama.model_manager.services import bench
        folder = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, folder, True)
        (folder / bench.LPIPS_WEIGHTS).write_bytes(b'')
        with mock.patch.object(bench, 'lpips_folder', return_value=folder), \
                mock.patch.object(LPIPSBackend, 'load', return_value=True) as load:
            first, second = bench._quality_metric(), bench._quality_metric()
        self.assertIsInstance(first, LPIPSBackend)
        self.assertIs(first, second, 'kept loaded by the common cache')
        load.assert_called_with(self.key)

    def test_the_manifest_requires_the_libraries_of_its_backend(self):
        from wama.common.manifests.builtin.model import _requires_librairies
        body = {'composition': {'runtime': {'engine': 'lpips'}},
                'capabilities': {'task': 'quality-metric'}}
        self.assertEqual(['lpips', 'torch'],
                         [r['key'] for r in _requires_librairies(body, self.key)])

    def test_the_discovery_retracts_the_loader_it_used_to_name(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        from wama.model_manager.services.model_sync import merged_composition
        registry = object.__new__(ModelRegistry)
        registry._models, registry.discovery_errors = {}, []
        registry._discover_quality_metric_models()
        prior = {'runtime': {'engine': 'lpips', 'loaded_by': 'wama.model_manager.services.bench'}}
        self.assertEqual({'runtime': {'engine': 'lpips'}},
                         merged_composition(prior, registry._models[self.key].composition))

    def test_the_literal_list_is_the_key_the_bench_names(self):
        from wama.common.backends.lpips_backend import LPIPSBackend
        from wama.common.utils.model_keys import backend_model_id
        self.assertEqual({backend_model_id(self.key): {'model_key': self.key}},
                         LPIPSBackend.SUPPORTED_MODELS)


FAKE_METRIC = '''
import numpy as np
from .quality_metric_base import QualityMetricBackend


class FakeMetric(QualityMetricBackend):
    direction = __DIRECTION__

    def load(self, model=None):
        self._loaded = True
        return True

    def unload(self):
        self._loaded = False

    def score(self, image, reference):
        return float(np.abs(image.astype(np.float64) - reference.astype(np.float64)).mean())
'''


class QualityMetricSmokeTest(TestCase):
    """The contract's trial (`backend_proposals.SMOKES`) : a metric proposed by the `backend` role
    must rate an intact image better than a noisy one, in the direction it declares."""

    def _smoke(self, direction):
        from wama.common.services.backend_proposals import SMOKES
        return SMOKES['QualityMetricBackend'](
            FAKE_METRIC.replace('__DIRECTION__', repr(direction)), module='fake_metric_backend',
            model_key='huggingface:org/fake-metric', out_dir=None)

    def test_a_distance_declared_lower_passes(self):
        out = self._smoke('lower')
        self.assertTrue(out['ok'], out)

    def test_a_distance_declared_higher_or_undeclared_fails(self):
        self.assertIn("n'est pas mieux notée", self._smoke('higher')['error'])
        self.assertIn('hors contrat', self._smoke('')['error'])
