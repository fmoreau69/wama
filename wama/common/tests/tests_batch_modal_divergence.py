"""La ⚙ d'un LOT n'écrase pas ce que personne n'a choisi (`MODES_QUEUE_UX §5ter`, 2026-11-03).

Vécu le soir même : changer la qualité d'un lot de 12 morceaux a remis la durée du premier sur les
douze. Le trou était mesuré depuis le 18/10 : une modale reposte TOUTES ses valeurs, y compris
celles que ses filles ne partagent pas. Le volet qui inspecte une card mère faisait de même, sur un
seul curseur touché.

Le geste : ce que les filles partagent s'affiche ; le reste est TENU — `WamaParams.read` ne le rend
pas — jusqu'à ce qu'un GESTE le rende. Vérifié sur la brique SERVIE, avec V8 (`py_mini_racer`, venv_win).
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

ROOT = Path(settings.BASE_DIR)
SERVED = ROOT / 'staticfiles'

#: Une modale sans navigateur : des champs nommés, une ligne par champ qui écoute les évènements.
FAKE_MODAL = """
function field(name, type, value) {
  var listeners = {};
  var row = {listeners: listeners, classList: {add: function () {}, remove: function () {}},
             addEventListener: function (t, f) { listeners[t] = f; },
             querySelector: function () { return row.note; },
             querySelectorAll: function () { return [el]; },
             note: {textContent: ''}};
  var el = {type: type || 'text', value: value, dataset: {}, tagName: 'INPUT', row: row,
            getAttribute: function (k) { return k === 'name' ? name : null; },
            closest: function () { return row; }, addEventListener: function () {},
            dispatchEvent: function () {}};
  return el;
}
var fields = {duration: field('duration', 'range', '210'), quality: field('quality', 'text', 'web'),
              model: field('model', 'text', 'auto'), media_type: field('media_type', 'hidden', 'audio')};
var host = {
  addEventListener: function () {},
  querySelector: function (sel) {
    var m = /\\[name="([^"]+)"/.exec(sel);
    return (m && fields[m[1]]) || null;
  },
  querySelectorAll: function (sel) {
    var all = Object.keys(fields).map(function (k) { return fields[k]; });
    if (sel === '[data-unset]') return all.filter(function (f) { return f.dataset.unset; });
    return sel === '[name],[data-param]' ? all : [];
  },
};
var SCHEMA = [{name: 'duration', contexts: ['batch']}, {name: 'quality', contexts: ['batch']},
              {name: 'model'}, {name: 'media_type', type: 'hidden'},
              {name: 'prompt', contexts: ['item']}];
var seenNames = null, sharedByDaughters = {quality: 'max', model: ''};
window.WamaInspector = {sharedGearValues: function (group, names) {
  seenNames = names; return JSON.parse(JSON.stringify(sharedByDaughters)); }};
