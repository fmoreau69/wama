/**
 * wama-reverse-audio.js — ENTENDRE un média lu À REBOURS (2026-11-18, décision de Fabien : « Oui
 * je veux entendre le son à l'envers en lecture inversée. C'est un moyen de se repérer dans l'audio
 * de la même façon qu'en avant en plus de voir la forme d'onde. […] Tous les logiciels audiovisuels
 * lisent l'audio à reculon »).
 *
 * Un <audio>/<video> ne joue pas à une vitesse négative. Le son d'un média est donc DÉCODÉ une fois
 * (WebAudio, `decodeAudioData`), RETOURNÉ, et joué par une source tampon à la vitesse du recul :
 * l'instant `t` du média est l'instant `durée − t` du tampon retourné. Mesuré dans Chromium sur un
 * morceau réel de 3:41 (Plus d'eau) : décodage 1,2 s, retournement 13 ms, 78 Mo, départ immédiat —
 * le premier recul attend le décodage (l'axe reste muet comme avant), les suivants partent aussitôt.
 *
 * Le lecteur à rebours est une OPTION d'attache de l'axe (`axis.attach(el, {reverse})`,
 * `wama-axis.js`) : seul un média qui la DÉCLARE se fait entendre en arrière, les autres restent
 * muets. Le volume et le muet sont ceux du média (que l'axe règle). Les tampons sont gardés par
 * adresse, sous une borne de mémoire (`MAX_BYTES`), les plus anciens rendus d'abord.
 *
 *   var rev = WamaReverseAudio.forMedia(el);   // null sans WebAudio
 *   rev.play(t, rate);  rev.time();  rev.stop();  rev.playing();
 *   WamaReverseAudio.memoryBytes();
 */
(function (global) {
    'use strict';

    /** La mémoire que les tampons retournés peuvent tenir ensemble (≈ 7 morceaux de 4 min). */
    var MAX_BYTES = 600 * 1024 * 1024;
    var context = null;
    /** Les tampons retournés, par adresse : `{buffer, bytes, used}` ou la promesse en cours. */
    var buffers = new Map();

    function audioContext() {
        var AC = global.AudioContext || global.webkitAudioContext;
        if (!AC) return null;
        if (!context) context = new AC();
        return context;
    }

    function bytesOf(buffer) { return buffer.length * buffer.numberOfChannels * 4; }

    function memoryBytes() {
        var total = 0;
        buffers.forEach(function (entry) { if (entry.buffer) total += entry.bytes; });
        return total;
    }

    /** Rend la place aux plus anciens jusqu'à tenir sous la borne, celui qu'on garde excepté. */
    function evict(keep) {
        var entries = [];
        buffers.forEach(function (entry, url) { if (entry.buffer && url !== keep) entries.push([url, entry]); });
        entries.sort(function (a, b) { return a[1].used - b[1].used; });
        while (memoryBytes() > MAX_BYTES && entries.length) buffers.delete(entries.shift()[0]);
    }

    /** Le tampon RETOURNÉ du fichier `url` (décodé une fois). */
    function reversed(url) {
        var entry = buffers.get(url);
        if (entry) {
            entry.used = Date.now();
            return entry.buffer ? Promise.resolve(entry.buffer) : entry.pending;
        }
        var ac = audioContext();
        if (!ac) return Promise.reject(new Error('WebAudio absent'));
        entry = { buffer: null, bytes: 0, used: Date.now() };
        entry.pending = fetch(url, { credentials: 'same-origin' })
            .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.arrayBuffer(); })
            .then(function (bytes) { return ac.decodeAudioData(bytes); })
            .then(function (buffer) {
                for (var c = 0; c < buffer.numberOfChannels; c++) buffer.getChannelData(c).reverse();
                entry.buffer = buffer;
                entry.bytes = bytesOf(buffer);
                evict(url);
                return buffer;
            })
            .catch(function (e) { buffers.delete(url); throw e; });
        buffers.set(url, entry);
        return entry.pending;
    }

    /** Le lecteur à rebours d'un média `el` (sa source courante) ; null sans WebAudio. `opts.gain()` :
     *  un niveau de plus que le média porte HORS de son volume (une piste du mixage passe par son
     *  propre nœud de gain, `wama-stem-mix.js`). */
    function forMedia(el, opts) {
        if (!el || !audioContext()) return null;
        opts = opts || {};
        var source = null, gain = null, started = 0, from = 0, rate = 1, wanted = null, decoding = false;

        function url() { return el.currentSrc || el.src || ''; }
        function level() {
            var own = el.muted ? 0 : (isFinite(el.volume) ? el.volume : 1);
            return own * (typeof opts.gain === 'function' ? Number(opts.gain()) || 0 : 1);
        }
        function stop() {
            wanted = null;
            if (!source) return;
            try { source.stop(); } catch (e) { /* déjà arrêtée */ }
            source.disconnect();
            source = null;
        }
        function start(buffer, t, r) {
            var ac = audioContext();
            if (ac.state === 'suspended' && ac.resume) ac.resume();
            if (source) { try { source.stop(); } catch (e) { /* déjà arrêtée */ } source.disconnect(); }
            if (!gain) { gain = ac.createGain(); gain.connect(ac.destination); }
            gain.gain.value = level();
            source = ac.createBufferSource();
            source.buffer = buffer;
            source.playbackRate.value = r;
            source.connect(gain);
            var offset = Math.max(0, Math.min(buffer.duration, buffer.duration - t));
            source.start(0, offset);
            started = ac.currentTime;
            from = t;
            rate = r;
        }
        return {
            /** Joue à rebours depuis l'instant `t` du média, `rate` fois plus vite que le temps réel.
             *  Un premier appel décode le média : le son part quand il est prêt, si on le veut encore. */
            play: function (t, r) {
                var address = url();
                if (!address) return;
                wanted = { t: t, r: r, at: audioContext().currentTime };
                if (decoding) return;                  // le décodage en cours prendra ce souhait
                decoding = true;
                reversed(address).then(function (buffer) {
                    decoding = false;
                    if (!wanted || url() !== address) return;
                    // L'instant a avancé (à rebours) pendant le décodage.
                    var late = audioContext().currentTime - wanted.at;
                    start(buffer, Math.max(0, wanted.t - late * wanted.r), wanted.r);
                }).catch(function () { decoding = false; /* le média reste muet en arrière, comme avant */ });
            },
            stop: stop,
            /** L'instant du média qui sonne, ou null quand rien ne sonne. */
            time: function () {
                if (!source) return null;
                return Math.max(0, from - (audioContext().currentTime - started) * rate);
            },
            playing: function () { return !!source; },
            /** Le volume du média (que l'axe règle) suit, sans redémarrer. */
            level: function () { if (gain) gain.gain.value = level(); },
        };
    }

    global.WamaReverseAudio = { forMedia: forMedia, memoryBytes: memoryBytes, MAX_BYTES: MAX_BYTES };
})(window);
