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
 *         mount: function (body, ctx, options) { … ; return { refresh: fn?, tools: el?, help: '…'? }; },
 *     });
 * `refresh()` est rappelé quand la valeur change (`change`) ou que l'élément est redimensionné
 * (`resize`). `help` : les gestes de la brique, que la brique d'actions affiche (`ctx.helps()`).
 * Événements du bus : `change`, `select`, `resize`, `saved`, `applied`, `focus`, `processes`,
 * `redone` (le process rejoué par « Appliquer » et son aval ont réussi : les médias lus sont neufs).
 *
 * L'AXE PARTAGÉ (2026-10-15, `wama-axis.js`) : `ctx.axis()` rend LE temps de la surface — un
 * seul par page, créé au premier appel. Le transport le pilote, les vues s'y abonnent ; une
 * brique ne parle jamais à une autre (`WAMA_DATA_WORLD §5bis`). Un emplacement peut nommer son
 * titre (`options.title`) : la même brique sert deux rôles sur une page.
 *
 * Un geste de FRAPPE passe `ctx.edit(fn, {burst: true})` : une rafale = UN cran d'annulation
 * (`WamaHistory.beginBurst`, la règle de la page de correction du Transcriber). Un geste
 * structurel (tracer, déplacer, retirer) reste un cran à lui seul.
 *
 * CONFLIT et VERROU DOUX (2026-10-13, `WAMA_COLLABORATION §2.4`, portés de la page de correction
 * du Transcriber pour toutes les surfaces) : chaque enregistrement dit de quel état il part
 * (`base`) ; un état périmé est refusé (409) et la page cesse d'enregistrer en proposant de
 * recharger. UN SEUL enregistrement en vol : demandé pendant le vol, il part avec l'empreinte que
 * la réponse rend. Le verrou doux (`WamaCardMenu.holdEditLock`) dit qui d'autre édite.
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
        var state = { reads: {}, media: {}, context: {}, value: {}, saved: '{}', selected: null, token: '' };
        var axis = null;
        var conflicted = false;
        var inFlight = null, queued = false;
        var helps = [];

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
            shortcuts: true,
        });

        /** Un bandeau au-dessus de la grille (conflit, verrou doux) — un seul par nature. */
        function banner(kind, cls, html) {
            var host = root.parentNode;
            var shown = host.querySelector('[data-surface-banner="' + kind + '"]');
            if (!html) { if (shown) shown.remove(); return null; }
            if (!shown) {
                shown = document.createElement('div');
                shown.dataset.surfaceBanner = kind;
                host.insertBefore(shown, root);
            }
            shown.className = 'alert small py-2 mb-2 ' + cls;
            shown.innerHTML = html;
            return shown;
        }

        function dirty() { return JSON.stringify(state.value) !== state.saved; }
        function changed() {
            status(dirty() ? 'Modifications non enregistrées' : '', dirty() ? 'dirty' : '');
            emit('change', state.value);
        }

        var ctx = {
            config: config,
            canEdit: !!config.can_edit,
            reads: function () { return state.reads; },
            /** `{rôle: {peaks, duration}}` des médias lus que le serveur a préparés (pics d'un audio long). */
            media: function () { return state.media; },
            context: function () { return state.context; },
            /** L'axe de temps PARTAGÉ de la surface (`WamaAxis`), créé au premier appel ; null si
             *  aucune brique chargée ne l'a demandé (`requires`). */
            axis: function () {
                if (!axis && global.WamaAxis) axis = global.WamaAxis.create();
                return axis;
            },
            /** `{process: état}` de l'élément (`STALE`, `RUNNING`, `SUCCESS`…). */
            processes: function () { return state.processes || {}; },
            value: function () { return state.value; },
            /** UN geste d'édition = un cran d'historique : `fn(copie)` rend la nouvelle valeur.
             *  `{burst: true}` : une frappe — la rafale entière ne fait qu'un cran. */
            edit: function (fn, opts) {
                if (!ctx.canEdit) return;
                if (opts && opts.burst) history.beginBurst(); else history.push();
                var next = fn(clone(state.value));
                state.value = next === undefined ? state.value : next;
                changed();
            },
            helps: function () { return helps.slice(); },
            selected: function () { return state.selected; },
            select: function (id, opts) {
                state.selected = id;
                emit('select', { id: id, focus: !!(opts && opts.focus) });
            },
            on: on, emit: emit, history: history, dirty: dirty, status: status,
            save: save, apply: apply, resetLayout: resetLayout,
        };

        function showConflict(res) {
            conflicted = true;
            status('Non enregistré', 'error');
            var box = banner('conflict', 'alert-danger',
                '<i class="fas fa-code-merge me-1"></i><span></span> ' +
                '<button type="button" class="btn btn-sm btn-light py-0 ms-2">Recharger</button>');
            box.querySelector('span').textContent = (res && res.reason) ||
                'Cet élément a été modifié depuis votre ouverture — rechargez pour reprendre la dernière version.';
            box.querySelector('button').addEventListener('click', function () { location.reload(); });
        }

        function save() {
            if (!ctx.canEdit || conflicted) return Promise.resolve(false);
            if (inFlight) { queued = true; return inFlight; }
            inFlight = send().then(function (ok) {
                inFlight = null;
                if (queued && ok && !conflicted) { queued = false; return save(); }
                queued = false;
                return ok;
            });
            return inFlight;
        }

        function send() {
            status('Enregistrement…', 'busy');
            var sent = state.value;
            return App.csrfFetch(config.save_url, App.csrfToken(), {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ value: sent, base: state.token }),
            }).then(function (response) {
                // 409 et 400 portent un corps JSON qui DIT la raison : lus avant le repli commun.
                if (response.status === 409 || response.status === 400) {
                    return response.json().then(function (res) { res.httpStatus = response.status; return res; });
                }
                return App.jsonOrExplain(response);
            }).then(function (res) {
                if (res.httpStatus === 409) { showConflict(res); return false; }
                if (res.error) throw new Error(res.error);
                if (res.token) state.token = res.token;
                state.saved = JSON.stringify(res.value);
                // Ce qui a été tapé PENDANT le vol reste la valeur éditée ; sinon la valeur
                // assainie du serveur (fins de ligne) la remplace.
                if (JSON.stringify(state.value) === JSON.stringify(sent)) state.value = res.value;
                (res.stale || []).forEach(function (k) {
                    state.processes = state.processes || {};
                    state.processes[k] = 'STALE';
                });
                emit('saved', res);
                if (res.stale && res.stale.length) emit('processes', state.processes);
                emit('change', state.value);
                // Après `change` : ce qui a été tapé pendant le vol reste « non enregistré ».
                if (dirty()) status('Modifications non enregistrées', 'dirty');
                else status(res.stale && res.stale.length
                    ? 'Enregistré — à rejouer : ' + res.stale.join(', ') : 'Enregistré', 'ok');
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
                        emit('applied', res);
                        track(surface.reruns);
                        return true;
                    }).catch(function (e) {
                        status('Échec du lancement : ' + e.message, 'error');
                        return false;
                    });
            });
        }

        // ── Suivi du process rejoué ───────────────────────────────────────────────────────
        // Après « Appliquer », la page relit l'état des process (lecture légère `only=state`)
        // jusqu'à ce que le process rejoué ait FINI — réussi ou échoué ; `STALE` ou en attente,
        // il n'a pas encore été pris — ET que son aval ne tourne plus (2026-10-15 : le rendu du
        // composer est suivi du process de sortie, qui écrit l'audio que la page relit). Chaque
        // relecture émet `processes` ; les rôles lus (`reads`) sont rafraîchis au passage : un
        // rendu refait peut changer d'adresse.
        var TRACK_EVERY_MS = 4000, TRACK_MAX_MS = 20 * 60 * 1000;
        var BUSY = ['PENDING', 'RUNNING', 'AWAITING_RESOURCES'];
        var tracking = null;

        function track(key) {
            if (!key) return;
            clearTimeout(tracking);
            var until = Date.now() + TRACK_MAX_MS;
            function tick() {
                fetch(config.data_url + '?only=state', { credentials: 'same-origin' })
                    .then(App.jsonOrExplain)
                    .then(function (res) {
                        state.reads = res.reads || state.reads;
                        state.media = res.media || state.media;
                        state.processes = res.processes || {};
                        emit('processes', state.processes);
                        var s = state.processes[key];
                        var busy = Object.keys(state.processes).some(function (k) {
                            return BUSY.indexOf(state.processes[k]) >= 0;
                        });
                        if (((s === 'SUCCESS' || s === 'FAILURE') && !busy) || Date.now() > until) {
                            // `redone` : les médias lus ont été refaits — une brique qui les montre
                            // (ou en tire une grille) les recharge ; une règle, pas une par brique.
                            if (s === 'SUCCESS' && !busy) emit('redone', state.reads);
                            return;
                        }
                        tracking = setTimeout(tick, TRACK_EVERY_MS);
                    })
                    .catch(function () { tracking = setTimeout(tick, TRACK_EVERY_MS * 2); });
            }
            tracking = setTimeout(tick, TRACK_EVERY_MS);
        }

        // ── Grille ────────────────────────────────────────────────────────────────────────
        var grid = global.GridStack.init({
            column: surface.columns || 12, cellHeight: CELL_HEIGHT, margin: 6, float: false,
            handle: '.wama-brick-head', resizable: { handles: 'e, se, s, sw, w' },
        }, root);
        var saved = readLayout(config.layout_key) || {};
        var mounted = [];

        // Le titre (la poignée `handle`) existe AVANT que gridstack ne prenne l'élément :
        // gridstack cherche ses poignées une seule fois, à `makeWidget`, et faute d'en trouver
        // rend TOUTE la brique déplaçable — un glisser dans l'image (redimensionner une zone)
        // devenait, après quelques pixels, un déplacement de la brique (relevé par Fabien,
        // 2026-10-13). D'où l'élément construit à la main plutôt que `addWidget`.
        function frame(slot) {
            var place = saved[slot.id] || slot;
            var el = document.createElement('div');
            el.className = 'grid-stack-item';
            var content = document.createElement('div');
            content.className = 'grid-stack-item-content';
            el.appendChild(content);
            var def = BRICKS[slot.brick] || {};
            var head = document.createElement('div');
            head.className = 'wama-brick-head';
            var title = document.createElement('span');
            title.className = 'wama-brick-title';
            title.textContent = (slot.options || {}).title || def.title
                || (surface.bricks[slot.brick] || {}).name || slot.brick;
            head.appendChild(title);
            var body = document.createElement('div');
            body.className = 'wama-brick-body';
            content.appendChild(head);
            content.appendChild(body);
            root.appendChild(el);
            grid.makeWidget(el, { id: slot.id, x: place.x, y: place.y, w: place.w, h: place.h });
            if (!def.mount) {
                body.textContent = 'Brique « ' + slot.brick + ' » non chargée.';
                return null;
            }
            var brick = def.mount(body, ctx, slot.options || {}) || {};
            if (brick.tools) head.appendChild(brick.tools);
            if (brick.help) helps.push(brick.help);
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

        // VERROU DOUX : tenu tant que la page est ouverte par qui peut éditer ; rien n'est refusé
        // à l'ouverture — c'est l'enregistrement qui l'est, s'il part d'un état périmé.
        function holdLock() {
            var menu = global.WamaCardMenu;
            if (!ctx.canEdit || !menu || !menu.holdEditLock) return;
            var release = menu.holdEditLock({ surface: surface.app, pk: config.pk }, function (res) {
                if (!res.held_by_other) { banner('lock', '', null); return; }
                var box = banner('lock', 'alert-warning',
                    '<i class="fas fa-user-pen me-1"></i><b></b> édite cet élément en ce moment. ' +
                    'S’il change avant votre enregistrement, celui-ci sera refusé plutôt que ' +
                    'd’effacer son travail.');
                box.querySelector('b').textContent = res.name || 'Quelqu’un';
            });
            global.addEventListener('pagehide', release);
        }

        status('Chargement…', 'busy');
        fetch(config.data_url, { credentials: 'same-origin' }).then(App.jsonOrExplain)
            .then(function (data) {
                if (data.error) throw new Error(data.error);
                state.reads = data.reads || {};
                state.media = data.media || {};
                state.context = data.context || {};
                state.value = data.value == null ? {} : data.value;
                state.saved = JSON.stringify(state.value);
                state.token = data.token || '';
                state.processes = data.processes || {};
                ctx.canEdit = !!data.can_edit;
                history.reset();
                surface.slots.forEach(function (slot) { mounted.push(frame(slot)); });
                status(ctx.canEdit ? '' : 'Lecture seule', ctx.canEdit ? '' : 'readonly');
                emit('change', state.value);
                holdLock();
            })
            .catch(function (e) { status('Chargement impossible : ' + e.message, 'error'); });

        return ctx;
    }

    global.WamaSurface = { registerBrick: registerBrick, mount: mount };
})(window);
