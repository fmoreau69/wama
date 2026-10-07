"""Enhancer — portage 2026-09-21 : routes déclarées, squelette commun, tirage « auto » au poids
du curseur (chantier C), NFE décliné. Premier fichier de tests de l'app (jusque-là, l'enhancer
n'était couvert que par les suites communes)."""
import inspect
import os
import tempfile
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.test import SimpleTestCase, TestCase, override_settings

from wama.enhancer.models import AudioEnhancement, Enhancement
from wama.enhancer.utils import auto_model as am


def _catalogue_row(key, model_type, **caps):
    from wama.model_manager.models import AIModel
    return AIModel.objects.create(model_key=key, name=key.split(':')[-1], model_type=model_type,
                                  source='enhancer', is_downloaded=True, capabilities=caps)


class MediaAutoResolutionTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('enh_media', password='x')
        _catalogue_row('enhancer:BSRGANx2', 'upscaling', task='upscale', scale=2)
        _catalogue_row('enhancer:BSRGANx4', 'upscaling', task='upscale', scale=4)
        _catalogue_row('enhancer:RealESRGANx4', 'upscaling', task='upscale', scale=4)
        _catalogue_row('enhancer:IRCNN_Mx1', 'upscaling', task='denoise')

    def _select(self, answer):
        seen = {}

        def fake(source, **kw):
            seen['source'] = source
            seen.update(kw)
            return answer
        return seen, fake

    def test_auto_draws_in_the_upscaler_domain_narrowed_to_the_factor_with_the_item_s_slider(self):
        e = Enhancement.objects.create(user=self.user, media_type='image', ai_model='auto',
                                       upscale_factor=4, quality_intent=90)
        seen, fake = self._select('enhancer:RealESRGANx4')
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual(am.resolve_media_model(e), 'enhancer:RealESRGANx4')
        # Route F4b ⑤ (2026-10-06) : le domaine est la TÂCHE, jamais la source — d'où une clé
        # entière en retour (règle `select_model_id`).
        self.assertIsNone(seen['source'])
        self.assertEqual(seen['task'], 'upscale,denoise')
        self.assertEqual(seen['quality_intent'], 90)
        self.assertEqual(set(seen['candidates']), {'enhancer:BSRGANx4', 'enhancer:RealESRGANx4'})

    def test_a_factor_of_two_keeps_only_the_x2_models(self):
        self.assertEqual(am.media_candidates(2), ['enhancer:BSRGANx2'])
        self.assertEqual(am.media_candidates(None), [])       # facteur inconnu : domaine entier

    def test_a_designated_model_is_kept_as_is_without_any_draw(self):
        e = Enhancement.objects.create(user=self.user, media_type='image', ai_model='BSRGANx2')
        seen, fake = self._select('never')
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual(am.resolve_media_model(e), 'enhancer:BSRGANx2')
        self.assertEqual(seen, {})

    def test_without_an_answer_the_fallback_is_the_app_s_historical_default(self):
        e = Enhancement.objects.create(user=self.user, media_type='image', ai_model='auto')
        _seen, fake = self._select(None)
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual(am.resolve_media_model(e), am.MEDIA_FALLBACK)
        self.assertEqual('enhancer:RealESR_Gx4', am.MEDIA_FALLBACK)


#: The catalogue rows as production carries them: the 7 bundled upscalers declare
#: `onnxruntime` (served by AIUpscaler), and an upscaler installed by the prospection chain.
SWIN2SR_KEY = 'huggingface:onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX'


def _onnx_row(key, task, **caps):
    from wama.model_manager.models import AIModel
    source, _, _ = key.partition(':')
    return AIModel.objects.create(
        model_key=key, name=key.rsplit('/', 1)[-1].split(':')[-1], model_type='upscaling',
        source=source, is_downloaded=True, capabilities={'task': task, **caps},
        composition={'runtime': {'engine': 'onnxruntime'}})


