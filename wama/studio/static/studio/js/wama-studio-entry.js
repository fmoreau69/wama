/*
 * WamaStudioEntry — la MODALE d'une card d'entrée médias du Studio (décision de Fabien,
 * 2026-10-20 — `STUDIO_VISION.md §Entrées du Studio`).
 *
 * Elle reprend la card d'entrée v4 de l'app que la card alimente, rendue par le serveur
 * (`/studio/api/entry-card/`, le gabarit commun des dix apps en `compose_only`), avec le VOLET
 * à côté : les réglages du nœud de l'app, par le rendu commun du Studio. Rien n'est écrit ici que
 * l'assemblage — chaque geste est celui d'une brique commune :
 *   - les onglets de port, les modalités, la face « fichiers » : `WamaInputSlots` (sa `wire`) ;
 *   - le dépôt sur le port principal, joint au port qui l'admet : `WamaImport({attach: 'card'})` ;
 *   - la médiathèque : la tuile de la card (`WamaApp.pickFromLibrary`, DÉSIGNATION, rien de recopié) ;
 *   - un fichier du poste : déposé dans l'espace du compte (`WamaFM.upload`, le geste de
 *     l'assistant), puis désigné ;
 *   - une URL : retenue telle quelle, téléchargée au lancement (`entries.received_value`) ;
 *   - le fichier de lot : déposé, puis lu par la règle du lancement (`/studio/api/entry-lot/`) qui
 *     dit combien d'éléments le pipeline jouera.
 *
 * `open({app, mode, port, entry, settings, onSave})` :
 *   mode  'card'  — la card ENTIÈRE (card universelle) : tous ses onglets et sa consigne ;
 *         'files' — UN port (card simplifiée de travail / de référence) : son onglet seul ;
 *         'lot'   — l'onglet du fichier de lot seul ;
 *   entry — ce que la card retient déjà (`{ports, prompt, lot}` ou `{files}`), montré au-dessus ;
 *   settings(host, rendered) — monte le volet (réglages du nœud de l'app) dans `host` et rappelle
 *         `rendered()` à chaque rendu : l'appariement entrée ↔ modèle s'y branche ;
 *   onSave(entry) — reçoit le contenu composé.
 */
