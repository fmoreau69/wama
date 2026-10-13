"""ONE preview brick, ONE face switch, ONE navigation — held without a browser (V8 and sources).

Asked by Fabien (2026-10-13) : « extrais la bascule du volet en brique commune […] une seule brique
commune de preview devrait suffire, s'adaptant à l'appel (filemanager, modale de card, volet droit,
plein écran) », and « dans les applications la navigation dans la preview ne semble plus
fonctionner : les flèches ne mettent pas la preview à jour […] l'Imager a 4 images par card […] et
dans le filemanager ».

Measured before the fix (browser, test account) : the viewer opened from a card ignored ←/→ (no
sequence of cards) ; ↓ moved the panel selection BEHIND the viewer, which did not change ; an imager
card showed only the first of its images ; after one file-manager preview, an arrow in a CARD's viewer
showed a file of the file manager's folder (its own key listener). The gestures themselves are played
in a browser by the nightly scenario `common.preview_navigation`; held here : the pure rules and the
structure that keeps one brick.
"""
import importlib.util
import json
import re
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from .tests_cap_from_js import FAKE_DOM, JS

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
FILEMANAGER_JS = Path(settings.BASE_DIR) / 'wama' / 'filemanager' / 'static' / 'filemanager' / 'js' / 'filemanager.js'

