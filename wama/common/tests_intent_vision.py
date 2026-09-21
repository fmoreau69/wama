"""Chantier C (2026-09-20) — le curseur rapide/qualité devient CONTRACTUEL dans le commun, et sa
déclinaison VISION (anonymizer) remonte dans la brique de couverture.

POURQUOI. Décision de Fabien (15/09) : « le curseur se généralise ; le curseur de précision de
l'anonymizer garde son fonctionnement mais REMONTE AU COMMUN avec sa spécificité vision ».
Mesuré avant d'écrire : `coerce_params` ignorait le type `intent` ; imager, composer, reader et
transcriber appelaient la brique SANS lui passer l'intention ; la déclinaison n/s/m/l/x et le
seuil de segmentation vivaient dans l'app ; sur « auto », rien n'était grisé.

Consigne de Fabien : « attention à bien conserver le comportement de l'anonymizer » — d'où la
table de non-régression cran par cran contre les seuils historiques.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from wama.common.services import model_coverage as cov
from wama.common.utils import auto_model
from wama.common.utils.param_schema import Param, coerce_params


def _legacy_size(level: int) -> str:
    """La table telle qu'elle était écrite dans `anonymizer/utils/model_selector.py` (avant C)."""
    if level <= 20:
        return 'n'
    if level <= 40:
        return 's'
    if level <= 60:
        return 'm'
    if level <= 80:
        return 'l'
    return 'x'


class VisionDeclinationTest(SimpleTestCase):

    def test_every_notch_gives_the_same_size_and_segmentation_as_the_anonymizer_did(self):
        from wama.anonymizer.utils.model_selector import (
            get_model_size_from_precision, should_use_segmentation)
        for level in range(0, 101):
            self.assertEqual(cov.size_for_intent(level), _legacy_size(level), level)
            self.assertEqual(get_model_size_from_precision(level), _legacy_size(level), level)
            self.assertEqual(cov.segmentation_for_intent(level), level >= 50, level)
            self.assertEqual(should_use_segmentation(level), level >= 50, level)

    def test_an_unreadable_intent_is_balanced_never_an_error(self):
        self.assertEqual(cov.size_for_intent(None), 'm')
        self.assertEqual(cov.size_for_intent('abc'), 'm')
        self.assertTrue(cov.segmentation_for_intent('quality'))       # position nommée ? non : 'quality' illisible → 50 → True
        self.assertEqual(cov.size_for_intent(250), 'x')

    def test_the_public_size_reader_is_the_same_rule_as_the_tie_break(self):
        self.assertEqual(cov.size_of_name('yolo11l-seg.pt'), 'l')
        self.assertEqual(cov.size_of_name('license-plate-finetune-v1m.onnx'), 'm')
        self.assertEqual(cov.size_of_name('sam3'), '')


class _Model:
    """Un AIModel minimal pour la couverture (la brique ne lit que ces attributs)."""

    def __init__(self, key, name, classes, task='detect', vram=1.0):
        self.model_key, self.name = key, name
        self.capabilities = {'classes': classes, 'task': task}
        self.quality_index, self.vram_gb, self.local_path = None, vram, ''


class CoverageDerivesItsPreferencesTest(SimpleTestCase):

    def _cover(self, **kw):
        models = [_Model('a:yolo11n', 'yolo11n.pt', ['face', 'car'], vram=0.2),
                  _Model('a:yolo11x', 'yolo11x.pt', ['face', 'car'], vram=2.0),
                  _Model('a:yolo11x-seg', 'yolo11x-seg.pt', ['face', 'car'], task='segment', vram=2.2)]
        with mock.patch('wama.model_manager.models.AIModel') as am:
            qs = mock.MagicMock()
            qs.filter.return_value = qs
            qs.__iter__.return_value = iter(models)
            am.objects.filter.return_value = qs
            return cov.couvrir_classes(['face'], taches_admises=('detect', 'segment'), **kw)

    def test_a_low_intent_prefers_the_small_model_and_a_high_one_segmentation(self):
        self.assertEqual(self._cover(quality_intent=10)['modeles'][0]['model_key'], 'a:yolo11n')
        self.assertEqual(self._cover(quality_intent=95)['modeles'][0]['model_key'], 'a:yolo11x-seg')

    def test_explicit_preferences_still_win_over_the_intent(self):
        r = self._cover(quality_intent=95, taille_preferee='n', preferer_segmentation=False)
        # segmentation dérivée (95 ≥ 50) ET taille explicite 'n' : la seg prime dans le départage
        self.assertIn(r['modeles'][0]['model_key'], ('a:yolo11x-seg', 'a:yolo11n'))
        r = self._cover(taille_preferee='n')
        self.assertEqual(r['modeles'][0]['model_key'], 'a:yolo11n')


