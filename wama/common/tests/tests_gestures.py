"""Les GESTES au pointeur — brique `WamaGestures` (ROADMAP §27, étape 3 — 2026-10-16).

Ce qui est gardé, dans l'ordre où cela peut casser :

1. **La brique est montée partout**, avant les pages qui l'adoptent (base.html).
2. **Le glisser HTML5 marche au doigt sans une ligne dans les pages** : appui long, le doigt bouge
   → `dragstart`, `dragenter`/`dragover` sous le doigt, `drop` SEULEMENT si le dernier `dragover`
   l'a accepté, `dragend` ; un balayage rapide reste un défilement ; le clic qui suivrait un
   glisser est retenu.
3. **L'appui long** : relâché sans bouger sur ce qu'on glisse, il ouvre le menu (`contextmenu`) ;
   sur une commande qui porte un `title`, il montre l'infobulle et retient le clic ; un appui
   seulement LENT, qui n'a rien montré, garde son clic ; un champ de saisie garde le sien.
4. **Suivre un pointeur** (`track`) : seuil (un appui qui tremble reste un clic), boutons de souris
   filtrés, pincement à deux doigts qui interrompt le glisser en cours.
5. **Les pages l'adoptent** : studio (nœud, fond, pincement) et éditeur du transcriber (onde,
   mini-carte) n'écrivent plus de mousedown/mousemove/mouseup ; la file et l'ordre des segments
   n'ont AUCUN code tactile à eux.

Les points 2 à 4 se jouent dans V8 avec un faux DOM (la brique, telle que servie). Le rendu réel —
Chromium, événements tactiles de confiance — est mesuré chaque nuit par `common.gestures.touch`.
"""
import importlib.util
import json
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase

BASE = Path(settings.BASE_DIR)
COMMON = BASE / 'wama' / 'common' / 'static' / 'common'
SERVED = BASE / 'staticfiles'
HAS_V8 = importlib.util.find_spec('py_mini_racer') is not None
GESTURES = COMMON / 'js' / 'wama-gestures.js'
STUDIO = BASE / 'wama' / 'studio' / 'static' / 'studio' / 'js' / 'wama-studio.js'
#: L'onde de la page de correction et sa minimap sont la LIGNE DE TEMPS commune, et la liste des
#: segments une brique de surface, depuis le 2026-10-21 (la page `edit.js` est retirée, R166 ; le
#: même jour, l'onde a quitté le transport pour sa propre vue).
EDITOR = COMMON / 'js' / 'wama-timeline.js'
SEGMENTS = COMMON / 'js' / 'surfaces' / 'brick-segment-list.js'
QUEUE = COMMON / 'js' / 'wama-queue-dnd.js'


def _read(path):
    return Path(path).read_text(encoding='utf-8')


class GesturesMountedTest(TestCase):

    def test_base_loads_the_brick_before_the_pages_that_adopt_it(self):
        request = RequestFactory().get('/')
        request.user = AnonymousUser()
        page = render_to_string('base.html', {}, request=request)
        self.assertIn('common/js/wama-gestures.js', page)
        self.assertLess(page.index('common/js/wama-app-base.js'), page.index('common/js/wama-gestures.js'))
        # Les pages chargent leur script dans `extra_js`, à la fin : la brique doit le précéder.
        template = _read(BASE / 'wama' / 'templates' / 'base.html')
        self.assertLess(template.index('common/js/wama-gestures.js'), template.index('{% block extra_js %}'))


