/**
 * wama-score.js — les règles d'une PARTITION ABC, sans DOM (2026-10-15, page d'édition de la
 * partition du composer ; la gravure est celle d'abcjs, vendorisé).
 *
 * Séparées de la brique (`surfaces/brick-score-view.js`) pour deux raisons : elles se testent
 * sous V8 sans navigateur (`tests_surfaces`), et le rendu d'une face « Partition » de la
 * visionneuse (`ROUTE §F3b`, « rendus par TYPE ») les reprendra telles quelles.
 *
 *   timeline(events, endMs)  les notes de chaque VOIX dans l'ordre du temps ;
 *   playingAt(tl, ms)        ce qui sonne à `ms` : la note en cours de CHAQUE voix (une note
 *                            longue d'une voix reste allumée pendant que l'autre avance) ;
 *   eventTime(timings, at)   l'instant d'une note désignée par sa place dans le texte ;
 *   transposeAt(abc, a, b, step)  la note du texte [a, b) déplacée de `step` degrés VERS LE BAS
 *                            (le signe du glisser d'abcjs : un pas positif = la souris descend).
 *
 * TRANSPOSER retire l'altération écrite de la note : la note déplacée suit l'armure. Un accord
 * `[CEG]` se déplace en bloc ; un symbole d'accord `"Am"`, une décoration `!trill!` ou `+…+` ne
 * bougent pas.
 */
