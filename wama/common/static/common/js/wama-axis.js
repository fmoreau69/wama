/**
 * wama-axis.js — L'AXE DE TEMPS PARTAGÉ (chantier « preview globale + transport commun »,
 * `WAMA_APP_GENERATION_ROUTE.md §F3b`, né le 2026-10-15 avec la page d'édition de la partition
 * du composer ; spécification cible : `WAMA_DATA_WORLD.md §5`, le magnéto de BIND, et §5bis).
 *
 * Le constat de la cartographie du 2026-10-01 : aucun transport de WAMA n'avait d'objet AXE —
 * chacun prenait un élément média pour source de vérité et appelait ses vues lui-même. Ici
 * l'axe EST la vérité : le magnéto (`wama-transport.js`, le clavier) lui envoie des
 * COMMANDES, les vues s'y ABONNENT et ne se parlent jamais. La synchronisation est une
 * conséquence du graphe d'observateurs, comme dans `Magneto.m`.
 *
 * Un MÉDIA s'y attache (`attach`) : tant qu'il joue en avant à une vitesse qu'il sait tenir, il
 * est l'HORLOGE (son temps fait foi, la lecture est audible) ; en arrière ou au-delà de
 * `MEDIA_MAX_RATE`, l'axe avance seul et recale le média à intervalles — la lecture arrière
 * silencieuse de l'éditeur du transcriber, écrite une fois. Un `offset` par média le décale
 * (la caméra du cam_analyzer, plus tard).
 *
 *   var axis = WamaAxis.create({duration: 0});
 *   var off  = axis.subscribe(function (s) { … s.time, s.duration, s.playing, s.rate, s.reason });
 *   axis.attach(audioElement, {offset: 0});
 *   axis.play(); axis.pause(); axis.toggle(); axis.seek(12.5); axis.jump(-5);
 *   axis.seek(83, 'goto');                         // un temps NOMMÉ : les vues le montrent
 *   axis.playFrom(20);                             // écouter depuis : le shuttle se rend
 *   axis.setSpeed(1.5);                            // la vitesse CHOISIE (avant), celle de la lecture
 *   axis.shuttle(-2);                              // un cran de shuttle : 0 = arrêt, < 0 = arrière
 *   axis.bindKeys({jump: 5});                      // Espace, ←/→, Début/Fin (+ J/K/L par WamaShuttle)
 *
 * VITESSE ET SHUTTLE (2026-10-20, portage de l'éditeur du transcriber) : la vitesse choisie et le
 * cran du shuttle sont deux choses. Le shuttle l'emporte tant qu'il est engagé (`shuttling`) ;
 * l'arrêter (K), ou Espace pendant qu'il tourne, ou la lecture arrière qui touche le début, le
 * DÉSENGAGE et rend la vitesse choisie — l'axe repassait à ×1, et le sélecteur de vitesse du
 * cam_analyzer avait le défaut inverse (matrice de parité, `§F3b`).
 *
 * Ce qu'il ne fait PAS encore (la matrice de parité de `§F3b` le dit, ligne par ligne) : le pas
 * image fps-aware, N médias synchronisés avec correction de dérive, la position persistée. Le
 * cam_analyzer n'est pas porté : contrainte de Fabien (19/08), « ne rien casser ».
 */
