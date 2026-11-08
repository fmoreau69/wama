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

        def transcribe(png, model, texts=None, device='cpu'):
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


# ── 2026-11-08 : the photographed DRUM pages of Fabien — « x3 », titles, tilted photos ─────────

def _measures(words_at=None, forward_at=None, words='repeat 3', empty_part=False) -> str:
    """A three-measure, one-part score (four quarters each) ; `words` written in measure
    `words_at`, a forward repeat bar line opening measure `forward_at` ; `empty_part` adds a second
    part whose measure 2 holds nothing (a staff that system hides)."""
    def measure(n, with_notes=True):
        body = ''
        if n == 1:
            body += ('<attributes><divisions>1</divisions><time><beats>4</beats><beat-type>4</beat-type>'
                     '</time><clef><sign>G</sign><line>2</line></clef></attributes>')
        if n == forward_at:
            body += '<barline location="left"><repeat direction="forward"/></barline>'
        if n == words_at:
            body += (f'<direction placement="above"><direction-type><words>{words}</words>'
                     '</direction-type></direction>')
        if with_notes:
            body += ''.join('<note><pitch><step>C</step><octave>5</octave></pitch><duration>1</duration>'
                            '<type>quarter</type></note>' for _ in range(4))
        return f'<measure number="{n}">{body}</measure>'
    parts = [('P1', (1, 2, 3))] + ([('P2', (1, 3))] if empty_part else [])
    declared = ''.join(f'<score-part id="{p}"><part-name>{p}</part-name></score-part>' for p, _ in parts)
    body = ''.join(f'<part id="{p}">' + ''.join(measure(n, n in filled) for n in (1, 2, 3)) + '</part>'
                   for p, filled in parts)
    return f'<score-partwise version="4.0"><part-list>{declared}</part-list>{body}</score-partwise>'


def _repeats(text):
    """`{(part, measure number): [(location, direction, times)]}` of a MusicXML text."""
    import xml.etree.ElementTree as ET
    out = {}
    for part in ET.fromstring(text.encode('utf-8')).findall('part'):
        for m in part.findall('measure'):
            for b in m.findall('barline'):
                for r in b.findall('repeat'):
                    out.setdefault((part.get('id'), m.get('number')), []).append(
                        (b.get('location'), r.get('direction'), r.get('times')))
    return out


class AMeasurePlayedSeveralTimesTest(SimpleTestCase):
    """« x3 » over a measure : the author did not write it out three times (Fabien, 2026-11-08)."""

    def test_the_count_is_read_in_its_written_and_misread_forms(self):
        from wama.common.utils.musicxml_score import repeat_count
        for text, times in (('x3', 3), ('×2', 2), ('4x', 4), ('X 3', 3), ('XZ', 2), ('x12', 12)):
            self.assertEqual(times, repeat_count(text), text)
        for text in ('x1', 'x40', 'x', 'Drum', 'S8 second', '3', ''):
            self.assertIsNone(repeat_count(text), text)

    def test_the_counted_measure_becomes_a_repeat_played_that_many_times(self):
        from wama.common.utils.musicxml_score import apply_repeat_counts
        out = apply_repeat_counts(_measures(words_at=2))
        self.assertEqual({('P1', '2'): [('left', 'forward', None), ('right', 'backward', '3')]},
                         _repeats(out))
        self.assertIn('<words>×3</words>', out, 'the page showed « ×3 » : it stays written')
        self.assertNotIn('repeat 3', out)

    def test_an_opened_repeat_takes_everything_up_to_the_count(self):
        from wama.common.utils.musicxml_score import apply_repeat_counts
        out = _repeats(apply_repeat_counts(_measures(words_at=3, forward_at=2)))
        self.assertEqual([('left', 'forward', None)], out[('P1', '2')])
        self.assertEqual([('right', 'backward', '3')], out[('P1', '3')])
        self.assertNotIn(('P1', '1'), out)

    def test_a_score_without_a_count_is_returned_as_it_is(self):
        from wama.common.utils.musicxml_score import apply_repeat_counts
        page = _measures(words_at=2, words='dolce')
        self.assertIs(page, apply_repeat_counts(page))

    def test_an_empty_measure_of_another_part_receives_no_repeat_and_the_abc_converts(self):
        from wama.common.utils.musicxml_score import apply_repeat_counts, musicxml_to_abc
        out = apply_repeat_counts(_measures(words_at=2, empty_part=True))
        self.assertNotIn(('P2', '2'), _repeats(out))
        abc = musicxml_to_abc(out, title='Groove')
        self.assertIn('|:', abc)
        self.assertIn(':|', abc)
        self.assertIn('×3', abc)


