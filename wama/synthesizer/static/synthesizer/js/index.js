// Attendre que le DOM soit chargé
document.addEventListener('DOMContentLoaded', function() {
    // Configuration - URLs définies côté serveur (injectées depuis le template)
    if (!window.WAMA_CONFIG) {
        console.error('WAMA_CONFIG not found. Make sure the template injects it.');
        WamaApp.toast('Erreur de configuration. Veuillez recharger la page.', 'warning');
        return;
    }

    const URLS = window.WAMA_CONFIG.urls;
    const csrfToken = window.WAMA_CONFIG.csrfToken;

    // Bouton de cycle commun ▶/⏹/↻ : clics délégués (start/restart→start, stop→stop). Les cards sont
    // re-rendues depuis le partial serveur au poll → l'icône suit le statut (pas besoin d'autoSync ici).
    if (window.WamaCycleButton) {
        WamaCycleButton.wire(document, {
            start: async (id) => {
                try { await fetch(URLS.start + id + '/', { method: 'GET', headers: { 'X-CSRFToken': csrfToken } }); } catch (e) {}
                window.location.reload();
            },
            stop: async (id) => {
                try { await fetch(URLS.stop + id + '/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } }); } catch (e) {}
                window.location.reload();
            },
        });
    }

    // Range sliders
    const speedSlider = document.getElementById('speed');
    const pitchSlider = document.getElementById('pitch');

    if (speedSlider) {
        speedSlider.addEventListener('input', (e) => {
            document.getElementById('speed_value').textContent = e.target.value;
        });
    }

    if (pitchSlider) {
        pitchSlider.addEventListener('input', (e) => {
            document.getElementById('pitch_value').textContent = e.target.value;
        });
    }

    const resetBtn = document.getElementById('resetOptions');
    if (resetBtn) {
        resetBtn.addEventListener('click', () => {
            document.getElementById('speed').value = 1.0;
            document.getElementById('pitch').value = 1.0;
            document.getElementById('speed_value').textContent = '1.0';
            document.getElementById('pitch_value').textContent = '1.0';
        });
    }

    // === Language compatibility warning ===
    const ENGLISH_ONLY_MODELS = new Set(['tacotron2', 'speedy_speech', 'vits']);

    function checkLangCompat(modelValue, langValue, warningEl) {
        if (!warningEl) return;
        warningEl.style.display =
            (ENGLISH_ONLY_MODELS.has(modelValue) && langValue !== 'en') ? 'block' : 'none';
    }

    const langSelect      = document.getElementById('language');
    const langWarning     = document.getElementById('lang-compat-warning');

    function updateMainLangWarning() {
        if (ttsModelSelect && langSelect)
            checkLangCompat(ttsModelSelect.value, langSelect.value, langWarning);
    }

    if (langSelect) langSelect.addEventListener('change', updateMainLangWarning);

    // === Higgs Audio model toggle ===
    function toggleHiggsOptions(modelValue) {
        const higgsOptions = document.getElementById('higgsOptions');
        const languageGroup = document.getElementById('languageGroup');
        const voicePresetGroup = document.getElementById('voicePresetGroup');
        const isHiggs = modelValue === 'higgs_audio';

        if (higgsOptions) higgsOptions.style.display = isHiggs ? 'block' : 'none';
        // Higgs handles language internally, hide language/voice preset selectors
        if (languageGroup) languageGroup.style.display = isHiggs ? 'none' : '';
        if (voicePresetGroup) voicePresetGroup.style.display = isHiggs ? 'none' : '';
    }

    const ttsModelSelect = document.getElementById('tts_model');
    if (ttsModelSelect) {
        ttsModelSelect.addEventListener('change', (e) => {
            toggleHiggsOptions(e.target.value);
            updateMainLangWarning();
        });
        // Initialize on page load
        toggleHiggsOptions(ttsModelSelect.value);
        updateMainLangWarning();
    }

    const multiSpeakerCheckbox = document.getElementById('multi_speaker');
    if (multiSpeakerCheckbox) {
        multiSpeakerCheckbox.addEventListener('change', (e) => {
            const sceneDescGroup = document.getElementById('sceneDescGroup');
            if (sceneDescGroup) sceneDescGroup.style.display = e.target.checked ? 'block' : 'none';
        });
    }

    // Helper: append Higgs-specific fields to FormData
    function appendHiggsFields(formData) {
        const multiSpeaker = document.getElementById('multi_speaker');
        if (multiSpeaker) {
            formData.append('multi_speaker', multiSpeaker.checked ? '1' : '0');
        }
        const sceneDesc = document.getElementById('scene_description');
        if (sceneDesc && sceneDesc.value.trim()) {
            formData.append('scene_description', sceneDesc.value.trim());
        }
    }

    // Drag & Drop
    const dropZone = document.getElementById('dropZoneSynthesizer');
    const fileInput = document.getElementById('fileInput');
    const browseBtn = document.getElementById('browseBtn');

    if (dropZone && fileInput) {
        dropZone.addEventListener('click', () => fileInput.click());

        if (browseBtn) {
            browseBtn.addEventListener('click', (e) => {
                e.stopPropagation();
                fileInput.click();
            });
        }

        dropZone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropZone.classList.add('drag-over');
        });

        dropZone.addEventListener('dragleave', () => {
            dropZone.classList.remove('drag-over');
        });

        dropZone.addEventListener('drop', async (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');

            // Check if this is a FileManager drop
            if (window.FileManager && window.FileManager.getFileManagerData) {
                const fileData = window.FileManager.getFileManagerData(e);
                if (fileData && fileData.path) {
                    // Handle FileManager import
                    try {
                        const result = await window.FileManager.importToApp(fileData.path, 'synthesizer');
                        if (result.imported && result.is_batch && result.tasks && result.tasks.length > 0) {
                            // Batch file detected — show batch bar instead of reloading
                            _batchServerPath = result.server_path;
                            _batchFile = null;
                            _showBatchBar(null, result.tasks, result.warnings || [], true);
                        } else if (result.imported) {
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
            handleFilesWithDetect(e.dataTransfer.files);
        });

        fileInput.addEventListener('change', (e) => {
            handleFilesWithDetect(e.target.files);
        });

        // FileManager import result (vakata.dnd path — native drop event never fires for filemanager drags)
        dropZone.addEventListener('filemanager:imported', (e) => {
            const result = e.detail;
            if (result.is_batch && result.tasks && result.tasks.length > 0) {
                e.preventDefault(); // Prevent filemanager from reloading
                _batchServerPath = result.server_path;
                _batchFile = null;
                _showBatchBar(null, result.tasks, result.warnings || [], true);
            }
            // Non-batch: let filemanager reload the page (defaultPrevented stays false)
        });
    }

    // Settings modal instance + live warning (used by delegation handler below)
    const settingsModal = document.getElementById('settingsModal');
    const settingsModalInstance = settingsModal ? new bootstrap.Modal(settingsModal) : null;

    // Live warning update inside item settings modal
    const settingsTtsModelEl = document.getElementById('settingsTtsModel');
    const settingsLanguageEl = document.getElementById('settingsLanguage');
    const settingsLangWarning = document.getElementById('settings-lang-compat-warning');
    function updateSettingsLangWarning() {
        if (settingsTtsModelEl && settingsLanguageEl)
            checkLangCompat(settingsTtsModelEl.value, settingsLanguageEl.value, settingsLangWarning);
    }
    if (settingsTtsModelEl) settingsTtsModelEl.addEventListener('change', updateSettingsLangWarning);
    if (settingsLanguageEl) settingsLanguageEl.addEventListener('change', updateSettingsLangWarning);

    // Save settings button
    const saveSettingsBtn = document.getElementById('saveSettingsBtn');
    if (saveSettingsBtn) {
        saveSettingsBtn.addEventListener('click', async () => {
            await saveSettings(false);
        });
    }

    // Save and start button
    const saveAndStartBtn = document.getElementById('saveAndStartBtn');
    if (saveAndStartBtn) {
        saveAndStartBtn.addEventListener('click', async () => {
            await saveSettings(true);
        });
    }

    // Save settings function
    async function saveSettings(startAfterSave) {
        const synthesisId = document.getElementById('settingsSynthesisId').value;
        const formData = new FormData();

        formData.append('tts_model', document.getElementById('settingsTtsModel').value);
        formData.append('language', document.getElementById('settingsLanguage').value);
        formData.append('voice_preset', document.getElementById('settingsVoicePreset').value);
        formData.append('speed', document.getElementById('settingsSpeed').value);
        formData.append('pitch', document.getElementById('settingsPitch').value);
        var _of = document.getElementById('settingsOutputFormat');
        var _oq = document.getElementById('settingsOutputQuality');
        if (_of) formData.append('output_format', _of.value);
        if (_oq) formData.append('output_quality', _oq.value);
        appendHiggsFields(formData);

        try {
            // Save settings
            const response = await fetch(URLS.updateOptions + synthesisId + '/', {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: formData
            });

            if (response.ok) {
                // Close modal
                if (settingsModalInstance) {
                    settingsModalInstance.hide();
                }

                if (startAfterSave) {
                    // Start the synthesis
                    const startResponse = await fetch(URLS.start + synthesisId + '/', {
                        method: 'GET',
                        headers: { 'X-CSRFToken': csrfToken }
                    });

                    if (startResponse.ok) {
                        location.reload();
                    } else {
                        const data = await startResponse.json();
                        WamaApp.toast('Paramètres sauvegardés mais erreur au démarrage: ' + (data.error || 'Échec'), 'error');
                        location.reload();
                    }
                } else {
                    // Just reload to show updated settings
                    location.reload();
                }
            } else {
                const data = await response.json();
                WamaApp.toast('Erreur lors de la sauvegarde: ' + (data.error || 'Échec'), 'error');
            }
        } catch (error) {
            console.error('Save settings error:', error);
            WamaApp.toast('Erreur: ' + error.message, 'error');
        }
    }

    // === Unified card button delegation ===
    // Uses document-level event delegation so that cards replaced in-place by the
    // polling loop (no full page reload) automatically get working buttons.
    document.addEventListener('click', async e => {
        // .start-btn — start or retry a synthesis
        const startBtn = e.target.closest('.start-btn');
        if (startBtn) {
            const id = startBtn.dataset.id;
            try {
                const r = await fetch(URLS.start + id + '/', { method: 'GET', headers: { 'X-CSRFToken': csrfToken } });
                if (r.ok) {
                    location.reload();
                } else {
                    const d = await r.json();
                    WamaApp.toast('Erreur: ' + (d.error || 'Échec du démarrage'), 'error');
                }
            } catch (err) { WamaApp.toast('Erreur: ' + err.message, 'error'); }
            return;
        }

        // .preview-text-btn — aperçu du texte via le composant commun
        // (showPreviewModal gère l'affichage scrollable + bouton Copier).
        const textBtn = e.target.closest('.preview-text-btn');
        if (textBtn) {
            const id = textBtn.dataset.id;
            try {
                const response = await fetch(URLS.textPreview + id + '/');
                const data = await response.json();
                if (response.ok && data.success) {
                    if (typeof window.showPreviewModal === 'function') {
                        window.showPreviewModal({
                            text_content: data.text_content || '',
                            name: data.filename || 'Texte',
                            properties: `${data.word_count} mots • Durée estimée: ${data.duration_display}`,
                        });
                    }
                } else {
                    WamaApp.toast(data.error || 'Impossible de charger le texte', 'error');
                }
            } catch (err) {
                WamaApp.toast('Erreur: ' + err.message, 'error');
            }
            return;
        }

        // .settings-btn — open item settings modal
        const settingsBtn = e.target.closest('.settings-btn');
        if (settingsBtn && settingsModalInstance) {
            const id = settingsBtn.dataset.id;
            const ttsModel = settingsBtn.dataset.ttsModel;
            const language = settingsBtn.dataset.language;
            const voicePreset = settingsBtn.dataset.voicePreset;
            const speed = settingsBtn.dataset.speed || '1.0';
            const pitch = settingsBtn.dataset.pitch || '1.0';
            document.getElementById('settingsSynthesisId').value = id;
            document.getElementById('settingsTtsModel').value = ttsModel;
            document.getElementById('settingsLanguage').value = language;
            document.getElementById('settingsVoicePreset').value = voicePreset;
            document.getElementById('settingsSpeed').value = speed;
            document.getElementById('settingsSpeedValue').textContent = speed;
            document.getElementById('settingsPitch').value = pitch;
            document.getElementById('settingsPitchValue').textContent = pitch;
            var _ofEl = document.getElementById('settingsOutputFormat');
            var _oqEl = document.getElementById('settingsOutputQuality');
            if (_ofEl && settingsBtn.dataset.outputFormat) _ofEl.value = settingsBtn.dataset.outputFormat;
            if (_oqEl && settingsBtn.dataset.outputQuality) _oqEl.value = settingsBtn.dataset.outputQuality;
            checkLangCompat(ttsModel, language, document.getElementById('settings-lang-compat-warning'));
            settingsModalInstance.show();
            return;
        }

        // .duplicate-btn — duplicate a synthesis
        const dupBtn = e.target.closest('.duplicate-btn');
        if (dupBtn) {
            const id = dupBtn.dataset.id;
            try {
                const r = await fetch(URLS.duplicate + id + '/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } });
                if (r.ok) {
                    location.reload();
                } else {
                    const d = await r.json();
                    WamaApp.toast('Erreur: ' + (d.error || 'Échec de la duplication'), 'error');
                }
            } catch (err) { WamaApp.toast('Erreur: ' + err.message, 'error'); }
            return;
        }

        // .delete-btn — remove a synthesis (no page reload: remove card from DOM)
        const deleteBtn = e.target.closest('.delete-btn');
        if (deleteBtn) {
            if (!confirm('Supprimer cette synthèse ?')) return;
            const id = deleteBtn.dataset.id;
            try {
                const r = await fetch(URLS.delete + id + '/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } });
                if (r.ok) {
                    // Élément issu d'un batch : total/affichage du batch changent → recharger
                    const data = await r.json().catch(() => ({}));
                    if (data.batch_changed) { if (window.WamaFM) WamaFM.deleted(); location.reload(); return; }
                    const card = deleteBtn.closest('.synthesis-card');
                    if (card) card.remove();
                    if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
                } else {
                    WamaApp.toast('Erreur lors de la suppression', 'error');
                }
            } catch (err) { WamaApp.toast('Erreur: ' + err.message, 'error'); }
            return;
        }
    });

    // Bulk actions
    const startAllBtn = document.getElementById('startAllBtn');
    if (startAllBtn) {
        startAllBtn.addEventListener('click', async () => {
            try {
                // Récupérer les options du formulaire
                const formData = new FormData();
                formData.append('tts_model', document.getElementById('tts_model').value);
                formData.append('language', document.getElementById('language').value);
                formData.append('voice_preset', document.getElementById('voice_preset').value);
                formData.append('speed', document.getElementById('speed').value);
                formData.append('pitch', document.getElementById('pitch').value);
                formData.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
                formData.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
                appendHiggsFields(formData);


                const response = await fetch(URLS.startAll, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData
                });

                if (response.ok) {
                    location.reload();
                } else {
                    const data = await response.json();
                    WamaApp.toast('Erreur: ' + (data.error || 'Échec du démarrage'), 'error');
                }
            } catch (error) {
                WamaApp.toast('Erreur: ' + error.message, 'error');
            }
        });
    }

    const downloadAllBtn = document.getElementById('downloadAllBtn');
    if (downloadAllBtn) {
        downloadAllBtn.addEventListener('click', () => {
            window.location.href = URLS.downloadAll;
        });
    }

    const clearAllBtn = document.getElementById('clearAllBtn');
    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', async () => {
            if (!confirm('Supprimer toutes les synthèses ?')) return;

            try {
                const response = await fetch(URLS.clearAll, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken }
                });

                if (response.ok) {
                    location.reload();
                } else {
                    WamaApp.toast('Erreur lors de la suppression', 'error');
                }
            } catch (error) {
                WamaApp.toast('Erreur: ' + error.message, 'error');
            }
        });
    }

    // Console toggle
    const toggleConsoleBtn = document.getElementById('toggleConsole');
    const consoleContainer = document.getElementById('consoleContainer');

    if (toggleConsoleBtn && consoleContainer) {
        toggleConsoleBtn.addEventListener('click', () => {
            if (consoleContainer.style.display === 'none') {
                consoleContainer.style.display = 'block';
                updateConsole();
            } else {
                consoleContainer.style.display = 'none';
            }
        });
    }

    // Auto-refresh progress
    setInterval(async () => {
        const runningCards = document.querySelectorAll('.synthesis-card.processing');

        for (const card of runningCards) {
            const id = card.dataset.id;
            try {
                const response = await fetch(URLS.progress + id + '/');
                const data = await response.json();

                // Update progress bar
                const progressBar = card.querySelector('.wama-progress-fill');
                const progressText = card.querySelector('.progress-text');
                if (progressBar) {
                    progressBar.style.width = data.progress + '%';
                    progressBar.classList.add('active');
                }
                if (progressText) progressText.textContent = data.progress + '%';
                if (window.WamaEta) WamaEta.render(card.querySelector('.wama-eta'), WamaEta.update(card.dataset.id, { progress: data.progress, status: data.status, seedSeconds: data.estimated_seconds, modelLoaded: false }));

                // Update card in-place on completion — no full page reload
                // (a full reload interrupts audio preview and reloads the slow FileManager)
                if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                    try {
                        const cardResp = await fetch(URLS.cardHtml + id + '/card/');
                        if (cardResp.ok) {
                            const html = await cardResp.text();
                            const temp = document.createElement('div');
                            temp.innerHTML = html.trim();
                            const newCard = temp.firstElementChild;
                            if (newCard) card.replaceWith(newCard);
                        }
                    } catch (fetchErr) {
                        console.error('[Synthesizer] Card refresh error:', fetchErr);
                    }
                    if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
                }
            } catch (error) {
                console.error('Progress update error:', error);
            }
        }
    }, 2000);

    // Auto-refresh global progress
    async function updateGlobalProgress() {
        return; // Neutralisé : barre globale + ETA pilotées par la brique commune wama-global-progress.js.
        try {
            const response = await fetch(URLS.globalProgress);
            const data = await response.json();

            const globalProgressBar = document.getElementById('globalProgressBar');
            const globalProgressText = document.getElementById('globalProgressText');
            const globalProgressStats = document.getElementById('globalProgressStats');
            const globalStatus = document.getElementById('globalStatus');

            const p = data.global_progress || 0;
            if (window.WamaEta) WamaEta.render(document.getElementById('globalEta'), WamaEta.aggregateAll());
            if (globalProgressBar) globalProgressBar.style.width = p + '%';
            if (globalProgressText) globalProgressText.textContent = p ? p + '%' : '';
            if (globalProgressStats) {
                globalProgressStats.textContent = `${data.completed}/${data.total} terminé · ${data.running} en cours${data.failed > 0 ? ` · ${data.failed} échoué` : ''}`;
            }
            if (globalStatus) {
                const active = (data.total || 0) > 0;
                globalStatus.style.opacity = active ? '1' : '0';
                globalStatus.style.pointerEvents = active ? '' : 'none';
            }
        } catch (error) {
            console.error('Global progress update error:', error);
        }
    }

    // Update global progress every 2 seconds
    updateGlobalProgress();
    setInterval(updateGlobalProgress, 2000);

    // Text input form submission
    const textInputForm = document.getElementById('textInputForm');
    if (textInputForm) {
        textInputForm.addEventListener('submit', async (e) => {
            e.preventDefault();

            const textContent = document.getElementById('textContent').value.trim();
            const title = document.getElementById('textTitle').value.trim();

            if (!textContent) {
                WamaApp.toast('Veuillez entrer du texte à synthétiser.', 'warning');
                return;
            }

            const submitBtn = document.getElementById('submitTextBtn');
            submitBtn.disabled = true;
            submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Ajout en cours...';

            try {
                const formData = new FormData();
                formData.append('text_content', textContent);
                formData.append('title', title);
                formData.append('tts_model', document.getElementById('tts_model').value);
                formData.append('language', document.getElementById('language').value);
                formData.append('voice_preset', document.getElementById('voice_preset').value);
                formData.append('speed', document.getElementById('speed').value);
                formData.append('pitch', document.getElementById('pitch').value);
                formData.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
                formData.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
                appendHiggsFields(formData);


                const response = await fetch(URLS.uploadText, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    WamaApp.toast(`Texte ajouté avec succès à la file d'attente !\nMots: ${data.word_count}`, 'success');
                    // Clear form
                    textInputForm.reset();
                    // Reload page to show new synthesis
                    location.reload();
                } else {
                    WamaApp.toast('Erreur: ' + (data.error || 'Échec de l\'ajout'), 'error');
                }
            } catch (error) {
                console.error('Text upload error:', error);
                WamaApp.toast('Erreur de communication: ' + error.message, 'error');
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-plus-circle"></i> Ajouter à la file d\'attente';
            }
        });
    }

    // ── Card « Nouvelle synthèse » : accordéon + voix/vitesse inline synchronisés au volet droit ──
    // Entrée progressive : le texte est l'entrée ; Entrée (ou saisie) déplie titre + voix + vitesse +
    // aperçu + ajouter. Voix/vitesse inline = miroirs des contrôles canoniques du volet droit
    // (#voice_preset / #speed) que le submit lit déjà → aucune modif du flux d'envoi.
    (function initNewSynthAccordion() {
        const textContent  = document.getElementById('textContent');
        const body         = document.getElementById('newSynthBody');
        const quickVoice   = document.getElementById('textVoiceQuick');
        const quickSpeed   = document.getElementById('textSpeedQuick');
        const quickSpeedVal = document.getElementById('textSpeedQuickVal');
        const voicePreset  = document.getElementById('voice_preset');
        const speed        = document.getElementById('speed');
        if (!textContent || !body) return;

        let expanded = false;
        function expand() {
            if (expanded) return;
            expanded = true;
            if (window.bootstrap && bootstrap.Collapse) {
                bootstrap.Collapse.getOrCreateInstance(body, { toggle: false }).show();
            } else {
                body.classList.add('show');
            }
        }
        function collapse() {
            if (!expanded) return;
            expanded = false;
            if (window.bootstrap && bootstrap.Collapse) {
                bootstrap.Collapse.getOrCreateInstance(body, { toggle: false }).hide();
            } else {
                body.classList.remove('show');
            }
        }
        // Entrée (sans Maj) déplie ; Maj+Entrée = nouvelle ligne (défaut)
        textContent.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                expand();
                if (quickVoice) quickVoice.focus();
            }
        });
        // Saisie déplie ; texte vidé → retour à l'état initial (champ texte seul)
        textContent.addEventListener('input', () => { textContent.value.trim() ? expand() : collapse(); });

        // Voix inline : cloner les options du volet droit (en retirant les id → pas de doublon)
        function cloneVoiceOptions() {
            if (!quickVoice || !voicePreset) return;
            quickVoice.innerHTML = voicePreset.innerHTML;
            quickVoice.querySelectorAll('[id]').forEach(el => el.removeAttribute('id'));
            quickVoice.value = voicePreset.value;
        }
        if (quickVoice && voicePreset) {
            cloneVoiceOptions();
            quickVoice.addEventListener('change', () => {
                voicePreset.value = quickVoice.value;
                voicePreset.dispatchEvent(new Event('change', { bubbles: true }));
            });
            voicePreset.addEventListener('change', () => {
                if (quickVoice.options.length !== voicePreset.options.length) cloneVoiceOptions();
                else quickVoice.value = voicePreset.value;
            });
        }
        // Vitesse inline ↔ volet droit
        if (quickSpeed && speed) {
            const setLabel = (v) => { if (quickSpeedVal) quickSpeedVal.textContent = parseFloat(v).toFixed(1); };
            quickSpeed.value = speed.value; setLabel(speed.value);
            quickSpeed.addEventListener('input', () => {
                speed.value = quickSpeed.value; setLabel(quickSpeed.value);
                speed.dispatchEvent(new Event('input', { bubbles: true }));
            });
            speed.addEventListener('input', () => { quickSpeed.value = speed.value; setLabel(speed.value); });
        }
    })();

    // Preview text button with streaming support
    const previewTextBtn = document.getElementById('previewTextBtn');
    let currentEventSource = null;

    if (previewTextBtn) {
        previewTextBtn.addEventListener('click', async () => {
            const textContent = document.getElementById('textContent').value.trim();

            if (!textContent) {
                WamaApp.toast('Veuillez entrer du texte pour générer un aperçu.', 'warning');
                return;
            }

            // Close any existing EventSource
            if (currentEventSource) {
                currentEventSource.close();
                currentEventSource = null;
            }

            const previewLoader = document.getElementById('previewLoader');
            const previewContainer = document.getElementById('previewAudioContainer');
            const previewProgress = document.getElementById('previewProgress');
            const previewStatus = document.getElementById('previewStatus');

            // Show loader, hide audio container
            previewLoader.style.display = 'block';
            previewContainer.style.display = 'none';

            // Reset progress
            previewProgress.style.width = '0%';
            previewProgress.textContent = '0%';
            previewStatus.textContent = 'Préparation...';

            // Disable preview button
            previewTextBtn.disabled = true;
            previewTextBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Génération...';

            try {
                // Step 1: Initialize the preview
                const formData = new FormData();
                formData.append('text_content', textContent);
                formData.append('tts_model', document.getElementById('tts_model').value);
                formData.append('language', document.getElementById('language').value);
                formData.append('voice_preset', document.getElementById('voice_preset').value);
                formData.append('speed', document.getElementById('speed').value);
                formData.append('pitch', document.getElementById('pitch').value);
                formData.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
                formData.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
                appendHiggsFields(formData);


                const response = await fetch(URLS.voicePreview, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData
                });

                const data = await response.json();

                if (!response.ok || !data.stream_url) {
                    throw new Error(data.error || 'Échec de l\'initialisation de l\'aperçu');
                }

                console.log('Preview initialized:', data);
                console.log('Stream URL:', data.stream_url);
                previewStatus.textContent = `Génération de ${data.word_count} mots...`;

                // Step 2: Connect to the streaming endpoint
                currentEventSource = new EventSource(data.stream_url);

                // Buffer pour collecter les chunks audio
                const audioChunks = [];
                const previewPlayer = document.getElementById('previewAudioPlayer');

                currentEventSource.onmessage = (event) => {
                    try {
                        const eventData = JSON.parse(event.data);
                        console.log('Stream event:', eventData);

                        switch (eventData.event) {
                            case 'start':
                                previewStatus.textContent = eventData.message;
                                previewProgress.style.width = '5%';
                                previewProgress.textContent = '5%';
                                break;

                            case 'info':
                                previewStatus.textContent = eventData.message;
                                break;

                            case 'progress':
                                const progress = eventData.progress || 0;
                                previewProgress.style.width = progress + '%';
                                previewProgress.textContent = progress + '%';
                                if (eventData.sentence) {
                                    previewStatus.textContent = `Génération: "${eventData.sentence.substring(0, 50)}..."`;
                                }
                                break;

                            case 'audio':
                                // Décoder et collecter le chunk audio base64
                                if (eventData.data) {
                                    audioChunks.push(eventData.data);
                                    previewStatus.textContent = `Réception de l'audio (${audioChunks.length} chunks)...`;
                                }
                                break;

                            case 'end':
                                previewProgress.style.width = '100%';
                                previewProgress.textContent = '100%';
                                previewStatus.textContent = 'Assemblage de l\'audio...';

                                // Assembler et jouer tous les chunks audio
                                if (audioChunks.length > 0) {
                                    assembleAndPlayAudio(audioChunks, previewPlayer, previewContainer, previewLoader);
                                } else {
                                    previewStatus.textContent = eventData.message;
                                    setTimeout(() => {
                                        previewLoader.style.display = 'none';
                                    }, 1000);
                                }

                                currentEventSource.close();
                                currentEventSource = null;
                                break;

                            case 'error':
                                console.error('Server error:', eventData.message);
                                if (eventData.details) {
                                    console.error('Error details:', eventData.details);
                                }
                                previewLoader.style.display = 'none';
                                WamaApp.toast('Erreur: ' + eventData.message, 'error');
                                if (currentEventSource) {
                                    currentEventSource.close();
                                    currentEventSource = null;
                                }
                                break;
                        }
                    } catch (parseError) {
                        console.error('Error parsing stream event:', parseError);
                        console.error('Raw event data:', event.data);
                    }
                };

                currentEventSource.onerror = (error) => {
                    console.error('EventSource error:', error);
                    console.error('EventSource readyState:', currentEventSource ? currentEventSource.readyState : 'null');
                    previewLoader.style.display = 'none';

                    // Show more detailed error information
                    const errorMsg = 'Erreur de streaming. Vérifiez la console pour plus de détails.';
                    WamaApp.toast(errorMsg, 'error');

                    if (currentEventSource) {
                        currentEventSource.close();
                        currentEventSource = null;
                    }
                };

            } catch (error) {
                console.error('Voice preview error:', error);
                WamaApp.toast('Erreur: ' + error.message, 'error');
                previewLoader.style.display = 'none';
            } finally {
                previewTextBtn.disabled = false;
                previewTextBtn.innerHTML = '<i class="fas fa-play-circle"></i> Preview';
            }
        });
    }

    // Function to assemble and play audio chunks
    async function assembleAndPlayAudio(base64Chunks, audioPlayer, containerElement, loaderElement) {
        try {
            console.log(`Assembling ${base64Chunks.length} audio chunks...`);

            // Décoder tous les chunks base64 en ArrayBuffer
            const audioBuffers = [];

            for (const base64Data of base64Chunks) {
                // Décoder base64
                const binaryString = atob(base64Data);
                const bytes = new Uint8Array(binaryString.length);
                for (let i = 0; i < binaryString.length; i++) {
                    bytes[i] = binaryString.charCodeAt(i);
                }
                audioBuffers.push(bytes.buffer);
            }

            console.log(`Decoded ${audioBuffers.length} chunks`);

            // Créer un blob avec tous les buffers WAV concaténés
            // Note: Pour une vraie concaténation WAV, il faudrait merger les headers
            // Pour simplifier, on va créer un blob avec le premier chunk (qui contient le header)
            // et ajouter uniquement les données audio des chunks suivants

            if (audioBuffers.length === 1) {
                // Un seul chunk, facile
                const blob = new Blob([audioBuffers[0]], { type: 'audio/wav' });
                const audioUrl = URL.createObjectURL(blob);

                audioPlayer.querySelector('source').src = audioUrl;
                audioPlayer.load();

                // Afficher le lecteur, masquer le loader
                loaderElement.style.display = 'none';
                containerElement.style.display = 'block';

                // Auto-play
                audioPlayer.play().catch(e => console.log('Autoplay prevented:', e));
            } else {
                // Plusieurs chunks - concaténation simple
                // ATTENTION: Ceci fonctionne mais n'est pas optimal pour WAV
                // car chaque chunk a son propre header
                const blob = new Blob(audioBuffers, { type: 'audio/wav' });
                const audioUrl = URL.createObjectURL(blob);

                audioPlayer.querySelector('source').src = audioUrl;
                audioPlayer.load();

                // Afficher le lecteur, masquer le loader
                loaderElement.style.display = 'none';
                containerElement.style.display = 'block';

                // Auto-play
                audioPlayer.play().catch(e => console.log('Autoplay prevented:', e));
            }

            console.log('Audio assembled and ready to play');

        } catch (error) {
            console.error('Error assembling audio:', error);
            WamaApp.toast('Erreur lors de l\'assemblage de l\'audio: ' + error.message, 'error');
            loaderElement.style.display = 'none';
        }
    }

    // Helper functions
    function escHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function handleFiles(files) {
        // Upload tous les fichiers, puis consolide en UN batch si plusieurs
        // (le serveur défait les batch-of-1 créés à l'upload). Un seul reload.
        const ids = [];
        for (const file of files) {
            const id = await uploadFile(file);
            if (id) ids.push(id);
        }
        if (ids.length > 1 && URLS.consolidate) {
            try {
                await fetch(URLS.consolidate, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                    body: JSON.stringify({ ids }),
                });
            } catch (_e) { /* à défaut : items individuels */ }
        }
        if (ids.length > 0) location.reload();
    }

    // ── Batch detection ───────────────────────────────────────────────────────
    // Detects if a file is a pipe-separated batch file before uploading.
    // For text-based formats (txt/md/csv): client-side analysis.
    // For binary formats (pdf/docx): server-side via batch_preview endpoint.

    let _batchFile = null;
    let _batchServerPath = null;  // used when file comes from FileManager (already on server)
    let _batchTasks = [];

    async function handleFilesWithDetect(files) {
        // Only intercept when dropping a single file
        if (files.length !== 1) {
            await handleFiles(files);
            return;
        }
        const file = files[0];
        const ext = file.name.split('.').pop().toLowerCase();

        if (['txt', 'md', 'csv', 'pdf', 'docx'].includes(ext)) {
            // Always use server-side detection (reliable for BOM, encoding, binary formats)
            try {
                const fd = new FormData();
                fd.append('batch_file', file);
                fd.append('default_voice', document.getElementById('voice_preset')?.value || 'default');
                fd.append('default_speed', document.getElementById('speed')?.value || '1.0');
                fd.append('csrfmiddlewaretoken', csrfToken);
                const resp = await fetch(URLS.batchPreview, { method: 'POST', body: fd });
                if (resp.ok) {
                    const data = await resp.json();
                    if (data.tasks && data.tasks.length >= 1) {
                        _showBatchBar(file, data.tasks, data.warnings || [], true);
                        return;
                    }
                }
            } catch (_e) { /* server error — treat as individual */ }
        }

        // No batch detected → regular individual upload
        await handleFiles([file]);
    }

    function _detectBatchLines(text) {
        const tasks = [];
        for (const line of text.split('\n')) {
            const l = line.trim();
            if (!l || l.startsWith('#')) continue;
            const parts = l.split('|').map(p => p.trim());
            if (parts.length >= 2 && parts[0] && parts[1]) {
                tasks.push({
                    output_filename: parts[0],
                    text: parts[1],
                    voice: parts[2] || '',
                    speed: parts[3] || '',
                });
            }
        }
        return tasks;
    }

    function _showBatchBar(file, tasks, warnings, alreadyParsed) {
        _batchFile = file;
        _batchTasks = tasks;
        const bar = document.getElementById('batchDetectBar');
        if (!bar) return;
        document.getElementById('batchDetectedCount').textContent = tasks.length;
        // If already parsed by server, show preview immediately
        if (alreadyParsed) {
            _populateBatchPreview(tasks, warnings || []);
            document.getElementById('batchDetectPreview').style.display = 'block';
        } else {
            document.getElementById('batchDetectPreview').style.display = 'none';
        }
        bar.style.display = 'block';
    }

    function _hideBatchBar() {
        _batchFile = null;
        _batchServerPath = null;
        _batchTasks = [];
        const bar = document.getElementById('batchDetectBar');
        if (bar) bar.style.display = 'none';
    }

    function _populateBatchPreview(tasks, warnings) {
        const warnEl = document.getElementById('batchDetectWarnings');
        if (warnEl) {
            if (warnings.length > 0) {
                warnEl.innerHTML = warnings.map(w => '⚠ ' + escHtml(w)).join('<br>');
                warnEl.style.display = 'block';
            } else {
                warnEl.style.display = 'none';
            }
        }
        const tbody = document.getElementById('batchDetectTable');
        if (tbody) {
            tbody.innerHTML = '';
            tasks.forEach(t => {
                const txt = t.text.length > 60 ? t.text.substring(0, 60) + '…' : t.text;
                const tr = document.createElement('tr');
                tr.innerHTML = `<td class="text-info">${escHtml(t.output_filename)}</td>
                    <td title="${escHtml(t.text)}">${escHtml(txt)}</td>
                    <td class="text-muted">${escHtml(t.voice || '—')}</td>
                    <td class="text-muted">${t.speed ? t.speed + 'x' : '—'}</td>`;
                tbody.appendChild(tr);
            });
        }
        const cnt = document.getElementById('batchCreateCount');
        if (cnt) cnt.textContent = tasks.length;
    }

    // "Mode batch" — calls server to get normalized parse then shows table
    const confirmBatchBtn = document.getElementById('batchConfirmBatchBtn');
    if (confirmBatchBtn) {
        confirmBatchBtn.addEventListener('click', async () => {
            if (!_batchFile) return;
            confirmBatchBtn.disabled = true;
            confirmBatchBtn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';
            try {
                const fd = new FormData();
                fd.append('batch_file', _batchFile);
                fd.append('default_voice', document.getElementById('voice_preset')?.value || 'default');
                fd.append('default_speed', document.getElementById('speed')?.value || '1.0');
                fd.append('csrfmiddlewaretoken', csrfToken);
                const resp = await fetch(URLS.batchPreview, { method: 'POST', body: fd });
                const data = await resp.json();
                if (!resp.ok) { WamaApp.toast(data.error || 'Erreur', 'error'); return; }
                _batchTasks = data.tasks;
                _populateBatchPreview(data.tasks, data.warnings || []);
                document.getElementById('batchDetectPreview').style.display = 'block';
            } finally {
                confirmBatchBtn.disabled = false;
                confirmBatchBtn.innerHTML = '<i class="fas fa-layer-group"></i> Voir le batch';
            }
        });
    }

    // "Synthèse individuelle" — ignore detection, upload normally
    const confirmIndividualBtn = document.getElementById('batchConfirmIndividualBtn');
    if (confirmIndividualBtn) {
        confirmIndividualBtn.addEventListener('click', async () => {
            const file = _batchFile;
            const serverPath = _batchServerPath;
            _hideBatchBar();
            if (file) {
                handleFiles([file]);
            } else if (serverPath) {
                // File already on server but VoiceSynthesis not yet created — create it now
                const fd = new FormData();
                fd.append('server_path', serverPath);
                fd.append('tts_model',    document.getElementById('tts_model')?.value    || 'xtts_v2');
                fd.append('language',     document.getElementById('language')?.value     || 'fr');
                fd.append('voice_preset', document.getElementById('voice_preset')?.value || 'default');
                fd.append('speed',        document.getElementById('speed')?.value        || '1.0');
                fd.append('pitch',        document.getElementById('pitch')?.value        || '1.0');
                fd.append('csrfmiddlewaretoken', csrfToken);
                try {
                    await fetch(URLS.importIndividualFromPath, { method: 'POST', body: fd });
                } catch (_e) { /* fall through */ }
                window.location.reload();
            }
        });
    }

    // "Annuler"
    const batchCancelBar = document.getElementById('batchCancelBar');
    if (batchCancelBar) batchCancelBar.addEventListener('click', _hideBatchBar);

    async function _doCreateBatch(andStart) {
        if (!_batchFile && !_batchServerPath) return;
        if (!_batchTasks.length) return;
        const progress = document.getElementById('batchCreateProgress');
        const btnStart = document.getElementById('batchCreateAndStartBtn');
        const btnOnly  = document.getElementById('batchCreateOnlyBtn');
        if (progress) progress.style.display = 'block';
        if (btnStart) btnStart.disabled = true;
        if (btnOnly)  btnOnly.disabled  = true;

        const fd = new FormData();
        if (_batchServerPath) {
            fd.append('server_path', _batchServerPath);
        } else {
            fd.append('batch_file', _batchFile);
        }
        fd.append('tts_model',    document.getElementById('tts_model')?.value    || 'xtts_v2');
        fd.append('language',     document.getElementById('language')?.value     || 'fr');
        fd.append('voice_preset', document.getElementById('voice_preset')?.value || 'default');
        fd.append('speed',        document.getElementById('speed')?.value        || '1.0');
        fd.append('pitch',        document.getElementById('pitch')?.value        || '1.0');
        fd.append('csrfmiddlewaretoken', csrfToken);

        try {
            const resp = await fetch(URLS.batchCreate, { method: 'POST', body: fd });
            const data = await resp.json();
            if (!resp.ok) { WamaApp.toast(data.error || 'Erreur création batch', 'error'); return; }

            if (andStart && data.batch_id) {
                await fetch(URLS.batchStart + data.batch_id + '/start/', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken, 'Content-Type': 'application/x-www-form-urlencoded' },
                    body: 'csrfmiddlewaretoken=' + encodeURIComponent(csrfToken),
                });
            }
            window.location.reload();
        } catch (err) {
            WamaApp.toast('Erreur : ' + err.message, 'error');
            if (progress) progress.style.display = 'none';
            if (btnStart) btnStart.disabled = false;
            if (btnOnly)  btnOnly.disabled  = false;
        }
    }

    const batchCreateAndStartBtn = document.getElementById('batchCreateAndStartBtn');
    if (batchCreateAndStartBtn) batchCreateAndStartBtn.addEventListener('click', () => _doCreateBatch(true));
    const batchCreateOnlyBtn = document.getElementById('batchCreateOnlyBtn');
    if (batchCreateOnlyBtn) batchCreateOnlyBtn.addEventListener('click', () => _doCreateBatch(false));
    // ─────────────────────────────────────────────────────────────────────────

    async function uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('tts_model', document.getElementById('tts_model').value);
        formData.append('language', document.getElementById('language').value);
        formData.append('voice_preset', document.getElementById('voice_preset').value);
        formData.append('speed', document.getElementById('speed').value);
        formData.append('pitch', document.getElementById('pitch').value);
        formData.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
        formData.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
        appendHiggsFields(formData);

        try {
            const response = await fetch(URLS.upload, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                // Ne PAS recharger ici : handleFiles consolide d'abord les
                // imports multiples en UN seul batch, puis recharge une fois.
                return data.id || null;
            } else {
                WamaApp.toast('Erreur: ' + (data.error || 'Upload échoué'), 'error');
                return null;
            }
        } catch (error) {
            console.error('Upload error:', error);
            WamaApp.toast('Erreur de communication: ' + error.message, 'error');
            return null;
        }
    }

    async function updateConsole() {
        try {
            const response = await fetch(URLS.console);
            const data = await response.json();

            const output = document.getElementById('consoleOutput');
            if (output && data.output) {
                output.innerHTML = data.output.map(line => `<div>${line}</div>`).join('');
                output.scrollTop = output.scrollHeight;
            }
        } catch (error) {
            console.error('Console update error:', error);
        }
    }

    // === Custom Voice Management ===
    const customVoiceModal = document.getElementById('customVoiceModal');
    const customVoiceModalInstance = customVoiceModal ? new bootstrap.Modal(customVoiceModal) : null;
    const customVoiceAudioInput = document.getElementById('customVoiceAudio');

    // Voice recording state
    let mediaRecorder = null;
    let audioChunks = [];
    let recordingStartTime = null;
    let recordingTimerInterval = null;

    let reopenSettingsAfterCustomVoice = false;

    function openCustomVoiceModal() {
        if (!customVoiceModalInstance) return;
        document.getElementById('customVoiceName').value = '';
        if (customVoiceAudioInput) customVoiceAudioInput.value = '';
        const resultDiv = document.getElementById('recordingResult');
        if (resultDiv) resultDiv.style.display = 'none';

        // If settings modal is open, hide it first and flag for reopen
        if (settingsModal && settingsModal.classList.contains('show')) {
            reopenSettingsAfterCustomVoice = true;
            settingsModalInstance.hide();
            settingsModal.addEventListener('hidden.bs.modal', function showCustomVoice() {
                settingsModal.removeEventListener('hidden.bs.modal', showCustomVoice);
                customVoiceModalInstance.show();
            }, { once: true });
        } else {
            reopenSettingsAfterCustomVoice = false;
            customVoiceModalInstance.show();
        }
    }

    // Reopen settings modal when custom voice modal closes
    if (customVoiceModal) {
        customVoiceModal.addEventListener('hidden.bs.modal', () => {
            if (reopenSettingsAfterCustomVoice && settingsModalInstance) {
                reopenSettingsAfterCustomVoice = false;
                settingsModalInstance.show();
            }
        });
    }

    // All "Ajouter une voix" buttons (panel + settings modal) use the same class
    document.querySelectorAll('.add-custom-voice-btn').forEach(btn => {
        btn.addEventListener('click', openCustomVoiceModal);
    });

    // Microphone recording inside the custom voice modal
    const recordVoiceBtn = document.getElementById('recordVoiceBtn');
    const stopRecordingBtn = document.getElementById('stopRecordingBtn');
    const recordingIndicator = document.getElementById('recordingIndicator');
    const recordingTimer = document.getElementById('recordingTimer');

    if (recordVoiceBtn) {
        recordVoiceBtn.addEventListener('click', async () => {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: { echoCancellation: true, noiseSuppression: true, sampleRate: 22050 }
                });

                mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' });
                audioChunks = [];

                mediaRecorder.ondataavailable = (e) => {
                    if (e.data.size > 0) audioChunks.push(e.data);
                };

                mediaRecorder.onstop = () => {
                    if (recordingTimerInterval) { clearInterval(recordingTimerInterval); recordingTimerInterval = null; }
                    stream.getTracks().forEach(track => track.stop());

                    const blob = new Blob(audioChunks, { type: 'audio/webm' });
                    const file = new File([blob], 'recorded_voice.webm', { type: 'audio/webm' });
                    const dt = new DataTransfer();
                    dt.items.add(file);
                    if (customVoiceAudioInput) customVoiceAudioInput.files = dt.files;

                    recordingIndicator.style.display = 'none';
                    recordVoiceBtn.disabled = false;

                    // Show confirmation
                    const resultDiv = document.getElementById('recordingResult');
                    const resultText = document.getElementById('recordingResultText');
                    if (resultDiv && resultText) {
                        resultText.textContent = `Enregistrement capturé (${recordingTimer.textContent})`;
                        resultDiv.style.display = 'block';
                    }
                };

                mediaRecorder.start();
                recordingStartTime = Date.now();
                recordingIndicator.style.display = 'block';
                recordVoiceBtn.disabled = true;
                const resultDiv = document.getElementById('recordingResult');
                if (resultDiv) resultDiv.style.display = 'none';

                recordingTimerInterval = setInterval(() => {
                    const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
                    recordingTimer.textContent = `${elapsed}s`;
                    if (elapsed >= 10 && stopRecordingBtn) stopRecordingBtn.click();
                }, 100);

            } catch (error) {
                console.error('Microphone access error:', error);
                WamaApp.toast(error.name === 'NotAllowedError'
                    ? 'Accès au microphone refusé. Veuillez autoriser l\'accès dans les paramètres du navigateur.'
                    : 'Erreur micro: ' + error.message, 'warning');
            }
        });
    }

    if (stopRecordingBtn) {
        stopRecordingBtn.addEventListener('click', () => {
            if (mediaRecorder && mediaRecorder.state === 'recording') mediaRecorder.stop();
        });
    }

    // Save custom voice
    const saveCustomVoiceBtn = document.getElementById('saveCustomVoiceBtn');
    if (saveCustomVoiceBtn) {
        saveCustomVoiceBtn.addEventListener('click', async () => {
            const name = document.getElementById('customVoiceName').value.trim();
            const audioFile = customVoiceAudioInput ? customVoiceAudioInput.files[0] : null;

            if (!name || !audioFile) {
                WamaApp.toast('Veuillez remplir le nom et sélectionner un fichier audio.', 'warning');
                return;
            }

            saveCustomVoiceBtn.disabled = true;
            saveCustomVoiceBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Envoi...';

            try {
                const formData = new FormData();
                formData.append('name', name);
                formData.append('audio', audioFile);

                const response = await fetch(URLS.uploadCustomVoice, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData
                });

                const data = await response.json();

                if (response.ok && data.id) {
                    // Add option to both dropdowns (ua_ = UserAsset)
                    const optionHtml = `<option value="ua_${data.id}">${data.name}</option>`;
                    addCustomVoiceOption('customVoicesGroup', optionHtml, 'voice_preset');
                    addCustomVoiceOption('settingsCustomVoicesGroup', optionHtml, 'settingsVoicePreset');

                    // Select the new voice in the panel dropdown
                    document.getElementById('voice_preset').value = `ua_${data.id}`;

                    if (customVoiceModalInstance) customVoiceModalInstance.hide();
                } else {
                    WamaApp.toast('Erreur: ' + (data.error || 'Échec de l\'enregistrement'), 'error');
                }
            } catch (error) {
                console.error('Custom voice upload error:', error);
                WamaApp.toast('Erreur: ' + error.message, 'error');
            } finally {
                saveCustomVoiceBtn.disabled = false;
                saveCustomVoiceBtn.innerHTML = '<i class="fas fa-save"></i> Enregistrer';
            }
        });
    }

    function addCustomVoiceOption(groupId, optionHtml, selectId) {
        let group = document.getElementById(groupId);
        if (!group) {
            // Create the optgroup if it doesn't exist yet
            const select = document.getElementById(selectId);
            if (!select) return;
            group = document.createElement('optgroup');
            group.id = groupId;
            group.label = 'Voix personnalisées (clonage)';
            // Insert after first optgroup (Voix intégrées)
            const firstGroup = select.querySelector('optgroup');
            if (firstGroup && firstGroup.nextSibling) {
                select.insertBefore(group, firstGroup.nextSibling);
            } else {
                select.appendChild(group);
            }
        }
        group.insertAdjacentHTML('beforeend', optionHtml);
    }

}); // Fin DOMContentLoaded
// Filemanager 'Envoyer vers...' — reload page to show imported item
document.addEventListener('wama:fileimported', function(e) {
    if (e.detail && e.detail.app === 'synthesizer') { window.location.reload(); }
});
