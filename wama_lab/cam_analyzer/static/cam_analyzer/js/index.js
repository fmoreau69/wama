/**
 * Cam Analyzer - Main JavaScript
 *
 * Session management, camera drag & drop, synchronized playback, profiles,
 * analysis polling, detection canvas overlay, proximity timeline.
 */

document.addEventListener('DOMContentLoaded', function () {
    const config = window.CAM_ANALYZER;
    if (!config) {
        console.error('CAM_ANALYZER config not found');
        return;
    }

    // =========================================================================
    // State
    // =========================================================================

    let currentSessionId = null;
    let cameras = {};          // { position: { id, videoUrl, duration, fps, width, height, ... } }
    let isPlaying = false;
    let maxDuration = 0;

    // Phase 2 state
    let pollingInterval = null;
    let detectionData = {};    // { position: { fps, width, height, frames: [{frame_number, timestamp, detections}] } }
    let proximityByTime = [];  // [{time, proximity}] for timeline

    // Phase 3 state
    let proximityChart = null;  // Chart.js instance
    let classChart = null;      // Chart.js instance

    // DOM references
    const sessionSelect = document.getElementById('sessionSelect');
    const newSessionBtn = document.getElementById('newSessionBtn');
    const deleteSessionBtn = document.getElementById('deleteSessionBtn');
    const startAnalysisBtn = document.getElementById('startAnalysisBtn');
    const cancelAnalysisBtn = document.getElementById('cancelAnalysisBtn');
    const profileSelect = document.getElementById('profileSelect');
    const editProfileBtn = document.getElementById('editProfileBtn');
    const playbackControls = document.getElementById('playbackControls');
    const syncPlayPauseBtn = document.getElementById('syncPlayPauseBtn');
    const playPauseIcon = document.getElementById('playPauseIcon');
    const syncStopBtn = document.getElementById('syncStopBtn');
    const syncSeekBar = document.getElementById('syncSeekBar');
    const syncTimeDisplay = document.getElementById('syncTimeDisplay');
    const playbackSpeed = document.getElementById('playbackSpeed');
    const sessionsContainer = document.getElementById('sessionsContainer');
    const refreshSessionsBtn = document.getElementById('refreshSessionsBtn');

    // Progress & results
    const analysisProgress = document.getElementById('analysisProgress');
    const progressLabel = document.getElementById('progressLabel');
    const progressPercent = document.getElementById('progressPercent');
    const progressBar = document.getElementById('progressBar');
    const resultsPanel = document.getElementById('resultsPanel');
    const resultsContent = document.getElementById('resultsContent');
    const closeResultsBtn = document.getElementById('closeResultsBtn');

    // Timeline
    const proximityTimeline = document.getElementById('proximityTimeline');
    const timelineBar = document.getElementById('timelineBar');
    const timelineCursor = document.getElementById('timelineCursor');

    // Modals
    const newSessionModal = new bootstrap.Modal(document.getElementById('newSessionModal'));
    const profileModal = new bootstrap.Modal(document.getElementById('profileModal'));

    const positions = ['front', 'rear', 'left', 'right'];

    // Detection class colors
    const classColors = {
        person: '#00ff88',
        bicycle: '#ffff00',
        car: '#4488ff',
        motorcycle: '#ff8800',
        bus: '#ff44ff',
        truck: '#00cccc',
        'traffic light': '#ff4444',
        'stop sign': '#ff0000',
        cat: '#88ff88',
        dog: '#8888ff',
    };
    const defaultColor = '#ffffff';

    // =========================================================================
    // Session Management
    // =========================================================================

    async function loadSessions() {
        try {
            const resp = await fetch(config.urls.listSessions);
            const data = await resp.json();

            // Update dropdown
            sessionSelect.innerHTML = '<option value="">-- Sélectionner une session --</option>';
            if (data.sessions) {
                data.sessions.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.id;
                    opt.textContent = `${s.name} (${s.camera_count} cam)`;
                    sessionSelect.appendChild(opt);
                });
            }

            // Render sessions table
            renderSessionsTable(data.sessions || []);

            // Restore selection
            if (currentSessionId) {
                sessionSelect.value = currentSessionId;
            }
        } catch (e) {
            console.error('Error loading sessions:', e);
            sessionsContainer.innerHTML = `
                <div class="text-center text-danger py-4">
                    <i class="fas fa-exclamation-triangle fa-2x mb-3"></i>
                    <p>Erreur lors du chargement</p>
                </div>`;
        }
    }

    function renderSessionsTable(sessions) {
        if (!sessions.length) {
            sessionsContainer.innerHTML = `
                <div class="text-center text-secondary py-4">
                    <i class="fas fa-folder-open fa-3x mb-3 opacity-50"></i>
                    <p>Aucune session</p>
                    <p class="small">Créez une nouvelle session pour commencer.</p>
                </div>`;
            return;
        }

        sessionsContainer.innerHTML = `
            <div class="table-responsive">
                <table class="table table-dark table-hover mb-0">
                    <thead><tr>
                        <th>Nom</th>
                        <th>Caméras</th>
                        <th>Statut</th>
                        <th>Date</th>
                        <th class="text-end">Actions</th>
                    </tr></thead>
                    <tbody>
                        ${sessions.map(s => `
                            <tr>
                                <td>${escapeHtml(s.name)}</td>
                                <td><span class="badge bg-secondary">${s.camera_count}</span></td>
                                <td>${getStatusBadge(s.status)}</td>
                                <td>${formatDate(s.created_at)}</td>
                                <td class="text-end">
                                    <div class="btn-group btn-group-sm">
                                        <button class="btn btn-outline-info load-session-btn" data-id="${s.id}" title="Charger">
                                            <i class="fas fa-folder-open"></i>
                                        </button>
                                        <button class="btn btn-outline-danger delete-session-btn" data-id="${s.id}" title="Supprimer">
                                            <i class="fas fa-trash"></i>
                                        </button>
                                    </div>
                                </td>
                            </tr>
                        `).join('')}
                    </tbody>
                </table>
            </div>`;

        // Attach event listeners
        sessionsContainer.querySelectorAll('.load-session-btn').forEach(btn => {
            btn.addEventListener('click', () => loadSession(btn.dataset.id));
        });
        sessionsContainer.querySelectorAll('.delete-session-btn').forEach(btn => {
            btn.addEventListener('click', () => deleteSession(btn.dataset.id));
        });
    }

    async function createSession() {
        const nameInput = document.getElementById('newSessionName');
        const name = nameInput.value.trim();

        try {
            const form = new FormData();
            form.append('name', name);

            const resp = await fetch(config.urls.createSession, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
                body: form,
            });
            const data = await resp.json();

            if (data.success) {
                currentSessionId = data.session_id;
                newSessionModal.hide();
                nameInput.value = '';
                clearCameraGrid();
                await loadSessions();
                sessionSelect.value = currentSessionId;
                deleteSessionBtn.disabled = false;
                startAnalysisBtn.disabled = false;
            } else {
                alert('Erreur: ' + (data.error || 'Inconnue'));
            }
        } catch (e) {
            console.error('Error creating session:', e);
            alert('Erreur lors de la création');
        }
    }

    async function loadSession(sessionId) {
        try {
            const resp = await fetch(`${config.urls.getSession}${sessionId}/`);
            const data = await resp.json();

            currentSessionId = sessionId;
            sessionSelect.value = sessionId;
            deleteSessionBtn.disabled = false;
            startAnalysisBtn.disabled = false;
            updateRtmapsPanel();

            // Clear and restore cameras
            clearCameraGrid();
            cameras = {};

            if (data.cameras) {
                data.cameras.forEach(cam => {
                    cameras[cam.position] = cam;
                    showCameraVideo(cam.position, cam.video_url, cam);
                });
            }

            // Set profile + update report type badge
            if (data.profile_id) {
                profileSelect.value = data.profile_id;
                const selectedOpt = profileSelect.options[profileSelect.selectedIndex];
                setReportTypeBadge(selectedOpt ? selectedOpt.dataset.reportType : null);
            } else {
                setReportTypeBadge(null);
            }

            updatePlaybackControls();

            // Check session status and react
            if (data.status === 'processing' || data.status === 'pending') {
                setAnalysisUI(true);
                startStatusPolling(sessionId);
            } else if (data.status === 'completed' && data.results_summary) {
                showResults(data.results_summary);
                loadAllDetections(sessionId);
            } else if (data.status === 'failed' && data.error_message) {
                showResults(null);
                alert('Dernière analyse échouée: ' + data.error_message);
            }
        } catch (e) {
            console.error('Error loading session:', e);
        }
    }

    async function deleteSession(sessionId) {
        if (!confirm('Supprimer cette session et ses vidéos ?')) return;

        try {
            const resp = await fetch(`${config.urls.deleteSession}${sessionId}/delete/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });

            if (resp.ok) {
                if (currentSessionId === sessionId) {
                    stopStatusPolling();
                    currentSessionId = null;
                    clearCameraGrid();
                    deleteSessionBtn.disabled = true;
                    startAnalysisBtn.disabled = true;
                    playbackControls.style.display = 'none';
                    hideProgress();
                    hideResults();
                }
                await loadSessions();
            }
        } catch (e) {
            console.error('Error deleting session:', e);
        }
    }

    // =========================================================================
    // Camera Drag & Drop
    // =========================================================================

    function initDropZones() {
        positions.forEach(pos => {
            const zone = document.getElementById(`dropzone-${pos}`);
            if (!zone) return;

            zone.addEventListener('dragover', e => {
                e.preventDefault();
                e.stopPropagation();
                zone.classList.add('drag-over');
            });

            zone.addEventListener('dragleave', e => {
                e.preventDefault();
                zone.classList.remove('drag-over');
            });

            zone.addEventListener('drop', e => {
                e.preventDefault();
                e.stopPropagation();
                zone.classList.remove('drag-over');

                const files = e.dataTransfer.files;
                if (files.length > 0 && currentSessionId) {
                    const file = files[0];
                    if (file.type.startsWith('video/')) {
                        uploadCamera(pos, file);
                    } else {
                        alert('Veuillez déposer un fichier vidéo');
                    }
                } else if (!currentSessionId) {
                    alert('Créez ou sélectionnez une session d\'abord');
                }
            });

            // Also allow click to select file
            zone.addEventListener('click', e => {
                if (!currentSessionId) {
                    alert('Créez ou sélectionnez une session d\'abord');
                    return;
                }
                // Don't trigger if clicking on video or buttons
                if (e.target.closest('.camera-video') || e.target.closest('.remove-camera-btn')) return;

                const input = document.createElement('input');
                input.type = 'file';
                input.accept = 'video/*';
                input.onchange = () => {
                    if (input.files.length > 0) {
                        uploadCamera(pos, input.files[0]);
                    }
                };
                input.click();
            });
        });

        // Remove camera buttons
        document.querySelectorAll('.remove-camera-btn').forEach(btn => {
            btn.addEventListener('click', e => {
                e.stopPropagation();
                const pos = btn.dataset.position;
                if (cameras[pos]) {
                    removeCamera(cameras[pos].id, pos);
                }
            });
        });
    }

    async function uploadCamera(position, file) {
        if (!currentSessionId) return;

        const zone = document.getElementById(`dropzone-${position}`);
        const placeholder = zone.querySelector('.drop-placeholder');
        if (placeholder) {
            placeholder.innerHTML = `
                <i class="fas fa-spinner fa-spin fa-2x mb-2"></i>
                <div class="small">Upload en cours...</div>`;
        }

        try {
            const form = new FormData();
            form.append('position', position);
            form.append('video_file', file);

            const resp = await fetch(`${config.urls.uploadCamera}${currentSessionId}/cameras/upload/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
                body: form,
            });
            const data = await resp.json();

            if (data.success && data.camera) {
                cameras[position] = data.camera;
                showCameraVideo(position, data.camera.video_url, data.camera);
                updatePlaybackControls();
                loadSessions();  // refresh camera count
            } else {
                alert('Erreur: ' + (data.error || 'Upload échoué'));
                resetDropZone(position);
            }
        } catch (e) {
            console.error('Error uploading camera:', e);
            alert('Erreur lors de l\'upload');
            resetDropZone(position);
        }
    }

    async function removeCamera(cameraId, position) {
        try {
            const resp = await fetch(`${config.urls.deleteCamera}${cameraId}/delete/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });

            if (resp.ok) {
                delete cameras[position];
                resetDropZone(position);
                updatePlaybackControls();
                loadSessions();
            }
        } catch (e) {
            console.error('Error removing camera:', e);
        }
    }

    function showCameraVideo(position, videoUrl, camData) {
        const zone = document.getElementById(`dropzone-${position}`);
        const video = document.getElementById(`video-${position}`);
        const info = document.getElementById(`info-${position}`);
        const placeholder = zone.querySelector('.drop-placeholder');

        if (placeholder) placeholder.style.display = 'none';
        video.src = videoUrl;
        video.style.display = 'block';
        video.load();
        zone.classList.add('has-video');
        if (info) info.style.display = 'flex';
    }

    function resetDropZone(position) {
        const zone = document.getElementById(`dropzone-${position}`);
        const video = document.getElementById(`video-${position}`);
        const info = document.getElementById(`info-${position}`);
        const placeholder = zone.querySelector('.drop-placeholder');

        video.src = '';
        video.style.display = 'none';
        zone.classList.remove('has-video');
        if (info) info.style.display = 'none';

        // Clear canvas
        clearCanvas(position);

        if (placeholder) {
            placeholder.style.display = '';
            placeholder.innerHTML = `
                <i class="fas fa-video fa-2x mb-2"></i>
                <div class="small">${getPositionLabel(position)}</div>
                <div class="text-muted small">Glisser une vidéo ici</div>`;
        }
    }

    function clearCameraGrid() {
        positions.forEach(pos => resetDropZone(pos));
        cameras = {};
        detectionData = {};
        syncStop();
        playbackControls.style.display = 'none';
    }

    // =========================================================================
    // Synchronized Playback
    // =========================================================================

    function updatePlaybackControls() {
        const activePositions = Object.keys(cameras);
        if (activePositions.length === 0) {
            playbackControls.style.display = 'none';
            return;
        }

        playbackControls.style.display = 'block';

        // Calculate max duration
        maxDuration = 0;
        activePositions.forEach(pos => {
            const cam = cameras[pos];
            if (cam.duration && cam.duration > maxDuration) {
                maxDuration = cam.duration;
            }
        });

        syncSeekBar.max = maxDuration || 100;
        updateTimeDisplay(0);
    }

    // ── rAF sync loop ────────────────────────────────────────────────────────
    // Drives seekbar, overlays and drift correction at display framerate (~60 Hz)
    // instead of the coarse timeupdate event (~4 Hz).
    const SYNC_THRESHOLD = 0.3;   // seconds — re-sync if drift exceeds this
    let rafHandle = null;
    let isSeeking = false;         // true while the user drags the seekbar

    function getRefPosition() {
        for (const pos of positions) {
            if (cameras[pos]) return pos;
        }
        return null;
    }

    function rafLoop() {
        const refPos = getRefPosition();
        if (!refPos || !isPlaying) { rafHandle = null; return; }

        const refVideo = document.getElementById(`video-${refPos}`);
        if (!refVideo) { rafHandle = null; return; }

        const refOffset = (cameras[refPos] && cameras[refPos].time_offset) || 0;
        const refTime   = refVideo.currentTime - refOffset;

        // Update seekbar + time display (only when user is not dragging)
        if (!isSeeking) {
            syncSeekBar.value = refTime;
            updateTimeDisplay(refTime);
            updateTimelineCursor(refTime);
        }

        // Per-camera: drift correction + overlay
        const speed = parseFloat(playbackSpeed.value) || 1;
        positions.forEach(pos => {
            const video  = document.getElementById(`video-${pos}`);
            const camCfg = cameras[pos];
            if (!video || !camCfg || !video.src) return;

            // Drift correction for non-reference cameras
            if (pos !== refPos && !video.paused) {
                const offset  = camCfg.time_offset || 0;
                const camTime = video.currentTime - offset;
                const drift   = camTime - refTime;
                if (Math.abs(drift) > SYNC_THRESHOLD) {
                    video.currentTime = Math.max(0, refTime + offset);
                }
            }

            // Overlay: each camera uses its own currentTime
            const data = detectionData[pos];
            if (data && data.frames.length) {
                const offset  = camCfg.time_offset || 0;
                const camTime = video.currentTime - offset;
                const frame   = findClosestFrame(data.frames, camTime);
                if (frame && frame.detections && frame.detections.length > 0) {
                    drawDetections(pos, frame.detections, data.width, data.height);
                } else {
                    clearCanvas(pos);
                }
            }
        });

        rafHandle = requestAnimationFrame(rafLoop);
    }

    function startRafLoop() {
        if (!rafHandle) rafHandle = requestAnimationFrame(rafLoop);
    }

    function stopRafLoop() {
        if (rafHandle) { cancelAnimationFrame(rafHandle); rafHandle = null; }
    }
    // ── End rAF sync loop ────────────────────────────────────────────────────

    function syncPlay() {
        isPlaying = true;
        playPauseIcon.className = 'fas fa-pause';

        const speed = parseFloat(playbackSpeed.value);
        const currentTime = parseFloat(syncSeekBar.value) || 0;
        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (video && video.src && cameras[pos]) {
                const offset = cameras[pos].time_offset || 0;
                video.currentTime = Math.max(0, currentTime + offset);
                video.playbackRate = speed;
                video.play().catch(() => {});
            }
        });

        startRafLoop();
    }

    function syncPause() {
        isPlaying = false;
        playPauseIcon.className = 'fas fa-play';
        stopRafLoop();

        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (video && video.src) video.pause();
        });
    }

    function syncStop() {
        syncPause();
        syncSeek(0);
    }

    function syncSeek(time) {
        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (video && video.src && cameras[pos]) {
                const offset = cameras[pos].time_offset || 0;
                video.currentTime = Math.max(0, time + offset);
            }
        });
        syncSeekBar.value = time;
        updateTimeDisplay(time);
        updateTimelineCursor(time);

        // Update overlays immediately at new position (works paused or playing)
        updateDetectionOverlay(time);
    }

    function updateTimeDisplay(currentTime) {
        syncTimeDisplay.textContent = `${formatTime(currentTime)} / ${formatTime(maxDuration)}`;
    }

    // setupTimeSync is kept for backward-compat but no longer attaches timeupdate
    function setupTimeSync() { /* overlays are driven by rafLoop */ }

    // Event listeners
    syncPlayPauseBtn.addEventListener('click', () => {
        if (isPlaying) syncPause();
        else syncPlay();
    });

    syncStopBtn.addEventListener('click', syncStop);

    // While dragging: seek all videos + update overlay without restarting play
    syncSeekBar.addEventListener('mousedown', () => { isSeeking = true; });
    syncSeekBar.addEventListener('touchstart', () => { isSeeking = true; }, { passive: true });

    syncSeekBar.addEventListener('input', () => {
        syncSeek(parseFloat(syncSeekBar.value));
    });

    syncSeekBar.addEventListener('mouseup', () => { isSeeking = false; });
    syncSeekBar.addEventListener('touchend', () => { isSeeking = false; });

    playbackSpeed.addEventListener('change', () => {
        const speed = parseFloat(playbackSpeed.value);
        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (video) video.playbackRate = speed;
        });
    });

    // =========================================================================
    // Analysis: Start, Poll, Cancel
    // =========================================================================

    function setAnalysisUI(running) {
        if (running) {
            startAnalysisBtn.style.display = 'none';
            cancelAnalysisBtn.style.display = '';
            analysisProgress.style.display = '';
            progressBar.style.width = '0%';
            progressPercent.textContent = '0%';
            progressLabel.textContent = 'Analyse en cours...';
        } else {
            startAnalysisBtn.style.display = '';
            cancelAnalysisBtn.style.display = 'none';
            analysisProgress.style.display = 'none';
        }
    }

    function hideProgress() {
        analysisProgress.style.display = 'none';
        startAnalysisBtn.style.display = '';
        cancelAnalysisBtn.style.display = 'none';
    }

    async function startAnalysis() {
        if (!currentSessionId) return;
        try {
            const resp = await fetch(`${config.urls.startAnalysis}${currentSessionId}/start/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });
            const data = await resp.json();
            if (data.success) {
                setAnalysisUI(true);
                hideResults();
                clearAllCanvases();
                startStatusPolling(currentSessionId);
            } else {
                alert(data.error || 'Erreur');
            }
        } catch (e) {
            console.error('Error starting analysis:', e);
        }
    }

    async function cancelAnalysis() {
        if (!currentSessionId) return;
        try {
            const resp = await fetch(`${config.urls.cancelAnalysis}${currentSessionId}/cancel/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });
            const data = await resp.json();
            if (data.success) {
                if (data.immediate) {
                    // PENDING session: cancelled immediately by server
                    stopStatusPolling();
                    hideProgress();
                    loadSessions();
                } else {
                    // PROCESSING session: waiting for task to check cancellation flag
                    progressLabel.textContent = 'Annulation en cours...';
                }
            }
        } catch (e) {
            console.error('Error cancelling analysis:', e);
        }
    }

    function startStatusPolling(sessionId) {
        stopStatusPolling();
        pollingInterval = setInterval(() => pollSessionStatus(sessionId), 2000);
    }

    function stopStatusPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }
    }

    async function pollSessionStatus(sessionId) {
        try {
            const resp = await fetch(`${config.urls.sessionStatus}${sessionId}/status/`);
            const data = await resp.json();

            const pct = Math.round(data.progress || 0);
            progressBar.style.width = `${pct}%`;
            progressPercent.textContent = `${pct}%`;
            if (data.status_message) {
                progressLabel.textContent = data.status_message;
            }

            if (data.status === 'completed') {
                stopStatusPolling();
                hideProgress();
                showResults(data.results_summary);
                loadAllDetections(sessionId);
                loadSessions(); // refresh table
            } else if (data.status === 'failed') {
                stopStatusPolling();
                hideProgress();
                alert('Analyse échouée: ' + (data.error_message || 'Erreur inconnue'));
                loadSessions();
            }
        } catch (e) {
            console.error('Error polling status:', e);
        }
    }

    // =========================================================================
    // Results Display
    // =========================================================================

    function showResults(summary) {
        if (!summary || !summary.detections_total) {
            resultsPanel.style.display = 'none';
            return;
        }

        const posLabels = { front: 'Avant', rear: 'Arrière', left: 'Gauche', right: 'Droite' };

        let classHtml = '';
        if (summary.by_class) {
            const entries = Object.entries(summary.by_class).sort((a, b) => b[1] - a[1]);
            classHtml = entries.map(([cls, count]) => {
                const color = classColors[cls] || defaultColor;
                return `<span class="badge me-1 mb-1" style="background:${color};color:#000">${cls}: ${count}</span>`;
            }).join('');
        }

        let cameraHtml = '';
        if (summary.by_camera) {
            cameraHtml = Object.entries(summary.by_camera).map(([pos, info]) => `
                <div class="col-md-3 col-6 mb-2">
                    <div class="p-2 rounded" style="background:rgba(255,255,255,0.05)">
                        <div class="fw-bold small">${posLabels[pos] || pos}</div>
                        <div class="small text-secondary">${info.detections} détections</div>
                        <div class="small text-secondary">Proximité max: ${(info.max_proximity * 100).toFixed(0)}%</div>
                    </div>
                </div>
            `).join('');
        }

        let videoHtml = '';
        if (summary.annotated_videos) {
            videoHtml = Object.entries(summary.annotated_videos).map(([pos, path]) =>
                `<a href="/media/${path}" target="_blank" class="btn btn-sm btn-outline-warning me-1 mb-1">
                    <i class="fas fa-film me-1"></i>${posLabels[pos] || pos}
                </a>`
            ).join('');
        }

        const timeStr = summary.processing_time_seconds
            ? `${Math.round(summary.processing_time_seconds)}s`
            : '';

        const segmentsStr = summary.segments_detected
            ? `${summary.segments_detected} segment${summary.segments_detected > 1 ? 's' : ''}`
            : '';

        resultsContent.innerHTML = `
            <div class="row mb-2">
                <div class="col-md-3">
                    <div class="text-warning fw-bold">${summary.detections_total}</div>
                    <div class="small text-secondary">détections totales</div>
                </div>
                <div class="col-md-3">
                    <div class="text-warning fw-bold">${summary.cameras_processed}</div>
                    <div class="small text-secondary">caméras traitées</div>
                </div>
                <div class="col-md-3">
                    <div class="text-warning fw-bold">${(summary.max_proximity * 100).toFixed(0)}%</div>
                    <div class="small text-secondary">proximité max</div>
                </div>
                <div class="col-md-3">
                    <div class="text-warning fw-bold">${segmentsStr || '—'}</div>
                    <div class="small text-secondary">segments temporels</div>
                </div>
            </div>
            ${classHtml ? `<div class="mb-2"><strong class="small text-light">Classes:</strong><br>${classHtml}</div>` : ''}
            ${cameraHtml ? `<div class="row">${cameraHtml}</div>` : ''}
            ${videoHtml ? `<div class="mt-2"><strong class="small text-light">Vidéos annotées:</strong><br>${videoHtml}</div>` : ''}
            ${timeStr ? `<div class="mt-2 small text-secondary">Temps de traitement: ${timeStr}</div>` : ''}
        `;
        resultsPanel.style.display = '';

        // Load analytics (Phase 3)
        if (currentSessionId) {
            loadAnalytics(currentSessionId);
        }
    }

    function hideResults() {
        resultsPanel.style.display = 'none';
        // Destroy Chart.js instances
        if (proximityChart) { proximityChart.destroy(); proximityChart = null; }
        if (classChart) { classChart.destroy(); classChart = null; }
        const analyticsSection = document.getElementById('analyticsSection');
        if (analyticsSection) analyticsSection.style.display = 'none';
    }

    // =========================================================================
    // Detection Canvas Overlay
    // =========================================================================

    function clearCanvas(position) {
        const canvas = document.getElementById(`canvas-${position}`);
        if (!canvas) return;
        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);
    }

    function clearAllCanvases() {
        positions.forEach(pos => clearCanvas(pos));
        detectionData = {};
    }

    async function loadAllDetections(sessionId) {
        detectionData = {};
        proximityByTime = [];

        for (const pos of positions) {
            const cam = cameras[pos];
            if (!cam) continue;

            try {
                const resp = await fetch(
                    `${config.urls.getDetections}${sessionId}/cameras/${cam.id}/detections/?start=0&end=999999`
                );
                const data = await resp.json();
                detectionData[pos] = {
                    fps: data.fps || cam.fps || 30,
                    width: data.width || cam.width || 1920,
                    height: data.height || cam.height || 1080,
                    frames: data.frames || [],
                };
            } catch (e) {
                console.error(`Error loading detections for ${pos}:`, e);
            }
        }

        // Build proximity timeline from all cameras
        buildProximityTimeline();

        // Show timeline if we have data
        if (proximityByTime.length > 0) {
            renderProximityTimeline();
            proximityTimeline.style.display = '';
        }

        // Draw detections at current time
        const currentTime = parseFloat(syncSeekBar.value) || 0;
        updateDetectionOverlay(currentTime);
    }

    function updateDetectionOverlay(currentTime) {
        // Used for immediate overlay update on seek (paused state).
        // During playback, the rAF loop handles per-camera overlay with individual currentTime.
        positions.forEach(pos => {
            const data   = detectionData[pos];
            const camCfg = cameras[pos];
            if (!data || !data.frames.length) { clearCanvas(pos); return; }

            // When paused, adjust for the camera's own time offset
            const offset     = (camCfg && camCfg.time_offset) || 0;
            const camTime    = currentTime + offset - offset; // = currentTime (offset applied in syncSeek)
            const targetFrame = findClosestFrame(data.frames, currentTime);
            if (!targetFrame || !targetFrame.detections || targetFrame.detections.length === 0) {
                clearCanvas(pos);
                return;
            }

            drawDetections(pos, targetFrame.detections, data.width, data.height);
        });
    }

    function findClosestFrame(frames, time) {
        if (!frames.length) return null;

        // Binary search for closest timestamp
        let low = 0, high = frames.length - 1;
        while (low < high) {
            const mid = Math.floor((low + high) / 2);
            if (frames[mid].timestamp < time) low = mid + 1;
            else high = mid;
        }

        // Check neighbors for closest
        if (low > 0 && Math.abs(frames[low - 1].timestamp - time) < Math.abs(frames[low].timestamp - time)) {
            low--;
        }

        return frames[low];
    }

    function drawDetections(position, detections, srcWidth, srcHeight) {
        const canvas = document.getElementById(`canvas-${position}`);
        const video = document.getElementById(`video-${position}`);
        if (!canvas || !video) return;

        // Match canvas to displayed video element size — only resize if changed
        // (resizing resets the canvas context and forces a DOM re-layout)
        const rect = video.getBoundingClientRect();
        const needResize = Math.round(rect.width)  !== canvas.width ||
                           Math.round(rect.height) !== canvas.height;
        if (needResize) {
            canvas.width  = Math.round(rect.width);
            canvas.height = Math.round(rect.height);
        }

        const ctx = canvas.getContext('2d');
        ctx.clearRect(0, 0, canvas.width, canvas.height);

        // Compute actual video display area (object-fit:contain creates letterbox)
        const containerAR = canvas.width / canvas.height;
        const videoAR = srcWidth / srcHeight;
        let drawW, drawH, offsetX, offsetY;

        if (videoAR > containerAR) {
            // Video wider than container → horizontal fit, vertical letterbox
            drawW = canvas.width;
            drawH = canvas.width / videoAR;
            offsetX = 0;
            offsetY = (canvas.height - drawH) / 2;
        } else {
            // Video taller than container → vertical fit, horizontal letterbox
            drawH = canvas.height;
            drawW = canvas.height * videoAR;
            offsetX = (canvas.width - drawW) / 2;
            offsetY = 0;
        }

        const scaleX = drawW / srcWidth;
        const scaleY = drawH / srcHeight;

        detections.forEach(det => {
            const [x1, y1, x2, y2] = det.bbox;
            const sx = x1 * scaleX + offsetX;
            const sy = y1 * scaleY + offsetY;
            const sw = (x2 - x1) * scaleX;
            const sh = (y2 - y1) * scaleY;

            const color = classColors[det.class_name] || defaultColor;

            // Draw bbox
            ctx.strokeStyle = color;
            ctx.lineWidth = 2;
            ctx.strokeRect(sx, sy, sw, sh);

            // Draw label background
            const label = `${det.class_name} ${(det.confidence * 100).toFixed(0)}%${det.track_id != null ? ' #' + det.track_id : ''}`;
            ctx.font = '11px sans-serif';
            const textWidth = ctx.measureText(label).width;
            ctx.fillStyle = color;
            ctx.fillRect(sx, sy - 16, textWidth + 6, 16);

            // Draw label text
            ctx.fillStyle = '#000';
            ctx.fillText(label, sx + 3, sy - 4);
        });
    }

    // =========================================================================
    // Proximity Timeline
    // =========================================================================

    function buildProximityTimeline() {
        proximityByTime = [];
        if (maxDuration <= 0) return;

        // Build proximity values in 0.5s bins
        const binSize = 0.5;
        const numBins = Math.ceil(maxDuration / binSize);

        for (let i = 0; i < numBins; i++) {
            proximityByTime.push({ time: i * binSize, proximity: 0 });
        }

        // Fill from all cameras
        positions.forEach(pos => {
            const data = detectionData[pos];
            if (!data || !data.frames.length) return;

            data.frames.forEach(frame => {
                const binIdx = Math.min(numBins - 1, Math.floor(frame.timestamp / binSize));
                if (!frame.detections) return;

                frame.detections.forEach(det => {
                    if (det.proximity > proximityByTime[binIdx].proximity) {
                        proximityByTime[binIdx].proximity = det.proximity;
                    }
                });
            });
        });
    }

    function renderProximityTimeline() {
        if (!proximityByTime.length) return;

        // Build gradient from proximity values
        const stops = proximityByTime.map((bin, i) => {
            const pct = (i / proximityByTime.length) * 100;
            const color = getProximityColor(bin.proximity);
            return `${color} ${pct}%`;
        });

        timelineBar.style.background = `linear-gradient(to right, ${stops.join(', ')})`;
        timelineBar.style.opacity = '1';
    }

    function getProximityColor(proximity) {
        if (proximity < 0.15) return '#198754';     // green - safe
        if (proximity < 0.30) return '#20c997';     // teal
        if (proximity < 0.45) return '#ffc107';     // yellow - caution
        if (proximity < 0.60) return '#fd7e14';     // orange - warning
        return '#dc3545';                            // red - critical
    }

    function updateTimelineCursor(currentTime) {
        if (!proximityTimeline || proximityTimeline.style.display === 'none') return;
        if (maxDuration <= 0) return;

        const pct = Math.min(100, (currentTime / maxDuration) * 100);
        timelineCursor.style.left = `${pct}%`;
    }

    // =========================================================================
    // Export (Phase 3)
    // =========================================================================

    function exportDetectionsCsv() {
        if (!currentSessionId) return;
        window.location.href = `${config.urls.exportDetections}${currentSessionId}/export/detections/`;
    }

    function exportSessionJson() {
        if (!currentSessionId) return;
        window.location.href = `${config.urls.exportJson}${currentSessionId}/export/json/`;
    }

    function exportSegmentsCsv() {
        if (!currentSessionId) return;
        window.location.href = `${config.urls.exportSegments}${currentSessionId}/export/segments/`;
    }

    function initExportButtons() {
        const csvBtn = document.getElementById('exportCsvBtn');
        const jsonBtn = document.getElementById('exportJsonBtn');
        const segBtn = document.getElementById('exportSegmentsBtn');
        if (csvBtn) csvBtn.addEventListener('click', exportDetectionsCsv);
        if (jsonBtn) jsonBtn.addEventListener('click', exportSessionJson);
        if (segBtn) segBtn.addEventListener('click', exportSegmentsCsv);
    }

    // =========================================================================
    // Analytics & Charts (Phase 3)
    // =========================================================================

    const cameraColors = {
        front: '#4488ff',
        rear: '#ff4444',
        left: '#00cc88',
        right: '#ffaa00',
    };

    async function loadAnalytics(sessionId) {
        try {
            const resp = await fetch(`${config.urls.getAnalytics}${sessionId}/analytics/`);
            const data = await resp.json();

            if (data.proximity_timeline && data.proximity_timeline.timestamps && data.proximity_timeline.timestamps.length > 0) {
                renderProximityChart(data.proximity_timeline);
            }

            if (data.class_distribution && Object.keys(data.class_distribution).length > 0) {
                renderClassChart(data.class_distribution);
            }

            loadSegments(sessionId);

            const analyticsSection = document.getElementById('analyticsSection');
            if (analyticsSection) analyticsSection.style.display = '';
        } catch (e) {
            console.error('Error loading analytics:', e);
        }
    }

    function renderProximityChart(timelineData) {
        if (proximityChart) { proximityChart.destroy(); proximityChart = null; }

        const canvas = document.getElementById('proximityChart');
        if (!canvas) return;

        const datasets = [];
        for (const [pos, values] of Object.entries(timelineData.series || {})) {
            datasets.push({
                label: getPositionLabel(pos),
                data: values,
                borderColor: cameraColors[pos] || '#888',
                backgroundColor: (cameraColors[pos] || '#888') + '20',
                borderWidth: 1.5,
                pointRadius: 0,
                fill: true,
                tension: 0.3,
            });
        }

        proximityChart = new Chart(canvas, {
            type: 'line',
            data: {
                labels: timelineData.timestamps.map(t => formatTime(t)),
                datasets: datasets,
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: { mode: 'index', intersect: false },
                plugins: {
                    title: {
                        display: true,
                        text: 'Proximité temporelle',
                        color: '#ccc',
                        font: { size: 13 },
                    },
                    legend: {
                        labels: { color: '#aaa', boxWidth: 12, font: { size: 11 } },
                    },
                },
                scales: {
                    x: {
                        ticks: {
                            color: '#888',
                            maxTicksLimit: 20,
                            font: { size: 10 },
                        },
                        grid: { color: '#333' },
                    },
                    y: {
                        min: 0,
                        max: 1,
                        ticks: {
                            color: '#888',
                            font: { size: 10 },
                            callback: v => `${(v * 100).toFixed(0)}%`,
                        },
                        grid: { color: '#333' },
                        title: {
                            display: true,
                            text: 'Proximité',
                            color: '#aaa',
                            font: { size: 11 },
                        },
                    },
                },
                onClick: (evt, elements) => {
                    if (elements.length > 0) {
                        const idx = elements[0].index;
                        const time = timelineData.timestamps[idx];
                        if (time != null) syncSeek(time);
                    }
                },
            },
        });
    }

    function renderClassChart(classData) {
        if (classChart) { classChart.destroy(); classChart = null; }

        const canvas = document.getElementById('classChart');
        if (!canvas) return;

        const labels = Object.keys(classData);
        const values = Object.values(classData);
        const colors = labels.map(cls => classColors[cls] || defaultColor);

        classChart = new Chart(canvas, {
            type: 'doughnut',
            data: {
                labels: labels,
                datasets: [{
                    data: values,
                    backgroundColor: colors.map(c => c + 'cc'),
                    borderColor: colors,
                    borderWidth: 1,
                }],
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    title: {
                        display: true,
                        text: 'Répartition par classe',
                        color: '#ccc',
                        font: { size: 13 },
                    },
                    legend: {
                        position: 'bottom',
                        labels: {
                            color: '#aaa',
                            boxWidth: 10,
                            font: { size: 10 },
                            padding: 8,
                        },
                    },
                },
            },
        });
    }

    async function loadSegments(sessionId) {
        const segmentsList = document.getElementById('segmentsList');
        if (!segmentsList) return;

        try {
            const resp = await fetch(`${config.urls.getSegments}${sessionId}/segments/`);
            const data = await resp.json();
            const segments = data.segments || [];

            if (segments.length === 0) {
                segmentsList.innerHTML = '<div class="text-secondary small">Aucun segment détecté</div>';
                return;
            }

            segmentsList.innerHTML = segments.map(seg => {
                const meta = seg.metadata || {};
                let details = '';
                if (seg.type === 'close_following') {
                    details = `Proximité max: ${((meta.max_proximity || 0) * 100).toFixed(0)}%`;
                    if (meta.dominant_class) details += ` | Classe: ${meta.dominant_class}`;
                } else if (seg.type === 'overtaking') {
                    details = `Direction: ${meta.direction === 'left_to_right' ? '→' : '←'}`;
                    if (meta.class_name) details += ` | ${meta.class_name}`;
                } else if (seg.type === 'crossing') {
                    if (meta.class_name) details = `Classe: ${meta.class_name}`;
                }

                const camLabel = seg.camera_position ? getPositionLabel(seg.camera_position) : '';

                return `
                    <div class="segment-item" data-start="${seg.start_time}">
                        <div class="d-flex align-items-center gap-2">
                            <span class="segment-badge ${seg.type}">${seg.type_display}</span>
                            ${camLabel ? `<span class="small text-secondary">${camLabel}</span>` : ''}
                            <span class="small text-light ms-auto">
                                ${formatTime(seg.start_time)} → ${formatTime(seg.end_time)}
                                <span class="text-secondary">(${seg.duration.toFixed(1)}s)</span>
                            </span>
                        </div>
                        ${details ? `<div class="small text-secondary mt-1">${details}</div>` : ''}
                    </div>`;
            }).join('');

            // Click to seek
            segmentsList.querySelectorAll('.segment-item').forEach(item => {
                item.addEventListener('click', () => {
                    const startTime = parseFloat(item.dataset.start);
                    if (!isNaN(startTime)) syncSeek(startTime);
                });
            });
        } catch (e) {
            console.error('Error loading segments:', e);
            segmentsList.innerHTML = '<div class="text-danger small">Erreur chargement segments</div>';
        }
    }

    // =========================================================================
    // Profiles
    // =========================================================================

    function populateModelDropdown() {
        const select = document.getElementById('profileModel');
        select.innerHTML = '<option value="">-- Sélectionner --</option>';

        config.availableModels.forEach(m => {
            const opt = document.createElement('option');
            opt.value = m.path;
            opt.textContent = `${m.name} (${m.task})`;
            select.appendChild(opt);
        });
    }

    function populateClassCheckboxes() {
        const container = document.getElementById('classCheckboxes');
        container.innerHTML = '';

        Object.entries(config.cocoClasses).forEach(([id, name]) => {
            const div = document.createElement('div');
            div.className = 'form-check form-check-inline';
            div.innerHTML = `
                <input class="form-check-input" type="checkbox" id="class_${id}" value="${id}" checked>
                <label class="form-check-label small text-light" for="class_${id}">${name} (${id})</label>`;
            container.appendChild(div);
        });
    }

    function getSelectedReportType() {
        const checked = document.querySelector('input[name="reportType"]:checked');
        return checked ? checked.value : 'proximity_overtaking';
    }

    function setReportTypeBadge(reportType) {
        const badge = document.getElementById('reportTypeBadge');
        if (!reportType || !profileSelect.value) {
            badge.classList.add('d-none');
            return;
        }
        const labels = {
            'proximity_overtaking': { text: 'Proximité & Dépassements', cls: 'bg-info text-dark' },
            'intersection_insertion': { text: 'Insertions', cls: 'bg-warning text-dark' },
        };
        const def = labels[reportType] || { text: reportType, cls: 'bg-secondary' };
        badge.className = `badge ${def.cls}`;
        badge.title = def.text;
        badge.textContent = def.text;
    }

    // =========================================================================
    // Intersection Management (profile modal)
    // =========================================================================

    let intersections = [];  // [{name, lat, lon, radius_m}, ...]
    let editingIntersectionIdx = null;
    let sam3Prompts = [];  // [{label, prompt}, ...]

    // ── Mini-map state ────────────────────────────────────────────────────────
    let intersectionMap = null;
    let intersectionMarker = null;
    let intersectionCircle = null;

    function _initIntersectionMap() {
        if (intersectionMap) return;  // already initialized
        intersectionMap = L.map('intersectionMap', { zoomControl: true }).setView([46.5, 2.3], 6);
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(intersectionMap);

        // Click on map → place marker + fill fields
        intersectionMap.on('click', (e) => {
            const { lat, lng } = e.latlng;
            _placeIntersectionMarker(lat, lng);
            document.getElementById('intLat').value = lat.toFixed(6);
            document.getElementById('intLon').value = lng.toFixed(6);
        });
    }

    function _placeIntersectionMarker(lat, lng) {
        const radius = parseInt(document.getElementById('intRadius').value) || 100;

        if (intersectionMarker) {
            intersectionMarker.setLatLng([lat, lng]);
        } else {
            intersectionMarker = L.marker([lat, lng], { draggable: true }).addTo(intersectionMap);
            intersectionMarker.on('dragend', (e) => {
                const pos = e.target.getLatLng();
                document.getElementById('intLat').value = pos.lat.toFixed(6);
                document.getElementById('intLon').value = pos.lng.toFixed(6);
                _updateIntersectionCircle(pos.lat, pos.lng);
            });
        }

        _updateIntersectionCircle(lat, lng);
        intersectionMap.setView([lat, lng], Math.max(intersectionMap.getZoom(), 15));
    }

    function _updateIntersectionCircle(lat, lng) {
        const radius = parseInt(document.getElementById('intRadius').value) || 100;
        if (intersectionCircle) {
            intersectionCircle.setLatLng([lat, lng]);
            intersectionCircle.setRadius(radius);
        } else {
            intersectionCircle = L.circle([lat, lng], {
                radius,
                color: '#f0ad4e',
                fillColor: '#f0ad4e',
                fillOpacity: 0.12,
                weight: 2,
            }).addTo(intersectionMap);
        }
    }

    function _refreshIntersectionMap(lat, lng) {
        // Called after form is visible — initialize map if needed then place marker
        _initIntersectionMap();
        intersectionMap.invalidateSize();
        if (lat !== null && lng !== null && !isNaN(lat) && !isNaN(lng)) {
            _placeIntersectionMarker(lat, lng);
        }
    }

    function renderIntersectionsList() {
        const list = document.getElementById('intersectionsList');
        if (!list) return;
        if (!intersections.length) {
            list.innerHTML = '<div class="text-muted small py-1">Aucune intersection configurée</div>';
            return;
        }
        list.innerHTML = intersections.map((it, idx) => `
            <div class="d-flex align-items-center gap-2 py-1 border-bottom border-secondary">
                <span class="badge bg-warning text-dark">${escapeHtml(it.name)}</span>
                <small class="text-secondary flex-grow-1">${it.lat.toFixed(5)}, ${it.lon.toFixed(5)} &mdash; ${it.radius_m}m</small>
                <button class="btn btn-sm btn-outline-secondary py-0 px-1 edit-int-btn" data-idx="${idx}" title="Modifier">
                    <i class="fas fa-pencil-alt"></i>
                </button>
                <button class="btn btn-sm btn-outline-danger py-0 px-1 del-int-btn" data-idx="${idx}" title="Supprimer">
                    <i class="fas fa-times"></i>
                </button>
            </div>
        `).join('');

        list.querySelectorAll('.edit-int-btn').forEach(btn => {
            btn.addEventListener('click', () => openIntersectionForm(parseInt(btn.dataset.idx)));
        });
        list.querySelectorAll('.del-int-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                intersections.splice(parseInt(btn.dataset.idx), 1);
                renderIntersectionsList();
            });
        });
    }

    function openIntersectionForm(idx = null) {
        editingIntersectionIdx = idx;
        const form = document.getElementById('intersectionForm');
        if (!form) return;

        let lat = null, lng = null;
        if (idx !== null && intersections[idx]) {
            const it = intersections[idx];
            document.getElementById('intName').value = it.name;
            document.getElementById('intLat').value = it.lat;
            document.getElementById('intLon').value = it.lon;
            document.getElementById('intRadius').value = it.radius_m;
            lat = it.lat;
            lng = it.lon;
        } else {
            document.getElementById('intName').value = '';
            document.getElementById('intLat').value = '';
            document.getElementById('intLon').value = '';
            document.getElementById('intRadius').value = 100;
            // Remove existing marker/circle for a fresh form
            if (intersectionMarker) { intersectionMarker.remove(); intersectionMarker = null; }
            if (intersectionCircle) { intersectionCircle.remove(); intersectionCircle = null; }
        }
        form.style.display = '';

        // Let the DOM render before initializing/refreshing the map
        requestAnimationFrame(() => _refreshIntersectionMap(lat, lng));
    }

    function saveIntersection() {
        const name = document.getElementById('intName').value.trim();
        const lat = parseFloat(document.getElementById('intLat').value);
        const lon = parseFloat(document.getElementById('intLon').value);
        const radius = parseInt(document.getElementById('intRadius').value) || 100;

        if (!name || isNaN(lat) || isNaN(lon)) {
            alert('Nom, latitude et longitude requis');
            return;
        }
        const entry = { name, lat, lon, radius_m: radius };
        if (editingIntersectionIdx !== null) {
            intersections[editingIntersectionIdx] = entry;
        } else {
            intersections.push(entry);
        }
        editingIntersectionIdx = null;
        document.getElementById('intersectionForm').style.display = 'none';
        if (intersectionMarker) { intersectionMarker.remove(); intersectionMarker = null; }
        if (intersectionCircle) { intersectionCircle.remove(); intersectionCircle = null; }
        renderIntersectionsList();
    }

    function toggleIntersectionSection(reportType) {
        const section = document.getElementById('intersectionsSection');
        if (section) {
            section.style.display = reportType === 'intersection_insertion' ? '' : 'none';
        }
    }

    // ── SAM3 Phase Avancée ────────────────────────────────────────────────────

    function renderSam3PromptsList() {
        const container = document.getElementById('sam3PromptsList');
        if (!container) return;
        if (!sam3Prompts.length) {
            container.innerHTML = '<div class="text-secondary small fst-italic">Aucun prompt — utilise les défauts (ligne de stop + passage piéton).</div>';
            return;
        }
        container.innerHTML = sam3Prompts.map((p, i) => `
            <div class="d-flex align-items-center gap-1 mb-1">
                <input type="text" class="form-control form-control-sm bg-dark text-light border-secondary flex-shrink-0"
                       style="width:90px;" value="${p.label}" placeholder="label"
                       onchange="(function(el){
                           const idx = ${i};
                           window._sam3LabelChange && window._sam3LabelChange(idx, el.value);
                       })(this)">
                <input type="text" class="form-control form-control-sm bg-dark text-light border-secondary"
                       value="${p.prompt}" placeholder="texte pour SAM3..."
                       onchange="(function(el){
                           const idx = ${i};
                           window._sam3PromptChange && window._sam3PromptChange(idx, el.value);
                       })(this)">
                <button class="btn btn-sm btn-outline-danger py-0 px-1" onclick="window._sam3Remove && window._sam3Remove(${i})">
                    <i class="fas fa-times"></i>
                </button>
            </div>`).join('');
    }

    // SAM3 prompt mutation helpers exposed on window to avoid inline closure issues
    window._sam3LabelChange = (idx, val) => { if (sam3Prompts[idx]) sam3Prompts[idx].label = val; };
    window._sam3PromptChange = (idx, val) => { if (sam3Prompts[idx]) sam3Prompts[idx].prompt = val; };
    window._sam3Remove = (idx) => { sam3Prompts.splice(idx, 1); renderSam3PromptsList(); };

    function toggleSam3Config() {
        const enabled = document.getElementById('sam3MarkingsEnabled').checked;
        const cfg = document.getElementById('sam3Config');
        if (cfg) cfg.style.display = enabled ? '' : 'none';
    }

    document.getElementById('sam3MarkingsEnabled').addEventListener('change', toggleSam3Config);

    document.getElementById('addSam3PromptBtn').addEventListener('click', () => {
        sam3Prompts.push({ label: 'stop_line', prompt: '' });
        renderSam3PromptsList();
    });

    // Sync circle radius when user changes the radius field
    document.getElementById('intRadius').addEventListener('input', () => {
        if (intersectionMarker) {
            const pos = intersectionMarker.getLatLng();
            _updateIntersectionCircle(pos.lat, pos.lng);
        }
    });

    // Sync marker when user types lat/lon manually
    ['intLat', 'intLon'].forEach(id => {
        document.getElementById(id).addEventListener('change', () => {
            const lat = parseFloat(document.getElementById('intLat').value);
            const lon = parseFloat(document.getElementById('intLon').value);
            if (!isNaN(lat) && !isNaN(lon) && intersectionMap) {
                _placeIntersectionMarker(lat, lon);
            }
        });
    });

    // ── Map city search (Nominatim) ───────────────────────────────────────────
    async function _searchCity() {
        const input = document.getElementById('mapCitySearch');
        const errEl = document.getElementById('mapSearchError');
        const errMsg = document.getElementById('mapSearchErrorMsg');
        const query = input.value.trim();
        if (!query || !intersectionMap) return;

        errEl.style.display = 'none';
        input.disabled = true;
        document.getElementById('mapCitySearchBtn').disabled = true;

        try {
            const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=1&accept-language=fr`;
            const resp = await fetch(url, { headers: { 'Accept-Language': 'fr' } });
            const data = await resp.json();
            if (data && data.length > 0) {
                const lat = parseFloat(data[0].lat);
                const lon = parseFloat(data[0].lon);
                intersectionMap.setView([lat, lon], 14);
            } else {
                errMsg.textContent = `Ville introuvable : « ${query} »`;
                errEl.style.display = '';
                setTimeout(() => { errEl.style.display = 'none'; }, 3000);
            }
        } catch (e) {
            errMsg.textContent = 'Erreur de recherche';
            errEl.style.display = '';
            setTimeout(() => { errEl.style.display = 'none'; }, 3000);
        } finally {
            input.disabled = false;
            document.getElementById('mapCitySearchBtn').disabled = false;
        }
    }

    document.getElementById('mapCitySearchBtn').addEventListener('click', _searchCity);
    document.getElementById('mapCitySearch').addEventListener('keydown', e => {
        if (e.key === 'Enter') { e.preventDefault(); _searchCity(); }
    });

    // Wire up intersection form buttons
    document.getElementById('addIntersectionBtn').addEventListener('click', () => openIntersectionForm(null));
    document.getElementById('saveIntersectionBtn').addEventListener('click', saveIntersection);
    document.getElementById('cancelIntersectionBtn').addEventListener('click', () => {
        document.getElementById('intersectionForm').style.display = 'none';
        editingIntersectionIdx = null;
        if (intersectionMarker) { intersectionMarker.remove(); intersectionMarker = null; }
        if (intersectionCircle) { intersectionCircle.remove(); intersectionCircle = null; }
    });

    // Show/hide intersections section on report type change
    document.querySelectorAll('input[name="reportType"]').forEach(radio => {
        radio.addEventListener('change', () => toggleIntersectionSection(radio.value));
    });

    // =========================================================================
    // RTMaps Upload
    // =========================================================================

    let rtmapsPollingTimer = null;

    function updateRtmapsPanel() {
        const panel = document.getElementById('rtmapsPanel');
        const opt = profileSelect.options[profileSelect.selectedIndex];
        const reportType = opt ? opt.dataset.reportType : '';
        if (panel) {
            panel.style.display = (reportType === 'intersection_insertion' && currentSessionId) ? '' : 'none';
        }
    }

    async function uploadRtmaps() {
        if (!currentSessionId) return;
        const recFile = document.getElementById('rtmapsRecFile').files[0];
        const csvFile = document.getElementById('rtmapsCsvFile').files[0];
        if (!recFile) { alert('Sélectionnez un fichier .rec'); return; }

        const form = new FormData();
        form.append('rec_file', recFile);
        if (csvFile) form.append('csv_file', csvFile);

        const extractBtn = document.getElementById('rtmapsExtractBtn');
        const progressDiv = document.getElementById('rtmapsProgress');
        extractBtn.disabled = true;
        if (progressDiv) progressDiv.style.display = '';
        setRtmapsProgress(2, 'Envoi du fichier...');

        try {
            const resp = await fetch(`${config.urls.uploadRtmaps}${currentSessionId}/rtmaps/upload/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
                body: form,
            });
            const data = await resp.json();
            if (!data.success) {
                alert('Erreur: ' + (data.error || 'Inconnue'));
                extractBtn.disabled = false;
                return;
            }
            // Start polling extraction status
            clearInterval(rtmapsPollingTimer);
            rtmapsPollingTimer = setInterval(() => pollRtmapsStatus(), 2000);
        } catch (e) {
            console.error('[RTMaps] upload error:', e);
            extractBtn.disabled = false;
        }
    }

    async function pollRtmapsStatus() {
        if (!currentSessionId) return;
        try {
            const resp = await fetch(`${config.urls.rtmapsStatus}${currentSessionId}/rtmaps/status/`);
            const data = await resp.json();
            setRtmapsProgress(data.progress || 0, data.status_message || '');

            if (data.session_status === 'completed' || data.session_status === 'failed' ||
                data.progress >= 100) {
                clearInterval(rtmapsPollingTimer);
                rtmapsPollingTimer = null;
                document.getElementById('rtmapsExtractBtn').disabled = false;
                if (data.session_status === 'failed') {
                    setRtmapsProgress(0, 'Extraction echouee');
                } else if (data.progress >= 100) {
                    setRtmapsProgress(100, 'Extraction terminee');
                    // Reload session to show extracted cameras
                    setTimeout(() => loadSession(currentSessionId), 1000);
                }
            }
            // If YOLO analysis started, switch to normal polling
            if (data.session_status === 'processing' || data.session_status === 'pending') {
                clearInterval(rtmapsPollingTimer);
                rtmapsPollingTimer = null;
                startStatusPolling(currentSessionId);
            }
        } catch (e) {
            console.error('[RTMaps] polling error:', e);
        }
    }

    function setRtmapsProgress(pct, msg) {
        const label = document.getElementById('rtmapsProgressLabel');
        const pctEl = document.getElementById('rtmapsProgressPct');
        const bar = document.getElementById('rtmapsProgressBar');
        if (label) label.textContent = msg || 'Extraction en cours...';
        if (pctEl) pctEl.textContent = Math.round(pct) + '%';
        if (bar) bar.style.width = pct + '%';
    }

    // Wire RTMaps extract button
    document.getElementById('rtmapsRecFile').addEventListener('change', () => {
        document.getElementById('rtmapsExtractBtn').disabled = !document.getElementById('rtmapsRecFile').files.length;
    });
    document.getElementById('rtmapsExtractBtn').addEventListener('click', uploadRtmaps);

    async function saveProfile() {
        const name = document.getElementById('profileName').value.trim();
        const reportType = getSelectedReportType();
        const modelPath = document.getElementById('profileModel').value;
        const taskType = document.getElementById('profileTaskType').value;
        const confidence = parseFloat(document.getElementById('profileConfidence').value);
        const iou = parseFloat(document.getElementById('profileIou').value);
        const tracker = document.getElementById('profileTracker').value;

        const targetClasses = [];
        document.querySelectorAll('#classCheckboxes input:checked').forEach(cb => {
            targetClasses.push(parseInt(cb.value));
        });

        if (!name || !modelPath) {
            alert('Nom et modèle requis');
            return;
        }

        // Send existing profile id to update instead of creating a new one
        const editingId = profileSelect.value || null;

        try {
            const resp = await fetch(config.urls.saveProfile, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    id: editingId,
                    name, report_type: reportType, intersections,
                    road_model_path: document.getElementById('roadModelPath').value.trim(),
                    sam3_markings_enabled: document.getElementById('sam3MarkingsEnabled').checked,
                    sam3_markings_prompts: sam3Prompts,
                    sam3_as_road_fallback: document.getElementById('sam3AsRoadFallback').checked,
                    model_path: modelPath, task_type: taskType,
                    target_classes: targetClasses, confidence, iou_threshold: iou, tracker,
                }),
            });
            const data = await resp.json();

            if (data.success) {
                profileModal.hide();
                // Add or update in dropdown
                let existing = profileSelect.querySelector(`option[value="${data.profile.id}"]`);
                if (existing) {
                    existing.textContent = data.profile.name;
                    existing.dataset.reportType = data.profile.report_type;
                } else {
                    const opt = document.createElement('option');
                    opt.value = data.profile.id;
                    opt.textContent = data.profile.name;
                    opt.dataset.reportType = data.profile.report_type;
                    profileSelect.appendChild(opt);
                }
                profileSelect.value = data.profile.id;
                setReportTypeBadge(data.profile.report_type);
            } else {
                alert('Erreur: ' + (data.error || 'Inconnue'));
            }
        } catch (e) {
            console.error('Error saving profile:', e);
        }
    }

    // Profile sliders
    document.getElementById('profileConfidence').addEventListener('input', e => {
        document.getElementById('confidenceValue').textContent = e.target.value;
    });
    document.getElementById('profileIou').addEventListener('input', e => {
        document.getElementById('iouValue').textContent = e.target.value;
    });

    // =========================================================================
    // Event Listeners
    // =========================================================================

    newSessionBtn.addEventListener('click', () => {
        document.getElementById('newSessionName').value = '';
        newSessionModal.show();
    });

    document.getElementById('createSessionBtn').addEventListener('click', createSession);

    // Enter key in new session modal
    document.getElementById('newSessionName').addEventListener('keydown', e => {
        if (e.key === 'Enter') createSession();
    });

    sessionSelect.addEventListener('change', () => {
        const id = sessionSelect.value;
        if (id) {
            loadSession(id);
        } else {
            stopStatusPolling();
            currentSessionId = null;
            clearCameraGrid();
            deleteSessionBtn.disabled = true;
            startAnalysisBtn.disabled = true;
            hideProgress();
            hideResults();
        }
    });

    deleteSessionBtn.addEventListener('click', () => {
        if (currentSessionId) deleteSession(currentSessionId);
    });

    startAnalysisBtn.addEventListener('click', startAnalysis);

    cancelAnalysisBtn.addEventListener('click', cancelAnalysis);

    editProfileBtn.addEventListener('click', async () => {
        populateModelDropdown();
        populateClassCheckboxes();

        // Load selected profile data into the modal
        const selectedId = profileSelect.value;
        if (selectedId) {
            try {
                const resp = await fetch(config.urls.listProfiles);
                const data = await resp.json();
                const profile = (data.profiles || []).find(p => String(p.id) === String(selectedId));
                if (profile) {
                    // Report type radio
                    const rtVal = profile.report_type || 'proximity_overtaking';
                    const rtRadio = document.querySelector(`input[name="reportType"][value="${rtVal}"]`);
                    if (rtRadio) rtRadio.checked = true;
                    toggleIntersectionSection(rtVal);

                    document.getElementById('profileName').value = profile.name || '';
                    document.getElementById('profileModel').value = profile.model_path || '';
                    document.getElementById('profileTaskType').value = profile.task_type || 'detect';
                    document.getElementById('profileConfidence').value = profile.confidence;
                    document.getElementById('confidenceValue').textContent = profile.confidence;
                    document.getElementById('profileIou').value = profile.iou_threshold;
                    document.getElementById('iouValue').textContent = profile.iou_threshold;
                    document.getElementById('profileTracker').value = profile.tracker || 'botsort';

                    // Uncheck all, then check target classes
                    document.querySelectorAll('#classCheckboxes input').forEach(cb => { cb.checked = false; });
                    (profile.target_classes || []).forEach(cls => {
                        const cb = document.getElementById(`class_${cls}`);
                        if (cb) cb.checked = true;
                    });

                    // Load intersections + road model
                    intersections = profile.intersections || [];
                    renderIntersectionsList();
                    document.getElementById('intersectionForm').style.display = 'none';
                    document.getElementById('roadModelPath').value = profile.road_model_path || '';

                    // SAM3 Phase Avancée
                    document.getElementById('sam3MarkingsEnabled').checked = !!profile.sam3_markings_enabled;
                    sam3Prompts = Array.isArray(profile.sam3_markings_prompts) ? [...profile.sam3_markings_prompts] : [];
                    document.getElementById('sam3AsRoadFallback').checked = !!profile.sam3_as_road_fallback;
                    toggleSam3Config();
                    renderSam3PromptsList();
                }
            } catch (e) {
                console.error('Error loading profile:', e);
            }
        } else {
            // No profile selected: reset to defaults
            const defaultRadio = document.querySelector('input[name="reportType"][value="proximity_overtaking"]');
            if (defaultRadio) defaultRadio.checked = true;
            toggleIntersectionSection('proximity_overtaking');
            document.getElementById('profileName').value = '';
            document.getElementById('profileModel').value = '';
            document.getElementById('profileTaskType').value = 'detect';
            document.getElementById('profileConfidence').value = 0.25;
            document.getElementById('confidenceValue').textContent = '0.25';
            document.getElementById('profileIou').value = 0.45;
            document.getElementById('iouValue').textContent = '0.45';
            document.getElementById('profileTracker').value = 'botsort';
            intersections = [];
            renderIntersectionsList();
            document.getElementById('intersectionForm').style.display = 'none';
            document.getElementById('roadModelPath').value = '';

            // SAM3 Phase Avancée — reset
            document.getElementById('sam3MarkingsEnabled').checked = false;
            sam3Prompts = [];
            document.getElementById('sam3AsRoadFallback').checked = false;
            toggleSam3Config();
            renderSam3PromptsList();
        }

        profileModal.show();
    });

    document.getElementById('saveProfileBtn').addEventListener('click', saveProfile);

    refreshSessionsBtn.addEventListener('click', loadSessions);

    closeResultsBtn.addEventListener('click', hideResults);

    // Profile assignment: when profile changes, update session + refresh badge + RTMaps panel
    profileSelect.addEventListener('change', async () => {
        // Update badge immediately from option data-attribute
        const selectedOpt = profileSelect.options[profileSelect.selectedIndex];
        setReportTypeBadge(selectedOpt ? selectedOpt.dataset.reportType : null);
        updateRtmapsPanel();

        if (!currentSessionId) return;
        try {
            const form = new FormData();
            form.append('profile_id', profileSelect.value || '');
            await fetch(`${config.urls.updateSession}${currentSessionId}/update/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
                body: form,
            });
        } catch (e) {
            console.error('Error updating profile:', e);
        }
    });

    // =========================================================================
    // Utilities
    // =========================================================================

    function getPositionLabel(pos) {
        const labels = { front: 'Avant', rear: 'Arrière', left: 'Gauche', right: 'Droite' };
        return labels[pos] || pos;
    }

    function getStatusBadge(status) {
        const badges = {
            draft: '<span class="badge bg-secondary">Brouillon</span>',
            pending: '<span class="badge bg-info">En attente</span>',
            processing: '<span class="badge bg-warning">En cours</span>',
            completed: '<span class="badge bg-success">Terminé</span>',
            failed: '<span class="badge bg-danger">Échec</span>',
        };
        return badges[status] || badges.draft;
    }

    function formatDate(dateStr) {
        const d = new Date(dateStr);
        return d.toLocaleDateString('fr-FR', {
            day: '2-digit', month: '2-digit', year: 'numeric',
            hour: '2-digit', minute: '2-digit',
        });
    }

    function formatTime(seconds) {
        if (!seconds || isNaN(seconds)) return '0:00';
        const m = Math.floor(seconds / 60);
        const s = Math.floor(seconds % 60);
        return `${m}:${s.toString().padStart(2, '0')}`;
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // =========================================================================
    // Init
    // =========================================================================

    initDropZones();
    setupTimeSync();
    initExportButtons();
    loadSessions();
});
