/**
 * wama-stem-mix.js — le MIXAGE EN TEMPS RÉEL de pistes séparées (2026-11-17, décision de Fabien :
 * « le mixage temps réel va dans la page d'édition, la card porte les process » ; brique
 * `stem_mixer`, `common/surfaces.py`).
 *
 * LA RÈGLE est celle de la refusion (`common/utils/stem_mix.py`) :
 *
 *         mélange = original + Σ (gain − 1) · piste
 *
 * — tout à 1, c'est l'original exact ; une piste à 0 est retranchée. Pour que la soustraction
 * annule vraiment, l'original et les pistes doivent tomber au MÊME échantillon : ils sont décodés
 * en tampons (WebAudio) et partent tous au même instant de l'horloge audio. Mesuré le 2026-11-17
 * sur les trois morceaux séparés de la base (MP3 et WAV, Chromium) : décalage 0 entre l'original
 * décodé par le navigateur et ses pistes, résidu identique à celui du serveur (9 à 11 %). Des
 * <audio> séparés, recalés à 20 ms près, n'annuleraient rien.
 *
 * LA MÉMOIRE : un tampon décodé pèse 8 octets par image stéréo — 85 Mo pour 4 minutes à 48 kHz,
 * 550 à 940 Mo pour un morceau et ses six pistes (mesuré sur la base). D'où le décodage PARESSEUX :
 * l'original au premier besoin, une piste seulement quand son niveau quitte 100 % ; au-delà de
 * `MAX_DECODED_BYTES`, refusé en le disant.
 *
 * L'AXE reste la seule horloge (`wama-axis.js`) : le mixeur est un MÉDIA qu'il suit, de la forme
 * d'un <audio> (`currentTime`, `play`, `pause`, `playbackRate`, `volume`, événements) — il
 * l'attache, le place, le recale. Sa position se lit sur l'horloge audio ; un recalage fin (une
 * vitesse corrigée de quelques millièmes) s'entend à peine sur un tampon, d'où le recalage doux
 * qu'il demande (`SYNC`, que le transport passe à l'axe). ⚠ Une vitesse autre que ×1 change aussi la
 * hauteur du son (un tampon n'a pas l'étirement d'un <audio>).
 *
 *   var mix = WamaStemMix.create({original: url, tracks: [{key, label, url, gain}], status: fn});
 *   axis.attach(mix.media, {sync: WamaStemMix.SYNC});
 *   mix.setGain('drums', 0);          // aussitôt entendu ; décode la piste au besoin
 *   mix.gains();                      // {clé: gain}
 *   mix.release();                    // libère les tampons et le contexte audio
 */
