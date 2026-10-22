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
 *
 *   retime(abc, at, op)      LE RYTHME (2026-10-22, demande de Fabien) : la note (ou l'accord) qui
 *                            couvre le caractère `at`, décalée d'un pas (`right`/`left`) ou
 *                            allongée/raccourcie d'un pas (`longer`/`shorter`), DANS sa mesure —
 *                            la durée de la mesure ne change jamais. Rend `{abc, start, end}` (la
 *                            place de la note dans le nouveau texte) ou `{error}`.
 *
 * Le PAS est la plus petite durée écrite dans la mesure (l'unité `L:`, ou sa fraction si la
 * mesure en écrit une). Ce qui ajuste la mesure :
 *   • une note qui empiète sur sa VOISINE la raccourcit — un silence peut disparaître, une note
 *     jamais (le geste est refusé) ;
 *   • le vide laissé est comblé par la note PRÉCÉDENTE quand la note part vers la droite (elle se
 *     prolonge jusqu'à elle), par un SILENCE sinon (fondu dans un silence voisin s'il y en a un) ;
 *   • une liaison (`-`) vers un silence est retirée ; un symbole d'accord suit sa place dans le
 *     temps, pas la note.
 * Une mesure qui écrit un triolet, un rythme pointé `>`/`<`, des notes d'agrément ou un silence
 * de plusieurs mesures n'est pas retouchée : la source ABC reste le recours.
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

    // ── Éditer le RYTHME d'une note dans sa mesure (2026-10-22) ──────────────────────────────

    /** La mesure qui contient le caractère `at` : `[start, end)`, bornée par `|` ou une fin de ligne. */
    function barAt(abc, at) {
        var start = at, end = at;
        while (start > 0 && abc[start - 1] !== '|' && abc[start - 1] !== '\n') start--;
        while (end < abc.length && abc[end] !== '|' && abc[end] !== '\n') end++;
        return { start: start, end: end };
    }

    function gcd(a, b) { while (b) { var t = a % b; a = b; b = t; } return a; }

    /** Une durée ABC lue à `i` : `{num, den, next}` (`A2`, `A/`, `A//`, `A3/2`, rien = 1). */
    function readLength(text, i) {
        var start = i, num = '', den = '', slashes = 0;
        while (i < text.length && /\d/.test(text[i])) num += text[i++];
        while (text[i] === '/') { slashes++; i++; }
        while (slashes && i < text.length && /\d/.test(text[i])) den += text[i++];
        var d = den ? Number(den) : Math.pow(2, slashes);
        return { num: num ? Number(num) : 1, den: d, next: i, raw: text.slice(start, i) };
    }

    /** Les éléments rythmiques d'une mesure — `{items, tail}`, ou null si la mesure écrit ce que
     *  ce geste ne sait pas retoucher. Un élément : `{pre, body, num, den, tie, rest, raw}` — `pre`
     *  le texte qui le précède (espaces, symbole d'accord, décoration, champ en ligne). */
    function parseBar(text) {
        var items = [], pre = '', i = 0;
        while (i < text.length) {
            var c = text[i];
            if (c === '(' && /\d/.test(text[i + 1] || '')) return null;       // triolet `(3`
            if (c === ' ' || c === '\t' || c === '(' || c === ')' || c === '.') { pre += c; i++; continue; }
            if (c === '"' || c === '!' || c === '+') {
                var close = text.indexOf(c, i + 1);
                if (close < 0) return null;
                pre += text.slice(i, close + 1);
                i = close + 1;
                continue;
            }
            if (c === '>' || c === '<' || c === '{' || c === 'Z') return null;
            var body = null, bodyEnd = i, rest = false;
            if (c === '[') {
                var shut = text.indexOf(']', i + 1);
                if (shut < 0) return null;
                if (/^\[[A-Za-z]:/.test(text.slice(i, i + 3))) {      // champ en ligne `[K:Am]`
                    pre += text.slice(i, shut + 1);
                    i = shut + 1;
                    continue;
                }
                body = text.slice(i, shut + 1);
                bodyEnd = shut + 1;
            } else if (c === 'z' || c === 'x') {
                body = c; bodyEnd = i + 1; rest = true;
            } else {
                PITCH.lastIndex = i;
                var m = PITCH.exec(text);
                if (!m || !m[0].length) return null;
                body = m[0]; bodyEnd = i + m[0].length;
            }
            var len = readLength(text, bodyEnd);
            var j = len.next, tie = false;
            if (text[j] === '-') { tie = true; j++; }
            items.push({ pre: pre, body: body, num: len.num, den: len.den, tie: tie, rest: rest,
                         raw: text.slice(i, j), changed: false });
            pre = '';
            i = j;
        }
        return { items: items, tail: pre };
    }

    function lengthText(units, scale) {
        var g = gcd(units, scale), n = units / g, d = scale / g;
        if (d === 1) return n === 1 ? '' : String(n);
        return (n === 1 ? '' : String(n)) + '/' + d;
    }

    /** Le texte d'une mesure ; rend aussi la place `[start, end)` de l'élément `keep`. */
    function writeBar(bar, scale, keep) {
        var out = '', place = null;
        bar.items.forEach(function (item, k) {
            out += item.pre;
            var start = out.length;
            out += item.changed ? item.body + lengthText(item.u, scale) + (item.tie && !item.rest ? '-' : '')
                                : item.raw;
            if (k === keep) place = { start: start, end: out.length };
        });
        return { text: out + bar.tail, place: place };
    }

    function retime(abc, at, op) {
        if (at == null || at < 0 || at >= abc.length) return { error: 'Aucune note choisie.' };
        var span = barAt(abc, at);
        var bar = parseBar(abc.slice(span.start, span.end));
        if (!bar || !bar.items.length) {
            return { error: 'Cette mesure écrit un rythme que ce geste ne retouche pas (triolet, ' +
                            'pointé, agrément) : la corriger dans la source ABC.' };
        }
        // Les durées en unités entières : le pas est la plus petite fraction écrite de `L:`.
        var scale = bar.items.reduce(function (s, it) { return s * it.den / gcd(s, it.den); }, 1);
        bar.items.forEach(function (it) { it.u = it.num * scale / it.den; });
        var offset = at - span.start, pos = 0, i = -1;
        for (var k = 0; k < bar.items.length; k++) {
            var from = pos;
            pos += bar.items[k].pre.length + bar.items[k].raw.length;
            if (offset >= from && offset < pos) { i = k; break; }
        }
        if (i < 0) return { error: 'Aucune note à cet endroit.' };
        var items = bar.items, cur = items[i], step = 1;
        if (cur.rest) return { error: 'Un silence ne se déplace pas : déplacer la note voisine.' };

        function touch(item, delta) { item.u += delta; item.changed = true; }
        function rest(units) { return { pre: '', body: 'z', u: units, rest: true, tie: false, changed: true }; }
        function remove(k) {                                  // son `pre` reste à sa place
            var gone = items.splice(k, 1)[0];
            var blank = !gone.pre.trim();                     // deux espaces n'en font qu'un
            if (k < items.length) items[k].pre = blank ? (items[k].pre || gone.pre) : gone.pre + items[k].pre;
            else bar.tail = blank ? (bar.tail || gone.pre) : gone.pre + bar.tail;
        }
        function untie(item) { if (item.tie) { item.tie = false; item.changed = true; } }
        /** La voisine `k` cède un pas : un silence peut disparaître, une note jamais. */
        function shrink(k, what) {
            var n = items[k];
            if (n.u > step) { touch(n, -step); return true; }
            if (n.rest) { remove(k); return true; }
            return what;
        }
        var refused;
        if (op === 'longer') {
            if (i + 1 >= items.length) return { error: 'Fin de la mesure : la note ne peut pas s’allonger.' };
            refused = shrink(i + 1, 'La note suivante disparaîtrait : la raccourcir d’abord.');
            if (refused !== true) return { error: refused };
            touch(cur, step);
        } else if (op === 'shorter') {
            if (cur.u <= step) return { error: 'La note a déjà la plus petite durée de la mesure.' };
            touch(cur, -step);
            if (i + 1 < items.length && items[i + 1].rest) touch(items[i + 1], step);
            else { items.splice(i + 1, 0, rest(step)); untie(cur); }
        } else if (op === 'right') {
            if (i + 1 < items.length) {
                refused = shrink(i + 1, 'La note suivante disparaîtrait : la raccourcir d’abord.');
                if (refused !== true) return { error: refused };
            } else if (cur.u > step) {
                touch(cur, -step);                            // la fin de la mesure ne bouge pas
            } else {
                return { error: 'Fin de la mesure : la note ne peut pas aller plus loin.' };
            }
            if (i === 0) {                                    // le vide, au début de la mesure
                var first = rest(step);
                first.pre = cur.pre; cur.pre = '';
                items.splice(0, 0, first);
                i = 1;
            } else {
                touch(items[i - 1], step);                    // la note précédente se prolonge
            }
        } else if (op === 'left') {
            if (i === 0) return { error: 'Début de la mesure : la note ne peut pas reculer.' };
            var before = items[i - 1];
            if (before.u > step) touch(before, -step);
            else if (before.rest) { remove(i - 1); i -= 1; }
            else return { error: 'La note précédente disparaîtrait : la raccourcir d’abord.' };
            if (i + 1 < items.length && items[i + 1].rest) touch(items[i + 1], step);
            else { items.splice(i + 1, 0, rest(step)); untie(cur); }
        } else {
            return { error: 'Geste inconnu : ' + op };
        }
        var written = writeBar(bar, scale, i);
        return { abc: abc.slice(0, span.start) + written.text + abc.slice(span.end),
                 start: span.start + written.place.start, end: span.start + written.place.end };
    }

    global.WamaScore = {
        degree: degree, pitchText: pitchText, transposeToken: transposeToken,
        transposeAt: transposeAt, voiceOf: voiceOf, timeline: timeline,
        playingAt: playingAt, eventTime: eventTime,
        notesFromTimings: notesFromTimings, align: align,
        barAt: barAt, parseBar: parseBar, retime: retime,
    };
})(window);
