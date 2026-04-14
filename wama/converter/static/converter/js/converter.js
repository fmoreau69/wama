/**
 * WAMA Converter — Frontend Logic
 *
 * Responsibilities:
 *  - File upload (drag & drop + file input) with media-type detection
 *  - Output format dropdown population
 *  - Options panels (image / video / audio)
 *  - Job queue rendering & polling
 *  - Start / delete / duplicate / clear-all / start-all actions
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
    const imageOpts = document.getElementById('imageOptions');
    const videoOpts = document.getElementById('videoOptions');
    const audioOpts = document.getElementById('audioOptions');

    // Global action buttons
    const startAllBtn = document.getElementById('converterStartAllBtn');
    const clearAllBtn = document.getElementById('converterClearAllBtn');

    // ── State ─────────────────────────────────────────────────────────────────
    let currentMediaType = null;
    const pollingTimers  = {};   // { jobId: intervalId }

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
        const labels = { image: 'Image', video: 'Vidéo', audio: 'Audio' };
        return labels[type] || type;
    }

    // ── UI updates ────────────────────────────────────────────────────────────

    function setMediaType(type) {
        currentMediaType = type;
        // Badge
        if (!type) {
            mediaTypeBadge.innerHTML = '<span class="text-muted fst-italic">— aucun fichier sélectionné —</span>';
        } else {
            const colours = { image: 'success', video: 'primary', audio: 'warning' };
            const icons   = { image: 'image', video: 'film', audio: 'music' };
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
    }

    function buildOptions() {
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
        return opts;
    }

    // ── Upload ────────────────────────────────────────────────────────────────

    async function uploadFile(file) {
        const mediaType = detectMediaType(file.name);
        if (!mediaType) {
            alert(`Format non supporté : ${file.name}`);
            return;
        }

        const outputFmt = outputFmtSel.value;
        if (!outputFmt) {
            alert('Choisissez un format de sortie avant d\'envoyer un fichier.');
            return;
        }

        const opts   = buildOptions();
        const fd     = new FormData();
        fd.append('file', file);
        fd.append('output_format', outputFmt);
        Object.entries(opts).forEach(([k, v]) => fd.append(k, v));

        try {
            const resp = await csrfPost(APP.urls.upload, fd);
            const data = await resp.json();
            if (!resp.ok || data.error) {
                alert('Erreur : ' + (data.error || resp.statusText));
                return;
            }
            // Reload to show new job in queue
            location.reload();
        } catch (err) {
            alert('Erreur réseau : ' + err.message);
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
        const files = Array.from(e.dataTransfer.files);
        if (!files.length) return;
        // Detect type from first file, set UI, then upload all
        const type = detectMediaType(files[0].name);
        if (type) setMediaType(type);
        // Upload sequentially
        files.reduce((p, f) => p.then(() => uploadFile(f)), Promise.resolve());
    });

    fileInput.addEventListener('change', () => {
        const files = Array.from(fileInput.files);
        if (!files.length) return;
        const type = detectMediaType(files[0].name);
        if (type) setMediaType(type);
        files.reduce((p, f) => p.then(() => uploadFile(f)), Promise.resolve());
        fileInput.value = '';
    });

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

        // Status badge
        const badge = card.querySelector('.badge');
        if (badge) {
            const STATUS_LABELS = {
                PENDING: 'En attente', RUNNING: 'En cours', DONE: 'Terminé', ERROR: 'Erreur'
            };
            const STATUS_CLASSES = {
                PENDING: 'bg-secondary', RUNNING: 'bg-warning text-dark',
                DONE: 'bg-success', ERROR: 'bg-danger'
            };
            badge.className = `badge ${STATUS_CLASSES[data.status] || 'bg-secondary'} badge-media`;
            badge.textContent = STATUS_LABELS[data.status] || data.status;
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
            // Show output filename + enable download
            let info = card.querySelector('.job-info-line');
            if (!info) {
                info = document.createElement('div');
                info.className = 'text-success small mt-1 job-info-line';
                card.appendChild(info);
            }
            info.innerHTML = `<i class="fas fa-check-circle"></i> ${data.output_filename || 'Converti'}`;

            // Enable download button
            const dlBtn = card.querySelector('.btn-outline-info');
            if (dlBtn) {
                const dlLink = document.createElement('a');
                dlLink.href = urlFor(APP.urls.download, jobId);
                dlLink.className = dlBtn.className;
                dlLink.title = 'Télécharger';
                dlLink.innerHTML = '<i class="fas fa-download"></i>';
                dlBtn.replaceWith(dlLink);
            }
            // Enable start btn (for restart)
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
    });

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

    // ── Settings modal (placeholder) ──────────────────────────────────────────

    function openSettingsModal(jobId) {
        const card = document.querySelector(`.job-card[data-job-id="${jobId}"]`);
        const filename = card ? card.querySelector('.fw-bold')?.textContent?.trim() : `Job #${jobId}`;
        document.getElementById('jobSettingsFilename').textContent = filename;
        document.getElementById('jobSettingsBody').innerHTML =
            `<p class="text-muted small">ID job : <code>${jobId}</code></p>` +
            '<p class="text-muted small">Paramètres détaillés disponibles en P2.</p>';
        const startBtn = document.getElementById('jobSettingsStartBtn');
        startBtn.onclick = () => {
            const modal = bootstrap.Modal.getInstance(document.getElementById('jobSettingsModal'));
            if (modal) modal.hide();
            startJob(jobId);
        };
        const modal = new bootstrap.Modal(document.getElementById('jobSettingsModal'));
        modal.show();
    }

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
    });

    // ── Auto-start polling for RUNNING jobs (on page load) ────────────────────

    document.querySelectorAll('.job-card[data-status="RUNNING"]').forEach(card => {
        startPolling(card.dataset.jobId);
    });

    // ── Init ──────────────────────────────────────────────────────────────────
    setMediaType(null);

})();
