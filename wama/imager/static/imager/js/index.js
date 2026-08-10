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

    // ── Inspecteur CONTEXTUEL (brique commune) ───────────────────────────────────────────
    // DEUX instances, une par domaine : la file de l'imager est scopée par onglet, et chaque
    // domaine a son propre volet + son propre schéma. Contrat : reader.js:624.
    // Le mapping dom_id(panel) ⇄ name est fait par la brique (`panelKey`), donc rien à traduire
    // ici — c'est ce qui rend params.py suffisant.
    function initInspector() {
        if (!window.WamaInspector || !WamaInspector.initFromSchema) {
            console.warn('[imager] WamaInspector absent — volet non contextuel.');
            return;
        }
        [{ queue: 'generationsQueue', panel: 'imagePanelParams',
           schema: window.IMAGER_IMAGE_SCHEMA, label: 'image' },
         { queue: 'videoGenerationsQueue', panel: 'videoPanelParams',
           schema: window.IMAGER_VIDEO_SCHEMA, label: 'vidéo' }
        ].forEach(function (d) {
            const q = document.getElementById(d.queue);
            const ph = document.getElementById(d.panel);
            if (!q || !ph) return;
            WamaInspector.initFromSchema({
                queueContainer: q,
                // [data-id] EXIGÉ : la card mère de batch porte .imager-card SANS data-id
                // (même correctif que pour le Poller — sinon requêtes sur `undefined`).
                cardSelector: '.imager-card[data-id]',
                batchSelector: '.batch-group',
                panelContainer: ph,
                schema: d.schema || [],
                itemLabel: function (id) { return "la génération #" + id; },
                batchLabel: function (id) { return "le batch #" + id + " (tous les éléments)"; },
                // Les deux endpoints lisent `request.POST` (coerce_schema_values) — donc
                // FormData, PAS du JSON comme reader.
                saveItem: function (id) {
                    return WamaApp.csrfFetch(
                        WamaApp.getUrl(config.urls.saveSettings, id), config.csrfToken,
                        { method: 'POST', body: _panelFormData(ph) }
                    ).then(function (r) { if (r && r.ok && window.imagerRefreshCard) imagerRefreshCard(id); });
                },
                saveBatch: function (bid) {
                    const url = (window.IMAGER_CARD || {}).urls.batchUpdate;
                    if (!url) return Promise.resolve();
                    return WamaApp.csrfFetch(
                        WamaApp.getUrl(url, bid), config.csrfToken,
                        { method: 'POST', body: _panelFormData(ph) }
                    ).then(function () { window.location.reload(); });
                },
            });
        });
    }

    function _panelFormData(host) {
        const fd = new FormData();
        const vals = (window.WamaParams ? WamaParams.read(host) : {}) || {};
        Object.keys(vals).forEach(function (k) {
            if (vals[k] !== null && vals[k] !== undefined) fd.append(k, vals[k]);
        });
        return fd;
    }

    document.addEventListener('DOMContentLoaded', function() {
        initializeEventListeners();
        initializeTabPersistence();
        renderRightPanel();
        initInspector();          // après renderRightPanel : le volet doit exister
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

        // ── Actions globales : barre d'outils COMMUNE de la file (_queue_toolbar) ────────
        // `start_id`/`clear_id`/`download_id` sont REQUIS par la brique mais leurs handlers
        // sont à la charge de l'app (doc du partial). Ils n'étaient câblés NULLE PART :
        // les deux toolbars (image + vidéo) étaient donc décoratives — support ≠ adoption.
        // Les boutons globaux du volet droit, eux, marchaient : le volet est désormais réservé
        // aux actions de SÉLECTION (_inspector_actions), comme dans reader.
        [['imager-image-start-all', startAllGenerations],
         ['imager-video-start-all', startAllGenerations],
         ['imager-image-clear-all', clearAllGenerations],
         ['imager-video-clear-all', clearAllGenerations],
        ].forEach(function (pair) {
            const el = document.getElementById(pair[0]);
            if (el) el.addEventListener('click', pair[1]);
        });
        ['imager-image-download-all', 'imager-video-download-all'].forEach(function (id) {
            const el = document.getElementById(id);
            if (el) el.addEventListener('click', function () {
                window.location.href = config.urls.downloadAll;
            });
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






        // downloadAllBtn RETIRÉ avec les boutons globaux du volet : « Tout télécharger » vit
        // désormais dans la barre d'outils commune de chaque file (câblée plus haut).

        // Download individual buttons
        document.addEventListener('click', function(e) {
            if (e.target.closest('.download-btn')) {
                const btn = e.target.closest('.download-btn');
                const genId = btn.getAttribute('data-id');
                window.location.href = config.urls.download.replace('0', genId);
            }
        });


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

                // Reset seed
                const seedInput = document.getElementById('seed');
                if (seedInput) seedInput.value = '';

                // Reset upscale
                const upscaleCheck = document.getElementById('upscale');
                if (upscaleCheck) upscaleCheck.checked = false;
            });
        }



        // ============ VIDEO TAB EVENT LISTENERS ============



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
     * Start all pending generations
     */
    function startAllGenerations(e) {
        // Bouton réel = celui de la toolbar cliquée (il y en a deux, une par file). L'ancien
        // `#startAllBtn` n'existe pas dans l'imager : `btn.disabled` levait un TypeError AVANT
        // le fetch — « Démarrer tout » était inopérant sur les deux toolbars.
        const btn = e && e.currentTarget ? e.currentTarget : null;
        const prev = btn ? btn.innerHTML : '';
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
        }
        function restore() {
            if (btn) { btn.disabled = false; btn.innerHTML = prev; }
        }

        fetch(config.urls.startAll, {
            method: 'POST',
            headers: {
                'X-CSRFToken': config.csrfToken
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                WamaApp.toast(`Started ${data.started} generation(s)!`, 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                WamaApp.toast('Error: ' + (data.error || 'Unknown error'), 'error');
                restore();
            }
        })
        .catch(error => {
            console.error('Error:', error);
            WamaApp.toast('Error starting generations', 'error');
            restore();
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
                WamaApp.toast(`Génération ${type} supprimée`, 'success');
                // Remove from DOM - check in both queues
                const imageCard = document.querySelector(`#generationsQueue [data-id="${genId}"]`);
                const videoCard = document.querySelector(`#videoGenerationsQueue [data-id="${genId}"]`);
                if (imageCard) imageCard.remove();
                if (videoCard) videoCard.remove();
                updateQueueCount();
                updateVideoQueueCount();
                if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
            } else {
                WamaApp.toast('Erreur : ' + (data.error || 'Erreur inconnue'), 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            WamaApp.toast(`Erreur lors de la suppression de la génération ${type}`, 'error');
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
                WamaApp.toast(`Deleted ${data.deleted} generation(s)`, 'success');
                setTimeout(() => location.reload(), 500);
            } else {
                WamaApp.toast('Error: ' + (data.error || 'Unknown error'), 'error');
            }
        })
        .catch(error => {
            console.error('Error:', error);
            WamaApp.toast('Error clearing generations', 'error');
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
            modelSelect.addEventListener('change', function (e) {
                // `isTrusted` distingue un vrai geste utilisateur d'un dispatchEvent
                // programmatique (inspecteur, restauration de réglages…).
                updateResolutionsForModel(this.value, 'resolution', 'resolution_warning',
                                          e && e.isTrusted === true);
            });
            // Initialisation : on rafraîchit les résolutions recommandées, mais SANS toucher
            // aux steps/guidance — ce sont les réglages persistés de l'utilisateur.
            updateResolutionsForModel(modelSelect.value, 'resolution', 'resolution_warning', false);
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
    // `applyModelDefaults` : n'imposer les steps/guidance du MODÈLE que si le changement vient
    // de l'UTILISATEUR. Cette fonction répond en ASYNCHRONE et écrasait sans distinction —
    // deux dégâts mesurés le 2026-08-07 :
    //   • inspecteur : sélectionner une card posait son `model` puis dispatchait `change` ;
    //     la réponse arrivait APRÈS la boucle d'application et effaçait les steps de la card ;
    //   • chargement de page : l'appel d'initialisation écrasait les réglages utilisateur
    //     persistés (brique user_settings) par les défauts du modèle.
    function updateResolutionsForModel(modelName, resolutionSelectId = 'resolution',
                                       warningId = 'resolution_warning',
                                       applyModelDefaults = true) {
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
                    }
                }

                // Update guidance scale and steps when model changes (main panel only)
                if (resolutionSelectId === 'resolution' && applyModelDefaults) {
                    if (data.default_guidance_scale !== undefined) {
                        const guidanceSlider = document.getElementById('guidance_scale');
                        if (guidanceSlider) { guidanceSlider.value = data.default_guidance_scale; }
                    }
                    if (data.default_steps !== undefined) {
                        const stepsSlider = document.getElementById('steps');
                        if (stepsSlider) { stepsSlider.value = data.default_steps; }
                    }
                }
            })
            .catch(error => {
                console.warn('Error fetching model resolutions:', error);
            });
    }


})();
