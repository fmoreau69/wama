"""Declared a-priori quality, WITH its source (2026-10-03, Fabien's decision).

Measured that day: none of the six music models carried a quality signal, so the draw ranked them
by VRAM — MiniMax-Music3 (13 GB) above YuE2 (8.8 GB). The table covers the models the structural
prior cannot rate and no machine-readable third-party bench covers.
"""
from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services.model_quality import DECLARED_PRIORS, declared_prior


class EachPriorSaysWhereItComesFromTest(SimpleTestCase):

    def test_every_prior_has_a_number_and_a_dated_source(self):
        for key, (value, source) in DECLARED_PRIORS.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, float)
                self.assertRegex(source, r'20\d\d-\d\d-\d\d', 'a source without a date ages silently')

    def test_an_undeclared_model_has_no_prior(self):
        self.assertIsNone(declared_prior('composer:nowhere'))
        self.assertIsNone(declared_prior(''))


class ATaskIsRatedWholeOrNotAtAllTest(SimpleTestCase):
    """The selection ranks only the RATED members of a lot: rating part of a task would make the
    unrated ones never drawn — even at the fast end of the cursor. Held on what is DECLARED
    statically (the composer's music models) ; the catalogue-wide check is a measure on the real
    base (`PROSPECTION_PIPELINE`, session of 2026-10-03)."""

    def test_every_music_model_of_the_composer_is_rated(self):
        from wama.composer.utils.model_config import COMPOSER_MODELS
        music = {f'composer:{k}' for k, v in COMPOSER_MODELS.items() if v.get('type') == 'music'}
        self.assertEqual(set(), music - set(DECLARED_PRIORS))


class TheSyncWritesTheDeclaredPriorTest(TestCase):

    def test_a_model_the_discovery_does_not_rate_gets_its_declared_prior(self):
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        from wama.model_manager.services.model_sync import ModelSyncService
        key = next(iter(DECLARED_PRIORS))
        info = ModelInfo(id=key.split(':', 1)[1], name='x', model_type=ModelType.MUSIC,
                         source=ModelSource(key.split(':', 1)[0]), vram_gb=1.0)
        ModelSyncService()._sync_model(key, info)
        self.assertEqual(DECLARED_PRIORS[key][0],
                         AIModel.objects.get(model_key=key).quality_index)

    def test_a_value_the_discovery_states_still_wins(self):
        from wama.model_manager.models import ModelSource, ModelType
        from wama.model_manager.services.model_registry import ModelInfo
        from wama.model_manager.services.model_sync import ModelSyncService
        key = next(iter(DECLARED_PRIORS))
        info = ModelInfo(id=key.split(':', 1)[1], name='x', model_type=ModelType.MUSIC,
                         source=ModelSource(key.split(':', 1)[0]), quality_index=12.5)
        ModelSyncService()._sync_model(key, info)
        self.assertEqual(12.5, AIModel.objects.get(model_key=key).quality_index)
