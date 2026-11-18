/**
 * wama-score-player.js — LIRE une partition gravée : la graver, en lire le temps, colorer ses notes
 * jouées et la faire défiler avec elles (2026-11-15, demande de Fabien : la partition jouable dans
 * la visionneuse « comme dans la page d'édition »).
 *
 * Sorti de la brique `score_view` (`surfaces/brick-score-view.js`), qui le lit ; la visionneuse
 * (`media-preview.js`, face « Partition ») monte la brique elle-même depuis le 2026-11-16
 * (`WamaSurface.view`) — une seule gravure, un seul temps des notes, une seule façon de les
 * allumer. Les règles sans DOM restent dans `wama-score.js`
 * (`timeline`, `playingAt`, le calage `timingFor`/`timeMap`) ; ce module en est la face DOM.
 *
 *   engrave(paper, abc, abcjsOptions) -> {tune, timings, tl, span, warnings}
 *       la gravure d'abcjs (`add_classes`, notes choisissables), lignes JUSTIFIÉES à la largeur de
 *       `paper` (reflux `wrap`, 2026-11-18 — à regraver quand cette largeur change : la brique
 *       la surveille), la séquence de ses événements
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

    // ── La MISE EN PAGE : des lignes JUSTIFIÉES à la largeur de la zone (2026-11-18) ───────────────
    // Fabien : « l'espace utilisé par les mesures est très aléatoire. Les mesures sortent de la
    // partition sur la droite, ne sont pas consistantes et ne sont pas bornées […] il faut que ça
    // soit aligné à droite dans la zone de la fenêtre de la partition, comme pour du texte
    // justifié. » Les lignes suivaient celles du texte ABC (1 à 4 mesures, selon l'extraction) :
    // une ligne dense débordait à droite (jusqu'à 84 px mesurés, Plus d'eau), une ligne courte
    // s'étirait sur toute la largeur. Le REFLUX d'abcjs (`wrap`) range les mesures ligne après
    // ligne dans la largeur gravée (`staffwidth`), l'espacement borné (`minSpacing` : en deçà,
    // la mesure passe à la ligne suivante ; `maxSpacing` : au-delà, une mesure de plus) — mesuré sur
    // les partitions de Plus d'eau et d'Electro Deluxe : aucun débord à 1100 px. Une mesure trop
    // dense pour la largeur (une fenêtre étroite) fait regraver plus LARGE : la partition se réduit
    // à l'échelle de la zone (`responsive: 'resize'`) plutôt que d'être coupée.
    var WRAP = { minSpacing: 1.8, maxSpacing: 2.7, preferredMeasuresPerLine: 4 };
    /** La largeur gravée minimale (unités d'abcjs) : en deçà, la partition se réduit à l'échelle. */
    var MIN_STAFF = 740;
    /** Les marges d'abcjs de part et d'autre de la portée (15 unités chacune). */
    var PADDING = 30;
    var WIDER = 1.15, ATTEMPTS = 3;

    /** La largeur gravée pour la zone `paper` : sa largeur, au moins `MIN_STAFF` — pure. */
    function staffWidth(paperWidth) {
        return Math.max(MIN_STAFF, Math.round((Number(paperWidth) || 0) - PADDING));
    }

    /** De combien (unités d'abcjs) la gravure dépasse sa largeur, 0 sinon — ou quand le
     *  navigateur ne sait pas la mesurer (`getBBox`). */
    function overflow(paper) {
        var svg = paper && paper.querySelector && paper.querySelector('svg');
        if (!svg || !svg.getBBox || !svg.viewBox || !svg.viewBox.baseVal) return 0;
        try {
            var box = svg.getBBox(), width = svg.viewBox.baseVal.width;
            return width ? Math.max(0, Math.round(box.x + box.width - width)) : 0;
        } catch (e) { return 0; }
    }

    function engrave(paper, abc, abcjsOptions) {
        var ABCJS = global.ABCJS, Score = global.WamaScore;
        var base = Object.assign({ add_classes: true, responsive: 'resize', selectTypes: ['note'],
                                   wrap: WRAP }, abcjsOptions || {});
        var width = staffWidth(paper.clientWidth), tune = null;
        for (var attempt = 0; attempt < ATTEMPTS; attempt++) {
            tune = ABCJS.renderAbc(paper, abc, Object.assign({ staffwidth: width }, base))[0];
            if (!overflow(paper)) break;
            width = Math.round(width * WIDER);
        }
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

    global.WamaScorePlayer = { engrave: engrave, lighter: lighter, PLAYING: PLAYING,
                               staffWidth: staffWidth, WRAP: WRAP };
})(window);
