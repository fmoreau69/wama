/**
 * WAMA Media Library — JS (Phase 2)
 * Search, pagination, preview modal, inline edit, badges.
 */

(function () {
    'use strict';

    // ── Config ────────────────────────────────────────────────────────────────

    const ALLOWED_EXT = {
        voice:       ['wav', 'mp3', 'flac', 'ogg', 'm4a'],
        audio_music: ['mp3', 'wav', 'flac', 'ogg', 'm4a', 'aac'],
        audio_sfx:   ['mp3', 'wav', 'ogg', 'flac', 'aiff'],
        image:       ['jpg', 'jpeg', 'png', 'gif', 'webp', 'bmp'],
        video:       ['mp4', 'webm', 'mov', 'avi', 'mkv'],
        document:    ['pdf', 'txt', 'docx', 'md', 'csv'],
        avatar:      ['jpg', 'jpeg', 'png', 'webp'],
    };
    const TYPE_HINTS = {
        voice:       'WAV, MP3, FLAC, OGG, M4A',
        audio_music: 'MP3, WAV, FLAC, OGG, M4A, AAC',
        audio_sfx:   'MP3, WAV, OGG, FLAC, AIFF',
        image:       'JPG, PNG, GIF, WEBP',
        video:       'MP4, WEBM, MOV',
        document:    'PDF, TXT, DOCX, MD, CSV',
        avatar:      'JPG, PNG, WEBP',
    };
    const TYPE_ICONS = {
        voice:       'fa-microphone',
        audio_music: 'fa-music',
        audio_sfx:   'fa-volume-up',
        image:       'fa-image',
        video:       'fa-film',
        document:    'fa-file-alt',
        avatar:      'fa-user-circle',
    };
    // Types qui utilisent un player audio
    const AUDIO_TYPES = ['voice', 'audio_music', 'audio_sfx'];

    // ── State ─────────────────────────────────────────────────────────────────

    let currentType          = document.querySelector('#assetTypeTabs .nav-link.active')?.dataset.type || 'voice';
    let currentPage          = 1;
    let hasMore              = false;
    let searchTimer          = null;
    let pendingFile          = null;
    let editingAsset         = null;
    let currentAssets        = [];   // assets visibles dans la grille (pour navigation)
    let currentSearchResults = [];   // résultats de recherche provider (pour navigation)

    // ── DOM ───────────────────────────────────────────────────────────────────

    const assetGrid       = document.getElementById('assetGrid');
    const searchInput     = document.getElementById('searchInput');
    const resultCount     = document.getElementById('resultCount');
    const loadMoreBtn     = document.getElementById('loadMoreBtn');
    const openUploadBtn   = document.getElementById('openUploadBtn');
    const uploadZoneWrap  = document.getElementById('uploadZoneWrap');
    const uploadZone      = document.getElementById('uploadZone');
    const uploadHint      = document.getElementById('uploadHint');
    const fileInput       = document.getElementById('fileInput');
    const uploadFormPanel = document.getElementById('uploadFormPanel');
    const uploadFileName  = document.getElementById('uploadFileName');
    const uploadProgress  = document.getElementById('uploadProgress');
    const assetNameInput  = document.getElementById('assetName');
    const assetDescInput  = document.getElementById('assetDescription');
    const assetTagsInput  = document.getElementById('assetTags');
    const confirmUploadBtn = document.getElementById('confirmUploadBtn');
    const cancelUploadBtn  = document.getElementById('cancelUploadBtn');

    const previewModal     = new bootstrap.Modal(document.getElementById('previewModal'));
    const editModal        = new bootstrap.Modal(document.getElementById('editModal'));

    // ── Toast ─────────────────────────────────────────────────────────────────

    function toast(msg, type = 'success') {
        const el   = document.getElementById('mlToast');
        const body = document.getElementById('mlToastBody');
        if (!el || !body) return;
        body.textContent = msg;
        el.className = `toast align-items-center text-white border-0 bg-${type === 'success' ? 'success' : 'danger'}`;
        bootstrap.Toast.getOrCreateInstance(el, { delay: 3000 }).show();
    }

    // ── Badges de comptage ────────────────────────────────────────────────────

    async function loadCounts() {
        try {
            const data = await (await fetch(ML_URLS.counts)).json();
            Object.entries(data.counts || {}).forEach(([type, n]) => {
                const badge = document.getElementById(`badge-${type}`);
                if (badge) badge.textContent = n || '0';
            });
        } catch (_) {}
    }

    // ── Panels ────────────────────────────────────────────────────────────────

    const libraryPanel = document.getElementById('assetGrid').parentElement
        .querySelector('.ml-toolbar')?.parentElement;  // container
    const searchPanel  = document.getElementById('searchPanel');

    function showLibraryMode() {
        document.querySelector('.ml-toolbar').style.display = '';
        document.getElementById('uploadZoneWrap').style.display =
            openUploadBtn.dataset.wasOpen ? 'block' : 'none';
        document.getElementById('assetGrid').style.display = '';
        document.getElementById('loadMoreBtn').parentElement.style.display = '';
        searchPanel.style.display = 'none';
    }

    function showSearchMode() {
        document.querySelector('.ml-toolbar').style.display = 'none';
        document.getElementById('uploadZoneWrap').style.display = 'none';
        document.getElementById('assetGrid').style.display = 'none';
        document.getElementById('loadMoreBtn').parentElement.style.display = 'none';
        searchPanel.style.display = 'block';
        loadProviderButtons();
    }

    // ── Onglets ───────────────────────────────────────────────────────────────

    document.querySelectorAll('#assetTypeTabs .nav-link').forEach(tab => {
        tab.addEventListener('click', e => {
            e.preventDefault();
            if (tab.dataset.type === currentType) return;
            document.querySelectorAll('#assetTypeTabs .nav-link').forEach(t => t.classList.remove('active'));
            tab.classList.add('active');
            currentType = tab.dataset.type;

            if (currentType === 'search') {
                showSearchMode();
            } else {
                showLibraryMode();
                uploadHint.textContent = TYPE_HINTS[currentType] || '';
                searchInput.value = '';
                resetUploadPanel();
                resetGrid();
                loadAssets(true);
            }
        });
    });

    // Init : si l'onglet actif est 'search', afficher le panneau recherche
    if (currentType === 'search') {
        showSearchMode();
    }

    // ── Recherche (debounce 300ms) ────────────────────────────────────────────

    searchInput.addEventListener('input', () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => { resetGrid(); loadAssets(true); }, 300);
    });

    // ── Bouton upload toggle ──────────────────────────────────────────────────

    openUploadBtn.addEventListener('click', () => {
        const visible = uploadZoneWrap.style.display !== 'none';
        uploadZoneWrap.style.display = visible ? 'none' : 'block';
        if (visible) resetUploadPanel();
    });

    // ── Chargement des assets ─────────────────────────────────────────────────

    function resetGrid() {
        currentPage = 1;
        hasMore     = false;
        loadMoreBtn.style.display = 'none';
        assetGrid.innerHTML = '';
    }

    async function loadAssets(showSpinner = false) {
        if (showSpinner) {
            assetGrid.innerHTML = `
                <div class="text-muted text-center w-100 py-5">
                    <i class="fas fa-spinner fa-spin fa-2x mb-2 d-block"></i>Chargement…
                </div>`;
        }

        const q = searchInput.value.trim();
        const params = new URLSearchParams({ type: currentType, page: currentPage });
        if (q) params.set('q', q);

        try {
            const [userResp, sysResp] = await Promise.all([
                fetch(`${ML_URLS.list}?${params}`),
                fetch(`${ML_URLS.systemList}?${params}`),
            ]);
            const userData = await userResp.json();
            const sysData  = await sysResp.json();

            const userAssets   = userData.assets || [];
            const systemAssets = sysData.assets  || [];
            const total        = (userData.total || 0) + (sysData.total || 0);

            hasMore = userData.has_more || sysData.has_more;
            loadMoreBtn.style.display = hasMore ? 'inline-block' : 'none';

            resultCount.textContent = total > 0 ? `${total} asset${total > 1 ? 's' : ''}` : '';

            if (currentPage === 1) {
                assetGrid.innerHTML = '';
            } else {
                assetGrid.querySelector('.empty-state')?.remove();
            }

            if (currentPage === 1 && userAssets.length === 0 && systemAssets.length === 0) {
                assetGrid.innerHTML = `
                    <div class="text-muted text-center w-100 py-5 empty-state">
                        <i class="fas fa-inbox fa-2x mb-2 d-block"></i>
                        ${q ? `Aucun résultat pour "<strong>${q}</strong>"` : 'Aucun asset. Utilisez le bouton + pour en ajouter.'}
                    </div>`;
                return;
            }

            // Assets système en premier (seulement page 1)
            if (currentPage === 1) {
                systemAssets.forEach(a => assetGrid.appendChild(buildCard(a, true)));
                currentAssets = [...systemAssets, ...userAssets].map(a => ({...a, _assetType: currentType}));
            } else {
                currentAssets = [...currentAssets, ...userAssets.map(a => ({...a, _assetType: currentType}))];
            }
            userAssets.forEach(a => assetGrid.appendChild(buildCard(a, false)));

        } catch (err) {
            assetGrid.innerHTML = `<div class="text-danger p-3">Erreur : ${err.message}</div>`;
        }
    }

    // ── Load more ─────────────────────────────────────────────────────────────

    loadMoreBtn.addEventListener('click', () => {
        currentPage++;
        loadAssets(false);
    });

    // ── Construction d'une carte ──────────────────────────────────────────────

    function buildCard(asset, isSystem) {
        const card = document.createElement('div');
        card.className = `asset-card${isSystem ? ' system-asset' : ''}`;
        card.dataset.id = asset.id;

        // Preview
        let previewHtml = '';
        let audioPlayerHtml = '';
        if (AUDIO_TYPES.includes(currentType) && asset.file_url) {
            // Audio : icône en zone preview (permet l'overlay), player dans le body
            const icon = TYPE_ICONS[currentType] || 'fa-music';
            previewHtml = `<div class="asset-preview-wrap" style="min-height:60px;">
                <i class="fas ${icon} asset-preview-icon"></i>
            </div>`;
            audioPlayerHtml = `<audio class="asset-preview-audio mt-1" controls src="${asset.file_url}" preload="none"></audio>`;
        } else if (['image', 'avatar'].includes(currentType) && asset.file_url) {
            previewHtml = `<div class="asset-preview-wrap">
                <img class="asset-preview-img" src="${asset.file_url}" alt="${esc(asset.name)}" loading="lazy">
            </div>`;
        } else if (currentType === 'video' && asset.file_url) {
            previewHtml = `<div class="asset-preview-wrap">
                <video class="asset-preview-video" src="${asset.file_url}" preload="none" muted></video>
            </div>`;
        } else {
            const icon = TYPE_ICONS[currentType] || 'fa-file';
            previewHtml = `<div class="asset-preview-wrap">
                <i class="fas ${icon} asset-preview-icon"></i>
            </div>`;
        }

        // Tags
        const tagsHtml = asset.tags
            ? asset.tags.split(',').map(t => t.trim()).filter(Boolean)
                .map(t => `<span class="asset-tag" data-tag="${esc(t)}">${esc(t)}</span>`).join('')
            : '';

        // Meta
        const metaParts = [];
        if (asset.file_size)  metaParts.push(`<span title="Taille"><i class="fas fa-hdd me-1"></i>${asset.file_size}</span>`);
        if (asset.duration)   metaParts.push(`<span title="Durée"><i class="fas fa-clock me-1"></i>${asset.duration}</span>`);
        if (asset.license)    metaParts.push(`<span class="text-success" title="Licence"><i class="fas fa-balance-scale me-1"></i>${asset.license}</span>`);
        if (asset.created_at) metaParts.push(`<span title="Ajouté le">${asset.created_at}</span>`);

        // Actions overlay
        const actionsHtml = `
            <div class="card-actions-overlay">
                ${asset.file_url ? `
                <button class="btn btn-sm btn-dark preview-btn" title="Aperçu" data-id="${asset.id}">
                    <i class="fas fa-expand"></i>
                </button>` : ''}
                ${!isSystem ? `
                <button class="btn btn-sm btn-dark edit-btn" title="Modifier" data-id="${asset.id}">
                    <i class="fas fa-pen"></i>
                </button>
                <button class="btn btn-sm btn-dark delete-btn" title="Supprimer" data-id="${asset.id}">
                    <i class="fas fa-trash-alt text-danger"></i>
                </button>` : ''}
                ${asset.file_url ? `
                <a class="btn btn-sm btn-dark" href="${asset.file_url}" download title="Télécharger">
                    <i class="fas fa-download"></i>
                </a>` : ''}
            </div>`;

        card.innerHTML = `
            ${isSystem ? '<span class="asset-badge-system"><i class="fas fa-lock me-1"></i>intégré</span>' : ''}
            ${actionsHtml}
            ${previewHtml}
            <div class="asset-card-body">
                <div class="asset-name" title="${esc(asset.name)}" data-id="${asset.id}">${esc(asset.name)}</div>
                ${audioPlayerHtml}
                ${asset.description ? `<div class="asset-meta text-truncate mt-1" title="${esc(asset.description)}">${esc(asset.description)}</div>` : ''}
                <div class="asset-meta">${metaParts.join(' · ')}</div>
                ${tagsHtml ? `<div class="asset-tags">${tagsHtml}</div>` : ''}
            </div>`;

        // Clic sur la zone preview → preview modal
        // Note : .asset-preview-video a pointer-events:none (couche GPU), on écoute le wrap parent
        card.querySelector('.asset-preview-wrap')?.addEventListener('click', () => openPreview(asset));
        // Clic sur le nom → preview aussi
        card.querySelector('.asset-name')?.addEventListener('click', () => openPreview(asset));
        // Bouton preview
        card.querySelector('.preview-btn')?.addEventListener('click', () => openPreview(asset));
        // Edit
        card.querySelector('.edit-btn')?.addEventListener('click', () => openEdit(asset, card));
        // Delete
        card.querySelector('.delete-btn')?.addEventListener('click', () => deleteAsset(asset.id, card));
        // Filtre par tag
        card.querySelectorAll('.asset-tag').forEach(tagEl => {
            tagEl.addEventListener('click', () => {
                searchInput.value = tagEl.dataset.tag;
                resetGrid();
                loadAssets(true);
            });
        });

        return card;
    }

    // ── Preview modal ─────────────────────────────────────────────────────────

    function assetToPreviewData(asset) {
        const assetType = asset._assetType || currentType;
        let mime = '';
        if (AUDIO_TYPES.includes(assetType)) {
            const ext = (asset.name || '').split('.').pop().toLowerCase();
            mime = ext === 'mp3' ? 'audio/mpeg' : ext === 'ogg' ? 'audio/ogg' : 'audio/wav';
        } else if (assetType === 'image' || assetType === 'avatar') {
            mime = 'image/jpeg';
        } else if (assetType === 'video') {
            mime = 'video/mp4';
        } else if (assetType === 'document') {
            const ext = (asset.name || '').split('.').pop().toLowerCase();
            const m = { pdf: 'application/pdf', txt: 'text/plain', md: 'text/plain', csv: 'text/plain' };
            mime = m[ext] || 'application/octet-stream';
        }
        return {
            url:        asset.file_url || '',
            name:       asset.name || '',
            mime_type:  mime,
            duration:   asset.duration || '',
            properties: asset.file_size || '',
        };
    }

    function searchResultToPreviewData(r) {
        // Note : base.py sérialise le download_url sous '_download_url' (préfixe _ = CDN public)
        let mime = '';
        let url  = '';
        if (r.asset_type === 'image' || r.asset_type === 'avatar') {
            mime = 'image/jpeg';
            url  = r.preview_url || '';
        } else if (AUDIO_TYPES.includes(r.asset_type)) {
            mime = 'audio/mpeg';
            url  = r.preview_url || r._download_url || '';
        } else if (r.asset_type === 'video') {
            // Préférer la vraie vidéo (meilleure UX) ; fallback vers thumbnail Vimeo
            if (r._download_url) {
                mime = 'video/mp4';
                url  = r._download_url;
            } else {
                mime = 'image/jpeg';
                url  = r.preview_url || '';
            }
        }
        return {
            url,
            name:       r.title || '',
            mime_type:  mime,
            duration:   r.duration ? `${Math.round(r.duration)}s` : '',
            properties: r.author || '',
        };
    }

    function openPreview(asset) {
        const idx = currentAssets.findIndex(a => a.id === asset.id);
        window.showPreviewModalWithNav(
            assetToPreviewData(asset),
            currentAssets.map(assetToPreviewData),
            idx >= 0 ? idx : 0
        );
    }

    // ── Edit modal ────────────────────────────────────────────────────────────

    function openEdit(asset, card) {
        editingAsset = { asset, card };
        document.getElementById('editAssetId').value = asset.id;
        document.getElementById('editName').value = asset.name;
        document.getElementById('editDescription').value = asset.description || '';
        document.getElementById('editTags').value = asset.tags || '';
        editModal.show();
    }

    document.getElementById('saveEditBtn').addEventListener('click', async () => {
        if (!editingAsset) return;
        const { asset, card } = editingAsset;
        const name  = document.getElementById('editName').value.trim();
        const desc  = document.getElementById('editDescription').value.trim();
        const tags  = document.getElementById('editTags').value.trim();

        if (!name) { document.getElementById('editName').focus(); return; }

        try {
            const resp = await fetch(`${ML_URLS.edit}${asset.id}/edit/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, description: desc, tags }),
            });
            const data = await resp.json();
            if (resp.ok) {
                editModal.hide();
                toast('Modifications enregistrées');
                updateCard(card, data);
                editingAsset = null;
                loadCounts();
            } else {
                toast(data.error || 'Erreur', 'error');
            }
        } catch (_) {
            toast('Erreur réseau', 'error');
        }
    });

    function updateCard(card, asset) {
        const nameEl = card.querySelector('.asset-name');
        if (nameEl) { nameEl.textContent = asset.name; nameEl.title = asset.name; }

        const descEl = card.querySelector('.asset-meta.text-truncate');
        if (descEl && asset.description) {
            descEl.textContent = asset.description;
            descEl.title = asset.description;
        }

        const tagsWrap = card.querySelector('.asset-tags');
        if (tagsWrap) {
            const tagsHtml = asset.tags
                ? asset.tags.split(',').map(t => t.trim()).filter(Boolean)
                    .map(t => `<span class="asset-tag" data-tag="${esc(t)}">${esc(t)}</span>`).join('')
                : '';
            tagsWrap.innerHTML = tagsHtml;
            tagsWrap.querySelectorAll('.asset-tag').forEach(tagEl => {
                tagEl.addEventListener('click', () => {
                    searchInput.value = tagEl.dataset.tag;
                    resetGrid();
                    loadAssets(true);
                });
            });
        }
    }

    // ── Suppression ───────────────────────────────────────────────────────────

    async function deleteAsset(id, card) {
        if (!confirm('Supprimer cet asset définitivement ?')) return;
        try {
            const resp = await fetch(`${ML_URLS.delete}${id}/delete/`, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF_TOKEN },
            });
            const data = await resp.json();
            if (resp.ok && data.deleted) {
                card.style.transition = 'opacity .25s';
                card.style.opacity = '0';
                setTimeout(() => {
                    card.remove();
                    if (assetGrid.querySelectorAll('.asset-card').length === 0) loadAssets(true);
                    loadCounts();
                }, 250);
                toast('Asset supprimé');
            } else {
                toast(data.error || 'Erreur', 'error');
            }
        } catch (_) {
            toast('Erreur réseau', 'error');
        }
    }

    // ── Upload ────────────────────────────────────────────────────────────────

    uploadZone.addEventListener('click', () => fileInput.click());
    fileInput.addEventListener('change', () => { if (fileInput.files[0]) openUploadForm(fileInput.files[0]); });

    uploadZone.addEventListener('dragover', e => { e.preventDefault(); uploadZone.classList.add('drag-over'); });
    uploadZone.addEventListener('dragleave', () => uploadZone.classList.remove('drag-over'));
    uploadZone.addEventListener('drop', e => {
        e.preventDefault();
        uploadZone.classList.remove('drag-over');
        if (e.dataTransfer.files[0]) openUploadForm(e.dataTransfer.files[0]);
    });

    function openUploadForm(file) {
        const ext = file.name.split('.').pop().toLowerCase();
        if (!(ALLOWED_EXT[currentType] || []).includes(ext)) {
            toast(`Format .${ext} non autorisé. Attendu : ${TYPE_HINTS[currentType]}`, 'error');
            return;
        }
        pendingFile = file;
        assetNameInput.value = file.name.replace(/\.[^.]+$/, '');
        uploadFileName.textContent = `${file.name} (${(file.size / 1024).toFixed(1)} Ko)`;
        uploadFormPanel.style.display = 'block';
        assetNameInput.focus();
        uploadZone.style.display = 'none';
    }

    cancelUploadBtn.addEventListener('click', resetUploadPanel);

    function resetUploadPanel() {
        pendingFile = null;
        uploadFormPanel.style.display = 'none';
        uploadZone.style.display = '';
        uploadProgress.style.display = 'none';
        assetNameInput.value = '';
        assetDescInput.value = '';
        assetTagsInput.value = '';
        uploadFileName.textContent = '';
        fileInput.value = '';
    }

    confirmUploadBtn.addEventListener('click', async () => {
        if (!pendingFile) return;
        const name = assetNameInput.value.trim();
        if (!name) { assetNameInput.focus(); return; }

        const fd = new FormData();
        fd.append('file', pendingFile);
        fd.append('name', name);
        fd.append('asset_type', currentType);
        fd.append('description', assetDescInput.value.trim());
        fd.append('tags', assetTagsInput.value.trim());

        confirmUploadBtn.disabled = true;
        uploadProgress.style.display = 'block';

        try {
            const resp = await fetch(ML_URLS.upload, {
                method: 'POST',
                headers: { 'X-CSRFToken': CSRF_TOKEN },
                body: fd,
            });
            const data = await resp.json();
            if (resp.ok && data.id) {
                toast(`"${data.name}" enregistré`);
                resetUploadPanel();
                uploadZoneWrap.style.display = 'none';
                // Insérer la carte en tête des assets utilisateur
                const firstUserCard = assetGrid.querySelector('.asset-card:not(.system-asset)');
                const newCard = buildCard(data, false);
                if (firstUserCard) assetGrid.insertBefore(newCard, firstUserCard);
                else assetGrid.appendChild(newCard);
                assetGrid.querySelector('.empty-state')?.remove();
                loadCounts();
            } else {
                toast(data.error || "Erreur lors de l'upload", 'error');
            }
        } catch (_) {
            toast('Erreur réseau', 'error');
        } finally {
            confirmUploadBtn.disabled = false;
            uploadProgress.style.display = 'none';
        }
    });

    // ── Provider search ───────────────────────────────────────────────────────

    let currentProvider   = null;
    let providerPage      = 1;
    let providerHasMore   = false;
    let providerSearchTimer = null;
    let allProviders      = [];

    async function loadProviderButtons() {
        const container = document.getElementById('providerButtons');
        if (!container) return;
        if (allProviders.length > 0) { renderProviderButtons(); return; }

        try {
            const data = await (await fetch(ML_URLS.providers)).json();
            allProviders = data.providers || [];
            renderProviderButtons();
        } catch (_) {
            container.innerHTML = '<span class="text-danger small">Erreur chargement providers</span>';
        }
    }

    function renderProviderButtons() {
        const container  = document.getElementById('providerButtons');
        const typeSelect = document.getElementById('providerTypeSelect');
        const selType    = typeSelect ? typeSelect.value : '';

        const filtered = allProviders.filter(p =>
            !selType || (p.supported_types || []).includes(selType)
        );

        if (filtered.length === 0) {
            container.innerHTML = '<span class="text-muted small">Aucun provider pour ce type.</span>';
            currentProvider = null;
            return;
        }

        container.innerHTML = filtered.map(p => `
            <button class="provider-btn ${p.has_key ? 'ready' : ''} ${currentProvider === p.slug ? 'active' : ''}"
                    data-slug="${p.slug}" title="${esc(p.description)}">
                <span class="provider-dot"></span>
                ${esc(p.name)}
                ${!p.has_key && p.requires_api_key
                    ? '<i class="fas fa-key ms-1 text-warning" title="Clé API requise"></i>' : ''}
            </button>
        `).join('');

        container.querySelectorAll('.provider-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                currentProvider = btn.dataset.slug;
                renderProviderButtons();
            });
        });

        // Sélection auto du premier provider ready si aucun actif
        if (!currentProvider || !filtered.find(p => p.slug === currentProvider)) {
            const first = filtered.find(p => p.has_key) || filtered[0];
            if (first) {
                currentProvider = first.slug;
                renderProviderButtons();
            }
        }
    }

    // Quand le type change dans la recherche, recharger les providers filtrés
    document.getElementById('providerTypeSelect')?.addEventListener('change', () => {
        allProviders = [];  // force refresh
        currentProvider = null;
        loadProviderButtons();
        document.getElementById('searchResultGrid').innerHTML = '';
        document.getElementById('providerResultCount').textContent = '';
    });

    document.getElementById('providerSearchBtn')?.addEventListener('click', () => {
        providerPage = 1;
        runProviderSearch(true);
    });

    document.getElementById('providerSearchInput')?.addEventListener('keydown', e => {
        if (e.key === 'Enter') { providerPage = 1; runProviderSearch(true); }
    });

    document.getElementById('loadMoreSearchBtn')?.addEventListener('click', () => {
        providerPage++;
        runProviderSearch(false);
    });

    async function runProviderSearch(reset) {
        const q        = document.getElementById('providerSearchInput').value.trim();
        const type     = document.getElementById('providerTypeSelect').value;
        const grid     = document.getElementById('searchResultGrid');
        const countEl  = document.getElementById('providerResultCount');
        const moreBtn  = document.getElementById('loadMoreSearchBtn');

        if (!currentProvider) { toast('Sélectionnez une source', 'error'); return; }
        if (!q) { document.getElementById('providerSearchInput').focus(); return; }

        if (reset) {
            grid.innerHTML = `<div class="text-muted text-center w-100 py-5" style="grid-column:1/-1;">
                <i class="fas fa-spinner fa-spin fa-2x mb-2 d-block"></i>Recherche en cours…</div>`;
            moreBtn.style.display = 'none';
            currentSearchResults = [];
        }

        const params = new URLSearchParams({
            provider: currentProvider, type, q, page: providerPage,
        });

        try {
            const data = await (await fetch(`${ML_URLS.providerSearch}?${params}`)).json();

            if (data.error && !data.results?.length) {
                grid.innerHTML = `<div class="text-warning p-3" style="grid-column:1/-1;">${esc(data.error)}</div>`;
                return;
            }

            if (reset) grid.innerHTML = '';

            const results = data.results || [];
            providerHasMore = data.has_more;
            moreBtn.style.display = providerHasMore ? 'inline-block' : 'none';
            countEl.textContent   = data.total ? `${data.total} résultat${data.total > 1 ? 's' : ''}` : '';

            if (reset && results.length === 0) {
                grid.innerHTML = `<div class="text-muted text-center w-100 py-5" style="grid-column:1/-1;">
                    <i class="fas fa-inbox fa-2x mb-2 d-block"></i>Aucun résultat pour "${esc(q)}".</div>`;
                return;
            }

            results.forEach(r => grid.appendChild(buildSearchCard(r)));
            currentSearchResults = [...currentSearchResults, ...results];

        } catch (err) {
            grid.innerHTML = `<div class="text-danger p-3" style="grid-column:1/-1;">Erreur : ${esc(err.message)}</div>`;
        }
    }

    function buildSearchCard(r) {
        const card = document.createElement('div');
        card.className = 'sr-card';

        let thumbHtml = '';
        if (r.asset_type === 'image' || r.asset_type === 'avatar') {
            thumbHtml = `<img class="sr-thumb" src="${r.preview_url}" alt="${esc(r.title)}" loading="lazy">`;
        } else if (AUDIO_TYPES.includes(r.asset_type)) {
            const icon = TYPE_ICONS[r.asset_type] || 'fa-music';
            thumbHtml = r.preview_url
                ? `<audio class="sr-thumb-audio" controls src="${r.preview_url}" preload="none"></audio>`
                : `<div class="sr-thumb-icon"><i class="fas ${icon}"></i></div>`;
        } else if (r.asset_type === 'video') {
            thumbHtml = r.preview_url
                ? `<img class="sr-thumb" src="${r.preview_url}" alt="${esc(r.title)}" loading="lazy">`
                : `<div class="sr-thumb-icon"><i class="fas fa-film"></i></div>`;
        } else {
            thumbHtml = `<div class="sr-thumb-icon"><i class="fas ${TYPE_ICONS[r.asset_type] || 'fa-file'}"></i></div>`;
        }

        const meta = [];
        if (r.author)   meta.push(esc(r.author));
        if (r.duration) meta.push(`${Math.round(r.duration)}s`);
        if (r.width)    meta.push(`${r.width}×${r.height}`);

        card.innerHTML = `
            ${thumbHtml}
            <button class="btn btn-sm btn-primary sr-import-btn" title="Importer dans ma médiathèque">
                <i class="fas fa-plus"></i>
            </button>
            <div class="sr-body">
                <div class="sr-title" title="${esc(r.title)}">${esc(r.title)}</div>
                <div class="sr-meta">
                    ${r.license ? `<span class="sr-license">${esc(r.license)}</span> ` : ''}
                    ${meta.join(' · ')}
                </div>
            </div>`;

        card.querySelector('.sr-import-btn').addEventListener('click', () => importSearchResult(r, card));

        // Clic sur la carte (hors bouton import) → preview avec navigation
        // Toujours actif : on peut avoir un _download_url même sans preview_url (vidéos sans thumb)
        const hasPreview = r.preview_url || r._download_url;
        if (hasPreview) {
            card.style.cursor = 'pointer';
            card.addEventListener('click', e => {
                if (e.target.closest('.sr-import-btn')) return;
                const idx = currentSearchResults.indexOf(r);
                window.showPreviewModalWithNav(
                    searchResultToPreviewData(r),
                    currentSearchResults.map(searchResultToPreviewData),
                    idx >= 0 ? idx : 0
                );
            });
        }

        return card;
    }

    async function importSearchResult(r, card) {
        const btn = card.querySelector('.sr-import-btn');
        btn.disabled = true;
        btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';

        try {
            const resp = await fetch(ML_URLS.providerDownload, {
                method:  'POST',
                headers: { 'X-CSRFToken': CSRF_TOKEN, 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    provider:      currentProvider,
                    provider_id:   r.provider_id,
                    title:         r.title,
                    asset_type:    r.asset_type,
                    license:       r.license,
                    author:        r.author,
                    tags:          r.tags,
                    _download_url: r._download_url,
                }),
            });
            const data = await resp.json();
            if (resp.ok && data.id) {
                btn.innerHTML = '<i class="fas fa-check"></i>';
                btn.className = 'btn btn-sm btn-success sr-import-btn';
                toast(`"${data.name}" importé dans votre médiathèque`);
                loadCounts();
            } else {
                btn.disabled = false;
                btn.innerHTML = '<i class="fas fa-plus"></i>';
                toast(data.error || 'Erreur import', 'error');
            }
        } catch (_) {
            btn.disabled = false;
            btn.innerHTML = '<i class="fas fa-plus"></i>';
            toast('Erreur réseau', 'error');
        }
    }

    // ── Utilitaires ───────────────────────────────────────────────────────────

    function esc(str) {
        return String(str ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ── Init ──────────────────────────────────────────────────────────────────

    loadCounts();
    if (currentType !== 'search') {
        loadAssets(true);
    }

})();
