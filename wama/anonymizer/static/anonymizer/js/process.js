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
        const btnToggle = btnRef || getButton();
        const loader = getLoader();
        const resultDiv = getResultDiv();

        if (!btnToggle) return;

        btnToggle.innerHTML = '<i class="fas fa-stop"></i> Stop Process';
        btnToggle.className = 'btn btn-danger';
        if (loader) loader.style.display = 'block';
        if (resultDiv) resultDiv.innerHTML = '';

        fetch("/anonymizer/process/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie('csrftoken') }
        })
        .then(r => r.json())
        .then(data => {
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

                    progressIntervals[mediaId] = setInterval(() => {
                        fetch(`/anonymizer/process_progress/?media_id=${mediaId}`)
                            .then(r => r.json())
                            .then(progressData => {
                                const pct = progressData.progress || 0;
                                progressBar.style.width = pct + '%';
                                progressBar.innerText = pct + '%';

                                if (pct >= 100) {
                                    clearInterval(progressIntervals[mediaId]);
                                    delete progressIntervals[mediaId];

                                    const btn = tr.querySelector("form[action$='download_media/'] button");
                                    if (btn) btn.removeAttribute('disabled');
                                }
                            })
                            .catch(() => clearInterval(progressIntervals[mediaId]));
                    }, 1000);
                });
            });

            // Polling global progress bar
            const globalBar = document.getElementById('process-progress');
            if (globalBar) {
                pollingGlobal = setInterval(() => {
                    fetch('/anonymizer/process_progress/')
                        .then(r => r.json())
                        .then(data => {
                            const pct = data.progress || 0;
                            globalBar.style.width = pct + '%';
                            globalBar.innerText = pct + '%';
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
            btnToggle.innerHTML = '<i class="fas fa-dice"></i> Start Process';
            btnToggle.className = 'btn btn-info';
        }
        isRunning = false;
    }

    function checkDownloadAll() {
        const wrapper = document.getElementById("download-all-wrapper");
        if (!wrapper) return;
        const url = wrapper.dataset.checkUrl;
        if (!url) return;

        fetch(url)
            .then(response => response.json())
            .then(data => {
                const btn = document.getElementById("download-all-btn");
                if (!btn) return;
                if (data.all_processed) btn.removeAttribute("disabled");
                else btn.setAttribute("disabled", "true");
            })
            .catch(err => console.error("Error checking processed:", err));
    }

    // Poll every second
    setInterval(checkDownloadAll, 1000);
});
