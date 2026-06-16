/*
 * wama-app-base.js — Plomberie JS commune aux apps WAMA (file d'attente / cards).
 *
 * Extrait du Transcriber (app de référence) pour éliminer la duplication inter-apps :
 *   - helpers sans état : escapeHtml, getUrl, csrfHeaders, csrfFetch, wordCount
 *   - WamaApp.Poller    : boucle de polling de progression résiliente (par id)
 *   - WamaApp.emptyState: insertion/retrait d'un état vide dans un conteneur de file
 *
 * Aucune dépendance. Expose un namespace global `WamaApp`.
 * Adoption : charger ce script AVANT l'index.js de l'app, puis déléguer.
 */
(function (global) {
  'use strict';

  // ── Helpers sans état ────────────────────────────────────────────────
  function escapeHtml(str) {
    return (str || '').replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
    });
  }

  // Remplace le segment id factice « /0/ » d'un template d'URL Django par l'id réel.
  function getUrl(template, id) {
    return (template || '').replace('/0/', '/' + id + '/');
  }

  function csrfHeaders(csrfToken, extra) {
    return Object.assign({}, extra || {}, { 'X-CSRFToken': csrfToken });
  }

  // fetch() avec en-tête CSRF injecté (les autres options sont transmises telles quelles).
  function csrfFetch(url, csrfToken, opts) {
    opts = opts || {};
    opts.headers = csrfHeaders(csrfToken, opts.headers);
    return fetch(url, opts);
  }

  function wordCount(text) {
    if (!text || !text.trim()) return 0;
    return text.trim().split(/\s+/).filter(Boolean).length;
  }

  // ── Poller : boucle de progression résiliente, indexée par id ────────
  // cfg = { urlTemplate, onData(id,data), interval=1200, maxFails=10, onGiveUp(id) }
  // Une exception dans onData ne tue PAS la boucle ; une erreur réseau transitoire
  // n'arrête le poller qu'après `maxFails` échecs consécutifs.
  function Poller(cfg) {
    cfg = cfg || {};
    this.urlTemplate = cfg.urlTemplate;
    this.onData = cfg.onData || function () {};
    this.onGiveUp = cfg.onGiveUp || function () {};
    this.interval = cfg.interval || 1200;
    this.maxFails = cfg.maxFails || 10;
    this._pollers = new Map();
  }

  Poller.prototype.has = function (id) { return this._pollers.has(id); };

  Poller.prototype.start = function (id) {
    if (this._pollers.has(id)) return;
    const self = this;
    let fails = 0;
    const handle = setInterval(function () {
      fetch(getUrl(self.urlTemplate, id))
        .then(function (r) { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
        .then(function (data) {
          fails = 0;
          try { self.onData(id, data); }
          catch (e) { console.error('[WamaApp.Poller] onData', id, e); }
        })
        .catch(function (err) {
          fails++;
          console.warn('[WamaApp.Poller] poll', id, 'échec', fails, err);
          if (fails >= self.maxFails) { self.stop(id); self.onGiveUp(id); }
        });
    }, this.interval);
    this._pollers.set(id, handle);
  };

  Poller.prototype.stop = function (id) {
    const handle = this._pollers.get(id);
    if (handle) { clearInterval(handle); this._pollers.delete(id); }
  };

  Poller.prototype.stopAll = function () {
    this._pollers.forEach(function (h) { clearInterval(h); });
    this._pollers.clear();
  };

  // ── État vide d'un conteneur de file ─────────────────────────────────
  // cfg = { container, cardSelector='.synthesis-card', emptyClass='empty-queue', html }
  function emptyState(cfg) {
    cfg = cfg || {};
    const container = cfg.container;
    const cardSelector = cfg.cardSelector || '.synthesis-card';
    const emptyClass = cfg.emptyClass || 'empty-queue';
    return {
      remove: function () {
        if (!container) return;
        const el = container.querySelector('.' + emptyClass);
        if (el) el.remove();
      },
      insertIfNeeded: function () {
        if (!container) return;
        const hasCards = container.querySelectorAll(cardSelector).length > 0;
        if (!hasCards && !container.querySelector('.' + emptyClass)) {
          const div = document.createElement('div');
          div.className = 'text-center py-5 ' + emptyClass;
          div.innerHTML = cfg.html || '<p class="text-white-50">Aucun élément</p>';
          container.appendChild(div);
        }
      },
    };
  }

  global.WamaApp = {
    escapeHtml: escapeHtml,
    getUrl: getUrl,
    csrfHeaders: csrfHeaders,
    csrfFetch: csrfFetch,
    wordCount: wordCount,
    Poller: Poller,
    emptyState: emptyState,
  };
})(window);
