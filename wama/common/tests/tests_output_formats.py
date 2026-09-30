"""Output settings — the SHARED post-processing of a render-based app (2026-09-30).

Upscaling moved from the backends (only `DiffusersBackend` honoured it, with a ×2 LANCZOS) to the
app's output settings, applied after ANY backend by `apply_output_settings`. The upscaler is
DRAWN from the catalogue (task `upscale`, capability `scale` = factor), never named.
"""
import os
import tempfile
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.common.utils import output_formats as of
from wama.model_manager.models import AIModel


def _upscaler(key, scale, task='upscale'):
    return AIModel.objects.create(
        model_key=key, name=key, model_type='upscaling', source=key.split(':')[0], vram_gb=0.5,
        is_available=True, is_downloaded=True, is_proposed=False,
        capabilities={'task': task, 'scale': scale},
        composition={'runtime': {'engine': 'onnxruntime'}})


class OutputUpscaleParamTest(SimpleTestCase):

    def test_the_factor_reads_the_shared_vocabulary(self):
        self.assertEqual(4, of.upscale_factor('x4'))
        self.assertEqual(2, of.upscale_factor('X2'))
        self.assertEqual(0, of.upscale_factor(''))
        self.assertEqual(0, of.upscale_factor('huge'))

    def test_the_setting_is_opt_in_and_image_only(self):
        names = lambda params: [p.name for p in params]   # noqa: E731
        self.assertNotIn('output_upscale', names(of.output_format_params('image')))
        self.assertNotIn('output_upscale', names(of.output_format_params('video', include_upscale=True)))
        image = names(of.output_format_params('image', include_upscale=True))
        self.assertEqual('output_upscale', image[0], 'the upscaling comes BEFORE the format')
        self.assertIn('output_upscale', of.OUTPUT_PARAM_NAMES)

    def test_the_imager_offers_it_on_images_only(self):
        from wama.imager.params import IMAGE_PARAMS, VIDEO_PARAMS
        self.assertIn('output_upscale', [p.name for p in IMAGE_PARAMS])
        self.assertNotIn('output_upscale', [p.name for p in VIDEO_PARAMS])
        self.assertNotIn('upscale', [p.name for p in IMAGE_PARAMS], 'the old toggle is gone')

    def test_the_generation_contract_no_longer_carries_upscaling(self):
        from wama.common.backends.diffusers_backend import DiffusersBackend
        from wama.common.backends.image_generation_base import GenerationParams
        self.assertNotIn('upscale', GenerationParams.__dataclass_fields__)
        self.assertFalse(hasattr(DiffusersBackend, '_upscale_image'))


class UpscalerDrawnFromCatalogueTest(TestCase):

    def setUp(self):
        _upscaler('enhancer:up-x2', 2)
        _upscaler('enhancer:up-x4', 4)
        _upscaler('enhancer:denoise-x1', 1, task='denoise')
        fd, self.path = tempfile.mkstemp(suffix='.png')
        os.close(fd)

    def tearDown(self):
        if os.path.exists(self.path):
            os.remove(self.path)

    def test_the_need_filters_before_the_ranking(self):
        from wama.common.utils.auto_model import candidates_with
        self.assertEqual(['enhancer:up-x2'], candidates_with('scale', 2, **of.UPSCALER_SPEC))
        self.assertEqual(['enhancer:up-x4'], candidates_with('scale', '4', **of.UPSCALER_SPEC))
        self.assertEqual([], candidates_with('scale', 8, **of.UPSCALER_SPEC))

    def test_no_upscaler_of_that_factor_is_said_not_skipped(self):
        with self.assertRaises(RuntimeError):
            of.upscale_output_image(self.path, 'x8')

    def test_the_drawn_upscaler_runs_through_its_declared_backend(self):
        seen = {}

        class FakeUpscaler:
            def __init__(self, model_name):
                seen['built'] = model_name

        def fake_run(src, dst, model_name, denoise, progress_callback, factory):
            factory(model_name)
            seen.update(src=src, model=model_name, denoise=denoise)
            open(dst, 'wb').write(b'upscaled')
            return (1024, 1024)

        with mock.patch('wama.common.backends.manager.backend_for_key', return_value=FakeUpscaler), \
                mock.patch('wama.common.backends.ai_upscaler.upscale_image_file', fake_run):
            size = of.upscale_output_image(self.path, 'x4', denoise=True)
        self.assertEqual((1024, 1024), size)
        self.assertEqual({'src': self.path, 'model': 'up-x4', 'denoise': True, 'built': 'up-x4'},
                         seen, 'the catalogue key is handed over as the id the backend knows')
        self.assertEqual(b'upscaled', open(self.path, 'rb').read(), 'replaced IN PLACE')


class ApplyOutputSettingsTest(SimpleTestCase):

    def _item(self, **kw):
        return SimpleNamespace(**{'output_upscale': '', 'output_format': 'original',
                                  'output_quality': 'balanced', **kw})

    def test_upscaling_comes_before_the_conversion(self):
        order = []
        with mock.patch.object(of, 'upscale_output_image',
                               side_effect=lambda p, f, **k: order.append(('up', p, f)) or (1, 1)), \
                mock.patch('wama.converter.utils.inline_convert.apply_inline_conversion',
                           side_effect=lambda p, fmt, q: order.append(('conv', p, fmt)) or p + '.webp'):
            out = of.apply_output_settings(['a.png'], self._item(output_upscale='x2',
                                                                 output_format='webp'),
                                           domain='image')
        self.assertEqual([('up', 'a.png', 2), ('conv', 'a.png', 'webp')], order)
        self.assertEqual(['a.png.webp'], out)

    def test_nothing_asked_changes_nothing(self):
        with mock.patch.object(of, 'upscale_output_image') as up:
            self.assertEqual(['a.png'], of.apply_output_settings(['a.png'], self._item(),
                                                                 domain='image'))
        up.assert_not_called()

    def test_a_video_is_never_upscaled_here(self):
        with mock.patch.object(of, 'upscale_output_image') as up:
            of.apply_output_settings(['a.mp4'], self._item(output_upscale='x2'), domain='video')
        up.assert_not_called()

    def test_a_failed_upscaling_raises_a_failed_conversion_keeps_the_file(self):
        with mock.patch.object(of, 'upscale_output_image', side_effect=RuntimeError('none')):
            with self.assertRaises(RuntimeError):
                of.apply_output_settings(['a.png'], self._item(output_upscale='x4'), domain='image')
        said = []
        with mock.patch('wama.converter.utils.inline_convert.apply_inline_conversion',
                        side_effect=OSError('ffmpeg')):
            out = of.apply_output_settings(['a.png'], self._item(output_format='webp'),
                                           domain='image', console=said.append)
        self.assertEqual(['a.png'], out)
        self.assertTrue(any('webp' in s for s in said), 'the failure is SAID')
