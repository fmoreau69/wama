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

    // Current preview data for fullscreen
    let currentPreviewData = null;

    // Navigation state
    let previewItems = [];
    let previewCurrentIndex = -1;

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

        // Show the modal
        showPreviewModal(data);
    }

    /**
     * Show the preview modal with the given media data.
     */
    function showPreviewModal(data) {
        if (!data || !data.url) {
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

        // Show modal
        const bsModal = new bootstrap.Modal(modal);
        bsModal.show();

        // Clean up when modal is hidden
        modal.addEventListener('hidden.bs.modal', function() {
            // Stop any playing media
            const video = container.querySelector('video');
            const audio = container.querySelector('audio');
            if (video) video.pause();
            if (audio) audio.pause();
            currentPreviewData = null;
            // Reset navigation state
            previewItems = [];
            previewCurrentIndex = -1;
        }, { once: true });
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
            const audioContainer = document.createElement('div');
            audioContainer.className = 'text-center p-4';

            const icon = document.createElement('i');
            icon.className = 'fas fa-music fa-5x text-info mb-4';
            audioContainer.appendChild(icon);

            const audio = document.createElement('audio');
            audio.src = data.url;
            audio.controls = true;
            audio.className = 'w-100';
            audio.style.maxWidth = '500px';
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
            fullscreenBtn.innerHTML = '<i class="fas fa-expand"></i>';
            fullscreenBtn.onclick = function(e) {
                e.stopPropagation();
                openFullscreen(data.url, data.name);
            };
            wrapper.appendChild(fullscreenBtn);

            return wrapper;
        } else if (mimeType === 'application/pdf') {
            const iframe = document.createElement('iframe');
            iframe.src = data.url;
            iframe.className = 'w-100';
            iframe.style.height = '70vh';
            iframe.style.border = 'none';
            return iframe;
        } else {
            // Fallback: show download link
            const fallback = document.createElement('div');
            fallback.className = 'text-center p-4';
            fallback.innerHTML = `
                <i class="fas fa-file fa-5x text-secondary mb-4"></i>
                <p class="mb-3">Preview not available for this file type</p>
                <a href="${data.url}" class="btn btn-primary" download>
                    <i class="fas fa-download"></i> Download
                </a>
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
                    <div class="modal-header border-secondary">
                        <h5 class="modal-title"></h5>
                        <span class="wama-preview-counter badge bg-secondary ms-2" style="display: none;"></span>
                        <button type="button" class="btn-close btn-close-white ms-auto" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body p-0">
                        <div class="preview-container d-flex justify-content-center align-items-center" style="min-height: 300px; background: #1a1a1a;">
                            <button class="wama-preview-nav-btn wama-preview-nav-prev" style="display: none;" title="Précédent (←)">
                                <i class="fas fa-chevron-left"></i>
                            </button>
                            <button class="wama-preview-nav-btn wama-preview-nav-next" style="display: none;" title="Suivant (→)">
                                <i class="fas fa-chevron-right"></i>
                            </button>
                        </div>
                    </div>
                    <div class="modal-footer border-secondary py-2">
                        <small class="preview-meta text-muted"></small>
                    </div>
                </div>
            </div>
        `;

        // Bind navigation button clicks
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
                <button class="wama-preview-nav-btn wama-preview-nav-prev ${previewCurrentIndex === 0 ? 'disabled' : ''}"
                        title="Précédent (←)">
                    <i class="fas fa-chevron-left"></i>
                </button>
                <button class="wama-preview-nav-btn wama-preview-nav-next ${previewCurrentIndex === previewItems.length - 1 ? 'disabled' : ''}"
                        title="Suivant (→)">
                    <i class="fas fa-chevron-right"></i>
                </button>
            `;
        }

        // Counter for fullscreen
        let counterHtml = '';
        if (previewItems.length > 1) {
            counterHtml = `<span class="wama-preview-counter badge bg-secondary ms-2">${previewCurrentIndex + 1} / ${previewItems.length}</span>`;
        }

        overlay.innerHTML = `
            <button class="fullscreen-close-btn" title="Fermer (Échap)">
                <i class="fas fa-times"></i>
            </button>
            ${navHtml}
            <img src="${imageUrl}" alt="${escapeHtml(imageName || 'Image')}" onclick="event.stopPropagation()">
            <div class="fullscreen-info">
                <span class="filename">${escapeHtml(imageName || 'Image')}</span>
                ${counterHtml}
            </div>
        `;

        // Bind close button
        overlay.querySelector('.fullscreen-close-btn').addEventListener('click', function(e) {
            e.stopPropagation();
            closeFullscreen();
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

    // Export functions to window for external use
    window.initMediaPreview = initMediaPreview;
    window.showPreviewModal = showPreviewModal;
    window.showPreviewModalWithNav = showPreviewModalWithNav;
    window.openWamaFullscreen = openFullscreen;
    window.closeWamaFullscreen = closeFullscreen;

})();
