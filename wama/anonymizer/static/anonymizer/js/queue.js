/**
 * Anonymizer — cycle de vie de la FILE (port schéma-driven 2026-08-03).
 *
 * Briques communes consommées (jamais re-implémentées) :
 *   WamaCycleButton (▶/⏹/↻, délégué UNE fois sur le conteneur) · WamaEta (ETA seedée)
 *   WamaParams (modale batch, context:'batch') · WamaInspector.initFromSchema (volet droit)
 *   queue-actions.js (brique GLOBALE de duplication — ne pas re-binder ici)
 *
 * Card = partial serveur UNIQUE (_media_card.html) rendu par l'endpoint card_html :
 * refreshCard() remplace le nœud sur TRANSITION d'état ; entre deux, seule la barre
 * de progression est mise à jour (léger).
 */
(function () {
  'use strict';

  const cfg = window.WAMA_ANON || {};
  const getUrl = (tpl, id) => (tpl || '').replace('/0/', '/' + id + '/');
  const queue = document.getElementById('anonymizer-queue');
  if (!queue) return;

  function csrfHeaders() {
    return { 'X-CSRFToken': cfg.csrfToken };
  }

  // ── Card partial serveur ────────────────────────────────────────────────
  async function refreshCard(id) {
    try {
      const resp = await fetch(getUrl(cfg.cardHtmlUrlTemplate, id));
      if (!resp.ok) return null;
      const tpl = document.createElement('template');
      tpl.innerHTML = (await resp.text()).trim();
      const fresh = tpl.content.firstElementChild;
      const existing = queue.querySelector('.anon-card[data-id="' + id + '"]');
      if (fresh && existing) {
        existing.replaceWith(fresh);
        // Re-bind par card : l'aperçu commun s'attache par forEach (leçon describer)
        if (typeof window.initMediaPreview === 'function') window.initMediaPreview();
        if (window.WamaCycleButton) WamaCycleButton.refresh(fresh);
      }
      return fresh;
    } catch (e) {
      return null;
    }
  }

  // ── Polling par card en cours ───────────────────────────────────────────
  const timers = {};

  function stopPolling(id) {
    if (timers[id]) {
      clearInterval(timers[id]);
      delete timers[id];
    }
  }

  function startPolling(id) {
    if (timers[id]) return;
    timers[id] = setInterval(async () => {
      let d;
      try {
        d = await (await fetch(cfg.progressUrl + '?media_id=' + id)).json();
      } catch (e) {
        return;
      }
      const card = queue.querySelector('.anon-card[data-id="' + id + '"]');
      if (!card) {
        stopPolling(id);
        return;
      }
      const prev = card.dataset.status;
      if (window.WamaEta) {
        WamaEta.render(card.querySelector('.wama-eta'), WamaEta.update(id, {
          progress: d.progress,
          status: d.status,
          seedSeconds: d.estimated_seconds,
          modelLoaded: true,
        }));
      }
      if (d.status && d.status !== prev) {
        // Transition d'état → re-render serveur (source unique du markup)
        await refreshCard(id);
        if (d.status !== 'RUNNING' && d.status !== 'PENDING') stopPolling(id);
        return;
      }
      const fill = card.querySelector('.wama-progress-fill');
      if (fill) fill.style.width = (d.progress || 0) + '%';
      const txt = card.querySelector('.progress-text');
      if (txt) txt.textContent = (d.progress || 0) + '%';
    }, 2500);
  }

  function pollRunningCards() {
    queue.querySelectorAll('.anon-card[data-status="RUNNING"]').forEach(c =>
      startPolling(parseInt(c.dataset.id, 10)));
  }

  function pollAllCards() {
    queue.querySelectorAll('.anon-card[data-id]').forEach(c => {
      if (c.dataset.status !== 'SUCCESS') startPolling(parseInt(c.dataset.id, 10));
    });
  }

  // ── Cycle ▶/⏹/↻ — brique commune, un seul listener sur la file ─────────
  if (window.WamaCycleButton) {
    WamaCycleButton.wire(queue, {
      start: async (id) => {
        try {
          const d = await (await fetch(getUrl(cfg.startUrlTemplate, id), {
            method: 'POST', headers: csrfHeaders(),
          })).json();
          if (d.error) {
            if (window.WamaApp) WamaApp.toast(d.error, 'warning');
            return;
          }
          if (window.WamaEta) WamaEta.reset(id);
          await refreshCard(id);
          startPolling(parseInt(id, 10));
        } catch (e) { /* réseau */ }
      },
      stop: async (id) => {
        try {
          await fetch(getUrl(cfg.stopUrlTemplate, id), { method: 'POST', headers: csrfHeaders() });
          stopPolling(parseInt(id, 10));
          await refreshCard(id);
        } catch (e) { /* réseau */ }
      },
    });
  }

  // 🗑 RÉSIDU de suppression — la brique commune (queue-actions.js) porte désormais la
  // confirmation, le POST vers `data-delete-url`, le retrait de la card, le lot vidé et le
  // signal au gestionnaire de fichiers. Portage 2026-08-23, ATOMIQUE avec le gabarit.
  //
  // ⚠ Ce portage a demandé une route AU FORMAT COMMUN côté serveur (`anonymizer:delete`) :
  // l'ancienne (`clear_media/` + `media_id` en champ de formulaire) ne pouvait pas être servie
  // par la brique, qui poste un corps JSON vide. L'appartenance à un LOT était en outre devinée
  // ICI en inspectant le DOM (`card.closest('.batch-group')`) faute que le serveur la dise ; la
  // nouvelle vue répond `batch_changed`, et c'est la brique qui tranche — comme pour les 9
  // autres apps.
  WamaQueueActions.onDeleted(function (id) {
    stopPolling(parseInt(id, 10));
    const badge = document.getElementById('queueCount');
    if (badge) badge.textContent = Math.max(0, parseInt(badge.textContent || '1', 10) - 1);
  });

  // ── Batch : lancer / paramètres (modale commune context:'batch') ────────
  let batchParamsRendered = false;

  function openBatchModal(batchId) {
    const modal = document.getElementById('batchSettingsModal');
    if (!modal || !window.WamaParams) return;
    if (!batchParamsRendered) {
      WamaParams.render(document.getElementById('anonBatchParams'),
                        window.WAMA_ANONYMIZER_SCHEMA || [],
                        // mêmes sections que la modale item (groupes déclarés dans params.py)
                        { context: 'batch', values: {}, groups: window.WAMA_ANONYMIZER_GROUPS || [] });
      batchParamsRendered = true;
    }
    modal.dataset.batchId = batchId;
    const idBadge = document.getElementById('batchSettingsBatchId');
    if (idBadge) idBadge.textContent = '#' + batchId;
    new bootstrap.Modal(modal).show();
  }

  async function saveBatchSettings(andStart) {
    const modal = document.getElementById('batchSettingsModal');
    const batchId = modal && modal.dataset.batchId;
    if (!batchId) return;
    const vals = WamaParams.read(document.getElementById('anonBatchParams'));
    try {
      const d = await (await fetch(getUrl(cfg.batchUpdateUrlTemplate, batchId), {
        method: 'POST',
        headers: Object.assign({ 'Content-Type': 'application/json' }, csrfHeaders()),
        body: JSON.stringify(vals),
      })).json();
      if (!d.success) {
        if (window.WamaApp) WamaApp.toast(d.error || 'Application impossible', 'error');
        return;
      }
    } catch (e) {
      return;
    }
    const inst = bootstrap.Modal.getInstance(modal);
    if (inst) inst.hide();
    if (andStart) {
      await startBatch(batchId);
    }
    location.reload(); // chips/cards re-rendues avec les nouveaux réglages
  }

  async function startBatch(batchId) {
    try {
      const d = await (await fetch(getUrl(cfg.batchStartUrlTemplate, batchId), {
        method: 'POST', headers: csrfHeaders(),
      })).json();
      (d.started || []).forEach(id => {
        if (window.WamaEta) WamaEta.reset(id);
        refreshCard(id).then(() => startPolling(id));
      });
    } catch (e) { /* réseau */ }
  }

  document.addEventListener('click', function (e) {
    const bs = e.target.closest('.batch-start-btn[data-batch-id]');
    if (bs) {
      startBatch(bs.dataset.batchId);
      return;
    }
    const bset = e.target.closest('.batch-settings-btn[data-batch-id]');
    if (bset) {
      openBatchModal(bset.dataset.batchId);
      return;
    }
    if (e.target.closest('#saveBatchSettingsBtn')) saveBatchSettings(false);
    if (e.target.closest('#saveBatchSettingsAndStartBtn')) saveBatchSettings(true);
  });

  // ── Toolbar commune (Tout lancer / Tout effacer / Tout télécharger) ─────
  const startAllBtn = document.getElementById('anon-start-all-btn');
  if (startAllBtn) {
    startAllBtn.addEventListener('click', async () => {
      try {
        const d = await (await fetch(cfg.startAllUrl, { method: 'POST', headers: csrfHeaders() })).json();
        if (d.error) {
          if (window.WamaApp) WamaApp.toast(d.error, 'warning');
          return;
        }
        if (window.WamaApp) WamaApp.toast('Traitement global lancé', 'success');
        setTimeout(() => location.reload(), 400); // cards re-rendues PENDING → polling au chargement
      } catch (e) { /* réseau */ }
    });
  }
  const clearAllBtn = document.getElementById('anon-clear-all-btn');
  if (clearAllBtn) {
    clearAllBtn.addEventListener('click', async () => {
      if (!confirm('Supprimer tous les médias de la file ?')) return;
      const fd = new FormData();
      fd.append('csrfmiddlewaretoken', cfg.csrfToken);
      try {
        await fetch(cfg.clearAllUrl, { method: 'POST', body: fd });
      } catch (e) { /* réseau */ }
      location.reload();
    });
  }
  const dlAllBtn = document.getElementById('anon-download-all-btn');
  if (dlAllBtn) {
    dlAllBtn.addEventListener('click', () => {
      const f = document.createElement('form');
      f.method = 'POST';
      f.action = cfg.downloadAllUrl;
      f.innerHTML = '<input type="hidden" name="csrfmiddlewaretoken" value="' + cfg.csrfToken + '">';
      document.body.appendChild(f);
      f.submit();
      f.remove();
    });
  }

  // ── Inspecteur (volet droit) — dérivé du SCHÉMA (dom_id.panel = ids legacy) ──
  if (window.WamaInspector && WamaInspector.initFromSchema) {
    window._anonInspector = WamaInspector.initFromSchema({
      queueContainer: queue,
      cardSelector: '.anon-card',
      batchSelector: '.batch-group',
      panelContainer: document.getElementById('global-settings-container'),
      schema: window.WAMA_ANONYMIZER_SCHEMA || [],
      itemLabel: id => "le média #" + id,
      batchLabel: id => "le batch #" + id + " (tous les éléments)",
      saveItem: async (id) => {
        const vals = WamaParams.read(document.getElementById('global-settings-container'));
        const fd = new FormData();
        fd.append('media_id', id);
        Object.keys(vals).forEach(k => fd.append(k, vals[k]));
        fd.append('restart', '0');
        fd.append('csrfmiddlewaretoken', cfg.csrfToken);
        const d = await (await fetch(cfg.settingsSaveUrl, { method: 'POST', body: fd })).json();
        if (d && d.success) refreshCard(id);
      },
      saveBatch: async (bid) => {
        const vals = WamaParams.read(document.getElementById('global-settings-container'));
        await fetch(getUrl(cfg.batchUpdateUrlTemplate, bid), {
          method: 'POST',
          headers: Object.assign({ 'Content-Type': 'application/json' }, csrfHeaders()),
          body: JSON.stringify(vals),
        });
        location.reload();
      },
      renderItemActions: (host, card) => {
        WamaInspector.cloneActions(host, card.querySelector('.btn-group-actions'),
          '<i class="fas fa-crosshairs text-info"></i> Actions — média #' + card.dataset.id);
      },
      renderBatchActions: (host, group) => {
        WamaInspector.cloneActions(host, group.querySelector('.btn-group-actions'),
          '<i class="fas fa-layer-group text-info"></i> Actions — batch #' + group.dataset.batchId);
      },
    });
  }

  // ── Enrichissement ✨ du prompt SAM3 du volet droit (pipeline commune) ──
  if (window.WamaPromptEnrich && document.getElementById('user_setting_sam3_prompt')) {
    WamaPromptEnrich.attach('#user_setting_sam3_prompt', {
      app: 'anonymizer',
      domain: 'detection',
      csrf: cfg.csrfToken,
    });
  }

  pollRunningCards();
  window.AnonQueue = { refreshCard, startPolling, stopPolling, pollAllCards };
})();
