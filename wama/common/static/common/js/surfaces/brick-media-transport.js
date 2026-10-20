/**
 * Brique `media_transport` — le MAGNÉTO d'une surface (2026-10-15, chantier « transport commun »,
 * `ROUTE §F3b` ; 1ᵉʳ consommateur : la page d'édition de la partition du composer).
 *
 * Universelle : elle attache le média d'un rôle lu (`options.role`, défaut `audio`) à l'AXE
 * partagé de la surface (`ctx.axis()`, `wama-axis.js`) et pilote cet axe — jamais une vue
 * (`WAMA_DATA_WORLD §5bis`). Elle ne réécrit aucun lecteur :
 *   • l'onde, la lecture exclusive et le clic-pour-aller sont ceux du lecteur commun
 *     (`WamaAudioPlayer`) ; un audio long reçoit les PICS serveur (`ctx.media()`), pas un
 *     décodage du fichier entier ;
 *   • J/K/L sont ceux de `WamaShuttle` (paliers déclarés), l'arrière silencieux celui de l'axe.
 *
 * Elle dit l'état du process que la surface rejoue (`reruns`) — « périmé » après une
 * modification enregistrée, « en cours » après « Appliquer » — et RECHARGE le média quand ce
 * process et son aval ont fini : on écoute le rendu refait, à la même place.
 */
(function (global) {
    'use strict';

    var RATES = [0.5, 0.75, 1, 1.25, 1.5, 2];
    var STATES = {
        STALE: ['périmé', 'text-bg-warning', 'Une modification enregistrée le périme : « Appliquer » le refait'],
        RUNNING: ['en cours', 'text-bg-info', 'Le média est en train d’être refait'],
        PENDING: ['en attente', 'text-bg-secondary', 'Le traitement attend son tour'],
        AWAITING_RESOURCES: ['en attente', 'text-bg-secondary', 'Le traitement attend que la mémoire GPU se libère'],
        FAILURE: ['échec', 'text-bg-danger', 'Le dernier traitement a échoué'],
    };

    function button(icon, title) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-sm btn-outline-emphasis';
        b.title = title;
        b.innerHTML = '<i class="fas ' + icon + '"></i>';
        return b;
    }

    function mount(body, ctx, options) {
        options = options || {};
        var Player = global.WamaAudioPlayer, Axis = global.WamaAxis;
        var axis = ctx.axis();
        var role = options.role || 'audio';
        var jump = Number(options.jump) || 5;
        var rerun = (ctx.config.surface || {}).reruns || '';
        var playerId = 'surface-' + ctx.config.pk + '-' + role;
        body.classList.add('wama-brick-transport');

        var wave = document.createElement('div');
        wave.className = 'wama-transport-wave';
        var bar = document.createElement('div');
        bar.className = 'wama-transport-bar';
        var toStart = button('fa-backward-step', 'Début (Début)');
        var back = button('fa-rotate-left', '−' + jump + ' s (←)');
        var play = button('fa-play', 'Lecture / pause (Espace)');
        var fwd = button('fa-rotate-right', '+' + jump + ' s (→)');
        var rate = document.createElement('select');
        rate.className = 'form-select form-select-sm wama-transport-rate';
        rate.title = 'Vitesse de lecture';
        RATES.forEach(function (r) {
            var o = document.createElement('option');
            o.value = String(r);
            o.textContent = '×' + r;
            rate.appendChild(o);
        });
        var shuttleOpt = document.createElement('option');
        shuttleOpt.hidden = true;
        rate.appendChild(shuttleOpt);
        var clock = document.createElement('span');
        clock.className = 'wama-transport-clock';
        [toStart, back, play, fwd, rate, clock].forEach(function (el) { bar.appendChild(el); });
        body.appendChild(wave);
        body.appendChild(bar);

        var badge = document.createElement('span');
        badge.className = 'badge d-none';

        var source = '';

        function load(url, bust) {
            source = url || '';
            if (!url) {
                if (Player) Player.destroy(playerId);
                wave.textContent = 'Aucun média à lire pour l’instant.';
                return;
            }
            if (!Player || !axis) { wave.textContent = 'Lecteur commun indisponible.'; return; }
            var keep = axis.time();
            axis.pause();
            axis.detach();
            wave.textContent = '';
            var full = bust ? url + (url.indexOf('?') < 0 ? '?' : '&') + 'v=' + Date.now() : url;
            Player.inject(full, playerId, wave, { height: Number(options.height) || 64 });
            var server = (ctx.media() || {})[role];
            // Les pics d'abord : le lecteur dessine l'onde SANS télécharger un long fichier.
            if (server && server.peaks) Player.setPeaks(playerId, server.peaks);
            var el = Player.getAudio(playerId);
            if (!el) return;
            if (server && server.duration) axis.setDuration(server.duration);
            // Le média joue et se positionne par le lecteur commun : sa lecture EXCLUSIVE, et sa
            // position reposée quand le fichier devient positionnable (métadonnées réclamées à un
            // player à pics serveur) — l'axe et la brique ne les refont pas.
            axis.attach(el, {
                offset: Number(options.offset) || 0,
                play: function () { return Player.play(playerId); },
                seek: function (t) { Player.seek(playerId, t, false); },
            });
            if (keep) axis.seek(keep);
        }

        var shuttle = global.WamaShuttle ? global.WamaShuttle.create({
            apply: function (speed) { axis.shuttle(speed); },
        }) : null;

        toStart.addEventListener('click', function () { axis.seek(0); });
        back.addEventListener('click', function () { axis.jump(-jump); });
        fwd.addEventListener('click', function () { axis.jump(jump); });
        play.addEventListener('click', function () { axis.toggle(); });
        rate.addEventListener('change', function () {
            if (shuttle) shuttle.reset();
            axis.setRate(Number(rate.value) || 1);
        });
        if (axis) axis.bindKeys({ jump: jump, shuttle: shuttle });

        if (axis) axis.subscribe(function (s) {
            play.innerHTML = '<i class="fas ' + (s.playing ? 'fa-pause' : 'fa-play') + '"></i>';
            clock.textContent = Axis.formatTime(s.time, true) + ' / ' + (s.duration ? Axis.formatTime(s.duration) : '--:--');
            if (RATES.indexOf(s.rate) >= 0) {
                rate.value = String(s.rate);
            } else {
                shuttleOpt.value = String(s.rate);
                shuttleOpt.textContent = (s.rate < 0 ? '◀ ×' + (-s.rate) : '×' + s.rate);
                rate.value = shuttleOpt.value;
            }
        });

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
        ctx.on('redone', function (reads) { load((reads || {})[role] || '', true); });

        load((ctx.reads() || {})[role] || '');
        return {
            tools: badge,
            help: 'Transport : Espace = lecture/pause · ←/→ = ±' + jump + ' s (Maj : ×6) · Début/Fin · ' +
                  'J/K/L = arrière / arrêt / avant par crans · clic dans l’onde = y aller',
        };
    }

    global.WamaSurface.registerBrick('media_transport', { title: 'Transport', mount: mount });
})(window);
