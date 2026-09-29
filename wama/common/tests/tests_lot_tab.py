"""The « Lot » tab of the v4 input card (2026-09-29, Fabien's decision — CARD_DESIGN §11.11).

A batch file is not a PORT: a port is an input of a Studio node (`studio_node_ports`), carried by
manifests and pipelines, while each line of a batch file fills a WHOLE card — work file, prompt,
reference, output, settings, schedule (`BATCH_FORMAT.md`). So the card gets a tab rendered like
the ports and derived from the app's `has_batch` declaration, never declared among the ports.

What is held here:
  * the tab exists iff the app declares `has_batch`, and is never a port;
  * the lot format and the batch template left the work tile — `#batchTemplateLink` (a nightly
    gesture contract) exists exactly ONCE, in the Lot pane;
  * `WamaBatchImport` registers under the base of its bar, previews a file the user DECLARED to
    be a lot (a `.pdf` included) and SAYS a refusal, while the implicit path (a file dropped on
    the work port) still stays silent — that silence is what lets it fall back to a direct upload.

⚠ `py_mini_racer` is only installed in venv_win: the V8 tests SKIP under venv_linux.
"""
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase

ROOT = Path(settings.BASE_DIR)
SERVED = ROOT / 'staticfiles'
TOUCHED = ['common/js/batch-import.js', 'common/js/wama-input-slots.js', 'common/js/wama-import.js',
           'common/css/wama-input-slots.css']

WORK_PORT = {'id': 'work_file', 'label': 'Fichier', 'group': 'travail', 'types': ['image'],
             'multi': True, 'required': True, 'description': 'texte'}


def _render(app, **extra):
    context = {'app_id': app, 'collapsible': True, 'file_input_id': 'f', 'drop_zone_id': 'z',
               'folder_input_id': 'd', 'formats_label': 'x',
               'batch_template_url': '/tpl/', 'show_batch_bar': True, **extra}
    with patch('wama.common.app_registry.app_input_ports', return_value=[WORK_PORT]):
        return render_to_string('common/_new_item_card_v4.html', context)


class LotTabTemplateTest(TestCase):

    def _catalog(self, has_batch):
        from wama.common.app_registry import APP_CATALOG
        entry = {'label': 'Witness', 'input_types': ('image',), 'output_types': ('image',),
                 'has_batch': has_batch}
        return patch.dict(APP_CATALOG, {'app_lot_witness': entry})

    def test_the_tab_comes_from_the_has_batch_declaration(self):
        with self._catalog(True):
            declared = _render('app_lot_witness')
        with self._catalog(False):
            silent = _render('app_lot_witness')
        self.assertIn('data-port-tab="lot"', declared)
        self.assertIn('data-port-pane="lot"', declared)
        self.assertNotIn('data-port-tab="lot"', silent)

    def test_the_lot_is_never_a_port(self):
        from wama.common.app_registry import APP_CATALOG, studio_node_ports
        for app, spec in APP_CATALOG.items():
            if spec.get('has_batch'):
                with self.subTest(app=app):
                    ids = [p.get('id') for p in (studio_node_ports(app) or {}).get('inputs') or []]
                    self.assertNotIn('lot', ids)

    def test_the_batch_template_link_exists_once_and_in_the_lot_pane(self):
        with self._catalog(True):
            html = _render('app_lot_witness')
        self.assertEqual(1, html.count('id="batchTemplateLink"'))
        self.assertGreater(html.index('id="batchTemplateLink"'), html.index('data-port-pane="lot"'))

    def test_without_the_tab_the_template_link_stays_under_the_work_tile(self):
        """An app without `has_batch` keeps its previous display exactly."""
        with self._catalog(False):
            html = _render('app_lot_witness')
        self.assertEqual(1, html.count('id="batchTemplateLink"'))

    def test_the_lot_input_accepts_every_format_the_server_reads(self):
        from wama.common.utils.batch_parsers import SUPPORTED_BATCH_EXTENSIONS
        with self._catalog(True):
            html = _render('app_lot_witness', card_id='c')
        start = html.index('id="c-lot-input"')
        tag = html[html.rindex('<input', 0, start):html.index('>', start)]
        for ext in SUPPORTED_BATCH_EXTENSIONS:
            self.assertIn('.' + ext, tag)

    def test_the_lot_pane_speaks_to_the_bar_of_its_own_card(self):
        """Two lot bars on one page (the imager's video card): each pane names ITS base."""
        with self._catalog(True):
            html = _render('app_lot_witness', batch_bid='vidBatch')
        self.assertIn('data-lot-base="vidBatch"', html)
        self.assertIn('id="vidBatchDetectBar"', html)


