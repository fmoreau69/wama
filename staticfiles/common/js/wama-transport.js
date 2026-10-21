/**
 * wama-transport.js — le TRANSPORT média COMMUN (2026-10-21, ROUTE §F3b « transport commun »).
 *
 * Décision de Fabien (2026-10-21) : *« le transport commun avec le transport de preview et le
 * monde Data — tout dans la même brique, par options »*. Ce module est ce transport, montable
 * PARTOUT (`WamaTransport.mount(hôte, cfg)`) : la brique de surface `media_transport` n'en est
 * que l'enveloppe ; l'aperçu (visionneuse, surcouches) et le magnéto du monde Data
 * (`WAMA_DATA_WORLD §5bis`) le monteront à leur tour.
 *
 * Il PILOTE un axe (`wama-axis.js`) et ne réécrit aucun lecteur : le média est attaché par le
 * lecteur commun (`WamaAudioPlayer` — lecture exclusive, position reposée), J/K/L sont ceux de
 * `WamaShuttle`, l'arrière silencieux celui de l'axe. Ses vues s'ABONNENT à l'axe.
 *
 * Options (toutes facultatives ; sans elles, le magnéto de la partition du composer) :
 *   jump        saut des boutons et de ←/→ (5 s)            height  hauteur de l'onde du lecteur
 *   speed       'select' (liste de vitesses) | 'steps' (− / valeur / +, de 0,5 à 2 par 0,25)
 *   goto        champ « aller à » (m:ss, h:mm:ss, virgule admise)
 *   window      onde FENÊTRÉE sur pics fins (zoom de 4 s à la durée, molette, glisser, pincer)
 *   zoom        boutons de zoom de l'onde fenêtrée
 *   segments    couches des segments sur l'onde : repères, silences hachurés
 *   quality     bande de qualité des segments (clic = écouter)    minimap  vue d'ensemble
 *   boundaries  'retime' : outil Bornes (glisser une borne, couper, créer dans un silence ; C)
 *   writing     modes d'écriture : la lecture transcrit (Complément, Touch / Latch avec R, Write)
 * Ce qui vient de la page (`cfg`) : `axis`, `player` + `playerId`, `segments()` (la suite montrée),
 * `edit(fn)` (un geste de structure), `select(i, {focus})`, `routes` (`retime`, `write_cursor`,
 * `write_results`), `densePeaks(poll)` (promesse des pics fins).
 *
 * Les gestes de la fenêtre et de ses couches ont été DÉPLACÉS de la page de correction du
 * transcriber (`edit.js`, R166) — même calcul, même rendu ; parité attestée par le scénario
 * `transcriber.editor_parity`, joué sur l'ancienne page puis sur la surface.
 */
