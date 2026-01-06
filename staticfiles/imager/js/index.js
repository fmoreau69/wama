/**
 * WAMA Imager - Main JavaScript
 * Handles image and video generation UI and interactions
 * Supports multi-modal generation: txt2img, file2img, describe2img, style2img, img2img, txt2vid, img2vid
 */

(function() {
    'use strict';

    const config = window.IMAGER_CONFIG;
    let progressInterval = null;
    let reloadedGenerations = new Set(); // Track generations that already triggered a reload
    let currentMode = 'txt2img'; // Track current image generation mode
    let currentVideoMode = 'txt2vid'; // Track current video generation mode

    // Initialize on page load
    document.addEventListener('DOMContentLoaded', function() {
        initializeEventListeners();
        initializeModeSelector();
        initializeDropZones();
        initializeVideoTab();
        initializeTabPersistence();
        initializeRightPanelSync();
        initializeModelDescriptions();
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

        // Restart buttons (for SUCCESS or FAILURE generations)
        document.addEventListener('click', function(e) {
            if (e.target.closest('.restart-btn')) {
                const btn = e.target.closest('.restart-btn');
                const genId = btn.getAttribute('data-id');
                if (confirm('Relancer cette génération ?')) {
                    restartGeneration(genId);
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

        // Download all button
        const downloadAllBtn = document.getElementById('downloadAllBtn');
        if (downloadAllBtn) {
            downloadAllBtn.addEventListener('click', function() {
                window.location.href = config.urls.downloadAll;
            });
        }

        // Download individual buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.download-btn')) {
                const btn = e.target.closest('.download-btn');
                const genId = btn.getAttribute('data-id');
                window.location.href = config.urls.download.replace('0', genId);
            }
        });

        // Range sliders
        const stepsSlider = document.getElementById('steps');
        if (stepsSlider) {
            stepsSlider.addEventListener('input', function(e) {
                document.getElementById('steps_value').textContent = e.target.value;
            });
        }

        const guidanceSlider = document.getElementById('guidance_scale');
        if (guidanceSlider) {
            guidanceSlider.addEventListener('input', function(e) {
                document.getElementById('guidance_value').textContent = e.target.value;
            });
        }

        // Reset options button
        const resetBtn = document.getElementById('resetOptions');
        if (resetBtn) {
            resetBtn.addEventListener('click', function() {
                // Reset model to first option
                const modelSelect = document.getElementById('model');
                if (modelSelect) modelSelect.selectedIndex = 0;

                // Reset dimensions
                const widthSelect = document.getElementById('width');
                const heightSelect = document.getElementById('height');
                if (widthSelect) widthSelect.value = '512';
                if (heightSelect) heightSelect.value = '512';

                // Reset num images
                const numImagesSelect = document.getElementById('num_images');
                if (numImagesSelect) numImagesSelect.value = '1';

                // Reset sliders
                if (stepsSlider) {
                    stepsSlider.value = 30;
                    document.getElementById('steps_value').textContent = '30';
                }
                if (guidanceSlider) {
                    guidanceSlider.value = 7.5;
                    document.getElementById('guidance_value').textContent = '7.5';
                }

                // Reset seed
                const seedInput = document.getElementById('seed');
                if (seedInput) seedInput.value = '';

                // Reset upscale
                const upscaleCheck = document.getElementById('upscale');
                if (upscaleCheck) upscaleCheck.checked = false;
            });
        }

        // Image strength slider
        const imageStrengthSlider = document.getElementById('image_strength');
        if (imageStrengthSlider) {
            imageStrengthSlider.addEventListener('input', function(e) {
                document.getElementById('image_strength_value').textContent = e.target.value + '%';
            });
        }

        // Remove prompt file button
        const removePromptFileBtn = document.getElementById('removePromptFile');
        if (removePromptFileBtn) {
            removePromptFileBtn.addEventListener('click', function() {
                document.getElementById('promptFileInput').value = '';
                document.getElementById('promptFilePreview').classList.add('d-none');
            });
        }

        // ============ VIDEO TAB EVENT LISTENERS ============

        // Video start buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.video-start-btn')) {
                const btn = e.target.closest('.video-start-btn');
                const genId = btn.getAttribute('data-id');
                startGeneration(genId, true);
            }
        });

        // Video restart buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.video-restart-btn')) {
                const btn = e.target.closest('.video-restart-btn');
                const genId = btn.getAttribute('data-id');
                if (confirm('Relancer cette génération vidéo ?')) {
                    restartGeneration(genId, true);
                }
            }
        });

        // Video delete buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.video-delete-btn')) {
                const btn = e.target.closest('.video-delete-btn');
                const genId = btn.getAttribute('data-id');
                if (confirm('Supprimer cette génération vidéo ?')) {
                    deleteGeneration(genId, true);
                }
            }
        });

        // Video download buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.video-download-btn')) {
                const btn = e.target.closest('.video-download-btn');
                const genId = btn.getAttribute('data-id');
                window.location.href = config.urls.download.replace('0', genId);
            }
        });

        // Video settings buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.video-settings-btn')) {
                const btn = e.target.closest('.video-settings-btn');
                const genId = btn.getAttribute('data-id');
                openVideoSettingsModal(genId);
            }
        });

        // Save video settings button (save and start)
        const saveVideoSettingsBtn = document.getElementById('saveVideoSettingsBtn');
        if (saveVideoSettingsBtn) {
            saveVideoSettingsBtn.addEventListener('click', function() {
                saveVideoSettings(true);
            });
        }

        // Save video settings only button
        const saveVideoSettingsOnlyBtn = document.getElementById('saveVideoSettingsOnlyBtn');
        if (saveVideoSettingsOnlyBtn) {
            saveVideoSettingsOnlyBtn.addEventListener('click', function() {
                saveVideoSettings(false);
            });
        }
    }

    /**
     * Initialize generation mode selector
     */
    function initializeModeSelector() {
        const modeRadios = document.querySelectorAll('input[name="generation_mode"]');

        modeRadios.forEach(radio => {
            radio.addEventListener('change', function() {
                currentMode = this.value;
                updateModeVisibility();
            });
        });

        // Initialize with default mode
        updateModeVisibility();
    }

    /**
     * Update visibility of mode-specific sections
     */
    function updateModeVisibility() {
        // Hide all mode sections
        document.querySelectorAll('.mode-section').forEach(section => {
            section.style.display = 'none';
        });

        // Show appropriate section based on mode
        if (currentMode === 'txt2img') {
            document.getElementById('section_txt2img').style.display = 'block';
        } else if (currentMode === 'file2img') {
            document.getElementById('section_file2img').style.display = 'block';
        } else if (currentMode === 'describe2img') {
            document.getElementById('section_describe2img').style.display = 'block';
        } else if (currentMode === 'style2img' || currentMode === 'img2img') {
            document.getElementById('section_img2img').style.display = 'block';

            // Update prompt label based on mode
            const promptLabel = document.getElementById('img2img_prompt_required');
            if (promptLabel) {
                if (currentMode === 'style2img') {
                    promptLabel.textContent = '(optionnel)';
                    promptLabel.className = 'text-white-50';
                } else {
                    promptLabel.textContent = '(recommandé)';
                    promptLabel.className = 'text-warning';
                }
            }
        }
    }

    /**
     * Initialize drag-and-drop zones
     */
    function initializeDropZones() {
        // Prompt file drop zone
        setupDropZone('promptFileDropZone', 'promptFileInput', function(file) {
            document.getElementById('promptFileName').textContent = file.name;
            document.getElementById('promptFilePreview').classList.remove('d-none');
        });

        // Describe image drop zone
        setupDropZone('describeImageDropZone', 'describeImageInput', function(file) {
            previewImage(file, 'describeImagePreview');
        });

        // Reference image drop zone (for img2img/style2img)
        setupDropZone('referenceImageDropZone', 'referenceImageInput', function(file) {
            previewImage(file, 'referenceImagePreview');
        });

        // Video image drop zone (for img2vid)
        setupDropZone('videoImageDropZone', 'videoImageInput', function(file) {
            previewImage(file, 'videoImagePreview');
        });
    }

    /**
     * Initialize video tab functionality
     */
    function initializeVideoTab() {
        // Video form submission
        const videoForm = document.getElementById('videoGenerationForm');
        if (videoForm) {
            videoForm.addEventListener('submit', handleVideoFormSubmit);
        }

        // Video mode selector (txt2vid / img2vid)
        const videoModeRadios = document.querySelectorAll('input[name="video_generation_mode"]');
        videoModeRadios.forEach(radio => {
            radio.addEventListener('change', function() {
                currentVideoMode = this.value;
                updateVideoModeVisibility();
            });
        });

        // Video sliders
        const videoDurationSlider = document.getElementById('video_duration');
        if (videoDurationSlider) {
            videoDurationSlider.addEventListener('input', function(e) {
                document.getElementById('video_duration_value').textContent = e.target.value;
            });
        }

        const videoStepsSlider = document.getElementById('video_steps');
        if (videoStepsSlider) {
            videoStepsSlider.addEventListener('input', function(e) {
                document.getElementById('video_steps_value').textContent = e.target.value;
            });
        }

        const videoGuidanceSlider = document.getElementById('video_guidance_scale');
        if (videoGuidanceSlider) {
            videoGuidanceSlider.addEventListener('input', function(e) {
                document.getElementById('video_guidance_value').textContent = e.target.value;
            });
        }

        // Initialize visibility
        updateVideoModeVisibility();
    }

    /**
     * Update visibility of video mode sections
     */
    function updateVideoModeVisibility() {
        const txt2vidSection = document.getElementById('section_txt2vid');
        const img2vidSection = document.getElementById('section_img2vid');

        if (currentVideoMode === 'txt2vid') {
            if (txt2vidSection) txt2vidSection.style.display = 'block';
            if (img2vidSection) img2vidSection.style.display = 'none';
        } else if (currentVideoMode === 'img2vid') {
            if (txt2vidSection) txt2vidSection.style.display = 'none';
            if (img2vidSection) img2vidSection.style.display = 'block';
        }
    }

    /**
     * Initialize tab persistence - remember active tab across page reloads
     */
    function initializeTabPersistence() {
        const imageTab = document.getElementById('image-tab');
        const videoTab = document.getElementById('video-tab');
        const imageSettings = document.getElementById('imageSettings');
        const videoSettings = document.getElementById('videoSettings');

        // Restore active tab from localStorage
        const savedTab = localStorage.getItem('imager_active_tab');
        if (savedTab === 'video' && videoTab) {
            // Activate video tab
            const tab = new bootstrap.Tab(videoTab);
            tab.show();
            // Switch settings panel
            if (imageSettings) imageSettings.style.display = 'none';
            if (videoSettings) videoSettings.style.display = 'block';
        }

        // Save tab state when switching
        if (imageTab) {
            imageTab.addEventListener('shown.bs.tab', function() {
                localStorage.setItem('imager_active_tab', 'image');
                // Switch settings panel
                if (imageSettings) imageSettings.style.display = 'block';
                if (videoSettings) videoSettings.style.display = 'none';
            });
        }

        if (videoTab) {
            videoTab.addEventListener('shown.bs.tab', function() {
                localStorage.setItem('imager_active_tab', 'video');
                // Switch settings panel
                if (imageSettings) imageSettings.style.display = 'none';
                if (videoSettings) videoSettings.style.display = 'block';
            });
        }
    }

    /**
     * Initialize right panel sync - sync panel settings with form settings
     */
    function initializeRightPanelSync() {
        // Video panel sliders
        const panelVideoDuration = document.getElementById('panel_video_duration');
        const panelVideoSteps = document.getElementById('panel_video_steps');
        const panelVideoGuidance = document.getElementById('panel_video_guidance');

        // Sync panel duration with form
        if (panelVideoDuration) {
            panelVideoDuration.addEventListener('input', function(e) {
                document.getElementById('panel_video_duration_value').textContent = e.target.value;
                // Sync with main form
                const formDuration = document.getElementById('video_duration');
                if (formDuration) {
                    formDuration.value = e.target.value;
                    document.getElementById('video_duration_value').textContent = e.target.value;
                }
            });
        }

        // Sync panel steps with form
        if (panelVideoSteps) {
            panelVideoSteps.addEventListener('input', function(e) {
                document.getElementById('panel_video_steps_value').textContent = e.target.value;
                // Sync with main form
                const formSteps = document.getElementById('video_steps');
                if (formSteps) {
                    formSteps.value = e.target.value;
                    document.getElementById('video_steps_value').textContent = e.target.value;
                }
            });
        }

        // Sync panel guidance with form
        if (panelVideoGuidance) {
            panelVideoGuidance.addEventListener('input', function(e) {
                document.getElementById('panel_video_guidance_value').textContent = e.target.value;
                // Sync with main form
                const formGuidance = document.getElementById('video_guidance_scale');
                if (formGuidance) {
                    formGuidance.value = e.target.value;
                    document.getElementById('video_guidance_value').textContent = e.target.value;
                }
            });
        }

        // Sync panel selects with form
        const panelVideoModel = document.getElementById('panel_video_model');
        const panelVideoResolution = document.getElementById('panel_video_resolution');
        const panelVideoFps = document.getElementById('panel_video_fps');
        const panelVideoSeed = document.getElementById('panel_video_seed');

        if (panelVideoModel) {
            panelVideoModel.addEventListener('change', function(e) {
                const formModel = document.getElementById('video_model');
                if (formModel) formModel.value = e.target.value;
            });
        }

        if (panelVideoResolution) {
            panelVideoResolution.addEventListener('change', function(e) {
                const formResolution = document.getElementById('video_resolution');
                if (formResolution) formResolution.value = e.target.value;
            });
        }

        if (panelVideoFps) {
            panelVideoFps.addEventListener('change', function(e) {
                const formFps = document.getElementById('video_fps');
                if (formFps) formFps.value = e.target.value;
            });
        }

        if (panelVideoSeed) {
            panelVideoSeed.addEventListener('input', function(e) {
                const formSeed = document.getElementById('video_seed');
                if (formSeed) formSeed.value = e.target.value;
            });
        }

        // Reset video options button
        const resetVideoBtn = document.getElementById('resetVideoOptions');
        if (resetVideoBtn) {
            resetVideoBtn.addEventListener('click', function() {
                // Reset panel values
                if (panelVideoModel) panelVideoModel.selectedIndex = 0;
                if (panelVideoResolution) panelVideoResolution.value = '480p';
                if (panelVideoFps) panelVideoFps.value = '16';
                if (panelVideoSeed) panelVideoSeed.value = '';

                if (panelVideoDuration) {
                    panelVideoDuration.value = 5;
                    document.getElementById('panel_video_duration_value').textContent = '5';
                }
                if (panelVideoSteps) {
                    panelVideoSteps.value = 30;
                    document.getElementById('panel_video_steps_value').textContent = '30';
                }
                if (panelVideoGuidance) {
                    panelVideoGuidance.value = 5;
                    document.getElementById('panel_video_guidance_value').textContent = '5.0';
                }

                // Sync with main form
                const formModel = document.getElementById('video_model');
                const formResolution = document.getElementById('video_resolution');
                const formDuration = document.getElementById('video_duration');
                const formFps = document.getElementById('video_fps');
                const formSteps = document.getElementById('video_steps');
                const formGuidance = document.getElementById('video_guidance_scale');
                const formSeed = document.getElementById('video_seed');

                if (formModel) formModel.selectedIndex = 0;
                if (formResolution) formResolution.value = '480p';
                if (formDuration) {
                    formDuration.value = 5;
                    document.getElementById('video_duration_value').textContent = '5';
                }
                if (formFps) formFps.value = '16';
                if (formSteps) {
                    formSteps.value = 30;
                    document.getElementById('video_steps_value').textContent = '30';
                }
                if (formGuidance) {
                    formGuidance.value = 5;
                    document.getElementById('video_guidance_value').textContent = '5.0';
                }
                if (formSeed) formSeed.value = '';
            });
        }

        // Also sync form changes back to panel (bidirectional sync)
        const formVideoModel = document.getElementById('video_model');
        const formVideoResolution = document.getElementById('video_resolution');
        const formVideoDuration = document.getElementById('video_duration');
        const formVideoFps = document.getElementById('video_fps');
        const formVideoSteps = document.getElementById('video_steps');
        const formVideoGuidance = document.getElementById('video_guidance_scale');
        const formVideoSeed = document.getElementById('video_seed');

        if (formVideoModel) {
            formVideoModel.addEventListener('change', function(e) {
                if (panelVideoModel) panelVideoModel.value = e.target.value;
            });
        }

        if (formVideoResolution) {
            formVideoResolution.addEventListener('change', function(e) {
                if (panelVideoResolution) panelVideoResolution.value = e.target.value;
            });
        }

        if (formVideoDuration) {
            formVideoDuration.addEventListener('input', function(e) {
                if (panelVideoDuration) {
                    panelVideoDuration.value = e.target.value;
                    document.getElementById('panel_video_duration_value').textContent = e.target.value;
                }
            });
        }

        if (formVideoFps) {
            formVideoFps.addEventListener('change', function(e) {
                if (panelVideoFps) panelVideoFps.value = e.target.value;
            });
        }

        if (formVideoSteps) {
            formVideoSteps.addEventListener('input', function(e) {
                if (panelVideoSteps) {
                    panelVideoSteps.value = e.target.value;
                    document.getElementById('panel_video_steps_value').textContent = e.target.value;
                }
            });
        }

        if (formVideoGuidance) {
            formVideoGuidance.addEventListener('input', function(e) {
                if (panelVideoGuidance) {
                    panelVideoGuidance.value = e.target.value;
                    document.getElementById('panel_video_guidance_value').textContent = e.target.value;
                }
            });
        }

        if (formVideoSeed) {
            formVideoSeed.addEventListener('input', function(e) {
                if (panelVideoSeed) panelVideoSeed.value = e.target.value;
            });
        }
    }

    /**
     * Handle video form submission
     */
    function handleVideoFormSubmit(e) {
        e.preventDefault();

        const formData = new FormData();
        const submitBtn = document.getElementById('videoSubmitBtn');

        // Set generation mode
        formData.set('generation_mode', currentVideoMode);

        // Get video parameters
        const videoModel = document.getElementById('video_model');
        const videoResolution = document.getElementById('video_resolution');
        const videoDuration = document.getElementById('video_duration');
        const videoFps = document.getElementById('video_fps');
        const videoSteps = document.getElementById('video_steps');
        const videoGuidance = document.getElementById('video_guidance_scale');
        const videoSeed = document.getElementById('video_seed');

        if (videoModel) formData.set('model', videoModel.value);
        if (videoResolution) formData.set('video_resolution', videoResolution.value);
        if (videoDuration) formData.set('video_duration', videoDuration.value);
        if (videoFps) formData.set('video_fps', videoFps.value);
        if (videoSteps) formData.set('steps', videoSteps.value);
        if (videoGuidance) formData.set('guidance_scale', videoGuidance.value);
        if (videoSeed && videoSeed.value) formData.set('seed', videoSeed.value);

        // Mode-specific data
        if (currentVideoMode === 'txt2vid') {
            const prompt = document.getElementById('video_prompt');
            const negativePrompt = document.getElementById('video_negative_prompt');

            if (!prompt || !prompt.value.trim()) {
                showNotification('Le prompt est requis pour la génération vidéo', 'warning');
                return;
            }

            formData.set('prompt', prompt.value);
            if (negativePrompt && negativePrompt.value) {
                formData.set('negative_prompt', negativePrompt.value);
            }
        } else if (currentVideoMode === 'img2vid') {
            const videoImage = document.getElementById('videoImageInput');
            const prompt = document.getElementById('video_img2vid_prompt');
            const negativePrompt = document.getElementById('video_img2vid_negative_prompt');

            if (!videoImage || !videoImage.files[0]) {
                showNotification('Veuillez sélectionner une image de référence', 'warning');
                return;
            }

            if (!prompt || !prompt.value.trim()) {
                showNotification('Le prompt est requis pour décrire le mouvement', 'warning');
                return;
            }

            formData.set('reference_image', videoImage.files[0]);
            formData.set('prompt', prompt.value);
            if (negativePrompt && negativePrompt.value) {
                formData.set('negative_prompt', negativePrompt.value);
            }
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Ajout...';

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
                showNotification('Génération vidéo ajoutée à la file !', 'success');
                // Ensure video tab stays active after reload
                localStorage.setItem('imager_active_tab', 'video');
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification('Erreur : ' + (data.error || 'Erreur inconnue'), 'danger');
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-plus"></i> Ajouter à la file vidéo';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Erreur lors de la création de la génération vidéo', 'danger');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-plus"></i> Ajouter à la file vidéo';
        });
    }

    /**
     * Setup a drop zone for file uploads
     */
    function setupDropZone(dropZoneId, inputId, onFileSelected) {
        const dropZone = document.getElementById(dropZoneId);
        const fileInput = document.getElementById(inputId);

        if (!dropZone || !fileInput) return;

        // Prevent default drag behaviors
        ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, preventDefaults, false);
        });

        function preventDefaults(e) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Highlight drop zone when dragging over it
        ['dragenter', 'dragover'].forEach(eventName => {
            dropZone.addEventListener(eventName, function() {
                dropZone.classList.add('dragover');
            }, false);
        });

        ['dragleave', 'drop'].forEach(eventName => {
            dropZone.addEventListener(eventName, function() {
                dropZone.classList.remove('dragover');
            }, false);
        });

        // Handle dropped files
        dropZone.addEventListener('drop', function(e) {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                if (onFileSelected) onFileSelected(files[0]);
            }
        }, false);

        // Handle file input change
        fileInput.addEventListener('change', function() {
            if (this.files.length > 0) {
                if (onFileSelected) onFileSelected(this.files[0]);
            }
        });
    }

    /**
     * Preview an image file
     */
    function previewImage(file, previewId) {
        const preview = document.getElementById(previewId);
        if (!preview) return;

        const reader = new FileReader();
        reader.onload = function(e) {
            preview.src = e.target.result;
            preview.classList.remove('d-none');
        };
        reader.readAsDataURL(file);
    }

    /**
     * Handle form submission - create new generation
     * Handles all modes: txt2img, file2img, describe2img, style2img, img2img
     */
    function handleFormSubmit(e) {
        e.preventDefault();

        const formData = new FormData();
        const submitBtn = document.getElementById('submitBtn');

        // Set generation mode
        formData.set('generation_mode', currentMode);

        // Add parameters from right panel
        const model = document.getElementById('model');
        const width = document.getElementById('width');
        const height = document.getElementById('height');
        const numImages = document.getElementById('num_images');
        const steps = document.getElementById('steps');
        const guidanceScale = document.getElementById('guidance_scale');
        const seed = document.getElementById('seed');
        const upscale = document.getElementById('upscale');

        if (model) formData.set('model', model.value);
        if (width) formData.set('width', width.value);
        if (height) formData.set('height', height.value);
        if (numImages) formData.set('num_images', numImages.value);
        if (steps) formData.set('steps', steps.value);
        if (guidanceScale) formData.set('guidance_scale', guidanceScale.value);
        if (seed && seed.value) formData.set('seed', seed.value);
        if (upscale) formData.set('upscale', upscale.checked ? 'true' : 'false');

        // Mode-specific data
        if (currentMode === 'txt2img') {
            const prompt = document.getElementById('prompt');
            const negativePrompt = document.getElementById('negative_prompt');

            if (!prompt || !prompt.value.trim()) {
                showNotification('Le prompt est requis', 'warning');
                return;
            }

            formData.set('prompt', prompt.value);
            if (negativePrompt && negativePrompt.value) {
                formData.set('negative_prompt', negativePrompt.value);
            }
        }
        else if (currentMode === 'file2img') {
            const promptFile = document.getElementById('promptFileInput');

            if (!promptFile || !promptFile.files[0]) {
                showNotification('Veuillez sélectionner un fichier de prompts', 'warning');
                return;
            }

            formData.set('prompt_file', promptFile.files[0]);
        }
        else if (currentMode === 'describe2img') {
            const describeImage = document.getElementById('describeImageInput');
            const promptStyle = document.getElementById('prompt_style');

            if (!describeImage || !describeImage.files[0]) {
                showNotification('Veuillez sélectionner une image à décrire', 'warning');
                return;
            }

            formData.set('reference_image', describeImage.files[0]);
            if (promptStyle) formData.set('prompt_style', promptStyle.value);
        }
        else if (currentMode === 'style2img' || currentMode === 'img2img') {
            const referenceImage = document.getElementById('referenceImageInput');
            const img2imgPrompt = document.getElementById('img2img_prompt');
            const img2imgNegativePrompt = document.getElementById('img2img_negative_prompt');
            const imageStrength = document.getElementById('image_strength');

            if (!referenceImage || !referenceImage.files[0]) {
                showNotification('Veuillez sélectionner une image de référence', 'warning');
                return;
            }

            formData.set('reference_image', referenceImage.files[0]);
            if (img2imgPrompt && img2imgPrompt.value) {
                formData.set('prompt', img2imgPrompt.value);
            }
            if (img2imgNegativePrompt && img2imgNegativePrompt.value) {
                formData.set('negative_prompt', img2imgNegativePrompt.value);
            }
            if (imageStrength) {
                // Convert percentage (0-100) to decimal (0.0-1.0)
                formData.set('image_strength', imageStrength.value / 100);
            }
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Ajout...';

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
                let message = 'Génération ajoutée à la file !';
                if (currentMode === 'file2img' && data.count) {
                    message = `${data.count} génération(s) créée(s) depuis le fichier !`;
                } else if (currentMode === 'describe2img' && data.auto_prompt) {
                    message = `Prompt généré : "${data.auto_prompt.substring(0, 50)}..."`;
                }
                showNotification(message, 'success');
                // Reload page to show new generation
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification('Erreur : ' + (data.error || 'Erreur inconnue'), 'danger');
                submitBtn.disabled = false;
                submitBtn.innerHTML = '<i class="fas fa-plus"></i> Ajouter à la file';
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification('Erreur lors de la création', 'danger');
            submitBtn.disabled = false;
            submitBtn.innerHTML = '<i class="fas fa-plus"></i> Ajouter à la file';
        });
    }

    /**
     * Start a specific generation (image or video)
     */
    function startGeneration(genId, isVideo = false) {
        const url = config.urls.start.replace('0', genId);
        const type = isVideo ? 'vidéo' : 'image';

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
                showNotification(`Génération ${type} démarrée !`, 'success');
                // Immediately update UI
                updateGenerationStatus(genId, 'RUNNING', 0, isVideo);
            } else {
                showNotification('Erreur : ' + (data.error || 'Erreur inconnue'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification(`Erreur lors du démarrage de la génération ${type}`, 'danger');
        });
    }

    /**
     * Restart a completed or failed generation
     */
    function restartGeneration(genId, isVideo = false) {
        const url = config.urls.restart.replace('0', genId);
        const type = isVideo ? 'vidéo' : 'image';

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
                showNotification(`Génération ${type} relancée !`, 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification('Erreur : ' + (data.error || 'Erreur inconnue'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification(`Erreur lors du redémarrage de la génération ${type}`, 'danger');
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
     * Delete a specific generation (image or video)
     */
    function deleteGeneration(genId, isVideo = false) {
        const url = config.urls.delete.replace('0', genId);
        const type = isVideo ? 'vidéo' : 'image';

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification(`Génération ${type} supprimée`, 'success');
                // Remove from DOM - check in both queues
                const imageCard = document.querySelector(`#generationsQueue [data-id="${genId}"]`);
                const videoCard = document.querySelector(`#videoGenerationsQueue [data-id="${genId}"]`);
                if (imageCard) imageCard.remove();
                if (videoCard) videoCard.remove();
                updateQueueCount();
                updateVideoQueueCount();
            } else {
                showNotification('Erreur : ' + (data.error || 'Erreur inconnue'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            showNotification(`Erreur lors de la suppression de la génération ${type}`, 'danger');
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
        // Initial update (delayed to not block page load)
        setTimeout(() => {
            updateGlobalProgress();
        }, 500);

        // Poll every 3 seconds (reduced from 2s)
        progressInterval = setInterval(() => {
            updateGlobalProgress();
            updateRunningGenerationsProgress();
        }, 3000);
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

                    statsText.textContent = `${data.success}/${data.total} terminé • ${data.running} en cours • ${data.pending} en attente`;

                    // Update progress bar color
                    progressBar.className = 'progress-bar';
                    if (data.failure > 0) {
                        progressBar.classList.add('bg-danger');
                    } else if (data.running > 0) {
                        progressBar.classList.add('bg-warning', 'progress-bar-striped', 'progress-bar-animated');
                    } else if (data.success === data.total && data.total > 0) {
                        progressBar.classList.add('bg-success');
                    }
                }
            })
            .catch(error => console.error('Error updating global progress:', error));
    }

    /**
     * Update progress only for RUNNING generations (optimization)
     * Only polls cards that are currently running to reduce network requests
     * Handles both image and video generations
     */
    function updateRunningGenerationsProgress() {
        // Get unique generation IDs that need updating from both queues
        const idsToUpdate = new Set();

        // Check image queue
        document.querySelectorAll('#generationsQueue [data-id]').forEach(card => {
            const badge = card.querySelector('.badge');
            const wasRunning = card.getAttribute('data-was-running') === 'true';
            if ((badge && badge.textContent.trim() === 'RUNNING') || wasRunning) {
                idsToUpdate.add(card.getAttribute('data-id'));
            }
        });

        // Check video queue
        document.querySelectorAll('#videoGenerationsQueue [data-id]').forEach(card => {
            const badge = card.querySelector('.badge');
            const wasRunning = card.getAttribute('data-was-running') === 'true';
            if ((badge && badge.textContent.trim() === 'RUNNING') || wasRunning) {
                idsToUpdate.add(card.getAttribute('data-id'));
            }
        });

        // Only make requests for running generations
        idsToUpdate.forEach(genId => {
            const url = config.urls.progress.replace('0', genId);

            // Find card in either queue
            let card = document.querySelector(`#generationsQueue [data-id="${genId}"]`);
            if (!card) {
                card = document.querySelector(`#videoGenerationsQueue [data-id="${genId}"]`);
            }

            fetch(url)
                .then(response => response.json())
                .then(data => {
                    if (card) {
                        updateGenerationCard(card, data);
                    }
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
    function updateGenerationStatus(genId, status, progress, isVideo = false) {
        // Try both queues
        let card = document.querySelector(`#generationsQueue [data-id="${genId}"]`);
        if (!card) {
            card = document.querySelector(`#videoGenerationsQueue [data-id="${genId}"]`);
        }
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
            const startBtn = card.querySelector('.start-btn, .video-start-btn');
            if (startBtn) startBtn.style.display = 'none';
        }
    }

    /**
     * Update image queue count badge
     */
    function updateQueueCount() {
        const count = document.querySelectorAll('#generationsQueue [data-id]').length;
        const badge = document.getElementById('queueCount');
        const tabBadge = document.getElementById('imageQueueCount');
        if (badge) badge.textContent = count;
        if (tabBadge) tabBadge.textContent = count;
    }

    /**
     * Update video queue count badge
     */
    function updateVideoQueueCount() {
        const count = document.querySelectorAll('#videoGenerationsQueue [data-id]').length;
        const badge = document.getElementById('videoQueueCountInner');
        const tabBadge = document.getElementById('videoQueueCount');
        if (badge) badge.textContent = count;
        if (tabBadge) tabBadge.textContent = count;
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

    /**
     * Open video settings modal for a generation
     */
    function openVideoSettingsModal(genId) {
        const url = config.urls.getSettings.replace('0', genId);

        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    showNotification('Error: ' + data.error, 'danger');
                    return;
                }

                // Populate modal with data
                document.getElementById('video_modal_gen_id').textContent = data.id;
                document.getElementById('video_settings_gen_id').value = data.id;
                document.getElementById('video_settings_prompt').value = data.prompt || '';
                document.getElementById('video_settings_negative_prompt').value = data.negative_prompt || '';
                document.getElementById('video_settings_model').value = data.model || 'wan-t2v-1.3b';
                document.getElementById('video_settings_resolution').value = data.video_resolution || '480p';

                // Duration
                const durationEl = document.getElementById('video_settings_duration');
                durationEl.value = data.video_duration || 5;
                document.getElementById('video_settings_duration_value').textContent = durationEl.value;

                // FPS
                document.getElementById('video_settings_fps').value = data.video_fps || 16;

                // Seed
                document.getElementById('video_settings_seed').value = data.seed || '';

                // Steps
                const stepsEl = document.getElementById('video_settings_steps');
                stepsEl.value = data.steps || 30;
                document.getElementById('video_settings_steps_value').textContent = stepsEl.value;

                // Guidance scale
                const guidanceEl = document.getElementById('video_settings_guidance');
                guidanceEl.value = data.guidance_scale || 5;
                document.getElementById('video_settings_guidance_value').textContent = guidanceEl.value;

                // Show modal
                const modal = new bootstrap.Modal(document.getElementById('videoSettingsModal'));
                modal.show();
            })
            .catch(error => {
                console.error('Error loading video settings:', error);
                showNotification('Erreur lors du chargement des paramètres vidéo', 'danger');
            });
    }

    /**
     * Save video settings from modal
     */
    function saveVideoSettings(andStart = false) {
        const genId = document.getElementById('video_settings_gen_id').value;
        const url = config.urls.saveSettings.replace('0', genId);

        const formData = new FormData();
        formData.append('prompt', document.getElementById('video_settings_prompt').value);
        formData.append('negative_prompt', document.getElementById('video_settings_negative_prompt').value);
        formData.append('model', document.getElementById('video_settings_model').value);
        formData.append('video_resolution', document.getElementById('video_settings_resolution').value);
        formData.append('video_duration', document.getElementById('video_settings_duration').value);
        formData.append('video_fps', document.getElementById('video_settings_fps').value);
        formData.append('steps', document.getElementById('video_settings_steps').value);
        formData.append('guidance_scale', document.getElementById('video_settings_guidance').value);
        formData.append('seed', document.getElementById('video_settings_seed').value);

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
                showNotification('Paramètres vidéo sauvegardés !', 'success');

                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('videoSettingsModal'));
                if (modal) modal.hide();

                if (andStart) {
                    // Start the generation
                    startGeneration(genId, true);
                } else {
                    // Ensure video tab stays active
                    localStorage.setItem('imager_active_tab', 'video');
                    // Refresh page to show updated settings
                    setTimeout(() => location.reload(), 500);
                }
            } else {
                showNotification('Erreur : ' + (data.error || 'Erreur inconnue'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error saving video settings:', error);
            showNotification('Erreur lors de la sauvegarde des paramètres vidéo', 'danger');
        });
    }

    /**
     * Initialize model description tooltips
     * Shows model descriptions below dropdowns when selection changes
     */
    function initializeModelDescriptions() {
        // Find all model selects with tooltip support
        const modelSelects = document.querySelectorAll('.model-select-with-tooltip');

        modelSelects.forEach(select => {
            // Get the description element (sibling small.model-description)
            const descriptionElement = select.parentElement.querySelector('.model-description');

            if (descriptionElement) {
                // Update description on change
                select.addEventListener('change', function() {
                    updateModelDescription(this, descriptionElement);
                });

                // Show initial description
                updateModelDescription(select, descriptionElement);
            }
        });
    }

    /**
     * Update model description element based on selected option
     */
    function updateModelDescription(selectElement, descriptionElement) {
        const selectedOption = selectElement.options[selectElement.selectedIndex];
        const description = selectedOption.getAttribute('data-description') || '';

        if (description) {
            descriptionElement.textContent = description;
            descriptionElement.style.display = 'block';
        } else {
            descriptionElement.textContent = '';
            descriptionElement.style.display = 'none';
        }
    }

})();