BATCH_ENV = r"""
var events = [], toasts = [], fetchReply = null;
function El(id) { this.id = id; this.style = { display: 'none' }; this.textContent = '';
  this.innerHTML = ''; this.addEventListener = function () {}; this.insertAdjacentHTML = function () {};
  this.dispatchEvent = function (ev) { events.push([ev.type, ev.detail]); }; }
var els = {};
var document = { readyState: 'complete', addEventListener: function () {},
                 getElementById: function (id) { return els[id] || (els[id] = new El(id)); } };
function CustomEvent(type, o) { this.type = type; this.detail = o.detail; }
function FormData() { this.append = function () {}; }
var window = { WamaApp: { toast: function (m, k) { toasts.push([k, m]); } } };
var console = { error: function () {} };
function fetch() { return Promise.resolve({ json: function () { return Promise.resolve(fetchReply); } }); }
"""


class LotBatchImportJsTest(SimpleTestCase):

    def _ctx(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter les briques')
        ctx = MiniRacer()
        ctx.eval(BATCH_ENV)
        ctx.eval((SERVED / 'common/js/batch-import.js').read_text(encoding='utf-8'))
        ctx.eval("var a = WamaBatchImport({batchPreviewUrl: '/p', batchCreateUrl: '/c', csrfToken: 't'});")
        return ctx

    def _run(self, ctx, reply, call):
        ctx.eval(f'events = []; toasts = []; fetchReply = {reply}; var r;'
                 f' {call}.then(function (x) {{ r = x; }}, function (e) {{ r = "REJECT " + e; }});')
        for _ in range(3):
            ctx.eval('0')                                    # drain the microtasks
        return ctx.eval('JSON.stringify({r: r, events: events, toasts: toasts})')

    def test_the_touched_files_parse_and_are_served_as_written(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv')
        for rel in TOUCHED:
            with self.subTest(file=rel):
                source = ROOT / 'wama' / 'common' / 'static' / rel
                self.assertEqual(source.read_bytes(), (SERVED / rel).read_bytes())
                if rel.endswith('.js'):
                    MiniRacer().eval('(function(){' + source.read_text(encoding='utf-8') + '\n})')

    def test_each_instance_registers_under_the_base_of_its_bar(self):
        ctx = self._ctx()
        ctx.eval("var v = WamaBatchImport({idBase: 'vidBatch', batchPreviewUrl: '/p', batchCreateUrl: '/c', csrfToken: 't'});")
        self.assertTrue(ctx.eval('WamaBatchImport.instances.batch === a && WamaBatchImport.instances.vidBatch === v'))

    def test_a_declared_lot_is_previewed_even_as_a_pdf_and_the_bar_says_so(self):
        import json
        out = json.loads(self._run(self._ctx(), '{count: 3, items: []}',
                                   "a.previewFile({name: 'lot.pdf', type: 'application/pdf'})"))
        self.assertIs(True, out['r'])
        self.assertEqual([['wama:batch-shown', {'base': 'batch', 'count': 3, 'name': 'lot.pdf'}]],
                         out['events'])

    def test_a_declared_lot_that_yields_nothing_is_SAID(self):
        import json
        out = json.loads(self._run(self._ctx(), "{count: 0, warnings: ['ligne 1 : introuvable']}",
                                   "a.previewFile({name: 'lot.csv', type: 'text/csv'})"))
        self.assertIs(False, out['r'])
        self.assertEqual(1, len(out['toasts']), out)
        self.assertEqual('error', out['toasts'][0][0])
        self.assertIn('ligne 1 : introuvable', out['toasts'][0][1])

    def test_a_port_tile_rejects_with_the_import_rule_and_any_type_accepts_all(self):
        """`WamaImport.accepts` is the ONE rule (the v4 port tile uses it on drop). « Any
        type » used to be read as « a type starting with star-slash », i.e. no file at all."""
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv')
        ctx = MiniRacer()
        ctx.eval('var window = this; var document = {};')
        ctx.eval((SERVED / 'common/js/wama-import.js').read_text(encoding='utf-8'))
        ctx.eval("function inp(a) { return { getAttribute: function () { return a; } }; }"
                 "var mp3 = {name: 'a.mp3', type: 'audio/mpeg'}, txt = {name: 'a.txt', type: 'text/plain'};")
        self.assertTrue(ctx.eval("WamaImport.accepts(inp('audio/*'), mp3)"))
        self.assertFalse(ctx.eval("WamaImport.accepts(inp('audio/*'), txt)"))
        self.assertTrue(ctx.eval("WamaImport.accepts(inp('.mp3,.wav'), mp3)"))
        self.assertTrue(ctx.eval("WamaImport.accepts(inp('*/*'), txt)"))
        self.assertTrue(ctx.eval("WamaImport.accepts(inp(''), txt)"))

    def test_the_implicit_path_still_stays_silent_on_a_pdf(self):
        """Counter-proof: a PDF dropped on the WORK port is a document to process, not a lot."""
        import json
        out = json.loads(self._run(self._ctx(), '{count: 3, items: []}',
                                   "a.detectAndHandle({name: 'doc.pdf', type: 'application/pdf'})"))
        self.assertIs(False, out['r'])
        self.assertEqual([], out['events'])
        self.assertEqual([], out['toasts'])
