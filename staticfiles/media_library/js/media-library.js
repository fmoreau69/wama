/**
 * WAMA Media Library — JS
 * Gestion des assets réutilisables (voix, images, vidéos, documents, avatars).
 */

(function () {
    'use strict';

    // ── Config ────────────────────────────────────────────────────────────────

    const ALLOWED_EXTENSIONS = {
        voice:    ['wav', 'mp3', 'flac', 'ogg', 'm4a'],
        image:    ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'],
        video:    ['mp4', 'webm', 'mov', 'avi', 'mkv'],
        document: ['pdf', 'txt', 'docx', 'md', 'csv'],
        avatar:   ['jpg', 'jpeg', 'png', 'webp'],
    };

    const TYPE_HINTS = {
        voice:    'WAV, MP3, FLAC, OGG, M4A',
        image:    'JPG, PNG, GIF, WEBP',
        video:    'MP4, WEBM, MOV',
        document: 'PDF, TXT, DOCX, MD, CSV',
        avatar:   'JPG, PNG, WEBP',
    };

    const TYPE_ICONS = {
        voice:    'fa-microphone',
        image:    'fa-image',
        video:    'fa-film',
        document: 'fa-file-alt',
        avatar:   'fa-user-circle',
    };

    // ── State ─────────────────────────────────────────────────────────────────

    let currentType = document.querySelector('#assetTypeTabs .nav-link.active')?.dataset.type || 'voice';
    let pendingFile = null;

    // ── DOM refs ──────────────────────────────────────────────────────────────

    const assetGrid      = document.getElementById('assetGrid');
    const uploadZone     = document.getElementById('uploadZone');
    const uploadHint     = document.getElementById('uploadHint');
    const fileInput      = document.getElementById('fileInput');
    const uploadForm     = document.getElementById('uploadForm');
    const uploadFileName = document.getElementById('uploadFileName');
    const uploadProgress = document.getElementById('uploadProgress');
    const assetName      = document.getElementById('assetName');
    const assetDesc      = document.getElementById('assetDescription');
    const assetTags      = document.getElementById('assetTags');
    const confirmBtn     = document.getElementById('confirmUploadBtn');
    const cancelBtn      = document.getElementById('cancelUploadBtn');

    // ── Toast ─────────────────────────────────────────────────────────────────

    function showToast(msg, type = 'success') {
        const el = document.getElementById('mlToast');
        const body = document.getElementById('mlToastBody');
        if (!el || !body) return;
        body.textContent = msg;
        el.className = `toast align-items-center text-white border-0 bg-${type === 'success' ? 'success' : 'danger'}`;
        bootstrap.Toast.getOrCreateInstance(el, { delay: 3000 }).show();
    }

    // ── Tab switching ─────────────────────────────────────────────────────────

    document.querySelectorAll('#assetTypeTabs .nav-link').forEach(tab => {
        tab.addEventListener('click', e => {
            e.preventDefault();
            document.querySelectorAll('#assetTypeTabs .nav-link').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentType = tab.dataset.type;
            uploadHint.textContent = TYPE_HINTS[currentType] || '';
            fileInput.value = '';
            resetUploadForm();
            loadAssets();
        });
    });

    // ── Load assets ───────────────────────────────────────────────────────────

    async function loadAssets() {
        assetGrid.innerHTML = `
            <div class="text-muted text-center w-100 py-5">
                <i class="fas fa-spinner fa-spin fa-2x mb-2 d-block"></i>
                Chargement…
            </div>`;

        try {
            const [userResp, sysResp] = await Promise.all([
                fetch(`${ML_URLS.list}?type=${currentType}`),
                fetch(`${ML_URLS.systemList}?type=${currentType}`),
            ]);
            const userData = await userResp.json();
            const sysData  = await sysResp.json();

            const userAssets   = userData.assets || [];
            const systemAssets = sysData.assets  || [];

            if (userAssets.length === 0 && systemAssets.length === 0) {
                assetGrid.innerHTML = `
                    <div class="text-muted text-center w-100 py-5">
                        <i class="fas fa-inbox fa-2x mb-2 d-block"></i>
                        Aucun asset de ce type. Utilisez la zone d'upload ci-dessus.
                    </div>`;
                return;
            }

            assetGrid.innerHTML = '';

            // Assets système en premier
            systemAssets.forEach(a => assetGrid.appendChild(buildCard(a, true)));
            userAssets.forEach(a => assetGrid.appendChild(buildCard(a, false)));

        } catch (err) {
            assetGrid.innerHTML = `<div class="text-danger">Erreur : ${err.message}</div>`;
        }
    }

    // ── Build asset card ──────────────────────────────────────────────────────

    function buildCard(asset, isSystem) {
        const card = document.createElement('div');
        card.className = `asset-card${isSystem ? ' system-asset' : ''}`;
        card.dataset.id = asset.id;

        let previewHtml = '';
        if (currentType === 'voice' && asset.file_url) {
            previewHtml = `<audio class="asset-preview-audio" controls src="${asset.file_url}" preload="none"></audio>`;
        } else if (currentType === 'image' && asset.file_url) {
            previewHtml = `<img class="asset-preview-img" src="${asset.file_url}" alt="${asset.name}" loading="lazy">`;
        } else if (currentType === 'avatar' && asset.file_url) {
            previewHtml = `<img class="asset-preview-img" src="${asset.file_url}" alt="${asset.name}" loading="lazy">`;
        } else if (currentType === 'video' && asset.file_url) {
            previewHtml = `<video class="asset-preview-img" src="${asset.file_url}" preload="none" controls muted></video>`;
        }

        const metaParts = [];
        if (asset.file_size)  metaParts.push(`<span><i class="fas fa-hdd"></i> ${asset.file_size}</span>`);
        if (asset.duration)   metaParts.push(`<span><i class="fas fa-clock"></i> ${asset.duration}</span>`);
        if (asset.license)    metaParts.push(`<span class="text-success"><i class="fas fa-balance-scale"></i> ${asset.license}</span>`);

        const deleteBtn = !isSystem
            ? `<button class="btn btn-outline-danger btn-sm ms-auto delete-btn" title="Supprimer">
                <i class="fas fa-trash-alt"></i>
               </button>`
            : '';

        card.innerHTML = `
            ${isSystem ? '<span class="asset-badge-system"><i class="fas fa-lock"></i> intégré</span>' : ''}
            ${previewHtml}
            <div class="asset-card-body">
                <div class="asset-card-name" title="${asset.name}">${asset.name}</div>
                <div class="asset-card-meta">${metaParts.join(' ')}</div>
                <div class="asset-card-actions">
                    ${asset.file_url
                        ? `<a href="${asset.file_url}" class="btn btn-outline-secondary btn-sm" download title="Télécharger">
                            <i class="fas fa-download"></i>
                           </a>`
                        : ''}
                    ${deleteBtn}
                </div>
            </div>`;

        if (!isSystem) {
            card.querySelector('.delete-btn')?.addEventListener('click', () => deleteAsset(asset.id, card));
        }

        return card;
    }

    // ── Delete ────────────────────────────────────────────────────────────────

    async function deleteAsset(id, card) {
        if (!confirm('Supprimer cet asset définitivement ?')) return;
        try {
            const resp = await fetch(`${ML_URLS.delete}${id}/delete/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF_TOKEN },
            });
            const data = await resp.json();
            if (resp.ok && data.deleted) {
                card.remove();
                showToast('Asset supprimé');
                if (assetGrid.querySelectorAll('.asset-card').length === 0) loadAssets();
            } else {
                showToast(data.error || 'Erreur lors de la suppression', 'error');
            }
        } catch (err) {
            showToast('Erreur réseau', 'error');
        }
    }

    // ── Upload — sélection fichier ────────────────────────────────────────────

    fileInput.addEventListener('change', () => {
        if (fileInput.files.length > 0) openUploadForm(fileInput.files[0]);
    });

    // Drag & drop
    uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
    uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
    uploadZone.addEventListener('drop', e => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
        const file = e.dataTransfer.files[0];
        if (file) openUploadForm(file);
    });

    function openUploadForm(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        const allowed = ALLOWED_EXTENSIONS[currentType] || [];
        if (!allowed.includes(ext)) {
            showToast(`Format .${ext} non autorisé pour ce type. Attendu : ${TYPE_HINTS[currentType]}`, 'error');
            return;
        }
        pendingFile = file;
        assetName.value = file.name.replace(/\.[^.]+$/, '');
        uploadFileName.textContent = `Fichier : ${file.name} (${(file.size / 1024).toFixed(1)} Ko)`;
        uploadForm.style.display = 'block';
        assetName.focus();
    }

    cancelBtn.addEventListener('click', resetUploadForm);

    function resetUploadForm() {
        pendingFile = null;
        uploadForm.style.display = 'none';
        uploadProgress.style.display = 'none';
        assetName.value = '';
        assetDesc.value = '';
        assetTags.value = '';
        uploadFileName.textContent = '';
        fileInput.value = '';
    }

    // ── Upload — confirmation ─────────────────────────────────────────────────

    confirmBtn.addEventListener('click', async () => {
        if (!pendingFile) return;
        const name = assetName.value.trim();
        if (!name) { assetName.focus(); return; }

        const formData = new FormData();
        formData.append('file', pendingFile);
        formData.append('name', name);
        formData.append('asset_type', currentType);
        formData.append('description', assetDesc.value.trim());
        formData.append('tags', assetTags.value.trim());

        confirmBtn.disabled = true;
        uploadProgress.style.display = 'block';

        try {
            const resp = await fetch(ML_URLS.upload, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF_TOKEN },
                body: formData,
            });
            const data = await resp.json();

            if (resp.ok && data.id) {
                showToast(`"${data.name}" enregistré`);
                resetUploadForm();
                const firstCard = assetGrid.querySelector('.asset-card:not(.system-asset)');
                const newCard   = buildCard(data, false);
                if (firstCard) {
                    assetGrid.insertBefore(newCard, firstCard);
                } else {
                    assetGrid.appendChild(newCard);
                }
                assetGrid.querySelector('.text-center.w-100')?.remove();
            } else {
                showToast(data.error || 'Erreur lors de l\'upload', 'error');
            }
        } catch (err) {
            showToast('Erreur réseau', 'error');
        } finally {
            confirmBtn.disabled = false;
            uploadProgress.style.display = 'none';
        }
    });

    // ── Init ──────────────────────────────────────────────────────────────────

    loadAssets();

})();
