/**
 * Anonymizer — modale « Paramètres du média », SCHÉMA-DRIVEN (port 2026-08-03).
 *
 * La modale est GÉNÉRÉE par la brique commune WamaParams.renderSettingsModal depuis
 * window.WAMA_ANONYMIZER_SCHEMA (params.py = source unique typage/bornes) ; le pied vient
 * du gabarit serveur #mediaSettingsFooterTpl (_settings_modal_footer.html, délégation par
 * classes .save-settings-btn / .save-and-restart-btn).
 *
 * Exceptions app-spécifiques (déclarées en tête de params.py, PAS des champs du schéma) :
 *   • classes2blur : grille de cases à cocher (multi-sélection d'objets YOLO) ;
 *   • model_to_use : options peuplées du catalogue (get_media_settings.model_choices).
 *
 * Remplace l'ancien settings_modal.js hand-built (listes sliders/booleans en dur qui
 * recopiaient le schéma).
 */
(function () {
  'use strict';

  const cfg = window.WAMA_ANON || {};
  const getUrl = (tpl, id) => (tpl || '').replace('/0/', '/' + id + '/');

  function esc(s) {
    const d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  // ── Pied commun : clone du gabarit serveur (remplace le footer par défaut) ──
  function graftCommonFooter(modal) {
    const tpl = document.getElementById('mediaSettingsFooterTpl');
    if (!tpl || !tpl.content.firstElementChild) return;
    const foot = tpl.content.firstElementChild.cloneNode(true);
    const oldFoot = modal.querySelector('.modal-footer');
    if (oldFoot) oldFoot.replaceWith(foot);
  }

  // ── Section bespoke classes2blur (exception hors schéma) ──
  function appendClassesSection(host, classes) {
    if (!classes || !classes.length) return;
    const sec = document.createElement('div');
    sec.className = 'mt-3 anon-classes2blur';
    sec.innerHTML =
      '<label class="form-label small fw-bold text-light">' +
      '<i class="fas fa-list-check"></i> Objets à flouter (YOLO)</label>' +
      '<div class="row">' +
      classes.map(c =>
        '<div class="col-md-4 col-sm-6"><div class="form-check">' +
        '<input class="form-check-input" type="checkbox" name="classes2blur" value="' + esc(c.value) + '"' +
        (c.checked ? ' checked' : '') + ' id="msClasses_' + esc(c.value) + '">' +
        '<label class="form-check-label text-light small" for="msClasses_' + esc(c.value) + '">' +
        esc(c.label) + '</label></div></div>'
      ).join('') +
      '</div>';
    host.appendChild(sec);
  }

  // ── Options du select modèle (catalogue serveur, groupées) ──
  function fillModelChoices(host, choices, current) {
    const sel = host.querySelector('select[name="model_to_use"]');
    if (!sel || !choices) return;
    sel.innerHTML = '<option value="">Auto (basé sur précision)</option>';
    const groups = {};
    choices.forEach(c => {
      (groups[c.group] = groups[c.group] || []).push(c);
    });
    Object.keys(groups).forEach(g => {
      const og = document.createElement('optgroup');
      og.label = g;
      groups[g].forEach(c => {
        const o = document.createElement('option');
        o.value = c.value;
        o.textContent = c.label;
        og.appendChild(o);
      });
      sel.appendChild(og);
    });
    sel.value = current || '';
  }

  async function openSettingsModal(id) {
    let data;
    try {
      const resp = await fetch(getUrl(cfg.settingsGetUrlTemplate, id));
      data = await resp.json();
    } catch (e) {
      if (window.WamaApp) WamaApp.toast('Impossible de charger les paramètres', 'error');
      return;
    }
    if (!data || !data.success) {
      if (window.WamaApp) WamaApp.toast((data && data.error) || 'Paramètres indisponibles', 'error');
      return;
    }

    const { modal, host } = WamaParams.renderSettingsModal({
      id: id,
      title: 'Paramètres du média #' + id,
      titleIcon: 'fa-user-secret',
      schema: window.WAMA_ANONYMIZER_SCHEMA || [],
      values: data.values || {},
      formClass: 'anon-settings-form',
    });
    modal.dataset.mediaId = id;
    graftCommonFooter(modal);
    fillModelChoices(host, data.model_choices, (data.values || {}).model_to_use);
    appendClassesSection(host, data.classes2blur);

    // Enrichissement ✨ du prompt SAM3 dans la modale (pipeline commune)
    const promptEl = host.querySelector('textarea[name="sam3_prompt"]');
    if (promptEl && window.WamaPromptEnrich) {
      promptEl.id = promptEl.id || 'msSam3Prompt' + id;
      WamaPromptEnrich.attach('#' + promptEl.id, {
        app: 'anonymizer',
        domain: 'detection',
        csrf: cfg.csrfToken,
        original: (data.values || {}).sam3_prompt || '',
      });
    }

    new bootstrap.Modal(modal).show();
  }

  async function saveSettings(modal, restart) {
    const id = modal.dataset.mediaId;
    const host = modal.querySelector('.wama-modal-fields');
    const vals = WamaParams.read(host);

    const fd = new FormData();
    fd.append('media_id', id);
    Object.keys(vals).forEach(k => fd.append(k, vals[k]));
    modal.querySelectorAll('input[name="classes2blur"]:checked')
         .forEach(cb => fd.append('classes2blur', cb.value));
    fd.append('restart', restart ? '1' : '0');
    fd.append('csrfmiddlewaretoken', cfg.csrfToken);

    let data;
    try {
      const resp = await fetch(cfg.settingsSaveUrl, { method: 'POST', body: fd });
      data = await resp.json();
    } catch (e) {
      if (window.WamaApp) WamaApp.toast("Erreur réseau à l'enregistrement", 'error');
      return;
    }
    if (!data.success) {
      if (window.WamaApp) WamaApp.toast(data.error || 'Enregistrement impossible', 'error');
      return;
    }

    const inst = bootstrap.Modal.getInstance(modal);
    if (inst) inst.hide();
    if (window.WamaApp) WamaApp.toast(restart && data.restarted ? 'Enregistré — relance…' : 'Paramètres enregistrés', 'success');
    if (window.WamaEta && data.restarted) WamaEta.reset(id);
    if (window.AnonQueue) {
      await AnonQueue.refreshCard(id);
      if (data.restarted) AnonQueue.startPolling(parseInt(id, 10));
    }
  }

  // Délégation : ouverture (⚙ des cards) + boutons du pied commun (modale générée)
  document.addEventListener('click', function (e) {
    const openBtn = e.target.closest('.settings-btn[data-id]');
    if (openBtn && openBtn.closest('.anon-card')) {
      openSettingsModal(openBtn.dataset.id);
      return;
    }
    const saveBtn = e.target.closest('.save-settings-btn, .save-and-restart-btn');
    if (saveBtn) {
      const modal = saveBtn.closest('.modal[data-media-id]');
      if (modal) saveSettings(modal, saveBtn.classList.contains('save-and-restart-btn'));
    }
  });

  window.AnonSettingsModal = { open: openSettingsModal };
})();
