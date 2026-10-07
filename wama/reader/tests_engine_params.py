"""Les réglages que chaque moteur OCR LIT sont déclarés et arrivent au catalogue (2026-09-29).

`READER_MODELS[…]['params']` dit ce que le moteur lit réellement (mesuré dans les backends :
olmOCR le mode et la langue, GLM-OCR la langue, docTR rien) ; la découverte le recopie en
capacité canonique `params`, que l'UI lit pour griser le reste (`WamaModelCaps`, reader.js).
Un nom mal orthographié griserait un réglage que le moteur lit, sans que rien ne le signale.
"""
from django.test import SimpleTestCase

from wama.reader.params import PARAMS_JSON
from wama.reader.utils.model_config import READER_MODELS


class EngineParamsTest(SimpleTestCase):

    def test_every_engine_lists_names_of_the_reader_schema(self):
        schema = {p['name'] for p in PARAMS_JSON}
        for key, config in READER_MODELS.items():
            with self.subTest(engine=key):
                self.assertIn('params', config, f'{key} ne dit pas quels réglages il lit')
                self.assertLessEqual(set(config['params']), schema,
                                     f'{key} : nom hors schéma du reader')

    def test_the_measured_reading_of_each_backend(self):
        """Ce que les backends lisent, mesuré le 2026-09-29 : le changer exige de relire le
        backend concerné, pas de retoucher cette liste pour faire passer le test."""
        self.assertEqual({'olmocr': ['mode', 'language'], 'doctr': []},
                         {k: c['params'] for k, c in READER_MODELS.items()})

    def test_glm_ocr_declares_its_reading_under_the_source_that_serves_it(self):
        """GLM-OCR left `READER_MODELS` on 2026-10-07 (its row lives under `ollama:`, the
        `reader:glm-ocr` row was a duplicate): what it reads — the language, measured in
        `glm_ocr_backend._ocr_image` — is now declared with its Ollama family."""
        from wama.model_manager.services.model_registry import FAMILLES_OLLAMA
        self.assertEqual(['language'], FAMILLES_OLLAMA['glm-ocr']['params'])
        self.assertNotIn('glm-ocr', READER_MODELS)

    def test_the_discovery_carries_params_into_the_capabilities(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        registry = object.__new__(ModelRegistry)       # hors singleton, sans `__init__`
        registry._models = {}
        registry.discovery_errors = []
        registry._discover_reader_models()
        for key, config in READER_MODELS.items():
            with self.subTest(engine=key):
                self.assertEqual(config['params'],
                                 registry._models[f'reader:{key}'].capabilities.get('params'))
