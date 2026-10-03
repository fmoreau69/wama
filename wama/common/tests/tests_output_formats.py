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


class KeepTheOriginalTest(SimpleTestCase):
    """`render_outputs` keeps the file the engine wrote next to the rendered one, as long as the
    output settings transform it — so the output can be replayed ALONE, without generating again
    (2026-10-03)."""

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__('shutil').rmtree(self.folder, True))
        self.engine_file = os.path.join(self.folder, 'gen7_model.png')
        with open(self.engine_file, 'wb') as out:
            out.write(b'native')

    def _item(self, **kw):
        values = dict(output_format='original', output_quality='balanced', output_upscale='')
        values.update(kw)
        return SimpleNamespace(**values)

    @staticmethod
    def _convert(path, fmt, preset='balanced', **_kw):
        """Stand-in for the converter : writes the target next to the source, removes the source."""
        target = os.path.splitext(path)[0] + '.' + fmt
        with open(path, 'rb') as src, open(target, 'wb') as out:
            out.write(src.read() + b'>' + fmt.encode())
        if target != path:
            os.remove(path)
        return target

    def _render(self, sources, item, previous=()):
        with mock.patch('wama.converter.utils.inline_convert.apply_inline_conversion',
                        side_effect=self._convert):
            return of.render_outputs(sources, item, domain='image', previous=previous)

    def _names(self):
        return sorted(os.listdir(self.folder))

    def test_names_of_a_kept_original(self):
        self.assertEqual('a/gen7.native.png', of.native_name('a/gen7.png'))
        self.assertEqual('a/gen7.native.png', of.native_name('a/gen7.native.png'))
        self.assertEqual('a/gen7.png', of.final_name('a/gen7.native.png'))
        self.assertTrue(of.is_native('a/gen7.native.png'))
        self.assertFalse(of.is_native('a/gen7.png'))

    def test_without_any_transformation_there_is_a_single_file(self):
        finals, natives = self._render([self.engine_file], self._item())
        self.assertEqual(([self.engine_file], []), (finals, natives))
        self.assertEqual(['gen7_model.png'], self._names())

    def test_a_conversion_keeps_the_original_next_to_the_rendered_file(self):
        finals, natives = self._render([self.engine_file], self._item(output_format='webp'))
        self.assertEqual(['gen7_model.native.png', 'gen7_model.webp'], self._names())
        self.assertEqual([os.path.join(self.folder, 'gen7_model.webp')], finals)
        self.assertEqual([os.path.join(self.folder, 'gen7_model.native.png')], natives)
        with open(natives[0], 'rb') as kept:
            self.assertEqual(b'native', kept.read(), 'the original is never altered')

    def test_the_output_is_replayed_from_the_kept_original_and_drops_the_previous_one(self):
        finals, natives = self._render([self.engine_file], self._item(output_format='webp'))
        again, kept = self._render(natives, self._item(output_format='jpg'), previous=finals)
        self.assertEqual(['gen7_model.jpg', 'gen7_model.native.png'], self._names())
        self.assertEqual(natives, kept)
        with open(again[0], 'rb') as rendered:
            self.assertEqual(b'native>jpg', rendered.read(), 'converted from the ORIGINAL, not from the webp')

    def test_going_back_to_the_original_format_keeps_a_single_file_again(self):
        finals, natives = self._render([self.engine_file], self._item(output_format='webp'))
        back, kept = self._render(natives, self._item(), previous=finals)
        self.assertEqual(([self.engine_file], []), (back, kept))
        self.assertEqual(['gen7_model.png'], self._names())
        with open(self.engine_file, 'rb') as restored:
            self.assertEqual(b'native', restored.read())

    def test_an_upscaling_counts_as_a_transformation_for_images_only(self):
        self.assertTrue(of.transforms_output(self._item(output_upscale='x2'), 'image'))
        self.assertFalse(of.transforms_output(self._item(output_upscale='x2'), 'video'))
        self.assertFalse(of.transforms_output(self._item(), 'image'))

    def test_the_shared_field_is_nullable_and_declared_once(self):
        from wama.common.models import NativeOutputsMixin
        field = NativeOutputsMixin._meta.get_field(of.NATIVE_FIELD)
        self.assertTrue(field.null, 'a new column must not break the inserts of the code in service')

    def test_a_failed_output_leaves_the_file_where_it_came_from(self):
        """Measured on the first real run (2026-10-03) : a failed upscaling left an orphan original."""
        with mock.patch.object(of, 'upscale_output_image', side_effect=RuntimeError('no upscaler')), \
                self.assertRaises(RuntimeError):
            of.render_outputs([self.engine_file], self._item(output_upscale='x2'), domain='image')
        self.assertEqual(['gen7_model.png'], self._names())
        finals, natives = self._render([self.engine_file], self._item(output_format='webp'))
        with mock.patch.object(of, 'upscale_output_image', side_effect=RuntimeError('no upscaler')), \
                self.assertRaises(RuntimeError):
            of.render_outputs(natives, self._item(output_upscale='x2'), domain='image', previous=finals)
        self.assertEqual(['gen7_model.native.png', 'gen7_model.webp'], self._names(),
                         'the previous rendering and its original are untouched')

    def test_the_upscaler_writes_its_temporary_file_next_to_the_output(self):
        """`os.replace` does not cross file systems : the temporary file is born in the output folder."""
        seen = {}

        def upscale(src, dst, **kw):
            seen['folder'] = os.path.dirname(dst)
            with open(dst, 'wb') as out:
                out.write(b'bigger')
            return (2, 2)
        with mock.patch('wama.common.utils.auto_model.candidates_with', return_value=['enhancer:up-x2']), \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice', return_value='enhancer:up-x2'), \
                mock.patch('wama.common.backends.manager.backend_for_key', return_value=object), \
                mock.patch('wama.common.backends.ai_upscaler.upscale_image_file', side_effect=upscale):
            of.upscale_output_image(self.engine_file, 'x2')
        self.assertEqual(os.path.abspath(self.folder), os.path.abspath(seen['folder']))
        self.assertEqual(['gen7_model.png'], self._names())
