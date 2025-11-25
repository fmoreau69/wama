document.addEventListener('DOMContentLoaded', function () {
  const config = window.TRANSCRIBER_APP || {};
  const csrfToken = config.csrfToken;
  const uploadBtn = document.getElementById('transcriber-upload-btn');
  const fileInput = document.getElementById('transcriber-file');
  const queueTable = document.getElementById('transcriber-queue');
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
    return Object.assign({}, extra, {
      'X-CSRFToken': csrfToken,
    });
  }

  function initUpload() {
    if (!uploadBtn || !fileInput) return;

    uploadBtn.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', function () {
      if (!this.files.length) return;
      const file = this.files[0];
      const body = new FormData();
      body.append('file', file);
      body.append('preprocess_audio', preprocessEnabled ? '1' : '0');
      uploadBtn.disabled = true;

      fetch(config.uploadUrl, {
        method: 'POST',
        headers: csrfHeaders(),
        body,
      })
        .then((response) => response.json())
        .then((data) => {
          if (data.error) {
            throw new Error(data.error);
          }
          data.status = data.status || 'PENDING';
          appendRow(data);
        })
        .catch((error) => {
          alert(error.message || 'Upload failed');
        })
        .finally(() => {
          uploadBtn.disabled = false;
          fileInput.value = '';
        });
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
    row.dataset.preprocess = data.preprocess_audio ? 'true' : 'false';
    row.innerHTML = `
      <td class="fw-bold text-center">#${data.id}</td>
      <td>
        <div class="fw-semibold">${escapeHtml(data.audio_label || data.audio_name || 'Audio')}</div>
        <div class="d-flex align-items-center gap-2 mt-1">
          <a href="${data.audio_url}" target="_blank" class="text-info small"><i class="fas fa-link"></i> Voir le fichier</a>
          <span class="badge bg-warning text-dark preprocess-badge${data.preprocess_audio ? '' : ' d-none'}">Prétraité</span>
        </div>
      </td>
      <td class="text-center small">${escapeHtml(data.properties || '-')}</td>
      <td class="text-center fw-semibold">${escapeHtml(data.duration_display || '--:--')}</td>
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
          <button class="btn btn-danger btn-sm js-delete-transcript"
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
    }, 1200);
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
    const deleteButtons = (scope || document).querySelectorAll('.js-delete-transcript');
    deleteButtons.forEach((btn) => {
      if (btn.dataset.bound === '1') return;
      btn.dataset.bound = '1';
      btn.addEventListener('click', () => handleDelete(btn));
    });
  }

  function handleDelete(button) {
    const url = button.dataset.deleteUrl;
    if (!url || !confirm('Supprimer cette transcription ?')) {
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

  function initExistingRows() {
    if (!queueTable) return;
    queueTable.querySelectorAll('tbody tr[data-id]').forEach((row) => {
      const id = row.dataset.id;
      const status = (row.dataset.status || '').toUpperCase();
      applyPreprocessBadge(row, row.dataset.preprocess === 'true');
      bindRowActions(row);
      if (['PENDING', 'RUNNING', 'STARTED'].includes(status)) {
        startPolling(id);
      }
    });
    updateDownloadAllState();
  }

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
      listening = true;
      finalTranscript = '';
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
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const transcript = event.results[i][0].transcript;
        if (event.results[i].isFinal) {
          finalTranscript += transcript + '\n';
        } else {
          interimTranscript += transcript;
        }
      }
      liveOutput.textContent = (finalTranscript + interimTranscript).trim() || '...';
    };

    speakButton.addEventListener('click', () => {
      if (listening) {
        recognition.stop();
      } else {
        try {
          recognition.start();
        } catch (error) {
          console.error(error);
        }
      }
    });
  }

  function initBulkActions() {
    if (startProcessBtn) {
      startProcessBtn.addEventListener('click', handleStartAll);
    }
    if (clearAllBtn) {
      clearAllBtn.addEventListener('click', handleClearAll);
    }
    if (preprocessToggle) {
      preprocessToggle.checked = preprocessEnabled;
      preprocessToggle.addEventListener('change', () => {
        preprocessEnabled = preprocessToggle.checked;
        persistPreprocessingPreference(preprocessEnabled);
      });
    }
  }

  function handleStartAll() {
    if (!config.startAllUrl || !queueTable) return;
    startProcessBtn.disabled = true;
    fetch(config.startAllUrl, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ preprocessing: preprocessEnabled }),
    })
      .then((response) => response.json())
      .then((data) => {
        const started = data.started_ids || [];
        if (!started.length) {
          alert('Aucune transcription à démarrer.');
          return;
        }
        started.forEach((id) => {
          const row = queueTable.querySelector(`tr[data-id="${id}"]`);
          if (row) {
            row.dataset.preprocess = preprocessEnabled ? 'true' : 'false';
            applyPreprocessBadge(row, preprocessEnabled);
          }
          startPolling(id);
        });
      })
      .catch((error) => {
        alert(error.message || 'Erreur lors du démarrage des transcriptions.');
      })
      .finally(() => {
        startProcessBtn.disabled = false;
      });
  }

  function handleClearAll() {
    if (!config.clearUrl || !queueTable) return;
    if (!confirm('Supprimer toutes les transcriptions ?')) {
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
      row.innerHTML =
        '<td colspan="7" class="text-center text-muted py-4">Aucune transcription en attente.</td>';
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

  function persistPreprocessingPreference(enabled) {
    const endpoint = config.preprocessingUrl || toggleDatasetUrl;
    if (!endpoint) return;
    fetch(endpoint, {
      method: 'POST',
      headers: csrfHeaders({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ enabled }),
    }).catch(() => {
      if (preprocessToggle) {
        preprocessToggle.checked = !enabled;
      }
    });
  }

  function applyPreprocessBadge(row, enabled) {
    if (!row) return;
    const badge = row.querySelector('.preprocess-badge');
    if (!badge) return;
    if (enabled) {
      badge.classList.remove('d-none');
    } else {
      badge.classList.add('d-none');
    }
  }

  function escapeHtml(str) {
    return (str || '').replace(/[&<>"']/g, function (match) {
      const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
      return map[match];
    });
  }

  initUpload();
  initExistingRows();
  initSpeech();
  initBulkActions();
  bindRowActions(document);
});
