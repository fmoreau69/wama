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
        const checked = $('input[name="workflow_mode"]:checked');
        return checked ? checked.value : 'pipeline';
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

    // -----------------------------------------------------------------------
    // Quality mode toggle — hint text + enhancer visibility
    // -----------------------------------------------------------------------
    const qmodeHint       = $('#qmode_hint');
    const enhancerSection = $('#enhancer_section');

    function updateQualityModeUI() {
        const mode = $('input[name="quality_mode"]:checked');
        if (!mode) return;
        if (mode.value === 'quality') {
            if (qmodeHint) qmodeHint.textContent = 'MuseTalk + CodeFormer — meilleure netteté';
            if (enhancerSection) enhancerSection.style.display = '';
        } else {
            if (qmodeHint) qmodeHint.textContent = 'MuseTalk seul — temps réel';
            if (enhancerSection) enhancerSection.style.display = 'none';
            const enhancerCb = $('#use_enhancer');
            if (enhancerCb) enhancerCb.checked = false;
        }
    }

    $$('input[name="quality_mode"]').forEach(r => r.addEventListener('change', updateQualityModeUI));
    updateQualityModeUI(); // init

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
            handleAvatarFile(e.dataTransfer.files[0]);
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
            alert('Format non supporté. Utilisez JPG, PNG ou WebP.');
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
            handleAudioFile(e.dataTransfer.files[0]);
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
                alert(`Format non supporté : .${ext}\nL'avatarizer accepte uniquement : ${allowedExts.join(', ')}`);
                return;
            }
            try {
                const mediaUrl = (window.MEDIA_URL || cfg.mediaUrl || '/media/') + path;
                const resp = await fetch(mediaUrl);
                if (!resp.ok) throw new Error(`Fichier introuvable sur le serveur (HTTP ${resp.status})`);
                const blob = await resp.blob();
                const file = new File([blob], name || 'audio', { type: blob.type || mime || 'audio/mpeg' });
                handleAudioFile(file);
                // S'assurer que l'onglet Standalone est actif
                const standaloneTab = $('#tab-standalone');
                if (standaloneTab) standaloneTab.click();
            } catch (err) {
                alert('Erreur lors du chargement du fichier depuis le Filemanager : ' + err.message);
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
    const textDropzone = $('#text-dropzone');
    // Formats identiques au Synthesizer
    const TEXT_EXTS_PLAIN  = ['txt', 'md', 'csv', 'text']; // lisibles directement côté client
    const TEXT_EXTS_SERVER = ['pdf', 'docx'];               // extraction serveur requise
    const TEXT_EXTS_ALL    = [...TEXT_EXTS_PLAIN, ...TEXT_EXTS_SERVER];

    function loadTextIntoArea(text) {
        if (!textArea) return;
        textArea.value = text;
        textArea.dispatchEvent(new Event('input')); // maj compteur mots + bouton générer
    }

    async function extractTextViaServer(formData) {
        const resp = await fetch(cfg.urls.extractText, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf },
            body: formData,
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || `Erreur extraction (HTTP ${resp.status})`);
        return data.text || '';
    }

    if (textDropzone) {
        // — Filemanager drag-and-drop —
        textDropzone.addEventListener('filemanager:filedrop', async (e) => {
            const { path, name } = e.detail;
            const ext = (name || '').split('.').pop().toLowerCase();
            if (!TEXT_EXTS_ALL.includes(ext)) {
                alert(`Format non supporté : .${ext}\nFormats acceptés : ${TEXT_EXTS_ALL.join(', ')}.`);
                return;
            }
            try {
                if (TEXT_EXTS_PLAIN.includes(ext)) {
                    // Lecture directe du fichier texte brut
                    const url = (window.MEDIA_URL || cfg.mediaUrl || '/media/') + path;
                    const resp = await fetch(url);
                    if (!resp.ok) throw new Error(`Fichier introuvable (HTTP ${resp.status})`);
                    loadTextIntoArea(await resp.text());
                } else {
                    // Extraction serveur (PDF, DOCX)
                    const fd = new FormData();
                    fd.append('media_path', path);
                    loadTextIntoArea(await extractTextViaServer(fd));
                }
            } catch (err) {
                alert('Erreur chargement fichier : ' + err.message);
            }
        });

        // — Windows Explorer / navigateur natif —
        textDropzone.addEventListener('dragover', e => {
            if (e.dataTransfer && e.dataTransfer.types && e.dataTransfer.types.includes('Files')) {
                e.preventDefault();
                textDropzone.classList.add('dragover');
            }
        });
        textDropzone.addEventListener('dragleave', e => {
            if (!textDropzone.contains(e.relatedTarget)) {
                textDropzone.classList.remove('dragover');
            }
        });
        textDropzone.addEventListener('drop', async (e) => {
            textDropzone.classList.remove('dragover');
            if (!e.dataTransfer || !e.dataTransfer.files || !e.dataTransfer.files.length) return;
            e.preventDefault();
            const file = e.dataTransfer.files[0];
            const ext = file.name.split('.').pop().toLowerCase();
            if (!TEXT_EXTS_ALL.includes(ext)) {
                alert(`Format non supporté : .${ext}\nFormats acceptés : ${TEXT_EXTS_ALL.join(', ')}.`);
                return;
            }
            try {
                if (TEXT_EXTS_PLAIN.includes(ext)) {
                    // Lecture client-side
                    const reader = new FileReader();
                    reader.onload = ev => loadTextIntoArea(ev.target.result);
                    reader.readAsText(file, 'UTF-8');
                } else {
                    // Envoi serveur pour extraction PDF/DOCX
                    const fd = new FormData();
                    fd.append('file', file);
                    loadTextIntoArea(await extractTextViaServer(fd));
                }
            } catch (err) {
                alert('Erreur extraction : ' + err.message);
            }
        });
    }

    function handleAudioFile(file) {
        if (!file) return;
        audioFile = file;
        audioFilename.textContent = file.name;
        audioInfo.classList.remove('d-none');
        updateGenerateButton();
    }

    // -----------------------------------------------------------------------
    // Mode radio sync (right panel ↔ left panel tabs)
    // -----------------------------------------------------------------------
    $$('input[name="workflow_mode"]').forEach(radio => {
        radio.addEventListener('change', () => {
            const mode = radio.value;
            const pipelineTab = $('#tab-pipeline');
            const standaloneTab = $('#tab-standalone');
            const pipelineSettings = $('#pipelineSettings');

            if (mode === 'pipeline') {
                pipelineTab && pipelineTab.click();
                pipelineSettings && (pipelineSettings.style.display = '');
            } else {
                standaloneTab && standaloneTab.click();
                pipelineSettings && (pipelineSettings.style.display = 'none');
            }
            updateGenerateButton();
        });
    });

    $$('#inputTabs .nav-link').forEach(btn => {
        btn.addEventListener('click', () => {
            const mode = btn.id === 'tab-pipeline' ? 'pipeline' : 'standalone';
            const radio = $(`input[name="workflow_mode"][value="${mode}"]`);
            if (radio) {
                radio.checked = true;
                radio.dispatchEvent(new Event('change'));
            }
        });
    });

    // -----------------------------------------------------------------------
    // Update "Generate" button state
    // -----------------------------------------------------------------------
    function updateGenerateButton() {
        const btn = $('#btn-generate');
        if (!btn) return;

        const mode = getMode();
        let ready = true;

        if (mode === 'pipeline') {
            const text = textArea ? textArea.value.trim() : '';
            if (!text) ready = false;
        } else {
            if (!audioFile) ready = false;
        }

        if (!selectedAvatarSource) ready = false;
        btn.disabled = !ready;
    }

    if (textArea) {
        textArea.addEventListener('input', updateGenerateButton);
    }

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

            } catch (err) {
                alert('Erreur : ' + err.message);
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
    async function createJob() {
        const mode = getMode();
        const fd = new FormData();
        fd.append('mode', mode);

        if (mode === 'pipeline') {
            fd.append('text_content', textArea.value.trim());
            fd.append('tts_model', $('#tts_model').value);
            fd.append('language', $('#language').value);
            fd.append('voice_preset', $('#voice_preset').value);
        } else {
            fd.append('audio_input', audioFile);
        }

        fd.append('avatar_source', selectedAvatarSource);
        if (selectedAvatarSource === 'gallery') {
            fd.append('avatar_gallery_name', selectedAvatarName);
        } else {
            fd.append('avatar_upload', avatarUploadFile);
        }

        const qmode = $('input[name="quality_mode"]:checked');
        fd.append('quality_mode', qmode ? qmode.value : 'fast');
        fd.append('bbox_shift', bboxSlider ? bboxSlider.value : '0');
        fd.append('use_enhancer', $('#use_enhancer') && $('#use_enhancer').checked ? 'true' : 'false');

        const resp = await fetch(cfg.urls.create, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf },
            body: fd,
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erreur création job');
        return data.job_id;
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
        if (progress >= 10)  return mode === 'pipeline' ? 'Synthèse audio TTS…' : 'Chargement audio…';
        if (progress >= 5)   return 'Démarrage…';
        return 'En attente…';
    }

    // -----------------------------------------------------------------------
    // Add job card dynamically (new job) — synthesis-card layout
    // -----------------------------------------------------------------------
    function addJobCard(jobId) {
        const container = $('#jobs-container');
        const noJobsMsg = $('#no-jobs-msg');
        if (noJobsMsg) noJobsMsg.remove();

        const mode = getMode();
        const qualityMode  = $('input[name="quality_mode"]:checked');
        const qIsQuality   = qualityMode && qualityMode.value === 'quality';
        const useEnhancer  = $('#use_enhancer') && $('#use_enhancer').checked;
        const bboxShiftVal = bboxSlider ? bboxSlider.value : '0';
        const textPreview  = (textArea && mode === 'pipeline') ? textArea.value.trim().substring(0, 60) : '';
        const now          = new Date().toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
        const modeLabel    = mode === 'pipeline' ? 'Pipeline' : 'Standalone';

        // Avatar thumbnail
        let thumbHtml;
        let avatarDisplayName;
        if (selectedAvatarSource === 'gallery' && selectedAvatarName) {
            const url = cfg.mediaUrl + 'avatarizer/gallery/' + selectedAvatarName;
            thumbHtml = `<img src="${url}" style="width:48px;height:48px;object-fit:cover;border-radius:4px;flex-shrink:0;" alt="${selectedAvatarName}">`;
            avatarDisplayName = selectedAvatarName.length > 14 ? selectedAvatarName.substring(0, 14) + '…' : selectedAvatarName;
        } else if (selectedAvatarSource === 'upload' && avatarUploadFile) {
            const objUrl = URL.createObjectURL(avatarUploadFile);
            thumbHtml = `<img src="${objUrl}" style="width:48px;height:48px;object-fit:cover;border-radius:4px;flex-shrink:0;" alt="Avatar">`;
            avatarDisplayName = 'Photo importée';
        } else {
            thumbHtml = `<div style="width:48px;height:48px;border-radius:4px;background:#343a40;flex-shrink:0;display:flex;align-items:center;justify-content:center;"><i class="fas fa-user text-muted"></i></div>`;
            avatarDisplayName = '—';
        }

        // Col 2: paramètres
        let col2Html = '';
        if (mode === 'pipeline') {
            const ttsEl = $('#tts_model');
            const ttsLabel = ttsEl ? ttsEl.options[ttsEl.selectedIndex].text : '';
            const lang  = $('#language')     ? $('#language').value : '';
            const voice = $('#voice_preset') ? $('#voice_preset').value : '';
            col2Html  = `<i class="fas fa-robot"></i> ${ttsLabel}<br>`;
            col2Html += `<i class="fas fa-language"></i> ${lang}<br>`;
            col2Html += `<i class="fas fa-microphone"></i> ${voice}<br>`;
        } else {
            col2Html = `<i class="fas fa-upload"></i> Audio importé<br>`;
        }
        col2Html += `<i class="fas fa-${qIsQuality ? 'star' : 'bolt'}"></i> ${qIsQuality ? 'Qualité' : 'Rapide'}`;
        if (useEnhancer) col2Html += ` <span class="badge bg-secondary" style="font-size:0.6rem;">CF</span>`;
        if (bboxShiftVal !== '0') col2Html += ` &bull; <i class="fas fa-arrows-alt-v"></i> ${bboxShiftVal}`;

        const card = document.createElement('div');
        card.className = 'synthesis-card';
        card.id = `job-${jobId}`;
        card.dataset.jobId = jobId;
        card.dataset.status = 'PENDING';
        card.dataset.mode = mode;
        card.dataset.textPreview = textPreview;
        card.innerHTML = `
            <div class="row align-items-center g-2">
                <div class="col-3 d-flex align-items-start gap-2">
                    ${thumbHtml}
                    <div>
                        <strong class="text-light d-block">${avatarDisplayName}</strong>
                        <small class="text-white-50">${modeLabel} &bull; ${now}</small>
                    </div>
                </div>
                <div class="col-3">
                    <small class="job-params-display">${col2Html}</small>
                </div>
                <div class="col-2">
                    <small class="text-white-50 step-desc">En attente…</small>
                </div>
                <div class="col-2">
                    <span class="badge bg-secondary job-status-badge">En attente</span>
                    <div class="progress-bar-custom mt-2">
                        <div class="progress-fill" style="width:0%"></div>
                    </div>
                    <small class="text-light progress-text">0%</small>
                </div>
                <div class="col-2">
                    <div class="btn-group-actions flex-wrap">
                        <button class="btn btn-sm btn-outline-warning btn-start-job" data-job-id="${jobId}" title="Relancer" style="display:none;">
                            <i class="fas fa-redo"></i>
                        </button>
                        <button class="btn btn-sm btn-secondary btn-settings-job"
                                data-job-id="${jobId}"
                                data-mode="${mode}"
                                data-tts-model="${$('#tts_model') ? $('#tts_model').value : ''}"
                                data-language="${$('#language') ? $('#language').value : 'fr'}"
                                data-voice-preset="${$('#voice_preset') ? $('#voice_preset').value : 'default'}"
                                data-quality-mode="${qualityMode ? qualityMode.value : 'fast'}"
                                data-use-enhancer="${useEnhancer ? 'true' : 'false'}"
                                data-bbox-shift="${bboxShiftVal}"
                                title="Paramètres"
                                style="display:none;">
                            <i class="fas fa-cog"></i>
                        </button>
                        <button class="btn btn-sm btn-danger btn-delete-job" data-job-id="${jobId}" title="Supprimer">
                            <i class="fas fa-trash"></i>
                        </button>
                    </div>
                </div>
            </div>
            <div id="preview-row-${jobId}"></div>
        `;
        container.prepend(card);
        bindJobCardEvents(card);
    }

    // -----------------------------------------------------------------------
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

        const badge      = $('.job-status-badge', card);
        const fill       = $('.progress-fill', card);
        const progText   = $('.progress-text', card);
        const stepDesc   = $('.step-desc', card);
        const actionsDiv = $('.btn-group-actions', card);

        const statusMap = {
            PENDING: { label: 'En attente',  cls: 'bg-secondary',        cardCls: '' },
            RUNNING: { label: 'En cours',    cls: 'bg-warning text-dark', cardCls: 'processing' },
            SUCCESS: { label: 'Terminé',     cls: 'bg-success',           cardCls: 'success' },
            FAILURE: { label: 'Échec',       cls: 'bg-danger',            cardCls: 'error' },
        };
        const st = statusMap[data.status] || { label: data.status, cls: 'bg-secondary', cardCls: '' };

        // Colored left border via card class
        card.className = `synthesis-card${st.cardCls ? ' ' + st.cardCls : ''}`;

        if (badge) {
            badge.textContent = st.label;
            badge.className = `badge ${st.cls} job-status-badge`;
        }
        if (fill)     fill.style.width = data.progress + '%';
        if (progText) progText.textContent = data.progress + '%';

        // Step description (col 3)
        if (stepDesc) {
            const mode = data.mode || card.dataset.mode || 'pipeline';
            if (data.status === 'RUNNING' || data.status === 'PENDING') {
                stepDesc.textContent = getStepLabel(data.progress, mode);
            } else if (data.status === 'SUCCESS') {
                const preview = data.text_preview || card.dataset.textPreview || '';
                stepDesc.textContent = preview ? `"${preview}"` : 'Vidéo générée ✓';
            } else if (data.status === 'FAILURE') {
                stepDesc.textContent = (data.error || 'Erreur').substring(0, 50);
            }
        }

        // Montrer/cacher les boutons start + settings selon statut
        const startBtnEl    = $('.btn-start-job', card);
        const settingsBtnEl = $('.btn-settings-job', card);
        const isActive = data.status === 'RUNNING' || data.status === 'PENDING';
        if (startBtnEl)    startBtnEl.style.display    = isActive ? 'none' : '';
        if (settingsBtnEl) settingsBtnEl.style.display = isActive ? 'none' : '';

        // SUCCESS : injecter download + prévisualisation vidéo
        if (data.status === 'SUCCESS' && data.video_url && actionsDiv) {
            if (!$('.btn-download-job', actionsDiv)) {
                const dlLink = document.createElement('a');
                dlLink.href = `${cfg.urls.download}${jobId}/`;
                dlLink.className = 'btn btn-sm btn-info btn-download-job';
                dlLink.title = 'Télécharger';
                dlLink.innerHTML = '<i class="fas fa-download"></i>';
                const deleteBtn = $('.btn-delete-job', actionsDiv);
                actionsDiv.insertBefore(dlLink, deleteBtn);
            }

            const previewRow = $(`#preview-row-${jobId}`);
            if (previewRow && !$('video', previewRow)) {
                previewRow.innerHTML = `
                    <div class="row mt-2">
                        <div class="col-12">
                            <video class="w-100" controls style="border-radius:6px;max-height:220px;">
                                <source src="${data.video_url}" type="video/mp4">
                            </video>
                        </div>
                    </div>`;
            }
        }

        // FAILURE : s'assurer que le bouton retry est visible (il est déjà dans le DOM, juste caché)
        if (data.status === 'FAILURE' && startBtnEl) {
            startBtnEl.style.display = '';
        }

        card.dataset.status = data.status;
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

    function openSettingsModal(btn) {
        if (!settingsModal) return;
        const jobId      = btn.dataset.jobId;
        const mode       = btn.dataset.mode;
        const ttsModel   = btn.dataset.ttsModel   || '';
        const language   = btn.dataset.language    || 'fr';
        const voice      = btn.dataset.voicePreset || 'default';
        const qmode      = btn.dataset.qualityMode || 'fast';
        const enhancer   = btn.dataset.useEnhancer === 'true';
        const bboxShift  = parseInt(btn.dataset.bboxShift || '0', 10);

        const jobIdInput = $('#settingsJobId');
        if (jobIdInput) jobIdInput.value = jobId;

        // Pipeline / standalone section visibility
        const pipelineSection = $('#settingsPipelineSection');
        if (pipelineSection) pipelineSection.style.display = mode === 'pipeline' ? '' : 'none';

        // Pre-fill TTS fields
        const ttsModelSel = $('#settingsTtsModel');
        if (ttsModelSel) ttsModelSel.value = ttsModel;
        const langSel = $('#settingsLanguage');
        if (langSel) langSel.value = language;
        const voiceSel = $('#settingsVoicePreset');
        if (voiceSel) voiceSel.value = voice;

        // Quality mode
        const qRadio = $(`input[name="settings_quality_mode"][value="${qmode}"]`);
        if (qRadio) qRadio.checked = true;

        // Enhancer
        const enhancerCb = $('#settingsUseEnhancer');
        if (enhancerCb) enhancerCb.checked = enhancer;

        // Bbox
        if (settingsBboxSlider) settingsBboxSlider.value = bboxShift;
        if (settingsBboxVal)    settingsBboxVal.textContent = bboxShift;

        settingsModal.show();
    }

    function buildParamsHtml(mode, ttsLabel, lang, voice, qmode, useEnhancer, bboxShift) {
        let html = '';
        if (mode === 'pipeline') {
            html += `<i class="fas fa-robot"></i> ${ttsLabel}<br>`;
            html += `<i class="fas fa-language"></i> ${lang}<br>`;
            html += `<i class="fas fa-microphone"></i> ${voice}<br>`;
        } else {
            html += `<i class="fas fa-upload"></i> Audio importé<br>`;
        }
        const qIsQuality = qmode === 'quality';
        html += `<i class="fas fa-${qIsQuality ? 'star' : 'bolt'}"></i> ${qIsQuality ? 'Qualité' : 'Rapide'}`;
        if (useEnhancer) html += ` <span class="badge bg-secondary" style="font-size:0.6rem;">CF</span>`;
        if (bboxShift !== '0' && bboxShift !== 0) html += ` &bull; <i class="fas fa-arrows-alt-v"></i> ${bboxShift}`;
        return html;
    }

    async function saveJobSettings(startAfterSave) {
        const jobId = $('#settingsJobId') ? $('#settingsJobId').value : null;
        if (!jobId) return;

        const ttsModelSel = $('#settingsTtsModel');
        const langSel     = $('#settingsLanguage');
        const voiceSel    = $('#settingsVoicePreset');
        const qRadio      = $('input[name="settings_quality_mode"]:checked');
        const enhancerCb  = $('#settingsUseEnhancer');

        const newTtsModel  = ttsModelSel ? ttsModelSel.value : '';
        const newTtsLabel  = ttsModelSel ? ttsModelSel.options[ttsModelSel.selectedIndex].text : '';
        const newLang      = langSel    ? langSel.value    : '';
        const newVoice     = voiceSel   ? voiceSel.value   : '';
        const newQmode     = qRadio     ? qRadio.value     : 'fast';
        const newEnhancer  = !!(enhancerCb && enhancerCb.checked);
        const newBbox      = settingsBboxSlider ? settingsBboxSlider.value : '0';

        const fd = new FormData();
        fd.append('tts_model',   newTtsModel);
        fd.append('language',    newLang);
        fd.append('voice_preset', newVoice);
        fd.append('quality_mode', newQmode);
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
                    paramsEl.innerHTML = buildParamsHtml(mode, newTtsLabel, newLang, newVoice, newQmode, newEnhancer, newBbox);
                }

                // 2. Mettre à jour les data-* du bouton settings (pour le prochain ouverture du modal)
                const settBtn = $('.btn-settings-job', card);
                if (settBtn) {
                    settBtn.dataset.ttsModel    = newTtsModel;
                    settBtn.dataset.language    = newLang;
                    settBtn.dataset.voicePreset = newVoice;
                    settBtn.dataset.qualityMode = newQmode;
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
                    alert('Erreur démarrage : ' + err.message);
                }
            }
        } catch (err) {
            alert('Erreur : ' + err.message);
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
        const deleteBtn = $('.btn-delete-job', card);
        if (deleteBtn) {
            deleteBtn.addEventListener('click', async () => {
                const jid = deleteBtn.dataset.jobId;
                if (!confirm('Supprimer cette vidéo ?')) return;
                try {
                    const resp = await fetch(`${cfg.urls.delete}${jid}/`, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': csrf },
                    });
                    if (resp.ok) {
                        clearInterval(activePollers[jid]);
                        delete activePollers[jid];
                        card.remove();
                        updateJobsCount(-1);
                        if (!$('.synthesis-card')) {
                            const container = $('#jobs-container');
                            if (container) container.innerHTML = `
                                <div id="no-jobs-msg" class="text-center text-muted py-4">
                                    <i class="fas fa-film fa-3x mb-2 d-block opacity-50"></i>
                                    <p>Aucune vidéo générée pour l'instant.</p>
                                </div>`;
                        }
                    }
                } catch (err) {
                    alert('Erreur lors de la suppression : ' + err.message);
                }
            });
        }

        const startBtn = $('.btn-start-job', card);
        if (startBtn) {
            startBtn.addEventListener('click', async () => {
                const jid = startBtn.dataset.jobId;
                try {
                    await startJob(jid);
                    startPolling(jid);
                } catch (err) {
                    alert('Erreur : ' + err.message);
                }
            });
        }

        const settingsBtn = $('.btn-settings-job', card);
        if (settingsBtn) {
            settingsBtn.addEventListener('click', () => openSettingsModal(settingsBtn));
        }
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
    const btnClearAll = $('#btn-clear-all');
    if (btnClearAll) {
        btnClearAll.addEventListener('click', async () => {
            if (!confirm('Supprimer tous les jobs et leurs fichiers ?')) return;
            const cards = $$('.synthesis-card');
            for (const card of cards) {
                const jid = card.dataset.jobId;
                try {
                    await fetch(`${cfg.urls.delete}${jid}/`, {
                        method: 'POST',
                        headers: { 'X-CSRFToken': csrf },
                    });
                    clearInterval(activePollers[jid]);
                    delete activePollers[jid];
                    card.remove();
                } catch (_) {}
            }
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

})();
