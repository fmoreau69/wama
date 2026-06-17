/*
 * wama-model-caps.js — Filtrage dynamique des <select> dépendants selon les CAPACITÉS
 * du modèle sélectionné (source unique : AIModel.capabilities via api/models/db/).
 *
 * Cas d'usage : masquer les voix de clonage (« Mes voix » ua_/cv_) si le modèle TTS ne clone
 * pas (supports_cloning=false) ; restreindre les langues à celles supportées par le modèle ; etc.
 * Générique : l'app fournit le mapping valeur→clé catalogue + les règles de filtrage.
 *
 * Usage :
 *   WamaModelCaps.init({
 *     source: 'synthesizer',
 *     modelSelectId: 'tts_model',
 *     resolveKey: (v) => 'synthesizer:' + ({xtts_v2:'coqui-xtts', higgs_audio:'higgs-audio'}[v] || v),
 *     filters: [
 *       // masque les options de clonage si le modèle ne clone pas
 *       { selectId: 'voice_preset',
 *         hideOption: (caps, opt) => caps.supports_cloning === false && /^(ua_|cv_)/.test(opt.value) },
 *       // ne garde que les langues supportées
 *       { selectId: 'language',
 *         hideOption: (caps, opt) => Array.isArray(caps.languages) && caps.languages.length
 *                                    && caps.languages.indexOf(opt.value) === -1 },
 *     ],
 *   });
 *
 * capabilities proviennent de api/models/db/?source=<source> (champ `capabilities`).
 */
(function (global) {
  'use strict';

  function init(cfg) {
    cfg = cfg || {};
    const sel = document.getElementById(cfg.modelSelectId);
    if (!sel) return null;
    const resolveKey = cfg.resolveKey || function (v) { return v; };
    const filters = cfg.filters || [];
    const base = cfg.url || '/model-manager/api/models/db/';
    let capsByKey = {};

    function applyFilter(f, caps) {
      const target = document.getElementById(f.selectId);
      if (!target || typeof f.hideOption !== 'function') return;
      let firstVisible = null;
      let selectedHidden = false;
      Array.prototype.forEach.call(target.options, function (opt) {
        const hide = !!caps && f.hideOption(caps, opt);
        opt.hidden = hide;
        opt.disabled = hide;
        if (!hide && firstVisible === null) firstVisible = opt;
        if (hide && opt.selected) selectedHidden = true;
      });
      // Si l'option sélectionnée vient d'être masquée → bascule sur la 1re visible.
      if (selectedHidden && firstVisible) {
        target.value = firstVisible.value;
        target.dispatchEvent(new Event('change', { bubbles: true }));
      }
    }

    function render() {
      const caps = capsByKey[resolveKey(sel.value)] || null;
      filters.forEach(function (f) { applyFilter(f, caps); });
    }

    sel.addEventListener('change', render);

    // Charge les capacités du catalogue puis applique le filtrage initial.
    const url = base + '?source=' + encodeURIComponent(cfg.source);
    fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        (data.models || []).forEach(function (m) {
          if (m.model_key) capsByKey[m.model_key] = m.capabilities || {};
        });
        render();
      })
      .catch(function () { /* pas de catalogue → on ne filtre pas (dégradation douce) */ });

    return { render: render, caps: function () { return capsByKey; } };
  }

  global.WamaModelCaps = { init: init };
})(window);
