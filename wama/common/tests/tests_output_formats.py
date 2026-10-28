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
from wama.common.tests.helpers import INLINE_CONVERSION, stand_in_conversion


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
                mock.patch(INLINE_CONVERSION,
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
        with mock.patch(INLINE_CONVERSION,
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

    _convert = staticmethod(stand_in_conversion)

    def _render(self, sources, item, previous=()):
        with mock.patch(INLINE_CONVERSION,
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

    def test_the_app_transformation_then_the_common_settings_from_one_kept_original(self):
        """`then_settings` (2026-10-28, the avatarizer : face, then format) — one process, one
        original; the common settings also hold when the app's own transformation does not."""
        def face(copy):
            with open(copy, 'ab') as out:
                out.write(b'+face')
            return copy
        with mock.patch(INLINE_CONVERSION, side_effect=self._convert):
            finals, natives = of.render_outputs([self.engine_file], self._item(output_format='webp'),
                                                domain='image', transform=True, apply=face,
                                                then_settings=True)
        with open(finals[0], 'rb') as rendered:
            self.assertEqual(b'native+face>webp', rendered.read())
        self.assertEqual(['gen7_model.native.png', 'gen7_model.webp'], self._names())
        with mock.patch(INLINE_CONVERSION, side_effect=self._convert):
            again, kept = of.render_outputs(natives, self._item(output_format='jpg'), domain='image',
                                            transform=False, apply=face, then_settings=True,
                                            previous=finals)
        with open(again[0], 'rb') as rendered:
            self.assertEqual(b'native>jpg', rendered.read(), 'no face asked : the format alone')
        back, kept = of.render_outputs(kept, self._item(), domain='image', transform=False,
                                       apply=face, then_settings=True, previous=again)
        self.assertEqual(([self.engine_file], []), (back, kept), 'nothing asked : one file again')

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


class KeepTheInputSizeTest(SimpleTestCase):
    """« Garder la résolution d'origine » (`output_keep_size`, 2026-10-16) — la sortie revient aux
    dimensions de l'ENTRÉE par le VRAI converter (aucune conversion simulée ici : c'est son moteur
    vidéo qui a appris `resize_w`/`resize_h`), et l'original gardé laisse décocher sans regénérer."""

    def setUp(self):
        import shutil
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder, True)

    def _image(self, name='enhanced.jpg', size=(80, 60)):
        from PIL import Image
        path = os.path.join(self.folder, name)
        Image.new('RGB', size, (30, 120, 200)).save(path)
        return path

    def _video(self, size=(64, 48)):
        import cv2
        import numpy as np
        path = os.path.join(self.folder, 'enhanced.mp4')
        writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*'mp4v'), 5, size)
        for k in range(5):
            writer.write(np.full((size[1], size[0], 3), 40 * k, dtype=np.uint8))
        writer.release()
        return path

    def _item(self, **kw):
        return SimpleNamespace(**{'output_upscale': '', 'output_format': 'original',
                                  'output_quality': 'balanced', 'output_keep_size': True, **kw})

    def _size(self, path):
        from wama.common.utils.video_utils import get_media_info
        info = get_media_info(path)
        return info['width'], info['height']

    def test_an_image_comes_back_to_the_input_size_in_its_own_format(self):
        out = of.apply_output_settings([self._image()], self._item(), domain='image',
                                       input_size=(20, 15))
        self.assertEqual('.jpg', os.path.splitext(out[0])[1])
        self.assertEqual((20, 15), self._size(out[0]))

    def test_the_size_and_the_format_are_applied_together(self):
        out = of.apply_output_settings([self._image()], self._item(output_format='png'),
                                       domain='image', input_size=lambda item: (20, 15))
        self.assertEqual('.png', os.path.splitext(out[0])[1])
        self.assertEqual((20, 15), self._size(out[0]))

    def test_a_video_comes_back_to_the_input_size(self):
        out = of.apply_output_settings([self._video()], self._item(), domain='video',
                                       input_size=(32, 24))
        self.assertEqual((32, 24), self._size(out[0]))

    def test_unchecked_or_without_an_input_size_or_for_audio_nothing_changes(self):
        image = self._image()
        for item, domain, size in ((self._item(output_keep_size=False), 'image', (20, 15)),
                                   (self._item(), 'image', None),
                                   (self._item(), 'audio', (20, 15))):
            with self.subTest(domain=domain, size=size):
                self.assertEqual([image], of.apply_output_settings([image], item, domain=domain,
                                                                   input_size=size))
                self.assertFalse(of.transforms_output(item, domain, input_size=size))
        self.assertEqual((80, 60), self._size(image))

    def test_a_size_the_converter_could_not_reach_is_an_error_not_a_silence(self):
        with mock.patch(INLINE_CONVERSION, side_effect=lambda p, fmt, q, extra_options=None: p), \
                self.assertRaisesRegex(RuntimeError, '20×15'):
            of.apply_output_settings([self._image()], self._item(), domain='image',
                                     input_size=(20, 15))

    def test_the_enhanced_original_is_kept_and_unchecking_brings_it_back(self):
        """Décocher ne relance pas l'amélioration : la sortie repart de l'original gardé."""
        engine_file = self._image('gen.png')
        finals, natives = of.render_outputs([engine_file], self._item(), domain='image',
                                            input_size=(20, 15))
        self.assertEqual((20, 15), self._size(finals[0]))
        self.assertEqual((80, 60), self._size(natives[0]))
        back, kept = of.render_outputs(natives, self._item(output_keep_size=False), domain='image',
                                       previous=finals, input_size=(20, 15))
        self.assertEqual(([engine_file], []), (back, kept))
        self.assertEqual((80, 60), self._size(engine_file))

    def test_the_setting_stales_the_output_process_and_only_where_it_is_offered(self):
        # Le changer périme le process « Sortie », pas la génération ; une app qui ne l'offre pas
        # ne le surveille pas (il n'entre pas dans les réglages de sortie de TOUTES les apps).
        from wama.common.services.output_process import OUTPUT_KEY
        param = of.keep_size_param()
        self.assertEqual(('output_keep_size', 'toggle', False, (OUTPUT_KEY,)),
                         (param.name, param.type, param.default, tuple(param.stales)))
        self.assertNotIn('output_keep_size', of.OUTPUT_PARAM_NAMES)


