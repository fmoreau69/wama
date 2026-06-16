/**
 * WAMA — Inspecteur de file commun (volet droit) : card / batch / file.
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

    function selectItem(id) {
      const card = qc.querySelector(CARD_SEL + '[data-id="' + id + '"]');
      if (!card) return;
      snapshotDefaults();
      itemId = id; batchId = null;
      clearHighlight(); card.classList.add(HL);
      if (panel.apply && cfg.cardSettings) panel.apply(cfg.cardSettings(card));
      fillActions(cfg.renderItemActions, card);
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

    return {
      selectItem: selectItem,
      selectBatch: selectBatch,
      deselect: deselect,
      save: save,
      state: function () { return { itemId: itemId, batchId: batchId }; },
    };
  }

  global.WamaInspector = { init: init };
})(window);