class CatalogueKeysTest(TestCase):
    """Route F4b, step ⑤ (2026-10-06): the media model select lists by TASK and stores
    catalogue KEYS — a model installed from the model manager (Swin2SR) becomes choosable,
    every writer goes through one normalisation, and the bare ids of before still read."""

    def setUp(self):
        self.user = get_user_model().objects.create_user('enh_keys', password='x')
        _onnx_row('enhancer:BSRGANx4', 'upscale', scale=4)
        _onnx_row('enhancer:IRCNN_Mx1', 'denoise')
        _onnx_row(SWIN2SR_KEY, 'upscale', scale=4)

    def test_every_writer_stores_a_catalogue_key(self):
        for given, stored in (('RealESR_Gx4', 'enhancer:RealESR_Gx4'), ('auto', 'auto'),
                              (SWIN2SR_KEY, SWIN2SR_KEY), ('', '')):
            with self.subTest(given=given):
                e = Enhancement.objects.create(user=self.user, media_type='image', ai_model=given)
                self.assertEqual(stored, Enhancement.objects.get(pk=e.pk).ai_model)

    def test_the_select_domain_is_the_task_and_carries_no_static_list(self):
        from wama.enhancer.params import MEDIA_PARAMS
        p = next(p for p in MEDIA_PARAMS if p.name == 'ai_model')
        self.assertEqual('catalog', p.options_source)
        self.assertEqual(am.MEDIA_SPEC, p.options_query)
        self.assertNotIn('source', p.options_query, 'a domain by source hides installed models')
        self.assertFalse(p.choices, 'a static list would bring the bare-id key space back')

    def test_the_panel_pre_renders_the_installed_upscaler(self):
        """The server pre-render of the panel select reads the schema's domain in the catalogue
        (`get_registry_models`, the brick the options endpoint calls) — the installed upscaler
        is there, under its key, beside the bundled ones."""
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        for role in (DEFAULT_APP_ACCESS.get('enhancer') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)
        page = self.client.get(reverse('enhancer:index')).content.decode()
        for key in ('auto', 'enhancer:BSRGANx4', 'enhancer:IRCNN_Mx1', SWIN2SR_KEY):
            self.assertIn(f'<option value="{key}"', page.replace('\n', ' '))

    def test_the_tool_door_rejects_neither_a_key_nor_a_bare_id_of_before(self):
        """Like the imager: no static list, no declared door domain — the door has nothing to
        refuse, and `Enhancement.save` normalises a bare id into its key."""
        from wama.common.utils.param_schema import invalid_choice_values, schema_for_app
        schema = schema_for_app('enhancer')
        for value in (SWIN2SR_KEY, 'enhancer:BSRGANx4', 'RealESR_Gx4', 'auto'):
            with self.subTest(value=value):
                self.assertEqual({}, invalid_choice_values(schema, {'ai_model': value}))

    def test_auto_at_x4_may_draw_the_installed_upscaler(self):
        self.assertEqual({'enhancer:BSRGANx4', SWIN2SR_KEY}, set(am.media_candidates(4)))

    def test_the_route_resolves_a_key_or_a_bare_id_to_the_backend_with_its_identifier(self):
        from wama.enhancer.backends import media_backend
        made = []

        class FakeUpscaler:
            def __init__(self, model_name, tile_size=0):
                made.append(model_name)

        with mock.patch('wama.common.backends.manager.backend_for_key',
                        side_effect=lambda key: FakeUpscaler if key in (
                            'enhancer:IRCNN_Mx1', SWIN2SR_KEY) else None) as resolve:
            media_backend._upscaler_for(SWIN2SR_KEY)
            media_backend._upscaler_for('IRCNN_Mx1')         # denoise pass of upscale_image_file
            with self.assertRaises(RuntimeError):
                media_backend._upscaler_for('enhancer:unknown')
        self.assertEqual([SWIN2SR_KEY, 'enhancer:IRCNN_Mx1', 'enhancer:unknown'],
                         [c.args[0] for c in resolve.call_args_list])
        self.assertEqual(['onnx-community/swin2SR-realworld-sr-x4-64-bsrgan-psnr-ONNX',
                          'IRCNN_Mx1'], made)

    def test_the_eta_keeps_learning_under_the_identifier(self):
        from wama.enhancer.tasks import enhancer_eta_key_size
        e = Enhancement(media_type='image', ai_model='enhancer:RealESR_Gx4', upscale_factor=4)
        self.assertEqual('enhancer:img:RealESR_Gx4:x4', enhancer_eta_key_size(e)[0])
        self.assertEqual('enhancer:img:RealESR_Gx4:x4',
                         enhancer_eta_key_size(e, model='RealESR_Gx4')[0], 'bare id, same key')

    def test_the_item_modal_finds_the_stored_model_among_its_options(self):
        """The ⚙ modal (WamaParams) is built on the SAME schema: it fetches the options endpoint
        with the declared domain, then re-selects the item's stored value — ONLY if that value is
        an option (`wama-params.js` `_bindOptionSources`, `wanted`); otherwise it falls back to
        « auto » and a save would overwrite the chosen model. Stored value and options must share
        one key space: measured here end to end, as the modal builds its request."""
        from urllib.parse import urlencode
        from django.contrib.auth.models import Group
        from django.urls import reverse
        from wama.accounts.permissions import DEFAULT_APP_ACCESS, GROUP_PREFIX
        from wama.enhancer.params import MEDIA_PARAMS
        for role in (DEFAULT_APP_ACCESS.get('model_manager') or {}).get('roles', []):
            self.user.groups.add(Group.objects.get_or_create(name=f'{GROUP_PREFIX}{role}')[0])
        self.client.force_login(self.user)
        field = next(p for p in MEDIA_PARAMS if p.name == 'ai_model')
        query = urlencode(sorted(field.options_query.items())) + '&auto=1'   # = `_optionQuery`
        response = self.client.get(reverse('model_manager:api_model_options') + '?' + query)
        self.assertEqual(200, response.status_code, response.content[:200])
        offered = {o[0] if isinstance(o, list) else o['value']
                   for g in response.json()['groups'] for o in g['options']}
        # A bare id of before (`BSRGANx4`), an installed model, and « auto ».
        for stored in ('BSRGANx4', SWIN2SR_KEY, 'auto'):
            with self.subTest(stored=stored):
                item = Enhancement.objects.create(user=self.user, media_type='image',
                                                  ai_model=stored)
                self.assertIn(item.gear_data['ai-model'], offered)

    def test_the_input_match_meta_names_the_media_options_by_key(self):
        from wama.enhancer.views import _input_match_meta_enhancer
        self.assertIn(SWIN2SR_KEY, _input_match_meta_enhancer())


