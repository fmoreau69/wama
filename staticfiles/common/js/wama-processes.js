/**
 * WamaProcesses — les PROCESSUS de WAMA qu'un administrateur relance depuis la page
 * « Exploitation » : chaque worker, tous les workers, la passerelle, les serveurs MCP, le serveur
 * web, WAMA entier.
 *
 * Sortie le 2026-11-14 de la page des modèles, qu'elle alourdissait pour des gestes qui ne la
 * concernent pas (`ROADMAP §31.1`). Rien n'est décidé ici : la liste, l'état de chaque ligne, ce
 * que coupe sa relance et les gestes offerts viennent du serveur
 * (`service_supervision.processes_overview`) ; un clic DÉPOSE un ordre que la surveillance
 * exécute à son prochain passage. Un geste qui coupe un travail redemande le mot de passe WAMA,
 * dans la confirmation commune (`WamaApp.ask`, champ masqué) — jamais en clair.
 *
 * Chaque processus est une LIGNE compacte du volet droit — la forme qu'il avait dans celui de la
 * page des modèles : son nom, son état en badge, son geste ; ce que coupe sa relance en infobulle.
 *
 * Montage : l'hôte `[data-wama-processes]` portant `data-api` (le relevé), `data-control-api`
 * (l'ordre) et, au choix, `data-count` (sélecteur des compteurs « en marche / total ») ; l'avis de
 * la surveillance s'écrit dans `[data-processes-notice-for="<id de la grille>"]`.
 */
(function (global) {
  'use strict';

  var TONES = {
    success: 'bg-success', warning: 'bg-warning text-dark', info: 'bg-info text-dark',
    secondary: 'bg-secondary', danger: 'bg-danger',
  };
  var REFRESH_MS = 15000;

  function esc(value) { return global.WamaApp.escapeHtml(value == null ? '' : String(value)); }

  /** Les lignes — rendu PUR (liste → HTML), exécuté tel quel par les tests. */
  function render(processes, canOrder) {
    return (processes || []).map(function (p) {
      var buttons = (p.actions || []).map(function () {
        return '<button type="button" class="btn btn-sm '
          + (p.kind === 'wama' ? 'btn-outline-danger' : 'btn-outline-secondary') + '"'
          + ' data-process="' + esc(p.key) + '" title="Relancer" aria-label="Relancer ' + esc(p.label) + '"'
          + (canOrder ? '' : ' disabled') + '>'
          + '<i class="fas fa-rotate" aria-hidden="true"></i></button>';
      }).join('');
      return '<div class="ops-process d-flex justify-content-between align-items-center gap-2"'
        + ' data-id="' + esc(p.key) + '" data-kind="' + esc(p.kind) + '" title="' + esc(p.when_off || '') + '">'
        + '<div><span class="text-body-emphasis">' + esc(p.label) + '</span><br>'
        + '<span class="badge ' + (TONES[p.tone] || TONES.secondary) + '">' + esc(p.state_label) + '</span></div>'
        + '<div class="d-flex gap-1 flex-shrink-0">' + buttons + '</div></div>';
    }).join('');
  }

  function mount(root) {
    if (!root || root._wamaProcesses) return;
    root._wamaProcesses = true;
    var api = root.dataset.api, controlApi = root.dataset.controlApi;
    var list = root;
    var notice = document.querySelector('[data-processes-notice-for="' + root.id + '"]');
    var counts = root.dataset.count ? document.querySelectorAll(root.dataset.count) : [];
    var known = {}, shown = null;

    function apply(data) {
      if (notice) {
        notice.hidden = !data.watchdog_message;
        notice.textContent = data.watchdog_message || '';
      }
      known = {};
      (data.processes || []).forEach(function (p) { known[p.key] = p; });
      // Rien n'est réécrit quand rien n'a changé : un relevé toutes les 15 s ne fait pas
      // clignoter la liste ni perdre le focus d'un bouton.
      var html = render(data.processes, data.watchdog === 'running');
      if (html !== shown) { list.innerHTML = html; shown = html; }
      var running = (data.processes || []).filter(function (p) { return p.state === 'ok'; }).length;
      Array.prototype.forEach.call(counts, function (count) {
        count.textContent = running + '/' + (data.processes || []).length;
      });
    }

    function load() {
      return fetch(api, { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (data) { if (data && data.success !== false) apply(data); })
        .catch(function () { /* le prochain passage relira */ });
    }

    function post(key, password) {
      var headers = global.WamaApp.csrfHeaders(global.WamaApp.csrfToken(),
        { 'Content-Type': 'application/json' });
      return fetch(controlApi, {
        method: 'POST', headers: headers,
        body: JSON.stringify({ service: key, action: 'restart', password: password || '' }),
      }).then(function (r) { return r.json(); });
    }

    function control(key) {
      var process = known[key];
      if (!process) return;
      var said = process.when_off ? '\n' + process.when_off : '';
      if (!global.confirm('Relancer « ' + process.label + ' » ?' + said)) return;
      post(key).then(function (data) {
        if (!data.needs_password) return data;
        return global.WamaApp.ask({
          text: data.error, okLabel: 'Relancer',
          input: { label: 'Mot de passe WAMA', secret: true },
        }).then(function (answer) { return answer.ok ? post(key, answer.value) : null; });
      }).then(function (data) {
        if (data) global.WamaApp.toast(data.success ? data.message : data.error, data.success ? 'success' : 'error');
        load();
      }).catch(function (err) { global.WamaApp.toast('Ordre non déposé : ' + err.message, 'error'); });
    }

    list.addEventListener('click', function (event) {
      var button = event.target.closest ? event.target.closest('button[data-process]') : null;
      if (button) control(button.dataset.process);
    });
    load();
    global.setInterval(load, REFRESH_MS);
  }

  global.WamaProcesses = { mount: mount, _render: render, TONES: TONES };

  function start() {
    document.querySelectorAll('[data-wama-processes]').forEach(mount);
  }
  if (typeof document === 'undefined' || !document.addEventListener) {
    /* hors navigateur (V8 des tests) */
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})(typeof window !== 'undefined' ? window : this);
