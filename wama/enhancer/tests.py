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
        seen, fake = self._select('RealESRGANx4')
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual(am.resolve_media_model(e), 'RealESRGANx4')
        self.assertEqual(seen['source'], 'enhancer')
        self.assertEqual(seen['model_type'], 'upscaling')
        self.assertEqual(seen['quality_intent'], 90)
        self.assertEqual(set(seen['candidates']), {'enhancer:BSRGANx4', 'enhancer:RealESRGANx4'})

    def test_a_factor_of_two_keeps_only_the_x2_models(self):
        self.assertEqual(am.media_candidates(2), ['enhancer:BSRGANx2'])
        self.assertEqual(am.media_candidates(None), [])       # facteur inconnu : domaine entier

    def test_a_designated_model_is_kept_as_is_without_any_draw(self):
        e = Enhancement.objects.create(user=self.user, media_type='image', ai_model='BSRGANx2')
        seen, fake = self._select('never')
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual(am.resolve_media_model(e), 'BSRGANx2')
        self.assertEqual(seen, {})

    def test_without_an_answer_the_fallback_is_the_app_s_historical_default(self):
        e = Enhancement.objects.create(user=self.user, media_type='image', ai_model='auto')
        _seen, fake = self._select(None)
        with mock.patch('wama.model_manager.services.select_model_id', fake):
            self.assertEqual(am.resolve_media_model(e), am.MEDIA_FALLBACK)


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
                self.assertEqual(options['ai_model'], 'RealESRGANx4')
                with open(output_path, 'wb') as f:
                    f.write(b'out')
                progress_callback(100)
                return {'width': 8, 'height': 6}

            ctx = _Ctx()
            with mock.patch('wama.enhancer.backends.media_backend.enhance_image', fake_route), \
                    mock.patch('wama.enhancer.utils.auto_model.resolve_media_model',
                               return_value='RealESRGANx4'):
                res = tasks._enhance_media(e, ctx)
        fields = res['fields']
        self.assertTrue(fields['output_file'].startswith(f'enhancer/{self.user.id}/output/media/'))
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
