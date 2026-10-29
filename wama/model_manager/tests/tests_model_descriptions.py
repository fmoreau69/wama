"""DESCRIPTIONS of the catalogue (2026-10-29, Fabien: « à l'installation des modèles on a pas
forcément les descriptions courtes et longues », then « l'exploration de sources externes (même
web) peut permettre de combler les trous de description à minima »).

Measured that day on 666 rows: 27 generic sweep texts (« Snapshot HF … »), 14 « Ollama LLM (x GB) »,
~488 remote rows reduced to « <provider> — modèle distant (<type>) ». The sync rewrote the generic
text at every pass, so a real description could not survive; OpenRouter's own description was
thrown away. Three remedies: the sync never replaces a real description by a filler, and marks the
filler it writes; the provider's description is kept; the marked rows are filled from the model
card (or the web), summarised in French, the source recorded.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.model_manager.models import (DESCRIPTION_PLACEHOLDER_KEY, DESCRIPTION_SOURCE_KEY,
                                       AIModel, ModelSource, ModelType)
from wama.model_manager.services import model_descriptions as md
from wama.model_manager.services.model_registry import ModelInfo
from wama.model_manager.services.model_sync import ModelSyncService

KEY = 'huggingface:org/some-ocr'
FILLER = 'Snapshot HuggingFace installé (ocr/Fam), catalogué par le balayage générique.'


def _info(description=FILLER, placeholder=True, extra=None):
    return ModelInfo(id='org/some-ocr', name='some-ocr', model_type=ModelType('ocr'),
                     source=ModelSource('huggingface'), description=description,
                     description_short='Snapshot HF some-ocr', is_downloaded=True,
                     description_placeholder=placeholder, extra_info=dict(extra or {}))


class TheSyncKeepsARealDescriptionTest(TestCase):

    def test_a_filler_is_written_marked_on_a_row_that_has_nothing(self):
        ModelSyncService()._sync_model(KEY, _info())
        row = AIModel.objects.get(model_key=KEY)
        self.assertEqual(FILLER, row.description)
        self.assertTrue(row.extra_info[DESCRIPTION_PLACEHOLDER_KEY])

    def test_a_real_description_survives_the_filler_and_its_source_stays(self):
        ModelSyncService()._sync_model(KEY, _info())
        AIModel.objects.filter(model_key=KEY).update(
            description='Lit les documents imprimés.', description_short='OCR imprimé',
            extra_info={DESCRIPTION_SOURCE_KEY: {'origin': 'fiche'}})
        ModelSyncService()._sync_model(KEY, _info())
        row = AIModel.objects.get(model_key=KEY)
        self.assertEqual(('Lit les documents imprimés.', 'OCR imprimé'),
                         (row.description, row.description_short))
        self.assertNotIn(DESCRIPTION_PLACEHOLDER_KEY, row.extra_info)
        self.assertEqual({'origin': 'fiche'}, row.extra_info[DESCRIPTION_SOURCE_KEY])

    def test_a_discovery_that_knows_still_writes_its_description(self):
        # Counter-check: an app's declaration is not a filler — it keeps the authority it had.
        ModelSyncService()._sync_model(KEY, _info())
        AIModel.objects.filter(model_key=KEY).update(description='ancienne', extra_info={})
        ModelSyncService()._sync_model(KEY, _info(description='Déclaré par son app.',
                                                  placeholder=False))
        row = AIModel.objects.get(model_key=KEY)
        self.assertEqual('Déclaré par son app.', row.description)
        self.assertNotIn(DESCRIPTION_PLACEHOLDER_KEY, row.extra_info)


class GenericTextsAreMarkedTest(SimpleTestCase):

    def test_the_remote_filler_is_marked_and_a_provider_description_is_not(self):
        from wama.model_manager.services.cloud_models import model_info_for
        bare = model_info_for('openrouter', {'id': 'org/m', 'name': 'M', 'type': 'text-generation'})
        said = model_info_for('openrouter', {'id': 'org/m', 'name': 'M', 'type': 'text-generation',
                                             'description': 'A model that writes.'})
        self.assertTrue(bare.description_placeholder)
        self.assertFalse(said.description_placeholder)
        self.assertEqual('A model that writes.', said.description)

    def test_the_listing_keeps_the_provider_description(self):
        from wama.model_manager.services import cloud_models as cm
        listing = {'data': [{'id': 'org/m', 'name': 'M', 'description': '  Writes code.  ',
                             'architecture': {'input_modalities': ['text'],
                                              'output_modalities': ['text']}}]}
        response = mock.Mock(status_code=200, json=lambda: listing)
        response.raise_for_status = lambda: None
        with mock.patch('requests.get', return_value=response):
            items = cm.list_remote_models('openrouter', api_key='k')
        self.assertEqual('Writes code.', items[0]['description'])


class FillingTest(TestCase):

    def _filler_row(self):
        ModelSyncService()._sync_model(KEY, _info())
        AIModel.objects.filter(model_key=KEY).update(platform_ref='huggingface:org/some-ocr')
        return AIModel.objects.get(model_key=KEY)

    def test_a_marked_row_is_filled_from_its_card_and_says_so(self):
        row = self._filler_row()
        summary = {'short': 'Lit les documents.', 'long': 'Un OCR. Il lit des pages.'}
        with mock.patch.object(md, 'card_text', return_value='# Some OCR\nReads documents.'), \
                mock.patch.object(md, 'summarize', return_value=(summary, 'ollama:x')):
            results = md.describe_rows(apply=True)
        self.assertEqual(['fiche'], [r.get('origin') for r in results])
        row.refresh_from_db()
        self.assertEqual(('Un OCR. Il lit des pages.', 'Lit les documents.'),
                         (row.description, row.description_short))
        self.assertNotIn(DESCRIPTION_PLACEHOLDER_KEY, row.extra_info)
        self.assertEqual('fiche', row.extra_info[DESCRIPTION_SOURCE_KEY]['origin'])
        self.assertEqual([], md.rows_to_describe(), 'nothing left to fill')

    def test_without_card_nor_web_nothing_is_guessed(self):
        row = self._filler_row()
        with mock.patch.object(md, 'card_text', return_value=''), \
                mock.patch.object(md, 'summarize') as summarize:
            out = md.describe(row, apply=True, web=False)
        summarize.assert_not_called()
        self.assertIn('skipped', out)
        row.refresh_from_db()
        self.assertEqual(FILLER, row.description)

    def test_the_dry_run_writes_nothing(self):
        row = self._filler_row()
        summary = {'short': 'Lit.', 'long': 'Lit des pages.'}
        with mock.patch.object(md, 'card_text', return_value='text'), \
                mock.patch.object(md, 'summarize', return_value=(summary, 'ollama:x')):
            md.describe(row)
        row.refresh_from_db()
        self.assertEqual(FILLER, row.description)


class SummarizeTest(SimpleTestCase):

    def _answer(self, text):
        with mock.patch('wama.common.utils.llm_utils.modele_par_defaut', return_value='m'), \
                mock.patch('wama.common.utils.llm_utils.llm_chat', return_value=(text, None)):
            return md.summarize('M', 'source', 'fiche')[0]

    def test_a_valid_answer_gives_both_texts_and_a_bounded_short_line(self):
        out = self._answer('{"short": "' + 'x' * 300 + '", "long": "Une phrase."}')
        self.assertEqual(md.SHORT_CHARS, len(out['short']))
        self.assertEqual('Une phrase.', out['long'])

    def test_an_empty_or_off_topic_answer_gives_nothing(self):
        self.assertIsNone(self._answer('{}'))
        self.assertIsNone(self._answer('pas du JSON'))
