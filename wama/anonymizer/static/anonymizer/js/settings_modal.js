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
                booleans: data.booleans || [],
                sam3: data.sam3 || { use_sam3: false, prompt: '' },
                model: data.model || { current: '', global_default: '', choices: [] }
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

        // SAM3 data - status will be loaded asynchronously
        const sam3Data = settingsData.sam3 || { use_sam3: false, prompt: '' };
        const useSam3 = sam3Data.use_sam3;

        // Detection mode toggle section - SAM3 status badge will be updated asynchronously
        settingsHTML += `
            <div class="mb-4">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <label class="form-label fw-bold text-light mb-0">
                        <i class="fas fa-crosshairs me-2"></i>Mode de detection
                    </label>
                    <span class="badge bg-secondary" id="sam3_status_badge_${mediaId}">
                        <i class="fas fa-spinner fa-spin"></i> Verification...
                    </span>
                </div>
                <div class="btn-group w-100" role="group" aria-label="Detection mode">
                    <input type="radio" class="btn-check" name="detection_mode_${mediaId}" id="mode_yolo_${mediaId}" value="yolo"
                           ${!useSam3 ? 'checked' : ''} autocomplete="off">
                    <label class="btn btn-outline-primary" for="mode_yolo_${mediaId}">
                        <i class="fas fa-object-group me-1"></i>YOLO (Classes)
                    </label>
                    <input type="radio" class="btn-check" name="detection_mode_${mediaId}" id="mode_sam3_${mediaId}" value="sam3"
                           ${useSam3 ? 'checked' : ''} autocomplete="off">
                    <label class="btn btn-outline-info" for="mode_sam3_${mediaId}" id="sam3_label_${mediaId}">
                        <i class="fas fa-comment-dots me-1"></i>SAM3 (Prompt)
                    </label>
                </div>
            </div>
        `;

        // SAM3 prompt section (shown when SAM3 mode is selected)
        settingsHTML += `
            <div class="mb-4" id="sam3_section_${mediaId}" style="display: ${useSam3 ? 'block' : 'none'};">
                <div class="d-flex justify-content-between align-items-center mb-3">
                    <label class="form-label fw-bold text-light mb-0">
                        <i class="fas fa-comment-dots me-2"></i>Prompt SAM3
                    </label>
                </div>
                <div class="p-3 rounded" style="background-color: #1a1d20; border: 1px solid #495057;">
                    <textarea class="form-control bg-dark text-white border-secondary mb-2"
                              name="sam3_prompt"
                              id="sam3_prompt_${mediaId}"
                              rows="3"
                              placeholder="Decrivez ce que vous voulez flouter..."
                              maxlength="500">${sam3Data.prompt || ''}</textarea>
                    <div class="d-flex justify-content-between align-items-center">
                        <small class="text-white-50">Decrivez les objets a flouter en langage naturel</small>
                        <small class="text-white-50" id="sam3_prompt_count_${mediaId}">${(sam3Data.prompt || '').length}/500</small>
                    </div>
                    <div class="mt-2">
                        <button type="button" class="btn btn-sm btn-outline-secondary sam3-examples-btn" data-media-id="${mediaId}">
                            <i class="fas fa-lightbulb me-1"></i>Exemples
                        </button>
                        <div class="collapse mt-2" id="sam3_examples_${mediaId}">
                            <div class="list-group list-group-flush" id="sam3_examples_list_${mediaId}">
                                <div class="text-white-50 small p-2">Chargement...</div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;

        // YOLO section container (includes model selection and classes)
        settingsHTML += `<div id="yolo_section_${mediaId}" style="display: ${useSam3 ? 'none' : 'block'};">`;

        // Model selection dropdown (only shown in YOLO mode)
        const modelData = settingsData.model || { current: '', global_default: '', choices: [] };
        if (modelData.choices && modelData.choices.length > 0) {
            // Group choices by category
            const groupedChoices = {};
            modelData.choices.forEach(choice => {
                const group = choice.group || 'Other';
                if (!groupedChoices[group]) groupedChoices[group] = [];
                groupedChoices[group].push(choice);
            });

            settingsHTML += `
                <div class="mb-4">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <label class="form-label fw-bold text-light mb-0">
                            <i class="fas fa-cube me-2"></i>Modele YOLO
                        </label>
                        <small class="text-white-50">Defaut: ${modelData.global_default || 'Auto'}</small>
                    </div>
                    <div class="p-3 rounded" style="background-color: #1a1d20; border: 1px solid #495057;">
                        <select class="form-select bg-dark text-white border-secondary"
                                name="model_to_use" id="model_to_use_${mediaId}">
                            <option value="" ${!modelData.current ? 'selected' : ''}>
                                -- Utiliser le parametre global (${modelData.global_default || 'Auto'}) --
                            </option>
                            ${Object.entries(groupedChoices).map(([group, choices]) => `
                                <optgroup label="${group}">
                                    ${choices.map(choice => `
                                        <option value="${choice.value}" ${modelData.current === choice.value ? 'selected' : ''}>
                                            ${choice.label}
                                        </option>
                                    `).join('')}
                                </optgroup>
                            `).join('')}
                        </select>
                        <small class="text-white-50 d-block mt-2">
                            Selectionnez un modele specifique ou laissez vide pour utiliser le parametre global.
                        </small>
                    </div>
                </div>
            `;
        }

        // Classes2blur section
        if (settingsData.classes2blur && settingsData.classes2blur.length > 0) {
            settingsHTML += `
                <div class="mb-4">
                    <div class="d-flex justify-content-between align-items-center mb-3">
                        <label class="form-label fw-bold text-light mb-0">
                            <i class="fas fa-eye-slash me-2"></i>Objets a flouter
                        </label>
                        <small class="text-white-50">${settingsData.classes2blur.filter(c => c.checked).length} selectionne(s)</small>
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

        // Close YOLO section container
        settingsHTML += `</div>`;

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

        // Detection mode toggle (YOLO/SAM3)
        const yoloRadio = modal.querySelector(`#mode_yolo_${mediaId}`);
        const sam3Radio = modal.querySelector(`#mode_sam3_${mediaId}`);
        const yoloSection = modal.querySelector(`#yolo_section_${mediaId}`);
        const sam3Section = modal.querySelector(`#sam3_section_${mediaId}`);

        function toggleDetectionSections(mode) {
            if (mode === 'yolo') {
                if (yoloSection) yoloSection.style.display = 'block';
                if (sam3Section) sam3Section.style.display = 'none';
            } else {
                if (yoloSection) yoloSection.style.display = 'none';
                if (sam3Section) sam3Section.style.display = 'block';
            }
        }

        if (yoloRadio) {
            yoloRadio.addEventListener('change', function() {
                if (this.checked) toggleDetectionSections('yolo');
            });
        }
        if (sam3Radio) {
            sam3Radio.addEventListener('change', function() {
                if (this.checked) toggleDetectionSections('sam3');
            });
        }

        // SAM3 prompt character count
        const sam3Prompt = modal.querySelector(`#sam3_prompt_${mediaId}`);
        const sam3PromptCount = modal.querySelector(`#sam3_prompt_count_${mediaId}`);
        if (sam3Prompt && sam3PromptCount) {
            sam3Prompt.addEventListener('input', function() {
                sam3PromptCount.textContent = this.value.length + '/500';
            });
        }

        // SAM3 examples button - load examples on first click
        const sam3ExamplesBtn = modal.querySelector('.sam3-examples-btn');
        if (sam3ExamplesBtn) {
            let examplesLoaded = false;
            sam3ExamplesBtn.addEventListener('click', function() {
                const collapseEl = modal.querySelector(`#sam3_examples_${mediaId}`);
                if (collapseEl) {
                    collapseEl.classList.toggle('show');
                    // Load examples only once
                    if (!examplesLoaded) {
                        examplesLoaded = true;
                        loadSam3Examples(mediaId);
                    }
                }
            });
        }

        // Fetch SAM3 status asynchronously (doesn't block modal display)
        fetchSam3StatusAsync(mediaId);
    }

    // Async SAM3 status check - runs in background after modal is shown
    function fetchSam3StatusAsync(mediaId) {
        const statusBadge = document.getElementById(`sam3_status_badge_${mediaId}`);
        const sam3Radio = document.getElementById(`mode_sam3_${mediaId}`);
        const sam3Label = document.getElementById(`sam3_label_${mediaId}`);

        fetch('/anonymizer/sam3/status/')
            .then(response => response.json())
            .then(data => {
                if (statusBadge) {
                    if (data.ready) {
                        statusBadge.className = 'badge bg-success';
                        statusBadge.innerHTML = '<i class="fas fa-check-circle"></i> SAM3 disponible';
                        if (sam3Radio) sam3Radio.disabled = false;
                        if (sam3Label) sam3Label.classList.remove('disabled');
                    } else if (data.installed && !data.hf_authenticated) {
                        statusBadge.className = 'badge bg-warning text-dark';
                        statusBadge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Token HF requis';
                        if (sam3Radio) sam3Radio.disabled = true;
                        if (sam3Label) sam3Label.classList.add('disabled');
                    } else if (!data.installed) {
                        statusBadge.className = 'badge bg-danger';
                        statusBadge.innerHTML = '<i class="fas fa-times-circle"></i> SAM3 non installe';
                        if (sam3Radio) sam3Radio.disabled = true;
                        if (sam3Label) sam3Label.classList.add('disabled');
                    } else {
                        statusBadge.className = 'badge bg-secondary';
                        statusBadge.innerHTML = '<i class="fas fa-info-circle"></i> ' + (data.error || 'Etat inconnu');
                    }
                }
            })
            .catch(err => {
                console.error('[settings_modal.js] SAM3 status check failed:', err);
                if (statusBadge) {
                    statusBadge.className = 'badge bg-secondary';
                    statusBadge.innerHTML = '<i class="fas fa-question-circle"></i> Non verifie';
                }
            });
    }

    // Load SAM3 examples asynchronously
    function loadSam3Examples(mediaId) {
        const examplesList = document.getElementById(`sam3_examples_list_${mediaId}`);
        if (!examplesList) return;

        fetch('/anonymizer/sam3/examples/')
            .then(response => response.json())
            .then(data => {
                if (data.examples && data.examples.length > 0) {
                    examplesList.innerHTML = data.examples.map(ex => `
                        <a href="#" class="list-group-item list-group-item-action bg-dark text-light border-secondary py-2 px-3 sam3-example-item" data-prompt="${ex.prompt}" data-media-id="${mediaId}">
                            <strong>${ex.prompt}</strong><br>
                            <small class="text-white-50">${ex.description}</small>
                        </a>
                    `).join('');

                    // Bind click handlers for newly created example items
                    examplesList.querySelectorAll('.sam3-example-item').forEach(item => {
                        item.addEventListener('click', function(e) {
                            e.preventDefault();
                            const prompt = this.dataset.prompt;
                            const mid = this.dataset.mediaId;
                            const targetTextarea = document.getElementById(`sam3_prompt_${mid}`);
                            if (targetTextarea) {
                                targetTextarea.value = prompt;
                                const countEl = document.getElementById(`sam3_prompt_count_${mid}`);
                                if (countEl) {
                                    countEl.textContent = prompt.length + '/500';
                                }
                            }
                            // Collapse the examples
                            const collapseEl = document.getElementById(`sam3_examples_${mid}`);
                            if (collapseEl) {
                                collapseEl.classList.remove('show');
                            }
                        });
                    });
                } else {
                    examplesList.innerHTML = '<div class="text-white-50 small p-2">Aucun exemple disponible</div>';
                }
            })
            .catch(err => {
                console.error('[settings_modal.js] Failed to load SAM3 examples:', err);
                examplesList.innerHTML = '<div class="text-danger small p-2">Erreur de chargement</div>';
            });
    }

    function saveMediaSettings(mediaId, andRestart) {
        console.log(`[settings_modal.js] Saving settings for media ${mediaId}, restart=${andRestart}`);

        const modal = document.getElementById(`settingsModal${mediaId}`);
        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', getCsrfToken());
        formData.append('media_id', mediaId);

        // Collect detection mode (YOLO or SAM3)
        const sam3Radio = modal.querySelector(`#mode_sam3_${mediaId}`);
        const useSam3 = sam3Radio && sam3Radio.checked;
        formData.append('use_sam3', useSam3 ? 'true' : 'false');

        // Collect SAM3 prompt
        const sam3Prompt = modal.querySelector(`#sam3_prompt_${mediaId}`);
        if (sam3Prompt) {
            formData.append('sam3_prompt', sam3Prompt.value || '');
        }

        // Collect all form values from modal
        modal.querySelectorAll('input[type="checkbox"]').forEach(input => {
            if (input.name === 'classes2blur') {
                if (input.checked) {
                    formData.append(input.name, input.value);
                }
            } else if (!input.name.startsWith('detection_mode_')) {
                // Skip detection_mode radio buttons, they're handled separately
                formData.append(input.name, input.checked ? 'true' : 'false');
            }
        });

        modal.querySelectorAll('input[type="range"]').forEach(input => {
            formData.append(input.name, input.value);
        });

        // Collect select values (model_to_use)
        modal.querySelectorAll('select').forEach(select => {
            if (select.name) {
                formData.append(select.name, select.value);
            }
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
                console.log('[settings_modal.js] Settings reset successfully, refreshing modal...');

                // Fetch new settings and update modal dynamically
                fetch(`/anonymizer/get_media_settings/${mediaId}/`, {
                    method: 'GET',
                    headers: {
                        'X-CSRFToken': getCsrfToken(),
                        'Content-Type': 'application/json',
                    },
                })
                .then(response => response.json())
                .then(newData => {
                    if (newData.success) {
                        updateModalWithSettings(mediaId, newData);
                        // Show success feedback
                        showResetSuccess(mediaId);
                    }
                })
                .catch(err => {
                    console.error('[settings_modal.js] Error fetching new settings:', err);
                });
            } else {
                alert('Erreur lors de la reinitialisation: ' + (data.error || 'Erreur inconnue'));
            }
        })
        .catch(error => {
            console.error('[settings_modal.js] Error resetting settings:', error);
            alert('Erreur lors de la reinitialisation. Veuillez reessayer.');
        });
    }

    function updateModalWithSettings(mediaId, data) {
        const modal = document.getElementById(`settingsModal${mediaId}`);
        if (!modal) return;

        // Update detection mode (YOLO/SAM3)
        const sam3Data = data.sam3 || { use_sam3: false, prompt: '' };
        const yoloRadio = modal.querySelector(`#mode_yolo_${mediaId}`);
        const sam3Radio = modal.querySelector(`#mode_sam3_${mediaId}`);
        const yoloSection = modal.querySelector(`#yolo_section_${mediaId}`);
        const sam3Section = modal.querySelector(`#sam3_section_${mediaId}`);

        if (yoloRadio && sam3Radio) {
            if (sam3Data.use_sam3) {
                sam3Radio.checked = true;
                yoloRadio.checked = false;
                if (yoloSection) yoloSection.style.display = 'none';
                if (sam3Section) sam3Section.style.display = 'block';
            } else {
                yoloRadio.checked = true;
                sam3Radio.checked = false;
                if (yoloSection) yoloSection.style.display = 'block';
                if (sam3Section) sam3Section.style.display = 'none';
            }
        }

        // Update SAM3 prompt
        const sam3Prompt = modal.querySelector(`#sam3_prompt_${mediaId}`);
        if (sam3Prompt) {
            sam3Prompt.value = sam3Data.prompt || '';
            const countEl = modal.querySelector(`#sam3_prompt_count_${mediaId}`);
            if (countEl) countEl.textContent = (sam3Data.prompt || '').length + '/500';
        }

        // Update model selection
        const modelSelect = modal.querySelector(`#model_to_use_${mediaId}`);
        if (modelSelect && data.model) {
            modelSelect.value = data.model.current || '';
        }

        // Update classes checkboxes
        if (data.classes2blur) {
            data.classes2blur.forEach((cls, idx) => {
                const checkbox = modal.querySelector(`#classes2blur_${mediaId}_${idx}`);
                if (checkbox) {
                    checkbox.checked = cls.checked;
                }
            });
        }

        // Update sliders
        if (data.sliders) {
            data.sliders.forEach(slider => {
                const input = modal.querySelector(`input[name="${slider.name}"]`);
                if (input) {
                    input.value = slider.value;
                    // Update displayed value
                    const valueEl = modal.querySelector(`#value_${slider.name}_${mediaId}`);
                    if (valueEl) valueEl.textContent = slider.value;
                }
            });
        }

        // Update booleans
        if (data.booleans) {
            data.booleans.forEach(bool => {
                const checkbox = modal.querySelector(`input[name="${bool.name}"]`);
                if (checkbox) {
                    checkbox.checked = bool.value;
                }
            });
        }

        console.log('[settings_modal.js] Modal updated with new settings');
    }

    function showResetSuccess(mediaId) {
        const modal = document.getElementById(`settingsModal${mediaId}`);
        if (!modal) return;

        // Find or create success message element
        let successMsg = modal.querySelector('.reset-success-msg');
        if (!successMsg) {
            successMsg = document.createElement('div');
            successMsg.className = 'reset-success-msg alert alert-success mt-2';
            successMsg.style.cssText = 'position: absolute; top: 10px; right: 10px; z-index: 1050;';
            modal.querySelector('.modal-body')?.prepend(successMsg);
        }

        successMsg.innerHTML = '<i class="fas fa-check-circle me-2"></i>Parametres reinitialises!';
        successMsg.style.display = 'block';

        // Hide after 2 seconds
        setTimeout(() => {
            successMsg.style.display = 'none';
        }, 2000);
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

                // Reset progress bar to 0% immediately
                const tr = document.querySelector(`tr[data-media-id="${mediaId}"]`);
                if (tr) {
                    const progressBar = tr.querySelector('.progress-bar');
                    if (progressBar) {
                        progressBar.style.width = '0%';
                        progressBar.innerText = '0%';
                    }
                    // Update status badge
                    const statusBadge = tr.querySelector('td:nth-child(6) .badge');
                    if (statusBadge) {
                        statusBadge.className = 'badge bg-warning';
                        statusBadge.textContent = 'En cours';
                    }
                    tr.dataset.mediaProcessed = 'false';
                }

                // Start polling for this media's progress
                // This function is defined in process.js and exposed globally
                if (typeof window.startMediaProgressPolling === 'function') {
                    console.log(`[settings_modal.js] Starting progress polling for media ${mediaId}`);
                    window.startMediaProgressPolling(mediaId);
                } else {
                    console.warn('[settings_modal.js] startMediaProgressPolling not available, progress may not update');
                }

                if (typeof window.refreshMediaTable === 'function') {
                    window.refreshMediaTable();
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
