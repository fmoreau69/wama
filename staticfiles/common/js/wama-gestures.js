/**
 * wama-gestures.js — LES GESTES AU POINTEUR, communs à toute page (ROADMAP §27, étape 3 — 2026-10-16).
 *
 * Montée par base.html : valable dans les trois mondes, et une app n'écrit aucune ligne pour que
 * ses gestes marchent au doigt. Avant elle, le glisser portait des gestes centraux à cinq endroits
 * (explorateur, file, studio, éditeur du transcriber, cam_analyzer), tous écrits pour la souris :
 * au relevé tablette du 2026-10-10, la file ne démarrait JAMAIS un glisser au doigt, le studio ne
 * défilait ni ne zoomait, l'onde du transcriber ne répondait qu'au clic.
 *
 * ══ TROIS CHOSES, ET RIEN D'AUTRE ══════════════════════════════════════════════════════════════
 *
 *   1. `WamaGestures.track(el, {...})` — SUIVRE UN POINTEUR sur une surface qui dessine elle-même
 *      (canvas du studio, onde du transcriber) : glisser avec un seuil (un appui qui n'a pas bougé
 *      reste un clic), et PINCER à deux doigts. Pointer Events : souris, stylet et doigt passent
 *      par le même code. C'est ce qu'adoptent les pages ; elles n'écrivent plus de
 *      mousedown/mousemove/mouseup.
 *
 *   2. LE GLISSER HTML5 AU DOIGT — automatique, sur tout `[draggable="true"]` de la page. Un
 *      navigateur tactile ne lance pas le glisser natif (Chromium jamais ; Safari selon les
 *      versions) : la brique le TRADUIT. Appui long, puis le doigt bouge → `dragstart`,
 *      `dragenter`/`dragover`/`dragleave` sous le doigt, `drop`, `dragend`, avec un `dataTransfer`
 *      réel. Les gestionnaires de la page sont donc LES MÊMES qu'à la souris : la file, la
 *      palette du studio et l'ordre des segments du transcriber n'ont pas changé d'une ligne pour
 *      cela. Une vignette suit le doigt, et la liste défile quand le doigt approche de son bord.
 *      ⚠ À la souris, la brique ne fait RIEN : le glisser natif reste celui du navigateur.
 *
 *   3. L'APPUI LONG — un doigt ne fait ni clic droit ni survol. Appui long sans bouger :
 *        • sur une commande qui porte un `title` (bouton-icône) → son INFOBULLE s'affiche, et le
 *          clic qui suivrait est retenu (l'appui long n'a pas déclenché le bouton) ;
 *        • ailleurs → un `contextmenu` est émis au point touché : le menu de card de la file
 *          (`wama-card-menu.js`) et celui de l'arbre de fichiers s'ouvrent comme au clic droit.
 *          Personne ne le prend ? l'infobulle de l'élément, s'il en a une ;
 *        • sur un élément qu'on peut glisser, l'appui long le SOULÈVE : bouger le glisse,
 *          relâcher sans bouger ouvre son menu (le geste de l'écran d'accueil d'une tablette).
 *      Les champs de saisie gardent leur appui long natif (sélection du texte).
 *
 * ══ CE QUE LA BRIQUE NE FAIT PAS ═══════════════════════════════════════════════════════════════
 *
 *   • Elle ne décide d'aucune action : elle traduit des gestes, la page garde ses gestionnaires.
 *   • La molette reste aux pages (zoom sous le curseur) : ce n'est pas un geste de doigt.
 *   • La sélection MULTIPLE de la file n'est pas un geste : c'est la case de chaque card
 *     (`wama-queue-dnd.js`, 2026-10-16), qu'un doigt coche comme une souris.
 *
 * Critère tactile : celui de l'événement (`pointerType`, `touchstart`), jamais une détection de
 * l'appareil — un portable tactile piloté à la souris garde ses gestes de souris.
 * Forme d'emploi : WAMA_APP_CONVENTIONS §23. Garde : `tests_gestures`, et le scénario nocturne
 * `common.gestures.touch`.
 */
