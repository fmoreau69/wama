/**
 * Brique `item_settings` — des RÉGLAGES de l'élément, sur la page (2026-10-21, décision de
 * Fabien : la correction du transcriber devenue surface — `ROUTE §F3b`, étape 2).
 *
 * Universelle : elle rend, par le moteur COMMUN des réglages (`WamaParams.render`, contexte
 * `surface`), les champs que l'emplacement nomme (`options.fields`) parmi ceux que la surface
 * déclare (`Surface.settings`), et les écrit par la route commune des réglages de l'app
 * (`ctx.saveSettings` → `update_settings`) après une courte pause de frappe — la même route que
 * la modale ⚙ : un réglage écrit ici se relit partout. Le titre et la date du document du
 * transcriber ; demain les paroles du composer, que sa surface ne savait pas éditer.
 * `options.facts` : le nom d'une valeur de contexte `[[icône, texte], …]` montrée en lecture seule.
 */
(function (global) {
    'use strict';

    var SAVE_AFTER_MS = 700;           // la pause de l'enregistrement de l'avant-propos de l'éditeur

    function esc(t) {
        var d = document.createElement('div'); d.textContent = t == null ? '' : t;
        return d.innerHTML;
    }

    function mount(body, ctx, options) {
        options = options || {};
        var wanted = options.fields || [];
        var settings = ctx.settings() || { schema: [], values: {} };
        var schema = (settings.schema || []).filter(function (p) {
            return !wanted.length || wanted.indexOf(p.name) >= 0;
        });
        body.classList.add('wama-brick-settings');
        var form = document.createElement('div');
        form.className = 'wama-params';
        form.setAttribute('data-settings', '');
        body.appendChild(form);
        global.WamaParams.render(form, schema, { context: 'surface', values: settings.values || {} });
        if (!ctx.canEdit) form.querySelectorAll('input, select, textarea').forEach(function (e) { e.disabled = true; });

        var timer = null;
        function save() {
            var read = global.WamaParams.read(form), out = {};
            schema.forEach(function (p) { if (p.name in read) out[p.name] = read[p.name]; });
            ctx.saveSettings(out);
        }
        function later() { clearTimeout(timer); timer = setTimeout(save, SAVE_AFTER_MS); }
        form.addEventListener('input', later);
        form.addEventListener('change', later);

        var facts = options.facts ? ((ctx.context() || {})[options.facts] || []) : [];
        if (facts.length) {
            var ro = document.createElement('div');
            ro.className = 'meta-ro';
            ro.innerHTML = facts.map(function (f) {
                return '<div><i class="fas ' + esc(f[0]) + '"></i> ' + esc(f[1]) + '</div>';
            }).join('');
            body.appendChild(ro);
        }
        return {};
    }

    global.WamaSurface.registerBrick('item_settings', { title: "Réglages de l'élément", mount: mount });
})(window);
