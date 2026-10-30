"""A setting PROPOSED by what the card's input is (2026-10-29, Fabien : « le switch s'adapte à
l'entrée, comme les filtrages bidirectionnels »).

`Param.default_from` (born 2026-10-04 for the composer's duration) gains a vocabulary of input
properties (`media_probe.INPUT_PROPERTIES`) and a NOTE that says why. What each test holds:
  * the common probe of a PDF measures its pages WITHOUT a text layer (`document_text`'s test),
    declared as attributes of the `document` nature — the media library stores what it measures;
  * `needs_ocr` proposes the OCR switch, with its reason, for a PDF only;
  * an element is BORN with the proposal between the panel's preferences and what is posted;
  * the card's input asks the same probe for an UPLOADED file the browser cannot read;
  * in the browser, a proposal ticks a switch and writes its note under it.
"""
import importlib.util
import json
import shutil
import tempfile
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from wama.common.tests.tests_cap_from_js import FAKE_DOM

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'
LINE = 'A native page with plenty of selectable text on it.'


def _pdfs(folder: Path) -> tuple:
    """(native.pdf, half_scanned.pdf, scanned.pdf) — built here, in `folder`."""
    import fitz
    with fitz.open() as pdf:
        pdf.new_page().insert_text((72, 100), LINE)
        pixmap = pdf[0].get_pixmap(dpi=50)
        pdf.save(str(folder / 'native.pdf'))
        scan = pdf.new_page()
        scan.insert_image(scan.rect, pixmap=pixmap)
        pdf.save(str(folder / 'half_scanned.pdf'))
    with fitz.open() as pdf:
        scan = pdf.new_page()
        scan.insert_image(scan.rect, pixmap=pixmap)
        pdf.save(str(folder / 'scanned.pdf'))
    return folder / 'native.pdf', folder / 'half_scanned.pdf', folder / 'scanned.pdf'


