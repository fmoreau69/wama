/**
 * Brique `media_transport` — le MAGNÉTO d'une surface (2026-10-15, chantier « transport commun »,
 * `ROUTE §F3b` ; 1ᵉʳ consommateur : la page d'édition de la partition du composer).
 *
 * Deux pièces, et rien d'autre depuis le redécoupage du 2026-10-21 (décision de Fabien : l'axe est
 * le temps, le transport ses commandes, les vues le regardent, les outils de domaine agissent
 * pendant la lecture) :
 *   • la SOURCE : le média d'un rôle lu (`options.role`, défaut `audio`), joué par le lecteur
 *     COMMUN (`WamaAudioPlayer` — lecture exclusive, position reposée) et ATTACHÉ à l'axe partagé
 *     de la surface (`ctx.axis()`), dont il devient l'horloge. Le lecteur montre sa propre onde
 *     (`options.wave`, vrai par défaut) ; une surface qui monte la ligne de temps la tait ;
 *   • le TRANSPORT commun (`wama-transport.js`, montable hors surface), à qui passent les options
 *     de l'emplacement (`jump`, `speed`, `goto`).
 * L'onde fenêtrée et ses couches sont la brique `media_timeline`, les modes d'écriture la brique
 * `playback_writing` : jusqu'au 21/10 des options d'ici.
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
        var axis = ctx.axis();
        // Le lecteur COMMUN (monté par la page de base) : la brique dit ce qu'elle monte.
        var Player = global.WamaAudioPlayer;
        var playerId = 'surface-' + ctx.config.pk + '-' + role;
        var showWave = options.wave !== false;
        body.classList.add('wama-brick-transport');

        // ── La source : le lecteur commun, attaché à l'axe ──────────────────────────────────
        var playerHost = document.createElement('div');
        playerHost.className = 'wama-transport-wave' + (showWave ? '' : ' wama-transport-player-hidden');
        body.appendChild(playerHost);

        function load(url, serverPeaks, bust) {
            if (!url) {
                if (Player) Player.destroy(playerId);
                playerHost.textContent = 'Aucun média à lire pour l’instant.';
                return;
            }
            if (!Player || !axis) { playerHost.textContent = 'Lecteur commun indisponible.'; return; }
            var keep = axis.time();
            axis.pause();
            axis.detach();
            playerHost.textContent = '';
            var full = bust ? url + (url.indexOf('?') < 0 ? '?' : '&') + 'v=' + Date.now() : url;
            Player.inject(full, playerId, playerHost, { height: Number(options.height) || 64 });
            // Les pics d'abord : le lecteur dessine l'onde SANS télécharger un long fichier.
            if (serverPeaks && serverPeaks.peaks) Player.setPeaks(playerId, serverPeaks.peaks);
            var media = Player.getAudio(playerId);
            if (!media) return;
            if (serverPeaks && serverPeaks.duration) axis.setDuration(serverPeaks.duration);
            // Le média joue et se positionne par le lecteur commun : sa lecture EXCLUSIVE, et sa
            // position reposée quand le fichier devient positionnable — l'axe ne les refait pas.
            axis.attach(media, {
                offset: Number(options.offset) || 0,
                play: function () { return Player.play(playerId); },
                seek: function (t) { Player.seek(playerId, t, false); },
            });
            if (keep) axis.seek(keep);
        }

        // ── Les commandes ───────────────────────────────────────────────────────────────────
        var transport = global.WamaTransport.mount(body, { axis: axis, options: options });

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
            load((reads || {})[role] || '', (ctx.media() || {})[role], true);
        });

        load((ctx.reads() || {})[role] || '', (ctx.media() || {})[role]);
        return {
            tools: badge,
            help: transport.help + (showWave ? ' · clic dans l’onde = y aller' : ''),
        };
    }

    global.WamaSurface.registerBrick('media_transport', { title: 'Transport', mount: mount });
})(window);