class AClefOnAStaffWithoutNotesTest(SimpleTestCase):

    def test_the_abc_converts_where_xml2abc_alone_gave_nothing(self):
        """Measured 2026-11-08 on a handwritten drum page : a clef change on a staff of a part that
        holds no note there made `xml2abc` raise (`stfMap`), and the whole score was lost."""
        from abc_xml_converter.xml2abc import vertaal
        from wama.common.utils.musicxml_score import musicxml_to_abc
        page = _measures().replace(
            '<measure number="2">',
            '<measure number="2"><attributes><clef number="2"><sign>F</sign><line>4</line></clef>'
            '</attributes>', 1)
        abc, _ = vertaal(page)
        self.assertNotIn('K:', abc or '', 'counter-proof : the converter alone loses the score')
        self.assertIn('K:', musicxml_to_abc(page))


def _ocr_page(*lines, width=1000, height=1400):
    """A page in the form of `OCRBackend.read_lines` : `(text, x0, y0, x1, y1)` lines."""
    return {'width': width, 'height': height, 'unit': 'px',
            'lines': [{'text': t, 'bbox': [x0, y0, x1, y1], 'conf': 0.95} for t, x0, y0, x1, y1 in lines]}


class TheTextOfAScorePageTest(SimpleTestCase):
    """Roles given by PLACE and SIZE — the lines docTR returned on « Nothing Else Matters »."""

    PAGE = _ocr_page(('Nothing Else Matters', 350, 50, 650, 90), ('Metallica', 820, 48, 960, 75),
                     ('2', 970, 52, 985, 75),
                     ('Bass Drum', 140, 120, 220, 140), ('Tom Toms', 780, 120, 870, 140),
                     ('2', 600, 160, 615, 180),
                     ('x3', 500, 700, 530, 720), ('S8 second', 30, 260, 150, 290),
                     ('2012 Tomas Chmura', 400, 1340, 600, 1365),
                     ('XX', 10, 400, 30, 420))

    def test_each_line_gets_its_role(self):
        from wama.common.utils.score_page import text_roles
        page = dict(self.PAGE)
        page['lines'] = page['lines'][:-1] + [dict(page['lines'][-1], conf=0.2)]
        roles = [(l['role'], l['text']) for l in text_roles(page)['lines']]
        self.assertEqual([('composer', 'Metallica'), ('title', 'Nothing Else Matters'),
                          ('page_number', '2'), ('subtitle', 'Bass Drum'), ('subtitle', 'Tom Toms'),
                          ('words', '2'), ('words', 'S8 second'), ('repeat_count', 'x3'),
                          ('footer', '2012 Tomas Chmura')], roles,
                         'the drum-key captions are no composer, the « 2 » of a two-bar repeat no '
                         'page number, a low-confidence line is dropped')
        count = next(l for l in text_roles(page)['lines'] if l['role'] == 'repeat_count')
        self.assertEqual(3, count['times'])

    def test_the_page_identity_names_title_composer_and_number(self):
        from wama.common.utils.score_page import page_identity, text_roles
        self.assertEqual({'title': 'Nothing Else Matters', 'composer': 'Metallica', 'page_number': 2},
                         page_identity(text_roles(self.PAGE)))
        self.assertEqual({'title': '', 'composer': '', 'page_number': None},
                         page_identity(text_roles(_ocr_page())))

    def test_a_page_read_upside_down_reads_worse(self):
        from wama.common.utils.score_page import text_quality
        upside_down = _ocr_page(('SIOME OSIE Sumyon', 400, 1300, 600, 1340))
        upside_down['lines'][0]['conf'] = 0.36
        self.assertGreater(text_quality(self.PAGE), text_quality(upside_down))


def _photo(angle=0.0, desk=False):
    """A white page of three staves (grey array), turned by `angle` degrees, laid on a dark desk."""
    import numpy as np
    from PIL import Image
    page = np.full((1400, 1000), 255, dtype=np.uint8)
    for staff in range(3):
        for line in range(5):
            y = 200 + staff * 300 + line * 14
            page[y:y + 2, 80:920] = 0
    image = Image.fromarray(page)
    if desk:                                 # the SHEET lies tilted on the desk, as photographed
        background = Image.new('L', (image.width + 1200, image.height + 600), 25)
        background.paste(image, (600, 300))
        image = background
    if angle:
        image = image.rotate(angle, expand=True, fillcolor=25 if desk else 255)
    return np.asarray(image)


