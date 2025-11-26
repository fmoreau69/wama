// Configuration
const csrfToken = '{{ csrf_token }}';

// Range sliders
document.getElementById('speed').addEventListener('input', (e) => {
    document.getElementById('speed_value').textContent = e.target.value;
});

document.getElementById('pitch').addEventListener('input', (e) => {
    document.getElementById('pitch_value').textContent = e.target.value;
});

document.getElementById('resetOptions').addEventListener('click', () => {
    document.getElementById('speed').value = 1.0;
    document.getElementById('pitch').value = 1.0;
    document.getElementById('speed_value').textContent = '1.0';
    document.getElementById('pitch_value').textContent = '1.0';
});

// Drag & Drop
const dropZone = document.getElementById('dropZone');
const fileInput = document.getElementById('fileInput');

dropZone.addEventListener('click', () => fileInput.click());
document.getElementById('browseBtn').addEventListener('click', (e) => {
    e.stopPropagation();
    fileInput.click();
});

dropZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropZone.classList.add('drag-over');
});

dropZone.addEventListener('dragleave', () => {
    dropZone.classList.remove('drag-over');
});

dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    handleFiles(e.dataTransfer.files);
});

fileInput.addEventListener('change', (e) => {
    handleFiles(e.target.files);
});

async function handleFiles(files) {
    for (const file of files) {
        await uploadFile(file);
    }
}

async function uploadFile(file) {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('tts_model', document.getElementById('tts_model').value);
    formData.append('language', document.getElementById('language').value);
    formData.append('voice_preset', document.getElementById('voice_preset').value);
    formData.append('speed', document.getElementById('speed').value);
    formData.append('pitch', document.getElementById('pitch').value);

    const voiceRef = document.getElementById('voice_reference').files[0];
    if (voiceRef) {
        formData.append('voice_reference', voiceRef);
    }

    try {
        const response = await fetch('{% url "synthesizer:upload" %}', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken },
            body: formData
        });

        const data = await response.json();

        if (response.ok) {
            location.reload();
        } else {
            alert('Erreur: ' + (data.error || 'Upload failed'));
        }
    } catch (error) {
        alert('Erreur de communication: ' + error.message);
    }
}

// Start synthesis
document.querySelectorAll('.start-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        const id = btn.dataset.id;
        try {
            const response = await fetch(`/wama_synthesizer/start/${id}/`, {
                method: 'GET',
                headers: { 'X-CSRFToken': csrfToken }
            });

            if (response.ok) {
                location.reload();
            }
        } catch (error) {
            alert('Erreur: ' + error.message);
        }
    });
});

// Preview
document.querySelectorAll('.preview-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const previewDiv = document.getElementById(`preview_${id}`);

        if (previewDiv.style.display === 'none') {
            previewDiv.style.display = 'block';
        } else {
            previewDiv.style.display = 'none';
        }
    });
});

// Delete
document.querySelectorAll('.delete-btn').forEach(btn => {
    btn.addEventListener('click', async () => {
        if (!confirm('Supprimer cette synthèse ?')) return;

        const id = btn.dataset.id;
        try {
            const response = await fetch(`/wama_synthesizer/delete/${id}/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': csrfToken }
            });

            if (response.ok) {
                location.reload();
            }
        } catch (error) {
            alert('Erreur: ' + error.message);
        }
    });
});

// Bulk actions
document.getElementById('startAllBtn').addEventListener('click', async () => {
    try {
        const response = await fetch('{% url "synthesizer:start_all" %}', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });

        if (response.ok) {
            location.reload();
        }
    } catch (error) {
        alert('Erreur: ' + error.message);
    }
});

document.getElementById('downloadAllBtn').addEventListener('click', () => {
    window.location.href = '{% url "synthesizer:download_all" %}';
});

document.getElementById('clearAllBtn').addEventListener('click', async () => {
    if (!confirm('Supprimer toutes les synthèses ?')) return;

    try {
        const response = await fetch('{% url "synthesizer:clear_all" %}', {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        });

        if (response.ok) {
            location.reload();
        }
    } catch (error) {
        alert('Erreur: ' + error.message);
    }
});

// Console toggle
document.getElementById('toggleConsole').addEventListener('click', () => {
    const console = document.getElementById('consoleContainer');
    console.style.display = console.style.display === 'none' ? 'block' : 'none';

    if (console.style.display === 'block') {
        updateConsole();
    }
});

async function updateConsole() {
    try {
        const response = await fetch('{% url "synthesizer:console" %}');
        const data = await response.json();

        const output = document.getElementById('consoleOutput');
        output.innerHTML = data.output.map(line => `<div>${line}</div>`).join('');
        output.scrollTop = output.scrollHeight;
    } catch (error) {
        console.error('Console update error:', error);
    }
}

// Auto-refresh progress
setInterval(async () => {
    const runningCards = document.querySelectorAll('.synthesis-card.processing');

    for (const card of runningCards) {
        const id = card.dataset.id;
        try {
            const response = await fetch(`/wama_synthesizer/progress/${id}/`);
            const data = await response.json();

            // Update progress bar
            const progressBar = card.querySelector('.progress-fill');
            const progressText = card.querySelector('.progress-bar-custom + small');
            if (progressBar && progressText) {
                progressBar.style.width = data.progress + '%';
                progressText.textContent = data.progress + '%';
            }

            // Reload if finished
            if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                location.reload();
            }
        } catch (error) {
            console.error('Progress update error:', error);
        }
    }
}, 2000);