#: Un faux DOM minimal : éléments, sélecteurs simples, propagation, minuteries à la main.
V8_HARNESS = r"""
var window = this;
var log = [];
var timers = {}, timerSeq = 0;
function setTimeout(fn) { timers[++timerSeq] = fn; return timerSeq; }
function clearTimeout(id) { delete timers[id]; }
function flushTimers() { var t = timers; timers = {}; Object.keys(t).forEach(function (k) { t[k](); }); }
function requestAnimationFrame() { return 0; }
function cancelAnimationFrame() {}
var navigator = {};
var innerHeight = 1000, pageXOffset = 0, pageYOffset = 0;
function getComputedStyle(e) { return { overflowY: (e.style && e.style.overflowY) || 'visible' }; }

function Event(type, init) {
  init = init || {};
  this.type = type; this.bubbles = !!init.bubbles; this.cancelable = !!init.cancelable;
  this.defaultPrevented = false; this.isTrusted = false;
  var self = this;
  Object.keys(init).forEach(function (k) { if (!(k in self)) self[k] = init[k]; });
}
Event.prototype.preventDefault = function () { if (this.cancelable) this.defaultPrevented = true; };
Event.prototype.stopPropagation = function () { this._stop = true; };
Event.prototype.stopImmediatePropagation = function () { this._stop = true; };
function MouseEvent(type, init) { Event.call(this, type, init); }
MouseEvent.prototype = Object.create(Event.prototype);

function matchSimple(el, s) {
  s = s.trim();
  var not = null, m = s.match(/^(.*):not\((.*)\)$/);
  if (m) { s = m[1]; not = m[2]; }
  var p = s.match(/^([a-z]*)((?:\.[\w-]+)*)((?:\[[^\]]+\])*)$/i);
  if (!p) throw new Error('selector not supported: ' + s);
  if (p[1] && el.tagName !== p[1].toUpperCase()) return false;
  if (!p[2].split('.').filter(Boolean).every(function (c) { return el.classList.contains(c); })) return false;
  var ok = (p[3].match(/\[[^\]]+\]/g) || []).every(function (a) {
    var mm = a.match(/^\[([\w-]+)(?:="([^"]*)")?\]$/);
    return mm[2] === undefined ? el.hasAttribute(mm[1]) : el.getAttribute(mm[1]) === mm[2];
  });
  if (!ok) return false;
  return !(not && matchSimple(el, not));
}

function Node(tag, attrs, parent) {
  var self = this;
  this.tagName = tag.toUpperCase(); this.nodeType = 1; this.attrs = {}; this.children = [];
  this.parentElement = null; this.listeners = {}; this.style = {}; this.textContent = '';
  this.rect = { left: 0, top: 0, width: 100, height: 40, right: 100, bottom: 40 };
  var set = {};
  this.classList = {
    add: function () { for (var i = 0; i < arguments.length; i++) set[arguments[i]] = 1; },
    remove: function () { for (var i = 0; i < arguments.length; i++) delete set[arguments[i]]; },
    contains: function (c) { return !!set[c]; },
    list: function () { return Object.keys(set); },
  };
  Object.keys(attrs || {}).forEach(function (k) {
    if (k === 'class') attrs[k].split(' ').forEach(function (c) { if (c) self.classList.add(c); });
    else self.attrs[k] = String(attrs[k]);
  });
  if (parent) parent.appendChild(this);
}
Node.prototype.appendChild = function (c) { c.parentElement = this; this.children.push(c); return c; };
Node.prototype.removeChild = function (c) { this.children.splice(this.children.indexOf(c), 1); c.parentElement = null; };
Object.defineProperty(Node.prototype, 'parentNode', { get: function () { return this.parentElement; } });
Object.defineProperty(Node.prototype, 'className', {
  get: function () { return this.classList.list().join(' '); },
  set: function (v) { var c = this.classList; c.list().forEach(function (k) { c.remove(k); });
                      String(v).split(' ').forEach(function (k) { if (k) c.add(k); }); },
});
Object.defineProperty(Node.prototype, 'offsetWidth', { get: function () { return this.rect.width; } });
Object.defineProperty(Node.prototype, 'offsetHeight', { get: function () { return this.rect.height; } });
Node.prototype.getAttribute = function (n) { return n in this.attrs ? this.attrs[n] : null; };
Node.prototype.hasAttribute = function (n) { return n in this.attrs; };
Node.prototype.setAttribute = function (n, v) { this.attrs[n] = String(v); };
Node.prototype.removeAttribute = function (n) { delete this.attrs[n]; };
Node.prototype.matches = function (sel) { var el = this; return sel.split(',').some(function (s) { return matchSimple(el, s); }); };
Node.prototype.closest = function (sel) {
  for (var n = this; n && n.nodeType === 1; n = n.parentElement) if (n.matches(sel)) return n;
  return null;
};
Node.prototype.contains = function (o) { for (var n = o; n; n = n.parentElement) if (n === this) return true; return false; };
Node.prototype.querySelectorAll = function (sel) {
  var out = [];
  (function walk(n) { n.children.forEach(function (c) { if (c.matches(sel)) out.push(c); walk(c); }); })(this);
  return out;
};
Node.prototype.cloneNode = function (deep) {
  var c = new Node(this.tagName.toLowerCase(), {});
  c.attrs = JSON.parse(JSON.stringify(this.attrs));
  this.classList.list().forEach(function (k) { c.classList.add(k); });
  c.rect = this.rect;
  if (deep) this.children.forEach(function (k) { c.appendChild(k.cloneNode(true)); });
  return c;
};
Node.prototype.getBoundingClientRect = function () { return this.rect; };
Node.prototype.addEventListener = function (t, fn) { (this.listeners[t] = this.listeners[t] || []).push(fn); };
Node.prototype.removeEventListener = function (t, fn) {
  var l = this.listeners[t] || []; var i = l.indexOf(fn); if (i >= 0) l.splice(i, 1);
};
Node.prototype.dispatchEvent = function (ev) {
  if (!ev.target) ev.target = this;
  var path = [];
  for (var n = this; n; n = n.parentElement) path.push(n);
  // Comme un navigateur : un élément retiré de la page ne fait plus remonter ses événements.
  if (path[path.length - 1] === html) path.push(document, window);
  for (var i = 0; i < path.length && !ev._stop; i++) {
    (path[i].listeners[ev.type] || []).slice().forEach(function (fn) { if (!ev._stop) fn(ev); });
    if (!ev.bubbles) break;
  }
  return !ev.defaultPrevented;
};
window.listeners = {};
window.addEventListener = Node.prototype.addEventListener;
window.removeEventListener = Node.prototype.removeEventListener;

var html = new Node('html'), body = new Node('body', {}, html);
html.clientWidth = 1000;
var hits = [];          // [élément, x0, y0, x1, y1] : ce que `elementFromPoint` rend
var document = {
  listeners: {}, documentElement: html, body: body, scrollingElement: html,
  addEventListener: Node.prototype.addEventListener,
  removeEventListener: Node.prototype.removeEventListener,
  createElement: function (t) { return new Node(t, {}); },
  elementFromPoint: function (x, y) {
    var found = null;
    hits.forEach(function (h) { if (x >= h[1] && x <= h[3] && y >= h[2] && y <= h[4]) found = h[0]; });
    return found;
  },
};
window.document = document;

function el(tag, attrs, parent, rect) {
  var n = new Node(tag, attrs, parent || body);
  if (rect) { n.rect = { left: rect[0], top: rect[1], right: rect[2], bottom: rect[3],
                         width: rect[2] - rect[0], height: rect[3] - rect[1] }; hits.push([n].concat(rect)); }
  return n;
}
function touch(target, type, x, y, ts) {
  var t = [{ identifier: 1, clientX: x, clientY: y }];
  var init = { bubbles: true, cancelable: true, touches: type === 'touchend' ? [] : t, changedTouches: t };
  if (ts !== undefined) init.timeStamp = ts;           // l'horodatage de l'événement (ms)
  var ev = new Event(type, init);
  target.dispatchEvent(ev);
  return ev;
}
function pointer(target, type, id, x, y, kind, button) {
  var ev = new Event(type, { bubbles: true, cancelable: true, pointerId: id, pointerType: kind || 'touch',
                             button: button || 0, clientX: x, clientY: y });
  target.dispatchEvent(ev);
  return ev;
}
function tipShown() {
  var t = body.querySelectorAll('.wama-touch-tip');
  return t.length ? t[0].textContent : null;
}
function record(node, types) {
  types.forEach(function (t) { node.addEventListener(t, function (e) { log.push(t + ':' + (node.attrs['data-k'] || node.tagName)); }); });
}
"""


