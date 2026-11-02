"""The TEXT LAYER of a document (ROADMAP §16.4bis, vision §5.4) — read its passages, rewrite them IN
PLACE keeping everything else ; and the privacy brick's file occultation on top of it.

What is held here, on documents built by the test (in a temporary folder it creates and removes) :
a TXT keeps its encoding ; a DOCX keeps its paragraphs and the formatting of the passage's start,
a name split across two runs, in a table, in a header, or left in a tracked DELETION is gone from
the file ; a native PDF loses the passage's text for good (not just covered) and its metadata ;
the occultation re-reads what it produced and names any original passage still there.
"""
import shutil
import tempfile
import zipfile
from pathlib import Path

from django.test import SimpleTestCase


class _TempDir(SimpleTestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='wama-doctext-'))
        self.addCleanup(shutil.rmtree, self.dir, True)


def _span(segment: str, passage: str) -> tuple:
    start = segment.index(passage)
    return start, start + len(passage)


class PlainTextTest(_TempDir):

    def test_a_cp1252_text_is_rewritten_in_its_own_encoding(self):
        from wama.common.utils.document_text import read_segments, write_replacements
        src = self.dir / 'lettre.txt'
        src.write_bytes('Chère Anne Martin, à bientôt.'.encode('cp1252'))
        [segment] = read_segments(src)
        out = write_replacements(src, self.dir / 'out.txt',
                                 {0: [(*_span(segment, 'Anne Martin'), '[PERSONNE]')]})
        self.assertEqual('Chère [PERSONNE], à bientôt.', Path(out).read_bytes().decode('cp1252'))


class DocxTest(_TempDir):

    def _document(self):
        import docx
        from docx.oxml import parse_xml
        document = docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run('Madame ')
        paragraph.add_run('Anne ').bold = True
        paragraph.add_run('Martin').italic = True
        paragraph.add_run(' viendra.')
        document.add_table(rows=1, cols=1).cell(0, 0).text = 'Responsable : Paul Girard'
        document.sections[0].header.paragraphs[0].text = 'Dossier de Paul Girard'
        # A tracked DELETION : its text stays in the file although no one sees it.
        deleted = parse_xml(
            '<w:del xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'w:id="1" w:author="x"><w:r><w:delText>Jeanne Secret</w:delText></w:r></w:del>')
        document.add_paragraph('Fin.')._p.append(deleted)
        document.core_properties.author = 'Anne Martin'
        path = self.dir / 'note.docx'
        document.save(str(path))
        return path

    def _xml(self, path) -> str:
        with zipfile.ZipFile(path) as z:
            return '\n'.join(z.read(n).decode('utf-8', 'replace') for n in z.namelist()
                             if n.endswith('.xml'))

    def test_names_across_runs_tables_headers_and_deletions_are_gone(self):
        from wama.common.utils.document_text import read_segments, write_replacements
        src = self._document()
        segments = read_segments(src)
        replacements = {}
        for i, segment in enumerate(segments):
            for name, label in (('Anne Martin', '[PERSONNE]'), ('Paul Girard', '[PERSONNE]')):
                if name in segment:
                    replacements.setdefault(i, []).append((*_span(segment, name), label))
        out = Path(write_replacements(src, self.dir / 'out.docx', replacements))
        xml = self._xml(out)
        for gone in ('Anne', 'Martin', 'Paul Girard', 'Jeanne Secret'):
            self.assertNotIn(gone, xml)
        after = read_segments(out)
        self.assertIn('Madame [PERSONNE] viendra.', after)
        self.assertIn('Responsable : [PERSONNE]', after)
        self.assertIn('Dossier de [PERSONNE]', after)
        self.assertEqual(len(segments), len(after))

    def test_the_formatting_of_the_passage_start_is_kept_and_the_rest_untouched(self):
        import docx
        from wama.common.utils.document_text import read_segments, write_replacements
        src = self._document()
        segment = read_segments(src)[0]
        out = write_replacements(src, self.dir / 'out.docx',
                                 {0: [(*_span(segment, 'Anne Martin'), '[PERSONNE]')]})
        runs = docx.Document(out).paragraphs[0].runs
        self.assertEqual(['Madame ', '[PERSONNE]', '', ' viendra.'], [r.text for r in runs])
        self.assertTrue(runs[1].bold)


class PdfTest(_TempDir):

    def _pdf(self):
        import fitz
        pdf = fitz.open()
        page = pdf.new_page()
        page.insert_text((72, 72), 'Contact : Anne Martin, bureau 12.', fontsize=12)
        page.insert_text((72, 100), 'Signature : Anne Martin.', fontsize=12)
        pdf.set_metadata({'author': 'Anne Martin', 'title': 'Dossier Anne Martin'})
        path = self.dir / 'fiche.pdf'
        pdf.save(str(path))
        pdf.close()
        return path

    def test_the_passage_text_is_removed_not_covered_and_the_metadata_scrubbed(self):
        import fitz
        from wama.common.utils.document_text import read_segments, write_replacements
        src = self._pdf()
        [page] = read_segments(src)
        out = write_replacements(src, self.dir / 'out.pdf',
                                 {0: [(*_span(page, 'Anne Martin'), '[PERSONNE]')]})
        with fitz.open(out) as pdf:
            text = pdf[0].get_text()
            self.assertNotIn('Anne Martin', text)          # every occurrence on the page
            self.assertIn('bureau 12', text)               # the rest untouched
            self.assertNotIn('Anne Martin', str(pdf.metadata))
        self.assertNotIn(b'Anne Martin', Path(out).read_bytes())


class PdfBlockFormTest(_TempDir):
    """2026-10-29 (a real translated paper : every block rewritten in sans-serif, no bold, 162
    blocks of 392 shrunk under 80 %) — unit `block` rewrites a block with its OWN dominant style,
    keeps its size by growing into the free room below, keeps its writing direction, and leaves an
    unchanged block untouched."""

    def _spans(self, path):
        import fitz
        with fitz.open(path) as pdf:
            return [s for b in pdf[0].get_text('dict')['blocks'] if b.get('type') == 0
                    for line in b['lines'] for s in line['spans'] if s['text'].strip()]

    def _rewrite(self, src, transform):
        from wama.common.utils.document_text import read_segments, write_replacements
        segments = read_segments(src, unit='block')
        replacements = {i: [(0, len(s), transform(s))] for i, s in enumerate(segments)}
        return write_replacements(src, self.dir / 'out.pdf', replacements, unit='block')

    def test_a_block_keeps_its_family_weight_size_and_color(self):
        import fitz
        src = self.dir / 'in.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 100), 'Titre en gras', fontname='tibo', fontsize=14,
                                       color=(0, 0, 1))
            pdf.save(str(src))
        [span] = self._spans(self._rewrite(src, str.upper))
        self.assertEqual('TITRE EN GRAS', span['text'].strip())
        self.assertTrue(span['flags'] & 4, 'serif family kept')
        self.assertTrue(span['flags'] & 16, 'bold kept')
        self.assertAlmostEqual(14, span['size'], delta=0.1)
        self.assertEqual(0x0000ff, span['color'])

    def test_a_longer_text_keeps_its_size_by_growing_into_the_free_room_below(self):
        import fitz
        src = self.dir / 'in.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page()
            page.insert_text((72, 100), 'Un court paragraphe', fontname='tiro', fontsize=11)
            page.insert_text((72, 400), 'Pied', fontname='tiro', fontsize=11)
            pdf.save(str(src))
        longer = lambda s: s if s == 'Pied' else ' '.join([s] * 12)  # noqa: E731
        spans = self._spans(self._rewrite(src, longer))
        body = [s for s in spans if s['text'].strip() != 'Pied']
        self.assertGreater(len({round(s['bbox'][1]) for s in body}), 1, 'wrapped on several lines')
        self.assertTrue(all(abs(s['size'] - 11) < 0.1 for s in body), 'size kept, not shrunk')
        foot = [s for s in spans if s['text'].strip() == 'Pied'][0]
        self.assertLess(max(s['bbox'][3] for s in body), foot['bbox'][1], 'the block below is not covered')

    def test_a_vertical_stamp_is_rewritten_vertical(self):
        import fitz
        src = self.dir / 'in.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((30, 500), 'Tampon vertical', fontsize=12, rotate=90)
            pdf.save(str(src))
        with fitz.open(self._rewrite(src, str.upper)) as pdf:
            [line] = [line for b in pdf[0].get_text('dict')['blocks'] for line in b['lines']]
        self.assertEqual('TAMPON VERTICAL', ''.join(s['text'] for s in line['spans']).strip())
        self.assertEqual((0, -1), tuple(round(v) for v in line['dir']))

    def test_an_unchanged_block_is_not_rewritten(self):
        """Counter-proof of the font : an untouched block keeps its EMBEDDED font, not the
        generic family a rewrite would give it."""
        import fitz
        src = self.dir / 'in.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((72, 100), '4.69 1.78', fontname='cour', fontsize=10)
            pdf.save(str(src))
        [span] = self._spans(self._rewrite(src, lambda s: s))
        self.assertEqual('Courier', span['font'])


