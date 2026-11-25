/*
 * Mes données d'annuaire — LE composant, monté à deux endroits de la page de profil : la carte
 * du profil et le panneau d'accueil de la première connexion (2026-11-25).
 *
 * Chaque donnée que l'annuaire propose est une pastille : la personne l'ajoute ou la retire, une
 * par une ou d'un geste. Les rôles métier se demandent au même endroit. La page ne porte aucune
 * donnée : tout vient de la route `accounts:directory-consent`, et ce que l'annuaire rend
 * s'écrit par `textContent`, jamais en HTML.
 *
 * Montage : tout élément `[data-directory-consent]` avec `data-url` (l'état et le choix) et
 * `data-role-url` (demander un rôle). Les montages d'une même page partagent leur état.
 */
(function () {
  'use strict';

  const mounts = [];
  let current = null;

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined) { node.textContent = text; }
    return node;
  }

  // L'envoi protégé est celui du socle commun (`WamaApp.csrfFetch`, `wama-app-base.js`).
  function send(url, body, asForm) {
    const options = asForm ? { method: 'POST', body: body }
      : { method: 'POST', body: JSON.stringify(body), headers: { 'Content-Type': 'application/json' } };
    return window.WamaApp.csrfFetch(url, window.WamaApp.csrfToken(), options)
      .then(function (response) { return response.json(); });
  }

  // Une donnée est GARDÉE si la personne l'a ajoutée, ou si elle n'a pas encore choisi et que le
  // profil la porte déjà.
  function kept(row) {
    return row.choice === 'accepted' || (row.choice === 'undecided' && row.stored);
  }

  function dataRow(mount, row) {
    const line = element('div', 'd-flex align-items-start gap-3 py-2 border-bottom border-secondary');
    const on = kept(row);
    const pill = element('button', 'btn btn-sm rounded-pill text-nowrap ' +
      (on ? (row.choice === 'accepted' ? 'btn-success' : 'btn-outline-success') : 'btn-outline-secondary'),
      on ? (row.choice === 'accepted' ? '✓ Ajoutée' : '✓ Présente') : (row.choice === 'declined' ? 'Retirée' : 'Non ajoutée'));
    pill.type = 'button';
    pill.style.minWidth = '8rem';
    pill.title = on ? 'Retirer cette donnée de mon profil' : 'Ajouter cette donnée à mon profil';
    pill.addEventListener('click', function () {
      choose(mount, on ? { decline: [row.key] } : { accept: [row.key] });
    });
    line.appendChild(pill);

    const text = element('div', 'flex-grow-1');
    text.appendChild(element('div', 'fw-semibold', row.label));
    let shown = '';
    if (row.stored && row.value) {
      shown = row.value;
    } else if (row.offer) {
      shown = "L'annuaire propose : " + row.offer;
    } else if (!on) {
      shown = "Sa valeur sera lue dans l'annuaire à l'ajout.";
    }
    if (shown) { text.appendChild(element('div', 'text-body-emphasis', shown)); }
    if (row.choice === 'undecided' && row.stored) {
      text.appendChild(element('div', 'small text-body-secondary',
        "Reprise de l'annuaire à la création de votre compte : gardez-la ou retirez-la."));
    }
    text.appendChild(element('div', 'small text-body-secondary', row.opens));
    line.appendChild(text);
    return line;
  }

  function roleButton(mount, role) {
    const pill = element('button', 'btn btn-sm rounded-pill me-2 mb-2 ' +
      (role.held ? 'btn-success' : (role.pending ? 'btn-outline-warning' : 'btn-outline-primary')),
      role.held ? '✓ ' + role.label : (role.pending ? role.label + ' — demandé' : role.label));
    pill.type = 'button';
    pill.title = role.description || '';
    pill.disabled = !!(role.held || role.pending);
    pill.addEventListener('click', function () {
      const form = new FormData();
      form.append('role', role.key);
      send(mount.roleUrl, form, true).then(function (result) {
        if (result.done) { load(mount); } else { say(mount, result.reason || 'Demande refusée.'); }
      }).catch(function () { say(mount, "La demande n'a pas pu partir."); });
    });
    return pill;
  }

  function say(mount, text) {
    if (mount.message) { mount.message.textContent = text || ''; }
  }

  function render(mount) {
    if (!current) { return; }
    mount.list.replaceChildren.apply(mount.list, current.data.map(function (row) { return dataRow(mount, row); }));
    if (mount.roles) {
      mount.roles.replaceChildren.apply(mount.roles, current.roles.map(function (role) { return roleButton(mount, role); }));
    }
    say(mount, '');
  }

  function apply(payload, mount) {
    if (!payload.success) { say(mount, payload.error || "L'état n'a pas pu être lu."); return; }
    current = payload;
    mounts.forEach(render);
  }

  function load(mount) {
    return fetch(mount.url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
      .then(function (response) { return response.json(); })
      .then(function (payload) { apply(payload, mount); })
      .catch(function () { say(mount, "L'état de vos données n'a pas pu être lu."); });
  }

  function choose(mount, body) {
    say(mount, 'Enregistrement…');
    return send(mount.url, body)
      .then(function (payload) { apply(payload, mount); return payload; })
      .catch(function () { say(mount, "Le choix n'a pas pu être enregistré."); });
  }

  function mountOn(root) {
    const mount = {
      root: root, url: root.dataset.url, roleUrl: root.dataset.roleUrl,
      list: root.querySelector('[data-consent-list]'),
      roles: root.querySelector('[data-consent-roles]'),
      message: root.querySelector('[data-consent-message]'),
    };
    if (!mount.url || !mount.list) { return null; }
    mounts.push(mount);
    root.querySelectorAll('[data-consent-all]').forEach(function (button) {
      button.addEventListener('click', function () {
        if (!current) { return; }
        const keys = current.data.map(function (row) { return row.key; });
        choose(mount, button.dataset.consentAll === 'accept' ? { accept: keys } : { decline: keys });
      });
    });
    // « Terminer » : la personne a vu le panneau ; ses choix restent ce qu'ils sont.
    root.querySelectorAll('[data-consent-done]').forEach(function (button) {
      button.addEventListener('click', function () {
        send(mount.url, { acknowledge: true }).then(function () {
          const next = button.dataset.next;
          if (next) { window.location.assign(next); } else { window.location.assign(window.location.pathname); }
        });
      });
    });
    return mount;
  }

  document.addEventListener('DOMContentLoaded', function () {
    const mounted = Array.from(document.querySelectorAll('[data-directory-consent]'))
      .map(mountOn).filter(Boolean);
    if (mounted.length) { load(mounted[0]); }
    const welcome = document.getElementById('directoryWelcomeModal');
    if (welcome && window.bootstrap) { window.bootstrap.Modal.getOrCreateInstance(welcome).show(); }
  });

  window.WamaDirectoryConsent = { kept: kept };
})();
