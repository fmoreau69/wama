/**
 * WAMA Imager - Main JavaScript
 * Handles image generation UI and interactions
 */

(function() {
    'use strict';

    const config = window.IMAGER_CONFIG;
    let progressInterval = null;
    let reloadedGenerations = new Set(); // Track generations that already triggered a reload

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', function() {
        initializeEventListeners();
        startProgressPolling();
    });

    /**
     * Initialize all event listeners
     */
    function initializeEventListeners() {
        // Form submission
        const form = document.getElementById('generationForm');
        if (form) {
            form.addEventListener('submit', handleFormSubmit);
        }

        // Start all button
        const startAllBtn = document.getElementById('startAllBtn');
        if (startAllBtn) {
            startAllBtn.addEventListener('click', startAllGenerations);
        }

        // Clear all button
        const clearAllBtn = document.getElementById('clearAllBtn');
        if (clearAllBtn) {
            clearAllBtn.addEventListener('click', clearAllGenerations);
        }

        // Individual start buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.start-btn')) {
                const btn = e.target.closest('.start-btn');
                const genId = btn.getAttribute('data-id');
                startGeneration(genId);
            }
        });

        // Individual delete buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.delete-btn')) {
                const btn = e.target.closest('.delete-btn');
                const genId = btn.getAttribute('data-id');
                if (confirm('Delete this generation?')) {
                    deleteGeneration(genId);
                }
            }
        });

        // Settings buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.settings-btn')) {
                const btn = e.target.closest('.settings-btn');
                const genId = btn.getAttribute('data-id');
                openSettingsModal(genId);
            }
        });

        // Save settings button (save and start)
        const saveSettingsBtn = document.getElementById('saveSettingsBtn');
        if (saveSettingsBtn) {
            saveSettingsBtn.addEventListener('click', function() {
                saveSettings(true);
            });
        }

        // Save settings only button
        const saveSettingsOnlyBtn = document.getElementById('saveSettingsOnlyBtn');
        if (saveSettingsOnlyBtn) {
            saveSettingsOnlyBtn.addEventListener('click', function() {
                saveSettings(false);
            });
        }
    }

    /**
     * Handle form submission - create new generation
     */
    function handleFormSubmit(e) {
        e.preventDefault();

        const formData = new FormData(e.target);
        const submitBtn = document.getElementById('submitBtn');

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Adding...';

        fetch(config.urls.create, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            },
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Generation added to queue!', 'success');
                // Reload page to show new generation
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification('Error: ' + (data.error || 'Unknown error'), 'danger');
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-plus"></i> Add to Queue';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Error creating generation', 'danger');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-plus"></i> Add to Queue';
        });
    }

    /**
     * Start a specific generation
     */
    function startGeneration(genId) {
        const url = config.urls.start.replace('0', genId);

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken,
                'Content-Type': 'application/json'
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Generation started!', 'success');
                // Immediately update UI
                updateGenerationStatus(genId, 'RUNNING', 0);
            } else {
                showNotification('Error: ' + (data.error || 'Unknown error'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Error starting generation', 'danger');
        });
    }

    /**
     * Start all pending generations
     */
    function startAllGenerations() {
        const btn = document.getElementById('startAllBtn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Starting...';

        fetch(config.urls.startAll, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(`Started ${data.started} generation(s)!`, 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification('Error: ' + (data.error || 'Unknown error'), 'danger');
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-play"></i> Start All';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Error starting generations', 'danger');
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-play"></i> Start All';
        });
    }

    /**
     * Delete a specific generation
     */
    function deleteGeneration(genId) {
        const url = config.urls.delete.replace('0', genId);

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Generation deleted', 'success');
                // Remove from DOM
                const card = document.querySelector(`[data-id="${genId}"]`);
                if (card) {
                    card.remove();
                }
                updateQueueCount();
            } else {
                showNotification('Error: ' + (data.error || 'Unknown error'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Error deleting generation', 'danger');
        });
    }

    /**
     * Clear all generations
     */
    function clearAllGenerations() {
        if (!confirm('Delete ALL generations? This cannot be undone!')) {
            return;
        }

        fetch(config.urls.clearAll, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(`Deleted ${data.deleted} generation(s)`, 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification('Error: ' + (data.error || 'Unknown error'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Error clearing generations', 'danger');
        });
    }

    /**
     * Start polling for progress updates
     */
    function startProgressPolling() {
        // Poll every 2 seconds
        progressInterval = setInterval(() => {
            updateGlobalProgress();
            updateAllGenerationsProgress();
        }, 2000);
    }

    /**
     * Update global progress bar
     */
    function updateGlobalProgress() {
        fetch(config.urls.globalProgress)
            .then(response => response.json())
            .then(data => {
                const progressBar = document.getElementById('globalProgressBar');
                const statsText = document.getElementById('globalProgressStats');

                if (progressBar && statsText) {
                    const progress = data.overall_progress || 0;
                    progressBar.style.width = progress + '%';
                    progressBar.textContent = progress + '%';

                    statsText.textContent = `${data.success}/${data.total} completed • ${data.running} running • ${data.pending} pending`;

                    // Update progress bar color
                    progressBar.className = 'progress-bar';
                    if (data.failure > 0) {
                        progressBar.classList.add('bg-danger');
                    } else if (data.running > 0) {
                        progressBar.classList.add('bg-warning');
                    } else if (data.success === data.total && data.total > 0) {
                        progressBar.classList.add('bg-success');
                    }
                }
            })
            .catch(error => console.error('Error updating global progress:', error));
    }

    /**
     * Update progress for all running generations
     */
    function updateAllGenerationsProgress() {
        const cards = document.querySelectorAll('[data-id]');

        cards.forEach(card => {
            const genId = card.getAttribute('data-id');
            const url = config.urls.progress.replace('0', genId);

            fetch(url)
                .then(response => response.json())
                .then(data => {
                    updateGenerationCard(card, data);
                })
                .catch(error => console.error(`Error updating generation ${genId}:`, error));
        });
    }

    /**
     * Update a generation card with new data
     */
    function updateGenerationCard(card, data) {
        // Update status badge
        const badge = card.querySelector('.badge');
        if (badge) {
            badge.className = 'badge';
            badge.textContent = data.status;

            if (data.status === 'PENDING') badge.classList.add('bg-secondary');
            else if (data.status === 'RUNNING') badge.classList.add('bg-warning');
            else if (data.status === 'SUCCESS') badge.classList.add('bg-success');
            else if (data.status === 'FAILURE') badge.classList.add('bg-danger');
        }

        // Update progress bar
        const progressBar = card.querySelector('.progress-bar');
        if (progressBar) {
            progressBar.style.width = data.progress + '%';
            progressBar.textContent = data.progress + '%';
        }

        // Show/hide error message
        const errorEl = card.querySelector('.text-danger');
        if (data.error_message && !errorEl) {
            const statusCol = card.querySelector('.col-md-3');
            if (statusCol) {
                const errorHtml = `<small class="text-danger d-block mt-1">
                    <i class="fas fa-exclamation-triangle"></i> ${data.error_message.substring(0, 50)}
                </small>`;
                statusCol.insertAdjacentHTML('beforeend', errorHtml);
            }
        }

        // If just completed (status changed to SUCCESS), reload to show images
        // Only reload once per generation to avoid infinite loop
        const genId = card.getAttribute('data-id');
        const wasRunning = card.getAttribute('data-was-running') === 'true';

        if (data.status === 'RUNNING') {
            card.setAttribute('data-was-running', 'true');
        }

        if (data.status === 'SUCCESS' && wasRunning && !reloadedGenerations.has(genId)) {
            reloadedGenerations.add(genId);
            setTimeout(() => location.reload(), 1000);
        }
    }

    /**
     * Update generation status (helper function)
     */
    function updateGenerationStatus(genId, status, progress) {
        const card = document.querySelector(`[data-id="${genId}"]`);
        if (!card) return;

        const badge = card.querySelector('.badge');
        if (badge) {
            badge.className = 'badge';
            badge.textContent = status;

            if (status === 'PENDING') badge.classList.add('bg-secondary');
            else if (status === 'RUNNING') badge.classList.add('bg-warning');
            else if (status === 'SUCCESS') badge.classList.add('bg-success');
            else if (status === 'FAILURE') badge.classList.add('bg-danger');
        }

        const progressBar = card.querySelector('.progress-bar');
        if (progressBar) {
            progressBar.style.width = progress + '%';
            progressBar.textContent = progress + '%';
        }

        // Hide start button if running
        if (status === 'RUNNING') {
            const startBtn = card.querySelector('.start-btn');
            if (startBtn) startBtn.style.display = 'none';
        }
    }

    /**
     * Update queue count badge
     */
    function updateQueueCount() {
        const count = document.querySelectorAll('[data-id]').length;
        const badge = document.getElementById('queueCount');
        if (badge) {
            badge.textContent = count;
        }
    }

    /**
     * Show notification (Bootstrap toast or alert)
     */
    function showNotification(message, type = 'info') {
        // Simple alert for now - can be enhanced with Bootstrap toasts
        const alertDiv = document.createElement('div');
        alertDiv.className = `alert alert-${type} alert-dismissible fade show position-fixed top-0 start-50 translate-middle-x mt-3`;
        alertDiv.style.zIndex = '9999';
        alertDiv.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;

        document.body.appendChild(alertDiv);

        setTimeout(() => {
            alertDiv.remove();
        }, 5000);
    }

    /**
     * Open settings modal for a generation
     */
    function openSettingsModal(genId) {
        const url = config.urls.getSettings.replace('0', genId);

        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showNotification('Error: ' + data.error, 'danger');
                    return;
                }

                // Populate modal with data
                document.getElementById('modal_gen_id').textContent = data.id;
                document.getElementById('settings_gen_id').value = data.id;
                document.getElementById('settings_prompt').value = data.prompt || '';
                document.getElementById('settings_negative_prompt').value = data.negative_prompt || '';
                document.getElementById('settings_model').value = data.model || '';
                document.getElementById('settings_width').value = data.width || 512;
                document.getElementById('settings_height').value = data.height || 512;
                document.getElementById('settings_num_images').value = data.num_images || 1;

                // Steps
                const stepsEl = document.getElementById('settings_steps');
                stepsEl.value = data.steps || 30;
                document.getElementById('settings_steps_value').textContent = stepsEl.value;

                // Guidance scale
                const guidanceEl = document.getElementById('settings_guidance_scale');
                guidanceEl.value = data.guidance_scale || 7.5;
                document.getElementById('settings_guidance_value').textContent = guidanceEl.value;

                // Seed
                document.getElementById('settings_seed').value = data.seed || '';

                // Upscale
                document.getElementById('settings_upscale').checked = data.upscale || false;

                // Show modal
                const modal = new bootstrap.Modal(document.getElementById('generationSettingsModal'));
                modal.show();
            })
            .catch(error => {
                console.error('Error loading settings:', error);
                showNotification('Error loading settings', 'danger');
            });
    }

    /**
     * Save settings from modal
     */
    function saveSettings(andStart = false) {
        const genId = document.getElementById('settings_gen_id').value;
        const url = config.urls.saveSettings.replace('0', genId);

        const formData = new FormData();
        formData.append('prompt', document.getElementById('settings_prompt').value);
        formData.append('negative_prompt', document.getElementById('settings_negative_prompt').value);
        formData.append('model', document.getElementById('settings_model').value);
        formData.append('width', document.getElementById('settings_width').value);
        formData.append('height', document.getElementById('settings_height').value);
        formData.append('steps', document.getElementById('settings_steps').value);
        formData.append('guidance_scale', document.getElementById('settings_guidance_scale').value);
        formData.append('seed', document.getElementById('settings_seed').value);
        formData.append('num_images', document.getElementById('settings_num_images').value);
        formData.append('upscale', document.getElementById('settings_upscale').checked ? 'true' : 'false');

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            },
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Settings saved!', 'success');

                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('generationSettingsModal'));
                if (modal) modal.hide();

                if (andStart) {
                    // Start the generation
                    startGeneration(genId);
                } else {
                    // Refresh page to show updated settings
                    setTimeout(() => location.reload(), 500);
                }
            } else {
                showNotification('Error: ' + (data.error || 'Unknown error'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error saving settings:', error);
            showNotification('Error saving settings', 'danger');
        });
    }

})();
