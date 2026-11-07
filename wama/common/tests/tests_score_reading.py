"""Reading a PRINTED SCORE — task `image-to-score` (2026-11-06, Fabien : « l'utilisateur scanne une
partition, la partition est rendue typographiée et éditable »).

What is guarded here, without the GPU nor the weights :
  • the task is declared like the two other score tasks, and the HF cards that say it map to it ;
  • its contract (`ScoreReadingBackend.read_score`) and its first engine (copisteria) resolve ;
  • the engine reads pages the WAMA way — a PDF rendered by the common brick (`pdf_pages`), every
    page copied into a WORK folder (the library writes its caches beside the page), the pages
    joined into ONE score, an empty reading refused in words ;
  • its catalogue line declares its files (installed by the `files` driver, Hub at a commit) ;
  • the common notation brick (`musicxml_score`) : pages merged, MusicXML → ABC, `.mxl` read.
The engine itself was measured on a rendered page (16/16 pitches, 0.3 GB, PROSPECTION_PIPELINE).
"""
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings

from wama.common.tests.tests_score_input import MUSICXML_CDEF, MXL_CONTAINER


def _page(steps: str, part_id: str = 'P1', extra_part: bool = False) -> str:
    """A one-measure MusicXML page whose notes are `steps` (quarters, octave 4)."""
    def part(pid):
        notes = ''.join(f'<note><pitch><step>{s}</step><octave>4</octave></pitch><duration>1</duration>'
                        f'<type>quarter</type></note>' for s in steps)
        return f'<part id="{pid}"><measure number="1">{notes}</measure></part>'
    ids = [part_id] + (['P9'] if extra_part else [])
    declared = ''.join(f'<score-part id="{i}"><part-name>{i}</part-name></score-part>' for i in ids)
    return (f'<score-partwise version="4.0"><part-list>{declared}</part-list>'
            + ''.join(part(i) for i in ids) + '</score-partwise>')


def _pdf(path: Path, pages: int = 2) -> Path:
    import fitz
    with fitz.open() as pdf:
        for n in range(pages):
            pdf.new_page(width=200, height=100).insert_text((20, 50), f'page {n + 1}')
        pdf.save(str(path))
    return path


class TheTaskSitsBesideTheOtherScoreTasksTest(SimpleTestCase):

    def test_the_task_has_its_category_its_inputs_and_no_platform_equivalent(self):
        from wama.model_manager.models import (TASK_DEFAULT_INPUTS, TASK_TO_MODEL_TYPE,
                                               TASK_TO_PLATFORM_TAGS, ModelTask, ModelType)
        task = ModelTask('image-to-score')
        self.assertEqual(ModelType.MUSIC, TASK_TO_MODEL_TYPE[task])
        self.assertEqual((('image', 'document'), ('work_file',), ()), TASK_DEFAULT_INPUTS[task])
        self.assertEqual((None, None, None, None), TASK_TO_PLATFORM_TAGS[task])

    def test_a_card_that_says_optical_music_recognition_is_read_as_this_task(self):
        """Transcoda publishes `text-generation` and carries `image-to-text` : without the card
        rule it entered the OCR."""
        from wama.model_manager.services.prospector import hf_task_to_wama
        self.assertEqual(('image-to-score', 'music'), hf_task_to_wama(
            'text-generation', ['image-to-text', 'omr', 'optical-music-recognition']))
        self.assertEqual('ocr', hf_task_to_wama('image-to-text', ['ocr'])[0],
                         'counter-proof : a plain OCR card stays an OCR')

    def test_the_contract_is_declared_and_copisteria_serves_it(self):
        from wama.common.backends.copisteria_backend import CopisteriaBackend
        from wama.common.backends.manager import backend_for_engine
        from wama.common.backends.score_reading_base import ScoreReadingBackend
        from wama.common.services.backend_inventory import TASK_CONTRACTS
        self.assertEqual(('score_reading_base', 'ScoreReadingBackend', False),
                         TASK_CONTRACTS['image-to-score'])
        self.assertIs(CopisteriaBackend, backend_for_engine('copisteria'))
        self.assertTrue(issubclass(CopisteriaBackend, ScoreReadingBackend))
        self.assertTrue(CopisteriaBackend.VENDORED, 'its code comes from the vendored route')
        self.assertEqual([], CopisteriaBackend.pip_install_spec(), 'nothing to pip')


