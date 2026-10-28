"""Declared a-priori quality, WITH its source (2026-10-03, Fabien's decision).

Measured that day: none of the six music models carried a quality signal, so the draw ranked them
by VRAM — MiniMax-Music3 (13 GB) above YuE2 (8.8 GB). The table covers the models the structural
prior cannot rate and no machine-readable third-party bench covers.

Declared DEFECTS (2026-10-28, Fabien's decision) : a model a WAMA measure caught returning a wrong
result without saying so — Albert's whisper-large-v3 drops distant speech. Greyed in the selects
with its reason, and out of the automatic draw, like a model without a backend.
"""
from unittest import mock

from django.contrib.auth import get_user_model
from django.test import Client, SimpleTestCase, TestCase

from wama.model_manager.models import AIModel
from wama.model_manager.services import model_quality
from wama.model_manager.services.model_quality import (DECLARED_DEFECTS, DECLARED_PRIORS,
                                                       declared_defect, declared_prior)


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


class EachDefectSaysWhyTest(SimpleTestCase):

    def test_every_defect_has_a_label_a_reason_and_a_dated_source(self):
        for key, (short, reason, source) in DECLARED_DEFECTS.items():
            with self.subTest(key=key):
                self.assertTrue(short and reason)
                self.assertRegex(source, r'20\d\d-\d\d-\d\d', 'a measure without a date ages silently')
                self.assertEqual((short, reason), declared_defect(key))

    def test_albert_whisper_is_declared_until_the_measure_changes(self):
        self.assertIn('albert:whisper-large-v3', DECLARED_DEFECTS)
        self.assertIsNone(declared_defect('transcriber:whisper'))
        self.assertIsNone(declared_defect(''))


def _asr(model_key, *, execution='local'):
    return AIModel.objects.create(
        model_key=model_key, name=model_key.split(':', 1)[1], model_type='speech',
        source=model_key.split(':', 1)[0], vram_gb=0.0 if execution == 'cloud' else 3.0,
        is_available=True, is_downloaded=execution != 'cloud', execution=execution,
        capabilities={'task': 'transcription', 'modalities': ['audio']})


class ADefectiveModelLeavesTheAutomaticDrawTest(TestCase):
    """The REMOTE model the user's key opens, preferred by the priority, is not drawn once its
    defect is declared — the local one is. Without the declaration it wins (counter-proof in the
    test itself : the guard would stay green if the draw never offered it)."""

    def setUp(self):
        _asr('albert:whisper-large-v3', execution='cloud')
        _asr('transcriber:local-asr')

    def _draw(self):
        from wama.model_manager.services import select_model
        chosen = select_model(model_type='speech', prefer_loaded=False, vram_budget_gb=10,
                              candidates=['albert:whisper-large-v3', 'transcriber:local-asr'],
                              cloud_keys=['albert:whisper-large-v3'],
                              priority=['whisper-large-v3'])
        return chosen.model_key if chosen else None

    def test_the_declared_defect_hands_the_draw_to_the_local_model(self):
        self.assertEqual('transcriber:local-asr', self._draw())

    def test_without_the_declaration_the_remote_model_would_win(self):
        with mock.patch.dict(model_quality.DECLARED_DEFECTS, clear=True):
            self.assertEqual('albert:whisper-large-v3', self._draw())


class TheSelectGreysItWithItsReasonTest(TestCase):
    """Listing is not choosing (`INPUT_MODEL_MATCHING §2`) : the option STAYS, greyed, its short
    label in the select and its reason on hover — never the « backend absent » of another verdict."""

    def test_the_option_is_listed_disabled_with_its_own_reason(self):
        _asr('transcriber:flawed-asr')
        _asr('transcriber:sound-asr')
        user = get_user_model().objects.create_user(username='defect_select', password='x')
        client = Client()
        client.force_login(user)
        entry = ('drops distant speech', 'Measured on a distant interview.', '2026-10-28 test')
        with mock.patch.dict(model_quality.DECLARED_DEFECTS, {'transcriber:flawed-asr': entry}):
            data = client.get('/model-manager/api/models/options/', {'task': 'transcription'}).json()
        options = [o for g in data['groups'] for o in g['options']]
        flawed = next(o for o in options if isinstance(o, dict) and o.get('value') == 'transcriber:flawed-asr')
        self.assertTrue(flawed['disabled'])
        self.assertIn('drops distant speech', flawed['label'])
        self.assertNotIn('backend absent', flawed['label'])
        self.assertEqual('Measured on a distant interview.', flawed['title'])
        self.assertIn(['transcriber:sound-asr', 'sound-asr'], options, 'a sound model stays selectable')