class PdfTableTest(_TempDir):
    """2026-10-29 — PyMuPDF keeps each table cell as its own LINE but puts the whole table in one
    block : translated as one sentence, it was poured across the cells. Unit `block` now gives one
    segment per cell, written back in its column ; numbers are never rewritten."""

    def _pdf(self, rows):
        import fitz
        src = self.dir / 'table.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page()
            writer = fitz.TextWriter(page.rect)
            for y, cells in rows:
                for x, cell in cells:
                    writer.append((x, y), cell, fontsize=9)
            writer.write_text(page)
            pdf.save(str(src))
        return src

    def test_each_cell_is_a_segment_written_back_in_its_column(self):
        import fitz
        from wama.common.utils.document_text import read_segments, write_replacements
        src = self._pdf([(100, ((72, 'Ensemble'), (160, 'Erreur'), (250, '4.69'))),
                         (112, ((72, 'Test'), (160, 'Écart'), (250, '1.78')))])
        segments = read_segments(src, unit='block')
        self.assertEqual(['Ensemble', 'Erreur', '4.69', 'Test', 'Écart', '1.78'], segments)
        out = write_replacements(src, self.dir / 'out.pdf',
                                 {i: [(0, len(s), s.upper())] for i, s in enumerate(segments)},
                                 unit='block')
        with fitz.open(out) as pdf:
            words = {w[4]: w[0] for w in pdf[0].get_text('words')}
        for word, x in (('ENSEMBLE', 72), ('ERREUR', 160), ('TEST', 72), ('ÉCART', 160),
                        ('4.69', 250), ('1.78', 250)):
            self.assertAlmostEqual(x, words[word], delta=3, msg=word)

    def test_a_longer_label_of_a_right_aligned_column_keeps_its_size_and_its_right_edge(self):
        """Measured on a real paper : a row label ends at the table rule, so it can only grow to
        the LEFT — it used to shrink to fit its own width."""
        import fitz
        from wama.common.utils.document_text import read_segments, write_replacements
        regular = fitz.Font('helv')                      # the TextWriter's default font
        right = 200
        rows = []
        for y, label, value in ((100, 'TS-CAN', '4.69'), (112, 'PhysNet [5]', '1.78')):
            rows.append((y, ((right - regular.text_length(label, fontsize=9), label),
                             (220, value))))
        src = self._pdf(rows)
        segments = read_segments(src, unit='block')
        longer = {i: [(0, len(s), s + ' (normalisé)')] for i, s in enumerate(segments)
                  if s.startswith('PhysNet')}
        out = write_replacements(src, self.dir / 'out.pdf', longer, unit='block')
        with fitz.open(out) as pdf:
            [span] = [s for b in pdf[0].get_text('dict')['blocks'] for line in b['lines']
                      for s in line['spans'] if 'normalisé' in s['text']]
        self.assertAlmostEqual(9, span['size'], delta=0.1)
        self.assertAlmostEqual(right, span['bbox'][2], delta=2)

    def test_a_paragraph_cut_once_by_a_formula_stays_one_segment(self):
        """Counter-proof : a single row of side-by-side lines is not a table."""
        from wama.common.utils.document_text import read_segments
        src = self._pdf([(100, ((72, 'Une phrase coupée'), (200, 'par une formule'))),
                         (112, ((72, 'qui continue ici.'),))])
        self.assertEqual(['Une phrase coupée par une formule qui continue ici.'],
                         read_segments(src, unit='block'))


