"""A setting VALUE that requires a model CAPABILITY greys the models without it (2026-10-05).

The composer's « Voix : Chanson » asks for a model that SINGS (`supports_vocals`); until then only
the launch console said so. The matching brick gained a generic slot for it
(`WamaInputMatch.capabilitySlot`), and two defects of the brick surfaced on the way:
  * a group « auto » (`auto:text-to-music`) was greyed like a model — only bare `auto` was spared;
  * the first pass judged BEFORE the catalogue capabilities arrived and was never replayed: a
    capability slot would have greyed every model at opening and switched the select silently.
Executed in V8 on the SERVED bricks (a `.js` never breaks at Python compile time).
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js'

#: Just enough DOM to run `WamaInputMatch.init` on a select and a setting field.
FAKE_DOM = """
var window = this; var listeners = [];
function Event(type) { this.type = type; }
function CustomEvent(type) { this.type = type; }
function option(value, label) {
  return { value: value, textContent: label || value, dataset: {}, disabled: false, title: '' };
}
var options = [option('auto:text-to-music', 'Auto'), option('composer:musicgen-small', 'MusicGen'),
               option('huggingface:org/Singer', 'Singer')];
var select = { id: 'modelSelect', options: options, value: 'huggingface:org/Singer',
  isConnected: true,
  get selectedOptions() { var v = this.value; return options.filter(function (o) { return o.value === v; }); },
  querySelectorAll: function () { return []; },
  addEventListener: function (t, f) { listeners.push(['select', t, f]); },
  dispatchEvent: function () {} };
var vocals = { id: 'vocalsSelect', value: 'song', selectedOptions: [{ textContent: 'Chanson' }],
  addEventListener: function (t, f) { listeners.push(['vocals', t, f]); } };
var byId = { modelSelect: select, vocalsSelect: vocals };
var document = { getElementById: function (id) { return byId[id] || null; },
                 addEventListener: function () {} };
var caps = {};
var resolveCaps; var capsReady = new Promise(function (r) { resolveCaps = r; });
"""


def _v8(test):
    try:
        from py_mini_racer import MiniRacer
    except ImportError:
        test.skipTest('py_mini_racer absent de ce venv')
    ctx = MiniRacer()
    ctx.eval(FAKE_DOM + (SERVED / 'wama-input-match.js').read_text(encoding='utf-8'))
    return ctx


class ACapabilitySlotGreysTheModelsWithoutItTest(SimpleTestCase):

    def _init(self, ctx):
        ctx.eval("var m = WamaInputMatch.init({ selectId: 'modelSelect', meta: {}, inputLabels: {},"
                 " slots: { vocals: WamaInputMatch.capabilitySlot('vocalsSelect',"
                 "   { capability: 'supports_vocals', values: ['song'], label: 'Voix : chanson' }) },"
                 " capsProvider: function () { return caps; }, capsReady: capsReady });")

    def _state(self, ctx):
        return json.loads(ctx.eval(
            "JSON.stringify(options.map(function (o) { return [o.value, o.disabled, o.title]; }))"))

    def test_nothing_is_greyed_before_the_catalogue_answers(self):
        ctx = _v8(self)
        self._init(ctx)
        self.assertEqual([False, False, False], [d for _, d, _ in self._state(ctx)])
        self.assertEqual('huggingface:org/Singer', ctx.eval('select.value'), 'no silent switch')

    def test_once_the_capabilities_arrive_the_non_singers_are_greyed_with_the_reason(self):
        ctx = _v8(self)
        self._init(ctx)
        ctx.eval("caps = {'huggingface:org/Singer': {supports_vocals: true},"
                 " 'composer:musicgen-small': {}}; resolveCaps(caps);")
        state = {v: (d, t) for v, d, t in self._state(ctx)}
        self.assertTrue(state['composer:musicgen-small'][0])
        self.assertIn('Voix : chanson', state['composer:musicgen-small'][1])
        self.assertFalse(state['huggingface:org/Singer'][0])
        self.assertFalse(state['auto:text-to-music'][0], 'a group auto is the DRAW, never greyed')

    def test_another_value_of_the_setting_greys_nothing(self):
        ctx = _v8(self)
        self._init(ctx)
        ctx.eval("caps = {'huggingface:org/Singer': {supports_vocals: true}}; resolveCaps(caps);")
        ctx.eval("vocals.value = 'instrumental'; m.refresh();")
        self.assertEqual([False, False, False], [d for _, d, _ in self._state(ctx)])

    def test_options_filled_later_are_judged_again(self):
        ctx = _v8(self)
        self._init(ctx)
        ctx.eval("caps = {'huggingface:org/Singer': {supports_vocals: true}}; resolveCaps(caps);")
        ctx.eval("options.push(option('composer:musicgen-medium'));"
                 "listeners.filter(function (l) { return l[0] === 'select' &&"
                 " l[1] === 'wama:options-filled'; }).forEach(function (l) { l[2](); });")
        state = {v: d for v, d, _ in self._state(ctx)}
        self.assertTrue(state['composer:musicgen-medium'])


class TheAutoRuleIsTheServerOneTest(SimpleTestCase):
    """`isAutoValue` is the client twin of `auto_model.is_auto`: two rules « is it the draw? »
    that diverged would grey in the browser what the launch draws."""

    def test_the_two_rules_agree(self):
        from wama.common.utils.auto_model import is_auto
        ctx = _v8(self)
        for value in ('auto', 'auto:text-to-music', 'auto:text-to-audio', 'composer:musicgen-small',
                      'huggingface:m-a-p/YuE2-3B', 'automatic'):
            with self.subTest(value=value):
                self.assertEqual(is_auto(value),
                                 ctx.eval(f"WamaInputMatch.isAutoValue({json.dumps(value)})"))


class TheComposerDeclaresTheSlotTest(SimpleTestCase):
    """The page only DECLARES (INPUT_MODEL_MATCHING §6.7): the slot, the catalogue domain read
    from the schema, and the capabilities' readiness — on the panel and in the ⚙ modal."""

    def test_panel_and_modal_declare_the_vocals_slot_and_wait_for_the_capabilities(self):
        root = Path(settings.BASE_DIR)
        page = (root / 'wama/composer/templates/composer/index.html').read_text(encoding='utf-8')
        modal = (root / 'staticfiles/composer/js/index.js').read_text(encoding='utf-8')
        self.assertIn("capability: 'supports_vocals'", page)
        self.assertIn('with_model_caps=True', page)
        self.assertIn("vocalsSlot('vocalsSelect')", page)
        self.assertIn("vocalsSlot('settingsVocals')", modal)
        for src in (page, modal):
            self.assertIn('capsReady:', src)
