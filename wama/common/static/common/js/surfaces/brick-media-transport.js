/**
 * Brique `media_transport` — le MAGNÉTO d'une surface (2026-10-15, chantier « transport commun »,
 * `ROUTE §F3b` ; 1ᵉʳ consommateur : la page d'édition de la partition du composer).
 *
 * Depuis le 2026-10-21, une ENVELOPPE du transport commun (`wama-transport.js`, montable hors
 * surface — l'aperçu et le monde Data le monteront aussi) : elle lui donne l'axe partagé de la
 * surface (`ctx.axis()`), le média d'un rôle lu (`options.role`, défaut `audio`), et — pour les
 * options de segments (onde fenêtrée et couches, bande de qualité, minimap, outil Bornes, modes
 * d'écriture) — la valeur éditée, le geste d'édition, la sélection et les routes de geste que la
 * surface déclare. Les options de l'emplacement passent telles quelles (`WamaTransport`).
 *
 * Ce qui reste propre à la brique : l'état du process que la surface rejoue (`reruns`) —
 * « périmé » après une modification enregistrée, « en cours » après « Appliquer » — et le
 * RECHARGEMENT du média quand ce process et son aval ont fini : on écoute le rendu refait, à la
 * même place.
 */
(function (global) {
    'use strict';

    var STATES = {
        STALE: ['périmé', 'text-bg-warning', 'Une modification enregistrée le périme : « Appliquer » le refait'],
        RUNNING: ['en cours', 'text-bg-info', 'Le média est en train d’être refait'],
        PENDING: ['en attente', 'text-bg-secondary', 'Le traitement attend son tour'],
        AWAITING_RESOURCES: ['en attente', 'text-bg-secondary', 'Le traitement attend que la mémoire GPU se libère'],
        FAILURE: ['échec', 'text-bg-danger', 'Le dernier traitement a échoué'],
    };

    function mount(body, ctx, options) {
        options = options || {};
        var role = options.role || 'audio';
        var rerun = (ctx.config.surface || {}).reruns || '';
        body.classList.add('wama-brick-transport');

        var transport = global.WamaTransport.mount(body, {
            axis: ctx.axis(),
            // Le lecteur COMMUN (monté par la page de base) : la brique dit ce qu'elle monte.
            player: global.WamaAudioPlayer,
            playerId: 'surface-' + ctx.config.pk + '-' + role,
            options: options,
            segments: options.segments ? function () { return ctx.value(); } : null,
            edit: function (fn) { ctx.edit(fn); },
            select: function (i, opts) { ctx.select(i, opts); },
            routes: ctx.config.routes || {},
            densePeaks: options.window ? function (poll) { return ctx.peaks(role, poll); } : null,
        });

        var badge = document.createElement('span');
        badge.className = 'badge d-none';

        function showState(states) {
            var now = (states || {})[rerun] || '';
            var shown = STATES[now];
            badge.classList.toggle('d-none', !shown);
            if (shown) {
                badge.className = 'badge ' + shown[1];
                badge.textContent = shown[0];
                badge.title = shown[2];
            }
            return now;
        }
        showState(ctx.processes());
        ctx.on('processes', showState);
        // Le média refait (le noyau le dit, `redone`) : même chemin réécrit le plus souvent —
        // d'où l'adresse « fraîche » qui contourne le cache du navigateur.
        ctx.on('redone', function (reads) {
            transport.load((reads || {})[role] || '', (ctx.media() || {})[role], true);
        });

        transport.load((ctx.reads() || {})[role] || '', (ctx.media() || {})[role]);
        return {
            tools: badge,
            help: transport.help,
            refresh: transport.redraw,
        };
    }

    global.WamaSurface.registerBrick('media_transport', { title: 'Transport', mount: mount });
})(window);
