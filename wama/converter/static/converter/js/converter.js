/**
 * WAMA Converter — Frontend Logic
 *
 * Responsibilities:
 *  - File upload (drag & drop + file input) with media-type detection
 *  - Output format dropdown population
 *  - Options panels (image / video / audio) — main panel + modal
 *  - Conversion profiles (save / load / delete)
 *  - Job queue rendering & polling
 *  - Start / delete / duplicate / clear-all / start-all actions
 *  - Per-job settings modal (edit output_format + options, then restart)
 */

(function () {
    'use strict';

    const APP       = window.CONVERTER_APP;
    const csrf      = APP.csrfToken;
    const FORMATS   = APP.supportedFormats;

    // Extension → media type lookup
    const EXT_TO_TYPE = {};
    Object.entries(FORMATS).forEach(([type, spec]) => {
        spec.input.forEach(ext => { EXT_TO_TYPE[ext.replace('.', '')] = type; });
    });

    // ── DOM refs ─────────────────────────────────────────────────────────────
    const dropZone       = document.getElementById('converterDropZone');
    const fileInput      = document.getElementById('converterFileInput');
    const mediaTypeBadge = document.getElementById('converterMediaTypeBadge');
    const queue          = document.getElementById('converterQueue');
    // État vide : ADOPTE la brique commune `WamaApp.emptyState` (2026-08-23). Le `const`
    // précédent (`getElementById('converterEmptyState')`) était DÉCLARÉ ET JAMAIS UTILISÉ :
    // l'app n'avait aucun état vide côté JS, elle rechargeait la page. Le retrait de card
    // désormais chirurgical (brique queue-actions) rend cette bascule nécessaire — sans elle,
    // supprimer la dernière conversion laissait une file vide SANS message.
    const _empty = WamaApp.emptyState({
        container: document.getElementById('converterQueue'),
        cardSelector: '.job-card',
        html: '<i class="fas fa-exchange-alt fa-2x mb-2" style="color:#20c997; opacity:.4;"></i>'
            + '<p class="mb-0">Aucune conversion — déposez un fichier pour commencer</p>',
    });

    // Options panels

    // Global action buttons
    const startAllBtn = document.getElementById('converterStartAllBtn');
    const downloadAllBtn = document.getElementById('converterDownloadAllBtn');
    const clearAllBtn = document.getElementById('converterClearAllBtn');

    // Profile dropdown
    const profileSelect    = document.getElementById('converterProfileSelect');
    const profileDeleteBtn = document.getElementById('converterProfileDeleteBtn');

    // ── State ─────────────────────────────────────────────────────────────────
    let currentMediaType = null;
    const pollingTimers  = {};   // { jobId: intervalId }
    let cachedProfiles   = [];   // last fetched list

    // ── Helpers ───────────────────────────────────────────────────────────────

    function csrfPost(url, formData) {
        if (!formData) formData = new FormData();
        if (!formData.has('csrfmiddlewaretoken')) {
            formData.append('csrfmiddlewaretoken', csrf);
        }
        return fetch(url, { method: 'POST', body: formData });
    }

    function urlFor(template, id) {
        return template.replace('/0/', '/' + id + '/');
    }

    function detectMediaType(filename) {
        const ext = filename.split('.').pop().toLowerCase();
        return EXT_TO_TYPE[ext] || null;
    }

    function formatLabel(type) {
        const labels = { image: 'Image', video: 'Vidéo', audio: 'Audio', document: 'Document' };
        return labels[type] || type;
    }

    // ── Main right-panel UI updates ───────────────────────────────────────────

    function setMediaType(type) {
        currentMediaType = type;
        // Badge
        if (!type) {
            mediaTypeBadge.innerHTML = '<span class="text-muted fst-italic">— aucun fichier sélectionné —</span>';
        } else {
            const colours = { image: 'success', video: 'primary', audio: 'warning', document: 'info' };
            const icons   = { image: 'image', video: 'film', audio: 'music', document: 'file-alt' };
            mediaTypeBadge.innerHTML =
                `<span class="badge bg-${colours[type] || 'secondary'}">` +
                `<i class="fas fa-${icons[type] || 'file'}"></i> ${formatLabel(type)}</span>`;
        }

        // Le TYPE détecté pilote le schéma : le champ caché `media_type` commande les
        // `show_if` (quels réglages sont visibles) ET le registre d'options `formats` (quels
        // formats de sortie sont proposés). Une seule déclaration fait les deux — plus de
        // dropdown peuplé à la main ni de panneaux montrés/cachés.
        applyOptionsToMainPanel(type, {});

        // Filter profile dropdown to current media type
        renderProfileDropdown(type);
    }

    // ── Zone de composition = le SCHÉMA (portage 2026-09-01) ────────────────────
    // Les champs de réglage écrits à la main ont disparu du gabarit : ils redisaient ce que
    // `params.py` déclare déjà, et cette double source avait produit la divergence du neutre
    // de rotation. Tout passe par l'hôte unique `#converterPanelParams`, rendu du schéma.
    function panelHost() { return document.getElementById('converterPanelParams'); }

    /** Réglages POSÉS dans le volet — hors `media_type` (piloté par la détection) et
     *  `output_format` (posté à part). Vides ignorés : « non réglé » doit rester
     *  distinguable, c'est ce qui laisse le préréglage agir (ROADMAP §23.2bis). */
    function readMainPanelOptions() {
        const host = panelHost();
        if (!host || !window.WamaParams) return {};
        const lus = WamaParams.read(host);
        const opts = {};
        Object.keys(lus).forEach(function (k) {
            if (k === 'media_type' || k === 'output_format') return;
            const v = lus[k];
            if (v === '' || v == null || v === false) return;
            opts[k] = v;
        });
        return opts;
    }

    /** Format de sortie choisi dans le volet ('' si aucun). */
    function panelOutputFormat() {
        const host = panelHost();
        return (host && window.WamaParams) ? (WamaParams.read(host).output_format || '') : '';
    }

    /** Applique des valeurs au volet (profil chargé, type détecté) — le `media_type` est
     *  posé AVEC, car c'est lui qui commande les `show_if` et la liste des formats. */
    function applyOptionsToMainPanel(mediaType, opts) {
        const host = panelHost();
        if (!host || !window.WamaParams || !window.CONVERTER_APP) return;
        const mt = mediaType || currentMediaType || '';
        // RE-RENDRE, et pas seulement appliquer : c'est le RENDU qui résout les options
        // dynamiques. Un `apply` seul changerait `media_type` sans re-borner la liste des
        // formats — elle resterait l'union de toutes les familles (mesuré : 37 formats
        // proposés pour une image, au lieu de ses 8).
        WamaParams.render(host, CONVERTER_APP.schema, {
            context: 'panel',
            values: Object.assign({ media_type: mt }, opts || {}),
            groups: CONVERTER_APP.groups,
        });
        // Fidélité au comportement d'avant : un type détecté propose d'emblée un format (le
        // dropdown d'origine sélectionnait le premier de la liste). Sans cela, déposer
        // exigerait un clic de plus — et le repli serveur (« dernier format utilisé pour ce
        // type ») ne serait jamais atteint, puisque l'envoi est refusé côté client.
        const sel = host.querySelector('[data-param="output_format"], #wp-panel-output_format');
        if (sel && !sel.value) {
            const premier = Array.from(sel.options).find(function (o) { return o.value; });
            if (premier) sel.value = premier.value;
        }
        window.CONVERTER_DEFAUTS = readMainPanelOptions();
    }

    // Upload UN fichier → retourne son job_id (ou null). PAS de reload ici :
    // le reload se fait une fois après la consolidation (handleFiles).
    async function uploadFile(file) {
        const mediaType = detectMediaType(file.name);
        if (!mediaType) { WamaApp.toast(`Format non supporté : ${file.name}`, 'warning'); return null; }
        const outputFmt = panelOutputFormat();
        if (!outputFmt) {
            WamaApp.toast('Choisissez un format de sortie avant d\'envoyer un fichier.', 'error');
            return null;
        }
        const opts = readMainPanelOptions();
        const fd   = new FormData();
        fd.append('file', file);
        fd.append('output_format', outputFmt);
        Object.entries(opts).forEach(([k, v]) => fd.append(k, v));
        try {
            const resp = await csrfPost(APP.urls.upload, fd);
            const data = await resp.json();
            if (!resp.ok || data.error) {
                WamaApp.toast('Erreur : ' + (data.error || resp.statusText), 'error');
                return null;
            }
            if (window.WamaFM) WamaFM.uploaded();  // fichier ajouté → refresh filemanager
            // `id` = contrat COMMUN des vues d'upload (trou #24). Les deux anciennes graphies
            // restent lues en repli le temps que le parc converge : un identifiant `undefined`
            // ne lève RIEN ici (`return null` silencieux, aucune card, aucune erreur console) —
            // c'est ce mutisme qui a rendu converter_01 inerte pendant tout le 22/08.
            return data.id || data.job_id || data.pk || null;
        } catch (err) {
            WamaApp.toast('Erreur réseau : ' + err.message, 'error');
            return null;
        }
    }

    // Point d'entrée unique : détecte un fichier batch (1 .txt/.csv) sinon
    // upload tous les fichiers puis les consolide en batch(s) par nature.
    async function handleFiles(files) {
        files = Array.from(files);
        if (!files.length) return;

        // 1 fichier descripteur de batch (urls/chemins) → flux batch dédié
        if (files.length === 1 && window._converterBatchImport &&
            await window._converterBatchImport.detectAndHandle(files[0])) {
            return;
        }

        const type = detectMediaType(files[0].name);
        if (type) setMediaType(type);

        const ids = [];
        for (const f of files) {
            const id = await uploadFile(f);
            if (id) ids.push(id);
        }
        if (ids.length) {
            // Consolidation en batch(s) par nature (1 fichier → batch-of-1)
            const fd = new FormData();
            ids.forEach(id => fd.append('job_ids', id));
            try { await csrfPost(APP.urls.consolidate, fd); } catch (_) { /* non-fatal */ }
            location.reload();
        }
    }

    // ── Drag & Drop ───────────────────────────────────────────────────────────

    // Clic pour parcourir : l'ancien markup avait un onclick inline sur la div, retiré au
    // passage à la card commune _new_item_card.html (2026-07-10, tête de file — cf. reader.js
    // initDropZone). Sans ce listener, cliquer la zone n'ouvrait plus le sélecteur de fichiers.
    dropZone.addEventListener('click', () => fileInput.click());

    dropZone.addEventListener('dragover', e => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        // Dossiers déposés → traversée récursive par la brique commune (F2 recursive_import).
        WamaFolderImport.collect(e.dataTransfer)
            .then(list => handleFiles(WamaFolderImport.files(list)));
    });

    fileInput.addEventListener('change', () => {
        handleFiles(fileInput.files);
        fileInput.value = '';
    });

    // Import de DOSSIER via le lien de la card commune (folder_input_id, webkitdirectory).
    const folderInput = document.getElementById('converterFolderInput');
    if (folderInput) {
        folderInput.addEventListener('change', () => {
            handleFiles(WamaFolderImport.files(WamaFolderImport.fromInput(folderInput.files)));
            folderInput.value = '';
        });
    }

    // ── Batch import (fichier d'URLs/chemins) — composant commun ────────────────
    if (typeof WamaBatchImport === 'function') {
        window._converterBatchImport = WamaBatchImport({
            batchPreviewUrl: APP.urls.batchPreview,
            batchCreateUrl:  APP.urls.batchCreate,
            csrfToken:       csrf,
            afterCreate:     function () { location.reload(); },
        });
    }

    // ── Queue actions ─────────────────────────────────────────────────────────

    async function startJob(jobId) {
        const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
        // Relance pendant le traitement (modale) : annuler d'abord (évite un double run / 409).
        if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') {
            await cancelJob(jobId);
        }
        if (card) card.dataset.status = 'RUNNING';
        try {
            const resp = await csrfPost(urlFor(APP.urls.start, jobId));
            if (resp.ok) {
                startPolling(jobId);
            } else {
                const d = await resp.json();
                WamaApp.toast(d.error || 'Erreur démarrage', 'error');
            }
        } catch (err) {
            WamaApp.toast('Erreur réseau : ' + err.message, 'error');
        }
    }

    // ⏹ Stop : annule la conversion en cours (revoke + reset PENDING côté serveur) → relançable.
    async function cancelJob(jobId) {
        const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
        try {
            await csrfPost(urlFor(APP.urls.cancel, jobId));
            if (card) card.dataset.status = 'PENDING';   // cancel → PENDING (autoSync repasse en ▶)
            stopPolling(jobId);
        } catch (err) {
            /* non-fatal */
        }
    }

    // Suppression : retirée le 2026-08-22 avec le passage à `.delete-btn[data-delete-url]`.
    // Ce que faisait la version locale et que le rechargement de la brique couvre : arrêt du
    // polling de l'item, rafraîchissement du filemanager, retrait de la card. Seule différence
    // assumée — un rechargement de page au lieu d'un retrait en place, exactement le
    // comportement que la duplication a déjà depuis qu'elle est passée à la brique.

    // Duplication ET suppression : gérées par la brique commune queue-actions.js (délégation
    // globale sur le bouton de card, aucun handler local ici).

    // ── Polling ───────────────────────────────────────────────────────────────

    function startPolling(jobId) {
        if (pollingTimers[jobId]) return;
        pollingTimers[jobId] = setInterval(() => pollJob(jobId), 1500);
    }

    function stopPolling(jobId) {
        if (pollingTimers[jobId]) {
            clearInterval(pollingTimers[jobId]);
            delete pollingTimers[jobId];
        }
    }

    async function pollJob(jobId) {
        try {
            const resp = await fetch(urlFor(APP.urls.status, jobId));
            if (!resp.ok) return;
            const data = await resp.json();
            const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
            if (card) {
                // ETA (moteur commun) — débit observé, sans seed côté converter
                if (window.WamaEta) {
                    const est = WamaEta.update(jobId, { progress: data.progress, status: data.status, seedSeconds: data.estimated_seconds, modelLoaded: false });
                    WamaEta.render(card.querySelector('.wama-eta'), est);
                }
                if (data.status === card.dataset.status) {
                    // Même état : maj légère de la progression, le markup ne bouge pas.
                    const fill = card.querySelector('.wama-progress-fill');
                    if (fill) fill.style.width = (data.progress || 0) + '%';
                    const pct = card.querySelector('.progress-text');
                    if (pct) pct.textContent = (data.progress || 0) + '%';
                } else {
                    // Transition d'état → re-rendu SERVEUR de la card (source unique).
                    await refreshCard(jobId);
                }
            }
            if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                stopPolling(jobId);
            }
        } catch (_) { /* ignore */ }
    }

    async function refreshCard(jobId) {
        // Card = partial serveur unique (endpoint card_html) ; les événements de la
        // file sont DÉLÉGUÉS sur le conteneur → aucun re-bind nécessaire.
        try {
            const resp = await fetch(urlFor(APP.urls.cardHtml, jobId));
            if (!resp.ok) return;
            const tpl = document.createElement('template');
            tpl.innerHTML = (await resp.text()).trim();
            const fresh = tpl.content.firstElementChild;
            const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
            if (fresh && card) card.replaceWith(fresh);
        } catch (_) { /* ignore */ }
    }

    // (updateCard supprimée : le markup vient du serveur via refreshCard — plus de
    // reconstruction client de la barre/badge/boutons, la card est la source unique.)

    // ── Event delegation for queue buttons ────────────────────────────────────

    // Bouton de cycle commun ▶/⏹/↻ : clics délégués (start/restart→startJob, stop→cancelJob) + auto-sync
    // de l'icône sur data-status (le re-rendu serveur refreshCard le maintient). Remplace l'ancien .job-start-btn.
    if (window.WamaCycleButton) {
        WamaCycleButton.wire(queue, { start: (id) => startJob(id), stop: (id) => cancelJob(id) });
        WamaCycleButton.autoSync({ container: queue, cardSelector: '.job-card' });
    }

    queue.addEventListener('click', e => {
        // (.job-start-btn legacy RETIRÉ le 31/08 — 0 occurrence dans les gabarits depuis le
        // bouton de cycle commun ; le repli était inerte par construction. REMOVAL_LEDGER.)

        // Suppression d'un ÉLÉMENT : plus de handler ici — la brique commune
        // `queue-actions.js` délègue sur `.delete-btn[data-delete-url]`, confirmation comprise
        // (2026-08-22). Le retrait est SOLIDAIRE du changement de classe dans `_job_card.html` :
        // les deux ensemble, sinon double-fire (app + brique) ou bouton mort.
        // Les actions de LOT restent locales tant que la brique ne les porte pas.

        // ⚙ d'un ÉLÉMENT : plus de handler ici non plus — même mouvement que la suppression
        // ci-dessus, un mois plus tard (2026-08-23). `.job-settings-btn` est devenu
        // `.settings-btn[data-id]` dans `_job_card.html` AU MÊME GESTE, et l'ouvreur est
        // déclaré à la brique (voir `WamaQueueActions.onSettings`, plus bas).

        // Actions de LOT (▶ ⧉ 🗑 ⚙) : portées à la brique commune le 2026-08-24 — voir le
        // bloc `WamaQueueActions` plus bas. Le stopPropagation qui évitait de toggler le
        // collapse est fait par la brique elle-même.
    });

    // ── Actions de LOT : brique commune (`queue-actions.js`) ────────────────────
    // `startBatch`/`duplicateBatch`/`deleteBatch` vivaient ici et faisaient EXACTEMENT ce que
    // fait la brique : POST + rechargement, avec confirm pour 🗑. Le converter appartient à la
    // famille « rechargent » : son ▶ posait bien un `startPolling` sur les éléments démarrés,
    // mais le `location.reload()` qui suivait l'annulait aussitôt — il n'y avait donc AUCUNE
    // suite à préserver, et pas de `onBatchStarted` à déclarer (le défaut sûr de la brique EST
    // le rechargement). Lu dans le code, pas supposé.
    // Seul le ⚙ déclare quelque chose : sa modale a besoin de la NATURE du lot, que le bouton
    // porte (ou son wrapper `.batch-group`) — la brique passe le bouton en 2ᵉ argument.
    WamaQueueActions.onBatchSettings(function (batchId, btn) {
        const mt = btn.dataset.mediaType || btn.closest('.batch-group')?.dataset.mediaType;
        openBatchSettingsModal(batchId, mt);
    });

    let _currentBatchId = null;
    function openBatchSettingsModal(batchId, mediaType) {
        _currentBatchId = batchId;
        const errEl = document.getElementById('batchSettingsError');
        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
        // Champs générés du SCHÉMA (context:'batch') — re-rendus à chaque ouverture : les
        // options de format dépendent de la NATURE du lot, passée par `values`. Le resolver
        // maison a été RETIRÉ le 2026-09-01 (convergence P1) : `WamaParams` interroge seul le
        // registre commun `PAGE_OPTION_SOURCES.formats`, adossé à la MÊME table
        // (`CONVERTER_OUTPUT_FORMATS`, projection de `SUPPORTED_CONVERSIONS`).
        const host = document.getElementById('converterBatchParams');
        if (host && window.WamaParams && APP.schema) {
            // Pré-remplissage = les valeurs PARTAGÉES des filles (2026-09-02, constat
            // Fabien : la modale s'ouvrait toujours sur « — inchangé — », comme si les
            // réglages sauvés étaient perdus — or un lot ne stocke rien, il APPLIQUE :
            // le juste est la sémantique de la carte mère, « valeur si partagée par
            // toutes les filles », lue du MÊME lecteur de gear que la modale d'item).
            // « inchangé » ne reste que là où les filles DIVERGENT réellement.
            const groupe = document.querySelector('.batch-group[data-batch-id="' + batchId + '"]');
            const partagees = (groupe && window.WamaInspector && WamaInspector.sharedGearValues)
                ? WamaInspector.sharedGearValues(groupe, APP.schema.map(p => p.name)) : {};
            WamaParams.render(host, APP.schema, {
                context: 'batch',
                values: Object.assign(partagees, { media_type: mediaType || '' }),
                groups: APP.groups,
            });
        }
        new bootstrap.Modal(document.getElementById('batchSettingsModal')).show();
    }

    async function applyBatchSettings(thenStart) {
        const vals = window.WamaParams
            ? WamaParams.read(document.getElementById('converterBatchParams')) : {};
        const errEl = document.getElementById('batchSettingsError');
        // TOUT le formulaire du lot part au serveur — plus la paire figée format/qualité
        // (02/09, demande Fabien : le lot est homogène par nature, ses réglages auxiliaires
        // s'appliquent en masse). Seul le POSÉ est envoyé : un champ vide/décoché veut dire
        // « ne pas toucher les filles », jamais « effacer » — c'est la sémantique du lot.
        const fd = new FormData();
        Object.entries(vals).forEach(([k, v]) => {
            if (v === '' || v == null || v === false) return;
            fd.append(k, v);
        });
        try {
            const resp = await csrfPost(urlFor(APP.urls.batchUpdate, _currentBatchId), fd);
            const data = await resp.json();
            if (!resp.ok || data.error) {
                if (errEl) { errEl.textContent = data.error || 'Erreur'; errEl.style.display = ''; }
                return;
            }
            const modal = bootstrap.Modal.getInstance(document.getElementById('batchSettingsModal'));
            if (modal) modal.hide();
            if (thenStart) { await csrfPost(urlFor(APP.urls.batchStart, _currentBatchId)); }
            location.reload();
        } catch (err) {
            if (errEl) { errEl.textContent = 'Erreur réseau : ' + err.message; errEl.style.display = ''; }
        }
    }

    document.getElementById('batchSettingsApplyBtn')?.addEventListener('click', () => applyBatchSettings(false));
    document.getElementById('batchSettingsApplyStartBtn')?.addEventListener('click', () => applyBatchSettings(true));

    // ── Global buttons ────────────────────────────────────────────────────────

    startAllBtn && startAllBtn.addEventListener('click', async () => {
        try {
            const resp = await csrfPost(APP.urls.startAll);
            const data = await resp.json();
            if (data.started && data.started.length) {
                data.started.forEach(id => startPolling(id));
            }
            location.reload();
        } catch (err) {
            WamaApp.toast('Erreur : ' + err.message, 'error');
        }
    });

    downloadAllBtn && downloadAllBtn.addEventListener('click', () => {
        window.location.href = APP.urls.downloadAll;
    });

    clearAllBtn && clearAllBtn.addEventListener('click', async () => {
        if (!confirm('Effacer toutes les conversions ?')) return;
        try {
            await csrfPost(APP.urls.clearAll);
            location.reload();
        } catch (err) {
            WamaApp.toast('Erreur : ' + err.message, 'error');
        }
    });

    // ── Settings modal — dynamic form + apply / restart ───────────────────────

    // buildModalFormHTML RETIRÉE le 31/08 (REMOVAL_LEDGER) : branche INATTEIGNABLE —
    // wama-params.js est chargé inconditionnellement et APP.schema jamais vide (audit B1).
    // 134 lignes de formulaire maison que WamaParams rend depuis le 06/08.

    // readModalForm RETIRÉE le 31/08 (REMOVAL_LEDGER) : lisait des attributs maison que
    // WamaParams n'émet pas (bug « Sauver comme profil », audit B2) — voie schéma seule.

    // Lecture SCHÉMA-DRIVEN d'un conteneur WamaParams (modale ⚙ OU volet inspecteur) →
    // {output_format, options} : coercition nombres/toggles + filtre show_if pour ne garder
    // que les options du media_type (WamaParams.read voit aussi les sections cachées).
    // PARTAGÉE modale/inspecteur (18/08) — exposée via APP.readParamsFrom pour le script
    // initFromSchema (index.html).
    function readParamsFrom(container, mediaType) {
        const body = container;
        const raw = WamaParams.read(body);
        const byName = {};
        (APP.schema || []).forEach(function (p) { byName[p.name] = p; });
        const mt = (mediaType !== undefined && mediaType !== null) ? mediaType : (raw.media_type || '');
        function matches(p) {
            const c = p.show_if;
            if (!c || typeof c === 'string' || c.field !== 'media_type') return true;
            if (c.in) return c.in.indexOf(mt) !== -1;
            if ('equals' in c) return String(c.equals) === String(mt);
            return true;
        }
        const options = {};
        Object.keys(raw).forEach(function (k) {
            if (k === 'output_format' || k === 'media_type') return;
            const p = byName[k] || {};
            if (!matches(p)) return;
            const v = raw[k];
            if (p.type === 'toggle') { if (v === true || v === 'true') options[k] = true; return; }
            if (p.type === 'number' || p.type === 'range') {
                if (v !== '' && v != null) {
                    const isFloat = p.step && parseFloat(p.step) !== Math.floor(parseFloat(p.step));
                    const n = isFloat ? parseFloat(v) : parseInt(v, 10);
                    if (!isNaN(n)) options[k] = n;
                }
                return;
            }
            if (v !== '' && v != null) options[k] = v;
        });
        return { output_format: raw.output_format || '', options: options };
    }
    APP.readParamsFrom = readParamsFrom;

    function readModalViaSchema() {
        return readParamsFrom(document.getElementById('jobSettingsBody'), currentModalMediaType);
    }

    let currentModalJobId = null;
    let currentModalMediaType = null;

    // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js), portage 2026-08-23.
    WamaQueueActions.onSettings(function (id) { openSettingsModal(id); });

    // 🗑 RÉSIDU de suppression — la brique retire la card, le lot vidé et signale au gestionnaire
    // de fichiers ; ne reste que l'état vide (brique commune, instance `_empty` en tête).
    WamaQueueActions.onDeleted(function () { _empty.insertIfNeeded(); });

    async function openSettingsModal(jobId) {
        currentModalJobId = jobId;
        const filenameSpan = document.getElementById('jobSettingsFilename');
        const body = document.getElementById('jobSettingsBody');

        filenameSpan.textContent = `Job #${jobId}`;
        body.innerHTML = '<div class="text-center text-muted py-3"><i class="fas fa-spinner fa-spin"></i> Chargement…</div>';
        const modalEl = document.getElementById('jobSettingsModal');
        const modal = new bootstrap.Modal(modalEl);
        modal.show();

        try {
            const resp = await fetch(urlFor(APP.urls.status, jobId));
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            const data = await resp.json();
            currentModalMediaType = data.media_type;
            filenameSpan.textContent = data.input_filename || `Job #${jobId}`;
            // Modale schéma-driven : WamaParams rend les champs (show_if par media_type, format dynamique).
            // Pont dom_id non requis ici car read/écriture passent aussi par WamaParams (readModalViaSchema).
            if (window.WamaParams && APP.schema) {
                const values = Object.assign(
                    { media_type: data.media_type, output_format: data.output_format }, data.options || {});
                // Descriptif moteur du TYPE du job (18/08) : le help_fallback statique par
                // format donnait le texte d'une AUTRE famille pour les formats multi-famille
                // (mp3/wav/ogg sortent aussi de la famille vidéo, gif de l'image…).
                if (APP.engineHelp && APP.engineHelp[data.media_type]) {
                    (APP.schema || []).forEach(function (p) {
                        if (p.name !== 'output_format') return;
                        const fb = {};
                        (((FORMATS[data.media_type] || {}).output) || []).forEach(function (f) {
                            fb[f] = APP.engineHelp[data.media_type];
                        });
                        p.help_fallback = fb;
                    });
                }
                // `values` porte déjà media_type : le registre commun borne les formats à la
                // nature de l'élément. Resolver maison RETIRÉ le 2026-09-01 (convergence P1).
                WamaParams.render(body, APP.schema, {
                    context: 'item',
                    values: values,
                    groups: APP.groups,
                });
            } else {
                // Jamais un blanc MUET : cet état signifie que wama-params.js a échoué au chargement.
                body.innerHTML = '<div class="alert alert-warning small">Formulaire indisponible (WamaParams non chargé) — recharger la page.</div>';
                console.error('[converter] WamaParams absent — modale de réglages non rendue');
            }

            // Disable Apply/Start if job is RUNNING
            const isRunning = data.status === 'RUNNING';
            const applyBtn = document.getElementById('jobSettingsApplyBtn');
            const startBtn = document.getElementById('jobSettingsStartBtn');
            if (applyBtn) applyBtn.disabled = isRunning;
            if (startBtn) {
                startBtn.disabled = isRunning;
                startBtn.innerHTML = data.status === 'SUCCESS'
                    ? '<i class="fas fa-redo"></i> Appliquer & Recommencer'
                    : '<i class="fas fa-play"></i> Appliquer & (Re)lancer';
            }
            if (isRunning) {
                const warn = document.createElement('div');
                warn.className = 'alert alert-warning small mt-2 mb-0';
                warn.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Conversion en cours — modification désactivée.';
                body.appendChild(warn);
            }
        } catch (err) {
            body.innerHTML = `<div class="alert alert-danger small">Erreur de chargement : ${err.message}</div>`;
        }
    }

    /**
     * POST update payload for the current modal job. Returns true on success.
     */
    async function applyCurrentModal() {
        const { output_format, options } = readModalViaSchema();
        if (!output_format) {
            WamaApp.toast('Format de sortie requis.', 'warning');
            return false;
        }
        const fd = new FormData();
        fd.append('output_format', output_format);
        fd.append('options_json', JSON.stringify(options));
        try {
            const resp = await csrfPost(urlFor(APP.urls.update, currentModalJobId), fd);
            const data = await resp.json();
            if (!resp.ok || data.error) {
                WamaApp.toast('Erreur : ' + (data.error || resp.statusText), 'error');
                return false;
            }
            // Reflect new format in the queue card immediately (re-rendu serveur)
            refreshCard(currentModalJobId);
            return true;
        } catch (err) {
            WamaApp.toast('Erreur réseau : ' + err.message, 'error');
            return false;
        }
    }

    // Apply (sans relancer)
    document.getElementById('jobSettingsApplyBtn')?.addEventListener('click', async () => {
        const ok = await applyCurrentModal();
        if (ok) {
            const modal = bootstrap.Modal.getInstance(document.getElementById('jobSettingsModal'));
            if (modal) modal.hide();
        }
    });

    // Apply & (Re)lancer
    document.getElementById('jobSettingsStartBtn')?.addEventListener('click', async () => {
        const ok = await applyCurrentModal();
        if (!ok) return;
        const modal = bootstrap.Modal.getInstance(document.getElementById('jobSettingsModal'));
        if (modal) modal.hide();
        startJob(currentModalJobId);
    });

    // ── Save current modal settings as a profile ──────────────────────────────

    document.getElementById('jobSettingsSaveProfileBtn')?.addEventListener('click', () => {
        // Voie schéma UNIQUE depuis le nettoyage du 31/08 — la voie legacy (cause du
        // bug « Sauver comme profil ») est RETIRÉE, le fork n'existe plus.
        const { output_format, options } = readModalViaSchema();
        if (!output_format) {
            WamaApp.toast('Format de sortie requis avant de sauver.', 'warning');
            return;
        }
        // Stash for confirm handler
        document.getElementById('saveProfileModal').dataset.pendingPayload = JSON.stringify({
            media_type:    currentModalMediaType,
            output_format,
            options,
        });
        document.getElementById('saveProfileName').value = '';
        document.getElementById('saveProfileDesc').value = '';
        const modal = new bootstrap.Modal(document.getElementById('saveProfileModal'));
        modal.show();
    });

    document.getElementById('saveProfileConfirmBtn')?.addEventListener('click', async () => {
        const name = (document.getElementById('saveProfileName').value || '').trim();
        const desc = (document.getElementById('saveProfileDesc').value || '').trim();
        if (!name) { WamaApp.toast('Nom requis', 'warning'); return; }
        let payload;
        try {
            payload = JSON.parse(document.getElementById('saveProfileModal').dataset.pendingPayload || '{}');
        } catch (_) { payload = {}; }

        const fd = new FormData();
        fd.append('name',          name);
        fd.append('description',   desc);
        fd.append('media_type',    payload.media_type || '');
        fd.append('output_format', payload.output_format || '');
        fd.append('options_json',  JSON.stringify(payload.options || {}));

        try {
            const resp = await csrfPost(APP.urls.profileSave, fd);
            const data = await resp.json();
            if (!resp.ok || data.error) {
                WamaApp.toast('Erreur : ' + (data.error || resp.statusText), 'error');
                return;
            }
            const modal = bootstrap.Modal.getInstance(document.getElementById('saveProfileModal'));
            if (modal) modal.hide();
            await loadProfiles();
            renderProfileDropdown(currentMediaType);
        } catch (err) {
            WamaApp.toast('Erreur réseau : ' + err.message, 'error');
        }
    });

    // ── Profiles (right panel dropdown) ───────────────────────────────────────

    async function loadProfiles() {
        try {
            const resp = await fetch(APP.urls.profileList);
            const data = await resp.json();
            cachedProfiles = data.profiles || [];
        } catch (_) {
            cachedProfiles = [];
        }
    }

    function renderProfileDropdown(mediaType) {
        if (!profileSelect) return;
        const filtered = mediaType
            ? cachedProfiles.filter(p => p.media_type === mediaType)
            : cachedProfiles.slice();
        profileSelect.innerHTML = '<option value="">— aucun profil —</option>';
        filtered.forEach(p => {
            const opt = document.createElement('option');
            opt.value = p.id;
            opt.textContent = `${p.name} (${p.output_format.toUpperCase()})`;
            opt.title = p.description || '';
            profileSelect.appendChild(opt);
        });
        if (profileDeleteBtn) profileDeleteBtn.disabled = true;
    }

    profileSelect?.addEventListener('change', () => {
        const pid = profileSelect.value;
        if (profileDeleteBtn) profileDeleteBtn.disabled = !pid;
        if (!pid) return;
        const profile = cachedProfiles.find(p => String(p.id) === String(pid));
        if (!profile) return;
        // Apply profile: set output format + options
        if (profile.media_type !== currentMediaType) {
            setMediaType(profile.media_type);
        }
        // Le format fait partie des valeurs appliquées au schéma : le select est peuplé
        // par le registre commun selon `media_type`, donc l'affectation suit le même chemin
        // que les autres réglages (plus de dropdown manipulé à la main).
        applyOptionsToMainPanel(profile.media_type,
                                Object.assign({ output_format: profile.output_format },
                                              profile.options || {}));
    });

    profileDeleteBtn?.addEventListener('click', async () => {
        const pid = profileSelect.value;
        if (!pid) return;
        const profile = cachedProfiles.find(p => String(p.id) === String(pid));
        if (!profile) return;
        if (!confirm(`Supprimer le profil "${profile.name}" ?`)) return;
        try {
            await csrfPost(urlFor(APP.urls.profileDelete, pid));
            await loadProfiles();
            renderProfileDropdown(currentMediaType);
        } catch (err) {
            WamaApp.toast('Erreur réseau : ' + err.message, 'error');
        }
    });

    // ── Reset options ─────────────────────────────────────────────────────────

    const resetBtn = document.getElementById('converterResetOptions');
    if (resetBtn) resetBtn.addEventListener('click', () => {
        // Un reset = RE-RENDRE l'hôte depuis le schéma : ses défauts d'affichage reviennent,
        // et rien n'est recopié à la main (c'est la copie manuelle qui dérivait).
        const host = panelHost();
        if (host && window.WamaParams && window.CONVERTER_APP) {
            WamaParams.render(host, CONVERTER_APP.schema,
                              { context: 'panel', values: { media_type: currentMediaType || '' },
                                groups: CONVERTER_APP.groups });
            window.CONVERTER_DEFAUTS = readMainPanelOptions();
        }
        if (profileSelect) {
            profileSelect.value = '';
            if (profileDeleteBtn) profileDeleteBtn.disabled = true;
        }
    });

    // ── Auto-start polling for RUNNING jobs (on page load) ────────────────────

    document.querySelectorAll('.job-card[data-status="RUNNING"]').forEach(card => {
        startPolling(card.dataset.jobId);
    });

    // ── Init ──────────────────────────────────────────────────────────────────
    setMediaType(null);
    loadProfiles().then(() => renderProfileDropdown(null));

})();
