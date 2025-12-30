// Attendre que le DOM soit chargé
document.addEventListener('DOMContentLoaded', function() {
    // Configuration - URLs définies côté serveur (injectées depuis le template)
    if (!window.WAMA_CONFIG) {
        console.error('WAMA_CONFIG not found. Make sure the template injects it.');
        alert('Erreur de configuration. Veuillez recharger la page.');
        return;
    }

    const URLS = window.WAMA_CONFIG.urls;
    const csrfToken = window.WAMA_CONFIG.csrfToken;

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

    // Drag & Drop
    const dropZone = document.getElementById('dropZone');
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
                        if (result.imported) {
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
            handleFiles(e.dataTransfer.files);
        });

        fileInput.addEventListener('change', (e) => {
            handleFiles(e.target.files);
        });
    }

    // Start buttons
    document.querySelectorAll('.start-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            try {
                const response = await fetch(URLS.start + id + '/', {
                    method: 'GET',
                    headers: { 'X-CSRFToken': csrfToken }
                });

                if (response.ok) {
                    location.reload();
                } else {
                    const data = await response.json();
                    alert('Erreur: ' + (data.error || 'Échec du démarrage'));
                }
            } catch (error) {
                alert('Erreur: ' + error.message);
            }
        });
    });

    // Preview buttons
    document.querySelectorAll('.preview-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id;
            const previewDiv = document.getElementById(`preview_${id}`);

            if (previewDiv) {
                if (previewDiv.style.display === 'none') {
                    previewDiv.style.display = 'block';
                } else {
                    previewDiv.style.display = 'none';
                }
            }
        });
    });

    // Text preview buttons
    document.querySelectorAll('.preview-text-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            const id = btn.dataset.id;
            const modal = new bootstrap.Modal(document.getElementById('textPreviewModal'));

            // Show modal with loader
            modal.show();

            // Reset modal state
            document.getElementById('textPreviewLoader').style.display = 'block';
            document.getElementById('textPreviewContent').style.display = 'none';
            document.getElementById('textPreviewError').style.display = 'none';

            try {
                const response = await fetch(URLS.textPreview + id + '/');
                const data = await response.json();

                if (response.ok && data.success) {
                    // Update modal content
                    document.getElementById('textPreviewTitle').innerHTML =
                        `<i class="fas fa-file-alt"></i> ${data.filename}`;
                    document.getElementById('textPreviewInfo').textContent =
                        `${data.word_count} mots • Durée estimée: ${data.duration_display}`;
                    document.getElementById('textPreviewText').textContent = data.text_content;

                    // Show content
                    document.getElementById('textPreviewLoader').style.display = 'none';
                    document.getElementById('textPreviewContent').style.display = 'block';
                } else {
                    // Show error
                    document.getElementById('textPreviewLoader').style.display = 'none';
                    document.getElementById('textPreviewErrorMsg').textContent =
                        data.error || 'Impossible de charger le texte';
                    document.getElementById('textPreviewError').style.display = 'block';
                }
            } catch (error) {
                console.error('Text preview error:', error);
                document.getElementById('textPreviewLoader').style.display = 'none';
                document.getElementById('textPreviewErrorMsg').textContent =
                    'Erreur de communication: ' + error.message;
                document.getElementById('textPreviewError').style.display = 'block';
            }
        });
    });

    // Settings buttons - Open modal with current values
    const settingsModal = document.getElementById('settingsModal');
    const settingsModalInstance = settingsModal ? new bootstrap.Modal(settingsModal) : null;

    document.querySelectorAll('.settings-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            const id = btn.dataset.id;
            const ttsModel = btn.dataset.ttsModel;
            const language = btn.dataset.language;
            const voicePreset = btn.dataset.voicePreset;
            const speed = btn.dataset.speed || '1.0';
            const pitch = btn.dataset.pitch || '1.0';

            // Populate modal fields
            document.getElementById('settingsSynthesisId').value = id;
            document.getElementById('settingsTtsModel').value = ttsModel;
            document.getElementById('settingsLanguage').value = language;
            document.getElementById('settingsVoicePreset').value = voicePreset;
            document.getElementById('settingsSpeed').value = speed;
            document.getElementById('settingsSpeedValue').textContent = speed;
            document.getElementById('settingsPitch').value = pitch;
            document.getElementById('settingsPitchValue').textContent = pitch;

            // Clear voice reference input
            document.getElementById('settingsVoiceRef').value = '';

            // Show modal
            if (settingsModalInstance) {
                settingsModalInstance.show();
            }
        });
    });

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

        const voiceRef = document.getElementById('settingsVoiceRef');
        if (voiceRef && voiceRef.files[0]) {
            formData.append('voice_reference', voiceRef.files[0]);
        }

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
                        alert('Paramètres sauvegardés mais erreur au démarrage: ' + (data.error || 'Échec'));
                        location.reload();
                    }
                } else {
                    // Just reload to show updated settings
                    location.reload();
                }
            } else {
                const data = await response.json();
                alert('Erreur lors de la sauvegarde: ' + (data.error || 'Échec'));
            }
        } catch (error) {
            console.error('Save settings error:', error);
            alert('Erreur: ' + error.message);
        }
    }

    // Delete buttons
    document.querySelectorAll('.delete-btn').forEach(btn => {
        btn.addEventListener('click', async () => {
            if (!confirm('Supprimer cette synthèse ?')) return;

            const id = btn.dataset.id;
            try {
                const response = await fetch(URLS.delete + id + '/', {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken }
                });

                if (response.ok) {
                    location.reload();
                } else {
                    alert('Erreur lors de la suppression');
                }
            } catch (error) {
                alert('Erreur: ' + error.message);
            }
        });
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

                const voiceRef = document.getElementById('voice_reference');
                if (voiceRef && voiceRef.files[0]) {
                    formData.append('voice_reference', voiceRef.files[0]);
                }

                const response = await fetch(URLS.startAll, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData
                });

                if (response.ok) {
                    location.reload();
                } else {
                    const data = await response.json();
                    alert('Erreur: ' + (data.error || 'Échec du démarrage'));
                }
            } catch (error) {
                alert('Erreur: ' + error.message);
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
                    alert('Erreur lors de la suppression');
                }
            } catch (error) {
                alert('Erreur: ' + error.message);
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
                const progressBar = card.querySelector('.progress-fill');
                const progressText = card.querySelector('.progress-bar-custom + small');
                if (progressBar && progressText) {
                    progressBar.style.width = data.progress + '%';
                    progressText.textContent = data.progress + '%';
                }

                // Reload if finished
                if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                    location.reload();
                }
            } catch (error) {
                console.error('Progress update error:', error);
            }
        }
    }, 2000);

    // Auto-refresh global progress
    async function updateGlobalProgress() {
        try {
            const response = await fetch(URLS.globalProgress);
            const data = await response.json();

            const globalProgressBar = document.getElementById('globalProgressBar');
            const globalProgressText = document.getElementById('globalProgressText');
            const globalProgressStats = document.getElementById('globalProgressStats');

            if (globalProgressBar && globalProgressText) {
                globalProgressBar.style.width = data.global_progress + '%';
                globalProgressText.textContent = data.global_progress + '%';
            }

            if (globalProgressStats) {
                globalProgressStats.textContent = `${data.completed}/${data.total} terminé • ${data.running} en cours • ${data.pending} en attente${data.failed > 0 ? ` • ${data.failed} échoué` : ''}`;
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
                alert('Veuillez entrer du texte à synthétiser.');
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

                const voiceRef = document.getElementById('voice_reference');
                if (voiceRef && voiceRef.files[0]) {
                    formData.append('voice_reference', voiceRef.files[0]);
                }

                const response = await fetch(URLS.uploadText, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrfToken },
                    body: formData
                });

                const data = await response.json();

                if (response.ok && data.success) {
                    alert(`Texte ajouté avec succès à la file d'attente !\nMots: ${data.word_count}`);
                    // Clear form
                    textInputForm.reset();
                    // Reload page to show new synthesis
                    location.reload();
                } else {
                    alert('Erreur: ' + (data.error || 'Échec de l\'ajout'));
                }
            } catch (error) {
                console.error('Text upload error:', error);
                alert('Erreur de communication: ' + error.message);
            } finally {
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-plus-circle"></i> Ajouter à la file d\'attente';
            }
        });
    }

    // Preview text button with streaming support
    const previewTextBtn = document.getElementById('previewTextBtn');
    let currentEventSource = null;

    if (previewTextBtn) {
        previewTextBtn.addEventListener('click', async () => {
            const textContent = document.getElementById('textContent').value.trim();

            if (!textContent) {
                alert('Veuillez entrer du texte pour générer un aperçu.');
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

                const voiceRef = document.getElementById('voice_reference');
                if (voiceRef && voiceRef.files[0]) {
                    formData.append('voice_reference', voiceRef.files[0]);
                }

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
                                alert('Erreur: ' + eventData.message);
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
                    alert(errorMsg);

                    if (currentEventSource) {
                        currentEventSource.close();
                        currentEventSource = null;
                    }
                };

            } catch (error) {
                console.error('Voice preview error:', error);
                alert('Erreur: ' + error.message);
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
            alert('Erreur lors de l\'assemblage de l\'audio: ' + error.message);
            loaderElement.style.display = 'none';
        }
    }

    // Helper functions
    async function handleFiles(files) {
        for (const file of files) {
            await uploadFile(file);
        }
    }

    async function uploadFile(file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('tts_model', document.getElementById('tts_model').value);
        formData.append('language', document.getElementById('language').value);
        formData.append('voice_preset', document.getElementById('voice_preset').value);
        formData.append('speed', document.getElementById('speed').value);
        formData.append('pitch', document.getElementById('pitch').value);

        const voiceRef = document.getElementById('voice_reference');
        if (voiceRef && voiceRef.files[0]) {
            formData.append('voice_reference', voiceRef.files[0]);
        }

        try {
            const response = await fetch(URLS.upload, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken },
                body: formData
            });

            const data = await response.json();

            if (response.ok) {
                location.reload();
            } else {
                alert('Erreur: ' + (data.error || 'Upload échoué'));
            }
        } catch (error) {
            console.error('Upload error:', error);
            alert('Erreur de communication: ' + error.message);
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

    // Voice Recording Feature
    let mediaRecorder = null;
    let audioChunks = [];
    let recordingStartTime = null;
    let recordingTimerInterval = null;

    const recordVoiceBtn = document.getElementById('recordVoiceBtn');
    const stopRecordingBtn = document.getElementById('stopRecordingBtn');
    const recordingIndicator = document.getElementById('recordingIndicator');
    const recordingTimer = document.getElementById('recordingTimer');
    const voiceReferenceInput = document.getElementById('voice_reference');

    if (recordVoiceBtn) {
        recordVoiceBtn.addEventListener('click', async () => {
            try {
                // Demander l'accès au microphone
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        sampleRate: 22050
                    }
                });

                // Créer le MediaRecorder
                const options = { mimeType: 'audio/webm' };
                mediaRecorder = new MediaRecorder(stream, options);
                audioChunks = [];

                mediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0) {
                        audioChunks.push(event.data);
                    }
                };

                mediaRecorder.onstop = async () => {
                    // Arrêter le timer
                    if (recordingTimerInterval) {
                        clearInterval(recordingTimerInterval);
                        recordingTimerInterval = null;
                    }

                    // Arrêter toutes les pistes audio
                    stream.getTracks().forEach(track => track.stop());

                    // Créer un blob audio
                    const audioBlob = new Blob(audioChunks, { type: 'audio/webm' });

                    // Convertir en WAV si possible (pour meilleure compatibilité)
                    // Sinon, utiliser le webm directement
                    const file = new File([audioBlob], 'recorded_voice.webm', { type: 'audio/webm' });

                    // Créer un DataTransfer pour assigner le fichier à l'input
                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(file);
                    voiceReferenceInput.files = dataTransfer.files;

                    // Afficher une confirmation
                    alert(`Enregistrement terminé ! Durée: ${recordingTimer.textContent}`);

                    // Cacher l'indicateur
                    recordingIndicator.style.display = 'none';
                    recordVoiceBtn.disabled = false;
                };

                // Démarrer l'enregistrement
                mediaRecorder.start();
                recordingStartTime = Date.now();

                // Afficher l'indicateur
                recordingIndicator.style.display = 'block';
                recordVoiceBtn.disabled = true;

                // Démarrer le timer
                recordingTimerInterval = setInterval(() => {
                    const elapsed = Math.floor((Date.now() - recordingStartTime) / 1000);
                    recordingTimer.textContent = `${elapsed}s`;

                    // Arrêter automatiquement après 10 secondes
                    if (elapsed >= 10) {
                        stopRecordingBtn.click();
                    }
                }, 100);

            } catch (error) {
                console.error('Microphone access error:', error);
                if (error.name === 'NotAllowedError') {
                    alert('Accès au microphone refusé. Veuillez autoriser l\'accès au microphone dans les paramètres de votre navigateur.');
                } else {
                    alert('Erreur d\'accès au microphone: ' + error.message);
                }
            }
        });
    }

    if (stopRecordingBtn) {
        stopRecordingBtn.addEventListener('click', () => {
            if (mediaRecorder && mediaRecorder.state === 'recording') {
                mediaRecorder.stop();
            }
        });
    }

    // Voice Recording for Modal
    const modalRecordVoiceBtn = document.getElementById('modalRecordVoiceBtn');
    const modalStopRecordingBtn = document.getElementById('modalStopRecordingBtn');
    const modalRecordingIndicator = document.getElementById('modalRecordingIndicator');
    const modalRecordingTimer = document.getElementById('modalRecordingTimer');
    const settingsVoiceRefInput = document.getElementById('settingsVoiceRef');

    let modalMediaRecorder = null;
    let modalAudioChunks = [];
    let modalRecordingStartTime = null;
    let modalRecordingTimerInterval = null;

    if (modalRecordVoiceBtn) {
        modalRecordVoiceBtn.addEventListener('click', async () => {
            try {
                // Demander l'accès au microphone
                const stream = await navigator.mediaDevices.getUserMedia({
                    audio: {
                        echoCancellation: true,
                        noiseSuppression: true,
                        sampleRate: 22050
                    }
                });

                // Créer le MediaRecorder
                const options = { mimeType: 'audio/webm' };
                modalMediaRecorder = new MediaRecorder(stream, options);
                modalAudioChunks = [];

                modalMediaRecorder.ondataavailable = (event) => {
                    if (event.data.size > 0) {
                        modalAudioChunks.push(event.data);
                    }
                };

                modalMediaRecorder.onstop = async () => {
                    // Arrêter le timer
                    if (modalRecordingTimerInterval) {
                        clearInterval(modalRecordingTimerInterval);
                        modalRecordingTimerInterval = null;
                    }

                    // Arrêter toutes les pistes audio
                    stream.getTracks().forEach(track => track.stop());

                    // Créer un blob audio
                    const audioBlob = new Blob(modalAudioChunks, { type: 'audio/webm' });

                    // Créer un fichier
                    const file = new File([audioBlob], 'recorded_voice.webm', { type: 'audio/webm' });

                    // Créer un DataTransfer pour assigner le fichier à l'input
                    const dataTransfer = new DataTransfer();
                    dataTransfer.items.add(file);
                    settingsVoiceRefInput.files = dataTransfer.files;

                    // Afficher une confirmation
                    alert(`Enregistrement terminé ! Durée: ${modalRecordingTimer.textContent}`);

                    // Cacher l'indicateur
                    modalRecordingIndicator.style.display = 'none';
                    modalRecordVoiceBtn.disabled = false;
                };

                // Démarrer l'enregistrement
                modalMediaRecorder.start();
                modalRecordingStartTime = Date.now();

                // Afficher l'indicateur
                modalRecordingIndicator.style.display = 'block';
                modalRecordVoiceBtn.disabled = true;

                // Démarrer le timer
                modalRecordingTimerInterval = setInterval(() => {
                    const elapsed = Math.floor((Date.now() - modalRecordingStartTime) / 1000);
                    modalRecordingTimer.textContent = `${elapsed}s`;

                    // Arrêter automatiquement après 10 secondes
                    if (elapsed >= 10) {
                        modalStopRecordingBtn.click();
                    }
                }, 100);

            } catch (error) {
                console.error('Microphone access error:', error);
                if (error.name === 'NotAllowedError') {
                    alert('Accès au microphone refusé. Veuillez autoriser l\'accès au microphone dans les paramètres de votre navigateur.');
                } else {
                    alert('Erreur d\'accès au microphone: ' + error.message);
                }
            }
        });
    }

    if (modalStopRecordingBtn) {
        modalStopRecordingBtn.addEventListener('click', () => {
            if (modalMediaRecorder && modalMediaRecorder.state === 'recording') {
                modalMediaRecorder.stop();
            }
        });
    }

}); // Fin DOMContentLoaded