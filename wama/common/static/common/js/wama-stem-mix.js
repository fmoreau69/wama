/**
 * wama-stem-mix.js — le MIXAGE EN TEMPS RÉEL de pistes séparées (2026-11-17, décision de Fabien :
 * « le mixage temps réel va dans la page d'édition, la card porte les process » ; brique
 * `stem_mixer`, `common/surfaces.py`).
 *
 * TROIS MODES (décision de Fabien, 2026-11-17 au soir — `modeFor`, choisis par les niveaux et la
 * vitesse de l'axe) :
 *   • `original` — aucune piste touchée : l'audio ORIGINAL, joué par un <audio> à toute vitesse
 *     (il garde la hauteur). Qualité d'origine, aucun mixage.
 *   • `exact` — des pistes touchées, à ×1 : LA RÈGLE de la refusion (`common/utils/stem_mix.py`),
 *
 *         mélange = original + Σ (gain − 1) · piste
 *
 *     — tout à 1, c'est l'original exact ; une piste à 0 est retranchée. Pour que la soustraction
 *     annule vraiment, l'original et les pistes doivent tomber au MÊME échantillon : ils sont
 *     décodés en tampons (WebAudio) et partent tous au même instant de l'horloge audio. Mesuré le
 *     2026-11-17 sur les trois morceaux séparés de la base (MP3 et WAV, Chromium) : décalage 0
 *     entre l'original décodé par le navigateur et ses pistes, résidu identique à celui du serveur
 *     (9 à 11 %). Un tampon n'a pas l'étirement d'un <audio> : à une autre vitesse, il changerait
 *     la hauteur du son — d'où le troisième mode.
 *   • `sum` — des pistes touchées, à une autre vitesse : l'ADDITION Σ gain · piste, une piste par
 *     <audio> (l'étirement natif garde la hauteur), chacun attaché à l'axe par l'`attach`
 *     ordinaire, comme plusieurs vidéos. Un gain au-delà de 1 passe par un GainNode. Mesuré le
 *     2026-11-17 (6 pistes Demucs, Chromium) : les lecteurs restent à 10 ms l'un de l'autre en
 *     médiane, jusqu'à 20 ms (la tolérance de l'axe) ; qualité un peu moindre ACCEPTÉE par
 *     Fabien, en édition seulement — la refusion de la card reste par retrait.
 *
 * LE RÉSEAU : six <audio> en lecture tiendraient les six connexions HTTP/1.1 que le navigateur
 * ouvre vers un hôte (mesuré : l'appel suivant de la page attendait sans fin). Chaque fichier est
 * donc téléchargé UNE fois, gardé en Blob, et joué ou décodé depuis lui (`blob:`) — un lecteur ne
 * garde aucune connexion, et les octets d'un mode servent à l'autre.
 *
 * LA MÉMOIRE : un tampon décodé pèse 8 octets par image stéréo — 85 Mo pour 4 minutes à 48 kHz ;
 * un fichier gardé pèse ce qu'il pèse (un WAV de 4 minutes : 42 Mo). D'où le chargement
 * PARESSEUX : ce que le mode en cours demande, rien d'autre ; au-delà de `MAX_DECODED_BYTES`
 * (fichiers et tampons comptés ensemble, `memoryBytes`), refusé en le disant.
 *
 * L'AXE reste la seule horloge (`wama-axis.js`) : le mixeur est un MÉDIA qu'il suit, de la forme
 * d'un <audio> (`currentTime`, `play`, `pause`, `playbackRate`, `volume`, événements) — c'est lui
 * que le lecteur commun pose sur l'axe (`WamaAudioPlayer.followLive` : la lecture exclusive) et
 * qui reçoit l'axe et son décalage (`joinAxis`) pour y attacher ses propres lecteurs dans les deux
 * autres modes ; il y suit alors le temps de l'axe. En mode exact, sa position se lit sur l'horloge
 * audio ; un recalage fin (une vitesse corrigée de quelques millièmes) s'entend à peine sur un
 * tampon, d'où le recalage doux qu'il demande (`SYNC`, que le transport passe à l'axe).
 *
 *   var mix = WamaStemMix.create({original: url, playback: copie, tracks: [{key, label, url, gain}], status: fn});
 *   WamaAudioPlayer.followLive(id, mix.media, axis, 0, WamaStemMix.SYNC);
 *   mix.setGain('drums', 0);          // aussitôt entendu ; charge la piste au besoin
 *   mix.gains();                      // {clé: gain}
 *   mix.mode();                       // 'original' | 'exact' | 'sum'
 *   mix.release();                    // libère lecteurs, fichiers, tampons et contexte audio
 */
