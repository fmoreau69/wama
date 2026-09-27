/**
 * Anonymizer — modale « Paramètres du média », SCHÉMA-DRIVEN (port 2026-08-03).
 *
 * La modale est GÉNÉRÉE par la brique commune WamaParams.renderSettingsModal depuis
 * window.WAMA_ANONYMIZER_SCHEMA (params.py = source unique typage/bornes) ; le pied vient
 * du gabarit serveur #mediaSettingsFooterTpl (_settings_modal_footer.html, délégation par
 * classes .save-settings-btn / .save-and-restart-btn).
 *
 * Exceptions app-spécifiques (déclarées en tête de params.py, PAS des champs du schéma) :
 *   • classes2blur : grille de cases à cocher (multi-sélection d'objets YOLO).
 * Le menu de modèle, lui, est un réglage du schéma comme un autre depuis le 2026-09-27 :
 * WamaParams le remplit depuis le catalogue, borné par le mode de l'élément (`options_mode`).
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


  // ── Section bespoke classes2blur (exception hors schéma) — insérée DANS le groupe
  // « Quoi flouter (classes) » : masquée avec lui en mode Description. ──
  function appendClassesSection(host, classes) {
    if (!classes || !classes.length) return;
    const yolo = host.querySelector('[data-group="classes"] .wama-param-group-body');
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
    // Visibilité : la condition du GROUPE déclaré (params.py, groupe `classes`), appliquée par
    // la visibilité conditionnelle commune de WamaParams — jamais réécrite ici. Le groupe n'est
    // pas rendu quand aucun réglage du schéma n'y vit ; la grille porte alors sa condition.
    const group = (window.WAMA_ANONYMIZER_GROUPS || []).find(g => g.key === 'classes');
    if (group && group.show_if) sec.setAttribute('data-show-if', JSON.stringify(group.show_if));
    (yolo || host).appendChild(sec);
    host.dispatchEvent(new Event('change', { bubbles: true }));   // applique la condition
  }

  // ── Badge d'état SAM3 dans le titre du groupe « Mode de détection » (référence
  // Uniformisation) — même endpoint et mêmes états que right_panel.js. ──
  function appendSam3Badge(host) {
    const title = host.querySelector('[data-group="mode"] .wama-param-group-title');
    if (!title) return;
    const badge = document.createElement('span');
    badge.className = 'badge bg-secondary float-end';
    badge.innerHTML = '<i class="fas fa-circle-notch fa-spin"></i>';
    title.appendChild(badge);
    fetch('/anonymizer/sam3/status/')
      .then(r => r.json())
      .then(d => {
        if (d.ready) {
          badge.className = 'badge bg-success float-end';
          badge.innerHTML = '<i class="fas fa-check-circle"></i> SAM3 disponible';
        } else if (d.installed && !d.hf_authenticated) {
          badge.className = 'badge bg-warning text-dark float-end';
          badge.innerHTML = '<i class="fas fa-exclamation-triangle"></i> Config HF requise';
        } else if (!d.installed) {
          badge.className = 'badge bg-danger float-end';
          badge.innerHTML = '<i class="fas fa-times-circle"></i> SAM3 non installé';
        } else {
          badge.className = 'badge bg-secondary float-end';
          badge.innerHTML = '<i class="fas fa-info-circle"></i> ' + (d.error || 'État inconnu');
        }
      })
      .catch(() => badge.remove());
  }

  // Ouverture : ORCHESTRATION COMMUNE (WamaParams.settingsModal). Ce fichier ne declare
  // plus que les specificites anonymizer via les hooks decorate/collect/onSaved/errorOf.
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

    return WamaParams.settingsModal({
      id: id,
      title: 'Paramètres du média #' + id,
      titleIcon: 'fa-user-secret',
      schema: window.WAMA_ANONYMIZER_SCHEMA || [],
      groups: window.WAMA_ANONYMIZER_GROUPS || [],   // sections calquées sur le volet droit
      values: data.values || {},
      formClass: 'anon-settings-form',
      footerTplId: 'mediaSettingsFooterTpl',
      saveUrl: cfg.settingsSaveUrl,
      csrf: cfg.csrfToken,
      idField: 'media_id',
      decorate: function (host) {
        appendClassesSection(host, data.classes2blur);
        appendSam3Badge(host);
        // Enrichissement ✨ du prompt SAM3 dans la modale (pipeline commune)
        const promptEl = host.querySelector('textarea[name="sam3_prompt"]');
        if (promptEl && window.WamaPromptEnrich) {
          promptEl.id = promptEl.id || 'msSam3Prompt' + id;
          WamaPromptEnrich.attach('#' + promptEl.id, {
            app: 'anonymizer', domain: 'detection', csrf: cfg.csrfToken,
            original: (data.values || {}).sam3_prompt || '',
          });
        }
      },
      collect: function (fd, host, d, restart) {
        // classes2blur : multi-sélection bespoke (hors schéma) + drapeau de relance
        host.querySelectorAll('input[name="classes2blur"]:checked')
            .forEach(function (cb) { fd.append('classes2blur', cb.value); });
        fd.append('restart', restart ? '1' : '0');
      },
      errorOf: function (resp) {
        return resp && resp.success ? null : ((resp && resp.error) || 'Enregistrement impossible');
      },
      onSaved: function (mid, restart, resp) {
        if (window.WamaEta && resp.restarted) WamaEta.reset(mid);
        if (window.AnonQueue) {
          Promise.resolve(AnonQueue.refreshCard(mid)).then(function () {
            if (resp.restarted) AnonQueue.startPolling(parseInt(mid, 10));
          });
        }
      },
    });
  }


  // Ouverture (⚙ des cards) : ouvreur DÉCLARÉ à la brique commune (queue-actions.js), qui tient
  // le sélecteur et la délégation. `within` conserve à l'identique le périmètre de l'ancien
  // handler local (`openBtn.closest('.anon-card')`) — une garde d'app se DÉCLARE, elle ne se
  // recode pas. Le pied de modale, lui, était déjà câblé par WamaParams sur la modale elle-même.
  WamaQueueActions.onSettings(function (id) {
    openSettingsModal(id);
  }, { within: '.anon-card' });

  window.AnonSettingsModal = { open: openSettingsModal };
})();
