/**
 * Imager — file de génération (P1 fondation) : polling → refreshCard via l'endpoint
 * card_html (partial serveur _generation_card = SOURCE UNIQUE du markup).
 * Remplace le repaint DOM manuel + le location.reload() au succès de l'ancien index.js.
 *
 * Tout ce qui est générique vient de wama-app-base.js (brique GLOBALE, jamais réécrite) :
 * WamaApp.Poller (boucle résiliente par id), WamaApp.getUrl, WamaApp.csrfFetch, WamaApp.toast.
 *
 * Contrats :
 *   .imager-card[data-id][data-status]  — cards des deux files (image + vidéo)
 *   WamaCycleButton (brique globale)    — ▶/↻ → endpoints start/restart existants,
 *                                         ⏹ → force_reset (revoke SIGTERM + FAILURE)
 *   IMAGER_CONFIG.urls.{start,restart,forceReset,progress} (gabarits avec /0/),
 *   IMAGER_CARD.urls.cardHtml, IMAGER_CONFIG.csrfToken
 */
(function () {
    'use strict';

    const POLL_MS = 3000;
    const TERMINAL = ['SUCCESS', 'FAILURE', 'CANCELLED'];

    function cfg() { return window.IMAGER_CONFIG || { urls: {} }; }
    function cardEl(id) { return document.querySelector('.imager-card[data-id="' + id + '"]'); }

    // ── Rafraîchissement d'UNE card depuis le serveur (source unique du markup) ──
    function refreshCard(id) {
        const tpl = (window.IMAGER_CARD && IMAGER_CARD.urls.cardHtml) || '';
        if (!tpl) return Promise.resolve();
        return fetch(WamaApp.getUrl(tpl, id))
            .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
            .then(function (data) {
                const el = cardEl(id);
                if (el && data.html) el.outerHTML = data.html;
                sync();          // la card remplacée peut avoir changé d'état
            })
            .catch(() => {});
    }
    window.imagerRefreshCard = refreshCard;   // réutilisable (actions, modales)

    // ── Polling : brique commune, un poller par card non terminale ──
    const poller = new WamaApp.Poller({
        urlTemplate: cfg().urls.progress,
        interval: POLL_MS,
        onData: function (id, data) {
            const el = cardEl(id);
            if (!el) { poller.stop(id); return; }
            const status = (data.status || el.dataset.status || '').toUpperCase();
            const prog = String(data.progress != null ? data.progress : '');
            if (status !== el.dataset.status || prog !== el.dataset.lastProgress) {
                el.dataset.lastProgress = prog;
                refreshCard(id);
            }
            if (TERMINAL.indexOf(status) !== -1) poller.stop(id);
        },
    });

    // Aligne l'ensemble des pollers sur le DOM (Poller.has garde de tout doublon).
    function sync() {
        document.querySelectorAll('.imager-card[data-status]').forEach(function (el) {
            const id = el.dataset.id;
            if (TERMINAL.indexOf((el.dataset.status || '').toUpperCase()) === -1) poller.start(id);
            else poller.stop(id);
        });
    }

    // ── Actions du bouton de cycle (start/restart → endpoints existants, stop → force_reset) ──
    function post(url) {
        return WamaApp.csrfFetch(url, cfg().csrfToken, { method: 'POST' })
            .then(r => r.json().catch(() => ({})).then(j => ({ ok: r.ok, j: j })));
    }

    function wireCycle(rootId) {
        const root = document.getElementById(rootId);
        if (!root || !window.WamaCycleButton) return;
        WamaCycleButton.wire(root, {
            start: function (id, btn) {
                const action = btn.getAttribute('data-cycle-action');   // 'start' | 'restart'
                const tpl = action === 'restart' ? cfg().urls.restart : cfg().urls.start;
                post(WamaApp.getUrl(tpl, id)).then(function (res) {
                    if (!res.ok || res.j.error) WamaApp.toast(res.j.error || 'Lancement impossible', 'error');
                    refreshCard(id);
                });
            },
            stop: function (id) {
                post(WamaApp.getUrl(cfg().urls.forceReset, id)).then(function () { refreshCard(id); });
            },
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        wireCycle('generationsQueue');
        wireCycle('videoGenerationsQueue');
        sync();
    });
})();
