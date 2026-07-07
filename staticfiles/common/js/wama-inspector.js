/**
 * WAMA — WamaInspector : le PANNEAU inspecteur commun (volet droit) : card / batch / file.
 * Famille : WamaInspector (CE FICHIER, panneau) · WamaParams (réglages ÉDITABLES) · WamaDetails (affichage READ-ONLY).
 *
 * Le volet droit devient un inspecteur :
 *   - clic sur une card  → réglages + actions de la card,
 *   - clic sur l'en-tête d'un batch → réglages communs (appliqués à tous les items) + actions batch,
 *   - rien de sélectionné → niveau file (valeurs par défaut).
 * Pendant l'inspection, le volet n'affiche QUE les infos de l'élément (sections globales masquées).
 *
 * Module GÉNÉRIQUE : toute la logique app-spécifique est fournie via `config` (callbacks).
 * Aucune dépendance app ici — réutilisable par toutes les apps WAMA (transcriber = référence).
 *
 * Usage :
 *   const insp = WamaInspector.init({
 *     queueContainer,                       // élément de la file
 *     ids: { banner, label, deselect, actions, hint },   // ids du volet (défauts ci-dessous)
 *     hideOnInspect: ['resetOptions'],      // ids masqués pendant l'inspection
 *     settingsTitleSelector, settingsTitleInspect,        // titre de section contextualisé
 *     panel: { read(), apply(values) },     // lecture/écriture du formulaire du volet
 *     cardSettings(card) -> values,         // extrait les réglages d'une card (data-*)
 *     renderItemActions(host, card),        // remplit le conteneur d'actions pour une card
 *     renderBatchActions(host, batchId),    // ... pour un batch
 *     saveItem(id), saveBatch(batchId), saveGlobal(),    // routage de la sauvegarde
 *     itemLabel(id), batchLabel(id),        // libellés de la bannière
 *     cardSelector, batchSelector, batchIdAttr, highlightClass,  // sélecteurs (défauts)
 *   });
 *   insp.save();  insp.deselect();  insp.state(); // {itemId, batchId}
 */
