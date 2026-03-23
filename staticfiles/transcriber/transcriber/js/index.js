document.addEventListener('DOMContentLoaded', function () {
  const config = window.TRANSCRIBER_APP || {};
  const csrfToken = config.csrfToken;
  const fileInput = document.getElementById('transcriber-file');
  const queueContainer = document.getElementById('transcriptQueue');
  const speakButton = document.getElementById('transcriber-speak-btn');
  const liveOutput = document.getElementById('live-transcription-output');
  const liveStatus = document.getElementById('live-transcription-status');
  const startProcessBtn = document.getElementById('transcriber-process-btn');
  const clearAllBtn = document.getElementById('transcriber-clear-btn');
  const downloadAllBtn = document.getElementById('transcriber-download-all-btn');
  const preprocessToggle = document.getElementById('preprocessingToggle');
  const toggleDatasetUrl = preprocessToggle ? preprocessToggle.dataset.preprocessUrl : '';

  const pollers = new Map();
  let preprocessEnabled = !!config.preprocessingEnabled;
  if (typeof config.preprocessingEnabled === 'string') {
    preprocessEnabled = config.preprocessingEnabled === 'true';
  }

  function getUrl(template, id) {
    return template.replace('/0/', `/${id}/`);
  }

  function csrfHeaders(extra = {}) {
    return Object.assign({}, extra, { 'X-CSRFToken': csrfToken });
  }

  function escapeHtml(str) {
    return (str || '').replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
    });
  }

  function wordCount(text) {
    if (!text || !text.trim()) return 0;
    return text.trim().split(/\s+/).filter(Boolean).length;
  }

  function setWordCount(spanId, text) {
    const span = document.getElementById(spanId);
    if (!span) return;
    const n = wordCount(text);
    if (n > 0) { span.textContent = `${n} mot${n !== 1 ? 's' : ''}`; span.style.display = ''; }
    else { span.textContent = ''; span.style.display = 'none'; }
  }

  // ======================================================================
  // Upload
  // ======================================================================
  async function uploadFile(file) {
    const body = new FormData();
    body.append('file', file);
    body.append('preprocess_audio', preprocessEnabled ? '1' : '0');

    // Include current panel settings
    const backendSel = document.getElementById('backendSelect');
    const hotwordsIn = document.getElementById('hotwordsInput');
    if (backendSel) body.append('backend', backendSel.value);
    if (hotwordsIn) body.append('hotwords', hotwordsIn.value);

    try {
      const response = await fetch(config.uploadUrl, {
        method: 'POST', headers: csrfHeaders(), body,
      });
      const data = await response.json();
      if (data.error) throw new Error(data.error);
      data.status = data.status || 'PENDING';
      appendCard(data);
    } catch (error) {
      alert(`Erreur pour ${file.name}: ${error.message}`);
    }
  }

  // ── Toast utility (simple bootstrap toast or fallback) ───────────────
  function showToast(message, type) {
    // Try to use a Bootstrap toast if available, else alert for errors
    if (type === 'danger' || type === 'error') {
      alert(message);
    } else {
      // For non-error messages, use console + optional visual cue
      console.info('[Transcriber]', message);
    }
  }

  function updateQueueCount() {
    const badge = document.getElementById('queueCount');
    if (!badge) return;
    const cards = document.querySelectorAll('#transcriptQueue .synthesis-card');
    badge.textContent = cards.length;
  }

  // ── Batch file detection ──────────────────────────────────────────────
  const BATCH_EXTS = ['txt', 'csv', 'md'];
  let _batchFile = null;
  let _batchItems = [];

  async function handleFiles(files) {
    const fileList = Array.from(files);
    // If exactly one .txt/.csv/.md file is dropped, treat as batch candidate
    if (fileList.length === 1) {
      const f = fileList[0];
      const ext = f.name.split('.').pop().toLowerCase();
      if (BATCH_EXTS.includes(ext)) {
        await _handleBatchFileDetect(f);
        return;
      }
    }
    for (const file of fileList) await uploadFile(file);
  }

  async function _handleBatchFileDetect(file) {
    _batchFile = file;
    _batchItems = [];
    const formData = new FormData();
    formData.append('batch_file', file);
    try {
      const resp = await fetch(config.batchPreviewUrl, {
        method: 'POST',
        headers: {'X-CSRFToken': csrfToken},
        body: formData,
      });
      const data = await resp.json();
      if (data.error || !data.count || data.count < 2) {
        // Not a valid batch or only 1 item — treat as regular file upload
        _batchFile = null;
        await uploadFile(file);
        return;
      }
      _batchItems = data.items || [];
      _showBatchBar(data);
    } catch (_) {
      _batchFile = null;
      await uploadFile(file);
    }
  }

  function _showBatchBar(data) {
    const batchBar = document.getElementById('batchDetectBar');
    const batchDetectedCount = document.getElementById('batchDetectedCount');
    const batchDetectPreview = document.getElementById('batchDetectPreview');
    if (!batchBar) return;
    if (batchDetectedCount) batchDetectedCount.textContent = data.count;
    if (batchDetectPreview) batchDetectPreview.style.display = 'none';
    batchBar.style.display = '';
  }

  function _hideBatchBar() {
    const batchBar = document.getElementById('batchDetectBar');
    const batchDetectPreview = document.getElementById('batchDetectPreview');
    if (batchBar) batchBar.style.display = 'none';
    if (batchDetectPreview) batchDetectPreview.style.display = 'none';
    _batchFile = null;
    _batchItems = [];
  }

  function _populateBatchPreview(data) {
    const batchDetectTable = document.getElementById('batchDetectTable');
    const batchCreateCount = document.getElementById('batchCreateCount');
    const batchDetectWarnings = document.getElementById('batchDetectWarnings');
    if (!batchDetectTable) return;
    batchDetectTable.innerHTML = '';
    (data.items || []).forEach(item => {
      const tr = document.createElement('tr');
      tr.innerHTML = `<td style="word-break:break-all;">${escapeHtml(item.path)}</td>`;
      batchDetectTable.appendChild(tr);
    });
    if (batchCreateCount) batchCreateCount.textContent = data.count;
    if (batchDetectWarnings) {
      if (data.warnings && data.warnings.length > 0) {
        batchDetectWarnings.textContent = data.warnings.join(' | ');
        batchDetectWarnings.style.display = '';
      } else {
        batchDetectWarnings.style.display = 'none';
      }
    }
  }

  function initBatchBar() {
    const batchPreviewBtn = document.getElementById('batchPreviewBtn');
    const batchCancelBar = document.getElementById('batchCancelBar');
    const batchCreateAndStartBtn = document.getElementById('batchCreateAndStartBtn');
    const batchCreateOnlyBtn = document.getElementById('batchCreateOnlyBtn');

    if (batchPreviewBtn) {
      batchPreviewBtn.addEventListener('click', async function() {
        if (!_batchFile) return;
        const formData = new FormData();
        formData.append('batch_file', _batchFile);
        try {
          const resp = await fetch(config.batchPreviewUrl, {
            method: 'POST',
            headers: {'X-CSRFToken': csrfToken},
            body: formData,
          });
          const data = await resp.json();
          if (!data.error) {
            _populateBatchPreview(data);
            const batchDetectPreview = document.getElementById('batchDetectPreview');
            if (batchDetectPreview) batchDetectPreview.style.display = '';
          }
        } catch (_) {
          showToast('Erreur lors de la prévisualisation', 'danger');
        }
      });
    }

    if (batchCancelBar) {
      batchCancelBar.addEventListener('click', _hideBatchBar);
    }

    async function _doBatchImport(autoStart) {
      if (!_batchFile) return;
      const batchCreateProgress = document.getElementById('batchCreateProgress');
      if (batchCreateProgress) batchCreateProgress.style.display = '';
      if (batchCreateAndStartBtn) batchCreateAndStartBtn.disabled = true;
      if (batchCreateOnlyBtn) batchCreateOnlyBtn.disabled = true;

      const formData = new FormData();
      formData.append('batch_file', _batchFile);
      // Include current panel settings
      const backendSel = document.getElementById('backendSelect');
      const hotwordsIn = document.getElementById('hotwordsInput');
      if (backendSel) formData.append('backend', backendSel.value);
      if (hotwordsIn) formData.append('hotwords', hotwordsIn.value);
      formData.append('preprocess_audio', preprocessEnabled ? '1' : '0');

      try {
        const resp = await fetch(config.batchCreateUrl, {
          method: 'POST',
          headers: {'X-CSRFToken': csrfToken},
          body: formData,
        });
        const data = await resp.json();
        if (data.error) {
          showToast('Erreur : ' + data.error, 'danger');
          return;
        }

        const batchId = data.batch_id;
        if (autoStart && batchId) {
          const startUrl = config.batchStartUrlTemplate.replace('/0/', `/${batchId}/`);
          await fetch(startUrl, {
            method: 'POST',
            headers: {'X-CSRFToken': csrfToken},
          });
        }

        _hideBatchBar();
        showToast(`Batch créé (${data.total} éléments)` + (autoStart ? ' — traitement lancé' : ''), 'success');
        setTimeout(() => location.reload(), 800);
      } catch (_) {
        showToast('Erreur lors de la création du batch', 'danger');
      } finally {
        if (batchCreateProgress) batchCreateProgress.style.display = 'none';
        if (batchCreateAndStartBtn) batchCreateAndStartBtn.disabled = false;
        if (batchCreateOnlyBtn) batchCreateOnlyBtn.disabled = false;
      }
    }

    if (batchCreateAndStartBtn) {
      batchCreateAndStartBtn.addEventListener('click', () => _doBatchImport(true));
    }
    if (batchCreateOnlyBtn) {
      batchCreateOnlyBtn.addEventListener('click', () => _doBatchImport(false));
    }
  }

  // ── Batch delete ─────────────────────────────────────────────────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-delete-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    if (!confirm('Supprimer ce batch et toutes ses transcriptions ?')) return;
    const url = config.batchDeleteUrlTemplate.replace('/0/', `/${batchId}/`);
    fetch(url, {method: 'POST', headers: csrfHeaders()})
      .then(r => r.json())
      .then(() => {
        const el = btn.closest('.batch-group');
        if (el) el.remove();
        else location.reload();
        updateQueueCount();
      })
      .catch(() => showToast('Erreur lors de la suppression', 'danger'));
  });

  // ── Batch duplicate ───────────────────────────────────────────────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-duplicate-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    const url = config.batchDuplicateUrlTemplate.replace('/0/', `/${batchId}/`);
    fetch(url, {method: 'POST', headers: csrfHeaders()})
      .then(r => r.json())
      .then(data => {
        if (data.success) {
          showToast('Batch dupliqué', 'success');
          setTimeout(() => location.reload(), 600);
        }
      })
      .catch(() => showToast('Erreur lors de la duplication', 'danger'));
  });

  function initUpload() {
    if (!fileInput) return;
    fileInput.addEventListener('change', function () {
      if (!this.files.length) return;
      handleFiles(this.files);
      fileInput.value = '';
    });
  }

  function initDragDrop() {
    const dropZone = document.getElementById('dropZoneTranscriber');
    const browseBtn = document.getElementById('transcriber-browse-btn');
    if (!dropZone || !fileInput) return;

    dropZone.addEventListener('click', (e) => { if (e.target !== browseBtn) fileInput.click(); });
    if (browseBtn) browseBtn.addEventListener('click', (e) => { e.stopPropagation(); fileInput.click(); });
    dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      if (e.dataTransfer.files.length > 0) handleFiles(e.dataTransfer.files);
    });
  }

  function initYoutube() {
    const youtubeUrl = document.getElementById('youtubeUrl');
    const youtubeBtn = document.getElementById('youtubeSubmitBtn');
    if (!youtubeUrl || !youtubeBtn) return;

    youtubeBtn.addEventListener('click', async () => {
      const url = youtubeUrl.value.trim();
      if (!url) { alert('Veuillez entrer une URL YouTube'); return; }

      youtubeBtn.disabled = true;
      youtubeBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Téléchargement...';

      try {
        const body = new FormData();
        body.append('youtube_url', url);
        body.append('preprocess_audio', preprocessEnabled ? '1' : '0');
        const response = await fetch(config.uploadYoutubeUrl, { method: 'POST', headers: csrfHeaders(), body });
        const data = await response.json();
        if (data.error) throw new Error(data.error);
        data.status = data.status || 'PENDING';
        appendCard(data);
        youtubeUrl.value = '';
      } catch (error) {
        alert(`Erreur YouTube: ${error.message}`);
      } finally {
        youtubeBtn.disabled = false;
        youtubeBtn.innerHTML = '<i class="fas fa-download"></i> Télécharger & Transcrire';
      }
    });

    youtubeUrl.addEventListener('keypress', (e) => { if (e.key === 'Enter') youtubeBtn.click(); });
  }

  // ======================================================================
  // Card rendering
  // ======================================================================
  function appendCard(data) {
    if (!queueContainer) return;
    removeEmptyState();

    const card = document.createElement('div');
    card.className = 'synthesis-card';
    card.dataset.id = data.id;
    card.dataset.status = (data.status || 'PENDING').toUpperCase();

    const label = escapeHtml(data.audio_label || data.audio_name || 'Audio');
    const duration = escapeHtml(data.duration_display || '--:--');
    const props = escapeHtml(data.properties || 'En attente');
    const backend = escapeHtml(data.backend || 'auto');

    const previewUrl = config.previewUrlTemplate ? getUrl(config.previewUrlTemplate, data.id) : '';

    card.innerHTML = `
      <div class="row align-items-center">
        <div class="col-md-3">
          <button type="button" class="btn btn-link p-0 text-decoration-none preview-media-link filename"
                  data-preview-url="${escapeHtml(previewUrl)}"
                  style="color: inherit;">
            <i class="fas fa-file-audio"></i> ${label}
          </button><br>
          <small class="text-white-50">
            ${duration}
            ${data.preprocess_audio ? '<span class="badge bg-warning text-dark ms-1">Prétraité</span>' : ''}
          </small>
        </div>
        <div class="col-md-2">
          <small>
            <i class="fas fa-microchip"></i> ${backend}<br>
          </small>
        </div>
        <div class="col-md-2">
          <small class="text-white-50">${props}</small>
        </div>
        <div class="col-md-2">
          <span class="badge status-badge bg-secondary">PENDING</span>
          <div class="progress mt-2" style="height: 8px;">
            <div class="progress-bar bg-info progress-fill" style="width: 0%"></div>
          </div>
          <small class="text-light progress-text">0%</small>
        </div>
        <div class="col-md-3">
          <div class="btn-group-actions">
            <button class="btn btn-sm btn-primary start-btn" data-id="${data.id}" title="Démarrer">
              <i class="fas fa-play"></i>
            </button>
            <button class="btn btn-sm btn-secondary settings-btn" data-id="${data.id}"
                    data-backend="${escapeHtml(data.backend || 'auto')}"
                    data-hotwords="${escapeHtml(data.hotwords || '')}"
                    data-preprocess="${data.preprocess_audio ? 'true' : 'false'}"
                    data-diarization="${document.getElementById('diarizationToggle')?.checked !== false ? 'true' : 'false'}"
                    data-temperature="0"
                    data-max-tokens="32768"
                    data-generate-summary="${document.getElementById('globalGenerateSummary')?.checked ? 'true' : 'false'}"
                    data-summary-type="${document.querySelector('input[name=\'globalSummaryType\']:checked')?.value || 'structured'}"
                    data-verify-coherence="${document.getElementById('globalVerifyCoherence')?.checked ? 'true' : 'false'}"
                    title="Paramètres">
              <i class="fas fa-cog"></i>
            </button>
            <button class="btn btn-sm btn-outline-info duplicate-btn" data-id="${data.id}" title="Dupliquer (tester un autre modèle)">
              <i class="fas fa-copy"></i>
            </button>
            <button class="btn btn-sm btn-danger delete-btn" data-id="${data.id}" title="Supprimer">
              <i class="fas fa-trash"></i>
            </button>
          </div>
        </div>
      </div>`;

    queueContainer.prepend(card);
    bindCardActions(card);
    if (window.initMediaPreview) window.initMediaPreview();
    updateDownloadAllState();
  }

  function updateCard(id, data) {
    const card = queueContainer ? queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`) : null;
    if (!card) { stopPolling(id); return; }

    const progress = Math.min(100, Math.max(0, data.progress || 0));
    const status = (data.status || 'PENDING').toUpperCase();

    // Update progress bar
    const bar = card.querySelector('.progress-fill');
    const progressText = card.querySelector('.progress-text');
    if (bar) bar.style.width = `${progress}%`;
    if (progressText) progressText.textContent = `${progress}%`;

    // Update status badge
    const badge = card.querySelector('.status-badge');
    if (badge) {
      badge.textContent = status;
      badge.className = 'badge status-badge ' + ({
        PENDING: 'bg-secondary', RUNNING: 'bg-warning',
        SUCCESS: 'bg-success', FAILURE: 'bg-danger'
      }[status] || 'bg-secondary');
    }

    // Update card class
    card.className = 'synthesis-card' + ({
      RUNNING: ' processing', SUCCESS: ' success', FAILURE: ' error'
    }[status] || '');
    card.dataset.status = status;

    // Update live transcription display
    updateLiveTranscriptionFromQueue(id, status, data.partial_text);

    // When done, rebuild actions to show download buttons
    if (['SUCCESS', 'FAILURE'].includes(status) || progress >= 100) {
      stopPolling(id);
      rebuildActions(card, id, status);
    }

    updateDownloadAllState();
  }

  function rebuildActions(card, id, status) {
    const actionsDiv = card.querySelector('.btn-group-actions');
    if (!actionsDiv) return;

    // Capture ALL data-attributes from the existing settings-btn BEFORE destroying it
    const oldBtn = actionsDiv.querySelector('.settings-btn');
    const sd = oldBtn ? {
      backend:         oldBtn.dataset.backend         || 'auto',
      hotwords:        oldBtn.dataset.hotwords        || '',
      preprocess:      oldBtn.dataset.preprocess      || 'false',
      diarization:     oldBtn.dataset.diarization     || 'true',
      temperature:     oldBtn.dataset.temperature     || '0',
      maxTokens:       oldBtn.dataset.maxTokens       || '32768',
      generateSummary: oldBtn.dataset.generateSummary || 'false',
      summaryType:     oldBtn.dataset.summaryType     || 'structured',
      verifyCoherence: oldBtn.dataset.verifyCoherence || 'false',
    } : null;

    let html = '';

    if (status !== 'RUNNING') {
      html += `<button class="btn btn-sm btn-primary start-btn" data-id="${id}" title="Démarrer"><i class="fas fa-play"></i></button>`;
      html += `<button class="btn btn-sm btn-secondary settings-btn" data-id="${id}" title="Paramètres"><i class="fas fa-cog"></i></button>`;
    }

    if (status === 'SUCCESS') {
      html += `<button class="btn btn-sm btn-success preview-btn" data-id="${id}" title="Voir le résultat"><i class="fas fa-eye"></i></button>`;
      const dlBase = getUrl(config.downloadUrlTemplate, id);
      html += `<div class="btn-group btn-group-sm">` +
        `<a href="${dlBase}?format=txt" class="btn btn-outline-info download-txt-btn" title="Télécharger TXT"><i class="fas fa-download"></i></a>` +
        `<button type="button" class="btn btn-outline-info dropdown-toggle dropdown-toggle-split" data-bs-toggle="dropdown" aria-expanded="false"><span class="visually-hidden">Autres formats</span></button>` +
        `<ul class="dropdown-menu dropdown-menu-dark dropdown-menu-end">` +
          `<li><a class="dropdown-item" href="${dlBase}?format=txt"><i class="fas fa-file-alt me-2"></i>TXT</a></li>` +
          `<li><a class="dropdown-item" href="${dlBase}?format=srt"><i class="fas fa-closed-captioning me-2"></i>SRT</a></li>` +
          `<li><hr class="dropdown-divider"></li>` +
          `<li><a class="dropdown-item" href="${dlBase}?format=pdf"><i class="fas fa-file-pdf me-2 text-danger"></i>PDF</a></li>` +
          `<li><a class="dropdown-item" href="${dlBase}?format=docx"><i class="fas fa-file-word me-2 text-primary"></i>DOCX</a></li>` +
        `</ul>` +
      `</div>`;
    }

    html += `<button class="btn btn-sm btn-outline-info duplicate-btn" data-id="${id}" title="Dupliquer (tester un autre modèle)"><i class="fas fa-copy"></i></button>`;
    html += `<button class="btn btn-sm btn-danger delete-btn" data-id="${id}" title="Supprimer"><i class="fas fa-trash"></i></button>`;

    actionsDiv.innerHTML = html;

    // Restore saved data-attributes onto the new settings-btn
    const newBtn = actionsDiv.querySelector('.settings-btn');
    if (newBtn && sd) {
      newBtn.dataset.backend         = sd.backend;
      newBtn.dataset.hotwords        = sd.hotwords;
      newBtn.dataset.preprocess      = sd.preprocess;
      newBtn.dataset.diarization     = sd.diarization;
      newBtn.dataset.temperature     = sd.temperature;
      newBtn.dataset.maxTokens       = sd.maxTokens;
      newBtn.dataset.generateSummary = sd.generateSummary;
      newBtn.dataset.summaryType     = sd.summaryType;
      newBtn.dataset.verifyCoherence = sd.verifyCoherence;
    }

    bindCardActions(card);
  }

  // ======================================================================
  // Card actions
  // ======================================================================
  function bindCardActions(scope) {
    const root = scope || document;

    root.querySelectorAll('.start-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleStart(btn.dataset.id));
    });

    root.querySelectorAll('.settings-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => openSettingsModal(btn));
    });

    root.querySelectorAll('.preview-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => openResultModal(btn.dataset.id));
    });

    root.querySelectorAll('.delete-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleDelete(btn.dataset.id));
    });

    root.querySelectorAll('.duplicate-btn').forEach(btn => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleDuplicate(btn.dataset.id));
    });
  }

  function handleStart(id) {
    const url = getUrl(config.startUrlTemplate, id);
    const card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);

    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          alert(data.error);
          return;
        }
        // Update card to RUNNING state
        if (card) {
          card.dataset.status = 'RUNNING';
          card.className = 'synthesis-card processing';
          const badge = card.querySelector('.status-badge');
          if (badge) { badge.textContent = 'RUNNING'; badge.className = 'badge status-badge bg-warning'; }
          const bar = card.querySelector('.progress-fill');
          if (bar) bar.style.width = '0%';
          const pt = card.querySelector('.progress-text');
          if (pt) pt.textContent = '0%';

          // Hide start+settings buttons during processing
          const actions = card.querySelector('.btn-group-actions');
          if (actions) {
            actions.querySelectorAll('.start-btn, .settings-btn').forEach(b => b.style.display = 'none');
          }
        }
        startPolling(id);
      })
      .catch(err => alert(err.message || 'Erreur'));
  }

  function handleDelete(id) {
    if (!confirm('Supprimer cette transcription ?')) return;

    const url = getUrl(config.deleteUrlTemplate, id);
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.deleted) throw new Error('Suppression impossible');
        const card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);
        if (card) card.remove();
        stopPolling(id);
        insertEmptyStateIfNeeded();
        updateDownloadAllState();
      })
      .catch(err => alert(err.message || 'Erreur lors de la suppression'));
  }

  function handleDuplicate(id) {
    const url = getUrl(config.duplicateUrlTemplate, id);
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        if (!data.duplicated) throw new Error('Duplication impossible');
        location.reload();
      })
      .catch(err => alert(err.message || 'Erreur lors de la duplication'));
  }

  // ======================================================================
  // Settings modal
  // ======================================================================
  function openSettingsModal(btn) {
    const modal = document.getElementById('settingsModal');
    if (!modal) return;

    document.getElementById('settingsTranscriptId').value = btn.dataset.id;
    document.getElementById('settingsBackend').value = btn.dataset.backend || 'auto';
    document.getElementById('settingsHotwords').value = btn.dataset.hotwords || '';
    document.getElementById('settingsPreprocess').checked = btn.dataset.preprocess === 'true';
    document.getElementById('settingsDiarization').checked = btn.dataset.diarization !== 'false';

    const temp = parseFloat(btn.dataset.temperature) || 0;
    document.getElementById('settingsTemperature').value = temp;
    document.getElementById('settingsTemperatureValue').textContent = temp;

    document.getElementById('settingsMaxTokens').value = parseInt(btn.dataset.maxTokens) || 32768;

    // New fields
    const genSummary = btn.dataset.generateSummary === 'true';
    const summaryType = btn.dataset.summaryType || 'structured';
    const verifyCoherence = btn.dataset.verifyCoherence === 'true';

    const genSumEl = document.getElementById('settingsGenerateSummary');
    const summaryTypeGroup = document.getElementById('summaryTypeGroup');
    if (genSumEl) {
      genSumEl.checked = genSummary;
      if (summaryTypeGroup) summaryTypeGroup.style.display = genSummary ? 'block' : 'none';
    }
    const stEl = document.querySelector(`input[name="summary_type"][value="${summaryType}"]`);
    if (stEl) stEl.checked = true;

    const vcEl = document.getElementById('settingsVerifyCoherence');
    if (vcEl) vcEl.checked = verifyCoherence;

    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();
  }

  // Toggle summary type group visibility — both global panel and per-transcript modal
  document.addEventListener('change', function(e) {
    if (e.target && e.target.id === 'settingsGenerateSummary') {
      const group = document.getElementById('summaryTypeGroup');
      if (group) group.style.display = e.target.checked ? 'block' : 'none';
    }
    if (e.target && e.target.id === 'globalGenerateSummary') {
      const group = document.getElementById('globalSummaryTypeGroup');
      if (group) group.style.display = e.target.checked ? 'block' : 'none';
    }
  });

  function saveSettings(andStart) {
    const id = document.getElementById('settingsTranscriptId').value;
    if (!id) return;

    const summaryTypeEl = document.querySelector('input[name="summary_type"]:checked');

    const payload = {
      backend: document.getElementById('settingsBackend').value,
      hotwords: document.getElementById('settingsHotwords').value,
      preprocess_audio: document.getElementById('settingsPreprocess').checked,
      enable_diarization: document.getElementById('settingsDiarization').checked,
      temperature: parseFloat(document.getElementById('settingsTemperature').value) || 0,
      max_tokens: parseInt(document.getElementById('settingsMaxTokens').value) || 32768,
      generate_summary: document.getElementById('settingsGenerateSummary')?.checked || false,
      summary_type: summaryTypeEl ? summaryTypeEl.value : 'structured',
      verify_coherence: document.getElementById('settingsVerifyCoherence')?.checked || false,
    };

    const url = getUrl(config.settingsUrlTemplate, id);
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(data => {
        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById('settingsModal'));
        if (modal) modal.hide();

        // Update card's data-attributes and options display
        const card = queueContainer.querySelector(`.synthesis-card[data-id="${id}"]`);
        if (card) {
          card.dataset.backend = payload.backend;
          card.dataset.hotwords = payload.hotwords;
          card.dataset.preprocess = payload.preprocess_audio ? 'true' : 'false';
          card.dataset.diarization = payload.enable_diarization ? 'true' : 'false';
          card.dataset.temperature = payload.temperature;
          card.dataset.maxTokens = payload.max_tokens;
          card.dataset.generateSummary = payload.generate_summary ? 'true' : 'false';
          card.dataset.summaryType = payload.summary_type;
          card.dataset.verifyCoherence = payload.verify_coherence ? 'true' : 'false';

          const settingsBtn = card.querySelector('.settings-btn');
          if (settingsBtn) {
            settingsBtn.dataset.backend = payload.backend;
            settingsBtn.dataset.hotwords = payload.hotwords;
            settingsBtn.dataset.preprocess = payload.preprocess_audio ? 'true' : 'false';
            settingsBtn.dataset.diarization = payload.enable_diarization ? 'true' : 'false';
            settingsBtn.dataset.temperature = payload.temperature;
            settingsBtn.dataset.maxTokens = payload.max_tokens;
            settingsBtn.dataset.generateSummary = payload.generate_summary ? 'true' : 'false';
            settingsBtn.dataset.summaryType = payload.summary_type;
            settingsBtn.dataset.verifyCoherence = payload.verify_coherence ? 'true' : 'false';
          }

          // Update options column display
          const optionsCol = card.querySelectorAll('.col-md-2')[0];
          if (optionsCol) {
            let optHtml = `<small><i class="fas fa-microchip"></i> ${escapeHtml(payload.backend)}<br>`;
            if (payload.hotwords) optHtml += `<i class="fas fa-tags"></i> ${escapeHtml(payload.hotwords.substring(0, 20))}${payload.hotwords.length > 20 ? '...' : ''}<br>`;
            if (payload.enable_diarization) optHtml += `<i class="fas fa-users"></i> Diarisation<br>`;
            if (payload.generate_summary) optHtml += `<i class="fas fa-file-lines"></i> Résumé<br>`;
            if (payload.verify_coherence) optHtml += `<i class="fas fa-spell-check"></i> Cohérence`;
            optHtml += '</small>';
            optionsCol.innerHTML = optHtml;
          }
        }

        if (andStart) handleStart(id);
      })
      .catch(err => alert(err.message || 'Erreur lors de la sauvegarde'));
  }

  // ======================================================================
  // Result modal — tabbed interface
  // ======================================================================

  const SPEAKER_COLORS = [
    '#4e79a7', '#f28e2b', '#e15759', '#76b7b2',
    '#59a14f', '#edc948', '#b07aa1', '#ff9da7',
    '#9c755f', '#bab0ac',
  ];
  const speakerColorMap = {};
  let speakerColorIdx = 0;

  function getSpeakerColor(speaker) {
    if (!speakerColorMap[speaker]) {
      speakerColorMap[speaker] = SPEAKER_COLORS[speakerColorIdx % SPEAKER_COLORS.length];
      speakerColorIdx++;
    }
    return speakerColorMap[speaker];
  }

  function renderDiarisation(segments) {
    const container = document.getElementById('diarisationContent');
    if (!container) return;

    const withSpeakers = segments.filter(s => s.speaker_id);
    if (!withSpeakers.length) {
      container.innerHTML = '<p class="text-muted text-center py-4">Aucune donnée de diarisation disponible.</p>';
      return;
    }

    // Reset color map for this transcript
    Object.keys(speakerColorMap).forEach(k => delete speakerColorMap[k]);
    speakerColorIdx = 0;

    let html = '';
    for (const seg of withSpeakers) {
      const color = getSpeakerColor(seg.speaker_id);
      const timeRange = seg.time_range || `${seg.start_time?.toFixed(1)}s → ${seg.end_time?.toFixed(1)}s`;
      html += `
        <div class="d-flex align-items-start mb-2 px-1">
          <div style="min-width: 120px;">
            <span class="badge me-1" style="background-color:${color}; color:#fff; font-size:0.75rem;">${escapeHtml(seg.speaker_id)}</span>
            <small class="text-muted">${escapeHtml(timeRange)}</small>
          </div>
          <div class="ms-2 text-light" style="font-size:14px; line-height:1.5;">${escapeHtml(seg.text || '')}</div>
        </div>`;
    }
    container.innerHTML = html;
  }

  function renderResume(data) {
    const resumeEl = document.getElementById('resumeContent');
    const tabBtn = document.getElementById('tab-resume-btn');
    if (!resumeEl || !tabBtn) return;

    if (!data.summary) {
      tabBtn.style.display = 'none';
      return;
    }

    tabBtn.style.display = '';

    // Convert markdown-like content to simple HTML
    let html = data.summary
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/### (.+)/g, '<h6 class="text-info mt-3 mb-1">$1</h6>')
      .replace(/## (.+)/g, '<h5 class="text-warning mt-3 mb-2">$1</h5>')
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/^- (.+)$/gm, '<li>$1</li>')
      .replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
      .replace(/\n\n/g, '<br><br>')
      .replace(/\n/g, '<br>');

    // Key points
    if (data.key_points && data.key_points.length) {
      html += '<h6 class="text-info mt-3">Points clés</h6><ul>';
      data.key_points.forEach(p => { html += `<li>${escapeHtml(String(p))}</li>`; });
      html += '</ul>';
    }

    // Action items
    if (data.action_items && data.action_items.length) {
      html += '<h6 class="text-warning mt-3">Actions à mener</h6><ul>';
      data.action_items.forEach(a => { html += `<li>${escapeHtml(String(a))}</li>`; });
      html += '</ul>';
    }

    resumeEl.innerHTML = html;
    setWordCount('wc-resume', data.summary || '');
  }

  function renderCoherence(data, originalText) {
    const container = document.getElementById('coherenceContent');
    const tabBtn = document.getElementById('tab-coherence-btn');
    if (!container || !tabBtn) return;

    if (data.coherence_score === null || data.coherence_score === undefined) {
      tabBtn.style.display = 'none';
      return;
    }

    tabBtn.style.display = '';

    const score = data.coherence_score;
    const scoreColor = score >= 80 ? 'success' : score >= 50 ? 'warning' : 'danger';

    let notesHtml = '';
    if (data.coherence_notes) {
      const notes = data.coherence_notes.split('\n').filter(l => l.trim());
      notesHtml = '<ul class="mt-2">' + notes.map(n => `<li class="text-light small">${escapeHtml(n)}</li>`).join('') + '</ul>';
    }

    let sideBySide = '';
    if (data.coherence_suggestion) {
      sideBySide = `
        <div class="row mt-3">
          <div class="col-md-6">
            <div class="card" style="background:#1e1e1e; border:1px solid #495057;">
              <div class="card-header py-1 small text-muted">Texte original</div>
              <div class="card-body p-2">
                <pre style="color:#d4d4d4; white-space:pre-wrap; font-size:13px; max-height:300px; overflow-y:auto; margin:0;">${escapeHtml(originalText || '')}</pre>
              </div>
            </div>
          </div>
          <div class="col-md-6">
            <div class="card" style="background:#1e2820; border:1px solid #2ea043;">
              <div class="card-header py-1 small text-muted">Correction proposée</div>
              <div class="card-body p-2">
                <pre style="color:#7ee787; white-space:pre-wrap; font-size:13px; max-height:300px; overflow-y:auto; margin:0;">${escapeHtml(data.coherence_suggestion)}</pre>
              </div>
            </div>
          </div>
        </div>`;
    }

    container.innerHTML = `
      <div class="d-flex align-items-center mb-2">
        <span class="badge bg-${scoreColor} fs-5 me-3">${score}/100</span>
        <span class="text-light">Score de cohérence</span>
      </div>
      ${notesHtml}
      ${sideBySide}`;
    setWordCount('wc-coherence', data.coherence_suggestion || originalText || '');
  }

  function openResultModal(id) {
    const modal = document.getElementById('resultModal');
    if (!modal) return;

    const resultText = document.getElementById('resultText');
    const title = document.getElementById('resultModalTitle');
    const dlBtn = document.getElementById('resultDownloadBtn');
    const srtBtn = document.getElementById('resultSrtBtn');

    if (title) title.textContent = `Transcription #${id}`;
    if (resultText) resultText.textContent = 'Chargement...';
    if (dlBtn) dlBtn.href = getUrl(config.downloadUrlTemplate, id) + '?format=txt';
    if (srtBtn) srtBtn.href = getUrl(config.downloadUrlTemplate, id) + '?format=srt';

    // Reset tabs visibility
    const tabResumeBtn = document.getElementById('tab-resume-btn');
    const tabCoherenceBtn = document.getElementById('tab-coherence-btn');
    if (tabResumeBtn) tabResumeBtn.style.display = 'none';
    if (tabCoherenceBtn) tabCoherenceBtn.style.display = 'none';

    // Reset diarisation
    const diarEl = document.getElementById('diarisationContent');
    if (diarEl) diarEl.innerHTML = '<p class="text-muted text-center py-3"><i class="fas fa-spinner fa-spin"></i> Chargement...</p>';

    // Activate transcription tab
    const transcriptionTab = document.getElementById('tab-transcription-btn');
    if (transcriptionTab) {
      const bsTab = new bootstrap.Tab(transcriptionTab);
      bsTab.show();
    }

    const bsModal = new bootstrap.Modal(modal);
    bsModal.show();

    // 1. Fetch progress data (text + summary + coherence)
    fetch(getUrl(config.progressUrlTemplate, id))
      .then(r => r.json())
      .then(data => {
        if (resultText) {
          resultText.textContent = data.text || data.partial_text || '(Aucun texte disponible)';
          setWordCount('wc-transcription', data.text || data.partial_text || '');
        }
        renderResume(data);
        renderCoherence(data, data.text || data.partial_text || '');
      })
      .catch(() => {
        if (resultText) resultText.textContent = 'Erreur de chargement';
      });

    // 2. Fetch segments for diarisation tab
    if (config.segmentsUrlTemplate) {
      fetch(getUrl(config.segmentsUrlTemplate, id))
        .then(r => r.json())
        .then(data => {
          renderDiarisation(data.segments || []);
        })
        .catch(() => {
          const diarEl2 = document.getElementById('diarisationContent');
          if (diarEl2) diarEl2.innerHTML = '<p class="text-muted text-center py-4">Erreur de chargement des segments.</p>';
        });
    }
  }

  // ======================================================================
  // Polling
  // ======================================================================
  function startPolling(id) {
    if (pollers.has(id)) return;
    const interval = setInterval(() => {
      fetch(getUrl(config.progressUrlTemplate, id))
        .then(r => r.json())
        .then(data => updateCard(id, data))
        .catch(() => stopPolling(id));
    }, 1200);
    pollers.set(id, interval);
  }

  function stopPolling(id) {
    const interval = pollers.get(id);
    if (interval) { clearInterval(interval); pollers.delete(id); }
  }

  // ======================================================================
  // Empty state
  // ======================================================================
  function removeEmptyState() {
    if (!queueContainer) return;
    const empty = queueContainer.querySelector('.empty-queue');
    if (empty) empty.remove();
  }

  function insertEmptyStateIfNeeded() {
    if (!queueContainer) return;
    const hasCards = queueContainer.querySelectorAll('.synthesis-card').length > 0;
    if (!hasCards && !queueContainer.querySelector('.empty-queue')) {
      const div = document.createElement('div');
      div.className = 'text-center py-5 empty-queue';
      div.innerHTML = '<i class="fas fa-inbox fa-3x mb-3 text-white-50"></i><p class="text-white-50">Aucune transcription en attente</p>';
      queueContainer.appendChild(div);
    }
  }

  // ======================================================================
  // Bulk actions
  // ======================================================================
  function initBulkActions() {
    if (startProcessBtn) startProcessBtn.addEventListener('click', handleStartAll);
    if (clearAllBtn) clearAllBtn.addEventListener('click', handleClearAll);
    if (downloadAllBtn) {
      downloadAllBtn.addEventListener('click', () => {
        window.location.href = config.startAllUrl.replace('start_all', 'download_all');
      });
    }
    if (preprocessToggle) {
      preprocessToggle.checked = preprocessEnabled;
      preprocessToggle.addEventListener('change', () => {
        preprocessEnabled = preprocessToggle.checked;
        persistPreprocessingPreference(preprocessEnabled);
        savePanelSettings();
      });
    }

    // Auto-save all other panel settings on change
    const panelBackendSel = document.getElementById('backendSelect');
    const panelHotwordsIn = document.getElementById('hotwordsInput');
    const panelDiarToggle = document.getElementById('diarizationToggle');
    const panelGenSumm    = document.getElementById('globalGenerateSummary');
    const panelVerifCoh   = document.getElementById('globalVerifyCoherence');
    if (panelBackendSel) panelBackendSel.addEventListener('change', savePanelSettings);
    if (panelHotwordsIn) panelHotwordsIn.addEventListener('blur', savePanelSettings);
    if (panelDiarToggle) panelDiarToggle.addEventListener('change', savePanelSettings);
    if (panelGenSumm)    panelGenSumm.addEventListener('change', savePanelSettings);
    if (panelVerifCoh)   panelVerifCoh.addEventListener('change', savePanelSettings);
    document.querySelectorAll('input[name="globalSummaryType"]').forEach(r =>
      r.addEventListener('change', savePanelSettings)
    );

    // Settings modal buttons
    const saveBtn = document.getElementById('saveSettingsBtn');
    const saveStartBtn = document.getElementById('saveAndStartBtn');
    if (saveBtn) saveBtn.addEventListener('click', () => saveSettings(false));
    if (saveStartBtn) saveStartBtn.addEventListener('click', () => saveSettings(true));

    // Reset button
    const resetBtn = document.getElementById('resetOptions');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        const backendEl = document.getElementById('backendSelect');
        if (backendEl) backendEl.value = 'auto';

        const hotwordsEl = document.getElementById('hotwordsInput');
        if (hotwordsEl) hotwordsEl.value = '';

        const preprocessEl = document.getElementById('preprocessingToggle');
        if (preprocessEl) { preprocessEl.checked = false; preprocessEnabled = false; }

        const diarizationEl = document.getElementById('diarizationToggle');
        if (diarizationEl) diarizationEl.checked = false;

        const genSummaryEl = document.getElementById('globalGenerateSummary');
        if (genSummaryEl) {
          genSummaryEl.checked = false;
          const group = document.getElementById('globalSummaryTypeGroup');
          if (group) group.style.display = 'none';
        }

        const summTypeEl = document.getElementById('globalSummaryTypeStructured');
        if (summTypeEl) summTypeEl.checked = true;

        const verifCoherEl = document.getElementById('globalVerifyCoherence');
        if (verifCoherEl) verifCoherEl.checked = false;

        savePanelSettings();
      });
    }
  }

  function handleStartAll() {
    if (!config.startAllUrl) return;
    startProcessBtn.disabled = true;
    fetch(config.startAllUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(data => {
        const started = data.started_ids || [];
        if (!started.length) { alert('Aucune transcription à démarrer.'); return; }
        started.forEach(id => startPolling(id));
        // Reload to get fresh card states
        window.location.reload();
      })
      .catch(err => alert(err.message || 'Erreur'))
      .finally(() => { startProcessBtn.disabled = false; });
  }

  function handleClearAll() {
    if (!config.clearUrl) return;
    if (!confirm('Supprimer toutes les transcriptions ?')) return;

    clearAllBtn.disabled = true;
    fetch(config.clearUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then(r => r.json())
      .then(() => {
        if (queueContainer) {
          queueContainer.querySelectorAll('.synthesis-card').forEach(c => c.remove());
        }
        pollers.forEach((_, id) => stopPolling(id));
        insertEmptyStateIfNeeded();
        updateDownloadAllState();
      })
      .catch(err => alert(err.message || 'Erreur'))
      .finally(() => { clearAllBtn.disabled = false; });
  }

  function updateDownloadAllState() {
    if (!downloadAllBtn || !queueContainer) return;
    const hasSuccess = !!queueContainer.querySelector('.synthesis-card[data-status="SUCCESS"]');
    downloadAllBtn.disabled = !hasSuccess;
  }

  function persistPreprocessingPreference(enabled) {
    const endpoint = config.preprocessingUrl || toggleDatasetUrl;
    if (!endpoint) return;
    fetch(endpoint, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ enabled }),
    }).catch(() => {
      if (preprocessToggle) preprocessToggle.checked = !enabled;
    });
  }

  function savePanelSettings() {
    if (!config.saveUserSettingsUrl) return;
    const backendSel  = document.getElementById('backendSelect');
    const hotwordsIn  = document.getElementById('hotwordsInput');
    const diarEl      = document.getElementById('diarizationToggle');
    const genSummEl   = document.getElementById('globalGenerateSummary');
    const summTypeEl  = document.querySelector('input[name="globalSummaryType"]:checked');
    const verifEl     = document.getElementById('globalVerifyCoherence');
    const payload = {
      backend:               backendSel ? backendSel.value  : 'auto',
      hotwords:              hotwordsIn ? hotwordsIn.value  : '',
      enable_diarization:    diarEl     ? diarEl.checked    : true,
      preprocessing_enabled: preprocessEnabled,
      generate_summary:      genSummEl  ? genSummEl.checked : false,
      summary_type:          summTypeEl ? summTypeEl.value  : 'structured',
      verify_coherence:      verifEl    ? verifEl.checked   : false,
    };
    fetch(config.saveUserSettingsUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload),
    }).catch(() => {});
  }

  // ======================================================================
  // Live transcription
  // ======================================================================
  function updateLiveTranscriptionFromQueue(transcriptId, status, partialText) {
    if (!liveOutput || !liveStatus) return;
    if (speakButton && speakButton.classList.contains('active')) return;

    const firstRunning = queueContainer ? queueContainer.querySelector('.synthesis-card[data-status="RUNNING"]') : null;

    if (!firstRunning) {
      if (liveOutput.textContent !== 'Appuyez sur Speak puis commencez à parler pour voir le texte apparaître ici en temps réel.') {
        liveOutput.textContent = 'Aucune transcription en cours.';
        liveStatus.textContent = 'En attente...';
      }
      return;
    }

    if (firstRunning.dataset.id !== String(transcriptId)) return;

    if (status === 'RUNNING') {
      liveStatus.textContent = `Transcription #${transcriptId} en cours...`;
    } else if (status === 'SUCCESS') {
      liveStatus.textContent = `Transcription #${transcriptId} terminée`;
    } else if (status === 'FAILURE') {
      liveStatus.textContent = `Transcription #${transcriptId} échouée`;
    }

    if (partialText && partialText.trim()) {
      displayTextWithHighlight(partialText);
    }
  }

  function displayTextWithHighlight(text) {
    if (!liveOutput) return;
    const words = text.split(/(\s+)/);
    let lastWordIndex = -1;
    for (let i = words.length - 1; i >= 0; i--) {
      if (words[i].trim().length > 0) { lastWordIndex = i; break; }
    }
    if (lastWordIndex >= 0) {
      const htmlParts = words.map((word, index) => {
        if (index === lastWordIndex) {
          return `<mark style="background-color: #ffc107; color: #000; padding: 2px 4px; border-radius: 3px;">${escapeHtml(word)}</mark>`;
        }
        return escapeHtml(word);
      });
      liveOutput.innerHTML = htmlParts.join('');
    } else {
      liveOutput.textContent = text;
    }
  }

  // ======================================================================
  // Speech recognition
  // ======================================================================
  function initSpeech() {
    if (!speakButton || !liveOutput || !liveStatus) return;
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      speakButton.disabled = true;
      liveStatus.textContent = 'Non supporté par ce navigateur';
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.lang = 'fr-FR';
    recognition.continuous = true;
    recognition.interimResults = true;

    let listening = false;
    let finalTranscript = '';

    recognition.onstart = () => {
      listening = true; finalTranscript = '';
      speakButton.classList.add('active');
      speakButton.innerHTML = '<i class="fas fa-stop"></i> Stop';
      liveStatus.textContent = 'Écoute en cours...';
    };
    recognition.onerror = (event) => {
      liveStatus.textContent = `Erreur: ${event.error}`;
      speakButton.classList.remove('active');
      speakButton.innerHTML = '<i class="fas fa-microphone"></i> Speak';
      listening = false;
    };
    recognition.onend = () => {
      speakButton.classList.remove('active');
      speakButton.innerHTML = '<i class="fas fa-microphone"></i> Speak';
      listening = false;
      liveStatus.textContent = finalTranscript ? 'Session terminée' : 'En attente...';
    };
    recognition.onresult = (event) => {
      let interimTranscript = '';
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) finalTranscript += transcript + '\n';
        else interimTranscript += transcript;
      }
      const fullText = (finalTranscript + interimTranscript).trim();
      if (fullText && fullText !== '...') displayTextWithHighlight(fullText);
      else liveOutput.textContent = '...';
    };

    speakButton.addEventListener('click', () => {
      if (listening) recognition.stop();
      else try { recognition.start(); } catch (e) { console.error(e); }
    });
  }

  // ======================================================================
  // Global progress
  // ======================================================================
  function updateGlobalProgress() {
    if (!config.globalProgressUrl) return;
    fetch(config.globalProgressUrl)
      .then(r => r.json())
      .then(data => {
        const bar = document.getElementById('globalProgressBar');
        const stats = document.getElementById('globalProgressStats');
        if (bar && stats) {
          const p = data.overall_progress || 0;
          bar.style.width = p + '%';
          bar.textContent = p + '%';
          stats.textContent = `${data.success}/${data.total} terminé`;
          bar.className = 'progress-bar';
          if (data.failure > 0) bar.classList.add('bg-danger');
          else if (data.running > 0) bar.classList.add('progress-bar-animated', 'progress-bar-striped');
          else if (data.success === data.total && data.total > 0) bar.classList.add('bg-success');
        }
      })
      .catch(err => console.error('Error updating global progress:', err));
  }

  // ======================================================================
  // Init
  // ======================================================================
  function initExistingCards() {
    if (!queueContainer) return;
    queueContainer.querySelectorAll('.synthesis-card[data-id]').forEach(card => {
      const status = (card.dataset.status || '').toUpperCase();
      bindCardActions(card);
      if (['PENDING', 'RUNNING', 'STARTED'].includes(status)) {
        startPolling(card.dataset.id);
      }
    });
    updateDownloadAllState();
  }

  // ======================================================================
  // Async backends loading (non-blocking)
  // ======================================================================
  async function loadBackendsAsync() {
    if (!config.backendsUrl) return;
    try {
      const resp = await fetch(config.backendsUrl);
      if (!resp.ok) return;
      const data = await resp.json();
      const backends = data.backends || [];
      if (!backends.length) return;

      const options = backends.map(b => {
        const label = b.display_name + (b.supports_diarization ? ' (diarisation)' : '');
        return `<option value="${escapeHtml(b.name)}">${escapeHtml(label)}</option>`;
      }).join('');

      // Populate global panel selector and restore saved value
      const globalSel = document.getElementById('backendSelect');
      if (globalSel) {
        const savedValue = globalSel.dataset.selected || 'auto';
        globalSel.insertAdjacentHTML('beforeend', options);
        globalSel.value = savedValue;
      }

      // Populate settings modal selector (value set when modal opens)
      const settingsSel = document.getElementById('settingsBackend');
      if (settingsSel) {
        settingsSel.insertAdjacentHTML('beforeend', options);
      }
    } catch (_) {
      // silently ignore — "Auto" remains functional
    }
  }

  initUpload();
  initDragDrop();
  initYoutube();
  initExistingCards();
  initSpeech();
  initBulkActions();
  initBatchBar();
  loadBackendsAsync();

  updateGlobalProgress();
  setInterval(updateGlobalProgress, 2000);
});

// Filemanager 'Envoyer vers...' — reload page to show imported item
document.addEventListener('wama:fileimported', function(e) {
    if (e.detail && e.detail.app === 'transcriber') { window.location.reload(); }
});