@skipUnless(HAS_V8, 'py_mini_racer absent')
class TouchDragBridgeTest(SimpleTestCase):
    """Le glisser HTML5 traduit pour le doigt — joué sur la brique SERVIE."""

    def _ctx(self):
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval(V8_HARNESS)
        ctx.eval(_read(SERVED / 'common' / 'js' / 'wama-gestures.js'))
        ctx.eval("""
            var list = el('div', {'data-k': 'list'}, body, [0, 0, 400, 400]);
            var card = el('div', {'draggable': 'true', 'data-k': 'card', 'title': 'Double-cliquez'}, list, [0, 0, 400, 80]);
            var gear = el('button', {'title': 'Paramètres', 'data-k': 'gear'}, card, [350, 10, 390, 40]);
            var plain = el('button', {'data-k': 'plain'}, card, [300, 10, 340, 40]);
            var zone = el('div', {'data-k': 'zone'}, list, [0, 200, 400, 300]);
            var field = el('textarea', {'data-k': 'field'}, list, [0, 320, 400, 380]);
            record(card, ['dragstart', 'dragend', 'contextmenu']);
            record(zone, ['dragenter', 'dragover', 'dragleave', 'drop']);
            card.addEventListener('dragstart', function (e) { e.dataTransfer.setData('text/wama', '42'); });
            var dropped = null, accept = true;
            zone.addEventListener('dragover', function (e) { if (accept) e.preventDefault(); });
            zone.addEventListener('drop', function (e) { dropped = e.dataTransfer.getData('text/wama'); });
        """)
        return ctx

    def _drag_to_zone(self, ctx):
        return json.loads(ctx.eval("""(function () {
            touch(card, 'touchstart', 50, 40);
            flushTimers();                                       // appui long
            var lifted = card.classList.contains('wama-touch-lifted');
            var m1 = touch(card, 'touchmove', 50, 120);
            var ghost = body.querySelectorAll('.wama-touch-ghost').length;
            touch(card, 'touchmove', 60, 250);
            var end = touch(card, 'touchend', 60, 250);
            return JSON.stringify({ lifted: lifted, ghost: ghost, moveHeld: m1.defaultPrevented,
                endPrevented: end.defaultPrevented, dropped: dropped, log: log,
                ghostLeft: body.querySelectorAll('.wama-touch-ghost').length,
                dragging: html.classList.contains('wama-touch-dragging') });
        })()"""))

    def test_a_long_press_then_a_move_drags_and_drops_with_the_data(self):
        r = self._drag_to_zone(self._ctx())
        self.assertTrue(r['lifted'], 'the long press must lift the element')
        self.assertEqual(r['ghost'], 1, 'a thumbnail follows the finger')
        self.assertTrue(r['moveHeld'], 'the page must not scroll under a drag')
        self.assertEqual(r['dropped'], '42', 'the drop reads what the dragstart wrote')
        self.assertEqual(r['log'], ['dragstart:card', 'dragenter:zone', 'dragover:zone', 'drop:zone', 'dragend:card'])
        self.assertTrue(r['endPrevented'], 'no click after a drag')
        self.assertEqual((r['ghostLeft'], r['dragging']), (0, False), 'the drag leaves nothing behind')

    def test_the_drag_survives_the_page_redrawing_the_held_element(self):
        # Mesuré sur le live le 2026-10-16 : le catalogue du studio se redessine pendant l'appui
        # long, l'élément tenu quitte la page et ses `touchmove` ne remontent plus au document.
        r = json.loads(self._ctx().eval("""(function () {
            touch(card, 'touchstart', 50, 40);
            flushTimers();
            list.removeChild(card);                               // la page redessine
            touch(card, 'touchmove', 50, 120);
            touch(card, 'touchmove', 60, 250);
            var end = touch(card, 'touchend', 60, 250);
            return JSON.stringify({ dropped: dropped, log: log, endPrevented: end.defaultPrevented });
        })()"""))
        self.assertEqual(r['dropped'], '42', 'the drop must still happen')
        self.assertEqual(r['log'], ['dragstart:card', 'dragenter:zone', 'dragover:zone', 'drop:zone', 'dragend:card'])
        self.assertTrue(r['endPrevented'])

    def test_an_event_seen_twice_is_handled_once(self):
        # Écouté sur le document ET sur l'élément touché : un événement qui remonte passe par les
        # deux, et ne doit faire avancer le geste qu'une fois.
        r = json.loads(self._ctx().eval("""(function () {
            touch(card, 'touchstart', 50, 40); flushTimers();
            touch(card, 'touchmove', 50, 120); touch(card, 'touchmove', 60, 250);
            touch(card, 'touchend', 60, 250);
            return JSON.stringify({ log: log });
        })()"""))
        self.assertEqual(r['log'].count('drop:zone'), 1)
        self.assertEqual(r['log'].count('dragstart:card'), 1)

    def test_no_drop_where_the_last_dragover_refused(self):
        ctx = self._ctx()
        ctx.eval('accept = false;')
        r = self._drag_to_zone(ctx)
        self.assertIsNone(r['dropped'])
        self.assertNotIn('drop:zone', r['log'])
        self.assertEqual(r['log'][-1], 'dragend:card', 'the source is always told the drag ended')

    def test_a_quick_swipe_stays_a_scroll(self):
        r = json.loads(self._ctx().eval("""(function () {
            touch(card, 'touchstart', 50, 40);
            var m = touch(card, 'touchmove', 50, 90);            // avant l'appui long
            flushTimers();
            touch(card, 'touchmove', 50, 250);
            var end = touch(card, 'touchend', 50, 250);
            return JSON.stringify({ log: log, moveHeld: m.defaultPrevented, endPrevented: end.defaultPrevented,
                                    lifted: card.classList.contains('wama-touch-lifted') });
        })()"""))
        self.assertEqual(r['log'], [])
        self.assertFalse(r['moveHeld'] or r['endPrevented'] or r['lifted'])

    def test_a_long_press_released_in_place_opens_the_menu(self):
        ctx = self._ctx()
        ctx.eval("card.addEventListener('contextmenu', function (e) { e.preventDefault(); });")
        r = json.loads(ctx.eval("""(function () {
            touch(card, 'touchstart', 50, 40);
            flushTimers();
            var end = touch(card, 'touchend', 50, 40);
            return JSON.stringify({ log: log, endPrevented: end.defaultPrevented, tip: tipShown(),
                                    lifted: card.classList.contains('wama-touch-lifted') });
        })()"""))
        self.assertEqual(r['log'], ['contextmenu:card'])
        self.assertTrue(r['endPrevented'], 'the click must not follow the menu')
        self.assertIsNone(r['tip'], 'a menu was opened: no tooltip on top of it')
        self.assertFalse(r['lifted'])

    def test_without_a_menu_the_long_press_explains_the_element(self):
        r = json.loads(self._ctx().eval("""(function () {
            touch(card, 'touchstart', 50, 40); flushTimers(); touch(card, 'touchend', 50, 40);
            return JSON.stringify({ tip: tipShown() });
        })()"""))
        self.assertEqual(r['tip'], 'Double-cliquez')

    def test_a_long_press_on_an_icon_button_shows_its_title_and_holds_the_click(self):
        r = json.loads(self._ctx().eval("""(function () {
            touch(gear, 'touchstart', 360, 20);
            flushTimers();
            var tip = tipShown();
            var end = touch(gear, 'touchend', 360, 20);
            return JSON.stringify({ tip: tip, endPrevented: end.defaultPrevented, log: log,
                                    lifted: card.classList.contains('wama-touch-lifted') });
        })()"""))
        self.assertEqual(r['tip'], 'Paramètres')
        self.assertTrue(r['endPrevented'], 'the long press must not press the button')
        self.assertFalse(r['lifted'], 'a button inside a card is a button, not a drag handle')
        self.assertEqual(r['log'], [], 'no menu, no drag')

    def test_a_title_that_repeats_the_visible_name_gives_way_to_the_menu(self):
        # L'arbre de fichiers : chaque entrée porte son propre nom en `title`. Son appui long ouvre
        # le menu (le clic droit d'une tablette), pas une infobulle qui redirait le nom.
        ctx = self._ctx()
        ctx.eval("""
            var tree = el('div', {'data-k': 'tree'}, body, [0, 500, 400, 600]);
            var entry = el('a', {'href': '#', 'title': 'Temporaires', 'data-k': 'entry'}, tree, [0, 500, 200, 530]);
            entry.textContent = 'Temporaires';
            tree.addEventListener('contextmenu', function (e) { log.push('menu'); e.preventDefault(); });
        """)
        r = json.loads(ctx.eval("""(function () {
            touch(entry, 'touchstart', 50, 515); flushTimers();
            var end = touch(entry, 'touchend', 50, 515);
            return JSON.stringify({ log: log, tip: tipShown(), endPrevented: end.defaultPrevented });
        })()"""))
        self.assertEqual(r['log'], ['menu'])
        self.assertIsNone(r['tip'])
        self.assertTrue(r['endPrevented'], 'the menu was opened: the click must not follow')

    def test_a_quick_tap_keeps_its_click(self):
        r = json.loads(self._ctx().eval("""(function () {
            touch(gear, 'touchstart', 360, 20);
            var end = touch(gear, 'touchend', 360, 20);
            flushTimers();
            return JSON.stringify({ endPrevented: end.defaultPrevented, tip: tipShown() });
        })()"""))
        self.assertFalse(r['endPrevented'])
        self.assertIsNone(r['tip'])

    def test_a_quick_tap_on_a_busy_page_is_still_a_tap(self):
        # Mesuré sur le live le 2026-10-16 : page occupée, le relâcher d'un toucher BREF traité après
        # l'échéance de l'appui long — l'infobulle s'affichait et le clic était retenu (l'outil
        # Bornes ne se refermait pas). La durée se lit aux horodatages, pas à la minuterie.
        r = json.loads(self._ctx().eval("""(function () {
            touch(gear, 'touchstart', 360, 20, 1000);
            flushTimers();                                        // la minuterie tourne en retard
            var end = touch(gear, 'touchend', 360, 20, 1120);     // doigt resté 120 ms
            return JSON.stringify({ endPrevented: end.defaultPrevented, tip: tipShown() });
        })()"""))
        self.assertFalse(r['endPrevented'], 'a 120 ms tap must keep its click')
        self.assertIsNone(r['tip'])

    def test_a_long_press_measured_by_timestamps_still_explains(self):
        r = json.loads(self._ctx().eval("""(function () {
            touch(gear, 'touchstart', 360, 20, 1000); flushTimers();
            var end = touch(gear, 'touchend', 360, 20, 1700);     // doigt resté 700 ms
            return JSON.stringify({ endPrevented: end.defaultPrevented, tip: tipShown() });
        })()"""))
        self.assertTrue(r['endPrevented'])
        self.assertEqual(r['tip'], 'Paramètres')

    def test_a_slow_press_that_showed_nothing_keeps_its_click(self):
        r = json.loads(self._ctx().eval("""(function () {
            touch(plain, 'touchstart', 320, 20);
            flushTimers();
            var end = touch(plain, 'touchend', 320, 20);
            return JSON.stringify({ endPrevented: end.defaultPrevented, tip: tipShown() });
        })()"""))
        self.assertIsNone(r['tip'])
        self.assertFalse(r['endPrevented'], 'a slow tap on a plain button must still press it')

    def test_a_text_field_keeps_its_native_long_press(self):
        r = json.loads(self._ctx().eval("""(function () {
            touch(field, 'touchstart', 50, 350); flushTimers();
            var end = touch(field, 'touchend', 50, 350);
            return JSON.stringify({ endPrevented: end.defaultPrevented, tip: tipShown(), log: log });
        })()"""))
        self.assertEqual((r['endPrevented'], r['tip'], r['log']), (False, None, []))


