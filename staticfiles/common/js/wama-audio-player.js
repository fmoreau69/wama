/**
 * WAMA Audio Waveform Player
 * Implémentation pure Canvas + Web Audio API — aucune dépendance externe.
 *
 * Fonctionnalités :
 *   - Décodage audio → waveform sur Canvas
 *   - Lecture via <audio> natif (seek, pause, events)
 *   - Lecture exclusive (pause des autres players)
 *   - Init lazy au premier clic
 *   - Hauteur configurable via data-waveform-height
 *
 * API publique : window.WamaAudioPlayer
 *   .create(url, id, options)      → HTMLElement prêt à insérer
 *   .inject(url, id, parent, opts) → insère dans parent
 *   .init(container, autoplay)     → initialise un container existant
 *   .destroy(id)                   → stoppe + supprime du DOM
 *   .pauseAll()                    → met en pause tous les players
 */
(function(global) {
    'use strict';

    /** Map playerId → { audio, canvas, channelData, height } */
    var registry = new Map();

    /* ── Utilitaires ─────────────────────────────────────────────────── */

    function formatTime(s) {
        s = Math.floor(s || 0);
        return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }

    function getContainer(playerId) {
        return document.getElementById('audioPlayer_' + playerId);
    }

    function pauseOthers(currentId) {
        registry.forEach(function(state, id) {
            if (id !== currentId && state.audio && !state.audio.paused) {
                state.audio.pause();
            }
        });
    }

    /* ── Dessin waveform ─────────────────────────────────────────────── */

    function drawWaveform(canvas, channelData, progress) {
        var ctx = canvas.getContext('2d');
        var W = canvas.width;
        var H = canvas.height;
        if (!W || !H) return;

        ctx.clearRect(0, 0, W, H);

        var step = Math.ceil(channelData.length / W);
        for (var i = 0; i < W; i++) {
            var max = 0;
            var end = Math.min((i + 1) * step, channelData.length);
            for (var j = i * step; j < end; j++) {
                var v = Math.abs(channelData[j]);
                if (v > max) max = v;
            }
            var barH = Math.max(2, max * H * 0.9);
            var y    = (H - barH) / 2;
            ctx.fillStyle = (i / W) <= progress ? '#0dcaf0' : '#2c3e50';
            ctx.fillRect(i, y, 1, barH);
        }

        // Cursor
        var cx = Math.min(Math.floor(W * progress), W - 1);
        ctx.fillStyle = '#20c997';
        ctx.fillRect(cx, 0, 1, H);
    }

    /* ── Initialisation d'un player ─────────────────────────────────── */

    function initPlayer(container, autoplay) {
        var playerId = container.id.replace('audioPlayer_', '');
        var audioUrl = container.dataset.audioUrl;
        if (!audioUrl) return;

        // Déjà initialisé → play/pause direct
        if (registry.has(playerId)) {
            if (autoplay) {
                var existing = registry.get(playerId);
                if (existing.audio.paused) {
                    pauseOthers(playerId);
                    existing.audio.play().catch(function() {});
                } else {
                    existing.audio.pause();
                }
            }
            return;
        }

        var height      = parseInt(container.dataset.waveformHeight, 10) || 48;
        var waveformEl  = container.querySelector('.wama-waveform');
        var loadingEl   = container.querySelector('.wama-waveform-loading');
        var playBtnIcon = container.querySelector('.wama-play-btn i');
        var currentEl   = container.querySelector('.wama-current-time');
        var totalEl     = container.querySelector('.wama-total-time');

        /* Canvas -------------------------------------------------------- */
        var canvas = document.createElement('canvas');
        canvas.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;cursor:pointer;display:block;';
        if (waveformEl) {
            waveformEl.style.position = 'relative';
            waveformEl.style.height   = height + 'px';
            waveformEl.appendChild(canvas);
        }

        /* Audio natif --------------------------------------------------- */
        var audio = new Audio();
        audio.preload = 'metadata';

        var state = { audio: audio, canvas: canvas, channelData: null, height: height };
        registry.set(playerId, state);

        /* Décodage waveform (fetch séparé pour ne pas bloquer la lecture) */
        fetch(audioUrl)
            .then(function(r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.arrayBuffer();
            })
            .then(function(buf) {
                var ActxClass = global.AudioContext || global.webkitAudioContext;
                if (!ActxClass) throw new Error('AudioContext non disponible');
                var actx = new ActxClass();
                return actx.decodeAudioData(buf).then(function(audioBuf) {
                    actx.close();
                    return audioBuf;
                });
            })
            .then(function(audioBuf) {
                state.channelData = audioBuf.getChannelData(0);
                // Dimensionner le canvas une seule fois
                canvas.width  = waveformEl ? (waveformEl.offsetWidth || 400) : 400;
                canvas.height = height;
                drawWaveform(canvas, state.channelData, 0);
                if (loadingEl) loadingEl.style.display = 'none';
            })
            .catch(function(err) {
                console.warn('WamaAudioPlayer waveform [' + playerId + ']:', err);
                if (loadingEl) {
                    loadingEl.innerHTML =
                        '<small class="text-danger" style="font-size:0.7rem;">' +
                        '<i class="fas fa-exclamation-triangle me-1"></i>Erreur audio</small>';
                    loadingEl.style.display = 'flex';
                }
            });

        /* Évènements audio ---------------------------------------------- */
        audio.addEventListener('loadedmetadata', function() {
            if (totalEl) totalEl.textContent = formatTime(audio.duration);
        });

        audio.addEventListener('timeupdate', function() {
            if (currentEl) currentEl.textContent = formatTime(audio.currentTime);
            if (state.channelData && audio.duration) {
                var progress = audio.currentTime / audio.duration;
                // Redimensionner si besoin (e.g. après redimensionnement fenêtre)
                var w = waveformEl ? (waveformEl.offsetWidth || canvas.width) : canvas.width;
                if (Math.abs(canvas.width - w) > 2) {
                    canvas.width  = w;
                    canvas.height = height;
                }
                drawWaveform(canvas, state.channelData, progress);
            }
        });

        audio.addEventListener('play', function() {
            pauseOthers(playerId);
            if (playBtnIcon) playBtnIcon.className = 'fas fa-pause fa-xs';
        });

        audio.addEventListener('pause', function() {
            if (playBtnIcon) playBtnIcon.className = 'fas fa-play fa-xs';
        });

        audio.addEventListener('ended', function() {
            if (playBtnIcon) playBtnIcon.className = 'fas fa-play fa-xs';
            if (state.channelData) drawWaveform(canvas, state.channelData, 0);
        });

        audio.addEventListener('error', function() {
            console.warn('WamaAudioPlayer erreur audio [' + playerId + ']');
            if (loadingEl) {
                loadingEl.innerHTML =
                    '<small class="text-danger" style="font-size:0.7rem;">' +
                    '<i class="fas fa-exclamation-triangle me-1"></i>Erreur audio</small>';
                loadingEl.style.display = 'flex';
            }
        });

        /* Click sur le canvas → seek ------------------------------------ */
        canvas.addEventListener('click', function(e) {
            if (!audio.duration) return;
            var rect  = canvas.getBoundingClientRect();
            var ratio = (e.clientX - rect.left) / rect.width;
            audio.currentTime = Math.max(0, Math.min(1, ratio)) * audio.duration;
        });

        audio.src = audioUrl;
        if (autoplay) {
            pauseOthers(playerId);
            audio.play().catch(function() {});
        }
    }

    /* ── Création d'élément DOM ─────────────────────────────────────── */

    function createElement(audioUrl, playerId, options) {
        var height = (options && options.height) ? options.height : 48;
        var esc    = String(audioUrl).replace(/"/g, '&quot;');
        var div    = document.createElement('div');
        div.innerHTML =
            '<div class="wama-audio-player"' +
                ' data-audio-url="' + esc + '"' +
                ' data-waveform-height="' + height + '"' +
                ' id="audioPlayer_' + playerId + '">' +
                '<div class="wama-waveform-wrap">' +
                    '<div class="wama-waveform" id="waveform_' + playerId + '"></div>' +
                    '<div class="wama-waveform-loading" id="waveformLoading_' + playerId + '">' +
                        '<i class="fas fa-spinner fa-spin text-muted" style="font-size:0.8rem;"></i>' +
                    '</div>' +
                '</div>' +
                '<div class="d-flex align-items-center gap-2 px-1 pt-1">' +
                    '<button class="wama-play-btn" data-player-id="' + playerId + '" title="Lecture / Pause">' +
                        '<i class="fas fa-play fa-xs"></i>' +
                    '</button>' +
                    '<div class="wama-audio-time">' +
                        '<span class="wama-current-time">0:00</span>' +
                        '<span class="text-secondary"> / </span>' +
                        '<span class="wama-total-time">--:--</span>' +
                    '</div>' +
                '</div>' +
            '</div>';
        return div.firstElementChild;
    }

    /* ── Délégation de clic globale ──────────────────────────────────── */

    document.addEventListener('click', function(e) {
        var btn = e.target.closest('.wama-play-btn');
        if (!btn) return;
        var playerId  = btn.dataset.playerId;
        var container = getContainer(playerId);
        if (!container) return;
        initPlayer(container, true);
    });

    /* ── API publique ────────────────────────────────────────────────── */

    global.WamaAudioPlayer = {

        /** Crée un élément DOM player (non encore initialisé). */
        create: function(audioUrl, playerId, options) {
            return createElement(audioUrl, String(playerId), options);
        },

        /** Initialise manuellement un container existant. */
        init: function(container, autoplay) {
            if (container) initPlayer(container, !!autoplay);
        },

        /** Insère un player dans parentEl (remplace l'existant si besoin). */
        inject: function(audioUrl, playerId, parentEl, options) {
            if (!parentEl || !audioUrl) return;
            var id = String(playerId);
            this.destroy(id);
            parentEl.appendChild(createElement(audioUrl, id, options));
        },

        /** Détruit un player et le retire du DOM. */
        destroy: function(playerId) {
            var id = String(playerId);
            if (registry.has(id)) {
                var s = registry.get(id);
                if (s.audio) { s.audio.pause(); s.audio.src = ''; }
                registry.delete(id);
            }
            var el = document.getElementById('audioPlayer_' + id);
            if (el) el.remove();
        },

        /** Met en pause tous les players actifs. */
        pauseAll: function() {
            registry.forEach(function(state) {
                if (state.audio && !state.audio.paused) state.audio.pause();
            });
        },
    };

})(window);
