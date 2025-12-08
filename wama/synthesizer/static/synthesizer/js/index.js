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

        dropZone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropZone.classList.remove('drag-over');
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

}); // Fin DOMContentLoaded