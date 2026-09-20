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


class IntentCascadeTest(TestCase):

    def test_the_schema_names_the_field_and_the_cascade_reads_item_then_user_then_default(self):
        from wama.common.utils.user_settings import save_user_app_settings
        self.assertEqual(auto_model.intent_field_for('synthesizer'), 'quality_intent')
        self.assertEqual(auto_model.intent_field_for('anonymizer'), 'precision_level')
        self.assertIsNone(auto_model.intent_field_for('converter'))
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
        # Adoption restante (autres sessions : imager, composer) — à retirer d'ici au fur et à mesure.
        self.assertEqual(missing, [], f"apps qui servent « auto » sans curseur : {missing}")