class IntentIsCoercedLikeAnyNumberTest(SimpleTestCase):

    def test_coerce_params_bounds_the_intent_and_returns_an_integer(self):
        schema = [Param(name='quality_intent', **auto_model.intent_param()),
                  Param(name='steps', type='number', min=1, max=10, default=4)]
        self.assertEqual(coerce_params(schema, {'quality_intent': '250', 'steps': '3'}),
                         {'quality_intent': 100, 'steps': 3.0})
        self.assertEqual(coerce_params(schema, {'quality_intent': 'x'})['quality_intent'], 50)
        self.assertEqual(coerce_params(schema, {'quality_intent': '-4'})['quality_intent'], 0)
        self.assertIsInstance(coerce_params(schema, {'quality_intent': '42.6'})['quality_intent'], int)


class PostedIntentAndNearestPresetTest(SimpleTestCase):
    """Deux lecteurs COMMUNS nés de la revérification du 21/09 (trois copies de vue, deux
    règles de proximité)."""

    def test_an_absent_or_blank_post_is_none_and_a_value_is_bounded(self):
        self.assertIsNone(auto_model.posted_quality_intent({}))
        self.assertIsNone(auto_model.posted_quality_intent({'quality_intent': ''}))
        self.assertIsNone(auto_model.posted_quality_intent({'quality_intent': '  '}))
        self.assertIsNone(auto_model.posted_quality_intent(None))
        self.assertEqual(auto_model.posted_quality_intent({'quality_intent': '77'}), 77)
        self.assertEqual(auto_model.posted_quality_intent({'quality_intent': '250'}), 100)
        self.assertEqual(auto_model.posted_quality_intent({'quality_intent': 'abc'}), 50)

    def test_the_nearest_named_position_wins_and_the_higher_one_on_a_tie(self):
        self.assertEqual(auto_model.preset_key_for_intent(0), 'fast')
        self.assertEqual(auto_model.preset_key_for_intent(32), 'fast')
        self.assertEqual(auto_model.preset_key_for_intent(33), 'balanced')
        self.assertEqual(auto_model.preset_key_for_intent(67), 'balanced')
        self.assertEqual(auto_model.preset_key_for_intent(68), 'quality')
        self.assertEqual(auto_model.preset_key_for_intent(100), 'quality')
        self.assertEqual(auto_model.preset_key_for_intent(None), 'balanced')

    def test_the_converter_preset_is_the_common_rule_translated_to_its_keys(self):
        from wama.converter.utils.quality_presets import preset_for_intent
        for v, key in ((10, 'web'), (50, 'balanced'), (90, 'max')):
            self.assertEqual(preset_for_intent(v), key)


class IntentCascadeTest(TestCase):

    def test_the_schema_names_the_field_and_the_cascade_reads_item_then_user_then_default(self):
        from wama.common.utils.user_settings import save_user_app_settings
        self.assertEqual(auto_model.intent_field_for('synthesizer'), 'quality_intent')
        self.assertEqual(auto_model.intent_field_for('anonymizer'), 'precision_level')
        self.assertEqual(auto_model.intent_field_for('converter'), 'quality_intent')   # rallié le 20/09
        self.assertIsNone(auto_model.intent_field_for('describer'))
        u = get_user_model().objects.create_user('c_intent', password='x')

        class _Item:
            quality_intent = 85
            user = u

        self.assertEqual(auto_model.quality_intent_of(_Item(), 'synthesizer'), 85)
        self.assertEqual(auto_model.quality_intent_of(None, 'synthesizer', u), 50)
        save_user_app_settings(u, 'reader', {'quality_intent': 20})
        self.assertEqual(auto_model.quality_intent_of(None, 'reader', u), 20)

        class _Blank:
            quality_intent = ''
            user = u

        self.assertEqual(auto_model.quality_intent_of(_Blank(), 'reader'), 20)

    def test_resolve_model_choice_fills_the_intent_from_the_item_unless_given(self):
        seen = {}

        def fake_select(source, **kw):
            seen.update(kw)
            return 'x'

        class _Item:
            precision_level = 90
            user = None

        with mock.patch('wama.model_manager.services.select_model_id', fake_select):
            auto_model.resolve_model_choice('auto', app_id='anonymizer', spec={'source': 'anonymizer'},
                                            item=_Item())
            self.assertEqual(seen['quality_intent'], 90)
            seen.clear()
            auto_model.resolve_model_choice('auto', spec={'source': 'x'}, item=_Item(),
                                            quality_intent=30)
            self.assertEqual(seen['quality_intent'], 30)
            seen.clear()
            auto_model.resolve_model_choice('auto', spec={'source': 'x'})
            self.assertNotIn('quality_intent', seen)      # comme avant : équilibré par défaut