class CatalogueKeysMigrationTest(SimpleTestCase):
    """`0018_model_catalog_keys`: PURE prefixing (no catalogue lookup), reversible on our own
    prefix only — the pattern of `imager/0023`."""

    def _migration(self):
        import importlib
        return importlib.import_module('wama.enhancer.migrations.0018_model_catalog_keys')

    def test_forward_prefixes_bare_ids_and_leaves_auto_and_keys(self):
        rows = {1: 'RealESR_Gx4', 2: 'auto', 3: SWIN2SR_KEY, 4: ''}
        self._run('to_catalog_keys', rows)
        self.assertEqual({1: 'enhancer:RealESR_Gx4', 2: 'auto', 3: SWIN2SR_KEY, 4: ''}, rows)

    def test_backward_strips_only_its_own_prefix(self):
        rows = {1: 'enhancer:RealESR_Gx4', 2: SWIN2SR_KEY, 3: 'auto'}
        self._run('to_bare_ids', rows)
        self.assertEqual({1: 'RealESR_Gx4', 2: SWIN2SR_KEY, 3: 'auto'}, rows)

    def _run(self, name, rows):
        """Runs the migration function on an in-memory table (shared double, field `ai_model`)."""
        from wama.common.tests.helpers import run_data_migration
        run_data_migration(getattr(self._migration(), name), 'ai_model', rows)


