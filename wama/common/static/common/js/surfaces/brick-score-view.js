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
 * une partition. Une version qui nomme un `field` (un `also_edits` de la surface) se CORRIGE comme
 * la principale : choisie, elle devient la valeur éditée (`ctx.retarget`).
 *
 * LE CLAVIER (2026-10-22, demande de Fabien : « hauteur et rythme, l'essentiel de l'édition ») : un
 * clic CHOISIT une note (et y amène la lecture) ; puis ↑ ↓ la montent ou la descendent d'un degré,
 * ← → la décalent d'un pas dans le temps, + − l'allongent ou la raccourcissent d'un pas — la
 * mesure garde sa durée (`WamaScore.retime`), Échap la quitte. Chaque touche est UN geste
 * (`ctx.edit`, Ctrl+Z l'annule). Le PAS est automatique (la plus petite durée écrite de la
 * mesure) tant qu'on n'en FORCE pas un — choix « Pas », ou les chiffres 2 à 7 comme MuseScore
 * (5 = noire), 0 = automatique ; gardé par le navigateur du lecteur.
 *
 * EXPORTER (même jour) : la partition MONTRÉE, telle qu'elle est à l'écran (modifications non
 * enregistrées comprises), en ABC, en MIDI (abcjs, `synth.getMidiFile`) — le format que lisent
 * MuseScore, Guitar Pro et les séquenceurs — ou en PDF (la gravure imprimée, « Enregistrer en
 * PDF » du navigateur).
 */
