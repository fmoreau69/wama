"""PLUSIEURS FICHIERS SUR UN PORT D'UNE CARD « ATTACHE » = UN LOT (2026-11-03, signalé par Fabien).

La règle est celle de `CARD_DESIGN §11.11 G` : plusieurs fichiers de travail déposés d'un coup font
un lot, une card mère et ses filles. Elle ne tenait que sur les cards dont le dépôt CRÉE. Sur une
card qui JOINT (composer, avatarizer, imager), deux défauts se suivaient :
  * `WamaImport` posait les fichiers un par un dans le port, chacun remplaçant le précédent ;
  * `WamaApp.addToQueue` ne postait que le premier de l'input — le sélecteur de fichiers, lui,
    y mettait bien les N, que la card affichait, pour n'en créer qu'un.

Ce qui se vérifie ici, sur les briques SERVIES, avec V8 (`AGENTS.md` §JS). ⚠ `py_mini_racer` n'est
installé que dans venv_win : ces tests-là SKIPPENT sous venv_linux. Le contrat de câblage, lui,
tourne partout.
"""
import json
import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase
from django.urls import reverse

ROOT = Path(settings.BASE_DIR)
SERVED = ROOT / 'staticfiles'

#: Un navigateur minimal : inputs de port, `DataTransfer`, évènements observés.
FAKE_ENV = """
var window = this; var changes = []; var toasts = [];
var elements = {};
function DataTransfer() { var list = []; this.items = { add: function (f) { list.push(f); } }; this.files = list; }
function CustomEvent(type, init) { this.type = type; this.detail = (init || {}).detail; }
function Event(type) { this.type = type; }
function FormData() { this.entries = []; }
FormData.prototype.append = function (k, v) { this.entries.push([k, (v && v.name) ? 'FILE:' + v.name : v]); };
FormData.prototype.set = FormData.prototype.append;
FormData.prototype.has = function (k) { return this.entries.some(function (e) { return e[0] === k; }); };
function el(id, accept, multiple) { return elements[id] = { id: id, dataset: {}, files: [], multiple: !!multiple,
  value: '', getAttribute: function (k) { return k === 'accept' ? (accept || '') : null; },
  addEventListener: function () {}, querySelector: function () { return null; },
  querySelectorAll: function () { return []; },
  dispatchEvent: function (e) { changes.push(id); } }; }
var document = { readyState: 'complete', getElementById: function (id) { return elements[id] || null; },
                 addEventListener: function () {}, querySelectorAll: function () { return []; },
                 querySelector: function () { return null; } };
window.location = { reloaded: 0, reload: function () { this.reloaded += 1; } };
window.setTimeout = function (f) { f(); };
"""


def _mini_racer(test):
    try:
        from py_mini_racer import MiniRacer
    except ImportError:
        test.skipTest('py_mini_racer absent de ce venv : pas de V8 pour exécuter les briques')
    return MiniRacer()


def _function(src, name):
    """Le corps d'une fonction de `wama-app-base.js`, au niveau de son module."""
    body = re.search(r'\n  function ' + name + r'\(.*?\n  }\n', src, re.S)
    if body is None:
        raise AssertionError(f'`{name}` a disparu ou changé de forme')
    return body.group(0)


