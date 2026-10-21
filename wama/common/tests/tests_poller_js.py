"""La boucle d'interrogation commune (`WamaApp.Poller`, wama-app-base.js) — 2026-10-13.

Constat de Fabien dans l'Imager : *« j'ai essayé d'ouvrir des modales, des previews, rien ne
s'affichait et tout s'est ouvert d'un coup, superposé »*. Mesuré au journal d'accès : jusqu'à
295 requêtes/minute d'un seul navigateur, `/imager/global-progress/` toujours PAR PAIRES. Les
boucles étaient des `setInterval` qui relançaient sans attendre la réponse précédente, y compris
en onglet caché : serveur lent → requêtes empilées → les ~6 connexions du navigateur vers l'hôte
occupées → les clics attendent derrière, puis tout arrive ensemble.

Ce que ces tests tiennent, pour toutes les boucles qui passent par la brique :
  * jamais deux requêtes du même poller en vol — le tour suivant part APRÈS la réponse ;
  * onglet caché → aucune requête ; au retour au premier plan, un tour immédiat ;
  * un arrêt décidé DANS `onData` n'est pas annulé par la reprogrammation ;
  * deux barres de file sur le MÊME endpoint (images + vidéos de l'Imager) → UN appel par tour ;
  * aucune app n'interroge le serveur par son propre `setInterval` (garde générique, sans V8).

V8 vient de `py_mini_racer` (AGENTS.md §JS) — absent de venv_linux : les tests qui l'exécutent
y SKIPPENT.
"""
import importlib.util
import json
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from wama.common.tests.tests_cap_from_js import FAKE_DOM

HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
JS = Path(settings.BASE_DIR) / 'wama' / 'common' / 'static' / 'common' / 'js'

