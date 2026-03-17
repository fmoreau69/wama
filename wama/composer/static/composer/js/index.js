/**
 * Composer — Music & SFX Generation
 */

(function () {
    'use strict';

    const CSRF = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';

    // ---------------------------------------------------------------------------
    // Estimation helpers (mirrors model_config.py logic)
    // ---------------------------------------------------------------------------

    const MODELS = window.COMPOSER_MODELS || {};

    function estimateSeconds(modelId, duration) {
        const cfg = MODELS[modelId] || { genFactor: 1.5, overheadS: 15 };
        return Math.max(5, Math.round(duration * cfg.genFactor + cfg.overheadS));
    }

    function formatDuration(seconds) {
        if (seconds < 60) return `~${Math.round(seconds)}s`;
        const m = Math.floor(seconds / 60);
        const s = Math.round(seconds % 60);
        return s ? `~${m}min${String(s).padStart(2, '0')}s` : `~${m}min`;
    }

    // ---------------------------------------------------------------------------
    // Right-panel interactivity
    // ---------------------------------------------------------------------------

    const typeRadios     = document.querySelectorAll('input[name="gen_type"]');
    const modelSelect    = document.getElementById('modelSelect');
    const durationSlider = document.getElementById('durationSlider');
    const durationDisplay  = document.getElementById('durationDisplay');
    const estimateDisplay  = document.getElementById('estimateDisplay');
    const promptInput    = document.getElementById('promptInput');
    const melodyGroup    = document.getElementById('melodyGroup');
    const melodyInput    = document.getElementById('melodyInput');
    const batchFileInput = document.getElementById('batchFileInput');
    const generateBtn    = document.getElementById('generateBtn');
    const importBatchBtn = document.getElementById('importBatchBtn');
    const startAllBtn    = document.getElementById('startAllBtn');
    const clearAllBtn    = document.getElementById('clearAllBtn');

    function getSelectedDuration() {
        return parseFloat(durationSlider?.value || 10);
    }

    function updateEstimate() {
        if (!estimateDisplay || !modelSelect) return;
        const est = estimateSeconds(modelSelect.value, getSelectedDuration());
        estimateDisplay.textContent = formatDuration(est);
    }

    if (durationSlider) {
        durationSlider.addEventListener('input', function () {
            durationDisplay.textContent = this.value + 's';
            updateEstimate();
        });
    }

    typeRadios.forEach(r => r.addEventListener('change', updateModelOptions));

    function updateModelOptions() {
        if (!modelSelect) return;
        const type = document.querySelector('input[name="gen_type"]:checked')?.value || 'music';
        const opts = Array.from(modelSelect.options);
        if (type === 'music') {
            const first = opts.find(o => o.value.startsWith('musicgen'));
            if (first) modelSelect.value = first.value;
        } else {
            const first = opts.find(o => o.value.startsWith('audiogen'));
            if (first) modelSelect.value = first.value;
        }
        checkMelodyVisibility();
        updateEstimate();
    }

    function checkMelodyVisibility() {
        if (!melodyGroup || !modelSelect) return;
        melodyGroup.style.display = modelSelect.value === 'musicgen-melody' ? '' : 'none';
    }

    if (modelSelect) {
        modelSelect.addEventListener('change', () => {
            checkMelodyVisibility();
            updateEstimate();
        });
    }

    // Settings modal estimate
    const settingsDuration = document.getElementById('settingsDuration');
    const settingsDurationVal = document.getElementById('settingsDurationVal');
    const settingsEstimate = document.getElementById('settingsEstimate');
    const settingsModel = document.getElementById('settingsModel');

    function updateSettingsEstimate() {
        if (!settingsEstimate || !settingsModel || !settingsDuration) return;
        const est = estimateSeconds(settingsModel.value, parseFloat(settingsDuration.value));
        settingsEstimate.textContent = formatDuration(est);
    }

    if (settingsDuration) {
        settingsDuration.addEventListener('input', function () {
            settingsDurationVal.textContent = this.value + 's';
            updateSettingsEstimate();
        });
    }
    if (settingsModel) {
        settingsModel.addEventListener('change', updateSettingsEstimate);
    }

    // Init
    updateEstimate();

    // ---------------------------------------------------------------------------
    // Global progress bar
    // ---------------------------------------------------------------------------

    const globalStatus = document.getElementById('globalStatus');
    const globalFill   = document.getElementById('globalProgressFill');
    const gpRunning    = document.getElementById('gpRunning');
    const gpTotal      = document.getElementById('gpTotal');
    const gpEta        = document.getElementById('gpEta');
    const gpPercent    = document.getElementById('gpPercent');

    // Track per-id estimated seconds and start time
    const genMeta = {};  // id → { estimatedSeconds, startedAt, lastProgress }

    document.querySelectorAll('.generation-card').forEach(card => {
        const id = parseInt(card.dataset.id);
        const est = parseInt(card.dataset.estimatedSeconds) || 30;
        genMeta[id] = { estimatedSeconds: est, startedAt: null, lastProgress: 0 };

        const badge = card.querySelector('.badge');
        const status = badge?.textContent.trim();
        if (status === 'En cours' || status === 'En attente') {
            genMeta[id].startedAt = Date.now();
        }
    });

    function updateGlobalBar() {
        const cards = document.querySelectorAll('.generation-card');
        let running = 0, pending = 0, total = cards.length;
        let weightedProgress = 0, totalWeight = 0;
        let totalRemainingSeconds = 0;

        cards.forEach(card => {
            const id = parseInt(card.dataset.id);
            const badge = card.querySelector('.badge');
            const status = badge?.textContent.trim();
            const bar = card.querySelector('.progress-bar');
            const pct = bar ? parseFloat(bar.style.width) || 0 : 0;
            const meta = genMeta[id] || { estimatedSeconds: 30 };

            if (status === 'En cours') running++;
            if (status === 'En attente') pending++;

            const w = meta.estimatedSeconds || 30;
            weightedProgress += pct * w;
            totalWeight += w;

            if (status === 'En cours' || status === 'En attente') {
                const remaining = meta.estimatedSeconds * (1 - pct / 100);
                totalRemainingSeconds += Math.max(0, remaining);
            }
        });

        const active = running + pending;

        if (!globalStatus) return;

        if (active === 0 && total > 0) {
            // All done — show 100% briefly then fade
            globalFill.style.width = '100%';
            globalFill.classList.remove('active');
            if (gpPercent) gpPercent.textContent = '';
            if (gpRunning) gpRunning.textContent = '0';
            if (gpEta) gpEta.textContent = 'terminé';
            setTimeout(() => {
                globalStatus.style.opacity = '0';
                globalStatus.style.pointerEvents = 'none';
            }, 2000);
        } else if (active > 0) {
            globalStatus.style.opacity = '1';
            globalStatus.style.pointerEvents = '';

            const overallPct = totalWeight > 0 ? Math.round(weightedProgress / totalWeight) : 0;
            globalFill.style.width = overallPct + '%';
            globalFill.classList.toggle('active', running > 0);

            if (gpRunning) gpRunning.textContent = running;
            if (gpTotal) gpTotal.textContent = active;
            if (gpPercent) gpPercent.textContent = overallPct ? overallPct + '%' : '';
            if (gpEta) {
                gpEta.textContent = totalRemainingSeconds > 0
                    ? formatDuration(totalRemainingSeconds).replace('~', '')
                    : '…';
            }
        } else if (total === 0) {
            // No items at all — hide bar
            globalStatus.style.opacity = '0';
            globalStatus.style.pointerEvents = 'none';
        }
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

            const modelId = modelSelect?.value || 'musicgen-small';
            const duration = getSelectedDuration();

            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', CSRF);
            formData.append('prompt', prompt);
            formData.append('model', modelId);
            formData.append('duration', duration);

            if (modelId === 'musicgen-melody' && melodyInput?.files[0]) {
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
                        promptInput.value = '';
                        appendGenerationCard(data);
                        startPolling(data.id);
                        updateGlobalBar();
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
            formData.append('default_duration', getSelectedDuration());

            importBatchBtn.disabled = true;
            importBatchBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Import…';

            fetch('/composer/import/', { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        alert('Erreur batch : ' + data.error);
                    } else {
                        if (data.warnings?.length) console.warn('[Composer] Warnings:', data.warnings);
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
        startAllBtn.addEventListener('click', () => {
            fetch('/composer/start_all/', { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json())
                .then(d => { if (d.launched > 0) { showToast(`${d.launched} génération(s) relancée(s)`, 'info'); location.reload(); } });
        });
    }

    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', () => {
            if (!confirm('Supprimer toutes les générations (sauf celles en cours) ?')) return;
            fetch('/composer/clear_all/', { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(() => location.reload());
        });
    }

    // ---------------------------------------------------------------------------
    // Card actions (event delegation)
    // ---------------------------------------------------------------------------

    document.addEventListener('click', function (e) {

        const deleteBtn = e.target.closest('.delete-btn');
        if (deleteBtn) {
            const id = deleteBtn.dataset.id;
            if (!confirm('Supprimer cette génération ?')) return;
            fetch(`/composer/delete/${id}/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(() => {
                    const card = document.querySelector(`.generation-card[data-id="${id}"]`);
                    if (card) card.closest('.mb-2') ? card.closest('.mb-2').remove() : card.remove();
                    delete genMeta[id];
                    updateGlobalBar();
                    checkEmptyState();
                });
            return;
        }

        const batchDeleteBtn = e.target.closest('.batch-delete-btn');
        if (batchDeleteBtn) {
            const bid = batchDeleteBtn.dataset.batchId;
            if (!confirm('Supprimer ce batch et toutes ses générations ?')) return;
            fetch(`/composer/batch/${bid}/delete/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(() => {
                    const group = document.querySelector(`.batch-group[data-batch-id="${bid}"]`);
                    if (group) {
                        group.querySelectorAll('.generation-card').forEach(c => delete genMeta[c.dataset.id]);
                        group.remove();
                    }
                    updateGlobalBar();
                    checkEmptyState();
                });
            return;
        }

        const previewBtn = e.target.closest('.preview-btn');
        if (previewBtn) {
            const id = previewBtn.dataset.id;
            const preview = document.getElementById(`preview_${id}`);
            if (preview) preview.style.display = preview.style.display === 'none' ? '' : 'none';
            return;
        }

        const settingsBtn = e.target.closest('.settings-btn');
        if (settingsBtn) {
            const id = settingsBtn.dataset.id;
            document.getElementById('settingsGenId').value = id;
            if (settingsModel) settingsModel.value = settingsBtn.dataset.model || 'musicgen-small';
            if (settingsDuration) {
                settingsDuration.value = settingsBtn.dataset.duration || 10;
                settingsDurationVal.textContent = settingsDuration.value + 's';
            }
            updateSettingsEstimate();
            new bootstrap.Modal(document.getElementById('settingsModal')).show();
            return;
        }

        const exportBtn = e.target.closest('.export-btn');
        if (exportBtn) {
            const id = exportBtn.dataset.id;
            fetch(`/composer/export/${id}/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json())
                .then(d => {
                    if (d.success) {
                        exportBtn.outerHTML = '<span class="btn btn-sm btn-outline-secondary disabled" title="Exporté"><i class="fas fa-check"></i></span>';
                        showToast('Exporté vers la médiathèque', 'success');
                    } else {
                        alert('Erreur export : ' + (d.error || 'inconnue'));
                    }
                });
            return;
        }

    });

    // Settings save
    const settingsSaveBtn = document.getElementById('settingsSaveBtn');
    if (settingsSaveBtn) {
        settingsSaveBtn.addEventListener('click', () => {
            const id = document.getElementById('settingsGenId').value;
            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', CSRF);
            formData.append('model', settingsModel.value);
            formData.append('duration', settingsDuration.value);

            fetch(`/composer/settings/${id}/`, { method: 'POST', body: formData })
                .then(r => r.json())
                .then(d => {
                    if (d.success) {
                        bootstrap.Modal.getInstance(document.getElementById('settingsModal'))?.hide();
                        // Update card meta with new estimate
                        genMeta[id] = {
                            estimatedSeconds: estimateSeconds(settingsModel.value, parseFloat(settingsDuration.value)),
                            startedAt: Date.now(),
                            lastProgress: 0,
                        };
                        updateCardStatus(id, 'PENDING', 0);
                        startPolling(parseInt(id));
                        updateGlobalBar();
                    } else {
                        alert('Erreur : ' + (d.error || 'inconnue'));
                    }
                });
        });
    }

    // ---------------------------------------------------------------------------
    // Polling
    // ---------------------------------------------------------------------------

    const pollingMap = {};

    function startPolling(genId) {
        if (pollingMap[genId]) return;
        if (!genMeta[genId]) {
            genMeta[genId] = { estimatedSeconds: 30, startedAt: Date.now(), lastProgress: 0 };
        } else {
            genMeta[genId].startedAt = Date.now();
        }
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
                updateGlobalBar();

                if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                    stopPolling(genId);
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

        // Border
        ['border-warning', 'border-success', 'border-danger', 'border-secondary',
         'processing', 'success', 'error'].forEach(c => card.classList.remove(c));
        const borderMap = { RUNNING: ['border-warning', 'processing'], SUCCESS: ['border-success', 'success'],
                            FAILURE: ['border-danger', 'error'], PENDING: ['border-secondary'] };
        (borderMap[status] || ['border-secondary']).forEach(c => card.classList.add(c));

        // Progress bar
        const bar = card.querySelector('.progress-bar');
        if (bar) {
            bar.style.width = progress + '%';
            bar.className = 'progress-bar';
            if (status === 'RUNNING') bar.classList.add('bg-warning', 'progress-bar-striped', 'progress-bar-animated');
            else if (status === 'SUCCESS') bar.classList.add('bg-success');
            else bar.classList.add('bg-secondary');
        }

        // Badge
        const badge = card.querySelector('.badge');
        if (badge) {
            const labels = { PENDING: 'En attente', RUNNING: 'En cours', SUCCESS: 'Succès', FAILURE: 'Échec' };
            const colors = { PENDING: 'bg-secondary', RUNNING: 'bg-warning', SUCCESS: 'bg-success', FAILURE: 'bg-danger' };
            badge.className = `badge flex-shrink-0 ${colors[status] || 'bg-secondary'}`;
            badge.textContent = labels[status] || status;
        }

        // Remaining time on running items
        if (status === 'RUNNING' && genMeta[id]) {
            const elapsed = (Date.now() - (genMeta[id].startedAt || Date.now())) / 1000;
            const est = genMeta[id].estimatedSeconds;
            const remaining = Math.max(0, est - elapsed);
            const remSpan = card.querySelector('.remaining-time');
            if (remSpan) {
                remSpan.textContent = remaining > 3 ? formatDuration(remaining) : '';
            }
        }

        if (genMeta[id]) genMeta[id].lastProgress = progress;

        // Clear or set error message
        const actionsCol = card.querySelector('.col-md-3');
        const existingErr = actionsCol?.querySelector('.error-message');
        if (status === 'FAILURE' && data?.error_message) {
            if (existingErr) {
                existingErr.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${data.error_message.substring(0, 80)}`;
            } else if (actionsCol) {
                actionsCol.insertAdjacentHTML('beforeend',
                    `<small class="error-message text-danger d-block mt-1">` +
                    `<i class="fas fa-exclamation-triangle"></i> ${data.error_message.substring(0, 80)}</small>`);
            }
        } else if (existingErr) {
            existingErr.remove();
        }

        // If success, inject audio player and action buttons
        if (status === 'SUCCESS' && data?.audio_url) {
            const preview = card.querySelector('.audio-preview');
            if (preview && !preview.querySelector('audio')) {
                preview.innerHTML = `<audio controls class="w-100" style="height:32px;">
                    <source src="${data.audio_url}" type="audio/wav"></audio>`;
            }
            if (data.download_url && !card.querySelector('.preview-btn')) {
                const actionsDiv = card.querySelector('.d-flex.flex-wrap');
                const settingsBtn = actionsDiv?.querySelector('.settings-btn');
                const btns = `
                    <button class="btn btn-sm btn-success preview-btn" data-id="${id}" title="Écouter">
                        <i class="fas fa-volume-up"></i></button>
                    <a href="${data.download_url}" class="btn btn-sm btn-info" title="Télécharger">
                        <i class="fas fa-download"></i></a>
                    <button class="btn btn-sm export-btn" data-id="${id}"
                        title="Exporter" style="color:#a78bfa;border:1px solid #a78bfa;background:transparent;">
                        <i class="fas fa-photo-film"></i></button>`;
                if (settingsBtn) settingsBtn.insertAdjacentHTML('afterend', btns);
                else actionsDiv?.insertAdjacentHTML('afterbegin', btns);
            }
        }
    }

    // Auto-start polling for active items on page load
    document.querySelectorAll('.generation-card').forEach(card => {
        const id = parseInt(card.dataset.id);
        const badge = card.querySelector('.badge');
        if (badge && (badge.textContent.trim() === 'En cours' || badge.textContent.trim() === 'En attente')) {
            startPolling(id);
        }
    });

    // Initial global bar update
    if (window.COMPOSER_QUEUE_COUNT > 0) updateGlobalBar();

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    function appendGenerationCard(data) {
        const queue = document.getElementById('composerQueue');
        if (!queue) return;

        const emptyHint = document.getElementById('emptyHint');
        if (emptyHint) emptyHint.remove();

        const typeIcon = data.generation_type === 'music'
            ? '<i class="fas fa-music text-success flex-shrink-0"></i>'
            : '<i class="fas fa-bolt text-danger flex-shrink-0"></i>';

        const est = estimateSeconds(data.model, data.duration);
        const estDisplay = formatDuration(est);

        // Register meta before appending
        genMeta[data.id] = { estimatedSeconds: est, startedAt: Date.now(), lastProgress: 0 };

        const html = `
        <div class="generation-card p-2 rounded border border-warning processing mb-1"
             data-id="${data.id}" data-estimated-seconds="${est}" style="background:#1e2124;">
            <div class="row align-items-center g-2">
                <div class="col-md-4">
                    <div class="d-flex align-items-center gap-2">
                        ${typeIcon}
                        <div class="overflow-hidden">
                            <div class="small text-light fw-bold text-truncate">
                                ${data.prompt.substring(0, 35)}${data.prompt.length > 35 ? '…' : ''}</div>
                            <div class="d-flex align-items-center gap-2">
                                <small class="text-muted">${data.model}</small>
                                <small class="text-white-50">${Math.round(data.duration)}s</small>
                                <small class="text-muted">
                                    <i class="fas fa-hourglass-half fa-xs opacity-50"></i>
                                    <span class="estimated-time">${estDisplay}</span>
                                </small>
                            </div>
                        </div>
                    </div>
                </div>
                <div class="col-md-3 d-none d-md-block">
                    <small class="text-white-50">${data.prompt.substring(0, 60)}</small>
                </div>
                <div class="col-md-2">
                    <div class="d-flex align-items-center gap-2">
                        <span class="badge flex-shrink-0 bg-warning">En cours</span>
                    </div>
                    <div class="progress mt-1" style="height:3px;">
                        <div class="progress-bar bg-warning progress-bar-striped progress-bar-animated" style="width:0%"></div>
                    </div>
                    <small class="text-muted progress-text" style="font-variant-numeric:tabular-nums;">
                        0%
                        <span class="remaining-time ms-1 text-info">${estDisplay}</span>
                    </small>
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
        updateGlobalBar();
    }

    function checkEmptyState() {
        const queue = document.getElementById('composerQueue');
        if (!queue) return;
        const cards = queue.querySelectorAll('.generation-card');
        if (cards.length === 0 && !document.getElementById('emptyHint')) {
            queue.innerHTML = `
            <div class="empty-hint d-flex flex-column align-items-center justify-content-center py-5 text-center"
                 id="emptyHint" style="min-height:280px;">
                <div style="font-size:3rem; opacity:0.15; margin-bottom:1rem;"><i class="fas fa-music"></i></div>
                <p class="text-muted mb-1" style="font-size:1rem;">Aucune génération pour l'instant</p>
                <p class="text-muted small mb-3" style="max-width:280px; line-height:1.6;">
                    Saisissez un <strong class="text-light">prompt</strong>,
                    choisissez un <strong class="text-light">modèle</strong>
                    et cliquez sur <strong class="text-success">Générer</strong> dans le panneau de droite.
                </p>
                <div class="mt-2" style="color:#6c757d; font-size:0.8rem;">
                    <span style="animation: arrowPulse 1.8s ease-in-out infinite; display:inline-block;">→</span>
                    Panneau de paramètres
                    <span style="animation: arrowPulse 1.8s ease-in-out infinite .2s; display:inline-block;">→</span>
                </div>
            </div>`;
        }
    }

    function showToast(message, type) {
        const colors = { success: '#198754', error: '#dc3545', info: '#0dcaf0', warning: '#ffc107' };
        const toast = document.createElement('div');
        toast.style.cssText = `position:fixed;bottom:20px;right:20px;z-index:9999;
            background:${colors[type]||'#333'};color:#fff;padding:10px 16px;border-radius:6px;
            font-size:.9rem;box-shadow:0 4px 12px rgba(0,0,0,.4);max-width:300px;`;
        toast.textContent = message;
        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3500);
    }

})();
