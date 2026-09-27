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

    // Widgets du volet HORS schéma (mode YOLO/SAM3, classes) : ils règlent les défauts de
    // l'utilisateur (brique `user_settings`, 2026-09-27 — ex-`update_settings/` par champ).
    function saveUserSetting(settingName, value) {
        if (!window.AnonQueue || !window.AnonQueue.saveUserSettings) return;
        window.AnonQueue.saveUserSettings({ [settingName]: value })
            .catch(err => console.error('[right_panel.js] Failed to save setting:', err));
    }

    // Le switch de mode (Classes / Description) est la brique commune WamaModes, qui porte le
    // réglage `target_mode` et affiche les sections du mode (2026-09-27) : ex-`initDetectionModeToggle`
    // (radios YOLO/SAM3, sections basculées ici, préférence écrite ici) retiré.

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

        // L'enregistrement du prompt est celui de tout réglage du schéma (`.setting-button`,
        // update.js) : il suit ce que le volet inspecte.
        sam3PromptTextarea.addEventListener('input', updatePromptCount);

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
    // Precision Label — RETIRÉ (rallié au curseur COMMUN, 2026-09-02)
    // ========================================
    // L'étiquette Quick/Balanced/… (anglais, 5 libellés locaux) est remplacée par les
    // zones du partial commun _intent_slider.html (Rapide/Équilibré/Qualité tricolores),
    // mises à jour par la liaison DÉLÉGUÉE de wama-params.js — plus rien à faire ici.

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

        // La LISTE entière est envoyée : le serveur la garde telle quelle.
        function saveClasses() {
            const checked = Array.from(document.querySelectorAll('.classes2blur-checkbox:checked'))
                .map(cb => cb.value);
            saveUserSetting('classes2blur', Array.from(new Set(checked)));
        }

        checkboxes.forEach(function(cb) {
            cb.addEventListener('change', function() {
                updateCount();
                saveClasses();
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
    // Reset Global Settings Handler
    // ========================================

    function initResetGlobalSettings() {
        const resetBtn = document.getElementById('reset-global-settings-btn');
        if (!resetBtn) return;

        resetBtn.addEventListener('click', function() {
            console.log('[right_panel.js] Resetting global settings...');

            // Show loading state
            const originalContent = resetBtn.innerHTML;
            resetBtn.disabled = true;
            resetBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Reset...';

            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', getCsrfToken());

            fetch('/anonymizer/reset_user_settings/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': getCsrfToken()
                },
                body: formData
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    console.log('[right_panel.js] Global settings reset successfully');
                    // Refresh settings dynamically
                    refreshGlobalSettings(data.settings);
                    showResetSuccessMessage();
                } else {
                    console.error('[right_panel.js] Reset failed:', data.error);
                    WamaApp.toast('Erreur: ' + (data.error || 'Erreur inconnue'), 'error');
                }
            })
            .catch(err => {
                console.error('[right_panel.js] Reset error:', err);
                WamaApp.toast('Erreur lors de la reinitialisation', 'error');
            })
            .finally(function() {
                resetBtn.disabled = false;
                resetBtn.innerHTML = originalContent;
            });
        });
    }

    function refreshGlobalSettings(settings) {
        if (!settings) return;
        // Les réglages du SCHÉMA (mode compris) : l'applicateur de l'inspecteur commun, qui
        // connaît chaque champ du volet — plus de recopie champ par champ ici.
        if (window._anonInspector && window._anonInspector.apply) window._anonInspector.apply(settings);
        // Classes à flouter : hors schéma (cases de la modale des classes).
        if (settings.classes2blur) {
            document.querySelectorAll('.classes2blur-checkbox').forEach(function(cb) {
                cb.checked = settings.classes2blur.includes(cb.value);
            });
            const countEl = document.getElementById('classes2blur_count');
            if (countEl) {
                const checked = document.querySelectorAll('.classes2blur-checkbox:checked').length;
                countEl.textContent = checked + ' classe(s) selectionnee(s)';
            }
        }
    }

    function showResetSuccessMessage() {
        // Create or find success message
        let successMsg = document.getElementById('reset-success-msg');
        if (!successMsg) {
            successMsg = document.createElement('div');
            successMsg.id = 'reset-success-msg';
            successMsg.className = 'alert alert-success py-1 px-2 mt-2';
            successMsg.style.fontSize = '0.85rem';
            const resetBtn = document.getElementById('reset-global-settings-btn');
            if (resetBtn && resetBtn.parentNode) {
                resetBtn.parentNode.insertBefore(successMsg, resetBtn.nextSibling);
            }
        }

        successMsg.innerHTML = '<i class="fas fa-check-circle me-1"></i>Parametres reinitialises!';
        successMsg.style.display = 'block';

        setTimeout(function() {
            successMsg.style.display = 'none';
        }, 2000);
    }

    // ========================================
    // Initialize All Handlers
    // ========================================

    function init() {
        console.log('[right_panel.js] Initializing...');

        checkSam3Status();
        initSam3Prompt();
        initSam3Examples();
        initClassesModal();
        initHfTokenConfig();
        initResetGlobalSettings();
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
