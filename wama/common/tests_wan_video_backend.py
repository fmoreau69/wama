"""FastWan 2.2 servi par le backend Wan (2026-09-15).

POURQUOI CE FICHIER. FastWan était au catalogue depuis le 02/09 (23 Go sur disque) sans être
sélectionnable : aucune app ne le déclarait, et le backend Wan ne le nommait pas. La sonde du
14/09 (`manage.py probe_fastwan`) a montré que `WanPipeline` accepte ses composants ; le lien a
été posé le 15/09. Ces tests tiennent les DEUX moitiés du lien (déclaration d'app ↔
`SUPPORTED_MODELS`) et le garde-fou mémoire, SANS GPU et sans charger de poids.

⚠ Aucun de ces tests n'atteste qu'une vidéo correcte sort : le pas DMD reste une hypothèse
tant que la première génération GPU n'a pas été jouée.
"""
import importlib.util
from unittest import mock, skipUnless

from django.conf import settings
from django.test import SimpleTestCase

MODEL_ID = 'fastwan-2.2-ti2v-5b'
HAS_TORCH = importlib.util.find_spec('torch') is not None
HAS_DIFFUSERS = HAS_TORCH and importlib.util.find_spec('diffusers') is not None


class FastWanDeclarationTest(SimpleTestCase):

    def test_la_declaration_imager_et_le_backend_designent_le_meme_depot(self):
        from wama.common.backends.wan_video_backend import WanVideoBackend
        from wama.imager.utils.model_config import IMAGER_MODELS, get_video_models
        declaration = IMAGER_MODELS[MODEL_ID]
        self.assertEqual(declaration['hf_id'], WanVideoBackend.SUPPORTED_MODELS[MODEL_ID][1])
        self.assertEqual(declaration['engine'], WanVideoBackend.ENGINE)
        self.assertEqual(declaration['type'], 'video')
        self.assertIn(MODEL_ID, get_video_models())

    def test_le_moteur_diffusers_resout_fastwan_vers_le_backend_wan(self):
        """`diffusers` est piloté par plusieurs backends : sans l'entrée de
        `SUPPORTED_MODELS`, la résolution rendrait None et la tâche vidéo s'arrêterait."""
        from wama.common.services.backend_inventory import resolve_entry
        entry = resolve_entry('diffusers', MODEL_ID)
        self.assertIsNotNone(entry, 'aucun backend résolu pour FastWan')
        self.assertTrue(entry.module.endswith('wan_video_backend'), entry.module)

    def test_le_backend_n_est_plus_declare_deprecie(self):
        from wama.common.backends.wan_video_backend import WanVideoBackend
        self.assertEqual(WanVideoBackend.DEPRECATED, '')

    def test_backend_imager_et_MODEL_PATHS_lisent_le_meme_dossier(self):
        from wama.common.backends.wan_video_backend import WanVideoBackend
        from wama.imager.utils.model_config import get_model_info
        declared = str(settings.MODEL_PATHS['diffusion']['fastwan'])
        self.assertEqual(WanVideoBackend.cache_dir_for(MODEL_ID), declared)
        self.assertEqual(get_model_info(MODEL_ID)['cache_dir'], declared)

    def test_la_famille_declaree_sort_du_balayage_generique(self):
        """Sinon FastWan aurait DEUX lignes de catalogue : `imager:` et `huggingface:`."""
        from pathlib import Path
        from wama.model_manager.services.model_registry import ModelRegistry
        self.assertIn(Path(settings.MODEL_PATHS['diffusion']['fastwan']).resolve(),
                      ModelRegistry._familles_model_paths())

    def test_la_decouverte_imager_porte_fastwan_en_texte_vers_video(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = object.__new__(ModelRegistry)      # hors singleton, sans `__init__`
        registry._models = {}
        registry.discovery_errors = []
        registry._discover_imager_models()
        info = registry._models.get(f'imager:{MODEL_ID}')
        self.assertIsNotNone(info, 'FastWan absent de la découverte imager')
        self.assertEqual(info.capabilities['modalities'], ['video'])
        self.assertEqual(info.capabilities['task'], 'text-to-video')


class FastWanMemoryTest(SimpleTestCase):

    def _strategy(self, preset):
        from wama.model_manager.services.memory_manager import MemoryManager
        with mock.patch.object(MemoryManager, 'get_gpu_memory_info',
                               return_value={'total_gb': 24.0, 'free_gb': 23.5}):
            return MemoryManager.get_strategy_for_model(preset, headroom_gb=4.0)

    def test_sur_24_Go_fastwan_passe_en_dechargement_et_non_en_plein_GPU(self):
        """Le défaut évité : sous le preset `wan-t2v` (14 Go), ~23 Go de poids tentaient
        FULL_GPU — un débordement WDDM, donc un risque de crash hôte."""
        from wama.common.backends.wan_video_backend import WanVideoBackend
        from wama.model_manager.services.memory_manager import MemoryStrategy
        preset = WanVideoBackend.MODEL_PROFILES[MODEL_ID]['memory_preset']
        self.assertEqual(self._strategy(preset), MemoryStrategy.MODEL_OFFLOAD)
        self.assertEqual(self._strategy('wan-t2v'), MemoryStrategy.FULL_GPU,
                         'contre-épreuve : le preset Wan 2.2 aurait tenté le plein GPU')

    def test_le_preset_et_la_declaration_ne_se_contredisent_pas(self):
        from wama.imager.utils.model_config import VRAM_DRIFT
        self.assertNotIn(MODEL_ID, VRAM_DRIFT)


class FastWanImageToVideoTest(SimpleTestCase):
    """TI2V : les DEUX métiers, par le MÊME dépôt (mesuré le 2026-09-16)."""

    def test_l_image_vers_video_passe_par_le_depot_du_modele_et_non_par_le_A14B(self):
        """Le défaut évité : la constante en dur envoyait tout modèle vers
        `Wan2.2-I2V-A14B`, absent du disque — soit ~25 Go téléchargés en pleine tâche."""
        from wama.common.backends.wan_video_backend import WanVideoBackend
        self.assertEqual(WanVideoBackend.i2v_model_id(MODEL_ID),
                         WanVideoBackend.SUPPORTED_MODELS[MODEL_ID][1])
        self.assertIn('A14B', WanVideoBackend.i2v_model_id('wan-t2v-14b'),
                      'un Wan 2.2 officiel garde son dépôt I2V dédié')

    def test_les_deux_metiers_sont_declares_et_l_image_est_une_entree_optionnelle(self):
        from wama.imager.utils.model_config import IMAGER_MODELS
        from wama.common.utils.model_capabilities import derive_inputs_from_tasks
        self.assertEqual(IMAGER_MODELS[MODEL_ID]['tasks'], 't2v+i2v')
        derived = derive_inputs_from_tasks('t2v+i2v', is_video=True)
        self.assertEqual(derived['task'], 'text-to-video')
        self.assertIn('work_image', derived['inputs_optional'],
                      "l'image de départ doit être proposée, jamais exigée")

    def test_le_conditionnement_par_image_est_celui_que_le_depot_declare(self):
        """`expand_timesteps=True` EST la condition : sans lui, diffusers attendrait des
        canaux d'entrée supplémentaires que ce transformer n'a pas (48 pour 48 latents)."""
        import json
        from pathlib import Path
        from wama.common.backends.wan_video_backend import WanVideoBackend
        hf_id = WanVideoBackend.SUPPORTED_MODELS[MODEL_ID][1]
        root = (Path(WanVideoBackend.cache_dir_for(MODEL_ID))
                / f"models--{hf_id.replace('/', '--')}")
        snapshots = sorted((root / 'snapshots').glob('*'))
        if not snapshots:
            self.skipTest('snapshot FastWan absent de cet hôte')
        try:
            texte = (snapshots[-1] / 'model_index.json').read_text(encoding='utf-8')
        except OSError:
            # Les poids ont été posés depuis WSL2 : le dossier se LISTE depuis Windows, mais
            # le fichier ne s'y ouvre pas (`OSError 22`). Ce contrôle s'exécute donc sous
            # venv_linux — mesuré vert le 2026-09-16 ; ici il se déclare ignoré plutôt que
            # de passer à vide.
            self.skipTest('snapshot illisible depuis cet hôte (déposé par WSL2)')
        self.assertTrue(json.loads(texte).get('expand_timesteps'))


@skipUnless(HAS_TORCH, 'torch absent de ce venv')
class DMDStepTest(SimpleTestCase):

    def test_le_pas_final_retrouve_x0_et_le_pas_intermediaire_rebruite(self):
        import torch
        from wama.common.backends.wan_video_backend import dmd_step
        g = torch.Generator().manual_seed(0)
        x0 = torch.randn(1, 4, 2, 8, 8, generator=g)
        noise = torch.randn(x0.shape, generator=g)
        x_t = (1 - 0.757) * x0 + 0.757 * noise
        velocity = noise - x0
        self.assertTrue(torch.allclose(dmd_step(velocity, x_t, 757, None), x0, atol=1e-5))
        fresh = torch.randn(x0.shape, generator=g)
        self.assertTrue(torch.allclose(dmd_step(velocity, x_t, 757, 522, fresh),
                                       0.478 * x0 + 0.522 * fresh, atol=1e-5))

    @skipUnless(HAS_DIFFUSERS, 'diffusers absent de ce venv')
    def test_le_scheduler_impose_ses_trois_pas_quel_que_soit_le_nombre_demande(self):
        from wama.common.backends.wan_video_backend import (
            FASTWAN_DMD_TIMESTEPS, make_dmd_scheduler)
        scheduler = make_dmd_scheduler()
        scheduler.set_timesteps(50)
        self.assertEqual([int(t) for t in scheduler.timesteps], list(FASTWAN_DMD_TIMESTEPS))
        self.assertEqual(scheduler.config.num_train_timesteps, 1000)


class VaeTilingCallTest(SimpleTestCase):
    """VAE tiling is enabled ON THE VAE, never through the pipeline shortcut.

    `pipe.enable_vae_tiling()` only exists on image pipelines (`StableDiffusionMixin`); video
    pipelines (Wan, Mochi) do not inherit it, the call raised, and the failure was logged at
    DEBUG. Measured on 2026-09-23 (generation #48, FastWan): 69 min of untiled VAE decoding for
    2.5 min of denoising. Scanned on every backend so that the next one does not repeat it.
    """

    def test_no_backend_calls_the_pipeline_shortcut(self):
        import ast
        from pathlib import Path
        offenders, scanned = [], 0
        for path in sorted((Path(settings.BASE_DIR) / 'wama' / 'common' / 'backends').rglob('*.py')):
            if 'vendor' in path.parts:
                continue
            scanned += 1
            tree = ast.parse(path.read_text(encoding='utf-8'))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                        and node.func.attr in ('enable_vae_tiling', 'enable_vae_slicing')):
                    offenders.append(f'{path.name}:{node.lineno}')
        self.assertGreater(scanned, 10, 'the scan must see the backends, or it proves nothing')
        self.assertEqual(offenders, [], 'call `pipe.vae.enable_tiling()` / `enable_slicing()`')


