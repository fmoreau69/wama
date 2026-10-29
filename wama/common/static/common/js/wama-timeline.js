/**
 * wama-timeline.js — la LIGNE DE TEMPS commune : une VUE du temps, abonnée à l'axe (2026-10-21,
 * ROUTE §F3b, redécoupage décidé par Fabien le même jour).
 *
 * Quatre niveaux, chacun à sa place : l'AXE est le temps (`wama-axis.js`), le TRANSPORT ses
 * commandes (`wama-transport.js`), les VUES le regardent — celle-ci, la vidéo, la partition —, et
 * les OUTILS DE DOMAINE agissent sur une donnée pendant la lecture. La ligne de temps ne pilote
 * l'axe que par les gestes d'une vue (un clic y amène la lecture) ; elle ne connaît aucun
 * transport, et le transport ne la connaît pas (`WAMA_DATA_WORLD §5bis`).
 *
 * Elle était, jusqu'à ce redécoupage, un ensemble d'options du transport : même calcul, même rendu
 * — les gestes ont été DÉPLACÉS de la page de correction du transcriber (`edit.js`, R166) puis du
 * transport ; parité attestée par le scénario `transcriber.editor_parity`.
 *
 * Ce qu'elle montre : l'onde FENÊTRÉE sur pics fins (zoom de 4 s à la durée, molette, glisser,
 * pincer) ; le zoom et la fenêtre visible sont un réglage de la VUE, pas du temps. Options :
 *   segments    couches des segments sur l'onde : repères, silences hachurés
 *   quality     bande de qualité des segments (clic = écouter)    minimap  vue d'ensemble
 *   zoom        boutons de zoom
 *   boundaries  'retime' : outil Bornes (glisser une borne, couper, créer dans un silence ; C) — un
 *               outil de la vue sur les segments, le calcul est serveur (`WamaSegments.retime`)
 * Ce qui vient de la page (`cfg`) : `axis`, `segments()` (la suite montrée), `edit(fn)` (un geste
 * de structure), `select(i, {focus})`, `routes` (`retime`), `densePeaks(poll)` (promesse des pics
 * fins), `bands()` — des plages que d'autres MARQUENT (`[{start, end, color}]`, `end` nul = jusqu'à
 * la tête de lecture : la plage qu'un mode d'écriture enregistre).
 * Rend `{load, redraw, splitAtTime, tools, help}` ; `tools` (zoom, Bornes) se place où la page
 * veut — le titre de la brique, sur une surface.
 */
