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
  var props = {};
  return {value: String(value), max: max, min: '1', dataset: {}, disabled: false,
          classList: classList(), style: {setProperty: function (k, v) { props[k] = v; },
          removeProperty: function (k) { delete props[k]; }, props: props},
          dispatchEvent: function () {}};
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
