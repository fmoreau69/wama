/**
 * Composer — Music & SFX Generation
 */

(function () {
    'use strict';

    const CSRF = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

    // ---------------------------------------------------------------------------
    // Right-panel interactivity
    // ---------------------------------------------------------------------------

    const typeRadios    = document.querySelectorAll('input[name="gen_type"]');
    const modelSelect   = document.getElementById('modelSelect');
    const durationSlider = document.getElementById('durationSlider');
    const durationDisplay = document.getElementById('durationDisplay');
    const promptInput   = document.getElementById('promptInput');
    const melodyGroup   = document.getElementById('melodyGroup');
    const melodyInput   = document.getElementById('melodyInput');
    const batchFileInput = document.getElementById('batchFileInput');
    const generateBtn   = document.getElementById('generateBtn');
    const importBatchBtn = document.getElementById('importBatchBtn');
    const startAllBtn   = document.getElementById('startAllBtn');
    const clearAllBtn   = document.getElementById('clearAllBtn');
    const queueCount    = document.getElementById('queueCount');

    if (durationSlider) {
        durationSlider.addEventListener('input', function () {
            durationDisplay.textContent = this.value + 's';
        });
    }

    // Update available models when type changes
    typeRadios.forEach(r => r.addEventListener('change', () => updateModelOptions()));

    function updateModelOptions() {
        if (!modelSelect) return;
        const type = document.querySelector('input[name="gen_type"]:checked')?.value || 'music';
        const groups = modelSelect.querySelectorAll('optgroup');
        groups.forEach(g => {
            const isSfx = g.id === 'sfxModelsGroup';
            const show = (type === 'sfx') ? isSfx : !isSfx;
            // Can't hide optgroup reliably; select first visible option
        });

        // Auto-select first model of the selected type
        const opts = Array.from(modelSelect.options);
        if (type === 'music') {
            const first = opts.find(o => o.value.startsWith('musicgen'));
            if (first) modelSelect.value = first.value;
        } else {
            const first = opts.find(o => o.value.startsWith('audiogen'));
            if (first) modelSelect.value = first.value;
        }
        checkMelodyVisibility();
    }

    function checkMelodyVisibility() {
        if (!melodyGroup || !modelSelect) return;
        melodyGroup.style.display = modelSelect.value === 'musicgen-melody' ? '' : 'none';
    }

    if (modelSelect) {
        modelSelect.addEventListener('change', checkMelodyVisibility);
    }

    // ---------------------------------------------------------------------------
    // Generate single item
    // ---------------------------------------------------------------------------

    if (generateBtn) {
        generateBtn.addEventListener('click', function () {
            const prompt = promptInput?.value.trim();
            if (!prompt) {
                alert('Veuillez saisir un prompt.');
                return;
            }

            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', CSRF);
            formData.append('prompt', prompt);
            formData.append('model', modelSelect?.value || 'musicgen-small');
            formData.append('duration', durationSlider?.value || '10');

            if (modelSelect?.value === 'musicgen-melody' && melodyInput?.files[0]) {
                formData.append('melody_reference', melodyInput.files[0]);
            }

            generateBtn.disabled = true;
            generateBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Envoi…';

            fetch('/composer/generate/', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        alert('Erreur : ' + data.error);
                    } else {
                        appendGenerationCard(data);
                        promptInput.value = '';
                        updateQueueCount(1);
                        startPolling(data.id);
                    }
                })
                .catch(err => alert('Erreur réseau : ' + err))
                .finally(() => {
                    generateBtn.disabled = false;
                    generateBtn.innerHTML = '<i class="fas fa-play me-1"></i> Générer';
                });
        });
    }

    // ---------------------------------------------------------------------------
    // Import batch file
    // ---------------------------------------------------------------------------

    if (importBatchBtn) {
        importBatchBtn.addEventListener('click', function () {
            const file = batchFileInput?.files[0];
            if (!file) {
                alert('Sélectionnez d\'abord un fichier batch.');
                return;
            }

            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', CSRF);
            formData.append('batch_file', file);
            formData.append('default_model', modelSelect?.value || 'musicgen-small');
            formData.append('default_duration', durationSlider?.value || '10');

            importBatchBtn.disabled = true;
            importBatchBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Import…';

            fetch('/composer/import/', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        alert('Erreur batch : ' + data.error);
                    } else {
                        if (data.warnings && data.warnings.length) {
                            console.warn('[Composer] Batch warnings:', data.warnings);
                        }
                        location.reload();
                    }
                })
                .catch(err => alert('Erreur réseau : ' + err))
                .finally(() => {
                    importBatchBtn.disabled = false;
                    importBatchBtn.innerHTML = '<i class="fas fa-file-import me-1"></i> Importer batch';
                    if (batchFileInput) batchFileInput.value = '';
                });
        });
    }

    // ---------------------------------------------------------------------------
    // Start all / Clear all
    // ---------------------------------------------------------------------------

    if (startAllBtn) {
        startAllBtn.addEventListener('click', function () {
            fetch('/composer/start_all/', {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF },
            })
                .then(r => r.json())
                .then(data => {
                    if (data.launched > 0) {
                        showToast(`${data.launched} génération(s) relancée(s)`, 'info');
                        location.reload();
                    }
                });
        });
    }

    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', function () {
            if (!confirm('Supprimer toutes les générations (sauf celles en cours) ?')) return;
            fetch('/composer/clear_all/', {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF },
            })
                .then(() => location.reload());
        });
    }

    // ---------------------------------------------------------------------------
    // Card actions (delegation)
    // ---------------------------------------------------------------------------

    document.addEventListener('click', function (e) {
        const deleteBtn = e.target.closest('.delete-btn');
        if (deleteBtn) {
            const id = deleteBtn.dataset.id;
            if (!confirm('Supprimer cette génération ?')) return;
            fetch(`/composer/delete/${id}/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF },
            }).then(() => {
                const card = document.querySelector(`.generation-card[data-id="${id}"]`);
                if (card) card.closest('.mb-2, .generation-card')?.remove() || card.remove();
            });
            return;
        }

        const batchDeleteBtn = e.target.closest('.batch-delete-btn');
        if (batchDeleteBtn) {
            const bid = batchDeleteBtn.dataset.batchId;
            if (!confirm('Supprimer ce batch et toutes ses générations ?')) return;
            fetch(`/composer/batch/${bid}/delete/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF },
            }).then(() => {
                const group = document.querySelector(`.batch-group[data-batch-id="${bid}"]`);
                if (group) group.remove();
            });
            return;
        }

        const previewBtn = e.target.closest('.preview-btn');
        if (previewBtn) {
            const id = previewBtn.dataset.id;
            const preview = document.getElementById(`preview_${id}`);
            if (preview) {
                preview.style.display = preview.style.display === 'none' ? '' : 'none';
            }
            return;
        }

        const settingsBtn = e.target.closest('.settings-btn');
        if (settingsBtn) {
            const id = settingsBtn.dataset.id;
            const model = settingsBtn.dataset.model;
            const duration = settingsBtn.dataset.duration;

            document.getElementById('settingsGenId').value = id;
            const modelSel = document.getElementById('settingsModel');
            if (modelSel && model) modelSel.value = model;
            const durSlider = document.getElementById('settingsDuration');
            const durDisplay = document.getElementById('settingsDurationDisplay');
            if (durSlider && duration) {
                durSlider.value = duration;
                durDisplay.textContent = parseFloat(duration).toFixed(0) + 's';
            }

            const modal = new bootstrap.Modal(document.getElementById('settingsModal'));
            modal.show();
            return;
        }

        const exportBtn = e.target.closest('.export-btn');
        if (exportBtn) {
            const id = exportBtn.dataset.id;
            fetch(`/composer/export/${id}/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF },
            })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        exportBtn.outerHTML = '<span class="btn btn-sm btn-outline-secondary disabled" title="Exporté"><i class="fas fa-check"></i></span>';
                        showToast('Exporté vers la médiathèque', 'success');
                    } else {
                        alert('Erreur export : ' + (data.error || 'inconnue'));
                    }
                });
            return;
        }
    });

    // Settings duration slider
    const settingsDuration = document.getElementById('settingsDuration');
    const settingsDurationDisplay = document.getElementById('settingsDurationDisplay');
    if (settingsDuration) {
        settingsDuration.addEventListener('input', function () {
            settingsDurationDisplay.textContent = this.value + 's';
        });
    }

    // Settings save
    const settingsSaveBtn = document.getElementById('settingsSaveBtn');
    if (settingsSaveBtn) {
        settingsSaveBtn.addEventListener('click', function () {
            const id = document.getElementById('settingsGenId').value;
            const model = document.getElementById('settingsModel').value;
            const duration = document.getElementById('settingsDuration').value;

            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', CSRF);
            formData.append('model', model);
            formData.append('duration', duration);

            fetch(`/composer/settings/${id}/`, { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        bootstrap.Modal.getInstance(document.getElementById('settingsModal'))?.hide();
                        startPolling(parseInt(id));
                        updateCardStatus(id, 'PENDING', 0);
                    } else {
                        alert('Erreur : ' + (data.error || 'inconnue'));
                    }
                });
        });
    }

    // ---------------------------------------------------------------------------
    // Polling
    // ---------------------------------------------------------------------------

    const pollingMap = {};  // id → intervalId

    function startPolling(genId) {
        if (pollingMap[genId]) return;
        pollingMap[genId] = setInterval(() => pollProgress(genId), 2000);
    }

    function stopPolling(genId) {
        clearInterval(pollingMap[genId]);
        delete pollingMap[genId];
    }

    function pollProgress(genId) {
        fetch(`/composer/progress/${genId}/`)
            .then(r => r.json())
            .then(data => {
                updateCardStatus(genId, data.status, data.progress, data);
                if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                    stopPolling(genId);
                    updateQueueCount(-1);
                    if (data.status === 'SUCCESS') {
                        showToast('Génération terminée !', 'success');
                    } else {
                        showToast('Génération échouée : ' + (data.error || ''), 'error');
                    }
                }
            })
            .catch(() => stopPolling(genId));
    }

    function updateCardStatus(id, status, progress, data) {
        const card = document.querySelector(`.generation-card[data-id="${id}"]`);
        if (!card) return;

        // Update border color
        card.className = card.className.replace(/border-\w+/, '');
        const borderClass = {
            RUNNING: 'border-warning',
            SUCCESS: 'border-success',
            FAILURE: 'border-danger',
            PENDING: 'border-secondary',
        }[status] || 'border-secondary';
        card.classList.add(borderClass);

        // Update progress bar
        const bar = card.querySelector('.progress-bar');
        if (bar) bar.style.width = progress + '%';
        const pctText = card.querySelector('.text-muted:last-of-type');

        // Update status badge
        const badge = card.querySelector('.badge');
        if (badge) {
            const labels = { PENDING: 'En attente', RUNNING: 'En cours', SUCCESS: 'Succès', FAILURE: 'Échec' };
            const colors = { PENDING: 'bg-secondary', RUNNING: 'bg-warning', SUCCESS: 'bg-success', FAILURE: 'bg-danger' };
            badge.className = `badge ${colors[status] || 'bg-secondary'}`;
            badge.textContent = labels[status] || status;
        }

        // If success, add audio controls
        if (status === 'SUCCESS' && data?.audio_url) {
            let preview = card.querySelector('.audio-preview');
            if (preview && !preview.querySelector('audio')) {
                preview.innerHTML = `<audio controls class="w-100" style="height:32px;">
                    <source src="${data.audio_url}" type="audio/wav"></audio>`;
            }
            // Add/show action buttons
            if (data.download_url && !card.querySelector('.preview-btn')) {
                const actionsDiv = card.querySelector('.d-flex.flex-wrap');
                if (actionsDiv) {
                    const settingsBtn = actionsDiv.querySelector('.settings-btn');
                    const downloadBtn = `
                        <button class="btn btn-sm btn-success preview-btn" data-id="${id}" title="Écouter">
                            <i class="fas fa-volume-up"></i></button>
                        <a href="${data.download_url}" class="btn btn-sm btn-info" title="Télécharger">
                            <i class="fas fa-download"></i></a>
                        <button class="btn btn-sm btn-outline-purple export-btn" data-id="${id}"
                            title="Exporter" style="color:#a78bfa; border-color:#a78bfa;">
                            <i class="fas fa-photo-film"></i></button>`;
                    if (settingsBtn) {
                        settingsBtn.insertAdjacentHTML('afterend', downloadBtn);
                    } else {
                        actionsDiv.insertAdjacentHTML('afterbegin', downloadBtn);
                    }
                }
            }
        }
    }

    // Auto-poll running generations on page load
    document.querySelectorAll('.generation-card').forEach(card => {
        const id = card.dataset.id;
        const badge = card.querySelector('.badge');
        if (badge && (badge.textContent.trim() === 'En cours' || badge.textContent.trim() === 'En attente')) {
            startPolling(parseInt(id));
        }
    });

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function appendGenerationCard(data) {
        const queue = document.getElementById('composerQueue');
        if (!queue) return;

        // Remove empty placeholder
        const placeholder = queue.querySelector('.text-center.py-5');
        if (placeholder) placeholder.remove();

        const typeIcon = data.generation_type === 'music'
            ? '<i class="fas fa-music text-success"></i>'
            : '<i class="fas fa-bolt text-danger"></i>';

        const html = `
        <div class="generation-card p-2 rounded border border-secondary mb-2" data-id="${data.id}" style="background:#1e2124;">
            <div class="row align-items-center g-2">
                <div class="col-md-4">
                    <div class="d-flex align-items-center gap-2">
                        ${typeIcon}
                        <div>
                            <div class="small text-light fw-bold">${data.prompt.substring(0, 35)}${data.prompt.length > 35 ? '…' : ''}</div>
                            <small class="text-muted">${data.model} · ${Math.round(data.duration)}s</small>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <small class="text-white-50">${data.prompt.substring(0, 60)}</small>
                </div>
                <div class="col-md-2">
                    <span class="badge bg-warning">En cours</span>
                    <div class="progress mt-1" style="height:4px;">
                        <div class="progress-bar bg-warning progress-bar-striped progress-bar-animated" style="width:0%"></div>
                    </div>
                    <small class="text-muted">0%</small>
                </div>
                <div class="col-md-3">
                    <div class="d-flex flex-wrap gap-1">
                        <button class="btn btn-sm btn-danger delete-btn" data-id="${data.id}" title="Supprimer">
                            <i class="fas fa-trash"></i></button>
                    </div>
                    <div class="audio-preview mt-1" id="preview_${data.id}" style="display:none;"></div>
                </div>
            </div>
        </div>`;

        queue.insertAdjacentHTML('afterbegin', html);
    }

    function updateQueueCount(delta) {
        if (!queueCount) return;
        const current = parseInt(queueCount.textContent) || 0;
        queueCount.textContent = Math.max(0, current + delta);
    }

    function showToast(message, type) {
        const colors = { success: '#198754', error: '#dc3545', info: '#0dcaf0', warning: '#ffc107' };
        const toast = document.createElement('div');
        toast.style.cssText = `
            position:fixed; bottom:20px; right:20px; z-index:9999;
            background:${colors[type] || '#333'}; color:#fff;
            padding:10px 16px; border-radius:6px; font-size:0.9rem;
            box-shadow:0 4px 12px rgba(0,0,0,0.4); max-width:300px;`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3500);
    }

})();
