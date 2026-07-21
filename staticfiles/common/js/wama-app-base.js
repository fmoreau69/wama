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

  // ── Toast non bloquant (généralise le toast composer ; remplace les alert()) ──
  // type ∈ {success, error|danger, info, warning} — mêmes couleurs que les badges Bootstrap.
  function toast(message, type) {
    const colors = { success: '#198754', error: '#dc3545', danger: '#dc3545',
                     info: '#0dcaf0', warning: '#ffc107' };
    const el = document.createElement('div');
    el.className = 'wama-toast';
    el.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:9999;' +
      'background:' + (colors[type] || '#333') + ';color:#fff;padding:10px 16px;' +
      'border-radius:6px;font-size:.9rem;box-shadow:0 4px 12px rgba(0,0,0,.4);max-width:300px;';
    el.textContent = message;
    document.body.appendChild(el);
    setTimeout(function () { el.remove(); }, 3500);
  }

  // ── Import par URL : câble le bloc URL de la carte commune (_new_item_card.html) ──
  // Élimine le handler fetch/CSRF/spinner/erreur dupliqué dans chaque app. L'app
  // déclare la capacité dans son template (show_url=True + url_input_id/url_submit_id)
  // et fournit ici l'endpoint + un hook de succès ; TOUTE la plomberie (POST du
  // champ URL, CSRF, spinner, gestion d'erreur, reset du champ, touche Entrée) est
  // centralisée. No-op silencieux si le bloc URL n'est pas présent sur la page.
  //
  // cfg = {
  //   inputId, buttonId,        // = url_input_id / url_submit_id passés au template
  //   onSubmit(url),            // MODE DÉLÉGUÉ (préféré) : l'app traite l'URL
  //                             //   (ex. la router vers le pipeline batch commun,
  //                             //   WamaBatchImport.ingestText). Peut renvoyer une
  //                             //   Promise. Si fourni, endpoint/fieldName ignorés.
  //   endpoint,                 // MODE POST : URL d'upload de l'app (reçoit le champ)
  //   csrfToken,
  //   fieldName='media_url',    // nom du champ POST portant l'URL
  //   extraFields,              // optionnel : () => ({k:v}) champs additionnels
  //   onSuccess(data),          // MODE POST : ajout de l'item à la file (spéc. app)
  //   onEmpty,                  // optionnel : URL vide (défaut = focus input)
  //   onError(err),             // optionnel ; défaut = toast rouge
  // }
  // Retourne { submit } ou null si le bloc URL est absent.
  function initUrlImport(cfg) {
    cfg = cfg || {};
    const input = document.getElementById(cfg.inputId);
    const btn   = document.getElementById(cfg.buttonId);
    if (!input || !btn) return null;           // capacité URL non déclarée ici
    const field = cfg.fieldName || 'media_url';

    function submit() {
      const url = (input.value || '').trim();
      if (!url) {
        if (typeof cfg.onEmpty === 'function') cfg.onEmpty();
        else input.focus();
        return;
      }
      const original = btn.innerHTML;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span>';

      // Mode délégué : l'app traite l'URL elle-même (ex. la router vers le
      // pipeline batch commun via WamaBatchImport.ingestText, réutilisant le
      // formalisme batch) au lieu du POST direct d'un champ vers un endpoint.
      if (typeof cfg.onSubmit === 'function') {
        Promise.resolve()
          .then(function () { return cfg.onSubmit(url); })
          .then(function () { input.value = ''; })
          .catch(function (err) {
            if (typeof cfg.onError === 'function') cfg.onError(err);
            else toast(err.message || "Échec de l'import de l'URL", 'error');
          })
          .finally(function () { btn.disabled = false; btn.innerHTML = original; });
        return;
      }

      const fd = new FormData();
      fd.append(field, url);
      const extra = (typeof cfg.extraFields === 'function') ? (cfg.extraFields() || {}) : {};
      Object.keys(extra).forEach(function (k) { fd.append(k, extra[k]); });
      csrfFetch(cfg.endpoint, cfg.csrfToken, { method: 'POST', body: fd })
        .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
        .then(function (res) {
          if (!res.ok || res.d.error) throw new Error(res.d.error || ('HTTP ' + (res.d.status || '')));
          input.value = '';
          if (typeof cfg.onSuccess === 'function') cfg.onSuccess(res.d);
        })
        .catch(function (err) {
          if (typeof cfg.onError === 'function') cfg.onError(err);
          else toast(err.message || "Échec du téléchargement de l'URL", 'error');
        })
        .finally(function () { btn.disabled = false; btn.innerHTML = original; });
    }

    btn.addEventListener('click', submit);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') { e.preventDefault(); submit(); }
    });
    return { submit: submit };
  }

  // ── Maps statut → apparence (source UNIQUE ; recopiées par app avant 2026-07-06) ──
  // Alignées sur le tricolore CARD_DESIGN : gris=brouillon · orange=en cours · vert=fini · rouge=échec.
  const STATUS_BADGE = {
    DRAFT: 'bg-secondary', PENDING: 'bg-secondary', RUNNING: 'bg-warning text-dark',
    SUCCESS: 'bg-success', FAILURE: 'bg-danger',
  };
  const STATUS_LABEL = {
    DRAFT: 'Brouillon', PENDING: 'En attente', RUNNING: 'En cours',
    SUCCESS: 'Terminé', FAILURE: 'Échec',
  };

  global.WamaApp = {
    escapeHtml: escapeHtml,
    getUrl: getUrl,
    csrfHeaders: csrfHeaders,
    csrfFetch: csrfFetch,
    wordCount: wordCount,
    Poller: Poller,
    emptyState: emptyState,
    toast: toast,
    initUrlImport: initUrlImport,
    STATUS_BADGE: STATUS_BADGE,
    STATUS_LABEL: STATUS_LABEL,
  };
})(window);
