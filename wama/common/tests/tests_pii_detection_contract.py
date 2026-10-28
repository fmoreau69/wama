"""The `pii-detection` task, written BEFORE its detectors (ROADMAP §16.4bis, 2026-10-28).

What is held here, without any model : the contract is declared and binding, the common vocabulary
gives the bracket label in the text's language, the catalogue knows the task and its category, the
prospection reads a PII model from its card tags (and only then), and the contract's smoke judges a
detector — green on a sound fake, red on one that answers outside the vocabulary or the text.
"""
import importlib
from pathlib import Path

from django.test import SimpleTestCase

FAKE_DETECTOR = '''
import re
from .pii_detection_base import PIIDetectionBackend


class FakeDetector(PIIDetectionBackend):
    ENTITY_MAP = {"mail": "EMAIL_ADDRESS", "name": "PERSON"}

    def load(self, model_id, **kwargs):
        self._loaded = True
        return True

    def unload(self):
        self._loaded = False

    def detect_entities(self, model_id, text, language, entities=None, threshold=None):
        found = [{"start": m.start(), "end": m.end(), "entity": "EMAIL_ADDRESS", "score": 0.9}
                 for m in re.finditer(r"[\\w.]+@[\\w.]+\\.\\w+", text)]
        found += [{"start": m.start(), "end": m.end(), "entity": __NAME_ENTITY__, "score": 0.8}
                  for m in re.finditer(r"(Marie Dubois|John Smith)", text)]
        return found
'''


class ContractTest(SimpleTestCase):

    def test_the_task_has_a_binding_contract_with_its_method(self):
        from wama.common.services.backend_inventory import TASK_CONTRACTS
        module, cls, binding = TASK_CONTRACTS['pii-detection']
        contract = getattr(importlib.import_module(f'wama.common.backends.{module}'), cls)
        self.assertTrue(binding)
        self.assertIn('detect_entities', contract.__abstractmethods__)

    def test_process_delegates_to_detect_entities(self):
        from wama.common.backends.pii_detection_base import PIIDetectionBackend

        class Detector(PIIDetectionBackend):
            def load(self, model_id, **kwargs):
                return True

            def unload(self):
                pass

            def detect_entities(self, **kwargs):
                return [{'start': 0, 'end': 4, 'entity': 'PERSON', 'score': 1.0}]

        self.assertEqual('PERSON', Detector().process(model_id='m', text='Anne', language='fr')[0]['entity'])


class VocabularyTest(SimpleTestCase):

    def test_the_bracket_label_follows_the_language_and_falls_back_to_english(self):
        from wama.common.privacy.entities import label_for
        self.assertEqual('[PERSONNE]', label_for('PERSON', 'fr'))
        self.assertEqual('[PERSON]', label_for('PERSON', 'en-GB'))
        self.assertEqual('[PERSON]', label_for('PERSON', 'de'))

    def test_a_type_outside_the_vocabulary_is_an_error(self):
        from wama.common.privacy.entities import label_for
        with self.assertRaises(KeyError):
            label_for('FAVOURITE_COLOUR', 'fr')


class CatalogueTest(SimpleTestCase):

    def test_the_task_is_anchored_in_the_nlp_category(self):
        from wama.model_manager.models import (
            TASK_DEFAULT_INPUTS, ModelTask, ModelType, model_type_for_task, platform_tag)
        self.assertEqual(ModelType.NLP, model_type_for_task('pii-detection'))
        self.assertEqual('token-classification', platform_tag('pii-detection'))
        self.assertIn('document', TASK_DEFAULT_INPUTS[ModelTask.PII_DETECTION][0])

    def test_the_prospection_reads_a_pii_model_from_its_card_tags_only(self):
        from wama.model_manager.services.prospector import hf_task_to_wama
        # Measured on the cards on 2026-10-28 (bardsai, knowledgator — `PII` upper-case).
        self.assertEqual(('pii-detection', 'nlp'),
                         hf_task_to_wama('token-classification', ['pii-detection', 'privacy']))
        self.assertEqual(('pii-detection', 'nlp'),
                         hf_task_to_wama('token-classification', ['NER', 'PII']))
        # Counter-proof : a general NER (camembert-ner) gets the category, never an invented task.
        self.assertEqual((None, 'nlp'), hf_task_to_wama('token-classification', ['camembert', 'fr']))


class SmokeTest(SimpleTestCase):

    def _smoke(self, entity):
        from wama.common.services.backend_proposals import SMOKES
        code = FAKE_DETECTOR.replace('__NAME_ENTITY__', repr(entity))
        return SMOKES['PIIDetectionBackend'](code, module='fake_pii_backend',
                                             model_key='huggingface:org/fake-pii',
                                             out_dir=Path('unused'))

    def test_a_sound_detector_passes(self):
        out = self._smoke('PERSON')
        self.assertTrue(out['ok'], out)
        self.assertEqual(4, len(out['covered']))

    def test_a_detector_answering_outside_the_vocabulary_fails(self):
        out = self._smoke('FIRST_NAME')
        self.assertFalse(out['ok'])
        self.assertIn('hors vocabulaire', out['error'])
