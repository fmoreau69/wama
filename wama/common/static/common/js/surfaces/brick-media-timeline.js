/**
 * Brique `media_timeline` — la LIGNE DE TEMPS d'une surface : une VUE du temps, abonnée à l'axe
 * partagé (2026-10-21, ROUTE §F3b, redécoupage décidé par Fabien — l'axe est le temps, le transport
 * ses commandes, les vues le regardent, les outils de domaine agissent pendant la lecture).
 *
 * Une ENVELOPPE de la ligne de temps commune (`wama-timeline.js`, montable hors surface) : elle lui
 * donne l'axe de la surface (`ctx.axis()`), les pics fins du média d'un rôle lu (`options.role`,
 * défaut `audio`), et — pour les couches de segments, la bande de qualité, la minimap et l'outil
 * Bornes — la valeur éditée, le geste d'édition, la sélection et les routes de geste que la surface
 * déclare. Les options de l'emplacement passent telles quelles (`WamaTimeline`).
 *
 * Ce qui reste propre à la brique : les plages que d'autres briques MARQUENT par le bus (`bands`,
 * une liste par brique qui marque) et la relecture des pics quand le média est refait (`redone`).
 */
(function (global) {
    'use strict';

    function mount(body, ctx, options) {
        options = options || {};
        var role = options.role || 'audio';
        var marked = {};
        body.classList.add('wama-brick-timeline');

        var timeline = global.WamaTimeline.mount(body, {
            axis: ctx.axis(),
            options: options,
            segments: options.segments ? function () { return ctx.value(); } : null,
            edit: function (fn) { ctx.edit(fn); },
            select: function (i, opts) { ctx.select(i, opts); },
            routes: ctx.config.routes || {},
            densePeaks: function (poll) { return ctx.peaks(role, poll); },
            bands: function () {
                return Object.keys(marked).reduce(function (all, k) { return all.concat(marked[k]); }, []);
            },
        });

        ctx.on('bands', function (p) {
            if (!p || !p.key) return;
            marked[p.key] = Array.isArray(p.bands) ? p.bands : [];
            timeline.redraw();
        });
        ctx.on('redone', function () { timeline.load(); });

        timeline.load();
        return {
            tools: timeline.tools,
            help: timeline.help,
            refresh: timeline.redraw,
        };
    }

    global.WamaSurface.registerBrick('media_timeline', { title: 'Ligne de temps', mount: mount });
})(window);
