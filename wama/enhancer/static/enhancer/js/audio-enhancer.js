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
    for (const f of files) {
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
    dropZone.addEventListener('drop', async e => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');

      // FileManager drag-and-drop (vakata dnd dispatches a synthetic drop)
      if (window.FileManager && window.FileManager.getFileManagerData) {
        const fileData = window.FileManager.getFileManagerData(e);
        if (fileData && fileData.path) {
          try {
            const result = await window.FileManager.importToApp(fileData.path, 'enhancer_audio');
            if (result.imported) {
              appendAudioRow(result);
            } else {
              alert('Import FileManager échoué: ' + (result.error || 'Erreur inconnue'));
            }
          } catch (err) {
            alert('Erreur import FileManager: ' + err.message);
          }
          return;
        }
      }

      // Regular file drop from OS
      const files = Array.from(e.dataTransfer.files).filter(f =>
        /\.(mp3|wav|flac|ogg|m4a|aac|opus|wma)$/i.test(f.name)
      );
      if (files.length === 0) {
        alert('Formats acceptés : MP3, WAV, FLAC, OGG, M4A, AAC, OPUS, WMA');
        return;
      }
      handleAudioFiles(files);
    });
  }

  // ── Queue row management ──────────────────────────────────────────────────

  function appendAudioRow(data) {
    const tbody = document.querySelector('#audio-enhancer-queue tbody');
    if (!tbody) return;

    // Remove empty-row if present
    const empty = tbody.querySelector('.empty-row');
    if (empty) empty.remove();

    const durationStr = data.duration
      ? (data.duration >= 60
          ? Math.floor(data.duration / 60) + 'min ' + Math.round(data.duration % 60) + 's'
          : data.duration.toFixed(1) + 's')
      : '—';

    const row = document.createElement('tr');
    row.dataset.id = data.id;
    row.dataset.status = data.status || 'PENDING';
    row.innerHTML = `
      <td class="fw-bold text-center">#${data.id}</td>
      <td>
        <div class="fw-semibold">${escHtml(data.input_filename || '')}</div>
        <small class="text-white-50">${durationStr}</small>
      </td>
      <td class="text-center small"><span class="badge bg-info audio-engine-badge">—</span></td>
      <td class="text-center small"><span class="badge bg-secondary audio-mode-badge">—</span></td>
      <td class="status text-uppercase text-center">${data.status || 'PENDING'}</td>
      <td>
        <div class="progress" style="height:22px;">
          <div class="progress-bar" role="progressbar" style="width:0%">0%</div>
        </div>
      </td>
      <td class="text-center">
        <div class="btn-group" role="group">
          <button class="btn btn-primary btn-sm js-audio-start" data-id="${data.id}" title="Lancer">
            <i class="fas fa-play"></i>
          </button>
          <a class="btn btn-success btn-sm js-audio-download disabled" href="#" data-id="${data.id}" title="Télécharger">
            <i class="fas fa-download"></i>
          </a>
          <button class="btn btn-warning btn-sm js-audio-settings"
                  data-id="${data.id}"
                  data-engine="resemble" data-mode="both"
                  data-strength="0.5" data-quality="64"
                  title="Paramètres">
            <i class="fas fa-cog"></i>
          </button>
          <button class="btn btn-danger btn-sm js-audio-delete" data-id="${data.id}" title="Supprimer">
            <i class="fas fa-trash-alt"></i>
          </button>
        </div>
      </td>
    `;
    tbody.appendChild(row);
    updateAudioGlobalProgress();
  }

  function escHtml(str) {
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  function updateRow(id, data) {
    const row = document.querySelector(`#audio-enhancer-queue tr[data-id="${id}"]`);
    if (!row) return;

    if (data.status) {
      row.dataset.status = data.status;
      const statusCell = row.querySelector('.status');
      if (statusCell) statusCell.textContent = data.status;
    }

    if (data.progress !== undefined) {
      const bar = row.querySelector('.progress-bar');
      if (bar) {
        bar.style.width = data.progress + '%';
        bar.textContent = data.progress + '%';
      }
    }

    if (data.status === 'SUCCESS') {
      const dlBtn = row.querySelector('.js-audio-download');
      if (dlBtn) {
        dlBtn.href = getUrl(cfg.audioDownloadUrlTemplate, id);
        dlBtn.classList.remove('disabled');
      }
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

      // Update badge labels and gear button data on the row
      const row = document.querySelector(`#audio-enhancer-queue tr[data-id="${id}"]`);
      if (row) {
        const engBadge = row.querySelector('.audio-engine-badge');
        const modeBadge = row.querySelector('.audio-mode-badge');
        if (engBadge) engBadge.textContent = engine === 'resemble' ? 'Resemble' : 'DeepFilter';
        if (modeBadge) modeBadge.textContent = mode;
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
      const row = document.querySelector(`#audio-enhancer-queue tr[data-id="${id}"]`);
      if (row) row.remove();
      if (pollers.has(id)) {
        clearInterval(pollers.get(id));
        pollers.delete(id);
      }
      const tbody = document.querySelector('#audio-enhancer-queue tbody');
      if (tbody && !tbody.querySelector('tr:not(.empty-row)')) {
        tbody.innerHTML = '<tr class="empty-row"><td colspan="7" class="text-center py-4">Aucun fichier audio en attente.</td></tr>';
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

      if (bar) {
        bar.style.width = data.overall_progress + '%';
        bar.textContent = data.overall_progress + '%';
      }
      if (stats) {
        stats.textContent = `${data.success}/${data.total} terminé`;
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
          const tbody = document.querySelector('#audio-enhancer-queue tbody');
          if (tbody) {
            tbody.innerHTML = '<tr class="empty-row"><td colspan="7" class="text-center py-4">Aucun fichier audio en attente.</td></tr>';
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
    document.querySelectorAll('#audio-enhancer-queue tr[data-status="RUNNING"]').forEach(row => {
      pollAudioProgress(parseInt(row.dataset.id));
    });
  }

  initAudioUpload();
  initAudioDragDrop();
  initButtons();
  updateAudioGlobalProgress();
});
