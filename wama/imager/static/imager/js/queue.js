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
    // [data-id] EXIGÉ : la card MÈRE de batch porte aussi .imager-card mais n'a pas d'id
    // d'item (data-status="batch") — sans ce filtre on pollait /progress/undefined/.
    function sync() {
        document.querySelectorAll('.imager-card[data-id][data-status]').forEach(function (el) {
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

    // ── Modale de réglages du BATCH (patron anonymizer/avatarizer) ──
    // Coquille dans le template, CHAMPS générés par WamaParams en contexte 'batch',
    // appliqués aux items non-RUNNING (vue batch_update, coercition par le schéma).
    function openBatchSettings(batchId, domain) {
        const host = document.getElementById('imagerBatchParams');
        const modalEl = document.getElementById('imagerBatchSettingsModal');
        if (!host || !modalEl || !window.WamaParams) return;
        const video = domain === 'video';
        WamaParams.render(host,
            (video ? window.IMAGER_VIDEO_SCHEMA : window.IMAGER_IMAGE_SCHEMA) || [],
            { context: 'batch', values: {},
              groups: (video ? window.IMAGER_VIDEO_GROUPS : window.IMAGER_IMAGE_GROUPS) || [] });
        modalEl.dataset.batchId = batchId;
        const badge = document.getElementById('imagerBatchSettingsId');
        if (badge) badge.textContent = '#' + batchId;
        new bootstrap.Modal(modalEl).show();
    }

    function saveBatchSettings(start) {
        const modalEl = document.getElementById('imagerBatchSettingsModal');
        const id = modalEl && modalEl.dataset.batchId;
        if (!id) return;
        const fd = new FormData();
        const vals = WamaParams.read(document.getElementById('imagerBatchParams'));
        Object.keys(vals).forEach(function (k) { fd.append(k, vals[k]); });
        fd.append('csrfmiddlewaretoken', cfg().csrfToken);
        WamaApp.csrfFetch(WamaApp.getUrl((window.IMAGER_CARD || {}).urls.batchUpdate, id),
                          cfg().csrfToken, { method: 'POST', body: fd })
            .then(r => r.json().catch(() => ({})))
            .then(function (resp) {
                if (!resp.success) { WamaApp.toast(resp.error || 'Application impossible', 'error'); return; }
                bootstrap.Modal.getInstance(modalEl).hide();
                WamaApp.toast((resp.updated || 0) + ' élément(s) mis à jour', 'success');
                if (start) {
                    return post(WamaApp.getUrl((window.IMAGER_CARD || {}).urls.batchStart, id))
                        .then(function () { window.location.reload(); });
                }
                window.location.reload();   // la file entière a changé
            })
            .catch(function () { WamaApp.toast('Erreur réseau', 'error'); });
    }

    document.addEventListener('DOMContentLoaded', function () {
        wireCycle('generationsQueue');
        wireCycle('videoGenerationsQueue');
        sync();

        document.addEventListener('click', function (e) {
            const b = e.target.closest('.batch-settings-btn');
            if (b) {
                const group = b.closest('.batch-group');
                const child = group && group.querySelector('.imager-card[data-domain]');
                openBatchSettings(b.getAttribute('data-batch-id'),
                                  child ? child.dataset.domain : 'image');
                return;
            }
            if (e.target.closest('#imagerSaveBatchSettingsBtn')) saveBatchSettings(false);
            else if (e.target.closest('#imagerSaveBatchSettingsAndStartBtn')) saveBatchSettings(true);
        });
    });
})();
