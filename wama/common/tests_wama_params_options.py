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
