/**
 * wama-score-player.js — LIRE une partition gravée : la graver, en lire le temps, colorer ses notes
 * jouées et la faire défiler avec elles (2026-11-15, demande de Fabien : la partition jouable dans
 * la visionneuse « comme dans la page d'édition »).
 *
 * Sorti de la brique `score_view` (`surfaces/brick-score-view.js`), qui le lit, pour que la
 * visionneuse (`media-preview.js`, face « Partition ») le lise AUSSI — une seule gravure, un seul
 * temps des notes, une seule façon de les allumer. Les règles sans DOM restent dans `wama-score.js`
 * (`timeline`, `playingAt`, le calage `timingFor`/`timeMap`) ; ce module en est la face DOM.
 *
 *   engrave(paper, abc, abcjsOptions) -> {tune, timings, tl, span, warnings}
 *       la gravure d'abcjs (`add_classes`, notes choisissables), la séquence de ses événements
 *       (`TimingCallbacks`, temps ÉCRIT en ms), la ligne du temps voix par voix
 *       (`WamaScore.timeline`) et la première et la dernière NOTE (`span`, ms) ;
 *   lighter(scroller, mayFollow) -> {paint(tl, ms, following), lit(), reset()}
 *       les notes qui sonnent à `ms` (temps écrit) colorées, les autres éteintes ; pendant la
 *       lecture (`following`), le défilement suit la note jouée (`WamaFollow.into`) quand
 *       `mayFollow()` le permet (la brique : pas pendant qu'une note est choisie pour l'éditer).
 */
(function (global) {
    'use strict';

    var PLAYING = 'wama-score-playing';

    function engrave(paper, abc, abcjsOptions) {
        var ABCJS = global.ABCJS, Score = global.WamaScore;
        var opts = Object.assign({ add_classes: true, responsive: 'resize', selectTypes: ['note'] },
                                 abcjsOptions || {});
        var tune = ABCJS.renderAbc(paper, abc, opts)[0];
        // La séquence audio d'abcjs donne aux notes leurs hauteurs MIDI — de quoi distinguer une
        // note d'un silence (la 1re et la dernière NOTE). Aucun son n'est produit.
        try { tune.setUpAudio({}); } catch (e) { /* hauteurs absentes */ }
        var timings = [];
        try { timings = new ABCJS.TimingCallbacks(tune, {}).noteTimings || []; } catch (e) { timings = []; }
        var events = [], endMs = 0, span = null;
        timings.forEach(function (ev) {
            endMs = Math.max(endMs, ev.milliseconds);
            if (ev.type !== 'event') return;
            if ((ev.midiPitches || []).length) {
                span = span ? [span[0], ev.milliseconds] : [ev.milliseconds, ev.milliseconds];
            }
            events.push({ ms: ev.milliseconds, sets: (ev.elements || []).map(function (els, i) {
                var first = els && els[0];
                var cls = first && first.getAttribute ? first.getAttribute('class') : '';
                return { voice: /abcjs-v\d/.test(cls || '') ? Score.voiceOf(cls) : i, ref: els || [] };
            }) });
        });
        return { tune: tune, timings: timings, tl: Score.timeline(events, endMs), span: span,
                 warnings: (tune && tune.warnings) || [] };
    }

    function lighter(scroller, mayFollow) {
        var lit = [];
        function paint(tl, ms, following) {
            var now = tl ? global.WamaScore.playingAt(tl, ms) : [];
            var keep = new Set(now);
            lit.forEach(function (els) {
                if (!keep.has(els)) els.forEach(function (el) { el.classList && el.classList.remove(PLAYING); });
            });
            now.forEach(function (els) { els.forEach(function (el) { el.classList && el.classList.add(PLAYING); }); });
            var changed = now.length !== lit.length || now.some(function (els, i) { return els !== lit[i]; });
            lit = now;
            if (following && changed && now.length && now[0][0] && (!mayFollow || mayFollow())
                    && global.WamaFollow) {
                global.WamaFollow.into(scroller, now[0][0]);
            }
        }
        return {
            paint: paint,
            lit: function () { return lit; },
            reset: function () { lit = []; },
        };
    }

    global.WamaScorePlayer = { engrave: engrave, lighter: lighter, PLAYING: PLAYING };
})(window);
