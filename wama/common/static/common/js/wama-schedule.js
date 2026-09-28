/**
 * WAMA — PROGRAMMER le lancement d'une card (calendrier, étape 3 — ROUTE §10.6 point 13).
 *
 * Deux choses, et rien par app :
 *   1. la fenêtre « Programmer… », ouverte par le menu COMMUN de card (`wama-card-menu.js`) :
 *      trois placements — dès que possible, en heures creuses, à une date — suivant la règle
 *      « auto + curseur + manuel ». Une date qui tombe dans une PLAGE RÉSERVÉE (tests nocturnes)
 *      est refusée par le serveur, qui propose la fin de la plage : un bouton la reprend ;
 *   2. la PASTILLE « ⏰ Programmé · … » posée dans la section État des cards programmées, avec
 *      « Modifier » et « Annuler ». Elle suit les cards redessinées (observateur de mutations) :
 *      le ▶ lance maintenant et le serveur annule la programmation — la pastille disparaît au
 *      rafraîchissement de la card, sans rien demander (décision de Fabien).
 *
 * Contrat : la file porte `data-schedule-url` et `data-schedule-tool` (`queue_dnd_attrs`, émis
 * seulement si l'app a un outil de lancement). Une file sans eux n'offre rien.
 */
(function (global) {
    'use strict';

    function $(sel, root) { return (root || document).querySelector(sel); }
    function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }

    function csrf() {
        return global.WamaApp && WamaApp.csrfToken ? WamaApp.csrfToken()
            : ((document.cookie.match(/csrftoken=([^;]+)/) || [])[1] || '');
    }

    function say(message, kind) {
        if (global.WamaApp && WamaApp.toast) { WamaApp.toast(message, kind || 'info'); }
    }

    function postJson(url, payload) {
        return fetch(url, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'X-CSRFToken': csrf(), 'Content-Type': 'application/json' },
            body: JSON.stringify(payload || {}),
        }).then(function (r) {
            return r.json().catch(function () {
                return { ok: false, error: 'Réponse inattendue du serveur (HTTP ' + r.status + ')' };
            });
        });
    }

    /** « jeu. 01/10 22:00 » — l'heure LOCALE du navigateur. */
    function label(iso) {
        var d = new Date(iso);
        return d.toLocaleString('fr-FR', { weekday: 'short', day: '2-digit', month: '2-digit',
                                           hour: '2-digit', minute: '2-digit' });
    }

    /** Valeur d'un `<input type="datetime-local">` (heure locale, à la minute). */
    function localInput(date) {
        var pad = function (n) { return String(n).padStart(2, '0'); };
        return date.getFullYear() + '-' + pad(date.getMonth() + 1) + '-' + pad(date.getDate())
            + 'T' + pad(date.getHours()) + ':' + pad(date.getMinutes());
    }

    function baseUrl() {
        var q = $('[data-schedule-url]');
        return q ? q.getAttribute('data-schedule-url') : '';
    }

    // ── La fenêtre « Programmer… » ──────────────────────────────────────────────────────────

    var host = null;
    function modalHost() {
        if (host) { return host; }
        host = document.createElement('div');
        host.className = 'modal fade wama-schedule-modal';
        host.tabIndex = -1;
        host.innerHTML = '<div class="modal-dialog modal-dialog-centered">'
            + '<div class="modal-content bg-dark text-light border-secondary"></div></div>';
        document.body.appendChild(host);
        return host;
    }

    // Le SCHÉMA de la fenêtre vient du serveur (`scheduled_actions.schedule_params`, servi avec
    // les programmations actives) : aucun champ n'est écrit ici — la fenêtre est RENDUE par
    // `WamaParams`, comme les réglages de n'importe quelle card.
    var schema = null;

    function body(opts) {
        return '<div class="modal-header border-secondary">'
            + '<h5 class="modal-title"><i class="fas fa-clock me-2"></i>'
            + (opts.action ? 'Modifier la programmation' : 'Programmer le lancement') + '</h5>'
            + '<button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button></div>'
            + '<div class="modal-body">'
            + '<p class="small text-secondary mb-3">' + (opts.subject || '') + '</p>'
            + '<div class="wama-schedule-fields"></div>'
            + '<div class="wama-schedule-feedback small mt-3"></div>'
            + '<p class="small text-secondary mt-3 mb-0">Les réglages de la card seront lus au moment '
            + 'du lancement. Le bouton ▶ lance tout de suite et annule la programmation.</p>'
            + '</div>'
            + '<div class="modal-footer border-secondary">'
            + '<button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Fermer</button>'
            + '<button type="button" class="btn btn-sm btn-success wama-schedule-ok">'
            + '<i class="fas fa-clock me-1"></i> Programmer</button></div>';
    }

    /**
     * Ouvre la fenêtre. `opts` : { url, tool, ids, subject } pour programmer, ou
     * { url, action } pour modifier une programmation existante.
     */
    function open(opts) {
        if (!schema) {                       // 1ʳᵉ ouverture avant le premier chargement
            return loadActive().then(function () { if (schema) { open(opts); } });
        }
        var el = modalHost();
        el.querySelector('.modal-content').innerHTML = body(opts);
        var feedback = el.querySelector('.wama-schedule-feedback');
        var fields = el.querySelector('.wama-schedule-fields');
        var modal = bootstrap.Modal.getOrCreateInstance(el);
        var values = opts.action ? opts.action.values
            : { when: 'manual', at: localInput(new Date(Date.now() + 60 * 60 * 1000)) };
        WamaParams.render(fields, schema, { context: 'item', values: values });

        function submit(overrideAt) {
            // Les valeurs portent les noms du SCHÉMA (`when`, `at`) — ceux d'une ligne de lot.
            var payload = overrideAt ? { when: 'manual', at: overrideAt } : WamaParams.read(fields);
            var url;
            if (opts.action) {
                url = opts.url + opts.action.id + '/';
            } else {
                url = opts.url;
                payload.tool = opts.tool;
                payload.ids = opts.ids;
            }
            feedback.textContent = '';
            postJson(url, payload).then(function (res) {
                if (res && res.ok) {
                    modal.hide();
                    var first = (res.actions || [])[0];
                    say(first ? 'Programmé : ' + label(first.runAt)
                        + (res.actions.length > 1 ? ' (' + res.actions.length + ' éléments)' : '')
                        : 'Programmé', 'success');
                    refresh();
                    return;
                }
                if (res && res.conflict) {
                    var c = res.conflict;
                    feedback.innerHTML = '<div class="text-warning mb-2"><i class="fas fa-triangle-exclamation me-1"></i>'
                        + 'Cette heure tombe dans « ' + c.title + ' » (' + label(c.start) + ' → '
                        + label(c.end) + '), une plage réservée.</div>'
                        + '<button type="button" class="btn btn-sm btn-outline-warning wama-schedule-suggested">'
                        + 'Programmer à ' + label(c.suggested) + '</button>';
                    feedback.querySelector('.wama-schedule-suggested').addEventListener('click', function () {
                        submit(c.suggested);
                    });
                    return;
                }
                feedback.innerHTML = '<span class="text-danger">' + ((res && res.error) || 'Programmation impossible') + '</span>';
            });
        }

        el.querySelector('.wama-schedule-ok').addEventListener('click', function () { submit(null); });
        modal.show();
    }

    // ── Les pastilles des cards programmées ─────────────────────────────────────────────────

    var decorating = false;

    function chip(action, url) {
        var div = document.createElement('div');
        div.className = 'wama-schedule-chip small mt-1';
        div.setAttribute('data-schedule-id', action.id);
        div.innerHTML = '<i class="fas fa-clock me-1"></i>Programmé · ' + label(action.runAt)
            + ' <button type="button" class="btn btn-link btn-sm p-0 ms-2 wama-schedule-edit">Modifier</button>'
            + ' <button type="button" class="btn btn-link btn-sm p-0 ms-2 text-danger wama-schedule-cancel">Annuler</button>';
        // Un clic sur la pastille ne SÉLECTIONNE pas la card : c'est un geste à part.
        div.addEventListener('click', function (ev) { ev.stopPropagation(); });
        div.querySelector('.wama-schedule-edit').addEventListener('click', function () {
            open({ url: url, action: action, subject: action.title });
        });
        div.querySelector('.wama-schedule-cancel').addEventListener('click', function () {
            postJson(url + action.id + '/cancel/', {}).then(function (res) {
                say(res && res.ok ? 'Programmation annulée' : 'Cette programmation n’existe plus',
                    res && res.ok ? 'success' : 'info');
                refresh();
            });
        });
        return div;
    }

    function decorate(actions) {
        decorating = true;
        try {
            $$('[data-schedule-tool]').forEach(function (queue) {
                var url = queue.getAttribute('data-schedule-url');
                var tool = queue.getAttribute('data-schedule-tool');
                var byId = {};
                actions.forEach(function (a) { if (a.tool === tool) { byId[String(a.objectId)] = a; } });
                $$('.wama-card[data-id]', queue).forEach(function (card) {
                    $$('.wama-schedule-chip', card).forEach(function (old) { old.remove(); });
                    var action = byId[String(card.getAttribute('data-id'))];
                    if (!action) { return; }
                    var slot = $('.wcv3-sec--state .wcv3-state', card) || $('.wcv3-sec--state', card) || card;
                    slot.appendChild(chip(action, url));
                });
            });
        } finally {
            setTimeout(function () { decorating = false; }, 0);
        }
    }

    var pending = null;
    function loadActive() {
        var base = baseUrl();
        if (!base) { return Promise.resolve({ actions: [] }); }
        return fetch(base + 'active/', { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : { actions: [] }; })
            .then(function (res) { if (res.schema) { schema = res.schema; } return res; })
            .catch(function () { return { actions: [] }; });
    }

    function refresh() {
        // Pastilles absentes si la lecture échoue : la programmation, elle, tient.
        loadActive().then(function (res) { decorate(res.actions || []); });
    }

    function scheduleRefresh() {
        if (decorating) { return; }
        clearTimeout(pending);
        pending = setTimeout(refresh, 400);
    }

    function watch() {
        if (!global.MutationObserver) { return; }
        $$('[data-schedule-tool]').forEach(function (queue) {
            new MutationObserver(function (mutations) {
                if (decorating) { return; }
                var foreign = mutations.some(function (m) {
                    return Array.prototype.some.call(m.addedNodes, function (n) {
                        return !(n.classList && n.classList.contains('wama-schedule-chip'));
                    });
                });
                if (foreign) { scheduleRefresh(); }
            }).observe(queue, { childList: true, subtree: true });
        });
    }

    global.WamaSchedule = { open: open, refresh: refresh, label: label };

    function start() { refresh(); watch(); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})(window);
