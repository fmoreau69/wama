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
        'wama/transcriber/static/transcriber/js/edit.js':
            (2, "lecture à rebours et frappe de l'éditeur, aucune requête"),
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