def _output_schemas():
    """Every settings schema of an app that renders a file and offers its output settings — read
    from the apps themselves, never listed by hand beyond the import paths."""
    from wama.anonymizer.params import PARAMS_JSON as anonymizer
    from wama.composer.params import PARAMS_JSON as composer
    from wama.enhancer.params import AUDIO_PARAMS_JSON, MEDIA_PARAMS_JSON
    from wama.imager.params import IMAGE_PARAMS_JSON, VIDEO_PARAMS_JSON
    from wama.synthesizer.params import PARAMS_JSON as synthesizer
    return {'anonymizer': anonymizer, 'composer': composer, 'enhancer.image_video': MEDIA_PARAMS_JSON,
            'enhancer.audio': AUDIO_PARAMS_JSON, 'imager.image': IMAGE_PARAMS_JSON,
            'imager.video': VIDEO_PARAMS_JSON, 'synthesizer': synthesizer}


class OneOutputRuleTest(SimpleTestCase):
    """ONE format list, ONE quality vocabulary, ONE display rule, for every app that renders a
    file (2026-10-28, step 1 of the settings alignment). The enhancer and the anonymizer copied
    their image + video union, showed the quality under « Original », and the anonymizer's panel
    wrote a third list by hand; the quality spoke « Web (léger) / Maximum » here and « Rapide (web)
    / Qualité » in the converter that applies it."""

    @staticmethod
    def _by_name(schema):
        return {p['name']: p for p in schema}

    @staticmethod
    def _values(param):
        if param.get('option_groups'):
            return [v for _, choices in param['option_groups'] for v, _ in choices]
        return [v for v, _ in param.get('choices') or []]

    def test_the_quality_speaks_the_words_of_the_table_that_applies_it(self):
        from wama.converter.utils.quality_presets import PRESET_CHOICES, PRESET_LABELS
        self.assertEqual([(k, PRESET_LABELS[k]) for k in PRESET_CHOICES], of.OUTPUT_QUALITY_CHOICES)
        for app, schema in _output_schemas().items():
            with self.subTest(app=app):
                quality = self._by_name(schema)['output_quality']
                self.assertEqual([list(c) for c in of.OUTPUT_QUALITY_CHOICES],
                                 [list(c) for c in quality['choices']])
                self.assertEqual(of.DEFAULT_PRESET, quality['default'])

    def test_the_quality_shows_only_when_the_file_is_re_encoded(self):
        from wama.common.utils.param_schema import _show_if_met
        for app, schema in _output_schemas().items():
            params = self._by_name(schema)
            quality, formats = params['output_quality'], self._values(params['output_format'])
            converted = [v for v in formats if v != of.ORIGINAL]
            with self.subTest(app=app):
                self.assertFalse(_show_if_met(quality['show_if'],
                                              {'output_format': of.ORIGINAL,
                                               'output_keep_size': False}),
                                 'hidden under « Original »')
                for value in converted:
                    self.assertTrue(_show_if_met(quality['show_if'], {'output_format': value}),
                                    f'shown for {value}')
                if 'output_keep_size' in params:
                    self.assertTrue(_show_if_met(quality['show_if'],
                                                 {'output_format': of.ORIGINAL,
                                                  'output_keep_size': True}),
                                    'shown when the input size is kept : the file is re-encoded')

    def test_an_app_of_two_natures_offers_exactly_the_formats_of_each(self):
        expected = {v for nature in ('image', 'video') for v, _ in of.get_output_formats(nature)}
        for app in ('anonymizer', 'enhancer.image_video'):
            with self.subTest(app=app):
                offered = set(self._values(self._by_name(_output_schemas()[app])['output_format']))
                self.assertEqual(set(), expected - offered, 'a format of the brick is missing')
                self.assertEqual({'input'} if app == 'anonymizer' else set(), offered - expected,
                                 'only the DECLARED specific choices are added')

    def test_the_rule_reads_the_same_on_an_element(self):
        item = SimpleNamespace(output_format='original', output_keep_size=False)
        self.assertFalse(of.quality_applies(item))
        self.assertTrue(of.quality_applies(SimpleNamespace(output_format='webp')))
        self.assertTrue(of.quality_applies(SimpleNamespace(output_format='original',
                                                           output_keep_size=True)))

    def test_a_format_of_another_nature_is_said_and_the_file_kept(self):
        said = []
        with mock.patch(INLINE_CONVERSION) as convert:
            out = of.apply_output_settings(['a.png'], SimpleNamespace(
                output_upscale='', output_format='mp4', output_quality='balanced'),
                domain='image', console=said.append)
        convert.assert_not_called()
        self.assertEqual(['a.png'], out)
        self.assertTrue(any('.mp4' in s and 'image' in s for s in said), said)

    def test_the_inspector_says_the_quality_only_when_it_acted(self):
        from wama.common.utils.detail_registry import build_detail
        kept = build_detail(SimpleNamespace(output_format='original', output_quality='balanced',
                                            status='SUCCESS', error_message=''))
        converted = build_detail(SimpleNamespace(output_format='webp', output_quality='max',
                                                 status='SUCCESS', error_message=''))
        self.assertNotIn('output_quality', kept)
        self.assertEqual('max', converted.get('output_quality'))