(function (global) {
    'use strict';

    // Les ids de la card servie : DÉCLARÉS par le serveur (`studio/views.ENTRY_CARD_IDS`), joints au
    // fragment sous l'élément `studioEntryIds` et relus à chaque ouverture — jamais recopiés ici.
    // Avec eux, l'appariement de la card (`input_match.card_match`) : `{field, meta, labels, ports}`.
    var IDS = {}, MATCH = {};
    function readIds() {
        var host = document.getElementById('studioEntryIds');
        var ids = host ? JSON.parse(host.textContent) : {};
        IDS = { card: ids.card_id, files: ids.file_input_id, drop: ids.drop_zone_id,
                folder: ids.folder_input_id, prompt: ids.prompt_input_id, lot: ids.batch_bid,
                match: ids.match_status_id };
        MATCH = ids.match || {};
    }
    var modal = null, state = null;

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }
    function esc(s) { return global.WamaApp.escapeHtml(s == null ? '' : String(s)); }
    function toast(msg, kind) { if (global.WamaApp && WamaApp.toast) WamaApp.toast(msg, kind || 'info'); }
    function nameOf(ref) { return String(ref || '').split('?')[0].split('/').pop() || String(ref); }
    function refs(v) { return (Array.isArray(v) ? v : (v ? [v] : [])).filter(Boolean); }

    function ensureModal() {
        if (modal) return modal;
        var root = el('div', 'modal fade');
        root.id = 'studioEntryModal';
        root.tabIndex = -1;
        root.innerHTML =
            '<div class="modal-dialog modal-xl modal-dialog-scrollable"><div class="modal-content">' +
            '<div class="modal-header py-2"><h6 class="modal-title" data-entry-title></h6>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal" title="Fermer"></button></div>' +
            '<div class="modal-body"><div class="row g-3">' +
            '<div class="col-lg-8"><div data-entry-kept class="mb-2 small"></div><div data-entry-card></div></div>' +
            '<div class="col-lg-4 border-start"><div class="small text-body-secondary mb-1">' +
            '<i class="fas fa-sliders-h me-1"></i>Réglages — volet de l’app</div><div data-entry-settings></div></div>' +
            '</div></div>' +
            '<div class="modal-footer py-2"><button type="button" class="btn btn-sm btn-outline-emphasis" data-bs-dismiss="modal">Annuler</button>' +
            '<button type="button" class="btn btn-sm btn-success" data-entry-save><i class="fas fa-check me-1"></i>Retenir l’entrée</button></div>' +
            '</div></div>';
        document.body.appendChild(root);
        root.querySelector('[data-entry-save]').addEventListener('click', save);
        modal = root;
        return modal;
    }

    // ── Ce que la card retient déjà : une chip retirable par référence ─────────────────────
    function renderKept() {
        var host = modal.querySelector('[data-entry-kept]');
        host.textContent = '';
        var rows = [];
        if (state.mode === 'files') {
            refs(state.entry.files).forEach(function (r, i) { rows.push(['files', null, i, r]); });
        } else {
            Object.keys(state.entry.ports || {}).forEach(function (port) {
                refs(state.entry.ports[port]).forEach(function (r, i) { rows.push(['ports', port, i, r]); });
            });
            if (state.entry.lot) rows.push(['lot', null, 0, state.entry.lot]);
        }
        if (!rows.length) return;
        host.appendChild(el('div', 'text-body-secondary mb-1', 'Déjà retenu :'));
        rows.forEach(function (row) {
            var chip = el('span', 'wama-file-chip me-1');
            chip.title = row[3];
            chip.appendChild(document.createTextNode((row[1] ? row[1] + ' · ' : row[0] === 'lot' ? 'lot · ' : '')
                                                     + nameOf(row[3])));
            var x = el('span', 'wama-file-x', '✕');
            x.setAttribute('role', 'button');
            x.title = 'Retirer';
            x.addEventListener('click', function () {
                if (row[0] === 'files') state.entry.files.splice(row[2], 1);
                else if (row[0] === 'lot') delete state.entry.lot;
                else state.entry.ports[row[1]].splice(row[2], 1);
                renderKept();
                if (state.match) state.match.refresh();
            });
            chip.appendChild(x);
            host.appendChild(chip);
        });
    }

    // ── La card de l'app, restreinte à ce que la card du Studio porte ──────────────────────
    // Les onglets que la card du Studio porte — tous ; celui de SON port ; celui du fichier de
    // lot — par la brique de la card (`WamaInputSlots.restrict`), seule à lire ses onglets.
    function keepOnly(card) {
        var keep = state.mode === 'lot' ? ['lot'] : state.mode === 'files' ? [state.port] : null;
        if (keep) {
            var prompt = document.getElementById(IDS.prompt);
            if (prompt && prompt.parentNode) prompt.parentNode.style.display = 'none';
        }
        state.kept = WamaInputSlots.restrict(card, keep);
        if (!state.kept.length) {
            card.querySelector('[data-wama-preview]').innerHTML =
                '<small class="text-warning p-2 d-block">Cette app n’a pas d’entrée « '
                + esc(state.port || state.mode) + ' » dans sa card.</small>';
        }
    }

    // ── L'appariement entrée ↔ modèle : la card à gauche, le select de modèle du volet à droite ──
    // Le geste des pages d'app (`WamaInputMatch.init`, slots = ports de la card par sa brique,
    // comme le composer), sur ce que le serveur a lu (`card_match`) : le select de modèle du schéma
    // et les seuls ports qu'il JUGE. Une entrée fournie grise les modèles qui ne la prennent pas ;
    // la ligne d'état de la card dit pourquoi. Fournie = jointe, désignée, une URL saisie, ou déjà
    // RETENUE par la card du Studio. Rejoué à chaque rendu du volet (le select est recréé).
    function provided(port, input, urlId) {
        var url = urlId ? document.getElementById(urlId) : null;
        var kept = state.mode === 'files' ? state.entry.files : (state.entry.ports || {})[port];
        return !!((input && input.files && input.files.length)
                  || (global.WamaApp && WamaApp.designationOf && WamaApp.designationOf(input))
                  || (url && url.value.trim()) || refs(kept).length);
    }
    function wireMatch() {
        var card = IDS.card ? document.getElementById(IDS.card) : null;
        var host = state && state.settingsHost;
        if (!card || !host || !global.WamaInputMatch || !MATCH.field) return;
        var row = host.querySelector('[data-param-row="' + MATCH.field + '"]');
        var select = row ? row.querySelector('select') : null;
        if (!select || !select.id || select === state.matchSelect) return;
        var slots = {};
        WamaInputSlots.filePorts(card).forEach(function (p) {
            if ((MATCH.ports || []).indexOf(p.id) < 0 || (state.kept || []).indexOf(p.id) < 0) return;
            slots[p.id] = { inputId: p.inputId, zoneId: p.zoneId,
                            isProvided: function (input) { return provided(p.id, input, p.urlInputId); } };
            var url = p.urlInputId ? document.getElementById(p.urlInputId) : null;
            if (url && !url.dataset.studioMatch) {
                url.dataset.studioMatch = '1';
                url.addEventListener('input', function () { if (state.match) state.match.refresh(); });
            }
        });
        if (!Object.keys(slots).length) return;
        state.matchSelect = select;
        state.match = WamaInputMatch.init({ selectId: select.id, meta: MATCH.meta || {},
                                            inputLabels: MATCH.labels || {}, slots: slots,
                                            statusId: IDS.match });
    }

    // Le fichier de lot (onglet du fichier de lot) : déposé, puis lu par la règle du lancement.
    function lotAdapter(card) {
        if (!global.WamaBatchImport) return;
        WamaBatchImport.instances = WamaBatchImport.instances || {};
        WamaBatchImport.instances[IDS.lot] = {
            previewFile: function (file) {
                WamaFM.upload([file]).then(function (d) {
                    var up = (d.uploaded || [])[0];
                    if (!up) throw new Error(d.error || 'dépôt refusé');
                    return global.fetch('/studio/api/entry-lot/', {
                        method: 'POST', credentials: 'same-origin',
                        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': WamaApp.csrfToken() },
                        body: JSON.stringify({ app: state.app, lot: up.path }),
                    }).then(function (r) { return r.json(); }).then(function (res) {
                        if (res.error) throw new Error(res.error);
                        state.lot = up.path;
                        card.dispatchEvent(new CustomEvent('wama:batch-shown', { bubbles: true,
                            detail: { base: IDS.lot, count: res.count, name: up.name } }));
                    });
                })['catch'](function (e) { toast('Fichier de lot refusé : ' + e.message, 'error'); });
            },
        };
    }

    function open(opts) {
        ensureModal();
        state = { app: opts.app, mode: opts.mode || 'card', port: opts.port || '',
                  entry: JSON.parse(JSON.stringify(opts.entry || {})), onSave: opts.onSave, lot: '' };
        if (state.mode === 'files') state.entry.files = refs(state.entry.files);
        else state.entry.ports = state.entry.ports || {};
        modal.querySelector('[data-entry-title]').textContent = opts.title || 'Composer l’entrée';
        var cardHost = modal.querySelector('[data-entry-card]');
        cardHost.innerHTML = '<span class="text-body-secondary small"><i class="fas fa-spinner fa-spin me-1"></i>Chargement de la card…</span>';
        var settingsHost = modal.querySelector('[data-entry-settings]');
        settingsHost.textContent = '';
        state.settingsHost = settingsHost;
        // `settings(host, rendered)` : `rendered` est rappelé à chaque rendu du volet — le select de
        // modèle est alors neuf, l'appariement s'y rebranche.
        if (opts.settings) opts.settings(settingsHost, wireMatch);
        else settingsHost.innerHTML = '<span class="small text-body-secondary">Aucun réglage ici.</span>';
        renderKept();
        bootstrap.Modal.getOrCreateInstance(modal).show();
        global.fetch('/studio/api/entry-card/?app=' + encodeURIComponent(state.app), { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) return r.json().then(function (d) { throw new Error(d.error || 'HTTP ' + r.status); });
                return r.text();
            })
            .then(function (html) {
                cardHost.innerHTML = html;
                readIds();
                var card = document.getElementById(IDS.card);
                if (!card) return;
                if (state.mode === 'card' && state.entry.prompt) {
                    var prompt = document.getElementById(IDS.prompt);
                    if (prompt) prompt.value = state.entry.prompt;
                }
                if (global.WamaInputSlots) WamaInputSlots.wire(card);
                keepOnly(card);
                lotAdapter(card);
                wireMatch();
                if (global.WamaImport && document.getElementById(IDS.drop)) {
                    // eslint-disable-next-line no-new
                    new WamaImport({ dropZoneId: IDS.drop, fileInputId: IDS.files,
                                     folderInputId: IDS.folder, attach: 'card', multiple: true });
                }
            })['catch'](function (e) {
                cardHost.innerHTML = '<span class="text-danger small">Card indisponible : ' + esc(e.message) + '</span>';
            });
    }

    // ── Retenir : les fichiers du poste déposés dans l'espace du compte, puis désignés ─────
    function portRefs(card) {
        // Par port GARDÉ : fichiers locaux (à déposer), désignation, URL — dans l'ordre de la card,
        // par la lecture de la brique (`filePorts`, son champ URL compris).
        return WamaInputSlots.filePorts(card).filter(function (p) {
            return (state.kept || []).indexOf(p.id) >= 0;
        }).map(function (p) {
            var input = document.getElementById(p.inputId);
            var urlEl = p.urlInputId ? document.getElementById(p.urlInputId) : null;
            var d = global.WamaApp ? WamaApp.designationOf(input) : null;
            return { port: p.id, files: input && input.files ? Array.prototype.slice.call(input.files) : [],
                     designated: d ? [d.path] : [], url: urlEl ? urlEl.value.trim() : '' };
        });
    }

    function save() {
        var card = document.getElementById(IDS.card);
        var rows = card ? portRefs(card) : [];
        // Le port de travail PRINCIPAL est celui que la card DÉSIGNE : il porte l'input aux ids
        // historiques (`file_input_id`, `input_slots` — le premier port de TRAVAIL, la règle
        // d'`entry_form` que le serveur suit au dépliage), jamais « le premier onglet », qui peut
        // être une référence. Sans port de travail : aucun, chaque port ne garde qu'un fichier.
        var principal = card ? (WamaInputSlots.filePorts(card).filter(function (p) {
            return p.inputId === IDS.files;
        })[0] || {}).id : '';
        Promise.all(rows.map(function (row) {
            if (!row.files.length) return Promise.resolve(row);
            return WamaFM.upload(row.files).then(function (d) {
                if (!d.uploaded || d.uploaded.length !== row.files.length) {
                    throw new Error(d.error || 'dépôt incomplet');
                }
                row.added = d.uploaded.map(function (u) { return u.path; });
                return row;
            });
        })).then(function (done) {
            var entry = state.entry;
            done.forEach(function (row) {
                var added = (row.added || []).concat(row.designated, row.url ? [row.url] : []);
                if (!added.length) return;
                if (state.mode === 'files') { entry.files = refs(entry.files).concat(added); return; }
                // Le port de travail PRINCIPAL accumule (plusieurs fichiers = un lot) ; un autre
                // port ne porte qu'un fichier : le nouveau remplace l'ancien.
                entry.ports[row.port] = row.port === principal ? refs(entry.ports[row.port]).concat(added)
                                                               : added.slice(-1);
            });
            if (state.mode !== 'files') {
                Object.keys(entry.ports).forEach(function (p) { if (!refs(entry.ports[p]).length) delete entry.ports[p]; });
                var prompt = document.getElementById(IDS.prompt);
                if (state.mode === 'card' && prompt) entry.prompt = prompt.value.trim();
                if (state.lot) entry.lot = state.lot;
            }
            if (state.onSave) state.onSave(entry);
            bootstrap.Modal.getOrCreateInstance(modal).hide();
        })['catch'](function (e) { toast('Entrée non retenue : ' + e.message, 'error'); });
    }

    global.WamaStudioEntry = { open: open };
})(window);
