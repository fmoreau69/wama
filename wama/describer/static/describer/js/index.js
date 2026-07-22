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

    // Bouton de cycle commun ▶/⏹/↻ : câblage délégué (start/restart→startDescription, stop→stopDescription)
    // + auto-sync sur data-status (l'icône suit le statut, plug-and-play). startDescription/stopDescription
    // sont des déclarations de fonction (hoistées) → référençables ici.
    if (window.WamaCycleButton && queueContainer) {
        WamaCycleButton.wire(queueContainer, { start: (id) => startDescription(id), stop: (id) => stopDescription(id) });
        WamaCycleButton.autoSync({ container: queueContainer, cardSelector: '.wama-card' });
    }

    // Global options
    const outputStyle = document.getElementById('output_style');
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

    // Browse button (legacy) + drop zone click
    if (fileInput) {
        fileInput.addEventListener('change', handleFileSelect);
    }
    if (browseBtn && fileInput) {
        browseBtn.addEventListener('click', () => fileInput.click());
    }

    // Drag and drop
    if (dropZone) {
        dropZone.addEventListener('click', () => fileInput && fileInput.click());
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

    function handleFileSelect(e) {
        if (e.target.files.length > 0) {
            handleFiles(e.target.files);
        }
    }

    async function handleFiles(files) {
        const fileList = Array.from(files);
        if (fileList.length === 1 && window._batchImport) {
            if (await window._batchImport.detectAndHandle(fileList[0])) return;
        }
        // Upload séquentiel puis consolidation en UN batch si plusieurs fichiers.
        const ids = [];
        for (const file of fileList) {
            const id = await uploadFile(file);
            if (id) ids.push(id);
        }
        if (ids.length > 1 && config.urls.consolidate) {
            try {
                await fetch(config.urls.consolidate, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ ids }),
                });
            } catch (e) { /* ignore : à défaut, items individuels */ }
            window.location.reload();
        }
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
        formData.append('output_style', outputStyle ? outputStyle.value : 'detailed');
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
            if (window.WamaFM) WamaFM.uploaded();  // fichier ajouté → refresh filemanager
            return data.id;

        } catch (error) {
            console.error('Upload error:', error);
            showToast('Erreur lors de l\'upload', 'danger');
            return null;
        }
    }

    // === Queue Management ===

    // addQueueItem : la reconstruction JS (~85 l. — sans .wama-card ni Dupliquer,
    // appendChild en FIN de file) est supprimee ; la card arrive rendue du serveur.
    function addQueueItem(data) {
        refreshCard(data.id);
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
    document.querySelectorAll('.wama-card').forEach(bindCardEvents);

    // Resume polling for cards already in RUNNING state (e.g. after page reload)
    document.querySelectorAll('.wama-card.processing').forEach(card => {
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

    // Mode batch de la modale : réutilise la modale individuelle (conventions §9.8).
    let _settingsBatchId = null;

    document.addEventListener('click', function (e) {
        const bbtn = e.target.closest('.batch-settings-btn');
        if (!bbtn) return;
        openBatchSettings(bbtn);
    });

    // Duplication d'un item (carte autonome ou dans un batch) — la vue place la
    // copie DANS le même batch (élément frère). Aucun handler n'existait avant.
    document.addEventListener('click', function (e) {
        const dbtn = e.target.closest('.duplicate-btn');
        if (!dbtn || !dbtn.dataset.duplicateUrl) return;
        fetch(dbtn.dataset.duplicateUrl, { method: 'POST', headers: { 'X-CSRFToken': config.csrfToken } })
            .then(r => r.json())
            .then(() => window.location.reload())
            .catch(() => {});
    });

    function openBatchSettings(btn) {
        const group = btn.closest('.batch-group');
        const firstItemBtn = group ? group.querySelector('.settings-btn') : null;
        if (firstItemBtn) {
            openSettings(firstItemBtn);
        } else if (settingsModalInstance) {
            settingsModalInstance.show();
        }
        _settingsBatchId = btn.dataset.batchId;
        const title = document.querySelector('#settingsModal .modal-title');
        if (title) title.textContent = 'Paramètres du batch — appliqués à tous les éléments';
    }

    function openSettings(btn) {
        _settingsBatchId = null;
        const _t = document.querySelector('#settingsModal .modal-title');
        if (_t) _t.textContent = 'Paramètres';
        const id = btn.dataset.id;
        const outputStyle = btn.dataset.outputStyle;
        const outputLanguage = btn.dataset.outputLanguage;
        const maxLength = btn.dataset.maxLength;
        const generateSummary = btn.dataset.generateSummary === 'true';
        const verifyCoherence = btn.dataset.verifyCoherence === 'true';

        // Populate modal fields — NULL-SAFE : les champs sont générés par WamaParams (context item).
        // On dispatch input+change pour que WamaParams mette à jour son affichage (ex. valeur du slider).
        // settingsMaxLengthValue (ancien span d'affichage) n'existe plus : WamaParams gère l'affichage.
        const _set = function (elId, val) {
            const el = document.getElementById(elId);
            if (!el) return;
            el.value = val;
            el.dispatchEvent(new Event('input', { bubbles: true }));
            el.dispatchEvent(new Event('change', { bubbles: true }));
        };
        _set('settingsDescriptionId', id);
        _set('settingsOutputFormat', outputStyle);
        _set('settingsOutputLanguage', outputLanguage);
        _set('settingsMaxLength', maxLength);

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
        const outputStyle = document.getElementById('settingsOutputFormat').value;
        const outputLanguage = document.getElementById('settingsOutputLanguage').value;
        const maxLength = document.getElementById('settingsMaxLength').value;
        const generateSummary = document.getElementById('settingsGenerateSummary')?.checked || false;
        const verifyCoherence = document.getElementById('settingsVerifyCoherence')?.checked || false;

        const payload = {
            output_style: outputStyle,
            output_language: outputLanguage,
            max_length: parseInt(maxLength),
            generate_summary: generateSummary,
            verify_coherence: verifyCoherence,
        };

        // Mode batch : applique à tous les items + relance éventuelle.
        if (_settingsBatchId) {
            const bid = _settingsBatchId;
            _settingsBatchId = null;
            try {
                await fetch(config.urls.batchUpdate.replace('/0/', `/${bid}/`), {
                    method: 'POST',
                    headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload),
                });
                if (settingsModalInstance) settingsModalInstance.hide();
                if (startAfterSave) {
                    await fetch(config.urls.batchStart.replace('/0/', `/${bid}/`), {
                        method: 'POST', headers: { 'X-CSRFToken': config.csrfToken },
                    });
                }
            } catch (e) { /* ignore */ }
            window.location.reload();
            return;
        }

        try {
            const response = await fetch(config.urls.updateOptions.replace('/0/', `/${descriptionId}/`), {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    output_style: outputStyle,
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
                const card = document.querySelector(`.wama-card[data-id="${descriptionId}"]`);
                if (card) {
                    updateCardSettings(card, outputStyle, outputLanguage, maxLength, generateSummary, verifyCoherence);
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

    function updateCardSettings(card, outputStyle, outputLanguage, maxLength, generateSummary, verifyCoherence) {
        // Update the settings button data attributes
        const settingsBtn = card.querySelector('.settings-btn');
        if (settingsBtn) {
            settingsBtn.dataset.outputStyle = outputStyle;
            settingsBtn.dataset.outputLanguage = outputLanguage;
            settingsBtn.dataset.maxLength = maxLength;
            settingsBtn.dataset.generateSummary = generateSummary ? 'true' : 'false';
            settingsBtn.dataset.verifyCoherence = verifyCoherence ? 'true' : 'false';
        }

        // Update the options display in the card
        const optionsCol = card.querySelector('.col-md-2 small');
        if (optionsCol && optionsCol.innerHTML.includes('fa-align-left')) {
            let html = `
                <i class="fas fa-align-left"></i> ${getFormatLabel(outputStyle)}<br>
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

    // ⏹ Stop : arrête le traitement (endpoint commun) → item relançable (↻ via autoSync sur data-status).
    async function stopDescription(id) {
        const card = document.querySelector(`.wama-card[data-id="${id}"]`);
        try {
            const response = await fetch(config.urls.stop.replace('/0/', `/${id}/`), {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
            });
            const data = await response.json();
            if (card && data && data.status) card.dataset.status = data.status;  // → autoSync repasse en ↻
        } catch (e) { /* non-fatal */ }
    }

    async function startDescription(id) {
        const card = document.querySelector(`.wama-card[data-id="${id}"]`);
        if (!card) return;

        // Relance PENDANT le traitement (modale « Enregistrer & démarrer ») : stopper d'abord pour
        // éviter le 409 « déjà en cours », puis relancer avec les params à jour.
        if ((card.dataset.status || '').toUpperCase() === 'RUNNING') {
            card.dataset.status = 'PENDING';
            await stopDescription(id);
        }

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
                const card = document.querySelector(`.wama-card[data-id="${id}"]`);

                if (!card) {
                    stopPolling(id);
                    return;
                }

                updateCardStatus(card, data.status, data.progress, data);

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
                    if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager

                    if (data.status === 'SUCCESS') {
                        refreshCard(card.dataset.id);
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

    function updateCardStatus(card, status, progress, data) {
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
        const progressBar = card.querySelector('.wama-progress-fill');
        if (progressBar) {
            progressBar.style.width = progress + '%';
            if (status === 'RUNNING') progressBar.classList.add('active');
            else progressBar.classList.remove('active');
        }

        const progressText = card.querySelector('.progress-text');
        if (progressText) {
            progressText.textContent = progress + '%';
        }

        // ETA (moteur commun) — seed depuis l'estimateur serveur (service-based → modèle chargé)
        if (window.WamaEta) {
            WamaEta.render(card.querySelector('.wama-eta'),
                           WamaEta.update(card.dataset.id, {
                               progress: progress, status: status,
                               seedSeconds: data && data.estimated_seconds,
                               modelLoaded: false,
                           }));
        }

        // Update card class + statut (data-status pilote le bouton de cycle via WamaCycleButton.autoSync).
        card.dataset.status = status;
        card.classList.remove('processing', 'success', 'error');
        switch (status) {
            case 'RUNNING':
                card.classList.add('processing');
                // (le bouton de cycle passe en ⏹ Stop via autoSync ; on ne retire plus aucun bouton)
                break;
            case 'SUCCESS': card.classList.add('success'); break;
            case 'FAILURE': card.classList.add('error'); break;
        }
    }

    // Card RENDUE SERVEUR — source unique : partial _description_card.html via
    // describer:card_html (recette T+C). Remplace updateCardWithResult (~60 lignes
    // d'injection de boutons/preview qui divergeaient du serveur) — 2026-07-05.
    // Card RENDUE SERVEUR — source unique : partial _description_card.html via
    // describer:card_html. Remplace la card si presente, sinon INSERE en tete de file
    // (upload). Re-bind obligatoire : les events sont attaches PAR card (pas de
    // delegation) — le refresh v1 les perdait (corrige 2026-07-05).
    function refreshCard(id) {
        fetch(config.urls.cardHtml.replace('/0/', '/' + id + '/'))
            .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(html => {
                const queue = document.getElementById('descriptionQueue');
                if (!queue) return;
                const existing = queue.querySelector(`.wama-card[data-id="${id}"]`);
                if (existing) existing.outerHTML = html;
                else {
                    queue.querySelector('.empty-queue')?.remove();
                    queue.insertAdjacentHTML('afterbegin', html);
                }
                const fresh = queue.querySelector(`.wama-card[data-id="${id}"]`);
                if (fresh) bindCardEvents(fresh);
            })
            .catch(() => {});
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
                // Élément issu d'un batch : total/affichage du batch changent → recharger
                if (data.batch_changed) { if (window.WamaFM) WamaFM.deleted(); location.reload(); return; }
                const card = document.querySelector(`.wama-card[data-id="${id}"]`);
                if (card) card.remove();
                updateQueueCount();
                if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
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
            if (downloadBtn) downloadBtn.href = config.urls.download.replace('/0/', `/${id}/`) + '?format=txt';

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

    // Reset settings
    document.getElementById('resetOptions')?.addEventListener('click', () => {
        const defaults = {
            'output_style': 'detailed',
            'output_language': 'fr',
            'max_length': '500',
        };
        Object.entries(defaults).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
            localStorage.removeItem(`describer_setting_${id}`);
        });
        // Reset range display
        const maxLengthVal = document.getElementById('max_length_value');
        if (maxLengthVal) maxLengthVal.textContent = '500';
        // Reset checkboxes
        const generateSummary = document.getElementById('globalGenerateSummary');
        if (generateSummary) generateSummary.checked = false;
        const verifyCoherence = document.getElementById('globalVerifyCoherence');
        if (verifyCoherence) verifyCoherence.checked = false;
    });

    // === Global Progress ===

    async function updateGlobalProgress() {
        return; // Neutralisé : barre globale + ETA pilotées par la brique commune wama-global-progress.js.
        try {
            const response = await fetch(config.urls.globalProgress, {
                headers: {
                    'X-CSRFToken': config.csrfToken
                }
            });

            const data = await response.json();

            const progressBar = document.getElementById('globalProgressBar');
            const progressStats = document.getElementById('globalProgressStats');
            const progressPct = document.getElementById('globalProgressPct');
            const globalStatus = document.getElementById('globalStatus');

            const p = data.overall_progress || 0;
            if (progressBar) progressBar.style.width = p + '%';
            if (progressStats) progressStats.textContent = `${data.success}/${data.total} terminé · ${data.running} en cours`;
            if (window.WamaEta) WamaEta.render(document.getElementById('globalEta'), WamaEta.aggregateAll());
            if (progressPct) progressPct.textContent = p ? p + '%' : '';
            if (globalStatus) {
                const active = (data.total || 0) > 0;
                globalStatus.style.opacity = active ? '1' : '0';
                globalStatus.style.pointerEvents = active ? '' : 'none';
            }

        } catch (error) {
            console.error('Global progress error:', error);
        }
    }

    function updateQueueCount() {
        const cards = document.querySelectorAll('.wama-card');
        if (queueCount) {
            queueCount.textContent = cards.length;
        }
    }

    // === Utilities ===

    function showToast(message, type = 'info') {
        // Brique commune (wama-app-base.js) — plus d'alert() bloquant
        if (window.WamaApp && WamaApp.toast) WamaApp.toast(message, type);
        else console.info('[Describer]', message);
    }

    // Initial global progress update
    updateGlobalProgress();

    // Update global progress every 5 seconds
    setInterval(updateGlobalProgress, 5000);

    // ── Batch template download — now served by Django view ───────────────
    // The batchTemplateLink anchor uses href="{% url 'describer:batch_template' %}" directly.

    // ── Batch delete ───────────────────────────────────────────────────────
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.batch-delete-btn');
        if (!btn) return;
        const batchId = btn.dataset.batchId;
        if (!confirm('Supprimer ce batch et toutes ses descriptions ?')) return;
        const url = config.urls.batchDelete.replace('/0/', `/${batchId}/`);
        fetch(url, {method: 'POST', headers: {'X-CSRFToken': config.csrfToken}})
            .then(r => r.json())
            .then(() => {
                const el = btn.closest('.batch-group');
                if (el) el.remove();
                else location.reload();
                updateQueueCount();
            })
            .catch(() => showToast('Erreur lors de la suppression', 'danger'));
    });

    // ── Batch start (▶ de la card mère commune _batch_card.html, 2026-07-06) ──
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.batch-start-btn');
        if (!btn) return;
        const url = config.urls.batchStart.replace('/0/', `/${btn.dataset.batchId}/`);
        fetch(url, {method: 'POST', headers: {'X-CSRFToken': config.csrfToken}})
            .then(r => r.json())
            .then(data => { (data.started || []).forEach(id => { refreshCard(id); startPolling(id); }); })
            .catch(() => showToast('Erreur lors du lancement du batch', 'danger'));
    });

    // ── Batch duplicate ────────────────────────────────────────────────────
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.batch-duplicate-btn');
        if (!btn) return;
        const batchId = btn.dataset.batchId;
        const url = config.urls.batchDuplicate.replace('/0/', `/${batchId}/`);
        fetch(url, {method: 'POST', headers: {'X-CSRFToken': config.csrfToken}})
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    showToast('Batch dupliqué', 'success');
                    setTimeout(() => location.reload(), 800);
                }
            })
            .catch(() => showToast('Erreur lors de la duplication', 'danger'));
    });
});

// Filemanager 'Envoyer vers...' — reload page to show imported item
document.addEventListener('wama:fileimported', function(e) {
    if (e.detail && e.detail.app === 'describer') { window.location.reload(); }
});
