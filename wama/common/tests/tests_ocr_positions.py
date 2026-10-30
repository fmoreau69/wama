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


class _Ctx:
    """The task context a glue receives (`task_skeleton`), reduced to what `ocr_step` uses."""

    def __init__(self, folder):
        self.folder, self.models, self.said = folder, [], []

    def console(self, message):
        self.said.append(message)

    def progress(self, *args):
        pass

    def ensure_model(self, key):
        self.models.append(key)

    def output_place(self, ext, source_name=''):
        path = self.folder / f'{source_name}{ext}'
        return str(path), str(path)


class OcrStepTest(SimpleTestCase):
    """The common glue of the « OCR of scanned pages » process (`ocr_process.ocr_step`, 2026-10-29),
    on the pattern of `output_process.output_step`."""

    def setUp(self):
        import shutil
        import tempfile
        from pathlib import Path
        import fitz
        self.dir = Path(tempfile.mkdtemp(prefix='wama-ocr-step-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 100), 'A native page with plenty of selectable text.')
            pixmap = pdf[0].get_pixmap(dpi=40)
            pdf.save(str(self.dir / 'native.pdf'))
            scan = pdf.new_page()
            scan.insert_image(scan.rect, pixmap=pixmap)
            pdf.save(str(self.dir / 'mixed.pdf'))

    def _item(self, name):
        from types import SimpleNamespace
        return SimpleNamespace(source_document=SimpleNamespace(path=str(self.dir / name)),
                               user=None, pk=1, ocr_file=None)

    def test_a_native_document_costs_nothing_and_stores_nothing(self):
        from wama.common.services.ocr_process import ocr_step
        ctx = _Ctx(self.dir)
        with mock.patch('wama.common.services.ocr_process.positioned_ocr_keys') as keys:
            result = ocr_step('source_document', 'ocr_file')(self._item('native.pdf'), ctx)
        self.assertEqual({'ocr_file': None}, result['fields'])
        keys.assert_not_called()
        self.assertEqual([], ctx.models, 'no engine is loaded for nothing')

    def test_only_the_pages_without_text_are_read_and_the_next_process_gets_them(self):
        from types import SimpleNamespace
        from wama.common.services.ocr_process import ocr_step, read_ocr_file
        page = {'width': 595, 'height': 842, 'unit': 'pt',
                'lines': [{'bbox': [72, 90, 300, 105], 'text': 'scanned', 'conf': 0.9, 'words': []}]}
        engine = SimpleNamespace(read_lines=lambda path: [page])
        ctx = _Ctx(self.dir)
        with mock.patch('wama.common.services.ocr_process.positioned_ocr_keys',
                        return_value=['reader:doctr']), \
                mock.patch('wama.common.utils.auto_model.resolve_model_choice',
                           return_value='reader:doctr'), \
                mock.patch('wama.common.backends.manager.backend_instance_for_key',
                           return_value=engine):
            result = ocr_step('source_document', 'ocr_file')(self._item('mixed.pdf'), ctx)
        self.assertEqual(['reader:doctr'], ctx.models)
        item = self._item('mixed.pdf')
        item.ocr_file = SimpleNamespace(path=result['fields']['ocr_file'])
        self.assertEqual({'1': page}, read_ocr_file(item, 'ocr_file'), 'page 1 only, as JSON keys')

    def test_without_an_engine_that_gives_places_it_says_so(self):
        from wama.common.services.ocr_process import ocr_step
        with mock.patch('wama.common.services.ocr_process.positioned_ocr_keys', return_value=[]):
            with self.assertRaisesMessage(RuntimeError, 'place du texte'):
                ocr_step('source_document', 'ocr_file')(self._item('mixed.pdf'), _Ctx(self.dir))

    def test_the_engines_kept_are_those_whose_engine_gives_places(self):
        from wama.common.services import ocr_process
        from wama.common.backends.glm_ocr_backend import GlmOcrBackend
        rows = mock.Mock()
        rows.values_list.return_value = ['ollama:glm-ocr:latest', 'reader:doctr']
        backends = {'ollama:glm-ocr:latest': GlmOcrBackend, 'reader:doctr': DocTRBackend}
        with mock.patch('wama.model_manager.models.AIModel.objects.filter', return_value=rows), \
                mock.patch('wama.common.backends.manager.backend_for_key', side_effect=backends.get):
            self.assertEqual(['reader:doctr'], ocr_process.positioned_ocr_keys())


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
