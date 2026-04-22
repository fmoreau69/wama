/**
 * WamaBatchImport — Common batch import component for all Type A apps.
 *
 * Returns an API object: { detectAndHandle(file) -> bool }
 * Hooks batch bar buttons automatically.
 * Optionally hooks drop zone + file input if dropZoneId/fileInputId are provided
 * (use for new apps; existing apps call detectAndHandle() from their own handleFiles).
 *
 * Usage — new app (auto-hooks events):
 *
 *   window._batchImport = WamaBatchImport({
 *     dropZoneId:      'dropZoneXxx',
 *     fileInputId:     'file-input-id',
 *     batchPreviewUrl: '/app/batch/preview/',
 *     batchCreateUrl:  '/app/batch/create/',
 *     csrfToken:       '{{ csrf_token }}',
 *     afterCreate:     function(data, autoStart) { location.reload(); },
 *   });
 *
 * Usage — existing app (manual integration):
 *
 *   window._batchImport = WamaBatchImport({
 *     batchPreviewUrl: '...',
 *     batchCreateUrl:  '...',
 *     csrfToken:       '...',
 *     formDataBuilder: function(fd) { fd.append('backend', 'auto'); },
 *     afterCreate:     function(data, autoStart) { ... },
 *   });
 *   // In the app's handleFiles():
 *   if (files.length === 1 && window._batchImport.detectAndHandle(files[0])) return;
 *
 * Expected DOM (provided by common/batch_detect_bar.html include):
 *   #batchDetectBar, #batchDetectedCount, #batchDetectPreview,
 *   #batchDetectWarnings, #batchDetectTable, #batchCreateCount,
 *   #batchCreateAndStartBtn, #batchCreateOnlyBtn, #batchPreviewBtn,
 *   #batchCancelBar, #batchCreateProgress
 */

