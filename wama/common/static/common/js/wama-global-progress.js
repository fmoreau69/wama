/* ===========================================================================
 * WAMA — Barre de progression globale commune (toujours visible)
 * ===========================================================================
 * Composant inter-apps. Pilote le partial common/_global_progress.html.
 *
 * Apps MONO-domaine (1 barre) — auto-init : poser sur la page
 *   window.WAMA_GLOBAL_PROGRESS_URL = "<endpoint>"
 *
 * Apps MULTI-domaines (N barres : imager image/vidéo, enhancer audio…) — réutiliser
 * la MÊME fonction, 1 appel par barre (pas de poller bespoke par app) :
 *   WamaGlobalProgress.init({ url, dataKey, bar, stats, pct, eta, status, interval, onData })
 *
 * L'endpoint renvoie un JSON tolérant : { total, done|success|completed,
 *   running, failed|failure|error, overall_progress? }  (overall_progress dérivé si absent).
 * dataKey : extrait data[dataKey] pour les endpoints imbriqués (ex. {image:{…}, video:{…}}).
 *
 * Comportement commun à TOUTES les barres :
 *   - met à jour #<…>ProgressBar / Stats / Pct, balayage bleu/vert PERMANENT (.active)
 *   - barre toujours visible (file vide → "Aucune tâche", 0 %)
 *   - ETA agrégée via WamaEta (si un élément eta existe)
 *   - event `media:processed` quand une tâche se termine (rafraîchit le filemanager)
 *   - onData(payload) optionnel après chaque tick (ex. activer un bouton download-all)
 * ======================================================================== */
(function (global) {
    'use strict';

    function startBar(opts) {
        opts = opts || {};
        var url = opts.url;
        var bar = document.getElementById(opts.bar || 'globalProgressBar');
        if (!url || !bar) return;

        var stats    = document.getElementById(opts.stats || 'globalProgressStats');
        var pct      = document.getElementById(opts.pct   || 'globalProgressPct');
        var statusEl = document.getElementById(opts.status || 'globalStatus');
        var etaId    = opts.eta || 'globalEta';
        var interval = opts.interval || 1500;
        var dataKey  = opts.dataKey || null;
        var onData   = (typeof opts.onData === 'function') ? opts.onData : null;
        var lastDone = -1;

        // Barre toujours visible (homogène) : neutralise un éventuel opacity:0 inline.
        if (statusEl) { statusEl.style.opacity = '1'; statusEl.style.pointerEvents = ''; }

        function tick() {
            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.json(); })
                .then(function (raw) {
                    // Endpoint imbriqué (multi-domaine) : on isole le sous-objet du domaine.
                    var d = dataKey ? (raw[dataKey] || {}) : raw;

                    // Tolérance aux variantes de nommage : done|success|completed, failed|failure|error.
                    var total   = d.total || 0;
                    var done    = (d.done != null ? d.done
                                 : d.success != null ? d.success
                                 : d.completed != null ? d.completed : 0) || 0;
                    var running = d.running || 0;
                    var failed  = (d.failed != null ? d.failed
                                 : d.failure != null ? d.failure
                                 : d.error != null ? d.error : 0) || 0;
                    var p       = (d.overall_progress != null ? d.overall_progress
                                 : (total ? Math.round(done / total * 100) : 0)) || 0;

                    bar.style.width = p + '%';
                    bar.classList.add('active');  // balayage coloré permanent ; l'état (%) reste toujours affiché

                    if (stats) {
                        stats.textContent = total
                            ? (done + '/' + total + ' terminé · ' + running
                               + ' en cours · ' + failed + ' échoué')
                            : 'Aucune tâche';
                    }
                    if (pct) pct.textContent = total ? p + '%' : '';

                    // Source UNIQUE des compteurs de file (l'inspecteur les LIT, ne recompte pas).
                    window.WamaQueueStats = { total: total, done: done, running: running, failed: failed };

                    if (window.WamaEta) {
                        var etaEl = document.getElementById(etaId);
                        if (etaEl) window.WamaEta.render(etaEl, window.WamaEta.aggregateAll());
                    }

                    if (lastDone >= 0 && done > lastDone) {
                        document.dispatchEvent(new CustomEvent('media:processed'));
                    }
                    lastDone = done;

                    if (onData) { try { onData(d); } catch (e) { /* callback app : ignorer */ } }
                })
                .catch(function () { /* réseau : ignorer ce tick */ });
        }

        tick();
        setInterval(tick, interval);
    }

    global.WamaGlobalProgress = { init: startBar };

    // Auto-init de la barre par défaut (apps mono-domaine) si l'URL est posée.
    function autoInit() {
        if (window.WAMA_GLOBAL_PROGRESS_URL) startBar({ url: window.WAMA_GLOBAL_PROGRESS_URL });
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoInit);
    } else {
        autoInit();
    }
})(window);