(function (global) {
    'use strict';

    var doc = global.document;
    if (!doc) return;

    // Seuils, en px écran. Un doigt tremble plus qu'une souris : un appui qui a bougé de moins
    // que son seuil reste un CLIC (à la souris, 3 px — la valeur que le studio tenait déjà).
    var THRESHOLD = { mouse: 3, pen: 4, touch: 8 };
    var HOLD_MS = 450;          // appui long (Android, iPadOS : entre 400 et 500 ms)
    var SLOP = 10;              // un doigt qui bouge davantage avant l'appui long fait défiler
    var TIP_MS = 2500;          // durée de l'infobulle
    var EDGE = 48;              // bande, au bord d'une liste, où le glisser la fait défiler

    function isTouch(ev) {
        return !!ev && (ev.pointerType === 'touch' || ev.pointerType === 'pen');
    }

    // ══ 1. SUIVRE UN POINTEUR ══════════════════════════════════════════════════════════════════
    //
    // opts :
    //   buttons    boutons de souris acceptés (défaut [0]) ; doigt et stylet passent toujours
    //   threshold  px avant qu'un appui devienne un glisser (défaut : selon le pointeur)
    //   touchAction  valeur posée sur l'élément (défaut 'none' : la surface défile ELLE-MÊME ;
    //              'pan-y' laisse la page défiler verticalement par-dessus)
    //   start(ev) → contexte, ou false pour ignorer cet appui
    //   move(ev, ctx, d)  d = {dx, dy} depuis l'appui, {mx, my} depuis le dernier mouvement
    //   end(ev, ctx, {moved, cancelled})
    //   pinch({scale, cx, cy, dx, dy})  deux doigts : facteur depuis le pas précédent, centre
    //              (coordonnées écran) et son déplacement — pincer zoome ET déplace
    //   pinchEnd()
    // Rend une fonction qui détache tout.
    function track(el, opts) {
        opts = opts || {};
        var buttons = opts.buttons || [0];
        var points = {};        // pointerId → {x, y} : tous les pointeurs posés sur l'élément
        var gesture = null;     // le glisser en cours (un seul pointeur)
        var pinch = null;       // {d, cx, cy} : le pincement en cours
        var swallowMouseDown = false;
        var listening = false;

        if (opts.touchAction !== false) el.style.touchAction = opts.touchAction || 'none';
        el.setAttribute('data-wama-track', '');

        function count() { return Object.keys(points).length; }

        function pinchState() {
            var ids = Object.keys(points), a = points[ids[0]], b = points[ids[1]];
            return { d: Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)),
                     cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
        }

        function onDown(ev) {
            if (ev.pointerType === 'mouse' && buttons.indexOf(ev.button) === -1) return;
            points[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
            listen();
            if (count() === 2 && opts.pinch) {
                // Un second doigt : le glisser en cours s'ARRÊTE (annulé), le pincement prend la main.
                if (gesture) finish(ev, true);
                pinch = pinchState();
                return;
            }
            if (count() > 1 || gesture || pinch) return;
            var ctx = opts.start ? opts.start(ev) : {};
            if (ctx === false || ctx == null) return;
            gesture = {
                id: ev.pointerId, ctx: ctx, sx: ev.clientX, sy: ev.clientY, lx: ev.clientX, ly: ev.clientY,
                moved: false,
                threshold: opts.threshold != null ? opts.threshold : (THRESHOLD[ev.pointerType] || 3),
            };
            // À la souris, l'appui retenu ne doit ni sélectionner du texte, ni lancer le défilement
            // automatique du bouton du milieu, ni un glisser natif d'image : c'est le `mousedown`
            // qui les porte (annuler `pointerdown` ne les empêche pas) — voir `onMouseDown`.
            if (ev.pointerType === 'mouse') swallowMouseDown = true;
        }

        function onMouseDown(ev) {
            if (!swallowMouseDown) return;
            swallowMouseDown = false;
            ev.preventDefault();
        }

        function onMove(ev) {
            if (!(ev.pointerId in points)) return;
            points[ev.pointerId] = { x: ev.clientX, y: ev.clientY };
            if (pinch) {
                if (count() < 2) return;
                var now = pinchState();
                if (opts.pinch) opts.pinch({ scale: now.d / pinch.d, cx: now.cx, cy: now.cy,
                                             dx: now.cx - pinch.cx, dy: now.cy - pinch.cy });
                pinch = now;
                if (ev.cancelable) ev.preventDefault();
                return;
            }
            if (!gesture || ev.pointerId !== gesture.id) return;
            var dx = ev.clientX - gesture.sx, dy = ev.clientY - gesture.sy;
            if (!gesture.moved) {
                if (Math.abs(dx) + Math.abs(dy) < gesture.threshold) return;
                gesture.moved = true;
            }
            if (ev.cancelable) ev.preventDefault();
            var d = { dx: dx, dy: dy, mx: ev.clientX - gesture.lx, my: ev.clientY - gesture.ly };
            gesture.lx = ev.clientX; gesture.ly = ev.clientY;
            if (opts.move) opts.move(ev, gesture.ctx, d);
        }

        function onUp(ev) {
            if (!(ev.pointerId in points)) return;
            delete points[ev.pointerId];
            if (pinch) {
                // Le doigt qui reste ne relance pas de glisser : on attend qu'ils soient tous levés.
                if (count() < 2) { pinch = null; if (opts.pinchEnd) opts.pinchEnd(); }
            } else if (gesture && ev.pointerId === gesture.id) {
                finish(ev, ev.type === 'pointercancel');
            }
            if (!count()) unlisten();
        }

        function finish(ev, cancelled) {
            var g = gesture;
            gesture = null;
            if (opts.end) opts.end(ev, g.ctx, { moved: g.moved, cancelled: !!cancelled });
        }

        // Mouvements et relâchers écoutés sur la FENÊTRE pendant le geste : le pointeur sort de
        // l'élément sans que le geste s'arrête (comme les écouteurs `document` d'avant).
        function listen() {
            if (listening) return;
            listening = true;
            global.addEventListener('pointermove', onMove, { passive: false });
            global.addEventListener('pointerup', onUp);
            global.addEventListener('pointercancel', onUp);
        }
        function unlisten() {
            if (!listening) return;
            listening = false;
            global.removeEventListener('pointermove', onMove, { passive: false });
            global.removeEventListener('pointerup', onUp);
            global.removeEventListener('pointercancel', onUp);
        }

        el.addEventListener('pointerdown', onDown);
        el.addEventListener('mousedown', onMouseDown);
        return function detach() {
            el.removeEventListener('pointerdown', onDown);
            el.removeEventListener('mousedown', onMouseDown);
            el.removeAttribute('data-wama-track');
            unlisten();
            points = {}; gesture = null; pinch = null;
        };
    }

    // ══ 2 et 3. LE DOIGT : glisser HTML5 et appui long ═════════════════════════════════════════
    //
    // Touch Events et non Pointer Events : un `pointermove` ne peut pas empêcher la page de
    // défiler une fois le doigt parti — `touchmove`, si (écouteur NON passif). C'est ce qui permet
    // de laisser défiler une liste au balayage et de la tenir dès que l'appui long a soulevé une
    // card.

    var INTERACTIVE = 'button, a[href], input, select, textarea, label, summary, [role="button"], ' +
                      '[data-bs-toggle], .btn';
    var TEXT_ENTRY = 'input, textarea, select, [contenteditable]:not([contenteditable="false"])';

    var session = null;     // l'appui en cours : {x, y, target, source, timer, held, ...}
    var drag = null;        // le glisser traduit : {source, dt, ghost, over, accepted, ...}
    var tip = null;         // l'infobulle affichée : {el, timer}

    function closestIn(el, selector, stop) {
        var found = el && el.closest ? el.closest(selector) : null;
        return found && (!stop || stop.contains(found)) ? found : null;
    }

    function tipText(el) {
        if (!el) return '';
        return (el.getAttribute('title') || el.getAttribute('aria-label') || '').trim();
    }

    /** L'élément dont l'appui long montre l'infobulle : le plus proche qui en porte une. */
    function tipSource(target) {
        var el = target && target.closest ? target.closest('[title], [aria-label]') : null;
        // `aria-label` seul ne vaut que sur une commande : sur un conteneur, c'est un nom de région.
        if (el && !el.hasAttribute('title') && !el.matches(INTERACTIVE)) return null;
        return el && tipText(el) ? el : null;
    }

    // ── L'infobulle ─────────────────────────────────────────────────────────────────────────────
    function hideTip() {
        if (!tip) return;
        clearTimeout(tip.timer);
        if (tip.el.parentNode) tip.el.parentNode.removeChild(tip.el);
        tip = null;
    }

    function showTip(source) {
        hideTip();
        var text = source ? tipText(source) : '';
        if (!text) return false;
        var el = doc.createElement('div');
        el.className = 'wama-touch-tip';
        el.setAttribute('role', 'tooltip');
        el.textContent = text;
        doc.body.appendChild(el);
        // Au-dessus de l'élément (le doigt cache le dessous), en dessous s'il n'y a pas la place ;
        // jamais hors de l'écran.
        var r = source.getBoundingClientRect(), w = el.offsetWidth, h = el.offsetHeight;
        var vw = doc.documentElement.clientWidth, gap = 8;
        var top = r.top - h - gap;
        if (top < gap) top = r.bottom + gap;
        var left = Math.min(vw - w - gap, Math.max(gap, r.left + r.width / 2 - w / 2));
        el.style.left = Math.round(left) + 'px';
        el.style.top = Math.round(top) + 'px';
        tip = { el: el, timer: setTimeout(hideTip, TIP_MS) };
        return true;
    }

    // ── Le transport du glisser ─────────────────────────────────────────────────────────────────
    // Un `DataTransfer` RÉEL quand le navigateur sait en construire un (Chromium, Firefox, Safari
    // 14.1+) : la page y lit `types`, `getData`, `dropEffect` comme à la souris. Sinon, un objet
    // qui en a la forme.
    function makeTransfer() {
        try {
            if (typeof global.DataTransfer === 'function') return new global.DataTransfer();
        } catch (e) { /* constructeur absent ou refusé : la forme suffit */ }
        var data = {};
        var shim = {
            dropEffect: 'none', effectAllowed: 'all', files: [], items: [], types: [],
            setData: function (k, v) { data[k] = String(v); if (shim.types.indexOf(k) < 0) shim.types.push(k); },
            getData: function (k) { return data[k] != null ? data[k] : ''; },
            clearData: function (k) {
                if (k == null) { data = {}; shim.types.length = 0; return; }
                delete data[k];
                var i = shim.types.indexOf(k);
                if (i >= 0) shim.types.splice(i, 1);
            },
            setDragImage: function () {},
        };
        return shim;
    }

    function fire(target, type, x, y, dt, related) {
        var ev = null;
        var init = { bubbles: true, cancelable: true, composed: true, clientX: x, clientY: y,
                     screenX: x, screenY: y, button: 0, buttons: type === 'dragend' || type === 'drop' ? 0 : 1,
                     relatedTarget: related || null };
        if (typeof global.DataTransfer === 'function' && dt instanceof global.DataTransfer) {
            try { init.dataTransfer = dt; ev = new global.DragEvent(type, init); } catch (e) { ev = null; }
        }
        if (!ev) {
            ev = new global.Event(type, { bubbles: true, cancelable: true, composed: true });
            var props = { clientX: x, clientY: y, pageX: x + global.pageXOffset, pageY: y + global.pageYOffset,
                          screenX: x, screenY: y, button: 0, buttons: init.buttons, dataTransfer: dt,
                          relatedTarget: related || null, ctrlKey: false, shiftKey: false, altKey: false,
                          metaKey: false };
            Object.keys(props).forEach(function (k) {
                Object.defineProperty(ev, k, { value: props[k], enumerable: true });
            });
        }
        target.dispatchEvent(ev);
        return ev;
    }

    // ── Le glisser traduit ──────────────────────────────────────────────────────────────────────
    function makeGhost(source, x, y, held) {
        // La boîte relevée à l'appui si l'élément a quitté la page depuis (voir `bindTarget`).
        var r = source.isConnected === false && held ? held : source.getBoundingClientRect();
        var ghost = source.cloneNode(true);
        ghost.removeAttribute('id');
        Array.prototype.forEach.call(ghost.querySelectorAll('[id]'), function (n) { n.removeAttribute('id'); });
        // Une vignette, pas la card entière : 260 px au plus, et le doigt reste au point saisi.
        var scale = Math.min(1, 260 / Math.max(1, r.width));
        ghost.classList.add('wama-touch-ghost');
        ghost.style.width = r.width + 'px';
        ghost.style.height = r.height + 'px';
        ghost.style.transformOrigin = '0 0';
        ghost.setAttribute('aria-hidden', 'true');
        doc.body.appendChild(ghost);
        return { el: ghost, scale: scale, ox: (x - r.left) * scale, oy: (y - r.top) * scale };
    }

    function placeGhost(x, y) {
        var g = drag.ghost;
        g.el.style.transform = 'translate(' + Math.round(x - g.ox) + 'px, ' + Math.round(y - g.oy) + 'px) scale(' + g.scale + ')';
    }

    /** Le premier ancêtre qui DÉFILE verticalement, ou le document. */
    function scrollerOf(el) {
        for (var e = el; e && e !== doc.body && e !== doc.documentElement; e = e.parentElement) {
            var oy = global.getComputedStyle(e).overflowY;
            if ((oy === 'auto' || oy === 'scroll') && e.scrollHeight > e.clientHeight + 1) return e;
        }
        return doc.scrollingElement || doc.documentElement;
    }

    function startDrag(s) {
        var dt = makeTransfer();
        drag = { source: s.source, dt: dt, over: null, accepted: false, x: s.x, y: s.y, raf: null, speed: 0, scroller: null };
        var start = fire(s.source, 'dragstart', s.x, s.y, dt);
        if (start.defaultPrevented) { drag = null; s.source.classList.remove('wama-touch-lifted'); return false; }
        s.source.classList.remove('wama-touch-lifted');
        drag.ghost = makeGhost(s.source, s.x, s.y, s.rect);
        placeGhost(s.x, s.y);
        doc.documentElement.classList.add('wama-touch-dragging');
        hideTip();
        return true;
    }

    function dragTo(x, y) {
        drag.x = x; drag.y = y;
        placeGhost(x, y);
        var under = doc.elementFromPoint(x, y);
        if (under !== drag.over) {
            if (drag.over) fire(drag.over, 'dragleave', x, y, drag.dt, under);
            if (under) fire(under, 'dragenter', x, y, drag.dt, drag.over);
            drag.over = under;
        }
        drag.accepted = under ? fire(under, 'dragover', x, y, drag.dt).defaultPrevented : false;
        edgeScroll(under, y);
    }

    // Près du bord d'une liste qui défile, le glisser la fait défiler — sinon une card ne pourrait
    // pas rejoindre une place hors de l'écran (la file en a souvent plus qu'il n'en tient).
    function edgeScroll(under, y) {
        var scroller = under ? scrollerOf(under) : null;
        var speed = 0;
        if (scroller) {
            var isDoc = scroller === doc.scrollingElement || scroller === doc.documentElement;
            var r = isDoc ? { top: 0, bottom: global.innerHeight } : scroller.getBoundingClientRect();
            var top = Math.max(0, r.top), bottom = Math.min(global.innerHeight, r.bottom);
            if (y < top + EDGE) speed = -Math.ceil((top + EDGE - y) / 4);
            else if (y > bottom - EDGE) speed = Math.ceil((y - (bottom - EDGE)) / 4);
        }
        drag.scroller = scroller;
        drag.speed = speed;
        if (speed && !drag.raf) drag.raf = global.requestAnimationFrame(scrollStep);
    }

    function scrollStep() {
        if (!drag) return;
        drag.raf = null;
        if (!drag.speed || !drag.scroller) return;
        var before = drag.scroller.scrollTop;
        drag.scroller.scrollTop = before + drag.speed;
        if (drag.scroller.scrollTop === before) return;      // au bout : on s'arrête
        dragTo(drag.x, drag.y);                              // ce qui est sous le doigt a changé
    }

    function endDrag(cancelled) {
        var d = drag;
        drag = null;
        unbindTarget();
        if (d.raf) global.cancelAnimationFrame(d.raf);
        if (d.ghost && d.ghost.el.parentNode) d.ghost.el.parentNode.removeChild(d.ghost.el);
        doc.documentElement.classList.remove('wama-touch-dragging');
        // Comme le navigateur : un `drop` n'a lieu que si le dernier `dragover` l'a accepté.
        if (!cancelled && d.over && d.accepted) {
            d.dt.dropEffect = d.dt.dropEffect && d.dt.dropEffect !== 'none' ? d.dt.dropEffect : 'move';
            fire(d.over, 'drop', d.x, d.y, d.dt);
        } else if (d.over) {
            fire(d.over, 'dragleave', d.x, d.y, d.dt, null);
        }
        fire(d.source, 'dragend', d.x, d.y, d.dt);
    }

    // ── L'appui long ────────────────────────────────────────────────────────────────────────────
    function contextMenuAt(s) {
        var ev = new global.MouseEvent('contextmenu', {
            bubbles: true, cancelable: true, composed: true, clientX: s.x, clientY: s.y,
            screenX: s.x, screenY: s.y, button: 2, buttons: 0,
        });
        s.target.dispatchEvent(ev);
        // Une page qui ouvre son menu annule celui du navigateur : c'est ainsi qu'on sait qu'il
        // a été PRIS (le natif qui suivrait, sur Android, est alors écarté).
        s.menuTaken = ev.defaultPrevented;
        return s.menuTaken;
    }

    function onHold() {
        var s = session;
        if (!s) return;
        s.held = true;
        if (s.source) {
            // Soulevée : bouger la glisse, relâcher ouvre son menu (voir `onTouchEnd`). Sa boîte
            // est relevée MAINTENANT : la page peut la retirer d'ici le glisser (voir `bindTarget`).
            var r = s.source.getBoundingClientRect();
            s.rect = { left: r.left, top: r.top, width: r.width, height: r.height };
            s.source.classList.add('wama-touch-lifted');
            if (global.navigator && global.navigator.vibrate) { try { global.navigator.vibrate(12); } catch (e) {} }
            return;
        }
        if (s.command && showTip(s.command)) { s.acted = true; return; }
        // L'infobulle de repli : celle de l'élément touché — jamais, pour un appui parti d'une
        // commande sans titre, celle d'un ancêtre (« Double-cliquez… » d'une card sur son bouton
        // « Ouvrir ») : elle mentirait sur ce qu'on tient, et avalerait son clic.
        var fallback = s.onCommand ? null : tipSource(s.target);
        // Une surface qui suit elle-même le pointeur (canvas, onde) n'a pas de menu à elle.
        if (s.tracked) { s.acted = showTip(fallback); return; }
        if (s.nativeMenu) return;                         // le navigateur l'a déjà émis (Android)
        s.acted = contextMenuAt(s) || showTip(fallback);
    }

    function onTouchStart(ev) {
        hideTip();
        if (drag) { endDrag(true); }
        if (ev.touches.length !== 1) { cancelSession(); return; }
        var t = ev.touches[0];
        var target = ev.target && ev.target.nodeType === 1 ? ev.target : (ev.target && ev.target.parentElement);
        if (!target || closestIn(target, TEXT_ENTRY) || closestIn(target, '[data-wama-gestures="off"]')) {
            cancelSession();
            return;
        }
        cancelSession();
        var source = closestIn(target, '[draggable="true"]');
        var command = closestIn(target, INTERACTIVE);
        // Un bouton DANS une card qu'on peut glisser reste un bouton : son appui long l'explique.
        if (source && command && source.contains(command) && command !== source) source = null;
        session = {
            x: t.clientX, y: t.clientY, id: t.identifier, target: target, source: source,
            command: command && tipText(command) ? command : null, onCommand: !!command,
            tracked: !!closestIn(target, '[data-wama-track]'),
            held: false, acted: false, menuTaken: false, nativeMenu: false,
        };
        session.timer = setTimeout(onHold, HOLD_MS);
        bindTarget(target);
    }

    // ⚠ L'élément touché peut QUITTER LA PAGE pendant le geste — mesuré sur le live le
    // 2026-10-16 : le catalogue du studio se redessine à l'arrivée de sa seconde réponse réseau,
    // parfois pendant l'appui long. Le navigateur continue d'adresser les `touchmove`/`touchend`
    // à l'élément d'origine, qui, hors de la page, ne les fait plus remonter jusqu'au document :
    // le glisser mourait sans un mot. On les écoute donc AUSSI sur l'élément lui-même ; une marque
    // sur l'événement évite de traiter deux fois celui qui, lui, remonte.
    var bound = null;
    function bindTarget(el) {
        unbindTarget();
        bound = el;
        el.addEventListener('touchmove', onTouchMove, { passive: false });
        el.addEventListener('touchend', onTouchEnd, { passive: false });
        el.addEventListener('touchcancel', onTouchEnd, { passive: false });
    }
    function unbindTarget() {
        if (!bound) return;
        bound.removeEventListener('touchmove', onTouchMove, { passive: false });
        bound.removeEventListener('touchend', onTouchEnd, { passive: false });
        bound.removeEventListener('touchcancel', onTouchEnd, { passive: false });
        bound = null;
    }
    function firstSight(ev) {
        if (ev.__wamaGestures) return false;
        ev.__wamaGestures = true;
        return true;
    }

    function touchOf(ev, id) {
        for (var i = 0; i < ev.changedTouches.length; i++) {
            if (ev.changedTouches[i].identifier === id) return ev.changedTouches[i];
        }
        return null;
    }

    function onTouchMove(ev) {
        if (!firstSight(ev)) return;
        if (drag) {
            var td = touchOf(ev, drag.touchId);
            if (!td) return;
            if (ev.cancelable) ev.preventDefault();          // la page ne défile pas sous le glisser
            dragTo(td.clientX, td.clientY);
            return;
        }
        if (!session) return;
        var t = touchOf(ev, session.id);
        if (!t) return;
        var far = Math.abs(t.clientX - session.x) + Math.abs(t.clientY - session.y) > SLOP;
        if (!session.held) {
            if (far) cancelSession();                        // c'est un défilement : on s'efface
            return;
        }
        if (session.source && far) {
            if (ev.cancelable) ev.preventDefault();
            var s = session;
            clearTimeout(s.timer);
            session = null;
            if (startDrag(s)) {
                drag.touchId = s.id;
                dragTo(t.clientX, t.clientY);
            }
            return;
        }
        if (session.held && ev.cancelable) ev.preventDefault();   // soulevée : la liste ne bouge pas
    }

    function onTouchEnd(ev) {
        if (!firstSight(ev)) return;
        if (drag) {
            if (!touchOf(ev, drag.touchId)) return;
            if (ev.cancelable) ev.preventDefault();          // ni clic ni souris émulée après un glisser
            endDrag(ev.type === 'touchcancel');
            return;
        }
        var s = session;
        if (!s || !touchOf(ev, s.id)) return;
        clearTimeout(s.timer);
        session = null;
        unbindTarget();
        if (!s.held) return;                                 // un appui bref : le clic suit son cours
        if (s.source) {
            s.source.classList.remove('wama-touch-lifted');
            if (ev.type === 'touchend' && !contextMenuAt(s)) showTip(tipSource(s.target));
            s.acted = true;
        }
        // L'appui long a agi (menu, infobulle, soulèvement) : le clic qui suivrait n'est pas voulu.
        // Un appui seulement LENT, qui n'a rien montré, garde son clic.
        if (s.acted && ev.cancelable) ev.preventDefault();
    }

    function cancelSession() {
        if (!session) return;
        clearTimeout(session.timer);
        if (session.source) session.source.classList.remove('wama-touch-lifted');
        session = null;
        unbindTarget();
    }

    // Le `contextmenu` NATIF d'un appui long (Android) : sur un élément qu'on peut glisser, c'est
    // la brique qui décidera au relâcher (menu ou glisser) ; ailleurs on le laisse passer — sauf
    // si un menu de la page a déjà pris le geste de la brique : il s'ouvrirait deux fois. Un natif
    // qui n'a rien en face (texte d'une page) garde son effet : la sélection du texte.
    function onNativeContextMenu(ev) {
        if (!ev.isTrusted || !session) return;
        if (session.source || session.menuTaken) {
            ev.preventDefault();
            ev.stopImmediatePropagation();
            return;
        }
        session.nativeMenu = true;
    }

    // Le glisser NATIF au doigt (Safari d'iPadOS en lance un sur appui long) : écarté pendant un
    // appui suivi par la brique — deux glisser du même élément se marcheraient dessus.
    function onNativeDragStart(ev) {
        if (ev.isTrusted && (session || drag)) ev.preventDefault();
    }

    function install() {
        doc.addEventListener('touchstart', onTouchStart, { passive: true, capture: true });
        doc.addEventListener('touchmove', onTouchMove, { passive: false, capture: true });
        doc.addEventListener('touchend', onTouchEnd, { passive: false, capture: true });
        doc.addEventListener('touchcancel', onTouchEnd, { passive: false, capture: true });
        global.addEventListener('contextmenu', onNativeContextMenu, true);
        doc.addEventListener('dragstart', onNativeDragStart, true);
        global.addEventListener('scroll', hideTip, { passive: true, capture: true });
    }

    install();

    global.WamaGestures = {
        track: track,
        isTouch: isTouch,
        showTip: showTip,
        hideTip: hideTip,
        HOLD_MS: HOLD_MS,
        INTERACTIVE: INTERACTIVE,       // ce qu'un appui long explique au lieu de le glisser
    };
})(window);
