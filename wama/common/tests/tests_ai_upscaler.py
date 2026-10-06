"""`AIUpscaler` serves upscalers INSTALLED by the prospection chain, not only its bundled ONNX files.

Lived on 2026-10-06 (Swin2SR, `onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX`): the
model reached the catalogue with `task: upscale`, `scale: 4` and the `onnxruntime` engine — so the
common output upscale (`output_formats.upscale_output_image`, six apps) could DRAW it — while
`onnxruntime` is shared with Supra2-IMG: without a `SUPPORTED_MODELS` entry its backend resolved
to None (« aucun backend résolu »).

The entry NAMES the model and designates its catalogue row (`model_key`, the field of
`pyannote_diarizer`) — nothing else: its factor, VRAM and file are read from the REGISTRY. The
bundled seven keep their facts in the backend because they run without a database (converter,
the enhancer's help fallback); an installed model only exists through its row.

The weights are not versioned: the end-to-end test builds a tiny ×4 ONNX graph and goes through
the real path (catalogue row → component → onnxruntime session on CPU → tiling).
"""
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import numpy as np
from django.test import TestCase

from wama.common.backends import ai_upscaler
from wama.common.utils import onnx_utils

SWIN2SR = 'onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX'
SWIN2SR_KEY = f'huggingface:{SWIN2SR}'


def _tiny_x4_graph(path: Path):
    """A ×4 nearest-neighbour upscaler with the I/O contract of the bundled models
    (RGB in [0, 1], NCHW, float32, any height and width)."""
    import onnx
    from onnx import TensorProto, helper
    scales = helper.make_tensor('scales', TensorProto.FLOAT, [4], [1.0, 1.0, 4.0, 4.0])
    node = helper.make_node('Resize', ['input', '', 'scales'], ['output'], mode='nearest')
    graph = helper.make_graph(
        [node], 'tiny_x4',
        [helper.make_tensor_value_info('input', TensorProto.FLOAT, [1, 3, 'h', 'w'])],
        [helper.make_tensor_value_info('output', TensorProto.FLOAT, [1, 3, 'H', 'W'])],
        initializer=[scales])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid('', 13)])
    model.ir_version = 8
    onnx.save(model, str(path))


def _cpu_providers(device_id=0, cpu_only=False, _original=onnx_utils.onnx_providers):
    return _original(device_id, cpu_only=True)


def _catalogue_row(**caps):
    from wama.model_manager.models import AIModel
    return AIModel.objects.create(
        model_key=SWIN2SR_KEY, name='swin2SR', model_type='upscaling', source='huggingface',
        is_downloaded=True, vram_gb=0.1, capabilities={'task': 'upscale', **caps},
        composition={'runtime': {'engine': 'onnxruntime'},
                     'components': [{'role': 'model', 'pattern': 'onnx/model.onnx'}]})


class CatalogueUpscalerTest(TestCase):

    def test_an_installed_upscaler_runs_from_its_catalogue_row(self):
        _catalogue_row(scale=4)
        with TemporaryDirectory() as d:
            graph = Path(d) / 'model.onnx'
            _tiny_x4_graph(graph)
            with mock.patch('wama.common.utils.model_components.component_paths',
                            return_value={'model': graph}) as paths, \
                    mock.patch('wama.common.utils.onnx_utils.onnx_providers', new=_cpu_providers):
                upscaler = ai_upscaler.AIUpscaler(model_name=SWIN2SR)
                image = (np.arange(40 * 24 * 3) % 255).astype(np.uint8).reshape(24, 40, 3)
                out = upscaler.upscale_image(image)
                upscaler.close()
        paths.assert_called_once_with(SWIN2SR_KEY)
        self.assertEqual((4, 0.1), (upscaler.scale_factor, upscaler.model_info['vram_usage']),
                         'factor and VRAM come from the registry row')
        self.assertEqual(str(graph), upscaler.model_path)
        self.assertEqual((96, 160, 3), out.shape, 'a non-square input comes out ×4 on both axes')
        self.assertTrue(np.array_equal(image[5, 7], out[5 * 4, 7 * 4]),
                        'colours and axes preserved (nearest neighbour)')

    def test_a_row_without_scale_is_said_not_guessed(self):
        _catalogue_row()
        with self.assertRaises(ValueError) as said:
            ai_upscaler.AIUpscaler(model_name=SWIN2SR)
        self.assertIn('scale', str(said.exception))

    def test_a_missing_row_or_component_is_said(self):
        from wama.common.utils.model_components import ComponentsUnavailable
        with self.assertRaises(ComponentsUnavailable):
            ai_upscaler.AIUpscaler(model_name=SWIN2SR)        # no catalogue row
        _catalogue_row(scale=4)
        with mock.patch('wama.common.utils.model_components.component_paths',
                        side_effect=ComponentsUnavailable('poids introuvables')):
            with self.assertRaises(ComponentsUnavailable):
                ai_upscaler.AIUpscaler(model_name=SWIN2SR)

    def test_an_installed_entry_carries_no_second_truth(self):
        """Bundled: `file` + its facts (they run without a database). Installed: `model_key`
        ONLY — its key is the identifier `backend_for_model` compares."""
        from wama.common.utils.model_keys import model_id
        for name, info in ai_upscaler.SUPPORTED_MODELS.items():
            with self.subTest(model=name):
                if info.get('file'):
                    self.assertIn('scale', info)
                else:
                    self.assertEqual({'model_key'}, set(info))
                    self.assertEqual(name, model_id(info['model_key']))

    def test_the_installed_upscaler_resolves_aiupscaler_beside_supra2(self):
        """The catalogue row as « Valider » left it: engine `onnxruntime`, shared with Supra2-IMG."""
        from wama.common.backends.manager import backend_for_model
        upscaler = SimpleNamespace(model_key=SWIN2SR_KEY,
                                   composition={'runtime': {'engine': 'onnxruntime'}},
                                   capabilities={'task': 'upscale', 'scale': 4})
        self.assertEqual('AIUpscaler', backend_for_model(upscaler).__name__)
        # Counter-case: the other onnxruntime model keeps its own backend.
        supra2 = SimpleNamespace(model_key='huggingface:Bartholomheow/Supra2-IMG-ONNX',
                                 composition={'runtime': {'engine': 'onnxruntime'}},
                                 capabilities={'task': 'text-to-image'})
        self.assertNotEqual('AIUpscaler', backend_for_model(supra2).__name__)