class OutputParamDefaultsTest(SimpleTestCase):
    """Les réglages de sortie de la brique déclarent le défaut de leurs colonnes (2026-10-11).

    Sans défaut déclaré, une surface GÉNÉRÉE (volet, modale) proposait la PREMIÈRE option —
    « web » pour la qualité — et « Réinitialiser » (`WamaParams.applyDefaults`) vidait le format.
    Mesuré sur le volet généré du synthesizer, quand le volet écrit à la main proposait
    « Équilibré » : le défaut de toutes les colonnes, et le repli de `apply_output_settings`."""

    def test_the_brick_states_the_column_defaults(self):
        params = {p.name: p for p in of.output_format_params('audio')}
        self.assertEqual('original', params['output_format'].default)
        self.assertEqual('balanced', params['output_quality'].default)

    def test_they_are_the_defaults_of_the_columns_of_the_apps_using_it(self):
        from django.apps import apps
        for label, model in (('synthesizer', 'VoiceSynthesis'), ('composer', 'ComposerGeneration'),
                             ('imager', 'ImageGeneration')):
            fields = {f.name: f for f in apps.get_model(label, model)._meta.concrete_fields}
            for name, expected in (('output_format', 'original'), ('output_quality', 'balanced')):
                if name in fields:
                    with self.subTest(model=model, field=name):
                        self.assertEqual(expected, fields[name].get_default())
