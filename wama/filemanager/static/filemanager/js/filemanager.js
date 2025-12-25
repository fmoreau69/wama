/**
 * WAMA FileManager - jstree integration with dark theme
 */
(function() {
    'use strict';

    const config = window.FILEMANAGER_CONFIG || {};
    const csrfToken = config.csrfToken || '';

    // State
    let tree = null;
    let isOpen = false;

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', init);

    function init() {
        // Check if jstree is available
        if (typeof $.jstree === 'undefined') {
            console.error('jstree not loaded');
            return;
        }

        setupToggleButton();
        setupSidebar();
        initJstree();
        setupSearch();
        setupUploadDropzone();
        setupPreviewModal();
    }

    function setupToggleButton() {
        const toggleBtn = document.getElementById('filemanager-toggle');
        if (!toggleBtn) return;

        toggleBtn.addEventListener('click', toggleSidebar);
    }

    function setupSidebar() {
        const sidebar = document.getElementById('filemanager-sidebar');
        if (!sidebar) return;

        // Close button
        const closeBtn = sidebar.querySelector('.btn-close-sidebar');
        if (closeBtn) {
            closeBtn.addEventListener('click', closeSidebar);
        }

        // Refresh button
        const refreshBtn = sidebar.querySelector('.btn-refresh');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', refreshTree);
        }
    }

    function toggleSidebar() {
        const sidebar = document.getElementById('filemanager-sidebar');
        const toggleBtn = document.getElementById('filemanager-toggle');

        if (!sidebar) return;

        isOpen = !isOpen;

        if (isOpen) {
            sidebar.classList.add('open');
            toggleBtn.classList.add('sidebar-open');
            toggleBtn.innerHTML = '<i class="fas fa-times"></i>';
            document.body.classList.add('filemanager-open');
            // Refresh tree when opening
            if (tree) {
                refreshTree();
            }
        } else {
            sidebar.classList.remove('open');
            toggleBtn.classList.remove('sidebar-open');
            toggleBtn.innerHTML = '<i class="fas fa-folder-open"></i>';
            document.body.classList.remove('filemanager-open');
        }
    }

    function closeSidebar() {
        const sidebar = document.getElementById('filemanager-sidebar');
        const toggleBtn = document.getElementById('filemanager-toggle');

        if (sidebar) {
            sidebar.classList.remove('open');
            isOpen = false;
        }
        if (toggleBtn) {
            toggleBtn.classList.remove('sidebar-open');
            toggleBtn.innerHTML = '<i class="fas fa-folder-open"></i>';
        }
        document.body.classList.remove('filemanager-open');
    }

    function initJstree() {
        const treeContainer = document.getElementById('filemanager-tree');
        if (!treeContainer) return;

        $(treeContainer).jstree({
            'core': {
                'themes': {
                    'name': 'default-dark',
                    'responsive': true,
                    'dots': false,
                    'icons': true
                },
                'data': {
                    'url': config.apiTreeUrl || '/filemanager/api/tree/',
                    'dataType': 'json'
                },
                'check_callback': true,
                'multiple': true
            },
            'plugins': ['contextmenu', 'search', 'wholerow', 'dnd', 'types'],
            'types': {
                'folder': {
                    'icon': 'fa fa-folder text-warning'
                },
                'file': {
                    'icon': 'fa fa-file text-secondary'
                }
            },
            'contextmenu': {
                'items': contextMenuItems
            },
            'search': {
                'show_only_matches': true,
                'show_only_matches_children': true
            },
            'dnd': {
                'is_draggable': function(nodes) {
                    // Only files can be dragged
                    return nodes.every(n => n.type === 'file');
                },
                'copy': true,
                'use_html5': true
            }
        });

        tree = $(treeContainer).jstree(true);

        // Event handlers
        $(treeContainer).on('dblclick.jstree', '.jstree-anchor', handleDoubleClick);
        $(treeContainer).on('loaded.jstree', handleTreeLoaded);

        // Setup external drag & drop
        setupExternalDragDrop(treeContainer);
    }

    function contextMenuItems(node) {
        const items = {};

        if (node.type === 'file') {
            items.preview = {
                label: '<i class="fa fa-eye"></i> Aperçu',
                action: function() { previewFile(node); }
            };
            items.download = {
                label: '<i class="fa fa-download"></i> Télécharger',
                action: function() { downloadFile(node); }
            };
            items.info = {
                label: '<i class="fa fa-info-circle"></i> Informations',
                action: function() { showFileInfo(node); }
            };
            items.separator1 = { separator: true };
            items.rename = {
                label: '<i class="fa fa-edit"></i> Renommer',
                action: function() { renameFile(node); }
            };
            items.delete = {
                label: '<i class="fa fa-trash text-danger"></i> Supprimer',
                action: function() { deleteFile(node); }
            };
        } else if (node.type === 'folder') {
            items.refresh = {
                label: '<i class="fa fa-sync"></i> Actualiser',
                action: function() { refreshTree(); }
            };
        }

        return items;
    }

    function handleDoubleClick(e) {
        const node = tree.get_node(e.target);
        if (node && node.type === 'file') {
            previewFile(node);
        }
    }

    function handleTreeLoaded() {
        console.log('FileManager tree loaded');
    }

    function refreshTree() {
        if (tree) {
            tree.refresh();
        }
    }

    // === FILE OPERATIONS ===

    function previewFile(node) {
        const path = node.data?.path;
        if (!path) return;

        fetch(`${config.apiPreviewUrl || '/filemanager/api/preview/'}?path=${encodeURIComponent(path)}`)
            .then(res => res.json())
            .then(data => {
                if (data.preview_url) {
                    showPreviewModal(data);
                } else {
                    showToast('Aperçu non disponible pour ce type de fichier', 'warning');
                }
            })
            .catch(err => {
                console.error('Preview error:', err);
                showToast('Erreur lors du chargement de l\'aperçu', 'danger');
            });
    }

    function downloadFile(node) {
        const path = node.data?.path;
        if (!path) return;

        const downloadUrl = `${config.apiDownloadUrl || '/filemanager/api/download/'}${path}`;
        window.location.href = downloadUrl;
    }

    function showFileInfo(node) {
        const path = node.data?.path;
        if (!path) return;

        fetch(`${config.apiInfoUrl || '/filemanager/api/info/'}?path=${encodeURIComponent(path)}`)
            .then(res => res.json())
            .then(data => {
                if (data.error) {
                    showToast(data.error, 'danger');
                    return;
                }
                showInfoModal(data);
            })
            .catch(err => {
                console.error('Info error:', err);
                showToast('Erreur lors du chargement des informations', 'danger');
            });
    }

    function renameFile(node) {
        const path = node.data?.path;
        const currentName = node.text;
        if (!path) return;

        const newName = prompt('Nouveau nom:', currentName);
        if (!newName || newName === currentName) return;

        fetch(config.apiRenameUrl || '/filemanager/api/rename/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ path: path, new_name: newName })
        })
            .then(res => res.json())
            .then(data => {
                if (data.renamed) {
                    showToast('Fichier renommé avec succès', 'success');
                    refreshTree();
                } else {
                    showToast(data.error || 'Erreur lors du renommage', 'danger');
                }
            })
            .catch(err => {
                console.error('Rename error:', err);
                showToast('Erreur lors du renommage', 'danger');
            });
    }

    function deleteFile(node) {
        const path = node.data?.path;
        if (!path) return;

        if (!confirm(`Supprimer "${node.text}" ?`)) return;

        fetch(config.apiDeleteUrl || '/filemanager/api/delete/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ path: path })
        })
            .then(res => res.json())
            .then(data => {
                if (data.deleted) {
                    showToast('Fichier supprimé', 'success');
                    tree.delete_node(node);
                } else {
                    showToast(data.error || 'Erreur lors de la suppression', 'danger');
                }
            })
            .catch(err => {
                console.error('Delete error:', err);
                showToast('Erreur lors de la suppression', 'danger');
            });
    }

    // === SEARCH ===

    function setupSearch() {
        const searchInput = document.getElementById('filemanager-search');
        if (!searchInput) return;

        let searchTimeout = null;

        searchInput.addEventListener('input', function() {
            clearTimeout(searchTimeout);
            const query = this.value.trim();

            searchTimeout = setTimeout(function() {
                if (tree) {
                    tree.search(query);
                }
            }, 300);
        });
    }

    // === UPLOAD DROPZONE ===

    function setupUploadDropzone() {
        const dropzone = document.getElementById('filemanager-dropzone');
        if (!dropzone) return;

        const fileInput = document.createElement('input');
        fileInput.type = 'file';
        fileInput.multiple = true;
        fileInput.style.display = 'none';
        document.body.appendChild(fileInput);

        dropzone.addEventListener('click', () => fileInput.click());

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('drag-over');
        });

        dropzone.addEventListener('drop', (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');
            handleFileUpload(e.dataTransfer.files);
        });

        fileInput.addEventListener('change', (e) => {
            handleFileUpload(e.target.files);
            fileInput.value = '';
        });
    }

    function handleFileUpload(files) {
        if (!files.length) return;

        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
            formData.append('files', files[i]);
        }

        showToast(`Upload de ${files.length} fichier(s)...`, 'info');

        fetch(config.apiUploadUrl || '/filemanager/api/upload/', {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            },
            body: formData
        })
            .then(res => res.json())
            .then(data => {
                if (data.count > 0) {
                    showToast(`${data.count} fichier(s) uploadé(s)`, 'success');
                    refreshTree();
                } else {
                    showToast('Aucun fichier uploadé', 'warning');
                }
            })
            .catch(err => {
                console.error('Upload error:', err);
                showToast('Erreur lors de l\'upload', 'danger');
            });
    }

    // === EXTERNAL DRAG & DROP ===

    function setupExternalDragDrop(treeContainer) {
        // Make files draggable to external drop zones
        $(treeContainer).on('dragstart', '.jstree-anchor', function(e) {
            const node = tree.get_node(e.target);
            if (node && node.type === 'file' && node.data?.path) {
                e.originalEvent.dataTransfer.setData('text/plain', node.data.path);
                e.originalEvent.dataTransfer.setData('application/x-wama-file', JSON.stringify({
                    path: node.data.path,
                    name: node.text,
                    mime: node.data.mime
                }));
                e.originalEvent.dataTransfer.effectAllowed = 'copy';
            }
        });
    }

    // === MODALS ===

    function setupPreviewModal() {
        // Modal will be created dynamically
    }

    function showPreviewModal(data) {
        let modal = document.getElementById('filePreviewModal');

        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'filePreviewModal';
            modal.className = 'modal fade';
            modal.innerHTML = `
                <div class="modal-dialog modal-lg modal-dialog-centered">
                    <div class="modal-content bg-dark text-white">
                        <div class="modal-header border-secondary">
                            <h5 class="modal-title"></h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <div class="preview-container"></div>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        const title = modal.querySelector('.modal-title');
        const container = modal.querySelector('.preview-container');

        title.textContent = data.name;

        if (data.mime.startsWith('image/')) {
            container.innerHTML = `<img src="${data.preview_url}" alt="${data.name}">`;
        } else if (data.mime.startsWith('video/')) {
            container.innerHTML = `<video src="${data.preview_url}" controls autoplay></video>`;
        } else if (data.mime.startsWith('audio/')) {
            container.innerHTML = `<audio src="${data.preview_url}" controls autoplay></audio>`;
        } else {
            container.innerHTML = `<p class="text-muted">Aperçu non disponible</p>`;
        }

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    function showInfoModal(data) {
        let modal = document.getElementById('fileInfoModal');

        if (!modal) {
            modal = document.createElement('div');
            modal.id = 'fileInfoModal';
            modal.className = 'modal fade';
            modal.innerHTML = `
                <div class="modal-dialog modal-dialog-centered">
                    <div class="modal-content bg-dark text-white">
                        <div class="modal-header border-secondary">
                            <h5 class="modal-title">Informations</h5>
                            <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>
                        </div>
                        <div class="modal-body">
                            <table class="file-info-table"></table>
                        </div>
                    </div>
                </div>
            `;
            document.body.appendChild(modal);
        }

        const table = modal.querySelector('.file-info-table');
        table.innerHTML = `
            <tr><td>Nom</td><td>${escapeHtml(data.name)}</td></tr>
            <tr><td>Chemin</td><td>${escapeHtml(data.path)}</td></tr>
            <tr><td>Type</td><td>${escapeHtml(data.mime)}</td></tr>
            <tr><td>Taille</td><td>${formatFileSize(data.size)}</td></tr>
            <tr><td>Modifié</td><td>${formatDate(data.modified)}</td></tr>
        `;

        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();
    }

    // === UTILITIES ===

    function showToast(message, type = 'info') {
        // Use Bootstrap toast or simple alert
        const toastContainer = document.getElementById('toast-container') ||
            createToastContainer();

        const toast = document.createElement('div');
        toast.className = `toast align-items-center text-white bg-${type} border-0`;
        toast.setAttribute('role', 'alert');
        toast.innerHTML = `
            <div class="d-flex">
                <div class="toast-body">${escapeHtml(message)}</div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
            </div>
        `;

        toastContainer.appendChild(toast);
        const bsToast = new bootstrap.Toast(toast, { delay: 3000 });
        bsToast.show();

        toast.addEventListener('hidden.bs.toast', () => toast.remove());
    }

    function createToastContainer() {
        const container = document.createElement('div');
        container.id = 'toast-container';
        container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
        container.style.zIndex = '1100';
        document.body.appendChild(container);
        return container;
    }

    function formatFileSize(bytes) {
        if (bytes === 0) return '0 B';
        const k = 1024;
        const sizes = ['B', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
    }

    function formatDate(timestamp) {
        if (!timestamp) return '-';
        const date = new Date(timestamp * 1000);
        return date.toLocaleString('fr-FR');
    }

    function escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }

    // === IMPORT TO APP ===

    /**
     * Import a file from FileManager to a specific app.
     * @param {string} filePath - The file path in media folder
     * @param {string} targetApp - The target app name (enhancer, anonymizer, synthesizer, transcriber)
     * @returns {Promise<object>} - The import result
     */
    async function importToApp(filePath, targetApp) {
        const response = await fetch(config.apiImportUrl || '/filemanager/api/import/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({
                path: filePath,
                app: targetApp
            })
        });

        const data = await response.json();

        if (!response.ok) {
            throw new Error(data.error || 'Import failed');
        }

        return data;
    }

    /**
     * Check if a drop event contains a FileManager file.
     * @param {DragEvent} event - The drop event
     * @returns {object|null} - The file data or null
     */
    function getFileManagerData(event) {
        const wamaData = event.dataTransfer.getData('application/x-wama-file');
        if (wamaData) {
            try {
                return JSON.parse(wamaData);
            } catch (e) {
                return null;
            }
        }

        // Fallback to plain text (path only)
        const textData = event.dataTransfer.getData('text/plain');
        if (textData && !textData.startsWith('http') && textData.includes('/')) {
            return { path: textData };
        }

        return null;
    }

    /**
     * Handle drop from FileManager to an app dropzone.
     * @param {DragEvent} event - The drop event
     * @param {string} targetApp - The target app name
     * @param {function} onSuccess - Callback on successful import
     * @param {function} onError - Callback on error
     * @returns {boolean} - True if handled, false if not a FileManager drop
     */
    async function handleDropFromFileManager(event, targetApp, onSuccess, onError) {
        const fileData = getFileManagerData(event);

        if (!fileData || !fileData.path) {
            return false; // Not a FileManager drop
        }

        event.preventDefault();
        event.stopPropagation();

        try {
            showToast(`Import de ${fileData.name || 'fichier'} vers ${targetApp}...`, 'info');
            const result = await importToApp(fileData.path, targetApp);

            if (result.imported) {
                showToast(`Fichier importé avec succès`, 'success');
                if (onSuccess) {
                    onSuccess(result);
                }
            } else {
                throw new Error(result.error || 'Import failed');
            }
        } catch (error) {
            showToast(`Erreur: ${error.message}`, 'danger');
            if (onError) {
                onError(error);
            }
        }

        return true;
    }

    // Expose to global scope
    window.FileManager = {
        toggle: toggleSidebar,
        refresh: refreshTree,
        close: closeSidebar,
        importToApp: importToApp,
        getFileManagerData: getFileManagerData,
        handleDropFromFileManager: handleDropFromFileManager,
        showToast: showToast
    };
})();
