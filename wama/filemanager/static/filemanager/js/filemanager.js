/**
 * WAMA FileManager - jstree integration with dark theme
 * Sidebar is always visible (fixed position)
 */
(function() {
    'use strict';

    const config = window.FILEMANAGER_CONFIG || {};
    const csrfToken = config.csrfToken || '';

    // State
    let tree = null;
    let lastTreeHash = null;
    let autoRefreshInterval = null;
    const AUTO_REFRESH_DELAY = 5000; // Check every 5 seconds

    // Initialize on DOM ready
    document.addEventListener('DOMContentLoaded', init);

    function init() {
        // Check if jstree is available
        if (typeof $.jstree === 'undefined') {
            console.error('jstree not loaded');
            return;
        }

        initJstree();
        setupSearch();
        setupUploadDropzone();
        setupPreviewModal();
        setupAutoRefresh();
        setupCustomEventListeners();
    }

    function setupAutoRefresh() {
        // Start periodic check for changes
        autoRefreshInterval = setInterval(checkForChanges, AUTO_REFRESH_DELAY);
    }

    function setupCustomEventListeners() {
        // Listen for custom refresh events from other apps
        document.addEventListener('filemanager:refresh', function() {
            console.log('[FileManager] Refresh triggered by custom event');
            refreshTree();
        });

        // Also listen for common events that might indicate file changes
        document.addEventListener('media:uploaded', refreshTree);
        document.addEventListener('media:deleted', refreshTree);
        document.addEventListener('media:processed', refreshTree);
    }

    async function checkForChanges() {
        if (!tree) return;

        try {
            const response = await fetch(config.apiTreeUrl || '/filemanager/api/tree/');
            const data = await response.json();
            const newHash = JSON.stringify(data);

            if (lastTreeHash && newHash !== lastTreeHash) {
                console.log('[FileManager] Tree changed, refreshing...');
                tree.refresh();
            }
            lastTreeHash = newHash;
        } catch (error) {
            // Silently ignore errors during auto-refresh
        }
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
                'check_callback': function(operation, node, parent, position, more) {
                    // Allow move only within temp folder (for internal tree moves)
                    if (operation === 'move_node') {
                        // Get tree instance from the container, not from the node
                        const treeContainer = document.getElementById('filemanager-tree');
                        const inst = treeContainer ? $.jstree.reference(treeContainer) : null;

                        if (!inst) {
                            console.warn('[FileManager] Could not get tree instance for move check');
                            return false;
                        }

                        // Check if source is in temp folder
                        const sourcePath = node.data?.path || '';
                        const isSourceInTemp = sourcePath.includes('/temp') || sourcePath.includes('\\temp');

                        if (!isSourceInTemp) {
                            console.log('[FileManager] Move denied: source not in temp folder', sourcePath);
                            return false;
                        }

                        // Get parent node
                        let parentNode;
                        if (typeof parent === 'string') {
                            parentNode = inst.get_node(parent);
                        } else {
                            parentNode = parent;
                        }

                        if (!parentNode || parentNode.id === '#') {
                            console.log('[FileManager] Move denied: invalid parent node');
                            return false;
                        }

                        // Check if destination is in temp folder
                        const destPath = parentNode.data?.path || '';
                        const parentId = parentNode.id || '';

                        // Valid destinations:
                        // 1. The 'temp' node itself
                        // 2. Any folder whose path contains '/temp' or '\temp'
                        // 3. Any folder whose id starts with 'folder_users_' (subfolders in temp)
                        const isDestInTemp = parentId === 'temp' ||
                                            destPath.includes('/temp') ||
                                            destPath.includes('\\temp') ||
                                            parentId.startsWith('folder_users_');

                        if (!isDestInTemp) {
                            console.log('[FileManager] Move denied: destination not in temp folder', parentId, destPath);
                        }

                        return isDestInTemp;
                    }
                    return true;
                },
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
                'items': contextMenuItems,
                'select_node': true,
                'show_at_node': true
            },
            'search': {
                'show_only_matches': true,
                'show_only_matches_children': true
            },
            'dnd': {
                'is_draggable': function(nodes) {
                    // Allow all files to be dragged (for external drag to apps)
                    // Internal move restrictions are handled by check_callback
                    return nodes.every(n => n.type === 'file');
                },
                'copy': false,  // Move, not copy
                'inside_pos': 'last',
                'touch': 'selected',
                'use_html5': true
            }
        });

        tree = $(treeContainer).jstree(true);
        console.log('[FileManager] jstree initialized, plugins:', tree.settings.plugins);

        // Event handlers
        $(treeContainer).on('dblclick.jstree', '.jstree-anchor', handleDoubleClick);
        $(treeContainer).on('loaded.jstree', handleTreeLoaded);
        $(treeContainer).on('refresh.jstree', handleTreeRefreshed);

        // Save tree state when nodes are opened/closed
        $(treeContainer).on('open_node.jstree close_node.jstree', function() {
            saveTreeState();
        });

        // Handle internal move (drag & drop within tree)
        $(treeContainer).on('move_node.jstree', handleMoveNode);

        // Setup external drag & drop
        setupExternalDragDrop(treeContainer);
    }

    function contextMenuItems(node) {
        console.log('[FileManager] Context menu requested for node:', node.id, 'type:', node.type);

        // Return false to disable context menu for nodes without a type
        if (!node.type || (node.type !== 'file' && node.type !== 'folder')) {
            return false;
        }

        const items = {};

        if (node.type === 'file') {
            items.preview = {
                label: 'Aperçu',
                icon: 'fa fa-eye',
                action: function() { previewFile(node); }
            };
            items.download = {
                label: 'Télécharger',
                icon: 'fa fa-download',
                action: function() { downloadFile(node); }
            };
            items.info = {
                label: 'Informations',
                icon: 'fa fa-info-circle',
                action: function() { showFileInfo(node); }
            };
            items.rename = {
                label: 'Renommer',
                icon: 'fa fa-edit',
                separator_before: true,
                action: function() { renameFile(node); }
            };
            items.delete = {
                label: 'Supprimer',
                icon: 'fa fa-trash',
                action: function() { deleteFile(node); },
                _class: 'context-menu-danger'
            };
        } else if (node.type === 'folder') {
            items.refresh = {
                label: 'Actualiser',
                icon: 'fa fa-sync',
                action: function() { refreshTree(); }
            };
            items.expand = {
                label: 'Tout déplier',
                icon: 'fa fa-folder-open',
                action: function() { tree.open_all(node); }
            };
            items.collapse = {
                label: 'Tout replier',
                icon: 'fa fa-folder',
                action: function() { tree.close_all(node); }
            };
            items.deleteAll = {
                label: 'Vider le dossier',
                icon: 'fa fa-trash',
                separator_before: true,
                action: function() { deleteAllInFolder(node); },
                _class: 'context-menu-danger'
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

    async function handleMoveNode(e, data) {
        const node = data.node;
        const newParent = data.parent;
        const oldParent = data.old_parent;

        // If same parent, no need to move on server
        if (newParent === oldParent) return;

        const sourcePath = node.data?.path;
        if (!sourcePath) {
            console.error('[FileManager] No source path for move');
            refreshTree();
            return;
        }

        // Get destination folder path
        let destPath;
        if (newParent === 'temp') {
            // Moving to root of temp folder - need to get the actual path
            const tempNode = tree.get_node('temp');
            destPath = tempNode?.data?.path;
        } else {
            const parentNode = tree.get_node(newParent);
            destPath = parentNode?.data?.path;
        }

        if (!destPath) {
            console.error('[FileManager] No destination path for move');
            refreshTree();
            return;
        }

        console.log('[FileManager] Moving', sourcePath, 'to', destPath);

        try {
            const response = await fetch(config.apiMoveUrl || '/filemanager/api/move/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': csrfToken
                },
                body: JSON.stringify({
                    source: sourcePath,
                    destination: destPath
                })
            });

            const result = await response.json();

            if (result.moved) {
                showToast('Fichier déplacé', 'success');
                // Update node data with new path
                node.data.path = result.new_path;
            } else {
                showToast(result.error || 'Erreur lors du déplacement', 'danger');
                refreshTree();
            }
        } catch (error) {
            console.error('[FileManager] Move error:', error);
            showToast('Erreur lors du déplacement', 'danger');
            refreshTree();
        }
    }

    function handleTreeLoaded() {
        console.log('FileManager tree loaded');

        // Store initial tree state for change detection
        fetchTreeHash();

        // Restore opened folders state from localStorage (for temp folder)
        restoreTreeState();

        // Always auto-expand folder corresponding to current app
        autoExpandCurrentAppFolder();
    }

    function getTreeStateKey() {
        return 'filemanager_tree_state';
    }

    function saveTreeState() {
        if (!tree) return;

        // Get all opened nodes
        const allOpenedNodes = tree.get_state().core.open;

        // Only save temp folder nodes (not app folders)
        const appFolders = ['anonymizer', 'describer', 'enhancer', 'imager', 'synthesizer', 'transcriber'];
        const tempNodes = allOpenedNodes.filter(nodeId => {
            // Keep only temp-related nodes
            return nodeId === 'temp' || nodeId.startsWith('folder_users_');
        });

        localStorage.setItem(getTreeStateKey(), JSON.stringify(tempNodes));
        console.log('[FileManager] Tree state saved:', tempNodes.length, 'temp nodes open');
    }

    function restoreTreeState() {
        if (!tree) return;

        const saved = localStorage.getItem(getTreeStateKey());
        if (!saved) return;

        try {
            const openedNodes = JSON.parse(saved);
            if (Array.isArray(openedNodes) && openedNodes.length > 0) {
                // Open each saved node
                openedNodes.forEach(nodeId => {
                    if (tree.get_node(nodeId)) {
                        tree.open_node(nodeId, false, false);
                    }
                });
                console.log('[FileManager] Tree state restored:', openedNodes.length, 'nodes');
            }
        } catch (e) {
            console.warn('[FileManager] Could not restore tree state:', e);
            localStorage.removeItem(getTreeStateKey());
        }
    }

    async function fetchTreeHash() {
        try {
            const response = await fetch(config.apiTreeUrl || '/filemanager/api/tree/');
            const data = await response.json();
            lastTreeHash = JSON.stringify(data);
        } catch (error) {
            console.warn('[FileManager] Could not fetch tree hash:', error);
        }
    }

    function handleTreeRefreshed() {
        console.log('FileManager tree refreshed');

        // Update hash after refresh
        fetchTreeHash();

        // Restore opened folders state and expand current app
        setTimeout(() => {
            restoreTreeState();
            autoExpandCurrentAppFolder();
        }, 100);
    }

    function autoExpandCurrentAppFolder() {
        if (!tree) return;

        // Get current app from URL pathname (e.g., /anonymizer/ -> anonymizer)
        const pathParts = window.location.pathname.split('/').filter(p => p);
        const currentApp = pathParts[0];

        // Map of app names to their tree node IDs
        const appFolderMap = {
            'anonymizer': ['anonymizer', 'anonymizer_input', 'anonymizer_output'],
            'describer': ['describer', 'describer_input', 'describer_output'],
            'enhancer': ['enhancer', 'enhancer_input', 'enhancer_output'],
            'imager': ['imager', 'imager_prompts', 'imager_references', 'imager_output_image', 'imager_output_video'],
            'synthesizer': ['synthesizer', 'synthesizer_input', 'synthesizer_output'],
            'transcriber': ['transcriber', 'transcriber_input', 'transcriber_output'],
        };

        // Close all app folders first (except current app)
        Object.keys(appFolderMap).forEach(appName => {
            if (appName !== currentApp) {
                const mainNode = tree.get_node(appName);
                if (mainNode && tree.is_open(mainNode)) {
                    tree.close_node(mainNode);
                }
            }
        });

        const nodesToOpen = appFolderMap[currentApp];

        if (nodesToOpen && nodesToOpen.length > 0) {
            console.log(`FileManager: Auto-expanding ${currentApp} folders`);

            // Open nodes sequentially (parent first, then children)
            nodesToOpen.forEach(nodeId => {
                const node = tree.get_node(nodeId);
                if (node) {
                    tree.open_node(node);
                }
            });
        }
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
                if (data.preview_url || data.text_content !== undefined) {
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

    function deleteAllInFolder(node) {
        const path = node.data?.path;
        if (!path) {
            showToast('Ce dossier ne peut pas être vidé', 'warning');
            return;
        }

        // Count files to give user feedback
        const childCount = countFilesRecursive(node);

        if (childCount === 0) {
            showToast('Le dossier est déjà vide', 'info');
            return;
        }

        const message = `Supprimer ${childCount} fichier(s) dans "${node.text}" et ses sous-dossiers ?\n\nCette action est irréversible.`;
        if (!confirm(message)) return;

        fetch(config.apiDeleteAllUrl || '/filemanager/api/delete-all/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': csrfToken
            },
            body: JSON.stringify({ path: path })
        })
            .then(res => res.json())
            .then(data => {
                if (data.deleted_count !== undefined) {
                    let message = `${data.deleted_count} fichier(s) supprimé(s)`;
                    if (data.deleted_folders > 0) {
                        message += `, ${data.deleted_folders} dossier(s) vide(s) supprimé(s)`;
                    }
                    showToast(message, 'success');
                    refreshTree();
                } else {
                    showToast(data.error || 'Erreur lors de la suppression', 'danger');
                }
            })
            .catch(err => {
                console.error('Delete all error:', err);
                showToast('Erreur lors de la suppression', 'danger');
            });
    }

    function countFilesRecursive(node) {
        let count = 0;
        if (node.children && node.children.length > 0) {
            node.children.forEach(childId => {
                const child = tree.get_node(childId);
                if (child) {
                    if (child.type === 'file') {
                        count++;
                    } else if (child.type === 'folder') {
                        count += countFilesRecursive(child);
                    }
                }
            });
        }
        return count;
    }

    // === SEARCH ===

    function setupSearch() {
        const searchInput = document.getElementById('filemanager-tree-filter');
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

        // Also create a folder input for click-to-select folders
        const folderInput = document.createElement('input');
        folderInput.type = 'file';
        folderInput.webkitdirectory = true;
        folderInput.multiple = true;
        folderInput.style.display = 'none';
        document.body.appendChild(folderInput);

        // Click handler - show choice between files or folder
        dropzone.addEventListener('click', (e) => {
            // If shift key is held, select folder, otherwise files
            if (e.shiftKey) {
                folderInput.click();
            } else {
                fileInput.click();
            }
        });

        dropzone.addEventListener('dragover', (e) => {
            e.preventDefault();
            dropzone.classList.add('drag-over');
        });

        dropzone.addEventListener('dragleave', () => {
            dropzone.classList.remove('drag-over');
        });

        // Handle drop - detect folders using webkitGetAsEntry
        dropzone.addEventListener('drop', async (e) => {
            e.preventDefault();
            dropzone.classList.remove('drag-over');

            const items = e.dataTransfer.items;
            if (items && items.length > 0) {
                // Check if any item is a directory using webkitGetAsEntry
                const entries = [];
                for (let i = 0; i < items.length; i++) {
                    const entry = items[i].webkitGetAsEntry?.();
                    if (entry) {
                        entries.push(entry);
                    }
                }

                if (entries.length > 0) {
                    // Process entries (files and folders)
                    await handleEntriesUpload(entries);
                } else {
                    // Fallback to regular file upload
                    handleFileUpload(e.dataTransfer.files);
                }
            } else {
                handleFileUpload(e.dataTransfer.files);
            }
        });

        fileInput.addEventListener('change', (e) => {
            handleFileUpload(e.target.files);
            fileInput.value = '';
        });

        folderInput.addEventListener('change', (e) => {
            // webkitdirectory gives us files with webkitRelativePath
            handleFolderFilesUpload(e.target.files);
            folderInput.value = '';
        });
    }

    /**
     * Read all files from FileSystemEntry objects (supports folders)
     */
    async function handleEntriesUpload(entries) {
        showToast('Lecture des fichiers...', 'info');
        console.log('[FileManager] Processing', entries.length, 'entries');

        const filesWithPaths = [];

        // Process all entries in parallel
        await Promise.all(entries.map(entry => readEntry(entry, '', filesWithPaths)));

        console.log('[FileManager] Found', filesWithPaths.length, 'files');

        if (filesWithPaths.length === 0) {
            showToast('Aucun fichier trouvé', 'warning');
            return;
        }

        await uploadFilesWithPaths(filesWithPaths);
    }

    /**
     * Recursively read a FileSystemEntry (file or directory)
     */
    async function readEntry(entry, parentPath, filesWithPaths) {
        try {
            if (entry.isFile) {
                // Get the File object
                const file = await new Promise((resolve, reject) => {
                    entry.file(resolve, reject);
                });

                const relativePath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
                filesWithPaths.push({ file, relativePath });
            } else if (entry.isDirectory) {
                // Read directory contents
                const dirPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
                const reader = entry.createReader();

                // Read all entries in the directory (may need multiple reads)
                const allEntries = await readAllDirectoryEntries(reader);

                console.log('[FileManager] Directory', dirPath, 'contains', allEntries.length, 'items');

                // Recursively process each entry in parallel
                await Promise.all(allEntries.map(childEntry => readEntry(childEntry, dirPath, filesWithPaths)));
            }
        } catch (error) {
            console.error('[FileManager] Error reading entry:', entry.name, error);
        }
    }

    /**
     * Read all entries from a directory reader (handles batched results)
     */
    async function readAllDirectoryEntries(reader) {
        const allEntries = [];

        // readEntries returns results in batches, keep reading until empty
        const readBatch = () => {
            return new Promise((resolve, reject) => {
                reader.readEntries(resolve, reject);
            });
        };

        let batch;
        do {
            try {
                batch = await readBatch();
                allEntries.push(...batch);
            } catch (error) {
                console.error('[FileManager] Error reading directory batch:', error);
                break;
            }
        } while (batch && batch.length > 0);

        return allEntries;
    }

    /**
     * Handle files from folder input (uses webkitRelativePath)
     */
    async function handleFolderFilesUpload(files) {
        if (!files.length) return;

        const filesWithPaths = [];
        for (let i = 0; i < files.length; i++) {
            const file = files[i];
            // webkitRelativePath includes the folder name
            const relativePath = file.webkitRelativePath || file.name;
            filesWithPaths.push({ file, relativePath });
        }

        await uploadFilesWithPaths(filesWithPaths);
    }

    /**
     * Upload files with their relative paths preserved
     */
    async function uploadFilesWithPaths(filesWithPaths) {
        const formData = new FormData();
        const paths = [];

        for (const { file, relativePath } of filesWithPaths) {
            formData.append('files', file);
            paths.push(relativePath);
        }

        // Send paths as JSON
        formData.append('paths', JSON.stringify(paths));

        showToast(`Upload de ${filesWithPaths.length} fichier(s)...`, 'info');

        try {
            const response = await fetch(config.apiUploadUrl || '/filemanager/api/upload/', {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken
                },
                body: formData
            });

            const data = await response.json();

            if (data.count > 0) {
                const folderInfo = data.folders_created ? ` (${data.folders_created} dossier(s) créé(s))` : '';
                showToast(`${data.count} fichier(s) uploadé(s)${folderInfo}`, 'success');
                refreshTree();
            } else {
                showToast('Aucun fichier uploadé', 'warning');
            }
        } catch (err) {
            console.error('Upload error:', err);
            showToast('Erreur lors de l\'upload', 'danger');
        }
    }

    /**
     * Simple file upload (no folder structure)
     */
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
                <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
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
            container.innerHTML = `<img src="${data.preview_url}" alt="${data.name}" style="max-width:100%; max-height:70vh;">`;
        } else if (data.mime.startsWith('video/')) {
            container.innerHTML = `
                <video controls autoplay muted style="max-width:100%; max-height:70vh;">
                    <source src="${data.preview_url}" type="${data.mime}">
                </video>
                <div class="video-error-message d-none text-center p-4">
                    <i class="fa fa-exclamation-triangle fa-3x text-warning mb-3"></i>
                    <h5>Lecture impossible</h5>
                    <p class="text-muted mb-2">Le codec de cette vidéo n'est pas supporté par le navigateur.</p>
                    <a href="${data.preview_url}" download class="btn btn-outline-light btn-sm">
                        <i class="fa fa-download me-2"></i>Télécharger le fichier
                    </a>
                </div>
            `;
            const video = container.querySelector('video');
            const errorMsg = container.querySelector('.video-error-message');
            video.addEventListener('error', function() {
                video.classList.add('d-none');
                errorMsg.classList.remove('d-none');
            });
        } else if (data.mime.startsWith('audio/')) {
            container.innerHTML = `<audio src="${data.preview_url}" controls autoplay style="width:100%;"></audio>`;
        } else if (data.text_content !== undefined) {
            // Text file preview
            const escapedContent = escapeHtml(data.text_content);
            container.innerHTML = `
                <pre class="text-preview" style="
                    background: #0d1117;
                    border: 1px solid #374151;
                    border-radius: 6px;
                    padding: 15px;
                    max-height: 60vh;
                    overflow: auto;
                    white-space: pre-wrap;
                    word-wrap: break-word;
                    font-family: 'Consolas', 'Monaco', monospace;
                    font-size: 0.85rem;
                    color: #e2e8f0;
                    margin: 0;
                ">${escapedContent}</pre>
            `;
        } else if (data.error) {
            container.innerHTML = `<p class="text-danger"><i class="fa fa-exclamation-triangle me-2"></i>${escapeHtml(data.error)}</p>`;
        } else {
            container.innerHTML = `<p class="text-muted">Aperçu non disponible pour ce type de fichier</p>`;
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

    // Helper to trigger refresh via custom event (useful for other apps)
    function triggerRefresh() {
        document.dispatchEvent(new CustomEvent('filemanager:refresh'));
    }

    // Expose to global scope
    window.FileManager = {
        refresh: refreshTree,
        triggerRefresh: triggerRefresh,
        importToApp: importToApp,
        getFileManagerData: getFileManagerData,
        handleDropFromFileManager: handleDropFromFileManager,
        showToast: showToast
    };
})();
