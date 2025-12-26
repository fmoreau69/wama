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
    function startMediaProgressPolling(mediaId, progressBar) {
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
                    progressBar.style.width = pct + '%';
                    progressBar.innerText = pct + '%';

                    // Update status badge
                    const tr = progressBar.closest('tr');
                    if (tr) {
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
                    }

                    if (pct >= 100) {
                        clearInterval(progressIntervals[mediaId]);
                        delete progressIntervals[mediaId];
                        console.log(`[process.js] Completed polling for media ${mediaId}`);

                        // Update the row to reflect processed state
                        if (tr) {
                            tr.dataset.mediaProcessed = 'true';
                        }

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
                    startMediaProgressPolling(mediaId, progressBar);
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
        if (!btnToggle || btnToggle.dataset.processBound === '1') {
            return;
        }
        btnToggle.dataset.processBound = '1';
        btnToggle.addEventListener('click', function(event) {
            event.preventDefault();
            if (isRunning) {
                stopProcess(btnToggle);
            } else {
                startProcess(btnToggle);
            }
        });
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
        const { video, placeholder, meta } = getPreviewElements();
        if (!video || !data || !data.url) return;

        if (placeholder) {
            placeholder.classList.add('d-none');
        }
        if (meta) {
            const parts = [data.name, data.resolution, data.duration].filter(Boolean);
            meta.textContent = parts.join(' • ');
            meta.classList.remove('d-none');
        }

        if (video.dataset.currentSrc !== data.url) {
            video.pause();
            video.src = data.url;
            video.dataset.currentSrc = data.url;
            video.load();
        }

        video.classList.remove('d-none');
        video.muted = true;
        video.play().catch(() => {});
    }

    function showPreviewError(message) {
        const { video, placeholder, meta } = getPreviewElements();
        if (video) {
            video.pause();
            video.classList.add('d-none');
        }
        if (placeholder) {
            placeholder.classList.remove('d-none');
            placeholder.innerHTML = `<h4 class="fw-bold mb-2">Impossible d'afficher l'aperçu</h4><p class="text-danger mb-0">${message}</p>`;
        }
        if (meta) {
            meta.classList.add('d-none');
            meta.textContent = '';
        }
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
        btnToggle.innerHTML = '<i class="fas fa-stop"></i> Stop Process';
        btnToggle.className = 'btn btn-danger';
        if (loader) loader.style.display = 'block';
        if (resultDiv) resultDiv.innerHTML = '';

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
                document.querySelectorAll(`${tableId} tbody tr[data-media-id]`).forEach(tr => {
                    const mediaId = tr.dataset.mediaId;
                    const progressBar = tr.querySelector(".progress-bar");
                    if (!progressBar) return;

                    // Use the centralized polling function
                    startMediaProgressPolling(mediaId, progressBar);
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
            btnToggle.innerHTML = '<i class="fas fa-play"></i> Démarrer le traitement';
            btnToggle.className = 'btn btn-success';
        }
        isRunning = false;
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
