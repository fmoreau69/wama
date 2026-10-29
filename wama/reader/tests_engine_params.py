"""Les réglages que chaque moteur OCR LIT sont déclarés et arrivent au catalogue (2026-09-29).

`READER_MODELS[…]['params']` dit ce que le moteur lit réellement (mesuré dans les backends :
olmOCR le mode et la langue, GLM-OCR la langue, docTR rien) ; la découverte le recopie en
capacité canonique `params`, que l'UI lit pour griser le reste — déclaré au schéma depuis le
2026-10-13 (`cap_from` « reads », `WamaParams`), câblé à la main dans `reader.js` avant.
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
        # olmOCR v1 (mode et langue) a quitté la déclaration le 2026-10-29 (R190).
        self.assertEqual({'doctr': []}, {k: c['params'] for k, c in READER_MODELS.items()})

    def test_glm_ocr_states_its_reading_under_the_source_that_serves_it(self):
        """GLM-OCR left `READER_MODELS` on 2026-10-07 (its row lives under `ollama:`, the
        `reader:glm-ocr` row was a duplicate): what it reads — the language, measured in
        `glm_ocr_backend._ocr_image` — is now declared with its Ollama family."""
        from wama.model_manager.services.model_registry import FAMILLES_OLLAMA
        self.assertEqual(['language'], FAMILLES_OLLAMA['glm-ocr']['params'])
        self.assertNotIn('glm-ocr', READER_MODELS)

    def test_every_setting_an_engine_may_read_is_bound_to_that_reading(self):
        """The schema declares the binding (`cap_from` « reads » on the engine select), for every
        setting that SOME engine lists — the panel, the item and the batch modals follow alone."""
        # The engines that list a setting now live under their own source (GLM-OCR and the OCR
        # families served by Ollama): their declaration counts as much as the reader's own.
        from wama.model_manager.services.model_registry import FAMILLES_OLLAMA
        listed = {name for config in READER_MODELS.values() for name in config['params']}
        listed |= {name for family in FAMILLES_OLLAMA.values() if family.get('task') == 'ocr'
                   for name in family.get('params') or ()}
        self.assertTrue(listed, 'vacuous: no engine lists a setting')
        by_name = {p['name']: p for p in PARAMS_JSON}
        for name in listed:
            with self.subTest(setting=name):
                cap_from = by_name[name].get('cap_from') or {}
                self.assertEqual(('backend', 'params', 'reads'),
                                 (cap_from.get('field'), cap_from.get('capability'),
                                  cap_from.get('mode')))

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
