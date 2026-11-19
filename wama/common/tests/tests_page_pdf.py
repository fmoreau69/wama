"""The PDF export of a page fetches its sub-resources OFF Playwright's event loop (2026-11-12).

Playwright's route handler runs inside its asyncio loop; a Django view called there raises
`SynchronousOnlyOperation` as soon as it touches the ORM — the export of the presentation answered
« Export PDF indisponible » while Chromium was fine. Found and fixed through the assistant
(Claude Code task `20261112-140730-752838`), guarded here.
"""
import asyncio

from django.contrib.auth import get_user_model
from django.test import RequestFactory, SimpleTestCase, TransactionTestCase

from wama.common.services.page_pdf import make_fetcher


class FetchOffTheEventLoopTest(TransactionTestCase):
    """A TransactionTestCase: the fetch runs in another thread, which only sees committed rows."""

    def test_a_view_that_reads_the_database_is_served_inside_a_running_loop(self):
        user = get_user_model().objects.create_user('pdf_fetch', password='x')
        request = RequestFactory().get('/')
        request.user, request.session = user, {}
        fetch = make_fetcher(request)

        async def from_the_loop():
            return fetch('/common/api/notifications/')

        status, content_type, body = asyncio.run(from_the_loop())
        self.assertEqual(200, status, body[:200])
        self.assertIn('json', content_type)
        self.assertIn(b'"items"', body)

    def test_an_unknown_path_is_a_404_not_an_error(self):
        request = RequestFactory().get('/')
        request.user, request.session = get_user_model()(), {}
        self.assertEqual(404, make_fetcher(request)('/no/such/page/')[0])


