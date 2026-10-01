/**
 * WamaReleasedFiles — ANNONCER les fichiers qu'une card retirée a libérés (2026-09-30).
 *
 * Décision de Fabien : retirer une card ne supprime plus ses fichiers. On PRÉVIENT : « ce fichier
 * n'est plus utilisé par aucune card » ; la suppression reste un GESTE EXPLICITE de l'utilisateur.
 * Le serveur tient la liste (`common/services/released_files.py`) ; cette brique la lit :
 *   • au chargement de chaque page — une suppression suivie d'un rechargement (« tout effacer »
 *     de plusieurs apps) est annoncée sur la page qui suit ;
 *   • à l'événement `media:deleted` — celui que TOUTE suppression émet déjà (`WamaFM.deleted()`,
 *     `wama-fm-notify.js`) : la brique commune de file comme les apps qui l'appellent elles-mêmes
 *     (transcriber, avatarizer, enhancer). Un événement neuf n'aurait couvert que la première.
 * Chaque fichier n'est annoncé qu'UNE fois ; « Garder » ne fait rien d'autre que fermer.
 */
(function (global) {
  'use strict';

  var LIST_URL = '/common/api/released-files/';
  var DELETE_URL = '/common/api/released-files/delete/';
  var busy = false;

  function csrf() {
    var m = document.cookie.match(/csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function host() {
    var el = document.getElementById('wama-released-files');
    if (el) return el;
    el = document.createElement('div');
    el.id = 'wama-released-files';
    el.className = 'position-fixed bottom-0 end-0 m-3';
    el.style.zIndex = 1090;
    el.style.maxWidth = '26rem';
    document.body.appendChild(el);
    return el;
  }

  function show(files) {
    var names = files.slice(0, 5).map(function (f) {
      return '<li class="text-truncate" title="' + esc(f.path) + '">' + esc(f.name) + '</li>';
    }).join('');
    var more = files.length > 5 ? '<li class="text-muted">… et ' + (files.length - 5) + ' autre(s)</li>' : '';
    var box = document.createElement('div');
    box.className = 'card bg-dark text-light border-warning shadow mb-2';
    box.setAttribute('data-released-files', '');
    box.innerHTML = '<div class="card-body p-2 small">'
      + '<div class="mb-1"><i class="fas fa-file-circle-exclamation text-warning me-1"></i>'
      + (files.length > 1
          ? files.length + ' fichiers ne sont plus utilisés par aucune card. Ils restent dans votre espace.'
          : 'Ce fichier n’est plus utilisé par aucune card. Il reste dans votre espace.')
      + '</div>'
      + '<ul class="mb-2 ps-3">' + names + more + '</ul>'
      + '<div class="d-flex gap-2 justify-content-end align-items-center">'
      + '<a href="/media-library/?tab=unused" class="link-light small me-auto">Tous les fichiers inutilisés</a>'
      + '<button type="button" class="btn btn-sm btn-outline-secondary" data-released-keep>Garder</button>'
      + '<button type="button" class="btn btn-sm btn-outline-danger" data-released-delete>Supprimer</button>'
      + '</div></div>';
    host().appendChild(box);
    box.querySelector('[data-released-keep]').addEventListener('click', function () { box.remove(); });
    box.querySelector('[data-released-delete]').addEventListener('click', function () {
      var fd = new FormData();
      files.forEach(function (f) { fd.append('ids', f.id); });
      fetch(DELETE_URL, { method: 'POST', body: fd, credentials: 'same-origin',
                          headers: { 'X-CSRFToken': csrf() } })
        .then(function (r) { return r.json(); })
        .then(function (res) {
          box.remove();
          var n = (res.deleted || []).length, kept = (res.kept || []).length;
          var msg = n + ' fichier(s) supprimé(s)' + (kept ? ' ; ' + kept + ' gardé(s) — repris par une card' : '');
          if (global.WamaApp && WamaApp.toast) WamaApp.toast(msg, kept ? 'warning' : 'success');
          if (global.WamaFM && WamaFM.deleted) WamaFM.deleted();
        })
        .catch(function () {
          if (global.WamaApp && WamaApp.toast) WamaApp.toast('Suppression impossible', 'danger');
        });
    });
  }

  // La LISTE des fichiers inutilisés (onglet « Inutilisés » de la médiathèque, `data-released-files-list`)
  // dit déjà tout : l'encart y ferait doublon, et masquerait ses boutons.
  function listShown() {
    var el = document.querySelector('[data-released-files-list]');
    return !!(el && el.offsetParent !== null);
  }

  function check() {
    if (busy || listShown()) return;
    busy = true;
    fetch(LIST_URL, { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { files: [] }; })
      .then(function (data) { if (data.files && data.files.length) show(data.files); })
      .catch(function () { /* silencieux : une annonce manquée sera faite à la page suivante */ })
      .then(function () { busy = false; });
  }

  document.addEventListener('media:deleted', function () { setTimeout(check, 300); });
  // Au chargement, un temps pour que la page montre son panneau (la médiathèque ouvre l'onglet
  // « Inutilisés » par son JS) avant de décider s'il faut annoncer.
  function checkSoon() { setTimeout(check, 600); }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', checkSoon);
  else checkSoon();

  global.WamaReleasedFiles = { check: check };
})(window);
