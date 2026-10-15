/**
 * Brique `score_view` — une partition ABC gravée, ABONNÉE à l'axe partagé (2026-10-15, 3ᵉ
 * surface : la partition du composer ; déclaration : `common/surfaces.py`).
 *
 * Universelle : elle lit la valeur éditée de la surface quand c'est un texte ABC (le contenu d'un
 * champ fichier, `surfaces.text_value`) et la réécrit telle quelle. La gravure est celle d'abcjs
 * (vendorisé, `tools/update_vendors.sh`) ; les règles sans DOM sont dans `wama-score.js`.
 *
 * Ce qu'elle fait :
 *   • les notes JOUÉES se colorent, voix par voix (`WamaScore.playingAt`), à chaque battement de
 *     l'axe — elle ne lit jamais un lecteur : elle observe le temps (`WAMA_DATA_WORLD §5bis`) ;
 *   • elle défile pour garder la note jouée visible ;
 *   • un clic sur une note y amène la lecture (`axis.seek`) ;
 *   • glisser une note vers le haut ou le bas la transpose d'un degré par cran (le glisser
 *     d'abcjs) : UN geste d'édition, `ctx.edit` — Ctrl+Z l'annule ;
 *   • « Caler sur le média » étire le tempo de la partition sur la durée de l'axe (un rendu qui
 *     n'a pas tenu exactement le tempo écrit) ; sinon le temps est celui du tempo écrit (`Q:`).
 */
(function (global) {
    'use strict';

    var RENDER_DELAY_MS = 250;
    var PLAYING = 'wama-score-playing';

    function mount(body, ctx) {
        var ABCJS = global.ABCJS, Score = global.WamaScore;
        var axis = ctx.axis();
        body.classList.add('wama-brick-score');
        var paper = document.createElement('div');
        paper.className = 'wama-score-paper';
        body.appendChild(paper);

        var tools = document.createElement('span');
        tools.className = 'wama-brick-tools';
        var warn = document.createElement('span');
        warn.className = 'badge text-bg-warning d-none';
        var fitLabel = document.createElement('label');
        fitLabel.className = 'wama-score-fit';
        fitLabel.title = 'Étirer le tempo de la partition sur la durée du média';
        var fit = document.createElement('input');
        fit.type = 'checkbox';
        fitLabel.appendChild(fit);
        fitLabel.appendChild(document.createTextNode(' Caler sur le média'));
        tools.appendChild(warn);
        tools.appendChild(fitLabel);
        // Les outils vivent dans la poignée de la brique : un clic ne doit pas la déplacer.
        tools.addEventListener('mousedown', function (e) { e.stopPropagation(); });

        var timings = [], tl = null, lit = [], rendered = null, pending = null;

        function text() { var v = ctx.value(); return typeof v === 'string' ? v : ''; }

        function stretch() {
            var d = axis ? axis.duration() : 0;
            return (fit.checked && tl && tl.end && d) ? tl.end / (d * 1000) : 1;
        }

        function render() {
            pending = null;
            var abc = text();
            if (abc === rendered) return;
            rendered = abc;
            var top = body.scrollTop;
            lit = [];
            timings = [];
            tl = null;
            if (!abc.trim() || !ABCJS) {
                paper.textContent = ABCJS ? 'Partition vide.' : 'Moteur de partition non chargé.';
                return;
            }
            var tune = ABCJS.renderAbc(paper, abc, {
                add_classes: true, responsive: 'resize', selectTypes: ['note'],
                dragging: !!ctx.canEdit, clickListener: onNote,
            })[0];
            try { timings = new ABCJS.TimingCallbacks(tune, {}).noteTimings || []; } catch (e) { timings = []; }
            var events = [], endMs = 0;
            timings.forEach(function (ev) {
                endMs = Math.max(endMs, ev.milliseconds);
                if (ev.type !== 'event') return;
                events.push({ ms: ev.milliseconds, sets: (ev.elements || []).map(function (els, i) {
                    var first = els && els[0];
                    var cls = first && first.getAttribute ? first.getAttribute('class') : '';
                    return { voice: /abcjs-v\d/.test(cls || '') ? Score.voiceOf(cls) : i, ref: els || [] };
                }) });
            });
            tl = Score.timeline(events, endMs);
            var warnings = (tune && tune.warnings) || [];
            warn.classList.toggle('d-none', !warnings.length);
            warn.textContent = warnings.length + ' avert.';
            warn.title = warnings.map(function (w) { return String(w).replace(/<[^>]*>/g, ''); }).join('\n');
            body.scrollTop = top;
            if (axis) paint(axis.time(), false);
        }

        function schedule() {
            if (pending) clearTimeout(pending);
            pending = setTimeout(render, RENDER_DELAY_MS);
        }

        function paint(seconds, follow) {
            var now = tl ? Score.playingAt(tl, seconds * 1000 * stretch()) : [];
            var keep = new Set(now);
            lit.forEach(function (els) {
                if (!keep.has(els)) els.forEach(function (el) { el.classList && el.classList.remove(PLAYING); });
            });
            now.forEach(function (els) { els.forEach(function (el) { el.classList && el.classList.add(PLAYING); }); });
            var changed = now.length !== lit.length || now.some(function (els, i) { return els !== lit[i]; });
            lit = now;
            if (follow && changed && now.length && now[0][0]) keepVisible(now[0][0]);
        }

        /** Fait défiler la BRIQUE (jamais la page) pour garder la note jouée en vue. */
        function keepVisible(el) {
            var box = body.getBoundingClientRect(), r = el.getBoundingClientRect();
            if (r.top < box.top + 8 || r.bottom > box.bottom - 8) {
                body.scrollTop += (r.top - box.top) - box.height / 3;
            }
        }

        function onNote(abcelem, tuneNumber, classes, analysis, drag) {
            if (!abcelem || abcelem.startChar == null) return;
            if (drag && drag.step && ctx.canEdit) {
                ctx.edit(function (v) { return Score.transposeAt(v, abcelem.startChar, abcelem.endChar, drag.step); });
                return;
            }
            var ms = Score.eventTime(timings, abcelem.startChar);
            if (ms != null && axis) axis.seek(ms / 1000 / stretch());
        }

        fit.addEventListener('change', function () { if (axis) paint(axis.time(), true); });
        if (axis) axis.subscribe(function (snap) { paint(snap.time, snap.playing || snap.reason === 'seek'); });

        render();
        return {
            refresh: function () { if (text() !== rendered) schedule(); },
            tools: tools,
            help: 'Partition : clic sur une note = y aller · glisser une note vers le haut ou le bas = la transposer d’un degré (Ctrl+Z annule) · « Caler sur le média » étire le tempo sur la durée de l’audio',
        };
    }

    global.WamaSurface.registerBrick('score_view', { title: 'Partition', mount: mount });
})(window);
