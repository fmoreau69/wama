document.addEventListener("DOMContentLoaded", function() {
    const btnToggle = document.getElementById('process-toggle-btn');
    const loader = document.getElementById('process-loader');
    const resultDiv = document.getElementById('process-result');

    if (!btnToggle) return; // arrêt si le bouton n'existe pas

    let isRunning = false;
    let taskId = null;
    const progressIntervals = {};
    let pollingYOLO = null;
    let pollingConsole = null;

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

    function startProcess() {
        btnToggle.innerHTML = '<i class="fas fa-stop"></i> Stop Process';
        btnToggle.className = 'btn btn-danger';
        loader.style.display = 'block';
        resultDiv.innerHTML = '';

        fetch("/medias/process/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie('csrftoken') }
        })
        .then(r => r.json())
        .then(data => {
            if (!data.task_id) {
                loader.style.display = 'none';
                resetButton();
                resultDiv.innerHTML = '<span class="text-warning">⚠️ Add media first</span>';
                return;
            }
            taskId = data.task_id;
            isRunning = true;

            // Polling pour chaque ligne <tr> qui contient un media_id
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
                            }
                        })
                        .catch(() => clearInterval(progressIntervals[mediaId]));
                }, 1000);
            });

            // Polling YOLO preview
            const previewContainer = document.querySelector("#collapsePreview .empty-box");
            if (previewContainer) {
                pollingYOLO = setInterval(() => {
                    fetch("/medias/yolo_preview/")
                        .then(r => r.text())
                        .then(html => { previewContainer.innerHTML = html; })
                        .catch(() => {});
                }, 2000);
            }

            // Polling console
            const consoleContainer = document.querySelector("#collapseConsole .empty-box");
            if (consoleContainer) {
                pollingConsole = setInterval(() => {
                    fetch("/medias/console_content/")
                        .then(r => r.json())
                        .then(data => {
                            consoleContainer.innerHTML = data.output.map(line => `<p>${line}</p>`).join('');
                        })
                        .catch(() => {});
                }, 2000);
            }
        })
        .catch(err => {
            loader.style.display = 'none';
            resetButton();
            resultDiv.innerHTML = `<span class="text-danger">Error: ${err}</span>`;
        });
    }

    function stopProcess() {
        fetch("/medias/stop_process/", {
            method: "POST",
            headers: { "X-CSRFToken": getCookie('csrftoken') }
        })
        .then(() => {
            Object.values(progressIntervals).forEach(interval => clearInterval(interval));
            if (pollingYOLO) clearInterval(pollingYOLO);
            if (pollingConsole) clearInterval(pollingConsole);

            loader.style.display = 'none';
            resetButton();
            resultDiv.innerHTML = '<span class="text-warning">⚠️ Process stopped</span>';
            taskId = null;
            isRunning = false;
        })
        .catch(() => {
            resultDiv.innerHTML = '<span class="text-danger">Error stopping process</span>';
        });
    }

    function resetButton() {
        btnToggle.innerHTML = '<i class="fas fa-dice"></i> Start Process';
        btnToggle.className = 'btn btn-info';
        isRunning = false;
    }

    btnToggle.addEventListener('click', function() {
        if (isRunning) {
            stopProcess();
        } else {
            startProcess();
        }
    });
});
