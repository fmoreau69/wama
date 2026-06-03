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
    const outputFmtSel   = document.getElementById('converterOutputFormat');
    const mediaTypeBadge = document.getElementById('converterMediaTypeBadge');
    const queue          = document.getElementById('converterQueue');
    const emptyState     = document.getElementById('converterEmptyState');

    // Options panels
    const imageOpts      = document.getElementById('imageOptions');
    const videoOpts      = document.getElementById('videoOptions');
    const audioOpts      = document.getElementById('audioOptions');
    const transformsOpts = document.getElementById('transformsOptions');

    // Global action buttons
    const startAllBtn = document.getElementById('converterStartAllBtn');
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

        // Format dropdown
        outputFmtSel.innerHTML = '';
        if (!type) {
            outputFmtSel.disabled = true;
            outputFmtSel.innerHTML = '<option value="">— choisissez un fichier —</option>';
        } else {
            outputFmtSel.disabled = false;
            FORMATS[type].output.forEach(fmt => {
                const opt = document.createElement('option');
                opt.value = fmt;
                opt.textContent = '.' + fmt.toUpperCase();
                outputFmtSel.appendChild(opt);
            });
        }

        // Options panels
        imageOpts.style.display = type === 'image' ? '' : 'none';
        videoOpts.style.display = type === 'video' ? '' : 'none';
        audioOpts.style.display = type === 'audio' ? '' : 'none';
        if (transformsOpts) {
            transformsOpts.style.display = (type === 'image' || type === 'video') ? '' : 'none';
        }

        // Filter profile dropdown to current media type
        renderProfileDropdown(type);
    }

    function readMainPanelOptions() {
        const opts = {};
        if (currentMediaType === 'image') {
            opts.quality  = parseInt(document.getElementById('imageQuality').value) || 85;
            const rw = parseInt(document.getElementById('resizeW').value) || 0;
            const rh = parseInt(document.getElementById('resizeH').value) || 0;
            if (rw) opts.resize_w = rw;
            if (rh) opts.resize_h = rh;
        } else if (currentMediaType === 'video') {
            const crf = document.getElementById('videoCRF').value;
            if (crf) opts.video_quality = parseInt(crf);
            const fps = document.getElementById('videoFPS').value;
            if (fps) opts.fps = parseFloat(fps);
        } else if (currentMediaType === 'audio') {
            const br = document.getElementById('audioBitrate').value;
            if (br) opts.audio_bitrate = br;
            if (document.getElementById('audioNormalize').checked) opts.normalize = true;
        }
        // Transforms (visible for image and video)
        if (currentMediaType === 'image' || currentMediaType === 'video') {
            const rot = parseInt(document.getElementById('rotation')?.value || '0', 10);
            if (rot) opts.rotation = rot;
            if (document.getElementById('flipH')?.checked) opts.flip_h = true;
            if (document.getElementById('flipV')?.checked) opts.flip_v = true;
        }
        return opts;
    }

    function applyOptionsToMainPanel(mediaType, opts) {
        opts = opts || {};
        if (mediaType === 'image') {
            const q = document.getElementById('imageQuality');
            if (q) {
                q.value = opts.quality != null ? opts.quality : 85;
                const disp = document.getElementById('qualityDisplay');
                if (disp) disp.textContent = q.value;
            }
            const rw = document.getElementById('resizeW'); if (rw) rw.value = opts.resize_w || '';
            const rh = document.getElementById('resizeH'); if (rh) rh.value = opts.resize_h || '';
        } else if (mediaType === 'video') {
            const crf = document.getElementById('videoCRF');
            if (crf) crf.value = opts.video_quality != null ? opts.video_quality : '';
            const fps = document.getElementById('videoFPS');
            if (fps) fps.value = opts.fps != null ? opts.fps : '';
        } else if (mediaType === 'audio') {
            const br = document.getElementById('audioBitrate');
            if (br) br.value = opts.audio_bitrate || '192k';
            const norm = document.getElementById('audioNormalize');
            if (norm) norm.checked = !!opts.normalize;
        }
        // Transforms (image + video)
        if (mediaType === 'image' || mediaType === 'video') {
            const rot = document.getElementById('rotation');
            if (rot) rot.value = String(opts.rotation || 0);
            const fh = document.getElementById('flipH');
            if (fh) fh.checked = !!opts.flip_h;
            const fv = document.getElementById('flipV');
            if (fv) fv.checked = !!opts.flip_v;
        }
    }

    // ── Upload ────────────────────────────────────────────────────────────────

    // Upload UN fichier → retourne son job_id (ou null). PAS de reload ici :
    // le reload se fait une fois après la consolidation (handleFiles).
    async function uploadFile(file) {
        const mediaType = detectMediaType(file.name);
        if (!mediaType) { alert(`Format non supporté : ${file.name}`); return null; }
        const outputFmt = outputFmtSel.value;
        if (!outputFmt) {
            alert('Choisissez un format de sortie avant d\'envoyer un fichier.');
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
                alert('Erreur : ' + (data.error || resp.statusText));
                return null;
            }
            return data.job_id || null;
        } catch (err) {
            alert('Erreur réseau : ' + err.message);
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

    dropZone.addEventListener('dragover', e => {
        e.preventDefault();
        dropZone.classList.add('dragover');
    });
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('dragover'));
    dropZone.addEventListener('drop', e => {
        e.preventDefault();
        dropZone.classList.remove('dragover');
        handleFiles(e.dataTransfer.files);
    });

    fileInput.addEventListener('change', () => {
        handleFiles(fileInput.files);
        fileInput.value = '';
    });

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
        if (card) card.dataset.status = 'RUNNING';
        try {
            const resp = await csrfPost(urlFor(APP.urls.start, jobId));
            if (resp.ok) {
                startPolling(jobId);
            } else {
                const d = await resp.json();
                alert(d.error || 'Erreur démarrage');
            }
        } catch (err) {
            alert('Erreur réseau : ' + err.message);
        }
    }

    async function deleteJob(jobId) {
        if (!confirm('Supprimer cette conversion ?')) return;
        try {
            await csrfPost(urlFor(APP.urls.delete, jobId));
            const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
            if (card) card.remove();
            stopPolling(jobId);
            if (!queue.querySelector('.job-card')) {
                if (!emptyState) location.reload();
            }
        } catch (err) {
            alert('Erreur réseau : ' + err.message);
        }
    }

    async function duplicateJob(jobId) {
        try {
            await csrfPost(urlFor(APP.urls.duplicate, jobId));
            location.reload();
        } catch (err) {
            alert('Erreur réseau : ' + err.message);
        }
    }

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
            updateCard(jobId, data);
            if (data.status === 'DONE' || data.status === 'ERROR') {
                stopPolling(jobId);
            }
        } catch (_) { /* ignore */ }
    }

    function updateCard(jobId, data) {
        const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
        if (!card) return;
        card.dataset.status = data.status;

        // Status badge — cibler le badge de STATUT (.status-badge), pas le badge
        // de format qui est aussi un .badge et apparaît en premier.
        const badge = card.querySelector('.status-badge') || card.querySelector('.badge');
        if (badge) {
            const STATUS_LABELS = {
                PENDING: 'En attente', RUNNING: 'En cours', DONE: 'Terminé', ERROR: 'Erreur'
            };
            const STATUS_CLASSES = {
                PENDING: 'bg-secondary', RUNNING: 'bg-warning text-dark',
                DONE: 'bg-success', ERROR: 'bg-danger'
            };
            badge.className = `badge status-badge ${STATUS_CLASSES[data.status] || 'bg-secondary'} badge-media`;
            badge.textContent = STATUS_LABELS[data.status] || data.status;
        }

        // Output-format badge update (in case settings changed it)
        if (data.output_format) {
            const filenameSpan = card.querySelector('.fw-bold');
            if (filenameSpan) {
                let fmtBadge = filenameSpan.parentElement.querySelector('.badge-media.bg-secondary');
                if (fmtBadge && fmtBadge.textContent.trim().startsWith('→')) {
                    fmtBadge.textContent = '→ .' + data.output_format;
                }
            }
        }

        // Progress bar
        let progressBar = card.querySelector('.wama-progress-fill');
        if (data.status === 'RUNNING') {
            if (!progressBar) {
                const track = document.createElement('div');
                track.className = 'wama-progress-track mt-2';
                const fill = document.createElement('div');
                fill.className = 'wama-progress-fill';
                track.appendChild(fill);
                card.appendChild(track);
                progressBar = fill;
            }
            progressBar.style.width = data.progress + '%';
        } else if (data.status === 'DONE') {
            const track = card.querySelector('.wama-progress-track');
            if (track) track.remove();
            let info = card.querySelector('.job-info-line');
            if (!info) {
                info = document.createElement('div');
                info.className = 'text-success small mt-1 job-info-line';
                card.appendChild(info);
            }
            info.innerHTML = `<i class="fas fa-check-circle"></i> ${data.output_filename || 'Converti'}`;

            const dlBtn = card.querySelector('.btn-outline-info');
            if (dlBtn) {
                const dlLink = document.createElement('a');
                dlLink.href = urlFor(APP.urls.download, jobId);
                dlLink.className = dlBtn.className;
                dlLink.title = 'Télécharger';
                dlLink.innerHTML = '<i class="fas fa-download"></i>';
                dlBtn.replaceWith(dlLink);
            }
            const startBtn = card.querySelector('.job-start-btn');
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fas fa-redo"></i>';
                startBtn.title = 'Recommencer';
            }
        } else if (data.status === 'ERROR') {
            const track = card.querySelector('.wama-progress-track');
            if (track) track.remove();
            let info = card.querySelector('.job-info-line');
            if (!info) {
                info = document.createElement('div');
                info.className = 'text-danger small mt-1 job-info-line';
                card.appendChild(info);
            }
            info.innerHTML = `<i class="fas fa-exclamation-triangle"></i> ${data.error_message}`;
            const startBtn = card.querySelector('.job-start-btn');
            if (startBtn) {
                startBtn.disabled = false;
                startBtn.innerHTML = '<i class="fas fa-redo"></i>';
            }
        }
    }

    // ── Event delegation for queue buttons ────────────────────────────────────

    queue.addEventListener('click', e => {
        const startBtn = e.target.closest('.job-start-btn');
        if (startBtn) { startJob(startBtn.dataset.jobId); return; }

        const delBtn = e.target.closest('.job-delete-btn');
        if (delBtn) { deleteJob(delBtn.dataset.jobId); return; }

        const dupBtn = e.target.closest('.job-duplicate-btn');
        if (dupBtn) { duplicateJob(dupBtn.dataset.jobId); return; }

        const settBtn = e.target.closest('.job-settings-btn');
        if (settBtn) { openSettingsModal(settBtn.dataset.jobId); return; }

        // ── Actions de groupe batch (stopPropagation → ne pas toggler le collapse) ──
        const bSet = e.target.closest('.batch-settings-btn');
        if (bSet) { e.stopPropagation(); openBatchSettingsModal(bSet.dataset.batchId, bSet.dataset.mediaType); return; }

        const bStart = e.target.closest('.batch-start-btn');
        if (bStart) { e.stopPropagation(); startBatch(bStart.dataset.batchId); return; }

        const bDel = e.target.closest('.batch-delete-btn');
        if (bDel) { e.stopPropagation(); deleteBatch(bDel.dataset.batchId); return; }
    });

    // ── Batch group actions ─────────────────────────────────────────────────────

    async function startBatch(batchId) {
        try {
            const resp = await csrfPost(urlFor(APP.urls.batchStart, batchId));
            const data = await resp.json();
            if (data.started && data.started.length) data.started.forEach(id => startPolling(id));
            location.reload();
        } catch (err) { alert('Erreur : ' + err.message); }
    }

    async function deleteBatch(batchId) {
        if (!confirm('Supprimer ce batch et tous ses fichiers ?')) return;
        try {
            await csrfPost(urlFor(APP.urls.batchDelete, batchId));
            location.reload();
        } catch (err) { alert('Erreur : ' + err.message); }
    }

    let _currentBatchId = null;
    function openBatchSettingsModal(batchId, mediaType) {
        _currentBatchId = batchId;
        const fmtSel = document.getElementById('batchSettingsFormat');
        const errEl  = document.getElementById('batchSettingsError');
        if (errEl) { errEl.style.display = 'none'; errEl.textContent = ''; }
        // Peuple le dropdown avec les formats de la nature du batch
        const formats = (FORMATS[mediaType] || {}).output || [];
        fmtSel.innerHTML = '<option value="">— inchangé —</option>';
        formats.forEach(f => {
            const o = document.createElement('option');
            o.value = f; o.textContent = '.' + f.toUpperCase();
            fmtSel.appendChild(o);
        });
        new bootstrap.Modal(document.getElementById('batchSettingsModal')).show();
    }

    async function applyBatchSettings(thenStart) {
        const fmt  = document.getElementById('batchSettingsFormat').value;
        const qual = document.getElementById('batchSettingsQuality').value;
        const errEl = document.getElementById('batchSettingsError');
        const fd = new FormData();
        fd.append('output_format', fmt);
        fd.append('output_quality', qual);
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
            alert('Erreur : ' + err.message);
        }
    });

    clearAllBtn && clearAllBtn.addEventListener('click', async () => {
        if (!confirm('Effacer toutes les conversions ?')) return;
        try {
            await csrfPost(APP.urls.clearAll);
            location.reload();
        } catch (err) {
            alert('Erreur : ' + err.message);
        }
    });

    // ── Settings modal — dynamic form + apply / restart ───────────────────────

    /**
     * Build the modal body HTML for editing a job's options.
     * Uses data-key attributes so we can read values back generically.
     */
    function buildModalFormHTML(mediaType, outputFormat, opts) {
        opts = opts || {};
        const escape = (s) => String(s).replace(/[&<>"']/g, ch =>
            ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));

        // Output format dropdown
        const formats = (FORMATS[mediaType] || {}).output || [];
        const fmtOpts = formats.map(f => {
            const sel = (f === outputFormat) ? ' selected' : '';
            return `<option value="${escape(f)}"${sel}>.${escape(f.toUpperCase())}</option>`;
        }).join('');

        let body = `
            <div class="mb-3">
                <label class="form-label small fw-bold text-light">
                    <i class="fas fa-file-export"></i> Format de sortie
                </label>
                <select class="form-select form-select-sm" data-key="output_format">${fmtOpts}</select>
            </div>
        `;

        const transformsHTML = (mt) => {
            if (mt !== 'image' && mt !== 'video') return '';
            const rot = String(opts.rotation || 0);
            const sel = v => (v === rot ? ' selected' : '');
            const fh = opts.flip_h ? ' checked' : '';
            const fv = opts.flip_v ? ' checked' : '';
            return `
                <hr class="border-secondary my-2">
                <div class="mb-2">
                    <label class="form-label small fw-bold text-light"><i class="fas fa-redo"></i> Rotation</label>
                    <select class="form-select form-select-sm" data-key="rotation">
                        <option value="0"${sel('0')}>Aucune</option>
                        <option value="90"${sel('90')}>90° gauche</option>
                        <option value="180"${sel('180')}>180° (inversé)</option>
                        <option value="270"${sel('270')}>90° droite</option>
                    </select>
                </div>
                <div class="row g-1 mb-2">
                    <div class="col-6">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" data-key="flip_h"${fh}>
                            <label class="form-check-label small">↔ Miroir H</label>
                        </div>
                    </div>
                    <div class="col-6">
                        <div class="form-check">
                            <input class="form-check-input" type="checkbox" data-key="flip_v"${fv}>
                            <label class="form-check-label small">↕ Miroir V</label>
                        </div>
                    </div>
                </div>
            `;
        };

        if (mediaType === 'image') {
            const q = opts.quality != null ? opts.quality : 85;
            body += `
                <div class="mb-2">
                    <label class="form-label small fw-bold text-light">
                        <i class="fas fa-sliders-h"></i> Qualité (JPG/WebP/AVIF)
                        <span class="text-muted ms-1" data-display="quality">${escape(q)}</span>
                    </label>
                    <input type="range" class="form-range" min="1" max="100" value="${escape(q)}"
                           data-key="quality"
                           oninput="this.parentNode.querySelector('[data-display=quality]').textContent=this.value">
                </div>
                <div class="row g-1 mb-2">
                    <div class="col-6">
                        <label class="form-label small text-muted mb-1">Largeur (px)</label>
                        <input type="number" class="form-control form-control-sm" data-key="resize_w"
                               placeholder="0 = auto" min="0" value="${escape(opts.resize_w || '')}">
                    </div>
                    <div class="col-6">
                        <label class="form-label small text-muted mb-1">Hauteur (px)</label>
                        <input type="number" class="form-control form-control-sm" data-key="resize_h"
                               placeholder="0 = auto" min="0" value="${escape(opts.resize_h || '')}">
                    </div>
                </div>
            `;
        } else if (mediaType === 'video') {
            body += `
                <div class="mb-2">
                    <label class="form-label small fw-bold text-light">
                        <i class="fas fa-film"></i> Qualité vidéo (CRF 0–51)
                    </label>
                    <input type="number" class="form-control form-control-sm" data-key="video_quality"
                           placeholder="23 (défaut)" min="0" max="51"
                           value="${escape(opts.video_quality != null ? opts.video_quality : '')}">
                </div>
                <div class="mb-2">
                    <label class="form-label small fw-bold text-light">
                        <i class="fas fa-tachometer-alt"></i> FPS <span class="text-muted">(vide = conserver)</span>
                    </label>
                    <input type="number" class="form-control form-control-sm" data-key="fps"
                           placeholder="25, 30, 60…" min="1" max="120"
                           value="${escape(opts.fps != null ? opts.fps : '')}">
                </div>
            `;
        } else if (mediaType === 'audio') {
            const bitrates = ['', '128k', '192k', '256k', '320k'];
            const labels = { '': 'Auto', '128k': '128 kbps', '192k': '192 kbps',
                             '256k': '256 kbps', '320k': '320 kbps (MP3 max)' };
            const brOpts = bitrates.map(b => {
                const sel = (b === (opts.audio_bitrate || '')) ? ' selected' : '';
                return `<option value="${escape(b)}"${sel}>${escape(labels[b])}</option>`;
            }).join('');
            const normCheck = opts.normalize ? ' checked' : '';
            body += `
                <div class="mb-2">
                    <label class="form-label small fw-bold text-light">
                        <i class="fas fa-headphones"></i> Débit audio
                    </label>
                    <select class="form-select form-select-sm" data-key="audio_bitrate">${brOpts}</select>
                </div>
                <div class="form-check mb-2">
                    <input class="form-check-input" type="checkbox" data-key="normalize"${normCheck}>
                    <label class="form-check-label small">
                        Normalisation loudness (EBU R128)
                    </label>
                </div>
            `;
        } else if (mediaType === 'document') {
            body += `<div class="text-muted small">Conversion de document (Pandoc / PyMuPDF) — choisissez le format de sortie ci-dessus.</div>`;
        } else if (mediaType === 'archive') {
            body += `<div class="text-muted small">Conversion d'archive — choisissez le format de sortie ci-dessus.</div>`;
        } else {
            body += `<div class="alert alert-warning small">Type de média inconnu : ${escape(mediaType)}</div>`;
        }

        body += transformsHTML(mediaType);

        return body;
    }

    /**
     * Read values back from the modal form. Returns { output_format, options }.
     */
    function readModalForm() {
        const body = document.getElementById('jobSettingsBody');
        const outputFormat = body.querySelector('[data-key="output_format"]')?.value || '';
        const options = {};
        body.querySelectorAll('[data-key]').forEach(el => {
            const k = el.dataset.key;
            if (k === 'output_format') return;
            if (el.type === 'checkbox') {
                if (el.checked) options[k] = true;
            } else if (el.type === 'number' || el.type === 'range') {
                if (el.value !== '' && el.value !== null) {
                    const n = el.step && parseFloat(el.step) !== Math.floor(parseFloat(el.step))
                              ? parseFloat(el.value) : parseInt(el.value);
                    if (!isNaN(n)) options[k] = n;
                }
            } else {
                if (el.value !== '' && el.value !== null) options[k] = el.value;
            }
        });
        return { output_format: outputFormat, options };
    }

    let currentModalJobId = null;
    let currentModalMediaType = null;

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
            body.innerHTML = buildModalFormHTML(data.media_type, data.output_format, data.options);

            // Disable Apply/Start if job is RUNNING
            const isRunning = data.status === 'RUNNING';
            const applyBtn = document.getElementById('jobSettingsApplyBtn');
            const startBtn = document.getElementById('jobSettingsStartBtn');
            if (applyBtn) applyBtn.disabled = isRunning;
            if (startBtn) {
                startBtn.disabled = isRunning;
                startBtn.innerHTML = data.status === 'DONE'
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
        const { output_format, options } = readModalForm();
        if (!output_format) {
            alert('Format de sortie requis.');
            return false;
        }
        const fd = new FormData();
        fd.append('output_format', output_format);
        fd.append('options_json', JSON.stringify(options));
        try {
            const resp = await csrfPost(urlFor(APP.urls.update, currentModalJobId), fd);
            const data = await resp.json();
            if (!resp.ok || data.error) {
                alert('Erreur : ' + (data.error || resp.statusText));
                return false;
            }
            // Reflect new format in the queue card immediately
            updateCard(currentModalJobId, {
                status: document.querySelector(`.job-card[data-job-id="${currentModalJobId}"]`)?.dataset.status || 'PENDING',
                progress: 0,
                output_format: data.output_format,
            });
            return true;
        } catch (err) {
            alert('Erreur réseau : ' + err.message);
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
        const { output_format, options } = readModalForm();
        if (!output_format) {
            alert('Format de sortie requis avant de sauver.');
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
        if (!name) { alert('Nom requis'); return; }
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
                alert('Erreur : ' + (data.error || resp.statusText));
                return;
            }
            const modal = bootstrap.Modal.getInstance(document.getElementById('saveProfileModal'));
            if (modal) modal.hide();
            await loadProfiles();
            renderProfileDropdown(currentMediaType);
        } catch (err) {
            alert('Erreur réseau : ' + err.message);
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
        const fmtOptions = Array.from(outputFmtSel.options).map(o => o.value);
        if (fmtOptions.includes(profile.output_format)) {
            outputFmtSel.value = profile.output_format;
        }
        applyOptionsToMainPanel(profile.media_type, profile.options);
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
            alert('Erreur réseau : ' + err.message);
        }
    });

    // ── Reset options ─────────────────────────────────────────────────────────

    const resetBtn = document.getElementById('converterResetOptions');
    if (resetBtn) resetBtn.addEventListener('click', () => {
        const q = document.getElementById('imageQuality');
        if (q) { q.value = 85; document.getElementById('qualityDisplay').textContent = '85'; }
        const rw = document.getElementById('resizeW'); if (rw) rw.value = '';
        const rh = document.getElementById('resizeH'); if (rh) rh.value = '';
        const crf = document.getElementById('videoCRF'); if (crf) crf.value = '';
        const fps = document.getElementById('videoFPS'); if (fps) fps.value = '';
        const br = document.getElementById('audioBitrate'); if (br) br.value = '192k';
        const norm = document.getElementById('audioNormalize'); if (norm) norm.checked = false;
        const rot = document.getElementById('rotation'); if (rot) rot.value = '0';
        const fh = document.getElementById('flipH'); if (fh) fh.checked = false;
        const fv = document.getElementById('flipV'); if (fv) fv.checked = false;
        if (profileSelect) {
            profileSelect.value = '';
            if (profileDeleteBtn) profileDeleteBtn.disabled = true;
        }
    });

    // ── Auto-start polling for RUNNING jobs (on page load) ────────────────────

    document.querySelectorAll('.job-card[data-status="RUNNING"]').forEach(card => {
        startPolling(card.dataset.jobId);
    });

    // ── Filemanager "Envoyer vers Converter" — reload to show new job ─────────
    // (Pattern WAMA standard, cf. enhancer/index.js)

    document.addEventListener('wama:fileimported', function(e) {
        if (e.detail && e.detail.app === 'converter') {
            window.location.reload();
        }
    });

    // ── Init ──────────────────────────────────────────────────────────────────
    setMediaType(null);
    loadProfiles().then(() => renderProfileDropdown(null));

})();
