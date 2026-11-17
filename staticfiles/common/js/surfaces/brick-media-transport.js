/**
 * Brique `media_transport` — le MAGNÉTO d'une surface (2026-10-15, chantier « transport commun »,
 * `ROUTE §F3b` ; 1ᵉʳ consommateur : la page d'édition de la partition du composer).
 *
 * Deux pièces, et rien d'autre depuis le redécoupage du 2026-10-21 (décision de Fabien : l'axe est
 * le temps, le transport ses commandes, les vues le regardent, les outils de domaine agissent
 * pendant la lecture) :
 *   • la SOURCE : le média d'un rôle lu (`options.role`, défaut `audio`), joué par le lecteur
 *     COMMUN (`WamaAudioPlayer` — lecture exclusive, position reposée) et ATTACHÉ à l'axe partagé
 *     de la surface (`ctx.axis()`), qu'il SUIT : l'axe est la seule horloge (2026-11-02, le média
 *     n'en est plus le maître). Le lecteur montre sa propre onde (`options.wave`, vrai par
 *     défaut) ; une surface qui monte la ligne de temps la tait ;
 *   • le TRANSPORT commun (`wama-transport.js`, montable hors surface), à qui passent les options
 *     de l'emplacement (`jump`, `speed`, `goto`).
 * L'onde fenêtrée et ses couches sont la brique `media_timeline`, les modes d'écriture la brique
 * `playback_writing` : jusqu'au 21/10 des options d'ici.
 *
 * Ce qui reste propre à la brique : l'état du process que la surface rejoue (`reruns`) —
 * « périmé » après une modification enregistrée, « en cours » après « Appliquer » — et le
 * RECHARGEMENT du média quand ce process et son aval ont fini : on écoute le rendu refait, à la
 * même place.
 *
 * SANS SOURCE (`options.media: false`, 2026-10-29) : les commandes seules. L'axe tient l'horloge
 * sans aucun média ; une vidéo, s'il y en a, est une vue qui le suit (`video_view`, les analyses
 * du face_analyzer).
 *
 * La VERSION écoutée (2026-10-21, demande de Fabien : « se rendre compte à l'oreille de
 * l'amélioration ou de la détérioration de l'audio ») : quand le média lu a plusieurs versions
 * (`ctx.sources()` — l'original et les sorties des process du même type, que le serveur DÉRIVE
 * du pipeline : l'audio nivelé, débruité), un choix « Écouter » les propose. La source est
 * l'enveloppe : elle recharge le lecteur à la même position, et le dit au bus (`ctx.setSource` →
 * `source`) — la ligne de temps relit alors les pics de la même version.
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
        // Monté hors d'une page (`WamaSurface.view`, la visionneuse) : un autre lecteur que celui de
        // la page du même élément, ouverte derrière.
        var playerId = (ctx.config.scope || 'surface') + '-' + ctx.config.pk + '-' + role;
        var showWave = options.wave !== false;
        // Ce sous quoi le transport GARDE la position (`options.remember`) : la page et son élément.
        var key = ((ctx.config.surface || {}).id || 'surface') + '.' + ctx.config.pk;
        body.classList.add('wama-brick-transport');
        if (options.media === false) {
            // Les commandes seules : une autre brique tient l'horloge (`video_view`).
            global.WamaTransport.mount(body, { axis: axis, options: options, key: key });
            return {};
        }

        // ── La source : le lecteur commun, attaché à l'axe ──────────────────────────────────
        var playerHost = document.createElement('div');
        playerHost.className = 'wama-transport-wave' + (showWave ? '' : ' wama-transport-player-hidden');
        body.appendChild(playerHost);
        // Le suiveur de CETTE brique : on ne détache que lui (l'axe en suit d'autres, peut-être).
        var dropMedia = null;
        function drop() { if (dropMedia) { dropMedia(); dropMedia = null; } }

        /** `start` : l'instant de l'axe où ce média COMMENCE (une version rendue dans la page qui suit
         *  les repères d'une partition, `WamaMidiPlayer.render`, 2026-11-15) — son suiveur est
         *  décalé d'autant ; 0 pour un média qui commence avec l'axe.
         *  La lecture CONTINUE (2026-11-16, Fabien : passer de l'audio au MIDI « sans interruption de
         *  la lecture ») : l'ancien média est détaché, le nouveau s'attache à l'axe qui tourne et
         *  part à son temps (`axis.attach`) — l'axe ne s'arrête plus à chaque version écoutée. */
        function load(url, serverPeaks, bust, start) {
            if (!url) {
                drop();
                if (Player) Player.destroy(playerId);
                playerHost.textContent = 'Aucun média à lire pour l’instant.';
                return;
            }
            if (!Player || !axis) { playerHost.textContent = 'Lecteur commun indisponible.'; return; }
            var keep = axis.time();
            drop();
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
            // (`Player.follow`, que l'aperçu emprunte aussi pour ses sons.)
            dropMedia = Player.follow(playerId, axis, (Number(options.offset) || 0) - (Number(start) || 0));
            // À l'arrêt, le nouveau média se pose au temps gardé ; en lecture, l'attache l'y a fait
            // partir (un `seek` recalerait aussi les autres médias de l'axe, pour rien).
            if (keep && !axis.playing()) axis.seek(keep);
        }

        /** Une version EN DIRECT (2026-11-17, le mixage des pistes, `wama-stem-mix.js`) : un média
         *  sans fichier, fait dans la page, que l'axe suit comme les autres (`axis.attach`, avec le
         *  recalage qu'il demande, `sync`) — pas de lecteur ni d'onde : le lecteur se le dit. */
        function attachLive(version) {
            if (!axis) return;
            var keep = axis.time();
            drop();
            if (Player) Player.destroy(playerId);
            playerHost.textContent = version.from ? 'En direct : ' + version.from : 'En direct';
            var media = version.media;
            dropMedia = axis.attach(media, { offset: (Number(options.offset) || 0) - (Number(version.start) || 0),
                                             sync: version.sync });
            if (keep && !axis.playing()) axis.seek(keep);
        }

        // ── Les commandes ───────────────────────────────────────────────────────────────────
        // Un hôte qui donne déjà les touches du temps à l'axe (la visionneuse, `WamaSurface.view`) :
        // les nôtres ne s'inscrivent pas à la page, une frappe ne joue pas deux fois.
        var transport = global.WamaTransport.mount(body, { axis: axis, options: options, key: key,
                                                           keys: !ctx.config.host_keys });

        var badge = document.createElement('span');
        badge.className = 'badge d-none';
        var tools = document.createElement('span');
        tools.className = 'd-inline-flex align-items-center gap-1';

        // ── La version écoutée ──────────────────────────────────────────────────────────────
        // Reconstruite quand une version ARRIVE (`ctx.addSource`, émis `sources` — 2026-11-08 : la
        // lecture MIDI d'une partition, faite dans la page) : une partition sans audio n'avait
        // aucune version, elle en gagne.
        var pick = null;
        function buildPick() {
            var versions = (ctx.sources() || {})[role] || [];
            if (pick) { pick.remove(); pick = null; }
            if (versions.length < 2 && !(versions.length === 1 && versions[0].render)) return;
            pick = document.createElement('select');
            pick.className = 'form-select form-select-sm py-0 w-auto';
            pick.title = 'Écouter : la version du média que lit le lecteur';
            pick.setAttribute('aria-label', 'Écouter');
            pick.dataset.transport = 'source';
            var current = ctx.source(role).key;
            // Aucun média lu (une partition sans audio) : rien n'est choisi tant qu'on ne choisit pas.
            if (!versions.some(function (v) { return v.key === current; })) {
                versions = [{ key: current, label: '— choisir une lecture —' }].concat(versions);
            }
            versions.forEach(function (version) {
                var option = document.createElement('option');
                option.value = version.key;
                option.textContent = version.label;
                pick.appendChild(option);
            });
            pick.value = current;
            pick.addEventListener('change', function () { ctx.setSource(role, pick.value); });
            tools.insertBefore(pick, badge);
        }
        tools.appendChild(badge);
        buildPick();
        ctx.on('sources', function (p) { if (p && p.role === role) buildPick(); });

        /** La version choisie : jouée, ou RENDUE d'abord quand elle se fait dans la page (`render`) —
         *  le rendu dit d'où vient le son (`from`), jamais une substitution muette. Le rendu rend une
         *  adresse (`url`, la lecture MIDI) ou un média EN DIRECT (`media`, le mixage). */
        function play(version, bust) {
            if (version.media) { attachLive(version); return; }
            if (version.url || !version.render) {
                load(version.url, version.peaks, bust, version.start);
                return;
            }
            // Dit dans le lecteur ET à la page : une onde tue (ligne de temps, visionneuse) le cacherait.
            var busy = 'Rendu de « ' + (version.label || 'la version') + ' »…';
            playerHost.textContent = busy;
            ctx.status(busy, 'busy');
            version.render().then(function (got) {
                version.url = got.url;
                version.media = got.media;
                version.sync = got.sync;
                version.start = got.start || 0;
                if (got.from) version.from = got.from;
                if (ctx.source(role).key !== version.key) return;      // un autre choix entre-temps
                if (got.media) attachLive(version); else load(got.url, null, false, version.start);
                ctx.status(got.from ? 'Lecture : ' + got.from : '', got.from ? 'ok' : '');
            }).catch(function (e) {
                playerHost.textContent = 'Rendu impossible : ' + e.message;
                ctx.status('Rendu impossible : ' + e.message, 'error');
            });
        }
        ctx.on('source', function (p) {
            if (!p || p.role !== role) return;
            // Choisie par une AUTRE brique (2026-11-17 : bouger une piste du mixage passe au mixage) :
            // la liste « Écouter » le dit — elle montrait encore la version d'avant.
            if (pick && pick.value !== p.key) pick.value = p.key;
            play(ctx.source(role));
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
        ctx.on('redone', function () {
            var version = ctx.source(role);
            if (version.render) return;          // faite dans la page : le serveur n'y a rien refait
            load(version.url, version.peaks, true);
        });

        var first = ctx.source(role);
        play(first);
        return {
            tools: tools,
            help: showWave ? 'Transport : clic dans l’onde = y aller' : null,
        };
    }

    // `dockable` (2026-10-26) : le transport s'épingle à un bord de la fenêtre (le geste est à la
    // disposition commune, `wama-brick-layout.js`) — il reste sous la main quand la partition défile. Tout panneau
    // s'épingle disposition modifiable ; `dockable` laisse l'épingle à portée même figée.
    global.WamaSurface.registerBrick('media_transport', { title: 'Transport', mount: mount, dockable: true });
})(window);
