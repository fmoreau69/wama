/* ===========================================================================
 * WAMA — Barre de progression globale commune (toujours visible)
 * ===========================================================================
 * Composant inter-apps. Pilote le partial common/_global_progress.html.
 *
 * DÉMARRAGE SEUL (2026-11-01, ROUTE §11 #42 ②) : une barre rendue par le partial avec `app`
 * porte son adresse (`data-progress-url`), sa clé de domaine (`data-progress-key`) et sa file
 * (`data-progress-queue`) — lues de la déclaration de l'app (`queue_context`). Chaque barre de la
 * page démarre d'elle-même, une par domaine : aucune page ne l'initialise plus, et aucune ne
 * recopie la barre d'un second domaine en HTML (l'imager et l'enhancer le faisaient).
 *
 * Forme d'avant, gardée pour les pages qui n'ont pas été régénérées : une barre sans adresse
 * démarre sur `window.WAMA_GLOBAL_PROGRESS_URL`, et `init({ url, dataKey, bar, stats, pct, eta,
 * status, interval, download, onData })` reste l'appel de bas niveau (`root` : l'élément de la
 * barre, ses parties se trouvent alors par leurs classes `wama-gp-*`).
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

    // Les barres d'actions de file que CETTE barre de progression renseigne : celle qui contient
    // son ⬇ réclamé (barre de domaine), sinon toutes celles dont le ⬇ n'est réclamé par personne.
    function actionBars(own) {
        if (own) {
            var el = document.getElementById(own);
            var box = el && el.closest('.wama-queue-actions');
            return box ? [box] : [];
        }
        return Array.prototype.filter.call(
            document.querySelectorAll('.wama-queue-actions'),
            function (box) {
                return !claimedDownloads.some(function (id) {
                    var el = document.getElementById(id);
                    return el && box.contains(el);
                });
            });
    }

    // Les entrées du menu ▾ de « tout lancer » / « tout effacer » (`data-queue-scope`, 2026-10-29) :
    // grisées quand leur périmètre est vide, avec leur nombre — compté par le SERVEUR, comme le ⬇.
    function setScopes(own, counts) {
        actionBars(own).forEach(function (box) {
            box.querySelectorAll('[data-queue-scope]').forEach(function (item) {
                var n = counts[item.getAttribute('data-queue-scope')];
                if (n == null) return;                       // compteur inconnu : ne rien deviner
                item.disabled = !n;
                var count = item.querySelector('.wama-scope-count');
                if (count) count.textContent = n ? '(' + n + ')' : '';
            });
        });
    }

    // Les ids des éléments de la file `queueId` (les cards portent `data-id`) — l'ETA d'une barre
    // de domaine est celle de SES cards, pas de toutes celles de la page.
    function queueIds(queueId) {
        var queue = queueId && document.getElementById(queueId);
        if (!queue) return null;
        var ids = [];
        Array.prototype.forEach.call(queue.querySelectorAll('[data-id]'), function (el) {
            if (ids.indexOf(el.dataset.id) < 0) ids.push(el.dataset.id);
        });
        return ids;
    }

    function startBar(opts) {
        opts = opts || {};
        var url = opts.url;
        var root = opts.root || null;
        function part(id, cls) {
            return root ? root.querySelector('.' + cls) : document.getElementById(id);
        }
        var bar = part(opts.bar || 'globalProgressBar', 'wama-gp-bar');
        if (!url || !bar) return;

        var stats    = part(opts.stats || 'globalProgressStats', 'wama-gp-stats');
        var pct      = part(opts.pct   || 'globalProgressPct', 'wama-gp-pct');
        var statusEl = root || document.getElementById(opts.status || 'globalStatus');
        var etaEl    = part(opts.eta || 'globalEta', 'wama-gp-eta');
        var interval = opts.interval || 1500;
        var dataKey  = opts.dataKey || null;
        var domain   = opts.domain || dataKey || null;
        var queueId  = opts.queue || null;
        var onData   = (typeof opts.onData === 'function') ? opts.onData : null;
        var download = opts.download || (queueId ? queueId + '-download-all' : null);
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
            // Sur une page à plusieurs domaines, la file que l'utilisateur regarde est celle de
            // l'onglet montré : seule sa barre renseigne les compteurs (les deux barres de
            // l'imager les écrivaient à tour de rôle).
            var pane = statusEl && statusEl.closest ? statusEl.closest('.tab-pane[data-domain]') : null;
            if (!pane || pane.classList.contains('active')) {
                var firstTime = !window.WamaQueueStats;
                window.WamaQueueStats = { total: total, done: done, running: running, failed: failed };
                if (firstTime) {
                    document.dispatchEvent(new CustomEvent('wama:queue-stats'));
                }
            }
            // Le compte d'un domaine, pour son onglet (`WamaModes.domainTabs`).
            if (domain) {
                document.dispatchEvent(new CustomEvent('wama:domain-stats',
                    { detail: { domain: domain, total: total } }));
            }

            if (window.WamaEta && etaEl) {
                var ids = queueIds(queueId);
                window.WamaEta.render(etaEl, ids ? window.WamaEta.aggregate(ids)
                                                 : window.WamaEta.aggregateAll());
            }

            if (lastDone >= 0 && done > lastDone) {
                document.dispatchEvent(new CustomEvent('media:processed'));
            }
            lastDone = done;

            // Lu au TOUR, pas à l'init : toutes les barres de la page sont alors déclarées, et
            // un ⬇ ré-rendu (barre de file rechargée) est retrouvé.
            downloadTargets(download).forEach(function (el) { setDownloadReady(el, done > 0); });
            var pending = d.pending || 0;
            setScopes(download, {
                pending: pending, failure: failed, success: done,
                unfinished: d.unfinished != null ? d.unfinished : pending + failed,
                relaunchable: d.relaunchable != null ? d.relaunchable : total - running,
            });

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

    // Chaque barre de la page démarre sur l'adresse qu'elle porte ; une barre sans adresse (page
    // d'avant le 2026-11-01) sur `WAMA_GLOBAL_PROGRESS_URL`.
    function autoInit() {
        var started = false;
        Array.prototype.forEach.call(
            document.querySelectorAll('[data-wama-brick="global_progress"][data-progress-url]'),
            function (el) {
                started = true;
                startBar({ root: el, url: el.dataset.progressUrl,
                           dataKey: el.dataset.progressKey || null,
                           domain: el.dataset.progressDomain || null,
                           queue: el.dataset.progressQueue || null });
            });
        if (!started && window.WAMA_GLOBAL_PROGRESS_URL) {
            startBar({ url: window.WAMA_GLOBAL_PROGRESS_URL });
        }
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoInit);
    } else {
        autoInit();
    }
})(window);