(function (global) {
  'use strict';

  // Actions de l'inspecteur = CLONE des boutons de la card/batch source + PROXY du clic vers
  // le vrai bouton (déjà câblé). APPROCHE UNIQUE pour toutes les apps (CARD_DESIGN §10) : aucune
  // hypothèse sur les fonctions/IDs de l'app. Les dropdowns (data-bs-toggle) et liens <a href>
  // fonctionnent nativement sur le clone. sourceEl = conteneur d'actions de la card/batch source.
  function cloneActions(host, sourceEl, label) {
    if (!host) return;
    if (!sourceEl) { host.innerHTML = ''; return; }
    host.innerHTML =
      '<div class="small text-white-50 mb-1">' + (label || '') + '</div>' +
      '<div class="btn-group-actions flex-wrap gap-1">' + sourceEl.innerHTML + '</div>' +
      '<hr class="border-secondary my-2">';
    const real = sourceEl.querySelectorAll('button');
    const clones = host.querySelectorAll('button');
    clones.forEach(function (clone, i) {
      const r = real[i];
      if (!r) return;
      if (clone.getAttribute('data-bs-toggle') === 'dropdown') return;  // Bootstrap gère le clone
      // stopPropagation : le clone peut porter une classe déléguée au document (.batch-*-btn) →
      // sans ça, clic = délégation directe du clone + proxy = DOUBLE déclenchement. On coupe la
      // remontée du clone ; seul r.click() (le vrai bouton) déclenche l'action, une seule fois.
      clone.addEventListener('click', function (e) { e.preventDefault(); e.stopPropagation(); r.click(); });
    });
  }

  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // Rendu INLINE compact d'un aperçu média dans le volet (≠ modale plein écran de media-preview.js).
  // Données = JSON de common:unified_preview {name, url, mime_type, …}. autoplay gated par le profil
  // (jamais de génération : on n'affiche que l'existant — CARD_DESIGN §10.6 / décision Fabien).
  function renderInlinePreview(host, data, autoplay) {
    if (!host) return;
    const mime = (data.mime_type || '').toLowerCase();
    const url = data.url || '';
    const name = escapeHtml(data.name || '');
    let media = '';
    if (mime.indexOf('image/') === 0) {
      media = '<img src="' + url + '" alt="" class="wama-inspector-preview-media" style="max-width:100%;max-height:220px;border-radius:6px;">';
    } else if (mime.indexOf('video/') === 0) {
      media = '<video src="' + url + '" controls ' + (autoplay ? 'autoplay muted ' : '') +
        'class="wama-inspector-preview-media" style="max-width:100%;max-height:220px;border-radius:6px;"></video>';
    } else if (mime.indexOf('audio/') === 0) {
      if (global.WamaAudioPlayer && WamaAudioPlayer.create) {
        host.innerHTML = '';
        try { host.appendChild(WamaAudioPlayer.create(url, 'insp', { autoplay: !!autoplay })); }
        catch (e) { host.innerHTML = '<audio src="' + url + '" controls ' + (autoplay ? 'autoplay ' : '') + 'style="width:100%;"></audio>'; }
        _previewCaption(host, name);
        return;
      }
      media = '<audio src="' + url + '" controls ' + (autoplay ? 'autoplay ' : '') + 'style="width:100%;"></audio>';
    } else if (mime === 'application/pdf') {
      media = '<embed src="' + url + '" type="application/pdf" style="width:100%;height:220px;border-radius:6px;">';
    } else {
      media = '<a href="' + url + '" target="_blank" rel="noopener" class="btn btn-sm btn-outline-info">' +
        '<i class="fas fa-external-link-alt"></i> Ouvrir</a>';
    }
    host.innerHTML = '<div class="wama-inspector-preview text-center">' + media + '</div>';
    _previewCaption(host, name, data);
  }

  // Légende : nom + métadonnées DÉJÀ présentes dans la réponse unified_preview
  // (durée/résolution/propriétés) — 1re brique d'infos dans l'inspecteur, sans nouvel endpoint.
  function _previewMeta(data) {
    const bits = [];
    if (data.duration) {
      const d = Math.round(data.duration), m = Math.floor(d / 60), s = d % 60;
      bits.push(m ? (m + ' min ' + (s < 10 ? '0' : '') + s + ' s') : (s + ' s'));
    }
    if (data.resolution) bits.push(String(data.resolution));
    if (data.properties) bits.push(String(data.properties));
    return bits;
  }

  function _previewCaption(host, name, data) {
    if (name) {
      const cap = document.createElement('small');
      cap.className = 'text-white-50 d-block text-truncate mt-1';
      cap.title = name; cap.textContent = name;
      host.appendChild(cap);
    }
    (data ? _previewMeta(data) : []).forEach(function (t) {
      const el = document.createElement('small');
      el.className = 'text-muted d-block text-truncate';
      el.style.fontSize = '.7rem';
      el.title = t; el.textContent = t;
      host.appendChild(el);
    });
  }

  // Rendu COMPACT des infos d'item = chips (cohérent avec les cards ; INSPECTOR_DETAIL_FIELDS.md).
  var DETAIL_META = {
    created_at: { label: 'Créé le', icon: 'fa-calendar-alt' },
    source_duration_display: { label: 'Durée', icon: 'fa-clock' },
    engine: { label: 'Moteur / Modèle', icon: 'fa-microchip' },
    engine_effective: { label: 'Moteur effectif', icon: 'fa-shield-alt' },
    output_format: { label: 'Format', icon: 'fa-file-export' },
    output_quality: { label: 'Qualité', icon: 'fa-sliders' },
    processing_time_display: { label: 'Temps de traitement', icon: 'fa-stopwatch' },
  };
  var DETAIL_ORDER = ['created_at', 'source_duration_display', 'engine', 'engine_effective', 'output_format', 'output_quality', 'processing_time_display'];
  function _detailChip(icon, value, label) {
    return '<span class="wama-chip" title="' + escapeHtml(label || '') + '"><i class="fas ' + icon + '"></i> ' + escapeHtml(value) + '</span>';
  }
  function renderDetailChips(d) {
    var st = (d.status || '').toUpperCase();
    var stCls = st === 'SUCCESS' ? 'success' : st === 'FAILURE' ? 'danger' : st === 'RUNNING' ? 'warning text-dark' : 'secondary';
    var stLbl = (global.WamaApp && WamaApp.STATUS_LABEL && WamaApp.STATUS_LABEL[st]) || st;
    var head = '<div class="d-flex align-items-center gap-2 flex-wrap mb-1">';
    if (d.id != null) head += '<strong class="text-light">#' + escapeHtml(d.id) + '</strong>';
    if (st) head += '<span class="badge bg-' + stCls + '">' + escapeHtml(stLbl) + '</span>';
    if (d.created_at) head += '<small class="text-white-50"><i class="fas fa-calendar-alt"></i> ' + escapeHtml(d.created_at) + '</small>';
    head += '</div>';
    var srcLine = '';
    if (d.source_file) {
      var fn = String(d.source_file).split('/').pop();
      srcLine = '<div class="small text-truncate mb-1" title="' + escapeHtml(d.source_file) + '"><i class="fas fa-file text-info"></i> ' + escapeHtml(fn) + '</div>';
    }
    var chips = [];
    DETAIL_ORDER.forEach(function (k) { if (d[k]) { var m = DETAIL_META[k]; chips.push(_detailChip(m.icon, d[k], m.label)); } });
    if (d.source_properties) chips.push(_detailChip(d.source_properties_icon || 'fa-circle-info', d.source_properties, 'Propriétés'));
    if (d.extra) Object.keys(d.extra).forEach(function (lbl) { chips.push(_detailChip('fa-sliders', d.extra[lbl], lbl)); });
    if (d.result_file) { var rf = String(d.result_file).split('/').pop(); chips.push('<a class="wama-chip" href="' + d.result_file + '" title="Résultat"><i class="fas fa-download"></i> ' + escapeHtml(rf) + '</a>'); }
    var chipsHtml = chips.length ? '<div class="d-flex flex-wrap gap-1">' + chips.join('') + '</div>' : '';
    var errHtml = d.error_message ? '<div class="small text-danger mt-1"><i class="fas fa-triangle-exclamation"></i> ' + escapeHtml(d.error_message) + '</div>' : '';
    return head + srcLine + chipsHtml + errHtml;
  }

  function init(cfg) {
    cfg = cfg || {};
    const qc = cfg.queueContainer;
    if (!qc) return null;

    const CARD_SEL   = cfg.cardSelector   || '.synthesis-card';
    const BATCH_SEL  = cfg.batchSelector  || '.batch-group';
    const BATCH_ATTR = cfg.batchIdAttr    || 'batchId';     // dataset key (data-batch-id)
    const HL         = cfg.highlightClass || 'inspector-selected';
    const ids = Object.assign({
      banner: 'inspectorBanner', label: 'inspectorLabel', deselect: 'inspectorDeselect',
      actions: 'inspectorActions', hint: 'inspectorActionsHint',
    }, cfg.ids || {});
    const hideOnInspect = cfg.hideOnInspect || [];
    const itemLabel  = cfg.itemLabel  || function (id) { return "l'élément #" + id; };
    const batchLabel = cfg.batchLabel || function (id) { return 'le batch #' + id; };
    const panel = cfg.panel || {};

    let itemId = null, batchId = null, defaults = null;
    const $ = function (id) { return document.getElementById(id); };

    function clearHighlight() {
      qc.querySelectorAll('.' + HL).forEach(function (c) { c.classList.remove(HL); });
    }

    function toggleSections(inspecting) {
      hideOnInspect.forEach(function (id) {
        const el = $(id);
        if (el) el.style.display = inspecting ? 'none' : '';
      });
      const hint = $(ids.hint);
      if (hint) hint.style.display = inspecting ? 'none' : '';
      if (cfg.settingsTitleSelector) {
        const t = document.querySelector(cfg.settingsTitleSelector);
        if (t) {
          if (!t.dataset.orig) t.dataset.orig = t.innerHTML;
          t.innerHTML = inspecting ? (cfg.settingsTitleInspect || t.dataset.orig) : t.dataset.orig;
        }
      }
    }

    function showBanner(text) {
      const b = $(ids.banner), l = $(ids.label);
      if (l) l.textContent = text;
      if (b) { b.classList.remove('d-none'); b.classList.add('d-flex'); }
    }
    function hideBanner() {
      const b = $(ids.banner);
      if (b) { b.classList.add('d-none'); b.classList.remove('d-flex'); }
    }

    function snapshotDefaults() {
      // Mémorise les valeurs par défaut UNE fois (à la 1re sélection), pour les restaurer ensuite.
      if (itemId === null && batchId === null && panel.read) defaults = panel.read();
    }

    function fillActions(renderFn, arg) {
      const host = $(ids.actions);
      if (!host) return;
      host.innerHTML = '';
      if (renderFn) renderFn(host, arg);
    }

    // --- Aperçu inline dans le volet (section media/#preview-container) ---
    var previewHost = cfg.previewHost ? $(cfg.previewHost) : document.getElementById('preview-container');
    var previewTitleEl = cfg.previewTitleSel ? $(cfg.previewTitleSel) : document.getElementById('rightPanelMediaTitle');
    var previewPlaceholder = previewHost ? previewHost.innerHTML : '';
    var previewTitleDefault = previewTitleEl ? previewTitleEl.textContent : '';
    var infoHost = document.getElementById('inspectorInfo');
    var infoSection = document.getElementById('info-section');
    function hideDetail() {
      if (infoHost) infoHost.innerHTML = '';
      if (infoSection) infoSection.style.display = 'none';
    }
    function fillDetail(card) {
      if (!infoHost || !card) { hideDetail(); return; }
      var link = (card.matches && card.matches('[data-preview-url]')) ? card : card.querySelector('[data-preview-url]');
      var purl = link && link.getAttribute('data-preview-url');
      if (!purl) { hideDetail(); return; }
      var durl = purl.replace('/preview/', '/detail/');
      fetch(durl).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d || d.error) { hideDetail(); return; }
        infoHost.innerHTML = renderDetailChips(d);
        if (infoSection) infoSection.style.display = '';
      }).catch(hideDetail);
    }
    function restorePreview() {
      if (previewHost) previewHost.innerHTML = previewPlaceholder;
      if (previewTitleEl) previewTitleEl.textContent = previewTitleDefault;
    }
    function fillPreview(card, title) {
      if (!previewHost || !card) return;
      var link = (card.matches && card.matches('[data-preview-url]')) ? card : card.querySelector('[data-preview-url]');
      var url = link && link.getAttribute('data-preview-url');
      if (!url) { restorePreview(); return; }
      fetch(url).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
        if (!d || !d.url) { restorePreview(); return; }
        var autoplay = (cfg.autoplay != null) ? cfg.autoplay : global.WAMA_INSPECTOR_AUTOPLAY;
        renderInlinePreview(previewHost, d, !!autoplay);
        if (previewTitleEl && title) previewTitleEl.textContent = title;
      }).catch(restorePreview);
    }

    function selectItem(id) {
      const card = qc.querySelector(CARD_SEL + '[data-id="' + id + '"]');
      if (!card) return;
      snapshotDefaults();
      itemId = id; batchId = null;
      clearHighlight(); card.classList.add(HL);
      if (panel.apply && cfg.cardSettings) panel.apply(cfg.cardSettings(card));
      fillActions(cfg.renderItemActions, card);
      fillPreview(card, 'Aperçu');
      fillDetail(card);
      toggleSections(true);
      showBanner(itemLabel(id));
    }

    function selectBatch(bid) {
      const group = qc.querySelector(BATCH_SEL + '[data-batch-id="' + bid + '"]');
      if (!group) return;
      snapshotDefaults();
      batchId = bid; itemId = null;
      clearHighlight(); group.classList.add(HL);
      const first = group.querySelector(CARD_SEL);   // réglages = ceux du 1er item
      if (first && panel.apply && cfg.cardSettings) panel.apply(cfg.cardSettings(first));
      fillActions(cfg.renderBatchActions, bid);
      fillPreview(first, 'Aperçu');
      fillDetail(first);
      toggleSections(true);
      showBanner(batchLabel(bid));
    }

    function deselect() {
      itemId = null; batchId = null;
      clearHighlight();
      if (defaults && panel.apply) panel.apply(defaults);
      const host = $(ids.actions);
      if (host) host.innerHTML = '';
      toggleSections(false);
      hideBanner();
      restorePreview();
      hideDetail();
    }

    function save() {
      if (batchId) { if (cfg.saveBatch) cfg.saveBatch(batchId); return; }
      if (itemId)  { if (cfg.saveItem)  cfg.saveItem(itemId);  return; }
      if (cfg.saveGlobal) cfg.saveGlobal();
    }

    // Délégation : clic card → inspecteur item ; clic en-tête batch → inspecteur batch.
    // (on ignore boutons/liens/champs et les zones d'actions pour ne pas voler leurs clics.)
    qc.addEventListener('click', function (e) {
      if (e.target.closest('button, a, input, select, textarea, .wama-card-preview, .btn-group-actions')) return;
      const card = e.target.closest(CARD_SEL);
      if (card && card.dataset.id) { selectItem(card.dataset.id); return; }
      const batch = e.target.closest(BATCH_SEL);
      if (batch && batch.dataset[BATCH_ATTR]) selectBatch(batch.dataset[BATCH_ATTR]);
    });
    const db = $(ids.deselect);
    if (db) db.addEventListener('click', deselect);

    // ── Navigation clavier (générique) ──────────────────────────────────────
    // ↑/↓ : déplace la sélection entre cards — UNIQUEMENT si une card est déjà sélectionnée
    // (on n'usurpe pas le scroll de page tant que l'utilisateur n'est pas « entré » dans la file).
    // Entrée/Espace : active la card (événement `wama:card-activate`). Échap : déselectionne.
    function cardList() { return Array.prototype.slice.call(qc.querySelectorAll(CARD_SEL)); }
    function moveSelection(dir) {
      const list = cardList();
      if (!list.length) return;
      let idx = list.findIndex(function (c) { return c.dataset.id === String(itemId); });
      let next = idx < 0 ? 0 : Math.min(list.length - 1, Math.max(0, idx + dir));
      const card = list[next];
      if (card && card.dataset.id) {
        selectItem(card.dataset.id);
        card.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      }
    }
    if (cfg.keyboardNav !== false) {
      document.addEventListener('keydown', function (e) {
        if (e.target.closest('input, textarea, select, [contenteditable="true"]')) return;
        if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && itemId !== null) {
          e.preventDefault();
          moveSelection(e.key === 'ArrowDown' ? 1 : -1);
        } else if (e.key === 'Escape' && (itemId !== null || batchId !== null)) {
          e.preventDefault();
          deselect();
        } else if ((e.key === 'Enter' || e.key === ' ') && itemId !== null) {
          const card = qc.querySelector(CARD_SEL + '[data-id="' + itemId + '"]');
          if (card) {
            e.preventDefault();
            card.dispatchEvent(new CustomEvent('wama:card-activate', { bubbles: true, detail: { id: itemId } }));
          }
        }
      });
    }

    return {
      selectItem: selectItem,
      selectBatch: selectBatch,
      deselect: deselect,
      save: save,
      state: function () { return { itemId: itemId, batchId: batchId }; },
    };
  }

  // ── Câblage CONTEXTUEL générique depuis un schéma WamaParams ──────────────────
  // Évite à chaque app de réécrire panel.read/apply + cardSettings : on les DÉRIVE du schéma.
  //   - panel.read/apply  → WamaParams.read/apply sur le conteneur du volet (data-param ↔ name)
  //   - cardSettings(card) → { paramName: card.dataset[...] } pour chaque param du schéma
  // L'app ne fournit plus que : queueContainer, panelContainer, schema, libellés, saveItem/saveBatch.
  function initFromSchema(cfg) {
    cfg = cfg || {};
    const schema = cfg.schema || [];
    const ph = cfg.panelContainer;                       // conteneur du volet (rendu WamaParams panel)
    const WP = global.WamaParams;
    const names = schema.map(function (p) { return p.name; });

    // dom_id du contexte panel pour un param (objet {panel:…} ou string), repli sur le nom.
    function panelKey(p) {
      const d = p.dom_id;
      return (d && typeof d === 'object') ? (d.panel || p.name) : (d || p.name);
    }
    // Élément d'un champ par dom_id : #id, sinon [name=]/[data-param=] dans le volet.
    function fieldEl(key) {
      return document.getElementById(key) ||
        (ph && ph.querySelector('[name="' + key + '"],[data-param="' + key + '"]'));
    }
    // Panel read/apply ROBUSTE (id OU name OU radios OU checkbox) — marche que les champs soient
    // rendus par WamaParams (id=dom_id) ou des champs maison (compose). Surchargable via cfg.panel.
    const panel = cfg.panel || {
      read: function () {
        const out = {};
        schema.forEach(function (p) {
          if (p.contexts && p.contexts.indexOf('panel') === -1) return;
          const key = panelKey(p);
          const radios = (ph || document).querySelectorAll('input[type="radio"][name="' + key + '"]');
          if (radios.length) { radios.forEach(function (r) { if (r.checked) out[p.name] = r.value; }); return; }
          const el = fieldEl(key);
          if (el) out[p.name] = (el.type === 'checkbox') ? el.checked : el.value;
        });
        return out;
      },
      apply: function (vals) {
        vals = vals || {};
        schema.forEach(function (p) {
          if (!(p.name in vals)) return;
          const key = panelKey(p);
          const radios = (ph || document).querySelectorAll('input[type="radio"][name="' + key + '"]');
          if (radios.length) {
            radios.forEach(function (r) {
              r.checked = (String(r.value) === String(vals[p.name]));
              if (r.checked) r.dispatchEvent(new Event('change', { bubbles: true }));
            });
            return;
          }
          const el = fieldEl(key);
          if (!el) return;
          const val = vals[p.name];
          if (el.type === 'checkbox') {
            // val vient d'un data-* (string) → "false"/"0" doivent décocher (!!"false" valait true).
            el.checked = (val === true || val === 'true' || val === 1 || val === '1');
          } else {
            el.value = val;
          }
          // 'input' (sliders/affichages de valeur qui écoutent input) ET 'change' (WamaModelCaps, etc.).
          el.dispatchEvent(new Event('input', { bubbles: true }));
          el.dispatchEvent(new Event('change', { bubbles: true }));
          // Select à options ASYNC (ex. voix filtrées par WamaModelCaps après le change du modèle) :
          // si la valeur n'a pas pris (option pas encore présente), re-essai au tick suivant.
          if (el.tagName === 'SELECT' && val != null && String(el.value) !== String(val)) {
            setTimeout(function () {
              el.value = val;
              if (String(el.value) === String(val)) el.dispatchEvent(new Event('change', { bubbles: true }));
            }, 200);
          }
        });
      },
    };

    const cardSettings = cfg.cardSettings || function (card) {
      const out = {};
      // Les data-* de params peuvent être sur la RACINE de card OU sur le bouton ⚙ (cas le plus courant :
      // Describer/Synthesizer/… rendent les data-output-format/… sur le bouton settings).
      const btn = card.querySelector('.settings-btn, [data-action="settings"], .btn-settings-job, .job-settings-btn');
      const datasets = btn ? [card.dataset, btn.dataset] : [card.dataset];
      names.forEach(function (n) {
        const camel = n.replace(/_([a-z])/g, function (_, c) { return c.toUpperCase(); });
        let v;
        datasets.forEach(function (ds) {
          if (v !== undefined) return;
          if (ds[n] !== undefined) v = ds[n];
          else if (ds[camel] !== undefined) v = ds[camel];
        });
        if (v !== undefined) out[n] = v;
      });
      return out;
    };

    return init(Object.assign({}, cfg, { panel: panel, cardSettings: cardSettings }));
  }

  global.WamaInspector = { init: init, initFromSchema: initFromSchema, cloneActions: cloneActions };
})(window);
