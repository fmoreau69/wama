/**
 * WAMA Common - Media Preview
 *
 * Unified media preview functionality for all WAMA applications.
 * Handles video, audio, image, and document previews in a modal.
 * Includes fullscreen support for images.
 *
 * Usage:
 *   1. Include this script in your template
 *   2. Add class="preview-media-link" and data-preview-url="..." to clickable elements
 *   3. Call initMediaPreview() after DOM is ready (or it auto-initializes)
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
     * Setup keyboard handlers for fullscreen.
     */
    function setupKeyboardHandlers() {
        document.addEventListener('keydown', function(e) {
            // Ignore if user is typing in an input
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') return;

            // Check if fullscreen is open
            const fullscreenOverlay = document.getElementById('wamaFullscreenOverlay');
            if (fullscreenOverlay && e.key === 'Escape') {
                e.preventDefault();
                closeFullscreen();
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

        // Clear previous content
        container.innerHTML = '';

        // Create appropriate preview element based on MIME type
        const mimeType = data.mime_type || '';

        if (mimeType.startsWith('video/')) {
            const video = document.createElement('video');
            video.src = data.url;
            video.controls = true;
            video.autoplay = false;
            video.className = 'w-100';
            video.style.maxHeight = '70vh';
            container.appendChild(video);
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

            container.appendChild(audioContainer);
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

            container.appendChild(wrapper);
        } else if (mimeType === 'application/pdf') {
            const iframe = document.createElement('iframe');
            iframe.src = data.url;
            iframe.className = 'w-100';
            iframe.style.height = '70vh';
            iframe.style.border = 'none';
            container.appendChild(iframe);
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
            container.appendChild(fallback);
        }

        // Update metadata
        const metaParts = [];
        if (data.duration) metaParts.push(data.duration);
        if (data.resolution) metaParts.push(data.resolution);
        if (data.properties) metaParts.push(data.properties);
        meta.textContent = metaParts.join(' | ');

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
        }, { once: true });
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
                        <button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal" aria-label="Close"></button>
                    </div>
                    <div class="modal-body p-0">
                        <div class="preview-container d-flex justify-content-center align-items-center" style="min-height: 300px; background: #1a1a1a;"></div>
                    </div>
                    <div class="modal-footer border-secondary py-2">
                        <small class="preview-meta text-muted"></small>
                    </div>
                </div>
            </div>
        `;
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

        overlay.innerHTML = `
            <button class="fullscreen-close-btn" onclick="event.stopPropagation(); window.closeWamaFullscreen()" title="Fermer (Échap)">
                <i class="fas fa-times"></i>
            </button>
            <img src="${imageUrl}" alt="${escapeHtml(imageName || 'Image')}" onclick="event.stopPropagation()">
            <div class="fullscreen-info">
                <span class="filename">${escapeHtml(imageName || 'Image')}</span>
            </div>
        `;

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
    window.openWamaFullscreen = openFullscreen;
    window.closeWamaFullscreen = closeFullscreen;

})();