class SharedPipelineHooksTest(SimpleTestCase):
    """Text→video and image→video share their modules (TI2V, `from_pipe`): the offload hooks
    belong to ONE pipeline at a time, the other re-applies them before serving — without that
    it would run on CPU (modules never moved back to the GPU)."""

    def _backend(self):
        from wama.common.backends.wan_video_backend import WanVideoBackend
        backend = WanVideoBackend()
        backend._pipe_t2v, backend._pipe_i2v = object(), object()
        backend._device = 'cuda'
        backend._shared_components, backend._hooks_owner = True, 'i2v'
        return backend

    def test_switching_pipeline_reapplies_the_memory_strategy(self):
        backend = self._backend()
        with mock.patch('wama.model_manager.services.memory_manager.MemoryManager'
                        '.apply_strategy_for_model') as apply:
            backend._rehook('t2v', 'fastwan-2.2-ti2v-5b')
            backend._rehook('t2v', 'fastwan-2.2-ti2v-5b')
        self.assertEqual(1, apply.call_count, 'once per switch, not on every call')
        self.assertIs(backend._pipe_t2v, apply.call_args.kwargs['pipeline'])
        self.assertEqual('t2v', backend._hooks_owner)

    def test_unshared_pipelines_never_rehook(self):
        backend = self._backend()
        backend._shared_components = False
        with mock.patch('wama.model_manager.services.memory_manager.MemoryManager'
                        '.apply_strategy_for_model') as apply:
            backend._rehook('t2v', 'fastwan-2.2-ti2v-5b')
        apply.assert_not_called()


