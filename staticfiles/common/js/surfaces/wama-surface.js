/**
 * wama-surface.js — le NOYAU d'une surface : une page d'édition COMPOSÉE de briques
 * (chantier SURFACES, 2026-10-10 ; déclaration : `wama/common/surfaces.py`).
 *
 * Ce que fait le noyau, et lui seul — une brique n'en réécrit rien :
 *   • la GRILLE (gridstack) : chaque brique est un élément déplaçable par son titre et
 *     redimensionnable ; la disposition se garde pour cet utilisateur (stockage local) et se
 *     réinitialise à celle que la surface déclare ;
 *   • le CONTEXTE partagé : ce que la page lit (`reads`), la valeur ÉDITÉE (la seule donnée que
 *     la page écrit), la SÉLECTION commune et un bus d'événements entre briques ;
 *   • l'HISTORIQUE commun de WAMA (`wama-history.js`) : chaque geste d'édition passe par
 *     `ctx.edit()`, qui marque le cran AVANT de muter (contrat `push()`) ;
 *   • l'ENREGISTREMENT (le champ déclaré, validé côté serveur) et « Appliquer » (le process que
 *     la modification périme, par la route commune `<app>:start_process`).
 *
 * Contrat d'une brique :
 *     WamaSurface.registerBrick('clé', {
 *         title: 'Titre affiché',
 *         mount: function (body, ctx, options) { … ; return { refresh: fn?, tools: el? }; },
 *     });
 * `refresh()` est rappelé quand la valeur change (`change`) ou que l'élément est redimensionné
 * (`resize`). Événements du bus : `change`, `select`, `resize`, `saved`, `focus`.
 */