class DepositOnAPortTest(SimpleTestCase):
    """`WamaImport`, mode attache : ce que le port TIENT après le dépôt."""

    def _route(self, zone_multiple=True):
        ctx = _mini_racer(self)
        ctx.eval(FAKE_ENV)
        # La brique de l'envoi fournit `designateInto` / `injectFiles` réels à celle du dépôt.
        base = (SERVED / 'common/js/wama-app-base.js').read_text(encoding='utf-8')
        ctx.eval("function toast(m, l) { toasts.push([l, m]); }"
                 + ''.join(_function(base, n) for n in ('keptByPort', 'designateInto', 'designationOf',
                                                        'designationsOf', 'clearDesignation', 'inputEntries',
                                                        'injectFiles'))
                 + "window.WamaApp = {designateInto: designateInto, injectFiles: injectFiles,"
                   " keptByPort: keptByPort, designationsOf: designationsOf, inputEntries: inputEntries,"
                   " toast: toast};")
        ctx.eval((SERVED / 'common/js/wama-import.js').read_text(encoding='utf-8'))
        ctx.eval(f"el('zone'); el('work', 'audio/*', {'true' if zone_multiple else 'false'}); el('score', '.abc');"
                 "var api = WamaImport({csrfToken: 't', dropZoneId: 'zone', fileInputId: 'work',"
                 " attach: ['work', 'score']});")
        return ctx

    @staticmethod
    def _held(ctx, port='work'):
        return json.loads(ctx.eval(f"JSON.stringify(WamaApp.inputEntries(elements.{port})"
                                   ".map(function (e) { return e.name; }))"))

    AUDIOS = "[{name: 'a.mp3', type: 'audio/mpeg'}, {name: 'b.mp3', type: 'audio/mpeg'}, {name: 'c.mp3', type: 'audio/mpeg'}]"

    def test_every_dropped_file_stays_on_the_port(self):
        """LE défaut signalé : de trois fichiers glissés, seul le dernier restait."""
        ctx = self._route()
        ctx.eval(f'api.handleFiles({self.AUDIOS});')
        self.assertEqual(['a.mp3', 'b.mp3', 'c.mp3'], self._held(ctx))

    def test_the_port_is_told_once_not_once_per_file(self):
        ctx = self._route()
        ctx.eval(f'api.handleFiles({self.AUDIOS});')
        self.assertEqual(['work'], json.loads(ctx.eval('JSON.stringify(changes)')))

    def test_every_file_dragged_from_the_tree_stays_on_the_port(self):
        """Le même geste depuis l'arbre de WAMA : des DÉSIGNATIONS, et le même défaut."""
        ctx = self._route()
        ctx.eval("api.handleDesignations([{path: 'users/1/a.mp3', type: 'audio/mpeg'},"
                 " {path: 'users/1/b.mp3', type: 'audio/mpeg'}]);")
        self.assertEqual(['a.mp3', 'b.mp3'], self._held(ctx))

    def test_a_single_file_port_keeps_the_first_and_names_the_others(self):
        """Contre-épreuve : un port sans `multiple` tient UN fichier, et ne perd rien en silence."""
        ctx = self._route()
        ctx.eval("api.handleFiles([{name: 'x.abc'}, {name: 'y.abc'}]);")
        self.assertEqual(['x.abc'], self._held(ctx, 'score'))
        toasts = json.loads(ctx.eval('JSON.stringify(toasts)'))
        self.assertEqual(1, len(toasts))
        self.assertIn('y.abc', toasts[0][1])

    def test_files_of_two_natures_each_reach_their_port(self):
        ctx = self._route()
        ctx.eval("api.handleFiles([{name: 'a.mp3', type: 'audio/mpeg'}, {name: 'x.abc'},"
                 " {name: 'b.mp3', type: 'audio/mpeg'}]);")
        self.assertEqual(['a.mp3', 'b.mp3'], self._held(ctx))
        self.assertEqual(['x.abc'], self._held(ctx, 'score'))