@skipUnless(HAS_DIFFUSERS, 'diffusers absent de ce venv')
class SharedPipelineDtypeTest(SimpleTestCase):
    """`from_pipe` defaults to `torch_dtype=float32` and converts the SHARED modules in place:
    23 GB of bf16 weights became 46 GB of fp32 and the GPU worker was OOM-killed (2026-09-23,
    first 15 s video). The i2v pipeline must be derived WITHOUT a dtype conversion."""

    def test_the_image_to_video_pipeline_is_derived_without_dtype_conversion(self):
        from wama.common.backends.wan_video_backend import WanVideoBackend
        backend = WanVideoBackend()
        backend._pipe_t2v = object()
        backend._device = 'cuda'
        backend._current_model = WanVideoBackend.i2v_model_id('fastwan-2.2-ti2v-5b')
        with mock.patch('diffusers.WanImageToVideoPipeline') as pipeline, \
                mock.patch('wama.model_manager.services.memory_manager.MemoryManager'
                           '.apply_strategy_for_model', side_effect=lambda **kw: kw['pipeline']):
            self.assertTrue(backend._load_i2v_pipeline('fastwan-2.2-ti2v-5b'))
        pipeline.from_pretrained.assert_not_called()
        self.assertIsNone(pipeline.from_pipe.call_args.kwargs['torch_dtype'])


