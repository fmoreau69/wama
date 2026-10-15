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
    };
})(window);