(function (global) {
    'use strict';

    /** Le départ commun est programmé un peu en avant de l'horloge audio : toutes les sources
     *  partent du même échantillon, et la position annoncée tient compte de cette avance. */
    var START_AHEAD = 0.05;
    /** Constante de temps d'un changement de niveau (s) : pas de clic. */
    var RAMP = 0.015;
    /** Au-delà, une piste de plus n'est pas décodée (octets de tampons). */
    var MAX_DECODED_BYTES = 1.5e9;
    /** Le recalage que le mixeur demande à l'axe : une vitesse corrigée de 0,3 % au plus (l'écart
     *  vient de deux horloges, quelques millisecondes par minute), un repositionnement au-delà. */
    var SYNC = { maxNudge: 0.003, tolerance: 0.03 };
    /** `readyState` d'un média : rien / métadonnées / tout. */
    var HAVE_NOTHING = 0, HAVE_METADATA = 1, HAVE_ENOUGH_DATA = 4;

    function create(opts) {
        opts = opts || {};
        var makeContext = opts.audioContext || function () {
            var AC = global.AudioContext || global.webkitAudioContext;
            return new AC();
        };
        var getBytes = opts.fetch || function (url) {
            return global.fetch(url, { credentials: 'same-origin' }).then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.arrayBuffer();
            });
        };
        var tell = opts.status || function () {};
        var lastKind = '';
        /** Dit un état ; « effacer » (`calm`) n'efface qu'un « en cours », jamais une erreur dite. */
        function say(text, kind) { lastKind = kind || ''; tell(text, kind); }
        function calm() { if (lastKind === 'busy') say('', ''); }
        var tracks = (opts.tracks || []).slice();
        var gains = {};
        tracks.forEach(function (t) { gains[t.key] = isFinite(t.gain) ? Number(t.gain) : 1; });

        var ac = null, master = null;
        var buffers = {};          // '' = l'original ; sinon la clé de la piste
        var loading = {};          // clé -> promesse du tampon
        var levels = {};           // clé -> GainNode (gain − 1)
        var running = [];          // sources en cours : {key, node}
        var listeners = {};
        // L'horloge : en lecture, position = `base` + (temps audio − `origin`) × vitesse.
        var playing = false, wanted = false, origin = 0, base = 0, position = 0, rate = 1;
        var volume = 1, muted = false, released = false;

        function emit(name) {
            (listeners[name] || []).slice().forEach(function (fn) {
                try { fn({ type: name, target: media }); } catch (e) { if (global.console) console.error('[stem-mix]', e); }
            });
        }
        function context() {
            if (!ac) {
                ac = makeContext();
                master = ac.createGain();
                master.connect(ac.destination);
                applySound();
            }
            return ac;
        }
        function applySound() {
            if (master) master.gain.value = muted ? 0 : volume;
        }
        function decodedBytes() {
            return Object.keys(buffers).reduce(function (sum, k) {
                var b = buffers[k];
                return sum + b.length * b.numberOfChannels * 4;
            }, 0);
        }
        /** Le tampon de `key` ('' = l'original), décodé une fois. */
        function load(key) {
            if (buffers[key]) return Promise.resolve(buffers[key]);
            if (loading[key]) return loading[key];
            var url = key ? (tracks.filter(function (t) { return t.key === key; })[0] || {}).url : opts.original;
            if (!url) return Promise.reject(new Error('piste inconnue : ' + key));
            var original = buffers[''];
            if (key && original && decodedBytes() + original.length * original.numberOfChannels * 4 > MAX_DECODED_BYTES) {
                return Promise.reject(new Error('mémoire : trop de pistes décodées pour un morceau de cette durée — « Rendre le mixage » le fait sur le serveur'));
            }
            var ctx = context();
            loading[key] = getBytes(url).then(function (bytes) {
                return new Promise(function (resolve, reject) {
                    var p = ctx.decodeAudioData(bytes, resolve, reject);
                    if (p && p.then) p.then(resolve, reject);
                });
            }).then(function (buffer) {
                delete loading[key];
                if (released) throw new Error('mixage libéré');
                buffers[key] = buffer;
                return buffer;
            }, function (error) {
                delete loading[key];
                throw error instanceof Error ? error : new Error('décodage impossible');
            });
            return loading[key];
        }
        function levelNode(key) {
            if (!levels[key]) {
                levels[key] = context().createGain();
                levels[key].gain.value = gains[key] - 1;
                levels[key].connect(master);
            }
            return levels[key];
        }
        /** La position au temps audio `t`. */
        function at(t) { return base + (t - origin) * rate; }
        function duration() { return buffers[''] ? buffers[''].duration : NaN; }

        /** Une source de `key`, partie à l'instant audio `when`, calée sur l'horloge commune. */
        function startSource(key, when) {
            var buffer = buffers[key];
            if (!buffer) return;
            var offset = at(when);
            if (offset >= buffer.duration) return;
            var node = ac.createBufferSource();
            node.buffer = buffer;
            node.playbackRate.value = rate;
            node.connect(key ? levelNode(key) : master);
            node.start(when, Math.max(0, offset));
            var entry = { key: key, node: node };
            if (!key) node.onended = function () { if (running.indexOf(entry) >= 0) ended(); };
            running.push(entry);
        }
        function stopAll() {
            running.forEach(function (s) {
                s.node.onended = null;
                try { s.node.stop(); } catch (e) { /* déjà arrêtée */ }
                try { s.node.disconnect(); } catch (e) { /* rien */ }
            });
            running = [];
        }
        /** Toutes les sources repartent ensemble depuis `from` : l'original, et chaque piste dont le
         *  niveau n'est pas 100 % (elle seule change le mélange). */
        function startAll(from) {
            stopAll();
            var now = ac.currentTime;
            origin = now; base = from;
            var when = now + START_AHEAD;
            startSource('', when);
            tracks.forEach(function (t) { if (gains[t.key] !== 1 && buffers[t.key]) startSource(t.key, when); });
        }
        function ended() {
            position = duration();
            stopAll();
            playing = false; wanted = false;
            emit('pause'); emit('ended');
        }
        function begin() {
            if (!wanted || released || !buffers['']) return;
            var ctx = context();
            var resumed = ctx.state === 'suspended' && ctx.resume ? ctx.resume() : null;
            playing = true;
            startAll(position);
            if (resumed && resumed.catch) resumed.catch(function () { /* lecture refusée */ });
        }
        /** Le tampon d'une piste arrive pendant la lecture : elle rejoint les autres au même échantillon. */
        function join(key) {
            if (!playing || !buffers[key] || running.some(function (s) { return s.key === key; })) return;
            startSource(key, ac.currentTime + START_AHEAD);
        }

        var media = {
            addEventListener: function (name, fn) { (listeners[name] = listeners[name] || []).push(fn); },
            removeEventListener: function (name, fn) {
                listeners[name] = (listeners[name] || []).filter(function (f) { return f !== fn; });
            },
            play: function () {
                if (released) return Promise.reject(new Error('mixage libéré'));
                if (wanted) return Promise.resolve();
                wanted = true;
                if (buffers['']) begin();
                else {
                    say('Décodage du morceau…', 'busy');
                    preload();
                }
                emit('play');
                return Promise.resolve();
            },
            pause: function () {
                if (!wanted) return;
                if (playing) position = Math.min(at(ac.currentTime), duration() || Infinity);
                wanted = false; playing = false;
                stopAll();
                emit('pause');
            },
            seeking: false,
            error: null,
        };
        Object.defineProperties(media, {
            readyState: { get: function () {
                return buffers[''] ? HAVE_ENOUGH_DATA : (loading[''] ? HAVE_METADATA : HAVE_NOTHING);
            } },
            duration: { get: duration },
            paused: { get: function () { return !wanted; } },
            ended: { get: function () { var d = duration(); return !wanted && isFinite(d) && position >= d; } },
            currentTime: {
                get: function () {
                    if (!playing) return position;
                    var t = at(ac.currentTime);
                    var d = duration();
                    return isFinite(d) ? Math.min(Math.max(t, 0), d) : Math.max(t, 0);
                },
                set: function (t) {
                    t = Math.max(0, Number(t) || 0);
                    var d = duration();
                    position = isFinite(d) ? Math.min(t, d) : t;
                    if (playing) startAll(position);
                },
            },
            playbackRate: {
                get: function () { return rate; },
                set: function (r) {
                    r = Number(r);
                    if (!(r > 0) || r === rate) return;
                    if (playing) { base = at(ac.currentTime); origin = ac.currentTime; }
                    rate = r;
                    running.forEach(function (s) { s.node.playbackRate.value = r; });
                },
            },
            volume: {
                get: function () { return volume; },
                set: function (v) { volume = Math.max(0, Math.min(1, Number(v) || 0)); applySound(); },
            },
            muted: {
                get: function () { return muted; },
                set: function (m) { muted = !!m; applySound(); },
            },
        });

        /** Décode l'original (les métadonnées d'un média) et les pistes qui arrivent déjà réglées
         *  ailleurs qu'à 100 % (les niveaux que porte l'élément) ; la lecture demandée part ensuite.
         *  Une piste qui ne se décode pas est dite, le reste joue. */
        function preload() {
            // L'original D'ABORD : sa durée dit ce que pèsera chaque piste (la borne de mémoire).
            return load('').then(function () {
                var moved = tracks.filter(function (t) { return gains[t.key] !== 1; });
                return Promise.all(moved.map(function (t) {
                    return load(t.key).then(function () { join(t.key); }, function (error) {
                        say('Piste non décodée (« ' + t.label + ' ») : ' + error.message, 'error');
                    });
                }));
            }).then(function () {
                emit('loadedmetadata');
                emit('canplay');
                calm();
                begin();
            }, function (error) {
                media.error = error;
                say('Mixage impossible : ' + error.message, 'error');
                emit('error');
            });
        }

        return {
            media: media,
            tracks: function () { return tracks.slice(); },
            gains: function () { return Object.assign({}, gains); },
            /** Le niveau d'une piste (0 = retirée, 1 = telle quelle, jusqu'à 2) — entendu aussitôt ;
             *  la piste est décodée la première fois qu'elle quitte 1. Rend une promesse. */
            setGain: function (key, gain) {
                if (!(key in gains)) return Promise.resolve(false);
                gain = Math.max(0, Number(gain));
                if (!isFinite(gain)) return Promise.resolve(false);
                gains[key] = gain;
                if (levels[key]) levels[key].gain.setTargetAtTime(gain - 1, ac.currentTime, RAMP);
                if (gain === 1 || buffers[key]) { join(key); return Promise.resolve(true); }
                say('Décodage de « ' + ((tracks.filter(function (t) { return t.key === key; })[0] || {}).label || key) + ' »…', 'busy');
                return load(key).then(function () {
                    calm();
                    if (levels[key]) levels[key].gain.value = gains[key] - 1;
                    join(key);
                    return true;
                }, function (error) {
                    say('Piste non décodée : ' + error.message, 'error');
                    return false;
                });
            },
            /** Prépare l'original sans jouer (l'axe le suivra dès qu'il est là). */
            preload: preload,
            /** Les octets de tampons décodés (la mesure de la mémoire). */
            decodedBytes: decodedBytes,
            release: function () {
                released = true;
                stopAll();
                buffers = {};
                if (ac && ac.close) { try { ac.close(); } catch (e) { /* déjà fermé */ } }
                ac = null; master = null; levels = {};
            },
        };
    }

    global.WamaStemMix = { create: create, SYNC: SYNC, MAX_DECODED_BYTES: MAX_DECODED_BYTES };
})(window);