class PdfFigureTest(_TempDir):
    """2026-10-29 (figure 1 of a real paper) — inside a FIGURE (a `picture` region of the layout
    analysis) the lines of a block are LABELS : two stacked lines facing each other are one label,
    translated in one piece ; the family is read on the font NAME before the PDF's flags ; a
    vertical label grows along its writing direction instead of shrinking."""

    def _figure_pdf(self):
        import fitz
        src = self.dir / 'figure.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page()
            writer = fitz.TextWriter(page.rect)
            for x, y, text in ((100, 100, 'Convolutional'), (220, 100, 'Fully Connected'),
                               (112, 110, 'Layers'), (240, 110, 'Layer')):
                writer.append((x, y), text, fontsize=8)
            writer.write_text(page)
            pdf.save(str(src))
        return src

    def test_stacked_lines_of_a_figure_are_one_label(self):
        import fitz
        from unittest import mock
        from wama.common.utils import document_text
        src = self._figure_pdf()
        whole_page = lambda page: [fitz.Rect(page.rect)]  # noqa: E731
        with mock.patch.object(document_text, '_figure_regions', whole_page):
            labels = document_text.read_segments(src, unit='block')
        self.assertEqual(['Convolutional Layers', 'Fully Connected Layer'], labels)
        # Counter-proof : outside a figure, the same block is a table of four cells.
        with mock.patch.object(document_text, '_figure_regions', lambda page: []):
            self.assertEqual(4, len(document_text.read_segments(src, unit='block')))

    def test_the_family_is_read_on_the_font_name_before_the_flags(self):
        from wama.common.utils.document_text import _span_style
        span = {'flags': 4, 'font': 'ABCDEF+Roboto-Regular', 'size': 8, 'color': 0}
        self.assertEqual('Helvetica', _span_style(span)[0])           # flagged serif, named sans
        self.assertEqual('Times', _span_style({**span, 'font': 'Unknown', 'flags': 4})[0])

    def test_a_longer_vertical_label_keeps_its_size(self):
        import fitz
        src = self.dir / 'in.pdf'
        with fitz.open() as pdf:
            pdf.new_page().insert_text((60, 400), 'Power', fontsize=8, rotate=90)
            pdf.save(str(src))
        from wama.common.utils.document_text import read_segments, write_replacements
        segments = read_segments(src, unit='block')
        out = write_replacements(src, self.dir / 'out.pdf', {0: [(0, len(segments[0]), 'Puissance')]},
                                 unit='block')
        with fitz.open(out) as pdf:
            [span] = [s for b in pdf[0].get_text('dict')['blocks'] for line in b['lines']
                      for s in line['spans'] if s['text'].strip()]
        self.assertEqual('Puissance', span['text'].strip())
        self.assertAlmostEqual(8, span['size'], delta=0.1)


