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
import json
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

    def _reads(self, caps_sequence, capability='params', name='mode'):
        """Applies « reads » for each caps of the sequence on the SAME field; returns the states."""
        import json
        cf = {'field': 'backend', 'capability': capability, 'mode': 'reads', 'reason': 'ignoré'}
        return self.v8.eval(f"""(function () {{
            var el = fakeRange('fast', '1'), note = fakeNote(), row = {{classList: classList()}};
            el.title = '';
            return {json.dumps(caps_sequence)}.map(function (caps) {{
                window.WamaParams.applyCapFrom(el, note, row, {json.dumps({'name': name})},
                                               {json.dumps(cf)}, caps);
                return {{disabled: el.disabled, value: String(el.value), note: note.textContent,
                         title: el.title, faded: row.classList.contains('opacity-50')}};
            }});
        }})()""")

    def test_a_setting_the_engine_does_not_list_is_greyed_with_its_reason(self):
        """`params` = the settings the engine reads (reader: docTR none, olmOCR mode+language)."""
        unread, read = self._reads([{'params': []}, {'params': ['mode', 'language']}])
        self.assertTrue(unread['disabled'] and unread['faded'])
        self.assertEqual(('ignoré', 'ignoré'), (unread['note'], unread['title']))
        # Counter-test: an engine that reads it gives it back, value untouched, nothing said.
        self.assertEqual((False, False, '', 'fast'),
                         (read['disabled'], read['faded'], read['note'], read['value']))

    def test_a_boolean_capability_answers_by_its_value(self):
        """`supports_hotwords` (transcriber): False greys, True gives back."""
        off, on = self._reads([{'supports_hotwords': False}, {'supports_hotwords': True}],
                              capability='supports_hotwords', name='hotwords')
        self.assertTrue(off['disabled'])
        self.assertFalse(on['disabled'])

    def test_show_if_says_the_same_in_the_browser_and_on_the_server(self):
        """`show_if` has TWO readers — `_bindConditional` (screen) and `param_schema._show_if_met`
        (defaults applied, card clauses). `not_equals` entered both on 2026-10-13 (the enhancer
        hides Resemble's settings under « auto » only); every form is checked on both sides."""
        import json
        from wama.common.utils.param_schema import _show_if_met
        cases = [({'field': 'engine', 'not_equals': 'auto'}, 'auto'),
                 ({'field': 'engine', 'not_equals': 'auto'}, 'enhancer:resemble'),
                 ({'field': 'engine', 'equals': 'auto'}, 'auto'),
                 ({'field': 'engine', 'equals': 'auto'}, 'x'),
                 ({'field': 'engine', 'in': ['a', 'b']}, 'b'),
                 ({'field': 'engine', 'in': ['a', 'b']}, 'c')]
        for cond, value in cases:
            with self.subTest(cond=cond, value=value):
                shown = self.v8.eval(f"""(function () {{
                    var field = {{type: 'select', value: {json.dumps(value)},
                                  getAttribute: function (n) {{ return n === 'name' ? 'engine' : null; }}}};
                    var row = {{style: {{}}, getAttribute: function () {{ return {json.dumps(json.dumps(cond))}; }}}};
                    var box = {{addEventListener: function () {{}}, querySelectorAll: function (sel) {{
                        return sel === '[data-show-if]' ? [row] : [field]; }}}};
                    window.WamaParams.bindConditional(box);
                    return row.style.display !== 'none';
                }})()""")
                self.assertEqual(_show_if_met(cond, {'engine': value}), shown)

    def test_a_carrier_holding_a_list_means_one_of_on_both_sides(self):
        """A carrier whose value is not known yet — the nature a Studio node will receive, image OR
        video — is a LIST (2026-10-18, `studio/services/graph_flow`): a condition holds if ONE of
        the values satisfies it, on screen (`data-any-of` hidden field) as on the server."""
        import json
        from wama.common.utils.param_schema import _show_if_met
        many = ['image', 'video']
        cases = [({'field': 'media_type', 'equals': 'image'}, True),
                 ({'field': 'media_type', 'equals': 'audio'}, False),
                 ({'field': 'media_type', 'in': ['audio', 'video']}, True),
                 ({'field': 'media_type', 'in': ['audio', 'document']}, False),
                 ({'field': 'media_type', 'not_equals': 'image'}, True),
                 ('media_type', True)]
        for cond, expected in cases:
            with self.subTest(cond=cond):
                shown = self.v8.eval(f"""(function () {{
                    var field = {{type: 'hidden', value: {json.dumps('|'.join(many))},
                                  getAttribute: function (n) {{
                                      return n === 'name' ? 'media_type' : (n === 'data-any-of' ? '1' : null); }}}};
                    var raw = {json.dumps(cond if isinstance(cond, str) else json.dumps(cond))};
                    var row = {{style: {{}}, getAttribute: function () {{ return raw; }}}};
                    var box = {{addEventListener: function () {{}}, querySelectorAll: function (sel) {{
                        return sel === '[data-show-if]' ? [row] : [field]; }}}};
                    window.WamaParams.bindConditional(box);
                    return row.style.display !== 'none';
                }})()""")
                self.assertEqual(expected, shown)
                self.assertEqual(expected, _show_if_met(cond, {'media_type': many}))

    def test_one_of_several_conditions_reads_the_same_on_both_sides(self):
        """`{any: [...]}` (2026-10-28): the output quality shows under a chosen format OR when the
        input size is kept (Fabien: « on peut vouloir garder la résolution d'origine et changer le
        format et la qualité »). Judged on screen and on the server, field by field; a branch whose
        field is not rendered keeps the row visible, the rule of a single condition."""
        import json
        from wama.common.utils.param_schema import _show_if_met
        cond = {'any': [{'field': 'output_format', 'in': ['webp', 'jpg']},
                        {'field': 'output_keep_size'}]}
        for fmt, keep in (('original', False), ('original', True), ('webp', False), ('jpg', True)):
            with self.subTest(fmt=fmt, keep=keep):
                shown = self.v8.eval(f"""(function () {{
                    var select = {{type: 'select', value: {json.dumps(fmt)},
                                   getAttribute: function (n) {{ return n === 'name' ? 'output_format' : null; }}}};
                    var toggle = {{type: 'checkbox', checked: {json.dumps(keep)},
                                   getAttribute: function (n) {{ return n === 'name' ? 'output_keep_size' : null; }}}};
                    var row = {{style: {{}}, getAttribute: function () {{ return {json.dumps(json.dumps(cond))}; }}}};
                    var box = {{addEventListener: function () {{}}, querySelectorAll: function (sel) {{
                        return sel === '[data-show-if]' ? [row] : [select, toggle]; }}}};
                    window.WamaParams.bindConditional(box);
                    return row.style.display !== 'none';
                }})()""")
                self.assertEqual(_show_if_met(cond, {'output_format': fmt, 'output_keep_size': keep}),
                                 shown)
                self.assertEqual(fmt != 'original' or keep, shown)

    def test_a_scope_keeps_every_field_one_of_several_conditions_reads(self):
        import json
        from wama.common.utils.param_schema import scoped_names
        schema = [{'name': 'output_keep_size', 'type': 'toggle'},
                  {'name': 'output_format', 'type': 'select'},
                  {'name': 'output_quality', 'type': 'select',
                   'show_if': {'any': [{'field': 'output_format', 'in': ['webp']},
                                       {'field': 'output_keep_size'}]}}]
        browser = list(self.v8.eval(
            f"window.WamaParams.scopedSchema({json.dumps(schema)}, ['output_quality'])"
            ".map(function (p) {{ return p.name; }})"))
        self.assertEqual(['output_keep_size', 'output_format', 'output_quality'], browser)
        self.assertEqual(browser, scoped_names(schema, ['output_quality']))

    def test_the_formats_of_an_unknown_nature_are_those_of_each_possible_one(self):
        """The output formats of a converter node whose input may be an image OR a video: both
        families, behind « Automatique » — « — inchangé — » only in a BATCH modal, where empty
        means « do not touch » (`read_settings_payload`)."""
        out = self.v8.eval("""(function () {
            window.WAMA_OUTPUT_FORMATS = {image: ['jpg', 'png'], video: ['mp4', 'png']};
            var p = {name: 'output_format', options_source: 'formats'};
            var item = window.WamaParams.resolvePageOptions(p, {media_type: ['image', 'video']}, 'item');
            var batch = window.WamaParams.resolvePageOptions(p, {media_type: 'image'}, 'batch');
            return {values: item.map(function (o) { return o.value; }), auto: item[0].label,
                    batchEmpty: batch[0].label};
        })()""")
        self.assertEqual(['', 'jpg', 'png', 'mp4'], list(out['values']))
        self.assertIn('Automatique', out['auto'])
        self.assertEqual('— inchangé —', out['batchEmpty'])

    def test_nothing_known_greys_nothing(self):
        """« auto » (no caps) or an undeclared capability: never grey on an absence of fact —
        FrWhisper's catalogue row does not carry its engine's flag yet."""
        greyed, auto, undeclared = self._reads([{'params': []}, None, {'task': 'ocr'}])
        self.assertTrue(greyed['disabled'])
        self.assertFalse(auto['disabled'] or undeclared['disabled'], 'restored once unknown')


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