(function (global) {
    'use strict';

    var LETTERS = 'CDEFGAB';
    var PITCH = /([_^=]*)([A-Ga-g])([,']*)/y;
    var QUOTED = { '"': '"', '!': '!', '+': '+' };

    /** Le degré d'une note : 0 = do du milieu (`C`), 7 = `c`, -7 = `C,`. */
    function degree(letter, marks) {
        var octave = letter === letter.toLowerCase() ? 1 : 0;
        for (var i = 0; i < marks.length; i++) octave += marks[i] === "'" ? 1 : -1;
        return LETTERS.indexOf(letter.toUpperCase()) + 7 * octave;
    }

    function pitchText(deg) {
        var octave = Math.floor(deg / 7);
        var letter = LETTERS[deg - 7 * octave];
        if (octave >= 1) return letter.toLowerCase() + new Array(octave).join("'");
        return letter + new Array(1 - octave).join(',');
    }

    /** Les hauteurs d'un morceau de texte ABC déplacées de `step` degrés vers le bas. */
    function transposeToken(token, step) {
        var out = '', i = 0;
        while (i < token.length) {
            var c = token[i];
            if (QUOTED[c]) {
                var j = token.indexOf(QUOTED[c], i + 1);
                if (j < 0) j = token.length - 1;
                out += token.slice(i, j + 1);
                i = j + 1;
                continue;
            }
            PITCH.lastIndex = i;
            var m = PITCH.exec(token);
            if (m) {
                out += pitchText(degree(m[2], m[3]) - step);
                i += m[0].length;
                continue;
            }
            out += c;
            i++;
        }
        return out;
    }

    function transposeAt(abc, start, end, step) {
        step = Math.round(Number(step) || 0);
        if (!step || start == null || end == null || end <= start) return abc;
        return abc.slice(0, start) + transposeToken(abc.slice(start, end), step) + abc.slice(end);
    }

    /** La voix d'un élément gravé, lue de ses classes (`abcjs-v1`) ; 0 sans classe. */
    function voiceOf(classes) {
        var m = /(?:^|\s)abcjs-v(\d+)(?:\s|$)/.exec(classes || '');
        return m ? Number(m[1]) : 0;
    }

    /** `events` : `[{ms, sets: [{voice, ref}]}]` dans l'ordre du temps ; `endMs` : la fin. */
    function timeline(events, endMs) {
        var voices = {};
        var last = 0;
        (events || []).forEach(function (ev) {
            (ev.sets || []).forEach(function (set) {
                (voices[set.voice] = voices[set.voice] || []).push({ ms: ev.ms, ref: set.ref });
            });
            last = Math.max(last, ev.ms);
        });
        Object.keys(voices).forEach(function (v) {
            voices[v].sort(function (a, b) { return a.ms - b.ms; });
        });
        return { voices: voices, end: endMs > last ? endMs : last };
    }

    /** Les `ref` qui sonnent à `ms` : la dernière note commencée de chaque voix ; rien avant la
     *  première ni après la fin. */
    function playingAt(tl, ms) {
        var out = [];
        if (!tl || ms < 0 || ms >= tl.end) return out;
        Object.keys(tl.voices).forEach(function (v) {
            var notes = tl.voices[v];
            var lo = 0, hi = notes.length - 1, found = -1;
            while (lo <= hi) {
                var mid = (lo + hi) >> 1;
                if (notes[mid].ms <= ms) { found = mid; lo = mid + 1; } else hi = mid - 1;
            }
            if (found >= 0) out.push(notes[found].ref);
        });
        return out;
    }

    // ── Caler la partition sur l'audio : LE TEMPS DE LA PARTITION GUIDE (2026-10-16) ──────────
    // Le tempo écrit est arrondi (#754 : `Q:1/4=88`, joué à 89,1) et l'audio ne commence pas à 0 :
    // caler par le tempo fait dériver tout le morceau et rate l'anacrouse. On cale donc le temps
    // ÉCRIT n sur le temps JOUÉ n + k (grille de l'audio, `common/utils/audio_rhythm.py`) — entre
    // deux temps, au prorata. Le décalage k est celui où les hauteurs écrites sonnent le mieux.

    /** Les notes d'une partition gravée, en TEMPS écrits : `[{beat, pcs}]` (classes de hauteur). */
    function notesFromTimings(timings, msPerBeat) {
        var out = [];
        (timings || []).forEach(function (ev) {
            if (ev.type !== 'event' || !(ev.midiPitches || []).length) return;
            out.push({ beat: ev.milliseconds / msPerBeat,
                       pcs: ev.midiPitches.map(function (p) { return ((p.pitch % 12) + 12) % 12; }) });
        });
        return out;
    }

    function median(values) {
        var s = values.slice().sort(function (a, b) { return a - b; });
        return s.length ? s[s.length >> 1] : 0;
    }

    /** Ramène une grille détectée au double ou à la moitié du tempo écrit au tempo écrit. */
    function normalizeGrid(beats, chroma, writtenSeconds) {
        var ibi = median(beats.slice(1).map(function (t, i) { return t - beats[i]; }));
        var ratio = ibi / writtenSeconds;
        if (ratio > 0 && ratio < 0.7) {                      // deux temps joués par temps écrit
            return [0, 1].map(function (phase) {
                return { beats: beats.filter(function (_, i) { return i % 2 === phase; }),
                         chroma: chroma.filter(function (_, i) { return i % 2 === phase; }) };
            });
        }
        if (ratio > 1.4) {                                   // un temps joué pour deux écrits
            var b = [], c = [];
            beats.forEach(function (t, i) {
                b.push(t); c.push(chroma[i]);
                if (i + 1 < beats.length) { b.push((t + beats[i + 1]) / 2); c.push(chroma[i]); }
            });
            return [{ beats: b, chroma: c }];
        }
        return [{ beats: beats, chroma: chroma }];
    }

    function cosine(a, b) {
        var ab = 0, aa = 0, bb = 0;
        for (var i = 0; i < 12; i++) { ab += a[i] * b[i]; aa += a[i] * a[i]; bb += b[i] * b[i]; }
        return aa && bb ? ab / Math.sqrt(aa * bb) : 0;
    }

    /** Le calage d'une partition (`notes`, temps écrits de `writtenSeconds`) sur une grille
     *  (`{beats, chroma}`). Rend `{shift, score, toAudio(temps écrit) → s, toScore(s) → temps
     *  écrit}`, ou null sans grille. `maxShift` : les décalages essayés, en temps (défaut 16). */
    function align(notes, writtenSeconds, grid, maxShift) {
        if (!grid || !(grid.beats || []).length || !(notes || []).length || !(writtenSeconds > 0)) return null;
        maxShift = maxShift == null ? 16 : maxShift;
        var written = {};
        notes.forEach(function (n) {
            var b = Math.floor(n.beat + 1e-6);
            var v = written[b] = written[b] || [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0];
            n.pcs.forEach(function (pc) { v[pc] += 1; });
        });
        var keys = Object.keys(written).map(Number);
        // Décalages du plus petit au plus grand : à égalité, le plus proche gagne — une chanson se
        // RÉPÈTE (un refrain plus loin sonne pareil), le décalage d'une section n'est pas le bon.
        var shifts = [0];
        for (var s = 1; s <= maxShift; s++) shifts.push(-s, s);
        var best = null;
        normalizeGrid(grid.beats, grid.chroma || [], writtenSeconds).forEach(function (g) {
            shifts.forEach(function (k) {
                var sum = 0, count = 0;
                keys.forEach(function (b) {
                    var c = g.chroma[b + k];
                    if (c) { sum += cosine(written[b], c); count += 1; }
                });
                // Une correspondance sur peu de temps ne prouve rien : au moins la moitié des notes,
                // et la moyenne se prend sur TOUTES — une note laissée hors de l'audio compte zéro.
                if (count < keys.length / 2) return;
                var score = sum / keys.length;
                if (!best || score > best.score + 1e-9) best = { shift: k, score: score, grid: g };
            });
        });
        if (!best) return null;
        var beats = best.grid.beats, k = best.shift, n = beats.length;
        var ibi = n > 1 ? (beats[n - 1] - beats[0]) / (n - 1) : writtenSeconds;
        function audioAt(i) {                                // l'instant du temps joué i (réel)
            if (i <= 0) return beats[0] + i * ibi;
            if (i >= n - 1) return beats[n - 1] + (i - (n - 1)) * ibi;
            var lo = Math.floor(i);
            return beats[lo] + (i - lo) * (beats[lo + 1] - beats[lo]);
        }
        function playedIndex(t) {                            // le temps joué (réel) à l'instant t
            if (t <= beats[0]) return (t - beats[0]) / ibi;
            if (t >= beats[n - 1]) return n - 1 + (t - beats[n - 1]) / ibi;
            var lo = 0, hi = n - 1;
            while (hi - lo > 1) { var mid = (lo + hi) >> 1; if (beats[mid] <= t) lo = mid; else hi = mid; }
            return lo + (t - beats[lo]) / (beats[lo + 1] - beats[lo]);
        }
        return {
            shift: k, score: best.score,
            toAudio: function (beat) { return audioAt(beat + k); },
            toScore: function (t) { return playedIndex(t) - k; },
        };
    }

    /** L'instant (ms) de la note qui commence au caractère `at` — `noteTimings` d'abcjs. */
    function eventTime(timings, at) {
        for (var i = 0; i < (timings || []).length; i++) {
            var ev = timings[i];
            if (ev.type === 'event' && (ev.startCharArray || []).indexOf(at) >= 0) return ev.milliseconds;
        }
        return null;
    }

    global.WamaScore = {
        degree: degree, pitchText: pitchText, transposeToken: transposeToken,
        transposeAt: transposeAt, voiceOf: voiceOf, timeline: timeline,
        playingAt: playingAt, eventTime: eventTime,
        notesFromTimings: notesFromTimings, align: align,
    };
})(window);
