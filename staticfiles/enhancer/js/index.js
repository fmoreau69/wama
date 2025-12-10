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
          <a class="btn btn-success btn-sm download-btn disabled" aria-disabled="true" tabindex="-1"
             href="${getUrl(config.downloadUrlTemplate, data.id)}">
            <i class="fas fa-download"></i>
          </a>
          <button class="btn btn-warning btn-sm settings-btn" disabled>
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
    bindRowActions(row);
    updateDownloadAllState();
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

    if (['SUCCESS', 'FAILURE'].includes(status) || progress >= 100) {
      stopPolling(id);
    }

    if (status === 'SUCCESS' && downloadBtn) {
      downloadBtn.classList.remove('disabled');
      downloadBtn.removeAttribute('aria-disabled');
      downloadBtn.removeAttribute('tabindex');
    }

    updateDownloadAllState();
  }

  function bindRowActions(scope) {
    const deleteButtons = (scope || document).querySelectorAll('.js-delete-enhancement');
    deleteButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleDelete(btn));
    });

    const saveSettingsButtons = (scope || document).querySelectorAll('.save-settings-btn');
    saveSettingsButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleSaveSettings(btn));
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

  function handleSaveSettings(button) {
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

        alert('Paramètres sauvegardés !');
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
      body: JSON.stringify({}),
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

  // Initialize
  initUpload();
  initDragDrop();
  initExistingRows();
  initBulkActions();
  bindRowActions(document);
});
