/**
 * WAMA Common - Media Preview
 *
 * Unified media preview functionality for all WAMA applications.
 * Handles video, audio, image, and document previews in a modal.
 * Includes fullscreen support for images and optional navigation (prev/next).
 *
 * Usage:
 *   1. Include this script in your template
 *   2. Add class="preview-media-link" and data-preview-url="..." to clickable elements
 *   3. Call initMediaPreview() after DOM is ready (or it auto-initializes)
 *
 * Navigation usage:
 *   showPreviewModalWithNav(currentItem, allItems, currentIndex)
 *   - allItems: [{url, name, mime_type}, ...]
 *   - currentIndex: position in array
 *
 * The data-preview-url should point to an endpoint that returns JSON with:
 *   - name: filename
 *   - url: absolute URL to the media file
 *   - mime_type: MIME type (e.g., 'video/mp4', 'audio/wav', 'image/jpeg')
 *   - duration: optional duration string
 *   - resolution: optional resolution string
 *   - properties: optional additional properties
 */

(function() {
    'use strict';

    // SVG icons — pas de dépendance Font Awesome
    const _SVG_PREV  = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 18 9 12 15 6"/></svg>`;
    const _SVG_NEXT  = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="9 18 15 12 9 6"/></svg>`;
    const _SVG_CLOSE = `<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`;
    const _SVG_EXPAND = `<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="15 3 21 3 21 9"/><polyline points="9 21 3 21 3 15"/><line x1="21" y1="3" x2="14" y2="10"/><line x1="3" y1="21" x2="10" y2="14"/></svg>`;

    // Current preview data for fullscreen
    let currentPreviewData = null;

    // Navigation state
    let previewItems = [];
    let previewCurrentIndex = -1;

    // Optional external nav callback (e.g. filemanager with lazy-loaded siblings)
    // Signature: callback(newIndex) — called instead of indexing previewItems
    let _navCallback = null;

    // Flag : cleanup listener enregistré une seule fois
    let _cleanupBound = false;

    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        initMediaPreview();
        setupKeyboardHandlers();
    }

    /**
     * Initialize media preview functionality.
     * Binds click handlers to elements with .preview-media-link class.
     */
    function initMediaPreview() {
        document.querySelectorAll('.preview-media-link').forEach(function(btn) {
            // Skip if already bound
            if (btn.dataset.previewBound === '1') {
                return;
            }
            btn.dataset.previewBound = '1';

            btn.addEventListener('click', function(event) {
                event.preventDefault();
                event.stopPropagation();

                const endpoint = btn.dataset.previewUrl;
                if (!endpoint) {
                    console.warn('[MediaPreview] No preview URL specified');
                    return;
                }

                // Show loading state
                btn.style.opacity = '0.5';

                fetch(endpoint)
                    .then(function(response) {
                        if (!response.ok) {
                            throw new Error('Preview unavailable');
                        }
                        return response.json();
                    })
                    .then(function(data) {
                        showPreviewModal(data);
                    })
                    .catch(function(err) {
                        showPreviewError(err.message);
                    })
                    .finally(function() {
                        btn.style.opacity = '1';
                    });
            });
        });
    }

    /**
     * Setup keyboard handlers for navigation and fullscreen.
     */
    function setupKeyboardHandlers() {
        document.addEventListener('keydown', function(e) {
            // Ignore if user is typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            // Check if fullscreen is open
            const fullscreenOverlay = document.getElementById('wamaFullscreenOverlay');
            if (fullscreenOverlay) {
                if (e.key === 'Escape') {
                    e.preventDefault();
                    closeFullscreen();
                } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    navigatePreview(-1);
                } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                    e.preventDefault();
                    navigatePreview(1);
                }
                return;
            }

            // Check if preview modal is open
            const modal = document.getElementById('wamaMediaPreviewModal');
            if (modal && modal.classList.contains('show')) {
                if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
                    e.preventDefault();
                    navigatePreview(-1);
                } else if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
                    e.preventDefault();
                    navigatePreview(1);
                }
            }
        });
    }

    /**
     * Escape HTML special characters.
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Show the preview modal with navigation support.
     *
     * @param {Object} data - Current item: {url, name, mime_type, ...}
     * @param {Array} items - All navigable items: [{url, name, mime_type}, ...]
     * @param {number} currentIndex - Current position in items array
     */
    function showPreviewModalWithNav(data, items, currentIndex) {
        // Store navigation state
        previewItems = items || [];
        previewCurrentIndex = (typeof currentIndex === 'number') ? currentIndex : -1;
        _navCallback = null;  // clear any external callback set previously

        // Show the modal
        showPreviewModal(data);
    }

    /**
     * Show the preview modal with the given media data.
     */
    function showPreviewModal(data) {
        if (!data || (!data.url && data.text_content === undefined)) {
            showPreviewError('No media URL available');
            return;
        }

        // Store current data for fullscreen
        currentPreviewData = data;

        let modal = document.getElementById('wamaMediaPreviewModal');

        if (!modal) {
            modal = createPreviewModal();
            document.body.appendChild(modal);
        }

        // Update modal content
        const title = modal.querySelector('.modal-title');
        const container = modal.querySelector('.preview-container');
        const meta = modal.querySelector('.preview-meta');

        title.textContent = data.name || 'Preview';

        // Clear previous content (keep nav buttons)
        const prevContent = container.querySelectorAll(':not(.wama-preview-nav-btn)');
        prevContent.forEach(function(el) { el.remove(); });

        // Build preview content
        const contentEl = buildPreviewContent(data);
        container.appendChild(contentEl);

        // Update metadata
        const metaParts = [];
        if (data.duration) metaParts.push(data.duration);
        if (data.resolution) metaParts.push(data.resolution);
        if (data.properties) metaParts.push(data.properties);
        meta.textContent = metaParts.join(' | ');

        // Update navigation UI
        updateNavigationUI(modal);

        // Enregistrer le cleanup UNE SEULE FOIS (pas à chaque navigation)
        if (!_cleanupBound) {
            _cleanupBound = true;
            modal.addEventListener('hidden.bs.modal', function() {
                const c = modal.querySelector('.preview-container');
                const video = c ? c.querySelector('video') : null;
                const audio = c ? c.querySelector('audio') : null;
                if (video) video.pause();
                if (audio) audio.pause();
                if (window.WamaAudioPlayer) WamaAudioPlayer.destroy('modal-audio');
                currentPreviewData = null;
                previewItems = [];
                previewCurrentIndex = -1;
                _navCallback = null;
                _cleanupBound = false; // reset pour la prochaine ouverture
            });
        }

        // Mettre en pause les players inline
        if (window.WamaAudioPlayer) WamaAudioPlayer.pauseAll();

        // getOrCreateInstance : réutilise l'instance existante (évite l'empilement de backdrops)
        const bsModal = bootstrap.Modal.getOrCreateInstance(modal);
        bsModal.show();
    }

    /**
     * Build the preview content element based on MIME type.
     */
    function buildPreviewContent(data) {
        const mimeType = data.mime_type || '';

        if (mimeType.startsWith('video/')) {
            const video = document.createElement('video');
            video.src = data.url;
            video.controls = true;
            video.autoplay = false;
            video.className = 'w-100';
            video.style.maxHeight = '70vh';
            return video;
        } else if (mimeType.startsWith('audio/')) {
            if (window.WamaAudioPlayer) {
                const wrapper = document.createElement('div');
                wrapper.className = 'p-3 w-100';
                wrapper.appendChild(WamaAudioPlayer.create(data.url, 'modal-audio', { height: 80 }));
                return wrapper;
            }
            // Fallback si WaveSurfer non chargé
            const audioContainer = document.createElement('div');
            audioContainer.className = 'wama-audio-preview text-center w-100 p-4';
            const audio = document.createElement('audio');
            audio.src = data.url;
            audio.controls = true;
            audio.className = 'w-100';
            audioContainer.appendChild(audio);
            return audioContainer;
        } else if (mimeType.startsWith('image/')) {
            // Create wrapper with fullscreen button
            const wrapper = document.createElement('div');
            wrapper.className = 'preview-image-wrapper';
            wrapper.ondblclick = function() {
                openFullscreen(data.url, data.name);
            };

            const img = document.createElement('img');
            img.src = data.url;
            img.className = 'img-fluid';
            img.style.maxHeight = '70vh';
            img.alt = data.name || 'Image preview';
            wrapper.appendChild(img);

            const fullscreenBtn = document.createElement('button');
            fullscreenBtn.className = 'preview-fullscreen-btn';
            fullscreenBtn.title = 'Plein écran (double-clic)';
            fullscreenBtn.innerHTML = _SVG_EXPAND;
            fullscreenBtn.onclick = function(e) {
                e.stopPropagation();
                openFullscreen(data.url, data.name);
            };
            wrapper.appendChild(fullscreenBtn);

            return wrapper;
        } else if (mimeType === 'application/pdf') {
            // Use <embed> instead of <iframe> — X-Frame-Options: deny does not apply to <embed>
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100';

            const embed = document.createElement('embed');
            embed.src = data.url;
            embed.type = 'application/pdf';
            embed.className = 'w-100';
            embed.style.height = '70vh';
            wrapper.appendChild(embed);

            const fallbackLink = document.createElement('div');
            fallbackLink.className = 'text-center mt-2';
            fallbackLink.innerHTML = `<a href="${escapeHtml(data.url)}" target="_blank" rel="noopener" class="btn btn-sm btn-outline-light"><i class="fas fa-external-link-alt me-1"></i>Ouvrir dans un nouvel onglet</a>`;
            wrapper.appendChild(fallbackLink);

            return wrapper;
        } else if (mimeType === 'text/plain' || (mimeType.startsWith('text/') && !mimeType.startsWith('text/html'))) {
            // Text file: fetch content and display in scrollable pre
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100';

            const toolbar = document.createElement('div');
            toolbar.className = 'd-flex justify-content-end mb-2 gap-2';

            const copyBtn = document.createElement('button');
            copyBtn.className = 'btn btn-sm btn-outline-secondary';
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier';

            const openBtn = document.createElement('a');
            openBtn.href = data.url;
            openBtn.target = '_blank';
            openBtn.rel = 'noopener';
            openBtn.className = 'btn btn-sm btn-outline-light';
            openBtn.innerHTML = '<i class="fas fa-external-link-alt"></i> Ouvrir';

            toolbar.appendChild(copyBtn);
            toolbar.appendChild(openBtn);

            const pre = document.createElement('pre');
            pre.className = 'text-light p-3 mb-0';
            pre.style.cssText = 'max-height:65vh; overflow-y:auto; background:#1e1e1e; border-radius:4px; font-size:13px; white-space:pre-wrap; word-wrap:break-word; border:1px solid #495057;';
            pre.textContent = 'Chargement…';

            copyBtn.addEventListener('click', () => {
                navigator.clipboard.writeText(pre.textContent).then(() => {
                    copyBtn.innerHTML = '<i class="fas fa-check text-success"></i> Copié';
                    setTimeout(() => { copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier'; }, 2000);
                }).catch(() => {});
            });

            wrapper.appendChild(toolbar);
            wrapper.appendChild(pre);

            fetch(data.url)
                .then(r => r.ok ? r.text() : Promise.reject(r.status))
                .then(text => { pre.textContent = text; })
                .catch(err => { pre.textContent = `Erreur lors du chargement (${err}).`; });

            return wrapper;
        } else if (data.text_content !== undefined) {
            // Pre-extracted text (e.g., DOCX — no direct URL available)
            const wrapper = document.createElement('div');
            wrapper.className = 'w-100';

            const copyBtn = document.createElement('button');
            copyBtn.className = 'btn btn-sm btn-outline-secondary mb-2';
            copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier';

            const pre = document.createElement('pre');
            pre.className = 'text-light p-3 mb-0';
            pre.style.cssText = 'max-height:65vh; overflow-y:auto; background:#1e1e1e; border-radius:4px; font-size:13px; white-space:pre-wrap; word-wrap:break-word; border:1px solid #495057;';
            pre.textContent = data.text_content || '';

            copyBtn.addEventListener('click', () => {
                navigator.clipboard.writeText(pre.textContent).then(() => {
                    copyBtn.innerHTML = '<i class="fas fa-check text-success"></i> Copié';
                    setTimeout(() => { copyBtn.innerHTML = '<i class="fas fa-copy"></i> Copier'; }, 2000);
                }).catch(() => {});
            });

            wrapper.appendChild(copyBtn);
            wrapper.appendChild(pre);
            return wrapper;
        } else {
            // Fallback: show download link (only if URL available)
            const fallback = document.createElement('div');
            fallback.className = 'text-center p-4';
            const downloadLink = data.url
                ? `<a href="${escapeHtml(data.url)}" class="btn btn-primary" download><i class="fas fa-download"></i> Download</a>`
                : '';
            fallback.innerHTML = `
                <i class="fas fa-file fa-5x text-secondary mb-4"></i>
                <p class="mb-3">Preview not available for this file type</p>
                ${downloadLink}
            `;
            return fallback;
        }
    }

    /**
     * Navigate to previous or next item.
     * @param {number} direction - -1 for previous, 1 for next
     */
    function navigatePreview(direction) {
        if (previewItems.length <= 1) return;

        const newIndex = previewCurrentIndex + direction;
        if (newIndex < 0 || newIndex >= previewItems.length) return;

        previewCurrentIndex = newIndex;

        // External callback (e.g. filemanager lazy-loads its own siblings)
        if (_navCallback) {
            const modal = document.getElementById('wamaMediaPreviewModal');
            if (modal) updateNavigationUI(modal);
            _navCallback(newIndex);
            return;
        }

        const item = previewItems[previewCurrentIndex];

        // Store current data
        currentPreviewData = item;

        // Update modal content
        const modal = document.getElementById('wamaMediaPreviewModal');
        if (!modal) return;

        const title = modal.querySelector('.modal-title');
        const container = modal.querySelector('.preview-container');
        const meta = modal.querySelector('.preview-meta');

        title.textContent = item.name || 'Preview';

        // Clear previous content (keep nav buttons)
        const prevContent = container.querySelectorAll(':not(.wama-preview-nav-btn)');
        prevContent.forEach(function(el) { el.remove(); });

        // Stop any playing media
        const video = container.querySelector('video');
        const audio = container.querySelector('audio');
        if (video) video.pause();
        if (audio) audio.pause();
        if (window.WamaAudioPlayer) WamaAudioPlayer.destroy('modal-audio');

        // Build new content
        const contentEl = buildPreviewContent(item);
        container.appendChild(contentEl);

        // Update metadata
        const metaParts = [];
        if (item.duration) metaParts.push(item.duration);
        if (item.resolution) metaParts.push(item.resolution);
        if (item.properties) metaParts.push(item.properties);
        meta.textContent = metaParts.join(' | ');

        // Update navigation UI
        updateNavigationUI(modal);

        // If fullscreen is open, update it too
        const fullscreenOverlay = document.getElementById('wamaFullscreenOverlay');
        if (fullscreenOverlay && item.mime_type && item.mime_type.startsWith('image/')) {
            const fsImg = fullscreenOverlay.querySelector('img');
            const fsName = fullscreenOverlay.querySelector('.filename');
            const fsCounter = fullscreenOverlay.querySelector('.wama-preview-counter');
            if (fsImg) fsImg.src = item.url;
            if (fsName) fsName.textContent = item.name || 'Image';
            if (fsCounter) fsCounter.textContent = (previewCurrentIndex + 1) + ' / ' + previewItems.length;
            // Réinitialiser le mode zoom à chaque changement d'image
            fullscreenOverlay.classList.remove('wama-fs-actual');
        }
    }

    /**
     * Update the navigation buttons and counter visibility/state.
     */
    function updateNavigationUI(modal) {
        const counter = modal.querySelector('.wama-preview-counter');
        const prevBtn = modal.querySelector('.wama-preview-nav-prev');
        const nextBtn = modal.querySelector('.wama-preview-nav-next');
        const hasNav = previewItems.length > 1;

        // Counter
        if (counter) {
            if (hasNav) {
                counter.textContent = (previewCurrentIndex + 1) + ' / ' + previewItems.length;
                counter.style.display = '';
            } else {
                counter.style.display = 'none';
            }
        }

        // Navigation buttons
        if (prevBtn) {
            prevBtn.style.display = hasNav ? '' : 'none';
            prevBtn.classList.toggle('disabled', previewCurrentIndex === 0);
        }
        if (nextBtn) {
            nextBtn.style.display = hasNav ? '' : 'none';
            nextBtn.classList.toggle('disabled', previewCurrentIndex === previewItems.length - 1);
        }
    }

    /**
     * Create the preview modal element.
     */
    function createPreviewModal() {
        const modal = document.createElement('div');
        modal.id = 'wamaMediaPreviewModal';
        modal.className = 'modal fade';
        modal.tabIndex = -1;
        modal.innerHTML = `
            <div class="modal-dialog modal-lg modal-dialog-centered modal-dialog-scrollable">
                <div class="modal-content bg-dark text-white">
                    <div class="modal-header border-secondary py-2">
                        <h6 class="modal-title text-truncate" style="max-width:70%;font-size:.95rem;"></h6>
                        <span class="wama-preview-counter text-muted small ms-2" style="display:none;white-space:nowrap;flex-shrink:0;"></span>
                        <button type="button" class="btn-close btn-close-white ms-auto" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body p-0 position-relative">
                        <!-- Boutons nav FRÈRES du container (pas dedans) — évite tout conflit z-index/flex -->
                        <button class="wama-preview-nav-btn wama-preview-nav-prev" style="display:none;" title="Précédent (←)">${_SVG_PREV}</button>
                        <button class="wama-preview-nav-btn wama-preview-nav-next" style="display:none;" title="Suivant (→)">${_SVG_NEXT}</button>
                        <div class="preview-container d-flex justify-content-center align-items-center" style="min-height:300px;background:#111;"></div>
                    </div>
                    <div class="modal-footer border-secondary py-2">
                        <small class="preview-meta text-muted w-100 text-center"></small>
                    </div>
                </div>
            </div>
        `;

        modal.querySelector('.wama-preview-nav-prev').addEventListener('click', function(e) {
            e.stopPropagation();
            navigatePreview(-1);
        });
        modal.querySelector('.wama-preview-nav-next').addEventListener('click', function(e) {
            e.stopPropagation();
            navigatePreview(1);
        });

        return modal;
    }

    /**
     * Open fullscreen overlay for an image.
     */
    function openFullscreen(imageUrl, imageName) {
        // Remove existing overlay if any
        closeFullscreen();

        const overlay = document.createElement('div');
        overlay.id = 'wamaFullscreenOverlay';
        overlay.onclick = function(e) {
            if (e.target === overlay) closeFullscreen();
        };

        // Build navigation buttons for fullscreen if nav is active
        let navHtml = '';
        if (previewItems.length > 1) {
            navHtml = `
                <button class="wama-preview-nav-btn wama-preview-nav-prev ${previewCurrentIndex === 0 ? 'disabled' : ''}" title="Précédent (←)">${_SVG_PREV}</button>
                <button class="wama-preview-nav-btn wama-preview-nav-next ${previewCurrentIndex === previewItems.length - 1 ? 'disabled' : ''}" title="Suivant (→)">${_SVG_NEXT}</button>
            `;
        }

        // Counter for fullscreen
        let counterHtml = '';
        if (previewItems.length > 1) {
            counterHtml = `<span class="wama-preview-counter">${previewCurrentIndex + 1} / ${previewItems.length}</span>`;
        }

        overlay.innerHTML = `
            <button class="fullscreen-close-btn" title="Fermer (Échap)">${_SVG_CLOSE}</button>
            ${navHtml}
            <img src="${imageUrl}" alt="${escapeHtml(imageName || 'Image')}" title="Cliquer pour basculer taille réelle / adapté">
            <div class="fullscreen-info">
                <span class="filename">${escapeHtml(imageName || 'Image')}</span>
                ${counterHtml}
            </div>
        `;

        // Bouton fermer
        overlay.querySelector('.fullscreen-close-btn').addEventListener('click', function(e) {
            e.stopPropagation();
            closeFullscreen();
        });

        // Clic sur l'image → toggle taille réelle / adapté à l'écran
        overlay.querySelector('img').addEventListener('click', function(e) {
            e.stopPropagation();
            overlay.classList.toggle('wama-fs-actual');
        });

        // Bind nav buttons in fullscreen
        const fsPrevBtn = overlay.querySelector('.wama-preview-nav-prev');
        const fsNextBtn = overlay.querySelector('.wama-preview-nav-next');
        if (fsPrevBtn) {
            fsPrevBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                navigatePreview(-1);
            });
        }
        if (fsNextBtn) {
            fsNextBtn.addEventListener('click', function(e) {
                e.stopPropagation();
                navigatePreview(1);
            });
        }

        document.body.appendChild(overlay);
        document.body.style.overflow = 'hidden';
    }

    /**
     * Close fullscreen overlay.
     */
    function closeFullscreen() {
        const overlay = document.getElementById('wamaFullscreenOverlay');
        if (overlay) {
            overlay.remove();
            document.body.style.overflow = '';
        }
    }

    /**
     * Show an error message in the preview.
     */
    function showPreviewError(message) {
        // Try to use toast if available
        if (window.FileManager && window.FileManager.showToast) {
            window.FileManager.showToast(message, 'danger');
            return;
        }

        // Try Bootstrap toast
        if (typeof showToast === 'function') {
            showToast(message, 'danger');
            return;
        }

        // Fallback to console
        console.error('Preview error:', message);
    }

    /**
     * Global delegated handler for .copy-result-btn buttons.
     * Any element with class "copy-result-btn" and data-target="<elementId>"
     * will copy the textContent of that element to clipboard.
     */
    document.addEventListener('click', function(e) {
        const btn = e.target.closest('.copy-result-btn');
        if (!btn) return;
        const el = document.getElementById(btn.dataset.target);
        if (!el) return;
        navigator.clipboard.writeText(el.textContent || el.innerText).then(() => {
            btn.innerHTML = '<i class="fas fa-check text-success"></i>';
            setTimeout(() => { btn.innerHTML = '<i class="fas fa-copy"></i>'; }, 2000);
        }).catch(() => {
            const range = document.createRange();
            range.selectNodeContents(el);
            window.getSelection().removeAllRanges();
            window.getSelection().addRange(range);
        });
    });

    /**
     * Show a simple text modal with a copy button.
     * Can be called from any app for displaying result/OCR text.
     * @param {string} text    - The text to display
     * @param {string} title   - Modal title (filename, label…)
     */
    function showTextModal(text, title) {
        showPreviewModal({ text_content: text || '', name: title || 'Texte' });
    }

    // Export functions to window for external use
    window.initMediaPreview = initMediaPreview;
    window.showPreviewModal = showPreviewModal;
    window.showPreviewModalWithNav = showPreviewModalWithNav;
    window.setPreviewNavCallback = function(cb) { _navCallback = cb; };
    window.showTextModal = showTextModal;
    window.openWamaFullscreen = openFullscreen;
    window.closeWamaFullscreen = closeFullscreen;

})();
