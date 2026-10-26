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
 *   • GARDER à l'écran (2026-10-26) : des briques EMPILÉES en un seul panneau (`stacks`, la tête
 *     d'abord — affichage seul, chaque brique garde son code et son état) et un panneau ÉPINGLÉ à
 *     un bord de la fenêtre (`docked` : haut, bas, gauche, droite), le centre défilant entre les
 *     bords ; tous deux gardés avec la disposition du compte ;
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
    var CELL_HEIGHT = 46;
    var MAX_ROWS = 400;                     // le plafond de `surfaces.MAX_LAYOUT_ROWS`

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

    /** Les poids d'une pile (`[{id, h}]`) ramenés à `rows` rangées : chaque brique garde sa part
     *  de la hauteur du panneau (au moins une rangée) — ce qu'elle retrouve détachée, ce qu'elle
     *  apporte à une autre pile. Pure (testée en V8). */
    function scaleWeights(list, rows) {
        var total = list.reduce(function (s, e) { return s + (e.h > 0 ? e.h : 1); }, 0) || 1;
        return list.map(function (e) {
            return { id: e.id, h: Math.max(1, Math.round((e.h > 0 ? e.h : 1) * rows / total)) };
        });
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
        //
        // La SECTION (titre + corps) est ce qu'une brique apporte dans un panneau : seule, elle
        // remplit le sien ; EMPILÉE, elle passe dans le panneau du groupe — le même élément, la
        // brique n'est jamais remontée. Deux temps : `build` pose les cadres (et reforme les piles
        // gardées), `mountBrick` monte les briques une fois tout attaché à la page.
        var frames = {};                    // emplacement → {slot, def, el, section, head, body, brick}
        function build(slot, placed) {
            var place = saved[slot.id] || slot;
            var zone = zoneOf(slot, place);
            var el = document.createElement('div');
            el.className = 'grid-stack-item';
            var content = document.createElement('div');
            content.className = 'grid-stack-item-content';
            el.appendChild(content);
            var def = BRICKS[slot.brick] || {};
            var section = document.createElement('div');
            section.className = 'wama-brick-section';
            section.dataset.slot = slot.id;
            var head = document.createElement('div');
            head.className = 'wama-brick-head';
            var title = document.createElement('span');
            title.className = 'wama-brick-title';
            title.textContent = (slot.options || {}).title || def.title
                || (surface.bricks[slot.brick] || {}).name || slot.brick;
            head.appendChild(title);
            var body = document.createElement('div');
            body.className = 'wama-brick-body';
            section.appendChild(head);
            section.appendChild(body);
            content.appendChild(section);
            var rec = { slot: slot, def: def, el: el, section: section, head: head, body: body,
                        brick: {}, zone: zone, place: placeIn(zone, place) };
            frames[slot.id] = rec;
            if (placed) putSolo(slot.id, rec.place, gridOf(zone));
            return rec;
        }

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
            layoutTools(rec);
            return rec;
        }

        // ── EMPILER des briques en UN panneau (2026-10-26, Fabien : « empiler/imbriquer des
        // briques pour les compacter en une seule, uniquement en affichage » — le transport, la
        // ligne de temps et l'écriture à la lecture, qu'on fixe ensemble). Chaque brique garde son
        // code et son état ; seul son CADRE change. Gardé par compte (`stacks` : `{tête: [{id, h}]}`,
        // `surfaces.clean_layout`) ; la tête donne au panneau sa place et son épinglage. Un geste de
        // DISPOSITION : il se fait disposition modifiable, comme déplacer ou redimensionner.
        layout.stacks = layout.stacks || {};
        layout.docked = layout.docked || {};
        var shells = {};                    // tête → l'élément du panneau d'une pile

        function groupOf(id) {
            for (var key in layout.stacks) {
                if (layout.stacks[key].some(function (e) { return e.id === id; })) return key;
            }
            return null;
        }
        /** Les panneaux de la page : une brique seule, ou la tête d'une pile. */
        function containers() {
            return surface.slots.map(function (s) { return s.id; }).filter(function (id) {
                if (!frames[id]) return false;
                var key = groupOf(id);
                return !key || key === id;
            });
        }
        function containerEl(key) { return shells[key] || frames[key].el; }
        // Un panneau ÉPINGLÉ quitte la grille — la page se referme derrière lui — et y retrouve SA
        // place quand on le désépingle : elle est gardée ici, et dans la disposition du compte.
        var dockPlaces = {};                // panneau → {x, y, w, h, grid}
        /** La place d'un panneau dans sa zone, qu'il y soit ou qu'il en soit sorti, épinglé. */
        function placeOf(key) {
            if (dockPlaces[key]) return dockPlaces[key];
            var node = containerEl(key).gridstackNode;
            return node ? { x: node.x, y: node.y, w: node.w, h: node.h, grid: node.grid } : null;
        }
        function titleOf(id) { return frames[id].head.querySelector('.wama-brick-title').textContent; }
        function labelOf(key) {
            return (layout.stacks[key] || [{ id: key }]).map(function (e) { return titleOf(e.id); })
                .join(' + ');
        }
        /** La place d'une zone : la colonne du volet n'a qu'une colonne. */
        function fit(at, g) {
            return g === panel ? { x: 0, y: at.y, w: 1, h: at.h }
                               : { x: at.x, y: at.y, w: Math.min(at.w, COLUMNS), h: at.h };
        }
        function putSolo(id, at, g) {
            var rec = frames[id];
            rec.section.style.flexGrow = '';
            rec.el.querySelector('.grid-stack-item-content').appendChild(rec.section);
            rec.el.dataset.panel = id;
            g.el.appendChild(rec.el);
            var place = fit(at, g);
            place.id = id;
            g.makeWidget(rec.el, place);
        }
        function buildShell(list, at, g) {
            var el = document.createElement('div');
            el.className = 'grid-stack-item wama-brick-stack-shell';
            el.dataset.panel = list[0].id;
            var content = document.createElement('div');
            content.className = 'grid-stack-item-content';
            list.forEach(function (entry) {
                var section = frames[entry.id].section;
                section.style.flexGrow = String(entry.h);     // son poids dans la hauteur du panneau
                content.appendChild(section);
            });
            el.appendChild(content);
            g.el.appendChild(el);
            var place = fit(at, g);
            place.id = list[0].id;
            g.makeWidget(el, place);
            shells[list[0].id] = el;
            return el;
        }
        /** Retire un panneau de sa zone (sans détruire ses briques) : rend sa place et sa zone. */
        function take(key) {
            var el = containerEl(key), node = el.gridstackNode, place = placeOf(key);
            var g = (place && place.grid) || grid;
            var at = place ? { x: place.x, y: place.y, w: place.w, h: place.h } : { x: 0, y: 0, w: 4, h: 4 };
            if (node && node.grid) node.grid.removeWidget(el, false, false);
            if (el.parentNode) el.parentNode.removeChild(el);
            clearDock(el);
            delete shells[key];
            delete dockPlaces[key];
            return { at: at, grid: g };
        }
        /** Ses briques et leur poids, ramenés à sa hauteur actuelle (un panneau a pu être retaillé). */
        function entriesOf(key) {
            var place = placeOf(key), rows = place ? place.h : 1;
            var list = layout.stacks[key];
            if (!list) return [{ id: key, h: rows }];
            return scaleWeights(list, rows);
        }

        function restack(fn) {
            if (layout.frozen) return;
            resetting = true;
            try { fn(); } finally { resetting = false; }
            if (onFullGrid()) layout.slots = layoutNow();
            syncLayoutTools();
            applyDocks();
            persistLayout();
        }
        /** Le panneau `other` (brique ou pile) rejoint celui de `own`, sous ses briques. */
        function join(own, other) {
            restack(function () {
                var a = entriesOf(own), b = entriesOf(other);
                var ta = take(own), tb = take(other);
                delete layout.stacks[own]; delete layout.stacks[other]; delete layout.docked[other];
                var list = a.concat(b);
                layout.stacks[list[0].id] = list;
                buildShell(list, { x: ta.at.x, y: ta.at.y, w: ta.at.w,
                                   h: Math.min(ta.at.h + tb.at.h, MAX_ROWS) }, ta.grid);
            });
        }
        /** Monte ou descend une brique dans sa pile ; la tête peut changer, son épinglage la suit. */
        function moveInStack(id, delta) {
            restack(function () {
                var key = groupOf(id), list = entriesOf(key);
                var i = list.findIndex(function (e) { return e.id === id; }), j = i + delta;
                if (j < 0 || j >= list.length) return;
                var moved = list[i]; list[i] = list[j]; list[j] = moved;
                var edge = layout.docked[key], t = take(key);
                delete layout.stacks[key]; delete layout.docked[key];
                layout.stacks[list[0].id] = list;
                if (edge) layout.docked[list[0].id] = edge;
                buildShell(list, t.at, t.grid);
            });
        }
        /** Sort une brique de sa pile : elle reprend sa hauteur, juste sous le panneau. */
        function detach(id) {
            restack(function () {
                var key = groupOf(id), list = entriesOf(key);
                var gone = list.filter(function (e) { return e.id === id; })[0];
                var rest = list.filter(function (e) { return e.id !== id; });
                var edge = layout.docked[key], t = take(key);
                delete layout.stacks[key]; delete layout.docked[key];
                var restH = Math.max(1, t.at.h - gone.h);
                var at = { x: t.at.x, y: t.at.y, w: t.at.w, h: restH };
                if (rest.length > 1) {
                    layout.stacks[rest[0].id] = rest;
                    buildShell(rest, at, t.grid);
                } else {
                    putSolo(rest[0].id, at, t.grid);
                }
                if (edge) layout.docked[rest[0].id] = edge;
                putSolo(id, { x: t.at.x, y: t.at.y + restH, w: t.at.w, h: gone.h }, t.grid);
            });
        }
        /** Défait toutes les piles, chaque brique à sa hauteur (« Disposition par défaut »). */
        function dissolveAll() {
            Object.keys(layout.stacks).forEach(function (key) {
                var list = entriesOf(key), t = take(key), y = t.at.y;
                list.forEach(function (e) {
                    putSolo(e.id, { x: t.at.x, y: y, w: t.at.w, h: e.h }, t.grid);
                    y += e.h;
                });
            });
            layout.stacks = {};
        }

        // ── GARDER un panneau à l'écran : ÉPINGLÉ à un bord de la fenêtre (2026-10-26, demande de
        // Fabien : « locker le transport […] pour qu'il ne défile pas avec la page », puis le jour
        // même : à gauche et à droite aussi, une colonne fixe pendant que le centre défile). Une
        // bande en haut ou en bas, une colonne à gauche ou à droite ; plusieurs panneaux sur un
        // même bord se rangent l'un après l'autre. Jamais « sur place » au milieu de la page : on
        // choisit un BORD. Gardé avec la disposition (`docked`) : une préférence de LECTURE, valable
        // aussi en lecture seule et disposition figée — pour une brique qui le DÉCLARE (`dockable`,
        // le transport) ou un panneau déjà épinglé ; disposition modifiable, pour tout panneau.
        var DOCK_CHOICES = [
            ['top', 'fa-arrow-up', 'En haut de la fenêtre'],
            ['bottom', 'fa-arrow-down', 'En bas de la fenêtre'],
            ['left', 'fa-arrow-left', 'À gauche — une colonne fixe'],
            ['right', 'fa-arrow-right', 'À droite — une colonne fixe'],
            ['', 'fa-arrows-up-down', 'Dans la page — défile avec elle'],
        ];
        var DOCK_SAID = { top: 'Épinglé en haut de la fenêtre', bottom: 'Épinglé en bas de la fenêtre',
                          left: 'Épinglé à gauche', right: 'Épinglé à droite' };
        var SIDES = ['left', 'right'];

        function toolButton(icon, title, fn) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn btn-xs';
            b.title = title;
            b.setAttribute('aria-label', title);
            b.innerHTML = '<i class="fas ' + icon + '"></i>';
            b.addEventListener('mousedown', function (e) { e.stopPropagation(); });
            b.addEventListener('click', function (e) { e.stopPropagation(); fn(b); });
            return b;
        }
        function openMenu(btn, entries, title) {
            var r = btn.getBoundingClientRect();
            if (global.WamaCardMenu) global.WamaCardMenu.ouvrir(r.left, r.bottom + 4, entries, title);
        }

        function layoutTools(rec) {
            var box = document.createElement('span');
            box.className = 'wama-brick-stack-tools';
            rec.head.appendChild(box);
            rec.stackTools = box;
            if (rec.def.dockable === false) return;
            rec.dockBtn = toolButton('fa-thumbtack', '', function (b) { openDockMenu(rec.slot.id, b); });
            rec.dockBtn.classList.add('wama-brick-dock');
            rec.head.appendChild(rec.dockBtn);
        }

        function openDockMenu(key, btn) {
            var current = layout.docked[key] || '';
            var narrow = !onFullGrid();
            openMenu(btn, DOCK_CHOICES.map(function (c) {
                return {
                    icone: 'fas ' + (c[0] === current ? 'fa-check' : c[1]), libelle: c[2],
                    desactive: c[0] === current || (narrow && SIDES.indexOf(c[0]) >= 0),
                    agir: function () {
                        if (c[0]) layout.docked[key] = c[0]; else delete layout.docked[key];
                        applyDocks();
                        syncLayoutTools();
                        persistLayout();
                    },
                };
            }), 'Garder ce panneau à l’écran');
        }

        function openStackMenu(key, btn) {
            var others = containers().filter(function (k) { return k !== key; });
            openMenu(btn, others.length ? others.map(function (k) {
                return { icone: 'fas fa-layer-group', libelle: labelOf(k),
                         agir: function () { join(key, k); } };
            }) : [{ vide: true, libelle: 'Aucun autre panneau sur la page' }],
            'Empiler dans ce panneau');
        }

        /** Les outils de disposition de chaque titre, d'après les piles et les épinglages. */
        function syncLayoutTools() {
            Object.keys(frames).forEach(function (id) {
                var rec = frames[id], key = groupOf(id), list = key ? layout.stacks[key] : null;
                var i = list ? list.findIndex(function (e) { return e.id === id; }) : 0;
                var box = rec.stackTools;
                if (!box) return;
                box.innerHTML = '';
                if (list && i > 0) box.appendChild(toolButton('fa-chevron-up', 'Monter dans le panneau',
                    function () { moveInStack(id, -1); }));
                if (list && i < list.length - 1) box.appendChild(toolButton('fa-chevron-down',
                    'Descendre dans le panneau', function () { moveInStack(id, 1); }));
                if (list) box.appendChild(toolButton('fa-object-ungroup', 'Détacher du panneau',
                    function () { detach(id); }));
                if (i === 0) box.appendChild(toolButton('fa-layer-group',
                    'Empiler un autre panneau dans celui-ci (une seule bande, fixée ensemble)',
                    function (b) { openStackMenu(key || id, b); }));
                // L'épingle : sur la tête du panneau seulement — c'est le panneau qui s'épingle.
                var dockable = (list || [{ id: id }]).some(function (e) { return frames[e.id].def.dockable; });
                var edge = i === 0 ? (layout.docked[key || id] || '') : '';
                if (rec.dockBtn) {
                    rec.dockBtn.hidden = i !== 0;
                    rec.dockBtn.classList.toggle('active', !!edge);
                    rec.dockBtn.classList.toggle('is-optional', !dockable && !edge);
                    rec.dockBtn.title = (edge ? DOCK_SAID[edge] + ' — ' : '') + 'Garder ce panneau à l’écran…';
                    rec.dockBtn.setAttribute('aria-pressed', edge ? 'true' : 'false');
                }
                rec.head.classList.toggle('has-tools', !!rec.hasTools
                    || !!(rec.dockBtn && i === 0 && (dockable || edge)));
            });
        }

        /** Pose les cadres — les piles gardées reformées, une brique dans une seule —, puis monte
         *  les briques dans l'ordre déclaré, chacune déjà attachée à la page où qu'elle soit. */
        function buildAll() {
            var known = {}, inGroup = {}, groups = {};
            surface.slots.forEach(function (s) { known[s.id] = true; });
            Object.keys(layout.stacks || {}).forEach(function (key) {
                var list = (layout.stacks[key] || []).filter(function (e) {
                    return known[e.id] && !inGroup[e.id];
                });
                if (list.length < 2) return;
                list.forEach(function (e) { inGroup[e.id] = true; });
                groups[list[0].id] = list;
            });
            layout.stacks = groups;
            surface.slots.forEach(function (slot) { build(slot, !inGroup[slot.id]); });
            Object.keys(groups).forEach(function (key) {
                buildShell(groups[key], frames[key].place, gridOf(frames[key].zone));
            });
            surface.slots.forEach(function (slot) { mounted.push(mountBrick(frames[slot.id])); });
            helps.push(LAYOUT_HELP);
        }
        var LAYOUT_HELP = 'Épingle : garder un panneau au bord de la fenêtre (haut, bas, gauche, '
            + 'droite) — disposition modifiable : empiler des panneaux en un seul (calques), les '
            + 'monter, les descendre, les détacher';

        function clearDock(el) {
            el.classList.remove('is-docked');
            DOCK_CHOICES.forEach(function (c) { if (c[0]) el.classList.remove('is-docked-' + c[0]); });
            el.style.removeProperty('--wama-dock-height');
            el.style.removeProperty('--wama-dock-width');
            el.style.removeProperty('--wama-dock-offset');
            delete el.dataset.docked;
        }
        /** Pose chaque panneau à son bord. Sa taille dans la grille, relevée AVANT qu'il ne la
         *  quitte, devient celle de sa bande (hauteur) ou de sa colonne (largeur). Une colonne n'a
         *  pas sa place sur une fenêtre de téléphone : le panneau y reste dans la page. */
        function applyDocks() {
            var narrow = !onFullGrid();
            var was = resetting;
            resetting = true;               // la page qui se referme n'est pas un geste à garder
            try {
                containers().forEach(function (key) {
                    var el = containerEl(key);
                    var edge = layout.docked[key] || '';
                    if (narrow && SIDES.indexOf(edge) >= 0) edge = '';
                    if (!edge) { undock(key, el); return; }
                    if (!dockPlaces[key]) {
                        // Sa taille dans la grille, relevée AVANT qu'il ne la quitte.
                        el.style.setProperty('--wama-dock-height', el.offsetHeight + 'px');
                        el.style.setProperty('--wama-dock-width', el.offsetWidth + 'px');
                        var node = el.gridstackNode;
                        if (node && node.grid) {
                            dockPlaces[key] = { x: node.x, y: node.y, w: node.w, h: node.h, grid: node.grid };
                            node.grid.removeWidget(el, false, false);
                        }
                    }
                    el.dataset.docked = edge;
                    el.classList.add('is-docked');
                    DOCK_CHOICES.forEach(function (c) {
                        if (c[0]) el.classList.toggle('is-docked-' + c[0], c[0] === edge);
                    });
                });
            } finally { resetting = was; }
            dockMargins();
            emit('resize');
        }
        /** Désépinglé : le panneau retrouve SA place dans sa zone (gridstack écarte les autres). */
        function undock(key, el) {
            var place = dockPlaces[key];
            clearDock(el);
            if (!place) return;
            delete dockPlaces[key];
            var at = fit(place, place.grid);
            at.id = key;
            place.grid.makeWidget(el, at);
        }
        /** Tous les panneaux épinglés rendus à la grille (avant de la réordonner). */
        function undockAll() {
            Object.keys(dockPlaces).forEach(function (key) { undock(key, containerEl(key)); });
        }
        /** Ce que chaque bord occupe : la page s'en écarte, rien ne passe dessous ; deux panneaux
         *  sur un même bord se rangent l'un après l'autre. Posé sur le corps : la colonne du volet
         *  le lit aussi. */
        function dockMargins() {
            var used = { top: 0, bottom: 0, left: 0, right: 0 };
            containers().forEach(function (key) {
                var el = containerEl(key), edge = el.dataset.docked;
                if (!edge) return;
                el.style.setProperty('--wama-dock-offset', used[edge] + 'px');
                used[edge] += SIDES.indexOf(edge) >= 0 ? el.offsetWidth : el.offsetHeight;
            });
            Object.keys(used).forEach(function (edge) {
                document.body.style.setProperty('--wama-dock-' + edge, used[edge] + 'px');
            });
        }
        global.addEventListener('resize', function () { if (Object.keys(frames).length) applyDocks(); });

        function layoutNow() {
            var out = {};
            zones.forEach(function (g) {
                var zone = g === panel ? 'panel' : 'grid';
                g.getGridItems().forEach(function (el) {
                    var n = el.gridstackNode;
                    if (n && n.id) out[n.id] = { x: n.x, y: n.y, w: n.w, h: n.h, zone: zone };
                });
            });
            // Un panneau épinglé a quitté la grille, pas la disposition : sa place reste la sienne.
            Object.keys(dockPlaces).forEach(function (key) {
                var p = dockPlaces[key];
                out[key] = { x: p.x, y: p.y, w: p.w, h: p.h, zone: p.grid === panel ? 'panel' : 'grid' };
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
                    body: JSON.stringify({ slots: layout.slots, frozen: !!layout.frozen,
                                           docked: layout.docked || {},
                                           stacks: layout.stacks || {} }),
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
            undockAll();                         // chacun reprend place dans la grille, pour s'y ranger
            dissolveAll();                       // une pile est un geste de disposition : défaite
            zones.forEach(function (g) { g.batchUpdate(); });
            surface.slots.forEach(function (slot) {
                var m = frames[slot.id];
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
            syncLayoutTools();
            applyDocks();
            persistLayout();
        }

        /** FIGER : la grille ne bouge plus, les panneaux perdent leur habit d'atelier (CSS
         *  `.is-frozen`) ; le titre d'un panneau qui porte des outils reste, en bande discrète. */
        function setFrozen(on) {
            layout.frozen = !!on;
            zones.forEach(function (g) { g.setStatic(layout.frozen); });
            showFrozen(layout.frozen);
            applyDocks();                        // rendue modifiable, un panneau épinglé reste immobile
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
                state.chosen = keptSources(state.sources, state.settings.values,
                                           surface.sources_setting);
                ctx.canEdit = !!data.can_edit;
                history.reset();
                building = true;
                try { buildAll(); }
                finally { building = false; }
                syncLayoutTools();
                applyDocks();
                status(ctx.canEdit ? '' : 'Lecture seule', ctx.canEdit ? '' : 'readonly');
                emit('change', state.value);
                holdLock();
            })
            .catch(function (e) { status('Chargement impossible : ' + e.message, 'error'); });

        return ctx;
    }

    global.WamaSurface = { registerBrick: registerBrick, mount: mount, keptSources: keptSources,
                           scaleWeights: scaleWeights };
})(window);