(function (global) {
    'use strict';

    var RENDER_DELAY_MS = 250;
    var PLAYING = 'wama-score-playing';
    /** Touche → geste rythmique (`WamaScore.retime`). `=` : le + sans Maj d'un clavier français. */
    var RETIME_KEYS = { ArrowLeft: 'left', ArrowRight: 'right', '+': 'longer', '=': 'longer',
                        '-': 'shorter' };
    /** Le PAS des gestes rythmiques (2026-10-22, Fabien : « forcer une rythmique précise ») : le
     *  dénominateur de la figure (4 = la noire) ; '' = automatique, le défaut. */
    var STEPS = [['', 'Pas : auto'], ['1', 'Pas : ronde'], ['2', 'Pas : blanche'], ['4', 'Pas : noire'],
                 ['8', 'Pas : croche'], ['16', 'Pas : double croche'], ['32', 'Pas : triple croche']];
    /** Chiffres → pas : la convention de MuseScore (vers qui on exporte), le chiffre monte avec la
     *  durée ; 0 rend l'automatique. */
    var STEP_KEYS = { '0': '', '2': '32', '3': '16', '4': '8', '5': '4', '6': '2', '7': '1' };
    var STEP_STORE = 'wama.score.step';           // un confort du lecteur : son dernier pas

    function readStep() {
        var v = '';
        try { v = localStorage.getItem(STEP_STORE) || ''; } catch (e) { v = ''; }
        return STEPS.some(function (s) { return s[0] === v; }) ? v : '';
    }
    function writeStep(v) { try { localStorage.setItem(STEP_STORE, v); } catch (e) { /* sans stockage */ } }

    /** Télécharge `data` sous `name` — un lien jetable, sans aller-retour serveur. */
    function download(data, type, name) {
        var url = URL.createObjectURL(new Blob([data], { type: type }));
        var a = document.createElement('a');
        a.href = url;
        a.download = name;
        document.body.appendChild(a);
        a.click();
        a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
    }

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

        var timings = [], tl = null, lit = [], rendered = null, pending = null, tune = null;
        var msPerBeat = 0, notes = [], grid = null, alignment = null;
        var versions = (options.versions && options.versions.length) ? options.versions
            : [{ role: options.role || '', empty: options.empty }];
        var chosen = 0;
        /** La note CHOISIE (`[start, end)` dans le texte) : ce que le clavier modifie. */
        var selection = null;

        function current() { return versions[chosen]; }
        function readOnly() { return !!current().role; }
        function editable() { return !readOnly() && !!ctx.canEdit && !!text().trim(); }

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
                var next = Number(pick.value) || 0, version = versions[next];
                // Une version ÉDITÉE (sans `role`) devient la valeur de la page : ce qui est en
                // cours s'enregistre d'abord (`ctx.retarget`).
                var ready = version.role || !ctx.retarget ? Promise.resolve(true)
                    : ctx.retarget(version.field || '');
                pick.disabled = true;
                ready.then(function (ok) {
                    pick.disabled = false;
                    if (!ok) { pick.value = String(chosen); return; }
                    chosen = next;
                    selection = null;
                    rendered = null;
                    render();
                });
            });
            tools.insertBefore(pick, warn);
        }

        // ── Le pas des gestes rythmiques ────────────────────────────────────────────────────
        var step = readStep();
        var stepPick = document.createElement('select');
        stepPick.className = 'form-select form-select-sm py-0 w-auto';
        stepPick.title = 'Pas des gestes ← → + − : automatique (la plus petite durée écrite de la ' +
            'mesure) ou une figure — chiffres 2 à 7 (comme MuseScore), 0 = automatique';
        stepPick.setAttribute('aria-label', 'Pas');
        STEPS.forEach(function (s) {
            var option = document.createElement('option');
            option.value = s[0];
            option.textContent = s[1];
            stepPick.appendChild(option);
        });
        stepPick.value = step;
        function setStep(v) {
            step = v;
            stepPick.value = v;
            writeStep(v);
            ctx.status(STEPS.filter(function (s) { return s[0] === v; })[0][1], '');
        }
        stepPick.addEventListener('change', function () { setStep(stepPick.value); });
        tools.insertBefore(stepPick, warn);

        // ── Exporter la partition montrée ───────────────────────────────────────────────────
        var exporter = document.createElement('select');
        exporter.className = 'form-select form-select-sm py-0 w-auto';
        exporter.title = 'Exporter la partition montrée (modifications non enregistrées comprises)';
        exporter.setAttribute('aria-label', 'Exporter');
        [['', 'Exporter…'], ['mid', 'MIDI'], ['pdf', 'PDF (impression)'], ['abc', 'ABC']].forEach(function (o) {
            var option = document.createElement('option');
            option.value = o[0];
            option.textContent = o[1];
            exporter.appendChild(option);
        });
        exporter.addEventListener('change', function () {
            var kind = exporter.value;
            exporter.value = '';
            if (kind) exportAs(kind);
        });
        tools.insertBefore(exporter, warn);

        function baseName() {
            var label = (current().label || 'partition').toLowerCase()
                .normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9]+/g, '-');
            return 'partition-' + (ctx.config.pk || '') + '-' + label;
        }

        function exportAs(kind) {
            var abc = text();
            if (!abc.trim()) { ctx.status('Rien à exporter : la partition est vide.', 'error'); return; }
            if (kind === 'abc') { download(abc, 'text/vnd.abc;charset=utf-8', baseName() + '.abc'); return; }
            if (kind === 'mid') {
                var midi = null;
                try { midi = ABCJS.synth.getMidiFile(tune || abc, { midiOutputType: 'binary' }); }
                catch (e) { midi = null; }
                if (Array.isArray(midi)) midi = midi[0];
                if (!midi || !midi.length) { ctx.status('Export MIDI impossible pour cette partition.', 'error'); return; }
                download(midi, 'audio/midi', baseName() + '.mid');
                return;
            }
            if (kind === 'pdf') printScore(abc);
        }

        /** La gravure, sans couleurs de lecture ni de choix, dans une fenêtre d'impression : le
         *  navigateur propose « Enregistrer en PDF ». */
        function printScore(abc) {
            var sheet = document.createElement('div');
            sheet.style.cssText = 'position:absolute;left:-10000px;top:0;width:760px';
            document.body.appendChild(sheet);
            // Un SVG par système : la page se coupe entre deux systèmes, jamais au milieu.
            try { ABCJS.renderAbc(sheet, abc, { staffwidth: 720, oneSvgPerLine: true }); } catch (e) { /* vide */ }
            var svg = sheet.innerHTML;
            sheet.remove();
            var w = global.open('', '_blank');
            if (!w) { ctx.status('Fenêtre d’impression bloquée par le navigateur.', 'error'); return; }
            w.document.write('<!doctype html><html><head><meta charset="utf-8"><title>' +
                baseName() + '</title><style>body{margin:12mm;background:#fff;color:#000}' +
                'svg{width:100%;height:auto;page-break-inside:avoid}</style></head><body>' +
                svg + '</body></html>');
            w.document.close();
            w.focus();
            setTimeout(function () { w.print(); }, 300);
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
            tune = null;
            if (!abc.trim() || !ABCJS) {
                paper.textContent = ABCJS ? (current().empty || options.empty || 'Partition vide.')
                    : 'Moteur de partition non chargé.';
                realign();
                return;
            }
            tune = ABCJS.renderAbc(paper, abc, {
                add_classes: true, responsive: 'resize', selectTypes: ['note'],
                dragging: editable(), clickListener: onNote,
            })[0];
            highlight();
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
                transpose(abcelem.startChar, abcelem.endChar, drag.step);
                return;
            }
            selection = { start: abcelem.startChar, end: abcelem.endChar };
            highlight();
            // Le clavier s'adresse à la brique : sans voler le défilement de la page.
            try { body.focus({ preventScroll: true }); } catch (e) { body.focus(); }
            var ms = Score.eventTime(timings, abcelem.startChar);
            if (ms != null && axis) axis.seek(axisSeconds(ms));
        }

        /** La note choisie, surlignée par abcjs (`rangeHighlight`) — refait après chaque gravure. */
        function highlight() {
            if (!tune || !tune.engraver || !tune.engraver.rangeHighlight) return;
            try { tune.engraver.rangeHighlight(selection ? selection.start : -1, selection ? selection.end : -1); }
            catch (e) { /* gravure en cours de remplacement */ }
        }

        /** ↑ ↓ (ou le glisser d'abcjs) : `step` degrés VERS LE BAS — la note garde sa place choisie. */
        function transpose(start, end, step) {
            ctx.edit(function (v) {
                var out = Score.transposeAt(v, start, end, step);
                if (selection && selection.start === start) selection.end = end + (out.length - v.length);
                return out;
            });
        }

        /** ← → + − : un geste refusé (la mesure ne le permet pas) ne fait pas de cran, il se dit. */
        function retime(op) {
            var r = Score.retime(text(), selection.start, op, step ? 1 / Number(step) : undefined);
            if (r.error) { ctx.status(r.error, 'error'); return; }
            selection = { start: r.start, end: r.end };
            ctx.edit(function () { return r.abc; });
        }

        // CAPTURE : la brique lit la touche AVANT la note gravée — abcjs, dont les notes glissables
        // écoutent elles-mêmes ↑ ↓, la transposerait une seconde fois.
        body.tabIndex = 0;
        body.addEventListener('keydown', function (e) {
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            // Une touche dans une saisie (la source ABC, un choix de la poignée) n'est pas un geste
            // sur la note : la règle commune des briques du temps (`WamaApp.isTyping`).
            if (App.isTyping && App.isTyping()) return;
            if (e.key === 'Escape' && selection) { selection = null; highlight(); return; }
            if (STEP_KEYS.hasOwnProperty(e.key)) {
                setStep(STEP_KEYS[e.key]);
                e.preventDefault();
                e.stopPropagation();
                return;
            }
            if (!selection || !editable()) return;
            var op = RETIME_KEYS[e.key];
            if (e.key === 'ArrowUp' || e.key === 'ArrowDown') {
                transpose(selection.start, selection.end, e.key === 'ArrowUp' ? -1 : 1);
            } else if (op) {
                retime(op);
            } else {
                return;
            }
            e.preventDefault();
            e.stopPropagation();
        }, true);

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
        // Annuler / rétablir peut rendre un texte où la note choisie n'est plus à sa place.
        ctx.on('change', function () { if (selection && selection.end > text().length) selection = null; });

        render();
        loadGrid();
        var anyEdited = versions.some(function (version) { return !version.role; });
        return {
            refresh: function () { if (text() !== rendered) schedule(); },
            tools: tools,
            // Ses touches sont déclarées au registre (`score_view.shortcuts`) ; une partition
            // seulement LUE les tait (rien à y modifier).
            keys: anyEdited,
            help: !anyEdited ? null
                : 'Partition : clic sur une note = la choisir et y aller · la glisser = la monter / descendre · le pas : choix « Pas » · « Exporter » : MIDI, PDF, ABC'
                  + (versions.some(function (v) { return v.role; }) ? ' · une partition LUE ne se modifie pas ici' : ''),
        };
    }

    global.WamaSurface.registerBrick('score_view', { title: 'Partition', mount: mount });
})(window);