@skipUnless(HAS_DIFFUSERS, 'diffusers absent de ce venv')
class LtxContinuationConditionTest(SimpleTestCase):
    """The LTX continuation conditions on a VIDEO at frame 0, trimmed to 8k+1 frames (the
    temporal VAE constraint `LTXConditionPipeline` enforces)."""

    def test_the_condition_is_a_video_of_8k_plus_1_frames(self):
        from PIL import Image
        from wama.common.backends.ltx_video_backend import LTXVideoBackend
        frames = [Image.new('RGB', (64, 64), (i, 0, 0)) for i in range(27)]
        [condition] = LTXVideoBackend()._build_continuation_conditions(frames, 32, 32)
        self.assertEqual(0, condition.frame_index)
        self.assertEqual(25, len(condition.video))
        self.assertEqual(2, condition.video[0].getpixel((0, 0))[0], 'the LAST 25 are kept')
        self.assertEqual((32, 32), condition.video[0].size)


class VaeMemorySavingsTest(SimpleTestCase):
    """The VAE decode is cut in SPACE and in TIME (2026-09-24): LTX tiled spatially only, and
    generation #275 decoded its 233 frames in one block — 24.6 GiB requested, OOM at 85 %."""

    def test_framewise_decoding_is_set_wherever_the_vae_knows_it(self):
        from types import SimpleNamespace

        from wama.common.backends.image_generation_base import enable_vae_memory_savings
        calls = []
        vae = SimpleNamespace(enable_tiling=lambda: calls.append('tiling'),
                              enable_slicing=lambda: calls.append('slicing'),
                              use_framewise_decoding=False, use_framewise_encoding=False)
        done = enable_vae_memory_savings(SimpleNamespace(vae=vae), 'test')
        self.assertEqual(['slicing', 'tiling'], calls)
        self.assertTrue(vae.use_framewise_decoding and vae.use_framewise_encoding)
        self.assertIn('framewise_decoding', done)

    def test_a_vae_without_temporal_tiling_is_left_alone(self):
        from types import SimpleNamespace

        from wama.common.backends.image_generation_base import enable_vae_memory_savings
        vae = SimpleNamespace(enable_tiling=lambda: None)
        self.assertEqual(['tiling'], enable_vae_memory_savings(SimpleNamespace(vae=vae), 'test'))
        self.assertFalse(hasattr(vae, 'use_framewise_decoding'))