class MarkupTest(_TempDir):
    """2026-10-29 — `markup=True` : a segment carries `<tN>…</tN>` around each passage whose
    formatting is not the dominant one, and a rewritten text gives each passage back ITS formatting
    (a translated paragraph used to take the formatting of its first run, everywhere)."""

    def _docx(self):
        import docx
        document = docx.Document()
        paragraph = document.add_paragraph()
        paragraph.add_run('Note :').bold = True
        paragraph.add_run(' le texte suit, ')
        paragraph.add_run('vraiment').italic = True
        paragraph.add_run('.')
        path = self.dir / 'note.docx'
        document.save(str(path))
        return path

    def _rewrite_docx(self, new):
        import docx
        from wama.common.utils.document_text import read_segments, write_replacements
        src = self._docx()
        [segment] = read_segments(src, markup=True)
        out = write_replacements(src, self.dir / 'out.docx', {0: [(0, len(segment), new)]},
                                 markup=True)
        return segment, [(r.text, bool(r.bold), bool(r.italic))
                         for r in docx.Document(out).paragraphs[0].runs if r.text]

    def test_a_docx_paragraph_gives_each_passage_back_its_formatting(self):
        segment, runs = self._rewrite_docx('<t1>Remark:</t1> the text follows, <t2>really</t2>.')
        self.assertEqual('<t1>Note :</t1> le texte suit, <t2>vraiment</t2>.', segment)
        self.assertEqual([('Remark:', True, False), (' the text follows, ', False, False),
                          ('really', False, True), ('.', False, False)], runs)

    def test_two_passages_swapped_by_the_translation_each_keep_their_formatting(self):
        """2026-10-30 (rest of ROADMAP §10.B) : the word order of the target language swaps the
        italic and the bold passages. The second used to join the previous run and lose its
        formatting ; it now gets a CLONE of its original run, right after."""
        _, runs = self._rewrite_docx('<t2>Vraiment</t2>, le texte suit la <t1>note</t1>.')
        self.assertEqual([('Vraiment', False, True), (', le texte suit la ', False, False),
                          ('note', True, False), ('.', False, False)], runs)

    def test_a_cloned_run_brings_no_tab_or_break_of_its_original(self):
        import docx
        from wama.common.utils.document_text import read_segments, write_replacements
        document = docx.Document()
        paragraph = document.add_paragraph()
        bold = paragraph.add_run('A')
        bold.bold = True
        bold.add_tab()
        paragraph.add_run(' plain text, ')
        paragraph.add_run('B').italic = True
        src = self.dir / 'tab.docx'
        document.save(str(src))
        [segment] = read_segments(src, markup=True)
        out = write_replacements(src, self.dir / 'out.docx',
                                 {0: [(0, len(segment), '<t2>B</t2> plain text, <t1>A</t1>')]},
                                 markup=True)
        xml = docx.Document(out).paragraphs[0]._p.xml
        self.assertEqual(1, xml.count('<w:tab/>'), 'the tab stays where it was, not duplicated')

    def test_illegible_tags_keep_the_text_in_the_dominant_formatting(self):
        _, runs = self._rewrite_docx('<t1>Remark: the text follows, <t9>really</t9>.')
        self.assertEqual([('Remark: the text follows, really.', False, False)], runs)

    def test_without_markup_the_segment_is_the_bare_text(self):
        """Counter-proof : the Anonymizer's indexes are those of the bare text."""
        from wama.common.utils.document_text import read_segments
        self.assertEqual(['Note : le texte suit, vraiment.'], read_segments(self._docx()))

    def test_a_pdf_block_gives_a_bold_word_back_its_weight(self):
        import fitz
        from wama.common.utils.document_text import read_segments, write_replacements
        src = self.dir / 'in.pdf'
        with fitz.open() as pdf:
            page = pdf.new_page()
            writer = fitz.TextWriter(page.rect)
            regular, bold = fitz.Font('tiro'), fitz.Font('tibo')
            _, end = writer.append((72, 100), 'Un mot ', font=regular, fontsize=11)
            _, end = writer.append(end, 'important', font=bold, fontsize=11)
            writer.append(end, ' dans la phrase.', font=regular, fontsize=11)
            writer.write_text(page)
            pdf.save(str(src))
        [segment] = read_segments(src, unit='block', markup=True)
        self.assertEqual('Un mot <t1>important</t1> dans la phrase.', segment)
        out = write_replacements(src, self.dir / 'out.pdf',
                                 {0: [(0, len(segment), 'An <t1>important</t1> word in the sentence.')]},
                                 unit='block', markup=True)
        with fitz.open(out) as pdf:
            spans = [s for b in pdf[0].get_text('dict')['blocks'] for line in b['lines']
                     for s in line['spans'] if s['text'].strip()]
        bold_text = ''.join(s['text'] for s in spans if s['flags'] & 16).strip()
        self.assertEqual('important', bold_text)
        self.assertIn('word in the sentence.', ''.join(s['text'] for s in spans))


def _scan_of(dir_, lines, extra_pages=()):
    """A PDF whose first page is a SCAN (an image, no text layer) of `lines` — `(x, y, text)` at
    11 pt —, and the lines an OCR would give for it (contract of `OCRBackend.read_lines`): the
    native boxes, made as tall as an OCR box (`OCR_SIZE_RATIO`). `extra_pages`: callables that
    draw further pages of the same file."""
    import fitz
    from wama.common.utils.document_text import OCR_SIZE_RATIO
    with fitz.open() as native:
        page = native.new_page()
        for x, y, text in lines:
            page.insert_text((x, y), text, fontsize=11)
        ocr_lines = []
        for block in page.get_text('dict')['blocks']:
            for line in block['lines']:
                x0, y0, x1, y1 = line['bbox']
                middle, half = (y0 + y1) / 2, 11 / OCR_SIZE_RATIO / 2
                ocr_lines.append({'bbox': [x0, middle - half, x1, middle + half], 'conf': 0.99,
                                  'text': ''.join(s['text'] for s in line['spans']), 'words': []})
        pixmap, size = page.get_pixmap(dpi=150), page.rect
    path = dir_ / 'scan.pdf'
    with fitz.open() as pdf:
        scanned = pdf.new_page(width=size.width, height=size.height)
        scanned.insert_image(scanned.rect, pixmap=pixmap)
        for draw in extra_pages:
            draw(pdf)
        pdf.save(str(path))
    return path, {0: {'width': size.width, 'height': size.height, 'unit': 'pt',
                      'lines': ocr_lines}}