#: A DOM element good enough for `sidesBar` (classes, attributes, children, one listener per type).
FAKE_ELEMENTS = """
document.createElement = function (tag) {
  var el = {tagName: tag, children: [], attrs: {}, listeners: {}, className: '', innerHTML: '',
            style: {}, classList: classList(),
            appendChild: function (c) { el.children.push(c); return c; },
            setAttribute: function (k, v) { el.attrs[k] = v; },
            addEventListener: function (t, fn) { el.listeners[t] = fn; }};
  return el;
};
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class NavigationStepTest(SimpleTestCase):
    """Where an arrow leads : file by file then the next item (←/→), item by item (↑/↓)."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))

    def _step(self, pos, direction, by_card=False):
        return self.v8.eval(f'JSON.stringify(window.WamaMediaPreview.stepTarget('
                            f'{json.dumps(pos)}, {direction}, {json.dumps(by_card)}))')

    def test_the_files_of_an_item_come_first_then_the_next_item(self):
        # card 1 of 3, image 2 of 4
        pos = {'count': 3, 'index': 0, 'sub': 1, 'files': 4}
        self.assertEqual({'index': 0, 'sub': 2}, json.loads(self._step(pos, 1)))
        self.assertEqual({'index': 0, 'sub': 0}, json.loads(self._step(pos, -1)))
        last = dict(pos, sub=3)
        self.assertEqual({'index': 1, 'sub': 0}, json.loads(self._step(last, 1)),
                         'after the last image : the first image of the NEXT card')

    def test_going_back_arrives_on_the_last_file_of_the_previous_item(self):
        pos = {'count': 3, 'index': 1, 'sub': 0, 'files': 2}
        self.assertEqual({'index': 0, 'sub': -1}, json.loads(self._step(pos, -1)),
                         '-1 = the last file of the item, known once it is loaded')

    def test_up_and_down_jump_from_item_to_item(self):
        pos = {'count': 3, 'index': 1, 'sub': 2, 'files': 4}
        self.assertEqual({'index': 2, 'sub': 0}, json.loads(self._step(pos, 1, True)))
        self.assertEqual({'index': 0, 'sub': 0}, json.loads(self._step(pos, -1, True)))

    def test_the_edges_stop_and_a_lone_item_walks_its_files(self):
        self.assertEqual('null', self._step({'count': 3, 'index': 2, 'sub': 0, 'files': 1}, 1))
        self.assertEqual('null', self._step({'count': 3, 'index': 0, 'sub': 0, 'files': 1}, -1))
        self.assertEqual('null', self._step({'count': 1, 'index': 0, 'sub': 0, 'files': 1}, 1))
        lone = {'count': 1, 'index': 0, 'sub': 0, 'files': 3}
        self.assertEqual({'index': 0, 'sub': 1}, json.loads(self._step(lone, 1, True)),
                         'no sequence : ↑/↓ walk the files')

    def test_a_flat_sequence_is_walked_by_every_arrow(self):
        pos = {'count': 4, 'index': 1, 'sub': 0, 'files': 1}
        for by_card in (False, True):
            self.assertEqual(2, json.loads(self._step(pos, 1, by_card))['index'])


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class OneFaceSwitchTest(SimpleTestCase):
    """The face switch is built ONCE (`WamaMediaPreview.sidesBar`) for the panel and the viewer —
    the panel had its own copy, without the « Pendant » face."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + FAKE_ELEMENTS)
        self.v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))

    def _keys(self, face):
        return list(self.v8.eval(f'window.WamaMediaPreview.faceButtons({json.dumps(face)})'
                                 f'.map(function (b) {{ return b.key; }})'))

    def test_the_faces_in_chronological_order(self):
        sides = {'has_input': True, 'has_output': True, 'comparable': True, 'has_during': True,
                 'faces': [{'key': 'detect', 'label': 'Détection'}]}
        self.assertEqual(['input', 'detect', 'during', 'compare', 'output'],
                         self._keys({'side': 'output', 'sides': sides}))

    def test_a_face_exists_only_when_its_content_does(self):
        self.assertEqual(['input', 'output'],
                         self._keys({'sides': {'has_input': True, 'has_output': True}}))
        self.assertEqual(['input', 'during'], self._keys({'side': 'during', 'sides': {'has_input': True}}),
                         'the PENDING face being shown is offered, output or not')
        self.assertEqual(['input'], self._keys({'sides': {'has_input': True, 'comparable': True}}),
                         'Compare needs an output')
        self.assertEqual([], self._keys({}))

    def test_the_bar_routes_its_clicks_and_marks_the_shown_face(self):
        out = self.v8.eval("""(function () {
            var went = [], compared = 0;
            var face = {side: 'output', sides: {has_input: true, has_output: true, comparable: true}};
            var bar = window.WamaMediaPreview.sidesBar(face, {
                go: function (k) { went.push(k); }, compare: function () { compared++; }});
            bar.children.forEach(function (b) { b.listeners.click(); });
            return [bar.children.map(function (b) { return b.attrs['data-side']; }),
                    bar.children.map(function (b) { return / btn-info$/.test(b.className); }),
                    went, compared];
        })()""")
        self.assertEqual(['input', 'compare', 'output'], list(out[0]))
        self.assertEqual([False, False, True], list(out[1]), 'the face shown is the filled one')
        self.assertEqual(['input', 'output'], list(out[2]))
        self.assertEqual(1, out[3])

    def test_the_panel_and_the_viewer_have_their_own_density(self):
        out = self.v8.eval("""(function () {
            var P = window.WamaMediaPreview, face = {sides: {has_input: true, has_output: true}};
            var panel = P.sidesBar(face, {compact: true}), viewer = P.sidesBar(face, {});
            return [panel.className, panel.children[0].className, viewer.className,
                    viewer.children[0].className, P.sidesBar({sides: {has_input: true}}, {}) === null];
        })()""")
        self.assertIn('w-100', out[0])
        self.assertIn('flex-fill', out[1])
        self.assertNotIn('w-100', out[2])
        self.assertIn('px-3', out[3])
        self.assertTrue(out[4], 'one face : nothing to switch between, no bar')


class OnePreviewBrickTest(SimpleTestCase):
    """The preview lives in ONE brick ; the panel, the file manager and the pages consume it."""

    MOVED = ('renderInline', 'compareView', 'followDuring', 'variantToggle', 'duringUrl',
             'hydrateCardPreviews', 'sidesBar', 'compareFaces', 'cardOfPreview', 'isRunningCard')

    def test_each_preview_function_is_defined_once_in_the_common_js(self):
        sources = {path.name: path.read_text(encoding='utf-8') for path in JS.glob('*.js')}
        for name in self.MOVED + ('renderInlinePreview',):
            defined = [file for file, text in sources.items()
                       if re.search(r'\bfunction ' + name + r'\s*\(', text)]
            expected = [] if name == 'renderInlinePreview' else ['media-preview.js']
            self.assertEqual(expected, defined, name)

    def test_the_panel_builds_no_switch_of_its_own(self):
        panel = (JS / 'wama-inspector.js').read_text(encoding='utf-8')
        self.assertIn('P.sidesBar(', panel)
        # The icon of the Entry face is drawn by the brick only.
        self.assertNotIn('fa-right-to-bracket', panel)
        self.assertNotIn('_renderSideToggle', panel)

    def test_the_viewer_keyboard_has_one_listener(self):
        """The file manager's own arrows ran on ANY open viewer : after one file preview, an arrow
        in a card's viewer showed a file of its folder. The panel's arrows moved the selection
        behind the viewer, and its Escape deselected while closing it."""
        fm = FILEMANAGER_JS.read_text(encoding='utf-8')
        self.assertNotRegex(fm, r"'Arrow(Left|Right|Up|Down)'")
        self.assertIn('WamaMediaPreview', fm)
        self.assertIn('P.openSequence(', fm)
        for name in ('wama-inspector.js', 'wama-queue.js'):
            source = (JS / name).read_text(encoding='utf-8')
            self.assertIn("document.querySelector('.modal.show')", source, name)

    def test_no_reader_of_the_retired_navigation_hook(self):
        uses = {path: path.read_text(encoding='utf-8', errors='replace')
                for root in ('wama', 'wama_lab', 'wama_data')
                for path in Path(settings.BASE_DIR, root).rglob('*.js')
                if 'static' in path.parts}
        self.assertEqual([], [str(p) for p, text in uses.items() if 'setPreviewNavCallback' in text])

    def test_the_panel_hands_the_viewer_its_card(self):
        """Double-click on the panel's preview : the viewer of the ITEM, with the cards around it."""
        panel = (JS / 'wama-inspector.js').read_text(encoding='utf-8')
        self.assertIn('P.openForCard(m, _panelCard, 0)', panel)
        self.assertIn("addEventListener('wama:preview-card'", panel,
                      'closed on another card, the viewer has the panel select it')

    @skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
    def test_the_inspector_names_are_aliases_of_the_brick(self):
        from py_mini_racer import MiniRacer
        v8 = MiniRacer()
        v8.eval(FAKE_DOM)
        v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))
        v8.eval((JS / 'wama-inspector.js').read_text(encoding='utf-8'))
        out = v8.eval("[typeof window.WamaInspector.renderInlinePreview, "
                      "window.WamaInspector.duringUrl('/p/1/', null)]")
        self.assertEqual(['function', '/p/1/?side=during'], list(out))

    def test_the_nightly_gestures_are_registered(self):
        from wama.common.services import nightly_tests
        from wama.common.services.ui_smoke_preview import register_preview_scenarios
        register_preview_scenarios()
        self.assertIn('common.preview_navigation', {s.id for s in nightly_tests.REGISTRY})
