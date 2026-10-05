"""The capability-bound settings and the sort brick, exercised in V8 (no browser).

Session of 2026-09-23/24 (Fabien: « les paramètres modale/inspecteur tirent leurs infos des
capacités des modèles », then « trier les modèles par nom, VRAM, performance, confiance »). The
rules live in common JavaScript bricks; a browser smoke saw them once, these tests keep them:
  • `WamaParams.applyCapFrom` — native zone, continued (orange) or extrapolated (red) beyond,
    bounded slider when the model cannot go beyond, value imposed by the model (`fixed`);
  • `WamaFilterBar.sort` — numbers or text, unknown values always last;
  • `WamaModelHelp.capabilityFacts` — the limits said under the model select, derived.
V8 comes from `py_mini_racer` (the venv's embedded engine, cf. AGENTS.md §JS): the files are
read from the SOURCE static folder and run with a minimal fake `window`/`document`.
"""
import importlib.util
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'

FAKE_DOM = """
var window = {};
var document = {readyState: 'complete', querySelectorAll: function () { return []; },
                querySelector: function () { return null; }, addEventListener: function () {},
                getElementById: function () { return null; }};
function classList() {
  var s = {};
  return {add: function (c) { s[c] = 1; }, remove: function (c) { delete s[c]; },
          toggle: function (c, on) { if (on === undefined) on = !s[c]; if (on) s[c] = 1; else delete s[c]; },
          contains: function (c) { return !!s[c]; }};
}
function fakeRange(value, max) {
  var props = {}, upper = max;
  var el = {value: String(value), min: '1', dataset: {}, disabled: false, dispatched: [],
            classList: classList(), style: {setProperty: function (k, v) { props[k] = v; },
            removeProperty: function (k) { delete props[k]; }, props: props},
            dispatchEvent: function (e) { el.dispatched.push(e.type); }};
  // Like a real <input type="range">: lowering `max` brings the value back inside the bounds,
  // silently (no event). A fake that did not clamp hid a real defect (2026-10-03).
  Object.defineProperty(el, 'max', {
    get: function () { return upper; },
    set: function (v) { upper = v; if (Number(el.value) > Number(v)) el.value = String(v); }});
  return el;
}
function fakeNote() { return {textContent: '', innerHTML: '', classList: classList()}; }
function Event(type) { this.type = type; }
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class CapFromTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _apply(self, value, caps, cf=None, p=None):
        cf = cf or {'field': 'model', 'capability': 'max_duration_s',
                    'extension': 'duration_extension', 'unit': ' s'}
        p = p or {'min': 1, 'max': 15}
        import json
        return self.v8.eval(f"""(function () {{
            var el = fakeRange({json.dumps(value)}, '15'), note = fakeNote(), row = {{classList: classList()}};
            window.WamaParams.applyCapFrom(el, note, row, {json.dumps(p)}, {json.dumps(cf)}, {json.dumps(caps)});
            return {{value: String(el.value), max: String(el.max), disabled: el.disabled,
                     dispatched: el.dispatched,
                     capped: el.classList.contains('wama-range-capped'),
                     continuation: el.classList.contains('wama-range-capped--continuation'),
                     extrapolated: row.classList.contains('is-extrapolated'),
                     continued: row.classList.contains('is-continued'),
                     note: note.innerHTML || note.textContent}};
        }})()""")

    def test_beyond_a_single_image_restart_is_red_and_said_extrapolated(self):
        out = self._apply(12, {'max_duration_s': 5.04, 'duration_extension': 'segments'})
        self.assertTrue(out['capped'] and out['extrapolated'])
        self.assertFalse(out['continued'])
        self.assertIn('extrapolé', out['note'])

    def test_beyond_a_continuation_is_orange_and_said_continued(self):
        out = self._apply(12, {'max_duration_s': 10.71, 'duration_extension': 'continuation'})
        self.assertTrue(out['continuation'] and out['continued'])
        self.assertFalse(out['extrapolated'])
        self.assertIn('continué', out['note'])

    def test_within_the_native_zone_nothing_is_flagged(self):
        out = self._apply(4, {'max_duration_s': 5.04, 'duration_extension': 'segments'})
        self.assertTrue(out['capped'])
        self.assertFalse(out['extrapolated'] or out['continued'])

    def test_a_model_that_cannot_go_beyond_bounds_the_slider(self):
        out = self._apply(12, {'max_duration_s': 2.8})
        self.assertEqual(('2', '2'), (out['max'], out['value']))
        self.assertIn('Limite du modèle', out['note'])

    def test_a_value_brought_back_under_the_bound_is_announced(self):
        """The browser clamps the value by itself when `max` drops, without any event: the
        displayed number and the app's listeners (estimate) stayed on the old value."""
        out = self._apply(12, {'max_duration_s': 2.8})
        self.assertEqual(['input'], list(out['dispatched']))
        # Counter-test: a value already under the bound announces nothing.
        self.assertEqual([], list(self._apply(2, {'max_duration_s': 2.8})['dispatched']))

    def test_auto_leaves_the_schema_slider_untouched(self):
        out = self._apply(12, None)
        self.assertEqual(('12', '15'), (out['value'], out['max']))
        self.assertFalse(out['capped'])

    def test_a_fixed_capability_imposes_the_value_and_gives_it_back(self):
        cf = {'field': 'model', 'capability': 'fps', 'mode': 'fixed', 'unit': ' i/s'}
        out = self._apply(16, {'fps': 24}, cf, {'min': 8, 'max': 30})
        self.assertEqual(('24', True), (out['value'], out['disabled']))
        # Counter-test: the same field under a model WITHOUT the capability is free again.
        restored = self.v8.eval("""(function () {
            var el = fakeRange('16', '30'), note = fakeNote();
            var cf = {field: 'model', capability: 'fps', mode: 'fixed'};
            window.WamaParams.applyCapFrom(el, note, null, {min: 8, max: 30}, cf, {fps: 24});
            window.WamaParams.applyCapFrom(el, note, null, {min: 8, max: 30}, cf, null);
            return [String(el.value), el.disabled];
        })()""")
        self.assertEqual(['16', False], list(restored))