LONG = 'The first paragraph runs from one edge of the column to the other'


class ScannedPageTest(_TempDir):
    """2026-10-29 (ROADMAP §10.B) — a page WITHOUT a text layer is read from the lines of an OCR
    that gives their place (`OCRBackend.read_lines`), passed in: the brick knows no engine. Its
    lines become paragraphs (`_stack(scanned=True)`), rewritten like any block once the scan's
    PIXELS under them are erased."""

    PARAGRAPHS = [(72, 100, LONG), (72, 114, 'and ends here.'),
                  (90, 128, 'A second paragraph starts indented'), (72, 142, LONG)]

    def test_a_page_lacks_text_only_when_it_carries_something_to_read(self):
        from wama.common.utils.document_text import pages_without_text

        def native(pdf):
            pdf.new_page().insert_text((72, 100), LONG, fontsize=11)

        def blank(pdf):
            pdf.new_page()

        def figure_with_labels(pdf):
            page = pdf.new_page()
            page.draw_rect((72, 72, 300, 300))
            page.insert_text((80, 90), 'Fig. 1', fontsize=9)

        def outlined_text(pdf):
            pdf.new_page().draw_line((72, 72), (300, 72))

        path, _ = _scan_of(self.dir, self.PARAGRAPHS,
                           [native, blank, figure_with_labels, outlined_text])
        self.assertEqual([0, 4], pages_without_text(path))

    def test_only_the_pages_without_text_are_given_to_the_ocr(self):
        import fitz
        from wama.common.utils.document_text import read_pages_without_text
        path, ocr = _scan_of(self.dir, self.PARAGRAPHS,
                             [lambda pdf: pdf.new_page().insert_text((72, 100), LONG)])
        seen = []

        def read_lines(work_file):
            with fitz.open(work_file) as pdf:
                seen.append(len(pdf))
            return [ocr[0]]
        self.assertEqual({0: ocr[0]}, read_pages_without_text(path, read_lines))
        self.assertEqual([1], seen)

    def test_ocr_lines_become_paragraphs_closed_by_a_short_line_or_an_indent(self):
        from wama.common.utils.document_text import read_segments
        path, ocr = _scan_of(self.dir, self.PARAGRAPHS)
        self.assertEqual([], read_segments(path, unit='block'))         # no OCR, nothing to read
        self.assertEqual([LONG + ' and ends here.', 'A second paragraph starts indented ' + LONG],
                         read_segments(path, unit='block', ocr=ocr))
        # A JSON read back gives its page keys as text.
        self.assertEqual(2, len(read_segments(path, unit='block', ocr={'0': ocr[0]})))

    def test_a_short_line_alone_closes_its_paragraph(self):
        from wama.common.utils.document_text import read_segments
        path, ocr = _scan_of(self.dir, [(72, 100, LONG), (72, 114, 'and ends here.'),
                                        (72, 128, LONG), (72, 142, LONG)])
        self.assertEqual([LONG + ' and ends here.', LONG + ' ' + LONG],
                         read_segments(path, unit='block', ocr=ocr))

    def test_an_indent_alone_opens_a_paragraph(self):
        from wama.common.utils.document_text import read_segments
        path, ocr = _scan_of(self.dir, [(72, 100, LONG), (72, 114, LONG),
                                        (90, 128, 'An indented first line'), (72, 142, LONG)])
        self.assertEqual([LONG + ' ' + LONG, 'An indented first line ' + LONG],
                         read_segments(path, unit='block', ocr=ocr))

    def test_a_scanned_paragraph_has_one_style_even_when_its_boxes_differ(self):
        from wama.common.utils.document_text import read_segments
        path, ocr = _scan_of(self.dir, self.PARAGRAPHS)
        ocr[0]['lines'][1]['bbox'][3] += 1.5             # a box a few per cent taller
        for segment in read_segments(path, unit='block', markup=True, ocr=ocr):
            self.assertNotIn('<t', segment)

    def test_the_rewrite_erases_the_scan_under_the_paragraph_and_writes_the_new_text(self):
        import fitz
        from wama.common.utils.document_text import read_segments, write_replacements
        path, ocr = _scan_of(self.dir, self.PARAGRAPHS)
        first, _ = read_segments(path, unit='block', ocr=ocr)
        out = write_replacements(path, self.dir / 'out.pdf', {0: [(0, len(first), 'Bonjour.')]},
                                 unit='block', ocr=ocr)

        def darkness(pdf, rect):
            """Dark pixels of the SCAN IMAGE itself under `rect` (page points) — not of the
            rendered page: a white box drawn over the image would hide the old text and leave
            it in the file."""
            page = pdf[0]
            image = fitz.Pixmap(pdf, page.get_images()[0][0])
            scale = image.width / page.rect.width
            samples = image.samples
            return sum(1 for y in range(int(rect.y0 * scale), int(rect.y1 * scale))
                       for x in range(int(rect.x0 * scale), int(rect.x1 * scale))
                       if samples[(y * image.width + x) * image.n] < 128)

        with fitz.open(out) as pdf, fitz.open(path) as before:
            self.assertIn('Bonjour.', pdf[0].get_text())
            old_end = fitz.Rect(250, 90, 400, 118)        # where the old first line ran
            self.assertGreater(darkness(before, old_end), 50)
            self.assertEqual(0, darkness(pdf, old_end))
            second = fitz.Rect(72, 120, 400, 146)           # the untouched paragraph is still there
            self.assertGreater(darkness(pdf, second), 50)