#: Horloge et réseau sous contrôle du test : `tick()` déclenche LE tour en attente, `answer()`
#: rend la plus ancienne requête en vol (vraies promesses : les microtâches s'écoulent entre
#: deux `eval`).
HARNESS = """
document.cookie = ''; var navigator = {}; var localStorage =
  {getItem: function () { return null; }, setItem: function () {}};
var listeners = {};
document.addEventListener = function (t, f) { (listeners[t] = listeners[t] || []).push(f); };
document.hidden = false;
function fire(t) { (listeners[t] || []).forEach(function (f) { f(); }); }
var timers = [];
function setTimeout(fn) { timers.push(fn); return timers.length; }
function clearTimeout(id) { if (id) timers[id - 1] = null; }
function tick() { var fns = timers.filter(Boolean); timers = timers.map(function () { return null; });
                  fns.forEach(function (f) { f(); }); }
var calls = [], inflight = [];
function fetch(url) {
  calls.push(url);
  return new Promise(function (resolve) { inflight.push(resolve); });
}
function answer(body) {
  var r = inflight.shift();
  r({ok: true, json: function () { return body; }});
}
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class PollerLoopTest(SimpleTestCase):

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(FAKE_DOM + HARNESS)
        self.v8.eval((JS / 'wama-app-base.js').read_text(encoding='utf-8'))
        self.v8.eval('var WamaApp = window.WamaApp; var seen = [];')

    def _js(self, expr):
        return json.loads(self.v8.eval(f'JSON.stringify({expr})'))

    def test_a_turn_never_starts_while_the_previous_answer_is_awaited(self):
        self.v8.eval("""var p = new WamaApp.Poller({urlTemplate: '/x/0/', immediate: true,
                          onData: function (id, d) { seen.push(d.n); }});
                        p.start(7);""")
        self.assertEqual(['/x/7/'], self._js('calls'))
        self.v8.eval('tick(); tick(); tick();')           # serveur lent : pas de 2ᵉ requête
        self.assertEqual(1, self._js('calls.length'), 'a slow server must not pile requests up')
        self.v8.eval("p.poke(7); fire('visibilitychange');")   # ni un filtre changé, ni un retour
        self.assertEqual(1, self._js('calls.length'), 'a turn in flight is never doubled')
        self.v8.eval('answer({n: 1});')
        self.assertEqual([1], self._js('seen'))
        self.v8.eval('tick();')                           # le tour suivant part après la réponse
        self.assertEqual(2, self._js('calls.length'))

    def test_a_hidden_tab_asks_nothing_and_catches_up_when_shown_again(self):
        self.v8.eval("""var p = new WamaApp.Poller({urlTemplate: '/x/0/', immediate: true,
                          onData: function (id, d) { seen.push(d.n); }});
                        p.start(1); answer({n: 1});""")
        self.v8.eval('document.hidden = true; tick(); tick();')
        self.assertEqual(1, self._js('calls.length'), 'a hidden tab must not poll')
        self.v8.eval("document.hidden = false; fire('visibilitychange');")
        self.assertEqual(2, self._js('calls.length'), 'coming back asks at once, without waiting')

    def test_a_poller_started_again_after_stopping_still_catches_up_when_shown(self):
        """Un Poller ne reste inscrit au retour de l'onglet que tant qu'il suit un id (2026-10-13 :
        ceux créés par geste — suivi de l'inspecteur, conversion rapide — y restaient jusqu'au
        rechargement). Relancé après `stopAll`, il doit s'y réinscrire."""
        self.v8.eval("""var p = new WamaApp.Poller({urlTemplate: '/x/0/', immediate: true});
                        p.start(1); answer({}); p.stopAll();
                        p.start(2); answer({});""")
        self.v8.eval('document.hidden = true; tick();')
        self.assertEqual(2, self._js('calls.length'))
        self.v8.eval("document.hidden = false; fire('visibilitychange');")
        self.assertEqual(['/x/1/', '/x/2/', '/x/2/'], self._js('calls'),
                         'a poller restarted after stopAll was forgotten by the tab return')

    def test_a_request_turn_follows_the_same_rules_and_awaits_its_on_data(self):
        """`request` (2026-10-13, cam_analyzer) : un tour qui n'est pas un GET JSON — un POST, un
        chargeur qui rend lui-même. Mêmes règles : jamais deux en vol, et un `onData` asynchrone
        est attendu avant le tour suivant (le rendu d'un tour ne chevauche pas le suivant)."""
        self.v8.eval("""
            var asked = 0, renders = [], finishRender = null;
            var p = new WamaApp.Poller({immediate: true,
                request: function (id) { asked++; return fetch('/custom/' + id + '/')
                                           .then(function (r) { return r.json(); }); },
                onData: function (id, d) { renders.push(d.n);
                    return new Promise(function (r) { finishRender = r; }); }});
            p.start(5);""")
        self.assertEqual(['/custom/5/'], self._js('calls'))
        self.v8.eval('answer({n: 1});')
        self.v8.eval('tick(); tick();')
        self.assertEqual(1, self._js('asked'), 'the next turn left before onData had finished')
        self.v8.eval('finishRender();')
        self.v8.eval('tick();')
        self.assertEqual(2, self._js('asked'))
        self.assertEqual([1], self._js('renders'))

    def test_a_stop_decided_in_on_data_is_final(self):
        self.v8.eval("""var p = new WamaApp.Poller({urlTemplate: '/x/0/', immediate: true,
                          onData: function (id) { p.stop(id); }});
                        p.start(3); answer({});""")
        self.v8.eval('tick(); tick();')
        self.assertEqual(1, self._js('calls.length'))
        self.assertFalse(self._js('p.has(3)'))

    def test_a_stop_with_the_id_as_text_stops_a_poll_started_with_a_number(self):
        """2026-10-21 : le Reader lance son suivi avec `parseInt(card.dataset.id)`, la brique de
        suppression l'arrête avec `btn.dataset.id` — une card supprimée restait interrogée (404)
        jusqu'à `maxFails`. Mesuré par le contrôle « autre élément » du geste ⚙ (`ui_smoke`)."""
        self.v8.eval("""var p = new WamaApp.Poller({urlTemplate: '/x/0/', immediate: true});
                        p.start(1769); answer({});
                        p.start('1769');""")
        self.assertEqual(1, self._js('calls.length'), 'the same element, followed twice')
        self.v8.eval("p.stop('1769'); tick(); tick();")
        self.assertEqual(1, self._js('calls.length'), 'the deleted card is still polled')
        self.assertFalse(self._js('p.has(1769)'))

    def test_two_queue_bars_on_one_endpoint_share_one_call(self):
        self.v8.eval("""
            function bar() { return {style: {}, classList: classList(), textContent: ''}; }
            var els = {globalProgressBar: bar(), globalProgressStats: bar(),
                       videoGlobalProgressBar: bar(), videoGlobalProgressStats: bar()};
            document.getElementById = function (id) { return els[id] || null; };
            var CustomEvent = function (t) { this.type = t; };
            document.dispatchEvent = function () {};
        """)
        self.v8.eval((JS / 'wama-global-progress.js').read_text(encoding='utf-8'))
        self.v8.eval("""
            window.WamaGlobalProgress.init({url: '/imager/global-progress/', dataKey: 'image'});
            window.WamaGlobalProgress.init({url: '/imager/global-progress/', dataKey: 'video',
                bar: 'videoGlobalProgressBar', stats: 'videoGlobalProgressStats'});
            answer({image: {total: 4, done: 1}, video: {total: 2, done: 2}});
        """)
        self.assertEqual(['/imager/global-progress/'], self._js('calls'),
                         'the images bar and the videos bar read ONE answer')
        self.assertEqual(['25%', '100%'], self._js(
            '[els.globalProgressBar.style.width, els.videoGlobalProgressBar.style.width]'))
        self.v8.eval('tick();')
        self.assertEqual(2, self._js('calls.length'), 'one call per turn, not one per bar')

    def test_each_bar_makes_the_download_button_of_its_own_queue_ready(self):
        """⬇ « Télécharger tout » (2026-10-17) : prêt dès qu'un élément de SA file est terminé,
        compté par le serveur. Une barre de domaine nomme son ⬇ (`download:`), la barre par défaut
        prend les autres — une file d'images terminée ne rend pas prêt le ⬇ de la file vidéo."""
        self.v8.eval("""
            function bar() { return {style: {}, classList: classList(), textContent: ''}; }
            function dl(id, tag) {
                var attrs = {};
                return {id: id, tagName: tag, disabled: true, classList: classList(),
                        setAttribute: function (k, v) { attrs[k] = v; },
                        removeAttribute: function (k) { delete attrs[k]; }, attrs: attrs};
            }
            var els = {globalProgressBar: bar(), videoGlobalProgressBar: bar(),
                       imgDl: dl('imgDl', 'A'), vidDl: dl('vidDl', 'BUTTON')};
            els.imgDl.classList.add('disabled');
            document.getElementById = function (id) { return els[id] || null; };
            document.querySelectorAll = function (sel) {
                return sel === '[data-queue-download]' ? [els.imgDl, els.vidDl] : []; };
            var CustomEvent = function (t) { this.type = t; };
            document.dispatchEvent = function () {};
        """)
        self.v8.eval((JS / 'wama-global-progress.js').read_text(encoding='utf-8'))
        self.v8.eval("""
            window.WamaGlobalProgress.init({url: '/g/', dataKey: 'image'});
            window.WamaGlobalProgress.init({url: '/g/', dataKey: 'video',
                bar: 'videoGlobalProgressBar', download: 'vidDl'});
            answer({image: {total: 3, done: 1}, video: {total: 2, done: 0}});
        """)
        state = ('[els.imgDl.classList.contains("disabled"), els.imgDl.attrs["aria-disabled"] || null,'
                 ' els.vidDl.disabled, els.vidDl.classList.contains("disabled")]')
        self.assertEqual([False, None, True, True], self._js(state),
                         'the images queue has a result, the videos queue has none')
        self.v8.eval("tick(); answer({image: {total: 0, done: 0}, video: {total: 2, done: 2}});")
        self.assertEqual([True, 'true', False, False], self._js(state),
                         'the readiness follows each new answer, queue by queue')


