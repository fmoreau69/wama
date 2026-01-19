document.addEventListener("DOMContentLoaded", function() {
    let isRunning = false;
    let taskId = null;
    const progressIntervals = {};
    let pollingYOLO = null;
    let pollingGlobal = null;

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie) {
            document.cookie.split(';').forEach(cookie => {
                cookie = cookie.trim();
                if (cookie.startsWith(name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                }
            });
        }
        return cookieValue;
    }

    // Start polling for a specific media's progress
    function startMediaProgressPolling(mediaId) {
        if (progressIntervals[mediaId]) {
            return; // Already polling this media
        }

        console.log(`[process.js] Starting progress polling for media ${mediaId}`);

        progressIntervals[mediaId] = setInterval(() => {
            fetch(`/anonymizer/process_progress/?media_id=${mediaId}`)
                .then(r => r.json())
                .then(progressData => {
                    const pct = progressData.progress || 0;
                    console.log(`[process.js] Media ${mediaId} progress: ${pct}%`);

                    // Find progress bar fresh each time (handles table refreshes)
                    const tr = document.querySelector(`tr[data-media-id="${mediaId}"]`);
                    if (!tr) {
                        console.warn(`[process.js] Row not found for media ${mediaId}`);
                        return;
                    }

                    const progressBar = tr.querySelector(".progress-bar");
                    if (progressBar) {
                        progressBar.style.width = pct + '%';
                        progressBar.innerText = pct + '%';
                    }

                    // Update status badge
                    const statusBadge = tr.querySelector('td:nth-child(6) .badge');
                    if (statusBadge) {
                        if (pct >= 100) {
                            statusBadge.className = 'badge bg-success';
                            statusBadge.textContent = 'Terminé';
                        } else if (pct > 0) {
                            statusBadge.className = 'badge bg-warning';
                            statusBadge.textContent = 'En cours';
                        }
                    }

                    if (pct >= 100) {
                        clearInterval(progressIntervals[mediaId]);
                        delete progressIntervals[mediaId];
                        console.log(`[process.js] Completed polling for media ${mediaId}`);

                        // Update the row to reflect processed state
                        tr.dataset.mediaProcessed = 'true';

                        // Enable download button
                        const btn = tr.querySelector("form[action$='download_media/'] button");
                        if (btn) {
                            btn.removeAttribute('disabled');
                            btn.removeAttribute('aria-disabled');
                            btn.removeAttribute('tabindex');
                            btn.classList.remove('disabled');
                            console.log(`[process.js] Download button enabled for media ${mediaId}`);
                        } else {
                            console.warn(`[process.js] Download button not found for media ${mediaId}`);
                        }

                        // Check if all media are processed to enable download all
                        if (typeof checkDownloadAll === 'function') {
                            checkDownloadAll();
                        }

                        // Refresh media table to update UI (more efficient than full content refresh)
                        if (typeof window.refreshMediaTable === 'function') {
                            console.log(`[process.js] Refreshing media table after media ${mediaId} completion`);
                            setTimeout(() => window.refreshMediaTable(), 1000);
                        } else if (typeof refreshContent === 'function') {
                            console.log(`[process.js] Fallback: Refreshing content after media ${mediaId} completion`);
                            setTimeout(() => refreshContent(), 1000);
                        }

                        // Check if all polling is complete (all medias processed)
                        if (isRunning && Object.keys(progressIntervals).length === 0) {
                            console.log('[process.js] All media polling complete, resetting button state');

                            // Stop global polling if exists
                            if (pollingGlobal) {
                                clearInterval(pollingGlobal);
                                pollingGlobal = null;
                            }
                            if (pollingYOLO) {
                                clearInterval(pollingYOLO);
                                pollingYOLO = null;
                            }

                            // Hide loader
                            const loader = getLoader();
                            if (loader) loader.style.display = 'none';

                            // Reset button to initial state
                            resetButton();

                            // Show success message
                            const resultDiv = getResultDiv();
                            if (resultDiv) {
                                resultDiv.innerHTML = '<span class="text-success">✅ Traitement terminé</span>';
                            }
                        }
                    }
                })
                .catch(err => {
                    console.error(`[process.js] Error polling media ${mediaId}:`, err);
                    clearInterval(progressIntervals[mediaId]);
                    delete progressIntervals[mediaId];
                });
        }, 1000);
    }

    // Auto-start polling for all in-progress media on page load
    function initializeProgressPolling() {
        console.log('[process.js] Initializing progress polling for in-progress media...');

        ["#medias", "#medias_process"].forEach(tableId => {
            const table = document.querySelector(tableId);
            if (!table) return;

            table.querySelectorAll('tbody tr[data-media-id]').forEach(tr => {
                const mediaId = tr.dataset.mediaId;
                const processed = tr.dataset.mediaProcessed === 'true';
                const progressBar = tr.querySelector('.progress-bar');

                if (!progressBar) return;

                const currentProgress = parseInt(progressBar.style.width) || 0;

                // Start polling if media is in progress (0 < progress < 100) and not yet processed
                if (currentProgress > 0 && currentProgress < 100 && !processed) {
                    console.log(`[process.js] Found in-progress media ${mediaId} at ${currentProgress}%`);
                    startMediaProgressPolling(mediaId);
                }
            });
        });
    }

    // Initialize polling on page load
    initializeProgressPolling();

    function getButton() {
        return document.getElementById('process-toggle-btn');
    }

    function getLoader() {
        return document.getElementById('process-loader');
    }

    function getResultDiv() {
        return document.getElementById('process-result');
    }

    window.initProcessControls = initProcessControls;
    window.initMediaPreview = initMediaPreview;
    initProcessControls();
    initMediaPreview();

    function initProcessControls() {
        const btnToggle = document.getElementById('process-toggle-btn');
        if (!btnToggle) {
            console.warn('[process.js] Process button not found');
            return;
        }

        // Remove existing listener if any (to prevent duplicates)
        if (btnToggle._processClickHandler) {
            btnToggle.removeEventListener('click', btnToggle._processClickHandler);
        }

        // Create and store the handler
        btnToggle._processClickHandler = function(event) {
            event.preventDefault();
            console.log('[process.js] Button clicked, isRunning:', isRunning);
            if (isRunning) {
                stopProcess(btnToggle);
            } else {
                startProcess(btnToggle);
            }
        };

        btnToggle.addEventListener('click', btnToggle._processClickHandler);
        console.log('[process.js] Process button initialized');
    }

    function initMediaPreview() {
        document.querySelectorAll('.preview-media-link').forEach(btn => {
            if (btn.dataset.previewBound === '1') {
                return;
            }
            btn.dataset.previewBound = '1';
            btn.addEventListener('click', function(event) {
                event.preventDefault();
                const endpoint = btn.dataset.previewUrl;
                if (!endpoint) return;
                fetch(endpoint)
                    .then(r => {
                        if (!r.ok) throw new Error("Preview unavailable");
                        return r.json();
                    })
                    .then(data => applyPreviewData(data))
                    .catch(err => showPreviewError(err.message));
            });
        });
    }

    function getPreviewElements() {
        return {
            video: document.getElementById('media-preview-player'),
            placeholder: document.getElementById('media-preview-empty'),
            meta: document.getElementById('media-preview-meta')
        };
    }

    function applyPreviewData(data) {
        if (!data || !data.url) return;

        // Show preview in modal (like FileManager)
        showPreviewModal(data);
    }

    function showPreviewModal(data) {
        let modal = document.getElementById('mediaPreviewModal');

        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'mediaPreviewModal';
            modal.className = 'modal fade';
            modal.innerHTML = `
                <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
                    <div class="modal-content bg-dark text-white">
                        <div class="modal-header border-secondary">
                            <h5 class="modal-title"></h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body p-0">
                            <div class="preview-container d-flex justify-content-center align-items-center" style="min-height: 300px;"></div>
                        </div>
                        <div class="modal-footer border-secondary py-2">
                            <small class="preview-meta"></small>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);

            // Clean up video/audio when modal is hidden
            modal.addEventListener('hidden.bs.modal', function() {
                const video = modal.querySelector('video');
                const audio = modal.querySelector('audio');
                if (video) video.pause();
                if (audio) audio.pause();
            });
        }

        const title = modal.querySelector('.modal-title');
        const container = modal.querySelector('.preview-container');
        const metaEl = modal.querySelector('.preview-meta');

        title.textContent = data.name || 'Aperçu';

        // Build meta info
        const metaParts = [data.resolution, data.duration].filter(Boolean);
        metaEl.textContent = metaParts.join(' • ');

        // Determine content type and render accordingly
        const mimeType = data.mime_type || '';

        if (mimeType.startsWith('image/')) {
            container.innerHTML = `<img src="${data.url}" alt="${data.name}" style="max-width:100%; max-height:70vh; object-fit: contain;">`;
        } else if (mimeType.startsWith('video/')) {
            container.innerHTML = `
                <video controls autoplay muted style="max-width:100%; max-height:70vh;">
                    <source src="${data.url}" type="${mimeType}">
                </video>
                <div class="video-error-message d-none text-center p-4">
                    <i class="fas fa-exclamation-triangle fa-3x text-warning mb-3"></i>
                    <h5>Lecture impossible</h5>
                    <p class="mb-2">Le codec de cette vidéo n'est pas supporté par le navigateur.</p>
                    <a href="${data.url}" download class="btn btn-outline-light btn-sm">
                        <i class="fas fa-download me-2"></i>Télécharger le fichier
                    </a>
                </div>
            `;
            // Handle video playback errors
            const video = container.querySelector('video');
            const errorMsg = container.querySelector('.video-error-message');
            video.addEventListener('error', function() {
                video.classList.add('d-none');
                errorMsg.classList.remove('d-none');
            });
        } else if (mimeType.startsWith('audio/')) {
            container.innerHTML = `<audio src="${data.url}" controls autoplay style="width:100%;"></audio>`;
        } else {
            // Default to video player for unknown types
            container.innerHTML = `
                <video controls autoplay muted style="max-width:100%; max-height:70vh;">
                    <source src="${data.url}" type="video/mp4">
                </video>
                <div class="video-error-message d-none text-center p-4">
                    <i class="fas fa-exclamation-triangle fa-3x text-warning mb-3"></i>
                    <h5>Lecture impossible</h5>
                    <p class="mb-2">Le codec de cette vidéo n'est pas supporté par le navigateur.</p>
                    <a href="${data.url}" download class="btn btn-outline-light btn-sm">
                        <i class="fas fa-download me-2"></i>Télécharger le fichier
                    </a>
                </div>
            `;
            const video = container.querySelector('video');
            const errorMsg = container.querySelector('.video-error-message');
            video.addEventListener('error', function() {
                video.classList.add('d-none');
                errorMsg.classList.remove('d-none');
            });
        }

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    function showPreviewError(message) {
        // Show error in a toast or alert
        const toastContainer = document.getElementById('toast-container') || createToastContainer();

        const toast = document.createElement('div');
        toast.className = 'toast align-items-center text-white bg-danger border-0';
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body"><i class="fas fa-exclamation-triangle me-2"></i>${message}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;

        toastContainer.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast, { delay: 4000 });
        bsToast.show();

        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    }

    function createToastContainer() {
        let container = document.getElementById('toast-container');
        if (!container) {
            container = document.createElement('div');
            container.id = 'toast-container';
            container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
            container.style.zIndex = '1100';
            document.body.appendChild(container);
        }
        return container;
    }

    function startProcess(btnRef) {
        console.log('[process.js] startProcess() called');

        const btnToggle = btnRef || getButton();
        const loader = getLoader();
        const resultDiv = getResultDiv();

        if (!btnToggle) {
            console.error('[process.js] Button not found!');
            return;
        }

        console.log('[process.js] Changing button state and sending request...');
        btnToggle.innerHTML = '<i class="fas fa-stop"></i> Arrêter';
        btnToggle.className = 'btn btn-danger btn-sm';
        if (loader) loader.style.display = 'block';
        if (resultDiv) resultDiv.innerHTML = '';

        // Reset all progress bars to 0% before starting
        ["#medias", "#medias_process"].forEach(tableId => {
            document.querySelectorAll(`${tableId} tbody tr[data-media-id]`).forEach(tr => {
                const progressBar = tr.querySelector(".progress-bar");
                if (progressBar) {
                    progressBar.style.width = '0%';
                    progressBar.innerText = '0%';
                }
                // Reset status badge
                const statusBadge = tr.querySelector('td:nth-child(6) .badge');
                if (statusBadge) {
                    statusBadge.className = 'badge bg-secondary';
                    statusBadge.textContent = 'En attente';
                }
                // Mark as not processed
                tr.dataset.mediaProcessed = 'false';
            });
        });

        // Reset global progress bar
        const globalBarReset = document.getElementById('globalProgressBar');
        if (globalBarReset) {
            globalBarReset.style.width = '0%';
            globalBarReset.innerText = '0%';
        }

        // Clear any existing polling intervals
        Object.keys(progressIntervals).forEach(mediaId => {
            clearInterval(progressIntervals[mediaId]);
            delete progressIntervals[mediaId];
        });
        if (pollingGlobal) {
            clearInterval(pollingGlobal);
            pollingGlobal = null;
        }
        if (pollingYOLO) {
            clearInterval(pollingYOLO);
            pollingYOLO = null;
        }

        console.log('[process.js] Sending POST to /anonymizer/process/');
        fetch("/anonymizer/process/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie('csrftoken') }
        })
        .then(r => {
            console.log(`[process.js] Response status: ${r.status}`);
            return r.json();
        })
        .then(data => {
            console.log('[process.js] Response data:', data);
            if (!data.task_id) {
                if (loader) loader.style.display = 'none';
                resetButton();
                if (resultDiv) resultDiv.innerHTML = '<span class="text-warning">⚠️ Add media first</span>';
                return;
            }

            taskId = data.task_id;
            isRunning = true;

            // Polling progress per media row (upload page & process page)
            ["#medias", "#medias_process"].forEach(tableId => {
                const table = document.querySelector(tableId);
                console.log(`[process.js] Looking for table: ${tableId}, found:`, table);

                if (!table) return;

                const rows = table.querySelectorAll('tbody tr[data-media-id]');
                console.log(`[process.js] Found ${rows.length} media rows in ${tableId}`);

                rows.forEach(tr => {
                    const mediaId = tr.dataset.mediaId;
                    console.log(`[process.js] Starting polling for media ${mediaId}`);

                    // Use the centralized polling function
                    startMediaProgressPolling(mediaId);
                });
            });

            // Polling global progress bar
            const globalBar = document.getElementById('globalProgressBar');
            if (globalBar) {
                pollingGlobal = setInterval(() => {
                    fetch('/anonymizer/process_progress/')
                        .then(r => r.json())
                        .then(data => {
                            const pct = data.progress || 0;
                            globalBar.style.width = pct + '%';
                            globalBar.innerText = pct + '%';

                            // Check if all processing is complete
                            if (pct >= 100 && isRunning) {
                                console.log('[process.js] All media processing complete, resetting button');

                                // Stop all polling intervals
                                if (pollingGlobal) {
                                    clearInterval(pollingGlobal);
                                    pollingGlobal = null;
                                }
                                if (pollingYOLO) {
                                    clearInterval(pollingYOLO);
                                    pollingYOLO = null;
                                }

                                // Hide loader
                                const loader = getLoader();
                                if (loader) loader.style.display = 'none';

                                // Reset button to initial state
                                resetButton();

                                // Show success message
                                const resultDiv = getResultDiv();
                                if (resultDiv) {
                                    resultDiv.innerHTML = '<span class="text-success">✅ Traitement terminé</span>';
                                }
                            }
                        })
                        .catch(() => {});
                }, 1000);
            }

            // YOLO preview polling (still commented)
            /*
            const previewContainer = document.querySelector("#collapsePreview .empty-box");
            if (previewContainer) {
                pollingYOLO = setInterval(() => {
                    fetch("/anonymizer/yolo_preview/")
                        .then(r => r.text())
                        .then(html => { previewContainer.innerHTML = html; })
                        .catch(() => {});
                }, 2000);
            }
            */
        })
        .catch(err => {
            if (loader) loader.style.display = 'none';
            resetButton();
            if (resultDiv) resultDiv.innerHTML = `<span class="text-danger">Error: ${err}</span>`;
        });
    }

    function stopProcess(btnRef) {
        const loader = getLoader();
        const resultDiv = getResultDiv();

        fetch("/anonymizer/stop_process/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie('csrftoken') }
        })
        .then(() => {
            Object.values(progressIntervals).forEach(interval => clearInterval(interval));

            if (pollingYOLO) clearInterval(pollingYOLO);
            if (pollingGlobal) clearInterval(pollingGlobal);

            if (loader) loader.style.display = 'none';
            resetButton();
            if (resultDiv) resultDiv.innerHTML = '<span class="text-warning">⚠️ Process stopped</span>';

            taskId = null;
            isRunning = false;
        })
        .catch(() => {
            if (resultDiv) {
                resultDiv.innerHTML = '<span class="text-danger">Error stopping process</span>';
            }
        });
    }

    function resetButton() {
        const btnToggle = getButton();
        if (btnToggle) {
            btnToggle.innerHTML = '<i class="fas fa-play"></i> Démarrer';
            btnToggle.className = 'btn btn-success btn-sm';
        }
        isRunning = false;
        taskId = null;
        console.log('[process.js] Button reset, isRunning:', isRunning);
    }

    function checkDownloadAll() {
        const url = '/anonymizer/check_all_processed/';

        fetch(url)
            .then(response => response.json())
            .then(data => {
                const btn = document.getElementById("download-all-btn");
                if (!btn) {
                    console.warn('[process.js] Download all button not found');
                    return;
                }
                if (data.all_processed) {
                    btn.removeAttribute("disabled");
                    console.log('[process.js] Download all button enabled');
                } else {
                    btn.setAttribute("disabled", "true");
                    console.log('[process.js] Download all button disabled - not all media processed');
                }
            })
            .catch(err => console.error("[process.js] Error checking all processed:", err));
    }

    // Poll every second
    setInterval(checkDownloadAll, 1000);
});