def _page_with_raster_figure(dir_):
    """A NATIVE page (selectable text) carrying a BITMAP figure: « Input Frames » and « Neural »
    drawn into the image, a black bar far from them, plus a native word laid over the image, and a
    small icon. Returns (path, the image's frame, a fake `read_lines` giving the words docTR
    would read in the image — with drawing noise —, in the image's pixels)."""
    import fitz
    with fitz.open() as art:
        canvas = art.new_page(width=300, height=150)
        canvas.insert_text((20, 40), 'Input Frames', fontsize=16)
        canvas.insert_text((200, 40), 'Neural', fontsize=16)
        canvas.draw_rect(fitz.Rect(20, 110, 280, 130), color=(0, 0, 0), fill=(0, 0, 0))
        words = [(w[4], fitz.Rect(w[:4]) * 2) for w in canvas.get_text('words')]   # 144 dpi
        figure_pixmap = canvas.get_pixmap(dpi=144)
        icon = art.new_page(width=40, height=40)
        icon.insert_text((5, 25), 'ic', fontsize=12)
        icon_pixmap = icon.get_pixmap(dpi=72)
    frame = fitz.Rect(100, 200, 400, 350)
    path = dir_ / 'native_figure.pdf'
    with fitz.open() as pdf:
        page = pdf.new_page()
        page.insert_text((72, 100), 'A native paragraph above the figure.', fontsize=11)
        page.insert_image(frame, pixmap=figure_pixmap)
        page.insert_image(fitz.Rect(450, 200, 490, 240), pixmap=icon_pixmap)
        page.insert_text((300, 340), 'Overlay', fontsize=9)      # native text ON the image
        pdf.save(str(path))
    by_text = {text: list(rect) for text, rect in words}
    a, b = by_text['Input'], by_text['Frames']

    def read_lines(work_file):
        with fitz.open(work_file) as sheet:
            width, height = sheet[0].rect.width, sheet[0].rect.height
        noise ={'bbox': [40, 220, 44, 260], 'text': 'I', 'conf': 1.0}
        layers = {'bbox': [300, 220, 330, 260], 'text': 'LL', 'conf': 0.51}
        overlay = {'bbox': [400, 260, 470, 280], 'text': 'Overlay', 'conf': 0.99}
        line = {'bbox': [a[0], a[1], by_text['Neural'][2], a[3]], 'text': 'Input Frames Neural',
                'conf': 0.95,
                'words': [{'bbox': a, 'text': 'Input', 'conf': 0.99},
                          {'bbox': b, 'text': 'Frames', 'conf': 0.98},
                          {'bbox': by_text['Neural'], 'text': 'Neural', 'conf': 0.97}]}
        return [{'width': width, 'height': height, 'unit': 'pt',
                 'lines': [line,
                           {'bbox': noise['bbox'], 'text': 'I', 'conf': 1.0, 'words': [noise]},
                           {'bbox': layers['bbox'], 'text': 'LL', 'conf': 0.51, 'words': [layers]},
                           {'bbox': overlay['bbox'], 'text': 'Overlay', 'conf': 0.99,
                            'words': [overlay]}]}]
    return path, frame, read_lines


