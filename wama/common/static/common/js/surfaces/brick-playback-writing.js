/**
 * Brique `playback_writing` — ÉCRIRE PENDANT LA LECTURE : la lecture d'un média transcrit une suite
 * de segments (demande de Fabien du 2026-09-23, calquée sur les modes d'automation d'une station
 * audio). Un OUTIL DE DOMAINE abonné à l'axe partagé (2026-10-21, ROUTE §F3b, redécoupage décidé
 * par Fabien) : ce n'est ni du temps ni une vue, c'est un process qui agit sur la donnée pendant
 * qu'on écoute. Jusque-là une option du transport commun ; DÉPLACÉE telle quelle — même boucle,
 * mêmes gestes, parité attestée par le scénario `transcriber.editor_parity`.
 *
 * Quatre modes. Seul Complément ÉCRIT (il comble les blancs devant la tête de lecture) ; Touch (R
 * maintenu), Latch (R jusqu'à l'arrêt) et Write (toute la lecture) enregistrent des plages et
 * PROPOSENT un nouveau texte, qu'on écoute, accepte ou refuse. La boucle serveur est commune
 * (`playhead_follow`) : la brique pose le curseur que la boucle suit (route `write_cursor`) et lit
 * ses résultats (`write_results`) ; une plage acceptée remplace ce qui s'y disait par le recalage
 * commun (`retime`, `WamaSegments.applyRetime`). Les trois routes sont celles que la surface déclare.
 *
 * Les plages enregistrées et proposées se MARQUENT sur les vues du temps par le bus de la surface
 * (événement `bands`) : la brique ne connaît aucune vue.
 */