class JoinPagesBoxInTheZoneTest(SimpleTestCase):
    """The « un seul document » box of `WamaImport` (`joinPages`, 2026-11-10), seen in the browser
    after the restart : set NEXT to the zone, it became one more tile of the flex row and crushed
    the zone to 79 px. It lives IN the zone now, and its label ticks it without opening the picker."""

    FAKE_DOM = """
    var window = this; var picked = 0; var handlers = {};
    function node(tag, id) { return { tagName: tag.toUpperCase(), id: id || '', dataset: {}, children: [],
      parent: null, files: [], getAttribute: function () { return null; },
      appendChild: function (c) { c.parent = this; this.children.push(c); return c; },
      addEventListener: function (t, f) { handlers[this.id + ':' + t] = f; },
      closest: function (sel) { var tags = sel.split(',').map(function (s) { return s.trim().toUpperCase(); });
        for (var n = this; n; n = n.parent) { if (tags.indexOf(n.tagName) >= 0) return n; } return null; },
      click: function () { if (this.id === 'work') picked += 1; } }; }
    var elements = { zone: node('div', 'zone'), work: node('input', 'work') };
    function find(n, id) { if (n.id === id) return n;
      for (var i = 0; i < n.children.length; i++) { var f = find(n.children[i], id); if (f) return f; } return null; }
    var document = { readyState: 'complete', createElement: function (t) { return node(t); },
      getElementById: function (id) { return elements[id] || find(elements.zone, id); },
      addEventListener: function () {}, querySelectorAll: function () { return []; },
      querySelector: function () { return null; } };
    """

    def _zone(self):
        ctx = _mini_racer(self)
        ctx.eval(self.FAKE_DOM)
        ctx.eval((SERVED / 'common/js/wama-import.js').read_text(encoding='utf-8'))
        ctx.eval("WamaImport({csrfToken: 't', dropZoneId: 'zone', fileInputId: 'work', joinPages: true});"
                 "var box = document.getElementById('zoneJoinPages');")
        return ctx

    def test_the_box_is_in_the_zone_and_its_label_does_not_open_the_picker(self):
        ctx = self._zone()
        self.assertTrue(ctx.eval("box.parent.parent === elements.zone"), 'inside the zone, not a tile')
        ctx.eval("handlers['zone:click']({target: box.parent.children[1]});")
        self.assertEqual(0, ctx.eval('picked'), 'the label ticks the box, the picker stays shut')

    def test_a_click_on_the_zone_still_opens_the_picker(self):
        """Counter-proof : the guard lets the labels through, not the zone."""
        ctx = self._zone()
        ctx.eval("handlers['zone:click']({target: elements.zone.appendChild(node('span'))});")
        self.assertEqual(1, ctx.eval('picked'))


