"""The studio CATALOGUE (`WAMA_APP_GENERATION_ROUTE §10.6` 5.4, 2026-10-03).

Three corrections noted on 2026-09-15, built here: the left palette is a « Catalogue » in
collapsible sections (inputs · outputs · pipelines · apps · functions by category) ; the saved
pipelines — mine and the ones the apps declare — are IN it, not only in the toolbar selector ; a
node is dropped where the user wants it. And the canvas speaks the six common states.

What a browser alone could attest (the drag, the toggle) is Fabien's test ; what is held here is
the CONTRACT read by the page, and that the script still parses under V8 (no `node` on this host).
"""
import importlib.util
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

STUDIO = Path(settings.BASE_DIR) / 'wama' / 'studio'
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None


def _src(rel):
    return (STUDIO / rel).read_text(encoding='utf-8')


class CatalogueContractTest(SimpleTestCase):

    def test_the_palette_is_a_catalogue_in_the_decided_sections(self):
        page = _src('templates/studio/index.html')
        self.assertIn('>Catalogue<', page)
        self.assertNotIn('>Apps<', page, 'the old title (« Apps ») is gone')
        self.assertIn('id="studioPaletteList"', page, 'the id the script fills')
        js = _src('static/studio/js/wama-studio.js')
        for key in ('inputs', 'outputs', 'pipelines', 'apps', 'functions'):
            self.assertIn(f"paletteSection('{key}'", js, f'section « {key} » missing')
        self.assertNotIn("'Library'", js, '« Library » names the pip packages, never the catalogue')

    def test_saved_and_declared_pipelines_open_from_the_catalogue_by_the_selector_path(self):
        js = _src('static/studio/js/wama-studio.js')
        self.assertIn("paletteItem(p.value, p, openPipeline)", js)
        self.assertIn("'declared:' + p.key", js, 'the declared pipelines of the apps are listed too')
        self.assertIn("if (sel && sel.value) openPipeline(sel.value);", js,
                      'the toolbar selector and the catalogue share ONE opener')

    def test_a_node_is_dropped_where_the_user_wants_it(self):
        js = _src('static/studio/js/wama-studio.js')
        self.assertIn("var PALETTE_MIME = 'text/wama-node';", js)
        self.assertIn("item.draggable = true;", js)
        self.assertIn("canvas.addEventListener('drop'", js)
        # Drag-and-drop INSTEAD of the click (decision of 15/09; the click survived until 07/10).
        # Only a pipeline (a document, not a node) still reacts to a click.
        self.assertNotIn("(onPick || addNode)", js, 'a click on the catalogue no longer adds a node')
        self.assertIn("item.addEventListener('click', function () { onPick(id); });", js)
        # The global `.drag-over` is the FILE drop class ("Déposez le fichier ici"): not for a node.
        self.assertNotIn("'drag-over'", js)
        self.assertIn('.studio-canvas.is-drop-target', _src('static/studio/css/wama-studio.css'))
        # Sous le curseur, en coordonnées du MONDE : la vue défile et zoome depuis le 2026-10-07.
        self.assertIn("var p = toWorld(e.clientX, e.clientY);", js)
        # Rounded: the position ends in the `layout` of a versioned pipeline manifest.
        self.assertIn("addNode(id, { x: Math.round(p.x - 20), y: Math.round(p.y - 12) });", js)

    def test_the_canvas_pans_and_zooms_and_the_graph_stays_in_world_coordinates(self):
        js = _src('static/studio/js/wama-studio.js')
        self.assertIn("canvas.addEventListener('wheel'", js, 'wheel zoom')
        self.assertIn("{ passive: false }", js, 'the wheel must be able to stop the page scroll')
        self.assertIn("world.appendChild(box);", js, 'nodes live in the world, not the viewport')
        # Port measured in LAYOUT (offsets), not on screen: a 1 px screen rounding divided by
        # the zoom froze a 4.5-unit gap into the link at 22 % (measured in the browser).
        self.assertIn("x += e.offsetLeft; y += e.offsetTop;", js,
                      'links are drawn in world coordinates, whatever the view')
        self.assertNotIn("dot.getBoundingClientRect()", js)
        self.assertIn("node.x = Math.round(ox + (ev.clientX - startX) / view.k);", js,
                      'a node drag follows the zoom')
        page = _src('templates/studio/index.html')
        self.assertIn('id="studioWorld"', page)
        self.assertIn('data-zoom="fit"', page)

    def test_the_canvas_speaks_the_six_common_states(self):
        js = _src('static/studio/js/wama-studio.js')
        self.assertIn("['PENDING', 'AWAITING_RESOURCES', 'RUNNING', 'SUCCESS', 'FAILURE', 'STALE']", js)
        css = _src('static/studio/css/wama-studio.css')
        for state in ('pending', 'awaiting_resources', 'running', 'success', 'failure', 'stale'):
            self.assertIn(f'.studio-node.run-{state}', css, f'no style for the common state {state}')

    def test_the_served_copies_are_the_sources(self):
        for rel in ('js/wama-studio.js', 'css/wama-studio.css'):
            served = Path(settings.BASE_DIR) / 'staticfiles' / 'studio' / rel
            self.assertEqual(_src('static/studio/' + rel), served.read_text(encoding='utf-8'),
                             f'staticfiles/studio/{rel} differs from its source — resync')


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class StudioScriptParsesTest(SimpleTestCase):

    def test_the_studio_script_parses_under_v8(self):
        from py_mini_racer import MiniRacer
        MiniRacer().eval('(function(){' + _src('static/studio/js/wama-studio.js') + '\n})')
