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
 * mesure en écrit une) — sauf un pas FORCÉ (`retime(abc, at, op, 1/4)` : une fraction de ronde,
 * ici la noire ; 2026-10-22, Fabien), ramené à l'unité `L:` en vigueur ; plus fin que l'écrit, il
 * donne des durées fractionnaires (`A/2`). Ce qui ajuste la mesure :
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

    // ── Caler la partition sur l'audio : par ses REPÈRES (2026-11-15) ──────────────────────────
    // Jusqu'au 2026-11-15, la page DEVINAIT le calage (ressemblance des hauteurs sur ±16 temps) et
    // se trompait de 6 à 16 s sur les huit partitions mesurées des cards de Fabien (pistes séparées
    // à longue intro). Le moteur qui écrit une partition sait où tombe chaque mesure : il le NOTE
    // dans l'en-tête (`common/utils/score_timing.py`, une ligne `% wama-sync:` — un couple
    // « ms écrit : s d'audio » par barre), la page le LIT. Une partition fournie n'en a pas : sa
    // première et sa dernière note se calent sur la première et la dernière attaque de l'audio
    // (`audio_rhythm`), au prorata entre les deux.

    var SYNC_PREFIX = '% wama-sync:';

    /** Les repères d'une partition : `[[ms écrit, s d'audio]]` dans l'ordre, ou null. */
    function syncOf(abc) {
        var lines = String(abc || '').split('\n');
        for (var i = 0; i < lines.length; i++) {
            if (lines[i].indexOf(SYNC_PREFIX) !== 0) continue;
            var pairs = [], re = /(-?\d+(?:\.\d+)?):(-?\d+(?:\.\d+)?)/g, m;
            while ((m = re.exec(lines[i].slice(SYNC_PREFIX.length)))) pairs.push([Number(m[1]), Number(m[2])]);
            return pairs.length >= 2 ? pairs : null;
        }
        return null;
    }

    /** Les repères d'une partition qui n'en porte pas : sa 1re et sa dernière note (ms écrits) sur
     *  la 1re et la dernière attaque de l'audio (s). Une seule note, ou des attaques qui ne laissent
     *  pas la place : la 1re seule, au tempo écrit. */
    function anchorPairs(firstMs, lastMs, firstS, lastS) {
        // `typeof` : `null >= 0` est VRAI en JavaScript — sans attaque mesurée, rien à caler.
        if (typeof firstMs !== 'number' || typeof firstS !== 'number' || !(firstMs >= 0) || !(firstS >= 0)) {
            return null;
        }
        if (typeof lastS === 'number' && lastMs > firstMs && lastS > firstS) {
            return [[firstMs, firstS], [lastMs, lastS]];
        }
        return [[firstMs, firstS], [firstMs + 1000, firstS + 1]];
    }

    /** Le CALAGE à appliquer selon ce qu'on écoute — la règle de la brique partition ET de la
     *  visionneuse (2026-11-15) : `{pairs, how, midi}`. Les REPÈRES (`marks`) valent sur l'audio
     *  dont la partition est tirée (`listened === follows`) et sur sa propre lecture MIDI
     *  (`ownMidi`) ; les notes extrêmes calées sur les attaques (`anchors`) valent sur l'audio dont
     *  ces attaques sont lues (`listened === anchorsOf`) ; sur tout autre audio, rien : le tempo
     *  écrit. `midi` : ce que la lecture MIDI suit — les repères, sinon les attaques. */
    function timingFor(o) {
        o = o || {};
        var midi = o.marks || o.anchors || null;
        var how = function (pairs) { return !pairs ? '' : (pairs === o.marks ? 'marks' : 'anchors'); };
        if (o.ownMidi) return { pairs: midi, how: how(midi), midi: midi };
        if (o.marks && o.listened === o.follows) return { pairs: o.marks, how: 'marks', midi: midi };
        if (o.anchors && o.listened === o.anchorsOf) return { pairs: o.anchors, how: 'anchors', midi: midi };
        return { pairs: null, how: '', midi: midi };
    }

    /** Le temps d'une partition calée par ses repères : `toAudio(ms écrit) → s`, `toScore(s) → ms
     *  écrit`, au prorata entre deux repères, prolongés au-delà par la pente du repère extrême. */
    function timeMap(pairs) {
        if (!pairs || pairs.length < 2) return null;
        var p = pairs.slice().sort(function (a, b) { return a[0] - b[0]; });
        function through(x, from, to) {
            var n = p.length, i = 0;
            if (x <= p[0][from]) i = 0;
            else if (x >= p[n - 1][from]) i = n - 2;
            else while (i < n - 2 && p[i + 1][from] <= x) i++;
            var a = p[i], b = p[i + 1], span = b[from] - a[from];
            return span ? a[to] + (x - a[from]) * (b[to] - a[to]) / span : a[to];
        }
        return {
            pairs: p,
            toAudio: function (ms) { return through(ms, 0, 1); },
            toScore: function (s) { return through(s, 1, 0); },
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

    /** L'unité de durée `L:` en vigueur au caractère `at` : `[a, b]` (fraction de ronde). Sans
     *  `L:`, la valeur par défaut de la norme ABC pour une mesure courante, la croche. */
    function unitAt(abc, at) {
        var re = /(?:^|\n)L:\s*(\d+)\s*\/\s*(\d+)/g, m, found = [1, 8];
        while ((m = re.exec(abc)) && m.index < at) found = [Number(m[1]), Number(m[2])];
        return found;
    }

    function retime(abc, at, op, stepWhole) {
        if (at == null || at < 0 || at >= abc.length) return { error: 'Aucune note choisie.' };
        var span = barAt(abc, at);
        var bar = parseBar(abc.slice(span.start, span.end));
        if (!bar || !bar.items.length) {
            return { error: 'Cette mesure écrit un rythme que ce geste ne retouche pas (triolet, ' +
                            'pointé, agrément) : la corriger dans la source ABC.' };
        }
        // Les durées en unités entières : le pas est la plus petite fraction écrite de `L:`, sauf
        // un pas FORCÉ (`stepWhole`, une fraction de ronde : 1/4 = la noire), ramené en `L:`.
        var stepNum = 1, stepDen = 1;
        if (stepWhole) {
            var unit = unitAt(abc, at), whole = Math.round(1 / stepWhole);
            stepNum = unit[1]; stepDen = whole * unit[0];
            var g0 = gcd(stepNum, stepDen); stepNum /= g0; stepDen /= g0;
        }
        var scale = bar.items.reduce(function (s, it) { return s * it.den / gcd(s, it.den); }, stepDen);
        bar.items.forEach(function (it) { it.u = it.num * scale / it.den; });
        var offset = at - span.start, pos = 0, i = -1;
        for (var k = 0; k < bar.items.length; k++) {
            var from = pos;
            pos += bar.items[k].pre.length + bar.items[k].raw.length;
            if (offset >= from && offset < pos) { i = k; break; }
        }
        if (i < 0) return { error: 'Aucune note à cet endroit.' };
        var items = bar.items, cur = items[i];
        var step = stepWhole ? stepNum * scale / stepDen : 1;
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
        var TOO_WIDE = 'Le pas choisi est plus grand que la place disponible : choisir un pas plus fin.';
        /** La voisine `k` cède un pas : un silence peut disparaître, une note jamais. Un silence
         *  plus court qu'un pas FORCÉ ne suffit pas à le céder. */
        function shrink(k, what) {
            var n = items[k];
            if (n.u > step) { touch(n, -step); return true; }
            if (n.rest && n.u === step) { remove(k); return true; }
            return n.rest ? TOO_WIDE : what;
        }
        var refused;
        if (op === 'longer') {
            if (i + 1 >= items.length) return { error: 'Fin de la mesure : la note ne peut pas s’allonger.' };
            refused = shrink(i + 1, 'La note suivante disparaîtrait : la raccourcir d’abord.');
            if (refused !== true) return { error: refused };
            touch(cur, step);
        } else if (op === 'shorter') {
            if (cur.u <= step) return { error: 'La note n’est pas plus longue que le pas : elle ne peut pas raccourcir.' };
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
                return { error: 'Fin de la mesure : la note ne peut pas aller plus loin d’un pas.' };
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
            else if (before.rest && before.u === step) { remove(i - 1); i -= 1; }
            else if (before.rest) return { error: TOO_WIDE };
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

    // ── LES PISTES d'une partition (2026-11-07, demande de Fabien : « récupérer la partition d'une
    // seule piste, la batterie par exemple, pour l'éditer, l'enregistrer, l'imprimer, la
    // réutiliser ») ─────────────────────────────────────────────────────────────────────────────
    // Une PISTE est un instrument : un groupe de `%%score` (les deux mains d'un piano, `{P1R P1L}`,
    // en font une), ou une voix seule. Son nom est celui de sa déclaration `V:<id> … name="…"`. La
    // forme est celle qu'écrivent nos producteurs (`midi_score`, SheetSage) : en-tête, `K:`, puis
    // des blocs `V:<id>` suivis de leurs notes. Sans DOM : tenues par `tests_score_tracks` (V8).

    /** `{head: [lignes], decl: {id: ligne}, blocks: [{id, lines}]}` — l'en-tête jusqu'à `K:`
     *  compris, les déclarations de voix, puis les blocs du corps (`id` '' avant la 1re voix). */
    function splitVoices(abc) {
        var lines = String(abc || '').split('\n'), head = [], decl = {}, blocks = [], i = 0;
        var voiceId = function (line) { return line.replace(/^V:\s*/, '').split(/\s+/)[0]; };
        for (; i < lines.length; i++) {
            head.push(lines[i]);
            if (/^V:/.test(lines[i])) decl[voiceId(lines[i])] = lines[i];
            if (/^K:/.test(lines[i])) { i++; break; }
        }
        var block = { id: '', lines: [] };
        for (; i < lines.length; i++) {
            if (/^V:/.test(lines[i])) {
                if (block.id || block.lines.length) blocks.push(block);
                block = { id: voiceId(lines[i]), lines: [lines[i]] };
            } else block.lines.push(lines[i]);
        }
        if (block.id || block.lines.length) blocks.push(block);
        return { head: head, decl: decl, blocks: blocks };
    }

    /** Les pistes de `abc` : `[{key, ids, label}]` dans l'ordre de `%%score` (sinon des
     *  déclarations). Une partition à une seule voix n'a qu'une piste. */
    function tracksOf(abc) {
        var parts = splitVoices(abc), ids = Object.keys(parts.decl), score = null;
        parts.head.forEach(function (line) { if (/^%%score\s/.test(line)) score = line; });
        var groups = [];
        if (score) {
            var rest = score.replace(/^%%score\s+/, ''), re = /\{([^}]*)\}|(\S+)/g, m;
            while ((m = re.exec(rest))) {
                var members = (m[1] !== undefined ? m[1] : m[2]).replace(/[()[\]|]/g, ' ')
                    .split(/\s+/).filter(function (id) { return id && parts.decl[id]; });
                if (members.length) groups.push(members);
            }
        }
        var grouped = {};
        groups.forEach(function (g) { g.forEach(function (id) { grouped[id] = true; }); });
        ids.forEach(function (id) { if (!grouped[id]) groups.push([id]); });
        return groups.map(function (g) {
            var named = /name="([^"]*)"/.exec(parts.decl[g[0]] || '');
            return { key: g.join(' '), ids: g, label: (named && named[1]) || g[0] };
        });
    }

    /** La partition de la seule piste `ids` : son en-tête (sans les déclarations des autres voix,
     *  `%%score` réduit à elle), puis ses blocs. Une ABC jouable, gravable, exportable telle quelle. */
    function trackOnly(abc, ids) {
        var keep = {};
        (ids || []).forEach(function (id) { keep[id] = true; });
        var parts = splitVoices(abc), out = [];
        parts.head.forEach(function (line) {
            if (/^V:/.test(line)) {
                if (keep[line.replace(/^V:\s*/, '').split(/\s+/)[0]]) out.push(line);
            } else if (/^%%score\s/.test(line)) {
                out.push('%%score ' + (ids.length > 1 ? '{' + ids.join(' ') + '}' : ids[0]));
            } else out.push(line);
        });
        parts.blocks.forEach(function (b) { if (keep[b.id]) out.push.apply(out, b.lines); });
        return out.join('\n');
    }

    /** Le geste fait sur la seule piste `ids` (`edited`, la sortie de `trackOnly` modifiée),
     *  RAPPORTÉ dans la partition entière : ses blocs remplacent, dans l'ordre, ceux de la piste ;
     *  l'en-tête et les autres pistes ne bougent pas. */
    function mergeTrack(abc, ids, edited) {
        var keep = {};
        (ids || []).forEach(function (id) { keep[id] = true; });
        var queues = {};
        splitVoices(edited).blocks.forEach(function (b) {
            if (keep[b.id]) (queues[b.id] = queues[b.id] || []).push(b.lines);
        });
        var parts = splitVoices(abc), out = parts.head.slice();
        parts.blocks.forEach(function (b) {
            var next = keep[b.id] && queues[b.id] && queues[b.id].length ? queues[b.id].shift() : null;
            out.push.apply(out, next || b.lines);
        });
        return out.join('\n');
    }

    // ── LES PAROLES SOUS LES NOTES (2026-11-08, décision de Fabien : afficher les paroles sur la
    // partition réduite, la partition complète et la piste de chant, en entrée comme en sortie) ──
    // Les mots horodatés (l'écoute du composer : modèle d'écoute + aligneur du transcriber) sont
    // posés sous les notes de la VOIX CHANTÉE par des lignes `w:` — la notation des paroles de l'ABC,
    // que la gravure place d'elle-même sous la portée. Un mot va à la note pendant laquelle il
    // commence ; plusieurs mots sur une note se lient (`~`), une note sans mot passe (`*`). Le temps
    // d'une note est celui que disent les REPÈRES de la partition (`syncOf`, 2026-11-15) ; sans
    // repères, celui du tempo écrit (`Q:`) mis à l'échelle de la durée de l'audio entendu
    // (`duration` du JSON) — la règle de `fit_to_duration` côté serveur, pas un calage fin.

    /** La voix CHANTÉE : la piste NOMMÉE comme une voix — `Vocal Melody` (SheetSage, YuE2), `Voix`
     *  (`midi_score`). Jamais « la seule voix » : la vue d'une seule piste (la batterie) en a une. */
    var VOCAL = /voi[xc]|vocal|chant|sing|lead/i;
    function vocalVoice(abc) {
        var sung = tracksOf(abc).filter(function (t) { return VOCAL.test(t.label); })[0];
        return sung ? sung.ids[0] : null;
    }

    function headerFraction(abc, field, fallback) {
        var m = new RegExp('(?:^|\\n)' + field + ':\\s*(\\d+)\\s*/\\s*(\\d+)').exec(abc);
        return m ? Number(m[1]) / Number(m[2]) : fallback;
    }

    function tempoOf(abc) {
        var m = /(?:^|\n)Q:\s*(?:(\d+)\s*\/\s*(\d+)\s*=\s*)?(\d+(?:\.\d+)?)/.exec(abc);
        if (!m) return { unit: 0.25, bpm: 120 };
        return { unit: m[1] ? Number(m[1]) / Number(m[2]) : 0.25, bpm: Number(m[3]) || 120 };
    }

    function lyricToken(word) {
        return String(word || '').replace(/[*~_|\\\s]/g, '').replace(/-/g, '\\-');
    }

    /** `abc` avec, sous chaque ligne de musique de la voix chantée, la ligne `w:` de ses mots —
     *  `{abc, inserts: [{at, length}]}` (`at` : position dans le texte d'ORIGINE où la ligne entre),
     *  de quoi ramener une position du texte gravé à celle du texte édité (`sourceAt`). Inchangé
     *  sans voix chantée, sans mots, ou sur une mesure que cette lecture ne sait pas compter. */
    function withLyrics(abc, lyrics) {
        var words = ((lyrics && lyrics.words) || []).filter(function (w) {
            return w && lyricToken(w.word) && typeof w.start === 'number';
        });
        var voice = words.length ? vocalVoice(abc) : null;
        if (!voice) return { abc: abc, inserts: [] };
        var unitL = headerFraction(abc, 'L', 1 / 8), meter = headerFraction(abc, 'M', 1);
        var tempo = tempoOf(abc);
        // 1er passage : les notes de la voix, ligne par ligne, et leur temps écrit (en ronde). Les
        // blocs de voix sont ceux de `splitVoices` (la lecture des pistes) ; il garde toutes les
        // lignes dans l'ordre, d'où la position de chacune dans le texte d'origine.
        var parts = splitVoices(abc), lines = [], pos = 0, clock = 0;
        parts.head.forEach(function (line) { pos += line.length + 1; });
        var body = [];
        parts.blocks.forEach(function (b) {
            b.lines.forEach(function (line) { body.push({ id: b.id, line: line }); });
        });
        body.forEach(function (entry) {
            var line = entry.line, start = pos;
            pos += line.length + 1;
            if (entry.id !== voice || !line.trim() || /^[A-Za-z]:|^%/.test(line)) return;
            var notes = [], countable = true;
            line.split('|').forEach(function (segment) {
                var bar = segment.replace(/^[\]:]+/, '').replace(/[\[:]+$/, '');
                if (!bar.trim()) return;
                var parsed = parseBar(bar);
                if (!parsed) { countable = false; clock += meter; return; }
                parsed.items.forEach(function (item) {
                    var span = item.num / item.den * unitL;
                    if (!item.rest) notes.push({ at: clock });
                    clock += span;
                });
            });
            lines.push({ start: start, end: start + line.length, notes: notes, countable: countable });
        });
        var seconds = function (whole) { return whole / tempo.unit * 60 / tempo.bpm; };
        var total = seconds(clock);
        var scale = (lyrics.duration > 0 && total > 0) ? lyrics.duration / total : 1;
        // Une partition qui porte ses REPÈRES (2026-11-15) dit l'instant d'audio de chaque note :
        // plus d'étirement à la durée de l'audio, faux dès qu'il y a une intro.
        var marks = timeMap(syncOf(abc));
        var all = [];
        lines.forEach(function (l) {
            l.notes.forEach(function (n) {
                n.t = marks ? marks.toAudio(seconds(n.at) * 1000) : seconds(n.at) * scale;
                n.tokens = [];
                all.push(n);
            });
        });
        if (!all.length) return { abc: abc, inserts: [] };
        // 2ᵉ passage : chaque mot va à la note pendant laquelle il commence.
        words.slice().sort(function (a, b) { return a.start - b.start; }).forEach(function (w) {
            var k = 0;
            while (k + 1 < all.length && all[k + 1].t <= w.start) k++;
            all[k].tokens.push(lyricToken(w.word));
        });
        var out = '', last = 0, inserts = [];
        lines.forEach(function (l) {
            if (!l.countable || !l.notes.some(function (n) { return n.tokens.length; })) return;
            var text = 'w: ' + l.notes.map(function (n) {
                return n.tokens.length ? n.tokens.join('~') : '*';
            }).join(' ');
            var at = Math.min(l.end + 1, abc.length);
            var piece = (l.end >= abc.length ? '\n' : '') + text + '\n';
            out += abc.slice(last, at) + piece;
            inserts.push({ at: at, length: piece.length });
            last = at;
        });
        out += abc.slice(last);
        return { abc: out, inserts: inserts };
    }

    /** Position du texte GRAVÉ (avec ses lignes `w:`) → position du texte édité ; -1 dans un ajout. */
    function sourceAt(inserts, shown) {
        var shift = 0;
        for (var i = 0; i < (inserts || []).length; i++) {
            var at = inserts[i].at + shift;
            if (shown < at) break;
            if (shown < at + inserts[i].length) return -1;
            shift += inserts[i].length;
        }
        return shown - shift;
    }

    /** Position du texte édité → position du texte gravé. */
    function shownAt(inserts, source) {
        var shift = 0;
        (inserts || []).forEach(function (ins) { if (ins.at <= source) shift += ins.length; });
        return source + shift;
    }

    global.WamaScore = {
        degree: degree, pitchText: pitchText, transposeToken: transposeToken,
        transposeAt: transposeAt, voiceOf: voiceOf, timeline: timeline,
        playingAt: playingAt, eventTime: eventTime,
        syncOf: syncOf, anchorPairs: anchorPairs, timeMap: timeMap, timingFor: timingFor,
        barAt: barAt, parseBar: parseBar, retime: retime, unitAt: unitAt,
        tracksOf: tracksOf, trackOnly: trackOnly, mergeTrack: mergeTrack,
        vocalVoice: vocalVoice, withLyrics: withLyrics, sourceAt: sourceAt, shownAt: shownAt,
    };
})(window);
