"""La DÉSIGNATION côté navigateur (2026-09-28, étape 1 de la card v4) : la tuile Médiathèque et
le glisser depuis l'arbre POINTENT un fichier au lieu de le re-téléverser.

Ce qui se vérifie ici, sur les briques SERVIES, avec V8 (un `.js` ne casse jamais à la
compilation Python — `AGENTS.md` §JS) :
  * les modules touchés se parsent ;
  * `WamaImport` poste `<champ>__designated` (le chemin) et JAMAIS le fichier, ne teste pas une
    désignation comme lot, remet une désignation au PORT en mode attache, et retrouve la voie
    d'import d'une card par l'id de sa zone ou de son input ;
  * `WamaApp.appendFile` / `appendInput` postent fichier OU désignation ;
  * le suffixe est le même en JS et en Python (`media_paths.DESIGNATION_SUFFIX`).

Même patron que `tests_toast.py`. ⚠ `py_mini_racer` n'est installé que dans venv_win : ces
tests SKIPPENT sous venv_linux.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.utils.media_paths import DESIGNATION_SUFFIX

ROOT = Path(settings.BASE_DIR)
SERVED = ROOT / 'staticfiles'
TOUCHED = ['common/js/wama-import.js', 'common/js/wama-app-base.js', 'common/js/media-picker.js',
           'common/js/wama-input-slots.js', 'common/js/wama-input-match.js',
           'imager/js/input_card.js', 'avatarizer/js/index.js', 'composer/js/index.js',
           'filemanager/js/filemanager.js']

#: De quoi instancier `WamaImport` sans navigateur : éléments, FormData et XHR OBSERVÉS.
FAKE_ENV = """
var window = this; var posted = []; var attached = []; var batchTested = [];
function FormData() { this.entries = []; }
FormData.prototype.append = function (k, v) { this.entries.push([k, (v && v.name) ? 'FILE:' + v.name : v]); };
function XMLHttpRequest() { this.upload = { addEventListener: function () {} }; }
XMLHttpRequest.prototype.open = function (m, u) { this.url = u; };
XMLHttpRequest.prototype.setRequestHeader = function () {};
XMLHttpRequest.prototype.send = function (fd) {
  posted.push(fd.entries); this.status = 200; this.statusText = 'OK';
  this.responseText = '{"id": 7}'; this.onload(); };
var elements = {};
function el(id, accept) { return elements[id] = { id: id, dataset: {}, files: [],
  getAttribute: function (k) { return k === 'accept' ? (accept || '') : null; },
  addEventListener: function () {}, querySelector: function () { return null; },
  dispatchEvent: function () {} }; }
var document = { readyState: 'complete', getElementById: function (id) { return elements[id] || null; },
                 addEventListener: function () {} };
window.WamaApp = { designateInto: function (input, f) { attached.push([input.id, f.designation]); return true; },
                   injectFiles: function () { return true; } };
