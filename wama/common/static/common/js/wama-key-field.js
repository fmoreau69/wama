/*
 * wama-key-field.js — Le champ d'une clé d'API : saisie masquée (jamais réaffichée), œil,
 * Enregistrer, Supprimer, message de retour.
 *
 * POURQUOI une brique (2026-10-07) : ce champ vivait en ligne dans le profil (clés
 * personnelles). La page « Sources externes » en a eu besoin pour les clés de l'INSTANCE
 * (posées par un admin) — même geste, même retour : le recopier aurait fait deux champs qui
 * divergent au premier correctif. Le serveur ne renvoie JAMAIS une clé enregistrée : le
 * champ ne montre que la saisie en cours.
 *
 * Usage :
 *   host.innerHTML = WamaKeyField.render({ id, name, hasKey, label, helpUrl, status, data, extra });
 *   WamaKeyField.bind(root, { onSave(btn, key), onDelete(btn) });   // une fois, délégué
 *   WamaKeyField.send({ url, body, btn, msgEl }).then(data => …);   // POST JSON + attente
 * `status` = { text, cls } (badge) ; `data` = attributs data-* posés sur les boutons (rendus
 * tels quels à `onSave`/`onDelete` par `btn.dataset`) ; `extra` = HTML ajouté sous le champ.
 * Dépend de `WamaApp` (wama-app-base.js, global) pour l'échappement et le jeton CSRF.
 */
(function (global) {
  'use strict';

  function esc(text) {
    return global.WamaApp ? global.WamaApp.escapeHtml(String(text == null ? '' : text))
                          : String(text == null ? '' : text);
  }

  function dataAttrs(data) {
    return Object.keys(data || {}).map(function (k) {
      return 'data-' + k + '="' + esc(data[k]) + '"';
    }).join(' ');
  }

  function showMsg(el, text, isError) {
    if (!el) return;
    el.style.display = 'block';
    el.className = 'mt-1 small ' + (isError ? 'text-danger' : 'text-success');
    el.textContent = text;
    setTimeout(function () { el.style.display = 'none'; }, 4000);
  }

  function render(opts) {
    var id = opts.id;
    var attrs = dataAttrs(Object.assign({ 'key-id': id }, opts.data || {}));
    var status = opts.status || (opts.hasKey ? { text: '✓ Configuré', cls: 'bg-success' }
                                             : { text: 'Non configuré', cls: 'bg-secondary' });
    var placeholder = opts.hasKey ? 'Clé enregistrée (jamais réaffichée) — saisir pour la remplacer'
                                  : (opts.label || 'Clé API');
    return '' +
      '<div class="key-row">' +
        '<div class="d-flex justify-content-between align-items-center mb-1">' +
          '<span class="small text-light">' + esc(opts.name) +
            ' <span class="ms-1 badge ' + esc(status.cls) + '">' + esc(status.text) + '</span>' +
          '</span>' +
          (opts.helpUrl ? '<a href="' + esc(opts.helpUrl) + '" target="_blank" rel="noopener"' +
             ' class="btn btn-outline-secondary btn-sm py-0" title="Obtenir une clé">' +
             '<i class="fas fa-external-link-alt"></i></a>' : '') +
        '</div>' +
        '<div class="input-group input-group-sm">' +
          '<input type="password" id="key-' + esc(id) + '"' +
          ' class="form-control bg-dark text-light border-secondary"' +
          ' placeholder="' + esc(placeholder) + '" autocomplete="off">' +
          '<button class="btn btn-outline-secondary" type="button" data-key-action="toggle" ' + attrs +
          ' title="Afficher / masquer la saisie (une clé enregistrée n\'est jamais renvoyée au navigateur)">' +
            '<i class="fas fa-eye" id="eye-' + esc(id) + '"></i></button>' +
          '<button class="btn btn-outline-primary" type="button" data-key-action="save" ' + attrs +
          ' title="Enregistrer"><i class="fas fa-save"></i></button>' +
          (opts.hasKey ? '<button class="btn btn-outline-danger" type="button" data-key-action="delete" ' +
             attrs + ' title="Supprimer la clé"><i class="fas fa-times"></i></button>' : '') +
        '</div>' +
        (opts.extra || '') +
        '<div id="msg-' + esc(id) + '" class="mt-1" style="display:none;"></div>' +
      '</div>';
  }

  function msgFor(btn) { return document.getElementById('msg-' + btn.dataset.keyId); }

  // Un seul écouteur délégué par racine : le rendu à neuf d'une liste ne perd pas ses boutons.
  function bind(root, handlers) {
    (root || document).addEventListener('click', function (e) {
      var btn = e.target.closest('[data-key-action]');
      if (!btn || !(root || document).contains(btn)) return;
      var id = btn.dataset.keyId;
      var input = document.getElementById('key-' + id);
      var action = btn.dataset.keyAction;
      if (action === 'toggle') {
        var show = input.type === 'password';
        input.type = show ? 'text' : 'password';
        document.getElementById('eye-' + id).className = show ? 'fas fa-eye-slash' : 'fas fa-eye';
      } else if (action === 'save') {
        var key = input.value.trim();
        if (!key) { showMsg(msgFor(btn), 'Saisissez une clé.', true); return; }
        handlers.onSave(btn, key);
      } else if (action === 'delete') {
        if (confirm('Supprimer la clé ?')) handlers.onDelete(btn);
      }
    });
  }

  // POST JSON avec retour IMMÉDIAT (2026-10-02) : sans lui, un enregistrement lent semblait sans
  // effet et se faisait cliquer deux fois. Rend la réponse ; le bouton est remis en état en cas
  // d'échec (un succès est suivi d'un rendu à neuf par l'appelant).
  function send(opts) {
    var btn = opts.btn;
    var original = btn ? btn.innerHTML : '';
    var restore = function () { if (btn) { btn.disabled = false; btn.innerHTML = original; } };
    if (btn) {
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span>';
    }
    if (opts.msgEl && opts.pending) showMsg(opts.msgEl, opts.pending);
    var token = global.WamaApp ? global.WamaApp.csrfToken() : '';
    return fetch(opts.url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': opts.csrfToken || token },
      body: JSON.stringify(opts.body),
    }).then(function (r) { return r.json(); })
      .then(function (data) {
        if (!data.success) { restore(); showMsg(opts.msgEl, data.error || 'Erreur', true); }
        return data;
      })
      .catch(function () {
        restore();
        showMsg(opts.msgEl, 'Erreur réseau', true);
        return { success: false };
      });
  }

  // Le message qui suit un enregistrement réussi — le même sur les deux écrans.
  function savedMessage(data, key) {
    if (!key) return ['✓ Clé supprimée', false];
    if (data.discovery_error) return ['Clé enregistrée, modèles non lus : ' + data.discovery_error, true];
    if (data.models_count !== undefined) {
      return ['✓ Clé enregistrée — ' + data.models_count +
              ' modèle(s) ouvert(s) ; le catalogue se met à jour en arrière-plan', false];
    }
    return ['✓ Clé enregistrée', false];
  }

  global.WamaKeyField = { render: render, bind: bind, send: send, showMsg: showMsg,
                          savedMessage: savedMessage };
})(window);