function WamaBatchImport(cfg) {
  'use strict';

  // Default: only plain-text formats can be batch descriptor files.
  // Binary formats (pdf, docx, images, audio, video) are always direct media —
  // they must never be misidentified as batch lists of URLs/paths.
  // Override per-app with cfg.batchExtensions if needed (rare edge case).
  const BATCH_EXTS = cfg.batchExtensions || ['txt', 'md', 'csv'];
  let _file = null;

  // ── Helpers ────────────────────────────────────────────────────────────────

  function el(id) { return document.getElementById(id); }

  function escHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function isBatch(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!BATCH_EXTS.includes(ext)) return false;
    // Additional guard: binary MIME types are never batch descriptors regardless of extension.
    const mime = file.type || '';
    if (mime && !mime.startsWith('text/') && mime !== 'application/octet-stream') return false;
    return true;
  }

  // ── Bar visibility ─────────────────────────────────────────────────────────

  function showBar(count) {
    const bar = el('batchDetectBar');
    const cnt = el('batchDetectedCount');
    const prv = el('batchDetectPreview');
    if (!bar) return;
    if (cnt) cnt.textContent = count;
    if (prv) prv.style.display = 'none';
    bar.style.display = '';
  }

  function hideBar() {
    _file = null;
    const bar = el('batchDetectBar');
    const prv = el('batchDetectPreview');
    if (bar) bar.style.display = 'none';
    if (prv) prv.style.display = 'none';
  }

  // ── Preview ────────────────────────────────────────────────────────────────

  function defaultBuildRow(item) {
    return `<tr><td class="text-truncate" style="max-width:200px;" title="${escHtml(item.path)}">${escHtml(item.filename || item.path)}</td></tr>`;
  }

  function populatePreview(data) {
    const tbody   = el('batchDetectTable');
    const cntSpan = el('batchCreateCount');
    const warnEl  = el('batchDetectWarnings');
    const prv     = el('batchDetectPreview');
    if (!tbody) return;

    tbody.innerHTML = '';
    const buildRow = cfg.buildRow || defaultBuildRow;
    (data.items || []).forEach(item => {
      tbody.insertAdjacentHTML('beforeend', buildRow(item));
    });

    if (cntSpan) cntSpan.textContent = data.count;
    if (warnEl) {
      if (data.warnings && data.warnings.length) {
        warnEl.textContent = data.warnings.join(' | ');
        warnEl.style.display = '';
      } else {
        warnEl.style.display = 'none';
      }
    }
    if (prv) prv.style.display = '';
  }

  async function doPreview(file) {
    _file = file;
    const fd = new FormData();
    fd.append('batch_file', file);
    fd.append('csrfmiddlewaretoken', cfg.csrfToken);

    let data;
    try {
      const resp = await fetch(cfg.batchPreviewUrl, { method: 'POST', body: fd });
      data = await resp.json();
    } catch (err) {
      console.error('[batch-import.js] preview error', err);
      hideBar();
      return false;
    }

    if (data.error) {
      _file = null;
      return false;
    }

    if (!data.count) {
      // Server found 0 valid items — file is not a usable batch descriptor.
      // Fall back to direct media upload (e.g. a PDF OCR document, not a URL list).
      _file = null;
      return false;
    }

    showBar(data.count);
    populatePreview(data);
    return true;
  }

  // ── Create ─────────────────────────────────────────────────────────────────

  async function doCreate(autoStart) {
    if (!_file) return;

    const progress = el('batchCreateProgress');
    const startBtn = el('batchCreateAndStartBtn');
    const addBtn   = el('batchCreateOnlyBtn');

    if (progress) progress.style.display = '';
    if (startBtn) startBtn.disabled = true;
    if (addBtn)   addBtn.disabled   = true;

    const fd = new FormData();
    fd.append('batch_file', _file);
    fd.append('csrfmiddlewaretoken', cfg.csrfToken);
    if (typeof cfg.formDataBuilder === 'function') cfg.formDataBuilder(fd);

    let data;
    try {
      const resp = await fetch(cfg.batchCreateUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': cfg.csrfToken },
        body: fd,
      });
      data = await resp.json();
    } catch (err) {
      console.error('[batch-import.js] create error', err);
      if (progress) progress.style.display = 'none';
      if (startBtn) startBtn.disabled = false;
      if (addBtn)   addBtn.disabled   = false;
      return;
    }

    if (progress) progress.style.display = 'none';
    if (startBtn) startBtn.disabled = false;
    if (addBtn)   addBtn.disabled   = false;

    if (data.error) {
      alert('Erreur batch : ' + data.error);
      return;
    }

    hideBar();

    if (typeof cfg.afterCreate === 'function') {
      cfg.afterCreate(data, autoStart);
    } else {
      location.reload();
    }
  }

  // ── Bar buttons ────────────────────────────────────────────────────────────

  function hookBarButtons() {
    el('batchPreviewBtn')?.addEventListener('click', () => {
      if (_file) doPreview(_file);
    });
    el('batchCancelBar')?.addEventListener('click', hideBar);
    el('batchCreateAndStartBtn')?.addEventListener('click', () => doCreate(true));
    el('batchCreateOnlyBtn')?.addEventListener('click',     () => doCreate(false));
  }

  // ── Optional: auto-hook drop zone + file input ─────────────────────────────
  // Used by new apps that don't have their own handleFiles logic.
  // Existing apps call detectAndHandle() from their own handler instead.

  function hookDropZone() {
    const dz = cfg.dropZoneId ? el(cfg.dropZoneId) : null;
    const fi = cfg.fileInputId ? el(cfg.fileInputId) : null;

    if (dz) {
      dz.addEventListener('dragover', e => e.preventDefault());
      dz.addEventListener('drop', async e => {
        e.preventDefault();
        const files = e.dataTransfer?.files;
        if (files) {
          for (const f of files) {
            if (isBatch(f)) { await doPreview(f); return; }
          }
        }
        // Non-batch: let other drop handlers or the app deal with it
      });
    }

    if (fi) {
      fi.addEventListener('change', async function () {
        if (!this.files || !this.files.length) return;
        for (const f of this.files) {
          if (isBatch(f)) {
            await doPreview(f);
            this.value = '';
            return;
          }
        }
      });
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * detectAndHandle(file) — call this from your app's handleFiles() to delegate
   * batch detection. Returns true if the file was identified as a batch file
   * (preview triggered); the caller should then return early.
   */
  async function detectAndHandle(file) {
    if (!isBatch(file)) return false;
    const ok = await doPreview(file);
    return ok !== false;
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    hookBarButtons();
    if (cfg.dropZoneId || cfg.fileInputId) hookDropZone();
  });

  return { detectAndHandle };
}