#: The composer's processes as the page receives them (`WAMA_APP_PROCESSES`), with what each one
#: requires from the model of the card (`ProcessSpec.needs`, 2026-11-05). The full score of the
#: INPUT requires a MUSIC model since 2026-11-07 (no longer a model taking a cover : the render is
#: optional) — held against the real pipeline by `test_the_fixture_is_what_the_real_pipeline_says`.
NEEDS_PROCESSES = [
    {'key': 'parts', 'label': 'Partition complète', 'optional': True, 'model_field': 'model',
     'needs': {'field': 'task', 'in': ['text-to-music']}},
    {'key': 'render', 'label': 'Rendu', 'optional': False},
    {'key': 'rendered_parts', 'label': 'Partition de sortie', 'optional': True, 'model_field': 'model',
     'needs': {'field': 'task', 'in': ['text-to-music']}},
    {'key': 'rendered_lyrics', 'label': 'Paroles de sortie', 'optional': True, 'model_field': 'model',
     'needs': 'supports_vocals'},
]
SFX = {'task': 'text-to-audio', 'supports_vocals': False}
SONG = {'task': 'text-to-music', 'supports_vocals': True}
COVER = {'task': 'text-to-music', 'supports_vocals': False, 'inputs_optional': ['work_audio']}


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class SettingsFollowWhatTheModelServesTest(SimpleTestCase):
    """2026-11-05, Fabien : « quelle capacité du modèle rend ce réglage utile ? » — a sound effect
    model showed the score and lyrics settings. A process DECLARES what it requires from the model
    (`ProcessSpec.needs`, a `show_if` condition judged on the model's capabilities) ; a setting that
    only serves such processes is hidden under a model that does not satisfy them, and a section
    whose settings are all hidden goes with them. The same data is judged on the server."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval(FAKE_BINDING)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _needs(self, stales):
        return json.loads(self.v8.eval(
            f"JSON.stringify(window.WamaParams.settingNeeds({json.dumps({'stales': stales})}, "
            f"{json.dumps(NEEDS_PROCESSES)}))"))

    def test_a_setting_requires_what_every_process_it_serves_requires(self):
        self.assertEqual({'needs': 'supports_vocals', 'field': 'model'}, self._needs(['rendered_lyrics']))
        self.assertEqual({'needs': {'any': [NEEDS_PROCESSES[0]['needs'], NEEDS_PROCESSES[2]['needs']]},
                          'field': 'model'}, self._needs(['parts', 'rendered_parts']),
                         'serving two processes, one of them suffices')
        self.assertIsNone(self._needs(['render']), 'a process without requirement')
        self.assertIsNone(self._needs(['parts', 'render']), 'one served process requires nothing')
        self.assertIsNone(self._needs([]))

    def test_the_fixture_is_what_the_real_pipeline_says(self):
        """The fixture above is a copy : it drifted once (2026-11-07). Held against the REAL
        composer pipeline."""
        from wama.composer.function_specs import PIPELINE
        for process in NEEDS_PROCESSES:
            with self.subTest(process=process['key']):
                self.assertEqual(PIPELINE.spec(process['key']).needs, process.get('needs'))

    def test_the_condition_reads_the_same_on_capabilities_in_the_browser_and_on_the_server(self):
        from wama.common.utils.param_schema import condition_met
        for process in NEEDS_PROCESSES:
            if 'needs' not in process:
                continue
            for caps in (SFX, SONG, COVER, {}):
                with self.subTest(needs=process['needs'], caps=caps):
                    shown = self.v8.eval(
                        f"window.WamaParams.conditionMet({json.dumps(process['needs'])}, "
                        f"function (name) {{ return {json.dumps(caps)}[name]; }})")
                    self.assertEqual(condition_met(process['needs'], caps), shown)
        self.assertFalse(condition_met('supports_vocals', {}), 'an absent capability is not satisfied')

    def test_every_requirement_of_the_composer_reads_the_same_on_both_sides(self):
        """2026-11-06 : `all` and `not` entered the grammar for « follows a score WITHOUT taking the
        audio » (`extract_score`). Every `needs` the REAL pipeline declares is judged by the two
        readers on the capabilities of each kind of model — a list copied here would not see a
        requirement added tomorrow."""
        from wama.common.utils.param_schema import condition_met
        from wama.composer.function_specs import PIPELINE
        score = {'task': 'text-to-music', 'inputs_optional': ['work_score'], 'supports_score_planning': True}
        both = {'task': 'text-to-music', 'inputs_optional': ['work_score', 'work_audio']}
        # `required_by` (2026-11-07) is the same grammar, judged on the same line : read here too.
        declared = ([spec.needs for spec in PIPELINE.ordered() if spec.needs]
                    + [spec.required_by for spec in PIPELINE.ordered() if spec.required_by])
        self.assertGreaterEqual(len(declared), 7)
        for needs in declared:
            for caps in (SFX, SONG, COVER, score, both, {}):
                with self.subTest(needs=needs, caps=caps):
                    shown = self.v8.eval(
                        f"window.WamaParams.conditionMet({json.dumps(needs)}, "
                        f"function (name) {{ return {json.dumps(caps)}[name]; }})")
                    self.assertEqual(condition_met(needs, caps), shown)
        covers_by_score = PIPELINE.spec('extract_score').required_by
        self.assertEqual((True, False, False), (condition_met(covers_by_score, score),
                                                condition_met(covers_by_score, both),
                                                condition_met(covers_by_score, COVER)))

    def test_a_value_set_without_a_gesture_redraws_the_help_of_its_model(self):
        """2026-11-06, seen in the browser : the batch ⚙ set « MusicGen Small » and its help still
        described « auto » — `apply` sets values without a `change` event. The help is replayed with
        the other value-bound bindings (`_wpCapApply`)."""
        self.v8.eval("""
            var said = [];
            var sel = {value: 'auto', type: 'select-one', getAttribute: function (a) {
                         return a === 'name' ? 'model' : null; }};
            document.getElementById = function (id) { return id === 'm' ? sel : (id === 'm-help' ? {} : null); };
            window.WamaModelHelp = {init: function (cfg) {
              said.push(document.getElementById(cfg.selectId).value);
              return {render: function () { said.push(document.getElementById(cfg.selectId).value); }}; }};
            var box = {querySelectorAll: function (s) { return s === '[name],[data-param]' ? [sel] : []; },
                       querySelector: function () { return null; }, addEventListener: function () {}};
            window.WamaParams.bindModelHelp(box, [{name: 'model', type: 'select', dom_id: {panel: 'm'},
                                                   help_fallback: {auto: 'Choix automatique'}}], 'panel');
            window.WamaParams.apply(box, {model: 'composer:musicgen-small'});""")
        self.assertEqual(['auto', 'composer:musicgen-small'], json.loads(self.v8.eval('JSON.stringify(said)')))

    def test_all_and_not_are_read_by_the_conditions_of_the_settings_too(self):
        """The same grammar drives `show_if` : the fields a condition reads are those of each branch
        (what `scopedSchema` / `scoped_names` follow), on both sides."""
        from wama.common.utils.param_schema import condition_fields
        cond = {'all': [{'field': 'a', 'equals': 'x'}, {'not': {'field': 'b', 'in': ['y']}}]}
        self.assertEqual(['a', 'b'], condition_fields(cond))
        self.assertEqual(['a', 'b'], json.loads(self.v8.eval(
            f"JSON.stringify(window.WamaParams.conditionFields({json.dumps(cond)}))")))
        for values, expected in (({'a': 'x', 'b': 'z'}, True), ({'a': 'x', 'b': 'y'}, False),
                                 ({'a': 'w', 'b': 'z'}, False)):
            with self.subTest(values=values):
                self.assertIs(expected, self.v8.eval(
                    f"window.WamaParams.conditionMet({json.dumps(cond)}, "
                    f"function (n) {{ return {json.dumps(values)}[n]; }})"))

    def _bind(self, model_key):
        """Rows of the composer's settings under the model `model_key`, after the binding."""
        self.v8.eval(f"""
            function fetch() {{
              var payload = {{models: [{{model_key: 'composer:audiogen', capabilities: {json.dumps(SFX)}}},
                                       {{model_key: 'composer:singer', capabilities: {json.dumps(SONG)}}},
                                       {{model_key: 'composer:cover', capabilities: {json.dumps(COVER)}}}]}};
              return {{then: function (f) {{ return Promise.resolve(f({{json: function () {{ return payload; }}}})); }}}};
            }}
            function classes() {{
              var on = {{}};
              return {{toggle: function (n, v) {{ on[n] = !!v; }},
                       contains: function (n) {{ return !!on[n]; }}}};
            }}
            function row(name, needs) {{
              return {{name: name, hidden: false, classList: classes(), getAttribute: function (a) {{
                return a === 'data-needs' ? JSON.stringify(needs.needs)
                     : (a === 'data-needs-field' ? needs.field : null); }}}};
            }}
            var NEEDS = {json.dumps({'parts_model': self._needs(['parts', 'rendered_parts']),
                                     'extract_parts': self._needs(['parts']),
                                     'lyrics_model': self._needs(['rendered_lyrics'])})};
            var rows = {{parts_model: row('parts_model', NEEDS.parts_model),
                         extract_parts: row('extract_parts', NEEDS.extract_parts),
                         lyrics_model: row('lyrics_model', NEEDS.lyrics_model)}};
            function section(members) {{
              return {{hidden: false, classList: classes(), querySelector: function () {{ return null; }},
                       querySelectorAll: function () {{ return members(); }}}};
            }}
            var partsSection = section(function () {{ return [rows.extract_parts, rows.parts_model]; }});
            var lyricsSection = section(function () {{ return [rows.lyrics_model]; }});
            var m = fakeField({json.dumps(model_key)}, '');
            var box = {{_wpCapApply: [], querySelector: function (sel) {{ return sel === '#m' ? m : null; }},
                        querySelectorAll: function (sel) {{
                          if (sel === '[data-group]') return [partsSection, lyricsSection];
                          return [rows.parts_model, rows.extract_parts, rows.lyrics_model]; }},
                        addEventListener: function () {{}}}};
            window.WamaParams.bindProcessNeeds(box, [{{name: 'model', type: 'select', help_source: 'composer',
                                                      dom_id: {{panel: 'm'}}}}], 'panel');""")
        # GREYED, never hidden (2026-11-07, Fabien : « grisée ») : the unserved mark and its class.
        return json.loads(self.v8.eval(
            "JSON.stringify({extract_parts: !!rows.extract_parts._wpUnserved,"
            " parts_model: !!rows.parts_model._wpUnserved, lyrics_model: !!rows.lyrics_model._wpUnserved,"
            " parts_section: partsSection.classList.contains('wama-proc-section--unserved'),"
            " lyrics_section: lyricsSection.classList.contains('wama-proc-section--unserved'),"
            " hidden: [rows.extract_parts, rows.parts_model, rows.lyrics_model, partsSection,"
            "          lyricsSection].some(function (e) { return e.hidden; }),"
            " greyed_row: rows.lyrics_model.classList.contains('wama-param--unserved')})"))

    def test_under_a_sound_effect_model_the_score_and_lyrics_settings_and_sections_are_greyed(self):
        self.assertEqual({'extract_parts': True, 'parts_model': True, 'lyrics_model': True,
                          'parts_section': True, 'lyrics_section': True, 'hidden': False,
                          'greyed_row': True}, self._bind('composer:audiogen'))

    def test_each_model_keeps_what_it_serves(self):
        # The full score of the INPUT needs a MUSIC model since 2026-11-07 (it no longer depends on
        # the model taking a cover : the render is optional) — a singer serves it.
        self.assertEqual({'extract_parts': False, 'parts_model': False, 'lyrics_model': False,
                          'parts_section': False, 'lyrics_section': False, 'hidden': False,
                          'greyed_row': False}, self._bind('composer:singer'),
                         'a singer : the scores and the lyrics stay')
        self.assertEqual({'extract_parts': False, 'parts_model': False, 'lyrics_model': True,
                          'parts_section': False, 'lyrics_section': True, 'hidden': False,
                          'greyed_row': True}, self._bind('composer:cover'))

    def test_the_settings_and_the_card_say_the_same_reason(self):
        """One decision, one wording : the greyed settings say what the card strip says."""
        from wama.common.services.process_pipeline import AppPipeline
        js = (JS / 'wama-params.js').read_text(encoding='utf-8')
        self.assertIn(f"var UNSERVED_NOTE = '{AppPipeline.REASONS['model']}.';", js)

    def test_under_auto_nothing_is_greyed(self):
        """The draw is not known : nothing is guessed (the rule of `cap_from`)."""
        self.assertEqual({'extract_parts': False, 'parts_model': False, 'lyrics_model': False,
                          'parts_section': False, 'lyrics_section': False, 'hidden': False,
                          'greyed_row': False}, self._bind('auto:text-to-music'))

    def test_a_step_the_model_imposes_is_checked_and_locked_and_the_user_value_still_posts(self):
        """`required_by` (2026-11-07, « partition réduite autonome ») : under a model that covers by
        its score, the switch of the reduced score is checked and locked, the section says why ;
        `read()` still posts the USER's value (the server imposes on its own), and another model
        gives it back."""
        imposed = {'all': [{'field': 'inputs_optional', 'in': ['work_score']},
                           {'not': {'field': 'inputs_optional', 'in': ['work_audio']}}]}
        by_score = {'task': 'text-to-music', 'inputs_optional': ['work_score']}
        self.v8.eval(f"""
            function fetch() {{
              var payload = {{models: [{{model_key: 'composer:yue', capabilities: {json.dumps(by_score)}}},
                                       {{model_key: 'composer:melody', capabilities: {json.dumps(COVER)}}}]}};
              return {{then: function (f) {{ return Promise.resolve(f({{json: function () {{ return payload; }}}})); }}}};
            }}
            var box = {{type: 'checkbox', checked: false, disabled: false, dataset: {{}},
                        getAttribute: function (a) {{ return a === 'name' ? 'extract_reduced_score' : null; }},
                        dispatchEvent: function () {{}}}};
            var sw = {{hidden: false, classList: {{toggle: function () {{}}}},
                       querySelector: function (s) {{ return s === 'input[type="checkbox"]' ? box : null; }},
                       getAttribute: function (a) {{
                         return a === 'data-imposed-by' ? {json.dumps(json.dumps(imposed))}
                              : (a === 'data-needs-field' ? 'model' : null); }}}};
            var m = fakeField('composer:yue', '');
            var host = {{_wpCapApply: [], querySelector: function (sel) {{ return sel === '#m' ? m : null; }},
                         querySelectorAll: function (sel) {{
                           if (sel === '[data-group]') return [];
                           if (sel === '[name],[data-param]') return [box];
                           if (sel === '[data-replace-own="1"]') return [];
                           return [sw]; }},
                         addEventListener: function () {{}}}};
            window.WamaParams.bindProcessNeeds(host, [{{name: 'model', type: 'select', help_source: 'composer',
                                                       dom_id: {{panel: 'm'}}}}], 'panel');""")
        under_yue = json.loads(self.v8.eval(
            "JSON.stringify([box.checked, box.disabled, window.WamaParams.read(host).extract_reduced_score,"
            " sw.title])"))
        self.assertEqual([True, True, False, 'Imposée par le modèle choisi.'], under_yue,
                         'checked and locked for the eye ; the user value (unchecked) is posted')
        back = json.loads(self.v8.eval(
            "m.value = 'composer:melody'; host._wpCapApply.forEach(function (f) { f(); });"
            " JSON.stringify([box.checked, box.disabled, sw.title])"))
        self.assertEqual([False, False, ''], back, 'another model gives the user value back')

    def test_the_rendered_row_carries_what_its_processes_require(self):
        schema = [{'name': 'duration', 'type': 'number', 'stales': ['render']},
                  {'name': 'lyrics_model', 'type': 'select', 'stales': ['rendered_lyrics']}]
        out = self.v8.eval(
            "(function () { var host = {innerHTML: '', querySelectorAll: function () { return []; },"
            " querySelector: function () { return null; }, addEventListener: function () {}};"
            f" window.WamaParams.render(host, {json.dumps(schema)},"
            f" {{context: 'panel', processes: {json.dumps(NEEDS_PROCESSES)}}});"
            " return host.innerHTML; })()")
        self.assertIn('data-param-row="lyrics_model" data-needs="&quot;supports_vocals&quot;" '
                      'data-needs-field="model"', out)
        self.assertNotIn('data-param-row="duration" data-needs', out)


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class TheBatchSaysWhatEachChildKeepsTest(SimpleTestCase):
    """2026-11-05, Fabien : the choice is made LINE BY LINE, and « réaligner » / « faire de ses
    réglages la référence » live beside the settings (« ne pas disperser »). What the page shows
    and posts ; the server judges the same rule (`tests_batch_views.OwnValuesOfTheChildrenTest`)."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval(FAKE_BINDING)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _line(self, computed, personal, total, replaced=False):
        return self.v8.eval(f"window.WamaParams.ownLineText({{computed: {computed}, personal: {personal}}}, "
                            f"{total}, {json.dumps(replaced)})")

    def test_the_line_counts_what_is_kept_and_why(self):
        self.assertEqual("S'appliquera à 2 cards · 3 gardent leur valeur (2 liées à leur entrée, "
                         "1 réglée à la main).", self._line(2, 1, 5))
        self.assertEqual("S'appliquera à 4 cards · 1 garde sa valeur (1 liée à leur entrée).",
                         self._line(1, 0, 5))
        self.assertEqual("S'appliquera aux 5 cards, valeurs propres comprises (2 liées à leur entrée).",
                         self._line(2, 0, 5, True))

    def test_a_line_marked_replace_too_travels_with_the_settings(self):
        out = json.loads(self.v8.eval("""JSON.stringify(window.WamaParams.read({
            querySelectorAll: function (sel) {
              if (sel === '[data-replace-own="1"]') return [
                {getAttribute: function () { return 'duration'; }},
                {getAttribute: function () { return 'prompt'; }}];
              return [{type: 'number', value: '60', dataset: {},
                       getAttribute: function (a) { return a === 'name' ? 'duration' : null; }}];
            }}))"""))
        self.assertEqual({'duration': '60', 'replace_own': 'duration,prompt'}, out)

    def _block(self, header_attrs, card=False):
        return self.v8.eval(f"""(function () {{
            var made = [];
            document.createElement = function () {{
              var el = {{className: '', innerHTML: '',
                         querySelector: function () {{ return {{addEventListener: function () {{}}}}; }}}};
              made.push(el); return el; }};
            var attrs = {json.dumps(header_attrs)};
            var header = {{getAttribute: function (a) {{ return attrs[a] === undefined ? null : attrs[a]; }}}};
            var group = {{querySelector: function () {{ return header; }}}};
            var host = {{querySelector: function () {{ return null; }}, appendChild: function () {{}}}};
            var block = window.WamaParams.batchAlignment(host, group, {'{dataset: {id: 7}}' if card else 'null'});
            return block ? block.innerHTML : null; }})()""")

    def test_the_mother_realigns_with_its_scope_and_says_when_there_is_no_reference(self):
        html = self._block({'data-batch-realign-url': '/r/', 'data-batch-reference': '1'})
        self.assertIn('Réaligner toutes les cards sur la référence', html)
        self.assertIn('<option value="keep_computed" selected>', html, 'default : the input values stay')
        self.assertNotIn('disabled', html)
        none = self._block({'data-batch-realign-url': '/r/', 'data-batch-reference': '0'})
        self.assertIn('disabled', none)
        self.assertIn('Aucune référence', none)

    def test_a_child_offers_its_settings_as_the_reference(self):
        html = self._block({'data-batch-promote-url': '/p/'}, card=True)
        self.assertIn('Faire de ses réglages la référence du lot', html)

    def test_without_the_route_nothing_is_offered(self):
        """Counter-proof : an app that does not route the gesture shows no block."""
        self.assertIsNone(self.v8.eval("""window.WamaParams.batchAlignment(
            {querySelector: function () { return null; }, appendChild: function () {}},
            {querySelector: function () { return null; }}, null)"""))


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
class ProcessSectionsTest(SimpleTestCase):
    """2026-10-26, Fabien : « des sections automatiques en accordéon par sous-process » in the
    modal and the panel — each setting in the section of the ONE process it stales, the shared
    ones first ; settings staling only OPTIONAL processes go with the first of them."""

    PROCESSES = json.dumps([{'key': 'extract_score', 'label': 'Partition réduite', 'optional': False},
                            {'key': 'parts', 'label': 'Partition complète', 'optional': True},
                            {'key': 'plan', 'label': 'Partition', 'optional': False},
                            {'key': 'render', 'label': 'Rendu', 'optional': False},
                            {'key': 'output', 'label': 'Sortie', 'optional': False},
                            {'key': 'rendered_parts', 'label': 'Partition de sortie', 'optional': True}])

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-params.js').read_text(encoding='utf-8'))

    def _sections(self, schema, processes=None):
        return json.loads(self.v8.eval(
            f"JSON.stringify(window.WamaParams.processSections({json.dumps(schema)}, "
            f"{processes or self.PROCESSES}))"))

    def test_each_setting_goes_to_the_section_of_its_process(self):
        schema = [{'name': 'prompt', 'stales': ['plan', 'render']},
                  {'name': 'model', 'stales': ['plan', 'render']},
                  {'name': 'duration', 'stales': ['render']},
                  {'name': 'extract_parts', 'stales': ['parts']},
                  {'name': 'extract_rendered_parts', 'stales': ['rendered_parts']},
                  {'name': 'parts_model', 'stales': ['parts', 'rendered_parts']},
                  {'name': 'output_format', 'stales': ['output']},
                  {'name': 'show_boxes', 'stales': []}]
        out = self._sections(schema)
        self.assertEqual(['prompt', 'model', 'show_boxes'], out['general'], 'shared ones first')
        self.assertEqual([('parts', ['extract_parts', 'parts_model']), ('render', ['duration']),
                          ('output', ['output_format']), ('rendered_parts', ['extract_rendered_parts'])],
                         [(s['key'], s['names']) for s in out['sections']],
                         'pipeline order ; the model of the two optional ones with the first')

    def test_a_section_names_the_optional_processes_its_shared_settings_also_serve(self):
        """The reader (2026-10-28, Fabien) : its language model serves the formatting AND the
        analysis — the analysis has no section of its own, so the section says both. The composer's
        « Partition de sortie » HAS its own section : it is not named twice."""
        reader = json.dumps([{'key': 'read', 'label': 'Lecture', 'optional': False},
                             {'key': 'format', 'label': 'Mise en forme', 'optional': True},
                             {'key': 'analyze', 'label': 'Analyse', 'optional': True}])
        out = self._sections([{'name': 'mode', 'stales': ['read']},
                              {'name': 'llm_model', 'stales': ['format', 'analyze']}], reader)
        self.assertEqual([('read', 'Lecture'), ('format', 'Mise en forme · Analyse')],
                         [(s['key'], s['label']) for s in out['sections']])
        composer = self._sections([{'name': 'extract_parts', 'stales': ['parts']},
                                   {'name': 'extract_rendered_parts', 'stales': ['rendered_parts']},
                                   {'name': 'parts_model', 'stales': ['parts', 'rendered_parts']}])
        self.assertEqual(['Partition complète', 'Partition de sortie'],
                         [s['label'] for s in composer['sections']])

    def test_the_gear_of_a_step_files_a_shared_setting_under_that_step(self):
        """2026-11-08, Fabien : in the gear of « Paroles chantées » the listening model sat under a
        section « Paroles de l'entrée » — the first optional step sharing it. With the step in
        focus, the shared setting goes to IT and its section names only it ; without a focus (the
        general modal) the rule is unchanged (counter-proof)."""
        processes = json.dumps([
            {'key': 'extract_lyrics', 'label': "Paroles de l'entrée", 'optional': True,
             'toggle': 'extract_input_lyrics', 'watched': ['extract_input_lyrics', 'lyrics_model']},
            {'key': 'render', 'label': 'Rendu', 'optional': False, 'watched': ['duration']},
            {'key': 'rendered_lyrics', 'label': 'Paroles chantées', 'optional': True,
             'toggle': 'extract_rendered_lyrics',
             'watched': ['extract_rendered_lyrics', 'lyrics_model']}])
        schema = [{'name': 'extract_rendered_lyrics', 'type': 'toggle'},
                  {'name': 'lyrics_model', 'type': 'select'},
                  {'name': 'duration', 'stales': ['render']}]
        focused = json.loads(self.v8.eval(
            f"JSON.stringify(window.WamaParams.processSections({json.dumps(schema)}, {processes},"
            " 'rendered_lyrics'))"))
        self.assertEqual([('render', 'Rendu', ['duration']),
                          ('rendered_lyrics', 'Paroles chantées', ['lyrics_model'])],
                         [(s['key'], s['label'], s['names']) for s in focused['sections']])
        general = self._sections(schema, processes)
        self.assertEqual("Paroles de l'entrée", general['sections'][0]['label'],
                         'no focus : the shared setting still goes with the first optional step')

    def test_the_switch_of_a_step_wears_the_label_of_the_step(self):
        """2026-11-08 : the strip and the section head said « Partition jouée », the switch rendered
        flat (a step's gear, the panel) « Partition de sortie (instruments) ». Read on the step ; a
        switch that commands no step keeps its own label (counter-proof)."""
        out = self._rendered([{'name': 'extract_rendered_parts', 'type': 'toggle',
                               'label': 'Partition de sortie (instruments)'},
                              {'name': 'loop', 'type': 'toggle', 'label': 'En boucle'}],
                             processes=json.dumps([{'key': 'rendered_parts', 'label': 'Partition jouée',
                                                    'toggle': 'extract_rendered_parts'}]))
        self.assertIn('Partition jouée', out)
        self.assertNotIn('Partition de sortie (instruments)', out)
        self.assertIn('En boucle', out)

    def test_nothing_to_structure_stays_flat(self):
        self.assertIsNone(self._sections([{'name': 'a', 'stales': ['render']},
                                          {'name': 'b', 'stales': ['render']}]),
                          'one section alone : flat')
        self.assertIsNone(self._sections([{'name': 'a', 'stales': ['render']}], '[]'),
                          'no pipeline : flat')

    SWITCHED = json.dumps([
        {'key': 'extract_score', 'label': 'Partition réduite', 'optional': True,
         'toggle': 'extract_reduced_score', 'watched': ['extract_reduced_score']},
        {'key': 'parts', 'label': 'Partition complète', 'optional': True, 'toggle': 'extract_parts',
         'watched': ['extract_parts', 'parts_model']},
        {'key': 'plan', 'label': 'Partition', 'optional': False, 'watched': ['prompt']},
        {'key': 'render', 'label': 'Rendu', 'optional': False, 'toggle': 'generate_audio',
         'watched': ['prompt', 'duration', 'seed', 'generate_audio']},
        {'key': 'output', 'label': 'Sortie', 'optional': False,
         'watched': ['output_format', 'output_quality']},
        {'key': 'rendered_parts', 'label': 'Partition de sortie', 'optional': True,
         'toggle': 'extract_rendered_parts', 'watched': ['extract_rendered_parts', 'parts_model']}])

    def _rendered(self, schema, processes=None, values=None, groups=None):
        return self.v8.eval(
            "(function () { var host = {innerHTML: '', querySelectorAll: function () { return []; },"
            " querySelector: function () { return null; }, addEventListener: function () {}};"
            f" window.WamaParams.render(host, {json.dumps(schema)},"
            f" {{context: 'panel', processes: {processes or self.SWITCHED},"
            f" values: {json.dumps(values or {})}, groups: {json.dumps(groups)}}});"
            " return host.innerHTML; })()")

    def test_one_folded_section_per_step_in_pipeline_order_its_switch_in_its_head(self):
        """2026-11-07, Fabien, on the map of the ten apps : one list in the CHRONOLOGICAL order of
        the pipeline, one foldable section per step, its SWITCH in the head — folded, the heads
        make the row of switches. A setting joins the step that WATCHES it (the output settings,
        which declare no `stales`, used to jump to the top) ; an advanced setting goes in a folded
        « Avancé » of ITS step ; the shared ones (prompt) stay on top."""
        schema = [{'name': 'output_format', 'type': 'select', 'choices': [['original', 'Original']]},
                  {'name': 'prompt', 'type': 'text', 'stales': ['plan', 'render']},
                  # `pills: []` : how the schema serialises a plain switch (seen in the browser).
                  {'name': 'generate_audio', 'type': 'toggle', 'stales': ['render'], 'default': True,
                   'pills': []},
                  {'name': 'duration', 'type': 'number', 'stales': ['render']},
                  {'name': 'extract_parts', 'type': 'toggle', 'stales': ['parts'], 'help': 'Une partie par instrument.'},
                  {'name': 'extract_reduced_score', 'type': 'toggle', 'stales': ['extract_score']},
                  {'name': 'seed', 'type': 'number', 'advanced': True, 'stales': ['render']}]
        out = self._rendered(schema, values={'extract_parts': True})
        heads = [out.index(f'data-group="_process_{k}"') for k in ('extract_score', 'parts', 'render', 'output')]
        self.assertEqual(sorted(heads), heads, 'pipeline order, whatever the schema order')
        self.assertLess(out.index('data-param-row="prompt"'), heads[0], 'shared settings first')
        self.assertNotIn(' open>', out.split('data-group="_process_')[1], 'sections start folded')
        # The switch IS the head of its step : in its <summary>, not in a body.
        render_head = out[heads[2]:out.index('</summary>', heads[2])]
        self.assertIn('class="wama-proc-switch" data-param-row="generate_audio"', render_head)
        self.assertIn('data-param="generate_audio" checked', render_head)
        parts_head = out[heads[1]:out.index('</summary>', heads[1])]
        self.assertIn('data-param="extract_parts" checked', parts_head)
        self.assertIn('Une partie par instrument.', out[heads[1]:heads[2]], 'its help heads the body')
        self.assertIn('wama-proc-section--off', out[heads[0] - 120:heads[0]],
                      'a switched-off step is greyed')
        self.assertTrue(heads[2] < out.index('data-param-row="duration"') < heads[3])
        self.assertTrue(heads[3] < out.index('data-param-row="output_format"'),
                        'the output settings, watched by the output, come last')
        self.assertTrue(heads[2] < out.index('data-group="_advanced_render"') < heads[3],
                        'an advanced setting of a step folds in ITS step')
        self.assertNotIn('data-group="_advanced"', out, 'no advanced left for the common box')

    def test_a_field_with_a_writer_gets_its_button_and_no_other_does(self):
        """`Param.write_from` (2026-11-08, « Écrire les paroles ») : the button under the field,
        carrying what it reads from THIS form ; a plain text area has none (counter-proof)."""
        cfg = {'app': 'composer', 'target': 'prompt', 'source': 'prompt', 'duration': 'duration',
               'model': 'model', 'label': 'Écrire les paroles'}
        out = self._rendered([{'name': 'lyrics', 'type': 'textarea', 'write_from': cfg},
                              {'name': 'notes', 'type': 'textarea'}], processes='[]')
        self.assertEqual(1, out.count('class="btn btn-sm btn-outline-secondary mt-1 wama-write-from"'))
        self.assertIn('data-write-for="wp-panel-lyrics"', out)
        self.assertIn('Écrire les paroles</button>', out)
        self.assertLess(out.index('wp-panel-lyrics'), out.index('wama-write-from'))
        self.assertLess(out.index('wama-write-from'), out.index('wp-panel-notes'),
                        'the button belongs to its own field only')

    def test_declared_groups_live_inside_the_section_of_each_step(self):
        """The imager, the anonymizer, the converter declare groups (ParamGroup) : they KEEP them,
        inside the section of each step ; a sub-group named like its section loses its title, not
        its condition."""
        processes = json.dumps([{'key': 'generate', 'label': 'Génération', 'watched': ['model', 'steps']},
                                {'key': 'output', 'label': 'Sortie', 'watched': ['output_format']}])
        groups = [{'key': 'qualite', 'title': 'Qualité'},
                  {'key': 'sortie', 'title': 'Sortie', 'show_if': {'field': 'model'}}]
        schema = [{'name': 'model', 'type': 'text'}, {'name': 'steps', 'type': 'number', 'group': 'qualite'},
                  {'name': 'output_format', 'type': 'text', 'group': 'sortie'}]
        out = self._rendered(schema, processes, groups=groups)
        generate, output = out.index('data-group="_process_generate"'), out.index('data-group="_process_output"')
        self.assertTrue(generate < out.index('data-group="qualite"') < output)
        self.assertIn('Qualité', out[generate:output])
        output_group = out.index('data-group="sortie"')
        self.assertGreater(output_group, output)
        self.assertNotIn('wama-param-group-title">Sortie', out[output_group:], 'same name : no second title')
        self.assertIn('data-show-if', out[output_group:output_group + 120], 'its condition stays')


class ProcessesOfThePageTest(SimpleTestCase):
    """What the base page hands to `processSections` (`window.WAMA_APP_PROCESSES`): the processes
    of the app of the address, in pipeline order — read through `app_pipeline`, which loads the
    declarations a fresh web process has not imported yet (the 500 of 2026-10-03)."""

    def _processes(self, path):
        from django.contrib.auth.models import AnonymousUser
        from django.test import RequestFactory
        from wama.accounts.context_processors import user_role
        request = RequestFactory().get(path)
        request.user = AnonymousUser()
        return json.loads(user_role(request)['current_app_processes_json'])

    def test_a_fresh_process_loads_the_declarations_before_answering(self):
        from unittest import mock
        from wama.common.services import process_pipeline as pp
        declared = pp.AppPipeline('composer', (
            pp.ProcessSpec('plan', label='Partition'),
            pp.ProcessSpec('render', label='Rendu', depends_on=('plan',)),
            pp.ProcessSpec('rendered_parts', label='Partition de sortie', depends_on=('render',),
                           degree='optional', toggle='extract_rendered_parts'),
        ), label='Demo')
        with mock.patch.dict(pp.APP_PIPELINES, clear=True), \
                mock.patch.object(pp, '_load_declarations',
                                  side_effect=lambda: pp.APP_PIPELINES.update(composer=declared)) as load:
            processes = self._processes('/composer/')
        load.assert_called_once_with()
        # `watched` (2026-11-07) : what each step watches, by which the page files each setting.
        watched = {p['key']: p.pop('watched') for p in processes}
        self.assertEqual({key: list(declared.watched_of(declared.spec(key))) for key in watched},
                         watched)
        self.assertEqual([{'key': 'plan', 'label': 'Partition', 'toggle': '', 'optional': False},
                          {'key': 'render', 'label': 'Rendu', 'toggle': '', 'optional': False},
                          {'key': 'rendered_parts', 'label': 'Partition de sortie',
                           'toggle': 'extract_rendered_parts', 'optional': True}], processes)

    def test_a_page_outside_the_apps_hands_nothing(self):
        self.assertEqual([], self._processes('/accounts/profile/'))


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

    def test_the_scoped_schema_keeps_the_field_that_commands_a_kept_setting(self):
        """The summary type was HIDDEN in the gear of the « Résumé » process (describer,
        transcriber, 2026-10-13): its `show_if` reads the summary switch, which the scope had
        left out — a condition that cannot be judged hides its row."""
        schema = ("[{name: 'generate_summary', type: 'toggle'},"
                  " {name: 'summary_type', type: 'radio', show_if: 'generate_summary'},"
                  " {name: 'engine', type: 'select', show_if: {field: 'mode', equals: 'x'}},"
                  " {name: 'mode', type: 'select', show_if: 'advanced'},"
                  " {name: 'advanced', type: 'toggle'}, {name: 'language', type: 'select'}]")
        names = lambda wanted: list(self.v8.eval(
            f"window.WamaParams.scopedSchema({schema}, {wanted})"
            ".map(function (p) {{ return p.name; }})"))
        self.assertEqual(['generate_summary', 'summary_type'], names("['summary_type']"))
        self.assertEqual(['engine', 'mode', 'advanced'], names("['engine']"),
                         'a command that has its own command is kept with it')
        self.assertEqual(['language'], names("['language']"), 'nothing more when nothing commands')

    def test_the_server_twin_reduces_exactly_like_the_card(self):
        """`param_schema.scoped_names` — the Studio step node and its executor — is the twin of
        `scopedSchema` (2026-10-18): every case above, and a hidden carrier, on both sides."""
        import json
        from wama.common.utils.param_schema import scoped_names
        schema = [{'name': 'media_type', 'type': 'hidden'},
                  {'name': 'generate_summary', 'type': 'toggle'},
                  {'name': 'summary_type', 'type': 'radio', 'show_if': 'generate_summary'},
                  {'name': 'engine', 'type': 'select', 'show_if': {'field': 'mode', 'equals': 'x'}},
                  {'name': 'mode', 'type': 'select', 'show_if': 'advanced'},
                  {'name': 'advanced', 'type': 'toggle'}, {'name': 'language', 'type': 'select'}]
        for wanted in (['summary_type'], ['engine'], ['language'], [], ['nope']):
            with self.subTest(wanted=wanted):
                browser = list(self.v8.eval(
                    f"window.WamaParams.scopedSchema({json.dumps(schema)}, {json.dumps(wanted)})"
                    ".map(function (p) {{ return p.name; }})"))
                self.assertEqual(browser, scoped_names(schema, wanted))

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

    def test_the_scope_carries_its_step_into_the_modal(self):
        """2026-11-08 : the gear of a step names ITS step (`data-process`), which the modal gets as
        its focus (`processSections`) — a scope without a step gives none."""
        out = self.v8.eval("""(function () {
            var P = window.WamaParams;
            P.scopeNextModal(['lyrics_model'], 'Paroles chantées', 'rendered_lyrics');
            var cfg = P.scopedConfig({schema: [{name: 'lyrics_model'}]}, P.takeModalScope());
            P.scopeNextModal(['lyrics_model'], 'Paroles chantées');
            var bare = P.scopedConfig({schema: []}, P.takeModalScope());
            return [cfg.processFocus, bare.processFocus];
        })()""")
        self.assertEqual(['rendered_lyrics', ''], list(out))

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
    the toggle has one button per view, the active one filled, and says the key it picks. Held in
    the preview brick (`WamaMediaPreview`) since 2026-10-13 ; `WamaInspector` keeps the old names."""

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
        self.v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))
        self.v8.eval((JS / 'wama-inspector.js').read_text(encoding='utf-8'))

    def test_the_address_carries_the_chosen_view(self):
        out = self.v8.eval("""(function () {
            var I = window.WamaMediaPreview;
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
            var bar = window.WamaMediaPreview.variantToggle(
                [{key: 'detection', label: 'Détection'}, {key: 'blur', label: 'Floutage'}],
                'blur', function (k) { picked.push(k); });
            bar.children[0].listeners.click();
            return [bar.children.length, bar.children[0].textContent,
                    bar.children[1].className.indexOf('btn-info ') >= 0
                      || / btn-info$/.test(bar.children[1].className) || bar.children[1].className.indexOf(' btn-info') >= 0,
                    bar.children[0].className.indexOf('btn-outline-info') >= 0, picked[0]];
        })()""")
        self.assertEqual([2, 'Détection', True, True, 'detection'], list(out))

    def test_the_inspector_keeps_its_old_names_as_aliases(self):
        out = self.v8.eval("[window.WamaInspector.duringUrl('/p/', 'blur'), "
                           "window.WamaInspector.variantToggle([{key: 'a'}], 'a', function () {}).children.length]")
        self.assertEqual(['/p/?side=during&variant=blur', 1], list(out))


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
        self.assertIn('_fetchItem(endpoint)', self._body('media-preview.js', 'function openPreview'))
        self.assertIn('data._baseUrl = base', self._body('media-preview.js', 'function _fetchItem'),
                      'a card thumbnail opens the modal WITH its faces')
        # The side panel's faces are the common face viewer since 2026-10-28 (the assistant's job
        # lines mount it too) : its PENDING face opens the modal like any other face.
        self.assertIn('P.faceViewer(previewHost', self._body('wama-inspector.js', 'function fillPreview'))
        self.assertIn('attach(d)', self._body('media-preview.js', 'function follow()'),
                      'the PENDING face of the side panel opens the modal too')
        self.assertIn('_startModalDuring(modal, data)', self._body('media-preview.js',
                                                                  'function _display('),
                      'the PENDING face is followed live in the modal')
        # The keyboard navigation goes through the SAME display as an opening (it raised a
        # ReferenceError from 2026-07-21 to 2026-10-05, then rebuilt the content by its own copy).
        navigation = self._body('media-preview.js', 'function _navigate')
        self.assertIn('_display(d)', navigation)
        self.assertNotIn('buildPreviewContent', navigation)

    def test_one_follower_of_the_pending_face_for_the_panel_and_the_modal(self):
        """The modal had its own copy of the panel's follower (2026-10-05, removed the next day
        at Fabien's « rien réinventé ? ») : both go through `WamaMediaPreview.followDuring`."""
        self.assertIn('followDuring(', self._body('media-preview.js', 'function follow()'),
                      'the face viewer of the side panel and of the job lines')
        modal = self._body('media-preview.js', 'function _startModalDuring')
        self.assertIn('followDuring(', modal)
        self.assertNotIn('setInterval', modal)
        self.assertIn('variantToggle(', self._body('media-preview.js',
                                                  'function _renderModalVariants'))

    def _follower_v8(self):
        """V8 with the common loop and the preview brick, a synchronous fake fetch and clock : each
        call answers the next payload. The follower runs on `WamaApp.Poller` (2026-10-13), which
        chains `setTimeout` after each answer — `tick()` fires the one pending turn."""
        from py_mini_racer import MiniRacer
        v8 = MiniRacer()
        v8.eval(FAKE_DOM)
        v8.eval("""
            var calls = [], payloads = [], pending = null;
            function setTimeout(fn) { pending = fn; return 1; }
            function clearTimeout() { pending = null; }
            function tick() { var fn = pending; pending = null; if (fn) fn(); }
            function thenable(value) {
              return {then: function (f) { return thenable(f(value)); },
                      catch: function () { return thenable(value); }};
            }
            function fetch(url) {
              calls.push(url);
              var body = payloads.shift();
              return thenable({ok: true, json: function () { return body; }});
            }
        """)
        v8.eval("document.cookie = ''; var navigator = {}; var localStorage = "
                "{getItem: function () { return null; }, setItem: function () {}};")
        v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        v8.eval('var WamaApp = window.WamaApp;')
        v8.eval((JS / 'media-preview.js').read_text(encoding='utf-8'))
        return v8

    def test_the_follower_renders_changes_only_keeps_the_view_and_ends_on_the_card(self):
        v8 = self._follower_v8()
        out = v8.eval("""(function () {
            var frame = function (url) { return {url: url, variant: 'blur',
              sides: {during_capable: true, has_during: true}}; };
            var gap = {sides: {during_capable: true, has_during: false}};
            var shown = [], ended = [], running = true;
            payloads = [frame('a.jpg'), frame('a.jpg'), gap, frame('b.jpg')];
            var f = window.WamaMediaPreview.followDuring('/p/7/', {
              isRunning: function () { return running; },
              onFrame: function (d) { shown.push(d.url); },
              onEnd: function () { ended.push('end'); }});
            tick(); tick(); tick();                     // same frame, gap between processes, new
            payloads = [frame('c.jpg')];
            f.choose('detection');                      // the chosen view is asked at once
            running = false; tick();                    // the card is done → end, once
            tick();
            return [shown, ended, calls[calls.length - 1]];
        })()""")
        self.assertEqual(['a.jpg', 'b.jpg', 'c.jpg'], list(out[0]),
                         'same frame not re-rendered ; a gap between processes is not the end')
        self.assertEqual(['end'], list(out[1]))
        self.assertEqual('/p/7/?side=during&variant=detection', out[2])

    def test_a_sound_that_grows_resumes_where_it_was_playing(self):
        """2026-10-20 (Composer : the music shown WHILE it is computed) : each new partial rebuilt
        the player, which restarted from 0 every few seconds. The follower itself takes the clock
        of what its `host()` shows before `onFrame`, and gives it to what `onFrame` rendered — for
        the panel and the viewer alike."""
        v8 = self._follower_v8()
        out = v8.eval("""(function () {
            var medium = function () { var m = {currentTime: 0, paused: true, ended: false, readyState: 4,
                duration: 60, played: 0, pause: function () { m.paused = true; },
                play: function () { m.played++; m.paused = false; return {catch: function () {}}; }};
                return m; };
            var shown = null;
            var host = {querySelector: function (sel) { return sel.indexOf('video') >= 0 ? shown : null; }};
            var frame = function (url) { return {url: url, mime_type: 'video/mp4',
              sides: {during_capable: true, has_during: true}}; };
            payloads = [frame('p1.mp4'), frame('p2.mp4')];
            var players = [];
            window.WamaMediaPreview.followDuring('/p/8/', {
              host: function () { return host; },
              onFrame: function (d) { shown = medium(); players.push(shown); }});
            // (the first partial is asked at once, `immediate` : nothing to resume yet)
            players[0].currentTime = 4.2; players[0].paused = false;   // the user listens
            tick();                                         // the next, longer partial
            return [players.length, players[0].paused, players[1].currentTime, players[1].played];
        })()""")
        self.assertEqual(2, out[0])
        self.assertTrue(out[1], 'the partial left is stopped')
        self.assertEqual([4.2, 1], [out[2], out[3]], 'the next partial resumes, playing, at 4.2 s')

    CARD_HOST = """
        function cardHost(attrs, card) {
          var a = {}; for (var k in attrs) a[k] = attrs[k];
          var h = {dataset: {previewMode: 'excerpt'}, classList: classList(), textContent: '',
            innerHTML: '', isConnected: true,
            getAttribute: function (k) { return k in a ? a[k] : null; },
            hasAttribute: function (k) { return k in a; },
            setAttribute: function (k, v) { a[k] = String(v); },
            removeAttribute: function (k) { delete a[k]; },
            closest: function () { return card; }, matches: function () { return true; },
            querySelector: function () { return null; }, querySelectorAll: function () { return []; },
            appendChild: function () {}};
          h.parentNode = {querySelectorAll: function () { return a['data-preview-hydrated'] ? [] : [h]; }};
          return h;
        }
        var text = function (t) { return {mime_type: 'text/plain', content: t,
          sides: {during_capable: true, has_during: true}}; };
    """

    def test_a_running_card_shows_its_pending_face_then_stops(self):
        """2026-10-20 (Fabien : « la card doit suivre la face Pendant ») : the host the template
        lays out while there is no output (`{% card_during %}`) is followed by THE follower, and
        rendered by THE inline renderer at the card's density — what the describer alone wrote in
        its card by hand."""
        v8 = self._follower_v8()
        v8.eval(self.CARD_HOST)
        out = v8.eval("""(function () {
            var card = {dataset: {status: 'RUNNING'}};
            var host = cardHost({'data-card-during': '/common/preview/describer/5/'}, card);
            payloads = [text('Un chat noir'), text('Un chat noir dort sur un canapé')];
            window.WamaMediaPreview.followCard(host);
            window.WamaMediaPreview.followCard(host);        // a second call adds no follower
            var first = host.textContent;
            tick();
            var second = host.textContent;
            card.dataset.status = 'SUCCESS'; tick(); tick(); // the card is done → the follow ends
            return [first, second, calls.slice(), host.classList.contains('wama-card-preview'),
                    host.getAttribute('data-preview-url'), host._wamaDuring];
        })()""")
        self.assertEqual('Un chat noir', out[0])
        self.assertEqual('Un chat noir dort sur un canapé', out[1])
        self.assertEqual(['/common/preview/describer/5/?side=during'] * 2, list(out[2]),
                         'one follower, and no request once the card is done')
        self.assertTrue(out[3], 'the waiting host becomes a card preview (style and gesture)')
        self.assertEqual('/common/preview/describer/5/?side=during', out[4])
        self.assertIsNone(out[5])

    def test_a_surface_that_publishes_nothing_costs_one_request(self):
        """The template does not copy the declaration : the server says whether the face exists
        (`sides.during_capable`, read from `during_preview`) — the enhancer's audio does not."""
        v8 = self._follower_v8()
        v8.eval(self.CARD_HOST)
        out = v8.eval("""(function () {
            var host = cardHost({'data-card-during': '/common/preview/audio_enhancer/4/'},
                                {dataset: {status: 'RUNNING'}});
            payloads = [{sides: {during_capable: false, has_during: false}}];
            window.WamaMediaPreview.followCard(host);
            tick(); tick();
            return [calls.length, host.textContent, host.classList.contains('wama-card-preview')];
        })()""")
        self.assertEqual([1, '', False], list(out))

    def test_a_card_not_running_is_not_followed(self):
        v8 = self._follower_v8()
        v8.eval(self.CARD_HOST)
        out = v8.eval("""(function () {
            var host = cardHost({'data-card-during': '/common/preview/reader/3/'},
                                {dataset: {status: 'PENDING'}});
            window.WamaMediaPreview.followCard(host);
            return calls.length;
        })()""")
        self.assertEqual(0, out)

    def test_a_relaunched_card_shows_the_pending_face_then_its_output_again(self):
        """A card that already had an output and is launched again : its OUTPUT host follows the
        Pending face, then gets its output back when the run ends."""
        v8 = self._follower_v8()
        v8.eval(self.CARD_HOST)
        out = v8.eval("""(function () {
            var card = {dataset: {status: 'RUNNING'}};
            var host = cardHost({'data-card-preview': '/common/preview/transcriber/9/?side=output',
                                 'data-preview-hydrated': '1'}, card);
            payloads = [text('Bonjour'), {mime_type: 'text/plain', content: 'Bonjour à tous.'}];
            window.WamaMediaPreview.followCard(host);
            var during = host.textContent;
            card.dataset.status = 'SUCCESS'; tick();
            return [during, host.textContent, calls.slice()];
        })()""")
        self.assertEqual('Bonjour', out[0])
        self.assertEqual('Bonjour à tous.', out[1])
        self.assertEqual(['/common/preview/transcriber/9/?side=during',
                          '/common/preview/transcriber/9/?side=output'], list(out[2]))

    def test_both_consumers_hand_their_host_to_the_follower(self):
        self.assertIn('host: function () { return host; }',
                      self._body('media-preview.js', 'function follow()'))
        modal = self._body('media-preview.js', 'function _startModalDuring')
        self.assertIn('host: _modalContainer', modal)
        self.assertNotIn('takeClock', modal, 'the clock is kept by the follower, not copied per consumer')

    def test_the_full_screen_of_an_item_is_the_modal_itself(self):
        expand = self._body('media-preview.js', 'function _expand')
        self.assertIn('_setModalFull(', expand, 'an item keeps its faces in full screen')
        css = (Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'css'
               / 'media-preview.css').read_text(encoding='utf-8')
        self.assertIn('.modal-dialog.modal-fullscreen .preview-container img', css)


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class FaceViewerTest(SimpleTestCase):
    """THE face viewer of an item in any host (2026-10-28, Fabien : « intégrer la preview dans
    l'échange avec l'assistant pour avoir le rendu preview — entrée/during/comparaison/sortie ») :
    what the side panel did alone for its single host, now mounted by every job line of the
    assistant's exchange too — the default face, the PENDING face followed then the OUTPUT, the face
    tabs, the double-click to the viewer."""

    _follower_v8 = PreviewModalTest._follower_v8

    ELEMENT = """
        function el(tag) {
          var e = {tagName: (tag || 'div').toUpperCase(), children: [], dataset: {}, style: {},
                   attrs: {}, classList: classList(), title: '', isConnected: true,
                   setAttribute: function (k, v) { this.attrs[k] = String(v); },
                   getAttribute: function (k) { return k in this.attrs ? this.attrs[k] : null; },
                   hasAttribute: function (k) { return k in this.attrs; },
                   removeAttribute: function (k) { delete this.attrs[k]; },
                   appendChild: function (c) { this.children.push(c); c.parentNode = this; return c; },
                   insertBefore: function (c) { this.children.unshift(c); c.parentNode = this; return c; },
                   addEventListener: function (t, f) { (this.on = this.on || {})[t] = f; },
                   querySelector: function () { return null; },
                   querySelectorAll: function () { return []; },
                   closest: function () { return null; }};
          Object.defineProperty(e, 'firstChild', {get: function () { return e.children[0] || null; }});
          Object.defineProperty(e, 'innerHTML', {get: function () { return e._html || ''; },
                                                 set: function (v) { e._html = v; e.children = []; }});
          return e;
        }
        document.createElement = el;
        function tabs(host) {
          var bar = host.children.filter(function (c) { return c.className && c.className.indexOf('wama-face-tabs') >= 0; })[0];
          return bar ? bar.children.map(function (b) { return b.attrs['data-side']; }) : [];
        }
        function face(side, url, sides) {
          return {side: side, url: url, mime_type: 'image/jpeg', sides: sides};
        }
        var SIDES = {has_input: true, has_output: true, comparable: true, during_capable: true};
    """

    def _v8(self):
        v8 = self._follower_v8()
        v8.eval(self.ELEMENT)
        return v8

    def test_a_running_item_shows_its_input_then_the_pending_face_then_its_output(self):
        v8 = self._v8()
        out = json.loads(v8.eval("""JSON.stringify((function () {
            var status = 'RUNNING', host = el('div');
            var during = Object.assign({}, SIDES, {has_output: false, has_during: true});
            payloads = [face('input', 'in.jpg', during), face('during', 'part.jpg', during)];
            var viewer = window.WamaMediaPreview.faceViewer(host, '/common/preview/imager/4/', {
              compact: true, status: function () { return status; }});
            viewer.refresh();
            var shown = [host.innerHTML.indexOf('part.jpg') >= 0, tabs(host)];
            payloads = [face('output', 'out.jpg', SIDES)];
            status = 'SUCCESS'; tick();                       // the item is done → its output
            return [shown, host.innerHTML.indexOf('out.jpg') >= 0, tabs(host), calls.slice(),
                    typeof host.ondblclick, host.title];
        })())"""))
        self.assertEqual([True, ['input', 'during']], out[0], 'the face being built, with its tabs')
        self.assertTrue(out[1], 'the output once done')
        self.assertEqual(['input', 'compare', 'output'], out[2])
        self.assertEqual(['/common/preview/imager/4/?side=input', '/common/preview/imager/4/?side=during',
                          '/common/preview/imager/4/?side=output'], list(out[3]))
        self.assertEqual(['function', 'Double-clic : plein écran'], [out[4], out[5]],
                         'a double-click opens the viewer, as in the side panel')

    def test_a_finished_item_opens_on_its_output_and_a_tab_on_its_face(self):
        v8 = self._v8()
        out = json.loads(v8.eval("""JSON.stringify((function () {
            var host = el('div');
            payloads = [face('output', 'out.jpg', SIDES)];
            var viewer = window.WamaMediaPreview.faceViewer(host, '/common/preview/imager/4/', {
              status: function () { return 'SUCCESS'; }});
            viewer.refresh();
            var bar = host.children[0];
            payloads = [face('input', 'in.jpg', SIDES)];
            bar.children[0].on.click();                       // « Entrée »
            return [host.innerHTML.indexOf('in.jpg') >= 0, calls.slice()];
        })())"""))
        self.assertTrue(out[0])
        self.assertEqual(['/common/preview/imager/4/?side=output', '/common/preview/imager/4/?side=input'],
                         list(out[1]))

    def test_a_tab_chosen_while_it_runs_stops_the_live_follow(self):
        """The Pending face is followed live ; choosing another face stops it — the next partial
        would otherwise cover the face the user asked for."""
        v8 = self._v8()
        out = json.loads(v8.eval("""JSON.stringify((function () {
            var host = el('div');
            var during = Object.assign({}, SIDES, {has_output: false, has_during: true});
            payloads = [face('input', 'in.jpg', during), face('during', 'part.jpg', during)];
            window.WamaMediaPreview.faceViewer(host, '/common/preview/imager/4/', {
              status: function () { return 'RUNNING'; }}).refresh();
            var followed = pending !== null;
            payloads = [face('input', 'in.jpg', during)];
            host.children[0].children[0].on.click();          // « Entrée »
            tick();
            return [followed, host.innerHTML.indexOf('in.jpg') >= 0, calls.length];
        })())"""))
        self.assertTrue(out[0], 'the Pending face was followed')
        self.assertEqual([True, 3], out[1:], 'the input stays : no partial asked after the choice')

    def test_a_host_gone_from_the_page_follows_nothing(self):
        """The assistant's thread cleared : its job lines leave the page — their follow ends."""
        v8 = self._v8()
        out = json.loads(v8.eval("""JSON.stringify((function () {
            var host = el('div');
            var during = Object.assign({}, SIDES, {has_output: false, has_during: true});
            payloads = [face('input', 'in.jpg', during), face('during', 'part.jpg', during)];
            window.WamaMediaPreview.faceViewer(host, '/common/preview/imager/4/', {
              status: function () { return 'RUNNING'; }}).refresh();
            host.isConnected = false;
            payloads = [face('output', 'out.jpg', SIDES)];
            tick(); tick();
            return calls.slice();
        })())"""))
        self.assertEqual(['/common/preview/imager/4/?side=input', '/common/preview/imager/4/?side=during'],
                         list(out), 'no request once its host has left the page')


