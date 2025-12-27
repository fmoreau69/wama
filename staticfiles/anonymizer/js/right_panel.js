/**
 * Anonymizer Right Panel Handler
 * Manages SAM3/YOLO toggle, precision settings, classes selection, and HuggingFace configuration
 */

(function() {
    'use strict';

    // ========================================
    // Utility Functions
    // ========================================

    function getCsrfToken() {
        return document.querySelector('[name=csrfmiddlewaretoken]')?.value || '';
    }

    function debounce(func, wait) {
        let timeout;
        return function(...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    function saveUserSetting(settingName, value) {
        const data = new FormData();
        data.append('setting_type', 'user_setting');
        data.append('setting_name', settingName);
        data.append('input_value', value);
        data.append('csrfmiddlewaretoken', getCsrfToken());

        fetch('/anonymizer/update_settings/', {
            method: 'POST',
            body: data
        })
        .then(response => response.json())
        .then(result => {
            console.log('[right_panel.js] Setting saved:', settingName, '=', value, result);
        })
        .catch(err => {
            console.error('[right_panel.js] Failed to save setting:', err);
        });
    }

    // ========================================
    // Detection Mode (YOLO/SAM3) Toggle
    // ========================================

    function initDetectionModeToggle() {
        const yoloRadio = document.getElementById('detection_mode_yolo');
        const sam3Radio = document.getElementById('detection_mode_sam3');
        const yoloSection = document.getElementById('yolo_settings_section');
        const sam3Section = document.getElementById('sam3_settings_section');
        const sam3StatusIndicator = document.getElementById('sam3_status_indicator');

        function toggleDetectionMode(mode) {
            if (mode === 'yolo') {
                if (yoloSection) yoloSection.style.display = 'block';
                if (sam3Section) sam3Section.style.display = 'none';
                if (sam3StatusIndicator) sam3StatusIndicator.style.display = 'none';
                saveUserSetting('use_sam3', 'false');
            } else {
                if (yoloSection) yoloSection.style.display = 'none';
                if (sam3Section) sam3Section.style.display = 'block';
                if (sam3StatusIndicator) sam3StatusIndicator.style.display = 'block';
                checkSam3Status();
                saveUserSetting('use_sam3', 'true');
            }
        }

        if (yoloRadio) {
            yoloRadio.addEventListener('change', function() {
                if (this.checked) toggleDetectionMode('yolo');
            });
        }

        if (sam3Radio) {
            sam3Radio.addEventListener('change', function() {
                if (this.checked) toggleDetectionMode('sam3');
            });

            // Check SAM3 status on page load if SAM3 mode is selected
            if (sam3Radio.checked) {
                checkSam3Status();
            }
        }
    }

    // ========================================
    // SAM3 Status Check
    // ========================================

    function checkSam3Status() {
        const sam3StatusBadge = document.getElementById('sam3_status_badge');
        const hfConfigWarning = document.getElementById('hf_config_warning');

        if (!sam3StatusBadge) return;

        fetch('/anonymizer/sam3/status/')
            .then(response => response.json())
            .then(data => {
                if (data.ready) {
                    sam3StatusBadge.className = 'badge bg-success';
                    sam3StatusBadge.innerHTML = '<i class="fas fa-check-circle"></i> SAM3 pret';
                    if (hfConfigWarning) hfConfigWarning.style.display = 'none';
                } else if (data.installed && !data.hf_authenticated) {
                    sam3StatusBadge.className = 'badge bg-warning text-dark';
                    sam3StatusBadge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Config HF requise';
                    if (hfConfigWarning) hfConfigWarning.style.display = 'block';
                } else if (!data.installed) {
                    sam3StatusBadge.className = 'badge bg-danger';
                    sam3StatusBadge.innerHTML = '<i class="fas fa-times-circle"></i> SAM3 non installe';
                    if (hfConfigWarning) hfConfigWarning.style.display = 'none';
                } else {
                    sam3StatusBadge.className = 'badge bg-secondary';
                    sam3StatusBadge.innerHTML = '<i class="fas fa-info-circle"></i> ' + (data.error || 'Etat inconnu');
                }
            })
            .catch(err => {
                sam3StatusBadge.className = 'badge bg-secondary';
                sam3StatusBadge.innerHTML = '<i class="fas fa-question-circle"></i> Verification echouee';
                console.error('[right_panel.js] SAM3 status check failed:', err);
            });
    }

    // ========================================
    // SAM3 Prompt Handler
    // ========================================

    function initSam3Prompt() {
        const sam3PromptTextarea = document.getElementById('user_setting_sam3_prompt');
        const sam3PromptCount = document.getElementById('sam3_prompt_count');

        if (!sam3PromptTextarea) return;

        // Update character count
        function updatePromptCount() {
            if (sam3PromptCount) {
                sam3PromptCount.textContent = sam3PromptTextarea.value.length + '/500';
            }
        }

        // Debounced save for SAM3 prompt
        const debouncedSavePrompt = debounce(function(value) {
            saveUserSetting('sam3_prompt', value);
        }, 500);

        sam3PromptTextarea.addEventListener('input', function() {
            updatePromptCount();
            debouncedSavePrompt(this.value);
        });

        // Initial count
        updatePromptCount();
    }

    // ========================================
    // SAM3 Examples Handler
    // ========================================

    function initSam3Examples() {
        const sam3ExamplesBtn = document.getElementById('sam3_examples_btn');
        const sam3ExamplesCollapse = document.getElementById('sam3_examples_collapse');
        const sam3ExamplesList = document.getElementById('sam3_examples_list');
        const sam3PromptTextarea = document.getElementById('user_setting_sam3_prompt');

        if (!sam3ExamplesBtn || !sam3ExamplesList) return;

        function loadSam3Examples() {
            fetch('/anonymizer/sam3/examples/')
                .then(response => response.json())
                .then(data => {
                    sam3ExamplesList.innerHTML = '';
                    if (data.examples && data.examples.length > 0) {
                        data.examples.forEach(example => {
                            const item = document.createElement('a');
                            item.href = '#';
                            item.className = 'list-group-item list-group-item-action bg-dark text-light border-secondary py-1 px-2';
                            item.innerHTML = '<small><strong>' + example.prompt + '</strong><br><span class="text-white-50">' + example.description + '</span></small>';
                            item.addEventListener('click', function(e) {
                                e.preventDefault();
                                if (sam3PromptTextarea) {
                                    sam3PromptTextarea.value = example.prompt;
                                    sam3PromptTextarea.dispatchEvent(new Event('input'));
                                }
                                if (sam3ExamplesCollapse) {
                                    sam3ExamplesCollapse.classList.remove('show');
                                }
                            });
                            sam3ExamplesList.appendChild(item);
                        });
                    }
                })
                .catch(err => {
                    console.error('[right_panel.js] Failed to load SAM3 examples:', err);
                });
        }

        sam3ExamplesBtn.addEventListener('click', function() {
            const isExpanded = sam3ExamplesCollapse && sam3ExamplesCollapse.classList.contains('show');
            if (!isExpanded) {
                loadSam3Examples();
            }
            if (sam3ExamplesCollapse) {
                sam3ExamplesCollapse.classList.toggle('show');
            }
        });
    }

    // ========================================
    // Precision Label Handler
    // ========================================

    function initPrecisionLabel() {
        const slider = document.getElementById('user_setting_precision_level');
        const label = document.getElementById('precision_label_rp');

        if (!slider || !label) return;

        function updatePrecisionLabel() {
            const value = parseInt(slider.value);
            if (value <= 20) {
                label.textContent = 'Quick';
                label.className = 'text-success';
            } else if (value <= 40) {
                label.textContent = 'Balanced Quick';
                label.className = 'text-info';
            } else if (value <= 60) {
                label.textContent = 'Balanced';
                label.className = 'text-primary';
            } else if (value <= 80) {
                label.textContent = 'Balanced Precise';
                label.className = 'text-warning';
            } else {
                label.textContent = 'Max Precision';
                label.className = 'text-danger';
            }
        }

        slider.addEventListener('input', updatePrecisionLabel);
        updatePrecisionLabel(); // Initial update
    }

    // ========================================
    // Classes Selection Modal Handler
    // ========================================

    function initClassesModal() {
        const checkboxes = document.querySelectorAll('.classes2blur-checkbox');
        const countEl = document.getElementById('classes2blur_count');

        if (!checkboxes.length) return;

        function updateCount() {
            const checked = document.querySelectorAll('.classes2blur-checkbox:checked').length;
            if (countEl) {
                countEl.textContent = checked + ' classe(s) selectionnee(s)';
            }
        }

        function saveClass(className, isChecked) {
            saveUserSetting('classes2blur_' + className, isChecked ? 'true' : 'false');
        }

        checkboxes.forEach(function(cb) {
            cb.addEventListener('change', function() {
                updateCount();
                saveClass(this.value, this.checked);
            });
        });

        // Initial count
        updateCount();
    }

    // ========================================
    // HuggingFace Token Configuration
    // ========================================

    function initHfTokenConfig() {
        const hfSaveBtn = document.getElementById('hf_config_save_btn');
        const hfTokenInput = document.getElementById('hf_token_input');
        const hfConfigResult = document.getElementById('hf_config_result');

        if (!hfSaveBtn || !hfTokenInput) return;

        hfSaveBtn.addEventListener('click', function() {
            const token = hfTokenInput.value.trim();

            if (!token) {
                if (hfConfigResult) {
                    hfConfigResult.className = 'alert alert-warning';
                    hfConfigResult.textContent = 'Veuillez entrer un token.';
                    hfConfigResult.classList.remove('d-none');
                }
                return;
            }

            hfSaveBtn.disabled = true;
            hfSaveBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Enregistrement...';

            const formData = new FormData();
            formData.append('hf_token', token);
            formData.append('csrfmiddlewaretoken', getCsrfToken());

            fetch('/anonymizer/sam3/configure-hf/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                },
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    if (hfConfigResult) {
                        hfConfigResult.className = 'alert alert-success';
                        hfConfigResult.textContent = 'Token configure avec succes!';
                        hfConfigResult.classList.remove('d-none');
                    }

                    // Update status badge
                    const sam3StatusBadge = document.getElementById('sam3_status_badge');
                    if (sam3StatusBadge) {
                        sam3StatusBadge.className = 'badge bg-success';
                        sam3StatusBadge.innerHTML = '<i class="fas fa-check-circle"></i> SAM3 pret';
                    }

                    // Hide warning
                    const hfConfigWarning = document.getElementById('hf_config_warning');
                    if (hfConfigWarning) {
                        hfConfigWarning.style.display = 'none';
                    }

                    // Close modal after 1.5s
                    setTimeout(function() {
                        const modalEl = document.getElementById('modal_hf_config');
                        if (modalEl && typeof bootstrap !== 'undefined') {
                            const modal = bootstrap.Modal.getInstance(modalEl);
                            if (modal) modal.hide();
                        }
                    }, 1500);
                } else {
                    if (hfConfigResult) {
                        hfConfigResult.className = 'alert alert-danger';
                        hfConfigResult.textContent = data.error || 'Erreur lors de la configuration.';
                        hfConfigResult.classList.remove('d-none');
                    }
                }
            })
            .catch(err => {
                if (hfConfigResult) {
                    hfConfigResult.className = 'alert alert-danger';
                    hfConfigResult.textContent = 'Erreur de connexion.';
                    hfConfigResult.classList.remove('d-none');
                }
                console.error('[right_panel.js] HF config error:', err);
            })
            .finally(function() {
                hfSaveBtn.disabled = false;
                hfSaveBtn.innerHTML = '<i class="fas fa-save me-1"></i>Enregistrer';
            });
        });
    }

    // ========================================
    // Move Modals to Body Level (for z-index fix)
    // ========================================

    function fixModalZIndex() {
        document.querySelectorAll('[id^="modal_classes2blur"]').forEach(function(modal) {
            if (modal.parentElement !== document.body) {
                document.body.appendChild(modal);
            }
        });
    }

    // ========================================
    // Initialize All Handlers
    // ========================================

    function init() {
        console.log('[right_panel.js] Initializing...');

        initDetectionModeToggle();
        initSam3Prompt();
        initSam3Examples();
        initPrecisionLabel();
        initClassesModal();
        initHfTokenConfig();
        fixModalZIndex();

        console.log('[right_panel.js] Initialized successfully');
    }

    // Initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    // Re-initialize after AJAX content updates
    window.reinitializeRightPanel = function() {
        initClassesModal();
        fixModalZIndex();
    };

})();
