"""The matching the SERVER read, wired once — `WamaInputMatch.fromCardMatch` (2026-11-09).

A generated app page and the Studio's entry modal both wired `input_match.card_match` by hand: the
select of `match.field` rendered under the panel, and the card ports the server judges, taken by
their brick (`WamaInputSlots.filePorts`). Two writings of one gesture (ROUTE §11 #41) — now one
function of the brick, which both call with what is theirs (`keep`, `isProvided`, `onPort`, `unless`).
Executed in V8 on the SERVED brick (a `.js` never breaks at Python compile time).
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js'

FAKE_DOM = """
var window = this;
function Event(type) { this.type = type; }
function noop() {}
function option(value) { return { value: value, textContent: value, dataset: {}, disabled: false, title: '' }; }
var options = [option('auto'), option('reads:image'), option('reads:text')];
var select = { id: 'appModel', options: options, value: 'reads:image', isConnected: true,
  get selectedOptions() { var v = this.value; return options.filter(function (o) { return o.value === v; }); },
  querySelectorAll: function () { return []; }, addEventListener: noop, dispatchEvent: noop };
function fileInput(id) { return { id: id, type: 'file', files: [], dataset: {}, addEventListener: noop }; }
var imageInput = fileInput('imageInput'), lotInput = fileInput('lotInput');
var byId = { appModel: select, imageInput: imageInput, lotInput: lotInput };
var document = { getElementById: function (id) { return byId[id] || null; }, addEventListener: noop };
var row = { querySelector: function (sel) { return sel === 'select' ? select : null; } };
var host = { querySelector: function (sel) { return sel === '[data-param-row="model"]' ? row : null; } };
var card = {};
window.WamaInputSlots = { filePorts: function (c) { return c === card ? [
  { id: 'work_image', inputId: 'imageInput', zoneId: 'imageZone' },
  { id: 'lot', inputId: 'lotInput', zoneId: 'lotZone' }] : []; } };
var MATCH = { field: 'model', ports: ['work_image'], labels: { work_image: 'Image' },
              meta: { 'reads:image': { inputs_optional: ['work_image'] }, 'reads:text': {} } };
"""


def _v8(test):
    try:
        from py_mini_racer import MiniRacer
    except ImportError:
        test.skipTest('py_mini_racer absent de ce venv')
    ctx = MiniRacer()
    ctx.eval(FAKE_DOM + (SERVED / 'wama-input-match.js').read_text(encoding='utf-8'))
    return ctx


def _greyed(ctx):
    return {o['value']: o['disabled'] for o in json.loads(ctx.eval("m.refresh(); JSON.stringify(options)"))}


class TheServerReadMatchingIsWiredByTheBrickTest(SimpleTestCase):

    def test_a_file_on_a_judged_port_greys_the_model_that_does_not_take_it(self):
        ctx = _v8(self)
        ctx.eval("var m = WamaInputMatch.fromCardMatch(card, host, MATCH, {});")
        self.assertTrue(ctx.eval("m.select === select"), 'the instance carries the select it wired')
        ctx.eval("imageInput.files = [{ name: 'photo.png' }];")
        self.assertEqual({'auto': False, 'reads:image': False, 'reads:text': True}, _greyed(ctx))

    def test_a_port_the_server_does_not_judge_is_not_a_slot(self):
        """Counter-test: a file on the batch port greys nothing — only `match.ports` are judged."""
        ctx = _v8(self)
        ctx.eval("var m = WamaInputMatch.fromCardMatch(card, host, MATCH, {});"
                 "lotInput.files = [{ name: 'lot.csv' }];")
        self.assertEqual({'auto': False, 'reads:image': False, 'reads:text': False}, _greyed(ctx))

    def test_the_caller_keeps_its_ports_and_says_what_is_provided(self):
        ctx = _v8(self)
        ctx.eval("var seen = []; var m = WamaInputMatch.fromCardMatch(card, host, MATCH, {"
                 " keep: function (p) { return p.id === 'work_image'; },"
                 " isProvided: function (p, input) { return p.id === 'work_image' && input === imageInput; },"
                 " onPort: function (p) { seen.push(p.id); } });")
        self.assertEqual('["work_image"]', ctx.eval('JSON.stringify(seen)'))
        self.assertTrue(_greyed(ctx)['reads:text'], 'provided by the caller, no file needed')

    def test_nothing_to_match_wires_nothing(self):
        ctx = _v8(self)
        for call in ("WamaInputMatch.fromCardMatch(card, host, { ports: ['work_image'] }, {})",
                     "WamaInputMatch.fromCardMatch(card, host, { field: 'other', ports: ['work_image'] }, {})",
                     "WamaInputMatch.fromCardMatch(card, host, { field: 'model', ports: ['lyrics'] }, {})",
                     "WamaInputMatch.fromCardMatch(card, host, MATCH, { keep: function () { return false; } })",
                     "WamaInputMatch.fromCardMatch(card, host, MATCH, { unless: function (s) { return s === select; } })",
                     "WamaInputMatch.fromCardMatch(null, host, MATCH, {})"):
            with self.subTest(call=call):
                self.assertTrue(ctx.eval(f'{call} === null'))
