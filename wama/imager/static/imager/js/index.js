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
    // ── Volet droit — GÉNÉRÉ depuis le schéma (params.py, surface "panel") ────────────────
    // Remplace 257 lignes de champs écrits à la main. Les `dom_id` du schéma reprennent les
    // IDs LEGACY du volet (#model, #steps, #num_images, #panel_video_*), donc tout le JS qui
    // les lit continue de fonctionner inchangé — recette common/README.md §3.1.
    function renderRightPanel() {
        if (!window.WamaParams) {
            console.warn('[imager] WamaParams absent — volet droit NON rendu.');
            return;
        }
        [['imagePanelParams', window.IMAGER_IMAGE_SCHEMA, window.IMAGER_IMAGE_GROUPS,
          window.IMAGER_IMAGE_PANEL_VALUES],
         ['videoPanelParams', window.IMAGER_VIDEO_SCHEMA, window.IMAGER_VIDEO_GROUPS,
          window.IMAGER_VIDEO_PANEL_VALUES]
        ].forEach(function (spec) {
            var host = document.getElementById(spec[0]);
            if (!host || !spec[1]) return;
            WamaParams.render(host, spec[1], {
                context: 'panel',
                groups: spec[2] || [],
                values: spec[3] || {}
            });
        });

        // Select modèle : options peuplées depuis les MÊMES groupes de catalogue que la modale
        // d'item et la card (fillModelChoices, settings_modal.js) — pas de 2e liste. Sans cet
        // appel le <select> du volet reste VIDE : le schéma déclare le champ, pas ses options.
        if (window.imagerFillModelChoices) {
            var vals = window.IMAGER_IMAGE_PANEL_VALUES || {};
            var vvals = window.IMAGER_VIDEO_PANEL_VALUES || {};
            imagerFillModelChoices(document.getElementById('imagePanelParams'), 'image', vals.model);
            imagerFillModelChoices(document.getElementById('videoPanelParams'), 'video', vvals.model);
        } else {
            console.warn('[imager] imagerFillModelChoices absent — select modèle du volet vide.');
        }

        // Zone HORS SCHÉMA (résolution image à présets, cf. docstring params.py) greffée dans
        // le groupe « Sortie » — même échappatoire que la modale d'item (settings_modal.js).
        // Repli explicite : si le groupe n'existe pas, la zone reste en place et VISIBLE —
        // jamais masquée, sinon la résolution disparaîtrait silencieusement du volet.
        var zone = document.getElementById('panelResolutionZone');
        if (!zone) return;
        var imgHost = document.getElementById('imagePanelParams');
        var body = imgHost && imgHost.querySelector('[data-group="sortie"] .wama-param-group-body');
        zone.hidden = false;
        if (body) body.appendChild(zone);
    }

    document.addEventListener('DOMContentLoaded', function() {
        initializeEventListeners();
        initializeModeSelector();
        initializeDropZones();
        initializeVideoTab();
        initializeTabPersistence();
        initializeRightPanelSync();
        // initializeModelDescriptions() RETIRÉ : descriptifs modèle (courte + ⓘ longue) rendus
        // par le composant COMMUN WamaModelHelp, meta = CATALOGUE (fetchCatalogMeta('imager')
        // dans index.html). L'ancien chemin data-description ne portait que la courte (pas
        // d'overlay) et double-écrirait les mêmes éléments. Fonction conservée le temps de la
        // transition (REMOVAL_LEDGER R15).
        renderRightPanel();
        initializeResolutionSelectors();
        startProgressPolling();

        // Flag active processing for file manager (bg-warning = RUNNING status)
        if (document.querySelector('#generationsQueue .badge.bg-warning, #videoGenerationsQueue .badge.bg-warning')) {
            document.body.setAttribute('data-wama-processing', 'true');
        }
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
                if (modelSelect) {
                    modelSelect.selectedIndex = 0;
                    // Trigger resolution update for new model
                    updateResolutionsForModel(modelSelect.value);
                }

                // Reset resolution
                const resolutionSelect = document.getElementById('resolution');
                if (resolutionSelect) {
                    resolutionSelect.value = '512x512';
                    updateWidthHeightFromResolution(resolutionSelect.value, 'width', 'height');
                }

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




        // Force reset button for stuck generations
        const forceResetVideoBtn = document.getElementById('forceResetVideoBtn');
        if (forceResetVideoBtn) {
            forceResetVideoBtn.addEventListener('click', function() {
                const genId = document.getElementById('video_settings_gen_id').value;
                if (confirm('Êtes-vous sûr de vouloir forcer la réinitialisation de cette génération ?\n\nCette action marquera la génération comme échouée et vous permettra de la relancer.')) {
                    forceResetGeneration(genId);
                }
            });
        }

        // ── Champ prompt à deux états ([[wama-prompt-enrich]], brique commune) ──────────────
        // Les 4 champs prompt d'imager (card d'entrée image/vidéo + les 2 modales de
        // paramètres) partagent le même composant : même geste partout, aucun code dupliqué.
        ['prompt', 'video_prompt', 'settings_prompt', 'video_settings_prompt'].forEach(function (id) {
            const el = document.getElementById(id);
            if (el && window.WamaPromptEnrich) {
                WamaPromptEnrich.attach(el, {
                    app: 'imager',
                    domain: id.indexOf('video') === 0 ? 'video' : 'image',
                    endpoint: config.urls.enhancePrompt,
                    csrf: config.csrfToken,
                    original: el.value, processed: ''
                });
            }
        });

        // Prompt enhancement buttons (image + video)
        document.addEventListener('click', function(e) {
            const btn = e.target.closest('.enhance-prompt-btn');
            if (!btn) return;
            const targetId = btn.dataset.target;
            const mode = btn.dataset.mode || 'image';
            const textarea = document.getElementById(targetId);
            if (!textarea || !textarea.value.trim()) return;
            const icon = btn.querySelector('i');
            const originalClass = icon.className;
            icon.className = 'fas fa-spinner fa-spin';
            btn.disabled = true;
            fetch(config.urls.enhancePrompt, {
                method: 'POST',
                headers: {'Content-Type': 'application/json', 'X-CSRFToken': config.csrfToken},
                body: JSON.stringify({
                    prompt: promptOf(textarea), app: 'imager', domain: mode,
                    // Mots-clés cliqués → glossaire : préservés VERBATIM par l'enrichissement.
                    keywords: window.WamaPromptChips ? WamaPromptChips.activeFor(textarea) : []
                })
            })
            .then(r => r.json())
            .then(data => {
                if (data.enhanced) {
                    textarea.dataset.originalPrompt = promptOf(textarea);
                    // Passe par la brique commune : c'est elle qui tient les deux états
                    // (« voir mon prompt » / « revenir au mien ») et resynchronise les chips.
                    if (window.WamaPromptEnrich && WamaPromptEnrich.get(textarea)) {
                        WamaPromptEnrich.setProcessed(textarea, data.enhanced);
                    } else {
                        textarea.value = data.enhanced;
                        if (window.WamaPromptChips) WamaPromptChips.refreshFor(textarea);
                    }
                } else {
                    WamaApp.toast(data.error || 'Erreur lors de l\'amélioration du prompt', 'error');
                }
            })
            .catch(() => WamaApp.toast('Erreur réseau', 'error'))
            .finally(() => {
                icon.className = originalClass;
                btn.disabled = false;
            });
        });
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
        // Formulaire legacy absent (card d'entrée commune) → no-op, sinon TypeError
        // sur getElementById qui tuerait toute la chaîne d'init (dont le polling file).
        if (!document.querySelector('.mode-section')) return;
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

            formData.set('prompt', promptOf(prompt));
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
            formData.set('prompt', promptOf(prompt));
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

        // Handle dropped files (native HTML5 drag)
        dropZone.addEventListener('drop', function(e) {
            const files = e.dataTransfer.files;
            if (files.length > 0) {
                fileInput.files = files;
                if (onFileSelected) onFileSelected(files[0]);
            }
        }, false);

        // Handle drop from FileManager sidebar (vakata DND — no native dataTransfer)
        dropZone.addEventListener('filemanager:filedrop', async function(e) {
            const { path, name, mime } = e.detail;
            try {
                const mediaUrl = (window.MEDIA_URL || '/media/') + path;
                const response = await fetch(mediaUrl);
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                const blob = await response.blob();
                const file = new File([blob], name || 'image', { type: blob.type || mime || 'image/jpeg' });
                const dt = new DataTransfer();
                dt.items.add(file);
                fileInput.files = dt.files;
                if (onFileSelected) onFileSelected(file);
            } catch (err) {
                console.error('[imager] FileManager drop failed:', err);
            }
        });

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
    /**
     * Prompt de l'UTILISATEUR pour un champ (et non l'enrichi affiché).
     * Invariant : en base, `prompt` = ce qu'il a tapé ; l'enrichi vit dans `prompt_processed`.
     * À la création on poste donc toujours l'original — le serveur ré-enrichit à l'ingestion
     * (même skill, même cache → immédiat), sinon un clic sur ✨ avant l'ajout écraserait
     * définitivement le prompt d'origine par sa version enrichie.
     */
    function promptOf(field) {
        const c = window.WamaPromptEnrich && WamaPromptEnrich.get(field);
        return c ? c.snapshot().original : field.value;
    }

    /**
     * (Ré)attache le champ à deux états d'une modale de paramètres sur l'item ouvert.
     * `data` vient de get_generation_settings : `prompt` (le sien) + `prompt_processed`.
     */
    function attachPromptStates(fieldId, domain, data) {
        const el = document.getElementById(fieldId);
        if (!el) return;
        if (!window.WamaPromptEnrich) {          // brique absente → comportement d'avant
            el.value = data.prompt || '';
            return;
        }
        WamaPromptEnrich.attach(el, {
            app: 'imager', domain: domain,
            endpoint: config.urls.enhancePrompt, csrf: config.csrfToken,
            original: data.prompt || '',
            processed: data.prompt_processed || '',
            keywords: data.prompt_keywords || []
        });
    }

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
        // Output format + quality (Phase 3)
        const outFmt = document.getElementById('output_format');
        const outQual = document.getElementById('output_quality');
        if (outFmt) formData.set('output_format', outFmt.value);
        if (outQual) formData.set('output_quality', outQual.value);

        // Mode-specific data
        if (currentMode === 'txt2img') {
            const prompt = document.getElementById('prompt');
            const negativePrompt = document.getElementById('negative_prompt');

            if (!prompt || !prompt.value.trim()) {
                showNotification('Le prompt est requis', 'warning');
                return;
            }

            formData.set('prompt', promptOf(prompt));
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
                formData.set('prompt', promptOf(img2imgPrompt));
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
                document.body.setAttribute('data-wama-processing', 'true');
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
                if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
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
        // DEUX barres globales SÉPARÉES — une par file : file IMAGES et file VIDÉOS.
        // On réutilise la fonction commune WamaGlobalProgress (zéro duplication) ; `dataKey`
        // isole le domaine dans l'endpoint imbriqué {image:{…}, video:{…}}. Chaque barre est
        // indépendante (sa part de données, ses propres éléments DOM), chacune s'auto-poll.
        if (window.WamaGlobalProgress) {
            // File images → IDs par défaut (#globalProgressBar/Stats/Pct, partial commun).
            WamaGlobalProgress.init({ url: config.urls.globalProgress, dataKey: 'image' });
            // File vidéos → IDs dédiés de la barre vidéo.
            WamaGlobalProgress.init({
                url: config.urls.globalProgress, dataKey: 'video',
                bar: 'videoGlobalProgressBar', stats: 'videoGlobalProgressStats',
                pct: 'videoGlobalProgressPct', status: 'videoGlobalStatus', eta: 'videoGlobalEta',
            });
        }

        // Progression PAR-CARTE (cartes en cours) — propre à imager, inchangé.
        // Polling par card : assuré par queue.js (WamaApp.Poller + refreshCard sur
        // l'endpoint card_html). Les fonctions de repaint DOM manuel ont été SUPPRIMÉES
        // avec les cards inline — seules les barres globales restent pilotées ici.
    }

    /**
     * Update progress only for RUNNING generations (optimization)
     * Only polls cards that are currently running to reduce network requests
     * Handles both image and video generations
     */

    /**
     * Update a generation card with new data
     */

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

    /**
     * Save settings from modal
     */

    /**
     * Open video settings modal for a generation
     */

    /**
     * Save video settings from modal
     */

    /**
     * Force reset a stuck generation to FAILURE status
     */
    function forceResetGeneration(genId) {
        const url = config.urls.forceReset.replace('0', genId);

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                showNotification('Génération réinitialisée. Vous pouvez maintenant la relancer.', 'success');

                // Close modal
                const modal = bootstrap.Modal.getInstance(document.getElementById('videoSettingsModal'));
                if (modal) modal.hide();

                // Ensure video tab stays active
                localStorage.setItem('imager_active_tab', 'video');

                // Refresh page to show updated status
                setTimeout(() => location.reload(), 500);
            } else {
                showNotification('Erreur : ' + (data.error || 'Erreur inconnue'), 'danger');
            }
        })
        .catch(error => {
            console.error('Error force resetting generation:', error);
            showNotification('Erreur lors de la réinitialisation', 'danger');
        });
    }

    /**
     * Force reset a stuck image generation to FAILURE status
     */

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

    /**
     * Initialize resolution selectors
     * Handles resolution dropdown changes and model-specific resolution recommendations
     */
    function initializeResolutionSelectors() {
        // Main panel resolution selector
        const resolutionSelect = document.getElementById('resolution');
        if (resolutionSelect) {
            resolutionSelect.addEventListener('change', function() {
                updateWidthHeightFromResolution(this.value, 'width', 'height');
            });
            // Initialize with current value
            updateWidthHeightFromResolution(resolutionSelect.value, 'width', 'height');
        }

        // Settings modal resolution selector
        const settingsResolutionSelect = document.getElementById('settings_resolution');
        if (settingsResolutionSelect) {
            settingsResolutionSelect.addEventListener('change', function() {
                updateWidthHeightFromResolution(this.value, 'settings_width', 'settings_height');
            });
        }

        // Model change triggers resolution update
        const modelSelect = document.getElementById('model');
        if (modelSelect) {
            modelSelect.addEventListener('change', function() {
                updateResolutionsForModel(this.value);
            });
            // Initialize with current model
            updateResolutionsForModel(modelSelect.value);
        }

        // Settings modal model change
        const settingsModelSelect = document.getElementById('settings_model');
        if (settingsModelSelect) {
            settingsModelSelect.addEventListener('change', function() {
                updateResolutionsForModel(this.value, 'settings_resolution', 'settings_resolution_warning');
            });
        }
    }

    /**
     * Update hidden width/height fields from resolution value
     */
    function updateWidthHeightFromResolution(resolution, widthId, heightId) {
        const parts = resolution.split('x');
        if (parts.length === 2) {
            const widthField = document.getElementById(widthId);
            const heightField = document.getElementById(heightId);
            if (widthField) widthField.value = parts[0];
            if (heightField) heightField.value = parts[1];
        }
    }

    /**
     * Update resolution options based on model selection
     * Fetches recommended resolutions from API and highlights them
     */
    function updateResolutionsForModel(modelName, resolutionSelectId = 'resolution', warningId = 'resolution_warning') {
        const resolutionSelect = document.getElementById(resolutionSelectId);
        const warningEl = document.getElementById(warningId);

        if (!resolutionSelect) return;

        // Fetch model-specific resolutions from API
        const url = config.urls.modelResolutions + '?model=' + encodeURIComponent(modelName);

        fetch(url)
            .then(response => response.json())
            .then(data => {
                if (data.error) {
                    console.warn('Error fetching resolutions:', data.error);
                    return;
                }

                const recommendedKeys = data.recommended || [];
                const defaultResolution = data.default || '512x512';
                const vramWarning = data.vram_warning || '';

                // Update warning message
                if (warningEl) {
                    if (vramWarning) {
                        warningEl.textContent = vramWarning;
                        warningEl.style.display = 'block';
                    } else {
                        warningEl.style.display = 'none';
                    }
                }

                // Highlight recommended options and set default
                const options = resolutionSelect.querySelectorAll('option');
                options.forEach(option => {
                    const isRecommended = recommendedKeys.includes(option.value);
                    // Add visual indicator for recommended resolutions
                    if (isRecommended) {
                        if (!option.textContent.includes('★')) {
                            option.textContent = '★ ' + option.textContent;
                        }
                        option.style.fontWeight = 'bold';
                    } else {
                        option.textContent = option.textContent.replace('★ ', '');
                        option.style.fontWeight = 'normal';
                    }
                });

                // Set default resolution for this model if current value is not recommended
                if (recommendedKeys.length > 0 && !recommendedKeys.includes(resolutionSelect.value)) {
                    resolutionSelect.value = defaultResolution;
                    // Update hidden fields
                    if (resolutionSelectId === 'resolution') {
                        updateWidthHeightFromResolution(defaultResolution, 'width', 'height');
                    } else if (resolutionSelectId === 'settings_resolution') {
                        updateWidthHeightFromResolution(defaultResolution, 'settings_width', 'settings_height');
                    }
                }

                // Update guidance scale and steps when model changes (main panel only)
                if (resolutionSelectId === 'resolution') {
                    if (data.default_guidance_scale !== undefined) {
                        const guidanceSlider = document.getElementById('guidance_scale');
                        const guidanceValue = document.getElementById('guidance_value');
                        if (guidanceSlider) { guidanceSlider.value = data.default_guidance_scale; }
                        if (guidanceValue) { guidanceValue.textContent = data.default_guidance_scale; }
                    }
                    if (data.default_steps !== undefined) {
                        const stepsSlider = document.getElementById('steps');
                        const stepsValue = document.getElementById('steps_value');
                        if (stepsSlider) { stepsSlider.value = data.default_steps; }
                        if (stepsValue) { stepsValue.textContent = data.default_steps; }
                    }
                }
            })
            .catch(error => {
                console.warn('Error fetching model resolutions:', error);
            });
    }

    /**
     * Get resolution string from width and height
     */
    function getResolutionFromWidthHeight(width, height) {
        return width + 'x' + height;
    }

})();