(function (global) {
    'use strict';

    /** Au-delà, un <audio> coupe le son (Chrome) : l'axe avance seul, silencieux. */
    var MEDIA_MAX_RATE = 4;
    /** En lecture silencieuse, le média n'est recalé qu'à cet intervalle (pas une tempête de seeks). */
    var SEEK_EVERY_MS = 90;

    function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }

    /** `m:ss` (`h:mm:ss` au-delà d'une heure), `.d` en option. */
    function formatTime(seconds, tenths) {
        var t = Math.max(0, Number(seconds) || 0);
        var whole = Math.floor(t);
        var h = Math.floor(whole / 3600), m = Math.floor((whole % 3600) / 60), s = whole % 60;
        var out = (h ? h + ':' + String(m).padStart(2, '0') : String(m)) + ':' + String(s).padStart(2, '0');
        return tenths ? out + '.' + Math.floor((t - whole) * 10) : out;
    }

    /** `1:23.4`, `1:23,4`, `83.4`, `1:02:03` → secondes ; null si illisible. */
    function parseTime(text) {
        var parts = String(text || '').trim().replace(/,/g, '.').split(':');
        if (!parts[0] && parts.length === 1) return null;
        var total = 0;
        for (var i = 0; i < parts.length; i++) {
            var n = Number(parts[i]);
            if (!isFinite(n) || n < 0 || parts[i] === '') return null;
            total = total * 60 + n;
        }
        return total;
    }

    function create(opts) {
        opts = opts || {};
        var now = opts.now || function () {
            return (global.performance && global.performance.now) ? global.performance.now() : Date.now();
        };
        var frame = opts.frame || function (fn) {
            return global.requestAnimationFrame ? global.requestAnimationFrame(fn)
                : setTimeout(function () { fn(now()); }, 16);
        };
        var cancelFrame = opts.cancelFrame || function (id) {
            if (global.cancelAnimationFrame) global.cancelAnimationFrame(id); else clearTimeout(id);
        };

        var s = { time: 0, duration: Number(opts.duration) || 0, playing: false, rate: 1,
                  speed: 1, shuttling: false };
        var observers = [];
        var media = null, offset = 0, unlisten = null, playHook = null, seekHook = null;
        var loop = null, last = 0, lastSeek = 0;

        function snapshot(reason) {
            return { time: s.time, duration: s.duration, playing: s.playing, rate: s.rate,
                     speed: s.speed, shuttling: s.shuttling, reason: reason };
        }
        /** Le shuttle rendu : la vitesse redevient celle qu'on a choisie. */
        function disengage() {
            s.shuttling = false;
            s.rate = s.speed;
        }
        function notify(reason) {
            var snap = snapshot(reason);
            observers.slice().forEach(function (fn) {
                try { fn(snap); } catch (e) { if (global.console) console.error('[axis]', e); }
            });
        }
        function end() { return s.duration > 0 ? s.duration : Infinity; }

        /** Le média joue-t-il lui-même (horloge audible) ? */
        function mediaIsClock() { return !!media && s.playing && s.rate > 0 && s.rate <= MEDIA_MAX_RATE; }

        function setMediaTime(t) {
            if (!media) return;
            // Le crochet du lecteur qui possède le média (`WamaAudioPlayer.seek` : il repose une
            // position demandée avant que le fichier ne soit positionnable, et réclame ses
            // métadonnées à un player à pics serveur) — l'axe ne le refait pas.
            if (seekHook) { seekHook(Math.max(0, t + offset)); return; }
            try { media.currentTime = Math.max(0, t + offset); } catch (e) { /* métadonnées pas encore là */ }
        }

        function pauseMedia() {
            if (media && !media.paused) media.pause();
        }

        /** Le média suit l'état de l'axe : il joue (horloge) ou se tait (lecture silencieuse). */
        function syncMedia() {
            if (!media) return;
            if (mediaIsClock()) {
                try { media.playbackRate = s.rate; } catch (e) { /* vitesse refusée : 1 */ }
                if (media.paused) {
                    // Le crochet du lecteur qui possède le média (la lecture EXCLUSIVE de
                    // `WamaAudioPlayer.play`, qui coupe les autres lecteurs de la page).
                    var p = playHook ? playHook() : media.play();
                    if (p && p.catch) p.catch(function () { s.playing = false; notify('state'); });
                }
            } else {
                pauseMedia();
            }
        }

        function tick(ts) {
            loop = null;
            if (!s.playing) return;
            var t = typeof ts === 'number' ? ts : now();
            var dt = Math.max(0, (t - last) / 1000);
            last = t;
            if (mediaIsClock()) {
                s.time = clamp(media.currentTime - offset, 0, end());
            } else {
                s.time += dt * s.rate;
                if (s.time <= 0) { s.time = 0; s.playing = false; }
                else if (s.time >= end()) { s.time = end(); s.playing = false; }
                if (!s.playing && s.shuttling) disengage();      // arrivé au bord : shuttle rendu
                if (media && (t - lastSeek >= SEEK_EVERY_MS || !s.playing)) { lastSeek = t; setMediaTime(s.time); }
            }
            notify(s.playing ? 'tick' : 'state');
            if (s.playing) loop = frame(tick);
        }
        function run() {
            if (loop) return;
            last = now();
            loop = frame(tick);
        }
        function halt() {
            if (loop) { cancelFrame(loop); loop = null; }
        }

        /** Une vitesse que le média sait tenir lui est posée TOUT DE SUITE, même à l'arrêt : une
         *  lecture lancée depuis le média lui-même (son bouton) part à la vitesse choisie. */
        function rateToMedia() {
            if (media && s.rate > 0 && s.rate <= MEDIA_MAX_RATE) {
                try { media.playbackRate = s.rate; } catch (e) { /* vitesse refusée */ }
            }
        }
        function applyRate(r) {
            s.rate = r;
            rateToMedia();
            if (s.playing) { syncMedia(); last = now(); run(); }
            notify('rate');
        }

        var axis = {
            time: function () { return s.time; },
            duration: function () { return s.duration; },
            playing: function () { return s.playing; },
            rate: function () { return s.rate; },
            media: function () { return media; },

            /** S'abonner : `fn(état)` à chaque changement — et tout de suite, avec l'état présent.
             *  Rend la fonction qui désabonne. */
            subscribe: function (fn) {
                observers.push(fn);
                try { fn(snapshot('subscribe')); } catch (e) { if (global.console) console.error('[axis]', e); }
                return function () { observers = observers.filter(function (o) { return o !== fn; }); };
            },

            setDuration: function (d) {
                d = Number(d) || 0;
                if (d === s.duration) return;
                s.duration = d;
                if (d > 0 && s.time > d) s.time = d;
                notify('duration');
            },

            play: function () {
                if (s.playing) return;
                if (s.rate > 0 && s.duration > 0 && s.time >= s.duration) axis.seek(0);
                if (s.rate < 0 && s.time <= 0) return;
                s.playing = true;
                syncMedia();
                run();
                notify('state');
            },
            pause: function () {
                if (!s.playing) return;
                s.playing = false;
                halt();
                if (media) {
                    pauseMedia();
                    s.time = clamp(media.currentTime - offset, 0, end());
                }
                notify('state');
            },
            speed: function () { return s.speed; },
            shuttling: function () { return s.shuttling; },

            /** Espace : pendant le shuttle, il le REND et s'arrête (le geste de l'éditeur) ;
             *  sinon lecture / pause à la vitesse choisie. */
            toggle: function () {
                if (s.shuttling) {
                    var was = s.playing;
                    disengage();
                    if (was) axis.pause(); else notify('rate');
                    return;
                }
                if (s.playing) axis.pause(); else axis.play();
            },
            stop: function () { axis.pause(); axis.seek(0); },

            /** Aller à `t`. `reason` dit aux abonnés POURQUOI (défaut `seek`) : `goto`, un temps
             *  nommé (« aller à ») — une vue fenêtrée le montre au centre, une liste choisit ce
             *  qui s'y trouve. L'axe ne connaît aucune vue : il le dit, elles décident. */
            seek: function (t, reason) {
                s.time = clamp(Number(t) || 0, 0, end());
                setMediaTime(s.time);
                last = now();
                notify(reason || 'seek');
            },
            jump: function (dt) { axis.seek(s.time + (Number(dt) || 0)); },
            /** Écouter depuis `t` (un segment, une proposition) : le shuttle se rend d'abord. */
            playFrom: function (t) {
                if (s.shuttling) axis.shuttle(0);
                axis.seek(t);
                axis.play();
            },

            /** Vitesse signée : < 0 = arrière (silencieux). 0 n'est pas une vitesse : c'est `pause`.
             *  Une vitesse positive devient la vitesse CHOISIE, et rend le shuttle. */
            setRate: function (r) {
                r = Number(r) || 0;
                if (!r) { axis.pause(); return; }
                s.shuttling = false;
                if (r > 0) s.speed = r;
                applyRate(r);
            },
            /** La vitesse choisie (avant) : celle de la lecture, à laquelle le shuttle revient.
             *  Pendant le shuttle, elle est retenue sans interrompre le cran en cours. */
            setSpeed: function (r) {
                r = Number(r) || 0;
                if (r <= 0) return;
                s.speed = r;
                if (s.shuttling) { notify('rate'); return; }
                applyRate(r);
            },
            /** Le geste du shuttle (J/K/L) : un cran ET la lecture ; 0 = arrêt, vitesse choisie rendue. */
            shuttle: function (level) {
                level = Number(level) || 0;
                if (!level) { axis.pause(); disengage(); notify('rate'); return; }
                s.shuttling = true;
                applyRate(level);
                axis.play();
            },

            /** Attache un <audio>/<video> : il devient l'horloge quand il joue en avant. Un geste
             *  sur le média lui-même (son bouton, un clic dans son onde) est suivi par l'axe.
             *  `o.offset` le décale ; `o.play` et `o.seek(t)` le font jouer et le positionnent à la
             *  place de `el.play()` / `el.currentTime` — le lecteur qui le possède garde ainsi SES
             *  règles (lecture exclusive, position reposée quand le fichier devient positionnable).
             *  Rend la fonction qui détache. */
            attach: function (el, o) {
                axis.detach();
                if (!el) return function () {};
                o = o || {};
                media = el;
                offset = Number(o.offset) || 0;
                playHook = typeof o.play === 'function' ? o.play : null;
                seekHook = typeof o.seek === 'function' ? o.seek : null;
                var handlers = {
                    loadedmetadata: function () {
                        if (isFinite(el.duration) && el.duration > 0 && !s.duration) axis.setDuration(el.duration - offset);
                    },
                    play: function () {
                        if (s.playing) return;
                        if (!(s.rate > 0 && s.rate <= MEDIA_MAX_RATE)) disengage();
                        rateToMedia();
                        s.playing = true;
                        run();
                        notify('state');
                    },
                    pause: function () {
                        // Une pause que l'axe a faite lui-même (lecture arrière ou trop rapide,
                        // `pause()`) le trouve déjà hors horloge : seule celle de l'utilisateur
                        // sur le média arrête l'axe.
                        if (!mediaIsClock()) return;
                        s.playing = false;
                        halt();
                        s.time = clamp(el.currentTime - offset, 0, end());
                        notify('state');
                    },
                    ended: function () {
                        s.playing = false;
                        if (s.shuttling) disengage();
                        halt();
                        s.time = end() === Infinity ? el.currentTime - offset : end();
                        notify('state');
                    },
                    seeked: function () {
                        if (s.playing) return;           // pendant la lecture, l'horloge suffit
                        var t = clamp(el.currentTime - offset, 0, end());
                        if (Math.abs(t - s.time) > 0.01) { s.time = t; notify('seek'); }
                    },
                };
                Object.keys(handlers).forEach(function (k) { el.addEventListener(k, handlers[k]); });
                handlers.loadedmetadata();
                unlisten = function () {
                    Object.keys(handlers).forEach(function (k) { el.removeEventListener(k, handlers[k]); });
                };
                if (s.time) setMediaTime(s.time);
                rateToMedia();
                return axis.detach;
            },
            detach: function () {
                if (unlisten) unlisten();
                unlisten = null;
                if (media) pauseMedia();
                media = null;
                playHook = null;
                seekHook = null;
            },

            /** Le clavier du magnéto (`WAMA_DATA_WORLD §5`) : Espace, ←/→ (±`jump` s), Début/Fin,
             *  et J/K/L si un shuttle est donné (`WamaShuttle.create`). Le transport est une brique
             *  PRIORITAIRE du clavier commun (`wama-keys.js`, qui décide à qui revient une frappe :
             *  jamais pendant une saisie, ni à travers une modale, ni à la place d'un contrôle
             *  atteint au clavier) ; sans Ctrl/Alt/Méta (Ctrl+Z est à l'historique commun), sauf
             *  Ctrl+Espace, lecture/pause MÊME en saisie. Rend la fonction qui délie. */
            bindKeys: function (o) {
                o = o || {};
                var jump = Number(o.jump) || 5;
                var spaceTarget = null;
                function handle(e) {
                    if (o.enabled && !o.enabled()) return false;
                    if (e.code === 'Space' && e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey) {
                        axis.toggle();
                        return true;
                    }
                    if (e.ctrlKey || e.metaKey || e.altKey) return false;
                    switch (e.code) {
                        case 'Space': axis.toggle(); spaceTarget = e.target; return true;
                        case 'ArrowLeft': axis.jump(e.shiftKey ? -jump * 6 : -jump); return true;
                        case 'ArrowRight': axis.jump(e.shiftKey ? jump * 6 : jump); return true;
                        case 'Home': axis.seek(0); return true;
                        case 'End': if (s.duration) axis.seek(s.duration); return true;
                        case 'KeyL': if (o.shuttle) { o.shuttle.forward(); return true; } return false;
                        case 'KeyJ': if (o.shuttle) { o.shuttle.reverse(); return true; } return false;
                        case 'KeyK': if (o.shuttle) { o.shuttle.stop(); return true; } return false;
                        default: return false;
                    }
                }
                // Espace pris au transport sur un contrôle cliqué : son relâché ne l'active pas
                // (un bouton s'active au relâché d'Espace).
                function onKeyUp(e) {
                    if (e.code === 'Space' && spaceTarget && e.target === spaceTarget) e.preventDefault();
                    if (e.code === 'Space') spaceTarget = null;
                }
                var off = global.WamaKeys.register({ owner: 'media_transport', scope: 'page',
                                                     typing: ['Ctrl+Space'], handle: handle });
                document.addEventListener('keyup', onKeyUp);
                // Le shuttle RENDU par l'axe (Espace, arrivée au bord, lecture sur le média) : son
                // échelle repart du stop, sinon le prochain L reprendrait au cran d'avant.
                var unsubscribe = o.shuttle && o.shuttle.reset ? axis.subscribe(function (st) {
                    if (!st.shuttling && o.shuttle.speed && o.shuttle.speed() !== 0) o.shuttle.reset();
                }) : null;
                return function () {
                    off();
                    document.removeEventListener('keyup', onKeyUp);
                    if (unsubscribe) unsubscribe();
                };
            },
        };
        return axis;
    }

    global.WamaAxis = {
        create: create, formatTime: formatTime, parseTime: parseTime,
        MEDIA_MAX_RATE: MEDIA_MAX_RATE,
    };
})(window);
