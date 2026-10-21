/**
 * wama-segments.js — les RÈGLES d'une suite de SEGMENTS (portions de temps bornées : début, fin,
 * texte, locuteur, mots horodatés — le type `segments` de `catalog.data_types`).
 *
 * DÉPLACÉES de la page de correction du transcriber (`edit.js`) le 2026-10-21, quand elle est
 * devenue une SURFACE (ROUTE §F3b, étape 2) : la liste des segments et le transport les
 * partagent, sans DOM, donc testables sous V8 (`tests_surfaces`). Rien n'y a changé de sens :
 *   • scinder et fusionner GARDENT les mots horodatés (concaténés, partagés au curseur ; la coupe
 *     tombe entre deux mots, plus au prorata des caractères — 2026-09-24) ;
 *   • les SILENCES sont l'audio qu'aucun segment ne couvre ; une borne glissée n'avale jamais sa
 *     voisine (`MIN_SECTION`) ;
 *   • la SÉVÉRITÉ d'un segment : la cohérence IA (`coh_severity`) sinon la confiance ASR ;
 *   • le RECALAGE (déplacer une borne, couper, remplacer une plage) est un calcul SERVEUR, fait
 *     sur les mots de la sortie ASR (`word_anchoring`) : `retime` l'appelle par la route que la
 *     surface déclare, et ne touche à rien si le serveur refuse.
 */