class APhotographedPageIsLeveledTest(SimpleTestCase):
    """Measured 2026-11-08 : the probe saw no staff on any of six phone photos."""

    def test_a_tilted_page_shows_its_staves_once_leveled(self):
        from wama.common.utils.score_page import count_staves, level_gray, page_angle
        tilted = _photo(angle=7)
        self.assertEqual(0, count_staves(tilted), 'counter-proof : tilted, no row fills')
        self.assertAlmostEqual(-7, page_angle(tilted), delta=0.5)
        self.assertEqual(3, count_staves(level_gray(tilted)))

    def test_the_sheet_is_cut_out_of_the_desk(self):
        from wama.common.utils.score_page import count_staves, level_gray, paper_box
        on_desk = _photo(desk=True)
        x0, y0, x1, y1 = paper_box(on_desk)
        self.assertAlmostEqual(600, x0, delta=15)
        self.assertAlmostEqual(1600, x1, delta=15)
        self.assertEqual(3, count_staves(level_gray(on_desk)))
        self.assertIsNone(paper_box(_photo()), 'a page that fills the image has nothing to cut')

    def test_the_probe_reads_a_photo_turned_by_its_exif_label(self):
        from PIL import Image
        from wama.common.utils.score_page import _gray_pages, page_staves
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'photo.jpg'
            shown = _photo(angle=2, desk=True)
            image = Image.fromarray(shown).rotate(90, expand=True)
            exif = Image.Exif()
            exif[0x0112] = 6                       # « rotate 90° clockwise to display »
            image.save(path, exif=exif)
            self.assertEqual(3, page_staves(str(path)))
            # The page the probe measures is the page AS SHOWN — the quarter turn the probe also
            # tries would hide a lost EXIF reading (counter-proof of 2026-11-08 : it stayed green).
            (page,) = _gray_pages(str(path))
            self.assertGreater(page.shape[0], page.shape[1], 'the sheet stands, as photographed')

    def test_a_straight_full_page_is_not_rewritten(self):
        from PIL import Image
        from wama.common.utils.score_page import level_page
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'scan.png'
            Image.fromarray(_photo()).save(path)
            self.assertEqual(str(path), level_page(str(path), tmp))
            leveled = level_page(str(_save(Path(tmp) / 'tilted.png', _photo(angle=5))), tmp)
            self.assertTrue(leveled.endswith('tilted_level.png'))


def _save(path: Path, page) -> Path:
    from PIL import Image
    Image.fromarray(page).save(path)
    return path


class TheEngineReceivesThePageTextTest(SimpleTestCase):

    def test_the_lines_reach_the_library_in_its_form_and_in_its_pixels(self):
        from wama.common.backends.copisteria_backend import _texts
        from wama.common.utils.score_page import text_roles
        page = text_roles(_ocr_page(('Nothing Else Matters', 350, 50, 650, 90),
                                    ('x3', 500, 700, 530, 720), width=500, height=700))
        texts = _texts(page, (1000, 1400))
        self.assertEqual([{'text': 'Nothing Else Matters', 'xyxy': [700.0, 100.0, 1300.0, 180.0],
                           'role': 'pgHead_title'},
                          {'text': 'repeat 3', 'xyxy': [1000.0, 1400.0, 1060.0, 1440.0],
                           'role': 'words'}], texts)
        self.assertIsNone(_texts(None, (10, 10)))

    def test_read_score_passes_each_page_its_texts(self):
        from PIL import Image
        from wama.common.backends.copisteria_backend import CopisteriaBackend
        engine = CopisteriaBackend()
        engine._model = object()
        received = []

        def transcribe(png, model, texts=None, device='cpu'):
            received.append(texts)
            return _page('CD')
        library = mock.Mock(transcribe=transcribe)
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / 'page.png'
            Image.new('L', (500, 700), 255).save(image)
            page = {'width': 500, 'height': 700,
                    'lines': [{'text': 'Groove', 'bbox': [0, 0, 50, 20], 'role': 'title'}]}
            with mock.patch.object(CopisteriaBackend, '_library', return_value=(library, None)):
                engine.read_score('copisteria', str(image), page_texts=[page])
        self.assertEqual([[{'text': 'Groove', 'xyxy': [0.0, 0.0, 50.0, 20.0], 'role': 'pgHead_title'}]],
                         received)
