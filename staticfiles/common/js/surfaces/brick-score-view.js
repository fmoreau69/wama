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
 *     d'abcjs) : UN geste d'édition, `ctx.edit` — Ctrl+Z l'annule.
 *
 * LE TEMPS DE LA PARTITION GUIDE (2026-10-16, remarque de Fabien — l'anacrouse ne tombait pas où
 * on l'entend) : le temps ÉCRIT n est calé sur le temps JOUÉ n + k de l'audio (`options.media`,
 * le rôle lu ; grille servie par `data/?only=rhythm`, `common/utils/audio_rhythm.py`), au prorata
 * entre deux temps — un tempo écrit arrondi (#754 : 88 écrit, 89,1 joué) ne fait plus dériver le
 * morceau. Tant que la grille n'est pas là, ou si on décoche « Calée sur les temps joués », le
 * temps est celui du tempo écrit (`Q:`).
 *
 * LECTURE SEULE (2026-10-16, la partition complète du composer) : `options.role` montre un rôle LU
 * en texte (`Surface.texts`) au lieu de la valeur éditée — même gravure, même axe, mêmes notes
 * colorées, aucun geste d'édition ; `options.empty` dit pourquoi il n'y a encore rien.
 *
 * PLUSIEURS PARTITIONS, UNE SEULE VUE (2026-10-22, demande de Fabien : « une seule UI, qui affiche
 * soit la partition réduite, soit la partition complète ») : `options.versions` = `[{label, role?,
 * empty?}]` — la valeur éditée (sans `role`) et des rôles lus en texte. Un choix « Partition » dans
 * la poignée passe de l'une à l'autre, sur la même largeur, le même axe ; une version lue (`role`)
 * se montre en lecture seule. Le geste de la version écoutée du transport (`ctx.sources()`), pour
 * une partition.
 */
(function (global) {
    'use strict';

    var RENDER_DELAY_MS = 250;
    var PLAYING = 'wama-score-playing';

    function mount(body, ctx, options) {
        options = options || {};
        var ABCJS = global.ABCJS, Score = global.WamaScore, Axis = global.WamaAxis;
        var App = global.WamaApp || {};
        var axis = ctx.axis();
        body.classList.add('wama-brick-score');
        var paper = document.createElement('div');
        paper.className = 'wama-score-paper';
        body.appendChild(paper);

        var tools = document.createElement('span');
        tools.className = 'wama-brick-tools';
        var warn = document.createElement('span');
        warn.className = 'badge text-bg-warning d-none';
        var syncLabel = document.createElement('label');
        syncLabel.className = 'wama-score-fit';
        var sync = document.createElement('input');
        sync.type = 'checkbox';
        sync.checked = true;
        sync.disabled = true;
        var syncText = document.createElement('span');
        syncText.textContent = ' Temps joués : calcul…';
        syncLabel.appendChild(sync);
        syncLabel.appendChild(syncText);
        tools.appendChild(warn);
        tools.appendChild(syncLabel);
        // Les outils vivent dans la poignée de la brique : un clic ne doit pas la déplacer.
        tools.addEventListener('mousedown', function (e) { e.stopPropagation(); });

        var timings = [], tl = null, lit = [], rendered = null, pending = null;
        var msPerBeat = 0, notes = [], grid = null, alignment = null;
        var versions = (options.versions && options.versions.length) ? options.versions
            : [{ role: options.role || '', empty: options.empty }];
        var chosen = 0;

        function current() { return versions[chosen]; }
        function readOnly() { return !!current().role; }
        function editable() { return !readOnly() && !!ctx.canEdit; }

        function text() {
            if (readOnly()) return String((ctx.reads() || {})[current().role] || '');
            var v = ctx.value();
            return typeof v === 'string' ? v : '';
        }

        if (versions.length > 1) {
            var pick = document.createElement('select');
            pick.className = 'form-select form-select-sm py-0 w-auto';
            pick.title = 'Partition : celle que la vue montre';
            pick.setAttribute('aria-label', 'Partition');
            versions.forEach(function (version, i) {
                var option = document.createElement('option');
                option.value = String(i);
                option.textContent = version.label || ('Partition ' + (i + 1));
                pick.appendChild(option);
            });
            pick.addEventListener('change', function () {
                chosen = Number(pick.value) || 0;
                rendered = null;
                render();
            });
            tools.insertBefore(pick, warn);
        }

        /** Le temps ÉCRIT (ms au tempo de la partition) qui sonne à l'instant `seconds` de l'axe. */
        function scoreMs(seconds) {
            if (alignment && sync.checked) return alignment.toScore(seconds) * msPerBeat;
            return seconds * 1000;
        }
        /** L'instant de l'axe (s) où sonne le temps écrit `ms`. */
        function axisSeconds(ms) {
            if (alignment && sync.checked) return alignment.toAudio(ms / msPerBeat);
            return ms / 1000;
        }

        function realign() {
            alignment = (grid && notes.length && msPerBeat) ? Score.align(notes, msPerBeat / 1000, grid) : null;
            sync.disabled = !alignment;
            if (alignment) {
                var first = notes[0].beat;
                syncText.textContent = ' Calée sur les temps joués';
                syncLabel.title = 'Chaque temps écrit est calé sur un temps joué de l’audio (1re note à ' +
                    Axis.formatTime(alignment.toAudio(first), true) + ', décalage ' + alignment.shift +
                    ' temps). Décocher : le tempo écrit seul.';
            } else {
                syncText.textContent = grid === false ? ' Tempo écrit (pas de grille de temps)'
                    : (grid ? ' Tempo écrit (calage impossible)' : ' Temps joués : calcul…');
                syncLabel.title = 'Le temps suit le tempo écrit de la partition (Q:).';
            }
        }

        function render() {
            pending = null;
            var abc = text();
            if (abc === rendered) return;
            rendered = abc;
            var top = body.scrollTop;
            lit = [];
            timings = [];
            notes = [];
            tl = null;
            if (!abc.trim() || !ABCJS) {
                paper.textContent = ABCJS ? (current().empty || options.empty || 'Partition vide.')
                    : 'Moteur de partition non chargé.';
                realign();
                return;
            }
            var tune = ABCJS.renderAbc(paper, abc, {
                add_classes: true, responsive: 'resize', selectTypes: ['note'],
                dragging: editable(), clickListener: onNote,
            })[0];
            // La séquence audio d'abcjs donne aux notes leurs hauteurs MIDI — de quoi les caler sur
            // ce qui sonne. Aucun son n'est produit.
            try { tune.setUpAudio({}); } catch (e) { /* hauteurs absentes : tempo écrit */ }
            try { timings = new ABCJS.TimingCallbacks(tune, {}).noteTimings || []; } catch (e) { timings = []; }
            try { msPerBeat = 60000 / tune.getBpm(); } catch (e) { msPerBeat = 0; }
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
            notes = msPerBeat ? Score.notesFromTimings(timings, msPerBeat) : [];
            var warnings = (tune && tune.warnings) || [];
            warn.classList.toggle('d-none', !warnings.length);
            warn.textContent = warnings.length + ' avert.';
            warn.title = warnings.map(function (w) { return String(w).replace(/<[^>]*>/g, ''); }).join('\n');
            realign();
            body.scrollTop = top;
            if (axis) paint(axis.time(), false);
        }

        function schedule() {
            if (pending) clearTimeout(pending);
            pending = setTimeout(render, RENDER_DELAY_MS);
        }

        function paint(seconds, follow) {
            var now = tl ? Score.playingAt(tl, scoreMs(seconds)) : [];
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
            if (drag && drag.step && editable()) {
                ctx.edit(function (v) { return Score.transposeAt(v, abcelem.startChar, abcelem.endChar, drag.step); });
                return;
            }
            var ms = Score.eventTime(timings, abcelem.startChar);
            if (ms != null && axis) axis.seek(axisSeconds(ms));
        }

        /** La grille des temps de l'audio, demandée à part : quelques secondes la 1re fois. */
        function loadGrid() {
            var role = options.media || 'audio';
            if (!(ctx.reads() || {})[role]) { grid = false; realign(); return; }
            fetch(ctx.config.data_url + '?only=rhythm&role=' + encodeURIComponent(role), { credentials: 'same-origin' })
                .then(App.jsonOrExplain)
                .then(function (res) { grid = (res && res.rhythm && res.rhythm.beats && res.rhythm.beats.length) ? res.rhythm : false; })
                .catch(function () { grid = false; })
                .then(function () { realign(); if (axis) paint(axis.time(), false); });
        }

        sync.addEventListener('change', function () { if (axis) paint(axis.time(), true); });
        if (axis) axis.subscribe(function (snap) { paint(snap.time, snap.playing || snap.reason === 'seek'); });
        // Un rendu refait (« Appliquer ») est un autre audio : sa grille se redemande — et une
        // partition LUE (lecture seule) a pu être réécrite par son process.
        ctx.on('redone', function () { grid = null; realign(); loadGrid(); if (readOnly()) schedule(); });
        ctx.on('processes', function () { if (readOnly() && text() !== rendered) schedule(); });

        render();
        loadGrid();
        var anyEdited = versions.some(function (version) { return !version.role; });
        return {
            refresh: function () { if (text() !== rendered) schedule(); },
            tools: tools,
            help: !anyEdited ? null
                : 'Partition : clic sur une note = y aller · glisser une note vers le haut ou le bas = la transposer d’un degré (Ctrl+Z annule) · les temps écrits sont calés sur les temps joués de l’audio'
                  + (versions.length > 1 ? ' · une partition LUE (choix « Partition ») ne se modifie pas ici' : ''),
        };
    }

    global.WamaSurface.registerBrick('score_view', { title: 'Partition', mount: mount });
})(window);