(function (global) {
    'use strict';

    /** Le départ commun est programmé un peu en avant de l'horloge audio : toutes les sources
     *  partent du même échantillon, et la position annoncée tient compte de cette avance. */
    var START_AHEAD = 0.05;
    /** Constante de temps d'un changement de niveau (s) : pas de clic. */
    var RAMP = 0.015;
    /** Au-delà, une piste de plus n'est pas chargée (octets de fichiers et de tampons). */
    var MAX_DECODED_BYTES = 1.5e9;
    /** Le recalage que le mixeur demande à l'axe : une vitesse corrigée de 0,3 % au plus (l'écart
     *  vient de deux horloges, quelques millisecondes par minute), un repositionnement au-delà. */
    var SYNC = { maxNudge: 0.003, tolerance: 0.03 };
    /** Une vitesse de l'axe à moins de ce pas de 1 est ×1 (le mode exact). */
    var UNIT_RATE = 1e-3;
    /** `readyState` d'un média : rien / métadonnées / tout. */
    var HAVE_NOTHING = 0, HAVE_METADATA = 1, HAVE_ENOUGH_DATA = 4;

    /** LE MODE, des niveaux et de la vitesse de l'axe : aucune piste touchée → l'original ; sinon
     *  le mélange exact à ×1, l'addition à une autre vitesse. */
    function modeFor(gains, rate) {
        var moved = Object.keys(gains || {}).some(function (k) { return gains[k] !== 1; });
        if (!moved) return 'original';
        return Math.abs(Number(rate) - 1) < UNIT_RATE ? 'exact' : 'sum';
    }

    function create(opts) {
        opts = opts || {};
        var makeContext = opts.audioContext || function () {
            var AC = global.AudioContext || global.webkitAudioContext;
            return new AC();
        };
        /** Un fichier, téléchargé une fois : un Blob (sa taille, `arrayBuffer()`). */
        var getFile = opts.fetch || function (url) {
            return global.fetch(url, { credentials: 'same-origin' }).then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.blob();
            });
        };
        var objectUrl = opts.objectUrl || function (blob) { return global.URL.createObjectURL(blob); };
        var revokeUrl = opts.revokeUrl || function (url) { try { global.URL.revokeObjectURL(url); } catch (e) { /* rien */ } };
        var makeAudio = opts.audio || function () { return new global.Audio(); };
        var tell = opts.status || function () {};
        var lastKind = '';
        /** Dit un état ; « effacer » (`calm`) n'efface qu'un « en cours », jamais une erreur dite. */
        function say(text, kind) { lastKind = kind || ''; tell(text, kind); }
        function calm() { if (lastKind === 'busy') say('', ''); }
        var tracks = (opts.tracks || []).slice();
        // Le fichier que JOUE le lecteur de l'original : sa copie de lecture quand le serveur en sert
        // une (`playback` — un MP3 se positionne faux, sa copie M4A juste, 2026-11-18) ; le mode
        // exact, lui, DÉCODE l'original, que ses pistes soustraient à l'échantillon près.
        var PLAYBACK = opts.playback && opts.playback !== opts.original ? '~playback' : '';
        var gains = {};
        tracks.forEach(function (t) { gains[t.key] = isFinite(t.gain) ? Number(t.gain) : 1; });

        var ac = null, master = null;
        var files = {};            // '' = l'original ; sinon la clé de la piste → Blob
        var fetching = {};         // clé -> promesse du fichier
        var buffers = {};          // clé -> tampon décodé
        var loading = {};          // clé -> promesse du tampon
        var levels = {};           // clé -> GainNode (gain − 1), mode exact
        var running = [];          // sources en cours : {key, node}, mode exact
        var players = {};          // clé -> {el, url, level, drop}, modes original et addition
        var listeners = {};
        // L'horloge du mode exact : en lecture, position = `base` + (temps audio − `origin`) × vitesse.
        var playing = false, wanted = false, origin = 0, base = 0, position = 0, rate = 1;
        var volume = 1, muted = false, released = false;
        // L'axe que le lecteur commun lui donne (`joinAxis`) — sans lui, le mode exact seul.
        var axis = null, axisOffset = 0, unsubscribe = null, mode = 'exact', knownDuration = NaN;

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
        function resume() {
            var r = ac && ac.state === 'suspended' && ac.resume ? ac.resume() : null;
            if (r && r.catch) r.catch(function () { /* lecture refusée */ });
        }
        function applySound() {
            if (master) master.gain.value = muted ? 0 : volume;
        }
        function labelOf(key) {
            return key ? ((tracks.filter(function (t) { return t.key === key; })[0] || {}).label || key) : 'morceau';
        }
        function decodedBytes() {
            return Object.keys(buffers).reduce(function (sum, k) {
                var b = buffers[k];
                return sum + b.length * b.numberOfChannels * 4;
            }, 0);
        }
        /** Ce que le mixage tient en mémoire : les fichiers gardés ET les tampons décodés. */
        function memoryBytes() {
            return decodedBytes() + Object.keys(files).reduce(function (sum, k) { return sum + (files[k].size || 0); }, 0);
        }
        function tooMuch() {
            return new Error('mémoire : trop de pistes pour un morceau de cette durée — « Rendre le mixage » le fait sur le serveur');
        }
        /** Le fichier de `key` ('' = l'original), téléchargé une fois. */
        function file(key) {
            if (files[key]) return Promise.resolve(files[key]);
            if (fetching[key]) return fetching[key];
            var url = key === PLAYBACK && key ? opts.playback
                : key ? (tracks.filter(function (t) { return t.key === key; })[0] || {}).url : opts.original;
            if (!url) return Promise.reject(new Error('piste inconnue : ' + key));
            fetching[key] = getFile(url).then(function (blob) {
                delete fetching[key];
                if (released) throw new Error('mixage libéré');
                if (memoryBytes() + (blob.size || 0) > MAX_DECODED_BYTES) throw tooMuch();
                files[key] = blob;
                emit('progress');                   // des données arrivent : l'axe attend encore
                return blob;
            }, function (error) {
                delete fetching[key];
                throw error instanceof Error ? error : new Error('téléchargement impossible');
            });
            return fetching[key];
        }
        /** Le tampon de `key` ('' = l'original), décodé une fois — depuis le fichier gardé. */
        function load(key) {
            if (buffers[key]) return Promise.resolve(buffers[key]);
            if (loading[key]) return loading[key];
            var original = buffers[''];
            if (key && original && decodedBytes() + original.length * original.numberOfChannels * 4 > MAX_DECODED_BYTES) {
                return Promise.reject(tooMuch());
            }
            var ctx = context();
            loading[key] = file(key).then(function (blob) {
                return blob.arrayBuffer();
            }).then(function (bytes) {
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
        /** La position au temps audio `t` (mode exact). */
        function at(t) { return base + (t - origin) * rate; }
        function duration() {
            if (buffers['']) return buffers[''].duration;
            if (isFinite(knownDuration)) return knownDuration;
            for (var k in players) {
                var d = players[k].el.duration;
                if (isFinite(d) && d > 0) return d;
            }
            return NaN;
        }

        // ── Le mode exact : des tampons sur l'horloge audio ─────────────────────────────────
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
            if (!wanted || released || mode !== 'exact' || !buffers['']) return;
            context();
            resume();
            // Sur un axe, au temps de l'axe : il a pu avancer pendant le décodage d'un changement de
            // mode (mesuré : 56 ms de retard tenus ensuite par un recalage de 0,3 %).
            if (axis) position = Math.min(Math.max(axis.time() + axisOffset, 0), buffers[''].duration);
            playing = true;
            startAll(position);
        }
        /** Le tampon d'une piste arrive pendant la lecture : elle rejoint les autres au même échantillon. */
        function join(key) {
            if (!playing || !buffers[key] || running.some(function (s) { return s.key === key; })) return;
            startSource(key, ac.currentTime + START_AHEAD);
        }
        /** Le mode exact : l'original décodé, et les pistes qui bougent ; la lecture demandée part ensuite. */
        function prepareExact() {
            return load('').then(function () {
                if (mode !== 'exact') return;
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
            });
        }

        // ── Les modes original et addition : des <audio> attachés à l'axe ──────────────────
        /** Le lecteur de `key`, sur son fichier gardé ; une piste passe par son niveau (GainNode,
         *  un gain au-delà de 1 compris). */
        function player(key) {
            if (players[key]) return players[key].ready;
            return file(key || PLAYBACK).then(function (blob) {
                if (players[key]) return players[key].ready;
                var el = makeAudio();
                el.preload = 'auto';
                var p = { el: el, url: objectUrl(blob), level: null, drop: null };
                el.src = p.url;
                if (key) {
                    var ctx = context();
                    p.level = ctx.createGain();
                    p.level.gain.value = gains[key];
                    ctx.createMediaElementSource(el).connect(p.level);
                    // Pas par `master` : le son de l'axe arrive à chaque lecteur qu'il suit (`volume`).
                    p.level.connect(ctx.destination);
                }
                players[key] = p;
                // Rendu quand il connaît sa durée : attaché avant, l'axe le ferait partir du début
                // du fichier, le temps qu'il soit positionnable.
                p.ready = new Promise(function (resolve, reject) {
                    function known() {
                        if (!isFinite(knownDuration) && isFinite(el.duration)) { knownDuration = el.duration; emit('loadedmetadata'); }
                        resolve(p);
                    }
                    if (el.readyState >= HAVE_METADATA) { known(); return; }
                    el.addEventListener('loadedmetadata', known);
                    el.addEventListener('error', function () {
                        delete players[key];
                        revokeUrl(p.url);
                        reject(new Error('lecture impossible'));
                    });
                });
                return p.ready;
            });
        }
        function onAxis(key) {
            var p = players[key];
            if (!p || p.drop || !axis) return;
            // À rebours, chaque lecteur se fait entendre à son niveau (2026-11-18, décision de
            // Fabien : la lecture inversée s'entend) — le gain d'une piste, hors du volume du média.
            var Rev = global.WamaReverseAudio;
            p.drop = axis.attach(p.el, { offset: axisOffset, reverse: Rev ? Rev.forMedia(p.el, {
                gain: function () { return p.level ? p.level.gain.value : 1; } }) : null });
        }
        function offAxis(key) {
            var p = players[key];
            if (!p || !p.drop) return;
            p.drop();
            p.drop = null;
        }
        /** Ce que le mode demande : ses lecteurs sur l'axe, les autres détachés. */
        function wantedPlayers() {
            if (mode === 'original') return [''];
            if (mode === 'sum') return tracks.filter(function (t) { return gains[t.key] > 0; }).map(function (t) { return t.key; });
            return [];
        }
        var settling = null;
        function settlePlayers() {
            var want = wantedPlayers();
            Object.keys(players).forEach(function (k) { if (want.indexOf(k) < 0) offAxis(k); });
            if (!want.length) return Promise.resolve();
            if (mode === 'sum') { context(); resume(); }
            var missing = want.filter(function (k) { return !players[k]; });
            if (missing.length) say(mode === 'sum' ? 'Chargement des pistes…' : 'Chargement du morceau…', 'busy');
            var current = settling = Promise.all(want.map(function (k) {
                return player(k).then(function () {
                    if (wantedPlayers().indexOf(k) >= 0) onAxis(k);
                }, function (error) {
                    say((k ? 'Piste non chargée (« ' + labelOf(k) + ' ») : ' : 'Morceau non chargé : ') + error.message, 'error');
                });
            })).then(function () {
                if (settling === current) settling = null;
                calm();
                emit('canplay');
            });
            return current;
        }

        /** Le mode suit les niveaux et la vitesse de l'axe ; changer de mode en lecture garde la
         *  position. */
        function apply() {
            if (released) return Promise.resolve();
            var next = axis ? modeFor(gains, axis.rate()) : 'exact';
            if (next !== mode) {
                var t = media.currentTime;
                if (mode === 'exact') { stopAll(); playing = false; }
                mode = next;
                position = t;
            }
            Object.keys(players).forEach(function (k) {
                var p = players[k];
                if (p.level) p.level.gain.setTargetAtTime(gains[k], ac.currentTime, RAMP);
            });
            if (mode === 'exact') {
                Object.keys(players).forEach(offAxis);
                if (buffers[''] && wanted && !playing) begin();
                return buffers[''] ? Promise.resolve() : prepareExact();
            }
            return settlePlayers();
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
                if (ac) resume();
                if (mode === 'exact') {
                    if (buffers['']) begin();
                    else {
                        say('Décodage du morceau…', 'busy');
                        preload();
                    }
                }
                // Les autres modes : l'axe fait jouer les lecteurs qu'il suit.
                emit('play');
                return Promise.resolve();
            },
            pause: function () {
                if (!wanted) return;
                position = media.currentTime;
                wanted = false; playing = false;
                stopAll();
                emit('pause');
            },
            seeking: false,
            error: null,
        };
        Object.defineProperties(media, {
            readyState: { get: function () {
                if (mode === 'exact') return buffers[''] ? HAVE_ENOUGH_DATA : (loading[''] ? HAVE_METADATA : HAVE_NOTHING);
                // Ses lecteurs chargent : il RETIENT l'axe (il joue et attend ses données).
                return settling ? HAVE_METADATA : HAVE_ENOUGH_DATA;
            } },
            duration: { get: duration },
            paused: { get: function () { return !wanted; } },
            ended: { get: function () { var d = duration(); return !wanted && isFinite(d) && position >= d; } },
            currentTime: {
                get: function () {
                    var d = duration(), t;
                    if (mode !== 'exact' && axis) t = axis.time() + axisOffset;       // il suit l'axe
                    else if (!playing) return position;
                    else t = at(ac.currentTime);
                    return isFinite(d) ? Math.min(Math.max(t, 0), d) : Math.max(t, 0);
                },
                set: function (t) {
                    t = Math.max(0, Number(t) || 0);
                    var d = duration();
                    position = isFinite(d) ? Math.min(t, d) : t;
                    if (playing && mode === 'exact') startAll(position);
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
        /** L'axe sur lequel le lecteur commun l'a posé, et son décalage (`followLive`) : ses
         *  lecteurs s'y attachent dans les modes original et addition ; `null` les en retire. */
        media.joinAxis = function (a, offset) {
            if (unsubscribe) { unsubscribe(); unsubscribe = null; }
            Object.keys(players).forEach(offAxis);
            if (!a) {
                if (mode !== 'exact') { position = media.currentTime; mode = 'exact'; }
                axis = null;
                return;
            }
            axis = a;
            axisOffset = Number(offset) || 0;
            // Une vitesse changée change de mode (×1 ↔ autre) : l'axe le dit à ses abonnés.
            unsubscribe = axis.subscribe(function (s) { if (s.reason === 'rate') apply(); });
            apply();
        };

        /** Prépare ce que le mode demande sans jouer (l'axe le suivra dès que c'est là) — avant
         *  l'axe, d'après les niveaux seuls : l'original s'il n'y a rien à mixer, sinon le mélange
         *  exact (×1). Une piste qui ne se charge pas est dite, le reste joue. */
        function preload() {
            if (!axis && modeFor(gains, 1) === 'original') {
                return file(PLAYBACK).then(function () { emit('canplay'); }, function (error) {
                    media.error = error;
                    say('Mixage impossible : ' + error.message, 'error');
                    emit('error');
                });
            }
            return (axis ? apply() : prepareExact()).then(null, function (error) {
                media.error = error;
                say('Mixage impossible : ' + error.message, 'error');
                emit('error');
            });
        }

        return {
            media: media,
            tracks: function () { return tracks.slice(); },
            gains: function () { return Object.assign({}, gains); },
            mode: function () { return mode; },
            /** Le niveau d'une piste (0 = retirée, 1 = telle quelle, jusqu'à la borne) — entendu
             *  aussitôt ; ce que le mode demande est chargé la première fois. Rend une promesse. */
            setGain: function (key, gain) {
                if (!(key in gains)) return Promise.resolve(false);
                gain = Math.max(0, Number(gain));
                if (!isFinite(gain)) return Promise.resolve(false);
                gains[key] = gain;
                if (levels[key]) levels[key].gain.setTargetAtTime(gain - 1, ac.currentTime, RAMP);
                var before = mode;
                var done = apply();
                if (mode !== 'exact' || before !== 'exact') return done.then(function () { return true; });
                if (gain === 1 || buffers[key]) { join(key); return Promise.resolve(true); }
                say('Décodage de « ' + labelOf(key) + ' »…', 'busy');
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
            /** Prépare le mode en cours sans jouer (l'axe le suivra dès qu'il est là). */
            preload: preload,
            /** Les octets de tampons décodés ; et toute la mémoire tenue (fichiers compris). */
            decodedBytes: decodedBytes,
            memoryBytes: memoryBytes,
            release: function () {
                released = true;
                stopAll();
                media.joinAxis(null);
                Object.keys(players).forEach(function (k) {
                    var p = players[k];
                    try { p.el.pause(); p.el.removeAttribute('src'); p.el.load(); } catch (e) { /* rien */ }
                    revokeUrl(p.url);
                });
                players = {}; files = {}; buffers = {};
                if (ac && ac.close) { try { ac.close(); } catch (e) { /* déjà fermé */ } }
                ac = null; master = null; levels = {};
            },
        };
    }

    global.WamaStemMix = { create: create, modeFor: modeFor, SYNC: SYNC, MAX_DECODED_BYTES: MAX_DECODED_BYTES };
})(window);
