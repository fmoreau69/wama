/**
 * Reader — OCR Document
 * Gestion de la file d'attente, upload, polling, actions par item.
 */
(function () {
    'use strict';

    const cfg = window.READER_APP || {};
    const urls = cfg.urls || {};
    const csrf = cfg.csrfToken || '';

    // ─── Helpers ─────────────────────────────────────────────────────────────

    // Délégués à WamaApp (brique commune wama-app-base.js) ; repli local si non chargé.
    function csrfFetch(url, opts = {}) {
        if (window.WamaApp) return WamaApp.csrfFetch(url, csrf, opts);
        opts.headers = Object.assign({ 'X-CSRFToken': csrf }, opts.headers || {});
        return fetch(url, opts);
    }

    function urlFor(key, id) {
        const base = urls[key] || '';
        if (id === undefined) return base;
        return window.WamaApp ? WamaApp.getUrl(base, id) : base.replace('/0/', `/${id}/`);
    }

    function formatDate(iso) {
        try {
            const d = new Date(iso);
            return d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
        } catch (e) { return ''; }
    }

    function statusBadge(status) {
        const m = {
            PENDING: '<span class="badge bg-secondary">En attente</span>',
            RUNNING: '<span class="badge bg-warning text-dark"><i class="fas fa-spinner fa-spin me-1"></i>En cours</span>',
            DONE:    '<span class="badge bg-success">Terminé</span>',
            ERROR:   '<span class="badge bg-danger">Erreur</span>',
        };
        return m[status] || `<span class="badge bg-secondary">${status}</span>`;
    }

    function backendLabel(b) {
        const m = { auto: 'Auto', olmocr: 'olmOCR-2', doctr: 'docTR' };
        return m[b] || b;
    }

    function modeLabel(m) {
        const l = { auto: 'Auto', printed: 'Imprimé', handwritten: 'Manuscrit' };
        return l[m] || m;
    }

    // ─── Card rendering ───────────────────────────────────────────────────────

    function buildCard(item) {
        const pagesBadge = item.page_count > 1
            ? `<span class="badge bg-secondary ms-1">${item.page_count} pages</span>`
            : (item.page_count === 1 ? `<span class="badge bg-secondary ms-1">1 page</span>` : '');

        const usedBackend = item.used_backend
            ? `<span class="badge bg-info text-dark ms-1 small">${backendLabel(item.used_backend)}</span>`
            : `<span class="badge bg-secondary ms-1 small">${backendLabel(item.backend)}</span>`;

        const progressHtml = (item.status === 'RUNNING')
            ? `<div class="wama-progress-track mt-2">
                 <div class="wama-progress-fill active" style="width:${item.progress}%"></div>
               </div>
               <small class="text-warning">${item.progress_msg || 'En cours…'}</small>
               <span class="wama-eta d-block"></span>`
            : (item.status === 'DONE')
            ? `<div class="wama-progress-track mt-2">
                 <div class="wama-progress-fill" style="width:100%"></div>
               </div>`
            : '';

        const previewHtml = item.result_preview
            ? `<div class="reader-preview mt-2 p-2 rounded bg-black bg-opacity-50 small text-light"
                    style="max-height:80px;overflow:hidden;cursor:pointer;word-break:break-word;"
                    data-action="expand" title="Clic : développer · Double-clic : texte complet">
                 <span class="preview-text">${escapeHtml(item.result_preview)}</span>
                 ${item.has_result ? '<span class="text-muted"> …</span>' : ''}
               </div>`
            : '';

        const errorHtml = item.error_message
            ? `<div class="alert alert-danger py-1 mt-2 small mb-0">${escapeHtml(item.error_message)}</div>`
            : '';

        const dlBase = urlFor('download', item.id);
        const jsonItem = item.has_raw_result
            ? `<li><hr class="dropdown-divider"></li>
                   <li><a class="dropdown-item" href="${dlBase}?format=json"><i class="fas fa-code me-2 text-warning"></i>JSON brut</a></li>`
            : '';
        const downloadBtn = item.has_result
            ? `<div class="btn-group">
                 <a href="${dlBase}?format=txt" class="btn btn-sm btn-outline-info" title="Télécharger TXT">
                   <i class="fas fa-download"></i>
                 </a>
                 <button type="button" class="btn btn-sm btn-outline-info dropdown-toggle dropdown-toggle-split"
                         data-bs-toggle="dropdown" aria-expanded="false">
                   <span class="visually-hidden">Autres formats</span>
                 </button>
                 <ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end">
                   <li><a class="dropdown-item" href="${dlBase}?format=txt"><i class="fas fa-file-alt me-2"></i>TXT</a></li>
                   <li><a class="dropdown-item" href="${dlBase}?format=md"><i class="fab fa-markdown me-2"></i>Markdown</a></li>
                   <li><hr class="dropdown-divider"></li>
                   <li><a class="dropdown-item" href="${dlBase}?format=pdf"><i class="fas fa-file-pdf me-2 text-danger"></i>PDF</a></li>
                   <li><a class="dropdown-item" href="${dlBase}?format=docx"><i class="fas fa-file-word me-2 text-primary"></i>DOCX</a></li>
                   ${jsonItem}
                 </ul>
               </div>`
            : `<button class="btn btn-sm btn-outline-info" disabled title="Pas encore de résultat">
                 <i class="fas fa-download"></i>
               </button>`;

        // Bouton de cycle commun ▶/⏹/↻ (toujours vert ; ⏹ Stop pendant RUNNING). Câblé via
        // WamaCycleButton.wire + autoSync (cf. init). Repli legacy si la brique n'est pas chargée.
        const startBtn = window.WamaCycleButton
            ? WamaCycleButton.html(item.status, item.id)
            : `<button class="btn btn-sm btn-outline-success" data-action="start" title="Lancer"><i class="fas fa-play"></i></button>`;

        return `
<div class="card-body py-2">
  <div class="d-flex justify-content-between align-items-start">
    <div class="d-flex align-items-center flex-wrap gap-1 me-2 overflow-hidden">
      <span role="button" class="source-preview-btn d-flex align-items-center gap-1"
            data-id="${item.id}" data-filename="${escapeHtml(item.filename)}" title="Aperçu du fichier source">
        <i class="fas fa-file-alt text-info me-1"></i>
        <span class="fw-semibold text-light text-truncate" style="max-width:240px;">${escapeHtml(item.filename)}</span>
      </span>
      ${pagesBadge}
      ${statusBadge(item.status)}
      ${usedBackend}
      <small class="text-muted ms-1">${modeLabel(item.mode)}</small>
    </div>
    <div class="d-flex gap-1 flex-shrink-0">
      <button class="btn btn-sm btn-outline-secondary" data-action="settings" title="Paramètres"
              data-id="${item.id}"
              data-backend="${item.backend}"
              data-mode="${item.mode}"
              data-output-format="${item.output_format}"
              data-language="${escapeHtml(item.language || '')}">
        <i class="fas fa-cog"></i>
      </button>
      ${startBtn}
      ${downloadBtn}
      <button class="btn btn-sm btn-outline-secondary" data-action="duplicate" title="Dupliquer">
        <i class="fas fa-copy"></i>
      </button>
      <button class="btn btn-sm btn-outline-danger" data-action="delete" title="Supprimer">
        <i class="fas fa-trash"></i>
      </button>
    </div>
  </div>
  ${progressHtml}
  ${previewHtml}
  ${errorHtml}
</div>`;
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function upsertCard(item) {
        let card = document.querySelector(`.reader-card[data-id="${item.id}"]`);
        if (card) {
            card.dataset.status = item.status;
            card.innerHTML = buildCard(item);
        } else {
            // Prepend new card
            const empty = document.getElementById('emptyState');
            if (empty) empty.remove();

            card = document.createElement('div');
            card.className = 'reader-card card bg-dark border-secondary mb-2';
            card.dataset.id = item.id;
            card.dataset.status = item.status;
            card.innerHTML = buildCard(item);

            const container = document.getElementById('queueContainer');
            container.prepend(card);
        }
        if (window.WamaEta) WamaEta.render(card.querySelector('.wama-eta'), WamaEta.update(item.id, { progress: item.progress, status: item.status, seedSeconds: item.estimated_seconds, modelLoaded: false }));
        bindCardActions(card, item);
        updateDownloadAllBtn();
        return card;
    }

    function removeCard(id) {
        const card = document.querySelector(`.reader-card[data-id="${id}"]`);
        if (card) card.remove();
        if (document.querySelectorAll('.reader-card').length === 0) {
            const container = document.getElementById('queueContainer');
            container.innerHTML = `<div id="emptyState" class="text-center text-secondary py-5">
                <i class="fas fa-inbox fa-3x mb-3 opacity-50"></i>
                <p>File d'attente vide — importez des documents pour commencer</p>
            </div>`;
        }
    }

    // ─── Card actions ─────────────────────────────────────────────────────────

    function bindCardActions(card, item) {
        card.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                if (action === 'settings') openItemSettings(btn);
                if (action === 'start' || action === 'restart') startItem(item.id);
                if (action === 'delete') deleteItem(item.id);
                if (action === 'duplicate') duplicateItem(item.id);
                if (action === 'expand') expandPreview(item.id);
            });
        });
        const preview = card.querySelector('.reader-preview');
        if (preview) {
            preview.addEventListener('dblclick', e => {
                e.stopPropagation();
                openFullTextModal(item.id);
            });
        }
    }

    // ─── Polling ──────────────────────────────────────────────────────────────

    const pollingTimers = {};

    // Polling délégué à WamaApp.Poller (résilient : retries) ; création paresseuse + repli local.
    let _poller = null;
    function _getPoller() {
        if (!window.WamaApp) return null;
        if (!_poller) {
            _poller = new WamaApp.Poller({
                urlTemplate: urls.progress,
                onData: function (id, item) {
                    upsertCard(item);
                    if (item.status !== 'RUNNING' && item.status !== 'PENDING') {
                        _poller.stop(id);
                        if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
                    }
                },
            });
        }
        return _poller;
    }

    function startPolling(id) {
        const p = _getPoller();
        if (p) { p.start(id); return; }
        if (pollingTimers[id]) return;
        pollingTimers[id] = setInterval(async () => {
            try {
                const r = await fetch(urlFor('progress', id));
                const item = await r.json();
                upsertCard(item);
                if (item.status !== 'RUNNING' && item.status !== 'PENDING') {
                    stopPolling(id);
                    if (window.WamaFM) WamaFM.processed();
                }
            } catch (e) {
                stopPolling(id);
            }
        }, 1500);
    }

    function stopPolling(id) {
        const p = _getPoller();
        if (p) { p.stop(id); return; }
        if (pollingTimers[id]) {
            clearInterval(pollingTimers[id]);
            delete pollingTimers[id];
        }
    }

    // ─── Item actions ─────────────────────────────────────────────────────────

    // ⏹ Stop : arrête l'OCR (endpoint commun) → item relançable (↻ via autoSync sur data-status).
    async function stopItem(id) {
        const card = document.querySelector(`.reader-card[data-id="${id}"]`);
        try {
            const r = await csrfFetch(urlFor('stop', id), { method: 'POST' });
            const data = await r.json().catch(() => ({}));
            if (card && data.status) card.dataset.status = data.status;
            stopPolling(id);
        } catch (e) {
            console.error('[Reader] stop error:', e);
        }
    }

    async function startItem(id) {
        const card = document.querySelector(`.reader-card[data-id="${id}"]`);
        // Relance pendant le traitement : stopper d'abord (évite le 409 « déjà en cours »).
        if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') {
            await stopItem(id);
        }
        if (card) {
            card.dataset.status = 'RUNNING';
        }
        try {
            await csrfFetch(urlFor('start', id), { method: 'POST' });
            startPolling(id);
        } catch (e) {
            console.error('[Reader] start error:', e);
        }
    }

    async function deleteItem(id) {
        stopPolling(id);
        try {
            const r = await csrfFetch(urlFor('delete', id), { method: 'POST' });
            const data = await r.json().catch(() => ({}));
            // Élément issu d'un batch : total/affichage du batch changent → recharger
            if (data.batch_changed) { if (window.WamaFM) WamaFM.deleted(); location.reload(); return; }
            removeCard(id);
            updateGlobalProgress();
            if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
        } catch (e) {
            console.error('[Reader] delete error:', e);
        }
    }

    async function duplicateItem(id) {
        try {
            const r = await csrfFetch(urlFor('duplicate', id), { method: 'POST' });
            const item = await r.json();
            upsertCard(item);
        } catch (e) {
            console.error('[Reader] duplicate error:', e);
        }
    }

    // ─── Settings modal ───────────────────────────────────────────────────────

    function getOrCreateSettingsModal() {
        let modal = document.getElementById('readerItemSettingsModal');
        if (modal) return modal;

        modal = document.createElement('div');
        modal.id = 'readerItemSettingsModal';
        modal.className = 'modal fade';
        modal.tabIndex = -1;
        modal.innerHTML = `
<div class="modal-dialog modal-dialog-centered">
  <div class="modal-content bg-dark border-secondary text-white">
    <div class="modal-header border-secondary py-2">
      <h6 class="modal-title"><i class="fas fa-cog text-secondary me-2"></i>Paramètres OCR</h6>
      <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
    </div>
    <div class="modal-body">
      <input type="hidden" id="rSettings_id">
      <div id="rSettingsParams"></div><!-- champs ITEM générés par WamaParams (context item, ids rSettings_*) -->

    </div>
    <div class="modal-footer border-secondary py-2">
      <button type="button" class="btn btn-secondary btn-sm" data-bs-dismiss="modal">Annuler</button>
      <button type="button" id="rSettings_saveBtn" class="btn btn-primary btn-sm">
        <i class="fas fa-save me-1"></i>Enregistrer
      </button>
    </div>
  </div>
</div>`;
        document.body.appendChild(modal);
        // Champs ITEM générés par WamaParams (schéma exposé par le template) — ids legacy rSettings_*.
        if (window.WamaParams && window.WAMA_READER_SCHEMA) {
            const host = modal.querySelector('#rSettingsParams');
            if (host) WamaParams.render(host, window.WAMA_READER_SCHEMA, { context: 'item', values: {} });
        }
        document.getElementById('rSettings_saveBtn').addEventListener('click', saveItemSettings);
        return modal;
    }

    function openItemSettings(btn) {
        const modal = getOrCreateSettingsModal();
        // NULL-SAFE : champs générés par WamaParams ; dispatch input+change pour ses affichages.
        const _set = function (elId, val) {
            const el = document.getElementById(elId);
            if (!el) return;
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        };
        _set('rSettings_id', btn.dataset.id);
        _set('rSettings_backend', btn.dataset.backend || 'auto');
        _set('rSettings_mode', btn.dataset.mode || 'auto');
        _set('rSettings_language', btn.dataset.language || '');
        bootstrap.Modal.getOrCreateInstance(modal).show();
    }

    async function saveItemSettings() {
        const _val = function (elId) { const el = document.getElementById(elId); return el ? el.value : ''; };
        const id = _val('rSettings_id');
        const payload = {
            backend:  _val('rSettings_backend'),
            mode:     _val('rSettings_mode'),
            language: _val('rSettings_language').trim(),
        };
        try {
            const r = await csrfFetch(urlFor('saveSettings', id), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const item = await r.json();
            const modal = bootstrap.Modal.getInstance(document.getElementById('readerItemSettingsModal'));
            if (modal) modal.hide();
            upsertCard(item);
        } catch (e) {
            console.error('[Reader] save_settings error:', e);
        }
    }

    async function openFullTextModal(id) {
        try {
            const r = await fetch(urlFor('text', id));
            const data = await r.json();
            if (typeof window.showTextModal === 'function') {
                window.showTextModal(data.text || '', data.filename || 'Texte OCR');
            }
        } catch (e) {
            console.error('[Reader] openFullTextModal error:', e);
        }
    }

    function openSourcePreview(id, filename) {
        const _urls = window.READER_APP?.urls || {};
        if (!_urls.previewUrlTemplate) return;
        const apiUrl = _urls.previewUrlTemplate.replace('/0/', `/${id}/`);
        fetch(apiUrl)
            .then(r => r.json())
            .then(data => { if (typeof window.showPreviewModal === 'function') window.showPreviewModal(data); })
            .catch(() => {});
    }

    function expandPreview(id) {
        const preview = document.querySelector(
            `.reader-card[data-id="${id}"] .reader-preview`
        );
        if (!preview) return;
        if (preview.style.maxHeight === 'none') {
            preview.style.maxHeight = '80px';
        } else {
            preview.style.maxHeight = 'none';
        }
    }

    // ─── Upload ───────────────────────────────────────────────────────────────

    async function uploadFiles(files) {
        if (!files || !files.length) return;

        const fd = new FormData();
        Array.from(files).forEach(f => fd.append('files', f));
        fd.append('backend',       document.getElementById('backendSelect')?.value || 'auto');
        fd.append('mode',          document.getElementById('modeSelect')?.value || 'auto');
        fd.append('output_format', document.getElementById('outputFormatSelect')?.value || 'txt');
        fd.append('language',      document.getElementById('languageInput')?.value.trim() || '');

        try {
            const r = await csrfFetch(urls.upload, { method: 'POST', body: fd });
            const data = await r.json();
            if (data.multi) {
                // Multi-file batch → reload to render the batch group structure
                window.location.reload();
                return;
            }
            (data.created || []).forEach(item => upsertCard(item));
            updateGlobalProgress();
            if (window.WamaFM) WamaFM.uploaded();  // fichier ajouté → refresh filemanager
        } catch (e) {
            console.error('[Reader] upload error:', e);
        }
    }

    // ─── Drag & drop + click to browse (defined later, with batch detection) ──

    // ─── Global actions ───────────────────────────────────────────────────────

    function updateDownloadAllBtn() {
        const btn = document.getElementById('reader-download-all-btn');
        if (!btn) return;
        const hasSuccess = document.querySelector('.reader-card[data-status="DONE"]') !== null;
        btn.disabled = !hasSuccess;
    }

    function initGlobalButtons() {
        document.getElementById('reader-process-btn')?.addEventListener('click', async () => {
            try {
                const r = await csrfFetch(urls.startAll, { method: 'POST' });
                const data = await r.json();
                // Start polling for all RUNNING/PENDING cards
                document.querySelectorAll('.reader-card').forEach(card => {
                    const st = card.dataset.status;
                    if (st === 'RUNNING' || st === 'PENDING') {
                        startPolling(parseInt(card.dataset.id));
                    }
                });
            } catch (e) {
                console.error('[Reader] start_all error:', e);
            }
        });

        const downloadAllBtn = document.getElementById('reader-download-all-btn');
        if (downloadAllBtn) {
            downloadAllBtn.addEventListener('click', () => {
                window.location.href = urls.downloadAll;
            });
        }

        document.getElementById('reader-clear-btn')?.addEventListener('click', async () => {
            if (!confirm('Supprimer tous les éléments de la file ?')) return;
            Object.keys(pollingTimers).forEach(stopPolling);
            try {
                await csrfFetch(urls.clearAll, { method: 'POST' });
                if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
                document.getElementById('queueContainer').innerHTML =
                    `<div id="emptyState" class="text-center text-secondary py-5">
                        <i class="fas fa-inbox fa-3x mb-3 opacity-50"></i>
                        <p>File d'attente vide — importez des documents pour commencer</p>
                    </div>`;
                updateDownloadAllBtn();
            } catch (e) {
                console.error('[Reader] clear_all error:', e);
            }
        });

        document.getElementById('resetOptions')?.addEventListener('click', () => {
            const fields = [
                { id: 'backendSelect', key: 'backendSelect' },
                { id: 'modeSelect',    key: 'modeSelect' },
                { id: 'languageInput', key: 'languageInput' },
            ];
            fields.forEach(({ id, key }) => {
                const el = document.getElementById(id);
                if (el) {
                    if (el.tagName === 'SELECT') {
                        el.selectedIndex = 0;
                    } else {
                        el.value = '';
                    }
                }
                localStorage.removeItem(`reader_setting_${key}`);
            });
        });
    }

    // ─── Global progress ──────────────────────────────────────────────────────

    function updateGlobalProgress() {
        return; // Neutralisé : barre globale + ETA pilotées par la brique commune wama-global-progress.js.
        if (!urls.globalProgress) return;
        fetch(urls.globalProgress)
            .then(r => r.json())
            .then(data => {
                const bar          = document.getElementById('globalProgressBar');
                const stats        = document.getElementById('globalProgressStats');
                const pct          = document.getElementById('globalProgressPct');
                const globalStatus = document.getElementById('globalStatus');
                const p = data.overall_progress || 0;
                if (window.WamaEta) WamaEta.render(document.getElementById('globalEta'), WamaEta.aggregateAll());
                if (bar)   bar.style.width    = p + '%';
                if (stats) stats.textContent  = `${data.done}/${data.total} terminé · ${data.running} en cours`;
                if (pct)   pct.textContent    = p ? p + '%' : '';
                if (globalStatus) {
                    const active = (data.total || 0) > 0;
                    globalStatus.style.opacity       = active ? '1' : '0';
                    globalStatus.style.pointerEvents = active ? '' : 'none';
                    // Remove shimmer once all done
                    if (bar && data.done === data.total && data.total > 0) {
                        bar.classList.remove('active');
                    } else if (bar) {
                        bar.classList.add('active');
                    }
                }
            })
            .catch(() => {});
    }

    // ─── Batch group URL helper ───────────────────────────────────────────────

    function urlForBatch(key, id) {
        const base = urls[key] || '';
        return id !== undefined ? base.replace('/0/', `/${id}/`) : base;
    }

    // ─── Batch group actions ──────────────────────────────────────────────────

    async function startBatch(batchId) {
        try {
            const r = await csrfFetch(urlForBatch('batchStart', batchId), { method: 'POST' });
            const data = await r.json();
            // Poll all started items directly — no page reload
            (data.started || []).forEach(id => startPolling(id));
            // Expand the batch group so the user can see progress
            const batchEl = document.querySelector(`.batch-group[data-batch-id="${batchId}"]`);
            if (batchEl) {
                const collapseEl = batchEl.querySelector('.collapse');
                if (collapseEl) bootstrap.Collapse.getOrCreateInstance(collapseEl).show();
            }
            updateGlobalProgress();
        } catch (e) {
            console.error('[Reader] batch start error:', e);
        }
    }

    async function deleteBatch(batchId) {
        if (!confirm('Supprimer ce batch et tous ses éléments ?')) return;
        try {
            await csrfFetch(urlForBatch('batchDelete', batchId), { method: 'POST' });
            if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
            const el = document.querySelector(`.batch-group[data-batch-id="${batchId}"]`);
            if (el) el.remove();
            if (document.querySelectorAll('.reader-card, .batch-group').length === 0) {
                document.getElementById('queueContainer').innerHTML =
                    `<div id="emptyState" class="text-center text-secondary py-5">
                        <i class="fas fa-inbox fa-3x mb-3 opacity-50"></i>
                        <p>File d'attente vide — importez des documents pour commencer</p>
                    </div>`;
            }
        } catch (e) {
            console.error('[Reader] batch delete error:', e);
        }
    }

    async function duplicateBatch(batchId) {
        try {
            await csrfFetch(urlForBatch('batchDuplicate', batchId), { method: 'POST' });
            window.location.reload();
        } catch (e) {
            console.error('[Reader] batch duplicate error:', e);
        }
    }

    // ─── Batch settings modal ─────────────────────────────────────────────────

    let _batchSettingsModal = null;

    function initBatchSettingsModal() {
        const el = document.getElementById('batchSettingsModal');
        if (!el) return;
        _batchSettingsModal = new bootstrap.Modal(el);

        const saveBtn = document.getElementById('saveBatchSettingsBtn');
        if (saveBtn) saveBtn.addEventListener('click', () => saveBatchSettings(false));
        const saveStartBtn = document.getElementById('saveBatchSettingsAndStartBtn');
        if (saveStartBtn) saveStartBtn.addEventListener('click', () => saveBatchSettings(true));
    }

    function openBatchSettingsModal(btn) {
        if (!_batchSettingsModal) return;
        const id = btn.dataset.batchId;
        document.getElementById('batchSettingsBatchLabel').textContent = '#' + id;
        document.getElementById('batchSettingsBatchId').value = id;
        const selEl = document.getElementById('batchSettingsBackend');
        if (selEl) selEl.value = btn.dataset.backend || '';
        const modeEl = document.getElementById('batchSettingsMode');
        if (modeEl) modeEl.value = btn.dataset.mode || '';
        const langEl = document.getElementById('batchSettingsLanguage');
        if (langEl) langEl.value = btn.dataset.language || '';
        _batchSettingsModal.show();
    }

    async function saveBatchSettings(andStart) {
        const batchId = document.getElementById('batchSettingsBatchId').value;
        const payload = {
            backend:  document.getElementById('batchSettingsBackend').value,
            mode:     document.getElementById('batchSettingsMode').value,
            language: (document.getElementById('batchSettingsLanguage').value || '').trim(),
        };
        try {
            const r = await csrfFetch(urlForBatch('batchUpdate', batchId), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await r.json();
            if (!r.ok || !data.success) { alert(data.error || 'Erreur sauvegarde'); return; }
            _batchSettingsModal.hide();
            if (andStart) {
                await startBatch(batchId);
            } else {
                window.location.reload();
            }
        } catch { alert('Erreur réseau'); }
    }

    function bindBatchGroupActions() {
        document.querySelectorAll('.batch-start-btn').forEach(btn => {
            btn.addEventListener('click', () => startBatch(btn.dataset.batchId));
        });
        document.querySelectorAll('.batch-delete-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteBatch(btn.dataset.batchId));
        });
        document.querySelectorAll('.batch-duplicate-btn').forEach(btn => {
            btn.addEventListener('click', () => duplicateBatch(btn.dataset.batchId));
        });
        document.querySelectorAll('.batch-settings-btn').forEach(btn => {
            btn.addEventListener('click', () => openBatchSettingsModal(btn));
        });
    }

    // ─── Init ─────────────────────────────────────────────────────────────────

    // Inspecteur contextuel commun : clic card/batch → bandeau « Réglages de l'élément #N » + valeurs
    // de l'élément dans le volet + sauvegarde routée. Câblage générique dérivé du schéma WamaParams.
    function initInspector() {
        const q  = document.getElementById('queueContainer');
        const ph = document.getElementById('readerPanelParams');
        if (!q || !ph || !window.WamaInspector || !WamaInspector.initFromSchema) return;
        const readPanel = () => (window.WamaParams ? WamaParams.read(ph) : {});
        window._readerInspector = WamaInspector.initFromSchema({
            queueContainer: q,
            cardSelector:   '.reader-card',
            batchSelector:  '.batch-group',
            panelContainer: ph,
            schema:         window.WAMA_READER_SCHEMA || [],
            itemLabel:  (id) => "l'élément #" + id,
            batchLabel: (id) => "le batch #" + id + " (tous les éléments)",
            saveItem: async (id) => {
                const r = await csrfFetch(urlFor('saveSettings', id), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(readPanel()),
                });
                if (r && r.ok) upsertCard(await r.json());
            },
            saveBatch: async (bid) => {
                const r = await csrfFetch(urlForBatch('batchUpdate', bid), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(readPanel()),
                });
                if (r && r.ok) window.location.reload();
            },
        });
    }

    function initCycleButton() {
        if (!window.WamaCycleButton) return;
        const q = document.getElementById('queueContainer');
        if (!q) return;
        // Câblage délégué (start/restart→startItem, stop→stopItem) + auto-sync de l'icône sur data-status.
        WamaCycleButton.wire(q, { start: (id) => startItem(id), stop: (id) => stopItem(id) });
        WamaCycleButton.autoSync({ container: q, cardSelector: '.reader-card' });
    }

    function init() {
        initDropZone();
        initGlobalButtons();
        initBatchSettingsModal();
        initInspector();
        initCycleButton();
        bindBatchGroupActions();
        updateDownloadAllBtn();
        updateGlobalProgress();
        setInterval(updateGlobalProgress, 2000);

        // Source file preview — delegated click on .source-preview-btn
        document.addEventListener('click', e => {
            const btn = e.target.closest('.source-preview-btn');
            if (!btn) return;
            openSourcePreview(btn.dataset.id, btn.dataset.filename);
        });

        // Persist settings
        ['backendSelect', 'modeSelect', 'languageInput'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            const key = `reader_setting_${id}`;
            const saved = localStorage.getItem(key);
            if (saved) el.value = saved;
            el.addEventListener('change', () => localStorage.setItem(key, el.value));
        });

        // Bind existing cards and start polling for RUNNING + PENDING items
        // (PENDING items may have tasks already queued — catch the RUNNING transition)
        document.querySelectorAll('.reader-card').forEach(card => {
            const id = parseInt(card.dataset.id);
            if (card.dataset.status === 'RUNNING' || card.dataset.status === 'PENDING') {
                startPolling(id);
            }
            // Bind action buttons
            card.querySelectorAll('[data-action]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const action = btn.dataset.action;
                    if (action === 'settings') openItemSettings(btn);
                    if (action === 'start' || action === 'restart') startItem(id);
                    if (action === 'delete') deleteItem(id);
                    if (action === 'duplicate') duplicateItem(id);
                    if (action === 'expand') expandPreview(id);
                });
            });
            // Double-click on preview → full text modal
            const preview = card.querySelector('.reader-preview');
            if (preview) {
                preview.addEventListener('dblclick', e => {
                    e.stopPropagation();
                    openFullTextModal(id);
                });
            }
        });
    }

    async function uploadFilesWithBatch(files) {
        if (!files || !files.length) return;
        const arr = Array.from(files);
        if (arr.length === 1 && window._batchImport) {
            if (await window._batchImport.detectAndHandle(arr[0])) return;
        }
        uploadFiles(files);
    }

    function initDropZone() {
        const zone = document.getElementById('dropZone');
        const input = document.getElementById('fileInput');
        if (!zone || !input) return;

        zone.addEventListener('click', (e) => {
            // Don't trigger file input if batch template link was clicked
            if (e.target.closest('a')) return;
            input.click();
        });
        input.addEventListener('change', () => {
            uploadFilesWithBatch(input.files);
            input.value = '';
        });

        zone.addEventListener('dragover', e => {
            e.preventDefault();
            zone.classList.add('dragover');
        });
        zone.addEventListener('dragleave', () => {
            zone.classList.remove('dragover');
        });
        zone.addEventListener('drop', e => {
            e.preventDefault();
            zone.classList.remove('dragover');
            uploadFilesWithBatch(e.dataTransfer.files);
        });
    }

    // Handle files imported via filemanager "Envoyer vers Reader" context menu
    document.addEventListener('wama:fileimported', e => {
        const result = e.detail;
        if (!result || result.app !== 'reader') return;
        if (result.id) {
            // Single-file import with known ID: add card dynamically
            fetch(urlFor('progress', result.id))
                .then(r => r.json())
                .then(item => { upsertCard(item); updateGlobalProgress(); })
                .catch(() => {});
        } else {
            // Multi-file import (no ID in event) → reload to show batch group
            window.location.reload();
        }
    });

    document.addEventListener('DOMContentLoaded', init);

})();
