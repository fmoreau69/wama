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
    let wasProcessing = false;  // Track previous processing state for edge detection
    const AUTO_REFRESH_DELAY = 5000; // Check every 5 seconds

    // Preview navigation state
    let currentPreviewNode = null;
    let previewSiblings = [];
    let previewIndex = -1;

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
        setupCustomEventListeners();
    }

    /**
     * Detect if any WAMA app on the page is currently processing.
     * Uses DOM indicators rendered by Django templates and set by app JS.
     */
    function isProcessingActive() {
        return !!document.querySelector(
            // Synthesizer, Transcriber, Describer: card with .processing class (Django template)
            '.synthesis-card.processing, ' +
            // Enhancer, Transcriber, Describer: row/card with data-status (Django template)
            '[data-status="RUNNING"], ' +
            // Anonymizer, Imager: body flag set by app JS
            '[data-wama-processing]'
        );
    }

    function setupAutoRefresh() {
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

        const processing = isProcessingActive();

        // If processing just ended, force a refresh
        if (wasProcessing && !processing) {
            wasProcessing = false;
            lastTreeHash = null;
            refreshTree();
            return;
        }

        wasProcessing = processing;
        if (processing) return;  // Skip auto-refresh while processing

        try {
            // Use lightweight mtime endpoint instead of full tree scan
            const mtimeUrl = config.apiTreeMtimeUrl || '/filemanager/api/tree/mtime/';
            const response = await fetch(mtimeUrl);
            const data = await response.json();
            const newHash = data.mtime_hash;

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
                'data': function(node, cb) {
                    // Root (#): load the skeleton tree (folder structure, no files).
                    // Any other node: lazy-load its children (files + subfolders) on expand.
                    const url = (node.id === '#')
                        ? (config.apiTreeUrl || '/filemanager/api/tree/')
                        : (config.apiChildrenUrl || '/filemanager/api/children/') +
                          '?path=' + encodeURIComponent((node.data && node.data.path) || '');
                    $.getJSON(url, function(data) { cb(data); })
                      .fail(function() { cb([]); });
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

                        // Prevent moving a folder into itself or its children
                        if (node.type === 'folder') {
                            // Check if parent is the node itself
                            if (parentNode.id === node.id) {
                                console.log('[FileManager] Move denied: cannot move folder into itself');
                                return false;
                            }
                            // Check if parent is a descendant of the node
                            let checkNode = parentNode;
                            while (checkNode && checkNode.id !== '#') {
                                if (checkNode.id === node.id) {
                                    console.log('[FileManager] Move denied: cannot move folder into its child');
                                    return false;
                                }
                                checkNode = inst.get_node(checkNode.parent);
                            }
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
                'folder':  { 'icon': 'fa fa-folder text-warning' },
                'file':    { 'icon': 'fa fa-file text-secondary' },
                'mount':   { 'icon': 'fa fa-plug text-info' },
                'section': { 'icon': 'fa fa-home text-secondary' },
                'error':   { 'icon': 'fa fa-exclamation-triangle text-warning' },
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
                    // Allow ALL files and folders to be dragged (for external drop to apps)
                    // Internal move restrictions are handled by check_callback
                    const result = nodes.every(n => {
                        const isDraggable = n.type === 'file' || n.type === 'folder';
                        return isDraggable;
                    });
                    return result;
                },
                'copy': false,  // Move, not copy
                'inside_pos': 'last',
                'touch': 'selected',
                'large_drop_target': true,
                'large_drag_target': true,
                'drag_selection': false,  // Don't drag selection, just the clicked node
                'always_copy': false
            }
        });

        tree = $(treeContainer).jstree(true);
        console.log('[FileManager] jstree initialized, plugins:', tree.settings.plugins);

        // Event handlers
        $(treeContainer).on('dblclick.jstree', '.jstree-anchor', handleDoubleClick);
        $(treeContainer).on('loaded.jstree', handleTreeLoaded);
        $(treeContainer).on('refresh.jstree', handleTreeRefreshed);

        // Save tree state when nodes are opened/closed + add tooltips on open
        $(treeContainer).on('open_node.jstree', function(e, data) {
            saveTreeState();
            // Add tooltips to newly revealed children
            const nodeEl = document.getElementById(data.node.id);
            if (nodeEl) setTimeout(() => addFilenameTitles(nodeEl), 50);
        });
        $(treeContainer).on('close_node.jstree', function() {
            saveTreeState();
        });

        // Handle internal move (drag & drop within tree)
        $(treeContainer).on('move_node.jstree', handleMoveNode);

        // Handle vakata dnd events for external drops
        // vakata.dnd doesn't use native HTML5 drag events, so we need to track the dragged data globally
        $(document).on('dnd_start.vakata', function(e, data) {
            console.log('[FileManager DND] dnd_start event fired', data);
            // Store the dragged node data globally for external drops
            if (data.data && data.data.nodes && data.data.nodes.length > 0) {
                const nodeId = data.data.nodes[0];
                const node = tree.get_node(nodeId);
                if (node && node.type === 'file' && node.data?.path) {
                    window._fileManagerDragData = {
                        path: node.data.path,
                        name: node.text,
                        mime: node.data.mime || 'application/octet-stream'
                    };
                    console.log('[FileManager DND] Stored drag data:', window._fileManagerDragData);
                }
            }
        });
        $(document).on('dnd_stop.vakata', function(e, data) {
            console.log('[FileManager DND] dnd_stop event fired', data);
            // Clear the drag data after a delay (to allow drop handlers to read it and perform imports)
            setTimeout(function() {
                window._fileManagerDragData = null;
            }, 500);
        });

        // Setup external drag & drop
        setupExternalDragDrop(treeContainer);
    }

    // Extension → compatible app list — built from server-injected WAMA_APP_CATALOG
    // Falls back to empty (no "send to" menu) if catalog unavailable
    const _catalog = window.WAMA_APP_CATALOG || {};
    const APP_EXTENSIONS = {};
    const APP_LABELS = {};
    Object.keys(_catalog).forEach(app => {
        const spec = _catalog[app];
        APP_EXTENSIONS[app] = new Set(spec.input_extensions || []);
        APP_LABELS[app] = { icon: spec.icon || 'fa fa-cube', label: spec.label || app };
    });

    function buildSendToSubmenu(node, ext) {
        const filePath = node.data && node.data.path;
        if (!filePath || !ext) return {};
        const submenu = {};
        Object.keys(APP_EXTENSIONS).forEach(app => {
            if (APP_EXTENSIONS[app].has(ext)) {
                const meta = APP_LABELS[app];
                submenu[app] = {
                    label: meta.label,
                    icon: meta.icon,
                    action: function() {
                        if (app === 'converter') {
                            convertFileFromManager(filePath, node.text, ext);
                            return;
                        }
                        importToApp(filePath, app)
                            .then(result => {
                                if (result.imported) {
                                    showToast(`"${node.text}" envoyé vers ${meta.label}`, 'success');
                                    document.dispatchEvent(new CustomEvent('wama:fileimported', {
                                        detail: result
                                    }));
                                }
                            })
                            .catch(err => showToast('Erreur : ' + err.message, 'danger'));
                    }
                };
            }
        });
        return submenu;
    }

    // ── Converter quick-convert from FileManager ─────────────────────────────

    // Extension → media type lookup (mirrors format_router.py)
    const _converterFormats = (config.converterOutputFormats) || {};
    const _extToMediaType = {};
    const _EXT_TO_TYPE_MAP = {
        image: ['jpg','jpeg','png','webp','bmp','tiff','tif','gif','heic','heif','avif'],
        video: ['mp4','avi','mov','mkv','webm','flv','mpg','mpeg','3gp','wmv','ts','m4v'],
        audio: ['mp3','wav','flac','ogg','m4a','aac','opus','wma','aiff','aif'],
    };
    Object.entries(_EXT_TO_TYPE_MAP).forEach(([type, exts]) => {
        exts.forEach(e => { _extToMediaType[e] = type; });
    });

    function convertFileFromManager(filePath, filename, ext) {
        const mediaType = _extToMediaType[ext.toLowerCase()];
        const outputFormats = mediaType ? (_converterFormats[mediaType] || []) : [];

        const modal       = document.getElementById('converterQuickModal');
        const fmtSel      = document.getElementById('converterQuickFormat');
        const fnameEl     = document.getElementById('converterQuickFilename');
        const errEl       = document.getElementById('converterQuickError');
        const confirmBtn  = document.getElementById('converterQuickConfirmBtn');

        if (!modal || !fmtSel) {
            alert('Convertisseur non disponible (modal manquant).');
            return;
        }

        // Populate dropdown
        fmtSel.innerHTML = '<option value="">— choisissez —</option>';
        outputFormats.forEach(fmt => {
            const opt = document.createElement('option');
            opt.value = fmt;
            opt.textContent = '.' + fmt.toUpperCase();
            fmtSel.appendChild(opt);
        });

        fnameEl.textContent = filename || filePath;
        errEl.style.display = 'none';
        errEl.textContent   = '';

        // Wire confirm button
        const oldBtn = confirmBtn.cloneNode(true);
        confirmBtn.parentNode.replaceChild(oldBtn, confirmBtn);
        const newBtn = document.getElementById('converterQuickConfirmBtn');
        newBtn.addEventListener('click', async function() {
            const fmt = fmtSel.value;
            if (!fmt) {
                errEl.textContent = 'Choisissez un format de sortie.';
                errEl.style.display = '';
                return;
            }
            newBtn.disabled = true;
            newBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
            errEl.style.display = 'none';

            try {
                const fd = new FormData();
                fd.append('csrfmiddlewaretoken', csrfToken);
                fd.append('file_path', filePath);
                fd.append('output_format', fmt);
                const resp = await fetch(config.converterQuickUrl || '/converter/quick/', {
                    method: 'POST',
                    body: fd,
                });
                const data = await resp.json();
                if (!resp.ok || data.error) {
                    errEl.textContent = data.error || 'Erreur conversion';
                    errEl.style.display = '';
                    newBtn.disabled = false;
                    newBtn.innerHTML = '<i class="fas fa-exchange-alt"></i> Convertir';
                    return;
                }
                // Success — dismiss modal and show toast
                bootstrap.Modal.getInstance(modal).hide();
                showToast(`Conversion démarrée → .${fmt.toUpperCase()} (job #${data.job_id})`, 'success');
            } catch(err) {
                errEl.textContent = 'Erreur réseau : ' + err.message;
                errEl.style.display = '';
                newBtn.disabled = false;
                newBtn.innerHTML = '<i class="fas fa-exchange-alt"></i> Convertir';
            }
        });

        new bootstrap.Modal(modal).show();
    }

    function contextMenuItems(node) {
        console.log('[FileManager] Context menu requested for node:', node.id, 'type:', node.type);

        // Mount root node — only show "Démonter"
        if (node.type === 'mount') {
            return {
                unmount: {
                    label: 'Démonter',
                    icon: 'fa fa-unlink',
                    action: function() { unmountFolder(node); },
                    _class: 'context-menu-danger'
                }
            };
        }

        // Return false to disable context menu for nodes without a type
        if (!node.type || (node.type !== 'file' && node.type !== 'folder')) {
            return false;
        }

        const items = {};
        const nodePath = node.data && node.data.path;
        const isMount = !!(nodePath && nodePath.startsWith('mounts/'));

        // Multi-selection: get all selected nodes
        const selectedNodes = $('#filemanager-tree').jstree('get_selected', true);
        const isMultiSelect = selectedNodes.length > 1;

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

            // "Envoyer vers..." — apps compatible with this file extension
            const filePath = node.data && node.data.path;
            const ext = filePath ? filePath.split('.').pop().toLowerCase() : '';
            const sendToSubmenu = buildSendToSubmenu(node, ext);
            if (sendToSubmenu && Object.keys(sendToSubmenu).length > 0) {
                items.sendTo = {
                    label: 'Envoyer vers…',
                    icon: 'fa fa-share-square',
                    separator_before: true,
                    submenu: sendToSubmenu,
                };
            }

            // Multi-selection: "Envoyer X fichier(s) vers..."
            if (isMultiSelect) {
                const filePaths = selectedNodes
                    .filter(n => n.type === 'file')
                    .map(n => n.data && n.data.path)
                    .filter(Boolean);

                if (filePaths.length > 0) {
                    const multiSendSubmenu = {};
                    Object.keys(APP_EXTENSIONS).forEach(app => {
                        const compatPaths = filePaths.filter(fp => {
                            const fExt = fp.split('.').pop().toLowerCase();
                            return APP_EXTENSIONS[app].has(fExt);
                        });
                        if (compatPaths.length > 0) {
                            const meta = APP_LABELS[app];
                            multiSendSubmenu[app] = {
                                label: `${meta.label} (${compatPaths.length} fichier(s))`,
                                icon: meta.icon,
                                action: function() {
                                    importMultipleToApp(compatPaths, app)
                                        .then(result => {
                                            const count = result.count || (result.imported ? 1 : 0);
                                            showToast(`${count} fichier(s) envoyé(s) vers ${meta.label}`, 'success');
                                            compatPaths.forEach(p => {
                                                document.dispatchEvent(new CustomEvent('wama:fileimported', {
                                                    detail: { imported: true, app: app, path: p }
                                                }));
                                            });
                                        })
                                        .catch(err => showToast(`Erreur : ${err.message}`, 'danger'));
                                },
                            };
                        }
                    });

                    if (Object.keys(multiSendSubmenu).length > 0) {
                        items.sendToMultiple = {
                            label: `Envoyer ${filePaths.length} fichier(s) vers…`,
                            icon: 'fa fa-share-square',
                            separator_before: true,
                            submenu: multiSendSubmenu,
                        };
                    }
                }
            }

            if (!isMount) {
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
            }

            // "Nouveau dossier ici" — create at temp root level (files live in temp folder)
            if (!isMount) items.mkdir = {
                label: 'Nouveau dossier ici',
                icon: 'fa fa-folder-plus',
                separator_before: true,
                action: function() {
                    const name = prompt('Nom du nouveau dossier :');
                    if (!name || !name.trim()) return;
                    mkdirFolder(name.trim(), '')
                        .then(result => {
                            if (result.success) {
                                showToast(`Dossier "${name.trim()}" créé`, 'success');
                                refreshTree();
                            } else {
                                showToast(result.error || 'Erreur création dossier', 'danger');
                            }
                        })
                        .catch(err => showToast(`Erreur : ${err.message}`, 'danger'));
                },
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

            // "Envoyer dossier vers..." — sends all compatible files in folder to an app
            const folderPath = node.data && node.data.path;
            if (folderPath) {
                const folderSendSubmenu = {};
                Object.keys(APP_LABELS).forEach(app => {
                    const meta = APP_LABELS[app];
                    folderSendSubmenu[app] = {
                        label: meta.label,
                        icon: meta.icon,
                        action: function() {
                            const treeInstance = $('#filemanager-tree').jstree(true);
                            const nodeData = treeInstance.get_node(node.id);
                            const allChildren = nodeData ? (nodeData.children_d || []) : [];
                            const filePaths = allChildren
                                .map(childId => treeInstance.get_node(childId))
                                .filter(n => n && n.type === 'file')
                                .map(n => n.data && n.data.path)
                                .filter(p => {
                                    if (!p) return false;
                                    const fExt = p.split('.').pop().toLowerCase();
                                    return APP_EXTENSIONS[app] && APP_EXTENSIONS[app].has(fExt);
                                });

                            if (filePaths.length === 0) {
                                showToast(`Aucun fichier compatible dans ce dossier pour ${meta.label}`, 'warning');
                                return;
                            }

                            importMultipleToApp(filePaths, app)
                                .then(result => {
                                    const count = result.count || (result.imported ? 1 : 0);
                                    showToast(`${count} fichier(s) du dossier envoyé(s) vers ${meta.label}`, 'success');
                                    filePaths.forEach(p => {
                                        document.dispatchEvent(new CustomEvent('wama:fileimported', {
                                            detail: { imported: true, app: app, path: p }
                                        }));
                                    });
                                })
                                .catch(err => showToast(`Erreur : ${err.message}`, 'danger'));
                        },
                    };
                });

                items.sendFolderTo = {
                    label: 'Envoyer dossier vers…',
                    icon: 'fa fa-share-square',
                    separator_before: true,
                    submenu: folderSendSubmenu,
                };
            }

            // "Nouveau dossier" — create subfolder inside this folder (only in temp)
            const folderPathForMkdir = node.data && node.data.path;
            const isInTemp = folderPathForMkdir && folderPathForMkdir.includes('/temp');
            if (isInTemp || node.id === 'temp') {
                // Determine the relative path within temp to use as parent
                // folderPath format: users/{id}/temp[/subpath]
                let parentRelPath = '';
                if (folderPathForMkdir) {
                    const tempMarker = '/temp/';
                    const idx = folderPathForMkdir.indexOf(tempMarker);
                    if (idx !== -1) {
                        parentRelPath = folderPathForMkdir.slice(idx + tempMarker.length);
                    }
                    // else it IS the temp root, parentRelPath stays ''
                }
                items.mkdir = {
                    label: 'Nouveau dossier',
                    icon: 'fa fa-folder-plus',
                    action: function() {
                        const name = prompt('Nom du nouveau dossier :');
                        if (!name || !name.trim()) return;
                        mkdirFolder(name.trim(), parentRelPath)
                            .then(result => {
                                if (result.success) {
                                    showToast(`Dossier "${name.trim()}" créé`, 'success');
                                    refreshTree();
                                } else {
                                    showToast(result.error || 'Erreur création dossier', 'danger');
                                }
                            })
                            .catch(err => showToast(`Erreur : ${err.message}`, 'danger'));
                    },
                };
            }

            if (!isMount) {
                items.deleteAll = {
                    label: 'Vider le dossier',
                    icon: 'fa fa-trash',
                    separator_before: true,
                    action: function() { deleteAllInFolder(node); },
                    _class: 'context-menu-danger'
                };
            }
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
        const isFolder = node.type === 'folder';

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

        console.log('[FileManager] Moving', isFolder ? 'folder' : 'file', sourcePath, 'to', destPath);

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
                const message = isFolder ? 'Dossier déplacé' : 'Fichier déplacé';
                showToast(message, 'success');

                // Update node data with new path
                node.data.path = result.new_path;

                // If it's a folder, we need to update all children paths
                if (isFolder && node.children_d && node.children_d.length > 0) {
                    const oldPrefix = sourcePath;
                    const newPrefix = result.new_path;
                    updateChildrenPaths(node, oldPrefix, newPrefix);
                }
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

    function updateChildrenPaths(parentNode, oldPrefix, newPrefix) {
        // Recursively update paths of all children
        if (!parentNode.children_d) return;

        parentNode.children_d.forEach(childId => {
            const childNode = tree.get_node(childId);
            if (childNode && childNode.data && childNode.data.path) {
                const oldPath = childNode.data.path;
                if (oldPath.startsWith(oldPrefix)) {
                    childNode.data.path = oldPath.replace(oldPrefix, newPrefix);
                    console.log('[FileManager] Updated child path:', oldPath, '->', childNode.data.path);
                }
            }
        });
    }

    function addFilenameTitles(container) {
        // Add title attribute to all tree anchors for full filename tooltip on hover
        const el = container || document.getElementById('filemanager-tree');
        if (!el) return;
        const anchors = el.querySelectorAll('.jstree-anchor');
        anchors.forEach(anchor => {
            // Get text content without the icon
            const text = anchor.textContent.trim();
            if (text && anchor.getAttribute('title') !== text) {
                anchor.setAttribute('title', text);
            }
        });
    }

    function handleTreeLoaded() {
        console.log('FileManager tree loaded');

        // Store initial tree state for change detection
        fetchTreeHash();

        // Restore opened folders state from localStorage (for temp folder)
        restoreTreeState();

        // Always auto-expand folder corresponding to current app
        autoExpandCurrentAppFolder();

        // Add tooltips with full filenames
        setTimeout(() => addFilenameTitles(), 200);
    }

    function getTreeStateKey() {
        return 'filemanager_tree_state';
    }

    function saveTreeState() {
        if (!tree) return;

        // Save all open nodes so refreshTree() can restore them
        const allOpenedNodes = tree.get_state().core.open;
        localStorage.setItem(getTreeStateKey(), JSON.stringify(allOpenedNodes));
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
            addFilenameTitles();
        }, 100);
    }

    function autoExpandCurrentAppFolder() {
        if (!tree) return;

        // Get current app from URL pathname (e.g., /anonymizer/ -> anonymizer)
        const pathParts = window.location.pathname.split('/').filter(p => p);
        let currentApp = pathParts[0];

        // Handle WAMA Lab apps with nested URL structure (e.g., /lab/face-analyzer/)
        if (currentApp === 'lab' && pathParts.length > 1) {
            // Convert URL format (face-analyzer) to folder ID format (face_analyzer)
            currentApp = pathParts[1].replace(/-/g, '_');
        }

        // Map of app names to their tree node IDs
        const appFolderMap = {
            'anonymizer': ['anonymizer', 'anonymizer_input', 'anonymizer_output'],
            'avatarizer': ['avatarizer', 'avatarizer_input', 'avatarizer_output', 'avatarizer_gallery'],
            'composer': ['composer', 'composer_input', 'composer_output'],
            'describer': ['describer', 'describer_input', 'describer_output'],
            'enhancer': ['enhancer', 'enhancer_input', 'enhancer_output'],
            'imager': ['imager', 'imager_prompts', 'imager_references', 'imager_output_image', 'imager_output_video'],
            'synthesizer': ['synthesizer', 'synthesizer_input', 'synthesizer_output', 'synthesizer_voices'],
            'transcriber': ['transcriber', 'transcriber_input', 'transcriber_output'],
            'reader':      ['reader', 'reader_input', 'reader_output'],
            // WAMA Lab apps (nested under wama_lab)
            'face_analyzer': ['wama_lab', 'face_analyzer', 'face_analyzer_input', 'face_analyzer_output'],
            'cam_analyzer': ['wama_lab', 'cam_analyzer', 'cam_analyzer_input', 'cam_analyzer_output'],
        };

        // Close all app folders first (except current app)
        Object.keys(appFolderMap).forEach(appName => {
            if (appName !== currentApp) {
                // Close main app node
                const mainNode = tree.get_node(appName);
                if (mainNode && tree.is_open(mainNode)) {
                    tree.close_node(mainNode);
                }
            }
        });

        // Also close wama_lab if current app is not a WAMA Lab app
        const wamaLabApps = ['face_analyzer', 'cam_analyzer'];
        if (!wamaLabApps.includes(currentApp)) {
            const wamaLabNode = tree.get_node('wama_lab');
            if (wamaLabNode && tree.is_open(wamaLabNode)) {
                tree.close_node(wamaLabNode);
            }
        }

        const nodesToOpen = appFolderMap[currentApp];

        if (nodesToOpen && nodesToOpen.length > 0) {
            console.log(`FileManager: Auto-expanding ${currentApp} folders`);

            // Open the Applications section first (it's collapsed by default)
            const sectionApps = tree.get_node('section_apps');
            if (sectionApps) tree.open_node(sectionApps);

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

        // Store current node and find siblings for navigation
        currentPreviewNode = node;
        updatePreviewSiblings(node);

        fetch(`${config.apiPreviewUrl || '/filemanager/api/preview/'}?path=${encodeURIComponent(path)}`)
            .then(res => res.json())
            .then(data => {
                if (data.url || data.text_content !== undefined) {
                    if (typeof window.showPreviewModalWithNav === 'function') {
                        // Stubs pour avoir le bon compte et activer les boutons nav
                        const stubs = previewSiblings.map(n => ({ name: n.text || n.id, url: '', mime_type: '' }));
                        window.showPreviewModalWithNav(data, stubs, previewIndex);
                        // Déléguer la navigation au filemanager (lazy fetch par fichier)
                        window.setPreviewNavCallback(function(newIdx) {
                            _filemanagerFetchAndShow(newIdx);
                        });
                    } else if (typeof window.showPreviewModal === 'function') {
                        window.showPreviewModal(data);
                    }
                } else {
                    showToast('Aperçu non disponible pour ce type de fichier', 'warning');
                }
            })
            .catch(err => {
                console.error('Preview error:', err);
                showToast('Erreur lors du chargement de l\'aperçu', 'danger');
            });
    }

    function _filemanagerFetchAndShow(newIdx) {
        const nextNode = previewSiblings[newIdx];
        if (!nextNode) return;
        previewIndex = newIdx;
        currentPreviewNode = nextNode;
        const path = nextNode.data?.path;
        if (!path) return;
        fetch(`${config.apiPreviewUrl || '/filemanager/api/preview/'}?path=${encodeURIComponent(path)}`)
            .then(res => res.json())
            .then(data => {
                // showPreviewModal met à jour le contenu sans réinitialiser previewItems/currentIndex
                if (typeof window.showPreviewModal === 'function') window.showPreviewModal(data);
            })
            .catch(err => console.error('[FileManager] Preview nav error:', err));
    }

    function updatePreviewSiblings(node) {
        // Get parent node to find siblings
        const parentId = node.parent;
        if (!parentId || !tree) {
            previewSiblings = [node];
            previewIndex = 0;
            return;
        }

        const parentNode = tree.get_node(parentId);
        if (!parentNode || !parentNode.children) {
            previewSiblings = [node];
            previewIndex = 0;
            return;
        }

        // Get all file siblings (not folders) that are previewable
        previewSiblings = parentNode.children
            .map(childId => tree.get_node(childId))
            .filter(child => child && child.type === 'file' && isPreviewable(child));

        // Find current index
        previewIndex = previewSiblings.findIndex(s => s.id === node.id);
        if (previewIndex === -1) {
            previewSiblings = [node];
            previewIndex = 0;
        }

        console.log(`[FileManager] Preview navigation: ${previewIndex + 1}/${previewSiblings.length} files`);
    }

    function isPreviewable(node) {
        // Check if file extension is previewable
        const name = node.text || '';
        const ext = name.split('.').pop()?.toLowerCase();
        const previewableExts = [
            // Images
            'jpg', 'jpeg', 'png', 'gif', 'webp', 'svg', 'bmp', 'ico',
            // Videos
            'mp4', 'webm', 'mov', 'avi', 'mkv', 'wmv', 'flv',
            // Audio
            'mp3', 'wav', 'ogg', 'flac', 'm4a', 'aac',
            // Documents
            'pdf',
            // Text
            'txt', 'md', 'json', 'xml', 'csv', 'log', 'py', 'js', 'css', 'html', 'yml', 'yaml'
        ];
        return previewableExts.includes(ext);
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

    function unmountFolder(node) {
        const mountId = node.data && node.data.mount_id;
        if (!mountId) return;
        if (!confirm(`Démonter "${node.text}" ?\nLes fichiers ne seront pas supprimés.`)) return;

        fetch(`${config.apiMountDeleteUrl}${mountId}/delete/`, {
            method: 'POST',
            headers: { 'X-CSRFToken': csrfToken }
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    showToast(`Dossier "${node.text}" démonté`, 'success');
                    tree.delete_node(node);
                } else {
                    showToast(data.error || 'Erreur lors du démontage', 'danger');
                }
            })
            .catch(err => showToast(`Erreur : ${err.message}`, 'danger'));
    }

    // ── Mount — connecteur de dossier (aucune copie de fichiers) ────────────
    const btnAddMount    = document.getElementById('btnAddMount');
    const mountModalEl   = document.getElementById('mountModal');
    const mountPathInput = document.getElementById('mountPathInput');
    const mountPathStatus= document.getElementById('mountPathStatus');
    const mountNameInput = document.getElementById('mountNameInput');
    const mountSaveBtn   = document.getElementById('mountSaveBtn');
    let _mountModal      = null;
    let _mountValidateTimer = null;

    btnAddMount?.addEventListener('click', () => {
        if (!mountModalEl) return;
        if (mountPathInput)  { mountPathInput.value = ''; mountPathInput.classList.remove('is-valid','is-invalid'); }
        if (mountNameInput)  mountNameInput.value = '';
        if (mountPathStatus) mountPathStatus.innerHTML = '';
        if (mountSaveBtn)    mountSaveBtn.disabled = true;
        if (mountSmbSection) mountSmbSection.style.display = 'none';
        if (mountSmbUser)     mountSmbUser.value = '';
        if (mountSmbPassword) mountSmbPassword.value = '';
        if (mountSmbDomain)   mountSmbDomain.value = '';
        _mountIsSMB = false;
        _mountModal = _mountModal || new bootstrap.Modal(mountModalEl);
        _mountModal.show();
        setTimeout(() => mountPathInput?.focus(), 300);
    });

    const mountSmbSection  = document.getElementById('mountSmbSection');
    const mountSmbUser     = document.getElementById('mountSmbUser');
    const mountSmbPassword = document.getElementById('mountSmbPassword');
    const mountSmbDomain   = document.getElementById('mountSmbDomain');
    let _mountIsSMB = false;

    function _checkMountPath(raw) {
        if (!raw.trim()) {
            mountPathStatus.innerHTML = '';
            mountSaveBtn.disabled = true;
            if (mountSmbSection) mountSmbSection.style.display = 'none';
            _mountIsSMB = false;
            return;
        }
        mountPathStatus.innerHTML = '<span class="text-muted"><i class="fas fa-spinner fa-spin me-1"></i></span>';
        const url = (config.apiValidatePathUrl || '/filemanager/api/validate-path/') + '?path=' + encodeURIComponent(raw);
        fetch(url, { headers: { 'X-CSRFToken': csrfToken } })
            .then(r => r.json())
            .then(data => {
                const last = raw.replace(/\\/g,'/').replace(/\/+$/,'').split('/').pop() || raw;
                if (!mountNameInput.value.trim()) mountNameInput.value = data.name || last;

                // Show/hide SMB credentials section
                _mountIsSMB = !!data.is_smb;
                if (mountSmbSection) mountSmbSection.style.display = _mountIsSMB ? '' : 'none';

                if (data.accessible) {
                    mountPathStatus.innerHTML = `<span class="text-success"><i class="fas fa-check-circle me-1"></i>Accessible</span>`;
                } else if (_mountIsSMB && data.smb_hint) {
                    mountPathStatus.innerHTML = `<span class="text-info"><i class="fas fa-network-wired me-1"></i>${data.smb_hint}</span>`;
                } else {
                    mountPathStatus.innerHTML = `<span class="text-warning"><i class="fas fa-exclamation-triangle me-1"></i>Non accessible — sera disponible quand le partage sera connect\u00e9</span>`;
                }
                mountSaveBtn.disabled = false;
            })
            .catch(() => {
                mountSaveBtn.disabled = false;
            });
    }

    mountPathInput?.addEventListener('input', () => {
        clearTimeout(_mountValidateTimer);
        mountSaveBtn.disabled = true;
        _mountValidateTimer = setTimeout(() => _checkMountPath(mountPathInput.value), 500);
    });
    mountPathInput?.addEventListener('keydown', e => {
        if (e.key === 'Enter') { clearTimeout(_mountValidateTimer); _checkMountPath(mountPathInput.value); }
    });

    mountSaveBtn?.addEventListener('click', () => {
        const rawPath = mountPathInput?.value.trim();
        const name    = mountNameInput?.value.trim();
        if (!name || !rawPath) { showToast('Chemin et nom requis', 'warning'); return; }
        mountSaveBtn.disabled = true;
        mountPathStatus.innerHTML = '<span class="text-muted"><i class="fas fa-spinner fa-spin me-1"></i>Connexion en cours\u2026</span>';

        const body = { name, local_path: rawPath };
        if (_mountIsSMB) {
            body.smb_username = mountSmbUser?.value.trim()     || '';
            body.smb_password = mountSmbPassword?.value.trim() || '';
            body.smb_domain   = mountSmbDomain?.value.trim()   || '';
        }

        fetch(config.apiMountsUrl || '/filemanager/api/mounts/', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
            body: JSON.stringify(body)
        })
            .then(r => r.json())
            .then(data => {
                mountSaveBtn.disabled = false;
                if (data.success) {
                    _mountModal?.hide();
                    showToast(`"${data.name}" connect\u00e9`, 'success');
                    refreshTree();
                } else if (data.needs_auth) {
                    // Show credentials section and ask user to fill in
                    if (mountSmbSection) mountSmbSection.style.display = '';
                    _mountIsSMB = true;
                    mountPathStatus.innerHTML = `<span class="text-danger"><i class="fas fa-lock me-1"></i>Authentification requise — renseignez vos identifiants AD</span>`;
                    mountSmbUser?.focus();
                } else {
                    mountPathStatus.innerHTML = `<span class="text-danger"><i class="fas fa-times me-1"></i>${data.error || 'Erreur'}</span>`;
                    showToast(data.error || 'Erreur', 'danger');
                }
            })
            .catch(err => {
                mountSaveBtn.disabled = false;
                showToast('Erreur : ' + err.message, 'danger');
            });
    });

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
        // Track the current drop zone element during vakata drag
        let currentDropZone = null;

        // Find all WAMA drop zones (elements with .drop-zone class)
        function findDropZoneAt(x, y) {
            const dropZones = document.querySelectorAll('.drop-zone');
            for (const zone of dropZones) {
                const rect = zone.getBoundingClientRect();
                if (x >= rect.left && x <= rect.right && y >= rect.top && y <= rect.bottom) {
                    return zone;
                }
            }
            return null;
        }

        // Get app name from drop zone
        function getAppFromDropZone(zone) {
            if (!zone) return null;
            const id = zone.id || '';
            if (id === 'dropZone') return 'describer';
            if (id === 'dropZoneEnhancer') return 'enhancer';
            if (id === 'dropZoneAudio') return 'enhancer';
            if (id === 'dropZoneTranscriber' || id.includes('transcriber')) return 'transcriber';
            if (id === 'dropZoneAnonymizer' || id.includes('anonymizer')) return 'anonymizer';
            if (id === 'dropZoneSynthesizer' || id.includes('synthesizer')) return 'synthesizer';
            if (id === 'dropZoneFaceAnalyzer' || id.includes('face_analyzer') || id.includes('face-analyzer')) return 'face_analyzer';
            // Try to get from data attribute
            return zone.dataset.wamaApp || null;
        }

        // Listen to vakata dnd move events to detect drop zones
        $(document).on('dnd_move.vakata', function(e, data) {
            // Only handle if we have file drag data
            if (!window._fileManagerDragData) return;

            const x = data.event.pageX;
            const y = data.event.pageY;
            const dropZone = findDropZoneAt(x, y);

            // Remove highlight from previous drop zone
            if (currentDropZone && currentDropZone !== dropZone) {
                currentDropZone.classList.remove('dragover', 'drag-over');
            }

            // Add highlight to new drop zone
            if (dropZone) {
                dropZone.classList.add('dragover', 'drag-over');
                currentDropZone = dropZone;

                // Change cursor to indicate drop is allowed
                if (data.helper) {
                    data.helper.find('.jstree-icon').first().removeClass('jstree-er').addClass('jstree-ok');
                }
            } else {
                currentDropZone = null;
            }
        });

        // Handle vakata dnd stop - perform the actual drop
        $(document).on('dnd_stop.vakata', function(e, data) {
            const dragData = window._fileManagerDragData;

            // Remove highlight from drop zone
            if (currentDropZone) {
                currentDropZone.classList.remove('dragover', 'drag-over');
            }

            // Check if we dropped on a valid drop zone
            if (dragData && currentDropZone) {
                const app = getAppFromDropZone(currentDropZone);
                console.log('[FileManager DND] Dropping on app:', app, 'file:', dragData.path);

                if (app && dragData.path) {
                    // These apps handle the blob fetch themselves via filemanager:filedrop custom event.
                    if (app === 'imager' || app === 'avatarizer' || app === 'cam_analyzer') {
                        currentDropZone.dispatchEvent(new CustomEvent('filemanager:filedrop', {
                            detail: { path: dragData.path, name: dragData.name, mime: dragData.mime },
                            bubbles: false,
                        }));
                    } else {
                        // Other apps: server-side import → dispatch event, then reload if not handled
                        const capturedZone = currentDropZone;
                        importToApp(dragData.path, app)
                            .then(result => {
                                if (result.imported) {
                                    showToast(`Fichier importé vers ${app}`, 'success');
                                    // Dispatch cancelable event — allows drop zones to handle batch/special results
                                    const ev = new CustomEvent('filemanager:imported', {
                                        detail: result,
                                        bubbles: false,
                                        cancelable: true,
                                    });
                                    if (capturedZone) capturedZone.dispatchEvent(ev);
                                    if (!ev.defaultPrevented) {
                                        // No special handler — default behavior
                                        if (app === 'face_analyzer' && result.id) {
                                            window.location.href = `/lab/face-analyzer/video/?session=${result.id}`;
                                        } else {
                                            window.location.reload();
                                        }
                                    }
                                }
                            })
                            .catch(error => {
                                console.error('[FileManager DND] Import error:', error);
                                showToast('Erreur d\'import: ' + error.message, 'danger');
                            });
                    }
                }
            }

            currentDropZone = null;
            // Clear drag data is handled by the other dnd_stop handler
        });
    }

    // === MODALS ===

    function setupPreviewModal() {
        // Set up keyboard navigation for preview modal and fullscreen
        document.addEventListener('keydown', function(e) {
            // Ignore if user is typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            // Check if fullscreen is open
            const fullscreenOverlay = document.getElementById('imageFullscreenOverlay');
            if (fullscreenOverlay) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    window.FileManagerFullscreen.close();
                } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    window.FileManagerFullscreen.navigate(-1);
                } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                    e.preventDefault();
                    window.FileManagerFullscreen.navigate(1);
                }
                return;
            }

            // Check if preview modal is open (unified modal)
            const modal = document.getElementById('wamaMediaPreviewModal');
            if (!modal || !modal.classList.contains('show')) return;

            if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                e.preventDefault();
                navigatePreview(-1);
            } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                e.preventDefault();
                navigatePreview(1);
            } else if (e.key === 'Escape') {
                // Let Bootstrap handle Escape
            }
        });

        // Setup fullscreen API
        setupFullscreen();
    }

    // === FULLSCREEN ===

    function setupFullscreen() {
        window.FileManagerFullscreen = {
            open: openFullscreen,
            close: closeFullscreen,
            navigate: navigateFullscreen
        };
    }

    function openFullscreen(imageUrl, imageName) {
        // Remove existing overlay if any
        closeFullscreen();

        const overlay = document.createElement('div');
        overlay.id = 'imageFullscreenOverlay';
        overlay.onclick = function(e) {
            if (e.target === overlay) closeFullscreen();
        };

        // Build navigation buttons if there are siblings
        let navPrev = '';
        let navNext = '';
        let infoBar = '';

        if (previewSiblings.length > 1) {
            const isFirst = previewIndex === 0;
            const isLast = previewIndex === previewSiblings.length - 1;

            navPrev = `
                <button class="fullscreen-nav-btn fullscreen-nav-prev ${isFirst ? 'disabled' : ''}"
                        onclick="event.stopPropagation(); window.FileManagerFullscreen.navigate(-1)" title="Précédent (←)">
                    <i class="fa fa-chevron-left"></i>
                </button>
            `;
            navNext = `
                <button class="fullscreen-nav-btn fullscreen-nav-next ${isLast ? 'disabled' : ''}"
                        onclick="event.stopPropagation(); window.FileManagerFullscreen.navigate(1)" title="Suivant (→)">
                    <i class="fa fa-chevron-right"></i>
                </button>
            `;
            infoBar = `
                <div class="fullscreen-info">
                    <span class="filename" title="${escapeHtml(imageName)}">${escapeHtml(imageName)}</span>
                    <span class="counter">${previewIndex + 1} / ${previewSiblings.length}</span>
                </div>
            `;
        } else {
            infoBar = `
                <div class="fullscreen-info">
                    <span class="filename" title="${escapeHtml(imageName)}">${escapeHtml(imageName)}</span>
                </div>
            `;
        }

        overlay.innerHTML = `
            <button class="fullscreen-close-btn" onclick="event.stopPropagation(); window.FileManagerFullscreen.close()" title="Fermer (Échap)">
                <i class="fa fa-times"></i>
            </button>
            ${navPrev}
            <img src="${imageUrl}" alt="${escapeHtml(imageName)}" onclick="event.stopPropagation()">
            ${navNext}
            ${infoBar}
        `;

        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';
    }

    function closeFullscreen() {
        const overlay = document.getElementById('imageFullscreenOverlay');
        if (overlay) {
            overlay.remove();
            document.body.style.overflow = '';
        }
    }

    function navigateFullscreen(direction) {
        if (previewSiblings.length <= 1) return;

        const newIndex = previewIndex + direction;
        if (newIndex < 0 || newIndex >= previewSiblings.length) return;

        const nextNode = previewSiblings[newIndex];
        previewIndex = newIndex;

        // Fetch new preview data
        fetch(`${config.apiPreviewUrl || '/filemanager/api/preview/'}?path=${encodeURIComponent(nextNode.data.path)}`)
            .then(response => response.json())
            .then(data => {
                if (data.mime_type && data.mime_type.startsWith('image/')) {
                    // Update fullscreen image
                    const overlay = document.getElementById('imageFullscreenOverlay');
                    if (overlay) {
                        const img = overlay.querySelector('img');
                        const filename = overlay.querySelector('.filename');
                        const counter = overlay.querySelector('.counter');
                        const prevBtn = overlay.querySelector('.fullscreen-nav-prev');
                        const nextBtn = overlay.querySelector('.fullscreen-nav-next');

                        if (img) img.src = data.url;
                        if (filename) { filename.textContent = data.name; filename.title = data.name; }
                        if (counter) counter.textContent = `${previewIndex + 1} / ${previewSiblings.length}`;
                        if (prevBtn) prevBtn.classList.toggle('disabled', previewIndex === 0);
                        if (nextBtn) nextBtn.classList.toggle('disabled', previewIndex === previewSiblings.length - 1);
                    }

                    // Also update the preview panel in background
                    updatePreviewContent(data);
                } else {
                    // Not an image, close fullscreen and update panel
                    closeFullscreen();
                    updatePreviewContent(data);
                }
            })
            .catch(err => {
                console.error('Failed to navigate fullscreen:', err);
            });
    }

    function navigatePreview(direction) {
        if (previewSiblings.length <= 1) return;
        const newIndex = previewIndex + direction;
        if (newIndex < 0 || newIndex >= previewSiblings.length) return;
        _filemanagerFetchAndShow(newIndex);
    }

    function updatePreviewContent(data) {
        const modal = document.getElementById('filePreviewModal');
        if (!modal) return;

        const title = modal.querySelector('.modal-title');
        const container = modal.querySelector('.preview-container');
        const counter = modal.querySelector('.preview-counter');
        const prevBtn = modal.querySelector('.preview-nav-prev');
        const nextBtn = modal.querySelector('.preview-nav-next');

        // Update title with counter
        title.textContent = data.name;
        if (counter) {
            counter.textContent = `${previewIndex + 1} / ${previewSiblings.length}`;
        }

        // Update navigation button states
        if (prevBtn) prevBtn.classList.toggle('disabled', previewIndex === 0);
        if (nextBtn) nextBtn.classList.toggle('disabled', previewIndex === previewSiblings.length - 1);

        // Update content (inline panel)
        const mime = data.mime_type || '';
        if (mime.startsWith('image/')) {
            container.innerHTML = `
                <div class="preview-image-wrapper" ondblclick="window.FileManagerFullscreen.open('${data.url}', '${escapeHtml(data.name)}')">
                    <img src="${data.url}" alt="${data.name}" style="max-width:100%; max-height:70vh;">
                    <button class="preview-fullscreen-btn" onclick="event.stopPropagation(); window.FileManagerFullscreen.open('${data.url}', '${escapeHtml(data.name)}')" title="Plein écran (double-clic)">
                        <i class="fa fa-expand"></i>
                    </button>
                </div>
            `;
        } else if (mime.startsWith('video/')) {
            container.innerHTML = `
                <video controls autoplay muted style="max-width:100%; max-height:70vh;">
                    <source src="${data.url}" type="${mime}">
                </video>
                <div class="video-error-message d-none text-center p-4">
                    <i class="fa fa-exclamation-triangle fa-3x text-warning mb-3"></i>
                    <h5>Lecture impossible</h5>
                    <p class="mb-2">Le codec de cette vidéo n'est pas supporté par le navigateur.</p>
                    <a href="${data.url}" download class="btn btn-outline-light btn-sm">
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
        } else if (mime.startsWith('audio/')) {
            container.innerHTML = `<audio src="${data.url}" controls autoplay style="width:100%;"></audio>`;
        } else if (mime === 'application/pdf') {
            container.innerHTML = `
                <embed src="${data.url}" type="application/pdf"
                       style="width:100%; height:70vh; border:none; border-radius:6px;">
            `;
        } else if (data.text_content !== undefined) {
            const escapedContent = escapeHtml(data.text_content);
            container.innerHTML = `<pre class="text-preview" style="background:#0d1117;border:1px solid #374151;border-radius:6px;padding:15px;max-height:60vh;overflow:auto;white-space:pre-wrap;word-wrap:break-word;font-family:'Consolas','Monaco',monospace;font-size:0.85rem;color:#e2e8f0;margin:0;">${escapedContent}</pre>`;
        } else {
            container.innerHTML = `<p>Aperçu non disponible pour ce type de fichier</p>`;
        }
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
     * Import multiple files from FileManager to a specific app.
     * @param {string[]} paths - Array of file paths in media folder
     * @param {string} targetApp - The target app name
     * @returns {Promise<object>} - The import result
     */
    async function importMultipleToApp(paths, targetApp) {
        const response = await fetch(config.apiImportUrl || '/filemanager/api/import/', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': config.csrfToken || csrfToken,
            },
            body: JSON.stringify({ paths: paths, app: targetApp }),
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        return response.json();
    }

    /**
     * Create a new subfolder inside the user's temp directory.
     * @param {string} name - Folder name
     * @param {string} parentPath - Relative path of parent folder ('' for temp root)
     * @returns {Promise<object>}
     */
    async function mkdirFolder(name, parentPath) {
        const mkdirUrl = config.apiMkdirUrl || '/filemanager/api/mkdir/';
        const response = await fetch(mkdirUrl, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'X-CSRFToken': config.csrfToken || csrfToken,
            },
            body: JSON.stringify({ name: name, parent: parentPath || '' }),
        });
        if (!response.ok) {
            const data = await response.json().catch(() => ({}));
            throw new Error(data.error || `HTTP ${response.status}`);
        }
        return response.json();
    }

    /**
     * Check if a drop event contains a FileManager file.
     * @param {DragEvent} event - The drop event
     * @returns {object|null} - The file data or null
     */
    function getFileManagerData(event) {
        // First, try native dataTransfer (for HTML5 drag events)
        if (event && event.dataTransfer) {
            const wamaData = event.dataTransfer.getData('application/x-wama-file');
            if (wamaData) {
                try {
                    return JSON.parse(wamaData);
                } catch (e) {
                    // Continue to fallbacks
                }
            }

            // Fallback to plain text (path only)
            const textData = event.dataTransfer.getData('text/plain');
            if (textData && !textData.startsWith('http') && textData.includes('/')) {
                return { path: textData };
            }
        }

        // Fallback to global variable (for vakata.dnd which doesn't use native dataTransfer)
        if (window._fileManagerDragData) {
            const dragData = window._fileManagerDragData;
            // Clear it after use to prevent stale data
            window._fileManagerDragData = null;
            return dragData;
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
        importMultipleToApp: importMultipleToApp,
        getFileManagerData: getFileManagerData,
        handleDropFromFileManager: handleDropFromFileManager,
        showToast: showToast
    };
})();