class _Folder(SimpleTestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='wama-proposals-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.native, self.half, self.scanned = _pdfs(self.dir)


class TheProbeMeasuresTheTextLayerTest(_Folder):

    def test_a_pdf_probe_tells_its_pages_without_text(self):
        from wama.common.utils.media_probe import probe_media
        half = probe_media(str(self.half))
        self.assertEqual({'pages': 2, 'pages_without_text': 1}, half['attributes'])
        self.assertEqual('PDF • 2 pages • 1 sans texte', half['properties'])
        native = probe_media(str(self.native))
        self.assertEqual({'pages': 1, 'pages_without_text': 0}, native['attributes'])
        self.assertEqual('PDF • 1 page', native['properties'])

    def test_the_document_nature_names_what_the_probe_measures(self):
        from wama.media_library.natures import is_canonical_attribute
        for name in ('pages', 'pages_without_text'):
            self.assertTrue(is_canonical_attribute('document', name), name)


class NeedsOcrIsProposedTest(_Folder):

    def _proposal(self, path):
        from wama.common.utils.media_probe import input_property, probe_media
        return input_property(probe_media(str(path)), 'needs_ocr')

    def test_a_pdf_without_text_asks_for_the_ocr_and_says_why(self):
        scanned = self._proposal(self.scanned)
        self.assertIs(True, scanned['value'])
        self.assertIn("l'OCR le lira", scanned['note'])
        half = self._proposal(self.half)
        self.assertIs(True, half['value'])
        self.assertIn('sur 1 page sur 2', half['note'])
        native = self._proposal(self.native)
        self.assertIs(False, native['value'])
        self.assertIn('porte son texte', native['note'])

    def test_another_document_or_an_unknown_property_proposes_nothing(self):
        from wama.common.utils.media_probe import input_property, probe_media
        text = self.dir / 'notes.txt'
        text.write_text('hello', encoding='utf-8')
        self.assertIsNone(self._proposal(text))
        self.assertIsNone(input_property(probe_media(str(self.scanned)), 'no_such_property'))


SWITCH = {'name': 'preprocess_audio', 'type': 'toggle', 'default': False,
          'contexts': ['item', 'batch', 'panel'],
          'default_from': {'port': 'source', 'property': 'needs_ocr'}}


class AnElementIsBornWithTheProposalTest(TestCase):
    """The cascade of `new_element_settings`: defaults ← panel ← PROPOSED BY THE INPUT ← posted.
    A real boolean column (`Transcript.preprocess_audio`) stands for any switch."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix='wama-proposals-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.native, _, self.scanned = _pdfs(self.dir)
        self.user = get_user_model().objects.create_user('proposals_born', password='x')

    def _born(self, path, post=None):
        from wama.common.utils.user_settings import new_element_settings
        from wama.transcriber.models import Transcript
        return new_element_settings(self.user, 'proposals_test', [SWITCH], Transcript,
                                    post=post, inputs={'source': str(path)})['preprocess_audio']

    def test_the_input_beats_the_panel_and_the_post_beats_the_input(self):
        from wama.common.utils.user_settings import save_panel_settings
        self.assertIs(True, self._born(self.scanned))
        save_panel_settings(self.user, 'proposals_test', [SWITCH], {'preprocess_audio': 'true'})
        self.assertIs(False, self._born(self.native), 'a native PDF unticks a remembered switch')
        self.assertIs(False, self._born(self.scanned, post={'preprocess_audio': 'false'}))

    def test_an_uploaded_file_is_probed_where_it_lies(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        from wama.common.utils.user_settings import input_proposals
        upload = SimpleUploadedFile('scan.pdf', self.scanned.read_bytes(), 'application/pdf')
        self.assertIs(True, input_proposals([SWITCH], {'source': upload})['preprocess_audio']['value'])
        self.assertEqual({}, input_proposals([SWITCH], {'other_port': upload}))


class TheCardAsksTheProbeTest(TestCase):

    def setUp(self):
        self.media = tempfile.mkdtemp()
        override = override_settings(MEDIA_ROOT=self.media)
        override.enable()
        self.addCleanup(override.disable)
        self.addCleanup(shutil.rmtree, self.media, True)
        self.dir = Path(tempfile.mkdtemp(prefix='wama-proposals-'))
        self.addCleanup(shutil.rmtree, self.dir, True)
        _, _, self.scanned = _pdfs(self.dir)
        self.user = get_user_model().objects.create_user('proposals_card', password='x')
        self.client.force_login(self.user)

    def test_an_uploaded_pdf_is_probed_and_nothing_is_kept(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        upload = SimpleUploadedFile('scan.pdf', self.scanned.read_bytes(), 'application/pdf')
        response = self.client.post(reverse('common:api_media_probe'),
                                    {'file': upload, 'properties': 'needs_ocr'})
        self.assertEqual(200, response.status_code)
        data = response.json()
        self.assertIs(True, data['proposals']['needs_ocr']['value'])
        self.assertEqual({'pages': 1, 'pages_without_text': 1}, data['attributes'])
        self.assertEqual([], list(Path(self.media).rglob('*')), 'the probe keeps nothing')

    def test_a_designated_pdf_gives_the_same_proposal(self):
        rel = f'users/{self.user.pk}/temp/scan.pdf'
        target = Path(self.media) / rel
        target.parent.mkdir(parents=True)
        shutil.copy(self.scanned, target)
        response = self.client.get(reverse('common:api_media_probe'),
                                   {'path': rel, 'properties': 'needs_ocr'})
        self.assertIs(True, response.json()['proposals']['needs_ocr']['value'])


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class TheSwitchFollowsTheInputTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + "\ndocument.cookie = ''; var navigator = {}; var localStorage = "
                     "{getItem: function () { return null; }, setItem: function () {}};")
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        self.v8.eval((JS / 'wama-input-slots.js').read_text(encoding='utf-8'))
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _js(self, expr):
        return json.loads(self.v8.eval(f'JSON.stringify({expr})'))

    def test_a_server_proposal_ticks_the_switch_and_says_why_under_it(self):
        self.v8.eval("""
            var listeners = {}, fired = [], asked = [];
            var input = {addEventListener: function (t, f) { listeners[t] = f; }};
            var notes = [];
            var row = {querySelector: function () { return null; },
                       appendChild: function (n) { notes.push(n); }};
            var box = {type: 'checkbox', checked: false, closest: function () { return row; },
                       dispatchEvent: function (e) { fired.push(e.type); }};
            var pane = {getAttribute: function (a) {
              return {'data-port-pane': 'source_document', 'data-port-input': 'docInput'}[a]; }};
            document.querySelectorAll = function (sel) {
              return sel.indexOf('data-port-pane') !== -1 ? [pane] : []; };
            document.getElementById = function (id) {
              return id === 'docInput' ? input : (id === 'ocrSwitch' ? box : null); };
            document.createElement = function () { return {className: '', textContent: ''}; };
            var CSS = {escape: function (s) { return s; }};
            var container = {querySelector: function (sel) {
              return sel === '#ocrSwitch' ? box : null; }};
            window.WamaApp.inputProposals = function (i, props) {
              asked.push(props.join(','));
              return Promise.resolve({needs_ocr: {value: true, note: 'Ce PDF n\\'a pas de texte.'}});
            };
            window.WamaParams.bindDefaultFrom(container, [{name: 'ocr', dom_id: {panel: 'ocrSwitch'},
              contexts: ['panel'], default_from: {port: 'source_document', property: 'needs_ocr'}}],
              'panel');
            listeners.change();
        """)
        self.assertEqual({'checked': True, 'note': "Ce PDF n'a pas de texte.", 'asked': ['needs_ocr'],
                          'fired': ['input', 'change']},
                         self._js("{checked: box.checked, note: notes[0] && notes[0].textContent,"
                                  " asked: asked, fired: fired}"))

    def test_the_duration_note_reads_the_same_in_the_browser_and_on_the_server(self):
        """The browser reads an uploaded file's duration itself and writes the note; the server
        writes it for a designated file or at birth — one sentence, two writers: parity guard."""
        from wama.common.utils.media_probe import format_duration, input_property
        self.v8.eval("""
            var listeners = {}, notes = [];
            var input = {addEventListener: function (t, f) { listeners[t] = f; }};
            var row = {querySelector: function () { return null; },
                       appendChild: function (n) { notes.push(n); }};
            var slider = {value: '10', step: '1', min: '1', max: '600', closest: function () { return row; },
                          dispatchEvent: function () {}};
            var pane = {getAttribute: function (a) {
              return {'data-port-pane': 'work_audio', 'data-port-input': 'songInput'}[a]; }};
            document.querySelectorAll = function (sel) {
              return sel.indexOf('data-port-pane') !== -1 ? [pane] : []; };
            document.getElementById = function (id) {
              return id === 'songInput' ? input : (id === 'durationSlider' ? slider : null); };
            document.createElement = function () { return {className: '', textContent: ''}; };
            var CSS = {escape: function (s) { return s; }};
            var container = {querySelector: function (sel) {
              return sel === '#durationSlider' ? slider : null; }};
            window.WamaApp.mediaDuration = function () { return Promise.resolve(210); };
            window.WamaParams.bindDefaultFrom(container, [{name: 'duration', dom_id:
              {panel: 'durationSlider'}, contexts: ['panel'],
              default_from: {port: 'work_audio', property: 'duration'}}], 'panel');
            listeners.change();
        """)
        server = input_property({'duration': 210, 'duration_display': format_duration(210)},
                                'duration')['note']
        self.assertEqual(server, self._js('notes[0].textContent'))

    def test_a_native_pdf_unticks_it_and_an_empty_answer_changes_nothing(self):
        self.assertEqual([False, True], self._js("""(function () {
            var a = {type: 'checkbox', checked: true, dispatchEvent: function () {}};
            window.WamaParams.applyProposal(a, {value: false, note: ''});
            var b = {type: 'checkbox', checked: true, dispatchEvent: function () {}};
            window.WamaParams.applyProposal(b, null);
            return [a.checked, b.checked]; })()"""))