(function (global) {
    'use strict';

    var MIN_SECTION = 0.05;
    var SEV_COLOR = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', none: '#3a3a42' };

    /** Libellé canonique d'un locuteur : « SPEAKER_NN » (les moteurs disent « 0 » ou « SPEAKER_00 »). */
    function canonSpeaker(raw) {
        if (raw == null) return '';
        var s = String(raw).trim();
        if (!s) return '';
        var m = s.match(/^(?:speaker[\s_\-]*)?(\d+)$/i);
        return m ? 'SPEAKER_' + String(parseInt(m[1], 10)).padStart(2, '0') : s;
    }

    /** Le nom montré d'un locuteur : celui que la correspondance lui donne, sinon son libellé. */
    function speakerName(raw, names) {
        var c = canonSpeaker(raw);
        return (names && names[c]) ? names[c] : c;
    }

    /** Les locuteurs canoniques présents, dans l'ordre d'apparition. */
    function speakers(segs) {
        var seen = [];
        (segs || []).forEach(function (s) {
            var c = canonSpeaker(s.speaker_id);
            if (c && seen.indexOf(c) === -1) seen.push(c);
        });
        return seen;
    }

    function indexAt(segs, t) {
        for (var i = 0; i < segs.length; i++) {
            if (t >= (segs[i].start_time || 0) && t < (segs[i].end_time || 0)) return i;
        }
        return -1;
    }

    /** [début, fin] de l'audio qu'aucun segment ne couvre, jusqu'à la durée `D`. */
    function gaps(segs, D) {
        var out = [], covered = 0;
        (segs || []).forEach(function (s) {
            var st = s.start_time || 0;
            if (st - covered > MIN_SECTION) out.push([covered, st]);
            covered = Math.max(covered, s.end_time || st);
        });
        if (D && D - covered > MIN_SECTION) out.push([covered, D]);
        return out;
    }

    function confidenceSeverity(c) {
        if (c == null) return 'none';
        if (c >= -0.4) return 'ok';
        if (c >= -0.8) return 'warn';
        return 'error';
    }
    function severity(s) { return s.coh_severity || confidenceSeverity(s.confidence); }
    function severityColor(s) { return SEV_COLOR[severity(s)] || SEV_COLOR.none; }
    function tooltip(s, i) {
        var t = 'Segment ' + (i + 1);
        if (s.confidence != null) t += ' · confiance ' + Number(s.confidence).toFixed(2);
        if (s.coh_note) t += '\n⚠ ' + s.coh_note;
        return t;
    }

    // ── Mots horodatés ────────────────────────────────────────────────────────────────────
    function spokenText(words) {
        return (words || []).map(function (w) { return w.word || ''; }).join('').trim();
    }
    function sameText(a, b) {
        return (a || '').split(/\s+/).join(' ').trim() === (b || '').split(/\s+/).join(' ').trim();
    }
    function wordsSayText(s) {
        return !!(s && s.words && s.words.length && sameText(spokenText(s.words), s.text));
    }
    function concatWords(list) {                     // tous en portent → concaténés, sinon aucun
        if (!list.every(function (s) { return s.words && s.words.length; })) return undefined;
        return [].concat.apply([], list.map(function (s) { return s.words; }));
    }
    /** Les mots d'avant le curseur restent à gauche ; l'heure de la coupe tombe entre deux mots. */
    function splitWordsAt(s, off) {
        if (!wordsSayText(s)) return null;
        var text = s.text || '';
        var cursor = 0, k = 0;
        for (; k < s.words.length; k++) {
            var w = (s.words[k].word || '').trim();
            var found = w ? text.indexOf(w, cursor) : cursor;
            if (found < 0 || found >= off) break;
            cursor = found + w.length;
        }
        if (k === 0 || k === s.words.length) return null;
        var lo = s.words[k - 1].end, hi = Math.max(lo, s.words[k].start);
        return { left: s.words.slice(0, k), right: s.words.slice(k), at: Math.round((lo + hi) * 500) / 1000 };
    }

    // ── Gestes de structure (chacun rend la NOUVELLE suite ; l'appelant en fait un cran) ─────
    /** Scinde le segment `i` au caractère `off`. */
    function splitAt(segs, i, off) {
        var s = segs[i], text = s.text || '';
        off = Math.max(0, Math.min(text.length, off));
        var st = s.start_time || 0, en = s.end_time || st;
        var byWords = splitWordsAt(s, off);
        var mid = byWords ? byWords.at : st + (en - st) * (text.length ? off / text.length : 0.5);
        var seg1 = Object.assign({}, s, { text: text.slice(0, off).trim(), end_time: mid,
                                          words: byWords ? byWords.left : undefined });
        var seg2 = Object.assign({}, s, { text: text.slice(off).trim(), start_time: mid,
                                          words: byWords ? byWords.right : undefined });
        var out = segs.slice();
        out.splice(i, 1, seg1, seg2);
        return out;
    }
    /** Fusionne `j` dans `i` (adjacents, i < j) ; rend `{segments, join}` (curseur à la jonction). */
    function mergeAt(segs, i, j) {
        var out = segs.slice();
        var a = Object.assign({}, out[i]), b = out[j];
        var join = (a.text || '').trim().length + 1;
        a.words = concatWords([a, b]);
        a.text = ((a.text || '').trim() + ' ' + (b.text || '').trim()).trim();
        a.end_time = b.end_time;
        out[i] = a;
        out.splice(j, 1);
        return { segments: out, join: join };
    }
    /** Fusionne la plage [min(a,b)..max(a,b)] ; null si elle est vide. */
    function mergeRange(segs, a, b) {
        var lo = Math.min(a, b), hi = Math.max(a, b);
        if (lo === hi || lo < 0 || hi >= segs.length) return null;
        var out = segs.slice();
        var first = Object.assign({}, out[lo]);
        var parts = [];
        for (var k = lo; k <= hi; k++) {
            var tx = (out[k].text || '').trim();
            if (tx) parts.push(tx);
        }
        first.words = concatWords(out.slice(lo, hi + 1));
        first.text = parts.join(' ').trim();
        first.end_time = out[hi].end_time;
        out[lo] = first;
        out.splice(lo + 1, hi - lo);
        return out;
    }
    /** Fusionne les segments consécutifs d'un même locuteur. */
    function compact(segs) {
        var out = [];
        segs.forEach(function (s) {
            var last = out[out.length - 1];
            var sp = s.speaker_id || '';
            if (last && sp && (last.speaker_id || '') === sp) {
                last.words = concatWords([last, s]);
                last.text = ((last.text || '').trim() + ' ' + (s.text || '').trim()).trim();
                last.end_time = s.end_time;
            } else { out.push(Object.assign({}, s)); }
        });
        return out;
    }
    /** Un segment vide qui couvre le silence où tombe `t` ; `{segments, at}` ou null. */
    function createInGap(segs, t, D) {
        var g = gaps(segs, D).filter(function (r) { return r[0] <= t && t <= r[1]; })[0];
        if (!g) return null;
        var at = 0;
        while (at < segs.length && (segs[at].start_time || 0) < g[0]) at++;
        var prev = segs[at - 1];
        var out = segs.slice();
        out.splice(at, 0, { speaker_id: prev ? (prev.speaker_id || '') : '', text: '',
                            start_time: Math.round(g[0] * 1000) / 1000,
                            end_time: Math.round(g[1] * 1000) / 1000, words: [] });
        return { segments: out, at: at };
    }

    // ── Recalage SERVEUR (`word_anchoring`, par la route déclarée de la surface) ────────────
    /**
     * Demande au serveur de remplacer `count` segments à partir de `first` : `body` porte l'op
     * (`move` / `split` + `time`, ou `replace` + plage et mots). Rend une promesse de
     * `{ok: true, segments: <nouvelle suite entière>}` ou `{ok: false, reason}` — un refus ne
     * change rien.
     */
    function retime(url, segs, first, count, body) {
        var App = global.WamaApp || {};
        if (!url) return Promise.resolve({ ok: false, reason: 'Recalage indisponible' });
        var payload = Object.assign({}, body, { segments: segs.slice(first, first + count) });
        var send = App.csrfFetch
            ? App.csrfFetch(url, App.csrfToken ? App.csrfToken() : '', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload) })
            : fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' },
                           body: JSON.stringify(payload) });
        return send.then(function (r) { return r.json(); }).then(function (d) {
            if (!d || !d.ok) return { ok: false, reason: (d && d.reason) || 'Opération refusée' };
            var out = segs.slice();
            Array.prototype.splice.apply(out, [first, count].concat(d.segments));
            return { ok: true, segments: out };
        });
    }

    /**
     * Recalage APPLIQUÉ : `retime`, puis la nouvelle suite devient UN geste (`o.edit`) et le
     * segment `o.selectAt` est choisi ; un refus se dit (`o.toast`) et ne touche à rien.
     * `o` : {url, segments, first, count, body, edit, select?, selectAt?, toast?}. Promesse d'un booléen.
     */
    function applyRetime(o) {
        var say = o.toast || function () {};
        return retime(o.url, o.segments, o.first, o.count, o.body).then(function (res) {
            if (!res.ok) { say(res.reason, 'warning'); return false; }
            o.edit(function () { return res.segments; });
            if (o.selectAt != null && o.select) o.select(o.selectAt);
            return true;
        }).catch(function () { say('Erreur réseau', 'danger'); return false; });
    }

    /**
     * Les CISEAUX à un temps — un seul geste pour l'outil Bornes (clic) et Ctrl+Entrée en
     * navigation : couper le segment qui contient `t`, ou, dans un silence, y créer un segment
     * vide à remplir (proposé le 2026-09-23). `o` : {url, segments, t, duration, edit, select, toast}.
     */
    function cutAt(o) {
        var i = indexAt(o.segments, o.t);
        if (i >= 0) {
            return applyRetime({ url: o.url, segments: o.segments, first: i, count: 1,
                                 body: { op: 'split', time: o.t }, edit: o.edit, select: o.select,
                                 selectAt: i + 1, toast: o.toast });
        }
        var made = createInGap(o.segments, o.t, o.duration);
        if (!made) return Promise.resolve(false);
        o.edit(function () { return made.segments; });
        if (o.select) o.select(made.at, { focus: true });
        return Promise.resolve(true);
    }

    /** Les segments qu'une plage [start, end] touche — `{first, count}` (insertion si aucun). */
    function spanOf(segs, start, end) {
        var lo = start - 0.05, hi = end + 0.05, first = -1, count = 0;
        segs.forEach(function (s, i) {
            if ((s.start_time || 0) <= hi && (s.end_time || 0) >= lo) { if (first < 0) first = i; count++; }
        });
        if (first < 0) {
            first = 0;
            while (first < segs.length && (segs[first].start_time || 0) < start) first++;
        }
        return { first: first, count: count };
    }

    global.WamaSegments = {
        MIN_SECTION: MIN_SECTION, SEV_COLOR: SEV_COLOR,
        canonSpeaker: canonSpeaker, speakerName: speakerName, speakers: speakers,
        indexAt: indexAt, gaps: gaps, severity: severity, severityColor: severityColor,
        tooltip: tooltip, wordsSayText: wordsSayText, concatWords: concatWords,
        splitWordsAt: splitWordsAt, splitAt: splitAt, mergeAt: mergeAt, mergeRange: mergeRange,
        compact: compact, createInGap: createInGap, retime: retime, applyRetime: applyRetime,
        cutAt: cutAt, spanOf: spanOf,
    };
})(window);
