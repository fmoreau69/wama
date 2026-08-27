/**
 * WAMA Avatarizer - Frontend JS
 * Gère : sélection avatar, upload fichiers, création/démarrage/polling des jobs
 */

"use strict";

(function () {
    const cfg = window.AVATARIZER_CONFIG;
    const csrf = cfg.csrfToken;

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    let selectedAvatarSource = null;  // 'gallery' | 'upload'
    let selectedAvatarName   = null;  // gallery filename
    let audioFile            = null;  // File object (standalone)
    let avatarUploadFile     = null;  // File object (avatar upload)
    let activePollers        = {};    // {job_id: intervalId}

    // -----------------------------------------------------------------------
    // DOM Helpers
    // -----------------------------------------------------------------------
    const $  = (sel, ctx = document) => ctx.querySelector(sel);
    const $$ = (sel, ctx = document) => ctx.querySelectorAll(sel);

    function getMode() {
        // STANDALONE-ONLY depuis 2026-07-11 (décision : le pipeline texte→TTS→avatar devient
        // une composition STUDIO synthesizer→avatarizer). Le backend garde le champ mode
        // (jobs historiques, batch, tool_api) — seule la création UI est standalone.
        return 'standalone';
    }

    // -----------------------------------------------------------------------
    // Word counter
    // -----------------------------------------------------------------------
    const textArea = $('#text_content');
    const wordCountEl = $('#word-count');
    if (textArea) {
        textArea.addEventListener('input', () => {
            const words = textArea.value.trim().split(/\s+/).filter(Boolean).length;
            wordCountEl.textContent = words;
        });
    }

    // -----------------------------------------------------------------------
    // bbox_shift slider
    // -----------------------------------------------------------------------
    const bboxSlider = $('#bbox_shift');
    const bboxVal    = $('#bbox_shift_val');
    if (bboxSlider) {
        bboxSlider.addEventListener('input', () => {
            bboxVal.textContent = bboxSlider.value;
        });
    }

    // Le couple de modes rapide/qualité est MORT (2026-08-03) : l'Amélioration
    // CodeFormer (#use_enhancer) est le SEUL contrôle de qualité, toujours visible.

    // -----------------------------------------------------------------------
    // Avatar gallery selection
    // -----------------------------------------------------------------------
    $$('.avatar-card').forEach(card => {
        card.addEventListener('click', () => {
            $$('.avatar-card').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
            selectedAvatarSource = 'gallery';
            selectedAvatarName   = card.dataset.avatarName;
            avatarUploadFile = null;
            $('#avatar-upload-info').classList.add('d-none');
            updateGenerateButton();
        });
    });

    // -----------------------------------------------------------------------
    // Avatar upload
    // -----------------------------------------------------------------------
    const avatarUploadZone  = $('#avatar-upload-zone');
    const avatarUploadInput = $('#avatar_upload');
    const avatarUploadInfo  = $('#avatar-upload-info');
    const avatarUploadPrev  = $('#avatar-upload-preview');
    const btnRemoveAvatar   = $('#btn-remove-avatar-upload');

    if (avatarUploadZone) {
        avatarUploadZone.addEventListener('click', () => avatarUploadInput.click());
        avatarUploadZone.addEventListener('dragover', e => {
            e.preventDefault();
            avatarUploadZone.classList.add('dragover');
        });
        avatarUploadZone.addEventListener('dragleave', () => avatarUploadZone.classList.remove('dragover'));
        avatarUploadZone.addEventListener('drop', e => {
            e.preventDefault();
            avatarUploadZone.classList.remove('dragover');
            // Slot MONO-fichier : un dossier déposé résout de vrais fichiers (brique
            // WamaFolderImport) et on prend le premier — avant, l'entrée dossier échouait.
            WamaFolderImport.collect(e.dataTransfer)
                .then(list => { const f = WamaFolderImport.files(list)[0]; if (f) handleAvatarFile(f); });
        });
    }
    if (avatarUploadInput) {
        avatarUploadInput.addEventListener('change', () => handleAvatarFile(avatarUploadInput.files[0]));
    }
    if (btnRemoveAvatar) {
        btnRemoveAvatar.addEventListener('click', () => {
            avatarUploadFile = null;
            selectedAvatarSource = null;
            avatarUploadInfo.classList.add('d-none');
            avatarUploadInput.value = '';
            updateGenerateButton();
        });
    }

    function handleAvatarFile(file) {
        if (!file) return;
        const allowed = ['image/jpeg', 'image/png', 'image/webp'];
        if (!allowed.includes(file.type)) {
            WamaApp.toast('Format non supporté. Utilisez JPG, PNG ou WebP.', 'error');
            return;
        }
        avatarUploadFile = file;
        selectedAvatarSource = 'upload';
        selectedAvatarName = null;
        $$('.avatar-card').forEach(c => c.classList.remove('selected'));

        const reader = new FileReader();
        reader.onload = e => { avatarUploadPrev.src = e.target.result; };
        reader.readAsDataURL(file);
        avatarUploadInfo.classList.remove('d-none');
        updateGenerateButton();
    }

    // -----------------------------------------------------------------------
    // Audio upload (Standalone)
    // -----------------------------------------------------------------------
    const audioDropzone = $('#audio-dropzone');
    const audioInput    = $('#audio_input');
    // Zones rendues par la card commune _new_item_card : data-wama-app posé ici (le partial ne
    // le rend pas) — requis par le quick-drop filemanager (getAppFromDropZone → dataset.wamaApp).
    ['audio-dropzone'].forEach(id => {
        const z = document.getElementById(id);
        if (z && !z.dataset.wamaApp) z.dataset.wamaApp = 'avatarizer';
    });
    const audioInfo     = $('#audio-info');
    const audioFilename = $('#audio-filename');
    const btnRemoveAudio = $('#btn-remove-audio');

    if (audioDropzone) {
        audioDropzone.addEventListener('click', () => audioInput.click());
        audioDropzone.addEventListener('dragover', e => {
            e.preventDefault();
            audioDropzone.classList.add('dragover');
        });
        audioDropzone.addEventListener('dragleave', () => audioDropzone.classList.remove('dragover'));
        audioDropzone.addEventListener('drop', e => {
            e.preventDefault();
            audioDropzone.classList.remove('dragover');
            // Slot MONO-fichier : même traitement que le slot avatar (dossier → 1er fichier).
            WamaFolderImport.collect(e.dataTransfer)
                .then(list => { const f = WamaFolderImport.files(list)[0]; if (f) handleAudioFile(f); });
        });
    }
    if (audioInput) {
        audioInput.addEventListener('change', () => handleAudioFile(audioInput.files[0]));
    }

    // Import depuis le Filemanager (drag-and-drop depuis le panneau latéral)
    if (audioDropzone) {
        audioDropzone.addEventListener('filemanager:filedrop', async (e) => {
            const { path, name, mime } = e.detail;
            const ext = (name || '').split('.').pop().toLowerCase();
            const allowedExts = ['wav', 'mp3', 'ogg', 'flac'];
            if (!allowedExts.includes(ext)) {
                WamaApp.toast(`Format non supporté : .${ext}\nL'avatarizer accepte uniquement : ${allowedExts.join(', ')}`, 'error');
                return;
            }
            try {
                const mediaUrl = (window.MEDIA_URL || cfg.mediaUrl || '/media/') + path;
                const resp = await fetch(mediaUrl);
                if (!resp.ok) throw new Error(`Fichier introuvable sur le serveur (HTTP ${resp.status})`);
                const blob = await resp.blob();
                const file = new File([blob], name || 'audio', { type: blob.type || mime || 'audio/mpeg' });
                handleAudioFile(file);
            } catch (err) {
                WamaApp.toast('Erreur lors du chargement du fichier depuis le Filemanager : ' + err.message, 'error');
            }
        });
    }
    if (btnRemoveAudio) {
        btnRemoveAudio.addEventListener('click', () => {
            audioFile = null;
            audioInfo.classList.add('d-none');
            audioInput.value = '';
            updateGenerateButton();
        });
    }

    // -----------------------------------------------------------------------
    // Text drop zone (Pipeline) — filemanager drag + Windows Explorer drag
    // -----------------------------------------------------------------------
    // Drop de fichier texte (.txt/.pdf/.docx) : RETIRÉ avec le workflow pipeline
    // (standalone-only 2026-07-11 — le pipeline texte→TTS→avatar = composition studio).

    async function handleAudioFile(file) {
        // Fichier batch déposé sur la zone audio → flux d'import de lot commun.
        // detectAndHandle est async : sans await, la Promise (toujours truthy)
        // court-circuitait TOUT fichier audio (bug import filemanager 2026-08-04).
        if (file && batchImport && await batchImport.detectAndHandle(file)) return;
        if (!file) return;
        audioFile = file;
        audioFilename.textContent = file.name;
        audioInfo.classList.remove('d-none');
        updateGenerateButton();
    }

    // -----------------------------------------------------------------------
    // Update "Generate" button state
    // -----------------------------------------------------------------------
    function updateGenerateButton() {
        const btn = $('#btn-generate');
        if (!btn) return;

        // Standalone-only (2026-07-11) : audio (fichier OU URL) + avatar requis
        const urlInputEl = $('#avatarizerUrlInput');
        const hasUrl = !!(urlInputEl && urlInputEl.value.trim());
        btn.disabled = !((audioFile || hasUrl) && selectedAvatarSource);
    }

    if (textArea) {
        textArea.addEventListener('input', updateGenerateButton);
    }

    // Import par URL (brique _new_item_card show_url → WAMA_INGEST) : l'URL vaut fichier audio
    const avatarizerUrlInput = $('#avatarizerUrlInput');
    const avatarizerUrlSubmit = $('#avatarizerUrlSubmit');
    if (avatarizerUrlInput) avatarizerUrlInput.addEventListener('input', updateGenerateButton);
    if (avatarizerUrlSubmit) avatarizerUrlSubmit.addEventListener('click', (e) => {
        e.preventDefault();
        const btn = $('#btn-generate');
        if (btn && !btn.disabled) btn.click();
        else WamaApp.toast("URL prise en compte — choisissez aussi l'avatar (galerie ou photo).", 'info');
    });

    // -----------------------------------------------------------------------
    // Generate button → create + start job
    // -----------------------------------------------------------------------
    const btnGenerate = $('#btn-generate');
    if (btnGenerate) {
        btnGenerate.addEventListener('click', async () => {
            btnGenerate.disabled = true;
            btnGenerate.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i> Envoi…';

            try {
                const jobId = await createJob();
                await startJob(jobId);
                addJobCard(jobId);
                startPolling(jobId);
                updateJobsCount(1);

                // Reset form
                if (textArea) textArea.value = '';
                if (wordCountEl) wordCountEl.textContent = '0';
                audioFile = null;
                if (audioInfo) audioInfo.classList.add('d-none');
                if (audioInput) audioInput.value = '';
                if (avatarizerUrlInput) avatarizerUrlInput.value = '';

            } catch (err) {
                WamaApp.toast('Erreur : ' + err.message, 'error');
            } finally {
                btnGenerate.innerHTML = '<i class="fas fa-play-circle me-1"></i> Générer la vidéo';
                updateGenerateButton();
            }
        });
    }

    function updateJobsCount(delta) {
        const counter = $('#jobs-count');
        if (!counter) return;
        const current = parseInt(counter.textContent || '0', 10);
        counter.textContent = Math.max(0, current + delta);
    }

    // -----------------------------------------------------------------------
    // Create job (POST /avatarizer/create/)
    // -----------------------------------------------------------------------
    // Import de LOT (brique commune batch-import.js) : détection des fichiers batch
    // (txt/csv/pdf/docx → parseur serveur commun parse_unified_batch) + barre de détection.
    // ⚠ `cfg.urls.batch` N'EXISTE PAS (le gabarit déclare `batchPreview`/`batchCreate`,
    // index.html:311-312) : l'interpolation rendait `/avatarizer/undefinedpreview/`, soit un
    // 404 servi en HTML que la brique tentait de lire en JSON. Défaut MUET côté page — la
    // console seule le disait ; le geste, lui, ne créait jamais rien. Mesuré le 2026-08-27.
    // De même `batchExts` n'était lu par personne : la brique lit `batchExtensions`
    // (`batch-import.js:46`). Les deux extensions binaires restent une INTENTION — la garde
    // MIME de `isBatch()` (l.64) écarte tout ce qui n'est pas `text/*`, donc pdf/docx ne
    // passent pas encore, même déclarés ici.
    const batchImport = window.WamaBatchImport ? WamaBatchImport({
        batchPreviewUrl: cfg.urls.batchPreview,
        batchCreateUrl: cfg.urls.batchCreate,
        csrfToken: csrf,
        batchExtensions: ['txt', 'csv', 'pdf', 'docx'],
        afterCreate: () => window.location.reload(),
    }) : null;

    async function createJob() {
        const fd = new FormData();
        fd.append('mode', getMode());          // standalone (pipeline = studio, 2026-07-11)
        if (audioFile) {
            fd.append('audio_input', audioFile);
        } else if (avatarizerUrlInput && avatarizerUrlInput.value.trim()) {
            fd.append('source_url', avatarizerUrlInput.value.trim());
        }

        fd.append('avatar_source', selectedAvatarSource);
        if (selectedAvatarSource === 'gallery') {
            fd.append('avatar_gallery_name', selectedAvatarName);
        } else {
            fd.append('avatar_upload', avatarUploadFile);
        }
        fd.append('bbox_shift', bboxSlider ? bboxSlider.value : '0');
        fd.append('use_enhancer', $('#use_enhancer') && $('#use_enhancer').checked ? 'true' : 'false');

        const resp = await fetch(cfg.urls.create, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf },
            body: fd,
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erreur création job');
        if (window.WamaFM) WamaFM.uploaded();  // fichiers d'entrée ajoutés → refresh filemanager
        // `id` = contrat COMMUN (trou #24) ; les anciennes graphies restent lues en repli le
        // temps que le parc converge. Sans ce repli, un identifiant `undefined` ne lèverait
        // RIEN — pas de card, pas d'erreur console : le mode de panne le plus coûteux à trouver.
        return data.id || data.job_id || data.pk || null;
    }

    // -----------------------------------------------------------------------
    // Start job (GET /avatarizer/start/<pk>/)
    // -----------------------------------------------------------------------
    async function startJob(jobId) {
        const resp = await fetch(`${cfg.urls.start}${jobId}/`, {
            headers: { 'X-CSRFToken': csrf },
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erreur démarrage job');
    }

    // -----------------------------------------------------------------------
    // Step label helper (from workers.py progress steps)
    // -----------------------------------------------------------------------
    function getStepLabel(progress, mode) {
        if (progress >= 100) return 'Vidéo générée ✓';
        if (progress >= 95)  return 'Finalisation…';
        if (progress >= 85)  return 'CodeFormer : amélioration faciale…';
        if (progress >= 80)  return 'Post-traitement…';
        if (progress >= 40)  return 'MuseTalk : synchronisation labiale…';
        if (progress >= 30)  return 'Préparation de la sortie…';
        if (progress >= 20)  return "Résolution de l'avatar…";
        if (progress >= 10)  return 'Chargement audio…';
        if (progress >= 5)   return 'Démarrage…';
        return 'En attente…';
    }

    // -----------------------------------------------------------------------
    // Add job card dynamically (new job) — synthesis-card layout
    // -----------------------------------------------------------------------
    // Card = partial SERVEUR unique (_avatar_card.html via card_html) — le JS ne fabrique
    // plus de markup : il insere/remplace le fragment rendu par Django.
    async function fetchCardHtml(jobId) {
        const r = await fetch(`${cfg.urls.card}${jobId}/html/`);
        if (!r.ok) throw new Error(`card_html ${r.status}`);
        const tmp = document.createElement('div');
        tmp.innerHTML = (await r.text()).trim();
        return tmp.firstElementChild;
    }

    async function addJobCard(jobId) {
        const container = $('#jobs-container');
        if (!container) return;
        try {
            const fresh = await fetchCardHtml(jobId);
            container.prepend(fresh);
            bindJobCardEvents(fresh);
        } catch (e) { /* la card apparaitra au prochain rechargement */ }
    }

    async function refreshCard(jobId) {
        const card = $(`#job-${jobId}`);
        if (!card) return;
        try {
            const fresh = await fetchCardHtml(jobId);
            card.replaceWith(fresh);
            bindJobCardEvents(fresh);   // RE-BIND apres re-rendu (lecon describer)
        } catch (e) { /* non-fatal */ }
    }

    // -----------------------------------------------------------------------
    // ⏹ Stop : arrête la génération (endpoint commun) → job relançable (↻ via autoSync sur data-status).
    async function stopJob(jobId) {
        const card = $(`.synthesis-card[data-job-id="${jobId}"]`);
        try {
            const r = await fetch(`${cfg.urls.stop}${jobId}/`, { method: 'POST', headers: { 'X-CSRFToken': csrf } });
            const data = await r.json().catch(() => ({}));
            if (card && data.status) card.dataset.status = data.status;
        } catch (e) { /* non-fatal */ }
        if (activePollers[jobId]) { clearInterval(activePollers[jobId]); delete activePollers[jobId]; }
        // Re-rendu SERVEUR de la card (badge/boutons/barre) — sans lui, l'état visuel restait
        // « en cours » jusqu'à un F5 (constat Fabien 17/08) : le poller étant coupé juste
        // au-dessus, aucune transition ne pouvait plus re-rendre la card.
        refreshCard(jobId);
    }

    // Bouton de cycle commun ▶/⏹/↻ : wire (start/restart→startJob+poll, stop→stopJob) + auto-sync.
    function initCycleButton() {
        const c = $('#jobs-container');
        if (!window.WamaCycleButton || !c) return;
        WamaCycleButton.wire(c, {
            start: async (id) => {
                const card = $(`.synthesis-card[data-job-id="${id}"]`);
                if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') await stopJob(id);
                try { await startJob(id); if (card) card.dataset.status = 'RUNNING'; startPolling(id); }
                catch (e) { WamaApp.toast(e.message || 'Erreur', 'error'); }
            },
            stop: (id) => stopJob(id),
        });
        WamaCycleButton.autoSync({ container: c, cardSelector: '.synthesis-card' });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initCycleButton);
    else initCycleButton();

    // Poll job progress
    // -----------------------------------------------------------------------
    function startPolling(jobId) {
        if (activePollers[jobId]) return;
        activePollers[jobId] = setInterval(() => pollJob(jobId), 2000);
    }

    async function pollJob(jobId) {
        try {
            const resp = await fetch(`${cfg.urls.progress}${jobId}/`);
            const data = await resp.json();
            updateJobCard(jobId, data);

            if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                clearInterval(activePollers[jobId]);
                delete activePollers[jobId];
            }
        } catch (_) { /* ignore network errors */ }
    }

    // -----------------------------------------------------------------------
    // Update job card from API data
    // -----------------------------------------------------------------------
    function updateJobCard(jobId, data) {
        const card = $(`#job-${jobId}`);
        if (!card) return;

        // Transition d'etat -> la card est re-rendue par le serveur (source unique du markup)
        if ((card.dataset.status || '') !== data.status) {
            card.dataset.status = data.status;
            refreshCard(jobId);
            return;
        }

        // Meme etat : progression/ETA/etape mises a jour en place (pas de re-fetch a chaque poll)
        // ⚠ .wama-progress-fill (brique commune) — l'ancien selecteur .progress-fill ne matchait
        // RIEN depuis le passage a la brique : la barre ne bougeait qu'aux transitions (no-op
        // silencieux attrape au port v3, 13/08).
        const fill     = $('.wama-progress-fill', card);
        const progText = $('.progress-text', card);
        if (fill)     fill.style.width = data.progress + '%';
        if (progText) progText.textContent = data.progress + '%';

        // ETA (moteur commun) — debit observe + seed serveur (apprentissage)
        if (window.WamaEta) {
            const est = WamaEta.update(jobId, { progress: data.progress, status: data.status,
                                                seedSeconds: data.estimated_seconds, modelLoaded: false });
            WamaEta.render($('.wama-eta', card), est);
        }

        const stepDesc = $('.step-desc', card);
        if (stepDesc && (data.status === 'RUNNING' || data.status === 'PENDING')) {
            stepDesc.textContent = getStepLabel(data.progress, data.mode || card.dataset.mode || 'pipeline');
        }
    }

    // -----------------------------------------------------------------------
    // Settings modal (per-job parameters)
    // -----------------------------------------------------------------------
    const settingsModal = document.getElementById('jobSettingsModal')
        ? new bootstrap.Modal(document.getElementById('jobSettingsModal'))
        : null;
    const settingsBboxSlider  = $('#settingsBboxShift');
    const settingsBboxVal     = $('#settingsBboxShiftVal');

    if (settingsBboxSlider) {
        settingsBboxSlider.addEventListener('input', () => {
            if (settingsBboxVal) settingsBboxVal.textContent = settingsBboxSlider.value;
        });
    }

    // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js), portage 2026-08-23.
    WamaQueueActions.onSettings(function (id, btn) { openSettingsModal(btn); });

    // 🗑 RÉSIDU de suppression — la brique retire la card, le lot vidé et signale au gestionnaire
    // de fichiers ; ne restent que le poller local (pas encore `WamaApp.Poller` ici), le compteur
    // d'en-tête et le message de file vide.
    WamaQueueActions.onDeleted(function (id) {
        if (activePollers[id]) { clearInterval(activePollers[id]); delete activePollers[id]; }
        updateJobsCount(-1);
        if (!$('.synthesis-card')) {
            const container = $('#jobs-container');
            if (container) container.innerHTML = `
                <div id="no-jobs-msg" class="text-center text-muted py-4">
                    <i class="fas fa-film fa-3x mb-2 d-block opacity-50"></i>
                    <p>Aucune vidéo générée pour l'instant.</p>
                </div>`;
        }
    });

    function openSettingsModal(btn) {
        if (!settingsModal) return;
        const jobId      = btn.dataset.jobId;
        const enhancer   = btn.dataset.useEnhancer === 'true';
        const bboxShift  = parseInt(btn.dataset.bboxShift || '0', 10);

        const jobIdInput = $('#settingsJobId');
        if (jobIdInput) jobIdInput.value = jobId;

        // Standalone-only (2026-07-15) : plus de TTS (relève du synthesizer). Réglages MuseTalk.
        // Le mode rapide/qualité est MORT (2026-08-03) : CodeFormer = seul contrôle de qualité.
        // Enhancer
        const enhancerCb = $('#settingsUseEnhancer');
        if (enhancerCb) enhancerCb.checked = enhancer;

        // Bbox
        if (settingsBboxSlider) {
            settingsBboxSlider.value = bboxShift;
            // Champ GÉNÉRÉ (WamaParams) : synchronise l affichage de valeur (.wama-range-val).
            settingsBboxSlider.dispatchEvent(new Event("input"));
        }
        if (settingsBboxVal)    settingsBboxVal.textContent = bboxShift;

        settingsModal.show();
    }

    function buildParamsHtml(useEnhancer, bboxShift) {
        // Standalone-only (2026-07-15) : l'audio vient d'amont/import, plus de TTS.
        let html = '<i class="fas fa-upload"></i> Audio<br>';
        html += useEnhancer
            ? '<i class="fas fa-wand-magic-sparkles"></i> CodeFormer'
            : '<i class="fas fa-bolt"></i> MuseTalk seul';
        if (bboxShift !== '0' && bboxShift !== 0) html += ` &bull; <i class="fas fa-arrows-alt-v"></i> ${bboxShift}`;
        return html;
    }

    async function saveJobSettings(startAfterSave) {
        const jobId = $('#settingsJobId') ? $('#settingsJobId').value : null;
        if (!jobId) return;

        const enhancerCb  = $('#settingsUseEnhancer');

        const newEnhancer  = !!(enhancerCb && enhancerCb.checked);
        const newBbox      = settingsBboxSlider ? settingsBboxSlider.value : '0';

        const fd = new FormData();
        fd.append('use_enhancer', newEnhancer ? 'true' : 'false');
        fd.append('bbox_shift',   newBbox);

        try {
            const resp = await fetch(`${cfg.urls.updateOptions}${jobId}/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrf },
                body: fd,
            });
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.error || 'Erreur mise à jour');

            // Mettre à jour l'affichage de la card sans rechargement
            const card = $(`#job-${jobId}`);
            if (card) {
                const mode = card.dataset.mode || 'pipeline';

                // 1. Rafraîchir le bloc paramètres (col-2)
                const paramsEl = $('.job-params-display', card);
                if (paramsEl) {
                    paramsEl.innerHTML = buildParamsHtml(newEnhancer, newBbox);
                }

                // 2. Mettre à jour les data-* du bouton settings (pour le prochain ouverture du modal)
                const settBtn = $('.settings-btn', card);   // graphie commune depuis le 23/08
                if (settBtn) {
                    settBtn.dataset.useEnhancer = newEnhancer ? 'true' : 'false';
                    settBtn.dataset.bboxShift   = newBbox;
                }
            }

            if (settingsModal) settingsModal.hide();

            if (startAfterSave) {
                try {
                    await startJob(jobId);
                    startPolling(jobId);
                } catch (err) {
                    WamaApp.toast('Erreur démarrage : ' + err.message, 'error');
                }
            }
        } catch (err) {
            WamaApp.toast('Erreur : ' + err.message, 'error');
        }
    }

    const btnSettingsSave      = $('#btnSettingsSave');
    const btnSettingsSaveStart = $('#btnSettingsSaveStart');
    if (btnSettingsSave)      btnSettingsSave.addEventListener('click',      () => saveJobSettings(false));
    if (btnSettingsSaveStart) btnSettingsSaveStart.addEventListener('click', () => saveJobSettings(true));

    // -----------------------------------------------------------------------
    // Bind delete / start / preview-video buttons on job cards
    // -----------------------------------------------------------------------
    function bindJobCardEvents(card) {
        // 🗑 : plus de bind PAR CARD ici — brique commune queue-actions.js, délégation unique
        // (portage 2026-08-23). Le résidu est déclaré une seule fois, plus bas.


        // ⚙ : plus de bind PAR CARD ici — la brique commune (queue-actions.js) délègue une fois
        // pour toutes, y compris sur les cards rendues après coup (portage 2026-08-23).
    }

    // Bind events on pre-existing job cards (server-side rendered)
    $$('.synthesis-card').forEach(card => {
        bindJobCardEvents(card);
        const status = card.dataset.status;
        if (status === 'RUNNING' || status === 'PENDING') {
            startPolling(card.dataset.jobId);
            // Initialise step label from progress-fill width
            const stepDesc = $('.step-desc', card);
            const fill     = $('.progress-fill', card);
            if (stepDesc && fill) {
                const prog = parseInt((fill.style.width || '0').replace('%', ''), 10);
                stepDesc.textContent = getStepLabel(prog, card.dataset.mode || 'pipeline');
            }
        }
    });

    // -----------------------------------------------------------------------
    // Clear all
    // -----------------------------------------------------------------------
    // Boutons globaux serveur (audit 2026-07-11)
    const btnStartAll = $('#startAllBtn');
    if (btnStartAll) {
        btnStartAll.addEventListener('click', async () => {
            try {
                const r = await fetch(cfg.urls.startAll, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrf },
                });
                const data = await r.json().catch(() => ({}));
                if (!r.ok) {
                    WamaApp.toast(data.error || 'Démarrage impossible', 'error');
                    return;
                }
                WamaApp.toast(`${data.count} job(s) démarré(s)`, 'success');
                location.reload();
            } catch (_) {
                WamaApp.toast('Erreur réseau', 'error');
            }
        });
    }

    const btnDownloadAll = $('#downloadAllBtn');
    if (btnDownloadAll) {
        btnDownloadAll.addEventListener('click', () => {
            window.location.href = cfg.urls.downloadAll;
        });
    }

    const btnClearAll = $('#clearAllBtn');
    if (btnClearAll) {
        btnClearAll.addEventListener('click', async () => {
            if (!confirm('Supprimer tous les jobs et leurs fichiers ?')) return;
            // Vue serveur commune (audit 2026-07-11) — remplace la boucle de DELETE unitaires
            try {
                const r = await fetch(cfg.urls.clearAll, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrf },
                });
                const data = await r.json().catch(() => ({}));
                if (!r.ok) {
                    WamaApp.toast(data.error || 'Suppression impossible', 'error');
                    return;
                }
            } catch (_) {
                WamaApp.toast('Erreur réseau', 'error');
                return;
            }
            $$('.synthesis-card').forEach((card) => {
                const jid = card.dataset.jobId;
                clearInterval(activePollers[jid]);
                delete activePollers[jid];
                card.remove();
            });
            if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
            const container = $('#jobs-container');
            if (container && !$('.synthesis-card')) {
                container.innerHTML = `
                    <div id="no-jobs-msg" class="text-center text-muted py-4">
                        <i class="fas fa-film fa-3x mb-2 d-block opacity-50"></i>
                        <p>Aucune vidéo générée pour l'instant.</p>
                    </div>`;
            }
            const counter = $('#jobs-count');
            if (counter) counter.textContent = '0';
        });
    }

    /* ============================================================
     * Import par fichier batch (format à balises)
     * ============================================================ */

    /* ============================================================
     * Actions d'ÉLÉMENT et de LOT : toutes à la brique commune
     * ============================================================
     * ⧉ d'un job → brique commune depuis le 2026-07-31.
     * ▶ ⧉ 🗑 d'un LOT → brique commune depuis le 2026-08-27 (`actions_communes=True` sur
     * l'include `_queue_entry.html`). Les trois handlers qui vivaient ici POSTaient vers des
     * URLs RECONSTRUITES à la main (`cfg.urls.batchStart + id + '/start/'`, un chemin littéral
     * dans le gabarit) : la card mère porte désormais `data-batch-*-url` résolue par `{% url %}`.
     * Le retrait et l'opt-in sont le MÊME geste — garder les deux aurait POSTé deux fois par clic.
     * Aucune suite à déclarer : l'avatarizer rechargeait après lancement, ce que fait le défaut
     * de la brique.
     */


    // ── Parametres de LOT : la ⚙ des cards batch communes ouvre la modale WamaParams
    // (context='batch'), le save POST vers batch_update (applique a tous les jobs du lot).
    let _batchSettingsModal = null;
    function ensureBatchSettingsModal() {
        if (_batchSettingsModal) return _batchSettingsModal;
        const el = document.getElementById('batchSettingsModal');
        if (!el || !window.bootstrap) return null;
        _batchSettingsModal = new bootstrap.Modal(el);
        const saveBtn = document.getElementById('saveBatchSettingsBtn');
        if (saveBtn) saveBtn.addEventListener('click', saveBatchSettings);
        return _batchSettingsModal;
    }

    async function saveBatchSettings() {
        const batchId = (document.getElementById('batchSettingsBatchId') || {}).value;
        const host = document.getElementById('avatarizerBatchParams');
        if (!batchId || !host || !window.WamaParams) return;
        const fd = new FormData();
        Object.entries(WamaParams.read(host)).forEach(([k, v]) => fd.append(k, v));
        try {
            const r = await fetch(`${cfg.urls.batch}${batchId}/update/`, {
                method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd,
            });
            if (!r.ok) throw new Error(`batch_update ${r.status}`);
            _batchSettingsModal.hide();
            WamaApp.toast('Paramètres appliqués au lot', 'success');
            window.location.reload();
        } catch (e) { WamaApp.toast(e.message || 'Erreur', 'error'); }
    }

    document.addEventListener('click', (e) => {
        const b = e.target.closest('.batch-settings-btn');
        if (!b) return;
        e.preventDefault();
        const m = ensureBatchSettingsModal();
        const idInput = document.getElementById('batchSettingsBatchId');
        if (idInput) idInput.value = b.dataset.batchId || '';
        if (m) m.show();
    });

})();