class AudioAutoResolutionTest(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user('enh_audio', password='x')

    def test_auto_draws_between_the_restoration_engines_with_the_item_s_slider(self):
        ae = AudioEnhancement.objects.create(user=self.user, engine='auto', quality_intent=12)
        seen = {}

        def fake(source, **kw):
            seen['source'] = source
            seen.update(kw)
            return 'deepfilternet'
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual(am.resolve_audio_engine(ae), 'deepfilternet')
        self.assertEqual((seen['source'], seen['task'], seen['quality_intent']),
                         ('enhancer', 'audio-enhance', 12))

    def test_a_designated_engine_is_kept_and_a_missing_answer_falls_back_to_resemble(self):
        ae = AudioEnhancement.objects.create(user=self.user, engine='deepfilternet')
        with mock.patch('wama.model_manager.services.select_model_id',
                        lambda *a, **k: self.fail('no draw expected')):
            self.assertEqual(am.resolve_audio_engine(ae), 'deepfilternet')
        ae2 = AudioEnhancement.objects.create(user=self.user, engine='auto')
        with mock.patch('wama.model_manager.services.select_model_id', lambda *a, **k: None):
            self.assertEqual(am.resolve_audio_engine(ae2), 'resemble')


class NfeDeclinesFromTheSliderTest(SimpleTestCase):

    def test_the_nearest_named_position_gives_the_nfe(self):
        self.assertEqual(am.nfe_for_intent(0), 32)
        self.assertEqual(am.nfe_for_intent(15), 32)
        self.assertEqual(am.nfe_for_intent(50), 64)
        self.assertEqual(am.nfe_for_intent(70), 128)
        self.assertEqual(am.nfe_for_intent(100), 128)
        self.assertEqual(am.nfe_for_intent(None), 64)          # illisible = équilibré

    def test_the_column_wins_when_the_engine_was_designated_the_slider_when_it_was_auto(self):
        designated = type('A', (), {'engine': 'resemble', 'quality': 128, 'quality_intent': 5,
                                    'user': None})()
        self.assertEqual(am.audio_nfe(designated, 'resemble'), 128)
        auto = type('A', (), {'engine': 'auto', 'quality': 64, 'quality_intent': 95,
                              'user': None})()
        self.assertEqual(am.audio_nfe(auto, 'resemble'), 128)
        self.assertEqual(am.audio_nfe(auto, 'deepfilternet'), 64)   # sans objet, colonne rendue


class VramNeedIsTheCommonFootprintTest(TestCase):
    """La garde VRAM du squelette lit la cascade COMMUNE (`model_footprint_gb`), jamais un
    chiffre recopié ; sans ligne de catalogue, pas de garde."""

    def test_the_catalogue_row_s_footprint_is_returned_and_an_unknown_key_gives_none(self):
        _catalogue_row('enhancer:resemble', 'speech', task='audio-enhance')
        from wama.model_manager.models import AIModel
        AIModel.objects.filter(model_key='enhancer:resemble').update(vram_gb=4.0)
        self.assertEqual(am.vram_needed_gb('enhancer:resemble'), 4.0)
        self.assertIsNone(am.vram_needed_gb('enhancer:absent'))


class MediaRouteHelpersTest(SimpleTestCase):

    def test_ffprobe_frame_rates_are_parsed_and_the_unreadable_falls_back_to_30(self):
        from wama.enhancer.backends.media_backend import _parse_fps
        self.assertEqual(_parse_fps('25'), 25.0)
        self.assertAlmostEqual(_parse_fps('30000/1001'), 29.97, places=2)
        self.assertEqual(_parse_fps(''), 30)
        self.assertEqual(_parse_fps('x/y'), 30)
        self.assertEqual(_parse_fps('1/0'), 30)

    def test_the_ingest_hook_classifies_only_images_and_videos(self):
        from wama.enhancer.tasks import _derive_media_type
        item = type('E', (), {'media_type': ''})()
        self.assertEqual(_derive_media_type(item, '/x/a.mp4', 'a.mp4'), ['media_type'])
        self.assertEqual(item.media_type, 'video')
        item2 = type('E', (), {'media_type': ''})()
        self.assertEqual(_derive_media_type(item2, '/x/a.wav', 'a.wav'), [])
        self.assertEqual(item2.media_type, '')
        item3 = type('E', (), {'media_type': 'image'})()
        self.assertEqual(_derive_media_type(item3, '/x/a.mp4', 'a.mp4'), [])


class RoutesContractTest(SimpleTestCase):
    """`backends/__init__.ROUTES` : chemins en chaînes, importables, au contrat « fichier »."""

    def test_every_route_is_a_string_path_to_a_callable_with_the_common_signature(self):
        from importlib import import_module

        from wama.enhancer.backends import ROUTES
        self.assertEqual(set(ROUTES), {'image', 'video', 'audio'})
        for nature, path in ROUTES.items():
            self.assertIsInstance(path, str, nature)
            mod, fn = path.rsplit('.', 1)
            target = getattr(import_module('.' + mod, 'wama.enhancer'), fn)
            names = list(inspect.signature(target).parameters)
            self.assertEqual(names[:3], ['input_path', 'output_path', 'output_format'], path)
            self.assertIn('options', names, path)
            self.assertIn('progress_callback', names, path)

    def test_a_route_rejects_an_unresolved_auto_instead_of_guessing(self):
        from wama.enhancer.backends.audio_backend import enhance_audio
        from wama.enhancer.backends.media_backend import enhance_image
        with self.assertRaises(ValueError):
            enhance_audio('in.wav', 'out.wav', None, options={'engine': 'auto'})
        with self.assertRaises(ValueError):
            enhance_image('in.png', 'out.png', None, options={})


class _Ctx:
    def __init__(self):
        self.progress_values, self.lines = [], []

    def progress(self, pct, msg=None):
        self.progress_values.append(pct)

    def console(self, msg, level=None):
        self.lines.append(msg)


class GlueTest(TestCase):
    """La glu du squelette : route par nature, modèle résolu dans les options, stockage à la
    convention, champs rendus au squelette, ligne d'exécution (`models`)."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.user = get_user_model().objects.create_user('enh_glue', password='x')

    def test_the_media_glue_stores_the_route_s_output_and_reports_the_resolved_model(self):
        from wama.enhancer import tasks
        with override_settings(MEDIA_ROOT=self.tmp):
            e = Enhancement.objects.create(user=self.user, media_type='image', ai_model='auto',
                                           upscale_factor=4, quality_intent=80)
            e.input_file.save('photo.png', ContentFile(b'\x89PNG' + b'\0' * 16), save=True)

            def fake_route(input_path, output_path, output_format=None, options=None,
                           progress_callback=None):
                self.assertEqual(options['ai_model'], 'enhancer:RealESRGANx4')
                with open(output_path, 'wb') as f:
                    f.write(b'out')
                progress_callback(100)
                return {'width': 8, 'height': 6}

            ctx = _Ctx()
            # Le tirage rend une CLÉ de catalogue depuis la route F4b ⑤ (2026-10-06).
            with mock.patch('wama.enhancer.backends.media_backend.enhance_image', fake_route), \
                    mock.patch('wama.enhancer.utils.auto_model.resolve_media_model',
                               return_value='enhancer:RealESRGANx4'):
                res = tasks._enhance_media(e, ctx)
        fields = res['fields']
        # ⚠ Attestait l'ANCIEN domicile jusqu'au 2026-09-22 — le test figeait le défaut. Le
        # préfixe attendu vient de la brique, pas d'une chaîne recopiée ici.
        from wama.common.utils.media_paths import app_media_dir
        self.assertTrue(fields['output_file'].startswith(
            app_media_dir('enhancer', self.user.id, 'output/media') + '/'), fields['output_file'])
        self.assertTrue(os.path.exists(os.path.join(self.tmp, fields['output_file'])))
        self.assertEqual((fields['output_width'], fields['output_height']), (8, 6))
        self.assertEqual(res['models'], ['enhancer:RealESRGANx4'])
        self.assertEqual(res['eta'][0], 'enhancer:img:RealESRGANx4:x4')
        self.assertTrue(any('Auto' in line for line in ctx.lines))
        self.assertEqual(max(ctx.progress_values), 95)

    def test_the_audio_glue_declines_the_nfe_from_the_slider_when_the_engine_was_auto(self):
        from wama.enhancer import tasks
        with override_settings(MEDIA_ROOT=self.tmp):
            ae = AudioEnhancement.objects.create(user=self.user, engine='auto', quality_intent=95)
            ae.input_file.save('voice.wav', ContentFile(b'RIFF' + b'\0' * 16), save=True)
            seen = {}

            def fake_route(input_path, output_path, output_format=None, options=None,
                           progress_callback=None):
                seen.update(options)
                with open(output_path, 'wb') as f:
                    f.write(b'wav')
                return output_path

            with mock.patch('wama.enhancer.backends.audio_backend.enhance_audio', fake_route), \
                    mock.patch('wama.enhancer.utils.auto_model.resolve_audio_engine',
                               return_value='resemble'):
                res = tasks._enhance_audio(ae, _Ctx())
        self.assertEqual((seen['engine'], seen['quality']), ('resemble', 128))
        self.assertTrue(res['fields']['output_file'].endswith('_resemble.wav'))
        self.assertEqual(res['models'], ['enhancer:resemble'])


class SchemaCarriesTheSliderTest(SimpleTestCase):

    def test_both_branches_serve_auto_and_condition_their_slider_on_it(self):
        from wama.common.utils.auto_model import intent_field_for
        from wama.enhancer.params import AUDIO_PARAMS_JSON, MEDIA_PARAMS_JSON
        for schema, model_field in ((MEDIA_PARAMS_JSON, 'ai_model'), (AUDIO_PARAMS_JSON, 'engine')):
            by_name = {p['name']: p for p in schema}
            self.assertTrue(by_name[model_field]['options_auto'], model_field)
            self.assertEqual(by_name['quality_intent']['type'], 'intent')
            self.assertEqual(by_name['quality_intent']['show_if'],
                             {'field': model_field, 'equals': 'auto'})
        self.assertEqual(intent_field_for('enhancer'), 'quality_intent')
        by_name = {p['name']: p for p in MEDIA_PARAMS_JSON}
        self.assertEqual(by_name['upscale_factor']['show_if'], {'field': 'ai_model', 'equals': 'auto'})


class ViewsCarryTheSliderTest(TestCase):

    def setUp(self):
        from django.contrib.auth.models import Group

        from wama.accounts.permissions import GROUP_PREFIX
        # `AppAccessMiddleware` redirige (302) tout compte sans le rôle de l'app : le test
        # franchit le portier, il ne le contourne pas (l'enhancer = rôle `communication`,
        # cf. `accounts/permissions.APP_ACCESS` et tests_import_contract).
        self.user = get_user_model().objects.create_user('enh_views', password='x')
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}communication')
        self.user.groups.add(group)
        self.client.force_login(self.user)

    def test_the_media_settings_view_writes_the_slider_the_factor_and_auto(self):
        from django.urls import reverse
        e = Enhancement.objects.create(user=self.user, media_type='image', ai_model='BSRGANx2')
        r = self.client.post(reverse('enhancer:update_settings', args=[e.pk]),
                             {'ai_model': 'auto', 'upscale_factor': '2', 'quality_intent': '77'})
        self.assertEqual(r.status_code, 200, r.content)
        e.refresh_from_db()
        self.assertEqual((e.ai_model, e.upscale_factor, e.quality_intent), ('auto', 2, 77))
        self.client.post(reverse('enhancer:update_settings', args=[e.pk]), {'quality_intent': ''})
        e.refresh_from_db()
        self.assertIsNone(e.quality_intent, 'posé vide = curseur effacé (cascade → réglage d\'app)')

    def test_the_audio_settings_view_writes_the_slider_and_the_output_format(self):
        from django.urls import reverse
        ae = AudioEnhancement.objects.create(user=self.user)
        r = self.client.post(reverse('enhancer:audio_update', args=[ae.pk]),
                             {'engine': 'auto', 'quality_intent': '12', 'output_format': 'mp3'})
        self.assertEqual(r.status_code, 200, r.content)
        ae.refresh_from_db()
        self.assertEqual((ae.engine, ae.quality_intent, ae.output_format), ('auto', 12, 'mp3'))