class TheEngineReadsPagesTheWamaWayTest(SimpleTestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='score_reading_'))
        self.addCleanup(__import__('shutil').rmtree, self.tmp, True)

    def test_a_pdf_becomes_one_png_per_page_in_the_work_folder(self):
        from wama.common.backends.copisteria_backend import CopisteriaBackend
        work = self.tmp / 'work'
        work.mkdir()
        pages = CopisteriaBackend._pages(str(_pdf(self.tmp / 'score.pdf', 3)), work)
        self.assertEqual(3, len(pages))
        self.assertTrue(all(p.parent == work and p.suffix == '.png' for p in pages))

    def test_an_image_is_copied_grey_and_the_original_is_never_read_in_place(self):
        from PIL import Image
        from wama.common.backends.copisteria_backend import CopisteriaBackend
        source = self.tmp / 'scan.jpg'
        Image.new('RGB', (40, 20), 'white').save(source)
        work = self.tmp / 'work'
        work.mkdir()
        (page,) = CopisteriaBackend._pages(str(source), work)
        self.assertEqual(work, page.parent)
        self.assertEqual('L', Image.open(page).mode)
        with self.assertRaisesMessage(ValueError, 'image ou d'):
            CopisteriaBackend._pages(str(self.tmp / 'notes.txt'), work)

    def _read(self, pages_read):
        """`read_score` with the library stood in : each page reads as the next text given."""
        from wama.common.backends.copisteria_backend import CopisteriaBackend
        engine = CopisteriaBackend()
        engine._model = object()
        seen = []

        def transcribe(png, model, device='cpu'):
            seen.append(Path(png))
            return pages_read[len(seen) - 1]
        library = mock.Mock(transcribe=transcribe)
        with mock.patch.object(CopisteriaBackend, '_library', return_value=(library, None)):
            return engine.read_score('copisteria', str(_pdf(self.tmp / 'two.pdf', len(pages_read)))), seen

    def test_the_pages_are_read_in_order_and_joined_into_one_score(self):
        import xml.etree.ElementTree as ET
        score, seen = self._read([_page('CD'), _page('EF')])
        self.assertEqual(['page_0000', 'page_0001'], [p.stem for p in seen])
        self.assertFalse(any(p.exists() for p in seen), 'the work folder is gone after the reading')
        measures = ET.fromstring(score).find('part').findall('measure')
        self.assertEqual(['1', '2'], [m.get('number') for m in measures])

    def test_a_reading_without_any_note_is_refused_in_words(self):
        with self.assertRaisesMessage(ValueError, 'Aucune note lue'):
            self._read([_page('')])

    def test_the_detector_the_library_reads_is_the_declared_file(self):
        """The library looks for its weights in its repository's `models/` folder : the backend
        points its table at the model folder — never an environment variable of the process."""
        import os
        from wama.common.backends import copisteria_backend as cb
        folder = self.tmp / 'model'
        (folder / 'small').mkdir(parents=True)
        for f in cb.COPISTERIA_FILES:
            (folder / f['path']).write_bytes(b'x')
        with override_settings(MODEL_PATHS={'music': {'copisteria': folder}}):
            if not (cb.CopisteriaBackend.vendor_dir() / 'src' / 'copisteria').exists():
                self.skipTest('vendored copisteria absent (manage.py install_library copisteria)')
            paths = cb.CopisteriaBackend.import_vendored('copisteria.paths', subdir='src')
            saved = dict(paths.DETECTORS), paths.DETECTOR
            self.addCleanup(lambda: (setattr(paths, 'DETECTORS', saved[0]),
                                     setattr(paths, 'DETECTOR', saved[1])))
            cb.CopisteriaBackend._library()
            self.assertEqual((folder / cb.DETECTOR, 'v7'), paths.detector())
        self.assertNotIn('COPISTERIA_DETECTOR', os.environ)


