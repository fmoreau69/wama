/**
 * Brique `speaker_names` — NOMMER les locuteurs d'une suite de segments (2026-10-21, la page de
 * correction du transcriber devenue surface — `ROUTE §F3b`, étape 2 ; DÉPLACÉE de son volet droit).
 *
 * Universelle : le réglage que l'emplacement nomme (`options.setting`, type `mapping`) est rendu
 * par le moteur COMMUN des réglages (`WamaParams`, une ligne par clé), ses clés étant les locuteurs
 * PRÉSENTS dans la valeur éditée (libellé canonique « SPEAKER_NN », `WamaSegments.speakers`), dans
 * l'ordre d'apparition. « Appliquer les noms » l'écrit par la route commune des réglages ; les
 * briques qui montrent les locuteurs suivent (`settings`). « Identifier automatiquement » appelle la
 * route de geste que la surface déclare (`options.suggest`) et PRÉ-REMPLIT les champs vides — rien
 * n'est appliqué sans le geste. L'audio et les segments ne changent pas : un nom n'est qu'un
 * affichage, et le document de sortie.
 */
(function (global) {
    'use strict';

    function mount(body, ctx, options) {
        options = options || {};
        var Seg = global.WamaSegments, Params = global.WamaParams;
        var key = options.setting || 'speaker_map';
        var suggestUrl = options.suggest ? (ctx.config.routes || {})[options.suggest] : '';
        var param = ((ctx.settings() || {}).schema || []).filter(function (p) { return p.name === key; })[0];
        body.classList.add('wama-brick-speakers');
        body.setAttribute('data-speakers', '');
        body.innerHTML =
            '<div class="wama-params wama-speaker-list"></div>' +
            '<p class="small text-body-secondary mb-2 d-none" data-speakers="empty">Aucun locuteur détecté (diarisation désactivée).</p>' +
            (suggestUrl ? '<button type="button" class="btn btn-sm btn-outline-info w-100 mb-1" data-speakers="suggest" ' +
                          'title="Détecter les noms à partir des présentations dans l\'audio (IA)">' +
                          '<i class="fas fa-wand-magic-sparkles"></i> Identifier automatiquement</button>' : '') +
            '<button type="button" class="btn btn-sm btn-info w-100" data-speakers="apply">' +
            '<i class="fas fa-user-check"></i> Appliquer les noms</button>';
        var host = body.querySelector('.wama-speaker-list');
        var empty = body.querySelector('[data-speakers="empty"]');
        var shown = null;

        function current() { return ((ctx.settings() || {}).values || {})[key] || {}; }

        /** Une ligne par locuteur présent ; redessiné seulement quand la liste des locuteurs change
         *  (une saisie en cours n'est jamais effacée par une frappe dans les segments). */
        function build() {
            var seen = Seg.speakers(Array.isArray(ctx.value()) ? ctx.value() : []);
            var sig = seen.join('|');
            if (sig === shown) return;
            shown = sig;
            empty.classList.toggle('d-none', !!seen.length);
            var names = current(), value = {};
            seen.forEach(function (c) { value[c] = names[c] || ''; });
            var values = {};
            values[key] = value;
            if (param && seen.length) Params.render(host, [param], { context: 'surface', values: values });
            else host.innerHTML = '';
            if (!ctx.canEdit) host.querySelectorAll('input').forEach(function (e) { e.disabled = true; });
        }

        body.querySelector('[data-speakers="apply"]').addEventListener('click', function (ev) {
            var btn = ev.currentTarget, map = {};
            var read = {};
            try { read = JSON.parse(Params.read(host)[key] || '{}'); } catch (e) { read = {}; }
            Object.keys(read).forEach(function (c) {
                var name = String(read[c] || '').trim();
                if (name) map[c] = name;
            });
            var out = {};
            out[key] = map;
            ctx.saveSettings(out);
            var old = btn.innerHTML;
            btn.innerHTML = '<i class="fas fa-check"></i> Noms appliqués';
            setTimeout(function () { btn.innerHTML = old; }, 1500);
        });

        var suggest = body.querySelector('[data-speakers="suggest"]');
        if (suggest) suggest.addEventListener('click', function () {
            var App = global.WamaApp || {};
            var orig = suggest.innerHTML;
            suggest.disabled = true;
            suggest.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyse en cours…';
            App.csrfFetch(suggestUrl, App.csrfToken(), { method: 'POST' })
                .then(function (r) { return r.json(); })
                .then(function (data) {
                    var sug = (data && data.suggestions) || {}, n = 0;
                    Object.keys(sug).forEach(function (sid) {
                        var inp = host.querySelector('input[data-key="' + sid + '"]');
                        if (inp && !inp.value.trim()) {                     // une saisie n'est jamais écrasée
                            inp.value = sug[sid]; n++;
                            inp.dispatchEvent(new Event('input', { bubbles: true }));
                        }
                    });
                    suggest.innerHTML = n
                        ? '<i class="fas fa-check"></i> ' + n + ' nom(s) proposé(s) — vérifiez puis Appliquer'
                        : '<i class="fas fa-circle-info"></i> Aucun nom détecté';
                })
                .catch(function () { suggest.innerHTML = '<i class="fas fa-triangle-exclamation"></i> Erreur'; })
                .then(function () {
                    suggest.disabled = false;
                    setTimeout(function () { suggest.innerHTML = orig; }, 3000);
                });
        });

        build();
        return { refresh: build };
    }

    global.WamaSurface.registerBrick('speaker_names', { title: 'Intervenants', mount: mount });
})(window);
