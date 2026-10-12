"""Trois pièces de `WamaParams` ajoutées par R1 (ROUTE §10.6 point 3.3bis, 2026-10-12), exercées
dans V8 sur le fichier lui-même :
  • l'UNITÉ d'un champ nombre se lit à côté de la valeur, et un décimal n'a pas de grille ;
  • `media_picker` — désigner un média de la médiathèque — est un renderer COMMUN : il n'existait
    que dans l'inspecteur du Studio, écrit à la main ;
  • GESTE ou REMPLISSAGE : un choix fait dans la fenêtre de la médiathèque est une décision
    (`isGesture`), la recharge des options d'un select n'en est pas une.

Même patron que `tests_wama_params_options` : V8 embarqué (`py_mini_racer`), DOM simulé.
⚠ `py_mini_racer` n'est installé que dans venv_win : ces tests SKIPPENT sous venv_linux.
⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import json
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

JS = Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-params.js'

DOM = """
var window = this; var global = this; var listeners = {};
function CustomEvent(t) { this.type = t; } function Event(t) { this.type = t; }
var field = { value: 'users/1/old.csv', events: [],
              dispatchEvent: function (e) { this.events.push(e); } };
var nameSpan = { textContent: 'old.csv' };
var button = { getAttribute: function () { return 'wp-item-asset_path'; },
               querySelector: function () { return nameSpan; } };
var document = { getElementById: function (id) { return id === 'wp-item-asset_path' ? field : null; },
                 querySelectorAll: function () { return []; },
                 addEventListener: function (t, f) { (listeners[t] = listeners[t] || []).push(f); } };
var MediaPicker = { open: function (o) { MediaPicker.opened = o; } };
function click(target) { (listeners.click || []).forEach(function (f) { f({ target: target }); }); }
function box() { return { innerHTML: '', querySelectorAll: function () { return []; },
                          querySelector: function () { return null; }, addEventListener: function () {} }; }
"""


class WamaParamsFieldsTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        self.ctx = MiniRacer()
        self.ctx.eval(DOM)
        self.ctx.eval(JS.read_text(encoding='utf-8'))

    def _render(self, param, values=None, context='item'):
        return self.ctx.eval(
            "(function(){ var b = box(); WamaParams.render(b, [%s], { context: '%s', values: %s });"
            " return b.innerHTML; })()" % (json.dumps(param), context, json.dumps(values or {})))

    def test_a_number_shows_its_unit_and_a_decimal_has_no_grid(self):
        html = self._render({'name': 'radius_m', 'type': 'number', 'min': 5, 'max': 100,
                             'step': 'any', 'unit': 'm'})
        self.assertIn('step="any"', html)
        self.assertIn('<span class="input-group-text">m</span>', html)

    def test_a_number_without_unit_is_unchanged(self):
        """Contre-épreuve : les 12 champs nombre des apps (aucun ne déclare d'unité) gardent leur
        rendu d'avant."""
        html = self._render({'name': 'resize_w', 'type': 'number', 'min': 0})
        self.assertNotIn('input-group', html)
        self.assertIn('<input type="number"', html)
        self.assertNotIn('step=', html)

    def test_a_media_field_carries_its_path_like_any_field(self):
        html = self._render({'name': 'asset_path', 'type': 'media_picker', 'label': 'Média'},
                            {'asset_path': 'users/1/trace.csv'})
        self.assertIn('<input type="hidden" id="wp-item-asset_path" name="asset_path" '
                      'value="users/1/trace.csv">', html)
        self.assertIn('trace.csv</span>', html)
        self.assertIn('data-media-pick="wp-item-asset_path"', html)

    def test_picking_a_media_designates_it_and_says_it_is_a_decision(self):
        self.ctx.eval("click({ closest: function (s) { return s === '[data-media-pick]' ? button : null; } });")
        self.assertEqual('all', self.ctx.eval('MediaPicker.opened.type'))
        self.assertTrue(self.ctx.eval("typeof MediaPicker.opened.onPick === 'function'"),
                        "désignation (onPick) : l'asset est pointé, jamais téléchargé")
        self.ctx.eval("MediaPicker.opened.onPick({ path: 'users/1/trace.csv', name: 'Trace GPS' });")
        self.assertEqual('users/1/trace.csv', self.ctx.eval('field.value'))
        self.assertEqual('Trace GPS', self.ctx.eval('nameSpan.textContent'))
        self.assertEqual('change', self.ctx.eval('field.events[0].type'))
        self.assertTrue(self.ctx.eval('WamaParams.isGesture(field.events[0])'))

    def test_a_refill_is_not_a_decision(self):
        self.assertFalse(self.ctx.eval("WamaParams.isGesture(new Event('change'))"))
        self.assertTrue(self.ctx.eval("WamaParams.isGesture({ isTrusted: true })"))
        self.assertFalse(self.ctx.eval('WamaParams.isGesture(null)'))
