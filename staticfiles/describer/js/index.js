/**
 * WAMA Describer - Queue Management JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
    const config = window.DESCRIBER_CONFIG || {};

    // DOM Elements
    const dropZone = document.getElementById('dropZone');
    const fileInput = document.getElementById('fileInput');
    const browseBtn = document.getElementById('browseBtn');
    const queueContainer = document.getElementById('descriptionQueue');
    const queueCount = document.getElementById('queueCount');

    // Global options
    const outputFormat = document.getElementById('output_format');
    const outputLanguage = document.getElementById('output_language');
    const maxLength = document.getElementById('max_length');
    const maxLengthValue = document.getElementById('max_length_value');

    // Action buttons
    const startAllBtn = document.getElementById('startAllBtn');
    const downloadAllBtn = document.getElementById('downloadAllBtn');
    const clearAllBtn = document.getElementById('clearAllBtn');

    // Progress tracking
    const pollers = new Map();

    // Update max length display
    if (maxLength && maxLengthValue) {
        maxLength.addEventListener('input', function() {
            maxLengthValue.textContent = this.value;
        });
    }

    // === File Upload ===

    // Browse button
    if (browseBtn && fileInput) {
        browseBtn.addEventListener('click', () => fileInput.click());
        fileInput.addEventListener('change', handleFileSelect);
    }

    // Drag and drop
    if (dropZone) {
        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('dragover');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('dragover');
        });

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('dragover');

            // Check for FileManager data
            if (window.FileManager && window.FileManager.getFileManagerData) {
                const fileData = window.FileManager.getFileManagerData(e);
                if (fileData && fileData.path) {
                    handleFileManagerImport(fileData.path);
                    return;
                }
            }

            // Regular file drop
            if (e.dataTransfer.files.length > 0) {
                handleFiles(e.dataTransfer.files);
            }
        });
    }

    // === URL Upload Form ===
    const mediaUrlForm = document.getElementById('media-url-form');
    if (mediaUrlForm) {
        mediaUrlForm.addEventListener('submit', async function(e) {
            e.preventDefault();

            const mediaUrlInput = this.querySelector('input[name="media_url"]');
            const mediaUrl = mediaUrlInput ? mediaUrlInput.value.trim() : '';

            if (!mediaUrl) {
                showToast('Veuillez entrer une URL de média.', 'warning');
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
                formData.append('output_format', outputFormat ? outputFormat.value : 'detailed');
                formData.append('output_language', outputLanguage ? outputLanguage.value : 'fr');
                formData.append('max_length', maxLength ? maxLength.value : '500');

                const response = await fetch(config.urls.upload, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': config.csrfToken
                    },
                    body: formData
                });

                const data = await response.json();

                if (data.error) {
                    showToast('Erreur: ' + data.error, 'danger');
                    return;
                }

                // Add item to queue
                addQueueItem(data);
                updateQueueCount();
                showToast('Média téléchargé avec succès!', 'success');

                // Clear the form
                mediaUrlInput.value = '';

            } catch (error) {
                console.error('URL upload error:', error);
                showToast('Erreur lors du téléchargement depuis l\'URL', 'danger');
            } finally {
                // Restore button
                if (submitBtn) {
                    submitBtn.disabled = false;
                    submitBtn.innerHTML = originalBtnHtml;
                }
            }
        });
    }

    function handleFileSelect(e) {
        if (e.target.files.length > 0) {
            handleFiles(e.target.files);
        }
    }

    function handleFiles(files) {
        Array.from(files).forEach(file => uploadFile(file));
    }

    async function handleFileManagerImport(path) {
        try {
            const result = await window.FileManager.importToApp(path, 'describer');
            if (result.imported) {
                window.location.reload();
            }
        } catch (error) {
            console.error('Import error:', error);
            showToast('Erreur lors de l\'import: ' + error.message, 'danger');
        }
    }

    async function uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('output_format', outputFormat ? outputFormat.value : 'detailed');
        formData.append('output_language', outputLanguage ? outputLanguage.value : 'fr');
        formData.append('max_length', maxLength ? maxLength.value : '500');

        try {
            const response = await fetch(config.urls.upload, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken
                },
                body: formData
            });

            const data = await response.json();

            if (data.error) {
                showToast('Erreur: ' + data.error, 'danger');
                return;
            }

            addQueueItem(data);
            updateQueueCount();

        } catch (error) {
            console.error('Upload error:', error);
            showToast('Erreur lors de l\'upload', 'danger');
        }
    }

    // === Queue Management ===

    function addQueueItem(data) {
        // Remove empty queue message
        const emptyQueue = queueContainer.querySelector('.empty-queue');
        if (emptyQueue) emptyQueue.remove();

        const card = document.createElement('div');
        card.className = 'synthesis-card';
        card.dataset.id = data.id;

        const previewUrl = `/common/preview/describer/${data.id}/`;

        card.innerHTML = `
            <div class="row align-items-center">
                <div class="col-md-3">
                    <strong>
                        <i class="fas ${data.type_icon || 'fa-file'}"></i>
                        <button type="button" class="btn btn-link p-0 text-decoration-none preview-media-link filename"
                                data-preview-url="${previewUrl}"
                                style="color: inherit;">
                            ${data.filename}
                        </button>
                    </strong>
                    <br>
                    <small class="text-white-50">
                        <span class="badge bg-secondary">${(data.detected_type || 'auto').toUpperCase()}</span>
                        ${data.file_size}
                    </small>
                </div>
                <div class="col-md-2">
                    <small>
                        <i class="fas fa-align-left"></i> ${getFormatLabel(data.output_format)}<br>
                        <i class="fas fa-language"></i> ${getLanguageLabel(data.output_language)}<br>
                        <i class="fas fa-text-width"></i> ${data.max_length || 500} mots
                    </small>
                </div>
                <div class="col-md-3">
                    <small class="text-white-50 result-preview">
                        ${data.properties || 'En attente de traitement'}
                    </small>
                </div>
                <div class="col-md-2">
                    <span class="badge bg-secondary status-badge">PENDING</span>
                    <div class="progress mt-2" style="height: 8px;">
                        <div class="progress-bar bg-info progress-fill" style="width: 0%"></div>
                    </div>
                    <small class="text-light progress-text">0%</small>
                </div>
                <div class="col-md-2">
                    <div class="btn-group-actions">
                        <button class="btn btn-sm btn-primary start-btn" data-id="${data.id}" title="Demarrer">
                            <i class="fas fa-play"></i>
                        </button>
                        <button class="btn btn-sm btn-secondary settings-btn"
                                data-id="${data.id}"
                                data-output-format="${data.output_format}"
                                data-output-language="${data.output_language}"
                                data-max-length="${data.max_length || 500}"
                                data-generate-summary="${document.getElementById('globalGenerateSummary')?.checked ? 'true' : 'false'}"
                                data-verify-coherence="${document.getElementById('globalVerifyCoherence')?.checked ? 'true' : 'false'}"
                                title="Parametres">
                            <i class="fas fa-cog"></i>
                        </button>
                        <button class="btn btn-sm btn-danger delete-btn" data-id="${data.id}" title="Supprimer">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
        `;

        queueContainer.appendChild(card);
        bindCardEvents(card);

        // Initialize preview for new item
        if (typeof initMediaPreview === 'function') {
            initMediaPreview();
        }
    }

    function getFormatLabel(format) {
        const labels = {
            'summary': 'Resume court',
            'detailed': 'Description detaillee',
            'scientific': 'Synthese scientifique',
            'bullet_points': 'Points cles',
            'meeting': 'Compte-rendu reunion'
        };
        return labels[format] || format;
    }

    function getLanguageLabel(lang) {
        const labels = {
            'fr': 'Francais',
            'en': 'English',
            'auto': 'Langue source'
        };
        return labels[lang] || lang;
    }

    function bindCardEvents(card) {
        // Start button
        const startBtn = card.querySelector('.start-btn');
        if (startBtn) {
            startBtn.addEventListener('click', () => startDescription(card.dataset.id));
        }

        // Delete button
        const deleteBtn = card.querySelector('.delete-btn');
        if (deleteBtn) {
            deleteBtn.addEventListener('click', () => deleteDescription(card.dataset.id));
        }

        // Preview button
        const previewBtn = card.querySelector('.preview-btn');
        if (previewBtn) {
            previewBtn.addEventListener('click', () => showPreview(card.dataset.id));
        }

        // Settings button
        const settingsBtn = card.querySelector('.settings-btn');
        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => openSettings(settingsBtn));
        }
    }

    // Bind events for existing cards
    document.querySelectorAll('.synthesis-card').forEach(bindCardEvents);

    // Resume polling for cards already in RUNNING state (e.g. after page reload)
    document.querySelectorAll('.synthesis-card.processing').forEach(card => {
        startPolling(card.dataset.id);
    });

    // === Settings Modal ===
    const settingsModal = document.getElementById('settingsModal');
    const settingsModalInstance = settingsModal ? new bootstrap.Modal(settingsModal) : null;

    // Update max length display in settings modal
    const settingsMaxLength = document.getElementById('settingsMaxLength');
    const settingsMaxLengthValue = document.getElementById('settingsMaxLengthValue');
    if (settingsMaxLength && settingsMaxLengthValue) {
        settingsMaxLength.addEventListener('input', function() {
            settingsMaxLengthValue.textContent = this.value;
        });
    }

    function openSettings(btn) {
        const id = btn.dataset.id;
        const outputFormat = btn.dataset.outputFormat;
        const outputLanguage = btn.dataset.outputLanguage;
        const maxLength = btn.dataset.maxLength;
        const generateSummary = btn.dataset.generateSummary === 'true';
        const verifyCoherence = btn.dataset.verifyCoherence === 'true';

        // Populate modal fields
        document.getElementById('settingsDescriptionId').value = id;
        document.getElementById('settingsOutputFormat').value = outputFormat;
        document.getElementById('settingsOutputLanguage').value = outputLanguage;
        document.getElementById('settingsMaxLength').value = maxLength;
        document.getElementById('settingsMaxLengthValue').textContent = maxLength;

        const genSumEl = document.getElementById('settingsGenerateSummary');
        if (genSumEl) genSumEl.checked = generateSummary;

        const vcEl = document.getElementById('settingsVerifyCoherence');
        if (vcEl) vcEl.checked = verifyCoherence;

        // Show modal
        if (settingsModalInstance) {
            settingsModalInstance.show();
        }
    }

    async function saveSettings(startAfterSave = false) {
        const descriptionId = document.getElementById('settingsDescriptionId').value;
        const outputFormat = document.getElementById('settingsOutputFormat').value;
        const outputLanguage = document.getElementById('settingsOutputLanguage').value;
        const maxLength = document.getElementById('settingsMaxLength').value;
        const generateSummary = document.getElementById('settingsGenerateSummary')?.checked || false;
        const verifyCoherence = document.getElementById('settingsVerifyCoherence')?.checked || false;

        try {
            const response = await fetch(config.urls.updateOptions.replace('/0/', `/${descriptionId}/`), {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    output_format: outputFormat,
                    output_language: outputLanguage,
                    max_length: parseInt(maxLength),
                    generate_summary: generateSummary,
                    verify_coherence: verifyCoherence,
                })
            });

            if (response.ok) {
                // Close modal
                if (settingsModalInstance) {
                    settingsModalInstance.hide();
                }

                // Update card display
                const card = document.querySelector(`.synthesis-card[data-id="${descriptionId}"]`);
                if (card) {
                    updateCardSettings(card, outputFormat, outputLanguage, maxLength, generateSummary, verifyCoherence);
                }

                if (startAfterSave) {
                    startDescription(descriptionId);
                } else {
                    showToast('Parametres enregistres', 'success');
                }
            } else {
                const data = await response.json();
                showToast('Erreur: ' + (data.error || 'Erreur inconnue'), 'danger');
            }
        } catch (error) {
            console.error('Save settings error:', error);
            showToast('Erreur lors de la sauvegarde', 'danger');
        }
    }

    function updateCardSettings(card, outputFormat, outputLanguage, maxLength, generateSummary, verifyCoherence) {
        // Update the settings button data attributes
        const settingsBtn = card.querySelector('.settings-btn');
        if (settingsBtn) {
            settingsBtn.dataset.outputFormat = outputFormat;
            settingsBtn.dataset.outputLanguage = outputLanguage;
            settingsBtn.dataset.maxLength = maxLength;
            settingsBtn.dataset.generateSummary = generateSummary ? 'true' : 'false';
            settingsBtn.dataset.verifyCoherence = verifyCoherence ? 'true' : 'false';
        }

        // Update the options display in the card
        const optionsCol = card.querySelector('.col-md-2 small');
        if (optionsCol && optionsCol.innerHTML.includes('fa-align-left')) {
            let html = `
                <i class="fas fa-align-left"></i> ${getFormatLabel(outputFormat)}<br>
                <i class="fas fa-language"></i> ${getLanguageLabel(outputLanguage)}<br>
                <i class="fas fa-text-width"></i> ${maxLength} mots`;
            if (generateSummary) html += `<br><i class="fas fa-file-lines"></i> Résumé`;
            if (verifyCoherence) html += `<br><i class="fas fa-spell-check"></i> Cohérence`;
            optionsCol.innerHTML = html;
        }
    }

    // Save settings buttons
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', () => saveSettings(false));
    }

    const saveAndStartBtn = document.getElementById('saveAndStartBtn');
    if (saveAndStartBtn) {
        saveAndStartBtn.addEventListener('click', () => saveSettings(true));
    }

    // === Description Processing ===

    async function startDescription(id) {
        const card = document.querySelector(`.synthesis-card[data-id="${id}"]`);
        if (!card) return;

        // Disable start button immediately to prevent double-clicks
        const startBtn = card.querySelector('.start-btn');
        if (startBtn) startBtn.disabled = true;

        try {
            const response = await fetch(config.urls.start.replace('/0/', `/${id}/`), {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken,
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();

            if (data.error) {
                showToast('Erreur: ' + data.error, 'danger');
                if (startBtn) startBtn.disabled = false;
                return;
            }

            updateCardStatus(card, 'RUNNING', 0);
            startPolling(id);

        } catch (error) {
            console.error('Start error:', error);
            showToast('Erreur lors du demarrage', 'danger');
            if (startBtn) startBtn.disabled = false;
        }
    }

    function startPolling(id) {
        if (pollers.has(id)) return;

        const interval = setInterval(async () => {
            try {
                const response = await fetch(config.urls.progress.replace('/0/', `/${id}/`), {
                    headers: {
                        'X-CSRFToken': config.csrfToken
                    }
                });

                const data = await response.json();
                const card = document.querySelector(`.synthesis-card[data-id="${id}"]`);

                if (!card) {
                    stopPolling(id);
                    return;
                }

                updateCardStatus(card, data.status, data.progress);

                // Update partial result if available
                if (data.partial_text) {
                    const preview = card.querySelector('.result-preview');
                    if (preview) {
                        preview.textContent = data.partial_text.substring(0, 150) + '...';
                    }
                }

                // Stop polling if done
                if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                    stopPolling(id);

                    if (data.status === 'SUCCESS') {
                        updateCardWithResult(card, data);
                    }

                    updateGlobalProgress();
                }

            } catch (error) {
                console.error('Polling error:', error);
            }
        }, 1000);

        pollers.set(id, interval);
    }

    function stopPolling(id) {
        const interval = pollers.get(id);
        if (interval) {
            clearInterval(interval);
            pollers.delete(id);
        }
    }

    function updateCardStatus(card, status, progress) {
        // Always show 100% when done
        if (status === 'SUCCESS') progress = 100;

        // Update status badge
        const badge = card.querySelector('.status-badge');
        if (badge) {
            badge.textContent = status;
            badge.className = 'badge status-badge ';
            switch (status) {
                case 'PENDING': badge.classList.add('bg-secondary'); break;
                case 'RUNNING': badge.classList.add('bg-warning'); break;
                case 'SUCCESS': badge.classList.add('bg-success'); break;
                case 'FAILURE': badge.classList.add('bg-danger'); break;
            }
        }

        // Update progress bar
        const progressBar = card.querySelector('.progress-fill');
        if (progressBar) {
            progressBar.style.width = progress + '%';
        }

        const progressText = card.querySelector('.progress-text');
        if (progressText) {
            progressText.textContent = progress + '%';
        }

        // Update card class and hide start button once running
        card.classList.remove('processing', 'success', 'error');
        switch (status) {
            case 'RUNNING':
                card.classList.add('processing');
                card.querySelector('.start-btn')?.remove();
                break;
            case 'SUCCESS': card.classList.add('success'); break;
            case 'FAILURE': card.classList.add('error'); break;
        }
    }

    function updateCardWithResult(card, data) {
        // Update result preview
        if (data.result_text) {
            const preview = card.querySelector('.result-preview');
            if (preview) {
                preview.textContent = data.result_text.substring(0, 150) + '...';
                preview.classList.remove('text-white-50');
                preview.classList.add('text-light');
            }
        }

        // Update action buttons
        const actions = card.querySelector('.btn-group-actions');
        if (actions) {
            const id = card.dataset.id;

            // Remove start button if present (it was shown before processing)
            actions.querySelector('.start-btn')?.remove();

            // Remove existing preview/download buttons to avoid duplication on re-run
            actions.querySelector('.preview-btn')?.remove();
            actions.querySelector('.download-btn')?.remove();

            // Insert preview + download before duplicate-btn (or delete-btn as fallback)
            const anchor = actions.querySelector('.duplicate-btn') || actions.querySelector('.delete-btn');
            if (anchor) {
                const downloadBtn = document.createElement('a');
                downloadBtn.className = 'btn btn-sm btn-info download-btn';
                downloadBtn.href = config.urls.download.replace('/0/', `/${id}/`);
                downloadBtn.title = 'Telecharger';
                downloadBtn.innerHTML = '<i class="fas fa-download"></i>';

                const previewBtn = document.createElement('button');
                previewBtn.className = 'btn btn-sm btn-success preview-btn';
                previewBtn.dataset.id = id;
                previewBtn.title = 'Voir le resultat';
                previewBtn.innerHTML = '<i class="fas fa-eye"></i>';
                previewBtn.addEventListener('click', () => showPreview(id));

                actions.insertBefore(downloadBtn, anchor);
                actions.insertBefore(previewBtn, downloadBtn);
            }
        }
    }

    async function deleteDescription(id) {
        if (!confirm('Supprimer cette description ?')) return;

        try {
            const response = await fetch(config.urls.delete.replace('/0/', `/${id}/`), {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken
                }
            });

            const data = await response.json();

            if (data.deleted) {
                stopPolling(id);
                const card = document.querySelector(`.synthesis-card[data-id="${id}"]`);
                if (card) card.remove();
                updateQueueCount();
                showToast('Description supprimee', 'success');
            }

        } catch (error) {
            console.error('Delete error:', error);
            showToast('Erreur lors de la suppression', 'danger');
        }
    }

    // === Preview Modal (tabbed) ===

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

    function renderDescMarkdown(text) {
        if (!text) return '';
        return text
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/### (.+)/g, '<h6 class="text-info mt-3 mb-1">$1</h6>')
            .replace(/## (.+)/g, '<h5 class="text-warning mt-3 mb-2">$1</h5>')
            .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
            .replace(/^- (.+)$/gm, '<li>$1</li>')
            .replace(/(<li>.*<\/li>\n?)+/g, m => `<ul>${m}</ul>`)
            .replace(/\n\n/g, '<br><br>')
            .replace(/\n/g, '<br>');
    }

    async function showPreview(id) {
        const modal = new bootstrap.Modal(document.getElementById('resultModal'));
        const loader = document.getElementById('resultLoader');
        const content = document.getElementById('resultContent');
        const resultText = document.getElementById('resultText');
        const downloadBtn = document.getElementById('resultDownloadBtn');

        loader.style.display = 'block';
        content.style.display = 'none';

        // Reset tabs visibility
        const tabResumeBtn = document.getElementById('tab-resume-btn');
        const tabCoherenceBtn = document.getElementById('tab-coherence-btn');
        if (tabResumeBtn) tabResumeBtn.style.display = 'none';
        if (tabCoherenceBtn) tabCoherenceBtn.style.display = 'none';

        // Activate description tab
        const descTab = document.getElementById('tab-description-btn');
        if (descTab) { try { new bootstrap.Tab(descTab).show(); } catch(e) {} }

        modal.show();

        try {
            // Use progress endpoint to get full data including summary/coherence
            const response = await fetch(config.urls.progress.replace('/0/', `/${id}/`), {
                headers: { 'X-CSRFToken': config.csrfToken }
            });

            const data = await response.json();

            document.getElementById('resultModalTitle').textContent = `Description #${id}`;
            resultText.textContent = data.result_text || 'Aucun resultat disponible';
            setWordCount('wc-description', data.result_text || '');
            downloadBtn.href = config.urls.download.replace('/0/', `/${id}/`);

            // Résumé tab
            const resumeContent = document.getElementById('resumeContent');
            if (data.summary && resumeContent) {
                resumeContent.innerHTML = renderDescMarkdown(data.summary);
                setWordCount('wc-resume', data.summary || '');
                if (tabResumeBtn) tabResumeBtn.style.display = '';
            }

            // Cohérence tab
            const coherenceContent = document.getElementById('coherenceContent');
            if (data.coherence_score !== null && data.coherence_score !== undefined && coherenceContent) {
                const score = data.coherence_score;
                const scoreColor = score >= 80 ? 'success' : score >= 50 ? 'warning' : 'danger';
                let notesHtml = '';
                if (data.coherence_notes) {
                    const notes = data.coherence_notes.split('\n').filter(l => l.trim());
                    notesHtml = '<ul class="mt-2">' + notes.map(n => `<li class="text-light small">${n.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</li>`).join('') + '</ul>';
                }
                let sideBySide = '';
                if (data.coherence_suggestion) {
                    const orig = (data.result_text || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                    const sugg = data.coherence_suggestion.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
                    sideBySide = `
                        <div class="row mt-3">
                          <div class="col-md-6">
                            <div class="card" style="background:#1e1e1e;border:1px solid #495057;">
                              <div class="card-header py-1 small text-muted">Texte original</div>
                              <div class="card-body p-2">
                                <pre style="color:#d4d4d4;white-space:pre-wrap;font-size:13px;max-height:300px;overflow-y:auto;margin:0;">${orig}</pre>
                              </div>
                            </div>
                          </div>
                          <div class="col-md-6">
                            <div class="card" style="background:#1e2820;border:1px solid #2ea043;">
                              <div class="card-header py-1 small text-muted">Correction proposée</div>
                              <div class="card-body p-2">
                                <pre style="color:#7ee787;white-space:pre-wrap;font-size:13px;max-height:300px;overflow-y:auto;margin:0;">${sugg}</pre>
                              </div>
                            </div>
                          </div>
                        </div>`;
                }
                coherenceContent.innerHTML = `
                    <div class="d-flex align-items-center mb-2">
                        <span class="badge bg-${scoreColor} fs-5 me-3">${score}/100</span>
                        <span class="text-light">Score de cohérence</span>
                    </div>
                    ${notesHtml}${sideBySide}`;
                setWordCount('wc-coherence', data.coherence_suggestion || data.result_text || '');
                if (tabCoherenceBtn) tabCoherenceBtn.style.display = '';
            }

            loader.style.display = 'none';
            content.style.display = 'block';

        } catch (error) {
            console.error('Preview error:', error);
            loader.innerHTML = '<p class="text-danger">Erreur lors du chargement</p>';
        }
    }

    // === Batch Actions ===

    if (startAllBtn) {
        startAllBtn.addEventListener('click', async () => {
            try {
                const response = await fetch(config.urls.startAll, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': config.csrfToken
                    }
                });

                const data = await response.json();

                if (data.started && data.started.length > 0) {
                    data.started.forEach(id => startPolling(id));
                    showToast(`${data.count} description(s) lancee(s)`, 'success');
                } else {
                    showToast('Aucune description a lancer', 'info');
                }

            } catch (error) {
                console.error('Start all error:', error);
                showToast('Erreur', 'danger');
            }
        });
    }

    if (downloadAllBtn) {
        downloadAllBtn.addEventListener('click', () => {
            window.location.href = config.urls.downloadAll;
        });
    }

    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', async () => {
            if (!confirm('Supprimer toutes les descriptions ?')) return;

            try {
                const response = await fetch(config.urls.clearAll, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': config.csrfToken
                    }
                });

                const data = await response.json();
                showToast(`${data.deleted} description(s) supprimee(s)`, 'success');
                window.location.reload();

            } catch (error) {
                console.error('Clear all error:', error);
                showToast('Erreur', 'danger');
            }
        });
    }

    // === Global Progress ===

    async function updateGlobalProgress() {
        try {
            const response = await fetch(config.urls.globalProgress, {
                headers: {
                    'X-CSRFToken': config.csrfToken
                }
            });

            const data = await response.json();

            const progressBar = document.getElementById('globalProgressBar');
            const progressStats = document.getElementById('globalProgressStats');

            if (progressBar) {
                progressBar.style.width = data.overall_progress + '%';
                progressBar.textContent = data.overall_progress + '%';
            }

            if (progressStats) {
                progressStats.textContent = `${data.success}/${data.total} termine`;
            }

        } catch (error) {
            console.error('Global progress error:', error);
        }
    }

    function updateQueueCount() {
        const cards = document.querySelectorAll('.synthesis-card');
        if (queueCount) {
            queueCount.textContent = cards.length;
        }
    }

    // === Utilities ===

    function showToast(message, type = 'info') {
        // Use FileManager toast if available
        if (window.FileManager && window.FileManager.showToast) {
            window.FileManager.showToast(message, type);
            return;
        }

        // Fallback to alert
        alert(message);
    }

    // Initial global progress update
    updateGlobalProgress();

    // Update global progress every 5 seconds
    setInterval(updateGlobalProgress, 5000);
});