class VideoPlayableInThePdfTest(SimpleTestCase):
    """A video of a presentation step stays PLAYABLE in its PDF export (2026-11-19, Fabien : « que je
    puisse simplement exporter le pdf de la présentation et que la vidéo soit lisible ») : the file
    is embedded where the video stands on the page, as the standard Screen + Rendition multimedia,
    played when the page shows and on click ; the page image (its poster) stays underneath."""

    def _pdf(self, folder):
        import pymupdf as fitz
        path = f'{folder}/slides.pdf'
        doc = fitz.open()
        doc.new_page(width=1200, height=675)
        doc.save(path)
        doc.close()
        return path

    def _screen(self, path):
        import pymupdf as fitz
        doc = fitz.open(path)
        page = doc[0]
        kind, refs = doc.xref_get_key(page.xref, 'Annots')
        screens = [int(r) for r in refs.strip('[]').replace('0 R', '').split()] if kind == 'array' else []
        return doc, page, [x for x in screens if doc.xref_get_key(x, 'Subtype')[1] == '/Screen']

    def test_the_video_is_embedded_where_it_stands_and_plays(self):
        import tempfile

        from wama.common.utils.pdf_pages import embed_videos
        data = b'\x00\x00\x00\x18ftypmp42' + bytes(range(256)) * 40
        with tempfile.TemporaryDirectory() as folder:
            path = self._pdf(folder)
            self.assertEqual(1, embed_videos(path, [{'page': 0, 'box': (0.25, 0.1, 0.5, 0.4),
                                                     'data': data, 'name': 'clip.mp4',
                                                     'mime': 'video/mp4'}]))
            doc, page, screens = self._screen(path)
            self.assertEqual(1, len(screens))
            annot = screens[0]
            # Fractions of the page, origin at the top left (a browser's) → PDF points, bottom left.
            rect = [float(c) for c in doc.xref_get_key(annot, 'Rect')[1].strip('[]').split()]
            self.assertEqual([300.0, 337.5, 900.0, 607.5], rect)
            for trigger in ('A', 'AA/PV'):
                with self.subTest(trigger=trigger):
                    self.assertEqual('/Rendition', doc.xref_get_key(annot, f'{trigger}/S')[1])
            self.assertEqual('xref', doc.xref_get_key(annot, 'AP/N')[0])
            rendition = int(doc.xref_get_key(annot, 'A/R')[1].split()[0])
            clip = int(doc.xref_get_key(rendition, 'C')[1].split()[0])
            self.assertEqual('video/mp4', doc.xref_get_key(clip, 'CT')[1])
            spec = int(doc.xref_get_key(clip, 'D')[1].split()[0])
            stream = int(doc.xref_get_key(spec, 'EF/F')[1].split()[0])
            self.assertEqual(data, doc.xref_stream(stream))
            doc.close()

    def test_every_video_a_step_contains_is_playable_on_that_step_page(self):
        """UNIVERSAL, read in the page and never written per video : a minimal presentation of the
        canvas engine (`window.WamaPrez`, its `wama:step` event), rendered by the real Chromium — the
        video of step 2 lands on page 2, page 1 has none. Skipped when no Chromium is installed."""
        import tempfile

        from wama.common.utils.html_render import render_page_to_pdf
        data = b'\x00\x00\x00\x18ftypmp42' + bytes(range(256)) * 8
        html = """<!doctype html><html><body style="margin:0">
<div class="frame" id="one" style="width:1600px;height:900px">first step</div>
<div class="frame" id="two" style="width:1600px;height:900px;display:none">
  <video src="/static/any/clip.mp4" style="position:absolute;left:400px;top:225px;width:800px;height:450px"></video>
</div>
<script>
const steps = [...document.querySelectorAll('.frame')];
window.WamaPrez = {steps, go(i) {
  steps.forEach((f, n) => { f.style.display = n === i ? 'block' : 'none'; });
  document.dispatchEvent(new CustomEvent('wama:step', {detail: {index: i, frame: steps[i], settled: true}}));
}};
</script></body></html>"""

        def fetch(target):
            return (200, 'video/mp4', data) if target.startswith('/static/any/clip.mp4') \
                else (404, 'text/plain', b'')

        with tempfile.TemporaryDirectory() as folder:
            path = f'{folder}/slides.pdf'
            if not render_page_to_pdf(html, path, fetch=fetch, path='/p/', slides=True):
                self.skipTest('Chromium indisponible ici')
            import pymupdf as fitz
            doc = fitz.open(path)
            self.assertEqual(2, doc.page_count)
            screens = []
            for page in doc:
                kind, refs = doc.xref_get_key(page.xref, 'Annots')
                screens.append([int(r) for r in refs.strip('[]').replace('0 R', '').split()]
                               if kind == 'array' else [])
            self.assertEqual([], screens[0])
            self.assertEqual(1, len(screens[1]))
            box = doc[1].mediabox
            rect = [float(c) for c in doc.xref_get_key(screens[1][0], 'Rect')[1].strip('[]').split()]
            # The video's place on the screen (a quarter in from each side), on the PDF page.
            self.assertEqual([round(c) for c in (box.width / 4, box.height / 4, box.width * 3 / 4,
                                                 box.height * 3 / 4)], [round(c) for c in rect])
            rendition = int(doc.xref_get_key(screens[1][0], 'A/R')[1].split()[0])
            clip = int(doc.xref_get_key(rendition, 'C')[1].split()[0])
            spec = int(doc.xref_get_key(clip, 'D')[1].split()[0])
            self.assertEqual(data, doc.xref_stream(int(doc.xref_get_key(spec, 'EF/F')[1].split()[0])))
            doc.close()

    def test_a_video_that_cannot_be_read_leaves_the_pdf_as_it_was(self):
        import tempfile

        from wama.common.utils.html_render import _embed_step_videos
        with tempfile.TemporaryDirectory() as folder:
            path = self._pdf(folder)
            before = open(path, 'rb').read()
            with self.assertLogs('wama.common.utils.html_render', 'WARNING'):
                _embed_step_videos(path, [{'src': 'http://wama.page/static/missing.mp4', 'page': 0,
                                           'box': (0, 0, 1, 1)}],
                                   lambda target: (404, 'text/plain', b''), 'http://wama.page')
            self.assertEqual(before, open(path, 'rb').read())

    def test_each_video_is_reencoded_by_the_converter_at_the_chosen_quality(self):
        """The export's quality is the COMMON output's (`output_quality`) : the video is re-encoded
        in MP4 by the converter's inline conversion — the one every app uses — never the source."""
        import tempfile
        from pathlib import Path
        from unittest import mock

        from wama.common.utils import html_render

        seen = {}

        def convert(source, fmt, preset, **kwargs):
            seen.update(fmt=fmt, preset=preset, source_kept=Path(source).read_bytes())
            out = Path(source).with_suffix('.mp4')
            out.write_bytes(b'lighter')
            return str(out)

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch('wama.converter.utils.inline_convert.apply_inline_conversion',
                           side_effect=convert), \
                mock.patch('wama.common.utils.pdf_pages.embed_videos') as embed:
            html_render._embed_step_videos(
                f'{folder}/slides.pdf', [{'src': 'http://wama.page/static/v/clip.webm', 'page': 1,
                                          'box': (0, 0, 1, 1)}],
                lambda target: (200, 'video/webm', b'served'), 'http://wama.page', 'web')
        self.assertEqual({'fmt': 'mp4', 'preset': 'web', 'source_kept': b'served'}, seen)
        placed = embed.call_args.args[1][0]
        self.assertEqual((b'lighter', 'clip.mp4', 'video/mp4'),
                         (placed['data'], placed['name'], placed['mime']))

    def test_the_export_options_are_the_common_output_quality_read_by_the_gate(self):
        from wama.common.services.page_pdf import export_params, read_export_options
        self.assertEqual([], export_params(slides=False))
        self.assertEqual(['output_quality'], [p.name for p in export_params(slides=True)])
        # Nothing posted (the presentation's own PDF button) : « Rapide », the export's declared default.
        self.assertEqual({'output_quality': 'web'}, read_export_options({}, slides=True))
        self.assertEqual({'output_quality': 'web'},
                         read_export_options({'output_quality': 'web'}, slides=True))
        with self.assertRaises(ValueError):
            read_export_options({'output_quality': 'ultra'}, slides=True)
        self.assertEqual({}, read_export_options({'output_quality': 'web'}, slides=False))

    def test_the_options_of_a_slides_page_are_served_and_a_document_has_none(self):
        import json

        from django.urls import reverse

        from wama import views
        request = RequestFactory().get('/')
        presentation = json.loads(views.page_pdf_options(request, 'presentation').content)
        self.assertEqual(['output_quality'], [p['name'] for p in presentation['schema']])
        # « Rapide » by default for the export (Fabien, 2026-11-19), the common default elsewhere.
        self.assertEqual({'output_quality': 'web'}, presentation['values'])
        from wama.common.utils.output_formats import DEFAULT_PRESET, output_quality_param
        self.assertEqual(DEFAULT_PRESET, output_quality_param().default)
        document = json.loads(views.page_pdf_options(request, 'fiches').content)
        self.assertEqual([], document['schema'])
        self.assertTrue(reverse('presentation_pdf_options').endswith('/presentation/pdf/options/'))

    def test_the_export_script_parses_and_is_served_as_written(self):
        from pathlib import Path

        from django.conf import settings
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv')
        name = 'wama-export-options.js'
        src = Path(settings.BASE_DIR, 'wama/common/static/common/js', name).read_text(encoding='utf-8')
        served = Path(settings.BASE_DIR, 'staticfiles/common/js', name).read_text(encoding='utf-8')
        MiniRacer().eval('(function(){' + src + '\n})')
        self.assertEqual(served, src)

    def test_a_new_rendering_does_not_serve_the_old_cached_pdf(self):
        """The cache is keyed by the rendered HTML : the HTML of the presentation did not change when
        its videos became playable, so the version of the rendering is part of the key."""
        import tempfile
        from pathlib import Path
        from unittest import mock

        from wama.common.services import page_pdf
        from wama.common.utils import html_render

        def render(html, output_path, **kwargs):
            Path(output_path).write_bytes(b'%PDF-1.4 ' + str(html_render.PAGE_RENDER_VERSION).encode())
            return True

        with tempfile.TemporaryDirectory() as folder, \
                mock.patch.object(page_pdf, 'CACHE_DIR', Path(folder)), \
                mock.patch('django.template.loader.render_to_string', return_value='<html>same</html>'), \
                mock.patch.object(html_render, 'render_page_to_pdf', side_effect=render):
            first = page_pdf.page_pdf(None, 'any.html', page_path='/p/', slides=True)
            with mock.patch.object(html_render, 'PAGE_RENDER_VERSION', html_render.PAGE_RENDER_VERSION + 1):
                second = page_pdf.page_pdf(None, 'any.html', page_path='/p/', slides=True)
            self.assertNotEqual(first, second)
            self.assertNotEqual(first.read_bytes(), second.read_bytes())
