/**
 * wama-axis.js — L'AXE DE TEMPS PARTAGÉ (chantier « preview globale + transport commun »,
 * `WAMA_APP_GENERATION_ROUTE.md §F3b`, né le 2026-10-15 avec la page d'édition de la partition
 * du composer ; spécification cible : `WAMA_DATA_WORLD.md §2` et §5, le magnéto de BIND, et §5bis).
 *
 * Le constat de la cartographie du 2026-10-01 : aucun transport de WAMA n'avait d'objet AXE —
 * chacun prenait un élément média pour source de vérité et appelait ses vues lui-même. Ici
 * l'axe EST la vérité : le magnéto (`wama-transport.js`, le clavier) lui envoie des
 * COMMANDES, les vues s'y ABONNENT et ne se parlent jamais. La synchronisation est une
 * conséquence du graphe d'observateurs, comme dans `Magneto.m`.
 *
 * L'AXE EST LA SEULE HORLOGE (décision de Fabien, 2026-11-02 — le modèle de BIND, où `TimerTrip`
 * avance seul et où le lecteur vidéo n'est qu'un observateur). Il avance en secondes réelles,
 * `temps + écoulé × vitesse` (`TimerTrip.m:354`), sans rien connaître des cadences de ce qui s'y
 * synchronise, et ne dépend de rien : ni d'un média, ni d'une donnée. Jusqu'à cette date, un média
 * qui jouait en avant DEVENAIT l'horloge — « média maître » : une session sans média, plusieurs
 * médias sur un axe ou une durée propre à l'axe étaient impossibles.
 *
 * Un MÉDIA est un SUIVEUR (`attach`, autant qu'il en faut, un `offset` chacun) : il joue lui-même
 * (la lecture reste audible) à la vitesse de l'axe, et l'axe le RECALE en deux niveaux — un petit
 * écart se rattrape par une vitesse à peine corrigée (le navigateur garde la hauteur du son), un
 * grand par un repositionnement. Les deux seuils sont des RÉGLAGES (`SYNC`, `create({sync})`,
 * `attach(el, {sync})`). En arrière ou au-delà de `MEDIA_MAX_RATE`, il se tait et l'axe le recale
 * à intervalles — la lecture arrière silencieuse de l'éditeur du transcriber. Un geste fait sur le
 * média lui-même (son bouton, un clic dans son onde) est une COMMANDE à l'axe, jamais une horloge.
 * L'axe n'attend pas un média qui charge : son image se fige, puis rattrape le temps juste.
 * ⚠ Une surcouche dessinée SUR un média suit l'image que ce média affiche (`el.currentTime`), pas
 * l'axe : un cadre de détection doit tomber sur l'image montrée.
 *
 * Une VUE de donnée montre l'échantillon le plus PROCHE du temps de l'axe (BIND n'interpole jamais,
 * `WAMA_DATA_WORLD §3`). L'axe bat au rythme de l'écran, quelle que soit la cadence des données
 * (2 000 Hz ne demandent pas 2 000 battements) ; ce qui s'y pose DÉCLARE sa cadence (`cadence(hz)`,
 * `attach(el, {fps})`), et le PAS (`step`) est celui de la plus fine. Sous charge, il espace ses
 * avis aux abonnés, jamais la justesse du temps (`TimerTrip.m:369-376` : au-delà de 80 % du temps
 * d'une image, un avis sur deux, puis sur trois… ; sous 20 %, il revient).
 *
 *   var axis = WamaAxis.create({duration: 0});
 *   var off  = axis.subscribe(function (s) { … s.time, s.duration, s.playing, s.rate, s.reason });
 *   var drop = axis.attach(audioElement, {offset: 0});   // un suiveur ; `drop()` le détache
 *   axis.play(); axis.pause(); axis.toggle(); axis.seek(12.5); axis.jump(-5);
 *   axis.seek(83, 'goto');                         // un temps NOMMÉ : les vues le montrent
 *   axis.playFrom(20);                             // écouter depuis : le shuttle se rend
 *   axis.setSpeed(1.5);                            // la vitesse CHOISIE (avant), celle de la lecture
 *   axis.shuttle(-2);                              // un cran de shuttle : 0 = arrêt, < 0 = arrière
 *   var gone = axis.cadence(2000); axis.step(1);   // un échantillon plus loin (0,5 ms)
 *   axis.bindKeys({jump: 5});                      // Espace, ←/→, Début/Fin (+ J/K/L par WamaShuttle)
 *
 * VITESSE ET SHUTTLE (2026-10-20, portage de l'éditeur du transcriber) : la vitesse choisie et le
 * cran du shuttle sont deux choses. Le shuttle l'emporte tant qu'il est engagé (`shuttling`) ;
 * l'arrêter (K), ou Espace pendant qu'il tourne, ou la lecture arrière qui touche le début, le
 * DÉSENGAGE et rend la vitesse choisie — l'axe repassait à ×1, et le sélecteur de vitesse du
 * cam_analyzer avait le défaut inverse (matrice de parité, `§F3b`).
 *
 * Ce qu'il ne fait PAS encore (la matrice de parité de `§F3b` le dit, ligne par ligne) : la
 * position persistée. Le cam_analyzer n'est pas porté : contrainte de Fabien (19/08), « ne rien
 * casser ».
 */