var GROUP = {};
"""


def _v8(test):
    try:
        from py_mini_racer import MiniRacer
    except ImportError:
        test.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter les briques')
    ctx = MiniRacer()
    ctx.eval("var window = this; var document = {addEventListener: function () {},"
             " querySelectorAll: function () { return []; }, getElementById: function () { return null; },"
             " readyState: 'complete', cookie: ''}; var CSS = {escape: function (s) { return s; }};"
             " function Event(t, o) { this.type = t; } function CustomEvent(t, o) { this.type = t; }")
    ctx.eval((SERVED / 'common/js/wama-params.js').read_text(encoding='utf-8'))
    ctx.eval(FAKE_MODAL)
    return ctx


class BatchModalTest(SimpleTestCase):

    def _read(self, ctx):
        return json.loads(ctx.eval('JSON.stringify(WamaParams.read(host))'))

    def _open(self):
        ctx = _v8(self)
        ctx.eval('WamaParams.fillFromBatch(host, GROUP, SCHEMA);')
        return ctx

    def test_a_setting_the_daughters_do_not_share_is_not_posted(self):
        """LE défaut : la durée diverge, on règle la qualité, la durée ne part pas."""
        posted = self._read(self._open())
        self.assertNotIn('duration', posted)
        self.assertEqual('max', posted['quality'], 'ce qu\'elles partagent est affiché et part')

    def test_it_says_why(self):
        ctx = self._open()
        self.assertIn('commune', ctx.eval('fields.duration.row.note.textContent'))

    def test_a_shared_empty_value_is_not_a_decision(self):
        self.assertNotIn('model', self._read(self._open()))

    def test_a_carrier_always_leaves(self):
        """`media_type` n'est pas un réglage : le serveur en a besoin pour lire le lot."""
        self.assertEqual('audio', self._read(self._open()).get('media_type'))

    def test_only_what_a_batch_can_set_is_asked_of_the_daughters(self):
        ctx = self._open()
        self.assertEqual(['duration', 'quality', 'model'], json.loads(ctx.eval('JSON.stringify(seenNames)')))

    def test_a_gesture_on_the_setting_posts_it_for_the_whole_lot(self):
        ctx = self._open()
        ctx.eval("fields.duration.value = '300'; fields.duration.row.listeners.input({isTrusted: true});")
        self.assertEqual('300', self._read(ctx).get('duration'))
        self.assertEqual('', ctx.eval('fields.duration.row.note.textContent'))

    def test_a_fill_by_code_does_not_post_it(self):
        """Choisir un modèle recale la borne de durée, par code : ce n'est pas une décision."""
        ctx = self._open()
        ctx.eval("fields.duration.value = '30'; fields.duration.row.listeners.input({isTrusted: false});")
        self.assertNotIn('duration', self._read(ctx))

    def test_a_profile_or_a_reset_posts_what_it_sets(self):
        """Modèle événementiel (ROADMAP §23.2quater) : un geste global écrase, filles comprises."""
        ctx = self._open()
        ctx.eval("WamaParams.apply(host, {duration: 120});")
        self.assertEqual('120', str(self._read(ctx).get('duration')))

    def test_reopening_on_another_lot_starts_afresh(self):
        ctx = self._open()
        ctx.eval("sharedByDaughters = {duration: '60', quality: 'max', model: 'm'};"
                 "WamaParams.fillFromBatch(host, GROUP, SCHEMA);")
        self.assertEqual('60', str(self._read(ctx).get('duration')))

    def test_a_port_holding_a_lot_survives_the_release_of_the_batch_holds(self):
        """Deux raisons, deux vies : inspecter un lot n'efface pas ce que le port a décidé."""
        ctx = _v8(self)
        ctx.eval("fields.duration.dataset.unset = 'input'; WamaParams.releaseFields(host, 'batch');")
        self.assertNotIn('duration', self._read(ctx))


class ThePanelSpeaksForTheLotTest(SimpleTestCase):
    """Le volet qui inspecte une card mère reposte tout à chaque curseur touché (`autoSave`)."""

    def test_selecting_a_batch_holds_what_its_daughters_do_not_share(self):
        src = (SERVED / 'common/js/wama-inspector.js').read_text(encoding='utf-8')
        body = src[src.index('function selectBatch(bid)'):src.index('function deselect()')]
        self.assertLess(body.index('panel.apply('), body.index('panel.holdDivergences(group)'),
                        'tenir APRÈS avoir rempli : le remplissage émet des évènements')

    def test_inspecting_anything_else_releases_them(self):
        src = (SERVED / 'common/js/wama-inspector.js').read_text(encoding='utf-8')
        for start, end in (('function selectItem(id, el)', 'function selectBatch(bid)'),
                           ('function deselect()', 'function save()')):
            with self.subTest(start=start):
                self.assertIn('panel.releaseHolds()', src[src.index(start):src.index(end)])

    def test_the_panel_reader_skips_a_held_field(self):
        src = (SERVED / 'common/js/wama-inspector.js').read_text(encoding='utf-8')
        reader = src[src.index('const panel = cfg.panel || {'):src.index('holdDivergences: function (group)')]
        self.assertIn('!el.dataset.unset', reader)
        self.assertIn('!r.dataset.unset', reader)