class EveryPollingLoopIsTheCommonOneTest(SimpleTestCase):
    """2026-10-13 — douze apps et pages interrogeaient le serveur par un `setInterval` local
    (avatarizer, describer, anonymizer, composer, synthesizer, enhancer ×2, converter, studio,
    reader, gestionnaire de fichiers, model manager), plus le cam_analyzer (statut, passes,
    RTMaps, battements du Live) trouvé par cette garde même : portés sur `WamaApp.Poller`. Ce qui reste
    de `setInterval` dans le code des apps est DÉCLARÉ ici, boucle par boucle, avec sa raison —
    aucune n'interroge le serveur en boucle rapide. Une boucle nouvelle fait rougir : soit elle
    passe par la brique, soit elle se déclare ici en disant pourquoi elle n'en relève pas.
    Les jumelles du bac à sable (copies gitignorées, jamais corrigées à la main) sont exclues."""

    #: `chemin relatif: (nombre, raison)` — le compte ne peut que descendre.
    DECLARED = {
        'wama/common/static/common/js/wama-app-base.js':
            (1, 'notifications toutes les 60 s ; continuent en onglet caché pour le son'),
        'wama/common/static/common/js/wama-assistant-chat.js':
            (1, 'compte à rebours affiché, aucune requête'),
        'wama/common/static/common/js/wama-assistant-voice.js':
            (1, "attente du silence de l'avatar, aucune requête"),
        'wama/common/static/common/js/wama-card-menu.js':
            (1, "battement d'un verrou (60 s) : doit continuer en onglet caché"),
        'wama/common/static/common/js/wama-eta.js':
            (1, 'rendu local des ETA de lot, aucune requête'),
        'wama/common/static/common/js/wama-schedule.js':
            (1, 'place dans la file toutes les 15 s, déjà muette en onglet caché'),
        'wama/common/static/common/js/library-add.js':
            (1, "chronomètre d'enregistrement micro, aucune requête"),
        # La page de correction du transcriber, devenue surface le 2026-10-21 : sa boucle est
        # passée au transport commun. ⚠ L'ancienne raison disait « aucune requête » : faux pour
        # celle-ci, qui interroge — mais seulement pendant qu'un mode d'écriture est choisi.
        'wama/common/static/common/js/wama-transport.js':
            (1, "modes d'écriture : pose le curseur que suit la boucle serveur `playhead_follow` et "
                "lit ses résultats chaque seconde, SEULEMENT tant qu'un mode est choisi"),
        'wama/static/presentation/wama-presentation-3d.js':
            (1, 'visite animée de la présentation, aucune requête'),
        'wama_lab/cam_analyzer/static/cam_analyzer/js/index.js':
            (1, 'lecture vidéo à rebours (currentTime décrémenté), aucune requête'),
        'wama_lab/face_analyzer/templates/face_analyzer/realtime.html':
            (1, "compteur d'images par seconde affiché, aucune requête"),
    }

    def test_no_app_polls_with_a_local_interval(self):
        import re
        from collections import Counter
        from wama.common.sandbox import sandbox_labels
        base = Path(settings.BASE_DIR)
        twins = set(sandbox_labels())
        found = Counter()
        for root in (base / 'wama', base / 'wama_lab', base / 'wama_data'):
            for path in list(root.rglob('*.js')) + list(root.rglob('templates/**/*.html')):
                parts = set(path.parts)
                if 'vendors' in parts or twins & parts or path.name.endswith('.min.js') \
                        or 'staticfiles' in parts:
                    continue
                rel = path.relative_to(base).as_posix()
                if rel.startswith('wama/static/js/'):
                    continue                       # bibliothèques tierces copiées
                code = re.sub(r'^\s*//.*$', '', path.read_text(encoding='utf-8', errors='replace'),
                              flags=re.M)
                n = len(re.findall(r'\bsetInterval\(', code))
                if n:
                    found[rel] = n
        unexpected = {f: n for f, n in found.items()
                      if n > self.DECLARED.get(f, (0, ''))[0]}
        self.assertEqual({}, unexpected,
                         'boucle `setInterval` non déclarée : passer par `WamaApp.Poller` '
                         '(wama-app-base.js), ou la déclarer ici avec sa raison')
        stale = {f for f, (n, _r) in self.DECLARED.items() if found.get(f, 0) < n}
        self.assertEqual(set(), stale, 'une boucle déclarée a disparu : baisser son compte')


