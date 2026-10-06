"""The cheap « during » preview of a diffusion: latents → an APPROXIMATE image, no VAE decode.

Decision of 2026-10-06 (Fabien): no extra VRAM on generations that already need a lot. The
latents of the current step are projected linearly to RGB on the CPU. Here: the factor table
(extracted from ComfyUI, never retyped), the family read from the VAE configuration, every
latent layout the installed pipelines use — the unpacking must give back the EXACT grid — and
the backend entry point, which must never break a generation.
"""
import math
from types import SimpleNamespace

import numpy as np
import torch
from django.test import SimpleTestCase

from wama.common.utils import latent_preview as lp
from wama.common.utils.latent_rgb_factors import LATENT_RGB, UPSTREAM


def _vae(class_name, **config):
    return type(class_name, (), {'config': config})()


def _pack_flux(chw):
    """diffusers convention (Flux, Qwen-Image): [C,H,W] → tokens [(H/2)(W/2), C·4]."""
    c, h, w = chw.shape
    return chw.view(c, h // 2, 2, w // 2, 2).permute(1, 3, 0, 2, 4).reshape((h // 2) * (w // 2), c * 4)


class FactorTableTest(SimpleTestCase):

    def test_every_family_has_three_coefficients_per_channel(self):
        for family, entry in LATENT_RGB.items():
            with self.subTest(family=family):
                self.assertEqual(entry['channels'], len(entry['factors']))
                self.assertTrue(all(len(row) == 3 for row in entry['factors']))
                self.assertEqual(3, len(entry['bias']))

    def test_the_source_is_pinned_and_declared(self):
        self.assertEqual(40, len(UPSTREAM['commit']))
        self.assertEqual('GPL-3.0', UPSTREAM['license'])

    def test_the_families_wama_serves_are_covered(self):
        for family in ('SD15', 'SDXL', 'Flux', 'Flux2', 'Wan21', 'Wan22', 'LTXV', 'QwenImage21'):
            self.assertIn(family, LATENT_RGB)


class FamilyFromVaeTest(SimpleTestCase):

    def test_the_vae_configuration_names_the_family(self):
        cases = {
            ('AutoencoderKL', 4, 0.18215, None): 'SD15',
            ('AutoencoderKL', 4, 0.13025, None): 'SDXL',
            ('AutoencoderKL', 16, 0.3611, 0.1159): 'Flux',
            ('AutoencoderKL', 16, 1.5305, 0.0609): 'SD3',
        }
        for (cls, channels, scaling, shift), family in cases.items():
            with self.subTest(family=family):
                vae = _vae(cls, latent_channels=channels, scaling_factor=scaling, shift_factor=shift)
                self.assertEqual(family, lp.vae_family(vae))
        self.assertEqual('Wan22', lp.vae_family(_vae('AutoencoderKLWan', z_dim=48)))
        self.assertEqual('LTXV', lp.vae_family(_vae('AutoencoderKLLTXVideo', latent_channels=128)))

    def test_an_unknown_vae_has_no_family(self):
        self.assertIsNone(lp.vae_family(_vae('AutoencoderKLCogVideoX', latent_channels=16)))
        self.assertIsNone(lp.vae_family(None))


class LatentLayoutsTest(SimpleTestCase):

    def setUp(self):
        torch.manual_seed(0)

    def test_packed_tokens_give_back_the_exact_grid(self):
        chw = torch.randn(16, 8, 12)
        out = lp._to_chw(_pack_flux(chw), 16, height=8 * 8, width=12 * 8, ratio=8)
        self.assertTrue(torch.equal(chw, out))

    def test_patchified_flux2_channels_are_unfolded_like_upstream(self):
        chw = torch.randn(32, 6, 4)
        # diffusers `_patchify_latents` (Flux2) — the inverse the preview must apply.
        patched = chw.view(32, 3, 2, 2, 2).permute(0, 2, 4, 1, 3).reshape(128, 3, 2)
        self.assertTrue(torch.equal(chw, lp._to_chw(patched, 32)))
        tokens = patched.reshape(128, 6).permute(1, 0)            # Flux2 `_pack_latents`
        self.assertTrue(torch.equal(chw, lp._to_chw(tokens, 32, height=6 * 8, width=4 * 8)))

    def test_a_video_shows_its_last_frame_in_both_axis_orders(self):
        video = torch.randn(16, 5, 4, 4)                           # [C, T, H, W]
        self.assertTrue(torch.equal(video[:, -1], lp._to_chw(video, 16)))
        cog = video.permute(1, 0, 2, 3)                            # [T, C, H, W] (CogVideoX)
        self.assertTrue(torch.equal(video[:, -1], lp._to_chw(cog, 16)))

    def test_packed_video_tokens_show_the_last_frame(self):
        frames = torch.randn(3, 128, 2, 4)                         # LTX: patch 1, T=3
        tokens = frames.permute(0, 2, 3, 1).reshape(3 * 2 * 4, 128)
        out = lp._to_chw(tokens, 128, height=2 * 32, width=4 * 32, ratio=32)
        self.assertTrue(torch.equal(frames[-1], out))

    def test_an_edited_image_finds_its_grid_from_the_proportions(self):
        chw = torch.randn(16, 6, 10)                               # real size unknown to the backend
        out = lp._to_chw(_pack_flux(chw), 16, height=600, width=1000, ratio=8)
        self.assertTrue(torch.equal(chw, out))


class ProjectionTest(SimpleTestCase):

    def test_a_known_family_uses_its_coefficients(self):
        latents = torch.zeros(1, 4, 2, 2)
        latents[0, 0] = 1.0
        image = lp.latents_to_image(latents, 'SD15')
        expected = [round((f + 1) / 2 * 255) for f in LATENT_RGB['SD15']['factors'][0]]
        b, g, r = image[0, 0]
        self.assertTrue(all(math.isclose(a, e, abs_tol=1) for a, e in zip((r, g, b), expected)))

    def test_the_preview_is_a_bgr_image_of_the_published_size(self):
        image = lp.latents_to_image(torch.randn(1, 4, 64, 96), 'SDXL')
        self.assertEqual((np.uint8, 3), (image.dtype, image.shape[2]))
        self.assertEqual(lp.PREVIEW_SIDE, max(image.shape[:2]))

    def test_a_family_without_coefficients_still_shows_its_composition(self):
        image = lp.latents_to_image(torch.randn(1, 16, 3, 8, 8), None, channels=16)
        self.assertIsNotNone(image)
        self.assertGreater(image.std(), 0, 'principal axes: a structured, non uniform image')

    def test_an_unreadable_layout_gives_nothing(self):
        self.assertIsNone(lp.latents_to_image(torch.randn(1, 7, 9), 'Flux', height=64, width=64))
        self.assertIsNone(lp.latents_to_image(None, 'SD15'))


#: Backends with a step callback that do NOT preview yet — the VIDEO ones, next step. The list
#: can only shrink: a new diffusion backend previews from day one.
STILL_TO_PREVIEW = {'cogvideox_backend.py', 'hunyuan_video_backend.py', 'ltx_video_backend.py',
                    'mochi_backend.py', 'wan_video_backend.py'}


class EveryDiffusionCallbackPreviewsTest(SimpleTestCase):

    def test_a_backend_with_a_step_callback_calls_the_preview_hook(self):
        import re
        from pathlib import Path
        from django.conf import settings
        folder = Path(settings.BASE_DIR) / 'wama' / 'common' / 'backends'
        uses_a_callback = re.compile(r'callback_on_step_end\s*=|def callback_on_step_end\b')
        missing, ported = [], []
        for path in sorted(folder.glob('*.py')):
            text = path.read_text(encoding='utf-8')
            if not uses_a_callback.search(text):          # the USE, not a mention in a docstring
                continue
            previews = 'self.preview_step(' in text
            if not previews and path.name not in STILL_TO_PREVIEW:
                missing.append(path.name)
            if previews and path.name in STILL_TO_PREVIEW:
                ported.append(path.name)
        self.assertEqual([], missing, 'call `self.preview_step(pipe, callback_kwargs, …)`')
        self.assertEqual([], ported, 'ported: take it out of STILL_TO_PREVIEW')


class BackendPreviewStepTest(SimpleTestCase):
    """`ImageGenerationBackend.preview_step` — the hook every diffusion callback calls."""

    def _backend(self):
        from wama.common.backends.image_generation_base import ImageGenerationBackend

        class Backend(ImageGenerationBackend):
            name = 'witness'
            is_available = classmethod(lambda cls: True)
            load = generate = unload = lambda self, *a, **k: None
        return Backend()

    def _pipe(self):
        return SimpleNamespace(vae=_vae('AutoencoderKL', latent_channels=4, scaling_factor=0.13025),
                               vae_scale_factor=8)

    def test_without_a_sink_nothing_is_computed(self):
        backend = self._backend()
        backend.preview_step(self._pipe(), {'latents': object()})     # would fail if read

    def test_a_due_sink_receives_the_image_and_a_late_one_nothing(self):
        backend = self._backend()
        received = []
        backend.preview_sink = type('Sink', (), {'due': lambda s: True,
                                                 '__call__': lambda s, img: received.append(img)})()
        backend.preview_step(self._pipe(), {'latents': torch.randn(1, 4, 8, 8)})
        self.assertEqual(1, len(received))
        backend.preview_sink = type('Sink', (), {'due': lambda s: False,
                                                 '__call__': lambda s, img: received.append(img)})()
        backend.preview_step(self._pipe(), {'latents': torch.randn(1, 4, 8, 8)})
        self.assertEqual(1, len(received), 'not due: not even computed')

    def test_a_failing_preview_never_breaks_the_generation(self):
        backend = self._backend()

        class Broken:
            def due(self):
                return True

            def __call__(self, image):
                raise OSError('disk full')
        backend.preview_sink = Broken()
        backend.preview_step(self._pipe(), {'latents': torch.randn(1, 4, 8, 8)})
