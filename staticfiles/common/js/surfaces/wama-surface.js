/**
 * wama-surface.js — le NOYAU d'une surface : une page d'édition COMPOSÉE de briques
 * (chantier SURFACES, 2026-10-10 ; déclaration : `wama/common/surfaces.py`).
 *
 * Ce que fait le noyau, et lui seul — une brique n'en réécrit rien :
 *   • la DISPOSITION, par la brique commune `wama-brick-layout.js` (sortie de ce noyau le
 *     2026-10-28, pour que les pages d'apps la montent sans lui) : la grille et la COLONNE du
 *     volet droit (`.wama-surface-panel`, `zone='panel'`), figer (`ctx.setFrozen`), empiler,
 *     épingler à un bord, glisser vers les bords, la disposition gardée PAR COMPTE (route
 *     `layout`) ; une surface jamais disposée s'ouvre FIGÉE. Le noyau lui passe ce que la surface
 *     déclare et monte chaque brique dans le cadre qu'elle pose ;
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
 *
 * UN AUTRE CHAMP ÉDITÉ (2026-10-22, la partition complète du composer, `Surface.also_edits`) :
 * `ctx.retarget(champ)` enregistre ce qui est en cours, relit la valeur de ce champ et en fait
 * la valeur éditée — l'historique repart de là ; `''` revient au champ principal. Événement
 * `target` (`{field}`) ; `ctx.target()` dit le champ édité.
 */