#: Faux DOM pour `wama-schedule.js` : une file, une card, des changements simulés, les relectures
#: de `/common/schedule/active/` comptées.
SCHEDULE_DOM = r"""
var window = {};
function Node(classes, attrs, children) {
  this.nodeType = 1; this.classes = classes || []; this.attrs = attrs || {}; this.children = children || [];
  var self = this;
  this.classList = { contains: function (c) { return self.classes.indexOf(c) !== -1; } };
}
Node.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
Node.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
Node.prototype.appendChild = function (n) { this.children.push(n); return n; };
Node.prototype.remove = function () {};
Node.prototype.matches = function (sel) {
  if (sel === '.wama-card[data-id]') return this.classList.contains('wama-card') && 'data-id' in this.attrs;
  if (sel === '[data-schedule-tool]') return 'data-schedule-tool' in this.attrs;
  if (sel === '[data-schedule-url]') return 'data-schedule-url' in this.attrs;
  if (sel.charAt(0) === '.' && sel.indexOf(' ') === -1) return this.classList.contains(sel.slice(1));
  return false;
};
Node.prototype.all = function () {
  var out = [];
  this.children.forEach(function (c) { if (c.nodeType === 1) { out.push(c); out = out.concat(c.all()); } });
  return out;
};
Node.prototype.querySelectorAll = function (sel) { return this.all().filter(function (n) { return n.matches(sel); }); };
Node.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
var card = new Node(['wama-card'], {'data-id': '5'}, [new Node(['wcv3-sec--state'])]);
var queue = new Node([], {'data-schedule-tool': 'start_describer', 'data-schedule-url': '/common/schedule/'}, [card]);
var root = new Node([], {}, [queue]);
var document = {
  readyState: 'complete', hidden: false, cookie: '',
  querySelectorAll: function (s) { return root.querySelectorAll(s); },
  querySelector: function (s) { return root.querySelector(s); },
  addEventListener: function () {},
  createElement: function () { return new Node([]); },
};
var timers = [];
function setTimeout(fn) { timers.push(fn); return timers.length; }
function clearTimeout(id) { if (id) timers[id - 1] = null; }
function setInterval() { return 0; }
function tick() { var fns = timers.filter(Boolean); timers = timers.map(function () { return null; });
                  fns.forEach(function (f) { f(); }); }
var reads = 0;
function fetch() { reads++; return Promise.resolve({ok: true, json: function () { return {actions: [], queue: []}; }}); }
var observers = [];
var MutationObserver = window.MutationObserver = function (cb) { this.cb = cb; observers.push(this); };
MutationObserver.prototype.observe = function () {};
function mutate(records) { observers.forEach(function (o) { o.cb(records); }); }
function text() { return {nodeType: 3}; }
"""


