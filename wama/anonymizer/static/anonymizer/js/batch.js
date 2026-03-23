/**
 * Anonymizer Batch Import
 * Handles .txt/.csv/.md/.pdf/.docx batch files (one URL/path per line).
 * After batch_create, items appear in the queue; user triggers processing
 * via the existing "Démarrer" button or individual item restart buttons.
 */

const AnonymizerBatch = (function () {
    'use strict';

    let _cfg = {};
    let _pendingFile = null;
    let _previewData = null;

    // ── DOM helpers ──────────────────────────────────────────────────────────

    function el(id) { return document.getElementById(id); }

    function getCsrf() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    // ── Batch file detection ─────────────────────────────────────────────────

    const BATCH_EXTS = ['txt', 'csv', 'md', 'pdf', 'docx'];

    function isBatchFile(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        return BATCH_EXTS.includes(ext);
    }

    function handleBatchFile(file) {
        _pendingFile = file;
        _previewData = null;

        // Show detect bar
        el('batchDetectBar').style.display = '';
        el('batchDetectedCount').textContent = '?';
        el('batchDetectPreview').style.display = 'none';

        // Auto-preview
        previewBatch();
    }

    // ── Preview ──────────────────────────────────────────────────────────────

    function previewBatch() {
        if (!_pendingFile) return;

        const fd = new FormData();
        fd.append('batch_file', _pendingFile);
        fd.append('csrfmiddlewaretoken', getCsrf());

        fetch(_cfg.batchPreviewUrl, { method: 'POST', body: fd })
            .then(r => r.json())
            .then(data => {
                if (data.error) { alert('Erreur batch : ' + data.error); cancelBatch(); return; }
                _previewData = data;
                renderPreview(data);
            })
            .catch(err => { console.error('[batch.js] preview error', err); cancelBatch(); });
    }

    function renderPreview(data) {
        el('batchDetectedCount').textContent = data.count;
        el('batchCreateCount').textContent = data.count;

        // Warnings
        const warnEl = el('batchDetectWarnings');
        if (data.warnings && data.warnings.length > 0) {
            warnEl.style.display = '';
            warnEl.textContent = data.warnings.join(' | ');
        } else {
            warnEl.style.display = 'none';
        }

        // Table
        const tbody = el('batchDetectTable');
        tbody.innerHTML = '';
        (data.items || []).forEach(item => {
            const tr = document.createElement('tr');
            tr.innerHTML = `<td class="text-truncate" style="max-width:180px;" title="${escHtml(item.path)}">${escHtml(item.filename || item.path)}</td>`;
            tbody.appendChild(tr);
        });

        el('batchDetectPreview').style.display = '';
    }

    function escHtml(s) {
        return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
    }

    // ── Create ───────────────────────────────────────────────────────────────

    function createBatch(andStart) {
        if (!_pendingFile) return;

        el('batchCreateProgress').style.display = '';
        el('batchCreateAndStartBtn').disabled = true;
        el('batchCreateOnlyBtn').disabled = true;

        const fd = new FormData();
        fd.append('batch_file', _pendingFile);
        fd.append('csrfmiddlewaretoken', getCsrf());

        fetch(_cfg.batchCreateUrl, { method: 'POST', body: fd })
            .then(r => r.json())
            .then(data => {
                el('batchCreateProgress').style.display = 'none';
                if (data.error) { alert('Erreur batch : ' + data.error); resetCreateBtns(); return; }

                cancelBatch();  // hide the bar

                // Reload page to show new queue items
                if (andStart) {
                    // Trigger process after reload by clicking process button
                    sessionStorage.setItem('anon_batch_autostart', '1');
                }
                location.reload();
            })
            .catch(err => {
                el('batchCreateProgress').style.display = 'none';
                console.error('[batch.js] create error', err);
                resetCreateBtns();
            });
    }

    function resetCreateBtns() {
        el('batchCreateAndStartBtn').disabled = false;
        el('batchCreateOnlyBtn').disabled = false;
    }

    // ── Cancel ───────────────────────────────────────────────────────────────

    function cancelBatch() {
        _pendingFile = null;
        _previewData = null;
        el('batchDetectBar').style.display = 'none';
        el('batchDetectPreview').style.display = 'none';
    }

    // ── Drop zone + file input integration ──────────────────────────────────

    function hookDropZone() {
        const dz = document.getElementById('dropZoneAnonymizer');
        const fileInput = document.getElementById('fileupload');
        if (!dz || !fileInput) return;

        // Intercept drag-over to check if it's a batch file
        dz.addEventListener('dragover', function (e) {
            e.preventDefault();
        });

        dz.addEventListener('drop', function (e) {
            e.preventDefault();
            const files = e.dataTransfer?.files;
            if (!files || files.length === 0) return;
            // If any dropped file is a batch file, handle it
            for (const f of files) {
                if (isBatchFile(f)) { handleBatchFile(f); return; }
            }
            // Otherwise let default jQuery File Upload handle it
        });

        // Hook the hidden file input to intercept batch files
        fileInput.addEventListener('change', function (e) {
            if (!this.files || this.files.length === 0) return;
            for (const f of this.files) {
                if (isBatchFile(f)) { handleBatchFile(f); this.value = ''; return; }
            }
            // Non-batch files handled by jQuery File Upload as normal
        });
    }

    // ── Auto-start after batch creation ─────────────────────────────────────

    function checkAutoStart() {
        if (sessionStorage.getItem('anon_batch_autostart') === '1') {
            sessionStorage.removeItem('anon_batch_autostart');
            const btn = el(_cfg.processToggleBtnId || 'process-toggle-btn');
            if (btn) {
                setTimeout(() => btn.click(), 500);
            }
        }
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    function init(cfg) {
        _cfg = cfg || {};

        document.addEventListener('DOMContentLoaded', function () {
            hookDropZone();
            checkAutoStart();

            const previewBtn = el('batchPreviewBtn');
            if (previewBtn) previewBtn.addEventListener('click', previewBatch);

            const cancelBtn = el('batchCancelBar');
            if (cancelBtn) cancelBtn.addEventListener('click', cancelBatch);

            const startBtn = el('batchCreateAndStartBtn');
            if (startBtn) startBtn.addEventListener('click', () => createBatch(true));

            const addBtn = el('batchCreateOnlyBtn');
            if (addBtn) addBtn.addEventListener('click', () => createBatch(false));
        });
    }

    return { init };
})();
