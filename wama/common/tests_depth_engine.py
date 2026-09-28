"""Le moteur de profondeur porte PLUSIEURS modèles déclarés — et chacun charge le sien.

Depuis le 2026-09-28 : Depth Pro (métrique déclaré) et ZoeDepth KITTI (échelle à ancrer, défaut
depuis le banc sur les images ENA). Ce qu'on garde : la déclaration est complète, un nom inconnu
ne retombe pas en silence sur un autre modèle, `load` range chaque modèle dans SON dossier
(`cache_dir=`, AGENTS.md), le post-traitement de ZoeDepth reçoit la taille source, chaque backend
au contrat charge le modèle qu'il déclare, et le catalogue connaît les deux.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from wama.common.backends import depth_engine
from wama.common.backends.depth_backend import DepthProBackend, ZoeDepthBackend

KEYS = ('hf_id', 'dir', 'label', 'metric_scale', 'estimates_focal', 'source_sizes', 'fp16_on_cuda')


class DepthModelDeclarationTest(SimpleTestCase):
    def test_each_model_lists_every_key(self):
        for key, spec in depth_engine.DEPTH_MODELS.items():
            self.assertEqual(set(spec), set(KEYS), key)

    def test_the_default_is_declared_and_an_unknown_key_raises(self):
        self.assertIn(depth_engine.DEFAULT_DEPTH_MODEL, depth_engine.DEPTH_MODELS)
        with self.assertRaises(KeyError):
            depth_engine.depth_model_spec('depth-inconnu')

    def test_each_contract_backend_loads_its_own_model(self):
        for cls in (DepthProBackend, ZoeDepthBackend):
            self.assertIn(cls.MODEL_KEY, depth_engine.DEPTH_MODELS)
            self.assertEqual(set(cls.SUPPORTED_MODELS), {cls.MODEL_KEY})

    def test_the_catalogue_knows_every_declared_model(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        reg = ModelRegistry.__new__(ModelRegistry)
        reg._models = {}
        reg._discover_depth_models()
        for key, spec in depth_engine.DEPTH_MODELS.items():
            info = reg._models.get(f'huggingface:{key}')
            self.assertIsNotNone(info, key)
            self.assertEqual(info.hf_id, spec['hf_id'])


class DepthModelLoadingTest(SimpleTestCase):
    def setUp(self):
        depth_engine._MODEL_CACHE.clear()

    def tearDown(self):
        depth_engine._MODEL_CACHE.clear()

    def _load(self, key):
        model = MagicMock()
        model.to.return_value.eval.return_value = model
        with patch('transformers.AutoImageProcessor.from_pretrained') as p, \
             patch('transformers.AutoModelForDepthEstimation.from_pretrained', return_value=model) as m, \
             patch('torch.cuda.is_available', return_value=False):
            depth_engine.load('cpu', model_key=key)
        return p, m

    def test_each_model_is_loaded_from_its_own_folder(self):
        for key, spec in depth_engine.DEPTH_MODELS.items():
            p, m = self._load(key)
            self.assertEqual(p.call_args.args[0], spec['hf_id'])
            self.assertEqual(p.call_args.kwargs['cache_dir'], str(spec['dir']))
            self.assertEqual(m.call_args.kwargs['cache_dir'], str(spec['dir']))

    def test_zoedepth_post_processing_receives_the_source_size(self):
        import numpy as np
        import torch
        processor, model = MagicMock(), MagicMock()
        processor.return_value = {'pixel_values': torch.zeros(1, 3, 4, 4)}
        processor.post_process_depth_estimation.return_value = [{'predicted_depth': torch.ones(6, 8)}]
        model.dtype = torch.float32
        depth_engine._MODEL_CACHE[('Intel/zoedepth-kitti', 'cpu')] = (processor, model)
        with patch('torch.cuda.is_available', return_value=False):
            depth, focal = depth_engine.estimate_depth(np.zeros((6, 8, 3), dtype=np.uint8), 'cpu',
                                                       model_key='zoedepth-kitti')
        kwargs = processor.post_process_depth_estimation.call_args.kwargs
        self.assertEqual(kwargs['source_sizes'], [(6, 8)])
        self.assertIsNone(focal)          # ZoeDepth n'estime pas de focale
        self.assertEqual(depth.shape, (6, 8))
