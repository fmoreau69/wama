/**
 * WamaNotifications — le PANNEAU de la cloche (`WAMA_COLLABORATION.md §2.3`, 2026-10-13).
 *
 * Demande de Fabien : *« quand je clique sur la cloche, une petite fenêtre contextuelle avec en bas
 * un lien vers la page complète, pour éviter d'être redirigé à chaque fois… je veux pouvoir
 * interagir avec les notifications directement dans la petite fenêtre »*. Jusque-là, la cloche
 * était un LIEN vers `/common/notifications/`.
 *
 * Ce que fait le panneau, sans quitter la page :
 *   - les 20 plus récentes, « Toutes » ou « Non lues » (choix retenu par navigateur) ;
 *   - cliquer une notification l'OUVRE (route qui la marque lue, puis son lien) ;
 *   - lu / non lu, supprimer (avec « Annuler » quelques secondes), « Tout marquer comme lu » ;
 *   - les gestes PROPRES à un type (« Accorder / Refuser » une demande d'accès) — déclarés par le
 *     serveur (`services/notification_panel.py`) : cette brique ne connaît AUCUN type ;
 *   - clavier : flèches entre les notifications, Entrée pour ouvrir, Suppr pour supprimer, Échap.
 * Ouvrir le panneau ne marque RIEN comme lu (décision de Fabien) : « lu » veut dire traité.
 *
 * La cloche garde son lien : Ctrl/Cmd-clic ou clic du milieu ouvrent toujours la page complète.
 * La relève périodique reste celle de `wama-app-base.js` (pastille, fenêtres en bas à droite) ;
 * elle annonce `wama:notifications`, et le panneau ouvert se relit.
 *
 * Les gestes `[data-wn-page-act]` de la page complète passent par les mêmes routes.
 */
