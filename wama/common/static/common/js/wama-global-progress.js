/* ===========================================================================
 * WAMA — Barre de progression globale commune (toujours visible)
 * ===========================================================================
 * Composant inter-apps. Pilote le partial common/_global_progress.html.
 *
 * Config requise sur la page :
 *   window.WAMA_GLOBAL_PROGRESS_URL = "<endpoint>"
 * L'endpoint renvoie un JSON : { total, done, running, overall_progress }.
 *
 * Comportement :
 *   - met à jour #globalProgressBar / #globalProgressStats / #globalProgressPct
 *   - la barre reste TOUJOURS visible (file vide → "Aucune tâche", 0 %)
 *   - dès qu'une tâche vient de se terminer (done augmente), notifie le
 *     filemanager via l'event `media:processed` → rafraîchit l'arborescence.
 * ======================================================================== */
(function () {
    'use strict';

    function init() {
        var url = window.WAMA_GLOBAL_PROGRESS_URL;
        var bar = document.getElementById('globalProgressBar');
        if (!url || !bar) return;

        var stats = document.getElementById('globalProgressStats');
        var pct   = document.getElementById('globalProgressPct');
        var lastDone = -1;

        function tick() {
            fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var total   = d.total || 0;
                    var done    = d.done || 0;
                    var running = d.running || 0;
                    var p       = d.overall_progress || 0;

                    bar.style.width = p + '%';
                    bar.classList.toggle('active', running > 0);

                    if (stats) {
                        stats.textContent = total
                            ? (done + '/' + total + ' terminé'
                               + (running ? ' · ' + running + ' en cours' : ''))
                            : 'Aucune tâche';
                    }
                    if (pct) pct.textContent = total ? p + '%' : '';

                    // ETA globale agrégée (alimentée par les polls par-item via WamaEta)
                    if (window.WamaEta) {
                        var etaEl = document.getElementById('globalEta');
                        if (etaEl) window.WamaEta.render(etaEl, window.WamaEta.aggregateAll());
                    }

                    // Une tâche vient de se terminer → rafraîchir le filemanager
                    if (lastDone >= 0 && done > lastDone) {
                        document.dispatchEvent(new CustomEvent('media:processed'));
                    }
                    lastDone = done;
                })
                .catch(function () { /* réseau : ignorer ce tick */ });
        }

        tick();
        setInterval(tick, 1500);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
