/**
 * wama-surface.js — le NOYAU d'une surface : une page d'édition COMPOSÉE de briques
 * (chantier SURFACES, 2026-10-10 ; déclaration : `wama/common/surfaces.py`).
 *
 * Ce que fait le noyau, et lui seul — une brique n'en réécrit rien :
 *   • la GRILLE (gridstack) : chaque brique est un élément déplaçable par son titre et
 *     redimensionnable ; la disposition se garde PAR COMPTE (route `layout`, 2026-10-21 — le
 *     stockage du navigateur ne sert plus qu'en secours) et se réinitialise à celle que la
 *     surface déclare. Elle se FIGE (`ctx.setFrozen`) : la grille ne bouge plus et les panneaux
 *     prennent un habit fini ; une surface jamais disposée s'ouvre FIGÉE (pour tous depuis le
 *     2026-10-21, décision de Fabien). Deux ZONES : la grille du centre et la COLONNE du volet
 *     droit (`.wama-surface-panel`, `zone='panel'`), où l'on réordonne et règle la hauteur ; une
 *     brique passe de l'une à l'autre en la glissant, sans être remontée.
 *     Sous 768 px de fenêtre, les panneaux s'empilent sur une colonne (rien n'est alors gardé) ;
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
 * `redone` (le process rejoué par « Appliquer » et son aval ont réussi : les médias lus sont neufs),
 * `layout` (la disposition vient d'être figée ou rendue modifiable : `{frozen}`), `bands` (des
 * plages du temps qu'une brique MARQUE — `{key, bands: [{start, end, color}]}`, une liste par
 * brique, `end` nul = jusqu'à la tête de lecture — que les vues du temps dessinent), `source` (la
 * VERSION écoutée d'un média lu a changé — `{role, key}` ; 2026-10-21 : l'original, ou la sortie
 * d'un process du même type, `Surface.sources_of` — que le transport recharge et dont la ligne de
 * temps relit les pics).
 *
 * L'AXE PARTAGÉ (2026-10-15, `wama-axis.js`) : `ctx.axis()` rend LE temps de la surface — un
 * seul par page, créé au premier appel. Le transport le pilote, les vues s'y abonnent ; une
 * brique ne parle jamais à une autre (`WAMA_DATA_WORLD §5bis`). Quatre niveaux depuis le
 * 2026-10-21 : l'axe, le transport (`media_transport`), les vues (`media_timeline`,
 * `score_view`, `segment_list`), les outils de domaine (`playback_writing`). Un emplacement
 * peut nommer son titre (`options.title`) : la même brique sert deux rôles sur une page.
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
 *
 * Depuis la correction du TRANSCRIBER devenue surface (2026-10-21, ROUTE §F3b), ce que la surface
 * DÉCLARE (`common/surfaces.py`) : enregistrement automatique après une pause (`autosave`), geste
 * « Terminer » (`ctx.finish()`, un enregistrement marqué fini), RÉGLAGES de l'élément lus et écrits
 * par la route commune des réglages (`ctx.settings()`, `ctx.saveSettings()`, événement `settings`),
 * routes de geste de l'app (`ctx.config.routes`), pics fins d'un média lu (`ctx.peaks(rôle)`).
 * `ctx.edit(fn, {inPlace: true})` MODIFIE la valeur sans la copier (une frappe dans une longue
 * transcription) ; `{untracked: true}` ne fait pas de cran (une case « revu », qui ne s'annulait
 * pas dans la page d'origine).
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
        var state = { reads: {}, media: {}, sources: {}, chosen: {}, context: {}, value: {}, saved: '{}',
                      selected: null, token: '', settings: { schema: [], values: {} } };
        var axis = null;
        var conflicted = false;
        var inFlight = null, queued = false, finishing = false;
        var autosaveTimer = null;
        var AUTOSAVE_MS = 800;              // la pause de l'enregistrement automatique de l'éditeur
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
            var d = dirty();
            status(d ? 'Modifications non enregistrées' : '', d ? 'dirty' : '');
            emit('change', state.value);
            if (d && surface.autosave && ctx.canEdit && !conflicted) {
                clearTimeout(autosaveTimer);
                autosaveTimer = setTimeout(function () { save(); }, AUTOSAVE_MS);
            }
        }

        var ctx = {
            config: config,
            canEdit: !!config.can_edit,
            reads: function () { return state.reads; },
            /** `{rôle: {peaks, duration}}` des médias lus que le serveur a préparés (pics d'un audio long). */
            media: function () { return state.media; },
            /** `{rôle: [{key, label, url, peaks?}]}` : les VERSIONS d'un média lu entre lesquelles
             *  choisir ce qu'on écoute (l'original d'abord, `key` vide) — absent : rien à choisir. */
            sources: function () { return state.sources; },
            /** La version écoutée d'un rôle : l'entrée de `sources()`, sinon celle du rôle lu. */
            source: function (role) {
                var list = state.sources[role] || [];
                var key = state.chosen[role] || '';
                for (var i = 0; i < list.length; i++) if (list[i].key === key) return list[i];
                return { key: '', url: state.reads[role] || '', peaks: state.media[role] };
            },
            /** Choisit la version écoutée d'un rôle ; émet `source` (`{role, key}`). */
            setSource: function (role, key) {
                state.chosen[role] = key || '';
                emit('source', { role: role, key: state.chosen[role] });
            },
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
                opts = opts || {};
                if (opts.untracked) { /* pas de cran : un état de relecture, pas une correction */ }
                else if (opts.burst) history.beginBurst(); else history.push();
                var next = fn(opts.inPlace ? state.value : clone(state.value));
                state.value = next === undefined ? state.value : next;
                changed();
            },
            /** Les RÉGLAGES déclarés de l'élément : `{schema, values}`. */
            settings: function () { return state.settings; },
            /** Écrit des réglages par la route commune des réglages de l'app ; émet `settings`. */
            saveSettings: saveSettings,
            /** « Terminer » : enregistre la valeur, marquée finie (`Surface.finish`). */
            finish: function () { finishing = true; clearTimeout(autosaveTimer); return save(); },
            /** Les pics fins d'un média lu : promesse de `{status, peaks?, duration?}`. `poll` :
             *  une page qui interroge en attendant (un échec n'y est pas retenté). */
            peaks: function (role, poll) {
                var key = state.chosen[role] || '';
                return fetch(config.data_url + '?only=peaks&role=' + encodeURIComponent(role) +
                             (key ? '&source=' + encodeURIComponent(key) : '') + (poll ? '&poll=1' : ''),
                             { credentials: 'same-origin' }).then(App.jsonOrExplain);
            },
            helps: function () { return helps.slice(); },
            selected: function () { return state.selected; },
            select: function (id, opts) {
                state.selected = id;
                emit('select', { id: id, focus: !!(opts && opts.focus) });
            },
            on: on, emit: emit, history: history, dirty: dirty, status: status,
            save: save, apply: apply, resetLayout: resetLayout,
            /** La disposition est-elle figée ? `setFrozen(bool)` la fige ou la rend modifiable
             *  (événement `layout`). Une préférence du LECTEUR : vaut aussi en lecture seule. */
            frozen: function () { return !!layout.frozen; },
            setFrozen: function (on) { setFrozen(on); },
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
            clearTimeout(autosaveTimer);
            // Ce qui part, figé en TEXTE : la valeur peut être modifiée en place pendant le vol, et
            // comparer l'objet à lui-même dirait toujours « rien n'a changé depuis l'envoi ».
            var sentJson = JSON.stringify(state.value);
            var finished = finishing;
            finishing = false;
            var body = { value: state.value, base: state.token };
            if (finished) body.finished = true;
            return App.csrfFetch(config.save_url, App.csrfToken(), {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
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
                if (JSON.stringify(state.value) === sentJson) state.value = res.value;
                (res.stale || []).forEach(function (k) {
                    state.processes = state.processes || {};
                    state.processes[k] = 'STALE';
                });
                emit('saved', res);
                if (res.stale && res.stale.length) emit('processes', state.processes);
                emit('change', state.value);
                // Après `change` : ce qui a été tapé pendant le vol reste « non enregistré ».
                if (dirty()) status('Modifications non enregistrées', 'dirty');
                else if (res.finished) status('Terminé', 'ok');
                else status(res.stale && res.stale.length
                    ? 'Enregistré — à rejouer : ' + res.stale.join(', ') : 'Enregistré', 'ok');
                return true;
            }).catch(function (e) {
                if (finished) finishing = true;             // « Terminer » n'est jamais perdu
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

        // ── Réglages de l'élément (`Surface.settings`) ──────────────────────────────────────
        // La route commune des réglages d'UN élément (`update_settings`), en JSON : la même qui
        // sert la modale ⚙ — un réglage écrit ici se relit partout. Ce n'est pas la valeur éditée :
        // ni cran d'annulation, ni empreinte de conflit (la règle de la modale).
        function saveSettings(values) {
            if (!ctx.canEdit || !config.settings_url) return Promise.resolve(false);
            Object.keys(values || {}).forEach(function (k) { state.settings.values[k] = values[k]; });
            emit('settings', state.settings.values);
            return App.csrfFetch(config.settings_url, App.csrfToken(), {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(values || {}),
            }).then(App.jsonOrExplain).then(function (res) {
                if (res && res.error) throw new Error(res.error);
                return true;
            }).catch(function (e) {
                if (App.toast) App.toast('Réglage non enregistré : ' + e.message, 'danger');
                return false;
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
                        state.sources = res.sources || state.sources;
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
        var COLUMNS = surface.columns || 12;
        var layout = config.layout || { slots: null, frozen: true, stored: false };
        var page = root.closest('.wama-surface-page') || root;
        // La COLONNE du volet (2026-10-21, décision de Fabien) : une seconde zone, d'une colonne —
        // on y réordonne, on y règle la hauteur, une brique passe d'une zone à l'autre en la
        // glissant. Absente (page sans volet), tout reste dans la grille.
        var panelRoot = document.querySelector('.wama-surface-panel');
        var grid = global.GridStack.init({
            column: COLUMNS, cellHeight: CELL_HEIGHT, margin: 6, float: false,
            handle: '.wama-brick-head', resizable: { handles: 'e, se, s, sw, w' },
            staticGrid: !!layout.frozen, acceptWidgets: !!panelRoot,
            // Téléphone : une colonne, les panneaux dans l'ordre de la grille (option de gridstack).
            columnOpts: { breakpointForWindow: true, breakpoints: [{ w: 768, c: 1 }], layout: 'list' },
        }, root);
        var panel = panelRoot ? global.GridStack.init({
            column: 1, cellHeight: CELL_HEIGHT, margin: 6, float: false, minRow: 2,
            handle: '.wama-brick-head', resizable: { handles: 's' },
            staticGrid: !!layout.frozen, acceptWidgets: true,
        }, panelRoot) : null;
        var zones = panel ? [grid, panel] : [grid];
        function showFrozen(on) {
            page.classList.toggle('is-frozen', on);
            if (panelRoot) panelRoot.classList.toggle('is-frozen', on);
        }
        showFrozen(!!layout.frozen);
        /** La zone d'une place : celle qu'elle porte (gardée), sinon celle que l'emplacement
         *  déclare ; une place gardée sans zone date d'avant la colonne : la grille. */
        function zoneOf(slot, place) {
            var zone = place === slot ? (slot.zone || 'grid') : ((place && place.zone) || 'grid');
            return zone === 'panel' && panel ? 'panel' : 'grid';
        }
        function gridOf(zone) { return zone === 'panel' ? panel : grid; }
        function placeIn(zone, place) {
            return zone === 'panel' ? { x: 0, y: place.y, w: 1, h: place.h }
                                    : { x: place.x, y: place.y, w: place.w, h: place.h };
        }
        // Une disposition gardée par ce navigateur AVANT la garde par compte est reprise une fois.
        var migrated = !layout.stored && readLayout(config.layout_key);
        if (migrated) layout.slots = migrated;
        var saved = layout.slots || {};
        var mounted = [];

        // Le titre (la poignée `handle`) existe AVANT que gridstack ne prenne l'élément :
        // gridstack cherche ses poignées une seule fois, à `makeWidget`, et faute d'en trouver
        // rend TOUTE la brique déplaçable — un glisser dans l'image (redimensionner une zone)
        // devenait, après quelques pixels, un déplacement de la brique (relevé par Fabien,
        // 2026-10-13). D'où l'élément construit à la main plutôt que `addWidget`.
        function frame(slot) {
            var place = saved[slot.id] || slot;
            var zone = zoneOf(slot, place);
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
            var target = gridOf(zone);
            target.el.appendChild(el);
            var at = placeIn(zone, place);
            at.id = slot.id;
            target.makeWidget(el, at);
            if (!def.mount) {
                body.textContent = 'Brique « ' + slot.brick + ' » non chargée.';
                return null;
            }
            var brick = def.mount(body, ctx, slot.options || {}) || {};
            if (brick.tools) { head.appendChild(brick.tools); head.classList.add('has-tools'); }
            if (brick.help) helps.push(brick.help);
            return { slot: slot, el: el, brick: brick };
        }

        function layoutNow() {
            var out = {};
            zones.forEach(function (g) {
                var zone = g === panel ? 'panel' : 'grid';
                g.getGridItems().forEach(function (el) {
                    var n = el.gridstackNode;
                    if (n && n.id) out[n.id] = { x: n.x, y: n.y, w: n.w, h: n.h, zone: zone };
                });
            });
            return out;
        }

        // La disposition part au serveur une fois le geste posé (un glisser émet plusieurs
        // `change`) ; refusée ou injoignable, elle reste dans ce navigateur, en secours.
        var persistTimer = null;
        function persistLayout() {
            clearTimeout(persistTimer);
            persistTimer = setTimeout(function () {
                if (!config.layout_url) { writeLayout(config.layout_key, layout.slots); return; }
                App.csrfFetch(config.layout_url, App.csrfToken(), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ slots: layout.slots, frozen: !!layout.frozen }),
                }).then(App.jsonOrExplain).then(function (res) {
                    if (res && res.error) throw new Error(res.error);
                    writeLayout(config.layout_key, null);
                }).catch(function () { writeLayout(config.layout_key, layout.slots); });
            }, 300);
        }
        if (migrated) persistLayout();

        /** Sur une colonne (téléphone), la grille n'est qu'un empilement : rien ne se garde. */
        function onFullGrid() { return grid.getColumn() === COLUMNS; }

        // Le montage des briques ajoute leurs éléments aux zones (`added`) : ce n'est pas un geste.
        var resetting = false, building = false;
        function resetLayout() {
            if (layout.frozen || !onFullGrid()) return;
            layout.slots = null;                 // la disposition DÉCLARÉE, qui suit la surface
            resetting = true;
            zones.forEach(function (g) { g.batchUpdate(); });
            surface.slots.forEach(function (slot) {
                var m = mounted.filter(function (x) { return x && x.slot.id === slot.id; })[0];
                if (!m) return;
                var zone = zoneOf(slot, slot), target = gridOf(zone), at = placeIn(zone, slot);
                var from = m.el.gridstackNode && m.el.gridstackNode.grid;
                if (from && from !== target) {
                    // Rendue à sa zone déclarée : le même élément change de grille, la brique
                    // montée ne se remonte pas.
                    from.removeWidget(m.el, false, false);
                    target.el.appendChild(m.el);
                    at.id = slot.id;
                    target.makeWidget(m.el, at);
                } else {
                    target.update(m.el, at);
                }
            });
            zones.forEach(function (g) { g.batchUpdate(false); });
            resetting = false;
            persistLayout();
            emit('resize');
        }

        /** FIGER : la grille ne bouge plus, les panneaux perdent leur habit d'atelier (CSS
         *  `.is-frozen`) ; le titre d'un panneau qui porte des outils reste, en bande discrète. */
        function setFrozen(on) {
            layout.frozen = !!on;
            zones.forEach(function (g) { g.setStatic(layout.frozen); });
            showFrozen(layout.frozen);
            persistLayout();
            emit('layout', { frozen: layout.frozen });
            emit('resize');
        }

        // Un geste posé dans l'une des deux zones — y compris une brique glissée de l'une à
        // l'autre (`added` / `removed`) — garde la disposition ENTIÈRE, les deux zones ensemble.
        // ⚠ Pas `changed` : c'est le nom du geste de VALEUR (`ctx.edit`), plus haut — une seconde
        // déclaration le remplacerait dans toute la fonction (vécu : la parité de l'éditeur l'a vu).
        function layoutChanged() {
            if (resetting || building || !onFullGrid()) return;
            layout.slots = layoutNow();
            persistLayout();
        }
        zones.forEach(function (g) {
            g.on('change added removed', layoutChanged);
            g.on('resizestop', function () { emit('resize'); });
            g.on('added', function () { emit('resize'); });      // la brique a changé de largeur
        });
        // Une brique venue du volet arrive dans la grille avec la largeur de la colonne (1) : on lui
        // donne celle de la colonne de droite d'une surface (un tiers), qu'on retaille ensuite.
        var FROM_PANEL_W = Math.round(COLUMNS / 3);
        if (panel) {
            panel.on('removed', function (e, items) {
                (items || []).forEach(function (n) { if (n.el) n.el.dataset.fromPanel = '1'; });
            });
            grid.on('added', function (e, items) {
                if (building || resetting) return;
                (items || []).forEach(function (n) {
                    if (!n.el || !n.el.dataset.fromPanel) return;
                    delete n.el.dataset.fromPanel;
                    if (n.w < FROM_PANEL_W) grid.update(n.el, { w: FROM_PANEL_W });
                });
            });
        }
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
                state.sources = data.sources || {};
                state.context = data.context || {};
                state.value = data.value == null ? {} : data.value;
                state.saved = JSON.stringify(state.value);
                state.token = data.token || '';
                state.processes = data.processes || {};
                if (data.settings) state.settings = { schema: data.settings.schema || [],
                                                      values: data.settings.values || {} };
                ctx.canEdit = !!data.can_edit;
                history.reset();
                building = true;
                try { surface.slots.forEach(function (slot) { mounted.push(frame(slot)); }); }
                finally { building = false; }
                status(ctx.canEdit ? '' : 'Lecture seule', ctx.canEdit ? '' : 'readonly');
                emit('change', state.value);
                holdLock();
            })
            .catch(function (e) { status('Chargement impossible : ' + e.message, 'error'); });

        return ctx;
    }

    global.WamaSurface = { registerBrick: registerBrick, mount: mount };
})(window);