window.location = { reload: function () {} };
"""


def _mini_racer(test):
    try:
        from py_mini_racer import MiniRacer
    except ImportError:
        test.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter les briques')
    return MiniRacer()


class DesignationJsTest(SimpleTestCase):

    def test_the_touched_modules_parse(self):
        ctx = _mini_racer(self)
        for rel in TOUCHED:
            with self.subTest(module=rel):
                src = (SERVED / rel).read_text(encoding='utf-8')
                ctx.eval('(function(){' + src + '\n})')          # parse sans exécuter

    def test_the_served_copies_match_their_sources(self):
        for rel in TOUCHED:
            app = rel.split('/')[0]
            source = ROOT / 'wama' / app / 'static' / rel
            with self.subTest(module=rel):
                self.assertEqual(source.read_bytes(), (SERVED / rel).read_bytes())

    def _import(self, extra_cfg=''):
        ctx = _mini_racer(self)
        src = (SERVED / 'common/js/wama-import.js').read_text(encoding='utf-8')
        ctx.eval(FAKE_ENV + src)
        ctx.eval("el('dz'); el('fi'); el('port', 'audio/*');"
                 "var api = WamaImport({uploadUrl: '/up/', csrfToken: 't', dropZoneId: 'dz',"
                 " fileInputId: 'fi', afterImport: function () {},"
                 " batch: {detectAndHandle: function (f) { batchTested.push(f.name); return false; }}"
                 + extra_cfg + "});")
        return ctx

    def test_a_designation_is_posted_by_path_never_as_a_file(self):
        # Les DEUX portées de lot : `single` (défaut) et `each` (enhancer, synthesizer, imager,
        # composer). Une 1ʳᵉ version ne jouait que la première — la contre-épreuve sur la branche
        # `each` est restée verte : la garde était aveugle à la moitié des apps.
        for scope in ('single', 'each'):
            with self.subTest(batch_scope=scope):
                ctx = self._import(f", batchScope: '{scope}'")
                ctx.eval("api.handleDesignations([{path: 'users/3/temp/talk.wav'}]);")
                posted = json.loads(ctx.eval('JSON.stringify(posted)'))
                self.assertEqual(1, len(posted), 'une requête, à la vue d’upload de la card')
                fields = dict(posted[0])
                self.assertEqual('users/3/temp/talk.wav', fields.get('file' + DESIGNATION_SUFFIX))
                self.assertNotIn('file', fields, 'aucun fichier téléversé pour une désignation')
                self.assertEqual([], json.loads(ctx.eval('JSON.stringify(batchTested)')),
                                 'une désignation n’est jamais testée comme lot (pas de contenu)')

    def test_a_real_file_still_goes_as_a_file(self):
        """Contre-épreuve : le dépôt ordinaire est inchangé."""
        ctx = self._import()
        ctx.eval("api.handleFiles([{name: 'a.wav', type: 'audio/wav', size: 4}]);")
        fields = dict(json.loads(ctx.eval('JSON.stringify(posted)'))[0])
        self.assertEqual('FILE:a.wav', fields.get('file'))
        self.assertNotIn('file' + DESIGNATION_SUFFIX, fields)

    def test_in_attach_mode_a_designation_joins_the_port(self):
        ctx = self._import(", attach: ['port']")
        ctx.eval("api.handleDesignations([{path: 'users/3/temp/melody.wav', type: 'audio/wav'}]);")
        self.assertEqual([['port', 'users/3/temp/melody.wav']],
                         json.loads(ctx.eval('JSON.stringify(attached)')))
        self.assertEqual([], json.loads(ctx.eval('JSON.stringify(posted)')),
                         'en mode attache, rien ne part avant la création')

    def _on_a_card(self, depot):
        """`attach: 'card'` (2026-10-19) sur une card dont la forme d'entrée est `depot` : une
        désignation audio, et ce qui en sort — `[ports qui l'ont reçue, requêtes envoyées]`. Les
        ports se lisent par la brique de la card, chargée comme sur la page."""
        ctx = self._import(", attach: 'card'")
        self._load_slots(ctx)
        ctx.eval("var card = fakeCard('" + depot + "', [fakePane('melody', 'file', 'port')]);"
                 "elements.dz.closest = function () { return card; };"
                 "api.handleDesignations([{path: 'users/3/temp/melody.wav', type: 'audio/wav'}]);")
        return json.loads(ctx.eval('JSON.stringify([attached, posted.length])'))

    #: Une card v4 sans navigateur : des panes qui répondent à `getAttribute`, une card qui ne rend
    #: que ceux que le sélecteur des ports FICHIER retient (le live et le lot n'en sont pas).
    FAKE_CARD = """
    function fakePane(port, kind, input, id) { var a = {'data-port-pane': port, 'data-port-kind': kind,
      'data-port-input': input || null}; return {id: id || '', getAttribute: function (k) { return k in a ? a[k] : null; }}; }
    function fakeCard(depot, panes) { var card = {
      getAttribute: function (k) { return k === 'data-wama-depot' ? depot : null; },
      querySelectorAll: function (sel) { return sel === '[data-port-pane][data-port-kind="file"]'
        ? panes.filter(function (p) { return p.getAttribute('data-port-kind') === 'file'; }) : []; } };
      card.closest = function () { return card; }; return card; }
    """

    def _load_slots(self, ctx):
        """La brique de la card (`wama-input-slots.js`), SERVIE, sur le faux document."""
        ctx.eval("document.querySelectorAll = function () { return []; };" + self.FAKE_CARD)
        ctx.eval((SERVED / 'common/js/wama-input-slots.js').read_text(encoding='utf-8'))

    def test_the_card_brick_lists_its_file_ports_in_order(self):
        """`WamaInputSlots.filePorts` (2026-10-20) : un port par onglet FICHIER qui porte un input,
        dans l'ordre de la card — depuis un élément de la card, la card, ou `document` ; rien hors
        d'une card."""
        ctx = _mini_racer(self)
        ctx.eval(FAKE_ENV)
        self._load_slots(ctx)
        got = json.loads(ctx.eval(
            "var card = fakeCard('attache', [fakePane('live', 'live'), fakePane('prompt_file', 'file', 'pf', 'pfPane'),"
            " fakePane('work_audio', 'file', 'wa'), fakePane('lot', 'lot'), fakePane('orphan', 'file')]);"
            "var inside = {closest: function () { return card; }};"
            "var outside = {closest: function () { return null; }};"
            "var page = {querySelectorAll: card.querySelectorAll};"
            "JSON.stringify([WamaInputSlots.filePorts(inside), WamaInputSlots.filePorts(card),"
            " WamaInputSlots.filePorts(page), WamaInputSlots.filePorts(outside), WamaInputSlots.filePorts(null)]);"))
        expected = [{'id': 'prompt_file', 'inputId': 'pf', 'zoneId': 'pfPane'},
                    {'id': 'work_audio', 'inputId': 'wa'}]
        self.assertEqual([expected, expected, expected, [], []], got)

    def test_the_card_ports_are_read_by_the_card_brick_only(self):
        """Une seule lecture des onglets de la card hors de sa brique : `filePorts`. L'envoi
        (`addToQueue`), le dépôt qui se joint (`WamaImport`), le réglage lié à un port
        (`wama-params`), l'avatarizer et le composer relevaient chacun les panes (2026-10-20).
        Jumelles du bac à sable exclues : elles se régénèrent."""
        from wama.common.app_registry import APP_CATALOG
        twins = {app for app, spec in APP_CATALOG.items()
                 if spec.get('generated_from') or spec.get('sandbox')}
        offenders = []
        for base in ('wama', 'wama_lab', 'wama_data'):
            for path in (ROOT / base).rglob('*'):
                if (path.suffix not in ('.js', '.html') or 'node_modules' in path.parts
                        or twins & set(path.parts)):
                    continue
                if path.name == 'wama-input-slots.js':
                    continue
                text = path.read_text(encoding='utf-8', errors='replace')
                if re.search(r"querySelector(All)?\(\s*['\"][^'\"]*\[data-port-pane", text):
                    offenders.append(str(path.relative_to(ROOT)))
        self.assertEqual([], offenders)

    def test_on_an_attach_card_the_file_joins_the_port_the_card_offers(self):
        attached, posted = self._on_a_card('attache')
        self.assertEqual([['port', 'users/3/temp/melody.wav']], attached)
        self.assertEqual(0, posted, 'rien ne part avant « Ajouter »')

    def test_on_a_card_whose_drop_creates_the_same_import_sends_it(self):
        """Contre-épreuve : la même instance, sur une card « cree », envoie à la vue d'upload."""
        attached, posted = self._on_a_card('cree')
        self.assertEqual([], attached)
        self.assertEqual(1, posted)

    def test_a_card_finds_its_import_route_by_either_id(self):
        ctx = self._import()
        self.assertTrue(ctx.eval("WamaImport.forElement('dz') === api && WamaImport.forElement('fi') === api"))
        self.assertTrue(ctx.eval("WamaImport.forElement('nowhere') === null"))

    def test_the_media_picker_is_reachable_from_window(self):
        """Mesuré au navigateur le 2026-09-28 : `const MediaPicker` n'était PAS `window.MediaPicker`
        — la tuile Médiathèque de la v4 et le bouton de `wama-modes.js` sortaient en silence."""
        ctx = _mini_racer(self)
        src = (SERVED / 'common/js/media-picker.js').read_text(encoding='utf-8')
        ctx.eval('var window = this;' + src)
        self.assertTrue(ctx.eval("typeof window.MediaPicker === 'object' && "
                                 "typeof window.MediaPicker.open === 'function'"))

    def test_the_suffix_is_the_same_in_javascript_and_python(self):
        for rel in ('common/js/wama-import.js', 'common/js/wama-app-base.js'):
            src = (SERVED / rel).read_text(encoding='utf-8')
            found = re.findall(r"DESIGNATION_SUFFIX = '([^']+)'", src)
            self.assertEqual([DESIGNATION_SUFFIX], found, rel)

    def test_append_file_and_input_post_a_file_or_a_designation(self):
        ctx = _mini_racer(self)
        src = (SERVED / 'common/js/wama-app-base.js').read_text(encoding='utf-8')
        pieces = [re.search(r"\n  const DESIGNATION_SUFFIX = '[^']+';", src).group(0)]
        for name in ('designationOf', 'appendFile', 'appendInput'):
            body = re.search(r'\n  function ' + name + r'\(.*?\n  }\n', src, re.S)
            self.assertIsNotNone(body, f'`{name}` a disparu ou changé de forme')
            pieces.append(body.group(0))
        ctx.eval('function FormData() { this.e = []; }'
                 'FormData.prototype.append = function (k, v) { this.e.push([k, v.name || v]); };'
                 + ''.join(pieces))
        got = json.loads(ctx.eval(
            "var a = new FormData(); appendFile(a, 'audio_input', {name: 'x.wav'});"
            "var b = new FormData(); appendFile(b, 'audio_input', {name: 'y.wav', designation: 'users/1/temp/y.wav'});"
            "var c = new FormData(); appendInput(c, {dataset: {designatedPath: 'users/1/temp/z.png'}, files: []}, 'reference_image');"
            "var d = new FormData(); var none = appendInput(d, {dataset: {}, files: []}, 'reference_image');"
            "JSON.stringify([a.e, b.e, c.e, d.e, none]);"))
        self.assertEqual([['audio_input', 'x.wav']], got[0])
        self.assertEqual([['audio_input' + DESIGNATION_SUFFIX, 'users/1/temp/y.wav']], got[1])
        self.assertEqual([['reference_image' + DESIGNATION_SUFFIX, 'users/1/temp/z.png']], got[2])
        self.assertEqual([], got[3])
        self.assertFalse(got[4], 'un port vide ne poste rien et le dit')
