"""Les options d'un select GÉNÉRÉ par WamaParams — un seul rendu, et un signal quand elles changent.

Deux défauts de la brique commune, mesurés dans V8 sur le fichier servi le 2026-09-22 :
  • le rendu SYNCHRONE et la recharge ASYNCHRONE avaient chacun leur rendu d'option ; le
    synchrone ne lisait pas les options en PAIRE `[valeur, libellé]` (la forme de
    `get_voice_groups`) : trois voix rendaient trois `<option value="">` vides, sans
    `data-language`, jusqu'à ce que la recharge les répare ;
  • la recharge remplaçait les options sans que les filtres de WamaModelCaps ne se rejouent —
    ils ne le font que sur un changement du select de MODÈLE : voix masquées et ⚠ de langue
    perdus quand la recharge arrivait après eux.

Même patron que `common/tests_queue_dnd.py` : V8 embarqué (`py_mini_racer`), DOM simulé.
⚠ `py_mini_racer` n'est installé que dans venv_win : ces tests SKIPPENT sous venv_linux.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

JS_DIR = Path(settings.BASE_DIR) / 'wama/common/static/common/js'
SERVED_DIR = Path(settings.BASE_DIR) / 'staticfiles/common/js'

GROUPS = [
    {"key": "default", "group": "Voix par défaut", "options": [["default", "Voix par défaut"]]},
    {"key": "reference", "group": "Français — Adulte", "options": [["sa_3", "Homme 1"]],
     "attributes": {"sa_3": {"language": "fr"}}},
    {"key": "mine", "group": "Mes voix (clonage)", "options": [["ua_7", "Ma voix"]],
     "attributes": {"ua_7": {"language": "en"}}},
]
PARAM = {"name": "voice_preset", "type": "select", "options_source": "voices", "dom_id": "voice_preset"}
FAKE_DOM = """
var window = this; var global = this; var events = [];
function CustomEvent(t) { this.type = t; } function Event(t) { this.type = t; }
var fakeSelect = { innerHTML: '', value: 'sa_3', parentNode: null,
  options: [{ value: 'sa_3', dataset: {}, textContent: 'Homme 1', selected: true }], _l: {},
  addEventListener: function (t, f) { (this._l[t] = this._l[t] || []).push(f); },
  dispatchEvent: function (e) { events.push(e.type); (this._l[e.type] || []).forEach(function (f) { f(e); }); } };
var fakeModel = { value: 'synthesizer:kokoro', addEventListener: function () {} };
var document = { getElementById: function (id) { return id === 'voice_preset' ? fakeSelect
                                            : id === 'tts_model' ? fakeModel : null; },
                 querySelectorAll: function () { return []; }, addEventListener: function () {} };
var fetched = null;
function fetch() { return Promise.resolve({ json: function () { return Promise.resolve(fetched); } }); }
function box() { return { innerHTML: '', querySelectorAll: function () { return []; },
                          querySelector: function () { return null; }, addEventListener: function () {} }; }
