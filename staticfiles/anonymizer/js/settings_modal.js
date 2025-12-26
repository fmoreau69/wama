/**
 * Anonymizer Settings Modal Handler
 * Manages settings modal, restart, and delete actions for media items
 */

document.addEventListener('DOMContentLoaded', function() {
    console.log('[settings_modal.js] Initializing...');

    // CSRF token helper
    function getCsrfToken() {
        return document.querySelector('input[name="csrfmiddlewaretoken"]')?.value ||
               document.querySelector('[name=csrfmiddlewaretoken]')?.value;
    }

    /* ============================
     * Settings Modal Management
     * ============================ */

    function createSettingsModal(mediaId) {
        console.log(`[settings_modal.js] Creating settings modal for media ${mediaId}`);

        // Check if modal already exists
        const existingModal = document.getElementById(`settingsModal${mediaId}`);
        if (existingModal) {
            const bsModal = bootstrap.Modal.getInstance(existingModal) || new bootstrap.Modal(existingModal);
            bsModal.show();
            return;
        }

        // Fetch media settings from server
        fetch(`/anonymizer/get_media_settings/${mediaId}/`, {
            method: 'GET',
            headers: {
                'X-CSRFToken': getCsrfToken(),
                'Content-Type': 'application/json',
            },
        })
        .then(response => {
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            return response.json();
        })
        .then(data => {
            console.log('[settings_modal.js] Received settings:', data);

            if (!data.success) {
                throw new Error(data.error || 'Failed to load settings');
            }

            // Build modal HTML with the received data
            const settingsData = {
                classes2blur: data.classes2blur || [],
                sliders: data.sliders || [],
                booleans: data.booleans || []
            };

            const modal = buildModalHTML(mediaId, settingsData);
            document.body.appendChild(modal);

            // Initialize Bootstrap modal and show
            const bsModal = new bootstrap.Modal(modal);
            bsModal.show();

            // Bind save and reset handlers
            bindModalHandlers(mediaId);
        })
        .catch(error => {
            console.error('[settings_modal.js] Error fetching settings:', error);
            alert('Erreur lors du chargement des paramètres. Veuillez réessayer.');
        });
    }

    function buildModalHTML(mediaId, settingsData) {
        const modal = document.createElement('div');
        modal.className = 'modal fade';
        modal.id = `settingsModal${mediaId}`;
        modal.tabIndex = -1;

        // Build settings form HTML
        let settingsHTML = '';

        // Classes2blur section
        if (settingsData.classes2blur && settingsData.classes2blur.length > 0) {
            settingsHTML += `
                <div class="mb-4">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <label class="form-label fw-bold text-light mb-0">
                            <i class="fas fa-eye-slash me-2"></i>Objets à flouter
                        </label>
                        <small class="text-white-50">${settingsData.classes2blur.filter(c => c.checked).length} sélectionné(s)</small>
                    </div>
                    <div class="p-3 rounded" style="background-color: #1a1d20; border: 1px solid #495057; max-height: 300px; overflow-y: auto;">
                        <div class="row">
                            ${settingsData.classes2blur.map((cls, idx) => `
                                <div class="col-md-4 col-sm-6 mb-2">
                                    <div class="form-check">
                                        <input class="form-check-input" type="checkbox"
                                               name="classes2blur" value="${cls.value}"
                                               id="classes2blur_${mediaId}_${idx}"
                                               ${cls.checked ? 'checked' : ''}>
                                        <label class="form-check-label text-light small" for="classes2blur_${mediaId}_${idx}">
                                            ${cls.label}
                                        </label>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                </div>
            `;
        }

        // Slider settings
        if (settingsData.sliders && settingsData.sliders.length > 0) {
            settingsHTML += `
                <div class="mb-4">
                    <label class="form-label fw-bold text-light mb-3">
                        <i class="fas fa-sliders-h me-2"></i>Paramètres de floutage
                    </label>
                    <div class="p-3 rounded" style="background-color: #1a1d20; border: 1px solid #495057;">
                        <div class="row">
            `;
            settingsData.sliders.forEach(slider => {
                settingsHTML += `
                    <div class="col-md-6 mb-3">
                        <label class="form-label text-white">
                            ${slider.title}: <span class="text-info fw-bold" id="value_${slider.name}_${mediaId}">${slider.value}</span>
                        </label>
                        <input type="range" class="form-range"
                               name="${slider.name}"
                               id="${slider.name}_${mediaId}"
                               min="${slider.min}"
                               max="${slider.max}"
                               step="${slider.step}"
                               value="${slider.value}"
                               oninput="document.getElementById('value_${slider.name}_${mediaId}').textContent = this.value">
                        ${slider.description ? `<small class="text-white-50">${slider.description}</small>` : ''}
                    </div>
                `;
            });
            settingsHTML += '</div></div></div>';
        }

        // Boolean settings (checkboxes)
        if (settingsData.booleans && settingsData.booleans.length > 0) {
            settingsHTML += `
                <div class="mb-3">
                    <label class="form-label fw-bold text-light mb-3">
                        <i class="fas fa-eye me-2"></i>Options d'affichage
                    </label>
                    <div class="p-3 rounded" style="background-color: #1a1d20; border: 1px solid #495057;">
                        <div class="row">
            `;
            settingsData.booleans.forEach(bool => {
                settingsHTML += `
                    <div class="col-md-6 mb-2">
                        <div class="form-check form-switch">
                            <input class="form-check-input" type="checkbox"
                                   name="${bool.name}"
                                   id="${bool.name}_${mediaId}"
                                   ${bool.value ? 'checked' : ''}>
                            <label class="form-check-label text-white" for="${bool.name}_${mediaId}">
                                ${bool.title}
                            </label>
                        </div>
                    </div>
                `;
            });
            settingsHTML += '</div></div></div>';
        }

        modal.innerHTML = `
            <div class="modal-dialog modal-lg">
                <div class="modal-content" style="background-color: #212529; color: #fff; border: 1px solid #495057;">
                    <div class="modal-header" style="border-bottom: 1px solid #495057;">
                        <h5 class="modal-title text-white">
                            <i class="fas fa-cog me-2"></i>Paramètres du média #${mediaId}
                        </h5>
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body" style="background-color: #212529; max-height: 70vh; overflow-y: auto;">
                        ${settingsHTML}
                    </div>
                    <div class="modal-footer" style="border-top: 1px solid #495057;">
                        <button type="button" class="btn btn-secondary" data-bs-dismiss="modal">
                            <i class="fas fa-times me-1"></i>Fermer
                        </button>
                        <button type="button" class="btn btn-danger reset-settings-btn" data-media-id="${mediaId}">
                            <i class="fas fa-rotate-left me-1"></i>Réinitialiser
                        </button>
                        <button type="button" class="btn btn-primary save-settings-btn" data-media-id="${mediaId}">
                            <i class="fas fa-save me-1"></i>Sauvegarder
                        </button>
                        <button type="button" class="btn btn-success save-restart-btn" data-media-id="${mediaId}">
                            <i class="fas fa-play me-1"></i>Sauvegarder & Relancer
                        </button>
                    </div>
                </div>
            </div>
        `;

        return modal;
    }

    function bindModalHandlers(mediaId) {
        const modal = document.getElementById(`settingsModal${mediaId}`);
        if (!modal) return;

        // Save settings
        const saveBtn = modal.querySelector('.save-settings-btn');
        if (saveBtn) {
            saveBtn.addEventListener('click', () => saveMediaSettings(mediaId, false));
        }

        // Save and restart
        const saveRestartBtn = modal.querySelector('.save-restart-btn');
        if (saveRestartBtn) {
            saveRestartBtn.addEventListener('click', () => saveMediaSettings(mediaId, true));
        }

        // Reset settings
        const resetBtn = modal.querySelector('.reset-settings-btn');
        if (resetBtn) {
            resetBtn.addEventListener('click', () => resetMediaSettings(mediaId));
        }
    }

    function saveMediaSettings(mediaId, andRestart) {
        console.log(`[settings_modal.js] Saving settings for media ${mediaId}, restart=${andRestart}`);

        const modal = document.getElementById(`settingsModal${mediaId}`);
        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', getCsrfToken());
        formData.append('media_id', mediaId);

        // Collect all form values from modal
        modal.querySelectorAll('input[type="checkbox"]').forEach(input => {
            if (input.name === 'classes2blur') {
                if (input.checked) {
                    formData.append(input.name, input.value);
                }
            } else {
                formData.append(input.name, input.checked ? 'true' : 'false');
            }
        });

        modal.querySelectorAll('input[type="range"]').forEach(input => {
            formData.append(input.name, input.value);
        });

        // Save settings
        fetch('/anonymizer/save_media_settings/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
            body: formData,
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                console.log('[settings_modal.js] Settings saved successfully');

                // Close modal
                const bsModal = bootstrap.Modal.getInstance(modal);
                if (bsModal) bsModal.hide();

                // Restart if requested
                if (andRestart) {
                    restartMedia(mediaId);
                } else {
                    // Refresh the media table to show updated settings
                    if (typeof window.refreshMediaTable === 'function') {
                        window.refreshMediaTable();
                    } else {
                        location.reload();
                    }
                }
            } else {
                alert('Error saving settings: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('[settings_modal.js] Error saving settings:', error);
            alert('Error saving settings. Please try again.');
        });
    }

    function resetMediaSettings(mediaId) {
        if (!confirm('Reset all settings for this media to default values?')) {
            return;
        }

        console.log(`[settings_modal.js] Resetting settings for media ${mediaId}`);

        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', getCsrfToken());
        formData.append('media_id', mediaId);

        fetch('/anonymizer/reset_media_settings/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
            body: formData,
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                console.log('[settings_modal.js] Settings reset successfully');
                // Close modal and refresh media table
                const modal = document.getElementById(`settingsModal${mediaId}`);
                if (modal) {
                    const bsModal = bootstrap.Modal.getInstance(modal);
                    if (bsModal) bsModal.hide();
                }
                if (typeof window.refreshMediaTable === 'function') {
                    window.refreshMediaTable();
                } else {
                    location.reload();
                }
            } else {
                alert('Error resetting settings: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('[settings_modal.js] Error resetting settings:', error);
            alert('Error resetting settings. Please try again.');
        });
    }

    /* ============================
     * Restart Media
     * ============================ */

    function restartMedia(mediaId) {
        console.log(`[settings_modal.js] Restarting media ${mediaId}`);
        console.log(`[settings_modal.js] CSRF token: ${getCsrfToken()}`);

        if (!confirm('Start/restart processing for this media?')) {
            console.log('[settings_modal.js] User cancelled restart');
            return;
        }

        console.log('[settings_modal.js] User confirmed, preparing request...');

        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', getCsrfToken());
        formData.append('media_id', mediaId);

        console.log('[settings_modal.js] Sending POST request to /anonymizer/restart_media/');

        fetch('/anonymizer/restart_media/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
            body: formData,
        })
        .then(response => {
            console.log(`[settings_modal.js] Response status: ${response.status}`);
            return response.json();
        })
        .then(data => {
            console.log('[settings_modal.js] Response data:', data);
            if (data.success) {
                console.log('[settings_modal.js] Media restarted successfully');
                if (typeof window.refreshMediaTable === 'function') {
                    window.refreshMediaTable();
                } else {
                    location.reload();
                }
            } else {
                console.error('[settings_modal.js] Restart failed:', data.error);
                alert('Error restarting media: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('[settings_modal.js] Error restarting media:', error);
            alert('Error restarting media. Please try again.');
        });
    }

    /* ============================
     * Delete Media
     * ============================ */

    function deleteMedia(mediaId) {
        console.log(`[settings_modal.js] Deleting media ${mediaId}`);

        if (!confirm('Delete this media permanently?')) {
            return;
        }

        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', getCsrfToken());
        formData.append('media_id', mediaId);

        fetch('/anonymizer/clear_media/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrfToken(),
            },
            body: formData,
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                console.log('[settings_modal.js] Media deleted successfully');

                // Update UI dynamically using refreshMediaTable
                if (typeof window.refreshMediaTable === 'function') {
                    window.refreshMediaTable();
                    if (typeof window.updateQueueCount === 'function') {
                        window.updateQueueCount();
                    }
                    console.log('[settings_modal.js] UI updated dynamically');
                } else {
                    location.reload();
                }
            } else {
                alert('Error deleting media: ' + (data.error || 'Unknown error'));
            }
        })
        .catch(error => {
            console.error('[settings_modal.js] Error deleting media:', error);
            alert('Error deleting media. Please try again.');
        });
    }

    /* ============================
     * Event Listeners
     * ============================ */

    // Settings button click
    document.addEventListener('click', function(e) {
        const settingsBtn = e.target.closest('.settings-btn');
        if (settingsBtn) {
            e.preventDefault();
            const mediaId = settingsBtn.dataset.mediaId;
            createSettingsModal(mediaId);
        }
    });

    // Restart button click
    document.addEventListener('click', function(e) {
        const restartBtn = e.target.closest('.restart-btn');
        if (restartBtn) {
            e.preventDefault();
            const mediaId = restartBtn.dataset.mediaId;
            restartMedia(mediaId);
        }
    });

    // Delete button click
    document.addEventListener('click', function(e) {
        const deleteBtn = e.target.closest('.delete-btn');
        if (deleteBtn) {
            e.preventDefault();
            const mediaId = deleteBtn.dataset.mediaId;
            deleteMedia(mediaId);
        }
    });

    console.log('[settings_modal.js] Initialized successfully');
});