@skipUnless(HAS_V8, 'py_mini_racer absent')
class TrackPointerTest(SimpleTestCase):
    """`WamaGestures.track` : seuil, boutons, pincement."""

    def _ctx(self):
        from py_mini_racer import MiniRacer
        ctx = MiniRacer()
        ctx.eval(V8_HARNESS)
        ctx.eval(_read(SERVED / 'common' / 'js' / 'wama-gestures.js'))
        ctx.eval("""
            var surface = el('div', {}, body, [0, 0, 800, 600]);
            var seen = { starts: 0, moves: [], ends: [], pinches: [] };
            WamaGestures.track(surface, {
                buttons: [0, 1],
                start: function (e) { seen.starts++; return e.clientX < 700 ? {} : false; },
                move: function (e, c, d) { seen.moves.push([d.dx, d.dy]); },
                end: function (e, c, info) { seen.ends.push(info); },
                pinch: function (p) { seen.pinches.push(Math.round(p.scale * 100) / 100); },
            });
        """)
        return ctx

    def _run(self, ctx, script):
        return json.loads(ctx.eval('(function () {' + script + '; return JSON.stringify(seen); })()'))

    def test_the_brick_takes_the_surface_off_the_page_scroll(self):
        ctx = self._ctx()
        self.assertEqual(ctx.eval('surface.style.touchAction'), 'none')

    def test_a_trembling_press_is_still_a_click(self):
        s = self._run(self._ctx(), """
            pointer(surface, 'pointerdown', 1, 100, 100);
            pointer(surface, 'pointermove', 1, 104, 102);      // 6 px < 8 : seuil du doigt
            pointer(surface, 'pointerup', 1, 104, 102)""")
        self.assertEqual(s['moves'], [])
        self.assertEqual(s['ends'], [{'moved': False, 'cancelled': False}])

    def test_a_drag_reports_its_offset_from_the_press(self):
        s = self._run(self._ctx(), """
            pointer(surface, 'pointerdown', 1, 100, 100, 'mouse');
            pointer(surface, 'pointermove', 1, 130, 90, 'mouse');
            pointer(surface, 'pointerup', 1, 130, 90, 'mouse')""")
        self.assertEqual(s['moves'], [[30, -10]])
        self.assertEqual(s['ends'], [{'moved': True, 'cancelled': False}])

    def test_unlisted_mouse_buttons_and_refused_presses_are_ignored(self):
        s = self._run(self._ctx(), """
            pointer(surface, 'pointerdown', 1, 100, 100, 'mouse', 2);   // clic droit
            pointer(surface, 'pointermove', 1, 200, 100, 'mouse', 2);
            pointer(surface, 'pointerup', 1, 200, 100, 'mouse', 2);
            pointer(surface, 'pointerdown', 2, 750, 100, 'mouse');      // refusé par start()
            pointer(surface, 'pointermove', 2, 650, 100, 'mouse');
            pointer(surface, 'pointerup', 2, 650, 100, 'mouse')""")
        self.assertEqual(s['starts'], 1, 'the right button never reaches start()')
        self.assertEqual((s['moves'], s['ends']), ([], []))

    def test_a_second_finger_turns_the_drag_into_a_pinch(self):
        s = self._run(self._ctx(), """
            pointer(surface, 'pointerdown', 1, 300, 300);
            pointer(surface, 'pointermove', 1, 320, 300);
            pointer(surface, 'pointerdown', 2, 420, 300);      // 100 px d'écart
            pointer(surface, 'pointermove', 2, 520, 300);      // 200 px : ×2
            pointer(surface, 'pointerup', 2, 520, 300);
            pointer(surface, 'pointermove', 1, 400, 300);      // le doigt restant ne relance rien
            pointer(surface, 'pointerup', 1, 400, 300)""")
        self.assertEqual(s['moves'], [[20, 0]])
        self.assertEqual(s['ends'], [{'moved': True, 'cancelled': True}])
        self.assertEqual(s['pinches'], [2.0])