"""
OPTION = re.compile(r'<option value="([^"]*)"[^>]*?(?: data-language="([^"]*)")?>([^<]*)</option>')


class WamaParamsOptionsTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        self.ctx = MiniRacer()
        self.ctx.eval(FAKE_DOM)
        self.ctx.eval((JS_DIR / 'wama-params.js').read_text(encoding='utf-8'))
        self.ctx.eval((JS_DIR / 'wama-model-caps.js').read_text(encoding='utf-8'))
        self.ctx.eval('fetched = %s;' % json.dumps({'groups': GROUPS}))

    def _render(self):
        """Rend le champ par le schéma : markup SYNCHRONE du conteneur, puis la recharge
        asynchrone remplit `fakeSelect` (le `fetch` simulé se résout dans la même évaluation)."""
        return self.ctx.eval(
            "(function(){ var b = box(); WamaParams.render(b, [%s], { context: 'panel',"
            " optionsResolver: function(){ return %s; } }); return b.innerHTML; })()"
            % (json.dumps(PARAM), json.dumps(GROUPS)))

    def test_the_synchronous_render_reads_option_pairs_and_their_attributes(self):
        """Le cas mesuré : trois voix rendaient trois options VIDES."""
        html = self._render()
        self.assertEqual([('default', '', 'Voix par défaut'), ('sa_3', 'fr', 'Homme 1'),
                          ('ua_7', 'en', 'Ma voix')], OPTION.findall(html))
        self.assertEqual(['default', 'reference', 'mine'], re.findall(r'data-group-key="([^"]*)"', html))

    def test_both_render_paths_produce_the_same_options(self):
        sync_html = self._render()
        async_html = self.ctx.eval('fakeSelect.innerHTML')
        self.assertEqual(OPTION.findall(sync_html), OPTION.findall(async_html))
        self.assertIn('data-group-key="mine"', async_html)

    def test_a_refill_announces_itself_and_replays_the_filters(self):
        self.ctx.eval("var replays = 0; WamaModelCaps.init({ modelSelectId: 'tts_model',"
                      " source: 'synthesizer', meta: { 'synthesizer:kokoro': {} },"
                      " filters: [{ selectId: 'voice_preset',"
                      " hideOption: function () { replays++; return false; } }] });")
        before = self.ctx.eval('replays')
        self.ctx.eval('events = [];')
        self._render()
        self.assertEqual('wama:options-filled,change', self.ctx.eval("events.join(',')"))
        self.assertGreater(self.ctx.eval('replays'), before,
                           "une recharge des options doit rejouer les filtres qui les annotent")


class SingleOptionRendererTest(SimpleTestCase):

    def test_wama_params_has_a_single_option_renderer(self):
        """La garde de non-retour : un second `'<option value="'` recréerait deux rendus qui
        divergent — exactement le défaut du 22/09."""
        src = (JS_DIR / 'wama-params.js').read_text(encoding='utf-8')
        self.assertEqual(1, src.count("'<option value=\"'"))

    def test_the_served_copies_match_their_source(self):
        for name in ('wama-params.js', 'wama-model-caps.js'):
            served = SERVED_DIR / name
            if served.exists():
                self.assertEqual((JS_DIR / name).read_bytes(), served.read_bytes(), name)


class RadioNameTest(SimpleTestCase):
    """A radio setting has ONE `name` per button (2026-09-27). The renderer wrote `name="<id>"` and
    then the identity attribute — `name="<param>"` in a modal — and the browser keeps the FIRST:
    a radio setting of a modal was posted as `wp-item-<param>`, which the server never reads
    (measured on the anonymizer's mode; the transcriber worked around it with `radio_name`)."""

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        self.ctx = MiniRacer()
        self.ctx.eval(FAKE_DOM)
        self.ctx.eval((JS_DIR / 'wama-params.js').read_text(encoding='utf-8'))

    def _inputs(self, param, context):
        html = self.ctx.eval("(function(){ var b = box(); WamaParams.render(b, [%s], { context: '%s' });"
                             " return b.innerHTML; })()" % (json.dumps(param), context))
        return re.findall(r'<input[^>]*type="radio"[^>]*>', html)

    def test_a_modal_radio_posts_under_the_setting_name_once(self):
        param = {"name": "target_mode", "type": "radio",
                 "choices": [["classes", "Classes"], ["description", "Description"]]}
        inputs = self._inputs(param, 'item')
        self.assertEqual(2, len(inputs))
        for tag in inputs:
            self.assertEqual(['target_mode'], re.findall(r'\bname="([^"]*)"', tag), tag)

    def test_a_declared_legacy_name_still_wins(self):
        """Counter-check: the transcriber's `radio_name` keeps working, alone."""
        param = {"name": "summary_type", "type": "radio",
                 "radio_name": {"panel": "globalSummaryType", "item": "summary_type_legacy"},
                 "choices": [["structured", "Structuré"], ["meeting", "Réunion"]]}
        for tag in self._inputs(param, 'item'):
            self.assertEqual(['summary_type_legacy'], re.findall(r'\bname="([^"]*)"', tag), tag)
        for tag in self._inputs(param, 'panel'):
            self.assertEqual(['globalSummaryType'], re.findall(r'\bname="([^"]*)"', tag), tag)
            self.assertIn('data-param="summary_type"', tag)


MODE_DOM = """
var window = this; var global = this; var urls = [];
function CustomEvent(t) { this.type = t; } function Event(t) { this.type = t; }
var modelSelect = { innerHTML: '', value: '', selectedIndex: -1, parentNode: null, options: [],
  addEventListener: function () {}, dispatchEvent: function () {} };
var modeField = { type: 'hidden', value: 'description' };
var container = { _l: {},
  querySelectorAll: function (sel) { return sel.indexOf('target_mode') >= 0 ? [modeField] : []; },
  querySelector: function () { return null; },
  addEventListener: function (t, f) { (this._l[t] = this._l[t] || []).push(f); } };
var document = { getElementById: function (id) { return id === 'model_menu' ? modelSelect : null; },
                 querySelectorAll: function () { return []; }, addEventListener: function () {} };
var pending = [];
function fetch(u) { urls.push(u); return new Promise(function (res) { pending.push({ u: u, res: res }); }); }
function answer(i, groups) { pending[i].res({ json: function () { return Promise.resolve({ groups: groups }); } }); }
"""
MODE_PARAM = {"name": "model_to_use", "type": "select", "dom_id": "model_menu", "contexts": ["panel"],
              "options_source": "catalog", "options_query": {"source": "anonymizer", "task": "detect,segment"},
              "options_mode": {"app": "anonymizer", "domain": "image_video", "field": "target_mode"}}


class ModeBoundMenuTest(SimpleTestCase):
    """A catalogue menu bounded by the element's MODE (`Param.options_mode`, 2026-09-27)."""

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        self.ctx = MiniRacer()
        self.ctx.eval(MODE_DOM)
        self.ctx.eval((JS_DIR / 'wama-params.js').read_text(encoding='utf-8'))
        self.ctx.eval("WamaParams.bindOptionSources(container, [%s], 'panel');" % json.dumps(MODE_PARAM))

    def test_the_request_carries_the_mode_read_in_the_same_container(self):
        url = self.ctx.eval('urls[0]')
        self.assertIn('mode=description', url)
        self.assertIn('app=anonymizer', url)
        self.assertIn('domain=image_video', url)

    def test_a_mode_change_reloads_and_a_stale_answer_never_fills_the_menu(self):
        """Measured in the browser: the answer of the FIRST request (other mode) could arrive
        last and put back a list that did not match the mode."""
        self.ctx.eval("modeField.value = 'classes';"
                      "container._l.change.forEach(function (f) { f({ target: { matches: function () { return true; } } }); });")
        self.assertIn('mode=classes', self.ctx.eval('urls[urls.length - 1]'))
        self.ctx.eval("answer(1, [{ options: [['yolo:a.pt', 'A']] }]);")   # the current one
        self.ctx.eval("answer(0, [{ options: [['sam3', 'SAM3']] }]);")     # the stale one, late
        self.assertIn('yolo:a.pt', self.ctx.eval('modelSelect.innerHTML'))
        self.assertNotIn('sam3', self.ctx.eval('modelSelect.innerHTML'))