class RasterFigureTest(_TempDir):
    """2026-10-30 (rest of ROADMAP §10.B) — the text drawn INSIDE a bitmap image of a native page
    is read by the OCR that gives places, then rewritten like a scan's, pixels erased under it."""

    def test_only_images_big_enough_to_carry_text_are_figures(self):
        import fitz
        from wama.common.utils.document_text import raster_figures
        path, frame, _ = _page_with_raster_figure(self.dir)
        with fitz.open(path) as pdf:
            self.assertEqual([tuple(frame)], [tuple(r) for _x, r in raster_figures(pdf[0])])

    def test_a_scanned_page_does_not_count_its_image_as_a_figure(self):
        """The one reading shared by the probe, the OCR step and `read_figure_text`: a page
        without a text layer is read whole, so its image is no figure ; another format has none."""
        import fitz
        from wama.common.utils.document_text import native_figures
        path, frame, _ = _page_with_raster_figure(self.dir)
        with fitz.open(path) as pdf:
            image = pdf[0].get_pixmap(dpi=72)
            scan = pdf.new_page()
            scan.insert_image(scan.rect, pixmap=image)
            pdf.save(str(self.dir / 'with_scan.pdf'))
        figures = native_figures(self.dir / 'with_scan.pdf')
        self.assertEqual([0], list(figures))
        self.assertEqual([tuple(frame)], [tuple(r) for _x, r in figures[0]])
        self.assertEqual({}, native_figures(self.dir / 'notes.txt'))

    def test_labels_come_in_page_points_without_noise_nor_native_text(self):
        from wama.common.utils.document_text import read_figure_text
        path, frame, read_lines = _page_with_raster_figure(self.dir)
        ocr = read_figure_text(path, read_lines)
        labels = [(line['text'], line['bbox']) for line in ocr[0]['figure_lines']]
        # « Input Frames » and « Neural » : two labels (far apart), « I », « LL », « Overlay » gone.
        self.assertEqual(['Input Frames', 'Neural'], [text for text, _box in labels])
        x0, y0, x1, y1 = labels[0][1]
        self.assertTrue(frame.x0 <= x0 < x1 <= frame.x1 and frame.y0 <= y0 < y1 <= frame.y1)
        self.assertLess(abs(x0 - (frame.x0 + 20)), 3, 'pixels brought back to page points')

    def test_two_centred_lines_stack_and_a_frame_title_does_not(self):
        from wama.common.utils.document_text import _stack

        def line(x0, y0, x1, y1):
            return {'bbox': (x0, y0, x1, y1), 'dir': (1, 0)}
        conv, layers = line(100, 100, 200, 112), line(125, 112, 175, 124)
        title, row = line(20, 100, 120, 112), line(20, 112, 300, 124)
        self.assertEqual(1, len(_stack([conv, layers], scanned=True, centred=True)))
        self.assertEqual(2, len(_stack([title, row], scanned=True, centred=True)))

    def test_the_rewrite_erases_the_label_in_the_image_and_nothing_else(self):
        import fitz
        from wama.common.utils.document_text import (read_figure_text, read_segments,
                                                     write_replacements)
        path, frame, read_lines = _page_with_raster_figure(self.dir)
        ocr = read_figure_text(path, read_lines)
        segments = read_segments(path, unit='block', ocr=ocr)
        index = segments.index('Input Frames')
        out = write_replacements(path, self.dir / 'out.pdf',
                                 {index: [(0, len('Input Frames'), 'Images')]}, unit='block', ocr=ocr)

        def dark(pdf, rect):
            page = pdf[0]
            xref = next(x for x, r in [(i[0], page.get_image_rects(i[0])[0]) for i in page.get_images()]
                        if r == frame)
            image = fitz.Pixmap(pdf, xref)
            scale = image.width / frame.width
            samples = image.samples
            return sum(1 for y in range(int((rect.y0 - frame.y0) * scale), int((rect.y1 - frame.y0) * scale))
                       for x in range(int((rect.x0 - frame.x0) * scale), int((rect.x1 - frame.x0) * scale))
                       if samples[(y * image.width + x) * image.n] < 128)

        label = fitz.Rect(frame.x0 + 22, frame.y0 + 28, frame.x0 + 110, frame.y0 + 42)
        bar = fitz.Rect(frame.x0 + 30, frame.y0 + 112, frame.x0 + 270, frame.y0 + 128)
        with fitz.open(out) as after, fitz.open(path) as before:
            self.assertGreater(dark(before, label), 20)
            self.assertEqual(0, dark(after, label), 'the drawn label is gone from the IMAGE')
            self.assertEqual(dark(before, bar), dark(after, bar), 'the drawing stays')
            self.assertIn('Images', after[0].get_text())

    def test_the_probe_counts_the_figures_and_the_switch_says_so_unticked(self):
        from wama.common.utils.media_probe import input_property, probe_media
        path, _frame, _ = _page_with_raster_figure(self.dir)
        info = probe_media(str(path))
        self.assertEqual(1, info['attributes']['raster_figures'])
        proposal = input_property(info, 'needs_ocr')
        self.assertIs(False, proposal['value'])
        self.assertIn('1 image', proposal['note'])


class OccultFileTest(_TempDir):

    def test_the_occultation_re_reads_its_output_and_names_what_remains(self):
        """Counter-proof : a name detected once but written twice must come back in `remaining`."""
        import docx
        from wama.common.privacy import engine
        from wama.common.utils import detections
        document = docx.Document()
        document.add_paragraph('Écrire à anne@exemple.fr.')
        document.add_paragraph('Anne Martin, encore Anne Martin.')
        src = self.dir / 'lettre.docx'
        document.save(str(src))
        doc = engine.detect_file(src, 'fr', detectors=())          # patterns only : the email
        report = engine.occult_file(src, self.dir / 'out.docx', doc)
        self.assertEqual([], report['remaining'])
        self.assertNotIn('anne@exemple.fr', '\n'.join(p.text for p in docx.Document(report['path']).paragraphs))
        detections.add(doc, 1, [detections.text_span(start=0, end=11, label='PERSON')])
        report = engine.occult_file(src, self.dir / 'out2.docx', doc)
        self.assertEqual(['Anne Martin'], report['remaining'])
        self.assertEqual('[PERSONNE], encore Anne Martin.', docx.Document(report['path']).paragraphs[1].text)


def _scan_with_words(dir_, lines):
    """A one-page SCAN of `lines` — `(x, y, text)` at 11 pt — and the OCR a positioned engine
    would give for it, WITH its words (contract of `OCRBackend.read_lines`): the native boxes."""
    import fitz
    with fitz.open() as native:
        page = native.new_page()
        for x, y, text in lines:
            page.insert_text((x, y), text, fontsize=11)
        by_line = {}
        for x0, y0, x1, y1, word, block, line, _ in page.get_text('words'):
            by_line.setdefault((block, line), []).append(
                {'bbox': [x0, y0, x1, y1], 'text': word, 'conf': 0.99})
        ocr_lines = [{'bbox': [min(w['bbox'][0] for w in words), min(w['bbox'][1] for w in words),
                               max(w['bbox'][2] for w in words), max(w['bbox'][3] for w in words)],
                      'text': ' '.join(w['text'] for w in words), 'conf': 0.99, 'words': words}
                     for _, words in sorted(by_line.items())]
        pixmap, size = page.get_pixmap(dpi=150), page.rect
    path = dir_ / 'scan_words.pdf'
    with fitz.open() as pdf:
        pdf.new_page(width=size.width, height=size.height).insert_image(
            fitz.Rect(0, 0, size.width, size.height), pixmap=pixmap)
        pdf.save(str(path))
    return path, {0: {'width': size.width, 'height': size.height, 'unit': 'pt',
                      'lines': ocr_lines}}


