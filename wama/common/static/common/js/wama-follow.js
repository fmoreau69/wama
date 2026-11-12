/**
 * WamaFollow — SUIVRE LA LECTURE : une brique garde en vue ce qui est joué, et un VERROU l'y oblige.
 *
 * Extrait le 2026-11-12 de la liste des segments (`brick-segment-list.js`, la page de correction du
 * transcriber — R166), quand la partition l'a demandé à son tour (#1516, Fabien : « le défilement
 * automatique de la partition pendant la lecture ; à voir si on reprend le système de lock de la
 * page d'édition du Transcriber »). Un geste, deux briques : la liste suit le segment joué, la
 * partition la note jouée.
 *
 *  • `WamaFollow.into(container, el)` : amène `el` en vue s'il sort du cadre visible de `container`
 *    — `scrollIntoView`, qui fait défiler le cadre ET la page quand c'est la page qui défile (une
 *    brique assez haute pour tout contenir ne défile pas elle-même : la partition sous un transport
 *    épinglé). Rien ne bouge tant que `el` est en vue.
 *  • `WamaFollow.lock(storeKey, labels)` : le BOUTON verrou (cadenas), son état gardé par le
 *    navigateur du lecteur (`localStorage`, un confort, jamais un réglage) → `{button, locked(),
 *    toggle()}`. Verrou mis, la brique suit même pendant qu'on édite ; ôté, elle ne suit que hors
 *    édition — la règle de la page d'origine. Le raccourci (Alt+L) se déclare au registre des
 *    briques (`surfaces.Shortcut`, `targets`) et s'appelle `toggle()` dans le clavier de la brique.
 */
(function (global) {
    'use strict';

    var MARGIN_PX = 8;

    function into(container, el) {
        if (!container || !el || !el.getBoundingClientRect) return;
        var box = container.getBoundingClientRect(), r = el.getBoundingClientRect();
        if (r.top < box.top + MARGIN_PX || r.bottom > box.bottom - MARGIN_PX) {
            el.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
    }

    function lock(storeKey, labels) {
        labels = labels || {};
        var locked = false;
        try { locked = localStorage.getItem(storeKey) === '1'; } catch (e) { locked = false; }
        var button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm py-0';
        function paint() {
            button.classList.toggle('btn-info', locked);
            button.classList.toggle('btn-outline-emphasis', !locked);
            button.setAttribute('aria-pressed', locked ? 'true' : 'false');
            button.innerHTML = locked ? '<i class="fas fa-lock"></i>' : '<i class="fas fa-lock-open"></i>';
            button.title = locked ? (labels.on || 'Suivi de lecture ACTIVÉ — clic pour débrayer (Alt+L)')
                                  : (labels.off || 'Suivre la lecture, même en édition (Alt+L)');
        }
        var api = {
            button: button,
            locked: function () { return locked; },
            /** Bascule le verrou ; `onLock` (si donné) est appelé quand il se MET — la brique y
             *  ramène aussitôt en vue ce qui est joué. */
            toggle: function () {
                locked = !locked;
                try { localStorage.setItem(storeKey, locked ? '1' : '0'); } catch (e) { /* sans stockage */ }
                paint();
                if (locked && typeof api.onLock === 'function') api.onLock();
            },
            onLock: null,
        };
        button.addEventListener('click', api.toggle);
        paint();
        return api;
    }

    global.WamaFollow = { into: into, lock: lock };
})(window);