class TheCatalogueLineNamesItsFilesTest(SimpleTestCase):

    def test_the_line_exists_absent_and_names_its_pinned_files(self):
        from wama.model_manager.services.model_registry import ModelRegistry
        with tempfile.TemporaryDirectory() as tmp, \
                override_settings(MODEL_PATHS={'music': {'copisteria': Path(tmp)}}):
            registry = ModelRegistry()
            registry._models, registry.discovery_errors = {}, []
            registry._discover_score_reading_models()
        self.assertEqual([], registry.discovery_errors)
        line = registry._models['huggingface:kobimusic/copisteria']
        self.assertFalse(line.is_downloaded)
        self.assertEqual('image-to-score', line.capabilities['task'])
        self.assertEqual({'engine': 'copisteria'}, line.composition['runtime'])
        files = line.extra_info['declared_files']
        self.assertEqual({'evidence-2m.pt', 'small/v7_obj-recall-30m_best.pt'},
                         {f['path'] for f in files})
        self.assertTrue(all(f['origin']['revision'] and len(f['sha256']) == 64 for f in files))


class TheMusicxmlBrickTest(SimpleTestCase):

    def test_pages_are_merged_part_by_part_with_their_measures_renumbered(self):
        import xml.etree.ElementTree as ET
        from wama.common.utils.musicxml_score import merge_pages
        root = ET.fromstring(merge_pages([_page('CD'), _page('EF', part_id='P7', extra_part=True)]))
        first = root.findall('part')[0].findall('measure')
        self.assertEqual(['1', '2'], [m.get('number') for m in first])
        self.assertEqual('yes', first[1].find('print').get('new-page'))
        self.assertEqual(['P1', 'P2'], [sp.get('id') for sp in root.find('part-list')])
        self.assertEqual(2, len(root.findall('part')), 'a part only the second page has is added')

    def test_one_page_is_returned_as_it_is_and_none_is_refused(self):
        from wama.common.utils.musicxml_score import merge_pages
        self.assertEqual(_page('C'), merge_pages([_page('C')]))
        with self.assertRaises(ValueError):
            merge_pages(['', '  '])

    def test_musicxml_becomes_abc_with_its_title(self):
        from wama.common.utils.musicxml_score import musicxml_to_abc
        abc = musicxml_to_abc(MUSICXML_CDEF, title='Scan #7')
        self.assertIn('T:Scan #7', abc)
        self.assertIn('C D E F', abc)
        self.assertIn('K:C', abc)

    def test_a_compressed_mxl_is_read_through_its_container(self):
        import zipfile
        from wama.common.utils.musicxml_score import read_musicxml
        with tempfile.TemporaryDirectory() as tmp:
            mxl = Path(tmp, 'tune.mxl')
            with zipfile.ZipFile(mxl, 'w') as archive:
                archive.writestr('META-INF/container.xml', MXL_CONTAINER)
                archive.writestr('score.xml', MUSICXML_CDEF)
            self.assertEqual(MUSICXML_CDEF, read_musicxml(mxl))


class PdfPagesBrickTest(SimpleTestCase):
    """`common/utils/pdf_pages` — the conversion GLM-OCR and olmOCR each kept a copy of."""

    def test_each_page_is_written_in_the_given_folder_in_order(self):
        from wama.common.utils.pdf_pages import pdf_page_images
        with tempfile.TemporaryDirectory() as tmp:
            pages = pdf_page_images(str(_pdf(Path(tmp) / 'doc.pdf', 2)), tmp, dpi=50)
            self.assertEqual(['page_0000.png', 'page_0001.png'], [Path(p).name for p in pages])
            self.assertTrue(all(Path(p).parent == Path(tmp) for p in pages))

    def test_olmocr_reads_its_pages_from_the_brick_and_leaves_no_folder(self):
        from wama.common.backends.olmocr_backend import OlmOCRBackend
        before = set(Path(tempfile.gettempdir()).glob('olmocr_pages_*'))
        with tempfile.TemporaryDirectory() as tmp:
            images = OlmOCRBackend._pdf_to_images(None, _pdf(Path(tmp) / 'doc.pdf', 2))
        self.assertEqual(2, len(images))
        self.assertEqual('RGB', images[0].mode)
        self.assertEqual(before, set(Path(tempfile.gettempdir()).glob('olmocr_pages_*')))
