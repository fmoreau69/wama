document.addEventListener('DOMContentLoaded', function () {
  const config = window.ENHANCER_APP || {};
  const csrfToken = config.csrfToken;
  const fileInput = document.getElementById('enhancer-file');
  const queueTable = document.getElementById('enhancer-queue');
  const startProcessBtn = document.getElementById('enhancer-process-btn');
  const clearAllBtn = document.getElementById('enhancer-clear-btn');
  const downloadAllBtn = document.getElementById('enhancer-download-all-btn');

  const pollers = new Map();

  // Délégué à WamaApp (brique commune wama-app-base.js) ; repli local si non chargé.
  function getUrl(template, id) {
    return window.WamaApp ? WamaApp.getUrl(template, id) : template.replace('/0/', `/${id}/`);
  }

  function csrfHeaders(extra = {}) {
    return Object.assign({}, extra, {
      'X-CSRFToken': csrfToken,
    });
  }

  async function uploadFile(file) {
    const body = new FormData();
    body.append('file', file);
    body.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
    body.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');

    try {
      const response = await fetch(config.uploadUrl, {
        method: 'POST',
        headers: csrfHeaders(),
        body,
      });

      const data = await response.json();

      if (data.error) {
        throw new Error(data.error);
      }

      console.log('[Enhancer] Upload response:', data);
      data.status = data.status || 'PENDING';
      appendRow(data);
      if (window.WamaFM) WamaFM.uploaded();  // fichier ajouté → refresh filemanager
      return data.id;
    } catch (error) {
      alert(`Erreur pour ${file.name}: ${error.message}`);
      return null;
    }
  }

  async function handleFiles(files) {
    const ids = [];
    for (const file of files) {
      if (window._batchImport && await window._batchImport.detectAndHandle(file)) continue;
      const id = await uploadFile(file);
      if (id) ids.push(id);
    }
    // Consolidation en UN batch si plusieurs fichiers médias importés ensemble.
    if (ids.length > 1 && config.consolidateUrl) {
      try {
        await fetch(config.consolidateUrl, {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, csrfHeaders()),
          body: JSON.stringify({ ids }),
        });
      } catch (e) { /* ignore : à défaut, items individuels */ }
      location.reload();
    }
  }

  function initUpload() {
    if (!fileInput) return;

    fileInput.addEventListener('change', function () {
      if (!this.files.length) return;
      handleFiles(this.files);
      fileInput.value = '';
    });
  }

  function initDragDrop() {
    const dropZone = document.getElementById('dropZoneEnhancer');
    const browseBtn = document.getElementById('enhancer-browse-btn');

    if (!dropZone || !fileInput) return;

    // Click on drop zone
    dropZone.addEventListener('click', (e) => {
      if (e.target !== browseBtn) {
        fileInput.click();
      }
    });

    // Browse button
    if (browseBtn) {
      browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
      });
    }

    // Drag over
    dropZone.addEventListener('dragover', (e) => {
      e.preventDefault();
      dropZone.classList.add('drag-over');
    });

    // Drag leave
    dropZone.addEventListener('dragleave', () => {
      dropZone.classList.remove('drag-over');
    });

    // Drop
    dropZone.addEventListener('drop', (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFiles(files);
      }
    });
  }

  function appendRow(data) {
    if (!queueTable) return;

    const empty = queueTable.querySelector('.empty-state');
    if (empty) empty.remove();

    const mediaIcon = data.media_type === 'image'
      ? '<i class="fas fa-image text-info"></i>'
      : '<i class="fas fa-video text-warning"></i>';

    const previewUrl = `/common/preview/enhancer/${data.id}/`;

    const card = document.createElement('div');
    card.className = 'synthesis-card';
    card.dataset.id = data.id;
    card.dataset.status = (data.status || 'PENDING').toUpperCase();

    card.innerHTML = `
      <div class="row align-items-center">
        <div class="col-md-3">
          <strong>
            <button type="button" class="btn btn-link p-0 text-start preview-media-link"
                    data-preview-url="${previewUrl}"
                    style="color: #fff; text-decoration: none; font-size: 0.9rem;">
              ${mediaIcon} ${escapeHtml(data.input_filename || 'Fichier')}
            </button>
          </strong>
          <br>
          <small class="text-white-50">${data.width}x${data.height}</small>
        </div>
        <div class="col-md-2">
          <small>
            <span class="badge bg-info">${escapeHtml(data.ai_model || '—')}</span>
          </small>
        </div>
        <div class="col-md-3">
          <span class="status-badge badge bg-secondary">PENDING</span>
          <div class="progress-bar-custom mt-2">
            <div class="progress-fill" style="width: 0%"></div>
          </div>
          <small class="progress-text text-light">0%</small>
        </div>
        <div class="col-md-4">
          <div class="btn-group-actions">
            <button class="btn btn-sm btn-secondary js-open-settings"
                    data-id="${data.id}"
                    data-ai-model="${escapeHtml(data.ai_model || '')}"
                    data-denoise="${data.denoise || 'false'}"
                    data-blend-factor="${data.blend_factor || 0}"
                    title="Paramètres">
              <i class="fas fa-cog"></i>
            </button>
            ${window.WamaCycleButton ? WamaCycleButton.html(data.status || 'PENDING', data.id) : `<button class="btn btn-sm btn-outline-success js-restart-enhancement action-btn" data-id="${data.id}" title="Lancer"><i class="fas fa-play"></i></button>`}
            <button class="btn btn-sm btn-danger js-delete-enhancement"
                    data-delete-url="${getUrl(config.deleteUrlTemplate, data.id)}"
                    title="Supprimer">
              <i class="fas fa-trash-alt"></i>
            </button>
          </div>
        </div>
      </div>
    `;

    queueTable.prepend(card);
    createSettingsModal(data);
    bindRowActions(card);
    updateDownloadAllState();

    if (typeof initMediaPreview === 'function') {
      initMediaPreview();
    }
  }

  function createSettingsModal(data) {
    // Remove existing modal if any
    const existingModal = document.getElementById(`settingsModal${data.id}`);
    if (existingModal) {
      existingModal.remove();
    }

    // Get AI models from the default dropdown
    const defaultModelSelect = document.getElementById('defaultAiModel');
    let modelOptions = '';
    if (defaultModelSelect) {
      Array.from(defaultModelSelect.options).forEach(option => {
        const selected = option.value === data.ai_model ? 'selected' : '';
        modelOptions += `<option value="${option.value}" ${selected}>${escapeHtml(option.text)}</option>`;
      });
    }

    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.id = `settingsModal${data.id}`;
    modal.setAttribute('tabindex', '-1');
    modal.innerHTML = `
      <div class="modal-dialog">
        <div class="modal-content bg-dark text-white">
          <div class="modal-header border-secondary">
            <h5 class="modal-title">Paramètres - #${data.id}</h5>
            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
          </div>
          <div class="modal-body">
            <form class="enhancement-settings-form" data-id="${data.id}">
              <div class="mb-3">
                <label class="form-label">Modèle AI</label>
                <select class="form-select bg-dark text-white border-secondary" name="ai_model">
                  ${modelOptions}
                </select>
              </div>
              <div class="mb-3 form-check form-switch">
                <input class="form-check-input" type="checkbox" name="denoise" ${data.denoise ? 'checked' : ''}>
                <label class="form-check-label">Débruitage</label>
              </div>
              <div class="mb-3">
                <label class="form-label">Blend Factor: <span class="blend-display">${data.blend_factor || 0}</span></label>
                <input type="range" class="form-range" name="blend_factor"
                       min="0" max="1" step="0.1" value="${data.blend_factor || 0}"
                       oninput="this.previousElementSibling.querySelector('.blend-display').textContent = this.value">
              </div>
            </form>
          </div>
          <div class="modal-footer border-secondary">
            <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">Annuler</button>
            <button type="button" class="btn btn-primary save-settings-btn" data-id="${data.id}">
              Sauvegarder
            </button>
            <button type="button" class="btn btn-success save-and-restart-btn" data-id="${data.id}">
              <i class="fas fa-play"></i> Sauvegarder et relancer
            </button>
          </div>
        </div>
      </div>
    `;

    document.body.appendChild(modal);

    // Bind actions for this modal's buttons
    bindRowActions(modal);
  }

  // Polling délégué à WamaApp.Poller (brique commune, résilient : retries maxFails).
  // Création paresseuse (config.progressUrlTemplate prêt) ; repli local si WamaApp absent.
  let _poller = null;
  function _getPoller() {
    if (!window.WamaApp) return null;
    if (!_poller) {
      _poller = new WamaApp.Poller({
        urlTemplate: config.progressUrlTemplate,
        onData: function (id, data) { updateRow(id, data); },
        interval: 1500,
      });
    }
    return _poller;
  }

  function startPolling(id) {
    const p = _getPoller();
    if (p) { p.start(id); return; }
    if (pollers.has(id)) return;
    const interval = setInterval(() => {
      fetch(getUrl(config.progressUrlTemplate, id))
        .then((response) => response.json())
        .then((data) => updateRow(id, data))
        .catch(() => stopPolling(id));
    }, 1500);
    pollers.set(id, interval);
  }

  function stopPolling(id) {
    const p = _getPoller();
    if (p) { p.stop(id); return; }
    const interval = pollers.get(id);
    if (interval) {
      clearInterval(interval);
      pollers.delete(id);
    }
  }

  function updateRow(id, data) {
    const card = queueTable ? queueTable.querySelector(`[data-id="${id}"]`) : null;
    if (!card) {
      stopPolling(id);
      return;
    }

    const progress = Math.min(100, Math.max(0, data.progress || 0));
    const status = (data.status || 'PENDING').toUpperCase();

    // Progress fill
    const fill = card.querySelector('.progress-fill');
    if (fill) fill.style.width = `${progress}%`;
    const progressText = card.querySelector('.progress-text');
    if (progressText) progressText.textContent = `${progress}%`;

    if (window.WamaEta) WamaEta.render(card.querySelector('.wama-eta'), WamaEta.update(id, { progress: progress, status: status, seedSeconds: data.estimated_seconds, modelLoaded: false }));

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
    card.dataset.status = status;

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
        actionBtn.className = 'btn btn-sm btn-warning js-restart-enhancement action-btn';
        actionBtn.innerHTML = '<i class="fas fa-redo"></i>';
        actionBtn.title = 'Relancer';
      } else {
        actionBtn.disabled = false;
        actionBtn.className = 'btn btn-sm btn-primary js-restart-enhancement action-btn';
        actionBtn.innerHTML = '<i class="fas fa-play"></i>';
        actionBtn.title = 'Lancer';
      }
    }

    // Show download button on SUCCESS
    if (status === 'SUCCESS') {
      if (!card.querySelector('.download-btn')) {
        const actionsDiv = card.querySelector('.btn-group-actions');
        const deleteBtn = card.querySelector('.js-delete-enhancement');
        if (actionsDiv && deleteBtn) {
          const dlBtn = document.createElement('a');
          dlBtn.className = 'btn btn-sm btn-success download-btn';
          dlBtn.href = getUrl(config.downloadUrlTemplate, id);
          dlBtn.title = 'Télécharger';
          dlBtn.innerHTML = '<i class="fas fa-download"></i>';
          actionsDiv.insertBefore(dlBtn, deleteBtn);
        }
      }
      if (progress < 100 && fill) fill.style.width = '100%';
      stopPolling(id);
      if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
    } else if (status === 'FAILURE') {
      stopPolling(id);
    } else if (progress >= 100) {
      stopPolling(id);
    }

    updateDownloadAllState();
  }

  // ⏹ Stop : arrête l'amélioration image/vidéo → item relançable (↻ via autoSync sur data-status).
  function handleStopEnhancement(id) {
    if (!id) return;
    fetch(`/enhancer/stop/${id}/`, { method: 'POST', headers: csrfHeaders() })
      .then(r => r.json())
      .then(data => {
        const card = queueTable ? queueTable.querySelector(`[data-id="${id}"]`) : null;
        if (card && data.status) card.dataset.status = data.status;
        stopPolling(id);
      })
      .catch(() => {});
  }

  // Bouton de cycle commun ▶/⏹/↻ (image/vidéo) : wire délégué + auto-sync sur data-status.
  if (window.WamaCycleButton && queueTable) {
    WamaCycleButton.wire(queueTable, { start: (id) => handleRestartEnhancement(id), stop: (id) => handleStopEnhancement(id) });
    WamaCycleButton.autoSync({ container: queueTable, cardSelector: '.synthesis-card' });
  }

  function handleRestartEnhancement(id) {
    if (!id) return;

    const card = queueTable ? queueTable.querySelector(`[data-id="${id}"]`) : null;
    if (!card) return;

    const status = (card.dataset.status || '').toUpperCase();
    if (status === 'SUCCESS' || status === 'RUNNING') {
      if (!confirm('Relancer le traitement de ce fichier ?')) {
        return;
      }
    }

    const form = document.querySelector(`.enhancement-settings-form[data-id="${id}"]`);
    let settings = {};
    if (form) {
      settings = {
        ai_model: form.querySelector('[name="ai_model"]')?.value,
        denoise: form.querySelector('[name="denoise"]')?.checked,
        blend_factor: form.querySelector('[name="blend_factor"]')?.value
      };
    }

    fetch(getUrl(config.startUrlTemplate, id), {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(settings),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw new Error(err.message || 'Erreur serveur');
          });
        }
        return response.json();
      })
      .then(() => {
        updateRow(id, { status: 'RUNNING', progress: 0 });
        startPolling(id);
      })
      .catch((error) => {
        console.error('Erreur restart:', error);
        alert(error.message || 'Erreur lors du démarrage du traitement.');
      });
  }

  function bindRowActions(scope) {
    const deleteButtons = (scope || document).querySelectorAll('.js-delete-enhancement');
    deleteButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleDelete(btn));
    });

    const restartButtons = (scope || document).querySelectorAll('.js-restart-enhancement');
    restartButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleRestartEnhancement(btn.dataset.id));
    });

    const openSettingsButtons = (scope || document).querySelectorAll('.js-open-settings');
    openSettingsButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => {
        const data = {
          id: btn.dataset.id,
          ai_model: btn.dataset.aiModel,
          denoise: btn.dataset.denoise === 'true',
          blend_factor: parseFloat(btn.dataset.blendFactor) || 0
        };
        createSettingsModal(data);
        const modal = new bootstrap.Modal(document.getElementById(`settingsModal${data.id}`));
        modal.show();
        // Re-bind settings buttons after modal creation
        bindRowActions(document.getElementById(`settingsModal${data.id}`));
      });
    });

    const saveSettingsButtons = (scope || document).querySelectorAll('.save-settings-btn');
    saveSettingsButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleSaveSettings(btn, false));
    });

    const saveAndRestartButtons = (scope || document).querySelectorAll('.save-and-restart-btn');
    saveAndRestartButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleSaveSettings(btn, true));
    });
  }

  function handleDelete(button) {
    const url = button.dataset.deleteUrl;
    if (!url || !confirm('Supprimer ce fichier ?')) {
      return;
    }

    button.disabled = true;
    fetch(url, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then((response) => response.json())
      .then((data) => {
        if (!data.deleted) {
          throw new Error('Suppression impossible');
        }
        // Élément issu d'un batch : total/affichage du batch changent → recharger
        if (data.batch_changed) { if (window.WamaFM) WamaFM.deleted(); location.reload(); return; }
        const card = button.closest('.synthesis-card');
        if (card) {
          const id = card.dataset.id;
          card.remove();
          stopPolling(id);
          if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
          insertEmptyRowIfNeeded();
          updateDownloadAllState();
        }
      })
      .catch((error) => {
        alert(error.message || 'Erreur lors de la suppression');
      })
      .finally(() => {
        button.disabled = false;
      });
  }

  function handleSaveSettings(button, restart = false) {
    const enhancementId = button.dataset.id;
    const form = document.querySelector(`.enhancement-settings-form[data-id="${enhancementId}"]`);

    if (!form) return;

    const formData = new FormData(form);

    // Mode batch : applique les réglages du form à tous les items du batch.
    if (window._enhancerBatchId) {
      const bid = window._enhancerBatchId;
      window._enhancerBatchId = null;
      fetch(getUrl(config.batchUpdateUrlTemplate, bid), {
        method: 'POST', headers: csrfHeaders(), body: formData,
      })
        .then((r) => r.json())
        .then(() => {
          const m = bootstrap.Modal.getInstance(document.getElementById(`settingsModal${enhancementId}`));
          if (m) m.hide();
          location.reload();
        })
        .catch(() => {});
      return;
    }

    fetch(getUrl(config.updateSettingsUrlTemplate, enhancementId), {
      method: 'POST',
      headers: csrfHeaders(),
      body: formData,
    })
      .then((response) => response.json())
      .then((data) => {
        // Close modal
        const modal = bootstrap.Modal.getInstance(document.getElementById(`settingsModal${enhancementId}`));
        if (modal) modal.hide();

        if (restart) {
          // Restart enhancement with new settings
          handleRestartEnhancement(enhancementId);
        } else {
          alert('Paramètres sauvegardés !');
        }
      })
      .catch((error) => {
        alert('Erreur lors de la sauvegarde: ' + error.message);
      });
  }

  function initExistingRows() {
    if (!queueTable) return;
    queueTable.querySelectorAll('[data-id]').forEach((card) => {
      const id = card.dataset.id;
      const status = (card.dataset.status || '').toUpperCase();
      bindRowActions(card);
      if (['PENDING', 'RUNNING', 'STARTED'].includes(status)) {
        startPolling(id);
      }
    });
    updateDownloadAllState();
  }

  function initBulkActions() {
    if (startProcessBtn) {
      startProcessBtn.addEventListener('click', handleStartAll);
    }
    if (clearAllBtn) {
      clearAllBtn.addEventListener('click', handleClearAll);
    }
    if (downloadAllBtn) {
      downloadAllBtn.addEventListener('click', () => {
        window.location.href = config.downloadAllUrl;
      });
    }
  }

  function handleStartAll() {
    if (!config.startAllUrl || !queueTable) return;

    // Get default settings
    const defaultAiModel = document.getElementById('defaultAiModel')?.value;
    const defaultDenoise = document.getElementById('defaultDenoise')?.checked;
    const defaultBlendFactor = document.getElementById('defaultBlendFactor')?.value;

    startProcessBtn.disabled = true;

    fetch(config.startAllUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({
        ai_model: defaultAiModel,
        denoise: defaultDenoise,
        blend_factor: defaultBlendFactor
      }),
    })
      .then((response) => {
        if (!response.ok) {
          return response.json().then((err) => {
            throw new Error(err.message || 'Erreur serveur');
          });
        }
        return response.json();
      })
      .then((data) => {
        const started = data.started_ids || [];
        const errors = data.errors || [];

        if (errors.length > 0) {
          console.error('Erreurs lors du démarrage:', errors);
          alert(`Certains fichiers n'ont pas pu démarrer. Vérifiez que Celery est lancé.\n${errors[0].error}`);
        }

        if (!started.length) {
          if (!errors.length) {
            alert('Aucun fichier à traiter.');
          }
          return;
        }
        started.forEach((id) => {
          startPolling(id);
        });
      })
      .catch((error) => {
        console.error('Erreur start_all:', error);
        alert(error.message || 'Erreur lors du démarrage des traitements.');
      })
      .finally(() => {
        startProcessBtn.disabled = false;
      });
  }

  function handleClearAll() {
    if (!config.clearUrl || !queueTable) return;
    if (!confirm('Supprimer tous les fichiers ?')) {
      return;
    }

    clearAllBtn.disabled = true;

    fetch(config.clearUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({}),
    })
      .then((response) => response.json())
      .then(() => {
        queueTable.querySelectorAll('[data-id]').forEach((card) => card.remove());
        pollers.forEach((_, id) => stopPolling(id));
        if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
        insertEmptyRowIfNeeded(true);
        updateDownloadAllState();
      })
      .catch((error) => {
        alert(error.message || 'Erreur lors de la suppression.');
      })
      .finally(() => {
        clearAllBtn.disabled = false;
      });
  }

  function insertEmptyRowIfNeeded(force = false) {
    if (!queueTable) return;

    const hasItems = queueTable.querySelectorAll('[data-id]').length > 0;
    const existingEmpty = queueTable.querySelector('.empty-state');

    if (!hasItems || force) {
      if (existingEmpty) return;
      const el = document.createElement('div');
      el.className = 'empty-state text-center py-4 text-white-50';
      el.textContent = 'Aucun fichier en attente.';
      queueTable.appendChild(el);
    } else if (existingEmpty) {
      existingEmpty.remove();
    }
  }

  function updateDownloadAllState() {
    if (!downloadAllBtn || !queueTable) return;
    const hasSuccess = !!queueTable.querySelector('[data-status="SUCCESS"]');
    if (hasSuccess) {
      downloadAllBtn.removeAttribute('disabled');
    } else {
      downloadAllBtn.setAttribute('disabled', 'true');
    }
  }

  function escapeHtml(str) {
    if (window.WamaApp) return WamaApp.escapeHtml(str);
    return (str || '').replace(/[&<>"']/g, function (match) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
      return map[match];
    });
  }

  function updateGlobalProgress() {
    return; // Neutralisé : barre globale + ETA pilotées par la brique commune wama-global-progress.js.
    if (!config.globalProgressUrl) return;

    fetch(config.globalProgressUrl)
      .then(response => response.json())
      .then(data => {
        const progressBar = document.getElementById('globalProgressBar');
        const statsText = document.getElementById('globalProgressStats');
        const pct = document.getElementById('globalProgressPct');
        const globalStatus = document.getElementById('globalStatus');
        const progress = data.overall_progress || 0;
        if (progressBar) progressBar.style.width = progress + '%';
        if (statsText) statsText.textContent = `${data.success}/${data.total} terminé · ${data.running} en cours`;
        if (window.WamaEta) WamaEta.render(document.getElementById('globalEta'), WamaEta.aggregateAll());
        if (pct) pct.textContent = progress ? progress + '%' : '';
        if (globalStatus) {
          const active = (data.total || 0) > 0;
          globalStatus.style.opacity = active ? '1' : '0';
          globalStatus.style.pointerEvents = active ? '' : 'none';
        }
      })
      .catch(error => console.error('Error updating global progress:', error));
  }

  // === URL Upload Form ===
  function initUrlUpload() {
    const mediaUrlForm = document.getElementById('media-url-form');
    if (!mediaUrlForm) return;

    mediaUrlForm.addEventListener('submit', async function(e) {
      e.preventDefault();

      const mediaUrlInput = this.querySelector('input[name="media_url"]');
      const mediaUrl = mediaUrlInput ? mediaUrlInput.value.trim() : '';

      if (!mediaUrl) {
        alert('Veuillez entrer une URL de média.');
        return;
      }

      // Show loading state
      const submitBtn = this.querySelector('button[type="submit"]');
      const originalBtnHtml = submitBtn ? submitBtn.innerHTML : '';
      if (submitBtn) {
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Téléchargement...';
      }

      try {
        const formData = new FormData();
        formData.append('media_url', mediaUrl);
        formData.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
        formData.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');

        const response = await fetch(config.uploadUrl, {
          method: 'POST',
          headers: csrfHeaders(),
          body: formData
        });

        const data = await response.json();

        if (data.error) {
          throw new Error(data.error);
        }

        // Add item to queue
        data.status = data.status || 'PENDING';
        appendRow(data);

        // Clear the form
        mediaUrlInput.value = '';

        // Show success message
        if (window.FileManager && window.FileManager.showToast) {
          window.FileManager.showToast('Média téléchargé avec succès!', 'success');
        }

      } catch (error) {
        console.error('URL upload error:', error);
        alert('Erreur lors du téléchargement: ' + error.message);
      } finally {
        // Restore button
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = originalBtnHtml;
        }
      }
    });
  }

  // Reset button
  const resetBtn = document.getElementById('resetOptions');
  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      // Detect active tab
      const audioSettings = document.getElementById('audioSettings');
      const audioActive = audioSettings && audioSettings.style.display !== 'none';

      if (audioActive) {
        // Reset audio settings
        const audioEngineEl = document.getElementById('audioEngine');
        if (audioEngineEl) audioEngineEl.value = 'resemble';

        const audioModeEl = document.getElementById('audioMode');
        if (audioModeEl) audioModeEl.value = 'both';

        const audioStrengthEl = document.getElementById('audioDenoisingStrength');
        if (audioStrengthEl) {
          audioStrengthEl.value = '0.5';
          const display = document.getElementById('audioStrengthValue');
          if (display) display.textContent = '0.5';
        }

        const audioQualityEl = document.getElementById('audioQuality');
        if (audioQualityEl) audioQualityEl.value = '64';
      } else {
        // Reset image/video settings
        const defaultAiModelEl = document.getElementById('defaultAiModel');
        if (defaultAiModelEl && defaultAiModelEl.options.length > 0) {
          defaultAiModelEl.selectedIndex = 0;
        }

        const defaultDenoiseEl = document.getElementById('defaultDenoise');
        if (defaultDenoiseEl) defaultDenoiseEl.checked = false;

        const defaultBlendEl = document.getElementById('defaultBlendFactor');
        if (defaultBlendEl) {
          defaultBlendEl.value = '0';
          const display = document.getElementById('blendValue');
          if (display) display.textContent = '0';
        }
      }
    });
  }

  // Initialize
  initUpload();
  initDragDrop();
  initUrlUpload();
  initExistingRows();
  initBulkActions();
  bindRowActions(document);

  // Bind actions to existing modals (loaded from Django template)
  setTimeout(() => {
    bindRowActions(document);
  }, 100);

  // Update global progress every 2 seconds
  updateGlobalProgress();
  setInterval(updateGlobalProgress, 2000);

  // ── Batch detect bar — delegated to WamaBatchImport (common/js/batch-import.js)
  // Initialisation dans le template via window._batchImport = WamaBatchImport({...})

  // ── Batch start ────────────────────────────────────────────────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-start-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    const url = config.batchStartUrlTemplate.replace('/0/', `/${batchId}/`);
    btn.disabled = true;
    fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
      .then(r => r.json())
      .then(d => {
        if (d.started && d.started.length > 0) {
          d.started.forEach(id => startPolling(id));
        }
        btn.disabled = false;
      })
      .catch(() => { btn.disabled = false; });
  });

  // ── Batch delete ───────────────────────────────────────────────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-delete-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    if (!confirm('Supprimer ce batch et toutes ses améliorations ?')) return;
    const url = config.batchDeleteUrlTemplate.replace('/0/', `/${batchId}/`);
    fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
      .then(r => r.json())
      .then(() => {
        const el = btn.closest('.batch-group');
        if (el) el.remove();
        else location.reload();
      })
      .catch(() => alert('Erreur lors de la suppression'));
  });

  // ── Duplication d'un item (autonome ou dans un batch) — la vue place la copie
  //    DANS le même batch. Aucun handler n'existait avant. ──────────────────
  document.addEventListener('click', function(e) {
    const dbtn = e.target.closest('.duplicate-btn');
    if (!dbtn || !dbtn.dataset.duplicateUrl) return;
    if (dbtn.dataset.busy) return;            // garde anti double-soumission (double-clic / double-fire)
    dbtn.dataset.busy = '1';
    dbtn.disabled = true;
    fetch(dbtn.dataset.duplicateUrl, { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
      .then(r => r.json())
      .then(() => location.reload())
      .catch(() => { delete dbtn.dataset.busy; dbtn.disabled = false; });
  });

  // ── ⚙ Batch settings : réutilise la modale du 1er item en mode batch ────
  document.addEventListener('click', function(e) {
    const bs = e.target.closest('.batch-settings-btn');
    if (!bs) return;
    const group = bs.closest('.batch-group');
    const firstOpen = group ? group.querySelector('.js-open-settings') : null;
    if (!firstOpen) return;
    window._enhancerBatchId = bs.dataset.batchId;   // bascule la sauvegarde vers batch_update
    firstOpen.click();                               // construit + affiche la modale du 1er item
  });

  // ── Batch duplicate ────────────────────────────────────────────────────
  document.addEventListener('click', function(e) {
    const btn = e.target.closest('.batch-duplicate-btn');
    if (!btn) return;
    const batchId = btn.dataset.batchId;
    const url = config.batchDuplicateUrlTemplate.replace('/0/', `/${batchId}/`);
    fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
      .then(r => r.json())
      .then(d => {
        if (d.success) {
          setTimeout(() => location.reload(), 400);
        }
      })
      .catch(() => alert('Erreur lors de la duplication'));
  });
});

// Filemanager 'Envoyer vers...' — reload page to show imported item
document.addEventListener('wama:fileimported', function(e) {
    if (e.detail && e.detail.app === 'enhancer') { window.location.reload(); }
});