class AnonymizerAutoGreyingTest(TestCase):
    """Sur « auto », la meta serveur porte l'union des modèles de DÉTECTION installés : une classe
    qu'aucun ne détecte est grisée (désactiver + expliquer) — avant, `caps = null`, rien."""

    def test_the_auto_entry_is_the_union_of_installed_detection_models(self):
        import json

        from wama.anonymizer.views import _class_coverage_meta
        from wama.model_manager.models import AIModel

        def row(key, classes, task='detect', downloaded=True):
            AIModel.objects.create(model_key=key, name=key.split(':')[-1], model_type='vision',
                                   source='anonymizer', is_downloaded=downloaded,
                                   capabilities={'classes': classes, 'task': task})

        row('anonymizer:yolo:face.pt', ['face'])
        row('anonymizer:yolo:plates.onnx', ['license_plate'])
        row('anonymizer:yolo:cls.pt', ['car'], task='classify')          # classifie, ne localise pas
        row('anonymizer:yolo:absent.pt', ['person'], downloaded=False)   # pas installé
        meta = json.loads(_class_coverage_meta())
        # Les ids sont ceux des CHECKBOXES de l'app (`get_all_class_choices`, casse comprise) :
        # la meta est faite pour elles, pas pour le vocabulaire du catalogue.
        self.assertEqual([c.lower() for c in meta['auto']['covered_classes']], ['face', 'plate'])
        self.assertEqual([c.lower() for c in meta['anonymizer:yolo:face.pt']['covered_classes']],
                         ['face'])
        self.assertEqual([c.lower() for c in meta['anonymizer:yolo:absent.pt']['covered_classes']],
                         ['person'])


