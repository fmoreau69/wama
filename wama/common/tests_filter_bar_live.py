"""La barre de filtrage COMMUNE sur une liste RE-RENDUE — option « cible vivante ».

Demande de Fabien (2026-09-28) : la barre de recherche/filtrage sur le calendrier, *« aligné sur
le fonctionnement de WAMA, sans rien réinventer »*. Le calendrier redessine ses événements à
chaque changement de vue ; la brique, elle, photographiait ses éléments AU MONTAGE. Une photo
périmée ne filtre pas les éléments dessinés ensuite : le filtre choisi semblait sans effet dès
qu'on changeait de semaine. D'où `data-cible-vivante` + `WamaFilterBar.refresh(barre)`.

Patron de `tests_toast.py` : V8 embarqué, la brique ENTIÈRE exécutée sur un DOM minimal.
⚠ `py_mini_racer` n'est installé que dans venv_win : ces tests SKIPPENT sous venv_linux.
"""
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SOURCE = Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-filter-bar.js'
SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-filter-bar.js'

#: DOM minimal : une barre à UNE facette (`app`), et une liste que le test REMPLACE comme le
#: ferait un composant qui se redessine. `live` pilote l'option étudiée.
FAKE_DOM = """
var window = this;
function setTimeout(fn) { fn(); return 1; }
function clearTimeout() {}
var console = { warn: function () {} };
function classList() {
  var set = {};
  return { toggle: function (c, on) { if (on) { set[c] = true; } else { delete set[c]; } },
           contains: function (c) { return !!set[c]; } };
}
function event(app) {
  return { app: app, classList: classList(),
           getAttribute: function (k) { return k === 'data-f-app' ? this.app : null; },
           textContent: app };
}
var listed = [];
var select = { value: 'all', options: { length: 3 },
               getAttribute: function (k) { return k === 'data-f-facette' ? 'app' : null; },
               addEventListener: function () {} };
var bar = {
  attrs: { 'data-mode': 'client', 'data-cible': '.ev' },
  getAttribute: function (k) { return this.attrs.hasOwnProperty(k) ? this.attrs[k] : null; },
  setAttribute: function (k, v) { this.attrs[k] = v; },
  querySelector: function () { return null; },
  querySelectorAll: function (sel) { return sel === '[data-f-facette]' ? [select] : []; },
  closest: function () { return null; },
  classList: classList()
};
var document = {
  readyState: 'complete',
  querySelector: function () { return null; },
  querySelectorAll: function (sel) {
    if (sel === '[data-wama-filter-bar]') { return [bar]; }
    if (sel === '.ev') { return listed; }
    return [];
  },
  addEventListener: function () {}
};
"""


class LiveTargetFilterTest(SimpleTestCase):

    def _mount(self, live):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        ctx = MiniRacer()
        ctx.eval(FAKE_DOM)
        if live:
            ctx.eval("bar.attrs['data-cible-vivante'] = '1';")
        ctx.eval("select.value = 'imager'; listed = [event('imager'), event('describer')];")
        ctx.eval(SOURCE.read_text(encoding='utf-8'))          # auto-montage sur la barre
        return ctx

    def _redraw_and_refresh(self, ctx):
        """Le composant redessine sa liste (nouveaux éléments), puis rappelle la brique."""
        ctx.eval("listed = [event('describer'), event('imager')];"
                 "WamaFilterBar.refresh(bar);")
        import json
        return json.loads(ctx.eval("JSON.stringify([listed[0].classList.contains('wama-f-hors-filtre'),"
                                   " listed[1].classList.contains('wama-f-hors-filtre')])"))

    def test_elements_drawn_after_mounting_are_filtered(self):
        ctx = self._mount(live=True)
        self.assertEqual(self._redraw_and_refresh(ctx), [True, False],
                         'le « describer » redessiné doit être masqué, « imager » gardé')

    def test_counter_proof_without_the_option_the_snapshot_is_stale(self):
        ctx = self._mount(live=False)
        self.assertEqual(self._redraw_and_refresh(ctx), [False, False],
                         "sans cible vivante, la brique ne voit pas les éléments redessinés : "
                         "c'est le défaut que l'option corrige")

    def test_the_served_copy_is_the_source(self):
        self.assertEqual(SERVED.read_text(encoding='utf-8'), SOURCE.read_text(encoding='utf-8'),
                         'staticfiles/ sert une autre version de la brique')


class CalendarScriptParsesTest(SimpleTestCase):
    """`wama-calendar.js` touche au DOM au chargement : on se limite au PARSE (V8 fait foi)."""

    def test_the_calendar_script_parses_in_v8(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv')
        for base in ('wama/common/static', 'staticfiles'):
            src = (Path(settings.BASE_DIR) / base / 'common/js/wama-calendar.js').read_text(
                encoding='utf-8')
            MiniRacer().eval('(function(){' + src + '\n})')