class GearValuesReadsTheCardsGearTest(SimpleTestCase):
    """`WamaInspector.gearValues` — the ONE reader of a card's settings (right panel and modal).
    2026-10-21, transcriber #2522: while RUNNING the card's ⚙ was missing, and the first
    `.settings-btn` of the card was the ⚙ of a PROCESS row (`_card_processes.html`, `data-process`)
    — it carries no setting: the panel received {} and kept showing other settings."""

    CARD = """
      function gear(data) { return {dataset: data}; }
      var processGear = gear({id: '7', process: 'transcribe', only: 'backend'});
      var cardGear = gear({id: '7', backend: 'albert:whisper-large-v3', levelSpeech: 'true'});
      function card(gears) {
        return {dataset: {}, querySelectorAll: function () { return gears; },
                querySelector: function () { return gears[0] || null; }};
      }"""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM)
        self.v8.eval((JS / 'wama-inspector.js').read_text(encoding='utf-8'))
        self.v8.eval(self.CARD)

    def _read(self, gears):
        return json.loads(self.v8.eval(
            f"JSON.stringify(window.WamaInspector.gearValues(card({gears}), ['backend', 'level_speech']))"))

    def test_the_process_gear_before_the_cards_gear_is_skipped(self):
        self.assertEqual({'backend': 'albert:whisper-large-v3', 'level_speech': 'true'},
                         self._read('[processGear, cardGear]'))

    def test_a_process_gear_alone_gives_nothing_rather_than_its_scope(self):
        self.assertEqual({}, self._read('[processGear]'))