#: A container holding a duration slider and (optionally) its model select, a catalogue stub that
#: answers at once, and what the brick needs around them. The binding is the REAL one.
FAKE_BINDING = """
var warned = [];
var console = {warn: function (m) { warned.push(String(m)); }};
window.console = console;
var CSS = {escape: function (s) { return s; }};
window.MutationObserver = null;
document.createElement = function () { return fakeNote(); };
function fetch() {
  var payload = {models: [{model_key: 'app:short', capabilities: {max_duration_s: 30}},
                          {model_key: 'app:long',  capabilities: {max_duration_s: 300}}]};
  return {then: function (f) { return Promise.resolve(f({json: function () { return payload; }})); }};
}
function fakeField(value, max) {
  var el = fakeRange(value, max), listeners = {};
  el.addEventListener = function (type, f) { (listeners[type] = listeners[type] || []).push(f); };
  el.closest = function () { return null; };
  el.parentNode = {appendChild: function () {}};
  return el;
}
function fakeContainer(fields) {
  return {querySelector: function (sel) { return fields[sel.slice(1)] || null; },
          querySelectorAll: function () { return []; }, addEventListener: function () {}};
}
var SCHEMA = [{name: 'model', type: 'select', help_source: 'app', dom_id: {panel: 'm'}},
              {name: 'duration', type: 'range', min: 10, max: 600, dom_id: {panel: 'd'},
               cap_from: {field: 'model', capability: 'max_duration_s'}}];
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class CapFromBindingTest(SimpleTestCase):
    """The WIRING of a bound setting — two silent failures closed on 2026-10-02 (composer)."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval(FAKE_BINDING)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def test_a_setting_rendered_without_its_model_field_says_so(self):
        """A panel split into several hosts, each rendered from a FILTERED schema: the bound was
        inactive and nothing said it."""
        self.v8.eval("""var lone = fakeContainer({d: fakeField(600, '600')});
            window.WamaParams.bindCapFrom(lone, SCHEMA.slice(1), 'panel');""")
        warned = list(self.v8.eval('warned'))
        self.assertEqual(1, len(warned), warned)
        self.assertIn('duration', warned[0])
        self.assertIn('borne inactive', warned[0])

    def test_rendered_together_the_slider_stops_at_the_model_capability(self):
        self.v8.eval("""var d = fakeField(600, '600'), m = fakeField('app:short', '');
            var both = fakeContainer({d: d, m: m});
            window.WamaParams.bindCapFrom(both, SCHEMA, 'panel');""")
        self.assertEqual(['30', '30', 0], list(self.v8.eval('[String(d.max), String(d.value), warned.length]')))

    def test_values_set_by_program_replay_the_bound(self):
        """A batch modal sets the model of its first daughter through `apply` — no `change`."""
        self.v8.eval("""var d = fakeField(20, '600'), m = fakeField('app:long', '');
            var modal = fakeContainer({d: d, m: m});
            window.WamaParams.bindCapFrom(modal, SCHEMA, 'panel');""")
        self.assertEqual('300', self.v8.eval('String(d.max)'))
        self.v8.eval("m.value = 'app:short'; window.WamaParams.apply(modal, {});")
        self.assertEqual('30', self.v8.eval('String(d.max)'), 'the bound kept the previous model')

    def test_a_setting_absent_from_the_container_is_left_alone(self):
        """Counter-test: a schema passed whole to a container that holds none of it warns nobody."""
        self.v8.eval("window.WamaParams.bindCapFrom(fakeContainer({}), SCHEMA, 'panel');")
        self.assertEqual(0, self.v8.eval('warned.length'))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class SortAndFactsTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)

    def test_sort_puts_unknown_values_last_in_both_directions(self):
        self.v8.eval((JS / 'wama-filter-bar.js').read_text(encoding='utf-8'))
        out = self.v8.eval("""(function () {
            var order = [], parent = {appendChild: function (e) { order.push(e.n); }};
            function el(n, v) { return {n: n, parentNode: parent,
                getAttribute: function () { return v === undefined ? null : String(v); }}; }
            var els = [el('a', 5), el('b'), el('c', 1.5), el('d', 20)];
            window.WamaFilterBar.sort(els, 'vram:asc'); var asc = order.join(''); order = [];
            window.WamaFilterBar.sort(els, 'vram:desc'); var desc = order.join(''); order = [];
            window.WamaFilterBar.sort([el('x', 'Zeta'), el('y', 'alpha'), el('z', 'Éclair')], 'name:asc');
            return [asc, desc, order.join('')];
        })()""")
        self.assertEqual(['cadb', 'dacb', 'yzx'], list(out))

    def test_the_model_limits_are_derived_from_its_capabilities(self):
        self.v8.eval((JS / 'wama-model-help.js').read_text(encoding='utf-8'))
        facts = self.v8.eval("""window.WamaModelHelp.capabilityFacts(
            {max_duration_s: 10.71, fps: 24, native_resolution: '1216x704',
             duration_extension: 'continuation'})""")
        self.assertEqual('natif ≤ 10,7 s (continuable), 24 i/s, 1216×704', facts)
        self.assertEqual('', self.v8.eval("window.WamaModelHelp.capabilityFacts({task: 'text-to-image'})"))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class ScopedSettingsModalTest(SimpleTestCase):
    """⚙ par process (P5, `ROUTE §10.6` 5.1) : the common modal rendered from the schema REDUCED to
    what one process watches — the rule is pure (`scopedSchema`), the scope is posed for the NEXT
    modal only and dies by itself."""

    SCHEMA = ("[{name: 'media_type', type: 'hidden'}, {name: 'prompt', type: 'text', group: 'g1'},"
              " {name: 'duration', type: 'range', group: 'g2'}, {name: 'model', type: 'select', group: 'g1'}]")

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def test_the_scoped_schema_keeps_the_named_settings_and_the_hidden_carriers(self):
        kept = self.v8.eval(f"window.WamaParams.scopedSchema({self.SCHEMA}, ['duration'])"
                            ".map(function (p) { return p.name; })")
        self.assertEqual(['media_type', 'duration'], list(kept))
        self.assertEqual([], list(self.v8.eval("window.WamaParams.scopedSchema([], ['x'])")))

    def test_a_scope_is_taken_once_by_the_next_modal_and_expires_by_itself(self):
        # `settingsModal` itself builds a DOM modal (too DOM-bound for V8) : what it does first —
        # take the pending scope — is exercised through the same function, exposed.
        out = self.v8.eval("""(function () {
            var P = window.WamaParams;
            P.scopeNextModal(['duration', ''], 'Rendu');
            var first = P.takeModalScope(), second = P.takeModalScope();
            P.scopeNextModal([], 'rien');                 // no name = no scope
            var empty = P.takeModalScope();
            P.scopeNextModal(['prompt'], 'Partition');
            var realNow = Date.now; Date.now = function () { return realNow() + 5000; };
            var late = P.takeModalScope();
            Date.now = realNow;
            return [first ? first.names.join(',') + '|' + first.label : null, second, empty, late];
        })()""")
        self.assertEqual(['duration|Rendu', None, None, None], list(out))

    def test_a_scoped_modal_renders_the_schema_only_and_still_collects(self):
        """The gear of « Sortie » showed the prompt of the imager and the classes of the
        anonymizer (2026-10-04) : the zones an app adds OUTSIDE the schema (`decorate`) are not
        settings of that process. `collect` stays — it carries the relaunch flag of some apps."""
        out = self.v8.eval(f"""(function () {{
            var P = window.WamaParams;
            var cfg = {{schema: {self.SCHEMA}, groups: [{{key: 'g1'}}, {{key: 'g2'}}],
                       title: 'Paramètres', decorate: function () {{}}, collect: function () {{}}}};
            var scoped = P.scopedConfig(cfg, {{names: ['duration'], label: 'Rendu'}});
            var plain = P.scopedConfig(cfg, null);
            return [scoped.schema.map(function (p) {{ return p.name; }}).join(','),
                    scoped.groups.map(function (g) {{ return g.key; }}).join(','),
                    scoped.title, scoped.decorate === null, typeof scoped.collect,
                    plain === cfg, typeof plain.decorate];
        }})()""")
        self.assertEqual(['media_type,duration', 'g2', 'Paramètres — Rendu', True, 'function',
                          True, 'function'], list(out))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class RunButtonOfAProcessTest(SimpleTestCase):
    """The ▶ of ONE process (`ROUTE §10.6` 5.1) : reading the process on the button and composing
    `start/<id>/<process>/` lived in eight app files — they live in the cycle-button brick."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-cycle-button.js').read_text(encoding='utf-8'))

    def test_the_process_is_read_from_the_button_and_appended_to_the_address(self):
        out = self.v8.eval("""(function () {
            var C = window.WamaCycleButton;
            return [C.processOf({dataset: {process: 'output'}}), C.processOf({dataset: {}}),
                    C.processOf(null), C.processUrl('/app/start/7/', 'output'),
                    C.processUrl('/app/start/7/', ''), C.processUrl('/app/start/7/', undefined)];
        })()""")
        self.assertEqual(['output', '', '', '/app/start/7/output/', '/app/start/7/',
                          '/app/start/7/'], list(out))

    def test_the_wiring_hands_the_process_to_the_start_handler(self):
        out = self.v8.eval("""(function () {
            var listener = null, seen = [];
            function button(action, process) {
                var b = {dataset: process ? {process: process} : {},
                         getAttribute: function (n) { return n === 'data-id' ? '7' : action; }};
                b.closest = function () { return b; };
                return b;
            }
            var root = {addEventListener: function (type, fn) { listener = fn; },
                        contains: function () { return true; }};
            window.WamaCycleButton.wire(root, {
                start: function (id, btn, process) { seen.push('start:' + id + ':' + process); },
                stop: function (id) { seen.push('stop:' + id); }});
            listener({target: button('start', 'output')});
            listener({target: button('restart', '')});
            listener({target: button('stop', 'output')});
            return seen;
        })()""")
        self.assertEqual(['start:7:output', 'start:7:', 'stop:7'], list(out))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class DuringVariantsOfThePreviewTest(SimpleTestCase):
    """The « during » preview offers a switch between the views a worker publishes (2026-10-04 :
    the anonymizer's detection and blur of the same frame). The address carries the chosen view ;
    the toggle has one button per view, the active one filled, and says the key it picks."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + """
        document.createElement = function (tag) {
          var el = {tagName: tag, children: [], attrs: {}, listeners: {}, className: '', textContent: '',
                    appendChild: function (c) { el.children.push(c); return c; },
                    setAttribute: function (k, v) { el.attrs[k] = v; },
                    addEventListener: function (t, fn) { el.listeners[t] = fn; }};
          return el;
        };""")
        self.v8.eval((JS / 'wama-inspector.js').read_text(encoding='utf-8'))

    def test_the_address_carries_the_chosen_view(self):
        out = self.v8.eval("""(function () {
            var I = window.WamaInspector;
            return [I.duringUrl('/preview/anonymizer/4/', null),
                    I.duringUrl('/preview/anonymizer/4/?x=1', 'blur'),
                    I.duringUrl('/p/', 'a b')];
        })()""")
        self.assertEqual(['/preview/anonymizer/4/?side=during',
                          '/preview/anonymizer/4/?x=1&side=during&variant=blur',
                          '/p/?side=during&variant=a%20b'], list(out))

    def test_the_toggle_has_one_button_per_view_and_says_the_one_picked(self):
        out = self.v8.eval("""(function () {
            var picked = [];
            var bar = window.WamaInspector.variantToggle(
                [{key: 'detection', label: 'Détection'}, {key: 'blur', label: 'Floutage'}],
                'blur', function (k) { picked.push(k); });
            bar.children[0].listeners.click();
            return [bar.children.length, bar.children[0].textContent,
                    bar.children[1].className.indexOf('btn-info ') >= 0
                      || / btn-info$/.test(bar.children[1].className) || bar.children[1].className.indexOf(' btn-info') >= 0,
                    bar.children[0].className.indexOf('btn-outline-info') >= 0, picked[0]];
        })()""")
        self.assertEqual([2, 'Détection', True, True, 'detection'], list(out))


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class PreviewOverlayTest(SimpleTestCase):
    """The detections drawn over a preview (2026-10-05) : the frame shown at a playing time, and
    where the picture really sits in its element (`object-fit: contain`, bars included)."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-preview-overlay.js').read_text(encoding='utf-8'))

    def test_the_frame_of_a_playing_time(self):
        out = self.v8.eval("""(function () {
            var O = window.WamaPreviewOverlay, v = {media: 'video', fps: 15};
            return [O.frameAt(v, 0), O.frameAt(v, 1.0), O.frameAt(v, 2.07), O.frameAt(v, -1),
                    O.frameAt({media: 'image'}, 3), O.frameAt(null, 3)];
        })()""")
        self.assertEqual([0, 15, 31, 0, 0, 0], list(out))

    def test_where_the_picture_sits_in_its_element(self):
        out = self.v8.eval("""(function () {
            var O = window.WamaPreviewOverlay;
            var wide = O.contentRect(400, 300, 800, 300);   // bars above and below
            var tall = O.contentRect(400, 300, 300, 600);   // bars left and right
            return [wide.x, wide.y, wide.scale, tall.x, tall.y, tall.scale, O.contentRect(0, 0, 1, 1).scale];
        })()""")
        self.assertEqual([0, 75, 0.5, 125, 0, 0.5, 1], list(out))

    def test_the_compared_video_follows_the_reference(self):
        """Compare on two videos : seek, play, pause and speed of the reference drive the other
        one, which is muted. Seen broken in the browser before (the other stayed at 0)."""
        out = self.v8.eval("""(function () {
            function video() {
                var v = {currentTime: 0, playbackRate: 1, muted: false, plays: 0, pauses: 0, on: {}};
                v.addEventListener = function (ev, fn) { (v.on[ev] = v.on[ev] || []).push(fn); };
                v.fire = function (ev) { (v.on[ev] || []).forEach(function (fn) { fn(); }); };
                v.play = function () { v.plays++; return {catch: function () {}}; };
                v.pause = function () { v.pauses++; };
                return v;
            }
            var master = video(), slave = video();
            window.WamaPreviewOverlay.syncVideos(master, slave);
            var trace = [slave.muted];
            master.currentTime = 2; master.fire('seeked'); trace.push(slave.currentTime);
            master.currentTime = 2.05; master.fire('timeupdate');
            trace.push(slave.currentTime);                 // within 0.12 s : left alone
            master.fire('play'); trace.push(slave.plays);
            master.currentTime = 3; master.fire('pause'); trace.push(slave.pauses, slave.currentTime);
            master.playbackRate = 1.5; master.fire('ratechange'); trace.push(slave.playbackRate);
            return trace;
        })()""")
        self.assertEqual([True, 2, 2, 1, 1, 3, 1.5], list(out))


class PreviewModalTest(SimpleTestCase):
    """The preview modal and its full screen (2026-10-05, Fabien : « mettre la during_preview en
    plein écran », then « la modale et le plein écran avec entrée, détection, comparaison,
    sortie »). Four defects that no error revealed : a modal opened from a card THUMBNAIL never
    had its faces (no item address), the PENDING face of the side panel had no full screen, the
    full screen was an image-only overlay, and the keyboard navigation of the modal raised a
    ReferenceError since 2026-07-21."""

    def test_the_item_address_drops_the_face_and_the_view_only(self):
        from py_mini_racer import MiniRacer
        v8 = MiniRacer()
        v8.eval(FAKE_DOM)
        v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))
        out = v8.eval("""(function () {
            var a = window.WamaMediaPreview.itemAddress;
            return [a('/common/preview/anonymizer/7/?side=output'),
                    a('/common/preview/anonymizer/7/?side=during&variant=blur'),
                    a('/p/7/?app=x&side=input&keep=1'), a('/p/7/'), a('')];
        })()""")
        self.assertEqual(['/common/preview/anonymizer/7/', '/common/preview/anonymizer/7/',
                          '/p/7/?app=x&keep=1', '/p/7/', ''], list(out))

    def _body(self, name, function):
        text = (JS / name).read_text(encoding='utf-8')
        body = text[text.index(function):]
        return body[:body.index('\n    }\n')]

    def test_every_way_into_the_modal_carries_the_item_and_its_live_face(self):
        self.assertIn('data._baseUrl = base', self._body('media-preview.js', 'function openPreview'),
                      'a card thumbnail opens the modal WITH its faces')
        self.assertIn('_attachFullscreen(d, baseUrl)', self._body('wama-inspector.js',
                                                                 'function _startDuring'),
                      'the PENDING face of the side panel opens the modal too')
        self.assertIn('_startModalDuring(modal, data)', self._body('media-preview.js',
                                                                  'function showPreviewModal('),
                      'the PENDING face is followed live in the modal')
        navigation = self._body('media-preview.js', 'function navigatePreview')
        self.assertIn('_renderModalSides(modal, item)', navigation)
        self.assertNotIn('_renderModalSides(modal, data)', navigation)

    def test_the_full_screen_of_an_item_is_the_modal_itself(self):
        expand = self._body('media-preview.js', 'function _expand')
        self.assertIn('_setModalFull(', expand, 'an item keeps its faces in full screen')
        css = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'css'
               / 'media-preview.css').read_text(encoding='utf-8')
        self.assertIn('.modal-dialog.modal-fullscreen .preview-container img', css)