(function (global) {
    'use strict';

    /** Au-delà, un <audio> coupe le son (Chrome) : le média se tait, l'axe le recale. */
    var MEDIA_MAX_RATE = 4;
    /** Un média qui se tait n'est recalé qu'à cet intervalle (pas une tempête de seeks). */
    var SEEK_EVERY_MS = 90;
    /** Le recalage d'un suiveur, en secondes (des RÉGLAGES — Fabien, 2026-11-02) : sous
     *  `tolerance`, rien ; jusqu'à `reseek`, un RATTRAPAGE à vitesse FIXE (± `maxNudge`, 5 %) tenu
     *  jusqu'à ce que l'écart s'annule ; au-delà, un repositionnement. L'écart est LISSÉ (`smoothing`) :
     *  `currentTime` avance par paliers. ⚠ Mesuré sur une card réelle (composer #880, 2026-11-02) :
     *  une vitesse corrigée en proportion de l'écart changeait à chaque battement, chaque changement
     *  coûtait au lecteur, et l'audio restait ~30 ms derrière en jouant à ×1,03 en permanence ; à
     *  vitesse fixe, la vitesse ne change que deux fois par rattrapage. */
    var SYNC = { tolerance: 0.02, reseek: 0.15, maxNudge: 0.05, smoothing: 0.3 };
    /** Un `play` / `pause` du média dans ce délai après que l'axe l'a demandé est le sien (les
     *  événements du média arrivent après coup ; une lecture refusée n'en envoie aucun). */
    var OWN_EVENT_MS = 500;
    /** Le pas quand rien n'a déclaré sa cadence. */
    var DEFAULT_STEP = 1 / 30;
    /** Les avis aux abonnés s'espacent au plus jusqu'à un sur `MAX_SKIP` images. */
    var MAX_SKIP = 6;
    /** Le temps d'une image (ms) : le budget d'un avis. Pas l'écart mesuré entre deux battements,
     *  qui contient déjà le temps passé chez les abonnés — un abonné lent n'y paraîtrait jamais lent. */
    var FRAME_MS = 1000 / 60;

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
        var sync = Object.assign({}, SYNC, opts.sync || {});

        var s = { time: 0, duration: Number(opts.duration) || 0, playing: false, rate: 1,
                  speed: 1, shuttling: false };
        var observers = [];
        var followers = [];
        var cadences = [];
        var loop = null, last = 0;
        var skip = 1, skipped = 0;

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

        // ── Les suiveurs ────────────────────────────────────────────────────────────────────
        /** Les médias joueraient-ils eux-mêmes (lecture audible) ? */
        function audible() { return s.playing && s.rate > 0 && s.rate <= MEDIA_MAX_RATE; }
        /** Le temps du média qui correspond au temps de l'axe. */
        function target(f) { return s.time + f.offset; }
        /** L'axe est-il dans ce que le média couvre ? (un média décalé commence plus tard) */
        function covers(f) {
            var t = target(f), d = f.el.duration;
            return t >= 0 && !(isFinite(d) && d > 0 && t >= d);
        }
        function place(f) {
            var t = Math.max(0, target(f));
            f.placedTo = t;
            f.drift = null;                  // un écart d'avant le positionnement ne dit plus rien
            f.catching = 0;
            f.sounding = false;              // reposé (au-delà de sa fin, par exemple) : relançable
            // Le crochet du lecteur qui possède le média (`WamaAudioPlayer.seek` : il repose une
            // position demandée avant que le fichier ne soit positionnable, et réclame ses
            // métadonnées à un player à pics serveur) — l'axe ne le refait pas.
            if (f.seek) { f.seek(t); return; }
            // Le média vient de s'y poser LUI-MÊME (un geste sur ses contrôles, dont l'axe fait une
            // commande, `here`) : le reposer referait un décodage pour rien (mesuré sur le banc de
            // l'aperçu, deux positionnements par geste). Partout ailleurs on repose, même à
            // `currentTime` égal : à la pause, une vidéo peut déjà MONTRER l'image suivante (mesuré :
            // deux vidéos de Comparer arrêtées sur deux images, sans ce repositionnement).
            var here = f.here;
            f.here = null;
            if (here != null && Math.abs(here - t) < 1e-3) return;
            try { f.el.currentTime = t; } catch (e) { /* métadonnées pas encore là */ }
        }
        function rateOf(f, r) {
            f.ownRate = r;
            try { if (f.el.playbackRate !== r) f.el.playbackRate = r; } catch (e) { /* vitesse refusée */ }
        }
        function hush(f) {
            f.sounding = false;
            if (f.el.paused) return;
            f.pausedAt = now();
            f.el.pause();
        }
        function sound(f) {
            if (!f.el.paused) { f.sounding = true; return; }
            // Arrêté sans que l'axe l'ait tu : un geste sur le média (son bouton, Espace sur ses
            // contrôles natifs) dont l'événement n'est pas encore arrivé, ou une lecture refusée.
            // L'axe ne le relance pas — son `pause` dira le geste. Mesuré au navigateur sur la
            // visionneuse (2026-11-05) : la relance passait AVANT l'événement, d'où une lecture et
            // une pause parasites à chaque pause au clavier. Un positionnement (`place`) ou un
            // silence de l'axe (`hush`) le rend de nouveau relançable.
            if (f.sounding) return;
            f.sounding = true;
            f.playedAt = now();
            // Le crochet du lecteur qui possède le média (la lecture EXCLUSIVE de
            // `WamaAudioPlayer.play`, qui coupe les autres lecteurs de la page).
            var p = f.play ? f.play() : f.el.play();
            // Lecture refusée (navigateur) : le média se tait, l'axe continue — il ne dépend de rien.
            if (p && p.catch) p.catch(function () { /* rien à défaire */ });
        }
        function ours(at) { return at != null && now() - at < OWN_EVENT_MS; }
        /** Recale UN suiveur sur l'axe. `at` : l'instant (ms) du battement, pour espacer les seeks. */
        function follow(f, at) {
            if (!audible() || !covers(f)) {
                hush(f);
                if (at == null || !s.playing || at - f.lastSeek >= SEEK_EVERY_MS) {
                    f.lastSeek = at == null ? now() : at;
                    place(f);
                }
                return;
            }
            if (f.el.readyState === 0 || f.el.seeking) { sound(f); return; }
            var raw = (f.el.currentTime - f.offset) - s.time;        // > 0 : le média est en avance
            var c = f.sync;
            if (Math.abs(raw) > c.reseek) {                          // un décrochage : on repose
                rateOf(f, s.rate);
                place(f);
                sound(f);
                return;
            }
            f.drift = f.drift == null ? raw : f.drift + c.smoothing * (raw - f.drift);
            // Un rattrapage commence au-delà de la tolérance et se TIENT jusqu'à ce que l'écart
            // s'annule (en retard : +maxNudge ; en avance : −maxNudge) — deux changements de vitesse.
            if (!f.catching && Math.abs(f.drift) > c.tolerance) f.catching = f.drift < 0 ? 1 : -1;
            else if (f.catching * f.drift >= 0) f.catching = 0;
            rateOf(f, s.rate * (1 + f.catching * c.maxNudge));
            sound(f);
        }
        function followAll(at) { followers.forEach(function (f) { follow(f, at); }); }
        /** L'axe arrêté : chaque média se tait, posé au temps de l'axe — l'image dit l'instant. */
        function settleAll() {
            followers.forEach(function (f) { hush(f); place(f); });
        }
        /** Une vitesse que le média sait tenir lui est posée TOUT DE SUITE, même à l'arrêt : une
         *  lecture lancée depuis le média lui-même (son bouton) part à la vitesse choisie. */
        function rateToFollowers() {
            if (!(s.rate > 0 && s.rate <= MEDIA_MAX_RATE)) return;
            followers.forEach(function (f) { rateOf(f, s.rate); });
        }

        function tick(ts) {
            loop = null;
            if (!s.playing) return;
            var t = typeof ts === 'number' ? ts : now();
            var dt = Math.max(0, (t - last) / 1000);
            last = t;
            s.time += dt * s.rate;
            // Le bord se juge dans le SENS de la lecture : le premier battement peut arriver avec un
            // écart nul (l'instant d'une image précède parfois celui du lancement), et une lecture
            // partie de 0 s'arrêtait — tant qu'un média jouait, il le cachait en donnant son temps.
            if (s.rate < 0 && s.time <= 0) { s.time = 0; s.playing = false; }
            else if (s.rate > 0 && s.time >= end()) { s.time = end(); s.playing = false; }
            if (!s.playing && s.shuttling) disengage();      // arrivé au bord : shuttle rendu
            if (s.playing) followAll(t); else settleAll();
            if (!s.playing) {
                notify('state');
                return;
            }
            // Sous charge, les avis s'espacent — le temps, lui, reste juste (`TimerTrip.m:369-376`).
            if (++skipped >= skip) {
                skipped = 0;
                var started = now();
                notify('tick');
                var cost = now() - started;
                if (cost > 0.8 * FRAME_MS && skip < MAX_SKIP) skip++;
                else if (cost < 0.2 * FRAME_MS && skip > 1) skip--;
            }
            loop = frame(tick);
        }
        function run() {
            if (loop) return;
            last = now();
            skipped = 0;
            loop = frame(tick);
        }
        function halt() {
            if (loop) { cancelFrame(loop); loop = null; }
        }
        function applyRate(r) {
            s.rate = r;
            rateToFollowers();
            if (s.playing) { followAll(null); last = now(); run(); }
            notify('rate');
        }
        /** Plusieurs suiveurs jouent ENSEMBLE : la lecture exclusive de la page (`WamaApp`, un
         *  média qui joue coupe les autres) les couperait l'un l'autre, et l'axe prendrait cette
         *  pause pour un geste. Ils portent alors l'échappatoire déclarée de cette exclusivité,
         *  `data-wama-multiplay` — posée par l'axe, retirée par lui seul. Un suiveur SEUL reste
         *  exclusif, comme avant. ⚠ Un lecteur commun (`WamaAudioPlayer`, hors DOM) n'a pas
         *  d'échappatoire : deux suiveurs de ce lecteur sur un même axe se couperaient encore. */
        function markTogether() {
            var together = followers.length > 1;
            followers.forEach(function (f) {
                var el = f.el;
                if (!el.setAttribute) return;
                if (together && !el.hasAttribute('data-wama-multiplay')) el.setAttribute('data-wama-multiplay', 'axis');
                else if (!together && el.getAttribute('data-wama-multiplay') === 'axis') el.removeAttribute('data-wama-multiplay');
            });
        }
        /** La durée de l'axe couvre ce qui s'y pose : un média plus long l'étend. */
        function cover(span) {
            if (isFinite(span) && span > s.duration) axis.setDuration(span);
        }

        var axis = {
            time: function () { return s.time; },
            duration: function () { return s.duration; },
            playing: function () { return s.playing; },
            rate: function () { return s.rate; },
            /** Le premier média suivi (null sans média) ; `medias()` les rend tous. */
            media: function () { return followers.length ? followers[0].el : null; },
            medias: function () { return followers.map(function (f) { return f.el; }); },
            /** Le recalage en vigueur (les seuils de l'axe). */
            sync: function () { return Object.assign({}, sync); },

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
                followAll(null);
                run();
                notify('state');
            },
            pause: function () {
                if (!s.playing) return;
                s.playing = false;
                halt();
                settleAll();
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
                last = now();
                if (s.playing) followers.forEach(function (f) { place(f); follow(f, null); });
                else settleAll();
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

            /** Ce qui se pose sur l'axe DÉCLARE sa cadence (Hz) : le pas est celui de la plus fine.
             *  Rend la fonction qui la retire. */
            cadence: function (hz) {
                hz = Number(hz);
                if (!(hz > 0) || !isFinite(hz)) return function () {};
                var entry = { hz: hz };
                cadences.push(entry);
                return function () { cadences = cadences.filter(function (c) { return c !== entry; }); };
            },
            /** Le pas : une période de la cadence la plus fine déclarée (`DEFAULT_STEP` sinon). */
            stepSize: function () {
                var finest = 0;
                cadences.forEach(function (c) { if (c.hz > finest) finest = c.hz; });
                return finest ? 1 / finest : DEFAULT_STEP;
            },
            /** `n` pas plus loin (arrière si négatif), l'axe arrêté — le STEP de `TimerTrip`. */
            step: function (n) {
                axis.pause();
                axis.seek(s.time + (Number(n) || 1) * axis.stepSize());
            },

            /** Attache un <audio>/<video> comme SUIVEUR de l'axe — autant qu'il en faut. Un geste
             *  sur le média lui-même (son bouton, un clic dans son onde) est suivi par l'axe, comme
             *  une commande. `o.offset` le décale ; `o.play` et `o.seek(t)` le font jouer et le
             *  positionnent à la place de `el.play()` / `el.currentTime` — le lecteur qui le
             *  possède garde ainsi SES règles (lecture exclusive, position reposée quand le fichier
             *  devient positionnable) ; `o.sync` règle SON recalage ; `o.fps` déclare sa cadence.
             *  Rend la fonction qui le détache, lui seul. */
            attach: function (el, o) {
                if (!el) return function () {};
                axis.detach(el);
                o = o || {};
                var f = { el: el, offset: Number(o.offset) || 0,
                          play: typeof o.play === 'function' ? o.play : null,
                          seek: typeof o.seek === 'function' ? o.seek : null,
                          sync: Object.assign({}, sync, o.sync || {}),
                          lastSeek: 0, pausedAt: null, playedAt: null, placedTo: null,
                          drift: null, catching: 0, ownRate: null, sounding: false, here: null };
                var dropCadence = o.fps ? axis.cadence(o.fps) : null;
                /** Le média EST-il censé jouer ? Sinon une pause qui arrive est la nôtre. */
                function expected() { return audible() && covers(f); }
                var handlers = {
                    loadedmetadata: function () {
                        if (isFinite(el.duration) && el.duration > 0) cover(el.duration - f.offset);
                        if (!s.playing) place(f);
                    },
                    play: function () {
                        if (ours(f.playedAt)) { f.playedAt = null; return; }
                        if (s.playing) return;
                        // Le bouton du média : une COMMANDE à l'axe, à une vitesse que le média tient.
                        if (!(s.rate > 0 && s.rate <= MEDIA_MAX_RATE)) disengage();
                        axis.play();
                    },
                    pause: function () {
                        if (ours(f.pausedAt)) { f.pausedAt = null; return; }
                        // La fin du média n'arrête pas l'axe : un autre suiveur, ou une donnée, peut
                        // continuer (la fin de l'axe est la sienne).
                        if (el.ended || !expected()) return;
                        axis.pause();
                    },
                    // Un positionnement fait sur le média PENDANT la lecture (un clic dans l'onde du
                    // lecteur commun) : une commande — sinon l'axe le recalerait là où il était. Les
                    // siens, l'axe les reconnaît à la POSITION qu'il a demandée (`place`), jamais à
                    // leur instant : il en fait un au départ de la lecture, et un clic juste après
                    // passait pour le sien (mesuré au navigateur, partition du composer).
                    seeking: function () {
                        if (!s.playing) return;
                        if (f.placedTo != null && Math.abs(el.currentTime - f.placedTo) < 0.05) return;
                        var t = clamp(el.currentTime - f.offset, 0, end());
                        if (Math.abs(t - s.time) > f.sync.reseek) { f.here = el.currentTime; axis.seek(t); }
                    },
                    seeked: function () {
                        if (s.playing) return;           // pendant la lecture, `seeking` l'a dit
                        var t = clamp(el.currentTime - f.offset, 0, end());
                        if (Math.abs(t - s.time) > 0.01) { f.here = el.currentTime; axis.seek(t); }
                    },
                    // Une vitesse choisie sur le média (le menu d'une vidéo à contrôles natifs) : une
                    // commande — sinon le prochain recalage la défaisait. Les siennes, l'axe les
                    // reconnaît à la VALEUR qu'il a posée (`rateOf`) : l'événement arrive après coup,
                    // et le média porte alors la dernière vitesse demandée.
                    ratechange: function () {
                        var r = el.playbackRate;
                        if (!(r > 0) || f.ownRate == null || Math.abs(r - f.ownRate) < 1e-3) return;
                        axis.setRate(r);
                    },
                };
                Object.keys(handlers).forEach(function (k) { el.addEventListener(k, handlers[k]); });
                f.drop = function () {
                    Object.keys(handlers).forEach(function (k) { el.removeEventListener(k, handlers[k]); });
                    if (dropCadence) dropCadence();
                };
                followers.push(f);
                markTogether();
                if (isFinite(el.duration) && el.duration > 0) cover(el.duration - f.offset);
                if (s.playing) follow(f, null); else place(f);
                rateToFollowers();
                notify('media');
                return function () { axis.detach(el); };
            },
            /** Détache le média `el` — ou TOUS les médias, sans argument. Un média détaché se tait. */
            detach: function (el) {
                var gone = followers.filter(function (f) { return !el || f.el === el; });
                if (!gone.length) return;
                followers = followers.filter(function (f) { return gone.indexOf(f) < 0; });
                gone.forEach(function (f) {
                    f.drop();
                    hush(f);
                    if (f.el.getAttribute && f.el.getAttribute('data-wama-multiplay') === 'axis') {
                        f.el.removeAttribute('data-wama-multiplay');
                    }
                });
                markTogether();
                notify('media');
            },

            /** Le clavier du magnéto (`WAMA_DATA_WORLD §5`) : Espace, ←/→ (±`jump` s), Début/Fin,
             *  et J/K/L si un shuttle est donné (`WamaShuttle.create`). Le transport est une brique
             *  PRIORITAIRE du clavier commun (`wama-keys.js`, qui décide à qui revient une frappe :
             *  jamais pendant une saisie, ni à travers une modale, ni à la place d'un contrôle
             *  atteint au clavier) ; sans Ctrl/Alt/Méta (Ctrl+Z est à l'historique commun), sauf
             *  Ctrl+Espace, lecture/pause MÊME en saisie. Rend la fonction qui délie. */
            bindKeys: function (o) {
                o = o || {};
                var keys = axis.keys(o);
                var off = global.WamaKeys.register({ owner: 'media_transport', scope: 'page',
                                                     typing: ['Ctrl+Space'], handle: keys.handle });
                return function () { off(); keys.release(); };
            },
            /** Les touches du magnéto SANS inscription au clavier commun : `{handle(e) → prise ?,
             *  release()}`. Pour une couche qui garde le clavier (la visionneuse, `scope: 'layer'`)
             *  et lui passe ce qu'elle ne prend pas — le même magnéto que celui d'une surface. */
            keys: function (o) {
                o = o || {};
                var jump = Number(o.jump) || 5;
                var spaceTarget = null;
                /** Un média à CONTRÔLES NATIFS qui a le focus garde Espace : il le traite lui-même,
                 *  et sa lecture est une commande à l'axe. Le prendre aussi le basculait deux fois
                 *  (mesuré au navigateur sur la visionneuse : le lecteur natif l'écoute même quand la
                 *  frappe est prise). */
                function ownSpace(t) {
                    return !!(t && (t.tagName === 'VIDEO' || t.tagName === 'AUDIO') && t.controls);
                }
                function handle(e) {
                    if (o.enabled && !o.enabled()) return false;
                    if (e.code === 'Space' && e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey) {
                        axis.toggle();
                        return true;
                    }
                    if (e.ctrlKey || e.metaKey || e.altKey) return false;
                    switch (e.code) {
                        case 'Space':
                            if (ownSpace(e.target)) return false;
                            axis.toggle(); spaceTarget = e.target; return true;
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
                document.addEventListener('keyup', onKeyUp);
                // Le shuttle RENDU par l'axe (Espace, arrivée au bord, lecture sur le média) : son
                // échelle repart du stop, sinon le prochain L reprendrait au cran d'avant.
                var unsubscribe = o.shuttle && o.shuttle.reset ? axis.subscribe(function (st) {
                    if (!st.shuttling && o.shuttle.speed && o.shuttle.speed() !== 0) o.shuttle.reset();
                }) : null;
                return {
                    handle: handle,
                    release: function () {
                        document.removeEventListener('keyup', onKeyUp);
                        if (unsubscribe) unsubscribe();
                    },
                };
            },
        };
        return axis;
    }

    global.WamaAxis = {
        create: create, formatTime: formatTime, parseTime: parseTime,
        MEDIA_MAX_RATE: MEDIA_MAX_RATE, SYNC: SYNC, DEFAULT_STEP: DEFAULT_STEP,
    };
})(window);