def _scan_darkness(pdf, rect):
    """Dark pixels of the SCAN IMAGE itself under `rect` (page points), not of the rendered page."""
    import fitz
    page = pdf[0]
    image = fitz.Pixmap(pdf, page.get_images()[0][0])
    scale = image.width / page.rect.width
    samples = image.samples
    return sum(1 for y in range(int(rect.y0 * scale), int(rect.y1 * scale))
               for x in range(int(rect.x0 * scale), int(rect.x1 * scale))
               if samples[(y * image.width + x) * image.n] < 128)


class ScannedPageOccultationTest(_TempDir):
    """2026-11-02 (domain `document` of the Anonymizer) — by PAGE, the unit that anonymizes: a
    page without a text layer is read from its OCR lines (`ocr=`), and a passage found there is
    redacted in its WORD boxes, the scan's pixels under them erased — the rest of the scan kept
    exactly as it was (anonymizing keeps the original form)."""

    LINES = [(72, 100, 'Contact: Anne Martin, Paris'), (72, 130, 'Second line of the letter')]

    def test_a_scanned_page_is_read_by_page_from_its_ocr_lines(self):
        from wama.common.utils.document_text import read_segments
        path, ocr = _scan_with_words(self.dir, self.LINES)
        self.assertEqual([''], [s.strip() for s in read_segments(path)])      # no OCR, no text
        self.assertEqual(['Contact: Anne Martin, Paris\nSecond line of the letter'],
                         read_segments(path, ocr=ocr))
        self.assertEqual(read_segments(path, ocr=ocr), read_segments(path, ocr={'0': ocr[0]}))

    def test_occulting_a_scanned_passage_erases_its_pixels_and_only_them(self):
        import fitz
        from wama.common.utils.document_text import read_segments, write_replacements
        path, ocr = _scan_with_words(self.dir, self.LINES)
        [segment] = read_segments(path, ocr=ocr)
        start = segment.index('Anne Martin')
        out = write_replacements(path, self.dir / 'out.pdf',
                                 {0: [(start, start + len('Anne Martin'), '[PERSONNE]')]}, ocr=ocr)
        words = {w['text']: fitz.Rect(w['bbox']) for w in ocr[0]['lines'][0]['words']}
        # « Martin, » : what the passage leaves of the word is a comma — the whole word goes.
        name = words['Anne'] | words['Martin,']
        with fitz.open(path) as before, fitz.open(out) as pdf:
            self.assertGreater(_scan_darkness(before, name), 50)
            self.assertEqual(0, _scan_darkness(pdf, name))
            for kept in (words['Contact:'], words['Paris'],
                         fitz.Rect(ocr[0]['lines'][1]['bbox'])):
                self.assertEqual(_scan_darkness(before, kept), _scan_darkness(pdf, kept))
            self.assertIn('[PERSONNE]', pdf[0].get_text())

    def test_without_words_the_line_box_is_cut_by_characters(self):
        import fitz
        from wama.common.utils.document_text import read_segments, write_replacements
        path, ocr = _scan_of(self.dir, [(72, 100, 'Contact: Anne Martin')])
        [segment] = read_segments(path, ocr=ocr)
        start = segment.index('Anne Martin')
        out = write_replacements(path, self.dir / 'out.pdf',
                                 {0: [(start, len(segment), '[PERSONNE]')]}, ocr=ocr)
        line = fitz.Rect(ocr[0]['lines'][0]['bbox'])
        head = fitz.Rect(line.x0, line.y0, line.x0 + line.width * 0.3, line.y1)   # « Contact: »
        tail = fitz.Rect(line.x0 + line.width * 0.5, line.y0, line.x1, line.y1)    # the name
        with fitz.open(path) as before, fitz.open(out) as pdf:
            self.assertEqual(_scan_darkness(before, head), _scan_darkness(pdf, head))
            self.assertGreater(_scan_darkness(before, tail), 50)
            self.assertEqual(0, _scan_darkness(pdf, tail))

    def test_the_occultation_takes_the_same_ocr_as_the_detection(self):
        """`occult_file(ocr=)` : the indexes of a span are those the detection read WITH the OCR."""
        import fitz
        from wama.common.privacy import engine
        from wama.common.utils import detections
        path, ocr = _scan_with_words(self.dir, self.LINES)
        doc = detections.new_document(media='text', width=0, height=0, frame_count=1,
                                      engine='presidio', models=[], classes=['PERSON'])
        doc['language'] = 'fr'
        start = 'Contact: Anne Martin, Paris'.index('Anne Martin')
        detections.add(doc, 0, [detections.text_span(start=start, end=start + 11, label='PERSON')])
        doc.pop('_index', None)
        report = engine.occult_file(path, self.dir / 'out.pdf', doc, ocr=ocr)
        self.assertEqual([], report['remaining'])
        with fitz.open(report['path']) as pdf:
            self.assertIn('[PERSONNE]', pdf[0].get_text())
