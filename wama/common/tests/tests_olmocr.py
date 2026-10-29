"""olmOCR-2 served by the olmOCR backend (2026-10-29, decision of Fabien: « olmOCR v1 → v2 »).

The installed olmOCR was v1 « preview » (Feb. 2025) under the name « olmOCR-2 », read with a home-made
instruction. olmOCR-2 (`allenai/olmOCR-2-7B-1025`, Qwen2.5-VL, 82.3 on olmOCR-Bench) is installed by
the route from its successor proposal ; the backend reads it the way its author trained it:
  * the row it is handed decides the repository and the weights folder (`catalogue_key`) ;
  * the page at 1288 px on its longest side, the toolkit's v4 instruction, the instruction first ;
  * the YAML header of the answer is removed — the OCR contract returns the text READ ;
  * the v1 line is retired (R190): with no handed row, there is nothing to load.
"""
from unittest import mock

from django.test import SimpleTestCase, TestCase

from wama.common.backends import olmocr_backend as ob
from wama.model_manager.models import AIModel

V2 = 'huggingface:allenai/olmOCR-2-7B-1025'


class TheAnswerIsTheTextReadTest(SimpleTestCase):

    def test_the_yaml_header_is_removed(self):
        answer = ('---\nprimary_language: fr\nis_rotation_valid: True\nrotation_correction: 0\n'
                  'is_table: False\nis_diagram: False\n---\n# Titre\n\nUn paragraphe.')
        self.assertEqual('# Titre\n\nUn paragraphe.', ob.without_front_matter(answer))
        # Counter-tests: no header, or an unclosed one, leave the text as is.
        self.assertEqual('Un texte.', ob.without_front_matter('Un texte.'))
        self.assertEqual('---\nlangue: fr', ob.without_front_matter('---\nlangue: fr'))

    def test_the_page_is_fitted_to_the_trained_size(self):
        from PIL import Image
        fitted = ob._fit_longest_side(Image.new('RGB', (1848, 4000)), 1288)
        self.assertEqual(1288, max(fitted.size))
        self.assertEqual(round(1848 * 1288 / 4000), fitted.size[0])

    def test_the_instruction_is_the_one_of_the_toolkit(self):
        """Word for word from `build_no_anchoring_v4_yaml_prompt()` (olmocr ≥ 0.4) — the model
        was trained on it ; « LateX » is in the original."""
        self.assertTrue(ob.OLMOCR_V4_YAML_PROMPT.startswith(
            'Attached is one page of a document that you must process. '))
        self.assertIn('Convert equations to LateX and tables to HTML.\n', ob.OLMOCR_V4_YAML_PROMPT)
        self.assertTrue(ob.OLMOCR_V4_YAML_PROMPT.endswith(
            'primary_language, is_rotation_valid, rotation_correction, is_table, and is_diagram '
            'parameters.'))


class EachModelIsReadItsWayTest(TestCase):

    def _engine(self, key):
        engine = ob.OlmOCRBackend()
        engine.catalogue_key = key
        return engine

    def test_the_handed_row_gives_the_repository_and_the_route_folder(self):
        AIModel.objects.create(model_key=V2, name='olmOCR-2-7B-1025', model_type='ocr',
                               source='huggingface',
                               platform_ref='huggingface:allenai/olmOCR-2-7B-1025')
        from pathlib import Path
        installed = Path('/models/ocr/olmOCR-2-7B-1025/models--allenai--olmOCR-2-7B-1025')
        with mock.patch('wama.model_manager.services.model_installer.weights_dir_of',
                        return_value=installed):
            repo, cache_dir = self._engine(V2)._weights()
        self.assertEqual(('allenai/olmOCR-2-7B-1025', str(installed.parent)), (repo, cache_dir))

    def test_olmocr_2_is_read_with_its_instruction_its_size_and_its_sampling(self):
        engine = self._engine(V2)
        seen = {}

        class Processor:
            def apply_chat_template(self, messages, **kw):
                seen['content'] = messages[0]['content']
                return 'prompt'

            def __call__(self, text, images, **kw):
                seen['size'] = images[0].size
                return _Inputs()

            def decode(self, ids, **kw):
                return '---\nprimary_language: fr\n---\nTexte lu.'

        class Model:
            device = 'cpu'

            def generate(self, **kw):
                seen['generate'] = kw
                return [[0, 1, 2]]

        engine._processor, engine._model = Processor(), Model()
        from PIL import Image
        text = engine._process_image(Image.new('RGB', (2000, 1000)), 'handwritten', 'fr')
        self.assertEqual('Texte lu.', text)
        self.assertEqual(['text', 'image'], [c['type'] for c in seen['content']])
        self.assertEqual(ob.OLMOCR_V4_YAML_PROMPT, seen['content'][0]['text'])
        self.assertEqual((1288, 644), seen['size'])
        self.assertEqual((True, 0.1, 8000), (seen['generate']['do_sample'],
                                             seen['generate']['temperature'],
                                             seen['generate']['max_new_tokens']))

    def test_without_a_handed_row_there_is_nothing_to_load(self):
        """v1 retired (R190): its declaration was the fallback of a backend handed no row."""
        self.assertNotIn('olmocr', ob.OlmOCRBackend.SUPPORTED_MODELS)
        for key in ('', 'reader:olmocr'):
            with self.subTest(key=key), self.assertRaises(ValueError):
                self._engine(key)._weights()
        self.assertEqual({}, self._engine('reader:olmocr')._served())


class _Inputs(dict):
    def __init__(self):
        super().__init__(input_ids=_Ids())

    def to(self, device):
        return self


class _Ids:
    shape = (1, 1)
