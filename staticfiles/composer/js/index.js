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

    // Durées : le formateur COMMUN (`WamaApp.formatDuration`, « 3:30 », 2026-10-04) — les deux
    // copies locales (« ~3min30s », « 3m30s ») sont retirées : une seule écriture de la durée.
    function formatDuration(seconds) {
        return '~' + WamaApp.formatDuration(seconds);
    }

    const _fmtDur = (secs) => WamaApp.formatDuration(secs);

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
    const generateBtn          = document.getElementById('generateBtn');
    const startAllBtn          = document.getElementById('startAllBtn');
    const clearAllBtn          = document.getElementById('clearAllBtn');
    // (La barre de lot — #batchDetectBar & co — est pilotée par la brique commune
    //  WamaBatchImport ; ses constantes, jamais lues ici, sont retirées le 2026-09-29.)

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
            const first = opts.find(o => o.value.includes('musicgen'));
            if (first) modelSelect.value = first.value;
        } else {
            const first = opts.find(o => o.value.includes('audiogen'));
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

    // (Switch « Type » retiré — décision Fabien 2026-07-02 : le type est dérivé du modèle,
    //  la lisibilité vient des optgroups Musique/Bruitages du select.)

    // Le prompt de la modale à DEUX ÉTATS (brique commune `WamaPromptEnrich`, la route de l'imager,
    // 2026-10-04) : l'enrichi (`data-prompt-processed` du gear) est affiché s'il existe, l'original
    // reste consultable et récupérable ; ✨ ré-enrichit selon le contrat du modèle choisi.
    function _wireSettingsPrompt(host, card) {
        const field = host.querySelector('#settingsPrompt');
        if (!field || !window.WamaPromptEnrich) return;
        const v = WamaInspector.gearValues(card, ['prompt', 'prompt_processed']);
        const original = v.prompt != null ? v.prompt : field.value;
        const processed = v.prompt_processed || '';
        field.value = processed || original;
        WamaPromptEnrich.attach(field, {
            app: 'composer', domain: 'music', csrf: CSRF, trigger: true,
            modelSelect: '#settingsModel', original: original, processed: processed,
        });
    }

    // Estimation (~20s) DANS la modale ⚙ : greffée à côté de la valeur du slider Durée du
    // formulaire GÉNÉRÉ (les champs n'existent qu'à l'ouverture — hook `decorate` du cycle commun).
    function _wireSettingsEstimate(host) {
        const model = host.querySelector('#settingsModel');
        const duration = host.querySelector('#settingsDuration');
        if (!model || !duration) return;
        const est = document.createElement('span');
        est.className = 'text-info small ms-2';
        est.id = 'settingsEstimate';
        const val = duration.closest('.wama-range') && duration.closest('.wama-range').querySelector('.wama-range-val');
        (val || duration).insertAdjacentElement('afterend', est);
        const refresh = function () {
            est.textContent = formatDuration(estimateSeconds(model.value, parseFloat(duration.value)));
        };
        duration.addEventListener('input', refresh);
        model.addEventListener('change', refresh);
        refresh();
    }


    // ⚙ de LOT — ouvreur DÉCLARÉ à la brique commune (queue-actions.js).
    WamaQueueActions.onBatchSettings(function (bid, btn) {
        const group = btn.closest('.batch-group');
        const firstItemBtn = group ? group.querySelector('.settings-btn') : null;
        const fd = firstItemBtn ? firstItemBtn.dataset : {};
        document.getElementById('batchSettingsBatchId').value = bid;
        const lbl = document.getElementById('batchSettingsBatchLabel');
        if (lbl) lbl.textContent = '#' + bid;
        // Valeurs posées par la brique (WamaParams.apply : re-sync des sliders inclus —
        // pas de setter maison, route unique).
        const bhost = document.getElementById('composerBatchParams');
        if (window.WamaParams && bhost) {
            const vals = { model: fd.model || 'auto:text-to-music', duration: fd.duration || 10 };
            if (fd.outputFormat) vals.output_format = fd.outputFormat;
            if (fd.outputQuality) vals.output_quality = fd.outputQuality;
            WamaParams.apply(bhost, vals);   // une clé absente n'écrase pas le champ
        }
        new bootstrap.Modal(document.getElementById('batchSettingsModal')).show();
    });

    // ▶ de LOT — suite DÉCLARÉE : composer insère les cards démarrées et lance leur
    // polling au lieu de recharger. C'est une divergence RÉELLE (3 apps sur 6 le font),
    // établie en lisant ce que le code fait après le POST — pas son nom.
    WamaQueueActions.onBatchStarted(function (d) {
        (d.started || []).forEach(function (id) { insertRenderedCard(id); startPolling(id); });
    });

    // 🗑 RÉSIDU de suppression — la brique commune fait tout le reste (portage 2026-08-23).
    WamaQueueActions.onDeleted(function () { checkEmptyState(); });

    // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js). Le bouton `.settings-btn`
    // et la délégation appartiennent désormais au commun ; l'app ne garde que le remplissage de
    // SA modale. Remplace la branche `closest('.settings-btn')` du handler délégué local
    // (portage 2026-08-23, ATOMIQUE : la branche a été retirée dans le même geste, sinon le clic
    // partait deux fois).
    // Le CYCLE complet (rendre du schéma → greffer le pied → afficher → lire → enregistrer →
    // enchaîner) est la brique commune `WamaParams.settingsModal` (portage 2026-09-24 — la modale
    // statique `#settingsModal` du gabarit, le remplissage par id et `_postSettings` vivaient ici).
    // Les VALEURS viennent des data-* du gear (brique `card_gear`), lues par LE lecteur unique
    // `WamaInspector.gearValues` ; l'app ne garde que ses hooks : l'estimation dans la modale
    // (`decorate`), le drapeau `restart` que la vue lit (`collect`), la card re-rendue (`onSaved`).
    WamaQueueActions.onSettings(function (id, settingsBtn) {
        const schema = window.COMPOSER_PARAMS_SCHEMA || [];
        const card = (settingsBtn && settingsBtn.closest('.wama-card')) || settingsBtn;
        WamaParams.settingsModal({
            id: id,
            title: 'Paramètres de génération',
            titleIcon: 'fa-cog',
            schema: schema,
            values: WamaInspector.gearValues(card, schema.map(function (p) { return p.name; })),
            formClass: 'composer-settings-form',
            footerTplId: 'composerSettingsFooterTpl',
            saveUrl: WamaApp.getUrl(APP.settingsUrlTemplate, id),
            csrf: CSRF,
            decorate: function (host) {
                _wireSettingsEstimate(host);
                _wireSettingsPrompt(host, card);
            },
            collect: function (fd, host, data, restart) {
                fd.append('restart', restart ? '1' : '0');
                // Prompt à DEUX ÉTATS : le texte affiché + son état — `apply_prompt_state` (vue)
                // l'écrit dans `prompt` (le sien) ou `prompt_processed` (l'enrichi).
                const p = host.querySelector('#settingsPrompt');
                const ctrl = p && window.WamaPromptEnrich && WamaPromptEnrich.get(p);
                if (ctrl) {
                    fd.set('prompt', p.value);
                    fd.set('prompt_state', ctrl.snapshot().state);
                }
            },
            errorOf: function (resp) { return resp && resp.success ? null : ((resp && resp.error) || 'inconnue'); },
            onSaved: function (gid, restart, resp) {
                // Re-rend la card serveur (SOURCE UNIQUE du markup) → data-* frais : modale ET
                // inspecteur relisent les valeurs ENREGISTRÉES ; le statut réel vient du rendu.
                if (window.WamaEta && resp.restarted) WamaEta.reset(gid);
                insertRenderedCard(gid);
                if (resp.restarted) startPolling(parseInt(gid));
            },
        });
    });

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

    // Brique commune `WamaApp.addToQueue` (portage 2026-10-01) : bouton « Envoi… », consigne,
    // fichiers JOINTS ou DÉSIGNÉS par port, URL de mélodie en repli (un fichier joint prime :
    // `ensure_local_input` la télécharge au lancement), refus dit, toast. AJOUTE à la file, ne
    // lance rien (règle des deux temps) : la card arrive en attente, son ▶ la lance.
    // Prompt VIDE autorisé = génération ALÉATOIRE (le placeholder de la card l'annonce ;
    // backend generate_unconditional / chroma-seule). Cf. INPUT_MODEL_MATCHING.md.
    if (generateBtn && window.WamaApp && WamaApp.addToQueue) {
        // Les ports de la card — le morceau à reprendre (cover) : audio `work_audio` (MusicGen
        // Melody), partition `work_score` (YuE2) — sont DÉRIVÉS des capacités des modèles ; chacun
        // est posté sous le nom de son PORT (2026-10-03). Seul le port principal a un champ URL.
        const ports = Array.from(document.querySelectorAll('#composerNewCard [data-port-pane]'))
            .filter((pane) => pane.dataset.portInput && pane.dataset.portPane !== 'lot')
            .map((pane) => (pane.dataset.portInput === 'melodyInput'
                ? { inputId: 'melodyInput', field: pane.dataset.portPane,
                    urlField: 'source_url', urlInputId: 'melodyUrlInput' }
                : { inputId: pane.dataset.portInput, field: pane.dataset.portPane }));
        WamaApp.addToQueue({
            url:       APP.generateUrl,
            csrfToken: CSRF,
            button:    generateBtn,
            prompt:    { inputId: promptInput ? promptInput.id : '', field: 'prompt' },
            // Référence fournie → jointe. Plus de test hardcodé par modèle : l'appariement
            // WamaInputMatch garantit qu'un modèle incompatible n'est pas sélectionnable.
            ports:     ports,
            extraFields: function (fd) {
                fd.append('model', modelSelect?.value || 'auto:text-to-music');
                fd.append('duration', getSelectedDuration());
                // Curseur rapide/qualité du volet (chantier C) — lu au lancement si le modèle est auto-*.
                fd.append('quality_intent', document.getElementById('qualityIntent')?.value || '');
                fd.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
                fd.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
            },
            // La mélodie et la partition RESTENT : plusieurs variations sur une même référence
            // s'enchaînent ; seule la consigne se vide.
            reset:   false,
            onAdded: function (data) {
                if (promptInput) promptInput.value = '';
                insertRenderedCard(data.id);
            },
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
            const firstMusic = Array.from(modelSelect.options).find(o => o.value.includes('musicgen'));
            if (firstMusic) modelSelect.value = firstMusic.value;
            updateEstimate();
        }
        // Le défaut du SCHÉMA (`params.py`, 3:30), jamais une copie ici ; le curseur généré est
        // relu au clic (il n'existe qu'après `WamaParams.render`).
        const slider = document.getElementById('durationSlider');
        const declared = (window.COMPOSER_PARAMS_SCHEMA || []).find((p) => p.name === 'duration');
        if (slider && declared && declared.default != null) {
            slider.value = declared.default;
            slider.dispatchEvent(new Event('input', { bubbles: true }));
            if (durationDisplay) durationDisplay.textContent = _fmtDur(slider.value);
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
    // Card actions
    // ---------------------------------------------------------------------------
    //
    // Plus AUCUN gestionnaire de clic local sur les actions de card :
    //   • 🗑 item et actions de LOT (▶ ⧉ 🗑 ⚙) : brique commune queue-actions.js (portage
    //     2026-08-23) — la suite de 🗑 est déclarée par `onDeleted`, plus bas, et ▶ de lot garde
    //     sa suite déclarée (insertion + polling) parce qu'elle DIFFÈRE réellement ;
    //   • médiathèque : le bouton dédié `.export-btn` et son handler sont RETIRÉS le 2026-09-18
    //     (demande de Fabien). Le geste est celui du menu « … » / clic droit, commun aux 10 apps
    //     (`wama-card-menu.js` → route commune `media_library:api_export_item`), avec l'état
    //     persisté (coche) et le retrait. Ce handler ne savait ni l'un ni l'autre.

    // Settings save — pied CONFORME : « Enregistrer » (sans relance) / « Enregistrer et relancer ».
    // Sauvegarde BATCH (modale dédiée) : champs lus GÉNÉRIQUEMENT (WamaParams.read) — un param
    // ajouté au schéma en contexte batch est posté automatiquement (batch_update les accepte).
    const batchSaveBtn = document.getElementById('batchSettingsSaveBtn');
    if (batchSaveBtn) batchSaveBtn.addEventListener('click', () => {
        const bid = document.getElementById('batchSettingsBatchId').value;
        const host = document.getElementById('composerBatchParams');
        const vals = (window.WamaParams && host) ? WamaParams.read(host) : {};
        const fd = new FormData();
        fd.append('csrfmiddlewaretoken', CSRF);
        Object.keys(vals).forEach((k) => fd.append(k, vals[k]));
        fetch(WamaApp.getUrl(APP.batchUpdateUrlTemplate, bid), { method: 'POST', body: fd })
            .then(r => r.json().then(data => ({ ok: r.ok, data })))
            .then(({ ok, data }) => {
                // Un réglage REFUSÉ (400) ne ferme plus la modale en silence : aucune fille
                // n'a été écrite, on le dit.
                if (!ok || data.error) { WamaApp.toast(data.error || 'Erreur', 'error'); return; }
                bootstrap.Modal.getInstance(document.getElementById('batchSettingsModal'))?.hide();
                location.reload();
            })
            .catch(() => WamaApp.toast('Erreur réseau', 'error'));
    });

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

        // Border — les classes d'ÉTAT (processing/success/error) ne sont plus posées ici : le CSS
        // les lit sur `data-status`, écrit juste au-dessus (2026-09-18). Restent les bordures
        // Bootstrap, qui sont une AUTRE famille — la couleur de bord de la card, pas l'état.
        ['border-warning', 'border-success', 'border-danger', 'border-secondary']
            .forEach(c => card.classList.remove(c));
        const borderMap = { RUNNING: ['border-warning'], SUCCESS: ['border-success'],
                            FAILURE: ['border-danger'], PENDING: ['border-secondary'] };
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

        // Card v3 (13/08) : le badge n'existe plus — point d'état + libellé mis à jour en
        // place (le re-rendu serveur complet n'arrive qu'en FIN de tâche sur composer).
        const dot = card.querySelector('.wama-status-dot');
        if (dot) {
            dot.dataset.s = status;
            const lbl = dot.nextElementSibling;
            const labelsV3 = { PENDING: 'En attente', RUNNING: 'En cours', SUCCESS: 'Terminé', FAILURE: 'Échec' };
            if (lbl) lbl.textContent = labelsV3[status] || status;
        }

        // PROCESS de la card (P5) : les lignes bougent pendant le traitement — brique commune.
        if (window.WamaApp && WamaApp.updateProcessRows) WamaApp.updateProcessRows(card, data?.processes);

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

    // Auto-start du polling des items LANCÉS au chargement — état lu sur data-status (plus de
    // détection par TEXTE de badge — audit B2-6). ⚠ PENDING n'en fait plus partie (2026-09-29) :
    // `begin_processing` pose RUNNING dès l'acceptation (puis AWAITING_RESOURCES si la tâche
    // attend sa VRAM) ; un PENDING n'a jamais été lancé et l'interroger ne s'arrêtait jamais.
    document.querySelectorAll('.generation-card').forEach(card => {
        if (card.dataset.status === 'RUNNING' || card.dataset.status === 'AWAITING_RESOURCES') {
            startPolling(parseInt(card.dataset.id));
        }
    });

    // Bouton de cycle commun ▶/⏹/↻ : wire (start/restart→/composer/start, stop→/composer/stop) + auto-sync.
    (function initCycleButton() {
        const q = document.getElementById('composerQueue');
        if (!window.WamaCycleButton || !q) return;
        WamaCycleButton.wire(q, {
            start: async (id, btn) => {
                const card = q.querySelector(`.generation-card[data-id="${id}"]`);
                if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') {
                    try { await fetch(WamaApp.getUrl(APP.stopUrlTemplate, id), { method: 'POST', headers: { 'X-CSRFToken': CSRF } }); } catch (e) {}
                }
                // ▶ d'UN process (bande des process, `data-process`) : lancement BORNÉ, route
                // `start/<id>/<process>/` ; sans attribut, le ▶ de la card lance tout ce qui est dû.
                const process = btn && btn.dataset ? btn.dataset.process : '';
                const startUrl = WamaApp.getUrl(APP.startUrlTemplate, id) + (process ? process + '/' : '');
                try {
                    const r = await fetch(startUrl, { method: 'POST', headers: { 'X-CSRFToken': CSRF } });
                    if (!r.ok) {
                        let why = 'lancement refusé';
                        try { why = (await r.json()).error || why; } catch (e) {}
                        if (window.WamaApp && WamaApp.toast) WamaApp.toast(why, 'error');
                        return;
                    }
                    if (card) card.dataset.status = 'RUNNING';
                    // Re-rendu SERVEUR, comme au ⏹ : une card rendue en attente n'a pas de barre
                    // (`_generation_card.html`, `status != 'PENDING'`) — le suivi n'avait rien à
                    // remplir et la barre n'apparaissait qu'au rechargement (Fabien, 2026-10-04).
                    insertRenderedCard(id);
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
                // Re-rendu SERVEUR : sans lui la card restait « en cours » si aucun poller
                // n'était actif (même défaut que l'avatarizer, corrigé en famille — 17/08).
                insertRenderedCard(id);
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
    // Redemandée par la brique commune (WamaApp.fetchCard, portage 2026-09-22) ; un serveur
    // qui ne répond pas → rechargement, comme avant.
    function insertRenderedCard(id) {
        WamaApp.fetchCard(APP.cardHtmlUrlTemplate, id).then(fresh => {
            if (!fresh) { location.reload(); return; }
            const queue = document.getElementById('composerQueue');
            if (!queue) return;
            const existing = queue.querySelector(`.generation-card[data-id="${id}"]`);
            if (existing) existing.replaceWith(fresh);
            else queue.prepend(fresh);
            checkEmptyState();
        });
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
