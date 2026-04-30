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

    // Persist the active session across page reloads. Per-user key so different
    // accounts on the same browser don't fight over each other's selection.
    const ACTIVE_SESSION_KEY = `camAnalyzer:activeSession:${(config && config.userId) || 'anon'}`;
    function saveActiveSession(id) {
        try {
            if (id) localStorage.setItem(ACTIVE_SESSION_KEY, id);
            else localStorage.removeItem(ACTIVE_SESSION_KEY);
        } catch (e) { /* localStorage may be disabled */ }
    }
    function loadActiveSessionId() {
        try { return localStorage.getItem(ACTIVE_SESSION_KEY); }
        catch (e) { return null; }
    }

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
                saveActiveSession(data.session_id);
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
            if (!resp.ok) {
                // Session no longer exists (deleted, wrong user, …) — clear state
                saveActiveSession(null);
                return;
            }
            const data = await resp.json();

            currentSessionId = sessionId;
            saveActiveSession(sessionId);
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

            // Set profile + update report type badge + active-profile context
            if (data.profile_id) {
                profileSelect.value = data.profile_id;
                const selectedOpt = profileSelect.options[profileSelect.selectedIndex];
                setReportTypeBadge(selectedOpt ? selectedOpt.dataset.reportType : null);
                loadActiveProfile(data.profile_id);
            } else {
                setReportTypeBadge(null);
                loadActiveProfile(null);
            }

            // Right-panel exports enabled only when analysis has finished
            setRightPanelExportsEnabled(data.status === 'completed');

            updatePlaybackControls();

            // Pre-computed intersection windows (if any)
            renderIntersectionWindows(data.intersection_windows || []);

            // Right-panel mini-map: trajectory + intersections + shuttle position
            renderMiniMap(data.gps_track || [], data.intersection_windows || []);

            // Check session status and react
            if (data.status === 'processing' || data.status === 'pending') {
                setAnalysisUI(true);
                startStatusPolling(sessionId);
            } else if (data.status === 'completed' && data.results_summary) {
                showResults(data.results_summary);
                loadAllDetections(sessionId);
                setRightPanelExportsEnabled(true);
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
                    saveActiveSession(null);
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

            // Handle drop from FileManager sidebar (vakata DND — dispatches filemanager:filedrop)
            zone.addEventListener('filemanager:filedrop', async function (e) {
                if (!currentSessionId) {
                    alert('Créez ou sélectionnez une session d\'abord');
                    return;
                }
                const { path, name, mime } = e.detail;
                try {
                    const mediaUrl = (window.MEDIA_URL || '/media/') + path;
                    const response = await fetch(mediaUrl);
                    if (!response.ok) throw new Error(`HTTP ${response.status}`);
                    const blob = await response.blob();
                    const file = new File([blob], name || 'video', { type: blob.type || mime || 'video/mp4' });
                    if (!file.type.startsWith('video/')) {
                        alert('Le fichier déposé n\'est pas une vidéo');
                        return;
                    }
                    uploadCamera(pos, file);
                } catch (err) {
                    console.error('[cam_analyzer] FileManager drop failed:', err);
                    alert('Erreur lors de l\'import depuis le filemanager');
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
        updateAnalyzedBadge(position);
    }

    // Active profile context — set by loadSession after fetching profile details.
    // Drives the per-tile "Analysée / Lecture seule" badges and the right-panel
    // profile summary.
    let activeProfile = null;

    function updateAnalyzedBadge(position) {
        const info = document.getElementById(`info-${position}`);
        if (!info) return;
        let badge = info.querySelector('.analyzed-badge');
        if (!badge) {
            badge = document.createElement('span');
            badge.className = 'badge analyzed-badge';
            badge.style.cssText = 'font-size:0.6rem; padding:0.2rem 0.45rem;';
            // Insert after the position label (first .badge child)
            const firstBadge = info.querySelector('.badge');
            if (firstBadge && firstBadge.nextSibling) {
                info.insertBefore(badge, firstBadge.nextSibling);
            } else {
                info.appendChild(badge);
            }
        }
        const analyzed = activeProfile
            ? (activeProfile.analyzed_positions || ['front', 'rear']).includes(position)
            : (position === 'front' || position === 'rear');
        if (analyzed) {
            badge.textContent = 'Analysée';
            badge.style.background = '#198754';
            badge.style.color = '#fff';
            badge.title = 'YOLO sera exécuté sur cette vue';
        } else {
            badge.textContent = 'Lecture seule';
            badge.style.background = '#495057';
            badge.style.color = '#dee2e6';
            badge.title = 'Vue extraite pour visualisation, pas d\'analyse YOLO';
        }
    }

    function refreshAllAnalyzedBadges() {
        positions.forEach(pos => {
            if (cameras[pos]) updateAnalyzedBadge(pos);
        });
    }

    const POSITION_LABELS = { front: 'Avant', rear: 'Arrière', left: 'Gauche', right: 'Droite' };

    async function loadActiveProfile(profileId) {
        const summary = document.getElementById('camAnalyzerProfileSummary');
        if (!profileId) {
            activeProfile = null;
            if (summary) summary.innerHTML = '<span class="text-secondary">Aucun profil sélectionné.</span>';
            refreshAllAnalyzedBadges();
            return;
        }
        try {
            const resp = await fetch(config.urls.listProfiles);
            const data = await resp.json();
            const p = (data.profiles || []).find(x => String(x.id) === String(profileId));
            activeProfile = p || null;
            renderProfileSummary();
            refreshAllAnalyzedBadges();
        } catch (e) {
            console.error('Error loading active profile:', e);
        }
    }

    function renderProfileSummary() {
        const summary = document.getElementById('camAnalyzerProfileSummary');
        if (!summary) return;
        if (!activeProfile) {
            summary.innerHTML = '<span class="text-secondary">Aucun profil sélectionné.</span>';
            return;
        }
        const p = activeProfile;
        const analyzed = (p.analyzed_positions || ['front', 'rear'])
            .map(x => POSITION_LABELS[x] || x).join(', ');
        const reportLabel = p.report_type === 'intersection_insertion'
            ? 'Insertions intersections' : 'Proximité & dépassements';
        const intersectionsCount = (p.intersections || []).length;
        const modelName = (p.model_path || '').split(/[\\/]/).pop() || '—';
        const classes = (p.target_classes || []).join(', ') || '—';
        summary.innerHTML = `
            <div class="d-flex flex-column gap-1" style="font-size: 0.78rem;">
                <div><span class="text-secondary">Nom :</span> <span class="text-light fw-semibold">${escapeHtml(p.name)}</span></div>
                <div><span class="text-secondary">Type :</span> <span class="text-light">${reportLabel}</span></div>
                <div><span class="text-secondary">Modèle :</span> <span class="text-light">${escapeHtml(modelName)}</span></div>
                <div><span class="text-secondary">Classes :</span> <span class="text-light">${escapeHtml(classes)}</span></div>
                <div><span class="text-secondary">Vues analysées :</span> <span class="text-warning">${escapeHtml(analyzed)}</span></div>
                ${p.report_type === 'intersection_insertion' ? `
                    <div><span class="text-secondary">Intersections :</span> <span class="text-light">${intersectionsCount}</span></div>
                    <div><span class="text-secondary">Restreint aux fenêtres :</span> <span class="text-light">${p.restrict_to_intersection_windows !== false ? 'Oui' : 'Non'}</span></div>
                ` : ''}
            </div>
            <button class="btn btn-sm btn-outline-warning mt-2 w-100" id="rpEditProfileBtn">
                <i class="fas fa-cog me-1"></i>Modifier le profil
            </button>
        `;
        const btn = document.getElementById('rpEditProfileBtn');
        if (btn) btn.addEventListener('click', () => {
            // Call the editor opener directly rather than synthetically clicking
            // the toolbar button — avoids any synthetic-event quirk and the
            // function is identical for both entry points.
            openProfileEditor();
        });
    }

    // (escapeHtml is defined later — same scope, no conflict at call time)

    // Right-panel quick exports — wired to the same URLs used by the main results panel
    function setupRightPanelExports() {
        const map = [
            ['rpExportCsvBtn', () => exportDetectionsCsv()],
            ['rpExportJsonBtn', () => exportSessionJson()],
            ['rpExportSegmentsBtn', () => exportSegmentsCsv()],
        ];
        map.forEach(([id, handler]) => {
            const btn = document.getElementById(id);
            if (btn) btn.addEventListener('click', handler);
        });
    }

    function setRightPanelExportsEnabled(enabled) {
        ['rpExportCsvBtn', 'rpExportJsonBtn', 'rpExportSegmentsBtn'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = !enabled;
        });
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
        const sticky = document.getElementById('stickyBottomBar');
        if (activePositions.length === 0) {
            playbackControls.style.display = 'none';
            if (sticky) updateStickyBarVisibility();
            return;
        }

        playbackControls.style.display = 'block';
        if (sticky) sticky.style.display = '';

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

        // Re-render intersection markers now that maxDuration is known
        renderIntersectionWindows(intersectionWindows);
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

    // Jump to an intersection window (small offset before t_enter for context)
    const intersectionJumpSelect = document.getElementById('intersectionJumpSelect');
    if (intersectionJumpSelect) {
        intersectionJumpSelect.addEventListener('change', () => {
            const t = parseFloat(intersectionJumpSelect.value);
            if (!isNaN(t) && maxDuration > 0) {
                const target = Math.max(0, t - 2);  // 2s lead-in for approach context
                syncSeek(target);
                syncSeekBar.value = String(target);
            }
            intersectionJumpSelect.value = '';  // reset to placeholder for repeat jumps
        });
    }

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
        updateStickyBarVisibility();
    }

    function hideProgress() {
        analysisProgress.style.display = 'none';
        startAnalysisBtn.style.display = '';
        cancelAnalysisBtn.style.display = 'none';
        updateStickyBarVisibility();
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

            if (data.intersection_windows) {
                renderIntersectionWindows(data.intersection_windows);
            }

            if (data.status === 'completed') {
                stopStatusPolling();
                hideProgress();
                showResults(data.results_summary);
                loadAllDetections(sessionId);
                loadSessions(); // refresh table
                setRightPanelExportsEnabled(true);
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
            updateStickyBarVisibility();
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
        // Mini-map + pass info should always follow the playback, even before
        // an analysis has produced the proximity timeline.
        updateMiniMapShuttle(currentTime);
        updatePassInfo(currentTime);

        if (!proximityTimeline || proximityTimeline.style.display === 'none') return;
        if (maxDuration <= 0) return;

        const pct = Math.min(100, (currentTime / maxDuration) * 100);
        timelineCursor.style.left = `${pct}%`;
    }

    // =========================================================================
    // Right-panel mini-map (Leaflet)
    // =========================================================================

    let miniMap = null;
    let miniMapPolyline = null;
    let miniMapShuttleMarker = null;
    let miniMapIntersectionLayers = [];
    let miniMapClickMarker = null;
    let miniMapPassHighlight = null;   // polyline showing the current pass in its colour
    let miniMapHighlightedPassIdx = -1; // last rendered pass — avoids 60Hz polyline rebuilds
    let cachedGpsTrack = [];           // [{ts, lat, lon}, ...] downsampled

    function initMiniMap() {
        const container = document.getElementById('camAnalyzerMiniMap');
        if (!container || miniMap) return;
        if (typeof L === 'undefined') {
            console.warn('Leaflet not loaded');
            return;
        }

        miniMap = L.map(container, { zoomControl: true, attributionControl: false })
                   .setView([46.5, 2.3], 6);
        // CartoDB dark tiles — no Referer-based blocking (unlike tile.openstreetmap.org)
        // and matches the WAMA dark theme. Same provider as the profile editor map.
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 19,
        }).addTo(miniMap);

        miniMap.on('click', (e) => handleMiniMapClick(e.latlng.lat, e.latlng.lng));
    }

    function renderMiniMap(gpsTrack, intersectionWindows) {
        initMiniMap();
        if (!miniMap) return;

        cachedGpsTrack = Array.isArray(gpsTrack) ? gpsTrack.filter(p => p.lat && p.lon) : [];

        // Clear previous layers
        if (miniMapPolyline) { miniMap.removeLayer(miniMapPolyline); miniMapPolyline = null; }
        miniMapIntersectionLayers.forEach(l => miniMap.removeLayer(l));
        miniMapIntersectionLayers = [];
        if (miniMapShuttleMarker) { miniMap.removeLayer(miniMapShuttleMarker); miniMapShuttleMarker = null; }
        if (miniMapClickMarker) { miniMap.removeLayer(miniMapClickMarker); miniMapClickMarker = null; }
        if (miniMapPassHighlight) { miniMap.removeLayer(miniMapPassHighlight); miniMapPassHighlight = null; }
        miniMapHighlightedPassIdx = -1;

        // Draw the shuttle trajectory polyline
        if (cachedGpsTrack.length >= 2) {
            const latlngs = cachedGpsTrack.map(p => [p.lat, p.lon]);
            miniMapPolyline = L.polyline(latlngs, {
                color: '#0dcaf0', weight: 3, opacity: 0.8,
            }).addTo(miniMap);
        }

        // Draw intersection centers (deduplicated by name) with their radius circles
        const seen = new Set();
        (intersectionWindows || []).forEach(w => {
            if (seen.has(w.name)) return;
            seen.add(w.name);
            if (w.lat == null || w.lon == null) return;

            const circle = L.circle([w.lat, w.lon], {
                radius: w.radius_m || 100,
                color: '#ffc107', weight: 2, fillColor: '#ffc107', fillOpacity: 0.12,
            }).addTo(miniMap);
            const center = L.circleMarker([w.lat, w.lon], {
                radius: 5, color: '#ffc107', weight: 2, fillColor: '#ffc107', fillOpacity: 1,
            }).addTo(miniMap)
              .bindTooltip(w.name, { permanent: false, direction: 'top' });
            miniMapIntersectionLayers.push(circle, center);
        });

        // Initial shuttle marker at first GPS point (if any)
        if (cachedGpsTrack.length > 0) {
            miniMapShuttleMarker = L.circleMarker([cachedGpsTrack[0].lat, cachedGpsTrack[0].lon], {
                radius: 7, color: '#fff', weight: 2, fillColor: '#dc3545', fillOpacity: 1,
            }).addTo(miniMap);
        }

        // Fit map to data
        if (miniMapPolyline) {
            miniMap.fitBounds(miniMapPolyline.getBounds(), { padding: [12, 12] });
        } else if (miniMapIntersectionLayers.length > 0) {
            const grp = L.featureGroup(miniMapIntersectionLayers);
            miniMap.fitBounds(grp.getBounds(), { padding: [12, 12] });
        }

        // Force redraw (Leaflet sometimes mis-sizes when its container was hidden)
        setTimeout(() => miniMap && miniMap.invalidateSize(), 50);
    }

    // Find the GPS point whose timestamp is closest to a given time
    function findGpsAtTime(t) {
        if (!cachedGpsTrack.length) return null;
        let lo = 0, hi = cachedGpsTrack.length - 1;
        while (lo < hi - 1) {
            const mid = (lo + hi) >> 1;
            if (cachedGpsTrack[mid].ts <= t) lo = mid; else hi = mid;
        }
        return Math.abs(cachedGpsTrack[lo].ts - t) <= Math.abs(cachedGpsTrack[hi].ts - t)
            ? cachedGpsTrack[lo] : cachedGpsTrack[hi];
    }

    function updateMiniMapShuttle(currentTime) {
        if (!miniMap || !miniMapShuttleMarker || !cachedGpsTrack.length) return;
        const p = findGpsAtTime(currentTime);
        if (p) miniMapShuttleMarker.setLatLng([p.lat, p.lon]);
        updateMiniMapPassHighlight(currentTime);
    }

    // Highlight the GPS segment corresponding to the pass that contains
    // currentTime. The segment is rendered ON TOP of the base polyline in the
    // pass's distinct colour, so the user can visually identify the active
    // passage even when several passages overlap geographically.
    //
    // Only rebuilds the polyline when the active pass *changes* — without this
    // throttling the rAF loop calls it 60×/sec which churns the DOM and steals
    // budget from the per-camera drift correction (the front video can fall
    // out of sync with rear/left/right).
    function updateMiniMapPassHighlight(currentTime) {
        if (!miniMap || !cachedGpsTrack.length) return;

        const w = (intersectionWindows || []).find(
            x => x.t_enter <= currentTime && currentTime <= x.t_exit
        );
        const newIdx = w ? (w._passIdx != null ? w._passIdx : -1) : -1;
        if (newIdx === miniMapHighlightedPassIdx) return;
        miniMapHighlightedPassIdx = newIdx;

        if (miniMapPassHighlight) {
            miniMap.removeLayer(miniMapPassHighlight);
            miniMapPassHighlight = null;
        }

        if (!w) return;

        const segment = cachedGpsTrack
            .filter(p => p.ts >= w.t_enter && p.ts <= w.t_exit)
            .map(p => [p.lat, p.lon]);

        if (segment.length >= 2) {
            miniMapPassHighlight = L.polyline(segment, {
                color: w._color || '#ffc107',
                weight: 5,
                opacity: 0.9,
            }).addTo(miniMap);
            if (miniMapShuttleMarker) miniMapShuttleMarker.bringToFront();
        }
    }

    // Click on map: snap to the spatially-closest GPS sample and seek there.
    // We do NOT prefer the temporal-closest among multiple matches: when the
    // shuttle drives the same road both ways, picking by time can land on the
    // OTHER direction's parallel-offset trace (apparent 50-80m miss). Spatial
    // closeness honours the click; the dropdown still lets the user pick a
    // specific passage when they want it.
    function handleMiniMapClick(lat, lng) {
        if (!cachedGpsTrack.length) return;

        const SNAP_THRESHOLD_M = 80;  // off-track clicks ignored
        const dToM = (a, b) => {
            const R = 6371000;
            const phi1 = a.lat * Math.PI / 180, phi2 = b.lat * Math.PI / 180;
            const dphi = (b.lat - a.lat) * Math.PI / 180;
            const dlam = (b.lon - a.lon) * Math.PI / 180;
            const x = Math.sin(dphi / 2) ** 2 +
                      Math.cos(phi1) * Math.cos(phi2) * Math.sin(dlam / 2) ** 2;
            return 2 * R * Math.asin(Math.sqrt(x));
        };

        const click = { lat, lon: lng };
        let best = null, bestD = Infinity;
        for (const p of cachedGpsTrack) {
            const d = dToM(p, click);
            if (d < bestD) { bestD = d; best = p; }
        }
        if (!best || bestD > SNAP_THRESHOLD_M) return;

        // Visual feedback
        if (miniMapClickMarker) miniMap.removeLayer(miniMapClickMarker);
        miniMapClickMarker = L.circleMarker([best.lat, best.lon], {
            radius: 9, color: '#0dcaf0', weight: 3, fillColor: 'transparent',
        }).addTo(miniMap);

        // Seek the players to the GPS timestamp; sync the seekbar manually
        // (syncSeek already sets it but we also need updateMiniMapShuttle to
        // run even when the proximity timeline isn't visible yet)
        syncSeek(best.ts);
        updateMiniMapShuttle(best.ts);
        updatePassInfo(best.ts);
    }

    // Update the right-panel info box to show details of the current pass
    function updatePassInfo(currentTime) {
        const box = document.getElementById('camAnalyzerPassInfo');
        if (!box || !intersectionWindows.length) {
            if (box) box.style.display = 'none';
            return;
        }
        // Find the pass whose [t_enter, t_exit] contains currentTime
        const w = intersectionWindows.find(x => x.t_enter <= currentTime && currentTime <= x.t_exit);
        if (!w) { box.style.display = 'none'; return; }

        box.style.display = '';
        // Border colour matches the pass colour for cross-reference with map +
        // seek bar markers
        if (w._color) box.style.borderLeft = `4px solid ${w._color}`;
        document.getElementById('passInfoTitle').textContent =
            `Passage #${(w._passIdx || 0) + 1} — ${w.name}`;
        document.getElementById('passInfoTime').textContent =
            `${formatTime(w.t_enter)} → ${formatTime(w.t_exit)} (closest @ ${formatTime(w.t_closest || (w.t_enter + w.t_exit) / 2)})`;
        document.getElementById('passInfoDistance').textContent =
            w.min_distance_m != null ? `Distance min : ${w.min_distance_m} m` : '';
        document.getElementById('passInfoBearing').textContent =
            w.bearing_deg != null ? `Cap entrée : ${Math.round(w.bearing_deg)}° ${bearingToCardinal(w.bearing_deg)}` : '';
    }

    // Toggle the sticky bottom bar based on whether any of its children are visible
    function updateStickyBarVisibility() {
        const sticky = document.getElementById('stickyBottomBar');
        if (!sticky) return;
        const childrenVisible = ['playbackControls', 'proximityTimeline', 'analysisProgress']
            .map(id => document.getElementById(id))
            .some(el => el && el.style.display !== 'none');
        sticky.style.display = childrenVisible ? '' : 'none';
    }

    // =========================================================================
    // Intersection windows — markers + jump dropdown
    // =========================================================================

    let intersectionWindows = [];

    function bearingToCardinal(deg) {
        if (deg === null || deg === undefined) return '';
        const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        const idx = Math.round(((deg % 360) + 360) % 360 / 45) % 8;
        return dirs[idx];
    }

    // Distinct colour for each pass — golden-angle hue rotation gives perceptually
    // separated colours regardless of N. Saturation/lightness tuned for the dark
    // theme.
    function passColor(idx, total) {
        const hue = (idx * 137.508) % 360;  // golden angle
        return `hsl(${hue.toFixed(0)}, 70%, 58%)`;
    }

    function annotateWindowsWithDirection(windows) {
        // Sort by t_enter, then group by intersection name and label sens A / sens B / ...
        // Also assign a global _passIdx by t_enter (chronological order across all
        // intersections) for display in the right-panel info box, and a unique
        // _color used by the seek-bar markers, the dropdown chips, and the map
        // highlight overlay.
        const grouped = new Map();
        windows.forEach((w, i) => {
            const key = w.name || '?';
            if (!grouped.has(key)) grouped.set(key, []);
            grouped.get(key).push({ ...w, _origIdx: i });
        });
        const annotated = new Array(windows.length);
        const labels = ['A', 'B', 'C', 'D'];
        grouped.forEach(group => {
            group.sort((a, b) => a.t_enter - b.t_enter);
            group.forEach((w, i) => {
                annotated[w._origIdx] = { ...w, _sens: labels[i] || String(i + 1) };
            });
        });
        // Global chronological index + colour
        const sortedByTime = annotated
            .map((w, i) => ({ w, i }))
            .sort((a, b) => a.w.t_enter - b.w.t_enter);
        const total = sortedByTime.length;
        sortedByTime.forEach(({ w, i }, idx) => {
            annotated[i]._passIdx = idx;
            annotated[i]._color = passColor(idx, total);
        });
        return annotated;
    }

    function renderIntersectionWindows(windows) {
        intersectionWindows = Array.isArray(windows) ? annotateWindowsWithDirection(windows) : [];

        const seekOverlay = document.getElementById('seekIntersectionMarkers');
        const tlOverlay = document.getElementById('timelineIntersectionMarkers');
        const jumpSelect = document.getElementById('intersectionJumpSelect');

        if (seekOverlay) seekOverlay.innerHTML = '';
        if (tlOverlay) tlOverlay.innerHTML = '';
        if (jumpSelect) {
            // Remove all children except the placeholder option
            while (jumpSelect.lastChild && jumpSelect.lastChild !== jumpSelect.firstChild) {
                jumpSelect.removeChild(jumpSelect.lastChild);
            }
        }

        if (!intersectionWindows.length || maxDuration <= 0) {
            if (jumpSelect) jumpSelect.style.display = 'none';
            return;
        }

        // Render markers on both timelines, each pass coloured distinctly so
        // it can be cross-referenced with the map polyline highlight and the
        // dropdown chip.
        intersectionWindows.forEach((w) => {
            const startPct = Math.max(0, Math.min(100, (w.t_enter / maxDuration) * 100));
            const widthPct = Math.max(0.3, Math.min(100 - startPct, ((w.t_exit - w.t_enter) / maxDuration) * 100));
            const color = w._color || '#ffc107';

            if (seekOverlay) {
                const m = document.createElement('div');
                m.style.cssText = `position:absolute; top:0; bottom:0; left:${startPct}%; width:${widthPct}%;
                                   background:${color}; border-radius:2px;`;
                m.title = `#${(w._passIdx || 0) + 1} ${w.name} — sens ${w._sens} — ${formatTime(w.t_enter)} → ${formatTime(w.t_exit)}`;
                seekOverlay.appendChild(m);
            }

            if (tlOverlay) {
                const m = document.createElement('div');
                m.style.cssText = `position:absolute; top:0; bottom:0; left:${startPct}%; width:${widthPct}%;
                                   border:2px solid ${color}; border-radius:3px; box-sizing:border-box;
                                   background:${color}33;`;
                m.title = `#${(w._passIdx || 0) + 1} ${w.name} — sens ${w._sens}`;
                tlOverlay.appendChild(m);
            }
        });

        // Dropdown: group by intersection name with <optgroup> for navigability
        if (jumpSelect) {
            const byName = new Map();
            intersectionWindows.forEach((w) => {
                if (!byName.has(w.name)) byName.set(w.name, []);
                byName.get(w.name).push(w);
            });

            byName.forEach((group, name) => {
                group.sort((a, b) => a.t_enter - b.t_enter);
                const og = document.createElement('optgroup');
                og.label = `${name} — ${group.length} passage${group.length > 1 ? 's' : ''}`;
                group.forEach((w, i) => {
                    const opt = document.createElement('option');
                    // Use t_closest for the seek target — feels more natural
                    // than t_enter (jumps right to the moment of pass)
                    opt.value = String(w.t_closest != null ? w.t_closest : w.t_enter);
                    const cardinal = bearingToCardinal(w.bearing_deg);
                    const bearingTxt = w.bearing_deg !== null && w.bearing_deg !== undefined
                        ? `${Math.round(w.bearing_deg)}° ${cardinal}`
                        : `sens ${w._sens}`;
                    // Coloured Unicode square as a chip prefix — matches the
                    // pass colour on the seek bar and the map highlight.
                    opt.textContent = `■ #${(w._passIdx || 0) + 1} ${bearingTxt} @ ${formatTime(w.t_enter)}`;
                    if (w._color) opt.style.color = w._color;
                    og.appendChild(opt);
                });
                jumpSelect.appendChild(og);
            });

            jumpSelect.style.display = '';
        }
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
        updateToggleAllBtn();
    }

    function updateToggleAllBtn() {
        const btn = document.getElementById('toggleAllClassesBtn');
        if (!btn) return;
        const checkboxes = document.querySelectorAll('#classCheckboxes input[type="checkbox"]');
        const allChecked = checkboxes.length > 0 && Array.from(checkboxes).every(cb => cb.checked);
        btn.innerHTML = allChecked
            ? '<i class="fas fa-square me-1"></i> Tout désélectionner'
            : '<i class="fas fa-check-square me-1"></i> Tout sélectionner';
    }

    document.getElementById('toggleAllClassesBtn')?.addEventListener('click', function () {
        const checkboxes = document.querySelectorAll('#classCheckboxes input[type="checkbox"]');
        const allChecked = Array.from(checkboxes).every(cb => cb.checked);
        checkboxes.forEach(cb => { cb.checked = !allChecked; });
        updateToggleAllBtn();
    });

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
        // When master is off, mirror the fallback checkbox so the user sees a
        // consistent state — otherwise it's hidden but still ticked, which would
        // silently re-enable SAM3 on the next save.
        if (!enabled) {
            const fallback = document.getElementById('sam3AsRoadFallback');
            if (fallback) fallback.checked = false;
        }
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
                document.getElementById('rtmapsAviImportBtn').disabled = false;
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

    // ── Mode toggle AVI / .rec ─────────────────────────────────────────────────
    document.querySelectorAll('input[name="rtmapsMode"]').forEach(radio => {
        radio.addEventListener('change', function () {
            const aviMode = document.getElementById('rtmapsAviMode');
            const recMode = document.getElementById('rtmapsRecMode');
            if (this.value === 'avi') {
                aviMode.style.display = '';
                recMode.style.display = 'none';
            } else {
                aviMode.style.display = 'none';
                recMode.style.display = '';
            }
        });
    });

    // ── Mode AVI: enable button when file selected ─────────────────────────────
    document.getElementById('rtmapsAviFile').addEventListener('change', () => {
        document.getElementById('rtmapsAviImportBtn').disabled =
            !document.getElementById('rtmapsAviFile').files.length;
    });

    document.getElementById('rtmapsAviImportBtn').addEventListener('click', async function () {
        if (!currentSessionId) return;
        const aviFile = document.getElementById('rtmapsAviFile').files[0];
        const gpsFile = document.getElementById('rtmapsAviGpsFile').files[0];
        if (!aviFile) { alert('Sélectionnez un fichier AVI quadrature'); return; }

        const form = new FormData();
        form.append('avi_file', aviFile);
        if (gpsFile) form.append('gps_csv_file', gpsFile);

        const btn = document.getElementById('rtmapsAviImportBtn');
        const progressDiv = document.getElementById('rtmapsProgress');
        btn.disabled = true;
        if (progressDiv) progressDiv.style.display = '';
        setRtmapsProgress(2, 'Envoi du fichier AVI...');

        try {
            const resp = await fetch(`${config.urls.uploadRtmaps}${currentSessionId}/rtmaps/upload-avi/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
                body: form,
            });
            const data = await resp.json();
            if (!data.success) {
                alert('Erreur: ' + (data.error || 'Inconnue'));
                btn.disabled = false;
                if (progressDiv) progressDiv.style.display = 'none';
                return;
            }
            clearInterval(rtmapsPollingTimer);
            rtmapsPollingTimer = setInterval(() => pollRtmapsStatus(), 2000);
        } catch (e) {
            console.error('[QuadratureAVI] upload error:', e);
            btn.disabled = false;
        }
    });

    // ── Mode .rec: enable button when file selected ────────────────────────────
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
                    restrict_to_intersection_windows: document.getElementById('restrictToIntersectionWindows').checked,
                    analyzed_positions: ['front', 'rear', 'left', 'right'].filter(p =>
                        document.getElementById('analyze-' + p)?.checked
                    ),
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
                // Refresh the right-panel summary + camera badges with the
                // freshly-saved profile so they don't stay stale.
                loadActiveProfile(data.profile.id);
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
            saveActiveSession(null);
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

    async function openProfileEditor() {
        populateModelDropdown();
        populateClassCheckboxes();

        // Load selected profile data into the modal
        const selectedId = profileSelect.value;
        if (selectedId) {
            try {
                const resp = await fetch(config.urls.listProfiles);
                const data = await resp.json();
                const profile = (data.profiles || []).find(p => String(p.id) === String(selectedId));
                if (!profile) {
                    console.warn('[cam_analyzer] Profile not found in listProfiles:', selectedId);
                }
                if (profile) {
                    // Report type radio
                    const rtVal = profile.report_type || 'proximity_overtaking';
                    const rtRadio = document.querySelector(`input[name="reportType"][value="${rtVal}"]`);
                    if (rtRadio) rtRadio.checked = true;
                    toggleIntersectionSection(rtVal);

                    document.getElementById('profileName').value = profile.name || '';
                    // Set model dropdown — warn if the saved path doesn't match
                    // any current option (e.g. model_registry has changed paths)
                    const modelSel = document.getElementById('profileModel');
                    modelSel.value = profile.model_path || '';
                    if (profile.model_path && modelSel.value !== profile.model_path) {
                        console.warn('[cam_analyzer] saved model_path not in dropdown:',
                            profile.model_path, '— available:',
                            Array.from(modelSel.options).map(o => o.value));
                    }
                    document.getElementById('profileTaskType').value = profile.task_type || 'detect';
                    document.getElementById('profileConfidence').value = profile.confidence;
                    document.getElementById('confidenceValue').textContent = profile.confidence;
                    document.getElementById('profileIou').value = profile.iou_threshold;
                    document.getElementById('iouValue').textContent = profile.iou_threshold;
                    document.getElementById('profileTracker').value = profile.tracker || 'botsort';

                    // Uncheck all, then check target classes
                    document.querySelectorAll('#classCheckboxes input').forEach(cb => { cb.checked = false; });
                    const targetMissing = [];
                    (profile.target_classes || []).forEach(cls => {
                        const cb = document.getElementById(`class_${cls}`);
                        if (cb) cb.checked = true; else targetMissing.push(cls);
                    });
                    if (targetMissing.length) {
                        console.warn('[cam_analyzer] target classes without matching checkbox:', targetMissing);
                    }
                    updateToggleAllBtn();

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

                    // Restrict analysis to intersection windows (default true)
                    document.getElementById('restrictToIntersectionWindows').checked =
                        profile.restrict_to_intersection_windows !== false;

                    // Analysed positions (default front + rear)
                    const analyzed = Array.isArray(profile.analyzed_positions) && profile.analyzed_positions.length
                        ? profile.analyzed_positions : ['front', 'rear'];
                    ['front', 'rear', 'left', 'right'].forEach(p => {
                        const cb = document.getElementById('analyze-' + p);
                        if (cb) cb.checked = analyzed.includes(p);
                    });
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

            // Restrict to intersection windows — default ON
            document.getElementById('restrictToIntersectionWindows').checked = true;

            // Analysed positions — default front + rear
            ['front', 'rear', 'left', 'right'].forEach(p => {
                const cb = document.getElementById('analyze-' + p);
                if (cb) cb.checked = (p === 'front' || p === 'rear');
            });
        }

        profileModal.show();
    }

    editProfileBtn.addEventListener('click', openProfileEditor);

    document.getElementById('saveProfileBtn').addEventListener('click', saveProfile);

    refreshSessionsBtn.addEventListener('click', loadSessions);

    closeResultsBtn.addEventListener('click', hideResults);

    // Profile assignment: when profile changes, update session + refresh badge + RTMaps panel
    profileSelect.addEventListener('change', async () => {
        // Update badge immediately from option data-attribute
        const selectedOpt = profileSelect.options[profileSelect.selectedIndex];
        setReportTypeBadge(selectedOpt ? selectedOpt.dataset.reportType : null);
        updateRtmapsPanel();
        loadActiveProfile(profileSelect.value || null);

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
    setupRightPanelExports();

    // Restore the previously active session from localStorage (per user) so a
    // page refresh (F5) keeps the user where they were.
    (async () => {
        await loadSessions();
        const storedId = loadActiveSessionId();
        if (storedId) {
            // Only restore if the session still exists in the dropdown — handles
            // sessions deleted from another tab.
            const found = Array.from(sessionSelect.options).some(o => o.value === storedId);
            if (found) {
                loadSession(storedId);
            } else {
                saveActiveSession(null);
            }
        }
    })();
});
