/**
 * WAMA — la page des LIBRAIRIES : la fiche de la librairie cliquée et ses gestes, dans le volet droit
 * (décision de Fabien, 2026-11-07, `WAMA_VOLETS §2` point 2 : « les librairies reçoivent la fiche
 * des modèles, plus des actions »).
 *
 * Fiche = les champs du registre servis par la vue (`library_catalog`, `library-details`), rendus par
 * la brique déclarative `WamaDetails` d'après le schéma ci-dessous — la forme de la fiche d'un
 * modèle. Gestes = ceux de la ligne de commande (`install_library` / `uninstall_library`), demandés
 * par `api_library_action` → `model_installer.request_library_action`, le corps que l'outil de
 * l'assistant appelle aussi ; la tâche est suivie par le Poller commun jusqu'à son issue, et reprise
 * à la sélection (un F5 n'efface rien : l'état vit au cache du serveur).
 *
 * La grille déclare : data-action-url, data-state-url, data-can-plan, data-can-install.
 */
(function (global) {
    'use strict';

    function esc(value) {
        if (global.WamaApp && global.WamaApp.escapeHtml) { return global.WamaApp.escapeHtml(value); }
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    /** Les pastilles de la fiche sont CELLES DE LA TUILE cliquée (installée / absente, dérive,
     *  allowlist, route), rendues par le gabarit : leurs libellés ne vivent qu'à un endroit. */
    function tileBadges(card) {
        var badges = card ? card.querySelectorAll('.wama-cat-badge') : [];
        return Array.prototype.map.call(badges, function (b) { return b.outerHTML; }).join(' ');
    }

    /** Le schéma de la fiche — ce qu'on montre d'une librairie, et dans quel ordre. */
    var DETAIL_SCHEMA = [
        { description: 'summary' },
        { section: 'Version', rows: [
            { k: 'Déclarée', field: 'declared_version' },
            { k: 'Installée ici', field: 'live_version' },
            { k: 'Spécificateur', field: 'pip_spec', code: true },
            { k: 'Python', field: 'requires_python' },
        ] },
        { section: 'Provenance', rows: [
            { k: 'Licence', field: 'license' },
            { k: 'Auteur', field: 'author' },
            { k: 'Dépôt', field: 'repository' },
            { k: 'Clone épinglé', field: 'vendor', code: true },
        ] },
        { section: 'Installation', rows: [
            { k: 'Versions tenues', field: 'constraints_pip' },
            { k: 'Sans dépendances', get: function (f) { return f.no_deps ? 'oui (--no-deps)' : ''; } },
            { k: 'Dépendances', field: 'dependencies' },
        ] },
    ];

    /** Les gestes — `when` lit la fiche ET le droit du compte (`can`). */
    function actionSchema(can, run) {
        return [
            { label: 'Simuler l’installation', icon: 'fas fa-flask', cls: 'btn btn-sm btn-outline-info',
              when: function () { return can.plan; },
              onClick: function (f) { run(f, 'plan'); } },
            { label: 'Installer', icon: 'fas fa-download', cls: 'btn btn-sm btn-success',
              when: function (f) { return can.install && !f.live_version; },
              onClick: function (f) { run(f, 'install'); } },
            { label: 'Aligner sur la version déclarée', icon: 'fas fa-arrows-rotate', cls: 'btn btn-sm btn-warning',
              when: function (f) { return can.install && f.drift; },
              onClick: function (f) { run(f, 'install'); } },
            { label: 'Désinstaller', icon: 'fas fa-trash', cls: 'btn btn-sm btn-outline-danger',
              when: function (f) { return can.install && !!f.live_version && f.route === 'pip'; },
              onClick: function (f) { run(f, 'uninstall'); } },
        ];
    }

    var ACTION_LABELS = { plan: 'Simulation', install: 'Installation', uninstall: 'Retrait' };

    /** Ce qu'un état publié par la tâche dit, en HTML — le plan (ce que pip ferait), l'issue. */
    function stateHtml(s) {
        if (!s || !s.state) { return ''; }
        var what = ACTION_LABELS[s.action] || s.action || '';
        if (s.state === 'RUNNING') {
            return '<div class="text-info small"><i class="fas fa-spinner fa-spin me-1"></i>'
                + esc(what) + ' : ' + esc(s.status || 'en cours') + '</div>';
        }
        var ok = s.state === 'SUCCESS' && s.ok !== false;
        var out = '<div class="small ' + (ok ? 'text-success' : 'text-danger') + '">'
            + esc(what) + (ok ? ' terminée' : ' en échec') + (s.error ? ' : ' + esc(s.error) : '') + '</div>';
        var plan = s.plan || {};
        var sim = plan.simulation || {};
        if (s.action === 'plan') {
            if (plan.already_satisfied) {
                out += '<div class="small text-muted">Déjà à la version déclarée : rien à installer.</div>';
            }
            if (sim.ok === false) {
                out += '<div class="small text-danger text-break">Simulation impossible : ' + esc(sim.error || '') + '</div>';
            }
            (sim.retrogradations || []).forEach(function (r) {
                out += '<div class="small text-warning text-break">Déplacerait ' + esc(r.paquet) + ' : '
                    + esc(r.installee) + ' → ' + esc(r.deviendrait) + '</div>';
            });
            if ((sim.would_install || []).length) {
                out += '<div class="small text-muted text-break">pip installerait : '
                    + (sim.would_install || []).map(esc).join(', ') + '</div>';
            }
        }
        var requirers = plan.requirers || {};
        var needed = (requirers.packages || []).concat(requirers.manifests || []);
        if (needed.length) {
            out += '<div class="small text-warning text-break">Encore requise par : ' + needed.map(esc).join(', ') + '</div>';
        }
        if (s.patches && s.patches.ok === false) {
            out += '<div class="small text-warning">Patches du venv non rejoués proprement.</div>';
        }
        return out;
    }

    function mount(grid, details) {
        var byKey = {};
        (details || []).forEach(function (f) { byKey[f.key] = f; });
        var can = { plan: grid.dataset.canPlan === '1', install: grid.dataset.canInstall === '1' };
        var current = null;
        var shown = {};          // dernier état connu, par clé
        var launched = {};       // clés dont le geste a été lancé depuis CETTE page

        function show(key) {
            var host = document.getElementById('libraryActionResult');
            if (host && key === current) { host.innerHTML = stateHtml(shown[key]); }
        }

        var poller = global.WamaApp && global.WamaApp.Poller ? new global.WamaApp.Poller({
            urlTemplate: function (key) { return grid.dataset.stateUrl + '?key=' + encodeURIComponent(key); },
            interval: 2000, immediate: true, maxFails: Infinity,
            onData: function (key, data) {
                var s = (data && data.state) || {};
                shown[key] = s;
                show(key);
                if (s.state === 'RUNNING') { return; }
                poller.stop(key);
                // Le venv a changé : les tuiles sont rendues par le serveur, la page se recharge —
                // pour un geste lancé ici seulement (pas sous les yeux de qui relit une issue ancienne).
                if (launched[key] && s.state === 'SUCCESS' && s.ok !== false && s.action !== 'plan') {
                    global.location.reload();
                }
                delete launched[key];
            },
        }) : null;

        function follow(key) { if (poller) { poller.start(key); } }

        function run(f, action) {
            var token = global.WamaApp && global.WamaApp.csrfToken ? global.WamaApp.csrfToken() : '';
            shown[f.key] = { state: 'RUNNING', action: action, status: 'demande envoyée…' };
            show(f.key);
            fetch(grid.dataset.actionUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': token },
                body: JSON.stringify({ key: f.key, action: action }),
            }).then(function (r) { return r.json(); }).then(function (data) {
                if (!data.success) {
                    shown[f.key] = { state: 'FAILURE', action: action, ok: false, error: data.error || 'refusé' };
                    show(f.key);
                    return;
                }
                launched[f.key] = true;
                follow(f.key);
            }).catch(function (e) {
                shown[f.key] = { state: 'FAILURE', action: action, ok: false, error: String(e) };
                show(f.key);
            });
        }

        var schema = actionSchema(can, run);
        global.WamaInspector.init({
            queueContainer: grid,
            cardSelector: '.wama-cat-card',
            highlightClass: 'wama-cat-active',
            itemLabel: function (key) { var f = byKey[key]; return f ? f.key : key; },
            renderItemActions: function (host, card) {
                var f = byKey[card.dataset.id];
                current = f ? f.key : null;
                if (host) {
                    host.innerHTML = f ? '<div class="wai-badges">' + tileBadges(card) + '</div>'
                                         + global.WamaDetails.renderSections(f, DETAIL_SCHEMA)
                                       : '<p class="text-muted small">Librairie inconnue.</p>';
                }
                var buttons = document.getElementById('libraryActionButtons');
                if (buttons && f) {
                    var r = global.WamaDetails.renderActions(f, schema);
                    buttons.innerHTML = r.html + '<div id="libraryActionResult" class="mt-2 w-100"></div>';
                    r.wire(buttons);
                    show(f.key);
                    // Une tâche lancée ailleurs (l'assistant, un autre onglet) ou avant un F5 : relue.
                    follow(f.key);
                }
            },
        });
    }

    function mountAll() {
        var grid = document.querySelector('[data-library-catalog]');
        var data = document.getElementById('library-details');
        if (!grid || !data || !global.WamaInspector || !global.WamaDetails) { return; }
        mount(grid, JSON.parse(data.textContent || '[]'));
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', mountAll); }
    else { mountAll(); }

    global.WamaLibraryCatalog = { mount: mount, stateHtml: stateHtml, DETAIL_SCHEMA: DETAIL_SCHEMA,
                                  actionSchema: actionSchema };
})(window);
