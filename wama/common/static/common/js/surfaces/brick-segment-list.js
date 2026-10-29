/**
 * Brique `segment_list` — la LISTE ÉDITABLE d'une suite de segments (type `segments` :
 * début, fin, texte, locuteur, mots horodatés), abonnée à l'axe partagé de la surface.
 *
 * DÉPLACÉE de la page de correction du transcriber (`edit.js`, R166) le 2026-10-21, quand elle est
 * devenue une surface (ROUTE §F3b, étape 2) — mêmes gestes, mêmes raccourcis, parité attestée par
 * le scénario `transcriber.editor_parity` :
 *   • DEUX MODES. Navigation : ↑/↓ choisit un segment sans bouger la lecture, Tab / Maj+Tab
 *     amène la lecture au segment suivant / précédent, Entrée édite, Ctrl+Entrée coupe à la tête
 *     de lecture. Édition : on tape ; Tab / Alt+↑↓ changent de champ, Ctrl+Entrée scinde au
 *     curseur, Suppr en fin / ⌫ au début fusionnent, Échap revient en Navigation ;
 *   • le segment JOUÉ se surligne et la liste le suit (toujours en Navigation, en Édition si le
 *     verrou « suivre la lecture » est mis — Alt+L) ;
 *   • ▶ d'un segment le lit ; la poignée ⋮⋮ glissée sur un autre fusionne la plage ; Compacter
 *     fusionne un même locuteur ; ✓ marque « revu » (aussi à l'édition) et la progression suit ;
 *   • les noms des intervenants (un RÉGLAGE de l'élément, `options.names`) s'affichent sous leur
 *     libellé ; « Charger la dernière transcription » reprend un rôle lu (`options.latest`).
 * Chaque geste passe par `ctx.edit` : l'annuler/rétablir est celui de WAMA. Une frappe modifie la
 * valeur EN PLACE et ne fait qu'un cran par rafale ; « revu » ne fait pas de cran (la règle de la
 * page d'origine).
 */