class AddToQueueTest(SimpleTestCase):
    """`WamaApp.addToQueue` : N fichiers sur un port, N créations puis UN regroupement."""

    #: Les réponses de la vue d'ajout, dans l'ordre ; le reste du module est bouchonné.
    STUBS = """
    var global = window; var calls = []; var nextId = 40; var refuse = {};
    function toast(m, l) { toasts.push([l, m]); }
    function csrfToken() { return 't'; }
    function jsonOrExplain(r) { return r.json(); }
    function csrfFetch(url, token, init) {
      var fields = init.body.entries; calls.push([url, fields]);
      var file = fields.filter(function (e) { return e[0] === 'work_audio'; })[0];
      var name = file ? file[1] : '';
      if (refuse[name]) return Promise.resolve({ok: false, status: 400,
        json: function () { return Promise.resolve({error: refuse[name]}); }});
      return Promise.resolve({ok: true, status: 200, json: function () {
        return Promise.resolve(url === '/add/' ? {id: nextId++} : {consolidated: true}); }});
    }
    window.WamaParams = {read: function () { return {duration: '90', model: 'm'}; }};
    """

    def _submit(self, setup, opts=''):
        ctx = _mini_racer(self)
        ctx.eval(FAKE_ENV + self.STUBS)
        base = (SERVED / 'common/js/wama-app-base.js').read_text(encoding='utf-8')
        ctx.eval(re.search(r"\n  const DESIGNATION_SUFFIX = '[^']+';", base).group(0)
                 + ''.join(_function(base, n) for n in ('designationOf', 'designationsOf', 'clearDesignation',
                                                        'inputEntries', 'appendFile', 'appendInput', 'addToQueue')))
        ctx.eval("el('work', 'audio/*', true); el('score', '.abc'); el('prompt'); el('host');"
                 "elements.prompt.value = 'jazz';"
                 "elements.prompt.dataset = {};" + setup)
        ctx.eval("var submit = addToQueue({url: '/add/', csrfToken: 't', prompt: {inputId: 'prompt', field: 'prompt'},"
                 " paramsHostId: 'host', ports: [{inputId: 'work', field: 'work_audio'},"
                 " {inputId: 'score', field: 'work_score'}], onAdded: function () { window.added = true; }"
                 + opts + "}); submit();")
        return ctx

    LOT = ", consolidateUrl: '/lot/'"
    TWO_FILES = "elements.work.files = [{name: 'a.mp3'}, {name: 'b.mp3'}];"

    @staticmethod
    def _calls(ctx):
        return json.loads(ctx.eval('JSON.stringify(calls)'))

    def test_two_files_make_two_elements_grouped_into_a_lot(self):
        ctx = self._submit(self.TWO_FILES, self.LOT)
        calls = self._calls(ctx)
        self.assertEqual(['/add/', '/add/', '/lot/'], [c[0] for c in calls])
        files = [[e[1] for e in c[1] if e[0] == 'work_audio'] for c in calls[:2]]
        self.assertEqual([['FILE:a.mp3'], ['FILE:b.mp3']], files, 'un fichier par élément, dans l’ordre')
        self.assertEqual([['ids', 40], ['ids', 41]], calls[2][1])
        self.assertEqual(1, ctx.eval('window.location.reloaded'), 'la card mère est rendue par le serveur')

    def test_the_prompt_and_settings_are_shared_by_the_lot(self):
        calls = self._calls(self._submit(self.TWO_FILES, self.LOT))
        for call in calls[:2]:
            fields = dict(map(tuple, call[1]))
            self.assertEqual('jazz', fields['prompt'])
            self.assertEqual('m', fields['model'])

    def test_a_lot_of_designations_posts_each_path(self):
        ctx = self._submit("elements.work.dataset = {designatedPath: 'users/1/a.mp3', designatedName: 'a.mp3',"
                           " designatedRest: JSON.stringify([{path: 'users/1/b.mp3', name: 'b.mp3'}])};", self.LOT)
        calls = self._calls(ctx)
        self.assertEqual(['/add/', '/add/', '/lot/'], [c[0] for c in calls])
        self.assertEqual(['users/1/a.mp3', 'users/1/b.mp3'],
                         [dict(map(tuple, c[1]))['work_audio__designated'] for c in calls[:2]])

    def test_a_refused_file_does_not_stop_the_others_and_is_named(self):
        ctx = self._submit("refuse['FILE:a.mp3'] = 'trop long';"
                           "elements.work.files = [{name: 'a.mp3'}, {name: 'b.mp3'}, {name: 'c.mp3'}];", self.LOT)
        calls = self._calls(ctx)
        self.assertEqual(['/add/', '/add/', '/add/', '/lot/'], [c[0] for c in calls])
        self.assertEqual(2, len(calls[3][1]), 'le lot regroupe ce qui a été créé')
        errors = [m for level, m in json.loads(ctx.eval('JSON.stringify(toasts)')) if level == 'error']
        self.assertEqual(1, len(errors))
        self.assertIn('a.mp3', errors[0])
        self.assertIn('trop long', errors[0])

    def test_everything_refused_keeps_the_page_and_the_files(self):
        ctx = self._submit("refuse['FILE:a.mp3'] = refuse['FILE:b.mp3'] = 'non';" + self.TWO_FILES, self.LOT)
        self.assertEqual(0, ctx.eval('window.location.reloaded'))
        self.assertNotIn('/lot/', [c[0] for c in self._calls(ctx)])

    def test_a_view_that_returns_no_id_is_told_not_grouped_silently(self):
        """Vécu sur l'imager (`generation_id`) : `undefined` partait au regroupement, qui répondait
        « rien à regrouper » — N cards isolées, sans un mot. Sans identifiant, on le DIT."""
        ctx = self._submit("csrfFetch = function (url, token, init) { calls.push([url, init.body.entries]);"
                           " return Promise.resolve({ok: true, status: 200, json: function () {"
                           " return Promise.resolve({generation_id: 3}); }}); };" + self.TWO_FILES, self.LOT)
        self.assertEqual(['/add/', '/add/'], [c[0] for c in self._calls(ctx)], 'aucun regroupement à vide')
        warnings = [m for level, m in json.loads(ctx.eval('JSON.stringify(toasts)')) if level == 'warning']
        self.assertEqual(1, len(warnings))
        self.assertIn('lot', warnings[0])
        self.assertEqual(1, ctx.eval('window.location.reloaded'), 'les éléments existent : la page les montre')

    def test_a_single_file_is_still_one_element_without_a_lot(self):
        """Contre-épreuve : le geste ordinaire ne change pas — sa card s'insère, sans rechargement."""
        ctx = self._submit("elements.work.files = [{name: 'a.mp3'}];", self.LOT)
        self.assertEqual(['/add/'], [c[0] for c in self._calls(ctx)])
        self.assertTrue(ctx.eval('window.added === true'))
        self.assertEqual(0, ctx.eval('window.location.reloaded'))


