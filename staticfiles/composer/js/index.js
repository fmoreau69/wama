/**
 * Composer — Music & SFX Generation
 */

(function () {
    'use strict';

    const CSRF = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || '';
    // URLs via {% url %} (config posee par le template) - plus d'URL en dur (audit B4-10).
    const APP = window.COMPOSER_APP || {};

    // ---------------------------------------------------------------------------
    // Estimation helpers (mirrors model_config.py logic)
    // ---------------------------------------------------------------------------

    const MODELS = window.COMPOSER_MODELS || {};

    function estimateSeconds(modelId, duration) {
        const cfg = MODELS[modelId] || { genFactor: 1.5, overheadS: 15 };
        return Math.max(5, Math.round(duration * cfg.genFactor + cfg.overheadS));
    }

    function formatDuration(seconds) {
        if (seconds < 60) return `~${Math.round(seconds)}s`;
        const m = Math.floor(seconds / 60);
        const s = Math.round(seconds % 60);
        return s ? `~${m}min${String(s).padStart(2, '0')}s` : `~${m}min`;
    }

    function _fmtDur(secs) {
        const s = parseInt(secs, 10);
        if (s < 60) return s + 's';
        const m = Math.floor(s / 60);
        const r = s % 60;
        return r ? `${m}m${String(r).padStart(2, '0')}s` : `${m}min`;
    }

    // ---------------------------------------------------------------------------
    // Right-panel interactivity
    // ---------------------------------------------------------------------------

    const typeRadios     = document.querySelectorAll('input[name="gen_type"]');
    const modelSelect    = document.getElementById('modelSelect');
    const durationSlider = document.getElementById('durationSlider');
    const durationDisplay  = document.getElementById('durationDisplay');
    const estimateDisplay  = document.getElementById('estimateDisplay');
    const promptInput    = document.getElementById('promptInput');
    const melodyInput    = document.getElementById('melodyInput');
    const batchFileInput       = document.getElementById('batchFileInput');
    const generateBtn          = document.getElementById('generateBtn');
    const startAllBtn          = document.getElementById('startAllBtn');
    const clearAllBtn          = document.getElementById('clearAllBtn');
    const batchDetectBar       = document.getElementById('batchDetectBar');
    const batchDetectedCount   = document.getElementById('batchDetectedCount');
    const batchCreateCount     = document.getElementById('batchCreateCount');
    const batchCreateAndStartBtn = document.getElementById('batchCreateAndStartBtn');
    const batchCreateOnlyBtn   = document.getElementById('batchCreateOnlyBtn');
    const batchCancelBar       = document.getElementById('batchCancelBar');

    function getSelectedDuration() {
        return parseFloat(durationSlider?.value || 10);
    }

    function updateEstimate() {
        if (!estimateDisplay || !modelSelect) return;
        const est = estimateSeconds(modelSelect.value, getSelectedDuration());
        estimateDisplay.textContent = formatDuration(est);
    }

    if (durationSlider) {
        durationSlider.addEventListener('input', function () {
            durationDisplay.textContent = _fmtDur(this.value);
            updateEstimate();
        });
    }

    typeRadios.forEach(r => r.addEventListener('change', updateModelOptions));

    function updateModelOptions() {
        if (!modelSelect) return;
        const type = document.querySelector('input[name="gen_type"]:checked')?.value || 'music';
        const opts = Array.from(modelSelect.options);
        if (type === 'music') {
            const first = opts.find(o => o.value.startsWith('musicgen'));
            if (first) modelSelect.value = first.value;
        } else {
            const first = opts.find(o => o.value.startsWith('audiogen'));
            if (first) modelSelect.value = first.value;
        }
        updateEstimate();
    }

    // checkMelodyVisibility PURGEE (R17) : le slot melodie est pilote par WamaInputMatch
    // (capacites du catalogue), plus par un test d'id de modele en dur.

    if (modelSelect) {
        modelSelect.addEventListener('change', () => {
            updateEstimate();
        });
    }

    // Settings modal estimate
    const settingsDuration = document.getElementById('settingsDuration');
    const settingsDurationVal = document.getElementById('settingsDurationVal');
    const settingsEstimate = document.getElementById('settingsEstimate');
    const settingsModel = document.getElementById('settingsModel');

    function updateSettingsEstimate() {
        if (!settingsEstimate || !settingsModel || !settingsDuration) return;
        const est = estimateSeconds(settingsModel.value, parseFloat(settingsDuration.value));
        settingsEstimate.textContent = formatDuration(est);
    }

    // (Switch « Type » retiré — décision Fabien 2026-07-02 : le type est dérivé du modèle,
    //  la lisibilité vient des optgroups Musique/Bruitages du select.)

    if (settingsDuration) {
        settingsDuration.addEventListener('input', function () {
            settingsDurationVal.textContent = _fmtDur(this.value);
            updateSettingsEstimate();
        });
    }
    if (settingsModel) {
        settingsModel.addEventListener('change', updateSettingsEstimate);
    }

    // Init
    updateEstimate();

    // ---------------------------------------------------------------------------
    // Global progress bar
    // ---------------------------------------------------------------------------

    // Barre globale : refs DOM retirées avec updateGlobalBar (brique commune wama-global-progress.js).

    // Track per-id estimated seconds and start time

    // (Seed d'estimation client supprimé — l'ETA vient du serveur via WamaEta, B4-13.)

    // Barre globale : BRIQUE COMMUNE (wama-global-progress.js, auto-poll) — l'ancienne
    // updateGlobalBar hand-made (scan DOM + moyenne ponderee) a ete supprimee (audit B1-2).

    // Affiche l'état correct dès le chargement (barre toujours visible).

    // ---------------------------------------------------------------------------
    // Generate single item
    // ---------------------------------------------------------------------------

    if (generateBtn) {
        generateBtn.addEventListener('click', function () {
            // Prompt VIDE autorisé = génération ALÉATOIRE (le placeholder de la card l'annonce ;
            // backend generate_unconditional / chroma-seule). Cf. INPUT_MODEL_MATCHING.md.
            const prompt = promptInput?.value.trim() || '';

            const modelId = modelSelect?.value || 'musicgen-small';
            const duration = getSelectedDuration();

            const formData = new FormData();
            formData.append('csrfmiddlewaretoken', CSRF);
            formData.append('prompt', prompt);
            formData.append('model', modelId);
            formData.append('duration', duration);
            formData.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
            formData.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');

            // Référence fournie → jointe. Plus de test hardcodé par modèle : l'appariement
            // WamaInputMatch garantit qu'un modèle incompatible n'est pas sélectionnable.
            if (melodyInput?.files[0]) {
                formData.append('melody_reference', melodyInput.files[0]);
            }

            generateBtn.disabled = true;
            generateBtn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Envoi…';

            fetch(APP.generateUrl, { method: 'POST', body: formData })
                .then(r => r.json())
                .then(data => {
                    if (data.error) {
                        alert('Erreur : ' + data.error);
                    } else {
                        promptInput.value = '';
                        insertRenderedCard(data.id);
                        startPolling(data.id);
                    }
                })
                .catch(err => alert('Erreur réseau : ' + err))
                .finally(() => {
                    generateBtn.disabled = false;
                    generateBtn.innerHTML = '<i class="fas fa-play me-1"></i> Générer';
                });
        });
    }

    // ---------------------------------------------------------------------------
    // Import batch : BRIQUE COMMUNE WamaBatchImport (auto-hooks dropzone + input + detect bar
    // avec APERÇU serveur). Init dans le template (URLs via {% url %}) — cf. index.html.
    // L'ancien flux hand-rolled (drop manuel, compteur figé à '?', lancement inconditionnel
    // côté serveur) est remplacé — audit B3-9, 2026-07-03.
    // ---------------------------------------------------------------------------

    // Reset options handler
    document.getElementById('resetOptions')?.addEventListener('click', () => {
        if (modelSelect) {
            const firstMusic = Array.from(modelSelect.options).find(o => o.value.startsWith('musicgen'));
            if (firstMusic) modelSelect.value = firstMusic.value;
            updateEstimate();
        }
        if (durationSlider) {
            durationSlider.value = 10;
            if (durationDisplay) durationDisplay.textContent = '10s';
            updateEstimate();
        }
        localStorage.removeItem('composer_setting_modelSelect');
        localStorage.removeItem('composer_setting_durationSlider');
    });

    // ---------------------------------------------------------------------------
    // Start all / Clear all
    // ---------------------------------------------------------------------------

    if (startAllBtn) {
        startAllBtn.addEventListener('click', () => {
            fetch(APP.startAllUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json())
                .then(d => { if (d.launched > 0) { showToast(`${d.launched} génération(s) relancée(s)`, 'info'); location.reload(); } });
        });
    }

    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', () => {
            if (!confirm('Supprimer toutes les générations (sauf celles en cours) ?')) return;
            fetch(APP.clearAllUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(() => location.reload());
        });
    }

    // ---------------------------------------------------------------------------
    // Card actions (event delegation)
    // ---------------------------------------------------------------------------

    document.addEventListener('click', function (e) {

        const deleteBtn = e.target.closest('.delete-btn');
        if (deleteBtn) {
            const id = deleteBtn.dataset.id;
            if (!confirm('Supprimer cette génération ?')) return;
            fetch(WamaApp.getUrl(APP.deleteUrlTemplate, id), { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json().catch(() => ({})))
                .then((data) => {
                    // Élément issu d'un batch : total/affichage du batch changent → recharger
                    if (data.batch_changed) { if (window.WamaFM) WamaFM.deleted(); location.reload(); return; }
                    const card = document.querySelector(`.generation-card[data-id="${id}"]`);
                    if (card) {
                        const batchGroup = card.closest('.batch-group');
                        card.remove();
                        if (batchGroup && batchGroup.querySelectorAll('.generation-card').length === 0) {
                            batchGroup.remove();
                        }
                    }
                    if (window.WamaEta) WamaEta.reset(id);
                    checkEmptyState();
                    if (window.WamaFM) WamaFM.deleted();  // fichier supprimé → refresh filemanager
                });
            return;
        }

        const batchDeleteBtn = e.target.closest('.batch-delete-btn');
        if (batchDeleteBtn) {
            const bid = batchDeleteBtn.dataset.batchId;
            if (!confirm('Supprimer ce batch et toutes ses générations ?')) return;
            fetch(WamaApp.getUrl(APP.batchDeleteUrlTemplate, bid), { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(() => {
                    const group = document.querySelector(`.batch-group[data-batch-id="${bid}"]`);
                    if (group) {
                        if (window.WamaEta) group.querySelectorAll('.generation-card').forEach(c => WamaEta.reset(c.dataset.id));
                        group.remove();
                    }
                    checkEmptyState();
                    if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
                });
            return;
        }

        const duplicateBtn = e.target.closest('.duplicate-btn');
        if (duplicateBtn) {
            const id = duplicateBtn.dataset.id;
            fetch(WamaApp.getUrl(APP.duplicateUrlTemplate, id), { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json())
                .then(d => { if (d.success) location.reload(); });
            return;
        }

        // ▶ batch (card mère commune _batch_card.html, 2026-07-06) : lance les PENDING du batch.
        const batchStartBtn = e.target.closest('.batch-start-btn');
        if (batchStartBtn) {
            const bid = batchStartBtn.dataset.batchId;
            fetch(WamaApp.getUrl(APP.batchStartUrlTemplate, bid), { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json())
                .then(d => { (d.started || []).forEach(id => { insertRenderedCard(id); startPolling(id); }); })
                .catch(() => showToast('Erreur lors du lancement du batch', 'danger'));
            return;
        }

        const batchDuplicateBtn = e.target.closest('.batch-duplicate-btn');
        if (batchDuplicateBtn) {
            const bid = batchDuplicateBtn.dataset.batchId;
            fetch(WamaApp.getUrl(APP.batchDuplicateUrlTemplate, bid), { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json())
                .then(d => { if (d.success) location.reload(); });
            return;
        }

        // ⚙ batch : réutilise la modale individuelle en mode batch.
        const batchSettingsBtn = e.target.closest('.batch-settings-btn');
        if (batchSettingsBtn) {
            const group = batchSettingsBtn.closest('.batch-group');
            const firstItemBtn = group ? group.querySelector('.settings-btn') : null;
            window._composerBatchSettingsId = batchSettingsBtn.dataset.batchId;
            document.getElementById('settingsGenId').value = firstItemBtn ? firstItemBtn.dataset.id : '';
            if (settingsModel) settingsModel.value = (firstItemBtn && firstItemBtn.dataset.model) || 'musicgen-small';
            if (settingsDuration) {
                settingsDuration.value = (firstItemBtn && firstItemBtn.dataset.duration) || 10;
                settingsDurationVal.textContent = _fmtDur(settingsDuration.value);
                settingsDuration.dispatchEvent(new Event("input"));   // sync .wama-range-val (champ généré)
            }
            updateSettingsEstimate();
            new bootstrap.Modal(document.getElementById('settingsModal')).show();
            return;
        }

        const settingsBtn = e.target.closest('.settings-btn');
        if (settingsBtn) {
            window._composerBatchSettingsId = null;
            const id = settingsBtn.dataset.id;
            document.getElementById('settingsGenId').value = id;
            if (settingsModel) settingsModel.value = settingsBtn.dataset.model || 'musicgen-small';
            if (settingsDuration) {
                settingsDuration.value = settingsBtn.dataset.duration || 10;
                settingsDurationVal.textContent = _fmtDur(settingsDuration.value);
                settingsDuration.dispatchEvent(new Event("input"));   // sync .wama-range-val (champ généré)
            }
            // Modale complète (P1) : prompt + format/qualité de sortie.
            const sp = document.getElementById('settingsPrompt');
            if (sp) sp.value = settingsBtn.dataset.prompt || '';
            const sof = document.getElementById('settingsOutputFormat');
            if (sof && settingsBtn.dataset.outputFormat) sof.value = settingsBtn.dataset.outputFormat;
            const soq = document.getElementById('settingsOutputQuality');
            if (soq && settingsBtn.dataset.outputQuality) soq.value = settingsBtn.dataset.outputQuality;
            updateSettingsEstimate();
            new bootstrap.Modal(document.getElementById('settingsModal')).show();
            return;
        }

        const exportBtn = e.target.closest('.export-btn');
        if (exportBtn) {
            const id = exportBtn.dataset.id;
            fetch(WamaApp.getUrl(APP.exportUrlTemplate, id), { method: 'POST', headers: { 'X-CSRFToken': CSRF } })
                .then(r => r.json())
                .then(d => {
                    if (d.success) {
                        exportBtn.outerHTML = '<span class="btn btn-sm btn-outline-secondary disabled" title="Exporté"><i class="fas fa-check"></i></span>';
                        showToast('Exporté vers la médiathèque', 'success');
                    } else {
                        alert('Erreur export : ' + (d.error || 'inconnue'));
                    }
                });
            return;
        }

    });

    // Settings save — pied CONFORME : « Enregistrer » (sans relance) / « Enregistrer et relancer ».
    function _postSettings(restart) {
        // Mode batch : applique modèle + durée à tous les items du batch (endpoint batch inchangé).
        if (window._composerBatchSettingsId) {
            const bid = window._composerBatchSettingsId;
            window._composerBatchSettingsId = null;
            const fd = new FormData();
            fd.append('csrfmiddlewaretoken', CSRF);
            fd.append('model', settingsModel.value);
            fd.append('duration', settingsDuration.value);
            fetch(WamaApp.getUrl(APP.batchUpdateUrlTemplate, bid), { method: 'POST', body: fd })
                .then(r => r.json())
                .then(() => {
                    bootstrap.Modal.getInstance(document.getElementById('settingsModal'))?.hide();
                    location.reload();
                })
                .catch(() => {});
            return;
        }
        const id = document.getElementById('settingsGenId').value;
        const formData = new FormData();
        formData.append('csrfmiddlewaretoken', CSRF);
        formData.append('model', settingsModel.value);
        formData.append('duration', settingsDuration.value);
        // Modale complète (P1) : prompt + format/qualité de sortie.
        const sp = document.getElementById('settingsPrompt');
        if (sp) formData.append('prompt', sp.value);
        const sof = document.getElementById('settingsOutputFormat');
        if (sof) formData.append('output_format', sof.value);
        const soq = document.getElementById('settingsOutputQuality');
        if (soq) formData.append('output_quality', soq.value);
        formData.append('restart', restart ? '1' : '0');

        fetch(WamaApp.getUrl(APP.settingsUrlTemplate, id), { method: 'POST', body: formData })
            .then(r => r.json())
            .then(d => {
                if (d.success) {
                    bootstrap.Modal.getInstance(document.getElementById('settingsModal'))?.hide();
                    if (!d.restarted) return;   // Enregistrer simple : rien à relancer
                    if (window.WamaEta) WamaEta.reset(id);   // l'ETA se re-seede via progress
                    updateCardStatus(id, 'PENDING', 0);
                    startPolling(parseInt(id));
                } else {
                    alert('Erreur : ' + (d.error || 'inconnue'));
                }
            });
    }
    const settingsSaveBtn = document.getElementById('settingsSaveBtn');
    if (settingsSaveBtn) settingsSaveBtn.addEventListener('click', () => _postSettings(false));
    const settingsSaveRestartBtn = document.getElementById('settingsSaveRestartBtn');
    if (settingsSaveRestartBtn) settingsSaveRestartBtn.addEventListener('click', () => _postSettings(true));

    // ---------------------------------------------------------------------------
    // Polling
    // ---------------------------------------------------------------------------

    const pollingMap = {};

    function startPolling(genId) {
        if (pollingMap[genId]) return;
        pollingMap[genId] = setInterval(() => pollProgress(genId), 2000);
    }

    function stopPolling(genId) {
        clearInterval(pollingMap[genId]);
        delete pollingMap[genId];
    }

    function pollProgress(genId) {
        fetch(WamaApp.getUrl(APP.progressUrlTemplate, genId))
            .then(r => r.json())
            .then(data => {
                updateCardStatus(genId, data.status, data.progress, data);

                if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                    stopPolling(genId);
                    if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
                    // Card FINALE rendue serveur (waveform + boutons complets) — plus d'injection JS.
                    insertRenderedCard(genId);
                    if (data.status === 'SUCCESS') {
                        showToast('Génération terminée !', 'success');
                    } else {
                        showToast('Génération échouée : ' + (data.error || ''), 'error');
                    }
                }
            })
            .catch(() => stopPolling(genId));
    }

    function updateCardStatus(id, status, progress, data) {
        const card = document.querySelector(`.generation-card[data-id="${id}"]`);
        if (!card) return;
        card.dataset.status = status;   // pilote le bouton de cycle (WamaCycleButton.autoSync)

        // Border
        ['border-warning', 'border-success', 'border-danger', 'border-secondary',
         'processing', 'success', 'error'].forEach(c => card.classList.remove(c));
        const borderMap = { RUNNING: ['border-warning', 'processing'], SUCCESS: ['border-success', 'success'],
                            FAILURE: ['border-danger', 'error'], PENDING: ['border-secondary'] };
        (borderMap[status] || ['border-secondary']).forEach(c => card.classList.add(c));

        // Progress bar (cartes composer = .wama-progress-fill, pas .progress-bar Bootstrap)
        const bar = card.querySelector('.wama-progress-fill');
        if (bar) {
            bar.style.width = progress + '%';
            bar.classList.toggle('active', status === 'RUNNING');
        }

        // Progress text percentage
        const progressText = card.querySelector('.progress-text');
        if (progressText) {
            const node = progressText.firstChild;
            if (node && node.nodeType === Node.TEXT_NODE) {
                node.textContent = progress + '%\n';
            } else {
                progressText.prepend(document.createTextNode(progress + '%\n'));
            }
        }

        // Badge
        const badge = card.querySelector('.badge');
        if (badge) {
            const labels = { PENDING: 'En attente', RUNNING: 'En cours', SUCCESS: 'Succès', FAILURE: 'Échec' };
            const colors = { PENDING: 'bg-secondary', RUNNING: 'bg-warning', SUCCESS: 'bg-success', FAILURE: 'bg-danger' };
            badge.className = `badge flex-shrink-0 ${colors[status] || 'bg-secondary'}`;
            badge.textContent = labels[status] || status;
        }

        // ETA COMMUNE (WamaEta) : seedSeconds = estimation a priori/apprise renvoyée par
        // progress (eta_estimator serveur) — remplace le remaining-time client maison (B4-13).
        const etaEl = card.querySelector('.wama-eta');
        if (etaEl && window.WamaEta) {
            WamaEta.render(etaEl, WamaEta.update(id, {
                progress: progress, status: status,
                seedSeconds: data?.estimated_seconds, modelLoaded: false,
            }));
        }

        // Clear or set error message  (view returns field as 'error', not 'error_message')
        const actionsCol = card.querySelector('.col-md-3');
        const existingErr = actionsCol?.querySelector('.error-message');
        const errMsg = data?.error || data?.error_message || '';
        if (status === 'FAILURE' && errMsg) {
            if (existingErr) {
                existingErr.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${errMsg.substring(0, 80)}`;
            } else if (actionsCol) {
                actionsCol.insertAdjacentHTML('beforeend',
                    `<small class="error-message text-danger d-block mt-1">` +
                    `<i class="fas fa-exclamation-triangle"></i> ${errMsg.substring(0, 80)}</small>`);
            }
        } else if (existingErr) {
            existingErr.remove();
        }

        // Fin de tâche : la card COMPLÈTE (waveform + boutons) est re-rendue par le serveur
        // (insertRenderedCard dans pollProgress) — l'injection de chaines HTML est supprimée (B2-5).
    }

    // Auto-start du polling des items actifs au chargement — état lu sur data-status
    // (plus de détection par TEXTE de badge, fragile/i18n — audit B2-6).
    document.querySelectorAll('.generation-card').forEach(card => {
        if (card.dataset.status === 'RUNNING' || card.dataset.status === 'PENDING') {
            startPolling(parseInt(card.dataset.id));
        }
    });

    // Bouton de cycle commun ▶/⏹/↻ : wire (start/restart→/composer/start, stop→/composer/stop) + auto-sync.
    (function initCycleButton() {
        const q = document.getElementById('composerQueue');
        if (!window.WamaCycleButton || !q) return;
        WamaCycleButton.wire(q, {
            start: async (id) => {
                const card = q.querySelector(`.generation-card[data-id="${id}"]`);
                if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') {
                    try { await fetch(WamaApp.getUrl(APP.stopUrlTemplate, id), { method: 'POST', headers: { 'X-CSRFToken': CSRF } }); } catch (e) {}
                }
                try {
                    await fetch(WamaApp.getUrl(APP.startUrlTemplate, id), { method: 'POST', headers: { 'X-CSRFToken': CSRF } });
                    if (card) card.dataset.status = 'RUNNING';
                    startPolling(parseInt(id));
                } catch (e) {}
            },
            stop: async (id) => {
                const card = q.querySelector(`.generation-card[data-id="${id}"]`);
                try {
                    const r = await fetch(WamaApp.getUrl(APP.stopUrlTemplate, id), { method: 'POST', headers: { 'X-CSRFToken': CSRF } });
                    const data = await r.json().catch(() => ({}));
                    if (card && data.status) card.dataset.status = data.status;
                } catch (e) {}
            },
        });
        WamaCycleButton.autoSync({ container: q, cardSelector: '.generation-card' });
    })();

    // Initial global bar update

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    // Card RENDUE SERVEUR — SOURCE UNIQUE du markup (partial _generation_card.html via
    // composer:card_html ; CARD_DESIGN « partial server-side + update JS en place »).
    // Remplace la reconstruction JS qui divergeait déjà du serveur (barre Bootstrap vs
    // .wama-progress-fill → jamais mise à jour, boutons ⚙/dupliquer absents) — audit B2-4.
    function insertRenderedCard(id) {
        fetch(WamaApp.getUrl(APP.cardHtmlUrlTemplate, id))
            .then(r => { if (!r.ok) throw new Error(r.status); return r.text(); })
            .then(html => {
                const queue = document.getElementById('composerQueue');
                if (!queue) return;
                const existing = queue.querySelector(`.generation-card[data-id="${id}"]`);
                if (existing) existing.outerHTML = html;
                else queue.insertAdjacentHTML('afterbegin', html);
                checkEmptyState();
            })
            .catch(() => location.reload());
    }

    // Etat vide : bascule du hint RENDU SERVEUR (source unique dans index.html) — audit B4-11.
    function checkEmptyState() {
        const queue = document.getElementById('composerQueue');
        const hint = document.getElementById('emptyHint');
        if (!queue || !hint) return;
        hint.classList.toggle('d-none', queue.querySelectorAll('.generation-card').length > 0);
    }

    // Toast : brique commune (wama-app-base.js) — l'implémentation locale a été PROMUE brique
    // (WamaApp.toast, 2026-07-06) puis supprimée ici.
    function showToast(message, type) {
        if (window.WamaApp && WamaApp.toast) WamaApp.toast(message, type);
        else console.info('[Composer]', message);
    }

})();