class ReaderCarriesTheSliderAsAnAppSettingTest(TestCase):

    def test_the_upload_persists_the_slider_and_the_launch_reads_it(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from django.urls import reverse

        from django.contrib.auth.models import Group

        from wama.accounts.permissions import GROUP_PREFIX
        from wama.common.utils.user_settings import get_user_app_setting
        u = get_user_model().objects.create_user('c_reader', password='x')
        # `AppAccessMiddleware` redirige (302) tout compte sans le rôle de l'app : le test
        # franchit le portier, il ne le contourne pas (rôle `recherche`, cf. tests_import_contract).
        group, _ = Group.objects.get_or_create(name=f'{GROUP_PREFIX}recherche')
        u.groups.add(group)
        self.client.force_login(u)
        png = SimpleUploadedFile('page.png', b'\x89PNG\r\n\x1a\n' + b'\0' * 32, content_type='image/png')
        r = self.client.post(reverse('wama.reader:upload'),
                             {'files': png, 'backend': 'auto', 'quality_intent': '88'})
        self.assertEqual(r.status_code, 200, r.content)
        self.assertEqual(get_user_app_setting(u, 'reader', 'quality_intent'), 88)
        item = type('I', (), {'user': u, 'quality_intent': None})()
        self.assertEqual(auto_model.quality_intent_of(item, 'reader'), 88)
        png2 = SimpleUploadedFile('page2.png', b'\x89PNG\r\n\x1a\n' + b'\0' * 32, content_type='image/png')
        self.client.post(reverse('wama.reader:upload'), {'files': png2, 'backend': 'auto'})
        self.assertEqual(get_user_app_setting(u, 'reader', 'quality_intent'), 88,
                         'sans POST, le dernier réglage tient')


class GridCriterionTest(SimpleTestCase):
    """Le critère `quality_intent` distingue « appelle la brique » de « lui passe l'intention »."""

    def _app(self, params: str, code: str):
        import tempfile
        from pathlib import Path

        from wama.common.services import conformity_checker as cc
        from wama.common.tests_conformity_backends import _Fichiers
        root = Path(tempfile.mkdtemp())
        (root / 'params.py').write_text(params, encoding='utf-8')
        (root / 'tasks.py').write_text(code, encoding='utf-8')
        return cc._quality_intent(_Fichiers('fake', [], root=root))

    def test_declared_and_passed_in_the_call_is_adopted(self):
        state, proof = self._app("x = intent_param(dom_id='q')",
                                 "chosen = select_model_id('fake', task='ocr',\n"
                                 "    quality_intent=quality_intent_of(item, 'fake'))")
        self.assertTrue(state, proof)

    def test_declared_but_not_passed_is_red_and_says_why(self):
        state, proof = self._app("x = intent_param()", "chosen = resolve_model_choice(v, spec=s)")
        self.assertIs(state, False)
        self.assertIn('jamais passé', proof)

    def test_auto_choice_without_a_slider_is_red(self):
        state, proof = self._app("x = 1", "chosen = resolve_model_choice(v, spec=s)")
        self.assertIs(state, False)
        self.assertIn('sans curseur', proof)

    def test_an_app_without_a_model_that_declines_the_slider_itself_is_adopted(self):
        """Le cas converter : pas de modèle à tirer, le curseur décline en réglages d'encodage."""
        state, proof = self._app("x = intent_param()", "q = read_quality_intent(request.POST.get('q'))")
        self.assertTrue(state, proof)
        state, proof = self._app("x = intent_param()", "y = 1")
        self.assertIs(state, False)
        self.assertIn('jamais lu', proof)

    def test_nothing_to_arbitrate_is_not_applicable(self):
        self.assertEqual(self._app("x = 1", "y = 2"), (None, None))


class ImagerAndComposerPassTheSliderTest(TestCase):
    """Les deux adopteurs historiques de la brique appelaient `resolve_model_choice` SANS
    intention (mesuré le 20/09) : l'item la porte désormais, et le tirage la reçoit."""

    def test_the_imager_resolution_passes_the_item_s_slider(self):
        from wama.imager.models import ImageGeneration
        from wama.imager.utils.auto_model import resolve_auto_model
        u = get_user_model().objects.create_user('c_imager', password='x')
        gen = ImageGeneration.objects.create(user=u, prompt='x', model='auto', quality_intent=88)
        seen = {}

        def fake_select(source, **kw):
            seen.update(kw)
            return 'sdxl'

        with mock.patch('wama.model_manager.services.select_model_id', fake_select):
            self.assertEqual(resolve_auto_model(gen), 'sdxl')
        self.assertEqual(seen.get('quality_intent'), 88)

    def test_the_composer_resolution_passes_the_item_s_slider(self):
        from wama.composer.models import ComposerGeneration
        from wama.composer.utils.auto_model import resolve_auto_model
        u = get_user_model().objects.create_user('c_composer', password='x')
        gen = ComposerGeneration.objects.create(user=u, prompt='x', model='auto-music',
                                                generation_type='music', quality_intent=12)
        seen = {}

        def fake_select(source, **kw):
            seen.update(kw)
            return 'musicgen-small'

        with mock.patch('wama.model_manager.services.select_model_id', fake_select):
            self.assertEqual(resolve_auto_model(gen), 'musicgen-small')
        self.assertEqual(seen.get('quality_intent'), 12)

    def test_both_schemas_carry_the_slider_conditioned_on_auto(self):
        from wama.common.utils.param_schema import schema_for_app
        for app in ('imager', 'composer'):
            field = next((f for f in schema_for_app(app) if f.get('name') == 'quality_intent'), None)
            self.assertIsNotNone(field, app)
            self.assertEqual(field.get('type'), 'intent', app)


class EveryAutoSelectCarriesTheSliderTest(SimpleTestCase):

    def test_every_app_that_serves_auto_carries_an_intent_param(self):
        """Fabien (19/09) : « toutes les apps auront le curseur ». Le test de parcours d'avant ne
        gardait que les apps qui l'avaient déjà ; celui-ci nomme celles qui servent « auto » sans
        le curseur — la liste est le RESTE du chantier C, elle doit finir vide."""
        from wama.common.app_registry import APP_CATALOG
        from wama.common.utils.param_schema import schema_for_app
        missing = []
        for app in sorted(APP_CATALOG):
            schema = schema_for_app(app) or []
            if any(f.get('options_auto') for f in schema) and \
                    not any(f.get('type') == 'intent' for f in schema):
                missing.append(app)
        # 21/09 : imager, composer puis enhancer ralliés — la liste est vide, et doit le rester.
        self.assertEqual(missing, [], f"apps qui servent « auto » sans curseur : {missing}")
