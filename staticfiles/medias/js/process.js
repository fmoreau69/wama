document.addEventListener("DOMContentLoaded", function() {
    let isRunning = false;
    let taskId = null;
    const progressIntervals = {};
    let pollingYOLO = null;
    let pollingConsole = null;
    let pollingGlobal = null;
    let consolePollingInterval = null;

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

    // Fonction pour mettre à jour les logs de la console
    function updateConsoleLogs() {
        const consoleContainer = document.querySelector("#console-logs-content");
        if (!consoleContainer) return;
        
        // Vérifier si la console est visible
        const collapseConsole = document.getElementById("collapseConsole");
        if (!collapseConsole || !collapseConsole.classList.contains("show")) {
            return;
        }
        
        fetch("/medias/console_content/")
            .then(r => r.json())
            .then(data => {
                if (data.output && data.output.length > 0) {
                    consoleContainer.innerHTML = data.output.map(line => {
                        // Échapper les caractères HTML pour la sécurité
                        const escapedLine = line.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
                        return `<div style="margin-bottom: 2px; white-space: pre-wrap; word-wrap: break-word;">${escapedLine}</div>`;
                    }).join('');
                    // Auto-scroll vers le bas pour voir les derniers logs
                    const logsWrapper = document.getElementById("console-logs-container");
                    if (logsWrapper) {
                        logsWrapper.scrollTop = logsWrapper.scrollHeight;
                    }
                } else {
                    consoleContainer.innerHTML = '<div class="text-center text-muted" style="padding: 20px;">Aucun log disponible. Les logs Celery worker apparaîtront ici.</div>';
                }
            })
            .catch(() => {});
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

        if (!btnToggle) {
            return;
        }

        btnToggle.innerHTML = '<i class="fas fa-stop"></i> Stop Process';
        btnToggle.className = 'btn btn-danger';
        if (loader) loader.style.display = 'block';
        if (resultDiv) resultDiv.innerHTML = '';

        fetch("/medias/process/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie('csrftoken') }
        })
        .then(r => r.json())
        .then(data => {
            if (!data.task_id) {
                if (loader) loader.style.display = 'none';
                resetButton();
                if (resultDiv) {
                    resultDiv.innerHTML = '<span class="text-warning">⚠️ Add media first</span>';
                }
                return;
            }
            taskId = data.task_id;
            isRunning = true;

            // Polling pour chaque ligne <tr> qui contient un media_id (upload page table id="medias")
            document.querySelectorAll("#medias tbody tr[data-media-id]").forEach(tr => {
                const mediaId = tr.dataset.mediaId;
                const progressBar = tr.querySelector(".progress-bar");
                if (!progressBar) return;

                progressIntervals[mediaId] = setInterval(() => {
                    fetch(`/medias/process_progress/?media_id=${mediaId}`)
                        .then(r => r.json())
                        .then(progressData => {
                            const pct = progressData.progress || 0;
                            progressBar.style.width = pct + '%';
                            progressBar.innerText = pct + '%';

                            if (pct >= 100) {
                                clearInterval(progressIntervals[mediaId]);
                                delete progressIntervals[mediaId];
                                // Enable download button on upload page
                                const row = document.querySelector(`#medias tbody tr[data-media-id='${mediaId}']`);
                                if (row) {
                                    const btn = row.querySelector("form[action$='download_media/'] button");
                                    if (btn) btn.removeAttribute('disabled');
                                }
                            }
                        })
                        .catch(() => clearInterval(progressIntervals[mediaId]));
                }, 1000);
            });

            // Polling aussi pour la table de la page process (id="medias_process")
            document.querySelectorAll("#medias_process tbody tr[data-media-id]").forEach(tr => {
                const mediaId = tr.dataset.mediaId;
                const progressBar = tr.querySelector(".progress-bar");
                if (!progressBar) return;

                progressIntervals[mediaId] = setInterval(() => {
                    fetch(`/medias/process_progress/?media_id=${mediaId}`)
                        .then(r => r.json())
                        .then(progressData => {
                            const pct = progressData.progress || 0;
                            progressBar.style.width = pct + '%';
                            progressBar.innerText = pct + '%';

                            if (pct >= 100) {
                                clearInterval(progressIntervals[mediaId]);
                                delete progressIntervals[mediaId];
                                // Enable download button on process page
                                const row = document.querySelector(`#medias_process tbody tr[data-media-id='${mediaId}']`);
                                if (row) {
                                    const btn = row.querySelector("form[action$='download_media/'] button");
                                    if (btn) btn.removeAttribute('disabled');
                                }
                            }
                        })
                        .catch(() => clearInterval(progressIntervals[mediaId]));
                }, 1000);
            });

            // Polling global progress bar if present
            const globalBar = document.getElementById('process-progress');
            if (globalBar) {
                pollingGlobal = setInterval(() => {
                    fetch('/medias/process_progress/')
                        .then(r => r.json())
                        .then(data => {
                            const pct = data.progress || 0;
                            globalBar.style.width = pct + '%';
                            globalBar.innerText = pct + '%';
                        })
                        .catch(() => {});
                }, 1000);
            }

//            // Polling YOLO preview
//            const previewContainer = document.querySelector("#collapsePreview .empty-box");
//            if (previewContainer) {
//                pollingYOLO = setInterval(() => {
//                    fetch("/medias/yolo_preview/")
//                        .then(r => r.text())
//                        .then(html => { previewContainer.innerHTML = html; })
//                        .catch(() => {});
//                }, 2000);
//            }
//
            // Polling console rapide pendant le processus (arrête le polling automatique)
            if (consolePollingInterval) {
                clearInterval(consolePollingInterval);
                consolePollingInterval = null;
            }
            const consoleContainer = document.querySelector("#console-logs-content");
            if (consoleContainer) {
                pollingConsole = setInterval(() => {
                    updateConsoleLogs();
                }, 1000); // Plus rapide pendant le processus
            }
        })
        .catch(err => {
            if (loader) loader.style.display = 'none';
            resetButton();
            if (resultDiv) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err}</span>`;
            }
        });
    }

    function stopProcess(btnRef) {
        const loader = getLoader();
        const resultDiv = getResultDiv();

        fetch("/medias/stop_process/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie('csrftoken') }
        })
        .then(() => {
            Object.values(progressIntervals).forEach(interval => clearInterval(interval));
            if (pollingYOLO) clearInterval(pollingYOLO);
            if (pollingConsole) {
                clearInterval(pollingConsole);
                pollingConsole = null;
            }

            if (loader) loader.style.display = 'none';
            resetButton();
            if (resultDiv) {
                resultDiv.innerHTML = '<span class="text-warning">⚠️ Process stopped</span>';
            }
            taskId = null;
            isRunning = false;
            if (pollingGlobal) { clearInterval(pollingGlobal); pollingGlobal = null; }
            
            // Reprendre le polling automatique si la console est visible
            const collapseConsole = document.getElementById("collapseConsole");
            if (collapseConsole && collapseConsole.classList.contains("show")) {
                startConsolePolling();
            }
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
                if (data.all_processed) {
                    btn.removeAttribute("disabled");
                } else {
                    btn.setAttribute("disabled", "true");
                }
            })
            .catch(err => console.error("Error checking processed:", err));
    }

    // Vérifie toutes les secondes
    setInterval(checkDownloadAll, 1000);

    // Démarrer le polling automatique de la console
    function startConsolePolling() {
        if (consolePollingInterval) return; // Déjà démarré
        consolePollingInterval = setInterval(updateConsoleLogs, 2000); // Toutes les 2 secondes
        updateConsoleLogs(); // Mise à jour immédiate
    }
    
    // Observer les changements de visibilité de la console
    const collapseConsole = document.getElementById("collapseConsole");
    if (collapseConsole) {
        // Utiliser MutationObserver pour détecter les changements de classe
        const observer = new MutationObserver(function(mutations) {
            mutations.forEach(function(mutation) {
                if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
                    if (collapseConsole.classList.contains("show")) {
                        startConsolePolling();
                    } else {
                        if (consolePollingInterval) {
                            clearInterval(consolePollingInterval);
                            consolePollingInterval = null;
                        }
                    }
                }
            });
        });
        observer.observe(collapseConsole, { attributes: true });
        
        // Démarrer si la console est déjà visible au chargement
        if (collapseConsole.classList.contains("show")) {
            startConsolePolling();
        }
    }

});