(function (global) {
    'use strict';

    var FOLLOW_KEY = 'wama.segments.follow';

    function esc(t) {
        var d = document.createElement('div'); d.textContent = t == null ? '' : t;
        return d.innerHTML;
    }

    function mount(body, ctx, options) {
        options = options || {};
        var Seg = global.WamaSegments, Axis = global.WamaAxis;
        var axis = ctx.axis();
        var routes = ctx.config.routes || {};
        body.classList.add('wama-brick-segments');
        var segsOf = function () { var v = ctx.value(); return Array.isArray(v) ? v : []; };

        var banner = document.createElement('div');
        banner.className = 'alert alert-warning py-2 mb-2 small d-none';
        var list = document.createElement('div');
        list.className = 'wama-segments';
        body.appendChild(banner);
        body.appendChild(list);

        // ── Outils de l'en-tête : relecture, compacter, suivi de lecture ────────────────────
        var tools = document.createElement('span');
        tools.className = 'wama-segments-tools';
        tools.innerHTML =
            '<span class="wama-segments-review" title="Segments passés en revue">' +
            '<i class="fas fa-list-check"></i> <span data-segments="review-count">0 / 0</span>' +
            '<span class="review-bar"><span data-segments="review-fill"></span></span></span>' +
            '<button type="button" class="btn btn-sm btn-outline-emphasis py-0" data-segments="compact" ' +
            'title="Fusionner les segments consécutifs d\'un même locuteur"><i class="fas fa-compress"></i> Compacter</button>' +
            '<button type="button" class="btn btn-sm btn-outline-emphasis py-0" data-segments="follow" aria-pressed="false"></button>';
        var lockBtn = tools.querySelector('[data-segments="follow"]');

        var activeIndex = -1, selIndex = -1, followLock = false, quiet = false, renderedSig = null;

        function names() {
            return ((ctx.settings() || {}).values || {})[options.names] || {};
        }
        function signature() {
            return JSON.stringify([names(), segsOf().map(function (s) {
                return [s.start_time, s.end_time, s.speaker_id, s.text, !!s.reviewed];
            })]);
        }

        // ── Rendu ───────────────────────────────────────────────────────────────────────────
        function render() {
            var map = names();
            list.innerHTML = segsOf().map(function (s, i) {
                var nm = Seg.speakerName(s.speaker_id, map);
                return (
                    '<div class="seg-row' + (s.reviewed ? ' seg-reviewed' : '') + '" data-i="' + i +
                        '" data-start="' + (s.start_time || 0) + '" data-end="' + (s.end_time || 0) + '">' +
                    '<span class="seg-drag" draggable="true" data-i="' + i +
                        '" title="Glisser sur un autre segment pour fusionner"><i class="fas fa-grip-vertical"></i></span>' +
                    '<span class="seg-time">' + Axis.formatTime(s.start_time) + '</span>' +
                    '<div class="seg-speaker"><input type="text" value="' + esc(s.speaker_id || '') +
                        '" placeholder="Loc." data-i="' + i + '"' + (ctx.canEdit ? '' : ' readonly') + '>' +
                        ((nm && nm !== (s.speaker_id || '')) ?
                            '<span class="seg-spk-name" title="' + esc(nm) + '">' + esc(nm) + '</span>' : '') +
                    '</div>' +
                    '<button class="seg-play btn btn-sm btn-outline-info py-0 px-2" data-i="' + i +
                        '" title="Écouter ce segment"><i class="fas fa-play fa-xs"></i></button>' +
                    '<div class="seg-text-wrap"><div class="seg-text" contenteditable="' + (ctx.canEdit ? 'true' : 'false') +
                        '" data-i="' + i + '" spellcheck="true">' + esc(s.text || '') + '</div></div>' +
                    '<button class="seg-review btn btn-sm py-0 px-1" data-i="' + i +
                        '" title="Marquer revu / non revu"><i class="fas fa-check"></i></button>' +
                    '</div>');
            }).join('');
            renderedSig = signature();
            var a = activeIndex; activeIndex = -1; highlight(a, true);
            if (selIndex >= 0 && !editing()) markSelected(selIndex);
            updateReviewProgress();
        }

        function refresh() {
            if (quiet) { renderedSig = signature(); return; }
            if (signature() !== renderedSig) render();
            else updateReviewProgress();
            showBanner();
        }

        function rowAt(i) { return list.querySelector('.seg-row[data-i="' + i + '"]'); }
        function texts() { return Array.prototype.slice.call(list.querySelectorAll('.seg-text')); }
        /** Le mode Édition : le clavier est à un champ (un locuteur, « aller à »…) ou à un texte. */
        function editing() {
            var a = document.activeElement;
            if (!a) return false;
            if (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA') return true;
            return !!(a.classList && a.classList.contains('seg-text'));
        }
        function scrollIntoBody(row) {
            var cr = body.getBoundingClientRect(), r = row.getBoundingClientRect();
            if (r.top < cr.top + 8 || r.bottom > cr.bottom - 8) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }

        /** Le segment JOUÉ se surligne ; la liste le suit en Navigation, ou toujours sous verrou. */
        function highlight(idx, force) {
            if (idx === activeIndex && !force) return;
            var prev = list.querySelector('.seg-row.seg-active');
            if (prev) prev.classList.remove('seg-active');
            activeIndex = idx;
            if (idx < 0) return;
            var row = rowAt(idx);
            if (!row) return;
            row.classList.add('seg-active');
            if (!force && (followLock || !editing())) scrollIntoBody(row);
        }

        function updateReviewProgress() {
            var all = segsOf(), done = 0;
            all.forEach(function (s) { if (s && s.reviewed) done++; });
            tools.querySelector('[data-segments="review-count"]').textContent = done + ' / ' + all.length;
            tools.querySelector('[data-segments="review-fill"]').style.width =
                (all.length ? done / all.length * 100 : 0) + '%';
        }

        // ── Gestes d'édition ────────────────────────────────────────────────────────────────
        /** Un geste de FRAPPE : la valeur modifiée en place, une rafale = un cran, la liste ne se
         *  redessine pas (le champ édité garderait sinon son curseur perdu). */
        function typed(fn) {
            quiet = true;
            try { ctx.edit(function (v) { fn(v); return v; }, { burst: true, inPlace: true }); }
            finally { quiet = false; }
            updateReviewProgress();
        }
        function markReviewed(v, i) {
            if (v[i] && !v[i].reviewed) {
                v[i].reviewed = true;
                var row = rowAt(i);
                if (row) row.classList.add('seg-reviewed');
            }
        }
        list.addEventListener('input', function (e) {
            var t = e.target, i = parseInt(t.dataset.i, 10);
            if (isNaN(i)) return;
            if (t.classList.contains('seg-text')) {
                typed(function (v) { v[i].text = t.textContent; markReviewed(v, i); });
            } else if (t.tagName === 'INPUT') {
                typed(function (v) { v[i].speaker_id = t.value; markReviewed(v, i); });
            }
        });

        list.addEventListener('click', function (e) {
            var rev = e.target.closest('.seg-review');
            if (rev) {
                var i = parseInt(rev.dataset.i, 10);
                if (isNaN(i) || !segsOf()[i]) return;
                quiet = true;
                try {
                    ctx.edit(function (v) { v[i].reviewed = !v[i].reviewed; return v; },
                             { inPlace: true, untracked: true });
                } finally { quiet = false; }
                var row = rev.closest('.seg-row');
                if (row) row.classList.toggle('seg-reviewed', !!segsOf()[i].reviewed);
                updateReviewProgress();
                return;
            }
            var btn = e.target.closest('.seg-play');
            if (btn) {
                var k = parseInt(btn.dataset.i, 10);
                if (isNaN(k)) return;
                axis.playFrom(segsOf()[k].start_time || 0);       // le shuttle se rend d'abord
                highlight(k);
            }
        });

        // Glisser la poignée ⋮⋮ d'un segment sur un autre : fusion de la plage.
        var dragIndex = -1;
        list.addEventListener('dragstart', function (e) {
            var h = e.target.closest('.seg-drag');
            if (!h) return;
            dragIndex = parseInt(h.dataset.i, 10);
            e.dataTransfer.effectAllowed = 'move';
            try { e.dataTransfer.setData('text/plain', String(dragIndex)); } catch (_) {}
            var row = h.closest('.seg-row');
            if (row) row.classList.add('seg-dragging');
        });
        list.addEventListener('dragover', function (e) {
            if (dragIndex < 0) return;
            var row = e.target.closest('.seg-row');
            if (!row) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            list.querySelectorAll('.seg-drop-target').forEach(function (r) { r.classList.remove('seg-drop-target'); });
            if (parseInt(row.dataset.i, 10) !== dragIndex) row.classList.add('seg-drop-target');
        });
        list.addEventListener('drop', function (e) {
            if (dragIndex < 0) return;
            var row = e.target.closest('.seg-row');
            if (row) {
                e.preventDefault();
                var j = parseInt(row.dataset.i, 10), from = dragIndex;
                var merged = (!isNaN(j) && j !== from) ? Seg.mergeRange(segsOf(), from, j) : null;
                if (merged) { ctx.edit(function () { return merged; }); selectSeg(Math.min(from, j)); }
            }
            dragIndex = -1;
        });
        list.addEventListener('dragend', function () {
            dragIndex = -1;
            list.querySelectorAll('.seg-dragging, .seg-drop-target').forEach(function (r) {
                r.classList.remove('seg-dragging', 'seg-drop-target');
            });
        });

        // ── Sélection et édition ────────────────────────────────────────────────────────────
        function markSelected(i) {
            list.querySelectorAll('.seg-row.seg-selected').forEach(function (r) { r.classList.remove('seg-selected'); });
            var row = rowAt(i);
            if (row) { row.classList.add('seg-selected'); scrollIntoBody(row); }
        }
        function selectSeg(idx) {
            var n = segsOf().length; if (!n) return;
            selIndex = Math.max(0, Math.min(n - 1, idx));
            markSelected(selIndex);
        }
        function caretAt(el, offset) {
            try {
                var node = (offset != null && el.firstChild && el.firstChild.nodeType === 3) ? el.firstChild : null;
                var rg = document.createRange();
                if (node) { rg.setStart(node, Math.max(0, Math.min(node.length, offset))); rg.collapse(true); }
                else { rg.selectNodeContents(el); rg.collapse(false); }
                var s = global.getSelection(); s.removeAllRanges(); s.addRange(rg);
            } catch (_) {}
        }
        /** Édite le segment `idx` — curseur en fin de texte, ou à `offset`. */
        function enterEdit(idx, offset) {
            var t = texts(); if (!t.length) return;
            var el = t[Math.max(0, Math.min(t.length - 1, idx < 0 ? 0 : idx))];
            el.focus();
            caretAt(el, offset);
        }
        function focusSeg(dir) {
            var t = texts(); if (!t.length) return;
            var idx = t.indexOf(document.activeElement);
            if (idx === -1) idx = dir > 0 ? -1 : 0;
            enterEdit(Math.max(0, Math.min(t.length - 1, idx + dir)));
        }
        function caretOffset(el) {
            var sel = global.getSelection();
            if (!sel.rangeCount) return (el.textContent || '').length;
            var r = sel.getRangeAt(0).cloneRange();
            r.selectNodeContents(el);
            r.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
            return r.toString().length;
        }
        /** Navigation : la lecture au début du segment suivant / précédent, sans la lancer. */
        function seekSegment(dir) {
            var all = segsOf(); if (!all.length) return;
            var t = axis.time(), cur = Seg.indexAt(all, t);
            if (cur < 0) {
                cur = 0;
                for (var k = 0; k < all.length; k++) { if ((all[k].start_time || 0) <= t) cur = k; }
            }
            var i = Math.max(0, Math.min(all.length - 1, cur + dir));
            selectSeg(i);
            axis.seek(all[i].start_time || 0);
        }
        list.addEventListener('focusin', function (e) {
            if (e.target.classList && e.target.classList.contains('seg-text')) {
                var i = texts().indexOf(e.target);
                if (i >= 0) selIndex = i;
                list.querySelectorAll('.seg-row.seg-selected').forEach(function (r) { r.classList.remove('seg-selected'); });
            }
        });
        list.addEventListener('focusout', function (e) {
            ctx.history.endBurst();      // quitter un champ ferme la rafale : la frappe suivante = un cran neuf
            if (e.target.classList && e.target.classList.contains('seg-text')) {
                setTimeout(function () { if (!editing()) selectSeg(selIndex); }, 0);
            }
        });

        function splitHere(i, off) {
            ctx.edit(function (v) { return Seg.splitAt(v, i, off); });
            enterEdit(i + 1, 0);
        }
        function mergeHere(i, j) {
            var res = Seg.mergeAt(segsOf(), i, j);
            ctx.edit(function () { return res.segments; });
            enterEdit(i, res.join);
        }

        tools.querySelector('[data-segments="compact"]').addEventListener('click', function () {
            ctx.edit(function (v) { return Seg.compact(v); });
        });

        // ── Verrou « suivre la lecture » (Alt+L), gardé pour cet utilisateur ────────────────
        function applyFollowLock() {
            lockBtn.classList.toggle('btn-info', followLock);
            lockBtn.classList.toggle('btn-outline-emphasis', !followLock);
            lockBtn.setAttribute('aria-pressed', followLock ? 'true' : 'false');
            lockBtn.innerHTML = followLock ? '<i class="fas fa-lock"></i>' : '<i class="fas fa-lock-open"></i>';
            lockBtn.title = followLock ? 'Suivi de lecture ACTIVÉ — clic ou Alt+L pour débrayer'
                                       : 'Suivre la lecture (la liste suit l\'audio même en édition) — Alt+L';
        }
        function toggleFollowLock() {
            followLock = !followLock;
            try { localStorage.setItem(FOLLOW_KEY, followLock ? '1' : '0'); } catch (_) {}
            applyFollowLock();
            var row = followLock && activeIndex >= 0 ? rowAt(activeIndex) : null;
            if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
        try { followLock = localStorage.getItem(FOLLOW_KEY) === '1'; } catch (_) {}
        applyFollowLock();
        lockBtn.addEventListener('click', toggleFollowLock);

        // ── « Charger la dernière transcription » (un rôle lu, `options.latest`) ────────────
        function latest() {
            var v = options.latest ? (ctx.reads() || {})[options.latest] : null;
            return Array.isArray(v) ? v : [];
        }
        var bannerClosed = false;
        function showBanner() {
            var shown = ctx.canEdit && !bannerClosed && options.latest && (ctx.context() || {}).corrected && latest().length;
            banner.classList.toggle('d-none', !shown);
        }
        banner.innerHTML = 'Vous éditez <strong>votre correction</strong>. Si vous avez relancé la transcription, ' +
            'vous pouvez charger la dernière version générée (cela remplacera votre correction).' +
            '<button type="button" class="btn btn-sm btn-outline-warning mt-1 w-100" data-segments="load-latest">' +
            'Charger la dernière transcription</button>';
        banner.querySelector('[data-segments="load-latest"]').addEventListener('click', function () {
            var fresh = latest();
            if (!fresh.length) { if (global.WamaApp) WamaApp.toast('Aucune nouvelle transcription disponible.', 'info'); return; }
            if (!confirm('Charger la dernière transcription générée ?\nVotre correction actuelle sera remplacée (annulable avec Ctrl+Z).')) return;
            ctx.edit(function () { return JSON.parse(JSON.stringify(fresh)); });
            bannerClosed = true;
            showBanner();
        });

        // ── Clavier — en CAPTURE : Échap qui sort d'une saisie est pris AVANT la ligne de temps
        // (qui, sinon, sortirait aussi de l'outil Bornes : une touche, un geste) ───────────────
        document.addEventListener('keydown', function (e) {
            var inField = editing();
            var tgt = e.target;
            // Frappe dans un champ (aller à, locuteur…) : ni transport ni navigation, sauf Ctrl/Alt/Échap.
            if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.tagName === 'SELECT')
                && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== 'Escape') return;
            if (e.altKey && (e.key === 'l' || e.key === 'L')) { e.preventDefault(); toggleFollowLock(); return; }
            if (e.key === 'Escape') {
                if (inField) { e.preventDefault(); document.activeElement.blur(); }
                return;
            }
            if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
                e.preventDefault();
                var d = e.key === 'ArrowDown' ? 1 : -1;
                if (inField) focusSeg(d); else selectSeg(selIndex < 0 ? 0 : selIndex + d);
                return;
            }
            if (e.key === 'Tab') {
                if (!segsOf().length) return;
                e.preventDefault();
                if (inField) focusSeg(e.shiftKey ? -1 : 1); else seekSegment(e.shiftKey ? -1 : 1);
                return;
            }
            var a = document.activeElement;
            if (inField && a.classList && a.classList.contains('seg-text')) {
                var i = parseInt(a.dataset.i, 10);
                if (!isNaN(i)) {
                    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); splitHere(i, caretOffset(a)); return; }
                    var off = caretOffset(a), len = (a.textContent || '').length;
                    if (e.key === 'Delete' && off >= len && i < segsOf().length - 1) { e.preventDefault(); mergeHere(i, i + 1); return; }
                    if (e.key === 'Backspace' && off === 0 && i > 0) { e.preventDefault(); mergeHere(i - 1, i); return; }
                }
            }
            if (inField) return;                                   // en Édition, le reste sert à taper
            if (e.key === 'ArrowUp') { e.preventDefault(); selectSeg(selIndex < 0 ? 0 : selIndex - 1); return; }
            if (e.key === 'ArrowDown') { e.preventDefault(); selectSeg(selIndex < 0 ? 0 : selIndex + 1); return; }
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
                // Couper à la TÊTE DE LECTURE — les ciseaux de l'outil Bornes (`WamaSegments.cutAt`).
                e.preventDefault();
                Seg.cutAt({ url: routes.retime, segments: segsOf(), t: axis.time(), duration: axis.duration(),
                            edit: function (fn) { ctx.edit(fn); }, select: ctx.select,
                            toast: function (m, k) { if (global.WamaApp) WamaApp.toast(m, k); } });
                return;
            }
            if (e.key === 'Enter') { e.preventDefault(); enterEdit(selIndex); }
        }, true);

        // La page choisit un segment (bande de qualité, borne, aller à) : le sélectionner, ou
        // l'éditer s'il vient d'être créé (`focus`).
        ctx.on('select', function (p) {
            if (p.id == null || p.id < 0) return;
            if (p.focus) enterEdit(p.id); else selectSeg(p.id);
        });
        ctx.on('settings', function () { if (signature() !== renderedSig) render(); });
        axis.subscribe(function (st) {
            var i = Seg.indexAt(segsOf(), st.time);
            highlight(i);
            // « Aller à » un temps nommé (`goto`, dit par l'axe) : le segment qui s'y trouve est choisi.
            if (st.reason === 'goto' && i >= 0) ctx.select(i);
        });

        render();
        showBanner();
        return {
            tools: tools,
            refresh: refresh,
            help: 'Segments : ⋮⋮ glissé = fusionner une plage · ✓ = revu',
        };
    }

    global.WamaSurface.registerBrick('segment_list', { title: 'Segments', mount: mount });
})(window);
