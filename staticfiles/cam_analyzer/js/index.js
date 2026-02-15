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

            // Clear and restore cameras
            clearCameraGrid();
            cameras = {};

            if (data.cameras) {
                data.cameras.forEach(cam => {
                    cameras[cam.position] = cam;
                    showCameraVideo(cam.position, cam.video_url, cam);
                });
            }

            // Set profile
            if (data.profile_id) {
                profileSelect.value = data.profile_id;
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

    function syncPlay() {
        isPlaying = true;
        playPauseIcon.className = 'fas fa-pause';

        const speed = parseFloat(playbackSpeed.value);
        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (video && video.src && cameras[pos]) {
                video.playbackRate = speed;
                video.play().catch(() => {});
            }
        });
    }

    function syncPause() {
        isPlaying = false;
        playPauseIcon.className = 'fas fa-play';

        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (video && video.src) {
                video.pause();
            }
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

        // Update detection overlay for current time
        updateDetectionOverlay(time);
    }

    function updateTimeDisplay(currentTime) {
        syncTimeDisplay.textContent = `${formatTime(currentTime)} / ${formatTime(maxDuration)}`;
    }

    // Time update listener on each video
    function setupTimeSync() {
        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (!video) return;

            video.addEventListener('timeupdate', () => {
                if (cameras[pos] && isPlaying) {
                    const offset = cameras[pos].time_offset || 0;
                    const currentTime = video.currentTime - offset;
                    syncSeekBar.value = currentTime;
                    updateTimeDisplay(currentTime);

                    // Update detection overlay
                    updateDetectionOverlay(currentTime);

                    // Update timeline cursor
                    updateTimelineCursor(currentTime);
                }
            });
        });
    }

    // Event listeners
    syncPlayPauseBtn.addEventListener('click', () => {
        if (isPlaying) syncPause();
        else syncPlay();
    });

    syncStopBtn.addEventListener('click', syncStop);

    syncSeekBar.addEventListener('input', () => {
        syncSeek(parseFloat(syncSeekBar.value));
    });

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
        positions.forEach(pos => {
            const data = detectionData[pos];
            if (!data || !data.frames.length) {
                clearCanvas(pos);
                return;
            }

            // Find closest frame by timestamp
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

        // Match canvas to displayed video element size
        const rect = video.getBoundingClientRect();
        canvas.width = rect.width;
        canvas.height = rect.height;

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

    async function saveProfile() {
        const name = document.getElementById('profileName').value.trim();
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
                    name, model_path: modelPath, task_type: taskType,
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
                } else {
                    const opt = document.createElement('option');
                    opt.value = data.profile.id;
                    opt.textContent = data.profile.name;
                    profileSelect.appendChild(opt);
                }
                profileSelect.value = data.profile.id;
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
                }
            } catch (e) {
                console.error('Error loading profile:', e);
            }
        } else {
            // No profile selected: reset to defaults
            document.getElementById('profileName').value = '';
            document.getElementById('profileModel').value = '';
            document.getElementById('profileTaskType').value = 'detect';
            document.getElementById('profileConfidence').value = 0.25;
            document.getElementById('confidenceValue').textContent = '0.25';
            document.getElementById('profileIou').value = 0.45;
            document.getElementById('iouValue').textContent = '0.45';
            document.getElementById('profileTracker').value = 'botsort';
        }

        profileModal.show();
    });

    document.getElementById('saveProfileBtn').addEventListener('click', saveProfile);

    refreshSessionsBtn.addEventListener('click', loadSessions);

    closeResultsBtn.addEventListener('click', hideResults);

    // Profile assignment: when profile changes, update session
    profileSelect.addEventListener('change', async () => {
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
