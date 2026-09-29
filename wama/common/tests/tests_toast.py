"""Le toast commun : un message d'ERREUR se lit, se comprend et se RECOPIE.

Constat de Fabien, 2026-09-27, en testant l'aperçu de voix : *« le temps d'affichage de la
pop-up d'erreur est un peu court. Je manque de temps pour copier le texte d'erreur. »* La
brique donnait **3,5 s à tous les types** — une confirmation se lit d'un coup d'œil, un
diagnostic non. Trois réponses, pas une : plus de temps, le survol qui SUSPEND la disparition,
et un clic qui ferme — sans rien ajouter dans le toast, dont le texte est LU par les sondes.

Brique COMMUNE montée par `base.html` : ce qui change ici change dans les dix apps. D'où cette
garde, alors qu'un toast n'a l'air de rien.

Même patron que `media_library/tests/tests_preview_mime.py` : V8 embarqué, la fonction extraite et
exécutée seule (le module entier touche au DOM au chargement).
⚠ `py_mini_racer` n'est installé que dans venv_win : ces tests SKIPPENT sous venv_linux.

⚠ Identifiants en anglais, noms de tests compris ; commentaires et docstrings en français.
"""
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

SOURCE = Path(settings.BASE_DIR) / 'wama/common/static/common/js/wama-app-base.js'
SERVED = Path(settings.BASE_DIR) / 'staticfiles/common/js/wama-app-base.js'

#: DOM minimal : de quoi construire un élément, l'attacher, et OBSERVER les délais posés.
FAKE_DOM = """
var window = this; var timers = []; var cleared = [];
window.getSelection = function () { return { toString: function () { return ''; } }; };
function setTimeout(fn, ms) { timers.push({ fn: fn, ms: ms }); return timers.length; }
function clearTimeout(id) { cleared.push(id); }
function fakeElement(tag) {
  return { tag: tag, style: { cssText: '' }, children: [], listeners: {}, textContent: '',
           className: '', attrs: {},
           setAttribute: function (k, v) { this.attrs[k] = v; },
           addEventListener: function (t, f) { (this.listeners[t] = this.listeners[t] || []).push(f); },
           insertBefore: function (node) { this.children.unshift(node); },
           appendChild: function (node) { this.children.push(node); },
           remove: function () { this.removed = true; },
           get firstChild() { return this.children[0] || null; } };
}
var appended = [];
var document = { createElement: fakeElement,
                 body: { appendChild: function (el) { appended.push(el); } } };
"""


def _extract(src, name):
    match = re.search(r'\n  function ' + name + r'\(.*?\n  }\n', src, re.S)
    return match.group(0) if match else None


class ToastTest(SimpleTestCase):

    def setUp(self):
        try:
            from py_mini_racer import MiniRacer
        except ImportError:
            self.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter la brique')
        src = SOURCE.read_text(encoding='utf-8')
        self.ctx = MiniRacer()
        self.ctx.eval('(function(){' + src + '\n})')            # parse du module ENTIER
        body = _extract(src, 'toast')
        self.assertIsNotNone(body, 'la fonction `toast` a disparu ou changé de forme')
        durations = re.search(r'const TOAST_MS = \{[^}]*\};', src)
        default = re.search(r'const TOAST_DEFAULT_MS = \d+;', src)
        self.assertIsNotNone(durations, 'les durées par type ont disparu')
        self.ctx.eval(FAKE_DOM + durations.group(0) + '\n' + default.group(0) + '\n' + body)

    def _show(self, message, kind):
        self.ctx.eval('appended = []; timers = []; cleared = [];')
        self.ctx.eval(f'toast({message!r}, {kind!r});')
        return self.ctx.eval('timers[timers.length - 1].ms')

    def test_an_error_stays_far_longer_than_a_confirmation(self):
        confirmation = self._show('Enregistré', 'success')
        error = self._show("Cannot set properties of null (setting 'src')", 'error')
        self.assertEqual(3500, confirmation)
        self.assertGreaterEqual(error, 15000)
        self.assertGreater(error, confirmation * 4)

    def test_an_error_can_be_closed_and_its_text_selected(self):
        message = "Erreur lors de l'assemblage"
        self._show(message, 'error')
        self.assertIn('user-select:text', self.ctx.eval('appended[0].style.cssText'),
                      "le texte d'une erreur est fait pour être copié")
        self.assertEqual('Cliquer pour fermer', self.ctx.eval('appended[0].attrs.title'),
                         'un message qui DURE doit pouvoir se fermer')

    def test_the_text_of_a_toast_is_the_message_and_nothing_else(self):
        """⚠ Garde née d'un défaut évité de justesse (2026-09-27, alerte de Fabien : « tu
        touches du commun »). Une croix « × » ajoutée comme premier enfant aurait été lue par
        les sondes qui comparent le texte d'un toast (`ui_smoke.py:1319` et `:2233`) : elles
        auraient vu « ×Erreur… ». *Un ajout au DOM d'une brique commune change ce que lisent
        tous ses observateurs, pas seulement ce que voit l'utilisateur.*"""
        message = "Cannot set properties of null (setting 'src')"
        self._show(message, 'error')
        self.assertEqual(message, self.ctx.eval('appended[0].textContent'))
        self.assertEqual(0, self.ctx.eval('appended[0].children.length'),
                         'aucun nœud ajouté dans le toast : son texte est LU ailleurs')

    def test_hovering_an_error_suspends_its_removal(self):
        """On ne retire pas un texte sous les yeux de qui est en train de le sélectionner."""
        self._show('Erreur', 'error')
        before = self.ctx.eval('cleared.length')
        self.ctx.eval("appended[0].listeners['mouseenter'][0]();")
        self.assertGreater(self.ctx.eval('cleared.length'), before)

    def test_a_confirmation_stays_bare(self):
        """Contre-épreuve : le cas COURANT ne gagne ni croix ni écouteurs — un toast de
        succès qui demanderait un geste serait une régression d'usage."""
        self._show('Enregistré', 'success')
        self.assertEqual(0, self.ctx.eval('appended[0].children.length'))
        self.assertEqual(0, self.ctx.eval("Object.keys(appended[0].listeners).length"))

    def test_the_served_copy_matches_its_source(self):
        if SERVED.exists():
            self.assertEqual(SOURCE.read_bytes(), SERVED.read_bytes())