(function (global) {
    'use strict';

    var RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
    var SPEED_MIN = 0.5, SPEED_MAX = 2, SPEED_STEP = 0.25;
    var MIN_VIEW = 4;                 // zoom max : une fenêtre de 4 s
    var DEFAULT_VIEW = 240;           // fenêtre d'ouverture : l'onde se voit d'emblée
    var LEGIBLE_PXPS = 1.5;           // en dessous, l'onde se tait (la minimap fait la vue d'ensemble)
    var HANDLE_PX = 6, HANDLE_PX_TOUCH = 16;
    var WRITE_SLICE = 20;             // une plage enregistrée se referme toutes les 20 s
    var COMPLEMENT_AHEAD = 20;        // Complément regarde 20 s devant la tête de lecture
    var WAIT_RESULTS_MS = 60000;
    var PEAKS_POLL_MS = 2500;

    /** Le libellé de la vitesse — UN pour tout WAMA : la vitesse choisie, ou le cran du shuttle. */
    function speedLabel(st) {
        if (st.shuttling) return (st.rate > 0 ? '▶▶ ' + st.rate : '◀◀ ' + (-st.rate)) + '×';
        return st.speed.toFixed(2).replace(/0$/, '') + '×';
    }

    function esc(t) {
        var d = document.createElement('div'); d.textContent = t == null ? '' : t;
        return d.innerHTML;
    }

    function el(tag, cls, attrs) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        return e;
    }

    function button(name, icon, title, text) {
        var b = el('button', 'btn btn-sm btn-outline-emphasis', { type: 'button', 'data-transport': name, title: title });
        b.innerHTML = (icon ? '<i class="fas ' + icon + '"></i>' : '') + (text ? ' ' + text : '');
        return b;
    }

    /** Le clavier est-il à une saisie ? (le magnéto s'efface alors de lui-même) */
    function typing() {
        var a = document.activeElement;
        if (!a) return false;
        return a.tagName === 'INPUT' || a.tagName === 'TEXTAREA' || a.tagName === 'SELECT' || !!a.isContentEditable;
    }

    function mount(host, cfg) {
        cfg = cfg || {};
        var o = cfg.options || {};
        // Le lecteur que la page donne (le lecteur commun, `WamaAudioPlayer`, par défaut).
        var Player = cfg.player || global.WamaAudioPlayer, Axis = global.WamaAxis, Seg = global.WamaSegments;
        var axis = cfg.axis;
        var jump = Number(o.jump) || 5;
        var routes = cfg.routes || {};
        var segs = function () { var s = cfg.segments ? cfg.segments() : null; return Array.isArray(s) ? s : []; };
        var edit = cfg.edit || function () {};
        var select = cfg.select || function () {};
        var toast = function (m, k) { if (global.WamaApp && WamaApp.toast) WamaApp.toast(m, k); };
        host.classList.add('wama-transport');

        // ── Le lecteur commun (son onde, cachée sous une onde fenêtrée) ────────────────────
        var playerHost = el('div', 'wama-transport-wave');
        host.appendChild(playerHost);
        if (o.window) playerHost.classList.add('wama-transport-player-hidden');

        // ── Onde fenêtrée, bande de qualité, minimap ────────────────────────────────────────
        var cv = null, heat = null, mini = null;
        if (o.window) {
            cv = el('canvas', 'zoom-wave', { 'data-transport': 'wave',
                title: "Forme d'onde — clic : placer · glisser : déplacer · molette : zoom" });
            host.appendChild(cv);
        }
        if (o.quality) {
            heat = el('div', 'seg-heatmap', { 'data-transport': 'heat', title: 'Qualité par segment — cliquez pour écouter' });
            host.appendChild(heat);
        }
        if (o.minimap) {
            mini = el('canvas', 'zoom-mini', { 'data-transport': 'mini', title: "Vue d'ensemble — cliquez/glissez pour vous déplacer" });
            host.appendChild(mini);
        }

        // ── La rangée de commandes ──────────────────────────────────────────────────────────
        var bar = el('div', 'wama-transport-bar');
        var toStart = button('start', 'fa-backward-step', 'Début (Début)');
        var back = button('skip-back', o.speed === 'steps' ? 'fa-backward' : 'fa-rotate-left',
                          'Reculer ' + jump + ' s (←)', o.speed === 'steps' ? jump + 's' : '');
        var play = button('play', 'fa-play', 'Lecture / pause (Espace)');
        var fwd = button('skip-fwd', '', 'Avancer ' + jump + ' s (→)',
                         o.speed === 'steps' ? jump + 's <i class="fas fa-forward"></i>' : '<i class="fas fa-rotate-right"></i>');
        var clock = el('span', 'wama-transport-clock', { 'data-transport': 'clock' });
        [toStart, back, play, fwd].forEach(function (b) { bar.appendChild(b); });

        var rate = null, speedLabelEl = null, shuttleOpt = null;
        if (o.speed === 'steps') {
            var down = button('speed-down', 'fa-minus', 'Ralentir');
            speedLabelEl = el('span', 'badge bg-secondary wama-transport-speed', { 'data-transport': 'speed-label' });
            var up = button('speed-up', 'fa-plus', 'Accélérer');
            var bump = function (d) {
                axis.setSpeed(Math.max(SPEED_MIN, Math.min(SPEED_MAX, Math.round((axis.speed() + d) * 100) / 100)));
            };
            down.addEventListener('click', function () { bump(-SPEED_STEP); });
            up.addEventListener('click', function () { bump(SPEED_STEP); });
            bar.appendChild(el('span', 'text-body-secondary ms-2')).innerHTML = '<i class="fas fa-gauge-high"></i>';
            [down, speedLabelEl, up].forEach(function (b) { bar.appendChild(b); });
        } else {
            rate = el('select', 'form-select form-select-sm wama-transport-rate', { 'data-transport': 'rate', title: 'Vitesse de lecture' });
            RATES.forEach(function (r) {
                var opt = document.createElement('option');
                opt.value = String(r); opt.textContent = '×' + r;
                rate.appendChild(opt);
            });
            shuttleOpt = document.createElement('option');
            shuttleOpt.hidden = true;
            rate.appendChild(shuttleOpt);
            bar.appendChild(rate);
        }
        bar.appendChild(clock);

        var gotoInp = null;
        if (o.goto) {
            gotoInp = el('input', 'form-control form-control-sm wama-transport-goto',
                         { type: 'text', 'data-transport': 'goto', placeholder: 'mm:ss',
                           title: 'Aller à un timecode (mm:ss ou hh:mm:ss) — Entrée' });
            var gotoBtn = button('goto-btn', 'fa-arrow-right-to-bracket', 'Aller au timecode');
            bar.appendChild(el('span', 'text-body-secondary ms-2')).innerHTML = '<i class="fas fa-clock"></i>';
            bar.appendChild(gotoInp);
            bar.appendChild(gotoBtn);
            gotoBtn.addEventListener('click', function () { gotoTimecode(); });
            gotoInp.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); gotoTimecode(); }
            });
        }
        var zoomLabel = null;
        if (o.window && o.zoom) {
            var zout = button('zoom-out', 'fa-minus', 'Dézoomer');
            zoomLabel = el('span', 'badge bg-secondary wama-transport-zoom', { 'data-transport': 'zoom-label' });
            var zin = button('zoom-in', 'fa-plus', 'Zoomer');
            bar.appendChild(el('span', 'text-body-secondary ms-2')).innerHTML = '<i class="fas fa-magnifying-glass"></i>';
            [zout, zoomLabel, zin].forEach(function (b) { bar.appendChild(b); });
            zin.addEventListener('click', function () { setZoom(viewDur * 0.6); });
            zout.addEventListener('click', function () { setZoom(viewDur * 1.7); });
        }
        var toolBtn = null;
        if (o.window && o.boundaries) {
            toolBtn = button('boundaries', 'fa-scissors',
                'Outil Bornes (C) — glisser une borne pour la déplacer · cliquer dans une section pour la couper · Échap pour sortir',
                'Bornes');
            toolBtn.setAttribute('aria-pressed', 'false');
            toolBtn.classList.add('ms-2');
            bar.appendChild(toolBtn);
            toolBtn.addEventListener('click', function () { setBoundaryTool(!boundaryTool); });
        }
        var writeSel = null, recBadge = null, proposalsHost = null;
        if (o.writing) {
            writeSel = el('select', 'form-select form-select-sm ms-2 wama-transport-write', { 'data-transport': 'write-mode',
                title: "Mode d'écriture — la lecture transcrit : Complément remplit les blancs ; Touch (R maintenu), " +
                       "Latch (R jusqu'à l'arrêt) et Write (toute la lecture) proposent un nouveau texte." });
            [['', 'Lecture'], ['complement', 'Complément'], ['touch', 'Touch (R maintenu)'],
             ['latch', 'Latch (R)'], ['write', 'Write']].forEach(function (p) {
                var opt = document.createElement('option'); opt.value = p[0]; opt.textContent = p[1];
                writeSel.appendChild(opt);
            });
            recBadge = el('span', 'badge bg-danger d-none', { 'data-transport': 'rec', title: 'Enregistrement : la plage jouée sera retranscrite' });
            recBadge.textContent = '● REC';
            bar.appendChild(writeSel);
            bar.appendChild(recBadge);
        }
        host.appendChild(bar);
        if (o.writing) {
            proposalsHost = el('div', 'write-proposals d-none', { 'data-transport': 'proposals' });
            host.appendChild(proposalsHost);
        }

        // ── Le média ────────────────────────────────────────────────────────────────────────
        var source = '';
        function load(url, serverPeaks, bust) {
            source = url || '';
            if (!url) {
                if (Player) Player.destroy(cfg.playerId);
                playerHost.textContent = 'Aucun média à lire pour l’instant.';
                return;
            }
            if (!Player || !axis) { playerHost.textContent = 'Lecteur commun indisponible.'; return; }
            var keep = axis.time();
            axis.pause();
            axis.detach();
            playerHost.textContent = '';
            var full = bust ? url + (url.indexOf('?') < 0 ? '?' : '&') + 'v=' + Date.now() : url;
            Player.inject(full, cfg.playerId, playerHost, { height: Number(o.height) || 64 });
            // Les pics d'abord : le lecteur dessine l'onde SANS télécharger un long fichier.
            if (serverPeaks && serverPeaks.peaks) Player.setPeaks(cfg.playerId, serverPeaks.peaks);
            var media = Player.getAudio(cfg.playerId);
            if (!media) return;
            if (serverPeaks && serverPeaks.duration) axis.setDuration(serverPeaks.duration);
            // Le média joue et se positionne par le lecteur commun : sa lecture EXCLUSIVE, et sa
            // position reposée quand le fichier devient positionnable — l'axe ne les refait pas.
            axis.attach(media, {
                offset: Number(o.offset) || 0,
                play: function () { return Player.play(cfg.playerId); },
                seek: function (t) { Player.seek(cfg.playerId, t, false); },
            });
            if (keep) axis.seek(keep);
            if (o.window) fetchPeaks(false);
        }

        var shuttle = global.WamaShuttle ? global.WamaShuttle.create({
            apply: function (level) { axis.shuttle(level); },
        }) : null;

        /** Lire depuis `t` (bande de qualité, proposition) : le shuttle se rend d'abord. */
        function playFrom(t) {
            if (axis.shuttling()) axis.shuttle(0);
            axis.seek(t);
            axis.play();
        }

        toStart.addEventListener('click', function () { axis.seek(0); });
        back.addEventListener('click', function () { axis.jump(-jump); });
        fwd.addEventListener('click', function () { axis.jump(jump); });
        play.addEventListener('click', function () { axis.toggle(); });
        if (rate) rate.addEventListener('change', function () {
            if (shuttle) shuttle.reset();
            axis.setRate(Number(rate.value) || 1);
        });
        if (axis) axis.bindKeys({ jump: jump, shuttle: shuttle });

        // ── Fenêtre de l'onde ───────────────────────────────────────────────────────────────
        var peaks = null, peaksDur = 0, peaksReady = !o.window;
        var viewStart = 0, viewDur = 0;
        function fullDur() { return axis.duration() || peaksDur || 0; }
        function clampView() {
            var D = fullDur(); if (!D) return;
            if (!viewDur || viewDur > D) viewDur = D;
            viewDur = Math.max(MIN_VIEW, Math.min(D, viewDur));
            viewStart = Math.max(0, Math.min(D - viewDur, viewStart));
        }
        function updateZoomLabel() {
            if (!zoomLabel) return;
            var D = fullDur();
            zoomLabel.textContent = (D && viewDur) ? ('×' + (D / viewDur).toFixed(1)) : '×1';
        }

        function fetchPeaks(poll) {
            if (!cfg.densePeaks) { peaksReady = true; return; }
            cfg.densePeaks(poll).then(function (d) {
                if (d.status === 'ready' && d.peaks) {
                    peaks = d.peaks; peaksDur = d.duration || 0; peaksReady = true; redrawWindow();
                } else if (d.status === 'pending') {
                    setTimeout(function () { fetchPeaks(true); }, PEAKS_POLL_MS);
                } else { peaksReady = true; redrawWindow(); }   // échec : ni onde ni attente, les couches restent
            }).catch(function () { peaksReady = true; });
        }

        // ── Outil « Bornes » (décisions de Fabien du 2026-09-23 : une borne par jonction, deux
        // gestes, jamais un mot coupé ni perdu ; le calcul est serveur, `WamaSegments.retime`) ──
        var boundaryTool = false, boundaryDrag = null, hoverT = null, hoverHandle = -1, retiming = false;
        var dragging = false, hatch = null;
        function hatchPattern(ctx) {
            if (hatch) return hatch;
            var c = document.createElement('canvas'); c.width = c.height = 6;
            var g = c.getContext('2d');
            g.strokeStyle = 'rgba(255,255,255,0.16)'; g.lineWidth = 1;
            g.beginPath(); g.moveTo(0, 6); g.lineTo(6, 0); g.stroke();
            hatch = ctx.createPattern(c, 'repeat');
            return hatch;
        }
        function handleAt(px, W, reach) {
            var s = segs(), best = -1, bestD = (reach || HANDLE_PX) + 1;
            for (var i = 1; i < s.length; i++) {
                var d = Math.abs(((s[i].start_time || 0) - viewStart) / viewDur * W - px);
                if (d < bestD) { bestD = d; best = i; }
            }
            return best;
        }
        function setBoundaryTool(on) {
            boundaryTool = !!on; boundaryDrag = null; hoverT = null; hoverHandle = -1;
            if (toolBtn) {
                toolBtn.classList.toggle('btn-warning', boundaryTool);
                toolBtn.classList.toggle('btn-outline-emphasis', !boundaryTool);
                toolBtn.setAttribute('aria-pressed', boundaryTool ? 'true' : 'false');
            }
            if (cv) cv.style.cursor = boundaryTool ? 'crosshair' : '';
            drawZoom();
        }
        /** Un geste de borne, un à la fois : remplacé par ce que rend le serveur, après confirmation. */
        function settle(promise) {
            retiming = true;
            return promise.then(function () { retiming = false; boundaryDrag = null; drawZoom(); });
        }
        /** Déplace la jonction `i` (entre `i - 1` et `i`) à `t`. */
        function moveBoundary(i, t) {
            if (retiming || !routes.retime) return;
            settle(Seg.applyRetime({ url: routes.retime, segments: segs(), first: i - 1, count: 2,
                                     body: { op: 'move', time: t }, edit: edit, select: select,
                                     selectAt: i - 1, toast: toast }));
        }
        /** Ciseaux : coupe le segment qui contient `t` ; dans un silence, y crée un segment vide. */
        function splitAtTime(t) {
            if (retiming) return;
            settle(Seg.cutAt({ url: routes.retime, segments: segs(), t: t, duration: fullDur(),
                               edit: edit, select: select, toast: toast }));
        }

        // ── Modes d'écriture : la lecture « écrit » (demande de Fabien du 2026-09-23, calquée sur
        // les modes d'automation d'une station audio). Seul Complément écrit ; les autres
        // PROPOSENT. La boucle serveur est commune (`playhead_follow`) ; ici, le geste. ─────────
        var writeMode = '', armedAt = null, recorded = [], resultsNext = -1, proposals = [];
        var writeTimer = null, lastActivity = 0;
        function isPlaying() { return axis.playing() && axis.rate() > 0; }
        function arm() { if (armedAt == null && isPlaying()) { armedAt = axis.time(); renderRec(); } }
        function disarm() {
            if (armedAt == null) return;
            var end = axis.time();
            if (end - armedAt >= 0.5) { recorded.push([armedAt, end]); lastActivity = Date.now(); }
            armedAt = null; renderRec();
        }
        function renderRec() { if (recBadge) recBadge.classList.toggle('d-none', armedAt == null); }
        function wantedRanges() {
            if (writeMode === 'complement') {
                var t = axis.time(), lo = Math.max(0, t - 1), hi = t + COMPLEMENT_AHEAD;
                var empty = segs().filter(function (s) { return !(s.text || '').trim(); })
                    .map(function (s) { return [s.start_time || 0, s.end_time || 0]; });
                return Seg.gaps(segs(), fullDur()).concat(empty)
                    .map(function (r) { return [Math.max(r[0], lo), Math.min(r[1], hi)]; })
                    .filter(function (r) { return r[1] - r[0] >= 1; });
            }
            return recorded.slice(-50);
        }
        function post(url, body) {
            var App = global.WamaApp || {};
            return App.csrfFetch(url, App.csrfToken(), {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
            });
        }
        function postWriteCursor(enabled) {
            if (!routes.write_cursor) return Promise.resolve();
            var body = enabled ? { mode: writeMode, t: axis.time(), wanted: wantedRanges() } : { enabled: false };
            return post(routes.write_cursor, body).catch(function () {});
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
                        else { proposals.push(res); renderProposals(); drawZoom(); }
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
            if (writeSel && writeSel.value !== writeMode) writeSel.value = writeMode;
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
            if (!proposalsHost) return;
            proposalsHost.classList.toggle('d-none', !proposals.length);
            var fmt = Axis.formatTime;
            proposalsHost.innerHTML = proposals.map(function (p) {
                return '<div class="wp-item" data-id="' + p.id + '">' +
                    '<span class="wp-time">' + fmt(p.start) + '–' + fmt(p.end) + '</span>' +
                    '<span class="wp-text" title="' + esc(p.text) + '">' + esc(p.text) + '</span>' +
                    '<button class="btn btn-sm btn-success py-0 px-2 wp-accept" title="Remplacer le texte de cette plage">' +
                    '<i class="fas fa-check"></i></button>' +
                    '<button class="btn btn-sm btn-outline-secondary py-0 px-2 wp-reject" title="Garder le texte actuel">' +
                    '<i class="fas fa-xmark"></i></button></div>';
            }).join('');
        }
        function dropProposal(id) {
            proposals = proposals.filter(function (p) { return p.id !== id; });
            renderProposals(); drawZoom();
        }
        if (writeSel) {
            writeSel.addEventListener('change', function () { setWriteMode(writeSel.value); writeSel.blur(); });
            proposalsHost.addEventListener('click', function (e) {
                var item = e.target.closest('.wp-item'); if (!item) return;
                var id = parseInt(item.dataset.id, 10);
                var p = proposals.filter(function (x) { return x.id === id; })[0]; if (!p) return;
                if (e.target.closest('.wp-accept')) applySpan(p).then(function (ok) { if (ok) dropProposal(id); });
                else if (e.target.closest('.wp-reject')) dropProposal(id);
                else playFrom(p.start);                                          // écouter
            });
            // L'arrêt de la lecture AVANT (pause, fin, passage en arrière) referme la plage.
            axis.subscribe(function (st) { if (!(st.playing && st.rate > 0)) disarm(); });
        }

        // ── Dessin ──────────────────────────────────────────────────────────────────────────
        function drawZoom() {
            if (!cv) return;
            var D = fullDur(); if (!D) return;
            clampView();
            var W = cv.clientWidth || 600, H = cv.clientHeight || 54;
            if (cv.width !== W) cv.width = W;
            if (cv.height !== H) cv.height = H;
            var ctx = cv.getContext('2d');
            ctx.clearRect(0, 0, W, H);
            var pxps = W / viewDur, mid = H / 2, s = segs();
            if (peaksReady && peaks && peaks.length && pxps >= LEGIBLE_PXPS) {
                var N = peaks.length;
                ctx.fillStyle = '#3b82f6';
                for (var x = 0; x < W; x++) {
                    var t0 = viewStart + (x / W) * viewDur, t1 = viewStart + ((x + 1) / W) * viewDur;
                    var i0 = Math.max(0, Math.min(N - 1, Math.floor(t0 / D * N)));
                    var i1 = Math.max(i0 + 1, Math.min(N, Math.ceil(t1 / D * N)));
                    var m = 0;
                    for (var k = i0; k < i1; k++) { if (peaks[k] > m) m = peaks[k]; }
                    var h = (m / 255) * (H - 4);
                    ctx.fillRect(x, mid - h / 2, 1, Math.max(1, h));
                }
            } else {
                ctx.fillStyle = '#5a5f68'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
                ctx.fillText(!peaksReady ? 'Calcul de la forme d’onde…'
                                         : 'Zoomez pour afficher la forme d’onde', W / 2, mid + 4);
            }
            if (o.segments) {
                // Silences hachurés : l'audio qu'AUCUN segment ne couvre.
                ctx.fillStyle = hatchPattern(ctx);
                Seg.gaps(s, D).forEach(function (g) {
                    if (g[1] < viewStart || g[0] > viewStart + viewDur) return;
                    var x0 = Math.max(0, (g[0] - viewStart) / viewDur * W);
                    var x1 = Math.min(W, (g[1] - viewStart) / viewDur * W);
                    ctx.fillRect(x0, 0, Math.max(1, x1 - x0), H);
                });
            }
            var band = function (a, b, color) {
                if (b < viewStart || a > viewStart + viewDur) return;
                var x0 = Math.max(0, (a - viewStart) / viewDur * W);
                var x1 = Math.min(W, (b - viewStart) / viewDur * W);
                ctx.fillStyle = color; ctx.fillRect(x0, 0, Math.max(1, x1 - x0), H);
            };
            proposals.forEach(function (p) { band(p.start, p.end, 'rgba(239,68,68,0.16)'); });
            if (armedAt != null) band(armedAt, axis.time(), 'rgba(239,68,68,0.32)');
            if (o.segments) {
                // Repères = les jonctions ; poignées quand l'outil Bornes est actif.
                ctx.strokeStyle = boundaryTool ? 'rgba(255,193,7,0.85)' : 'rgba(255,255,255,0.22)';
                ctx.lineWidth = 1;
                for (var j = 1; j < s.length; j++) {
                    var t = (boundaryDrag && boundaryDrag.i === j) ? boundaryDrag.t : (s[j].start_time || 0);
                    if (t < viewStart || t > viewStart + viewDur) continue;
                    var bx = (t - viewStart) / viewDur * W;
                    ctx.beginPath(); ctx.moveTo(bx, 0); ctx.lineTo(bx, H); ctx.stroke();
                    if (boundaryTool) {
                        ctx.fillStyle = 'rgba(255,193,7,0.95)';
                        ctx.beginPath(); ctx.moveTo(bx - 4, 0); ctx.lineTo(bx + 4, 0); ctx.lineTo(bx, 6); ctx.fill();
                    }
                }
            }
            if (boundaryTool && !boundaryDrag && hoverT != null && hoverHandle < 0) {
                var hx = (hoverT - viewStart) / viewDur * W;
                ctx.save(); ctx.setLineDash([3, 3]); ctx.strokeStyle = 'rgba(255,193,7,0.7)';
                ctx.beginPath(); ctx.moveTo(hx, 0); ctx.lineTo(hx, H); ctx.stroke(); ctx.restore();
            }
            var px = (axis.time() - viewStart) / viewDur * W;
            if (px >= 0 && px <= W) {
                ctx.strokeStyle = '#0dcaf0'; ctx.lineWidth = 2;
                ctx.beginPath(); ctx.moveTo(px, 0); ctx.lineTo(px, H); ctx.stroke(); ctx.lineWidth = 1;
            }
        }

        function renderHeatmap() {
            if (!heat) return;
            var D = fullDur(); if (!D) return;
            clampView();
            var vs = cv ? viewStart : 0, vd = cv ? viewDur : D;
            heat.innerHTML = '';
            var frag = document.createDocumentFragment();
            segs().forEach(function (s, i) {
                var st = s.start_time || 0, en = s.end_time || st;
                if (en < vs || st > vs + vd) return;
                var L = Math.max(0, (st - vs) / vd * 100), R = Math.min(100, (en - vs) / vd * 100);
                var z = document.createElement('div');
                z.className = 'hz';
                z.style.left = L + '%';
                z.style.width = Math.max(0.4, R - L) + '%';
                z.style.background = Seg.severityColor(s);
                z.title = Seg.tooltip(s, i);
                z.addEventListener('click', function () { playFrom(st); select(i); });
                frag.appendChild(z);
            });
            heat.appendChild(frag);
        }

        function drawMini() {
            if (!mini) return;
            var D = fullDur(); if (!D) return;
            var W = mini.clientWidth || 600, H = mini.clientHeight || 14;
            if (mini.width !== W) mini.width = W;
            if (mini.height !== H) mini.height = H;
            var ctx = mini.getContext('2d'); ctx.clearRect(0, 0, W, H);
            segs().forEach(function (s) {
                var st = s.start_time || 0, en = s.end_time || st;
                ctx.fillStyle = Seg.severityColor(s);
                ctx.fillRect(st / D * W, 0, Math.max(1, (en - st) / D * W), H);
            });
            if (!cv) return;
            var vx = viewStart / D * W, vw = Math.max(2, viewDur / D * W);
            ctx.fillStyle = 'rgba(13,202,240,0.18)'; ctx.fillRect(vx, 0, vw, H);
            ctx.strokeStyle = '#0dcaf0'; ctx.lineWidth = 1.5;
            ctx.strokeRect(vx + 0.5, 0.5, Math.max(1, vw - 1), H - 1);
        }

        function redrawWindow() { clampView(); drawZoom(); renderHeatmap(); drawMini(); updateZoomLabel(); }

        function setZoom(newViewDur, centerT) {
            var D = fullDur(); if (!D) return;
            var c = (centerT != null) ? centerT : axis.time();
            viewDur = Math.max(MIN_VIEW, Math.min(D, newViewDur));
            viewStart = c - viewDur / 2;
            redrawWindow();
        }
        function followWindow(t) {           // recentre si la tête de lecture sort de la fenêtre
            if (!cv) return false;
            if (t < viewStart || t > viewStart + viewDur) { viewStart = t - viewDur / 2; clampView(); return true; }
            return false;
        }

        /** Aller à un timecode — lecture COMMUNE du temps ; recentre la fenêtre, choisit le segment. */
        function gotoTimecode() {
            var sec = Axis.parseTime(gotoInp && gotoInp.value);
            if (sec == null) {
                if (gotoInp) { gotoInp.classList.add('is-invalid'); setTimeout(function () { gotoInp.classList.remove('is-invalid'); }, 1200); }
                return;
            }
            var D = fullDur();
            var t = D ? Math.min(sec, D) : sec;
            axis.seek(t);
            viewStart = t - viewDur / 2; clampView(); redrawWindow();
            var i = Seg ? Seg.indexAt(segs(), t) : -1;
            if (i >= 0) select(i);
        }

        // ── Gestes sur l'onde et la minimap (`WamaGestures.track` : souris, stylet et doigt) ──
        if (cv) {
            cv.addEventListener('wheel', function (e) {            // molette = zoom autour du curseur
                e.preventDefault();
                var W = cv.clientWidth || 600;
                setZoom(viewDur * (e.deltaY > 0 ? 1.25 : 0.8), viewStart + (e.offsetX / W) * viewDur);
            }, { passive: false });
            var timeAt = function (clientX) {
                var rect = cv.getBoundingClientRect();
                return viewStart + ((clientX - rect.left) / (cv.clientWidth || 600)) * viewDur;
            };
            global.WamaGestures.track(cv, {
                touchAction: 'pan-y',
                threshold: 2,                                         // un tremblement d'1 px reste un clic
                start: function (e) {
                    if (boundaryTool && !retiming) {
                        var reach = global.WamaGestures.isTouch(e) ? HANDLE_PX_TOUCH : HANDLE_PX;
                        var i = handleAt(e.offsetX, cv.clientWidth || 600, reach);
                        if (i > 0) { boundaryDrag = { i: i, t: segs()[i].start_time || 0 }; return { boundary: true }; }
                    }
                    dragging = true;
                    return { boundary: false };
                },
                move: function (e, ctx, d) {
                    if (ctx.boundary) {                               // la borne suit le pointeur,
                        var s = segs(), i = boundaryDrag.i;           // bornée par ses deux voisines
                        var lo = (s[i - 1].start_time || 0) + Seg.MIN_SECTION;
                        var hi = (s[i].end_time || 0) - Seg.MIN_SECTION;
                        boundaryDrag.t = Math.max(lo, Math.min(hi, timeAt(e.clientX)));
                        drawZoom();
                        return;
                    }
                    viewStart -= (d.mx / (cv.clientWidth || 600)) * viewDur; clampView(); redrawWindow();
                },
                end: function (e, ctx, info) {
                    if (ctx.boundary) {
                        var b = boundaryDrag;
                        if (info.cancelled || Math.abs(b.t - (segs()[b.i].start_time || 0)) < 0.001) {
                            boundaryDrag = null; drawZoom(); return;
                        }
                        moveBoundary(b.i, b.t);
                        return;
                    }
                    dragging = false;
                    if (!info.moved && !info.cancelled) {
                        var t = Math.max(0, timeAt(e.clientX));
                        if (boundaryTool) { splitAtTime(t); return; }
                        axis.seek(t);
                        redrawWindow();
                    }
                },
                pinch: function (p) {
                    var D = fullDur(); if (!D) return;
                    var W = cv.clientWidth || 600;
                    // Le temps sous les doigts RESTE sous les doigts ; la fenêtre suit les doigts.
                    var at = (p.cx - cv.getBoundingClientRect().left) / W;
                    var ct = viewStart + at * viewDur;
                    viewDur = Math.max(MIN_VIEW, Math.min(D, viewDur / p.scale));
                    viewStart = ct - at * viewDur - (p.dx / W) * viewDur;
                    redrawWindow();
                },
            });
            cv.addEventListener('mousemove', function (e) {       // survol : poignée ou ciseaux
                if (!boundaryTool || boundaryDrag || dragging) return;
                hoverHandle = handleAt(e.offsetX, cv.clientWidth || 600);
                hoverT = timeAt(e.clientX);
                cv.style.cursor = hoverHandle > 0 ? 'ew-resize' : 'crosshair';
                drawZoom();
            });
            cv.addEventListener('mouseleave', function () {
                if (!boundaryTool || boundaryDrag) return;
                hoverT = null; hoverHandle = -1; drawZoom();
            });
        }
        if (mini && cv) {
            var jumpView = function (e) {
                var D = fullDur(); if (!D) return;
                var rect = mini.getBoundingClientRect();
                viewStart = ((e.clientX - rect.left) / (mini.clientWidth || 600)) * D - viewDur / 2;
                clampView(); redrawWindow();
            };
            global.WamaGestures.track(mini, {           // appuyer place la fenêtre, glisser la promène
                touchAction: 'pan-y', threshold: 0,
                start: function (e) { jumpView(e); return {}; },
                move: function (e) { jumpView(e); },
            });
        }

        // ── Clavier PROPRE au transport : C (Bornes), R (Touch / Latch), Échap ────────────────
        // Jamais pendant une saisie ; Échap déjà traité par la page (sortir d'une saisie) ne sort
        // pas en plus de l'outil — une touche, un geste.
        function onKeyDown(e) {
            if (e.key === 'Escape') {
                if (e.defaultPrevented) return;
                if (typing()) {
                    if (host.contains(document.activeElement)) { e.preventDefault(); document.activeElement.blur(); }
                    return;
                }
                if (boundaryTool) { e.preventDefault(); setBoundaryTool(false); }
                return;
            }
            if (typing() || e.ctrlKey || e.metaKey || e.altKey) return;
            var k = (e.key || '').toLowerCase();
            if (k === 'r' && o.writing && (writeMode === 'touch' || writeMode === 'latch')) {
                e.preventDefault(); if (!e.repeat) arm(); return;
            }
            if (k === 'c' && toolBtn) { e.preventDefault(); setBoundaryTool(!boundaryTool); }
        }
        function onKeyUp(e) {                                      // Touch : relâcher R ferme la plage
            if (writeMode === 'touch' && (e.key || '').toLowerCase() === 'r') disarm();
        }
        document.addEventListener('keydown', onKeyDown);
        document.addEventListener('keyup', onKeyUp);
        global.addEventListener('resize', redrawWindow);

        // ── L'abonnement à l'axe ────────────────────────────────────────────────────────────
        if (axis) axis.subscribe(function (st) {
            play.innerHTML = '<i class="fas ' + (st.playing ? 'fa-pause' : 'fa-play') + '"></i>';
            clock.textContent = Axis.formatTime(st.time, true) + ' / ' + (st.duration ? Axis.formatTime(st.duration) : '--:--');
            if (speedLabelEl) speedLabelEl.textContent = speedLabel(st);
            if (rate) {
                if (!st.shuttling && RATES.indexOf(st.rate) >= 0) {
                    rate.value = String(st.rate);
                } else {
                    shuttleOpt.value = String(st.rate);
                    shuttleOpt.textContent = speedLabel(st);
                    rate.value = shuttleOpt.value;
                }
            }
            if (cv || heat || mini) {
                if (st.duration && !viewDur) viewDur = Math.min(st.duration, DEFAULT_VIEW);
                if (followWindow(st.time) || st.reason !== 'tick') redrawWindow();
                else drawZoom();
            }
        });

        var help = 'Transport : Espace = lecture/pause · ←/→ = ±' + jump + ' s (Maj : ×6) · Début/Fin · ' +
                   'J/K/L = arrière / arrêt / avant par crans' +
                   (cv ? ' · onde : clic = y aller, glisser = défiler, molette = zoom' : ' · clic dans l’onde = y aller') +
                   (toolBtn ? ' · C = outil Bornes (glisser une borne, cliquer pour couper ou créer dans un blanc ; Échap)' : '') +
                   (writeSel ? " · R = enregistrer (Touch : maintenu ; Latch : jusqu'à l'arrêt)" : '');

        return {
            load: load,
            source: function () { return source; },
            redraw: redrawWindow,
            playFrom: playFrom,
            /** Coupe à la tête de lecture (Ctrl+Entrée de la liste, en navigation). */
            splitAtTime: splitAtTime,
            help: help,
        };
    }

    global.WamaTransport = { mount: mount, speedLabel: speedLabel, RATES: RATES };
})(window);