@skipUnless(HAS_V8, 'py_mini_racer absent de ce venv')
class ScheduleChipsRereadOnlyWhatMattersTest(SimpleTestCase):
    """`wama-schedule.js` relit `/common/schedule/active/` quand la file CHANGE — mais seulement ce
    qui touche aux programmations (2026-10-13, relevé à la revérification demandée par Fabien) :
    tout nœud ajouté comptait, texte compris, et une card en cours faisait relire la file à chaque
    tour de son suivi (13 lectures en 16 s sur le Transcriber).
    Contre-épreuves faites : la version d'avant relit sur un pourcentage ; une version qui reposait
    la pastille AVANT de demander la relecture ne relisait plus rien (son drapeau bloquait)."""

    def setUp(self):
        from py_mini_racer import MiniRacer
        self.v8 = MiniRacer()
        self.v8.eval(SCHEDULE_DOM)
        self.v8.eval((JS / 'wama-schedule.js').read_text(encoding='utf-8'))
        self._settle()

    def _settle(self):
        # Un tour de minuterie par `eval` : la réponse de `fetch` se règle ENTRE deux `eval`, puis
        # le drapeau `decorating` retombe au tour suivant (piège du harnais, vécu en l'écrivant).
        for _ in range(4):
            self.v8.eval('tick();')

    def _reads_after(self, records):
        before = self.v8.eval('reads')
        self.v8.eval(f'mutate({records});')
        self._settle()
        return self.v8.eval('reads') - before

    def test_a_progress_that_moves_rereads_nothing(self):
        self.assertEqual(1, self.v8.eval('reads'), 'the page reads the schedule once on load')
        self.assertEqual(0, self._reads_after('[{addedNodes: [text()], removedNodes: [text()]}]'))
        self.assertEqual(0, self._reads_after("[{addedNodes: [new Node(['progress-text'])], removedNodes: []}]"))

    def test_a_card_that_arrives_rereads_the_schedule(self):
        self.assertEqual(1, self._reads_after(
            "[{addedNodes: [new Node(['wama-card'], {'data-id': '9'})], removedNodes: []}]"))

    def test_a_chip_lost_by_a_redrawn_section_rereads_the_schedule(self):
        self.assertEqual(1, self._reads_after(
            "[{addedNodes: [new Node(['wcv3-sec--state'])], removedNodes: "
            "[new Node(['wcv3-sec--state'], {}, [new Node(['wama-schedule-chip'])])]}]"))
