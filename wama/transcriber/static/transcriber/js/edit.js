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
  // Indicateur d'enregistrement — présent en double (toolbar haut + volet droit) → on met
  // à jour tous les exemplaires via la classe .t-savestate.
  function setSaveState(html) {
    document.querySelectorAll('.t-savestate').forEach(function (el) { el.innerHTML = html; });
  }
  let activeIndex = -1;
  let dirty = false;
  let followLock = false;   // verrou « suivre la lecture » : la liste suit le playhead même en édition

  // Renommage des locuteurs (speaker_map) — clés canoniques « SPEAKER_NN » → noms.
  let speakerMap = CFG.speakerMap || {};
  function canonSpeaker(raw) {
    if (raw == null) return '';
    const s = String(raw).trim();
    if (!s) return '';
    const m = s.match(/^(?:speaker[\s_\-]*)?(\d+)$/i);
    return m ? 'SPEAKER_' + String(parseInt(m[1], 10)).padStart(2, '0') : s;
  }
  function speakerDisplay(raw) {
    const c = canonSpeaker(raw);
    return (speakerMap && speakerMap[c]) ? speakerMap[c] : c;
  }

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
        '<div class="seg-row' + (s.reviewed ? ' seg-reviewed' : '') + '" data-i="' + i +
          '" data-start="' + (s.start_time || 0) +
          '" data-end="' + (s.end_time || 0) + '">' +
          '<span class="seg-drag" draggable="true" data-i="' + i +
            '" title="Glisser sur un autre segment pour fusionner"><i class="fas fa-grip-vertical"></i></span>' +
          '<span class="seg-time">' + fmt(s.start_time) + '</span>' +
          '<div class="seg-speaker"><input type="text" value="' + esc(s.speaker_id || '') +
            '" placeholder="Loc." data-i="' + i + '">' +
            (function () {
              var nm = speakerDisplay(s.speaker_id);
              return (nm && nm !== (s.speaker_id || '')) ?
                '<span class="seg-spk-name" title="' + esc(nm) + '">' + esc(nm) + '</span>' : '';
            })() +
          '</div>' +
          '<button class="seg-play btn btn-sm btn-outline-info py-0 px-2" data-i="' + i +
            '" title="Écouter ce segment"><i class="fas fa-play fa-xs"></i></button>' +
          '<div class="seg-text-wrap">' +
            '<div class="seg-text" contenteditable="true" data-i="' + i + '" spellcheck="true">' +
              esc(s.text || '') + '</div>' +
          '</div>' +
          '<button class="seg-review btn btn-sm py-0 px-1" data-i="' + i +
            '" title="Marquer revu / non revu"><i class="fas fa-check"></i></button>' +
        '</div>'
      );
    }).join('');
    updateReviewProgress();
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
      // Scroll synchronisé liste ↔ audio : en Navigation (défaut), OU toujours si le verrou
      // « suivre la lecture » est activé (force le suivi même en Édition).
      if (followLock || !inEdit()) {
        const cr = segContainer.getBoundingClientRect();
        const r = row.getBoundingClientRect();
        if (r.top < cr.top + 8 || r.bottom > cr.bottom - 8) {
          row.scrollIntoView({ block: 'center', behavior: 'smooth' });
        }
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
    setSaveState('<i class="fas fa-circle text-warning" style="font-size:.5rem;"></i> Modifié…');
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () { save('draft'); }, 800);
  }
  function save(status) {
    setSaveState('<i class="fas fa-spinner fa-spin"></i> Enregistrement…');
    return fetch(CFG.saveUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CFG.csrfToken },
      body: JSON.stringify({ segments: segments, status: status || 'draft' }),
    })
      .then(function (r) { return r.json(); })
      .then(function () {
        dirty = false;
        setSaveState((status === 'done')
          ? '<i class="fas fa-check-double text-success"></i> Correction terminée'
          : '<i class="fas fa-check text-success"></i> À jour');
      })
      .catch(function () {
        setSaveState('<i class="fas fa-triangle-exclamation text-danger"></i> Erreur');
      });
  }

  /* ── Événements d'édition ───────────────────────────────────────────── */
  // AVANT toute mutation du texte/locuteur → fige l'état d'avant-rafale dans l'historique
  // (DOM et `segments` encore intacts ici). Une rafale de frappe = une seule entrée undo.
  segContainer.addEventListener('beforeinput', function (e) {
    const el = e.target;
    if (el && (el.classList && el.classList.contains('seg-text') || el.tagName === 'INPUT')) {
      beginTextBurst();
    }
  });
  segContainer.addEventListener('input', function (e) {
    const el = e.target;
    const i = parseInt(el.dataset.i, 10);
    if (isNaN(i)) return;
    if (el.classList.contains('seg-text')) { segments[i].text = el.textContent; markReviewed(i); markDirty(); }
    else if (el.tagName === 'INPUT') { segments[i].speaker_id = el.value; markReviewed(i); markDirty(); }
  });

  /* ── Suivi de relecture : « revu » auto à l'édition + bascule manuelle (✓) ──── */
  function markReviewed(i) {
    if (segments[i] && !segments[i].reviewed) {
      segments[i].reviewed = true;
      const row = segContainer.querySelector('.seg-row[data-i="' + i + '"]');
      if (row) row.classList.add('seg-reviewed');
      updateReviewProgress();
    }
  }
  function updateReviewProgress() {
    const total = segments.length;
    let done = 0;
    for (let k = 0; k < total; k++) { if (segments[k] && segments[k].reviewed) done++; }
    const cnt = document.getElementById('reviewCount');
    const fill = document.getElementById('reviewBarFill');
    if (cnt) cnt.textContent = done + ' / ' + total;
    if (fill) fill.style.width = (total ? (done / total * 100) : 0) + '%';
  }

  // Clic ✓ → bascule « revu » manuellement
  segContainer.addEventListener('click', function (e) {
    const rev = e.target.closest('.seg-review');
    if (rev) {
      const i = parseInt(rev.dataset.i, 10);
      if (!isNaN(i) && segments[i]) {
        segments[i].reviewed = !segments[i].reviewed;
        const row = rev.closest('.seg-row');
        if (row) row.classList.toggle('seg-reviewed', !!segments[i].reviewed);
        updateReviewProgress(); markDirty();
      }
      return;
    }
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

  /* ── Drag & drop : glisser un segment (poignée ⋮⋮) sur un autre → fusion ──── */
  let _dragIndex = -1;
  segContainer.addEventListener('dragstart', function (e) {
    const h = e.target.closest('.seg-drag');
    if (!h) return;
    _dragIndex = parseInt(h.dataset.i, 10);
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', String(_dragIndex)); } catch (_) {}
    const row = h.closest('.seg-row');
    if (row) row.classList.add('seg-dragging');
  });
  segContainer.addEventListener('dragover', function (e) {
    if (_dragIndex < 0) return;
    const row = e.target.closest('.seg-row');
    if (!row) return;
    e.preventDefault();                                // autorise le drop
    e.dataTransfer.dropEffect = 'move';
    segContainer.querySelectorAll('.seg-drop-target').forEach(function (r) { r.classList.remove('seg-drop-target'); });
    const j = parseInt(row.dataset.i, 10);
    if (j !== _dragIndex) row.classList.add('seg-drop-target');
  });
  segContainer.addEventListener('drop', function (e) {
    if (_dragIndex < 0) return;
    const row = e.target.closest('.seg-row');
    if (row) {
      e.preventDefault();
      const j = parseInt(row.dataset.i, 10);
      if (!isNaN(j) && j !== _dragIndex) mergeRange(_dragIndex, j);
    }
    _dragIndex = -1;
  });
  segContainer.addEventListener('dragend', function () {
    _dragIndex = -1;
    segContainer.querySelectorAll('.seg-dragging, .seg-drop-target').forEach(function (r) {
      r.classList.remove('seg-dragging', 'seg-drop-target');
    });
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

  // Une seule lecture audio à la fois : démarrer une lecture met en pause toutes les autres
  // (évite la superposition player principal ↔ aperçu audio du volet droit, etc.).
  // 'play' ne bulle pas → écoute en phase de capture.
  document.addEventListener('play', function (e) {
    const playing = e.target;
    document.querySelectorAll('audio, video').forEach(function (m) {
      if (m !== playing && !m.paused) { try { m.pause(); } catch (_) {} }
    });
  }, true);

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
  // Paliers fins (1.25/1.5/1.75) entre 1 et 2 — comme les boutons vitesse — puis
  // accélération rapide (4/8/16) pour le scrubbing. Symétrique en arrière.
  const SHUTTLE = [-16, -8, -4, -2, -1.75, -1.5, -1.25, -1, 0, 1, 1.25, 1.5, 1.75, 2, 4, 8, 16];
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
  // Navigation audio : relocalise la lecture au début du segment suivant (dir=1)
  // ou précédent (dir=-1), relativement à la position courante. Conserve l'état
  // lecture/pause (seek sans forcer play) + surligne le segment ciblé.
  function seekSegment(dir) {
    const a = audio(); if (!a || !segments.length) return;
    let cur = indexAt(a.currentTime || 0);
    if (cur < 0) {  // hors d'un segment → dernier dont le début précède la position
      cur = 0;
      for (let k = 0; k < segments.length; k++) {
        if ((segments[k].start_time || 0) <= (a.currentTime || 0)) cur = k;
      }
    }
    const i = Math.max(0, Math.min(segments.length - 1, cur + dir));
    selectSeg(i);
    if (window.WamaAudioPlayer) WamaAudioPlayer.seek(playerId, segments[i].start_time || 0, false);
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
    _burstActive = false;  // quitter un champ ferme la rafale → la frappe suivante = nouvelle entrée undo
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
  /* ── Historique undo / redo (état complet des segments) ────────────── */
  // Couvre TOUTES les modifs : texte, locuteur, scission, fusion, compactage,
  // load-latest. Les frappes sont coalescées en « rafales » (1 entrée par burst).
  let undoStack = [];
  let redoStack = [];
  let _burstActive = false;   // une rafale de frappe est en cours (déjà snapshotée)
  let _burstTimer = null;
  const MAX_HISTORY = 100;
  function snapshot() { return JSON.parse(JSON.stringify(segments)); }
  function pushHistory() {
    undoStack.push(snapshot());
    if (undoStack.length > MAX_HISTORY) undoStack.shift();
    redoStack.length = 0;
    _burstActive = false;     // une nouvelle action structurelle ferme la rafale
    updateUndoButtons();
  }
  // Fige l'état AVANT une rafale de frappe (beforeinput → DOM/segments encore intacts).
  function beginTextBurst() {
    if (!_burstActive) { pushHistory(); _burstActive = true; }
    clearTimeout(_burstTimer);
    _burstTimer = setTimeout(function () { _burstActive = false; }, 900);  // fin après 0,9 s
  }
  function restoreState(state) {
    segments.length = 0; Array.prototype.push.apply(segments, state);
    render(); renderOverlays(); markDirty(); updateUndoButtons();
  }
  function undo() {
    if (!undoStack.length) return;
    redoStack.push(snapshot());
    restoreState(undoStack.pop());
  }
  function redo() {
    if (!redoStack.length) return;
    undoStack.push(snapshot());
    restoreState(redoStack.pop());
  }
  function updateUndoButtons() {
    document.querySelectorAll('.t-undo').forEach(function (b) { b.disabled = !undoStack.length; });
    document.querySelectorAll('.t-redo').forEach(function (b) { b.disabled = !redoStack.length; });
  }

  function splitAt(i, off) {                          // Ctrl+Entrée
    pushHistory();
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
    pushHistory();
    const a = segments[i], b = segments[j];
    const join = (a.text || '').trim().length + 1;    // position du curseur à la jonction
    a.text = ((a.text || '').trim() + ' ' + (b.text || '').trim()).trim();
    a.end_time = b.end_time; a.words = undefined;
    segments.splice(j, 1);
    refresh(); enterEditAt(i, join);
  }
  function mergeRange(a, b) {                         // drag&drop : fusionne la plage [min..max]
    const lo = Math.min(a, b), hi = Math.max(a, b);
    if (lo === hi || lo < 0 || hi >= segments.length) return;
    pushHistory();
    const first = segments[lo];
    const parts = [];
    for (let k = lo; k <= hi; k++) {
      const tx = (segments[k].text || '').trim();
      if (tx) parts.push(tx);
    }
    first.text = parts.join(' ').trim();
    first.end_time = segments[hi].end_time;            // borne temporelle = fin du dernier
    first.words = undefined;
    segments.splice(lo + 1, hi - lo);                  // retire les segments fusionnés
    refresh();
    selectSeg(lo);
  }
  function compact() {                               // fusionne segments consécutifs même locuteur
    pushHistory();
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
  // Boutons d'action présents en double (toolbar haut + volet droit) → bind sur tous via classe.
  document.querySelectorAll('.t-compact').forEach(function (b) { b.addEventListener('click', compact); });
  document.querySelectorAll('.t-undo').forEach(function (b) { b.addEventListener('click', undo); });
  document.querySelectorAll('.t-redo').forEach(function (b) { b.addEventListener('click', redo); });

  // Verrou « suivre la lecture » : la liste suit le playhead même en édition (Alt+L / bouton).
  const followLockBtn = document.getElementById('followLockBtn');
  function applyFollowLock() {
    if (!followLockBtn) return;
    followLockBtn.classList.toggle('btn-info', followLock);
    followLockBtn.classList.toggle('btn-outline-light', !followLock);
    followLockBtn.innerHTML = followLock ? '<i class="fas fa-lock"></i>' : '<i class="fas fa-lock-open"></i>';
    followLockBtn.title = (followLock ? 'Suivi de lecture ACTIVÉ — clic ou Alt+L pour débrayer'
                                      : 'Suivre la lecture (la liste suit l\'audio même en édition) — Alt+L');
  }
  function toggleFollowLock() {
    followLock = !followLock;
    try { localStorage.setItem('wama_transcriber_followlock', followLock ? '1' : '0'); } catch (_) {}
    applyFollowLock();
    if (followLock && activeIndex >= 0) {                        // recentre immédiatement
      const row = segContainer.querySelector('.seg-row[data-i="' + activeIndex + '"]');
      if (row) row.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }
  followLock = localStorage.getItem('wama_transcriber_followlock') === '1';
  applyFollowLock();
  if (followLockBtn) followLockBtn.addEventListener('click', toggleFollowLock);

  // Hauteur de la zone d'édition : seuls les champs défilent (toolbar + player + footer fixes).
  function sizeSegments() {
    if (!segContainer) return;
    const top = segContainer.getBoundingClientRect().top;     // position dans le viewport
    const bar = document.getElementById('editorAudiobar');
    const reserve = 40 + (bar ? bar.offsetHeight : 0) + 16;    // footer (40) + barre audio + marge
    segContainer.style.maxHeight = Math.max(160, window.innerHeight - top - reserve) + 'px';
  }
  window.addEventListener('resize', sizeSegments);

  // Réduire / afficher le player fixe en bas (libère de l'espace pour le texte).
  const audiobar = document.getElementById('editorAudiobar');
  const audiobarToggle = document.getElementById('audiobarToggle');
  if (audiobar && audiobarToggle) {
    const KEY = 'wama_transcriber_audiobar_collapsed';
    function applyCollapsed(c) {
      audiobar.classList.toggle('collapsed', c);
      sizeSegments();   // la barre change de hauteur → recalcule la zone scrollable
    }
    applyCollapsed(localStorage.getItem(KEY) === '1');
    audiobarToggle.addEventListener('click', function () {
      const c = !audiobar.classList.contains('collapsed');
      applyCollapsed(c);
      try { localStorage.setItem(KEY, c ? '1' : '0'); } catch (_) {}
    });
  }
  sizeSegments();                       // calcul initial
  setTimeout(sizeSegments, 350);        // re-calcul après layout tardif (onde/player)


  /* ── Volet droit : métadonnées (titre + date) ───────────────────────── */
  function saveMeta(payload) {
    if (!CFG.saveMetaUrl) return;
    fetch(CFG.saveMetaUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': CFG.csrfToken },
      body: JSON.stringify(payload),
    }).catch(function () {});
  }
  let metaTimer = null;
  function scheduleMetaSave() {
    clearTimeout(metaTimer);
    metaTimer = setTimeout(function () {
      const titleEl = document.getElementById('metaTitle');
      const dateEl = document.getElementById('metaDate');
      saveMeta({ title: titleEl ? titleEl.value : '', meeting_date: dateEl ? (dateEl.value || null) : null });
    }, 700);
  }
  ['metaTitle', 'metaDate'].forEach(function (id) {
    const el = document.getElementById(id);
    if (el) el.addEventListener('input', scheduleMetaSave);
  });

  /* ── Volet droit : intervenants (renommage en une passe) ────────────── */
  function buildSpeakerList() {
    const host = document.getElementById('speakerList');
    const empty = document.getElementById('speakerEmpty');
    if (!host) return;
    // Locuteurs canoniques présents, dans l'ordre d'apparition.
    const seen = [];
    segments.forEach(function (s) {
      const c = canonSpeaker(s.speaker_id);
      if (c && seen.indexOf(c) === -1) seen.push(c);
    });
    if (!seen.length) {
      host.innerHTML = '';
      if (empty) empty.style.display = 'block';
      return;
    }
    if (empty) empty.style.display = 'none';
    host.innerHTML = seen.map(function (c) {
      const val = speakerMap[c] || '';
      return '<div class="spk-row"><span class="spk-label">' + esc(c) + '</span>' +
        '<input type="text" data-spk="' + esc(c) + '" placeholder="Nom de l\'intervenant" value="' + esc(val) + '"></div>';
    }).join('');
  }
  // Identification automatique des intervenants (IA) → pré-remplit les champs (sans appliquer).
  const suggestSpeakersBtn = document.getElementById('suggestSpeakersBtn');
  if (suggestSpeakersBtn) {
    suggestSpeakersBtn.addEventListener('click', function () {
      if (!CFG.suggestSpeakersUrl) return;
      const orig = suggestSpeakersBtn.innerHTML;
      suggestSpeakersBtn.disabled = true;
      suggestSpeakersBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Analyse en cours…';
      fetch(CFG.suggestSpeakersUrl, { method: 'POST', headers: { 'X-CSRFToken': CFG.csrfToken } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          const sug = (data && data.suggestions) || {};
          let n = 0;
          Object.keys(sug).forEach(function (sid) {
            const inp = document.querySelector('#speakerList input[data-spk="' + sid + '"]');
            if (inp && !inp.value.trim()) { inp.value = sug[sid]; n++; }  // ne pas écraser une saisie manuelle
          });
          suggestSpeakersBtn.innerHTML = n
            ? '<i class="fas fa-check"></i> ' + n + ' nom(s) proposé(s) — vérifiez puis Appliquer'
            : '<i class="fas fa-circle-info"></i> Aucun nom détecté';
        })
        .catch(function () { suggestSpeakersBtn.innerHTML = '<i class="fas fa-triangle-exclamation"></i> Erreur'; })
        .finally(function () {
          suggestSpeakersBtn.disabled = false;
          setTimeout(function () { suggestSpeakersBtn.innerHTML = orig; }, 3000);
        });
    });
  }

  const applySpeakersBtn = document.getElementById('applySpeakersBtn');
  if (applySpeakersBtn) {
    applySpeakersBtn.addEventListener('click', function () {
      const map = {};
      document.querySelectorAll('#speakerList input[data-spk]').forEach(function (inp) {
        const name = (inp.value || '').trim();
        if (name) map[inp.dataset.spk] = name;
      });
      speakerMap = map;
      saveMeta({ speaker_map: map });
      render(); renderOverlays();  // ré-affiche les chips de noms dans les segments
      const old = applySpeakersBtn.innerHTML;
      applySpeakersBtn.innerHTML = '<i class="fas fa-check"></i> Noms appliqués';
      setTimeout(function () { applySpeakersBtn.innerHTML = old; }, 1500);
    });
  }
  buildSpeakerList();  // la liste des intervenants est toujours visible dans le volet droit

  // « Charger la dernière transcription » : remplace la correction par la dernière
  // génération ASR (l'utilisateur garde sa correction tant qu'il ne clique pas).
  const loadLatestBtn = document.getElementById('loadLatestBtn');
  if (loadLatestBtn) {
    loadLatestBtn.addEventListener('click', function () {
      let latest = [];
      try { latest = JSON.parse(document.getElementById('latestData').textContent) || []; } catch (_) {}
      if (!latest.length) { alert('Aucune nouvelle transcription disponible.'); return; }
      if (!confirm('Charger la dernière transcription générée ?\nVotre correction actuelle sera remplacée (annulable avec Ctrl+Z).')) return;
      pushHistory();
      segments.length = 0; Array.prototype.push.apply(segments, latest);
      refresh();  // re-render + ticks + heatmap + auto-save (devient la nouvelle base corrigée)
      const banner = loadLatestBtn.closest('.alert');
      if (banner) banner.style.display = 'none';
    });
  }

  document.addEventListener('keydown', function (e) {
    const editing = inEdit();

    // Frappe dans un champ (timecode, locuteur, recherche…) → ne pas déclencher les raccourcis
    // de transport/navigation (J/K/L, Espace, ←/→…). On laisse passer Ctrl/Alt + Échap.
    const tgt = e.target;
    if (tgt && (tgt.tagName === 'INPUT' || tgt.tagName === 'TEXTAREA' || tgt.tagName === 'SELECT')
        && !e.ctrlKey && !e.metaKey && !e.altKey && e.key !== 'Escape') {
      return;
    }

    // Undo/Redo (Ctrl+Z / Ctrl+Maj+Z / Ctrl+Y) — dans LES DEUX modes. On remplace
    // l'annulation native du contenteditable par l'historique applicatif : source de
    // vérité unique couvrant texte, locuteur, scission, fusion, compactage, load-latest.
    if (e.ctrlKey || e.metaKey) {
      const k = e.key.toLowerCase();
      // restoreState() reconstruit le DOM (le champ édité disparaît) → on ferme la rafale
      // en cours pour que la frappe d'après recrée une entrée d'historique propre.
      if (k === 'z') { _burstActive = false; e.preventDefault(); e.shiftKey ? redo() : undo(); return; }
      if (k === 'y') { _burstActive = false; e.preventDefault(); redo(); return; }
    }

    // Alt+L : (dé)verrouille le suivi de lecture (les deux modes).
    if (e.altKey && (e.key === 'l' || e.key === 'L')) { e.preventDefault(); toggleFollowLock(); return; }

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

    // Tab / Maj+Tab :
    //  - Édition : champ de correction suivant/précédent (inchangé).
    //  - Navigation : relocalise la LECTURE AUDIO au début du segment suivant/précédent
    //    (complément de J/K/L) + sélection. N'entre PAS en édition (utiliser Entrée pour ça).
    if (e.key === 'Tab') {
      if (!segments.length) return;
      e.preventDefault();
      if (editing) focusSeg(e.shiftKey ? -1 : 1);
      else seekSegment(e.shiftKey ? -1 : 1);
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
  document.querySelectorAll('.t-finalize').forEach(function (b) {
    b.addEventListener('click', function () {
      clearTimeout(saveTimer);
      save('done');
    });
  });

  // Avertir si modifications non enregistrées
  window.addEventListener('beforeunload', function (e) {
    if (dirty) { e.preventDefault(); e.returnValue = ''; }
  });

  /* ── Visualisation audio (onde zoomable + heatmap + mini-map) ───────── */
  // Sévérité = cohérence IA par-segment (coh_severity) sinon confiance ASR (avg_logprob).
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

  /* ── Forme d'onde ZOOMABLE (Phase B) : peaks serveur + rendu fenêtré ─── */
  let peaks = null, peaksDur = 0, peaksReady = false;
  let viewStart = 0, viewDur = 0;          // fenêtre visible (secondes)
  const MIN_VIEW = 4;                       // zoom max : fenêtre de 4 s
  const DEFAULT_VIEW = 240;                  // fenêtre initiale (s) : on ouvre déjà zoomé → onde visible d'emblée
  const LEGIBLE_PXPS = 1.5;                  // seuil bas → l'onde apparaît avec peu de zoom (mini-map = vue d'ensemble)

  function fullDur() {
    const a = audio();
    return (a && isFinite(a.duration) && a.duration) ? a.duration : (peaksDur || 0);
  }
  function clampView() {
    const D = fullDur(); if (!D) return;
    if (!viewDur || viewDur > D) viewDur = D;
    viewDur = Math.max(MIN_VIEW, Math.min(D, viewDur));
    viewStart = Math.max(0, Math.min(D - viewDur, viewStart));
  }
  function updateZoomLabel() {
    const el = document.getElementById('zoomLabel'); if (!el) return;
    const D = fullDur();
    el.textContent = (D && viewDur) ? ('×' + (D / viewDur).toFixed(1)) : '×1';
  }

  function drawZoom() {
    const cv = document.getElementById('zoomWave'); if (!cv) return;
    const D = fullDur(); if (!D) return;
    clampView();
    const W = cv.clientWidth || 600, H = cv.clientHeight || 54;
    if (cv.width !== W) cv.width = W;
    if (cv.height !== H) cv.height = H;
    const ctx = cv.getContext('2d');
    ctx.clearRect(0, 0, W, H);
    const pxps = W / viewDur, mid = H / 2;
    if (peaksReady && peaks && peaks.length && pxps >= LEGIBLE_PXPS) {
      const N = peaks.length;
      ctx.fillStyle = '#3b82f6';
      for (let x = 0; x < W; x++) {
        const t0 = viewStart + (x / W) * viewDur;
        const t1 = viewStart + ((x + 1) / W) * viewDur;
        let i0 = Math.max(0, Math.min(N - 1, Math.floor(t0 / D * N)));
        const i1 = Math.max(i0 + 1, Math.min(N, Math.ceil(t1 / D * N)));
        let m = 0;
        for (let k = i0; k < i1; k++) { if (peaks[k] > m) m = peaks[k]; }
        const h = (m / 255) * (H - 4);
        ctx.fillRect(x, mid - h / 2, 1, Math.max(1, h));
      }
    } else {
      ctx.fillStyle = '#5a5f68'; ctx.font = '11px sans-serif'; ctx.textAlign = 'center';
      ctx.fillText(!peaksReady ? 'Calcul de la forme d’onde…'
                               : 'Zoomez pour afficher la forme d’onde', W / 2, mid + 4);
    }
    // Ticks de segments dans la fenêtre
    ctx.strokeStyle = 'rgba(255,255,255,0.22)'; ctx.lineWidth = 1;
    for (let i = 1; i < segments.length; i++) {
      const t = segments[i].start_time || 0;
      if (t < viewStart || t > viewStart + viewDur) continue;
      const x = (t - viewStart) / viewDur * W;
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke();
    }
    // Playhead
    const a = audio();
    if (a && isFinite(a.currentTime)) {
      const x = (a.currentTime - viewStart) / viewDur * W;
      if (x >= 0 && x <= W) {
        ctx.strokeStyle = '#0dcaf0'; ctx.lineWidth = 2;
        ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); ctx.lineWidth = 1;
      }
    }
  }

  // Heatmap FENÊTRÉE : zones repositionnées dans [viewStart, viewStart+viewDur].
  function renderHeatmap() {
    const band = document.getElementById('segHeatmap');
    const D = fullDur(); if (!band || !D) return;
    clampView();
    band.innerHTML = '';
    const frag = document.createDocumentFragment();
    segments.forEach(function (s, i) {
      const st = s.start_time || 0, en = s.end_time || st;
      if (en < viewStart || st > viewStart + viewDur) return;     // hors fenêtre
      const L = Math.max(0, (st - viewStart) / viewDur * 100);
      const R = Math.min(100, (en - viewStart) / viewDur * 100);
      const sev = s.coh_severity || confidenceSeverity(s.confidence);
      const z = document.createElement('div');
      z.className = 'hz';
      z.style.left = L + '%';
      z.style.width = Math.max(0.4, R - L) + '%';
      z.style.background = SEV_COLOR[sev] || SEV_COLOR.none;
      z.title = segTooltip(s, i);
      z.addEventListener('click', function () {
        if (window.WamaAudioPlayer) WamaAudioPlayer.seek(playerId, st, true);
        selectSeg(i);
      });
      frag.appendChild(z);
    });
    band.appendChild(frag);
  }

  // Mini-map : heatmap pleine durée + rectangle de la fenêtre visible.
  function drawMini() {
    const cv = document.getElementById('zoomMini'); if (!cv) return;
    const D = fullDur(); if (!D) return;
    const W = cv.clientWidth || 600, H = cv.clientHeight || 14;
    if (cv.width !== W) cv.width = W;
    if (cv.height !== H) cv.height = H;
    const ctx = cv.getContext('2d'); ctx.clearRect(0, 0, W, H);
    segments.forEach(function (s) {
      const st = s.start_time || 0, en = s.end_time || st;
      const x = st / D * W, w = Math.max(1, (en - st) / D * W);
      const sev = s.coh_severity || confidenceSeverity(s.confidence);
      ctx.fillStyle = SEV_COLOR[sev] || SEV_COLOR.none;
      ctx.fillRect(x, 0, w, H);
    });
    const vx = viewStart / D * W, vw = Math.max(2, viewDur / D * W);
    ctx.fillStyle = 'rgba(13,202,240,0.18)'; ctx.fillRect(vx, 0, vw, H);
    ctx.strokeStyle = '#0dcaf0'; ctx.lineWidth = 1.5;
    ctx.strokeRect(vx + 0.5, 0.5, Math.max(1, vw - 1), H - 1);
  }

  function redrawWindow() { clampView(); drawZoom(); renderHeatmap(); drawMini(); updateZoomLabel(); }
  function renderOverlays() { redrawWindow(); }     // remplace ticks+heatmap pleine durée

  /* ── Zoom : interactions ────────────────────────────────────────────── */
  function setZoom(newViewDur, centerT) {
    const D = fullDur(); if (!D) return;
    const a = audio();
    const c = (centerT != null) ? centerT : (a ? a.currentTime : viewStart + viewDur / 2);
    viewDur = Math.max(MIN_VIEW, Math.min(D, newViewDur));
    viewStart = c - viewDur / 2;
    redrawWindow();
  }
  function followWindow() {            // recentre si le playhead sort de la fenêtre
    const a = audio(); if (!a) return false;
    const t = a.currentTime;
    if (t < viewStart || t > viewStart + viewDur) { viewStart = t - viewDur / 2; clampView(); return true; }
    return false;
  }

  /* ── Aller à un timecode (mm:ss / hh:mm:ss / ss) ───────────────────── */
  function parseTimecode(s) {
    s = (s || '').trim();
    if (!s) return null;
    const parts = s.split(':').map(function (p) { return parseFloat(p.replace(',', '.')); });
    if (parts.some(isNaN)) return null;
    let sec;
    if (parts.length === 1) sec = parts[0];
    else if (parts.length === 2) sec = parts[0] * 60 + parts[1];
    else if (parts.length === 3) sec = parts[0] * 3600 + parts[1] * 60 + parts[2];
    else return null;
    return Math.max(0, sec);
  }
  function gotoTimecode() {
    const inp = document.getElementById('gotoTime');
    const sec = parseTimecode(inp && inp.value);
    if (sec == null) { if (inp) { inp.classList.add('is-invalid'); setTimeout(function () { inp.classList.remove('is-invalid'); }, 1200); } return; }
    const D = fullDur();
    const t = D ? Math.min(sec, D) : sec;
    if (window.WamaAudioPlayer) WamaAudioPlayer.seek(playerId, t, false);
    viewStart = t - viewDur / 2; clampView(); redrawWindow();   // recentre la fenêtre d'onde
    const i = indexAt(t); if (i >= 0) { selectSeg(i); }          // surligne/sélectionne le segment
  }
  function initZoomUI() {
    const cv = document.getElementById('zoomWave');
    const mini = document.getElementById('zoomMini');
    const zin = document.getElementById('zoomIn'), zout = document.getElementById('zoomOut');
    if (zin) zin.addEventListener('click', function () { setZoom(viewDur * 0.6); });
    if (zout) zout.addEventListener('click', function () { setZoom(viewDur * 1.7); });
    // Aller à un timecode (bouton + Entrée dans le champ)
    const gotoBtn = document.getElementById('gotoBtn');
    const gotoInp = document.getElementById('gotoTime');
    if (gotoBtn) gotoBtn.addEventListener('click', gotoTimecode);
    if (gotoInp) gotoInp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); gotoTimecode(); }
    });
    if (cv) {
      cv.addEventListener('wheel', function (e) {            // molette = zoom autour du curseur
        e.preventDefault();
        const W = cv.clientWidth || 600;
        const ct = viewStart + (e.offsetX / W) * viewDur;
        setZoom(viewDur * (e.deltaY > 0 ? 1.25 : 0.8), ct);
      }, { passive: false });
      let dragging = false, moved = false, lastX = 0;        // clic = seek ; glisser = déplacer
      cv.addEventListener('mousedown', function (e) { dragging = true; moved = false; lastX = e.clientX; });
      window.addEventListener('mousemove', function (e) {
        if (!dragging) return;
        const W = cv.clientWidth || 600, dx = e.clientX - lastX; lastX = e.clientX;
        if (Math.abs(dx) > 1) moved = true;
        viewStart -= (dx / W) * viewDur; clampView(); redrawWindow();
      });
      window.addEventListener('mouseup', function (e) {
        if (!dragging) return; dragging = false;
        if (!moved) {
          const rect = cv.getBoundingClientRect();
          const t = viewStart + ((e.clientX - rect.left) / (cv.clientWidth || 600)) * viewDur;
          if (window.WamaAudioPlayer) WamaAudioPlayer.seek(playerId, Math.max(0, t), false);
          redrawWindow();
        }
      });
    }
    if (mini) {
      const jump = function (e) {
        const D = fullDur(); if (!D) return;
        const rect = mini.getBoundingClientRect();
        viewStart = ((e.clientX - rect.left) / (mini.clientWidth || 600)) * D - viewDur / 2;
        clampView(); redrawWindow();
      };
      let mdrag = false;
      mini.addEventListener('mousedown', function (e) { mdrag = true; jump(e); });
      window.addEventListener('mousemove', function (e) { if (mdrag) jump(e); });
      window.addEventListener('mouseup', function () { mdrag = false; });
    }
    window.addEventListener('resize', redrawWindow);
  }

  /* ── Récupération asynchrone des peaks (poll jusqu'à prêt) ──────────── */
  function fetchPeaks() {
    if (!CFG.peaksUrl) { peaksReady = true; return; }
    fetch(CFG.peaksUrl).then(function (r) { return r.json(); }).then(function (d) {
      if (d.status === 'ready' && d.peaks) {
        peaks = d.peaks; peaksDur = d.duration || 0; peaksReady = true; redrawWindow();
      } else if (d.status === 'pending') {
        setTimeout(fetchPeaks, 2500);
      } else { peaksReady = true; redrawWindow(); }   // failed → pas d'onde, ticks/heatmap restent
    }).catch(function () { peaksReady = true; });
  }

  document.addEventListener('DOMContentLoaded', function () {
    render();
    initTransport();
    initZoomUI();
    fetchPeaks();
    if (window.WamaAudioPlayer) {
      const a = WamaAudioPlayer.getAudio(playerId);
      if (a) {
        a.playbackRate = playbackRate;
        let raf = null;
        function tick() { drawZoom(); raf = a.paused ? null : requestAnimationFrame(tick); }
        a.addEventListener('play', function () { if (!raf) tick(); });
        a.addEventListener('pause', drawZoom);
        a.addEventListener('seeked', function () { followWindow(); redrawWindow(); });
        a.addEventListener('timeupdate', function () {
          highlight(indexAt(a.currentTime));
          if (followWindow()) redrawWindow();
        });
        a.addEventListener('loadedmetadata', function () { if (!viewDur) viewDur = Math.min(a.duration, DEFAULT_VIEW); redrawWindow(); });
        if (a.duration) { if (!viewDur) viewDur = Math.min(a.duration, DEFAULT_VIEW); redrawWindow(); }
      }
    }
  });
})();
