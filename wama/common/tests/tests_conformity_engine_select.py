"""La porte `_has_engine_select` de la grille lit TOUS les schémas d'une app (2026-09-28).

Elle décide si `model_help`, `input_match_ui` et `model_caps_ui` s'appliquent. Elle ne lisait que
`PARAMS_JSON` ; l'imager, dont les schémas sont éclatés par domaine (`IMAGE_PARAMS_JSON`,
`VIDEO_PARAMS_JSON`), n'était reconnu que par le select de modèle de sa card d'entrée. Ce select
est parti au volet (CARD_DESIGN §11.11 Étape 3 (c)) : sans cette lecture, les trois critères
passaient N/A et le `model_caps_ui` ROUGE de l'imager disparaissait de la grille sans être réparé.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.services import conformity_checker as cc


class EngineSelectGateReadsSplitSchemasTest(SimpleTestCase):

    def test_the_imager_is_recognised_by_its_schemas_alone(self):
        templates = Path(settings.BASE_DIR) / 'wama' / 'imager' / 'templates'
        signal = re.compile(r'(?:id|name|for)\s*=\s*["\'][^"\']*ModelSelect')
        self.assertFalse([p for p in templates.rglob('*.html')
                          if signal.search(p.read_text(encoding='utf-8'))],
                         'la card de l’imager porte de nouveau un select de modèle')
        self.assertTrue(cc._has_engine_select(cc._AppFiles('imager')),
                        'le select de modèle déclaré par IMAGE_/VIDEO_PARAMS_JSON n’est pas vu')

    def test_an_app_without_an_engine_select_stays_outside(self):
        """Contre-épreuve : lire plus de schémas ne doit pas ouvrir la porte à tout le monde."""
        self.assertFalse(cc._has_engine_select(cc._AppFiles('converter')))


class InputCardV4CountsAsTheCommonCardTest(SimpleTestCase):
    """Une app portée sur la card v4 garde ses critères de card d'entrée (2026-09-29).

    L'avatarizer, 1ʳᵉ app en place en v4, est passé ROUGE sur `new_item_card` et
    `media_library_slot` : la grille ne reconnaissait que l'include v3 et `show_media_library`,
    un littéral que la v4 dérive des ports au lieu de le lire."""

    def _verdict(self, key, app):
        crit = next(c for c in cc.CRITERIA if c.key == key)
        state, _evidence = crit.fn(cc._AppFiles(app))
        return state

    def test_the_v4_avatarizer_passes_both_card_criteria(self):
        for key in ('new_item_card', 'media_library_slot'):
            self.assertTrue(self._verdict(key, 'avatarizer'), key)

    def test_a_v3_app_still_passes(self):
        """Contre-épreuve : la graphie v3 reste reconnue."""
        for key in ('new_item_card', 'media_library_slot'):
            self.assertTrue(self._verdict(key, 'transcriber'), key)
