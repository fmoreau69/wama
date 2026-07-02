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

    function _fmtDur(secs) {
        const s = parseInt(secs, 10);
        if (s < 60) return s + 's';
        const m = Math.floor(s / 60);
        const r = s % 60;
        return r ? `${m}m${String(r).padStart(2, '0')}s` : `${m}min`;
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
    const batchFileInput       = document.getElementById('batchFileInput');
    const generateBtn          = document.getElementById('generateBtn');
    const startAllBtn          = document.getElementById('startAllBtn');
    const clearAllBtn          = document.getElementById('clearAllBtn');
    const batchDetectBar       = document.getElementById('batchDetectBar');
    const batchDetectedCount   = document.getElementById('batchDetectedCount');
    const batchCreateCount     = document.getElementById('batchCreateCount');
    const batchCreateAndStartBtn = document.getElementById('batchCreateAndStartBtn');
    const batchCreateOnlyBtn   = document.getElementById('batchCreateOnlyBtn');
    const batchCancelBar       = document.getElementById('batchCancelBar');

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
            durationDisplay.textContent = _fmtDur(this.value);
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

    // (Switch Type retiré — décision Fabien 2026-07-02 : type dérivé du modèle.)

    // Settings save — pied CONFORME : « Enregistrer » (sans relance) / « Enregistrer et relancer ».
    function _postSettings(restart) {
        // Mode batch : applique modèle + durée à tous les items du batch (endpoint batch inchangé).
        if (window._composerBatchSettingsId) {
            const bid = window._composerBatchSettingsId;
            window._composerBatchSettingsId = null;
            const fd = new FormData();
            fd.append('csrfmiddlewaretoken', CSRF);
            fd.append('model', settingsModel.value);
            fd.append('duration', settingsDuration.value);
            fetch(`/composer/batch/${bid}/update/`, { method: 'POST', body: fd })
                .then(r => r.json())
                .then(() => {
                    bootstrap.Modal.getInstance(document.getElementById('settingsModal'))?.hide();
                    location.reload();
                })
                .catch(() => {});
            return;
        }
        const id = document.getElementById('settingsGenId').value;
        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', CSRF);
        formData.append('model', settingsModel.value);
        formData.append('duration', settingsDuration.value);
        // Modale complète (P1) : prompt + format/qualité de sortie.
        const sp = document.getElementById('settingsPrompt');
        if (sp) formData.append('prompt', sp.value);
        const sof = document.getElementById('settingsOutputFormat');
        if (sof) formData.append('output_format', sof.value);
        const soq = document.getElementById('settingsOutputQuality');
        if (soq) formData.append('output_quality', soq.value);
        formData.append('restart', restart ? '1' : '0');

        fetch(`/composer/settings/${id}/`, { method: 'POST', body: formData })
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    bootstrap.Modal.getInstance(document.getElementById('settingsModal'))?.hide();
                    if (!d.restarted) return;   // Enregistrer simple : rien à relancer
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
    }
    const settingsSaveBtn = document.getElementById('settingsSaveBtn');
    if (settingsSaveBtn) settingsSaveBtn.addEventListener('click', () => _postSettings(false));
    const settingsSaveRestartBtn = document.getElementById('settingsSaveRestartBtn');
    if (settingsSaveRestartBtn) settingsSaveRestartBtn.addEventListener('click', () => _postSettings(true));

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
                    if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
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
        card.dataset.status = status;   // pilote le bouton de cycle (WamaCycleButton.autoSync)

        // Border
        ['border-warning', 'border-success', 'border-danger', 'border-secondary',
         'processing', 'success', 'error'].forEach(c => card.classList.remove(c));
        const borderMap = { RUNNING: ['border-warning', 'processing'], SUCCESS: ['border-success', 'success'],
                            FAILURE: ['border-danger', 'error'], PENDING: ['border-secondary'] };
        (borderMap[status] || ['border-secondary']).forEach(c => card.classList.add(c));

        // Progress bar (cartes composer = .wama-progress-fill, pas .progress-bar Bootstrap)
        const bar = card.querySelector('.wama-progress-fill');
        if (bar) {
            bar.style.width = progress + '%';
            bar.classList.toggle('active', status === 'RUNNING');
        }

        // Progress text percentage
        const progressText = card.querySelector('.progress-text');
        if (progressText) {
            const node = progressText.firstChild;
            if (node && node.nodeType === Node.TEXT_NODE) {
                node.textContent = progress + '%\n';
            } else {
                progressText.prepend(document.createTextNode(progress + '%\n'));
            }
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

        // Clear or set error message  (view returns field as 'error', not 'error_message')
        const actionsCol = card.querySelector('.col-md-3');
        const existingErr = actionsCol?.querySelector('.error-message');
        const errMsg = data?.error || data?.error_message || '';
        if (status === 'FAILURE' && errMsg) {
            if (existingErr) {
                existingErr.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${errMsg.substring(0, 80)}`;
            } else if (actionsCol) {
                actionsCol.insertAdjacentHTML('beforeend',
                    `<small class="error-message text-danger d-block mt-1">` +
                    `<i class="fas fa-exclamation-triangle"></i> ${errMsg.substring(0, 80)}</small>`);
            }
        } else if (existingErr) {
            existingErr.remove();
        }

        // Si succès : injecter waveform + boutons download/export
        if (status === 'SUCCESS' && data?.audio_url) {
            // Waveform player (si pas encore injecté)
            if (!document.getElementById(`audioPlayer_${id}`) && window.WamaAudioPlayer) {
                WamaAudioPlayer.inject(data.audio_url, id, card);
            }
            // Boutons download + export (si pas encore injectés)
            if (data.download_url && !card.querySelector('a[title="Télécharger"]')) {
                const actionsDiv = card.querySelector('.d-flex.flex-wrap');
                if (!actionsDiv?.querySelector('.settings-btn')) {
                    const model = card.dataset.model || '';
                    const dur   = card.dataset.duration || '10';
                    actionsDiv?.insertAdjacentHTML('afterbegin',
                        `<button class="btn btn-sm btn-secondary settings-btn"
                            data-id="${id}" data-model="${model}" data-duration="${dur}"
                            title="Modifier les paramètres et re-générer">
                            <i class="fas fa-cog"></i></button>`);
                }
                const settingsBtn = actionsDiv?.querySelector('.settings-btn');
                const btns = `<a href="${data.download_url}" class="btn btn-sm btn-info" title="Télécharger">
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
            const est = parseInt(card.dataset.estimatedSeconds) || 30;
            genMeta[id] = { estimatedSeconds: est, startedAt: Date.now(), lastProgress: 0 };
            startPolling(id);
        }
    });

    // Bouton de cycle commun ▶/⏹/↻ : wire (start/restart→/composer/start, stop→/composer/stop) + auto-sync.
    (function initCycleButton() {
        const q = document.getElementById('composerQueue');
        if (!window.WamaCycleButton || !q) return;
        WamaCycleButton.wire(q, {
            start: async (id) => {
                const card = q.querySelector(`.generation-card[data-id="${id}"]`);
                if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') {
                    try { await fetch(`/composer/stop/${id}/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } }); } catch (e) {}
                }
                try {
                    await fetch(`/composer/start/${id}/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } });
                    if (card) card.dataset.status = 'RUNNING';
                    startPolling(parseInt(id));
                } catch (e) {}
            },
            stop: async (id) => {
                const card = q.querySelector(`.generation-card[data-id="${id}"]`);
                try {
                    const r = await fetch(`/composer/stop/${id}/`, { method: 'POST', headers: { 'X-CSRFToken': CSRF } });
                    const data = await r.json().catch(() => ({}));
                    if (card && data.status) card.dataset.status = data.status;
                } catch (e) {}
            },
        });
        WamaCycleButton.autoSync({ container: q, cardSelector: '.generation-card' });
    })();

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
             data-id="${data.id}" data-status="RUNNING" data-estimated-seconds="${est}"
             data-model="${data.model}" data-duration="${data.duration}"
             data-output-format="${data.output_format || 'original'}" data-output-quality="${data.output_quality || 'balanced'}"
             style="background:#1e2124;">
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
                        ${window.WamaCycleButton ? WamaCycleButton.html('RUNNING', data.id) : ''}
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
