/**
 * WAMA Describer - Queue Management JavaScript
 */

document.addEventListener('DOMContentLoaded', function() {
    const config = window.DESCRIBER_CONFIG || {};

    // DOM Elements (zone de dépôt et sélecteurs de fichier/dossier : câblés par WamaImport, plus bas)
    const queueContainer = document.getElementById('descriptionQueue');
    const queueCount = document.getElementById('queueCount');

    // Bouton de cycle commun ▶/⏹/↻ : câblage délégué (start/restart→startDescription, stop→stopDescription)
    // + auto-sync sur data-status (l'icône suit le statut, plug-and-play). startDescription/stopDescription
    // sont des déclarations de fonction (hoistées) → référençables ici.
    // `process` : le ▶ d'UN process de la bande (2026-10-13, pipeline) → lancement borné (route
    // `start/<id>/<process>/`) ; vide pour le ▶ de la card, qui lance tout ce qui est dû.
    if (window.WamaCycleButton && queueContainer) {
        WamaCycleButton.wire(queueContainer, {
            start: (id, btn, process) => startDescription(id, process),
            stop: (id) => stopDescription(id),
        });
        WamaCycleButton.autoSync({ container: queueContainer, cardSelector: '.wama-card' });
    }

    // Global options
    const outputStyle = document.getElementById('output_style');
    const outputLanguage = document.getElementById('output_language');
    const maxLength = document.getElementById('max_length');
    const maxLengthValue = document.getElementById('max_length_value');

    // Action buttons
    const startAllBtn = document.getElementById('startAllBtn');
    // (`downloadAllBtn` : const retirée le 2026-08-30 avec son handler — bouton = brique commune.)
    const clearAllBtn = document.getElementById('clearAllBtn');

    // Progress tracking — boucle COMMUNE `WamaApp.Poller` (2026-10-13 — un `setInterval` local à
    // la seconde, qui relançait sans attendre la réponse et tournait en onglet caché).
    const poller = new WamaApp.Poller({
        urlTemplate: config.urls.progress,
        interval: 1000,
        maxFails: Infinity,
        onError: (id, error) => console.error('Polling error:', error),
        onData: (id, data) => {
            const card = document.querySelector(`.wama-card[data-id="${id}"]`);
            if (!card) { stopPolling(id); return; }

            updateCardStatus(card, data.status, data.progress, data);

            // Update partial result if available
            if (data.partial_text) {
                const preview = card.querySelector('.result-preview');
                if (preview) preview.textContent = data.partial_text.substring(0, 150) + '...';
            }

            if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                stopPolling(id);
                if (window.WamaFM) WamaFM.processed();  // sortie créée → refresh filemanager
                // Transition d'état → re-rendu SERVEUR (source unique du markup). AUSSI en
                // FAILURE depuis la card v3 (13/08) : l'update en place ciblait .status-badge,
                // qui n'existe plus — sans re-rendu la card restait affichée « En cours ».
                refreshCard(card.dataset.id);
            }
        },
    });

    // Update max length display
    if (maxLength && maxLengthValue) {
        maxLength.addEventListener('input', function() {
            maxLengthValue.textContent = this.value;
        });
    }

    // === Voie d'import : brique commune WamaImport (wama-import.js) — portage 2026-09-07 ===
    //
    // 3ᵉ app EN PLACE à l'adopter (plan « fichiers d'entrée », MEDIA_STORAGE_TIERING §8 ;
    // inventaire ROUTE §Portage F2). Ce qui vivait ici — sélecteur, bouton « parcourir » (jamais
    // rendu par la card commune), drop récursif, sélecteur de dossier, upload séquentiel,
    // consolidation `ids`, reload — est le contrat de la brique. L'app ne DÉCLARE que :
    //   • `extraFields`  : les 3 réglages du volet postés avec chaque dépôt (mêmes valeurs que
    //                      `formDataBuilder` du lot, dans le gabarit) ;
    //   • `afterImport`  : la BIFURCATION propre au describer — 1 élément créé → la card arrive
    //                      RENDUE DU SERVEUR (`refreshCard`, insérée en tête, sans reload) ;
    //                      plusieurs → reload (la consolidation par NATURE vient d'être faite
    //                      par la brique, `describer:consolidate` lit JSON comme champ répété).
    // RETIRÉ en connaissance de cause : la branche « drop depuis le FileManager »
    // (`FileManager.getFileManagerData(e)` puis `importToApp`). Mesuré le 07/09 : le type MIME
    // `application/x-wama-file` qu'elle lit n'est ÉMIS NULLE PART ; un glisser jstree (vakata)
    // ne produit AUCUN événement `drop` natif — il est pris par le canal GLOBAL de
    // `filemanager.js` (`dnd_stop.vakata`), qui importe côté serveur pour toute card « crée »
    // (MEDIA_STORAGE_TIERING §8.6 D5). La branche ne pouvait donc jouer que sur un texte
    // glissé contenant « / » : un chemin déposé à la main, sans garde. Un canal de moins.
    if (typeof window.WamaImport === 'function') {
        window._import = WamaImport({
            uploadUrl:        config.urls.upload,
            consolidateUrl:   config.urls.consolidate,
            consolidateField: 'ids',
            csrfToken:        config.csrfToken,
            dropZoneId:       'dropZone',
            fileInputId:      'fileInput',
            folderInputId:    'describerFolderInput',
            batch:            window._batchImport,
            extraFields:      function (fd) {
                fd.append('output_style', outputStyle ? outputStyle.value : 'detailed');
                fd.append('output_language', outputLanguage ? outputLanguage.value : 'fr');
                fd.append('max_length', maxLength ? maxLength.value : '500');
            },
            afterImport:      function (ids) {
                if (ids.length === 1) { refreshCard(ids[0]); updateQueueCount(); return; }
                window.location.reload();
            },
        });
    } else {
        // Défaut le plus silencieux qui soit (une zone de dépôt que rien n'écoute) → on le DIT.
        showToast("Voie d'import non chargée (wama-import.js) — dépôt impossible", 'danger');
        console.error('[Describer] WamaImport absent : wama-import.js non chargé par le gabarit');
    }

    // === Queue Management ===
    // (getFormatLabel / getLanguageLabel RETIRÉS le 2026-09-24 : seuls consommateurs = la repeinte
    // manuelle de la card après ⚙, remplacée par le re-rendu serveur `refreshCard`.)

    function bindCardEvents(card) {
        // Start button
        const startBtn = card.querySelector('.start-btn');
        if (startBtn) {
            startBtn.addEventListener('click', () => startDescription(card.dataset.id));
        }

        // 🗑 : plus de bind PAR CARD ici — brique commune queue-actions.js, délégation unique
        // (portage 2026-08-23). La suite est déclarée par `onDeleted`, plus bas.

        // 👁 : plus de bouton ni de modale de résultat propres (retirés le 2026-10-13, R125) — le
        // résultat s'ouvre par l'aperçu de la card ou du volet, dans la visionneuse commune.

        // ⚙ : plus rien à lier ICI. La brique commune (queue-actions.js) délègue une fois pour
        // toutes ; ce bind PAR CARD était précisément le défaut visé par CARD_DESIGN §3 (N
        // handlers pour N cards) et il fallait le rejouer à chaque re-render. L'ouvreur est
        // déclaré une seule fois, plus bas (portage 2026-08-23).
    }

    // Bind events for existing cards
    document.querySelectorAll('.wama-card').forEach(bindCardEvents);

    // Reprise du suivi des cards DÉJÀ en cours à l'ouverture de la page. Lu sur l'état de
    // l'ÉLÉMENT (`data-element-status`, 2026-10-13) : `data-status` est l'état MONTRÉ, déduit des
    // process — une card terminée dont un optionnel reste à compléter s'y montre « en attente »,
    // et la suivre la ferait recharger en boucle. (La classe `.processing`, lue jusqu'au
    // 2026-09-24, avait été retirée des cards le 2026-09-18 : une card en cours restait figée.)
    document.querySelectorAll('.wama-card[data-id]').forEach(card => {
        const status = (card.dataset.elementStatus || card.dataset.status || '').toUpperCase();
        if (status === 'RUNNING' || status === 'AWAITING_RESOURCES') startPolling(card.dataset.id);
    });

    // === Settings Modal ===
    // ⚙ item : le CYCLE complet (rendre du schéma → greffer le pied → afficher → lire →
    // enregistrer → enchaîner) est la brique commune `WamaParams.settingsModal` (portage
    // 2026-09-24 — la modale statique `#settingsModal` du gabarit, `openSettings`/`saveSettings`
    // et `updateCardSettings` (qui repeignait la card à la main) vivaient ici). Les VALEURS
    // viennent des data-* du gear (brique `card_gear`), lues par LE lecteur unique
    // `WamaInspector.gearValues` ; la card enregistrée est RE-RENDUE par le serveur (`refreshCard`).
    function openSettings(id, btn) {
        const schema = window.WAMA_DESCRIBER_SCHEMA || [];
        const card = (btn && btn.closest('.wama-card')) || btn;
        return WamaParams.settingsModal({
            id: id,
            title: 'Paramètres de description',
            titleIcon: 'fa-cog',
            schema: schema,
            values: WamaInspector.gearValues(card, schema.map(function (p) { return p.name; })),
            formClass: 'describer-settings-form',
            footerTplId: 'describerSettingsFooterTpl',
            saveUrl: config.urls.updateSettings.replace('/0/', `/${id}/`),
            csrf: config.csrfToken,
            onSaved: function (did, restart) {
                refreshCard(did);
                if (restart) startDescription(did);
            },
        });
    }

    // Modale BATCH DÉDIÉE générée du schéma (context 'batch', contrat reader — remplace le
    // détournement de la modale item par _settingsBatchId + titre échangé, 17/08).
    // ⚙ de LOT — ouvreur DÉCLARÉ à la brique commune (queue-actions.js), portage 2026-08-23.
    WamaQueueActions.onBatchSettings(function (bid, btn) { openBatchSettings(btn); });

    // Duplication : gérée par la brique commune queue-actions.js (base.html) via
    // le bouton [data-duplicate-url] — pas de handler local (un doublon ici
    // provoquait DEUX copies par clic).

    function openBatchSettings(btn) {
        const bid = btn.dataset.batchId;
        const modalEl = document.getElementById('batchSettingsModal');
        if (!modalEl) return;
        document.getElementById('batchSettingsBatchId').value = bid;
        const lbl = document.getElementById('batchSettingsBatchLabel');
        if (lbl) lbl.textContent = '#' + bid;
        // Défauts lus sur la 1re card FILLE, posés par la brique (WamaParams.apply : coercition
        // checkbox + re-sync des sliders — pas de _set maison, route unique).
        const group = btn.closest('.batch-group');
        const first = group ? group.querySelector('.settings-btn') : null;
        const host = document.getElementById('describerBatchParams');
        if (window.WamaParams && host && first) {
            // LE lecteur unique des data-* du gear (`WamaInspector.gearValues`, celui de la modale
            // d'élément) sur les noms du SCHÉMA — la liste de cinq réglages écrite ici à la main
            // ignorait tout réglage ajouté (les modèles et le curseur, 2026-10-13).
            const schema = window.WAMA_DESCRIBER_SCHEMA || [];
            const vals = WamaInspector.gearValues(first.closest('.wama-card') || first,
                                                  schema.map(function (p) { return p.name; }));
            WamaParams.apply(host, vals);   // une clé absente n'écrase pas le champ
        }
        new bootstrap.Modal(modalEl).show();
    }

    async function saveBatchSettings(startAfterSave) {
        const bid = document.getElementById('batchSettingsBatchId').value;
        // Lecture GÉNÉRIQUE (WamaParams.read) : un param ajouté au schéma en contexte batch est
        // posté sans toucher ce code (_apply_description_options coerce int/bool côté serveur).
        const host = document.getElementById('describerBatchParams');
        const payload = (window.WamaParams && host) ? WamaParams.read(host) : {};
        try {
            await fetch(config.urls.batchUpdate.replace('/0/', `/${bid}/`), {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (startAfterSave) {
                await fetch(config.urls.batchStart.replace('/0/', `/${bid}/`), {
                    method: 'POST', headers: { 'X-CSRFToken': config.csrfToken },
                });
            }
        } catch (e) { /* ignore */ }
        window.location.reload();
    }
    document.getElementById('batchSaveSettingsBtn')
        ?.addEventListener('click', () => saveBatchSettings(false));
    document.getElementById('batchSaveStartBtn')
        ?.addEventListener('click', () => saveBatchSettings(true));

    // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js). Une seule délégation pour
    // toute la file, y compris les cards rendues APRÈS le chargement : le bind par card de
    // `bindCardEvents` a été retiré dans le même geste (portage 2026-08-23).
    WamaQueueActions.onSettings(function (id, btn) { openSettings(id, btn); });

    // === Description Processing ===

    // ⏹ Stop : arrête le traitement (endpoint commun) → item relançable (↻ via autoSync sur data-status).
    async function stopDescription(id) {
        const card = document.querySelector(`.wama-card[data-id="${id}"]`);
        try {
            const response = await fetch(config.urls.stop.replace('/0/', `/${id}/`), {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
            });
            const data = await response.json();
            if (card && data && data.status) card.dataset.status = data.status;  // → autoSync repasse en ↻
        } catch (e) { /* non-fatal */ }
    }

    async function startDescription(id, process) {
        const card = document.querySelector(`.wama-card[data-id="${id}"]`);
        if (!card) return;

        // Relance PENDANT le traitement (modale « Enregistrer & démarrer ») : stopper d'abord pour
        // éviter le 409 « déjà en cours », puis relancer avec les params à jour.
        if ((card.dataset.status || '').toUpperCase() === 'RUNNING') {
            card.dataset.status = 'PENDING';
            await stopDescription(id);
        }

        // Disable start button immediately to prevent double-clicks
        const startBtn = card.querySelector('.start-btn');
        if (startBtn) startBtn.disabled = true;

        try {
            // `process` : le ▶ d'un process de la bande — adresse composée par la brique commune.
            const url = WamaCycleButton.processUrl(config.urls.start.replace('/0/', `/${id}/`), process);
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken,
                    'Content-Type': 'application/json'
                }
            });

            const data = await response.json();

            if (data.error) {
                showToast('Erreur: ' + data.error, 'danger');
                if (startBtn) startBtn.disabled = false;
                return;
            }

            updateCardStatus(card, 'RUNNING', 0);
            startPolling(id);

        } catch (error) {
            console.error('Start error:', error);
            showToast('Erreur lors du demarrage', 'danger');
            if (startBtn) startBtn.disabled = false;
        }
    }

    function startPolling(id) { poller.start(id); }

    function stopPolling(id) { poller.stop(id); }

    function updateCardStatus(card, status, progress, data) {
        // Always show 100% when done
        if (status === 'SUCCESS') progress = 100;

        // Update status badge
        const badge = card.querySelector('.status-badge');
        if (badge) {
            badge.textContent = status;
            badge.className = 'badge status-badge ';
            switch (status) {
                case 'PENDING': badge.classList.add('bg-secondary'); break;
                case 'RUNNING': badge.classList.add('bg-warning'); break;
                case 'SUCCESS': badge.classList.add('bg-success'); break;
                case 'FAILURE': badge.classList.add('bg-danger'); break;
            }
        }

        // Update progress bar
        const progressBar = card.querySelector('.wama-progress-fill');
        if (progressBar) {
            progressBar.style.width = progress + '%';
            if (status === 'RUNNING') progressBar.classList.add('active');
            else progressBar.classList.remove('active');
        }

        const progressText = card.querySelector('.progress-text');
        if (progressText) {
            progressText.textContent = progress + '%';
        }

        // ETA (moteur commun) — seed depuis l'estimateur serveur (service-based → modèle chargé)
        if (window.WamaEta) {
            WamaEta.render(card.querySelector('.wama-eta'),
                           WamaEta.update(card.dataset.id, {
                               progress: progress, status: status,
                               seedSeconds: data && data.estimated_seconds,
                               modelLoaded: false,
                           }));
        }

        // Les PROCESS de la card (bande commune) suivent le traitement en place.
        if (data && window.WamaApp && WamaApp.updateProcessRows) WamaApp.updateProcessRows(card, data.processes);

        // `data-status` pilote TOUT : la couleur d'état (CSS sur l'attribut) et le bouton de
        // cycle (WamaCycleButton.autoSync, qui passe en ⏹ Stop sans qu'on retire de bouton).
        // Les classes processing/success/error posées ici recopiaient l'information — retirées
        // le 2026-09-18. `data-element-status` : l'état de l'ÉLÉMENT, sur lequel le suivi se fie.
        card.dataset.status = status;
        card.dataset.elementStatus = status;
    }

    // Card RENDUE SERVEUR — source unique : partial _description_card.html via
    // describer:card_html (recette T+C). Remplace updateCardWithResult (~60 lignes
    // d'injection de boutons/preview qui divergeaient du serveur) — 2026-07-05.
    // Card RENDUE SERVEUR — source unique : partial _description_card.html via
    // describer:card_html. Remplace la card si presente, sinon INSERE en tete de file
    // (upload). Re-bind obligatoire : les events sont attaches PAR card (pas de
    // delegation) — le refresh v1 les perdait (corrige 2026-07-05).
    // Redemandée par la brique commune (WamaApp.fetchCard, portage 2026-09-22 — la copie
    // locale du fetch + parse vivait ici).
    function refreshCard(id) {
        WamaApp.fetchCard(config.urls.cardHtml, id).then(fresh => {
            const queue = document.getElementById('descriptionQueue');
            if (!queue || !fresh) return;
            const existing = queue.querySelector(`.wama-card[data-id="${id}"]`);
            if (existing) existing.replaceWith(fresh);
            else {
                queue.querySelector('.empty-queue')?.remove();
                queue.prepend(fresh);
            }
            bindCardEvents(fresh);
        });
    }

    // 🗑 RÉSIDU de suppression — la brique commune fait tout le reste (portage 2026-08-23).
    WamaQueueActions.onDeleted(function (id) {
        stopPolling(id);
        updateQueueCount();
        showToast('Description supprimee', 'success');
    });

    // === Batch Actions ===

    if (startAllBtn) {
        startAllBtn.addEventListener('click', async () => {
            try {
                const response = await fetch(config.urls.startAll, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': config.csrfToken
                    }
                });

                const data = await response.json();

                if (data.started && data.started.length > 0) {
                    data.started.forEach(id => startPolling(id));
                    showToast(`${data.count} description(s) lancee(s)`, 'success');
                } else {
                    showToast('Aucune description a lancer', 'info');
                }

            } catch (error) {
                console.error('Start all error:', error);
                showToast('Erreur', 'danger');
            }
        });
    }

    // ⬇ « Télécharger tout » : PLUS de handler ici (2026-08-30) — bouton rendu par la brique
    // commune _download_button (menu des formats déclarés, navigation par <a> du menu).
    // Un window.location au clic détournerait l'OUVERTURE du menu.

    if (clearAllBtn) {
        clearAllBtn.addEventListener('click', async () => {
            if (!confirm('Supprimer toutes les descriptions ?')) return;

            try {
                const response = await fetch(config.urls.clearAll, {
                    method: 'POST',
                    headers: {
                        'X-CSRFToken': config.csrfToken
                    }
                });

                const data = await response.json();
                showToast(`${data.deleted} description(s) supprimee(s)`, 'success');
                window.location.reload();

            } catch (error) {
                console.error('Clear all error:', error);
                showToast('Erreur', 'danger');
            }
        });
    }

    // Reset settings
    document.getElementById('resetOptions')?.addEventListener('click', () => {
        const defaults = {
            'output_style': 'detailed',
            'output_language': 'fr',
            'max_length': '500',
        };
        Object.entries(defaults).forEach(([id, val]) => {
            const el = document.getElementById(id);
            if (el) el.value = val;
            localStorage.removeItem(`describer_setting_${id}`);
        });
        // Reset range display
        const maxLengthVal = document.getElementById('max_length_value');
        if (maxLengthVal) maxLengthVal.textContent = '500';
        // Reset checkboxes
        const generateSummary = document.getElementById('globalGenerateSummary');
        if (generateSummary) generateSummary.checked = false;
        const verifyCoherence = document.getElementById('globalVerifyCoherence');
        if (verifyCoherence) verifyCoherence.checked = false;
    });

    // (Barre globale + ETA : brique commune wama-global-progress.js. La copie locale, neutralisée
    // par un `return` et pourtant rappelée toutes les 5 s, est retirée le 2026-10-13.)

    function updateQueueCount() {
        const cards = document.querySelectorAll('.wama-card');
        if (queueCount) {
            queueCount.textContent = cards.length;
        }
    }

    // === Utilities ===

    function showToast(message, type = 'info') {
        // Brique commune (wama-app-base.js) — plus de dialogue natif bloquant
        if (window.WamaApp && WamaApp.toast) WamaApp.toast(message, type);
        else console.info('[Describer]', message);
    }

    // ── Batch template download — now served by Django view ───────────────
    // The batchTemplateLink anchor uses href="{% url 'describer:batch_template' %}" directly.

    // 🗑 et ⧉ de LOT : brique commune queue-actions.js (portage 2026-08-23) — mêmes
    // confirm+POST+reload que dans 7 autres apps, URLs émises par `_batch_card.html`.

    // ▶ de LOT — suite DÉCLARÉE : describer rafraîchit les cards démarrées et lance leur
    // polling au lieu de recharger (divergence RÉELLE, mesurée — cf. la brique).
    WamaQueueActions.onBatchStarted(function (data) {
        (data.started || []).forEach(id => { refreshCard(id); startPolling(id); });
    });

});
