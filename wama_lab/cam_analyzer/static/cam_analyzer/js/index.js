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
    let showAllSegments = false;   // false = masquer les segments of_interest=false (non pertinents)
    // Usagers de la route : seule cette famille est affichée (répartition) et
    // dessinée en overlay par défaut ; le reste (faux positifs COCO, masques) est écarté.
    const ROAD_USER_CLASSES = new Set(['person', 'bicycle', 'car', 'motorcycle', 'bus', 'truck']);
    // Classes visibles en overlay : usagers de la route dès le départ (filtre actif
    // avant même le chargement du rapport). La légende du camembert l'ajuste ensuite.
    let overlayVisibleClasses = new Set(ROAD_USER_CLASSES);
    let overlayMinConf = 0;          // filtre de confiance à l'AFFICHAGE (sans ré-analyse)
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
    let lastSam3TestOverlay = null;  // { time, res } — overlay du dernier 🔬 Test SAM3 (persistant)
    let lastRoadMask = {};           // position → derniers road_mask connus (overlay route persistant)
    let gpsTimeOffset = 0;           // recalage GPS↔vidéo (s) : ts_gps = t*scale + offset
    let gpsTimeScale = 1;            // échelle temps vidéo→réel (corrige fps AVI erroné)
    let laneWidthM = 3.5;            // largeur de voie (m) pour le gabarit vue de dessus
    let miniMapLaneLayer = null;     // calque du gabarit de voie
    let topDown360 = false;          // fusion multi-caméra dans le repère véhicule (toggle)
    // Orientation de montage de chaque caméra (deg, sens horaire depuis l'avant véhicule).
    // Rig 360° ~90° ; ajustable ensuite (les caméras ne sont pas exactement à 90°).
    const CAMERA_YAW = { front: 0, right: 90, rear: 180, left: -90 };
    let TOPDOWN_FOV_V_DEG = 60;      // FOV vertical caméra (deg) pour le cap pinhole (ajustable)
    let _lastTimeSave = 0;           // throttle de la persistance de position timeline
    let _restoreTargetTime = 0;      // position timeline à restaurer (capturée avant reset)
    let _savedMinimapZoom = null;    // zoom mini-carte sauvegardé (persistance)
    let _zoomRestored = false;       // zoom déjà restauré (une seule fois)
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

    // Double-click any camera tile to toggle fullscreen on its drop-zone (so
    // the detection canvas overlay tags along). Wired once at boot — drop-zones
    // are static in the template.
    positions.forEach(pos => {
        const zone = document.getElementById(`dropzone-${pos}`);
        if (!zone) return;
        zone.addEventListener('dblclick', (e) => {
            // Ignore double-clicks on overlay buttons (remove camera, etc.)
            if (e.target.closest('button')) return;
            const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
            if (fsEl) {
                (document.exitFullscreen || document.webkitExitFullscreen).call(document);
            } else {
                (zone.requestFullscreen || zone.webkitRequestFullscreen).call(zone);
            }
        });
    });

    // When entering fullscreen, move the playback controls bar inside the
    // fullscreen element so play/pause/seek/frame-step are reachable. On exit,
    // restore them to their original parent. We also flip a flag so the rAF
    // sync loop keeps the canvas overlays redrawing.
    let _playbackOriginalParent = null;
    let _playbackOriginalNextSibling = null;
    document.addEventListener('fullscreenchange', () => {
        const fsEl = document.fullscreenElement;
        const controls = document.getElementById('playbackControls');
        if (!controls) return;
        if (fsEl && fsEl.classList.contains('camera-drop-zone')) {
            _playbackOriginalParent = controls.parentElement;
            _playbackOriginalNextSibling = controls.nextElementSibling;
            controls.classList.add('playback-controls-fs');
            fsEl.appendChild(controls);
            controls.style.display = 'block';
        } else if (_playbackOriginalParent) {
            controls.classList.remove('playback-controls-fs');
            if (_playbackOriginalNextSibling) {
                _playbackOriginalParent.insertBefore(controls, _playbackOriginalNextSibling);
            } else {
                _playbackOriginalParent.appendChild(controls);
            }
            _playbackOriginalParent = null;
            _playbackOriginalNextSibling = null;
        }
    });

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
                                        <button class="btn btn-outline-secondary rename-session-btn" data-id="${s.id}" data-name="${escapeHtml(s.name).replace(/"/g, '&quot;')}" title="Renommer">
                                            <i class="fas fa-pen"></i>
                                        </button>
                                        <button class="btn btn-outline-warning duplicate-session-btn" data-id="${s.id}" title="Dupliquer (copie de test — vidéos partagées, aucune ré-analyse)">
                                            <i class="fas fa-copy"></i>
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
        sessionsContainer.querySelectorAll('.rename-session-btn').forEach(btn => {
            btn.addEventListener('click', () => renameSession(btn.dataset.id, btn.dataset.name));
        });
        sessionsContainer.querySelectorAll('.duplicate-session-btn').forEach(btn => {
            btn.addEventListener('click', () => duplicateSession(btn.dataset.id));
        });
    }

    async function duplicateSession(sessionId) {
        if (!confirm('Dupliquer cette session à l\'identique ?\n\nLa copie partage les vidéos source (aucune ré-analyse) — idéale pour tester/debug sans risquer l\'original.')) return;
        try {
            const resp = await fetch(`${config.urls.deleteSession}${sessionId}/duplicate/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });
            const d = await resp.json();
            if (d.success) {
                loadSessions();
                alert(`Session dupliquée : « ${d.name} ».`);
            } else {
                alert('Échec de la duplication : ' + (d.error || '?'));
            }
        } catch (e) {
            alert('Échec de la duplication : ' + e.message);
        }
    }

    async function renameSession(sessionId, currentName) {
        const name = prompt('Nouveau nom de la session :', currentName || '');
        if (name === null) return;                 // annulé
        const trimmed = name.trim();
        if (!trimmed || trimmed === currentName) return;
        try {
            const form = new FormData();
            form.append('name', trimmed);
            const resp = await fetch(`${config.urls.updateSession}${sessionId}/update/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
                body: form,
            });
            const data = await resp.json();
            if (data.success) {
                loadSessions();   // rafraîchit le tableau ET le menu déroulant
            } else {
                alert('Échec du renommage : ' + (data.error || 'inconnu'));
            }
        } catch (e) {
            alert('Échec du renommage : ' + e.message);
        }
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
                refreshRightPanelActionState();
                loadPipelinePanel();
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
            // Capturer la position timeline sauvegardée TÔT : le setup appelle syncStop()
            // → syncSeek(0) → saveTime(0) qui écraserait la valeur avant le restore.
            try {
                _restoreTargetTime = parseFloat(localStorage.getItem('cam_analyzer_time_' + sessionId) || '0') || 0;
            } catch (e) { _restoreTargetTime = 0; }
            saveActiveSession(sessionId);
            sessionSelect.value = sessionId;
            deleteSessionBtn.disabled = false;
            startAnalysisBtn.disabled = false;
            updateRtmapsPanel();

            // Clear and restore cameras
            clearCameraGrid();
            cameras = {};
            lastRoadMask = {};   // reset overlay route persistant (nouvelle session)

            // Chaque étape non-critique est isolée : son échec ne doit JAMAIS empêcher
            // l'affichage du rapport (le vrai objectif). `_safe` avale + logue.
            const _safe = (label, fn) => { try { fn(); } catch (e) { console.error('[loadSession] ' + label, e); } };

            if (data.cameras) {
                data.cameras.forEach(cam => {
                    cameras[cam.position] = cam;
                    _safe('showCameraVideo:' + cam.position, () => showCameraVideo(cam.position, cam.video_url, cam));
                });
            }

            // Offset de synchro GPS↔vidéo (recalage manuel par session).
            gpsTimeOffset = data.gps_time_offset || 0;
            gpsTimeScale = data.gps_time_scale || 1;
            // Largeur de voie : override manuel (par session) > auto-estimée > défaut 3,5m.
            let _lwManual = null;
            try { _lwManual = localStorage.getItem('cam_analyzer_lane_width_' + sessionId); } catch (e) { /* noop */ }
            laneWidthM = _lwManual ? (parseFloat(_lwManual) || 3.5)
                : (data.lane_width_m && data.lane_width_m > 0 ? data.lane_width_m : 3.5);
            const _lws = document.getElementById('laneWidthSlider');
            if (_lws) _lws.value = laneWidthM;
            const _lwv = document.getElementById('laneWidthVal');
            if (_lwv) _lwv.textContent = laneWidthM.toFixed(1) + 'm';
            const _goi = document.getElementById('gpsOffsetInput');
            if (_goi) _goi.value = gpsTimeOffset;
            const _gos = document.getElementById('gpsOffsetSlider');
            if (_gos) _gos.value = gpsTimeOffset;

            // Set profile + update report type badge + active-profile context
            _safe('profile', () => {
                if (data.profile_id) {
                    profileSelect.value = data.profile_id;
                    const selectedOpt = profileSelect.options[profileSelect.selectedIndex];
                    setReportTypeBadge(selectedOpt ? selectedOpt.dataset.reportType : null);
                    loadActiveProfile(data.profile_id);
                } else {
                    setReportTypeBadge(null);
                    loadActiveProfile(null);
                }
            });

            // Right-panel exports enabled only when analysis has finished
            _safe('exports', () => setRightPanelExportsEnabled(data.status === 'completed'));
            // Pipeline des passes (analyse incrémentale) : le montrer aussi au chargement.
            _safe('pipeline', () => loadPipelinePanel());
            _safe('playback', () => updatePlaybackControls());
            _safe('windows', () => renderIntersectionWindows(data.intersection_windows || []));
            // Mini-carte : trajectoire + intersections + navette (Leaflet, peut throw).
            _safe('minimap', () => renderMiniMap(data.gps_track || [], data.intersection_windows || []));

            // Check session status and react — s'exécute TOUJOURS (rapport garanti).
            if (data.status === 'processing' || data.status === 'pending') {
                setAnalysisUI(true);
                showResults(data.results_summary);  // dernier rapport généré, consultable pendant l'analyse
                startStatusPolling(sessionId);
            } else if (data.status === 'failed' && data.error_message) {
                showResults(null);
                alert('Dernière analyse échouée: ' + data.error_message);
            } else {
                // completed / paused / cancelled (+ completed sans résumé) : afficher
                // le rapport PARTIEL + détections depuis la BDD (données conservées).
                // showResults charge l'analytics même sans results_summary.
                showResults(data.results_summary);
                loadAllDetections(sessionId);
                setRightPanelExportsEnabled(data.status === 'completed' || data.status === 'paused');
            }
        } catch (e) {
            // Ne plus avaler silencieusement : un throw ici laissait l'UI en état
            // partiel (tuiles au placeholder « import ») + pas de rapport.
            console.error('Error loading session:', e);
            alert('Erreur au chargement de la session : ' + (e && e.message ? e.message : e)
                + '\n(détails dans la console F12)');
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
        // Restaurer la position timeline QUAND la vidéo front est réellement seekable
        // (le restore dans setup s'exécutait trop tôt → la timeline repartait à 0).
        if (position === 'front') {
            video.addEventListener('loadeddata', () => {
                try {
                    // Utiliser la valeur capturée TÔT (avant que syncStop→saveTime(0) l'écrase).
                    const t = _restoreTargetTime || 0;
                    if (t > 0) syncSeek(t);
                } catch (e) { /* noop */ }
            }, { once: true });
        }
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

    // ── Pipeline panel ───────────────────────────────────────────────────
    // Renders the AnalysisPass list with status icons and 2 main CTAs.
    // Called after loadSession + after any pass-changing operation.
    const STATUS_ICONS = {
        completed: '<i class="fas fa-check-circle text-success"></i>',
        running:   '<i class="fas fa-spinner fa-spin text-info"></i>',
        stale:     '<i class="fas fa-exclamation-triangle text-warning"></i>',
        failed:    '<i class="fas fa-times-circle text-danger"></i>',
        pending:   '<i class="far fa-circle text-secondary"></i>',
        never:     '<i class="far fa-circle text-secondary"></i>',
    };
    const STATUS_LABELS = {
        completed: 'OK',
        running:   'En cours',
        stale:     'Périmé',
        failed:    'Échec',
        pending:   'En attente',
        never:     'Jamais',
    };

    function _formatPassTooltip(p) {
        const lines = [`État : ${STATUS_LABELS[p.status] || p.status}`];
        if (p.completed_at) lines.push(`Terminé : ${new Date(p.completed_at).toLocaleString()}`);
        if (p.duration_s != null) lines.push(`Durée : ${p.duration_s.toFixed(1)} s`);
        if (p.error_message) lines.push(`Erreur : ${p.error_message.slice(0, 200)}`);
        const summary = p.output_summary || {};
        if (summary.cameras) lines.push(`Caméras : ${summary.cameras.join(', ')}`);
        if (summary.detections_total != null) lines.push(`Détections : ${summary.detections_total}`);
        if (summary.count != null) lines.push(`Nombre : ${summary.count}`);
        if (summary.events_count != null) lines.push(`Évènements : ${summary.events_count}`);
        if (summary.scanned != null) lines.push(`Frames analysées : ${summary.scanned}`);
        const params = p.parameters || {};
        const watched = Object.keys(params);
        if (watched.length) {
            lines.push('Paramètres watch :');
            for (const k of watched) {
                const v = params[k];
                lines.push(`  ${k} = ${typeof v === 'object' ? JSON.stringify(v).slice(0, 60) : v}`);
            }
        }
        return lines.join('\n');
    }

    async function loadPipelinePanel() {
        const panel = document.getElementById('camAnalyzerPipelinePanel');
        if (!panel) return;
        if (!currentSessionId) {
            panel.innerHTML = '<div class="text-secondary">Sélectionnez une session.</div>';
            return;
        }
        try {
            const resp = await fetch(`${config.urls.listPasses}${currentSessionId}/passes/`);
            const data = await resp.json();
            const rows = (data.passes || []).map(p => {
                const icon = STATUS_ICONS[p.status] || STATUS_ICONS.never;
                const tip = _formatPassTooltip(p).replace(/"/g, '&quot;');
                // Per-camera passes get a "[front]" / "[rear]" suffix (Prop A)
                const camSuffix = p.camera ? ` <span class="text-secondary" style="font-size:0.7rem;">[${p.camera}]</span>` : '';
                // The button payload includes camera for per-camera passes
                const dataPayload = p.camera
                    ? `data-rp-run="${p.pass_type}" data-rp-camera="${p.camera}"`
                    : `data-rp-run="${p.pass_type}"`;
                return `
                    <div class="d-flex align-items-center gap-2 py-1" title="${tip}">
                        <span style="width:16px;text-align:center">${icon}</span>
                        <span class="flex-grow-1 text-light" style="font-size:0.78rem;">${escapeHtml(p.label)}${camSuffix}</span>
                        <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-1"
                                ${dataPayload} title="Lancer ce passage seul"
                                style="font-size:0.7rem;">▶</button>
                    </div>`;
            }).join('');
            panel.innerHTML = `
                ${rows || '<div class="text-secondary">Aucun passage enregistré.</div>'}
                <div class="d-grid gap-1 mt-2">
                    <button type="button" class="btn btn-sm btn-success" id="rpRunMissingBtn">
                        <i class="fas fa-play me-1"></i>Compléter (manquant + périmé)
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-warning" id="rpRunAllBtn">
                        <i class="fas fa-redo me-1"></i>Tout relancer (force)
                    </button>
                    <button type="button" class="btn btn-sm btn-outline-info" id="rpLoadPartialBtn"
                            title="Charge les détections actuellement en DB (utile pendant une analyse en cours ou après annulation)">
                        <i class="fas fa-eye me-1"></i>Afficher détections actuelles
                    </button>
                </div>`;
            document.getElementById('rpRunMissingBtn')?.addEventListener('click', () => runPasses([], false));
            document.getElementById('rpRunAllBtn')?.addEventListener('click', () => {
                if (confirm('Relancer toutes les passes en force ? Cela écrase les résultats existants.')) {
                    runPasses([], true);
                }
            });
            // Proposition E — load partial detections at any time (running, paused, completed)
            document.getElementById('rpLoadPartialBtn')?.addEventListener('click', () => {
                loadAllDetections(currentSessionId);
                setRightPanelExportsEnabled(true);
            });
            panel.querySelectorAll('[data-rp-run]').forEach(btn => {
                btn.addEventListener('click', () => runPasses([btn.dataset.rpRun], false));
            });
        } catch (e) {
            console.error('loadPipelinePanel:', e);
            panel.innerHTML = '<div class="text-danger small">Erreur de chargement</div>';
        }
    }

    async function runPasses(types, force) {
        if (!currentSessionId) return;
        try {
            const resp = await fetch(`${config.urls.runPasses}${currentSessionId}/passes/run/`, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': config.csrfToken,
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({ types, force }),
            });
            const data = await resp.json();
            if (!data.success) {
                alert('Erreur: ' + (data.error || 'lancement échoué'));
                return;
            }
            // If a Celery task was launched, switch to the running UI + start polling
            if ((data.launched || []).some(t => t.endsWith('_task'))) {
                setAnalysisUI(true);
                startStatusPolling(currentSessionId);
            }
            await loadPipelinePanel();
        } catch (e) {
            console.error('runPasses:', e);
            alert('Erreur réseau');
        }
    }

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
            refreshSam3OnlyButton();
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
        // Le filtre d'AFFICHAGE suit les classes cibles du profil (ID COCO → nom) : si
        // seul « car » est coché, l'overlay ne montre que les voitures — sans ré-analyse.
        if (Array.isArray(p.target_classes) && p.target_classes.length) {
            overlayVisibleClasses = new Set(p.target_classes.map(c => {
                const nm = (config.cocoClasses && config.cocoClasses[c]) || String(c);
                return String(nm).toLowerCase();
            }).filter(Boolean));
            if (typeof currentTime === 'number') updateDetectionOverlay(currentTime);
        }
        const isIntersection = p.report_type === 'intersection_insertion';
        const sam3Enabled = !!p.sam3_markings_enabled;
        summary.innerHTML = `
            <div class="d-flex flex-column gap-1" style="font-size: 0.78rem;">
                <div><span class="text-secondary">Nom :</span> <span class="text-light fw-semibold">${escapeHtml(p.name)}</span></div>
                <div><span class="text-secondary">Type :</span> <span class="text-light">${reportLabel}</span></div>
                <div><span class="text-secondary">Modèle :</span> <span class="text-light">${escapeHtml(modelName)}</span></div>
                <div><span class="text-secondary">Classes :</span> <span class="text-light">${escapeHtml(classes)}</span></div>
                <div><span class="text-secondary">Vues analysées :</span> <span class="text-warning">${escapeHtml(analyzed)}</span></div>
                ${isIntersection ? `
                    <div><span class="text-secondary">Intersections :</span> <span class="text-light">${intersectionsCount}</span></div>
                    <div><span class="text-secondary">Restreint aux fenêtres :</span> <span class="text-light">${p.restrict_to_intersection_windows !== false ? 'Oui' : 'Non'}</span></div>
                ` : ''}
            </div>
            <button class="btn btn-sm btn-outline-warning mt-2 w-100" id="rpEditProfileBtn">
                <i class="fas fa-cog me-1"></i>Modifier le profil
            </button>
            <hr class="my-2 border-secondary opacity-50">
            <div class="text-secondary text-uppercase mb-1" style="font-size:0.7rem; letter-spacing:0.5px;">
                Lancer une analyse
            </div>
            <button class="btn btn-sm btn-success w-100 mb-1" id="rpStartAnalysisBtn"
                    title="Détection véhicules (YOLO)${sam3Enabled ? ' + SAM3' : ''}">
                <i class="fas fa-play me-1"></i>Détection véhicules${sam3Enabled ? ' + SAM3' : ''}
            </button>
            ${sam3Enabled ? `
                <button class="btn btn-sm btn-info w-100 mb-1" id="rpStartSam3OnlyBtn"
                        title="Re-lancer SAM3 seul, sans refaire YOLO">
                    <i class="fas fa-route me-1"></i>Marquages SAM3 (seul)
                </button>
            ` : ''}
            ${isIntersection ? `
                <button class="btn btn-sm btn-outline-info w-100 mb-1" id="rpRecomputeWindowsBtn"
                        title="Recalcule les fenêtres d'intersection à partir du profil — sans refaire l'analyse">
                    <i class="fas fa-sync-alt me-1"></i>Recalculer fenêtres
                </button>
            ` : ''}
            <button class="btn btn-sm btn-danger w-100" id="rpCancelAnalysisBtn" style="display:none">
                <i class="fas fa-stop me-1"></i>Annuler l'analyse
            </button>
        `;
        const btn = document.getElementById('rpEditProfileBtn');
        if (btn) btn.addEventListener('click', () => {
            // Call the editor opener directly rather than synthetically clicking
            // the toolbar button — avoids any synthetic-event quirk and the
            // function is identical for both entry points.
            openProfileEditor();
        });
        const recomputeBtn = document.getElementById('rpRecomputeWindowsBtn');
        if (recomputeBtn) recomputeBtn.addEventListener('click', recomputeWindows);
        const rpStart = document.getElementById('rpStartAnalysisBtn');
        if (rpStart) rpStart.addEventListener('click', startAnalysis);
        const rpSam3 = document.getElementById('rpStartSam3OnlyBtn');
        if (rpSam3) rpSam3.addEventListener('click', startSam3Only);
        const rpCancel = document.getElementById('rpCancelAnalysisBtn');
        if (rpCancel) rpCancel.addEventListener('click', cancelAnalysis);
        // Sync visibility/enabled state with the toolbar twin buttons.
        refreshRightPanelActionState();
    }

    async function recomputeWindows() {
        if (!currentSessionId) return;
        const btn = document.getElementById('rpRecomputeWindowsBtn');
        const oldHTML = btn ? btn.innerHTML : null;
        if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Recalcul...';
        }
        try {
            const url = `${config.urls.recomputeWindows}${currentSessionId}/recompute-windows/`;
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });
            const data = await resp.json();
            if (!data.success) {
                alert('Erreur: ' + (data.error || 'Recalcul échoué'));
                return;
            }
            // Re-render windows everywhere — dropdown, seek-bar markers, mini-map.
            const windows = data.intersection_windows || [];
            renderIntersectionWindows(windows);
            renderMiniMap(cachedGpsTrack || [], windows);
        } catch (e) {
            console.error('recomputeWindows failed:', e);
            alert('Erreur réseau lors du recalcul');
        } finally {
            if (btn) {
                btn.disabled = false;
                if (oldHTML) btn.innerHTML = oldHTML;
            }
        }
    }

    async function startSam3Only() {
        if (!currentSessionId) return;
        if (!confirm('Lancer SAM3 seul ? La détection YOLO existante sera conservée.')) return;
        try {
            const url = `${config.urls.startSam3Only}${currentSessionId}/start-sam3/`;
            const resp = await fetch(url, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });
            const data = await resp.json();
            if (!data.success) {
                alert('Erreur: ' + (data.error || 'Lancement SAM3 échoué'));
                return;
            }
            setAnalysisUI(true);
            startStatusPolling(currentSessionId);
        } catch (e) {
            console.error('startSam3Only failed:', e);
            alert('Erreur réseau lors du lancement SAM3');
        }
    }

    // Show the SAM3-only button when the active profile has SAM3 enabled and
    // the session is in a state where re-running SAM3 makes sense (i.e. not
    // currently processing). Called after loadActiveProfile + setAnalysisUI.
    function refreshSam3OnlyButton() {
        const btn = document.getElementById('startSam3OnlyBtn');
        if (!btn) return;
        const sam3Enabled = activeProfile && activeProfile.sam3_markings_enabled;
        const running = startAnalysisBtn.style.display === 'none'
                        && cancelAnalysisBtn.style.display !== 'none';
        const sessionReady = !!currentSessionId;
        if (sam3Enabled && sessionReady && !running) {
            btn.style.display = '';
            btn.disabled = false;
        } else if (sam3Enabled && running) {
            btn.style.display = 'none';
        } else {
            btn.style.display = 'none';
        }
    }

    // Mirror toolbar state on the right-panel action buttons. The buttons
    // exist in two places (toolbar + right panel) so the user can launch from
    // wherever their attention is; this keeps both in sync.
    function refreshRightPanelActionState() {
        const start = document.getElementById('rpStartAnalysisBtn');
        const sam3 = document.getElementById('rpStartSam3OnlyBtn');
        const recompute = document.getElementById('rpRecomputeWindowsBtn');
        const cancel = document.getElementById('rpCancelAnalysisBtn');
        if (!start) return;  // panel summary not rendered yet

        const running = startAnalysisBtn.style.display === 'none'
                        && cancelAnalysisBtn.style.display !== 'none';
        const sessionReady = !!currentSessionId;
        const sam3Enabled = activeProfile && activeProfile.sam3_markings_enabled;

        // Disable both YOLO + SAM3 launchers while a job is running, and the
        // recompute button (it'd touch the windows the running task reads).
        start.disabled = !sessionReady || running || startAnalysisBtn.disabled;
        if (sam3) sam3.disabled = !sessionReady || running;
        if (recompute) recompute.disabled = !sessionReady || running;

        if (cancel) cancel.style.display = running ? '' : 'none';
        // Hide the launchers while running so the cancel CTA is unambiguous.
        start.style.display = running ? 'none' : '';
        if (sam3) sam3.style.display = running ? 'none' : '';
    }

    // (escapeHtml is defined later — same scope, no conflict at call time)

    // Right-panel quick exports — wired to the same URLs used by the main results panel
    function setupRightPanelExports() {
        const map = [
            ['rpExportCsvBtn', () => exportDetectionsCsv()],
            ['rpExportJsonBtn', () => exportSessionJson()],
            ['rpExportSegmentsBtn', () => exportSegmentsCsv()],
            ['rpExportConflictsBtn', () => exportConflictsCsv()],
        ];
        map.forEach(([id, handler]) => {
            const btn = document.getElementById(id);
            if (btn) btn.addEventListener('click', handler);
        });
    }

    function setRightPanelExportsEnabled(enabled) {
        ['rpExportCsvBtn', 'rpExportJsonBtn', 'rpExportSegmentsBtn', 'rpExportConflictsBtn'].forEach(id => {
            const btn = document.getElementById(id);
            if (btn) btn.disabled = !enabled;
        });
    }

    function exportConflictsCsv() {
        if (!currentSessionId) return;
        window.location.href = `${config.urls.exportConflicts}${currentSessionId}/export/conflicts/`;
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
        // (Restauration de la position déplacée sur l'event 'loadeddata' de la vidéo
        // front — voir showCameraVideo — car ici la vidéo n'est pas encore seekable.)

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
            // Persister la position en lecture (throttle ~2s) pour la restaurer au refresh.
            if (Math.abs(refTime - _lastTimeSave) >= 2) { _lastTimeSave = refTime; saveTime(); }
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

    // Persiste la position timeline courante (restaurée au rafraîchissement / retour session).
    function saveTime() {
        if (!currentSessionId) return;
        try { localStorage.setItem('cam_analyzer_time_' + currentSessionId, String(parseFloat(syncSeekBar.value) || 0)); }
        catch (e) { /* noop */ }
    }

    function syncPause() {
        isPlaying = false;
        playPauseIcon.className = 'fas fa-play';
        stopRafLoop();

        positions.forEach(pos => {
            const video = document.getElementById(`video-${pos}`);
            if (video && video.src) video.pause();
        });
        saveTime();
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
        saveTime();
    }

    function updateTimeDisplay(currentTime) {
        syncTimeDisplay.textContent = `${formatTime(currentTime)} / ${formatTime(maxDuration)}`;
    }

    // setupTimeSync is kept for backward-compat but no longer attaches timeupdate
    function setupTimeSync() { /* overlays are driven by rafLoop */ }

    // ── Frame stepping + reverse playback ────────────────────────────────────
    // Browsers don't support negative HTMLVideoElement.playbackRate, so reverse
    // is emulated with a setInterval that decrements currentTime each tick.
    let reverseTimer = null;

    function _firstCamFps() {
        for (const pos of positions) {
            const v = document.getElementById(`video-${pos}`);
            if (v && v.src && cameras[pos] && cameras[pos].fps) return cameras[pos].fps;
        }
        return 30;
    }

    function frameStep(deltaFrames) {
        stopReverse();
        if (isPlaying) syncPause();
        const fps = _firstCamFps();
        const t = Math.max(0, Math.min(maxDuration || 0,
            (parseFloat(syncSeekBar.value) || 0) + deltaFrames / fps));
        syncSeek(t);
    }

    function startReverse() {
        if (reverseTimer) return;
        if (isPlaying) syncPause();
        const fps = _firstCamFps();
        const speed = parseFloat(playbackSpeed.value) || 1;
        const stepMs = 1000 / (fps * speed);
        const reverseBtn = document.getElementById('syncReverseBtn');
        if (reverseBtn) reverseBtn.classList.add('active', 'btn-warning');
        reverseTimer = setInterval(() => {
            const t = (parseFloat(syncSeekBar.value) || 0) - 1 / fps;
            if (t <= 0) { syncSeek(0); stopReverse(); return; }
            syncSeek(t);
        }, stepMs);
    }

    function stopReverse() {
        if (!reverseTimer) return;
        clearInterval(reverseTimer);
        reverseTimer = null;
        const reverseBtn = document.getElementById('syncReverseBtn');
        if (reverseBtn) reverseBtn.classList.remove('active', 'btn-warning');
    }

    function toggleReverse() {
        if (reverseTimer) stopReverse();
        else startReverse();
    }

    // Event listeners
    syncPlayPauseBtn.addEventListener('click', () => {
        stopReverse();
        if (isPlaying) syncPause();
        else syncPlay();
    });

    // Auto-download keremberke/yolov8m-bdd100k-seg from HuggingFace.
    document.getElementById('downloadRoadModelBtn')?.addEventListener('click', async (e) => {
        const btn = e.currentTarget;
        const orig = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin me-1"></i>Téléchargement...';
        try {
            const resp = await fetch(config.urls.downloadRoadModel, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken },
            });
            const data = await resp.json();
            if (data.success) {
                document.getElementById('roadModelPath').value = data.path;
                alert(data.message + '\nChemin : ' + data.path);
            } else {
                alert('Échec : ' + (data.error || 'inconnu'));
            }
        } catch (err) {
            console.error('Download failed:', err);
            alert('Erreur réseau pendant le téléchargement.');
        } finally {
            btn.disabled = false;
            btn.innerHTML = orig;
        }
    });

    document.getElementById('syncPrevFrameBtn')?.addEventListener('click', () => frameStep(-1));
    document.getElementById('syncNextFrameBtn')?.addEventListener('click', () => frameStep(1));
    document.getElementById('syncReverseBtn')?.addEventListener('click', toggleReverse);

    syncStopBtn.addEventListener('click', () => { stopReverse(); syncStop(); });

    // Keyboard shortcuts — work everywhere, including fullscreen. Skip when the
    // user is typing in a field/modal.
    // Shuttle J/K/L via la brique COMMUNE WamaShuttle (mutualisée avec le Transcriber).
    if (window.WamaShuttle) {
        const camShuttle = WamaShuttle.create({
            levels: [-4, -2, -1, 0, 0.5, 1, 1.5, 2, 4],
            enabled: () => playbackControls && playbackControls.style.display !== 'none',
            apply: (speed) => {
                if (speed === 0) { stopReverse(); syncPause(); return; }
                if (speed < 0) { syncPause(); startReverse(); return; }
                stopReverse();
                if (!isPlaying) syncPlay();
                ['front', 'rear', 'left', 'right'].forEach(p => {
                    const v = document.getElementById('video-' + p);
                    if (v) v.playbackRate = speed;
                });
            },
        });
        camShuttle.bindKeys();
    }

    document.addEventListener('keydown', (e) => {
        const target = e.target;
        if (target && (target.matches('input, textarea, select')
                       || target.isContentEditable
                       || target.closest('.modal.show'))) return;
        if (playbackControls.style.display === 'none') return;

        if (e.code === 'Space') {
            e.preventDefault();
            stopReverse();
            if (isPlaying) syncPause(); else syncPlay();
        } else if (e.code === 'ArrowLeft') {
            e.preventDefault();
            frameStep(e.shiftKey ? -10 : -1);
        } else if (e.code === 'ArrowRight') {
            e.preventDefault();
            frameStep(e.shiftKey ? 10 : 1);
        } else if (e.code === 'KeyR') {
            e.preventDefault();
            toggleReverse();
        }
        // j/k/l gérés par WamaShuttle (brique commune) ci-dessus.
    });

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
        refreshSam3OnlyButton();
        refreshRightPanelActionState();
        updateStickyBarVisibility();
    }

    function hideProgress() {
        analysisProgress.style.display = 'none';
        startAnalysisBtn.style.display = '';
        cancelAnalysisBtn.style.display = 'none';
        refreshSam3OnlyButton();
        refreshRightPanelActionState();
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
                loadPipelinePanel();
            } else if (data.status === 'paused') {
                // Proposition C — cancel maps to PAUSED. Partial data is
                // viewable ; the user can resume or just inspect what's done.
                stopStatusPolling();
                hideProgress();
                showResults(data.results_summary);  // rapport partiel (données conservées)
                loadAllDetections(sessionId);
                loadSessions();
                setRightPanelExportsEnabled(true);
                loadPipelinePanel();
            } else if (data.status === 'failed') {
                stopStatusPolling();
                hideProgress();
                alert('Analyse échouée: ' + (data.error_message || 'Erreur inconnue'));
                loadSessions();
            }
            // En cours (processing/pending) : on ne touche PAS au rapport — le dernier
            // rapport généré (results_summary du run précédent) reste affiché tel quel.
        } catch (e) {
            console.error('Error polling status:', e);
        }
    }

    // =========================================================================
    // Results Display
    // =========================================================================

    function showResults(summary) {
        if (!summary || !summary.detections_total) {
            // Résumé vide/absent (ex. analyse interrompue → detections_total=0) : NE PAS
            // masquer resultsPanel — analyticsSection est DEDANS. On montre le conteneur,
            // on vide juste le résumé, et on charge le rapport analytics (depuis la BDD).
            resultsPanel.style.display = '';
            const _rc = document.getElementById('resultsContent');
            if (_rc) _rc.innerHTML = '<div class="text-secondary small">'
                + '<i class="fas fa-info-circle me-1"></i>Résumé indisponible (analyse interrompue) — '
                + 'rapport détaillé ci-dessous.</div>';
            if (currentSessionId) loadAnalytics(currentSessionId);
            return;
        }

        const posLabels = { front: 'Avant', rear: 'Arrière', left: 'Gauche', right: 'Droite' };

        let classHtml = '';
        if (summary.by_class) {
            const entries = Object.entries(summary.by_class).sort((a, b) => b[1] - a[1]);
            // Usagers de la route = badges colorés ; le reste (faux positifs COCO,
            // masques) est replié dans une note discrète plutôt qu'affiché en vrac.
            const road = entries.filter(([cls]) => ROAD_USER_CLASSES.has(cls.toLowerCase()));
            const other = entries.filter(([cls]) => !ROAD_USER_CLASSES.has(cls.toLowerCase()));
            classHtml = road.map(([cls, count]) => {
                const color = classColors[cls] || defaultColor;
                return `<span class="badge me-1 mb-1" style="background:${color};color:#000">${cls}: ${count}</span>`;
            }).join('');
            if (other.length) {
                const otherTotal = other.reduce((s, [, n]) => s + n, 0);
                const names = other.map(([cls]) => cls).slice(0, 8).join(', ')
                    + (other.length > 8 ? '…' : '');
                classHtml += `<span class="badge me-1 mb-1 bg-dark border border-secondary text-secondary"
                    title="${names}">+${otherTotal} hors-scope (${other.length} classes)</span>`;
            }
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
        // Ré-afficher l'overlay du test SAM3 s'il correspond à la frame courante
        // (drawDetections vient d'effacer le canvas front).
        if (lastSam3TestOverlay && Math.abs(currentTime - lastSam3TestOverlay.time) < 0.35) {
            drawSam3TestMarkings(lastSam3TestOverlay.res);
        }
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

        const closest = frames[low];

        // Reject frames outside the analysis zone: only frames are stored for
        // analyzed windows, so when playback is between/outside windows the
        // nearest analyzed frame can be seconds away — drawing it freezes a
        // stale, incoherent overlay on screen. Guard with a tolerance derived
        // from the LOCAL sampling interval (robust to frame subsampling): if
        // the requested time is farther than ~1.5× the neighbour spacing, we
        // are in a gap → no overlay here. Callers treat null as "clear canvas".
        let localGap = Infinity;
        if (low > 0)                 localGap = Math.min(localGap, closest.timestamp - frames[low - 1].timestamp);
        if (low < frames.length - 1) localGap = Math.min(localGap, frames[low + 1].timestamp - closest.timestamp);
        if (!isFinite(localGap)) localGap = 0;              // single-frame dataset
        const tol = Math.max(localGap * 1.5, 0.04);         // floor absorbs fps jitter
        if (Math.abs(closest.timestamp - time) > tol) return null;

        return closest;
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

        // Persistance de l'aire roulable : si la frame courante a un road_mask, on
        // mémorise ; sinon on redessine le dernier connu (atténué, pointillés) → pas de
        // clignotement (l'aire change lentement ; road_mask parfois épars/disjoint SAM3).
        const _roadHere = (detections || []).filter(d =>
            d && d.type === 'road_mask' && Array.isArray(d.polygon) && d.polygon.length >= 3);
        const _lr = lastRoadMask[position];
        // Timing basé sur le VRAI élément vidéo (fiable), pas la variable de sync.
        const _vidEl = document.getElementById('video-' + position);
        const _now = _vidEl ? _vidEl.currentTime : 0;
        if (_roadHere.length) {
            lastRoadMask[position] = { polys: _roadHere, t: _now };
        } else if (_lr && Math.abs(_now - _lr.t) < 0.5) {
            // Persister sur un gap COURT (<0.5 s) → lisse les trous à l'intérieur des
            // fenêtres d'analyse (road_mask dense, gap 1-2 frames) sans dériver ; au-delà
            // (ex. entre 2 fenêtres) on n'affiche rien (pas de donnée = pas d'overlay faux).
            _lr.polys.forEach(d => {
                ctx.beginPath();
                d.polygon.forEach(([px, py], i) => {
                    const x = px * scaleX + offsetX, y = py * scaleY + offsetY;
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                });
                ctx.closePath();
                ctx.fillStyle = 'rgba(255, 64, 192, 0.10)';
                ctx.fill();
                ctx.setLineDash([6, 4]);
                ctx.strokeStyle = 'rgba(255, 64, 192, 0.5)';
                ctx.lineWidth = 1.2;
                ctx.stroke();
                ctx.setLineDash([]);
            });
        }

        detections.forEach(det => {
            // Segmentation en POLYGONE : road_mask (aire roulable) ET marquages SAM3
            // (qui ont aussi un bbox, mais on préfère afficher la FORME segmentée que
            // SAM3 a produite plutôt qu'une boîte). Couleur : road=magenta,
            // passage=cyan, ligne d'arrêt/autre=jaune.
            const _hasPoly = Array.isArray(det.polygon) && det.polygon.length >= 3;
            const _isRoad = det.type === 'road_mask';
            const _isSam3 = det.type === 'sam3_marking';
            if (_hasPoly && (_isRoad || _isSam3 || !Array.isArray(det.bbox))) {
                let rgb = '255, 64, 192';   // road_mask = magenta
                if (_isSam3) rgb = /cross/i.test(det.label || det.class_name || '') ? '0, 229, 255' : '255, 213, 0';
                ctx.beginPath();
                det.polygon.forEach(([px, py], i) => {
                    const x = px * scaleX + offsetX;
                    const y = py * scaleY + offsetY;
                    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
                });
                ctx.closePath();
                ctx.fillStyle = `rgba(${rgb}, 0.18)`;
                ctx.fill();
                ctx.strokeStyle = `rgba(${rgb}, 0.9)`;
                ctx.lineWidth = 1.5;
                ctx.stroke();
                // Étiquette du marquage SAM3 (au 1er sommet du polygone).
                if (_isSam3 && det.polygon[0]) {
                    const lx = det.polygon[0][0] * scaleX + offsetX;
                    const ly = det.polygon[0][1] * scaleY + offsetY;
                    const txt = `${det.label || 'marquage'} ${Math.round((det.confidence || 0) * 100)}%`;
                    ctx.font = '11px sans-serif';
                    const tw = ctx.measureText(txt).width + 6;
                    ctx.fillStyle = `rgba(${rgb}, 0.95)`;
                    ctx.fillRect(lx, ly - 14, tw, 14);
                    ctx.fillStyle = '#000';
                    ctx.fillText(txt, lx + 3, ly - 3);
                }
                return;
            }
            if (!Array.isArray(det.bbox) || det.bbox.length < 4) return;

            // Filtre overlay par classe (défaut = usagers de la route). Les
            // marquages SAM3 en sont exemptés (gérés séparément).
            if (overlayVisibleClasses && det.type !== 'sam3_marking' && det.class_name &&
                !overlayVisibleClasses.has(det.class_name.toLowerCase())) return;

            // Filtre overlay par CONFIANCE (à l'affichage, sans ré-analyse) — exempte
            // road_mask/sam3 (rendus en polygone plus haut, pas ici).
            if (overlayMinConf > 0 && det.type !== 'sam3_marking' && det.type !== 'road_mask'
                && typeof det.confidence === 'number' && det.confidence < overlayMinConf) return;

            const [x1, y1, x2, y2] = det.bbox;
            const sx = x1 * scaleX + offsetX;
            const sy = y1 * scaleY + offsetY;
            const sw = (x2 - x1) * scaleX;
            const sh = (y2 - y1) * scaleY;

            // SAM3 markings (sam3_marking) get distinct cyan/yellow colours so
            // they're visually separable from YOLO vehicle bboxes.
            const isSam3 = det.type === 'sam3_marking';
            const inShuttleLane = det.in_shuttle_lane === true;
            const color = isSam3
                ? (det.class_name && /cross/i.test(det.class_name) ? '#00ffff' : '#ffd700')
                : (classColors[det.class_name] || defaultColor);

            // Draw bbox — thicker + filled-glow for objects in the shuttle lane
            ctx.strokeStyle = color;
            ctx.lineWidth = inShuttleLane ? 3 : (isSam3 ? 1.5 : 2);
            if (isSam3) ctx.setLineDash([4, 3]);
            ctx.strokeRect(sx, sy, sw, sh);
            if (isSam3) ctx.setLineDash([]);

            // Phase 4 — show distance / speed / TTC in the label when present
            // Phase 2 — flag in_shuttle_lane with a 🚌 marker
            let label = `${det.class_name} ${(det.confidence * 100).toFixed(0)}%`;
            if (det.track_id != null) label += ` #${det.track_id}`;
            if (inShuttleLane) label += ' 🚌';
            const dist = det.distance_m;
            const ttc = det.ttc_s;
            const rspeed = det.relative_speed_kmh;
            const extras = [];
            if (typeof dist === 'number') extras.push(`${dist.toFixed(0)}m`);
            if (typeof rspeed === 'number') extras.push(`${rspeed > 0 ? '↑' : '↓'}${Math.abs(rspeed).toFixed(0)}km/h`);
            if (typeof ttc === 'number') extras.push(`TTC ${ttc.toFixed(1)}s`);
            const extrasLabel = extras.join(' · ');

            ctx.font = '11px sans-serif';
            const textWidth = ctx.measureText(label).width;
            const xtraWidth = extrasLabel ? ctx.measureText(extrasLabel).width : 0;
            const labelHeight = extrasLabel ? 30 : 16;
            ctx.fillStyle = color;
            ctx.fillRect(sx, sy - labelHeight, Math.max(textWidth, xtraWidth) + 6, labelHeight);
            ctx.fillStyle = '#000';
            ctx.fillText(label, sx + 3, sy - (extrasLabel ? 18 : 4));
            if (extrasLabel) ctx.fillText(extrasLabel, sx + 3, sy - 4);
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

    // ── Vue de dessus (couche objets sur la carte, zoom sémantique) ─────────
    let miniMapObjectLayer = null;     // marqueurs objets (X,Y → lat/lon)
    let miniMapTrailLayer = null;      // traces récentes (opacité décroissante)
    let miniMapHeadingLine = null;     // flèche de cap navette
    let miniMapEgoRect = null;         // rectangle navette à l'échelle (zoom tactique)
    const topDownTrails = new Map();   // track_id -> [[lat,lon], ...] récent
    let topDownLastTime = -999;        // détection de saut (reset traces)
    let topDownLastRender = -999;      // throttle ~10 Hz
    let topDownAutoFollow = true;      // recentrage auto en lecture (zoom tactique)
    const TOPDOWN_ZOOM_MIN = 17;       // seuil d'apparition des objets
    const TRAIL_LEN = 25;              // longueur de trace (frames)
    const EGO_LENGTH_M = 4.75, EGO_WIDTH_M = 2.11;   // Navya Autonom (défaut)

    function initMiniMap() {
        const container = document.getElementById('camAnalyzerMiniMap');
        if (!container || miniMap) return;
        if (typeof L === 'undefined') {
            console.warn('Leaflet not loaded');
            return;
        }

        miniMap = L.map(container, { zoomControl: true, attributionControl: false, maxZoom: 24 })
                   .setView([46.5, 2.3], 6);
        // CartoDB dark tiles — no Referer-based blocking (unlike tile.openstreetmap.org)
        // and matches the WAMA dark theme. Same provider as the profile editor map.
        // maxNativeZoom 19 = zoom réel des tuiles ; maxZoom 24 = overzoom (tuiles étirées,
        // un peu floues) pour ÉTALER les objets de la vue de dessus (sinon empilés à z19).
        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxNativeZoom: 19,
            maxZoom: 24,
        }).addTo(miniMap);

        // Barre d'échelle (mètres) — pour estimer les distances (ex. l'offset GPS/vidéo).
        L.control.scale({ metric: true, imperial: false, position: 'bottomright' }).addTo(miniMap);

        // Indicateur de niveau de zoom : dit si on a atteint le seuil de la vue de
        // dessus (≥ TOPDOWN_ZOOM_MIN). Répond à « le zoom atteint-il jamais 17 ? ».
        const zoomInfo = L.control({ position: 'bottomleft' });
        zoomInfo.onAdd = function () {
            const div = L.DomUtil.create('div', '');
            div.style.cssText = 'background:rgba(20,22,28,.85);color:#ddd;padding:2px 7px;'
                + 'border-radius:4px;font-size:.72rem;font-family:monospace;';
            const upd = () => {
                const z = miniMap.getZoom();
                const on = z >= TOPDOWN_ZOOM_MIN;
                div.innerHTML = 'zoom ' + z + (on ? ' · vue de dessus ✓' : ' (≥' + TOPDOWN_ZOOM_MIN + ' pour la vue de dessus)');
                div.style.color = on ? '#00e5ff' : '#ddd';
            };
            upd();
            miniMap.on('zoomend', upd);
            return div;
        };
        zoomInfo.addTo(miniMap);

        miniMap.on('click', (e) => handleMiniMapClick(e.latlng.lat, e.latlng.lng));
        // Semantic zoom : re-render la vue de dessus quand on zoome/dézoome, sinon la
        // couche objets (qui n'apparaît qu'au zoom ≥ TOPDOWN_ZOOM_MIN) ne se met à jour
        // qu'au prochain seek/lecture — l'utilisateur zoome et « rien ne se passe ».
        miniMap.on('zoomend', () => {
            try { localStorage.setItem('cam_analyzer_minimap_zoom', String(miniMap.getZoom())); } catch (e) { /* noop */ }
            if (typeof currentTime === 'number') { topDownLastRender = -999; updateMiniMapShuttle(currentTime); }
        });
        // Zoom sauvegardé (capturé une fois, appliqué après le fitBounds initial).
        try {
            const _z = parseFloat(localStorage.getItem('cam_analyzer_minimap_zoom'));
            if (!isNaN(_z)) _savedMinimapZoom = _z;
        } catch (e) { /* noop */ }
    }

    function renderMiniMap(gpsTrack, intersectionWindows) {
        initMiniMap();
        if (!miniMap) return;
        addMapControls();   // boutons Calibrer/Suivi sur la carte (pas sur le viewport)

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
        // Restaurer le niveau de zoom sauvegardé (une seule fois, après le fitBounds).
        if (_savedMinimapZoom != null && !_zoomRestored) {
            _zoomRestored = true;
            try { miniMap.setZoom(_savedMinimapZoom); } catch (e) { /* noop */ }
        }

        // Force redraw (Leaflet sometimes mis-sizes when its container was hidden)
        setTimeout(() => miniMap && miniMap.invalidateSize(), 50);
    }

    // Find the GPS point whose timestamp is closest to a given time
    function findGpsAtTime(t) {
        if (!cachedGpsTrack.length) return null;
        // ts_gps = temps_vidéo * scale + offset (scale corrige un fps AVI erroné → la
        // désync ne grandit plus ; offset = recalage constant). Voir gps_time_scale.
        t = t * gpsTimeScale + gpsTimeOffset;
        let lo = 0, hi = cachedGpsTrack.length - 1;
        while (lo < hi - 1) {
            const mid = (lo + hi) >> 1;
            if (cachedGpsTrack[mid].ts <= t) lo = mid; else hi = mid;
        }
        const a = cachedGpsTrack[lo], b = cachedGpsTrack[hi];
        // Interpolation linéaire entre les 2 fixes encadrants : le GPS est à ~1 Hz,
        // renvoyer le fixe le plus proche fait « sauter » le marqueur de ±0,5 s.
        // On interpole lat/lon pour un déplacement fluide et calé sur le temps.
        if (a === b || b.ts <= a.ts || t <= a.ts) return a;
        if (t >= b.ts) return b;
        const f = (t - a.ts) / (b.ts - a.ts);
        return { ...a, ts: t, lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f };
    }

    function updateMiniMapShuttle(currentTime) {
        if (!miniMap || !miniMapShuttleMarker || !cachedGpsTrack.length) return;
        const p = findGpsAtTime(currentTime);
        if (p) {
            miniMapShuttleMarker.setLatLng([p.lat, p.lon]);
            // Suivi : recentrer la navette à TOUT zoom (avant, le panTo était dans
            // updateTopDown, APRÈS le return early zoom<17 → pas de suivi dézoomé).
            if (topDownAutoFollow) miniMap.panTo([p.lat, p.lon], { animate: false });
        }
        updateMiniMapPassHighlight(currentTime);
        updateTopDown(currentTime);
    }

    // ── Vue de dessus : objets (X,Y) égo → lat/lon sur la carte ──────────────
    // Position d'un objet dans le monde depuis sa position égo (X latéral droite+,
    // Y longitudinal avant+) et la pose navette (lat/lon + cap depuis le Nord, CW).
    function egoToLatLon(lat, lon, headingDeg, X, Y) {
        const h = headingDeg * Math.PI / 180;
        const east = Y * Math.sin(h) + X * Math.cos(h);     // avant·sin + droite·cos
        const north = Y * Math.cos(h) - X * Math.sin(h);
        const dLat = north / 111320;
        const dLon = east / (111320 * Math.cos(lat * Math.PI / 180));
        return [lat + dLat, lon + dLon];
    }

    // Couleur en paliers selon TTC (sinon distance) : vert/orange/rouge.
    function ttcColor(det) {
        const ttc = det.ttc_s;
        if (ttc != null && ttc >= 0) return ttc < 2 ? '#dc3545' : (ttc < 4 ? '#fd7e14' : '#28a745');
        const d = det.dist_euclid_m;
        if (d != null) return d < 5 ? '#dc3545' : (d < 12 ? '#fd7e14' : '#28a745');
        return '#0dcaf0';
    }

    // Cap navette : flèche (tous zooms) + rectangle à l'échelle (zoom tactique).
    function updateEgoShape(pose) {
        if (miniMapHeadingLine) { miniMap.removeLayer(miniMapHeadingLine); miniMapHeadingLine = null; }
        if (miniMapEgoRect) { miniMap.removeLayer(miniMapEgoRect); miniMapEgoRect = null; }
        if (!pose || pose.heading == null) return;
        const tip = egoToLatLon(pose.lat, pose.lon, pose.heading, 0, 6);
        miniMapHeadingLine = L.polyline([[pose.lat, pose.lon], tip],
            { color: '#ffd400', weight: 3, opacity: 0.9 }).addTo(miniMap);
        if (miniMap.getZoom() >= TOPDOWN_ZOOM_MIN) {
            const hw = EGO_WIDTH_M / 2, half = EGO_LENGTH_M / 2;
            const corners = [[-hw, -half], [hw, -half], [hw, half], [-hw, half]]
                .map(([x, y]) => egoToLatLon(pose.lat, pose.lon, pose.heading, x, y));
            miniMapEgoRect = L.polygon(corners,
                { color: '#ffd400', weight: 1.5, fillOpacity: 0.15 }).addTo(miniMap);
        }
    }

    function updateTopDown(currentTime) {
        if (!miniMap || typeof L === 'undefined') return;
        // Throttle ~10 Hz (le marqueur navette reste fluide à 60 Hz au-dessus).
        if (Math.abs(currentTime - topDownLastRender) < 0.09) return;
        topDownLastRender = currentTime;
        if (!miniMapObjectLayer) miniMapObjectLayer = L.layerGroup().addTo(miniMap);
        if (!miniMapTrailLayer) miniMapTrailLayer = L.layerGroup().addTo(miniMap);
        if (!miniMapLaneLayer) miniMapLaneLayer = L.layerGroup().addTo(miniMap);
        // Reset des traces sur saut temporel (seek).
        if (Math.abs(currentTime - topDownLastTime) > 1.0) topDownTrails.clear();
        topDownLastTime = currentTime;

        miniMapObjectLayer.clearLayers();
        miniMapTrailLayer.clearLayers();
        miniMapLaneLayer.clearLayers();

        const pose = findGpsAtTime(currentTime);
        updateEgoShape(pose);
        // Objets seulement en zoom tactique + pose+cap disponibles + détections front.
        const _zoomOk = miniMap.getZoom() >= TOPDOWN_ZOOM_MIN;
        if (!pose || pose.heading == null || !_zoomOk) {
            if (_zoomOk) console.warn('[topdown] rien : pose/heading GPS manquant à t=' + currentTime.toFixed(1),
                pose ? ('heading=' + pose.heading) : 'pas de fix GPS');
            return;
        }
        // Gabarit de voie. France : navette dans SA voie (droite) → ligne centrale à gauche
        // (pointillés jaunes), bords pleins. laneWidthM = largeur (auto/slider).
        const _half = laneWidthM / 2;
        const _edges = [{ x: _half, c: '#e0e0e0', d: null }, { x: -_half, c: '#ffd54f', d: '6,6' },
                        { x: -_half * 3, c: '#e0e0e0', d: null }];
        // Fenêtre de trajectoire GPS ±50 m autour de la position courante (le long du path).
        const _distM = (a, b) => {
            const dLa = (b.lat - a.lat) * 111320;
            const dLo = (b.lon - a.lon) * 111320 * Math.cos(a.lat * Math.PI / 180);
            return Math.hypot(dLa, dLo);
        };
        const _tsCur = currentTime * gpsTimeScale + gpsTimeOffset;
        const _win = [];
        if (cachedGpsTrack.length) {
            let lo = 0, hi = cachedGpsTrack.length - 1;
            while (lo < hi - 1) { const m = (lo + hi) >> 1; if (cachedGpsTrack[m].ts <= _tsCur) lo = m; else hi = m; }
            _win.push(cachedGpsTrack[lo]);
            let acc = 0;
            for (let i = lo + 1; i < cachedGpsTrack.length && acc < 50; i++) { acc += _distM(cachedGpsTrack[i - 1], cachedGpsTrack[i]); _win.push(cachedGpsTrack[i]); }
            acc = 0;
            for (let i = lo - 1; i >= 0 && acc < 50; i--) { acc += _distM(cachedGpsTrack[i + 1], cachedGpsTrack[i]); _win.unshift(cachedGpsTrack[i]); }
        }
        // OPTION 1 (traits pleins) : aligné sur la trajectoire → suit la courbe réelle.
        if (_win.length >= 2) {
            _edges.forEach(e => {
                const pts = _win.filter(p => p.heading != null).map(p => egoToLatLon(p.lat, p.lon, p.heading, e.x, 0));
                if (pts.length >= 2) L.polyline(pts, { color: e.c, weight: 1.5, opacity: 0.85, dashArray: e.d }).addTo(miniMapLaneLayer);
            });
        }
        // OPTION 2 (pointillés fins atténués) : droit le long du cap LISSÉ, ±25 m → confrontation.
        let _sh = pose.heading, _sx = 0, _sy = 0;
        _win.forEach(p => { if (p.heading != null) { _sx += Math.cos(p.heading * Math.PI / 180); _sy += Math.sin(p.heading * Math.PI / 180); } });
        if (_sx || _sy) _sh = Math.atan2(_sy, _sx) * 180 / Math.PI;
        _edges.forEach(e => {
            const pts = [];
            for (let y = -25; y <= 25; y += 5) pts.push(egoToLatLon(pose.lat, pose.lon, _sh, e.x, y));
            L.polyline(pts, { color: e.c, weight: 1, opacity: 0.35, dashArray: '2,6' }).addTo(miniMapLaneLayer);
        });

        // Objets : mode "avant seul" (existant) OU "fusion 360°" (toutes les caméras
        // ramenées dans le repère VÉHICULE via l'orientation de chaque caméra). Togglable
        // (topDown360) à tout moment — le mode existant reste intact.
        const seen = new Set();
        const _camToVeh = (cx, cy, yawDeg) => {   // cam(latéral droite, avant) → véhicule(droite, avant)
            const t = yawDeg * Math.PI / 180, s = Math.sin(t), c = Math.cos(t);
            return [cy * s + cx * c, cy * c - cx * s];
        };
        const _drawCam = (camPos, yawDeg) => {
            const dd = detectionData[camPos];
            if (!dd || !dd.frames || !dd.frames.length) return;
            const camOff = (cameras[camPos] && cameras[camPos].time_offset) || 0;
            const fr = findClosestFrame(dd.frames, currentTime + camOff);
            if (!fr || !fr.detections) return;
            const vid = document.getElementById('video-' + camPos);
            const iw = (vid && vid.videoWidth) || 384;
            const ih = (vid && vid.videoHeight) || 288;
            const focal = ih / (2 * Math.tan(TOPDOWN_FOV_V_DEG * Math.PI / 360));  // px (pixels carrés)
            fr.detections.forEach(det => {
                if (det.type === 'road_mask' || det.type === 'sam3_marking') return;
                // POSITION reconstruite depuis le PINHOLE (précis + centré), pas l'homographie
                // (qui COMPRIME la distance ×3-4 ET la biaise latéralement de ~1,5m → objets
                // de gauche projetés à droite). X = distance·(centre_bbox−centre_image)/focale ;
                // Y = distance. Centré (objet au centre image = latéral 0) et à la bonne distance.
                let g;
                if (det.distance_m != null && Array.isArray(det.bbox)) {
                    const bcx = (det.bbox[0] + det.bbox[2]) / 2;
                    g = [det.distance_m * (bcx - iw / 2) / focal, det.distance_m];
                } else {
                    g = det.ground_xy;
                    if (!Array.isArray(g) || g.length < 2) return;
                }
                if (g[1] <= 0 || g[1] > 60 || Math.abs(g[0]) > 25) return;          // zone fiable
                const bb = det.bbox;
                if (Array.isArray(bb) && (bb[0] <= 8 || bb[2] >= iw - 8)) return;   // coupé/partiel au bord
                const v = _camToVeh(g[0], g[1], yawDeg);          // → repère véhicule commun
                const ll = egoToLatLon(pose.lat, pose.lon, pose.heading, v[0], v[1]);
                const color = ttcColor(det);
                const tkey = camPos + ':' + det.track_id;
                if (det.track_id != null) {
                    seen.add(tkey);
                    const tr = topDownTrails.get(tkey) || [];
                    tr.push(ll);
                    if (tr.length > TRAIL_LEN) tr.shift();
                    topDownTrails.set(tkey, tr);
                    for (let i = 1; i < tr.length; i++)
                        L.polyline([tr[i - 1], tr[i]],
                            { color, weight: 2, opacity: 0.1 + 0.7 * (i / tr.length) }).addTo(miniMapTrailLayer);
                }
                const label = `${det.class_name || 'objet'} [${camPos}]`
                    + `${det.dist_euclid_m != null ? ' · ' + det.dist_euclid_m + ' m' : ''}`
                    + `${det.ttc_s != null ? ' · TTC ' + det.ttc_s + ' s' : ''}`;
                const sz = ({ car: [4.5, 1.8], truck: [8, 2.5], bus: [10, 2.8], person: [0.6, 0.6],
                             bicycle: [1.8, 0.6], motorcycle: [2, 0.8] })[(det.class_name || '').toLowerCase()]
                           || [1.5, 1.5];
                const hl = sz[0] / 2, hw = sz[1] / 2;
                const corners = [[v[0] - hw, v[1] - hl], [v[0] + hw, v[1] - hl],
                                 [v[0] + hw, v[1] + hl], [v[0] - hw, v[1] + hl]]
                    .map(c => egoToLatLon(pose.lat, pose.lon, pose.heading, c[0], c[1]));
                L.polygon(corners, { color: '#000', weight: 1, fillColor: color, fillOpacity: 0.75 })
                    .bindTooltip(label, { direction: 'top' }).addTo(miniMapObjectLayer);
            });
        };
        if (topDown360) Object.keys(CAMERA_YAW).forEach(cp => _drawCam(cp, CAMERA_YAW[cp]));
        else _drawCam('front', 0);
        // Purge des traces d'objets non vus cette frame (borne la mémoire).
        for (const k of topDownTrails.keys()) if (!seen.has(k)) topDownTrails.delete(k);
        // (Recentrage auto déplacé dans updateMiniMapShuttle → suivi à tout zoom.)
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

        // Ne garder que les usagers de la route (les faux positifs COCO et les
        // masques route `lane`/`drivable area` sont écartés de la répartition).
        const roadEntries = Object.entries(classData)
            .filter(([cls]) => ROAD_USER_CLASSES.has(cls.toLowerCase()))
            .sort((a, b) => b[1] - a[1]);
        const hiddenCount = Object.entries(classData)
            .filter(([cls]) => !ROAD_USER_CLASSES.has(cls.toLowerCase()))
            .reduce((s, [, n]) => s + n, 0);

        // Init des classes visibles en overlay = usagers présents (1re fois).
        if (overlayVisibleClasses === null) {
            overlayVisibleClasses = new Set(roadEntries.map(([cls]) => cls.toLowerCase()));
        }

        const labels = roadEntries.map(([cls]) => cls);
        const values = roadEntries.map(([, n]) => n);
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
                        text: 'Usagers de la route' + (hiddenCount ? `  (+${hiddenCount} hors-scope masqués)` : ''),
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
                        // La légende EST le filtre overlay : cliquer une classe la
                        // masque à la fois dans le camembert ET dans l'overlay vidéo.
                        onClick: (e, legendItem, legend) => {
                            const ci = legend.chart;
                            ci.toggleDataVisibility(legendItem.index);
                            ci.update();
                            const cls = (legendItem.text || '').toLowerCase();
                            if (overlayVisibleClasses.has(cls)) overlayVisibleClasses.delete(cls);
                            else overlayVisibleClasses.add(cls);
                            const t = parseFloat(syncSeekBar.value) || 0;
                            updateDetectionOverlay(t);
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

            // Pertinence : par défaut, on masque les segments explicitement
            // tagués of_interest=false (véhicules 'turn'/non-usagers aux
            // intersections). Les autres types (proximité, dépassement…) n'ont
            // pas ce tag et restent visibles.
            const isNoise = seg => (seg.metadata || {}).of_interest === false;
            const hiddenCount = segments.filter(isNoise).length;
            const visible = showAllSegments ? segments : segments.filter(s => !isNoise(s));

            // Barre d'en-tête : compteur + bascule "tout afficher"
            const header = `
                <div class="d-flex align-items-center gap-2 mb-2 pb-1 border-bottom border-secondary">
                    <span class="small text-light">${visible.length} véhicule(s) d'intérêt</span>
                    ${hiddenCount ? `
                    <label class="small text-secondary ms-auto mb-0" style="cursor:pointer;">
                        <input type="checkbox" id="toggleAllSegments" ${showAllSegments ? 'checked' : ''}>
                        Afficher tout (+${hiddenCount} masqué·s)
                    </label>` : ''}
                </div>`;

            // Chips t0/t1/t2 cliquables (repositionnent la timeline)
            const timeChip = (label, t, title) => (t == null) ? '' :
                `<span class="segment-tmark badge bg-dark border border-secondary me-1"
                       data-seek="${t}" title="${title}" style="cursor:pointer;">
                    ${label} ${formatTime(t)}</span>`;

            const rows = visible.map(seg => {
                const meta = seg.metadata || {};
                const isIntersection = (seg.type === 'insertion_front' || seg.type === 'intersection_stop');
                let details = '';
                if (seg.type === 'close_following') {
                    details = `Proximité max: ${((meta.max_proximity || 0) * 100).toFixed(0)}%`;
                    if (meta.dominant_class) details += ` | Classe: ${meta.dominant_class}`;
                } else if (seg.type === 'overtaking') {
                    details = `Direction: ${meta.direction === 'left_to_right' ? '→' : '←'}`;
                    if (meta.class_name) details += ` | ${meta.class_name}`;
                } else if (seg.type === 'crossing') {
                    if (meta.class_name) details = `Classe: ${meta.class_name}`;
                } else if (isIntersection) {
                    const bits = [];
                    if (meta.vehicle_class) bits.push(meta.vehicle_class);
                    if (meta.event_type) bits.push(meta.event_type === 'insertion' ? 'insertion' : 'attente');
                    if (meta.intersection_name) bits.push(meta.intersection_name);
                    details = bits.join(' | ');
                }

                const camLabel = seg.camera_position ? getPositionLabel(seg.camera_position) : '';
                const tmarks = isIntersection ? `
                    <div class="mt-1">
                        ${timeChip('t0', meta.t0, "Entrée dans la zone")}
                        ${timeChip('t1', meta.t1, "Début de mouvement / insertion")}
                        ${timeChip('t2', meta.t2, "Insertion complète")}
                    </div>` : '';

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
                        ${tmarks}
                    </div>`;
            }).join('');

            segmentsList.innerHTML = header + rows;

            // Bascule "tout afficher"
            const toggle = document.getElementById('toggleAllSegments');
            if (toggle) toggle.addEventListener('change', () => {
                showAllSegments = toggle.checked;
                loadSegments(sessionId);
            });

            // Clic ligne → seek au début ; clic chip t0/t1/t2 → seek au repère
            segmentsList.querySelectorAll('.segment-tmark').forEach(chip => {
                chip.addEventListener('click', (e) => {
                    e.stopPropagation();
                    const t = parseFloat(chip.dataset.seek);
                    if (!isNaN(t)) syncSeek(t);
                });
            });
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
                    yolopv2_all_views: document.getElementById('yolopv2AllViews')?.checked || false,
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
                loadPipelinePanel();
                // The server auto-recomputes intersection_windows for sessions
                // tied to this profile (Pass A). Re-pull the current session
                // so the mini-map circles + dropdown reflect the new radii
                // without forcing a full re-analysis.
                if (currentSessionId
                    && Array.isArray(data.recomputed_sessions)
                    && data.recomputed_sessions.includes(String(currentSessionId))) {
                    try {
                        const r = await fetch(`${config.urls.getSession}${currentSessionId}/`);
                        const sd = await r.json();
                        if (sd && sd.intersection_windows) {
                            renderIntersectionWindows(sd.intersection_windows);
                            renderMiniMap(sd.gps_track || cachedGpsTrack || [], sd.intersection_windows);
                        }
                    } catch (refreshErr) {
                        console.warn('Could not refresh session windows after profile save:', refreshErr);
                    }
                }
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

    const sam3OnlyBtn = document.getElementById('startSam3OnlyBtn');
    if (sam3OnlyBtn) sam3OnlyBtn.addEventListener('click', startSam3Only);

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
                    const _yav = document.getElementById('yolopv2AllViews');
                    if (_yav) _yav.checked = !!profile.yolopv2_all_views;

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
            const _yavD = document.getElementById('yolopv2AllViews');
            if (_yavD) _yavD.checked = false;

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
        if (!seconds || isNaN(seconds)) return '0:00:00';
        const h = Math.floor(seconds / 3600);
        const m = Math.floor((seconds % 3600) / 60);
        const s = Math.floor(seconds % 60);
        return `${h}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
    }

    // ===== Calibration homographie sol (4 coins d'un passage piéton) =========
    // Clique 4 coins d'un passage piéton sur la caméra avant → endpoint calibrate/
    // (DLT). Architecture prête pour SAM3 : seule la SOURCE des coins changerait.
    let calibMode = false;
    let calibPoints = [];   // [[frameX, frameY], ...] repère pixel caméra
    const CALIB_ORDER = ['proche-gauche', 'proche-droite', 'loin-droite', 'loin-gauche'];

    // Écran → pixel-caméra : inverse exact du letterbox « contain » de drawDetections.
    function screenToFrame(position, clientX, clientY) {
        const canvas = document.getElementById(`canvas-${position}`);
        const cam = cameras[position];
        if (!canvas || !cam) return null;
        // MÊME espace pixel que drawDetections/les bbox/l'homographie : on prend en
        // priorité detectionData[pos].width (l'espace où YOLO a tourné), sinon la caméra.
        const dd = (typeof detectionData !== 'undefined') ? detectionData[position] : null;
        const srcW = (dd && dd.width) || cam.width;
        const srcH = (dd && dd.height) || cam.height;
        if (!srcW || !srcH) return null;
        const rect = canvas.getBoundingClientRect();
        const cw = rect.width, ch = rect.height;
        const videoAR = srcW / srcH, containerAR = cw / ch;
        let drawW, drawH, offsetX, offsetY;
        if (videoAR > containerAR) { drawW = cw; drawH = cw / videoAR; offsetX = 0; offsetY = (ch - drawH) / 2; }
        else { drawH = ch; drawW = ch * videoAR; offsetX = (cw - drawW) / 2; offsetY = 0; }
        const fx = (clientX - rect.left - offsetX) / (drawW / srcW);
        const fy = (clientY - rect.top - offsetY) / (drawH / srcH);
        if (fx < 0 || fy < 0 || fx > srcW || fy > srcH) return null;   // clic dans la bande noire
        return [Math.round(fx * 10) / 10, Math.round(fy * 10) / 10];
    }

    function calibMarkerLayer() {
        const video = document.getElementById('video-front');
        if (!video || !video.parentElement) return null;
        const host = video.parentElement;
        if (getComputedStyle(host).position === 'static') host.style.position = 'relative';
        let layer = document.getElementById('calibMarkerLayer');
        if (!layer) {
            layer = document.createElement('div');
            layer.id = 'calibMarkerLayer';
            layer.style.cssText = 'position:absolute;inset:0;pointer-events:none;z-index:30;';
            host.appendChild(layer);
        }
        return layer;
    }

    function addCalibMarker(clientX, clientY, n) {
        const layer = calibMarkerLayer();
        if (!layer) return;
        const hostRect = layer.parentElement.getBoundingClientRect();
        const m = document.createElement('div');
        m.textContent = String(n);
        m.style.cssText = `position:absolute;left:${clientX - hostRect.left}px;top:${clientY - hostRect.top}px;`
            + 'transform:translate(-50%,-50%);width:18px;height:18px;border-radius:50%;background:#ffd400;'
            + 'color:#000;font:bold 11px sans-serif;display:flex;align-items:center;justify-content:center;'
            + 'border:1px solid #000;';
        layer.appendChild(m);
    }

    function clearCalibMarkers() {
        const layer = document.getElementById('calibMarkerLayer');
        if (layer) layer.innerHTML = '';
    }

    function onCalibClick(e) {
        if (!calibMode || calibPoints.length >= 4) return;
        e.preventDefault(); e.stopPropagation();
        const fp = screenToFrame('front', e.clientX, e.clientY);
        if (!fp) return;
        calibPoints.push(fp);
        addCalibMarker(e.clientX, e.clientY, calibPoints.length);
        updateCalibPanel();
    }

    function updateCalibPanel() {
        const step = document.getElementById('calibStep');
        if (step) step.textContent = calibPoints.length < 4
            ? `Clique le coin : ${CALIB_ORDER[calibPoints.length]} (${calibPoints.length}/4)`
            : '4 coins placés — saisis les dimensions puis Valider.';
        const btn = document.getElementById('calibSubmit');
        if (btn) btn.disabled = calibPoints.length !== 4;
    }

    function startCalibration() {
        if (!currentSessionId) { alert('Charge une session d\'abord.'); return; }
        if (!cameras['front']) { alert('Pas de caméra « front » dans cette session.'); return; }
        calibMode = true; calibPoints = [];
        Object.keys(cameras).forEach(p => { const v = document.getElementById(`video-${p}`); if (v) v.pause(); });
        clearCalibMarkers();
        ['canvas-front', 'video-front'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.style.cursor = 'crosshair'; el.addEventListener('click', onCalibClick, true); }
        });
        showCalibPanel();
        updateCalibPanel();
        const b = document.getElementById('calibToggleBtn'); if (b) b.innerHTML = '<i class="fas fa-times me-1"></i>Fermer';
    }

    function stopCalibration() {
        calibMode = false; calibPoints = [];
        clearCalibMarkers();
        ['canvas-front', 'video-front'].forEach(id => {
            const el = document.getElementById(id);
            if (el) { el.style.cursor = ''; el.removeEventListener('click', onCalibClick, true); }
        });
        const panel = document.getElementById('calibPanel'); if (panel) panel.remove();
        const b = document.getElementById('calibToggleBtn'); if (b) b.innerHTML = '<i class="fas fa-ruler-combined me-1"></i>Calibrer';
    }

    function showCalibPanel() {
        const old = document.getElementById('calibPanel'); if (old) old.remove();
        const panel = document.createElement('div');
        panel.id = 'calibPanel';
        panel.style.cssText = 'position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:3000;'
            + 'background:#1e1e24;color:#eee;border:1px solid #444;border-radius:8px;padding:12px 14px;'
            + 'font-size:13px;box-shadow:0 4px 16px rgba(0,0,0,.5);max-width:560px;';
        panel.innerHTML =
            '<div style="font-weight:600;margin-bottom:6px;">📐 Calibration sol — caméra avant</div>'
            + '<div id="calibStep" style="margin-bottom:8px;color:#ffd400;"></div>'
            + '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:end;">'
            + '<label>Largeur passage (m)<br><input id="calibW" type="number" step="0.1" value="4" style="width:80px"></label>'
            + '<label>Longueur (m)<br><input id="calibL" type="number" step="0.1" value="2.5" style="width:80px"></label>'
            + '<label>Dist. bord proche (m)<br><input id="calibY0" type="number" step="0.5" value="8" style="width:80px"></label>'
            + '</div>'
            + '<div style="margin-top:10px;display:flex;gap:8px;justify-content:flex-end;">'
            + '<button id="calibReset" class="btn btn-sm btn-outline-secondary">Recommencer</button>'
            + '<button id="calibCancel" class="btn btn-sm btn-outline-danger">Annuler</button>'
            + '<button id="calibSubmit" class="btn btn-sm btn-success" disabled>Valider</button>'
            + '</div>';
        document.body.appendChild(panel);
        document.getElementById('calibReset').onclick = () => { calibPoints = []; clearCalibMarkers(); updateCalibPanel(); };
        document.getElementById('calibCancel').onclick = stopCalibration;
        document.getElementById('calibSubmit').onclick = submitCalibration;
    }

    async function submitCalibration() {
        if (calibPoints.length !== 4) return;
        const body = {
            position: 'front',
            image_points: calibPoints,
            crossing_width_m: parseFloat(document.getElementById('calibW').value),
            crossing_length_m: parseFloat(document.getElementById('calibL').value),
            near_distance_m: parseFloat(document.getElementById('calibY0').value),
        };
        try {
            const resp = await fetch(`${config.urls.updateSession}${currentSessionId}/calibrate/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            const data = await resp.json();
            if (data.success) {
                const s = data.sample ? ` (bas d'image ≈ ${data.sample.ground_xy[1]} m devant)` : '';
                const rms = (data.rms_error_m != null) ? ` — erreur reprojection ${data.rms_error_m} m` : '';
                alert(`Calibration enregistrée${s}${rms}.\nRelance l'analyse pour peupler les distances géométriques.`);
                stopCalibration();
            } else {
                alert('Échec : ' + (data.error || 'inconnu'));
            }
        } catch (e) {
            alert('Échec : ' + e.message);
        }
    }

    // Boutons calibration + suivi = contrôle Leaflet SUR la mini-carte (dans le
    // corps du cam analyzer, PAS position:fixed sur le viewport — sinon ils
    // chevauchent en-tête/pied/volets de WAMA).
    function addMapControls() {
        if (!miniMap || typeof L === 'undefined') return;
        // Boutons d'ACTION (calibration, test SAM3, debug) = barre d'outils du volet
        // droit (statiques dans le template, HORS carte) → juste le câblage ici.
        const wire = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
        wire('calibToggleBtn', () => calibMode ? stopCalibration() : startCalibration());
        wire('sam3TestBtn', () => runSam3Test(false));
        wire('sam3CalibBtn', () => runSam3Test(true));
        wire('copyDebugBtn', copyDebugInfo);
        // Bascule fusion multi-caméra 360° (repère véhicule) ↔ avant seul.
        const _tdb = document.getElementById('topDown360Btn');
        if (_tdb) _tdb.onclick = () => {
            topDown360 = !topDown360;
            _tdb.classList.toggle('active', topDown360);
            _tdb.classList.toggle('btn-warning', topDown360);
            _tdb.classList.toggle('btn-outline-warning', !topDown360);
            topDownTrails.clear();
            if (typeof currentTime === 'number') { topDownLastRender = -999; updateMiniMapShuttle(currentTime); }
        };
        // Synchro auto depuis le .rec (scale+offset GPS + largeur de voie).
        const _srb = document.getElementById('syncRecBtn');
        if (_srb) _srb.onclick = async () => {
            if (!currentSessionId) return;
            const _t0 = _srb.innerHTML; _srb.disabled = true; _srb.innerHTML = '⏳';
            try {
                const r = await fetch(`${config.urls.deleteSession}${currentSessionId}/sync-rec/`, {
                    method: 'POST', headers: { 'X-CSRFToken': config.csrfToken },
                });
                const d = await r.json();
                if (d.success) {
                    try { localStorage.removeItem('cam_analyzer_lane_width_' + currentSessionId); } catch (e) { /* noop */ }
                    alert('Synchro .rec OK :\nscale=' + d.gps_time_scale + '  offset=' + d.gps_time_offset + 's'
                          + (d.lane_width_m ? '\nlargeur voie=' + d.lane_width_m + 'm' : '') + '\n(' + d.rec + ')');
                    loadSession(currentSessionId);
                } else { alert('Sync .rec : ' + (d.error || '?')); }
            } catch (e) { alert('Sync .rec échec : ' + e.message); }
            finally { _srb.disabled = false; _srb.innerHTML = _t0; }
        };
        // Largeur de voie (gabarit vue de dessus) : slider + persistance + re-render live.
        const _lw = document.getElementById('laneWidthSlider');
        if (_lw) {
            _lw.oninput = () => {
                laneWidthM = parseFloat(_lw.value) || 3.5;
                const _lwl = document.getElementById('laneWidthVal'); if (_lwl) _lwl.textContent = laneWidthM.toFixed(1) + 'm';
                // Override manuel PAR SESSION (gagne sur l'auto au rechargement).
                try { if (currentSessionId) localStorage.setItem('cam_analyzer_lane_width_' + currentSessionId, String(laneWidthM)); } catch (e) { /* noop */ }
                if (typeof currentTime === 'number') { topDownLastRender = -999; updateMiniMapShuttle(currentTime); }
            };
        }
        // Filtre de confiance à l'affichage (sans ré-analyse) + persistance de la valeur.
        const _cf = document.getElementById('overlayConfSlider');
        if (_cf) {
            try {
                const _sv = localStorage.getItem('cam_analyzer_min_conf');
                if (_sv !== null) overlayMinConf = parseFloat(_sv) || 0;
            } catch (e) { /* noop */ }
            _cf.value = overlayMinConf;
            const _lbl0 = document.getElementById('overlayConfVal');
            if (_lbl0) _lbl0.textContent = Math.round(overlayMinConf * 100) + '%';
            _cf.oninput = () => {
                overlayMinConf = parseFloat(_cf.value) || 0;
                const _lbl = document.getElementById('overlayConfVal');
                if (_lbl) _lbl.textContent = Math.round(overlayMinConf * 100) + '%';
                try { localStorage.setItem('cam_analyzer_min_conf', String(overlayMinConf)); } catch (e) { /* noop */ }
                if (typeof currentTime === 'number') updateDetectionOverlay(currentTime);
            };
        }
        // Offset GPS↔vidéo : ajustement en direct (re-aligne la navette/objets) + save.
        const _goInput = document.getElementById('gpsOffsetInput');
        const _goSlider = document.getElementById('gpsOffsetSlider');
        const _applyOffset = (v) => {
            gpsTimeOffset = parseFloat(v) || 0;
            if (_goInput) _goInput.value = gpsTimeOffset;
            if (_goSlider) _goSlider.value = gpsTimeOffset;
            // Forcer le re-render (le throttle de la vue de dessus skippe sinon car le
            // temps vidéo ne bouge pas pendant le drag) → recalage navette + objets live.
            topDownLastRender = -999;
            if (currentSessionId && typeof currentTime === 'number') updateMiniMapShuttle(currentTime);
        };
        if (_goInput) _goInput.oninput = () => _applyOffset(_goInput.value);
        if (_goSlider) _goSlider.oninput = () => _applyOffset(_goSlider.value);
        const _goSave = document.getElementById('gpsOffsetSaveBtn');
        if (_goSave) _goSave.onclick = async () => {
            if (!currentSessionId) return;
            try {
                const r = await fetch(`${config.urls.deleteSession}${currentSessionId}/gps-offset/`, {
                    method: 'POST', headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ gps_time_offset: gpsTimeOffset }),
                });
                const d = await r.json();
                if (d.success) { _goSave.textContent = '✓'; setTimeout(() => { _goSave.textContent = '💾'; }, 1200); }
                else alert('Échec sauvegarde offset : ' + (d.error || '?'));
            } catch (e) { alert('Échec : ' + e.message); }
        };

        // Contrôles de VUE minimalistes superposés (icônes seules) : plein écran + suivi.
        if (document.getElementById('mapFullscreenBtn')) return;   // overlay ajouté 1×
        const ctrl = L.control({ position: 'topright' });
        ctrl.onAdd = function () {
            const div = L.DomUtil.create('div', 'leaflet-bar');
            div.style.cssText = 'background:#1e1e24;padding:3px;display:flex;flex-direction:column;gap:3px;';
            div.innerHTML =
                '<button id="mapFullscreenBtn" class="btn btn-sm btn-outline-light" style="padding:1px 7px;" title="Plein écran de la carte">⛶</button>'
                + '<button id="followToggleBtn" class="btn btn-sm btn-outline-warning" style="padding:1px 7px;" title="Recentrage auto en lecture">🎯</button>';
            L.DomEvent.disableClickPropagation(div);   // clic bouton ≠ déplacement carte
            return div;
        };
        ctrl.addTo(miniMap);
        wire('mapFullscreenBtn', toggleMapFullscreen);
        const fb = document.getElementById('followToggleBtn');
        if (fb) {
            fb.style.opacity = topDownAutoFollow ? '1' : '0.45';
            fb.onclick = () => {
                topDownAutoFollow = !topDownAutoFollow;
                fb.style.opacity = topDownAutoFollow ? '1' : '0.45';
                fb.title = `Recentrage auto : ${topDownAutoFollow ? 'ON' : 'OFF'}`;
            };
        }
        // Recaler la carte Leaflet à chaque entrée/sortie de plein écran.
        document.addEventListener('fullscreenchange', () => {
            if (miniMap) setTimeout(() => miniMap.invalidateSize(), 60);
        });
    }

    // Plein écran de la carte (comme les tuiles vidéo) — sur le wrapper pour que
    // les contrôles superposés suivent ; invalidateSize géré par le listener ci-dessus.
    function toggleMapFullscreen() {
        const wrap = document.getElementById('camAnalyzerMapWrap');
        if (!wrap) return;
        const fsEl = document.fullscreenElement || document.webkitFullscreenElement;
        if (fsEl) {
            (document.exitFullscreen || document.webkitExitFullscreen).call(document);
        } else {
            (wrap.requestFullscreen || wrap.webkitRequestFullscreen).call(wrap);
        }
    }

    // Test SAM3 sur la frame front courante : lance la tâche gpu, poll le résultat,
    // affiche masks + scores et les dessine sur la vidéo front. Si calibrate=true,
    // calibre la vue de dessus depuis le meilleur passage détecté (chaîne 1 frame).
    async function runSam3Test(calibrate = false) {
        if (!currentSessionId || !cameras['front']) { alert('Charge une session avec caméra front.'); return; }
        const conf = parseFloat(prompt('Seuil de confiance min (0 = tout afficher) :', '0') || '0') || 0;
        const t = parseFloat(syncSeekBar.value) || 0;
        const fps = cameras['front'].fps || 12;
        const frameNumber = Math.round(t * fps);
        const btnId = calibrate ? 'sam3CalibBtn' : 'sam3TestBtn';
        const label = calibrate ? '📐 Calib. SAM3' : '🔬 Test SAM3';
        const btn = document.getElementById(btnId);
        if (btn) { btn.disabled = true; btn.textContent = calibrate ? '📐 …' : '🔬 …'; }
        try {
            const r = await fetch(`${config.urls.updateSession}${currentSessionId}/sam3-test/`, {
                method: 'POST', headers: { 'X-CSRFToken': config.csrfToken, 'Content-Type': 'application/json' },
                body: JSON.stringify({ position: 'front', frame_number: frameNumber, min_confidence: conf, calibrate }),
            });
            const d = await r.json();
            if (!d.success) { alert('Échec : ' + (d.error || '?')); return; }
            for (let i = 0; i < 60; i++) {
                await new Promise(res => setTimeout(res, 2000));
                const rr = await fetch(`${config.urls.updateSession}${currentSessionId}/sam3-test-result/`);
                const res = await rr.json();
                if (res.status === 'done') {
                    const scores = (res.markings || []).map(m => `${m.label}:${m.confidence}`).join(', ') || '(aucun mask)';
                    let msg = `SAM3 frame ${res.frame_number} : ${res.count} mask(s)\n${scores}\nPrompts: ${(res.prompts || []).join(' | ')}`;
                    const c = res.calibration;
                    if (c) {
                        msg += c.ok
                            ? `\n\n✅ Calibration [${c.position}] OK — RMS ${c.rms_error_m} m. Vue de dessus mise à jour.`
                            : `\n\n❌ Calibration : ${c.error || 'échec'}`;
                    }
                    alert(msg);
                    lastSam3TestOverlay = { time: t, res };
                    drawSam3TestMarkings(res);
                    // Calibration réussie → recharger la session (distances sol + vue de dessus).
                    if (c && c.ok) loadSession(currentSessionId);
                    return;
                }
                if (res.status === 'error') { alert('SAM3 : ' + (res.error || '?')); return; }
            }
            alert('Test SAM3 : délai dépassé (le modèle charge ~30 s, réessaie).');
        } catch (e) { alert('Échec : ' + e.message); }
        finally { if (btn) { btn.disabled = false; btn.textContent = label; } }
    }

    // Copie un instantané de synchro de l'instant courant (temps vidéo, frames &
    // offsets par caméra, fix GPS interpolé, détections front) dans le presse-papier
    // → l'utilisateur le colle pour un debug contextualisé (comparé à la BDD).
    function copyDebugInfo() {
        const t = parseFloat(syncSeekBar && syncSeekBar.value) || 0;
        const L = [];
        L.push('=== WAMA cam_analyzer debug ===');
        L.push('session: ' + currentSessionId);
        L.push('sync_time_s: ' + t.toFixed(3));
        let frontFrame = null;
        ['front', 'rear', 'left', 'right'].forEach(pos => {
            const c = cameras[pos];
            if (!c) return;
            const off = c.time_offset || 0;
            const fps = c.fps || 0;
            const vt = t + off;
            const fn = fps ? Math.round(vt * fps) : '?';
            let ndet = '?';
            const dd = detectionData[pos];
            if (dd && dd.frames && dd.frames.length) {
                let best = null, bd = Infinity;
                for (const fr of dd.frames) {
                    const ts = (fr.timestamp != null) ? fr.timestamp : (fps ? fr.frame_number / fps : 0);
                    const dv = Math.abs(ts - vt);
                    if (dv < bd) { bd = dv; best = fr; }
                }
                ndet = best ? (best.detections || []).length : 0;
                if (pos === 'front') frontFrame = best;
            }
            L.push(`cam ${pos}: video_time=${vt.toFixed(3)}s frame=${fn} fps=${fps} offset=${off} dets=${ndet}`);
        });
        const g = findGpsAtTime(t);
        if (g) {
            const f = (v, n) => (typeof v === 'number' ? v.toFixed(n) : '?');
            L.push(`gps@t: ts=${f(g.ts, 3)}s lat=${f(g.lat, 7)} lon=${f(g.lon, 7)} heading=${f(g.heading, 1)}deg speed=${f(g.speed, 2)}`);
        } else {
            L.push('gps@t: (aucun fix)');
        }
        if (cachedGpsTrack && cachedGpsTrack.length) {
            const a = cachedGpsTrack[0], b = cachedGpsTrack[cachedGpsTrack.length - 1];
            L.push(`gps_track: ${cachedGpsTrack.length} fixes span [${a.ts.toFixed(2)}..${b.ts.toFixed(2)}]s`);
        }
        if (frontFrame) {
            L.push(`front_frame: number=${frontFrame.frame_number} ts=${(frontFrame.timestamp != null ? frontFrame.timestamp : 0).toFixed(3)}s`);
            (frontFrame.detections || []).slice(0, 12).forEach(d => {
                L.push(`  - ${d.class_name || d.type || '?'} id=${d.track_id != null ? d.track_id : ''} conf=${d.confidence != null ? Number(d.confidence).toFixed(2) : ''}`
                    + ` bbox=${JSON.stringify(d.bbox || [])} dist_long=${d.dist_longitudinal_m != null ? d.dist_longitudinal_m : ''}`
                    + ` ground_xy=${d.ground_xy ? JSON.stringify(d.ground_xy) : ''}`);
            });
        }
        const txt = L.join('\n');
        const done = () => alert('Debug copié dans le presse-papier ✔\nColle-le dans le chat.');
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(txt).then(done, () => prompt('Copie manuelle :', txt));
        } else {
            prompt('Copie manuelle :', txt);
        }
    }

    function drawSam3TestMarkings(res) {
        const canvas = document.getElementById('canvas-front');
        const video = document.getElementById('video-front');
        if (!canvas || !video) return;
        const srcW = res.width || (cameras['front'] && cameras['front'].width);
        const srcH = res.height || (cameras['front'] && cameras['front'].height);
        if (!srcW || !srcH) return;
        // Synchro identique à drawDetections : recaler la taille interne du canvas
        // sur la vidéo affichée AVANT le letterbox (sinon overlay décalé).
        const rect = video.getBoundingClientRect();
        if (Math.round(rect.width) !== canvas.width || Math.round(rect.height) !== canvas.height) {
            canvas.width = Math.round(rect.width);
            canvas.height = Math.round(rect.height);
        }
        const ctx = canvas.getContext('2d');
        const cw = canvas.width, ch = canvas.height;
        const videoAR = srcW / srcH, containerAR = cw / ch;
        let drawW, drawH, ox, oy;
        if (videoAR > containerAR) { drawW = cw; drawH = cw / videoAR; ox = 0; oy = (ch - drawH) / 2; }
        else { drawH = ch; drawW = ch * videoAR; ox = (cw - drawW) / 2; oy = 0; }
        const sx = drawW / srcW, sy = drawH / srcH;
        (res.markings || []).forEach(m => {
            const poly = m.polygon;
            if (!Array.isArray(poly) || poly.length < 3) return;
            ctx.beginPath();
            poly.forEach(([px, py], i) => { const x = ox + px * sx, y = oy + py * sy; i ? ctx.lineTo(x, y) : ctx.moveTo(x, y); });
            ctx.closePath();
            ctx.strokeStyle = '#00ff88'; ctx.lineWidth = 2; ctx.stroke();
            ctx.fillStyle = 'rgba(0,255,136,0.2)'; ctx.fill();
        });
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