class WiringTest(SimpleTestCase):
    """Une app dont la card joint et porte un port `multiple` DÉCLARE sa route de regroupement :
    sans elle, le dépôt de N fichiers ferait N cards isolées, sans un mot."""

    ADOPTERS = {'composer': 'wama/composer/static/composer/js/index.js',
                'avatarizer': 'wama/avatarizer/static/avatarizer/js/index.js',
                'imager': 'wama/imager/static/imager/js/input_card.js'}

    def test_each_app_passes_its_consolidate_route(self):
        for app, rel in self.ADOPTERS.items():
            with self.subTest(app=app):
                src = (ROOT / rel).read_text(encoding='utf-8')
                call = src[src.index('WamaApp.addToQueue({'):]
                self.assertRegex(call[:call.index('onAdded') if 'onAdded' in call else 1500], r'consolidateUrl:')
                self.assertTrue(reverse(f'{app}:consolidate'))

    def test_every_success_of_the_imager_add_view_returns_the_common_id(self):
        """Ses cinq branches répondent chacune à la main : une seule sans `id` et son mode ne
        forme plus de lot."""
        src = (ROOT / 'wama/imager/views.py').read_text(encoding='utf-8')
        answers = re.findall(r"'success': True,\s*(?:'id': generation\.id,[^\n]*\s*)?'generation_id'", src)
        self.assertEqual(5, len(answers), 'le nombre de branches a changé : relire ce test')
        self.assertTrue(all("'id': generation.id" in a for a in answers), answers)

    def test_the_generator_emits_it_too(self):
        from wama.common.manifests.codegen import templates_gen
        src = Path(templates_gen.__file__).read_text(encoding='utf-8')
        call = src[src.index('WamaApp.addToQueue({{'):]
        self.assertIn('consolidateUrl:', call[:call.index('}});')])

    TOUCHED = ('common/js/wama-import.js', 'common/js/wama-app-base.js', 'common/js/wama-input-slots.js',
               'common/js/wama-params.js', 'composer/js/index.js', 'avatarizer/js/index.js',
               'imager/js/input_card.js', 'studio/js/wama-studio-entry.js', 'filemanager/js/filemanager.js')

    def test_the_served_copies_match_their_sources(self):
        for rel in self.TOUCHED:
            source = ROOT / 'wama' / rel.split('/')[0] / 'static' / rel
            with self.subTest(module=rel):
                self.assertEqual(source.read_bytes(), (SERVED / rel).read_bytes())

    def test_the_touched_modules_parse(self):
        ctx = _mini_racer(self)
        for rel in self.TOUCHED:
            with self.subTest(module=rel):
                ctx.eval('(function(){' + (SERVED / rel).read_text(encoding='utf-8') + '\n})')

    def test_the_studio_keeps_every_designation_of_its_main_port(self):
        """La modale du Studio retient ce que le port tient, pas sa seule première désignation."""
        src = (ROOT / 'wama/studio/static/studio/js/wama-studio-entry.js').read_text(encoding='utf-8')
        self.assertIn('WamaApp.designationsOf(input)', src)
        self.assertNotIn('WamaApp.designationOf(input) : null', src)
