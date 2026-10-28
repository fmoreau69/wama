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
class SelectionAcrossAppsTest(SimpleTestCase):
    """The journal and the calendar mix the items of ten apps : two cards there carry the same
    `data-id` (item 5 of the transcriber, item 5 of the imager). A click selects the card that was
    CLICKED (2026-10-18) ; the search by number took the first one. Counter-proof : called with a
    number only (an app's own call), the selection is the one of before."""

    SETUP = """
    function fakeCard(app) {
      return {dataset: {id: '5', app: app}, classList: classList(),
              matches: function () { return false; }, querySelector: function () { return null; }};
    }
    var first = fakeCard('transcriber'), second = fakeCard('imager'), handlers = {};
    var qc = {addEventListener: function (t, fn) { handlers[t] = fn; },
              contains: function (el) { return el === first || el === second; },
              querySelector: function () { return first; },
              querySelectorAll: function (sel) {     // the highlighted cards, for `clearHighlight`
                return [first, second].filter(function (c) {
                  return sel === '.inspector-selected' && c.classList.contains('inspector-selected'); });
              }};
    var insp = window.WamaInspector.init({queueContainer: qc, cardSelector: '.c', keyboardNav: false});
    function selected() {
      return [first, second].filter(function (c) { return c.classList.contains('inspector-selected'); })
                            .map(function (c) { return c.dataset.app; }).join(',');
    }
    """

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-inspector.js').read_text(encoding='utf-8'))
        self.v8.eval(self.SETUP)

    def test_a_click_selects_the_clicked_card_not_the_first_with_its_number(self):
        self.v8.eval("handlers.click({target: {closest: function (s) { return s === '.c' ? second : null; }}})")
        self.assertEqual('imager', self.v8.eval('selected()'))

    def test_the_card_given_by_the_caller_is_the_one_selected(self):
        self.v8.eval("insp.selectItem('5', second)")
        self.assertEqual('imager', self.v8.eval('selected()'))
        self.v8.eval("insp.selectItem('5')")
        self.assertEqual('transcriber', self.v8.eval('selected()'))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class QueueKeyboardStopsTest(SimpleTestCase):
    """↑/↓ of the panel walk the WHOLE queue : single cards, each batch (its mother card), its
    children. Asked by Fabien (2026-10-14) : « avant je pouvais naviguer à travers toutes les cards
    batch, filles, unitaires ; maintenant ça bloque ». Measured in a browser (test account, describer
    queue = a single card above a batch of two) : ↓ from the single card did nothing — the list was
    the app's card class, which the MOTHER card carries too, with no `data-id` — and a selected batch
    ignored the arrows."""

    # The page order of the describer queue measured that day : a single card, the batch wrapper,
    # its mother card (app card class, NO id), its two children, then another single card.
    PAGE = [{'id': '1945'}, {'batch': '1565'}, {}, {'id': '1943'}, {'id': '1944'}, {'id': '1950'}]

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-inspector.js').read_text(encoding='utf-8'))

    def _next(self, current, direction, page=None):
        return self.v8.eval('(function () { var I = window.WamaInspector; return I.nextStop('
                            f'I.queueStops({json.dumps(page or self.PAGE)}), {json.dumps(current)}, '
                            f'{direction}); }})()')

    def _walk(self, start, direction):
        seen, at = [], start
        while True:
            i = self._next(at, direction)
            if i < 0:
                return seen
            stop = self.PAGE[i]
            seen.append(stop.get('id') or 'batch ' + stop['batch'])
            at = {'id': stop.get('id'), 'batch': stop.get('batch')}

    def test_down_from_a_single_card_reaches_the_batch_then_its_children(self):
        self.assertEqual(['batch 1565', '1943', '1944', '1950'], self._walk({'id': '1945'}, 1))

    def test_up_from_the_last_card_comes_back_through_the_batch(self):
        self.assertEqual(['1944', '1943', 'batch 1565', '1945'], self._walk({'id': '1950'}, -1))

    def test_a_selected_batch_moves_on(self):
        self.assertEqual(3, self._next({'id': None, 'batch': '1565'}, 1), 'its first child')
        self.assertEqual(0, self._next({'id': None, 'batch': 1565}, -1), 'the card above it')

    def test_the_mother_card_without_id_is_never_a_stop(self):
        self.assertNotIn(2, [self._next({'id': '1943'}, -1), self._next({'batch': '1565'}, 1)])

    def test_the_edges_stay_and_an_unknown_selection_starts_at_the_first_stop(self):
        self.assertEqual(-1, self._next({'id': '1950'}, 1))
        self.assertEqual(-1, self._next({'id': '1945'}, -1))
        self.assertEqual(0, self._next({'id': '999'}, 1))
        self.assertEqual(-1, self._next({'id': '1'}, 1, page=[{}]))


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
                    bar.children.map(function (b) { return / is-active$/.test(b.className)
                                                           && b.attrs['aria-selected'] === 'true'; }),
                    went, compared, bar.attrs.role, bar.children.map(function (b) { return b.attrs.role; })];
        })()""")
        self.assertEqual(['input', 'compare', 'output'], list(out[0]))
        self.assertEqual([False, False, True], list(out[1]), 'the face shown is the active tab')
        self.assertEqual('tablist', out[4])
        self.assertEqual(['tab'] * 3, list(out[5]))
        self.assertEqual(['input', 'output'], list(out[2]))
        self.assertEqual(1, out[3])

    def test_the_playback_follows_the_face(self):
        """Asked by Fabien (2026-10-15) : switching from the Entry to the Detection then the Output of
        a video restarted it from 0 ; and the audio of the side panel (a player OUTSIDE the DOM) went
        on playing, unseen, once its face was left. The clock is taken (the medium STOPS), and given
        to the medium of the face shown — the same item only ; a face without medium keeps it."""
        out = self.v8.eval("""(function () {
            var P = window.WamaMediaPreview;
            var medium = function (t, paused) { var m = {currentTime: t, paused: paused, ended: false, readyState: 4,
                duration: 60, played: 0, pause: function () { m.paused = true; },
                play: function () { m.played++; m.paused = false; return {catch: function () {}}; }}; return m; };
            var host = function (m) { return {querySelector: function (sel) {
                return (m && sel.indexOf('video') >= 0) ? m : null; }}; };
            var old = medium(12.5, false);
            var clock = P.takeClock(host(old), '/p/1/', null);
            var text = P.takeClock(host(null), '/p/1/', clock);            // left for a text face
            var next = medium(0, true), other = medium(0, true);
            P.giveClock(host(next), clock, '/p/1/');
            P.giveClock(host(other), clock, '/p/2/');                     // another item
            return [clock, old.paused, text, next.currentTime, next.played, other.currentTime, other.played,
                    P.takeClock(host(null), '/p/1/', null)];
        })()""")
        self.assertEqual({'base': '/p/1/', 'time': 12.5, 'playing': True}, dict(out[0]))
        self.assertTrue(out[1], 'the medium left is stopped')
        self.assertEqual({'base': '/p/1/', 'time': 12.5, 'playing': False}, dict(out[2]),
                         'a face without medium keeps the position, paused')
        self.assertEqual([12.5, 1], [out[3], out[4]], 'the next face resumes where the first one was')
        self.assertEqual([0, 0], [out[5], out[6]], 'never from one item to another')
        self.assertIsNone(out[7])

    def test_the_viewer_width_follows_what_it_shows(self):
        """A media takes the room, a text keeps a reading width, a sound stays narrow (2026-10-14 :
        the viewer was 800 px whatever it showed)."""
        kinds = self.v8.eval("""(function () {
            var k = window.WamaMediaPreview.viewerKind;
            return [k({mime_type: 'image/png'}), k({mime_type: 'video/mp4'}), k({mime_type: 'application/pdf'}),
                    k({mime_type: 'text/html'}), k({mime_type: 'model/gltf-binary'}), k({side: 'compare'}),
                    k({mime_type: 'text/plain'}), k({content: 'x'}), k({mime_type: 'text/csv'}),
                    k({mime_type: 'audio/wav'}), k({})];
        })()""")
        self.assertEqual(['media'] * 6 + ['text'] * 3 + ['audio', 'media'], list(kinds))

    def test_compare_is_titled_by_the_two_files_it_confronts(self):
        """The title kept the face shown before (the entry, or « 4 fichiers ») — 2026-10-13."""
        out = self.v8.eval("""(function () {
            var t = window.WamaMediaPreview.compareTitle;
            return [t({name: 'source.jpg'}, {name: 'floutee.jpg'}), t({}, null)];
        })()""")
        self.assertEqual(['source.jpg ↔ floutee.jpg', 'Entrée ↔ Sortie'], list(out))

    def test_the_panel_and_the_viewer_have_their_own_density(self):
        out = self.v8.eval("""(function () {
            var P = window.WamaMediaPreview, face = {sides: {has_input: true, has_output: true}};
            var panel = P.sidesBar(face, {compact: true}), viewer = P.sidesBar(face, {});
            return [panel.className, viewer.className, panel.children[0].attrs['data-label'],
                    P.sidesBar({sides: {has_input: true}}, {}) === null];
        })()""")
        self.assertIn('is-compact', out[0])
        self.assertNotIn('is-compact', out[1])
        self.assertEqual('Entrée', out[2], 'the name an icon shows on hover once the row is condensed')
        self.assertTrue(out[3], 'one face : nothing to switch between, no bar')

    def test_a_row_too_narrow_keeps_the_icons_and_the_active_name(self):
        """Asked by Fabien (2026-10-14) : in the side panel the row of faces did not fit (« Résumé »
        cut at 280 px). When the names do not fit, the row CONDENSES (icons, the active tab keeps its
        name) ; when even that overflows, it scrolls ; widened again, it shows every name."""
        out = self.v8.eval("""(function () {
            var observed = [];
            window.ResizeObserver = function (fn) { this.observe = function (el) { observed.push([fn, el]); }; };
            var face = {side: 'output', sides: {has_input: true, has_output: true,
                        faces: [{key: 'transcribe', label: 'Transcription'}]}};
            var bar = window.WamaMediaPreview.sidesBar(face, {compact: true});
            var set = {};
            bar.classList = {add: function () { for (var i = 0; i < arguments.length; i++) set[arguments[i]] = 1; },
                             remove: function () { for (var i = 0; i < arguments.length; i++) delete set[arguments[i]]; },
                             contains: function (c) { return !!set[c]; }};
            // Natural widths : 300 px with every name, 150 px condensed.
            Object.defineProperty(bar, 'scrollWidth', {get: function () { return set['is-condensed'] ? 150 : 300; }});
            bar.querySelector = function () { return {offsetLeft: 40, offsetWidth: 90}; };
            var measure = observed[0][0], states = [];
            [400, 260, 120, 500].forEach(function (w) {
                bar.clientWidth = w; measure();
                states.push([!!set['is-condensed'], !!set['is-scrolling']]);
            });
            delete window.ResizeObserver;
            return [observed.length, observed[0][1] === bar, states];
        })()""")
        self.assertEqual(1, out[0])
        self.assertTrue(out[1], 'the row watches its own width')
        self.assertEqual([[False, False], [True, False], [True, True], [False, False]],
                         [list(s) for s in out[2]])


class OnePreviewBrickTest(SimpleTestCase):
    """The preview lives in ONE brick ; the panel, the file manager and the pages consume it."""

    MOVED = ('renderInline', 'compareView', 'followDuring', 'variantToggle', 'duringUrl',
             'hydrateCardPreviews', 'sidesBar', 'compareFaces', 'cardOfPreview', 'isRunningCard',
             'faceViewer')

    def test_each_preview_function_is_defined_once_in_the_common_js(self):
        sources = {path.name: path.read_text(encoding='utf-8') for path in JS.glob('*.js')}
        for name in self.MOVED + ('renderInlinePreview',):
            defined = [file for file, text in sources.items()
                       if re.search(r'\bfunction ' + name + r'\s*\(', text)]
            expected = [] if name == 'renderInlinePreview' else ['media-preview.js']
            self.assertEqual(expected, defined, name)

    def test_the_panel_builds_no_switch_of_its_own(self):
        panel = (JS / 'wama-inspector.js').read_text(encoding='utf-8')
        # Its faces are the common face viewer (2026-10-28), whose tabs are `sidesBar`.
        self.assertIn('P.faceViewer(', panel)
        brick = (JS / 'media-preview.js').read_text(encoding='utf-8')
        viewer = brick[brick.index('function faceViewer('):]
        self.assertIn('sidesBar(d,', viewer[:viewer.index('\n    }\n')])
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
        fill = panel[panel.index('function fillPreview'):]
        self.assertIn('card: card,', fill[:fill.index('\n    }\n')], 'the panel gives its card to the viewer')
        brick = (JS / 'media-preview.js').read_text(encoding='utf-8')
        self.assertIn('openForCard(m, opts.card || null, 0)', brick)
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

    def test_the_panel_arrows_walk_the_stops_of_the_queue(self):
        """↑/↓ of the panel go through `queueStops`/`nextStop`, and a selected BATCH answers them
        too (it ignored them : `itemId !== null` only)."""
        panel = (JS / 'wama-inspector.js').read_text(encoding='utf-8')
        body = panel[panel.index('function moveSelection('):panel.index('if (cfg.keyboardNav !== false)')]
        self.assertIn('nextStop(queueStops(entries)', body)
        self.assertIn('selectBatch(e.batch)', body)
        self.assertIn("(e.key === 'ArrowDown' || e.key === 'ArrowUp') && (itemId !== null || batchId !== null)",
                      panel)

    def test_the_nightly_gestures_are_registered(self):
        from wama.common.services import nightly_tests
        from wama.common.services.ui_smoke_preview import register_preview_scenarios
        register_preview_scenarios()
        self.assertIn('common.preview_navigation', {s.id for s in nightly_tests.REGISTRY})
