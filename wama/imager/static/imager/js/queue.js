/**
 * Imager — file de génération (P1 fondation) : polling → refreshCard via l'endpoint
 * card_html (partial serveur _generation_card = SOURCE UNIQUE du markup).
 * Remplace le repaint DOM manuel + le location.reload() au succès de l'ancien index.js.
 *
 * Contrats :
 *   .imager-card[data-id][data-status]  — cards des deux files (image + vidéo)
 *   WamaCycleButton (brique globale)    — ▶/↻ → endpoints start/restart existants,
 *                                         ⏹ → force_reset (revoke SIGTERM + FAILURE)
 *   IMAGER_CONFIG.urls.{start,restart,forceReset,progress} (gabarits avec '0'),
 *   IMAGER_CARD.urls.cardHtml, IMAGER_CONFIG.csrfToken
 */
(function () {
    'use strict';

    const POLL_MS = 3000;

    function cfg() { return window.IMAGER_CONFIG || { urls: {} }; }
    function u(tpl, id) { return (tpl || '').replace('0', id); }

    function toast(msg, type) {
        if (window.WamaApp && WamaApp.toast) WamaApp.toast(msg, type || 'info');
    }

    function cardEl(id) {
        return document.querySelector('.imager-card[data-id="' + id + '"]');
    }

    // ── Rafraîchissement d'UNE card depuis le serveur (source unique du markup) ──
    function refreshCard(id) {
        const tpl = (window.IMAGER_CARD && IMAGER_CARD.urls.cardHtml) || '';
        if (!tpl) return Promise.resolve();
        return fetch(u(tpl, id))
            .then(r => r.ok ? r.json() : Promise.reject())
            .then(data => {
                const el = cardEl(id);
                if (el && data.html) el.outerHTML = data.html;
            })
            .catch(() => {});
    }
    window.imagerRefreshCard = refreshCard;   // réutilisable (actions, modales)

    // ── Polling : cards non terminales → progress (JSON léger) ; tout changement → refreshCard ──
    function tick() {
        document.querySelectorAll('.imager-card[data-status="RUNNING"], .imager-card[data-status="PENDING"]')
            .forEach(function (el) {
                const id = el.dataset.id;
                fetch(u(cfg().urls.progress, id))
                    .then(r => r.ok ? r.json() : Promise.reject())
                    .then(function (p) {
                        const status = p.status || el.dataset.status;
                        const prog = String(p.progress != null ? p.progress : '');
                        if (status !== el.dataset.status || prog !== el.dataset.lastProgress) {
                            el.dataset.lastProgress = prog;
                            refreshCard(id);
                        }
                    })
                    .catch(() => {});
            });
    }

    // ── Actions du bouton de cycle (start/restart → endpoints existants, stop → force_reset) ──
    function post(url) {
        return fetch(url, { method: 'POST', headers: { 'X-CSRFToken': cfg().csrfToken } })
            .then(r => r.json().catch(() => ({})).then(j => ({ ok: r.ok, j: j })));
    }

    function wireCycle(rootId) {
        const root = document.getElementById(rootId);
        if (!root || !window.WamaCycleButton) return;
        WamaCycleButton.wire(root, {
            start: function (id, btn) {
                const action = btn.getAttribute('data-cycle-action');   // 'start' | 'restart'
                const tpl = action === 'restart' ? cfg().urls.restart : cfg().urls.start;
                post(u(tpl, id)).then(function (res) {
                    if (!res.ok || res.j.error) toast(res.j.error || 'Lancement impossible', 'danger');
                    refreshCard(id);
                });
            },
            stop: function (id) {
                post(u(cfg().urls.forceReset, id)).then(function () { refreshCard(id); });
            },
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        wireCycle('generationsQueue');
        wireCycle('videoGenerationsQueue');
        setInterval(tick, POLL_MS);
    });
})();
