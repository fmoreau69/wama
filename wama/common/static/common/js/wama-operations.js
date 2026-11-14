/**
 * WamaOperations — les OPÉRATIONS de la page « Exploitation » (2026-11-14, `ROADMAP §31.1`) :
 * lancer une opération déclarée (`common/operations.py`) et suivre celles qui ont été lancées.
 *
 * La page ne connaît aucune opération : le serveur les rend (un formulaire par opération) et les
 * lance en tâche de fond (`dev_run_operation`, par le serveur de développement). Ici : poster le
 * formulaire, relire la liste des tâches — plus souvent tant qu'une tourne —, et montrer la fin
 * du journal d'une tâche au clic. Une tâche est une TUILE des pages de gestion : elle porte sa
 * nature (`data-f-nature`, le mot que la page déclare sur l'hôte), son état (libellé et ton
 * rendus par le serveur, `operations.JOB_STATES`) et ses clés de tri (`data-s-*`) — la barre
 * commune la filtre et la trie, l'inspecteur commun en dérive la fiche.
 */
(function (global) {
  'use strict';

  // Les classes d'un TON : celles de la liste des processus (une table, pas deux).
  var TONES = (global.WamaProcesses && global.WamaProcesses.TONES) || {};
  var BUSY_MS = 4000, IDLE_MS = 30000;

  function esc(value) { return global.WamaApp.escapeHtml(value == null ? '' : String(value)); }

  /** Les tâches — rendu PUR (liste → HTML), exécuté tel quel par les tests. */
  function renderJobs(jobs, nature) {
    if (!jobs || !jobs.length) return '<p class="text-body-secondary">Aucune opération lancée.</p>';
    return jobs.map(function (job, index) {
      var state = job.state_label || job.status || '?';
      var name = job.label || String(job.tool || '');
      return '<div class="wama-cat-card ops-job" data-job="' + esc(job.id) + '" data-id="' + esc(job.id) + '"'
        + ' data-f-nature="' + esc(nature || '') + '" data-f-etat="' + esc(state) + '"'
        + ' data-s-order="' + (index + 1) + '" data-s-label="' + esc(name) + '" data-s-since="' + esc(job.id) + '"'
        + ' tabindex="0" role="button" aria-label="Voir le journal de ' + esc(name) + '">'
        + '<h4>' + esc(name) + ' <span class="badge ' + (TONES[job.tone] || 'bg-secondary') + '">'
        + esc(state) + '</span></h4>'
        + '<div class="wama-cat-meta">' + esc(job.user || '') + ' · <code>' + esc(job.id) + '</code></div>'
        + '<pre class="ops-log" hidden></pre></div>';
    }).join('');
  }

  function start() {
    var root = document.getElementById('wamaOperations');
    var host = document.getElementById('wamaOperationJobs');
    if (!root || !host) return;
    var runApi = root.dataset.runApi, jobsApi = root.dataset.jobsApi;
    var timer = null, open = {}, shown = null;

    /** La liste vient d'être re-rendue : la barre commune ré-applique filtre et tri. */
    function refreshBars() {
      if (!global.WamaFilterBar) return;
      document.querySelectorAll('[data-wama-filter-bar]').forEach(global.WamaFilterBar.refresh);
    }

    function load() {
      clearTimeout(timer);
      return fetch(jobsApi, { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) {
            host.innerHTML = '<p class="text-body-secondary">' + esc(data.error) + '</p>';
            timer = setTimeout(load, IDLE_MS);
            return;
          }
          var html = renderJobs(data.jobs, host.dataset.nature);
          if (html !== shown) {
            host.innerHTML = html; shown = html;
            Object.keys(open).forEach(showLog);
            refreshBars();
          }
          var busy = (data.jobs || []).some(function (j) { return j.status === 'running'; });
          timer = setTimeout(load, busy ? BUSY_MS : IDLE_MS);
        })
        .catch(function () { timer = setTimeout(load, IDLE_MS); });
    }

    function showLog(id) {
      var row = host.querySelector('[data-job="' + id + '"]');
      var log = row && row.querySelector('.ops-log');
      if (!log) { delete open[id]; return; }
      open[id] = true;
      log.hidden = false;
      fetch(jobsApi + '?job=' + encodeURIComponent(id), { headers: { Accept: 'application/json' } })
        .then(function (r) { return r.json(); })
        .then(function (job) { log.textContent = job.log_tail || job.error || '(journal vide)'; })
        .catch(function () { log.textContent = 'Journal illisible.'; });
    }

    host.addEventListener('click', function (event) {
      var row = event.target.closest ? event.target.closest('[data-job]') : null;
      if (!row) return;
      var id = row.dataset.job, log = row.querySelector('.ops-log');
      if (open[id]) { delete open[id]; log.hidden = true; } else { showLog(id); }
    });
    host.addEventListener('keydown', function (event) {
      if (event.key !== 'Enter' && event.key !== ' ') return;
      var row = event.target.closest ? event.target.closest('[data-job]') : null;
      if (row) { event.preventDefault(); row.click(); }
    });

    root.addEventListener('submit', function (event) {
      var form = event.target.closest ? event.target.closest('form[data-operation]') : null;
      if (!form) return;
      event.preventDefault();
      var argument = form.querySelector('[name="argument"]');
      var body = 'operation=' + encodeURIComponent(form.dataset.operation)
        + '&argument=' + encodeURIComponent(argument ? argument.value : '');
      var headers = global.WamaApp.csrfHeaders(global.WamaApp.csrfToken(),
        { 'Content-Type': 'application/x-www-form-urlencoded' });
      var button = form.querySelector('button[type="submit"]');
      if (button) button.disabled = true;
      fetch(runApi, { method: 'POST', headers: headers, body: body })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          global.WamaApp.toast(data.error ? data.error : 'Opération lancée', data.error ? 'error' : 'success');
          load();
        })
        .catch(function (err) { global.WamaApp.toast('Opération non lancée : ' + err.message, 'error'); })
        .then(function () { if (button) button.disabled = false; });
    });

    load();
  }

  global.WamaOperations = { _renderJobs: renderJobs };

  if (typeof document === 'undefined' || !document.addEventListener) {
    /* hors navigateur (V8 des tests) */
  } else if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})(typeof window !== 'undefined' ? window : this);
