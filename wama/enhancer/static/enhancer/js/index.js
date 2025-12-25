document.addEventListener('DOMContentLoaded', function () {
  const config = window.ENHANCER_APP || {};
  const csrfToken = config.csrfToken;
  const fileInput = document.getElementById('enhancer-file');
  const queueTable = document.getElementById('enhancer-queue');
  const startProcessBtn = document.getElementById('enhancer-process-btn');
  const clearAllBtn = document.getElementById('enhancer-clear-btn');
  const downloadAllBtn = document.getElementById('enhancer-download-all-btn');

  const pollers = new Map();

  function getUrl(template, id) {
    return template.replace('/0/', `/${id}/`);
  }

  function csrfHeaders(extra = {}) {
    return Object.assign({}, extra, {
      'X-CSRFToken': csrfToken,
    });
  }

  async function uploadFile(file) {
    const body = new FormData();
    body.append('file', file);

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

      data.status = data.status || 'PENDING';
      appendRow(data);
    } catch (error) {
      alert(`Erreur pour ${file.name}: ${error.message}`);
    }
  }

  async function handleFiles(files) {
    for (const file of files) {
      await uploadFile(file);
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
    dropZone.addEventListener('drop', async (e) => {
      e.preventDefault();
      dropZone.classList.remove('drag-over');

      // Check if this is a FileManager drop
      if (window.FileManager && window.FileManager.getFileManagerData) {
        const fileData = window.FileManager.getFileManagerData(e);
        if (fileData && fileData.path) {
          // Handle FileManager import
          try {
            const result = await window.FileManager.importToApp(fileData.path, 'enhancer');
            if (result.imported) {
              // Reload the page to show the new file, or fetch it via API
              window.location.reload();
            }
          } catch (error) {
            console.error('FileManager import error:', error);
            if (window.FileManager.showToast) {
              window.FileManager.showToast('Erreur d\'import: ' + error.message, 'danger');
            }
          }
          return;
        }
      }

      // Regular file drop
      const files = e.dataTransfer.files;
      if (files.length > 0) {
        handleFiles(files);
      }
    });
  }

  function appendRow(data) {
    if (!queueTable) return;
    const tbody = queueTable.querySelector('tbody');
    if (!tbody) return;

    const existingEmpty = tbody.querySelector('.empty-row');
    if (existingEmpty) {
      existingEmpty.remove();
    }

    const row = document.createElement('tr');
    row.dataset.id = data.id;
    row.dataset.status = (data.status || 'PENDING').toUpperCase();

    const mediaIcon = data.media_type === 'image'
      ? '<i class="fas fa-image text-info"></i> Image'
      : '<i class="fas fa-video text-warning"></i> Vidéo';

    row.innerHTML = `
      <td class="fw-bold text-center">#${data.id}</td>
      <td class="text-center">${mediaIcon}</td>
      <td>
        <div class="fw-semibold">${escapeHtml(data.input_filename || 'Fichier')}</div>
        <div class="d-flex align-items-center gap-2 mt-1">
          <a href="${data.input_url}" target="_blank" class="text-info small">
            <i class="fas fa-link"></i> Voir le fichier
          </a>
        </div>
      </td>
      <td class="text-center small">${data.width}x${data.height}</td>
      <td class="text-center small"><span class="badge bg-info">En attente</span></td>
      <td class="status text-uppercase text-center">${data.status || 'PENDING'}</td>
      <td>
        <div class="progress" style="height: 24px;">
          <div class="progress-bar" role="progressbar" style="width: 0%;">0%</div>
        </div>
      </td>
      <td class="text-center">
        <div class="btn-group" role="group">
          <button class="btn btn-primary btn-sm js-restart-enhancement"
                  data-id="${data.id}"
                  title="Relancer le traitement">
            <i class="fas fa-play"></i>
          </button>
          <a class="btn btn-success btn-sm download-btn disabled" aria-disabled="true" tabindex="-1"
             href="${getUrl(config.downloadUrlTemplate, data.id)}">
            <i class="fas fa-download"></i>
          </a>
          <button class="btn btn-warning btn-sm settings-btn"
                  data-bs-toggle="modal" data-bs-target="#settingsModal${data.id}">
            <i class="fas fa-cog"></i>
          </button>
          <button class="btn btn-danger btn-sm js-delete-enhancement"
                  data-delete-url="${getUrl(config.deleteUrlTemplate, data.id)}">
            <i class="fas fa-trash-alt"></i>
          </button>
        </div>
      </td>
    `;

    tbody.prepend(row);
    createSettingsModal(data);
    bindRowActions(row);
    updateDownloadAllState();
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

  function startPolling(id) {
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
    const interval = pollers.get(id);
    if (interval) {
      clearInterval(interval);
      pollers.delete(id);
    }
  }

  function updateRow(id, data) {
    const row = queueTable ? queueTable.querySelector(`tr[data-id="${id}"]`) : null;
    if (!row) {
      stopPolling(id);
      return;
    }

    const bar = row.querySelector('.progress-bar');
    const statusCell = row.querySelector('.status');
    const downloadBtn = row.querySelector('.download-btn');

    const progress = Math.min(100, Math.max(0, data.progress || 0));
    const status = (data.status || 'PENDING').toUpperCase();

    if (bar) {
      bar.style.width = `${progress}%`;
      bar.textContent = `${progress}%`;

      // Animate progress bar
      if (status === 'RUNNING') {
        bar.classList.add('progress-bar-animated', 'progress-bar-striped');
      } else {
        bar.classList.remove('progress-bar-animated', 'progress-bar-striped');
      }
    }

    if (statusCell) {
      statusCell.textContent = status;
    }
    row.dataset.status = status;

    if (status === 'SUCCESS' && downloadBtn) {
      downloadBtn.classList.remove('disabled');
      downloadBtn.removeAttribute('aria-disabled');
      downloadBtn.removeAttribute('tabindex');
    }

    // Stop polling after terminal states, but ensure we show 100% for SUCCESS
    if (['SUCCESS', 'FAILURE'].includes(status)) {
      // If SUCCESS and progress not yet 100%, force it to 100%
      if (status === 'SUCCESS' && progress < 100 && bar) {
        bar.style.width = '100%';
        bar.textContent = '100%';
      }
      stopPolling(id);
    } else if (progress >= 100) {
      stopPolling(id);
    }

    updateDownloadAllState();
  }

  function handleRestartEnhancement(id) {
    if (!id) return;

    const row = queueTable ? queueTable.querySelector(`tr[data-id="${id}"]`) : null;
    if (!row) return;

    // Confirm restart if already completed
    const status = (row.dataset.status || '').toUpperCase();
    if (status === 'SUCCESS' || status === 'RUNNING') {
      if (!confirm('Relancer le traitement de ce fichier ?')) {
        return;
      }
    }

    // Get settings from the enhancement's settings form
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
      .then((data) => {
        // Update row status
        row.dataset.status = 'RUNNING';
        const statusCell = row.querySelector('.status');
        if (statusCell) {
          statusCell.textContent = 'RUNNING';
        }

        // Start polling
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
        const row = button.closest('tr');
        if (row) {
          const id = row.dataset.id;
          row.remove();
          stopPolling(id);
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
    queueTable.querySelectorAll('tbody tr[data-id]').forEach((row) => {
      const id = row.dataset.id;
      const status = (row.dataset.status || '').toUpperCase();
      bindRowActions(row);
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
        queueTable.querySelectorAll('tbody tr[data-id]').forEach((row) => row.remove());
        pollers.forEach((_, id) => stopPolling(id));
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
    const tbody = queueTable.querySelector('tbody');
    if (!tbody) return;

    const hasRows = tbody.querySelectorAll('tr[data-id]').length > 0;
    const existingEmpty = tbody.querySelector('.empty-row');

    if (!hasRows || force) {
      if (existingEmpty) return;
      const row = document.createElement('tr');
      row.className = 'empty-row';
      row.innerHTML = '<td colspan="8" class="text-center text-muted py-4">Aucun fichier en attente.</td>';
      tbody.appendChild(row);
    } else if (existingEmpty) {
      existingEmpty.remove();
    }
  }

  function updateDownloadAllState() {
    if (!downloadAllBtn || !queueTable) return;
    const hasSuccess = !!queueTable.querySelector('tbody tr[data-status="SUCCESS"]');
    if (hasSuccess) {
      downloadAllBtn.removeAttribute('disabled');
    } else {
      downloadAllBtn.setAttribute('disabled', 'true');
    }
  }

  function escapeHtml(str) {
    return (str || '').replace(/[&<>"']/g, function (match) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
      return map[match];
    });
  }

  function updateGlobalProgress() {
    if (!config.globalProgressUrl) return;

    fetch(config.globalProgressUrl)
      .then(response => response.json())
      .then(data => {
        const progressBar = document.getElementById('globalProgressBar');
        const statsText = document.getElementById('globalProgressStats');

        if (progressBar && statsText) {
          const progress = data.overall_progress || 0;
          progressBar.style.width = progress + '%';
          progressBar.textContent = progress + '%';

          statsText.textContent = `${data.success}/${data.total} terminé`;

          // Update progress bar color based on status
          progressBar.className = 'progress-bar';
          if (data.failure > 0) {
            progressBar.classList.add('bg-danger');
          } else if (data.running > 0) {
            progressBar.classList.add('progress-bar-animated', 'progress-bar-striped');
          } else if (data.success === data.total && data.total > 0) {
            progressBar.classList.add('bg-success');
          }
        }
      })
      .catch(error => console.error('Error updating global progress:', error));
  }

  // Initialize
  initUpload();
  initDragDrop();
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
});