class PagesAdoptTheBrickTest(SimpleTestCase):

    def test_the_studio_moves_nodes_and_view_through_the_brick(self):
        js = _read(STUDIO)
        self.assertEqual(js.count('WamaGestures.track('), 2, 'node drag and canvas pan/pinch')
        self.assertIn('pinch: function', js)
        self.assertNotIn("addEventListener('mousedown'", js)
        self.assertNotIn("addEventListener('mouseup'", js)

    def test_the_editor_wave_and_minimap_go_through_the_brick(self):
        js = _read(EDITOR)
        self.assertEqual(js.count('WamaGestures.track('), 2, 'wave and minimap')
        self.assertIn('pinch: function', js)
        for gone in ("addEventListener('mousedown'", "addEventListener('mouseup'",
                     "window.addEventListener('mousemove'"):
            self.assertNotIn(gone, js)
        # Un doigt saisit une borne de plus loin qu'une souris.
        self.assertIn('WamaGestures.isTouch(e) ? HANDLE_PX_TOUCH : HANDLE_PX', js)

    def test_the_drag_sources_have_no_touch_code_of_their_own(self):
        # La file, la palette et l'ordre des segments gardent leurs gestionnaires HTML5 : c'est la
        # brique qui traduit le doigt. Un second chemin tactile dans une page serait une 2e version
        # du même geste.
        for path in (QUEUE, STUDIO, EDITOR, SEGMENTS):
            js = _read(path)
            for touch_event in ('touchstart', 'touchmove', 'touchend'):
                self.assertNotIn(touch_event, js, f'{path.name} carries its own {touch_event}')

    def test_the_gestures_are_measured_every_night(self):
        from wama.common.services import nightly_tests
        ids = {s.id for s in nightly_tests.REGISTRY}
        self.assertIn('common.gestures.touch', ids)
        # La garde du PC : les mêmes pages à la souris (canvas, onde, case, survol, cloche).
        self.assertIn('common.gestures.mouse', ids)

    def test_the_served_copies_are_the_sources(self):
        pairs = [(GESTURES, SERVED / 'common' / 'js' / 'wama-gestures.js'),
                 (QUEUE, SERVED / 'common' / 'js' / 'wama-queue-dnd.js'),
                 (COMMON / 'css' / 'wama-touch.css', SERVED / 'common' / 'css' / 'wama-touch.css'),
                 (STUDIO, SERVED / 'studio' / 'js' / 'wama-studio.js'),
                 (EDITOR, SERVED / 'common' / 'js' / 'wama-timeline.js'),
                 (SEGMENTS, SERVED / 'common' / 'js' / 'surfaces' / 'brick-segment-list.js')]
        for source, served in pairs:
            self.assertEqual(_read(source), _read(served), f'{served} is stale')

    @skipUnless(HAS_V8, 'py_mini_racer absent')
    def test_the_touched_scripts_parse_under_v8(self):
        from py_mini_racer import MiniRacer
        for path in (GESTURES, STUDIO, EDITOR, SEGMENTS, QUEUE):
            MiniRacer().eval('(function(){' + _read(path) + '\n})')