(function (global) {
  'use strict';

  const API = '/common/api/notifications/';
  const PAGE_URL = '/common/notifications/';
  const FILTER_KEY = 'wama.notifications.filter';
  const UNDO_MS = 5000;

  // ── Rendu : fonctions PURES (état → HTML), testées dans V8 ───────────────────────────────

  // L'échappement COMMUN (`WamaApp.escapeHtml`) ; la conversion en texte d'abord, qu'il ne fait
  // pas (un nombre n'a pas de `.replace`).
  function esc(value) { return global.WamaApp.escapeHtml(value == null ? '' : String(value)); }

  function pad(n) { return (n < 10 ? '0' : '') + n; }

  // « à l'instant », « il y a 5 min », « il y a 2 h », « hier », « il y a 3 j », puis la date.
  function relativeTime(iso, now) {
    const t = Date.parse(iso || '');
    if (!isFinite(t)) return '';
    const s = Math.max(0, Math.round(((now || Date.now()) - t) / 1000));
    if (s < 45) return 'à l’instant';
    if (s < 3600) return 'il y a ' + Math.max(1, Math.round(s / 60)) + ' min';
    if (s < 86400) return 'il y a ' + Math.round(s / 3600) + ' h';
    const days = Math.floor(s / 86400);
    if (days === 1) return 'hier';
    if (days < 7) return 'il y a ' + days + ' j';
    const d = new Date(t);
    return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear();
  }

  function absoluteTime(iso) {
    const t = Date.parse(iso || '');
    if (!isFinite(t)) return '';
    const d = new Date(t);
    return pad(d.getDate()) + '/' + pad(d.getMonth() + 1) + '/' + d.getFullYear() + ' '
      + pad(d.getHours()) + ':' + pad(d.getMinutes());
  }

  function renderActions(n, state) {
    const consent = state.consent[n.id];
    if (consent) {
      return '<div class="wn-consent">'
        + '<div class="wn-consent-text">' + esc(consent.statement) + '</div>'
        + '<div class="wn-actions">'
        + '<button type="button" class="wn-btn tone-success" data-wn-consent="' + n.id + '">'
        + '<i class="fas fa-check" aria-hidden="true"></i> Valider et ' + esc(consent.label.toLowerCase())
        + '</button>'
        + '<button type="button" class="wn-btn" data-wn-consent-cancel="' + n.id + '">Annuler</button>'
        + '</div></div>';
    }
    if (!n.actions || !n.actions.length) return '';
    const busy = state.busy[n.id];
    return '<div class="wn-actions">' + n.actions.map(function (a, i) {
      return '<button type="button" class="wn-btn tone-' + esc(a.tone || 'neutral') + '"'
        + ' data-wn-do="' + i + '"' + (busy ? ' disabled' : '') + '>'
        + (a.icon ? '<i class="fas ' + esc(a.icon) + '" aria-hidden="true"></i> ' : '')
        + esc(a.label) + '</button>';
    }).join('') + '</div>';
  }

  function renderItem(n, state, now) {
    if (state.pending[n.id]) {
      return '<li class="wn-undo" data-id="' + n.id + '">Notification supprimée'
        + '<button type="button" class="wn-link" data-wn-undo="' + n.id + '">Annuler</button></li>';
    }
    const expanded = !!state.expanded[n.id];
    const label = n.read ? 'Marquer comme non lue' : 'Marquer comme lue';
    return '<li class="wn-item' + (n.read ? '' : ' is-unread') + (expanded ? ' is-expanded' : '') + '"'
      + ' data-id="' + n.id + '">'
      + '<div class="wn-row" tabindex="0" data-wn-open'
      + ' aria-label="' + esc((n.read ? '' : 'Non lue : ') + n.title) + '">'
      + '<span class="wn-icon tone-' + esc(n.tone || 'neutral') + '" aria-hidden="true">'
      + '<i class="fas ' + esc(n.icon || 'fa-bell') + '"></i></span>'
      + '<div class="wn-main">'
      + '<div class="wn-title">' + esc(n.title) + '</div>'
      + (n.body ? '<div class="wn-text">' + esc(n.body) + '</div>' : '')
      + '<div class="wn-meta"><time datetime="' + esc(n.created_at) + '" title="'
      + esc(absoluteTime(n.created_at)) + '">' + esc(relativeTime(n.created_at, now)) + '</time>'
      + (n.open_url ? '<span class="wn-go">Ouvrir <i class="fas fa-arrow-right" aria-hidden="true"></i></span>' : '')
      + '</div>'
      + '</div>'
      + (n.read ? '' : '<span class="wn-dot" aria-hidden="true"></span>')
      + '</div>'
      + renderActions(n, state)
      + '<div class="wn-tools">'
      + '<button type="button" class="wn-tool" data-wn-toggle title="' + label + '" aria-label="' + label + '">'
      + '<i class="fas ' + (n.read ? 'fa-envelope' : 'fa-envelope-open') + '" aria-hidden="true"></i></button>'
      + '<button type="button" class="wn-tool" data-wn-delete title="Supprimer" aria-label="Supprimer">'
      + '<i class="fas fa-trash-alt" aria-hidden="true"></i></button>'
      + '</div>'
      + '</li>';
  }

  function renderBody(state, now) {
    if (state.error && !state.items.length) {
      return '<div class="wn-state"><i class="fas fa-exclamation-triangle" aria-hidden="true"></i>'
        + '<div>Impossible de charger les notifications.</div>'
        + '<button type="button" class="wn-btn" data-wn-retry>Réessayer</button></div>';
    }
    if (state.loading && !state.items.length) {
      return '<div class="wn-state"><i class="fas fa-spinner fa-spin" aria-hidden="true"></i>'
        + '<div>Chargement…</div></div>';
    }
    if (!state.items.length) {
      return state.filter === 'unread'
        ? '<div class="wn-state"><i class="fas fa-check-circle" aria-hidden="true"></i>'
          + '<div>Tout est lu.</div></div>'
        : '<div class="wn-state"><i class="fas fa-bell-slash" aria-hidden="true"></i>'
          + '<div>Aucune notification.</div></div>';
    }
    return '<ul class="wn-list">' + state.items.map(function (n) {
      return renderItem(n, state, now);
    }).join('') + '</ul>';
  }

  function renderPanel(state, now) {
    const tab = function (key, label) {
      const on = state.filter === key;
      return '<button type="button" role="tab" class="wn-tab' + (on ? ' is-on' : '') + '"'
        + ' aria-selected="' + on + '" data-wn-filter="' + key + '">' + label + '</button>';
    };
    return '<div class="wn-head">'
      + '<span class="wn-heading" id="wn-heading">Notifications</span>'
      + '<div class="wn-tabs" role="tablist">'
      + tab('all', 'Toutes')
      + tab('unread', 'Non lues' + (state.unread ? ' <span class="wn-count">' + state.unread + '</span>' : ''))
      + '</div>'
      + '<button type="button" class="wn-tool" data-wn-readall title="Tout marquer comme lu"'
      + ' aria-label="Tout marquer comme lu"' + (state.unread ? '' : ' disabled') + '>'
      + '<i class="fas fa-check-double" aria-hidden="true"></i></button>'
      + '</div>'
      + '<div class="wn-scroll">' + renderBody(state, now) + '</div>'
      + '<a class="wn-foot" href="' + PAGE_URL + '">Voir toutes les notifications'
      + ' <i class="fas fa-arrow-right" aria-hidden="true"></i></a>';
  }

  // ── État et échanges ─────────────────────────────────────────────────────────────────────

  function readFilter() {
    try { return localStorage.getItem(FILTER_KEY) === 'unread' ? 'unread' : 'all'; }
    catch (e) { return 'all'; }
  }

  const state = {
    open: false, filter: readFilter(), items: [], unread: 0, loading: false, error: false,
    expanded: {}, busy: {}, consent: {}, pending: {},
  };
  let panel = null;
  let loadSeq = 0;

  function bell() { return document.getElementById('wamaNotificationsLink'); }

  function post(url, data, keepalive) {
    const body = new FormData();
    Object.keys(data || {}).forEach(function (k) { body.append(k, data[k]); });
    return global.WamaApp.csrfFetch(url, global.WamaApp.csrfToken(),
                                    { method: 'POST', body: body, keepalive: !!keepalive })
      .then(function (r) { return r.json().catch(function () { return { done: r.ok }; }); });
  }

  function setUnread(n) {
    state.unread = Math.max(0, n | 0);
    if (global.WamaApp && global.WamaApp.setBellCount) global.WamaApp.setBellCount(state.unread);
  }

  function itemById(id) {
    id = Number(id);
    for (let i = 0; i < state.items.length; i++) if (state.items[i].id === id) return state.items[i];
    return null;
  }

  function load() {
    const seq = ++loadSeq;
    state.loading = true; state.error = false;
    render();
    return fetch(API + '?limit=20&filter=' + state.filter, { headers: { Accept: 'application/json' } })
      .then(function (r) {
        // Route absente (serveur pas encore relancé après l'ajout du panneau) : la cloche fait
        // ce qu'elle faisait jusque-là, elle mène à la page complète.
        if (r.status === 404) { global.location.href = PAGE_URL; throw new Error('HTTP 404'); }
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      })
      .then(function (d) {
        if (seq !== loadSeq) return;                      // un chargement plus récent a gagné
        // Une suppression en attente d'« Annuler » reste à sa place dans la liste relue.
        const kept = state.items.filter(function (n) { return state.pending[n.id]; });
        state.items = (d.items || []).filter(function (n) { return !state.pending[n.id]; });
        kept.forEach(function (n) { state.items.push(n); });
        state.items.sort(function (a, b) { return Date.parse(b.created_at) - Date.parse(a.created_at) || b.id - a.id; });
        state.loading = false;
        setUnread(d.unread);
        render();
      })
      .catch(function () {
        if (seq !== loadSeq) return;
        state.loading = false; state.error = true;
        render();
      });
  }

  function act(id, action) {
    return post(API + id + '/' + action + '/', {}).then(function (d) {
      if (!d || !d.done) throw new Error((d && d.reason) || 'refusé');
      if (typeof d.unread === 'number') setUnread(d.unread);
      return d;
    });
  }

  function toggleRead(id) {
    const n = itemById(id);
    if (!n) return;
    const wasRead = n.read;
    n.read = !wasRead;
    render();
    act(id, wasRead ? 'unread' : 'read').catch(function () {
      n.read = wasRead; render();
      global.WamaApp.toast('Notification non modifiée', 'error');
    });
  }

  function markRead(n) {
    if (n.read) return;
    n.read = true;
    render();
    act(n.id, 'read').catch(function () { n.read = false; render(); });
  }

  // Supprimer : la ligne devient « Notification supprimée · Annuler » ; la suppression part au bout
  // de quelques secondes, ou dès que le panneau se ferme.
  function remove(id) {
    const n = itemById(id);
    if (!n || state.pending[id]) return;
    state.pending[id] = setTimeout(function () { commitRemove(id); }, UNDO_MS);
    render();
  }

  function commitRemove(id, keepalive) {
    if (!state.pending[id]) return;
    clearTimeout(state.pending[id]);
    delete state.pending[id];
    const n = itemById(id);
    state.items = state.items.filter(function (x) { return x.id !== Number(id); });
    render();
    post(API + id + '/delete/', {}, keepalive).then(function (d) {
      if (d && typeof d.unread === 'number') setUnread(d.unread);
      if (!d || !d.done) throw new Error('refusé');
    }).catch(function () {
      if (n) { state.items.push(n); load(); }
      global.WamaApp.toast('Notification non supprimée', 'error');
    });
  }

  function undoRemove(id) {
    clearTimeout(state.pending[id]);
    delete state.pending[id];
    render();
  }

  function flushRemovals(keepalive) {
    Object.keys(state.pending).forEach(function (id) { commitRemove(id, keepalive); });
  }

  function readAll() {
    state.items.forEach(function (n) { n.read = true; });
    render();
    post(API + 'read-all/', {}).then(function (d) {
      if (!d || !d.done) throw new Error('refusé');
      setUnread(0);
      if (state.filter === 'unread') load(); else render();
    }).catch(function () {
      global.WamaApp.toast('Notifications non marquées', 'error');
      load();
    });
  }

  // Un geste propre au type (déclaré par le serveur). Contrat de réponse lu : `done`, `reason`,
  // `consent_required` + `statement` (accepter une cession de propriété demande un consentement).
  function runAction(id, index, withConsent) {
    const n = itemById(id);
    const a = n && n.actions && n.actions[index];
    if (!a) return;
    state.busy[id] = true;
    render();
    const data = Object.assign({}, a.data || {});
    if (withConsent) data.consent = '1';
    post(a.post, data).then(function (d) {
      delete state.busy[id];
      if (d && d.consent_required) {
        state.consent[id] = { statement: d.statement || '', index: index, label: a.label };
        render();
        return;
      }
      delete state.consent[id];
      if (!d || !d.done) {
        render();
        global.WamaApp.toast((d && d.reason) || 'Geste refusé', 'error');
        return;
      }
      global.WamaApp.toast(a.done || 'Fait', 'success');
      markRead(n);
      load();                         // les gestes se recalculent (une demande traitée n'en a plus)
    }).catch(function () {
      delete state.busy[id];
      render();
      global.WamaApp.toast('Erreur réseau', 'error');
    });
  }

  function openItem(id) {
    const n = itemById(id);
    if (!n) return;
    if (n.open_url) { global.location.href = n.open_url; return; }   // marque lue côté serveur
    state.expanded[id] = !state.expanded[id];
    markRead(n);
  }

  // ── Panneau : ouverture, placement, rendu ────────────────────────────────────────────────

  function render() {
    if (!panel || !state.open) return;
    const focused = document.activeElement;
    const focusId = focused && panel.contains(focused) && focused.closest('[data-id]')
      ? focused.closest('[data-id]').getAttribute('data-id') : null;
    const focusSel = focused && focused.hasAttribute && focused.hasAttribute('data-wn-filter')
      ? '[data-wn-filter="' + focused.getAttribute('data-wn-filter') + '"]' : null;
    const scroll = panel.querySelector('.wn-scroll');
    const top = scroll ? scroll.scrollTop : 0;
    panel.innerHTML = renderPanel(state, Date.now());
    const after = panel.querySelector('.wn-scroll');
    if (after) after.scrollTop = top;
    let target = null;
    if (focusId) target = panel.querySelector('[data-id="' + focusId + '"] .wn-row');
    else if (focusSel) target = panel.querySelector(focusSel);
    if (target) target.focus({ preventScroll: true });
  }

  function place() {
    const b = bell();
    if (!panel || !b) return;
    const r = b.getBoundingClientRect();
    const vw = global.innerWidth || document.documentElement.clientWidth;
    panel.style.top = Math.round(r.bottom + 8) + 'px';
    if (vw <= 576) {                                   // téléphone : toute la largeur
      panel.style.left = '8px'; panel.style.right = '8px';
    } else {
      panel.style.left = 'auto';
      panel.style.right = Math.max(8, Math.round(vw - r.right - 8)) + 'px';
    }
  }

  function open() {
    if (state.open) return;
    if (!panel) {
      panel = document.createElement('div');
      panel.className = 'wn-panel';
      panel.id = 'wama-notifications-panel';
      panel.setAttribute('role', 'dialog');
      panel.setAttribute('aria-labelledby', 'wn-heading');
      panel.addEventListener('click', onPanelClick);
      panel.addEventListener('keydown', onPanelKey);
      document.body.appendChild(panel);
    }
    state.open = true;
    state.expanded = {};
    panel.hidden = false;
    const b = bell();
    if (b) b.setAttribute('aria-expanded', 'true');
    place();
    render();
    load().then(function () {
      const first = panel.querySelector('.wn-row') || panel.querySelector('.wn-tab.is-on');
      if (first && state.open) first.focus({ preventScroll: true });
    });
  }

  function close(returnFocus) {
    if (!state.open) return;
    state.open = false;
    flushRemovals(false);
    state.consent = {};
    if (panel) panel.hidden = true;
    const b = bell();
    if (b) {
      b.setAttribute('aria-expanded', 'false');
      if (returnFocus) b.focus();
    }
  }

  function rows() { return panel ? Array.prototype.slice.call(panel.querySelectorAll('.wn-row')) : []; }

  function onPanelKey(e) {
    if (e.key === 'Escape') { e.preventDefault(); close(true); return; }
    const row = e.target.closest && e.target.closest('.wn-row');
    if (!row) return;
    const id = row.closest('[data-id]').getAttribute('data-id');
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      const all = rows();
      const i = all.indexOf(row) + (e.key === 'ArrowDown' ? 1 : -1);
      if (all[i]) all[i].focus();
    } else if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault(); openItem(id);
    } else if (e.key === 'Delete') {
      e.preventDefault(); remove(Number(id));
    }
  }

  function onPanelClick(e) {
    const t = e.target;
    const hit = function (sel) { return t.closest ? t.closest(sel) : null; };
    const li = hit('[data-id]');
    const id = li ? Number(li.getAttribute('data-id')) : null;
    let el;
    if ((el = hit('[data-wn-filter]'))) {
      const f = el.getAttribute('data-wn-filter');
      if (f !== state.filter) {
        state.filter = f;
        try { localStorage.setItem(FILTER_KEY, f); } catch (err) { /* préférence non retenue */ }
        state.items = [];
        load();
      }
    } else if (hit('[data-wn-readall]')) readAll();
    else if (hit('[data-wn-retry]')) load();
    else if ((el = hit('[data-wn-undo]'))) undoRemove(Number(el.getAttribute('data-wn-undo')));
    else if ((el = hit('[data-wn-consent]'))) {
      const c = state.consent[id];
      if (c) runAction(id, c.index, true);
    } else if (hit('[data-wn-consent-cancel]')) { delete state.consent[id]; render(); }
    else if ((el = hit('[data-wn-do]'))) runAction(id, Number(el.getAttribute('data-wn-do')), false);
    else if (hit('[data-wn-toggle]')) toggleRead(id);
    else if (hit('[data-wn-delete]')) remove(id);
    else if (hit('[data-wn-open]')) openItem(id);
  }

  function onBellClick(e) {
    // Ctrl/Cmd/Maj-clic ou clic du milieu : le lien garde son sens (page complète).
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;
    e.preventDefault();
    if (state.open) close(false); else open();
  }

  function onDocumentPointer(e) {
    if (!state.open || !panel) return;
    const b = bell();
    if (panel.contains(e.target) || (b && b.contains(e.target))) return;
    close(false);
  }

  // Gestes de la PAGE complète (`notifications.html`) : mêmes routes, puis la page se relit.
  function onPageAct(e) {
    const btn = e.target.closest ? e.target.closest('[data-wn-page-act]') : null;
    if (!btn) return;
    e.preventDefault();
    const action = btn.getAttribute('data-wn-page-act');
    // Pas d'« Annuler » sur la page (elle se relit) : la suppression se confirme.
    if (action === 'delete' && !global.confirm('Supprimer cette notification ?')) return;
    btn.disabled = true;
    act(btn.getAttribute('data-id'), action)
      .then(function () { global.location.reload(); })
      .catch(function () {
        btn.disabled = false;
        global.WamaApp.toast('Notification non modifiée', 'error');
      });
  }

  function start() {
    document.addEventListener('click', onPageAct);
    const b = bell();
    if (!b) return;                                    // visiteur sans compte : pas de cloche
    b.setAttribute('aria-haspopup', 'dialog');
    b.setAttribute('aria-expanded', 'false');
    b.setAttribute('aria-controls', 'wama-notifications-panel');
    b.addEventListener('click', onBellClick);
    document.addEventListener('pointerdown', onDocumentPointer);
    global.addEventListener('resize', function () { if (state.open) place(); });
    document.addEventListener('wama:notifications', function () { if (state.open) load(); });
    // Une suppression en attente part même si l'on quitte la page avant « Annuler ».
    global.addEventListener('pagehide', function () { flushRemovals(true); });
  }

  global.WamaNotifications = {
    open: open,
    close: close,
    isOpen: function () { return state.open; },
    reload: load,
    // Pour les tests (rendu pur) :
    _renderPanel: renderPanel,
    _relativeTime: relativeTime,
  };

  if (typeof document === 'undefined' || !document.addEventListener) {
    /* hors navigateur (V8 des tests) */
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})(window);
