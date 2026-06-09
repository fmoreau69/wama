/**
 * Transcriber — Éditeur de correction manuelle (page /edit/<id>/).
 * Forme d'onde = composant commun WamaAudioPlayer. Phase 1 : synchro onde↔texte,
 * édition inline, locuteur, navigation clavier, auto-save. Voir TRANSCRIBER_CORRECTION.md.
 */
(function () {
  'use strict';
  const CFG = window.TRANSCRIBER_EDIT || {};
  const playerId = CFG.playerId;

  let segments = [];
  try {
    segments = JSON.parse(document.getElementById('segmentsData').textContent) || [];
  } catch (e) { segments = []; }

  const segContainer = document.getElementById('segments');
  const saveState = document.getElementById('saveState');
  let activeIndex = -1;
  let dirty = false;

  function fmt(s) {
    s = Math.max(0, Math.floor(s || 0));
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }
  function esc(t) {
    const d = document.createElement('div'); d.textContent = t == null ? '' : t;
    return d.innerHTML;
  }

  /* ── Rendu de la liste des segments ─────────────────────────────────── */
  function render() {
    segContainer.innerHTML = segments.map(function (s, i) {
      return (
        '<div class="seg-row" data-i="' + i + '" data-start="' + (s.start_time || 0) +
          '" data-end="' + (s.end_time || 0) + '">' +
          '<span class="seg-time">' + fmt(s.start_time) + '</span>' +
          '<div class="seg-speaker"><input type="text" value="' + esc(s.speaker_id || '') +
            '" placeholder="Loc." data-i="' + i + '"></div>' +
          '<button class="seg-play btn btn-sm btn-outline-info py-0 px-2" data-i="' + i +
            '" title="Écouter ce segment"><i class="fas fa-play fa-xs"></i></button>' +
          '<div class="seg-text-wrap">' +
            '<div class="seg-text" contenteditable="true" data-i="' + i + '" spellcheck="true">' +
              esc(s.text || '') + '</div>' +
          '</div>' +
        '</div>'
      );
    }).join('');
  }

  /* ── Synchro : surligne le segment courant pendant la lecture ───────── */
  function highlight(idx) {
    if (idx === activeIndex) return;
    const prev = segContainer.querySelector('.seg-row.seg-active');
    if (prev) prev.classList.remove('seg-active');
    activeIndex = idx;
    if (idx < 0) return;
    const row = segContainer.querySelector('.seg-row[data-i="' + idx + '"]');
    if (row) {
      row.classList.add('seg-active');
      const r = row.getBoundingClientRect();
      if (r.top < 90 || r.bottom > window.innerHeight) {
        row.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
  }
  function indexAt(t) {
    for (let i = 0; i < segments.length; i++) {
      if (t >= (segments[i].start_time || 0) && t < (segments[i].end_time || 0)) return i;
    }
    return -1;
  }

  /* ── Auto-save (débounce) ───────────────────────────────────────────── */
  let saveTimer = null;
  function markDirty() {
    dirty = true;
    if (saveState) saveState.innerHTML = '<i class="fas fa-circle text-warning" style="font-size:.5rem;"></i> Modifié…';
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { save('draft'); }, 800);
  }
  function save(status) {
    if (saveState) saveState.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Enregistrement…';
    return fetch(CFG.saveUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CFG.csrfToken },
      body: JSON.stringify({ segments: segments, status: status || 'draft' }),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        dirty = false;
        if (saveState) {
          saveState.innerHTML = (status === 'done')
            ? '<i class="fas fa-check-double text-success"></i> Correction terminée'
            : '<i class="fas fa-check text-success"></i> À jour';
        }
      })
      .catch(function () {
        if (saveState) saveState.innerHTML = '<i class="fas fa-triangle-exclamation text-danger"></i> Erreur';
      });
  }

  /* ── Événements d'édition ───────────────────────────────────────────── */
  segContainer.addEventListener('input', function (e) {
    const el = e.target;
    const i = parseInt(el.dataset.i, 10);
    if (isNaN(i)) return;
    if (el.classList.contains('seg-text')) { segments[i].text = el.textContent; markDirty(); }
    else if (el.tagName === 'INPUT') { segments[i].speaker_id = el.value; markDirty(); }
  });

  // Clic ▶ d'un segment → seek + lecture
  segContainer.addEventListener('click', function (e) {
    const btn = e.target.closest('.seg-play');
    if (!btn) return;
    const i = parseInt(btn.dataset.i, 10);
    if (isNaN(i) || !window.WamaAudioPlayer) return;
    WamaAudioPlayer.seek(playerId, segments[i].start_time || 0, true);
    highlight(i);
  });

  /* ── Clavier ────────────────────────────────────────────────────────── */
  // Déplace le focus de `dir` segments (clamp, sans fuite). Curseur en fin de texte.
  function focusSeg(dir) {
    const texts = Array.prototype.slice.call(segContainer.querySelectorAll('.seg-text'));
    if (!texts.length) return;
    let idx = texts.indexOf(document.activeElement);
    if (idx === -1) idx = dir > 0 ? -1 : 0;  // pas dans un segment → entre par le bord
    const next = Math.max(0, Math.min(texts.length - 1, idx + dir));
    const el = texts[next];
    el.focus();
    // Place le curseur en fin de texte pour continuer l'édition naturellement.
    try {
      const r = document.createRange(); r.selectNodeContents(el); r.collapse(false);
      const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
    } catch (_) {}
  }

  /* ── Transport : saut avant/arrière + vitesse ──────────────────────── */
  let playbackRate = 1.0;
  function audio() { return window.WamaAudioPlayer ? WamaAudioPlayer.getAudio(playerId) : null; }
  function skip(delta) {
    const a = audio();
    if (a) { try { a.currentTime = Math.max(0, (a.currentTime || 0) + delta); } catch (_) {} }
  }
  function setSpeed(rate) {
    playbackRate = Math.max(0.5, Math.min(2.0, Math.round(rate * 100) / 100));
    const a = audio();
    if (a) a.playbackRate = playbackRate;
    const el = document.getElementById('speedVal');
    if (el) el.textContent = playbackRate.toFixed(2).replace(/0$/, '') + '×';
  }
  function initTransport() {
    const sb = document.getElementById('skipBack');
    const sf = document.getElementById('skipFwd');
    const sd = document.getElementById('speedDown');
    const su = document.getElementById('speedUp');
    if (sb) sb.addEventListener('click', function () { skip(-5); });
    if (sf) sf.addEventListener('click', function () { skip(5); });
    if (sd) sd.addEventListener('click', function () { setSpeed(playbackRate - 0.25); });
    if (su) su.addEventListener('click', function () { setSpeed(playbackRate + 0.25); });
    // Réapplique la vitesse quand l'audio est (ré)initialisé.
    const a = audio();
    if (a) a.playbackRate = playbackRate;
  }

  /* ── Shuttle JKL (montage) — échelle de vitesse unique ─────────────── */
  // L incrémente, J décrémente sur l'échelle ci-dessous, K = stop. Donc depuis
  // 4× avant, J → 2× (réduit la vitesse), pas un passage direct en arrière.
  // L'arrière (<0) est un défilement silencieux (<audio> ne lit pas le son à l'envers).
  const SHUTTLE = [-16, -8, -4, -2, -1, 0, 1, 2, 4, 8, 16];
  const STOP_IDX = SHUTTLE.indexOf(0);
  let shuttleIdx = STOP_IDX;
  let shuttle = 0;                 // = SHUTTLE[shuttleIdx], pour l'affichage
  let reverseTimer = null;
  function stopReverse() { if (reverseTimer) { clearInterval(reverseTimer); reverseTimer = null; } }
  function shuttleLabel() {
    const el = document.getElementById('speedVal');
    if (!el) return;
    if (shuttle > 0) el.textContent = '▶▶ ' + shuttle + '×';
    else if (shuttle < 0) el.textContent = '◀◀ ' + (-shuttle) + '×';
    else el.textContent = playbackRate.toFixed(2).replace(/0$/, '') + '×';
  }
  function startReverse(rate) {
    stopReverse();
    reverseTimer = setInterval(function () {
      const na = audio(); if (!na) { stopReverse(); return; }
      na.currentTime = Math.max(0, (na.currentTime || 0) - rate * 0.06);
      if (na.currentTime <= 0) { shuttleIdx = STOP_IDX; shuttle = 0; stopReverse(); shuttleLabel(); }
    }, 60);
  }
  function applyShuttle() {
    shuttle = SHUTTLE[shuttleIdx];
    const a = audio(); if (!a) { shuttleLabel(); return; }
    if (shuttle > 0) { stopReverse(); a.playbackRate = shuttle; a.play().catch(function () {}); }
    else if (shuttle < 0) { a.pause(); startReverse(-shuttle); }
    else { stopReverse(); a.pause(); a.playbackRate = playbackRate; }
    shuttleLabel();
  }
  function shuttleStep(dir) {
    shuttleIdx = Math.max(0, Math.min(SHUTTLE.length - 1, shuttleIdx + dir));
    applyShuttle();
  }
  function shuttleForward() { shuttleStep(1); }   // L : un cran vers l'avant / + rapide
  function shuttleReverse() { shuttleStep(-1); }  // J : un cran vers l'arrière / réduit
  function shuttleStop() { shuttleIdx = STOP_IDX; applyShuttle(); }  // K

  /* ── Deux modes : Navigation (audio/JKL) ↔ Édition (frappe) ─────────── */
  let selIndex = -1;  // segment sélectionné en mode Navigation
  function rows() { return Array.prototype.slice.call(segContainer.querySelectorAll('.seg-text')); }
  function inEdit() {
    const a = document.activeElement;
    if (!a) return false;
    if (a.tagName === 'INPUT' || a.tagName === 'TEXTAREA') return true;     // locuteur
    return a.classList && a.classList.contains('seg-text');                 // texte segment
  }
  function selectSeg(idx) {
    const t = rows(); if (!t.length) return;
    selIndex = Math.max(0, Math.min(t.length - 1, idx));
    segContainer.querySelectorAll('.seg-row.seg-selected').forEach(function (r) { r.classList.remove('seg-selected'); });
    const row = t[selIndex].closest('.seg-row');
    if (row) {
      row.classList.add('seg-selected');
      const r = row.getBoundingClientRect();
      if (r.top < 90 || r.bottom > window.innerHeight) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }
  function enterEdit(idx) {
    const t = rows(); if (!t.length) return;
    const i = Math.max(0, Math.min(t.length - 1, idx < 0 ? 0 : idx));
    const el = t[i]; el.focus();
    try {
      const rg = document.createRange(); rg.selectNodeContents(el); rg.collapse(false);
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
    } catch (_) {}
  }
  function togglePlay() {
    const a = audio(); if (!a) return;
    // Espace = lecture normale → désengage le shuttle (retour échelle au stop).
    stopReverse(); shuttleIdx = STOP_IDX; shuttle = 0;
    if (a.paused) {
      a.playbackRate = playbackRate;
      if (window.WamaAudioPlayer) WamaAudioPlayer.pauseAll();
      a.play().catch(function () {});
    } else { a.pause(); }
    shuttleLabel();
  }
  // Synchronise la sélection avec le focus (clic dans un segment = édition)
  segContainer.addEventListener('focusin', function (e) {
    if (e.target.classList && e.target.classList.contains('seg-text')) {
      const i = rows().indexOf(e.target);
      if (i >= 0) selIndex = i;
      segContainer.querySelectorAll('.seg-row.seg-selected').forEach(function (r) { r.classList.remove('seg-selected'); });
    }
  });
  segContainer.addEventListener('focusout', function (e) {
    if (e.target.classList && e.target.classList.contains('seg-text')) {
      setTimeout(function () { if (!inEdit()) selectSeg(selIndex); }, 0);  // sortie d'édition → re-surligne
    }
  });

  /* ── Édition de segments : split / merge / compact ─────────────────── */
  function caretOffset(el) {
    const sel = window.getSelection();
    if (!sel.rangeCount) return (el.textContent || '').length;
    const r = sel.getRangeAt(0).cloneRange();
    r.selectNodeContents(el);
    r.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
    return r.toString().length;
  }
  function enterEditAt(idx, offset) {
    const t = rows(); if (idx < 0 || idx >= t.length) return;
    const el = t[idx]; el.focus();
    try {
      const node = (el.firstChild && el.firstChild.nodeType === 3) ? el.firstChild : null;
      const rg = document.createRange();
      if (node) { rg.setStart(node, Math.max(0, Math.min(node.length, offset))); rg.collapse(true); }
      else { rg.selectNodeContents(el); rg.collapse(false); }
      const s = window.getSelection(); s.removeAllRanges(); s.addRange(rg);
    } catch (_) {}
  }
  function refresh() { render(); renderOverlays(); markDirty(); }
  function splitAt(i, off) {                          // Ctrl+Entrée
    const s = segments[i]; const text = s.text || '';
    off = Math.max(0, Math.min(text.length, off));
    const st = s.start_time || 0, en = s.end_time || st;
    const mid = st + (en - st) * (text.length ? off / text.length : 0.5);
    const seg1 = Object.assign({}, s, { text: text.slice(0, off).trim(), end_time: mid, words: undefined });
    const seg2 = Object.assign({}, s, { text: text.slice(off).trim(), start_time: mid, words: undefined });
    segments.splice(i, 1, seg1, seg2);
    refresh(); enterEditAt(i + 1, 0);                 // curseur au début de la 2e moitié
  }
  function mergeAt(i, j) {                            // i < j adjacents : j → i
    const a = segments[i], b = segments[j];
    const join = (a.text || '').trim().length + 1;    // position du curseur à la jonction
    a.text = ((a.text || '').trim() + ' ' + (b.text || '').trim()).trim();
    a.end_time = b.end_time; a.words = undefined;
    segments.splice(j, 1);
    refresh(); enterEditAt(i, join);
  }
  function compact() {                               // fusionne segments consécutifs même locuteur
    const out = [];
    segments.forEach(function (s) {
      const last = out[out.length - 1];
      const sp = s.speaker_id || '';
      if (last && sp && (last.speaker_id || '') === sp) {
        last.text = ((last.text || '').trim() + ' ' + (s.text || '').trim()).trim();
        last.end_time = s.end_time; last.words = undefined;
      } else { out.push(Object.assign({}, s)); }
    });
    segments.length = 0; Array.prototype.push.apply(segments, out);
    refresh();
  }
  const compactBtn = document.getElementById('compactBtn');
  if (compactBtn) compactBtn.addEventListener('click', compact);

  document.addEventListener('keydown', function (e) {
    const editing = inEdit();

    // Échap : en ÉDITION → sortir vers Navigation (l'audio se repilote au clavier).
    if (e.key === 'Escape') {
      if (editing) { e.preventDefault(); document.activeElement.blur(); }
      return;
    }
    // Alt+↑/↓ : segment précédent/suivant dans LES DEUX modes.
    if (e.altKey && (e.key === 'ArrowUp' || e.key === 'ArrowDown')) {
      e.preventDefault();
      const d = e.key === 'ArrowDown' ? 1 : -1;
      if (editing) focusSeg(d);
      else selectSeg(selIndex < 0 ? 0 : selIndex + d);
      return;
    }

    // Tab / Maj+Tab : balaye les champs de correction (focus) — DANS LES DEUX MODES.
    // En Navigation : entre dans le segment sélectionné, puis enchaîne au suivant/précédent.
    if (e.key === 'Tab') {
      if (!rows().length) return;
      e.preventDefault();
      if (editing) {
        focusSeg(e.shiftKey ? -1 : 1);
      } else {
        let i = selIndex;
        if (i < 0) i = e.shiftKey ? rows().length - 1 : 0;
        enterEdit(i);
      }
      return;
    }

    // Édition de segments : split (Ctrl+Entrée), fusion (Suppr en fin / Backspace au début)
    if (editing && document.activeElement.classList
        && document.activeElement.classList.contains('seg-text')) {
      const el = document.activeElement;
      const i = parseInt(el.dataset.i, 10);
      if (!isNaN(i)) {
        if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
          e.preventDefault(); splitAt(i, caretOffset(el)); return;
        }
        const off = caretOffset(el), len = (el.textContent || '').length;
        if (e.key === 'Delete' && off >= len && i < segments.length - 1) {
          e.preventDefault(); mergeAt(i, i + 1); return;        // fusion avec le suivant
        }
        if (e.key === 'Backspace' && off === 0 && i > 0) {
          e.preventDefault(); mergeAt(i - 1, i); return;        // fusion avec le précédent
        }
      }
    }

    if (editing) return;  // en Édition, le reste des touches sert à taper

    // ── MODE NAVIGATION : transport audio + sélection de segment (sans focus). ──
    if (e.key === 'ArrowUp') { e.preventDefault(); selectSeg(selIndex < 0 ? 0 : selIndex - 1); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); selectSeg(selIndex < 0 ? 0 : selIndex + 1); return; }
    if (e.key === 'Enter') { e.preventDefault(); enterEdit(selIndex); return; }
    if (e.key === 'ArrowLeft') { e.preventDefault(); skip(-5); return; }
    if (e.key === 'ArrowRight') { e.preventDefault(); skip(5); return; }
    if (e.code === 'Space') { e.preventDefault(); togglePlay(); return; }
    const k = e.key.toLowerCase();
    if (k === 'j') { e.preventDefault(); shuttleReverse(); return; }
    if (k === 'k') { e.preventDefault(); shuttleStop(); return; }
    if (k === 'l') { e.preventDefault(); shuttleForward(); return; }
  });

  /* ── Finaliser ──────────────────────────────────────────────────────── */
  const finalizeBtn = document.getElementById('finalizeBtn');
  if (finalizeBtn) {
    finalizeBtn.addEventListener('click', function () {
      clearTimeout(saveTimer);
      save('done');
    });
  }

  // Avertir si modifications non enregistrées
  window.addEventListener('beforeunload', function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ''; }
  });

  /* ── Init ───────────────────────────────────────────────────────────── */
  /* ── Calque de ticks de segments (overlay mappé sur le TEMPS) ───────── */
  // Indépendant du décodage de l'onde → marche aussi sur la timeline de repli.
  // Fondation réutilisée par la heatmap (Phase 2).
  function waveformEl() {
    const c = document.getElementById('audioPlayer_' + playerId);
    return c ? c.querySelector('.wama-waveform') : null;
  }
  function renderTicks() {
    const a = audio();
    const dur = a && a.duration;
    const wrap = waveformEl();
    if (!wrap || !dur || !isFinite(dur)) return;
    wrap.querySelectorAll('.seg-tick').forEach(function (t) { t.remove(); });
    const frag = document.createDocumentFragment();
    segments.forEach(function (s, i) {
      if (i === 0) return;  // pas de tick au tout début
      const pct = Math.max(0, Math.min(100, ((s.start_time || 0) / dur) * 100));
      const tick = document.createElement('div');
      tick.className = 'seg-tick';
      tick.style.left = pct + '%';
      frag.appendChild(tick);
    });
    wrap.appendChild(frag);
  }

  /* ── Heatmap qualité par segment (Phase 2) ─────────────────────────── */
  // Couleur = sévérité : cohérence IA par-segment si dispo (Phase 2b :
  // s.coh_severity / s.coh_note), sinon confiance ASR (Whisper avg_logprob).
  function confidenceSeverity(c) {
    if (c == null) return 'none';
    if (c >= -0.4) return 'ok';
    if (c >= -0.8) return 'warn';
    return 'error';
  }
  const SEV_COLOR = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', none: '#3a3a42' };
  function segTooltip(s, i) {
    let t = 'Segment ' + (i + 1);
    if (s.confidence != null) t += ' · confiance ' + Number(s.confidence).toFixed(2);
    if (s.coh_note) t += '\n⚠ ' + s.coh_note;
    return t;
  }
  function renderHeatmap() {
    const a = audio(); const dur = a && a.duration;
    const band = document.getElementById('segHeatmap');
    if (!band || !dur || !isFinite(dur)) return;
    band.innerHTML = '';
    const frag = document.createDocumentFragment();
    segments.forEach(function (s, i) {
      const st = s.start_time || 0, en = s.end_time || st;
      const left = Math.max(0, Math.min(100, st / dur * 100));
      const w = Math.max(0.3, Math.min(100 - left, (en - st) / dur * 100));
      const sev = s.coh_severity || confidenceSeverity(s.confidence);
      const z = document.createElement('div');
      z.className = 'hz';
      z.style.left = left + '%';
      z.style.width = w + '%';
      z.style.background = SEV_COLOR[sev] || SEV_COLOR.none;
      z.title = segTooltip(s, i);
      z.addEventListener('click', function () {
        if (window.WamaAudioPlayer) WamaAudioPlayer.seek(playerId, st, true);
        selectSeg(i);
      });
      frag.appendChild(z);
    });
    band.appendChild(frag);
    const legend = document.getElementById('heatmapLegend');
    if (legend) legend.style.display = 'flex';
  }
  function renderOverlays() { renderTicks(); renderHeatmap(); }

  document.addEventListener('DOMContentLoaded', function () {
    render();
    initTransport();
    if (window.WamaAudioPlayer) {
      const a = WamaAudioPlayer.getAudio(playerId);
      if (a) {
        a.playbackRate = playbackRate;
        a.addEventListener('timeupdate', function () {
          highlight(indexAt(a.currentTime));
        });
        a.addEventListener('loadedmetadata', renderOverlays);
        if (a.duration) renderOverlays();
      }
    }
  });
})();
