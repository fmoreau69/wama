/**
 * Brique `stem_mixer` — le MIXAGE EN TEMPS RÉEL des pistes séparées d'un morceau (2026-11-17,
 * décision de Fabien : « le mixage temps réel va dans la page d'édition, la card porte les
 * process » ; `common/surfaces.py`).
 *
 * Universelle — l'emplacement nomme ce qu'elle lit et écrit :
 *   • `tracks` : la valeur de contexte `{original, tracks: [{key, label, url, gain}], error}` que la
 *     surface déclare (`Surface.context`) — chaque piste avec le niveau que l'élément porte ;
 *   • `role` : le média lu dont le mixage devient une VERSION de plus (`ctx.addSource`) — le
 *     transport la joue sur l'axe partagé, comme la lecture MIDI d'une partition ;
 *   • `levels` / `without` : les réglages de l'élément où s'écrivent les niveaux (`{piste: gain}`,
 *     ceux ni à 0 ni à 100 %) et les pistes retirées (leurs noms) — par la route commune des
 *     réglages, celle de la ⚙ ;
 *   • `process` : l'étape qui écrit le fichier du mixage (« Rendre le mixage », `ctx.run`).
 * Le son se fait dans la page (`wama-stem-mix.js`) avec la règle de la refusion : ce qu'on entend
 * est ce que l'étape rendra.
 */
