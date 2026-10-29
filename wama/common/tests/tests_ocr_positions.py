"""The OCR that gives the PLACE of what it reads (2026-10-29, ROADMAP §10.B / §16.4bis): a flag of the
engine (`supports_text_positions`) and a method kept for the engines that declare it
(`OCRBackend.read_lines`) — the pattern of `supports_score_planning` / `plan_score`.

Measured the same day on a 150 dpi scan of two pages of a real article (native lines as truth):
docTR finds 44/46 and 54/57 lines, same text in median; its own grouping into blocks mixes two
paragraphs too often, hence lines in the contract, not blocks.
"""
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from wama.common.backends.base import BaseModelBackend
from wama.common.backends.doctr_backend import DocTRBackend
from wama.common.backends.ocr_base import OCRBackend


def _word(value, geometry, confidence=0.9):
    return SimpleNamespace(value=value, geometry=geometry, confidence=confidence)


def _result(*lines):
    """A docTR result of ONE page made of `lines` (docTR puts them in one block by default)."""
    block = SimpleNamespace(lines=[SimpleNamespace(geometry=g, words=w) for g, w in lines])
    return SimpleNamespace(pages=[SimpleNamespace(blocks=[block])])


class _TextOnlyOCR(OCRBackend):
    ENGINE = 'text-only-ocr'

    def load(self, model=None):
        return True

    @property
    def is_loaded(self):
        return True

    def unload(self):
        pass

    def run(self, work_file, mode='auto', language='', progress_callback=None, on_partial=None):
        return 'text'


class TheFlagBelongsToTheEngineTest(SimpleTestCase):

    def test_the_common_contract_promises_nothing_and_the_vocabulary_names_it(self):
        from wama.common.utils.model_capabilities import CANONICAL_CAPABILITIES
        self.assertIs(BaseModelBackend.supports_text_positions, False)
        self.assertIn('supports_text_positions', CANONICAL_CAPABILITIES)

    def test_doctr_has_it_and_the_vision_engines_do_not(self):
        from wama.common.backends.glm_ocr_backend import GlmOcrBackend
        from wama.common.backends.olmocr_backend import OlmOCRBackend
        from wama.common.utils.model_capabilities import declared_engine_flag
        self.assertIs(declared_engine_flag(DocTRBackend, 'supports_text_positions'), True)
        for cls in (GlmOcrBackend, OlmOCRBackend):
            with self.subTest(engine=cls.__name__):
                self.assertFalse(cls.supports_text_positions)

    def test_an_engine_without_the_flag_says_so_instead_of_an_empty_page(self):
        with self.assertRaisesMessage(NotImplementedError, 'supports_text_positions'):
            _TextOnlyOCR().read_lines('/scan.pdf')

    def test_the_contract_keeps_one_work_method(self):
        """`read_lines` is concrete: an abstract second method would make the common launch door
        refuse the OCR contract as ambiguous (`manager._work_method`)."""
        from wama.common.backends import manager
        self.assertEqual('run', manager._work_method(DocTRBackend))


class DoctrPlacesTest(SimpleTestCase):

    def test_relative_boxes_become_page_points_line_by_line(self):
        result = _result(
            (((0.1, 0.1), (0.5, 0.12)), [_word('Hello', ((0.1, 0.1), (0.25, 0.12)), 0.8),
                                         _word('world', ((0.3, 0.1), (0.5, 0.12)), 1.0)]),
            (((0.1, 0.2), (0.3, 0.22)), []),     # a line without words is not a line
        )
        pages = DocTRBackend._positioned(result, [(600.0, 800.0, 'pt')])
        self.assertEqual(1, len(pages))
        page = pages[0]
        self.assertEqual((600.0, 800.0, 'pt'), (page['width'], page['height'], page['unit']))
        self.assertEqual(1, len(page['lines']))
        line = page['lines'][0]
        self.assertEqual([60.0, 80.0, 300.0, 96.0], line['bbox'])
        self.assertEqual('Hello world', line['text'])
        self.assertEqual(0.9, line['conf'])
        self.assertEqual({'bbox': [60.0, 80.0, 150.0, 96.0], 'text': 'Hello', 'conf': 0.8},
                         line['words'][0])

    def test_a_rotated_word_gives_the_box_that_encloses_its_polygon(self):
        polygon = ((0.2, 0.1), (0.4, 0.15), (0.38, 0.2), (0.18, 0.15))
        result = _result((polygon, [_word('tilted', polygon)]))
        line = DocTRBackend._positioned(result, [(100, 200, 'px')])[0]['lines'][0]
        self.assertEqual([18.0, 20.0, 40.0, 40.0], line['bbox'])

    def test_read_lines_gives_the_places_and_run_still_gives_the_text(self):
        result = _result((((0.1, 0.1), (0.5, 0.12)), [_word('Hello', ((0.1, 0.1), (0.5, 0.12)))]))
        backend = DocTRBackend()
        with mock.patch.object(DocTRBackend, '_predict', return_value=(result, [(10, 10, 'px')])):
            pages = backend.read_lines('/scan.png')
            partial = []
            text = backend.run('/scan.png', on_partial=partial.append)
        self.assertEqual('Hello', pages[0]['lines'][0]['text'])
        self.assertEqual('Hello', text)
        self.assertEqual(['Hello'], partial)
