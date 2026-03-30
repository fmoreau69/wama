/**
 * WAMA Enhancer — Audio Speech Enhancement
 * Handles Resemble Enhance (quality) and DeepFilterNet 3 (speed).
 */
document.addEventListener('DOMContentLoaded', function () {
  const cfg = window.AUDIO_ENHANCER_APP || {};
  const csrfToken = cfg.csrfToken;

  const pollers = new Map();

  function csrfHeaders(extra) {
    return Object.assign({}, extra || {}, { 'X-CSRFToken': csrfToken });
  }

  function getUrl(template, id) {
    return template.replace('/0/', '/' + id + '/');
  }

  // ── Right-panel settings visibility ──────────────────────────────────────

  function getEngine() {
    const el = document.getElementById('audioEngine');
    return el ? el.value : 'resemble';
  }

  function updateResembleVisibility() {
    const engine = getEngine();
    const resembleOnly = document.querySelectorAll('.resemble-only');
    resembleOnly.forEach(el => {
      el.style.display = engine === 'resemble' ? '' : 'none';
    });
  }

  const audioEngineSelect = document.getElementById('audioEngine');
  if (audioEngineSelect) {
    audioEngineSelect.addEventListener('change', updateResembleVisibility);
    updateResembleVisibility();
  }

  // Denoising strength display
  const strengthSlider = document.getElementById('audioDenoisingStrength');
  const strengthVal = document.getElementById('audioStrengthValue');
  if (strengthSlider && strengthVal) {
    strengthSlider.addEventListener('input', () => {
      strengthVal.textContent = parseFloat(strengthSlider.value).toFixed(1);
    });
  }

  // ── Batch file detection ─────────────────────────────────────────────────

  const AUDIO_BATCH_EXTS = ['txt', 'md', 'csv', 'pdf', 'docx'];
  let _audioBatchFile = null;
  let _audioBatchItems = [];

  // ── File upload ───────────────────────────────────────────────────────────

  async function uploadAudioFile(file) {
    const body = new FormData();
    body.append('file', file);

    try {
      const resp = await fetch(cfg.audioUploadUrl, {
        method: 'POST',
        headers: csrfHeaders(),
        body,
      });
      const data = await resp.json();
      if (data.error) throw new Error(data.error);
      appendAudioRow(data);
    } catch (err) {
      alert('Erreur upload audio: ' + err.message);
    }
  }

  async function handleAudioFiles(files) {
    const fileList = Array.from(files);
    if (fileList.length === 1) {
      const ext = fileList[0].name.split('.').pop().toLowerCase();
      if (AUDIO_BATCH_EXTS.includes(ext)) {
        await _handleAudioBatchFileDetect(fileList[0]);
        return;
      }
    }
    for (const f of fileList) {
      await uploadAudioFile(f);
    }
  }

  function initAudioUpload() {
    const fileInput = document.getElementById('audio-enhancer-file');
    if (!fileInput) return;
    fileInput.addEventListener('change', function () {
      if (!this.files.length) return;
      handleAudioFiles(this.files);
      fileInput.value = '';
    });
  }

  function initAudioDragDrop() {
    const dropZone = document.getElementById('dropZoneAudio');
    const browseBtn = document.getElementById('audio-browse-btn');
    const fileInput = document.getElementById('audio-enhancer-file');
    if (!dropZone || !fileInput) return;

    dropZone.addEventListener('click', e => {
      if (e.target !== browseBtn) fileInput.click();
    });
    if (browseBtn) {
      browseBtn.addEventListener('click', e => {
        e.stopPropagation();
        fileInput.click();
      });
    }

    dropZone.addEventListener('dragover', e => {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });
    dropZone.addEventListener('dragleave', () => {
      dropZone.classList.remove('drag-over');
    });
    dropZone.addEventListener('drop', e => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      const allFiles = Array.from(e.dataTransfer.files);
      // Allow batch files through
      const files = allFiles.filter(f => {
        const ext = f.name.split('.').pop().toLowerCase();
        return AUDIO_BATCH_EXTS.includes(ext) || /\.(mp3|wav|flac|ogg|m4a|aac|opus|wma)$/i.test(f.name);
      });
      if (files.length === 0) {
        alert('Formats acceptés : MP3, WAV, FLAC, OGG, M4A, AAC, OPUS, WMA (ou fichier batch .txt/.csv/.md)');
        return;
      }
      handleAudioFiles(files);
    });
  }

  // ── Audio Batch bar ──────────────────────────────────────────────────────

  async function _handleAudioBatchFileDetect(file) {
    _audioBatchFile = file;
    _audioBatchItems = [];
    if (!cfg.audioBatchPreviewUrl) { await uploadAudioFile(file); return; }

    const fd = new FormData();
    fd.append('batch_file', file);
    try {
      const resp = await fetch(cfg.audioBatchPreviewUrl, { method: 'POST', headers: csrfHeaders(), body: fd });
      const data = await resp.json();
      if (data.error || !data.items || data.items.length === 0) { await uploadAudioFile(file); return; }
      _audioBatchItems = data.items;
      _showAudioBatchBar(data);
    } catch (e) {
      await uploadAudioFile(file);
    }
  }

  function _showAudioBatchBar(data) {
    const bar = document.getElementById('audioBatchDetectBar');
    if (!bar) return;
    const cnt = document.getElementById('audioBatchDetectedCount');
    if (cnt) cnt.textContent = data.count;
    const preview = document.getElementById('audioBatchDetectPreview');
    if (preview) preview.style.display = 'none';
    bar.style.display = '';
  }

  function _hideAudioBatchBar() {
    const bar = document.getElementById('audioBatchDetectBar');
    if (bar) bar.style.display = 'none';
    const preview = document.getElementById('audioBatchDetectPreview');
    if (preview) preview.style.display = 'none';
    _audioBatchFile = null;
    _audioBatchItems = [];
  }

  function _populateAudioBatchPreview(data) {
    const tbody = document.getElementById('audioBatchDetectTable');
    if (tbody) {
      tbody.innerHTML = '';
      (data.items || []).forEach(item => {
        const tr = document.createElement('tr');
        tr.innerHTML = `<td style="word-break:break-all;">${item.filename || item.path}</td>`;
        tbody.appendChild(tr);
      });
    }
    const cnt = document.getElementById('audioBatchCreateCount');
    if (cnt) cnt.textContent = data.count;
    const warnEl = document.getElementById('audioBatchDetectWarnings');
    if (warnEl) {
      if (data.warnings && data.warnings.length > 0) {
        warnEl.textContent = data.warnings.join(' | ');
        warnEl.style.display = '';
      } else {
        warnEl.style.display = 'none';
      }
    }
  }

  async function _doAudioBatchImport(autoStart) {
    if (!_audioBatchFile) return;
    const progress = document.getElementById('audioBatchCreateProgress');
    const btnStart = document.getElementById('audioBatchCreateAndStartBtn');
    const btnOnly  = document.getElementById('audioBatchCreateOnlyBtn');
    if (progress) progress.style.display = '';
    if (btnStart) btnStart.disabled = true;
    if (btnOnly)  btnOnly.disabled  = true;

    const fd = new FormData();
    fd.append('batch_file', _audioBatchFile);

    try {
      const resp = await fetch(cfg.audioBatchCreateUrl, { method: 'POST', headers: csrfHeaders(), body: fd });
      const data = await resp.json();
      if (!resp.ok) { alert(data.error || 'Erreur création batch'); return; }
      if (autoStart && data.batch_id) {
        const startUrl = cfg.audioBatchStartUrlTemplate.replace('/0/', `/${data.batch_id}/`);
        const engine = document.getElementById('audioEngine')?.value || 'resemble';
        const mode   = document.getElementById('audioMode')?.value || 'both';
        const strength = document.getElementById('audioDenoisingStrength')?.value || '0.5';
        const quality  = document.getElementById('audioQuality')?.value || '64';
        await fetch(startUrl, {
          method: 'POST',
          headers: csrfHeaders({ 'Content-Type': 'application/json' }),
          body: JSON.stringify({ engine, mode, denoising_strength: parseFloat(strength), quality: parseInt(quality) }),
        });
      }
      _hideAudioBatchBar();
      setTimeout(() => location.reload(), 600);
    } catch (e) {
      alert('Erreur lors de la création du batch audio');
    } finally {
      if (progress) progress.style.display = 'none';
      if (btnStart) btnStart.disabled = false;
      if (btnOnly)  btnOnly.disabled  = false;
    }
  }

  function initAudioBatchBar() {
    const previewBtn = document.getElementById('audioBatchPreviewBtn');
    if (previewBtn) {
      previewBtn.addEventListener('click', async () => {
        if (!_audioBatchFile) return;
        const fd = new FormData();
        fd.append('batch_file', _audioBatchFile);
        try {
          const resp = await fetch(cfg.audioBatchPreviewUrl, { method: 'POST', headers: csrfHeaders(), body: fd });
          const data = await resp.json();
          if (!data.error) {
            _populateAudioBatchPreview(data);
            const preview = document.getElementById('audioBatchDetectPreview');
            if (preview) preview.style.display = '';
          }
        } catch (e) {}
      });
    }

    const cancelBtn = document.getElementById('audioBatchCancelBar');
    if (cancelBtn) cancelBtn.addEventListener('click', _hideAudioBatchBar);

    const createAndStartBtn = document.getElementById('audioBatchCreateAndStartBtn');
    if (createAndStartBtn) createAndStartBtn.addEventListener('click', () => _doAudioBatchImport(true));

    const createOnlyBtn = document.getElementById('audioBatchCreateOnlyBtn');
    if (createOnlyBtn) createOnlyBtn.addEventListener('click', () => _doAudioBatchImport(false));
  }

  // ── Queue row management ──────────────────────────────────────────────────

  function appendAudioRow(data) {
    const container = document.getElementById('audio-enhancer-queue');
    if (!container) return;

    const empty = container.querySelector('.empty-state');
    if (empty) empty.remove();

    const durationStr = data.duration
      ? (data.duration >= 60
          ? Math.floor(data.duration / 60) + 'min ' + Math.round(data.duration % 60) + 's'
          : data.duration.toFixed(1) + 's')
      : '—';

    const card = document.createElement('div');
    card.className = 'synthesis-card';
    card.dataset.id = data.id;
    card.dataset.status = data.status || 'PENDING';
    card.innerHTML = `
      <div class="row align-items-center">
        <div class="col-md-3">
          <button type="button" class="btn btn-link p-0 text-start preview-media-link"
                  data-preview-url="/common/preview/audio_enhancer/${data.id}/"
                  style="color: #fff; text-decoration: none; font-size: 0.9rem;">
            <i class="fas fa-microphone-alt text-success"></i> ${escHtml(data.input_filename || '')}
          </button>
          <br>
          <small class="text-white-50">${durationStr}</small>
        </div>
        <div class="col-md-3">
          <small>
            <span class="badge bg-info audio-engine-badge">—</span>
            <span class="text-white-50 ms-1 properties-text">—</span>
            <br>
            <span class="badge bg-secondary audio-mode-badge mt-1">—</span>
          </small>
        </div>
        <div class="col-md-2">
          <span class="status-badge badge bg-secondary">PENDING</span>
          <div class="progress-bar-custom mt-2">
            <div class="progress-fill" style="width: 0%"></div>
          </div>
          <small class="progress-text text-light">0%</small>
        </div>
        <div class="col-md-4">
          <div class="btn-group-actions">
            <button class="btn btn-sm btn-secondary js-audio-settings"
                    data-id="${data.id}"
                    data-engine="resemble" data-mode="both"
                    data-strength="0.5" data-quality="64"
                    title="Paramètres">
              <i class="fas fa-cog"></i>
            </button>
            <button class="btn btn-sm btn-primary js-audio-start action-btn"
                    data-id="${data.id}" title="Lancer">
              <i class="fas fa-play"></i>
            </button>
            <button class="btn btn-sm btn-danger js-audio-delete action-delete"
                    data-id="${data.id}" title="Supprimer">
              <i class="fas fa-trash-alt"></i>
            </button>
          </div>
        </div>
      </div>
    `;
    container.appendChild(card);

    if (typeof window.initMediaPreview === 'function') {
      window.initMediaPreview();
    }
    updateAudioGlobalProgress();
  }

  function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function updateRow(id, data) {
    const container = document.getElementById('audio-enhancer-queue');
    const card = container ? container.querySelector(`[data-id="${id}"]`) : null;
    if (!card) return;

    if (data.status) {
      const status = data.status.toUpperCase();
      card.dataset.status = status;

      // Status badge
      const statusBadge = card.querySelector('.status-badge');
      if (statusBadge) {
        const badgeClass = { PENDING: 'bg-secondary', RUNNING: 'bg-warning', SUCCESS: 'bg-success', FAILURE: 'bg-danger' }[status] || 'bg-secondary';
        statusBadge.textContent = status;
        statusBadge.className = `status-badge badge ${badgeClass}`;
      }

      // Card border
      card.classList.remove('processing', 'success', 'error');
      if (status === 'RUNNING') card.classList.add('processing');
      else if (status === 'SUCCESS') card.classList.add('success');
      else if (status === 'FAILURE') card.classList.add('error');

      // Action button
      const actionBtn = card.querySelector('.action-btn');
      if (actionBtn) {
        if (status === 'RUNNING') {
          actionBtn.disabled = true;
          actionBtn.className = 'btn btn-sm btn-secondary action-btn';
          actionBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
          actionBtn.title = 'En cours...';
        } else if (status === 'SUCCESS' || status === 'FAILURE') {
          actionBtn.disabled = false;
          actionBtn.className = 'btn btn-sm btn-warning js-audio-start action-btn';
          actionBtn.innerHTML = '<i class="fas fa-redo"></i>';
          actionBtn.title = 'Relancer';
        } else {
          actionBtn.disabled = false;
          actionBtn.className = 'btn btn-sm btn-primary js-audio-start action-btn';
          actionBtn.innerHTML = '<i class="fas fa-play"></i>';
          actionBtn.title = 'Lancer';
        }
      }

      // Show download button on SUCCESS
      if (status === 'SUCCESS' && !card.querySelector('.js-audio-download')) {
        const actionsDiv = card.querySelector('.btn-group-actions');
        const deleteBtn = card.querySelector('.action-delete');
        if (actionsDiv && deleteBtn) {
          const dlBtn = document.createElement('a');
          dlBtn.className = 'btn btn-sm btn-success js-audio-download';
          dlBtn.href = getUrl(cfg.audioDownloadUrlTemplate, id);
          dlBtn.title = 'Télécharger';
          dlBtn.innerHTML = '<i class="fas fa-download"></i>';
          actionsDiv.insertBefore(dlBtn, deleteBtn);
        }
        // Waveform player (audio URL = download URL, compatible WaveSurfer fetch)
        if (!document.getElementById('audioPlayer_' + id) && window.WamaAudioPlayer) {
          WamaAudioPlayer.inject(getUrl(cfg.audioDownloadUrlTemplate, id), id, card);
        }
      }
    }

    if (data.progress !== undefined) {
      const fill = card.querySelector('.progress-fill');
      if (fill) fill.style.width = data.progress + '%';
      const progressText = card.querySelector('.progress-text');
      if (progressText) progressText.textContent = data.progress + '%';
    }
  }

  // ── Per-row settings modal ───────────────────────────────────────────────

  function createAudioSettingsModal(id, engine, mode, strength, quality) {
    const existing = document.getElementById(`audioSettingsModal${id}`);
    if (existing) existing.remove();

    const resembleDisplay = engine === 'resemble' ? '' : 'none';

    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.id = `audioSettingsModal${id}`;
    modal.setAttribute('tabindex', '-1');
    modal.innerHTML = `
      <div class="modal-dialog">
        <div class="modal-content bg-dark text-white">
          <div class="modal-header border-secondary">
            <h5 class="modal-title"><i class="fas fa-microphone-alt me-2 text-success"></i>Paramètres audio — #${id}</h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <div class="mb-3">
              <label class="form-label small fw-bold text-light">Moteur</label>
              <select class="form-select bg-dark text-white border-secondary modal-audio-engine">
                <option value="resemble"     ${engine === 'resemble'     ? 'selected' : ''}>Resemble Enhance (Recommandé)</option>
                <option value="deepfilternet" ${engine === 'deepfilternet' ? 'selected' : ''}>DeepFilterNet 3 (Rapide)</option>
              </select>
            </div>
            <div class="modal-resemble-only" style="display:${resembleDisplay}">
              <div class="mb-3">
                <label class="form-label small fw-bold text-light">Mode</label>
                <select class="form-select bg-dark text-white border-secondary modal-audio-mode">
                  <option value="both"    ${mode === 'both'    ? 'selected' : ''}>Débruitage + Amélioration</option>
                  <option value="denoise" ${mode === 'denoise' ? 'selected' : ''}>Débruitage seul (Rapide)</option>
                  <option value="enhance" ${mode === 'enhance' ? 'selected' : ''}>Amélioration seule</option>
                </select>
              </div>
              <div class="mb-3">
                <label class="form-label small fw-bold text-light">
                  Force débruitage: <span class="modal-strength-val">${parseFloat(strength).toFixed(1)}</span>
                </label>
                <input type="range" class="form-range modal-audio-strength"
                       min="0" max="1" step="0.1" value="${strength}">
              </div>
              <div class="mb-3">
                <label class="form-label small fw-bold text-light">Qualité (NFE)</label>
                <select class="form-select bg-dark text-white border-secondary modal-audio-quality">
                  <option value="32"  ${quality === '32'  ? 'selected' : ''}>Rapide (32 étapes)</option>
                  <option value="64"  ${quality === '64'  ? 'selected' : ''}>Équilibré (64 étapes)</option>
                  <option value="128" ${quality === '128' ? 'selected' : ''}>Meilleur (128 étapes)</option>
                </select>
              </div>
            </div>
          </div>
          <div class="modal-footer border-secondary">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
            <button type="button" class="btn btn-primary modal-audio-save" data-id="${id}" data-bs-dismiss="modal">
              Sauvegarder
            </button>
            <button type="button" class="btn btn-success modal-audio-save-start" data-id="${id}" data-bs-dismiss="modal">
              <i class="fas fa-play"></i> Sauvegarder et lancer
            </button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Engine toggle
    const engineSel = modal.querySelector('.modal-audio-engine');
    const resembleSection = modal.querySelector('.modal-resemble-only');
    engineSel.addEventListener('change', () => {
      resembleSection.style.display = engineSel.value === 'resemble' ? '' : 'none';
    });

    // Strength display
    const strengthInput = modal.querySelector('.modal-audio-strength');
    const strengthDisplay = modal.querySelector('.modal-strength-val');
    strengthInput.addEventListener('input', () => {
      strengthDisplay.textContent = parseFloat(strengthInput.value).toFixed(1);
    });

    // Save helpers
    function readModalSettings() {
      return {
        engine:   modal.querySelector('.modal-audio-engine').value,
        mode:     modal.querySelector('.modal-audio-mode').value,
        strength: modal.querySelector('.modal-audio-strength').value,
        quality:  modal.querySelector('.modal-audio-quality').value,
      };
    }

    function applyToGearBtn(settings) {
      const gearBtn = document.querySelector(`#audio-enhancer-queue .js-audio-settings[data-id="${id}"]`);
      if (gearBtn) {
        gearBtn.dataset.engine   = settings.engine;
        gearBtn.dataset.mode     = settings.mode;
        gearBtn.dataset.strength = settings.strength;
        gearBtn.dataset.quality  = settings.quality;
      }
    }

    modal.querySelector('.modal-audio-save').addEventListener('click', () => {
      applyToGearBtn(readModalSettings());
    });

    modal.querySelector('.modal-audio-save-start').addEventListener('click', () => {
      const s = readModalSettings();
      applyToGearBtn(s);
      // Override right-panel settings then start
      const engineEl = document.getElementById('audioEngine');
      const modeEl   = document.getElementById('audioMode');
      const strEl    = document.getElementById('audioDenoisingStrength');
      const qualEl   = document.getElementById('audioQuality');
      const strValEl = document.getElementById('audioStrengthValue');
      if (engineEl) { engineEl.value = s.engine; updateResembleVisibility(); }
      if (modeEl)   modeEl.value = s.mode;
      if (strEl)    strEl.value  = s.strength;
      if (strValEl) strValEl.textContent = parseFloat(s.strength).toFixed(1);
      if (qualEl)   qualEl.value = s.quality;
      startAudio(parseInt(id));
    });

    // Clean up modal from DOM after hide
    modal.addEventListener('hidden.bs.modal', () => modal.remove());

    return modal;
  }

  function openAudioSettingsModal(btn) {
    const id       = btn.dataset.id;
    const engine   = btn.dataset.engine   || 'resemble';
    const mode     = btn.dataset.mode     || 'both';
    const strength = btn.dataset.strength || '0.5';
    const quality  = btn.dataset.quality  || '64';

    const modal = createAudioSettingsModal(id, engine, mode, strength, quality);
    new bootstrap.Modal(modal).show();
  }

  // ── Start / polling (also called from modal "Save and Start") ────────────

  async function startAudio(id) {
    const engine = document.getElementById('audioEngine')?.value || 'resemble';
    const mode = document.getElementById('audioMode')?.value || 'both';
    const strength = document.getElementById('audioDenoisingStrength')?.value || '0.5';
    const quality = document.getElementById('audioQuality')?.value || '64';

    try {
      const resp = await fetch(getUrl(cfg.audioStartUrlTemplate, id), {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ engine, mode, denoising_strength: parseFloat(strength), quality: parseInt(quality) }),
      });
      const data = await resp.json();
      if (data.error) throw new Error(data.error);

      updateRow(id, { status: 'RUNNING', progress: 0 });
      pollAudioProgress(id);

      // Update badge labels, properties, and gear button data on the row
      const row = document.querySelector(`#audio-enhancer-queue [data-id="${id}"]`);
      if (row) {
        const engBadge = row.querySelector('.audio-engine-badge');
        const modeBadge = row.querySelector('.audio-mode-badge');
        const propsText = row.querySelector('.properties-text');
        if (engBadge) engBadge.textContent = engine === 'resemble' ? 'Resemble' : 'DeepFilter';
        if (modeBadge) modeBadge.textContent = mode;
        if (propsText) {
          propsText.textContent = engine === 'resemble'
            ? `Force ${parseFloat(strength).toFixed(1)} / NFE ${quality}`
            : 'Rapide';
        }
        // Persist used settings on the gear button for next time
        const gearBtn = row.querySelector('.js-audio-settings');
        if (gearBtn) {
          gearBtn.dataset.engine   = engine;
          gearBtn.dataset.mode     = mode;
          gearBtn.dataset.strength = strength;
          gearBtn.dataset.quality  = quality;
        }
      }
    } catch (err) {
      alert('Erreur démarrage: ' + err.message);
    }
  }

  function pollAudioProgress(id) {
    if (pollers.has(id)) return;

    const interval = setInterval(async () => {
      try {
        const resp = await fetch(getUrl(cfg.audioProgressUrlTemplate, id));
        const data = await resp.json();
        updateRow(id, data);

        if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
          clearInterval(interval);
          pollers.delete(id);
          updateAudioGlobalProgress();
        }
      } catch (e) {
        clearInterval(interval);
        pollers.delete(id);
      }
    }, 1500);

    pollers.set(id, interval);
  }

  async function deleteAudio(id) {
    if (!confirm('Supprimer cet audio ?')) return;
    try {
      await fetch(getUrl(cfg.audioDeleteUrlTemplate, id), {
        method: 'POST',
        headers: csrfHeaders(),
      });
      const container = document.getElementById('audio-enhancer-queue');
      const card = container ? container.querySelector(`[data-id="${id}"]`) : null;
      if (card) {
        // If inside a batch group, remove the group if it becomes empty
        const batchGroup = card.closest('.batch-group');
        card.remove();
        if (batchGroup && !batchGroup.querySelector('[data-id]')) {
          batchGroup.remove();
        }
      }
      if (pollers.has(id)) {
        clearInterval(pollers.get(id));
        pollers.delete(id);
      }
      if (container && !container.querySelector('[data-id]')) {
        const el = document.createElement('div');
        el.className = 'empty-state text-center py-4 text-white-50';
        el.textContent = 'Aucun fichier audio en attente.';
        container.appendChild(el);
      }
      updateAudioGlobalProgress();
    } catch (err) {
      alert('Erreur suppression: ' + err.message);
    }
  }

  // ── Global progress ───────────────────────────────────────────────────────

  async function updateAudioGlobalProgress() {
    if (!cfg.audioGlobalProgressUrl) return;
    try {
      const resp = await fetch(cfg.audioGlobalProgressUrl);
      const data = await resp.json();

      const bar = document.getElementById('audioGlobalProgressBar');
      const stats = document.getElementById('audioGlobalProgressStats');
      const pct = document.getElementById('audioGlobalProgressPct');
      const audioStatus = document.getElementById('audioGlobalStatus');
      const progress = data.overall_progress || 0;
      if (bar) bar.style.width = progress + '%';
      if (stats) stats.textContent = `${data.success}/${data.total} terminé · ${data.running} en cours`;
      if (pct) pct.textContent = progress ? progress + '%' : '';
      if (audioStatus) {
        const active = (data.total || 0) > 0;
        audioStatus.style.opacity = active ? '1' : '0';
        audioStatus.style.pointerEvents = active ? '' : 'none';
      }

      // Enable/disable download-all
      const dlAllBtn = document.getElementById('audio-download-all-btn');
      if (dlAllBtn) {
        dlAllBtn.disabled = data.success === 0;
      }
    } catch (e) {
      // ignore
    }
  }

  // ── Button handlers ───────────────────────────────────────────────────────

  function initButtons() {
    // Start all
    const startAllBtn = document.getElementById('audio-process-btn');
    if (startAllBtn) {
      startAllBtn.addEventListener('click', async () => {
        const engine = document.getElementById('audioEngine')?.value || 'resemble';
        const mode = document.getElementById('audioMode')?.value || 'both';
        const strength = document.getElementById('audioDenoisingStrength')?.value || '0.5';
        const quality = document.getElementById('audioQuality')?.value || '64';

        try {
          const resp = await fetch(cfg.audioStartAllUrl, {
            method: 'POST',
            headers: csrfHeaders({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ engine, mode, denoising_strength: parseFloat(strength), quality: parseInt(quality) }),
          });
          const data = await resp.json();
          data.started_ids?.forEach(id => {
            updateRow(id, { status: 'RUNNING', progress: 0 });
            pollAudioProgress(id);
          });
        } catch (err) {
          alert('Erreur: ' + err.message);
        }
      });
    }

    // Clear all
    const clearBtn = document.getElementById('audio-clear-btn');
    if (clearBtn) {
      clearBtn.addEventListener('click', async () => {
        if (!confirm('Effacer tous les fichiers audio ?')) return;
        try {
          await fetch(cfg.audioClearUrl, { method: 'POST', headers: csrfHeaders() });
          const container = document.getElementById('audio-enhancer-queue');
          if (container) {
            container.querySelectorAll('[data-id]').forEach(card => card.remove());
            const el = document.createElement('div');
            el.className = 'empty-state text-center py-4 text-white-50';
            el.textContent = 'Aucun fichier audio en attente.';
            container.appendChild(el);
          }
          pollers.forEach(clearInterval);
          pollers.clear();
          updateAudioGlobalProgress();
        } catch (err) {
          alert('Erreur: ' + err.message);
        }
      });
    }

    // Download all
    const dlAllBtn = document.getElementById('audio-download-all-btn');
    if (dlAllBtn) {
      dlAllBtn.addEventListener('click', () => {
        window.location.href = cfg.audioDownloadAllUrl;
      });
    }

    // Queue table: per-row buttons (event delegation)
    const queueTable = document.getElementById('audio-enhancer-queue');
    if (queueTable) {
      queueTable.addEventListener('click', e => {
        const startBtn    = e.target.closest('.js-audio-start');
        const dlBtn       = e.target.closest('.js-audio-download');
        const delBtn      = e.target.closest('.js-audio-delete');
        const settingsBtn = e.target.closest('.js-audio-settings');

        if (startBtn) startAudio(parseInt(startBtn.dataset.id));
        if (delBtn) deleteAudio(parseInt(delBtn.dataset.id));
        if (settingsBtn) openAudioSettingsModal(settingsBtn);
        if (dlBtn && !dlBtn.classList.contains('disabled')) {
          // navigation handled by <a> href
        }
      });
    }

    // Resume polling for running jobs on page load
    const audioContainer = document.getElementById('audio-enhancer-queue');
    if (audioContainer) {
      audioContainer.querySelectorAll('[data-status="RUNNING"]').forEach(card => {
        pollAudioProgress(parseInt(card.dataset.id));
      });
    }

    // Audio batch start
    document.addEventListener('click', function(e) {
      const btn = e.target.closest('.audio-batch-start-btn');
      if (!btn) return;
      const batchId = btn.dataset.batchId;
      const url = cfg.audioBatchStartUrlTemplate.replace('/0/', `/${batchId}/`);
      const engine   = document.getElementById('audioEngine')?.value || 'resemble';
      const mode     = document.getElementById('audioMode')?.value || 'both';
      const strength = document.getElementById('audioDenoisingStrength')?.value || '0.5';
      const quality  = document.getElementById('audioQuality')?.value || '64';
      btn.disabled = true;
      fetch(url, {
        method: 'POST',
        headers: csrfHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({ engine, mode, denoising_strength: parseFloat(strength), quality: parseInt(quality) }),
      }).then(r => r.json()).then(data => {
        data.started?.forEach(id => { updateRow(id, { status: 'RUNNING', progress: 0 }); pollAudioProgress(id); });
        btn.disabled = false;
      }).catch(() => { btn.disabled = false; });
    });

    // Audio batch delete
    document.addEventListener('click', function(e) {
      const btn = e.target.closest('.audio-batch-delete-btn');
      if (!btn) return;
      const batchId = btn.dataset.batchId;
      if (!confirm('Supprimer ce batch audio et toutes ses améliorations ?')) return;
      const url = cfg.audioBatchDeleteUrlTemplate.replace('/0/', `/${batchId}/`);
      fetch(url, { method: 'POST', headers: csrfHeaders() })
        .then(r => r.json())
        .then(() => {
          const el = btn.closest('.batch-group');
          if (el) el.remove(); else location.reload();
          updateAudioGlobalProgress();
        });
    });

    // Audio batch duplicate
    document.addEventListener('click', function(e) {
      const btn = e.target.closest('.audio-batch-duplicate-btn');
      if (!btn) return;
      const batchId = btn.dataset.batchId;
      const url = cfg.audioBatchDuplicateUrlTemplate.replace('/0/', `/${batchId}/`);
      fetch(url, { method: 'POST', headers: csrfHeaders() })
        .then(r => r.json())
        .then(() => setTimeout(() => location.reload(), 500));
    });
  }

  initAudioUpload();
  initAudioDragDrop();
  initButtons();
  initAudioBatchBar();
  updateAudioGlobalProgress();
});