(function (global) {
    'use strict';

    var SAVE_AFTER_MS = 600;           // une pause dans les gestes, puis les niveaux s'écrivent
    var LIVE_KEY = 'live-mix';         // la version « Mixage » du média lu

    /** La BORNE d'un niveau, en % : le `max` que le réglage nommé par l'emplacement (`levels`)
     *  déclare au schéma servi (2026-11-17 — elle était écrite ici ET dans la refusion, ×2 et ×4).
     *  Un réglage sans borne : 100 %, jamais plus fort que la piste telle quelle. */
    function maxPercent(ctx, name) {
        var schema = ((ctx.settings && ctx.settings()) || {}).schema || [];
        for (var i = 0; i < schema.length; i++) {
            if (schema[i].name === name && Number(schema[i].max) > 0) return Math.round(Number(schema[i].max) * 100);
        }
        return 100;
    }

    function esc(t) {
        var d = document.createElement('div'); d.textContent = t == null ? '' : t;
        return d.innerHTML;
    }
    /** Un niveau tel qu'il s'écrit : deux décimales au plus. */
    function level(g) { return String(Math.round(g * 100) / 100); }

    function mount(body, ctx, options) {
        options = options || {};
        var role = options.role || 'audio';
        var data = (ctx.context() || {})[options.tracks || 'tracks'];
        body.classList.add('wama-brick-mixer');
        // L'étape qu'elle lance est SANS OBJET pour cet élément (2026-11-17, Fabien : une piste
        // séparée n'a plus qu'une piste — `config.excluded`, la règle de la bande) : le dire, et
        // mener à la card d'origine d'une card dérivée, où le mixage a lieu (`config.origin`).
        var config = ctx.config || {};
        var excluded = options.process && (config.excluded || {})[options.process];
        if (excluded) {
            var origin = config.origin || {};
            body.innerHTML = '<p class="small text-body-secondary mb-0">' +
                (origin.id ? 'Cette card est tirée de #' + esc(origin.id) + ' : le mixage des pistes se ' +
                             'fait sur sa card d’origine. <a href="' + esc(origin.url) + '">Ouvrir #' +
                             esc(origin.id) + '</a>'
                           : esc(excluded)) + '</p>';
            return {};
        }
        if (!data || !(data.tracks || []).length) {
            body.innerHTML = '<p class="small text-body-secondary mb-0">' +
                esc(options.empty || 'Aucune piste à mixer pour cet élément.') + '</p>';
            return {};
        }
        var mix = global.WamaStemMix.create({
            original: data.original, playback: data.playback, tracks: data.tracks,
            status: function (text, kind) { say(text, kind); },
        });
        var MAX_PERCENT = maxPercent(ctx, options.levels);
        var canWrite = !!(ctx.canEdit && options.levels);
        var canRender = !!(ctx.canEdit && options.process && ctx.run);

        body.innerHTML =
            '<div class="wama-mixer-rows"></div>' +
            '<div class="d-flex gap-1 mt-2">' +
            '  <button type="button" class="btn btn-sm btn-outline-secondary" data-mixer="reset" ' +
            '          title="Toutes les pistes à 100 % : le morceau d\'origine">' +
            '    <i class="fas fa-arrow-rotate-left"></i> Tout à 100 %</button>' +
            (canRender ? '  <button type="button" class="btn btn-sm btn-success flex-grow-1" data-mixer="render" ' +
                         '          title="Écrire ce mixage dans un fichier : une card de plus dans le lot">' +
                         '    <i class="fas fa-file-audio"></i> Rendre le mixage</button>' : '') +
            '</div>' +
            '<div class="small text-body-secondary mt-1" data-mixer="status" aria-live="polite"></div>';
        var rows = body.querySelector('.wama-mixer-rows');
        var statusLine = body.querySelector('[data-mixer="status"]');
        function say(text, kind) {
            statusLine.textContent = text || '';
            statusLine.classList.toggle('text-danger', kind === 'error');
        }
        if (data.error) say(data.error, 'error');

        var lastAudible = {};
        data.tracks.forEach(function (t) {
            var g = mix.gains()[t.key];
            lastAudible[t.key] = g > 0 ? g : 1;
            var row = document.createElement('div');
            row.className = 'wama-mixer-row d-flex align-items-center gap-2 mb-1';
            row.dataset.track = t.key;
            row.innerHTML =
                '<button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1" data-mixer="mute" ' +
                '        title="Couper / rendre « ' + esc(t.label) + ' »"><i class="fas"></i></button>' +
                '<span class="text-truncate" style="flex:0 0 5.2em" title="' + esc(t.label) + '">' + esc(t.label) + '</span>' +
                '<input type="range" class="form-range flex-grow-1" style="min-width:3em" min="0" max="' + MAX_PERCENT + '" step="1" ' +
                '       data-mixer="level" aria-label="Niveau de ' + esc(t.label) + '" ' +
                '       title="Niveau de « ' + esc(t.label) + ' » — double-clic : 100 %">' +
                '<span class="small text-end text-nowrap" style="flex:0 0 3.6em" data-mixer="value"></span>';
            rows.appendChild(row);
            show(t.key, g);
        });

        function rowOf(key) { return rows.querySelector('[data-track="' + key + '"]'); }
        function show(key, g) {
            var row = rowOf(key);
            row.querySelector('[data-mixer="level"]').value = String(Math.round(g * 100));
            row.querySelector('[data-mixer="value"]').textContent = Math.round(g * 100) + ' %';
            var icon = row.querySelector('[data-mixer="mute"] i');
            icon.className = 'fas ' + (g === 0 ? 'fa-volume-xmark' : 'fa-volume-high');
            row.classList.toggle('opacity-50', g === 0);
        }

        // La version « Mixage » du média lu : le transport la joue comme une autre. Son « rendu » est
        // le décodage du morceau (le transport le dit en cours) ; les pistes viennent à la demande.
        ctx.addSource(role, {
            key: LIVE_KEY, label: options.label || 'Mixage des pistes', url: '',
            render: function () {
                return mix.preload().then(function () {
                    if (mix.media.error) throw mix.media.error;
                    return { media: mix.media, sync: global.WamaStemMix.SYNC,
                             from: options.label || 'mixage des pistes' };
                });
            },
        });

        var timer = null;
        function values() {
            var gains = mix.gains(), levels = {}, without = [];
            data.tracks.forEach(function (t) {
                var g = gains[t.key];
                if (g === 0) without.push(t.label);
                else if (g !== 1) levels[t.key] = level(g);
            });
            var out = {};
            out[options.levels] = levels;
            if (options.without) out[options.without] = without.join(', ');
            return out;
        }
        function save() {
            clearTimeout(timer); timer = null;
            return canWrite ? ctx.saveSettings(values()) : Promise.resolve(true);
        }
        function set(key, g) {
            g = Math.max(0, Math.min(MAX_PERCENT / 100, g));
            if (g > 0) lastAudible[key] = g;
            show(key, g);
            // Bouger une piste, c'est vouloir l'entendre : la lecture passe au mixage.
            if (ctx.source(role).key !== LIVE_KEY) ctx.setSource(role, LIVE_KEY);
            mix.setGain(key, g);
            if (canWrite) { clearTimeout(timer); timer = setTimeout(save, SAVE_AFTER_MS); }
        }

        rows.addEventListener('input', function (ev) {
            var range = ev.target.closest('[data-mixer="level"]');
            if (range) set(range.closest('[data-track]').dataset.track, Number(range.value) / 100);
        });
        rows.addEventListener('dblclick', function (ev) {
            var range = ev.target.closest('[data-mixer="level"]');
            if (range) set(range.closest('[data-track]').dataset.track, 1);
        });
        rows.addEventListener('click', function (ev) {
            var mute = ev.target.closest('[data-mixer="mute"]');
            if (!mute) return;
            var key = mute.closest('[data-track]').dataset.track;
            set(key, mix.gains()[key] === 0 ? lastAudible[key] : 0);
        });
        body.querySelector('[data-mixer="reset"]').addEventListener('click', function () {
            data.tracks.forEach(function (t) { set(t.key, 1); });
        });
        var render = body.querySelector('[data-mixer="render"]');
        if (render) render.addEventListener('click', function () {
            render.disabled = true;
            save().then(function (ok) {
                return ok === false ? false : ctx.run(options.process);
            }).then(function (ok) {
                say(ok ? 'Mixage en cours d’écriture : il arrivera dans le lot.' : '', ok ? 'ok' : '');
            }).then(function () { render.disabled = false; });
        });
        global.addEventListener('pagehide', function () { if (timer) save(); });

        return { help: 'Mixage : glisser un curseur, double-clic = 100 %' };
    }

    global.WamaSurface.registerBrick('stem_mixer', { title: 'Mixage', mount: mount });
})(window);