(function (global) {
    'use strict';

    var WRITE_SLICE = 20;             // une plage enregistrée se referme toutes les 20 s
    var COMPLEMENT_AHEAD = 20;        // Complément regarde 20 s devant la tête de lecture
    var WAIT_RESULTS_MS = 60000;
    var PROPOSAL_BAND = 'rgba(239,68,68,0.16)', RECORDING_BAND = 'rgba(239,68,68,0.32)';

    /** Le clavier est-il à une saisie ? La règle commune (`WamaApp.isTyping`). */
    function typing() { return global.WamaApp.isTyping(); }

    function mount(body, ctx) {
        var Seg = global.WamaSegments, Axis = global.WamaAxis;
        var axis = ctx.axis();
        var routes = ctx.config.routes || {};
        var segs = function () { var v = ctx.value(); return Array.isArray(v) ? v : []; };
        var edit = function (fn) { ctx.edit(fn); };
        var toast = function (m, k) { if (global.WamaApp && WamaApp.toast) WamaApp.toast(m, k); };
        body.classList.add('wama-brick-writing');

        var row = document.createElement('div');
        row.className = 'wama-writing-row';
        var writeSel = document.createElement('select');
        writeSel.className = 'form-select form-select-sm wama-writing-mode';
        writeSel.dataset.writing = 'mode';
        writeSel.title = "Mode d'écriture — la lecture transcrit : Complément remplit les blancs ; Touch (R maintenu), " +
                         "Latch (R jusqu'à l'arrêt) et Write (toute la lecture) proposent un nouveau texte.";
        [['', 'Lecture'], ['complement', 'Complément'], ['touch', 'Touch (R maintenu)'],
         ['latch', 'Latch (R)'], ['write', 'Write']].forEach(function (p) {
            var opt = document.createElement('option'); opt.value = p[0]; opt.textContent = p[1];
            writeSel.appendChild(opt);
        });
        var recBadge = document.createElement('span');
        recBadge.className = 'badge bg-danger d-none';
        recBadge.dataset.writing = 'rec';
        recBadge.title = 'Enregistrement : la plage jouée sera retranscrite';
        recBadge.textContent = '● REC';
        row.appendChild(writeSel);
        row.appendChild(recBadge);
        var proposalsHost = document.createElement('div');
        proposalsHost.className = 'write-proposals d-none';
        proposalsHost.dataset.writing = 'proposals';
        body.appendChild(row);
        body.appendChild(proposalsHost);

        var writeMode = '', armedAt = null, recorded = [], resultsNext = -1, proposals = [];
        var writeTimer = null, lastActivity = 0;

        /** Les plages à marquer sur les vues du temps : propositions, enregistrement en cours. */
        function showBands() {
            var bands = proposals.map(function (p) { return { start: p.start, end: p.end, color: PROPOSAL_BAND }; });
            if (armedAt != null) bands.push({ start: armedAt, end: null, color: RECORDING_BAND });
            ctx.emit('bands', { key: 'playback_writing', bands: bands });
        }
        function isPlaying() { return axis.playing() && axis.rate() > 0; }
        function arm() { if (armedAt == null && isPlaying()) { armedAt = axis.time(); renderRec(); } }
        function disarm() {
            if (armedAt == null) return;
            var end = axis.time();
            if (end - armedAt >= 0.5) { recorded.push([armedAt, end]); lastActivity = Date.now(); }
            armedAt = null; renderRec();
        }
        function renderRec() { recBadge.classList.toggle('d-none', armedAt == null); showBands(); }
        function wantedRanges() {
            if (writeMode === 'complement') {
                var t = axis.time(), lo = Math.max(0, t - 1), hi = t + COMPLEMENT_AHEAD;
                var empty = segs().filter(function (s) { return !(s.text || '').trim(); })
                    .map(function (s) { return [s.start_time || 0, s.end_time || 0]; });
                return Seg.gaps(segs(), axis.duration()).concat(empty)
                    .map(function (r) { return [Math.max(r[0], lo), Math.min(r[1], hi)]; })
                    .filter(function (r) { return r[1] - r[0] >= 1; });
            }
            return recorded.slice(-50);
        }
        function post(url, payload) {
            var App = global.WamaApp || {};
            return App.csrfFetch(url, App.csrfToken(), {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
            });
        }
        function postWriteCursor(enabled) {
            if (!routes.write_cursor) return Promise.resolve();
            var payload = enabled ? { mode: writeMode, t: axis.time(), wanted: wantedRanges() } : { enabled: false };
            return post(routes.write_cursor, payload).catch(function () {});
        }
        function pollWriteResults() {
            if (!routes.write_results) return;
            fetch(routes.write_results + '?since=' + resultsNext, { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var fresh = resultsNext < 0 ? [] : (d.results || []);
                    resultsNext = d.next || 0;
                    fresh.forEach(function (res) {
                        lastActivity = Date.now();
                        recorded = recorded.filter(function (r) { return r[1] <= res.start || r[0] >= res.end; });
                        if (!res.words || !res.words.length) return;          // rien entendu : rien à écrire
                        if (res.mode === 'complement') applySpan(res);         // comble du vide : direct
                        else { proposals.push(res); renderProposals(); }
                    });
                })
                .catch(function () {});
        }
        function writeTick() {
            if (!writeMode) return;
            if (writeMode === 'write') { if (isPlaying()) arm(); else disarm(); }
            if (armedAt != null && axis.time() - armedAt >= WRITE_SLICE) { disarm(); arm(); }
            var waiting = recorded.length && Date.now() - lastActivity < WAIT_RESULTS_MS;
            if (isPlaying() || waiting) postWriteCursor(true);
            pollWriteResults();
        }
        function setWriteMode(mode) {
            if (armedAt != null) disarm();
            var was = writeMode;
            writeMode = mode || '';
            if (writeMode && !writeTimer) writeTimer = setInterval(writeTick, 1000);
            if (!writeMode) {
                if (writeTimer) { clearInterval(writeTimer); writeTimer = null; }
                recorded = [];
                if (was) postWriteCursor(false);
            }
            if (resultsNext < 0) pollWriteResults();
            if (writeSel.value !== writeMode) writeSel.value = writeMode;
        }
        /** Une plage transcrite remplace ce qui s'y disait, ou remplit un blanc (`replace_span`). */
        function applySpan(res) {
            var s = segs(), span = Seg.spanOf(s, res.start, res.end);
            var neighbour = s[span.first] || s[span.first - 1];
            return Seg.applyRetime({ url: routes.retime, segments: s, first: span.first, count: span.count,
                                     body: { op: 'replace', start: res.start, end: res.end, words: res.words,
                                             speaker_id: neighbour ? (neighbour.speaker_id || '') : '' },
                                     edit: edit, toast: toast });
        }
        function renderProposals() {
            proposalsHost.classList.toggle('d-none', !proposals.length);
            var fmt = Axis.formatTime;
            proposalsHost.innerHTML = proposals.map(function (p) {
                return '<div class="wp-item" data-id="' + p.id + '">' +
                    '<span class="wp-time">' + fmt(p.start) + '–' + fmt(p.end) + '</span>' +
                    '<span class="wp-text" title="' + global.WamaApp.escapeHtml(p.text) + '">' + global.WamaApp.escapeHtml(p.text) + '</span>' +
                    '<button class="btn btn-sm btn-success py-0 px-2 wp-accept" title="Remplacer le texte de cette plage">' +
                    '<i class="fas fa-check"></i></button>' +
                    '<button class="btn btn-sm btn-outline-secondary py-0 px-2 wp-reject" title="Garder le texte actuel">' +
                    '<i class="fas fa-xmark"></i></button></div>';
            }).join('');
            showBands();
        }
        function dropProposal(id) {
            proposals = proposals.filter(function (p) { return p.id !== id; });
            renderProposals();
        }
        writeSel.addEventListener('change', function () { setWriteMode(writeSel.value); writeSel.blur(); });
        proposalsHost.addEventListener('click', function (e) {
            var item = e.target.closest('.wp-item'); if (!item) return;
            var id = parseInt(item.dataset.id, 10);
            var p = proposals.filter(function (x) { return x.id === id; })[0]; if (!p) return;
            if (e.target.closest('.wp-accept')) applySpan(p).then(function (ok) { if (ok) dropProposal(id); });
            else if (e.target.closest('.wp-reject')) dropProposal(id);
            else axis.playFrom(p.start);                                     // écouter
        });
        // L'arrêt de la lecture AVANT (pause, fin, passage en arrière) referme la plage.
        axis.subscribe(function (st) { if (!(st.playing && st.rate > 0)) disarm(); });

        // ── Clavier : R (Touch / Latch) ; Échap rend le clavier quand il est à la brique ──────
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                if (!e.defaultPrevented && typing() && body.contains(document.activeElement)) {
                    e.preventDefault(); document.activeElement.blur();
                }
                return;
            }
            if (typing() || e.ctrlKey || e.metaKey || e.altKey) return;
            if ((e.key || '').toLowerCase() === 'r' && (writeMode === 'touch' || writeMode === 'latch')) {
                e.preventDefault(); if (!e.repeat) arm();
            }
        });
        document.addEventListener('keyup', function (e) {           // Touch : relâcher R ferme la plage
            if (writeMode === 'touch' && (e.key || '').toLowerCase() === 'r') disarm();
        });

        return {
            help: "Écriture à la lecture : R = enregistrer (Touch : maintenu ; Latch : jusqu'à l'arrêt) · " +
                  'une proposition se clique pour l’écouter, ✓ remplace la plage, ✗ la refuse',
        };
    }

    global.WamaSurface.registerBrick('playback_writing', { title: 'Écriture à la lecture', mount: mount });
})(window);
