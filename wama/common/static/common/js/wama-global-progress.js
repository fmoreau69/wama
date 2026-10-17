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
 *   WamaGlobalProgress.init({ url, dataKey, bar, stats, pct, eta, status, interval, download, onData })
 *
 * L'endpoint renvoie un JSON tolérant : { total, done|success|completed,
 *   running, failed|failure|error, overall_progress? }  (overall_progress dérivé si absent).
 * dataKey : extrait data[dataKey] pour les endpoints imbriqués (ex. {image:{…}, video:{…}}).
 *
 * Plusieurs barres sur le MÊME endpoint partagent UN appel (une boucle `WamaApp.Poller` par
 * URL : tour suivant après la réponse, pause en onglet caché).
 *
 * Comportement commun à TOUTES les barres :
 *   - met à jour #<…>ProgressBar / Stats / Pct, balayage bleu/vert PERMANENT (.active)
 *   - barre toujours visible (file vide → "Aucune tâche", 0 %)
 *   - ETA agrégée via WamaEta (si un élément eta existe)
 *   - event `media:processed` quand une tâche se termine (rafraîchit le filemanager)
 *   - le ⬇ « Télécharger tout » de la MÊME file (`data-queue-download`, rendu par la brique
 *     `_download_button.html`) est prêt dès qu'un élément est terminé (`done > 0`), désactivé
 *     sinon (2026-10-17) — le compte vient du SERVEUR, donc un filtre de statut qui masque les
 *     cards réussies ne trompe pas le bouton. Barre par défaut : les ⬇ que nulle autre barre ne
 *     réclame ; barre d'un domaine : `init({ …, download: '<id du ⬇ de sa file>' })`. Remplace
 *     quatre bascules écrites dans les apps (DOM des cards ×3, `onData` de l'audio).
 *   - onData(payload) optionnel après chaque tick
 * ======================================================================== */
(function (global) {
    'use strict';

    // Les ⬇ réclamés par une barre de DOMAINE ; la barre par défaut prend les autres.
    var claimedDownloads = [];

    function downloadTargets(own) {
        if (own) {
            var el = document.getElementById(own);
            return el ? [el] : [];
        }
        return Array.prototype.filter.call(
            document.querySelectorAll('[data-queue-download]'),
            function (el) { return claimedDownloads.indexOf(el.id) < 0; });
    }

    function setDownloadReady(el, ready) {
        if (el.tagName === 'BUTTON') el.disabled = !ready;
        el.classList.toggle('disabled', !ready);
        if (ready) {
            el.removeAttribute('aria-disabled');
            el.removeAttribute('tabindex');
        } else {
            el.setAttribute('aria-disabled', 'true');
            el.setAttribute('tabindex', '-1');
        }
    }

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
        var download = opts.download || null;
        if (download) claimedDownloads.push(download);
        var lastDone = -1;

        // Barre toujours visible (homogène) : neutralise un éventuel opacity:0 inline.
        if (statusEl) { statusEl.style.opacity = '1'; statusEl.style.pointerEvents = ''; }

        function render(raw) {
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
            // ⚠ L'événement fait partie du contrat (2026-09-02) : au chargement,
            // l'inspecteur rend son résumé « File · N éléments » AVANT le premier
            // poll — WamaQueueStats est alors indéfini et la section restait cachée
            // jusqu'à la première désélection (constat Fabien sur converter_01, vrai
            // sur les 10 apps : même course, même code). Le poller ANNONCE donc ses
            // stats ; l'inspecteur ré-affiche si rien n'est sélectionné.
            var premiereFois = !window.WamaQueueStats;
            window.WamaQueueStats = { total: total, done: done, running: running, failed: failed };
            if (premiereFois) {
                document.dispatchEvent(new CustomEvent('wama:queue-stats'));
            }

            if (window.WamaEta) {
                var etaEl = document.getElementById(etaId);
                if (etaEl) window.WamaEta.render(etaEl, window.WamaEta.aggregateAll());
            }

            if (lastDone >= 0 && done > lastDone) {
                document.dispatchEvent(new CustomEvent('media:processed'));
            }
            lastDone = done;

            // Lu au TOUR, pas à l'init : toutes les barres de la page sont alors déclarées, et
            // un ⬇ ré-rendu (barre de file rechargée) est retrouvé.
            downloadTargets(download).forEach(function (el) { setDownloadReady(el, done > 0); });

            if (onData) { try { onData(d); } catch (e) { /* callback app : ignorer */ } }
        }

        follow(url, interval, render);
    }

    // UNE boucle par endpoint, quel que soit le nombre de barres qui le lisent : l'Imager
    // (barres images + vidéos sur `global-progress/`) faisait DEUX requêtes identiques toutes
    // les 1,5 s (mesuré le 2026-10-13, toujours par paires dans le journal d'accès). La boucle
    // est `WamaApp.Poller` — réponse attendue avant le tour suivant, pause en onglet caché.
    var loops = {};
    function follow(url, interval, render) {
        if (loops[url]) { loops[url].renders.push(render); return; }
        var loop = loops[url] = { renders: [render] };
        var poller = new WamaApp.Poller({
            urlTemplate: function () { return url; },
            interval: interval,
            immediate: true,
            maxFails: Infinity,                   // une barre de file ne renonce jamais
            onError: function () { /* réseau : ignorer ce tour */ },
            onData: function (id, raw) {
                loop.renders.forEach(function (r) {
                    try { r(raw || {}); } catch (e) { console.error('[WamaGlobalProgress]', e); }
                });
            },
        });
        poller.start('global');
    }

    global.WamaGlobalProgress = { init: startBar, setDownloadReady: setDownloadReady };

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