(function (global) {
    'use strict';

    var MIN_VIEW = 4;                 // zoom max : une fenêtre de 4 s
    var DEFAULT_VIEW = 240;           // fenêtre d'ouverture : l'onde se voit d'emblée
    var LEGIBLE_PXPS = 1.5;           // en dessous, l'onde se tait (la minimap fait la vue d'ensemble)
    var HANDLE_PX = 6, HANDLE_PX_TOUCH = 16;
    var PEAKS_POLL_MS = 2500;

    function el(tag, cls, attrs) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        return e;
    }

    function button(name, icon, title, text) {
        var b = el('button', 'btn btn-sm btn-outline-emphasis', { type: 'button', 'data-timeline': name, title: title });
        b.innerHTML = (icon ? '<i class="fas ' + icon + '"></i>' : '') + (text ? ' ' + text : '');
        return b;
    }

    function mount(host, cfg) {
        cfg = cfg || {};
        var o = cfg.options || {};
        var Seg = global.WamaSegments;
        var axis = cfg.axis;
        var routes = cfg.routes || {};
        var segs = function () { var s = cfg.segments ? cfg.segments() : null; return Array.isArray(s) ? s : []; };
        var bands = function () { var b = cfg.bands ? cfg.bands() : null; return Array.isArray(b) ? b : []; };
        var edit = cfg.edit || function () {};
        var select = cfg.select || function () {};
        var toast = function (m, k) { if (global.WamaApp && WamaApp.toast) WamaApp.toast(m, k); };
        host.classList.add('wama-timeline');

        // ── Onde fenêtrée, bande de qualité, minimap ────────────────────────────────────────
        var cv = el('canvas', 'zoom-wave', { 'data-timeline': 'wave',
            title: "Forme d'onde — clic : placer · glisser : déplacer · molette : zoom" });
        host.appendChild(cv);
        var heat = null, mini = null;
        if (o.quality) {
            heat = el('div', 'seg-heatmap', { 'data-timeline': 'heat', title: 'Qualité par segment — cliquez pour écouter' });
            host.appendChild(heat);
        }
        if (o.minimap) {
            mini = el('canvas', 'zoom-mini', { 'data-timeline': 'mini', title: "Vue d'ensemble — cliquez/glissez pour vous déplacer" });
            host.appendChild(mini);
        }

        // ── Les outils de la vue : zoom, Bornes ─────────────────────────────────────────────
        var tools = el('div', 'wama-timeline-tools');
        var zoomLabel = null;
        if (o.zoom) {
            var zout = button('zoom-out', 'fa-minus', 'Dézoomer');
            zoomLabel = el('span', 'badge bg-secondary wama-timeline-zoom', { 'data-timeline': 'zoom-label' });
            var zin = button('zoom-in', 'fa-plus', 'Zoomer');
            tools.appendChild(el('span', 'text-body-secondary')).innerHTML = '<i class="fas fa-magnifying-glass"></i>';
            [zout, zoomLabel, zin].forEach(function (b) { tools.appendChild(b); });
            zin.addEventListener('click', function () { setZoom(viewDur * 0.6); });
            zout.addEventListener('click', function () { setZoom(viewDur * 1.7); });
        }
        var toolBtn = null;
        if (o.boundaries) {
            toolBtn = button('boundaries', 'fa-scissors',
                'Outil Bornes (C) — glisser une borne pour la déplacer · cliquer dans une section pour la couper · Échap pour sortir',
                'Bornes');
            toolBtn.setAttribute('aria-pressed', 'false');
            toolBtn.classList.add('ms-2');
            tools.appendChild(toolBtn);
            toolBtn.addEventListener('click', function () { setBoundaryTool(!boundaryTool); });
        }

        // ── Fenêtre de l'onde ───────────────────────────────────────────────────────────────
        var peaks = null, peaksDur = 0, peaksReady = false;
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
        /** (Re)lit les pics fins du média montré — à l'ouverture, et quand le média est refait. */
        function load() { fetchPeaks(false); }

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
            cv.style.cursor = boundaryTool ? 'crosshair' : '';
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

        // ── Dessin ──────────────────────────────────────────────────────────────────────────
        function drawZoom() {
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
            // Les plages MARQUÉES par d'autres (propositions et enregistrement d'un mode d'écriture).
            bands().forEach(function (b) {
                var a = b.start, z = b.end == null ? axis.time() : b.end;
                if (z < viewStart || a > viewStart + viewDur) return;
                var x0 = Math.max(0, (a - viewStart) / viewDur * W);
                var x1 = Math.min(W, (z - viewStart) / viewDur * W);
                ctx.fillStyle = b.color; ctx.fillRect(x0, 0, Math.max(1, x1 - x0), H);
            });
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
            heat.innerHTML = '';
            var frag = document.createDocumentFragment();
            segs().forEach(function (s, i) {
                var st = s.start_time || 0, en = s.end_time || st;
                if (en < viewStart || st > viewStart + viewDur) return;
                var L = Math.max(0, (st - viewStart) / viewDur * 100), R = Math.min(100, (en - viewStart) / viewDur * 100);
                var z = document.createElement('div');
                z.className = 'hz';
                z.style.left = L + '%';
                z.style.width = Math.max(0.4, R - L) + '%';
                z.style.background = Seg.severityColor(s);
                z.title = Seg.tooltip(s, i);
                z.addEventListener('click', function () { axis.playFrom(st); select(i); });
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
        /** Recentre la fenêtre quand la tête de lecture en sort — toute cause confondue (lecture,
         *  segment suivant, saut) : la vue suit le temps, personne ne la pilote. */
        function followWindow(t) {
            if (t < viewStart || t > viewStart + viewDur) { viewStart = t - viewDur / 2; clampView(); return true; }
            return false;
        }

        // ── Gestes sur l'onde et la minimap (`WamaGestures.track` : souris, stylet et doigt) ──
        cv.addEventListener('wheel', function (e) {                // molette = zoom autour du curseur
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
            threshold: 2,                                             // un tremblement d'1 px reste un clic
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
                if (ctx.boundary) {                                   // la borne suit le pointeur,
                    var s = segs(), i = boundaryDrag.i;               // bornée par ses deux voisines
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
        cv.addEventListener('mousemove', function (e) {           // survol : poignée ou ciseaux
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
        if (mini) {
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

        // ── Clavier PROPRE à la vue : C (Bornes), Échap — par le clavier commun (`WamaKeys`) ─────
        // Une brique prioritaire de la page. Jamais pendant une saisie ; Échap déjà traité (sortir
        // d'une saisie) ne sort pas en plus de l'outil — une touche, un geste : la règle du module.
        if (toolBtn) global.WamaKeys.register({ owner: 'media_timeline', scope: 'page', handle: function (e) {
            if (e.key === 'Escape') {
                if (!boundaryTool) return false;
                setBoundaryTool(false);
                return true;
            }
            if (e.ctrlKey || e.metaKey || e.altKey || (e.key || '').toLowerCase() !== 'c') return false;
            setBoundaryTool(!boundaryTool);
            return true;
        } });
        global.addEventListener('resize', redrawWindow);

        // ── L'abonnement à l'axe ────────────────────────────────────────────────────────────
        if (axis) axis.subscribe(function (st) {
            if (st.duration && !viewDur) viewDur = Math.min(st.duration, DEFAULT_VIEW);
            // « Aller à » un temps nommé (`goto`) : la fenêtre le montre au centre.
            if (st.reason === 'goto') { viewStart = st.time - viewDur / 2; clampView(); }
            if (followWindow(st.time) || st.reason !== 'tick') redrawWindow();
            else drawZoom();
        });

        var help = 'Ligne de temps : clic = y aller, glisser = défiler, molette = zoom' +
                   (toolBtn ? ' · outil Bornes : glisser une borne, cliquer pour couper ou créer dans un blanc' : '');

        return {
            load: load,
            redraw: redrawWindow,
            /** Coupe à `t` (les ciseaux de l'outil Bornes). */
            splitAtTime: splitAtTime,
            tools: tools.childNodes.length ? tools : null,
            help: help,
        };
    }

    global.WamaTimeline = { mount: mount };
})(window);