(function (global) {
    'use strict';

    var BRICKS = {};
    var CELL_HEIGHT = 46;

    function registerBrick(key, def) { BRICKS[key] = def; }

    function clone(v) { return JSON.parse(JSON.stringify(v == null ? {} : v)); }

    function readLayout(key) {
        try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
    }
    function writeLayout(key, value) {
        try {
            if (value) localStorage.setItem(key, JSON.stringify(value));
            else localStorage.removeItem(key);
        } catch (e) { /* stockage indisponible : la disposition déclarée reste */ }
    }

    function mount(root, config) {
        var App = global.WamaApp || {};
        var surface = config.surface;
        var listeners = {};
        var statusEl = document.querySelector('.wama-surface-status');
        var state = { reads: {}, context: {}, value: {}, saved: '{}', selected: null };

        function on(name, fn) { (listeners[name] = listeners[name] || []).push(fn); }
        function emit(name, payload) {
            (listeners[name] || []).forEach(function (fn) {
                try { fn(payload); } catch (e) { console.error('[surface]', name, e); }
            });
        }
        function status(text, kind) {
            if (!statusEl) return;
            statusEl.textContent = text || '';
            statusEl.dataset.kind = kind || '';
        }

        var history = global.WamaHistory.create({
            snapshot: function () { return clone(state.value); },
            restore: function (s) { state.value = s; changed(); },
            shortcuts: true, burstWindow: 0,
        });

        function dirty() { return JSON.stringify(state.value) !== state.saved; }
        function changed() {
            status(dirty() ? 'Modifications non enregistrées' : '', dirty() ? 'dirty' : '');
            emit('change', state.value);
        }

        var ctx = {
            config: config,
            canEdit: !!config.can_edit,
            reads: function () { return state.reads; },
            context: function () { return state.context; },
            value: function () { return state.value; },
            /** UN geste d'édition = un cran d'historique : `fn(copie)` rend la nouvelle valeur. */
            edit: function (fn) {
                if (!ctx.canEdit) return;
                history.push();
                state.value = fn(clone(state.value)) || state.value;
                changed();
            },
            selected: function () { return state.selected; },
            select: function (id, opts) {
                state.selected = id;
                emit('select', { id: id, focus: !!(opts && opts.focus) });
            },
            on: on, emit: emit, history: history, dirty: dirty, status: status,
            save: save, apply: apply, resetLayout: resetLayout,
        };

        function save() {
            if (!ctx.canEdit) return Promise.resolve(false);
            status('Enregistrement…', 'busy');
            return App.csrfFetch(config.save_url, App.csrfToken(), {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: state.value }),
            }).then(App.jsonOrExplain).then(function (res) {
                if (res.error) throw new Error(res.error);
                state.value = res.value || {};
                state.saved = JSON.stringify(state.value);
                status(res.stale && res.stale.length
                    ? 'Enregistré — à rejouer : ' + res.stale.join(', ') : 'Enregistré', 'ok');
                emit('saved', res);
                emit('change', state.value);
                return true;
            }).catch(function (e) {
                status('Échec : ' + e.message, 'error');
                if (App.toast) App.toast('Enregistrement impossible : ' + e.message, 'danger');
                return false;
            });
        }

        function apply() {
            if (!config.run_url) return save();
            return (dirty() ? save() : Promise.resolve(true)).then(function (ok) {
                if (!ok) return false;
                status('Lancement…', 'busy');
                return App.csrfFetch(config.run_url, App.csrfToken(), { method: 'POST' })
                    .then(App.jsonOrExplain).then(function (res) {
                        if (res && res.error) throw new Error(res.error);
                        status('Relancé : ' + (surface.reruns || ''), 'ok');
                        if (App.toast) App.toast('Traitement relancé', 'success');
                        return true;
                    }).catch(function (e) {
                        status('Échec du lancement : ' + e.message, 'error');
                        return false;
                    });
            });
        }

        // ── Grille ────────────────────────────────────────────────────────────────────────
        var grid = global.GridStack.init({
            column: surface.columns || 12, cellHeight: CELL_HEIGHT, margin: 6, float: false,
            handle: '.wama-brick-head', resizable: { handles: 'e, se, s, sw, w' },
        }, root);
        var saved = readLayout(config.layout_key) || {};
        var mounted = [];

        function frame(slot) {
            var place = saved[slot.id] || slot;
            var el = grid.addWidget({ id: slot.id, x: place.x, y: place.y, w: place.w, h: place.h });
            var content = el.querySelector('.grid-stack-item-content');
            var def = BRICKS[slot.brick] || {};
            var head = document.createElement('div');
            head.className = 'wama-brick-head';
            var title = document.createElement('span');
            title.className = 'wama-brick-title';
            title.textContent = def.title || (surface.bricks[slot.brick] || {}).name || slot.brick;
            head.appendChild(title);
            var body = document.createElement('div');
            body.className = 'wama-brick-body';
            content.appendChild(head);
            content.appendChild(body);
            if (!def.mount) {
                body.textContent = 'Brique « ' + slot.brick + ' » non chargée.';
                return null;
            }
            var brick = def.mount(body, ctx, slot.options || {}) || {};
            if (brick.tools) head.appendChild(brick.tools);
            return { slot: slot, el: el, brick: brick };
        }

        function layoutNow() {
            var out = {};
            grid.getGridItems().forEach(function (el) {
                var n = el.gridstackNode;
                if (n && n.id) out[n.id] = { x: n.x, y: n.y, w: n.w, h: n.h };
            });
            return out;
        }

        function resetLayout() {
            writeLayout(config.layout_key, null);
            grid.batchUpdate();
            surface.slots.forEach(function (slot) {
                var m = mounted.filter(function (x) { return x && x.slot.id === slot.id; })[0];
                if (m) grid.update(m.el, { x: slot.x, y: slot.y, w: slot.w, h: slot.h });
            });
            grid.batchUpdate(false);
            emit('resize');
        }

        grid.on('change', function () { writeLayout(config.layout_key, layoutNow()); });
        grid.on('resizestop', function () { emit('resize'); });
        global.addEventListener('resize', function () { emit('resize'); });

        on('change', function () { mounted.forEach(function (m) { m && m.brick.refresh && m.brick.refresh(); }); });
        on('resize', function () { mounted.forEach(function (m) { m && m.brick.refresh && m.brick.refresh(); }); });

        global.addEventListener('beforeunload', function (ev) {
            if (dirty()) { ev.preventDefault(); ev.returnValue = ''; }
        });

        status('Chargement…', 'busy');
        fetch(config.data_url, { credentials: 'same-origin' }).then(App.jsonOrExplain)
            .then(function (data) {
                if (data.error) throw new Error(data.error);
                state.reads = data.reads || {};
                state.context = data.context || {};
                state.value = data.value || {};
                state.saved = JSON.stringify(state.value);
                ctx.canEdit = !!data.can_edit;
                history.reset();
                surface.slots.forEach(function (slot) { mounted.push(frame(slot)); });
                status(ctx.canEdit ? '' : 'Lecture seule', ctx.canEdit ? '' : 'readonly');
                emit('change', state.value);
            })
            .catch(function (e) { status('Chargement impossible : ' + e.message, 'error'); });

        return ctx;
    }

    global.WamaSurface = { registerBrick: registerBrick, mount: mount };
})(window);