(function (global) {
    'use strict';

    var BRICKS = {};

    function registerBrick(key, def) { BRICKS[key] = def; }

    function clone(v) { return JSON.parse(JSON.stringify(v == null ? {} : v)); }


    /** La version écoutée GARDÉE sur la card, par rôle (le réglage `setting`, `Surface.
     *  sources_setting`) — seulement une version que le serveur propose encore : un process
     *  décoché, une sortie libérée, laissent l'original. Lue AVANT le montage des briques, qui
     *  jouent `ctx.source(rôle)` à leur montage. Pure (testée en V8). */
    function keptSources(sources, values, setting) {
        var kept = (setting && (values || {})[setting]) || {};
        var chosen = {};
        Object.keys(sources || {}).forEach(function (role) {
            var key = kept[role];
            if (key && (sources[role] || []).some(function (v) { return v.key === key; })) {
                chosen[role] = key;
            }
        });
        return chosen;
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
        var target = '';                    // le champ édité : '' = le principal de la surface
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
            /** Choisit la version écoutée d'un rôle ; émet `source` (`{role, key}`). La surface qui
             *  le déclare (`sources_setting`) GARDE ce choix sur la card, par la route commune des
             *  réglages : la prochaine ouverture le reprend (2026-10-22). */
            setSource: function (role, key) {
                state.chosen[role] = key || '';
                emit('source', { role: role, key: state.chosen[role] });
                if (surface.sources_setting) {
                    var kept = {}, values = {};
                    Object.keys(state.chosen).forEach(function (r) {
                        if (state.chosen[r]) kept[r] = state.chosen[r];
                    });
                    values[surface.sources_setting] = kept;
                    saveSettings(values);
                }
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
            /** Les raccourcis clavier des briques montées, tels que le REGISTRE les déclare
             *  (`UIBrick.shortcuts`, 2026-10-29) : `[{title, items: [{label, action, scope}]}]`, une
             *  fois par brique, ceux qu'une option d'emplacement conditionne seulement si elle est
             *  posée. Une brique tait les siens en rendant `keys: false` (une partition seulement
             *  lue). */
            shortcuts: function () {
                var seen = {}, groups = [];
                mounted.forEach(function (rec) {
                    var key = rec && rec.slot && rec.slot.brick;
                    var declared = (surface.bricks[key] || {}).shortcuts || [];
                    if (!key || seen[key] || (rec.brick && rec.brick.keys === false)) return;
                    var options = rec.slot.options || {};
                    var items = declared.filter(function (s) { return !s.option || options[s.option]; });
                    if (!items.length) return;
                    seen[key] = true;
                    groups.push({ title: options.title || (rec.def || {}).title
                                         || (surface.bricks[key] || {}).name || key, items: items });
                });
                return groups;
            },
            selected: function () { return state.selected; },
            select: function (id, opts) {
                state.selected = id;
                emit('select', { id: id, focus: !!(opts && opts.focus) });
            },
            on: on, emit: emit, history: history, dirty: dirty, status: status,
            save: save, apply: apply, resetLayout: resetLayout,
            /** Le champ édité : '' = le principal, sinon l'un des `also_edits` de la surface. */
            target: function () { return target; },
            retarget: retarget,
            /** La disposition est-elle figée ? `setFrozen(bool)` la fige ou la rend modifiable
             *  (événement `layout`). Une préférence du LECTEUR : vaut aussi en lecture seule. */
            frozen: function () { return layout.frozen(); },
            setFrozen: function (on) { layout.setFrozen(on); },
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
            if (target) body.field = target;
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

        /** Édite un autre champ (`Surface.also_edits`), ou le principal (`''`) : ce qui est en
         *  cours s'enregistre d'abord ; la valeur du champ est relue, l'historique repart. */
        function retarget(field) {
            field = field || '';
            if (field === target) return Promise.resolve(true);
            if (field && (surface.also_edits || []).indexOf(field) < 0) return Promise.resolve(false);
            return (dirty() && ctx.canEdit ? save() : Promise.resolve(true)).then(function (ok) {
                if (!ok) return false;
                status('Chargement…', 'busy');
                return fetch(config.data_url + (field ? '?field=' + encodeURIComponent(field) : ''),
                             { credentials: 'same-origin' })
                    .then(App.jsonOrExplain).then(function (data) {
                        if (data.error) throw new Error(data.error);
                        target = field;
                        state.value = data.value == null ? {} : data.value;
                        state.saved = JSON.stringify(state.value);
                        state.token = data.token || '';
                        history.reset();
                        status(ctx.canEdit ? '' : 'Lecture seule', ctx.canEdit ? '' : 'readonly');
                        emit('target', { field: field });
                        emit('change', state.value);
                        return true;
                    });
            }).catch(function (e) {
                status('Chargement impossible : ' + e.message, 'error');
                return false;
            });
        }

        function apply() {
            // Le process rejoué lit le champ PRINCIPAL : un autre champ édité ne fait qu'enregistrer.
            if (!config.run_url || target) return save();
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

        // ── Disposition : la brique commune `wama-brick-layout.js` (2026-10-28) ────────────────
        // La grille et la colonne du volet, figer, empiler, épingler, glisser vers les bords, la
        // disposition gardée par compte : sortis de ce noyau pour que les pages d'apps les montent
        // sans lui. Le noyau lui passe ce que la surface déclare et monte les briques dans les
        // cadres qu'elle pose.
        var mounted = [];
        var layout = global.WamaBrickLayout.create({
            root: root, page: root.closest('.wama-surface-page') || root,
            panelRoot: document.querySelector('.wama-surface-panel'),
            slots: surface.slots, columns: surface.columns,
            maxRows: surface.max_rows, dockEdges: surface.dock_edges,
            layout: config.layout, url: config.layout_url, key: config.layout_key,
            defOf: function (slot) { return BRICKS[slot.brick] || {}; },
            titleOf: function (slot, def) {
                return (slot.options || {}).title || def.title
                    || (surface.bricks[slot.brick] || {}).name || slot.brick;
            },
            mount: mountBrick,
            emit: emit,
        });
        function resetLayout() { layout.reset(); }

        /** Les CONTRÔLES DE PAGE de l'en-tête (`wama-page-controls.js`, 2026-10-29) : la surface y
         *  déclare sa disposition (le cadenas et son bandeau), les raccourcis des briques montées
         *  et leurs gestes (l'aide de la page) — la brique Actions ne les porte plus. */
        function offerToPage() {
            var controls = global.WamaPageControls;
            if (!controls) return;
            controls.offerLayout({
                subject: 'de la page',
                frozen: function () { return layout.frozen(); },
                setFrozen: function (on) { layout.setFrozen(on); },
                reset: resetLayout,
            });
            controls.addShortcuts(ctx.shortcuts);
            controls.addHelp(ctx.helps);
            on('layout', controls.layoutChanged);
        }

        /** Monte une brique dans le cadre que la disposition lui a posé (ses outils dans le titre). */
        function mountBrick(rec) {
            var def = rec.def;
            if (!def.mount) {
                rec.body.textContent = 'Brique « ' + rec.slot.brick + ' » non chargée.';
            } else {
                rec.brick = def.mount(rec.body, ctx, rec.slot.options || {}) || {};
                if (rec.brick.tools) {
                    rec.head.appendChild(rec.brick.tools);
                    rec.head.classList.add('has-tools');
                    rec.hasTools = true;
                }
                if (rec.brick.help) helps.push(rec.brick.help);
            }
            mounted.push(rec);
        }

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
                state.chosen = keptSources(state.sources, state.settings.values,
                                           surface.sources_setting);
                ctx.canEdit = !!data.can_edit;
                history.reset();
                layout.build();
                offerToPage();
                status(ctx.canEdit ? '' : 'Lecture seule', ctx.canEdit ? '' : 'readonly');
                emit('change', state.value);
                holdLock();
            })
            .catch(function (e) { status('Chargement impossible : ' + e.message, 'error'); });

        return ctx;
    }

    global.WamaSurface = { registerBrick: registerBrick, mount: mount, keptSources: keptSources };
})(window);
